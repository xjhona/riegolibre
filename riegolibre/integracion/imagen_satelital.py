"""Imagen satelital de la zona del proyecto, recortada al DEM, y vista 3D del terreno.

La imagen se dibuja con el motor de mapas de QGIS a partir de un servicio de teselas (XYZ) o de
cualquier capa ráster del proyecto, por bloques, en el sistema de coordenadas del DEM, y se guarda
como GeoTIFF. Antes se busca el mayor nivel de zoom que tiene imagen real en el centro de la zona:
algunos servicios devuelven teselas de relleno («Map data not yet available») cuando no hay imagen.
"""

import json
import math
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import quote

import numpy
from osgeo import gdal
from qgis.core import (QgsBlockingNetworkRequest, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.PyQt.QtCore import QEventLoop, QSize, QUrl
from qgis.PyQt.QtGui import QColor, QImage
from qgis.PyQt.QtNetwork import QNetworkRequest

from .topografia_cad import _con_excepciones

LADO_BLOQUE = 2048  # píxeles por lado de cada bloque que se dibuja
MAX_PIXELES = 150_000_000
ZOOM_MINIMO_PRUEBA = 14


@dataclass(frozen=True)
class FuenteTeselas:
    nombre: str
    url: str  # con {x}, {y} y {z}
    zoom_max: int
    atribucion: str
    url_disponibilidad: str = ""  # Esri: dice si la tesela tiene imagen real

    def capa(self, zoom_max=None) -> QgsRasterLayer:
        # «&» y «=» de la dirección se codifican para no confundirse con los parámetros de la capa.
        uri = f"type=xyz&url={quote(self.url, safe=':/?')}&zmax={zoom_max or self.zoom_max}&zmin=0"
        return QgsRasterLayer(uri, self.nombre, "wms")


FUENTES = (
    FuenteTeselas("Google Satélite", "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", 20, "© Google"),
    FuenteTeselas("Esri World Imagery",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                  19, "© Esri, Maxar, Earthstar Geographics",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tilemap/{z}/{y}/{x}/1/1"),
)


@dataclass
class ResultadoImagen:
    ruta: str
    columnas: int
    filas: int
    resolucion_m: float
    zoom: Optional[int]  # nivel de zoom usado (None si la fuente es una capa del proyecto)
    metros_por_pixel_fuente: Optional[float]


def tesela(lon, lat, zoom):
    """Índices (x, y) de la tesela XYZ que contiene el punto."""
    n = 2 ** zoom
    lat = max(-85.0511, min(85.0511, lat))
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(x, n - 1), min(y, n - 1)


def metros_por_pixel(lat, zoom):
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** zoom


def _descargar(url):
    peticion = QgsBlockingNetworkRequest()
    error = peticion.get(QNetworkRequest(QUrl(url)))
    respuesta = peticion.reply()
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        return None, ""
    tipo = respuesta.rawHeader(b"Content-Type").data().decode("latin-1")
    return bytes(respuesta.content().data()), tipo


def tiene_imagen(fuente: FuenteTeselas, lon, lat, zoom) -> Optional[bool]:
    """True/False según el servicio tenga imagen en ese zoom; None si no hubo respuesta."""
    x, y = tesela(lon, lat, zoom)
    if fuente.url_disponibilidad:
        contenido, _ = _descargar(fuente.url_disponibilidad.format(x=x, y=y, z=zoom))
        if contenido is None:
            return None
        try:
            return json.loads(contenido.decode("utf-8")).get("data", [0])[0] == 1
        except (ValueError, IndexError, AttributeError):
            return None
    contenido, tipo = _descargar(fuente.url.format(x=x, y=y, z=zoom))
    if contenido is None:
        return False  # Google responde 404 donde no hay imagen
    return tipo.startswith("image/") and len(contenido) > 0


def zoom_disponible(fuente: FuenteTeselas, lon, lat) -> int:
    """Mayor zoom con imagen real en el punto. ValueError si el servicio no responde."""
    respondio = False
    for zoom in range(fuente.zoom_max, ZOOM_MINIMO_PRUEBA - 1, -1):
        hay = tiene_imagen(fuente, lon, lat, zoom)
        respondio = respondio or hay is not None
        if hay:
            return zoom
    if not respondio:
        raise ValueError(f"No hubo respuesta de «{fuente.nombre}». Revise la conexión a internet.")
    raise ValueError(f"«{fuente.nombre}» no tiene imagen de esta zona.")


def centro_geografico(capa_dem):
    """(lon, lat) del centro del DEM."""
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    transformacion = QgsCoordinateTransform(capa_dem.crs(), wgs84, QgsProject.instance())
    centro = transformacion.transform(capa_dem.extent().center())
    return centro.x(), centro.y()


def _dibujar(capa, crs, extension, columnas, filas):
    """Bloque de la capa como matriz RGBA (filas × columnas × 4)."""
    ajustes = QgsMapSettings()
    ajustes.setLayers([capa])
    ajustes.setDestinationCrs(crs)
    ajustes.setOutputSize(QSize(columnas, filas))
    ajustes.setExtent(extension)
    ajustes.setBackgroundColor(QColor(0, 0, 0, 0))
    trabajo = QgsMapRendererParallelJob(ajustes)
    bucle = QEventLoop()
    trabajo.finished.connect(bucle.quit)
    trabajo.start()
    bucle.exec()
    imagen = trabajo.renderedImage().convertToFormat(QImage.Format.Format_RGBA8888)
    puntero = imagen.constBits()
    puntero.setsize(imagen.sizeInBytes())
    datos = numpy.frombuffer(puntero, numpy.uint8).reshape(imagen.height(), imagen.bytesPerLine())
    return datos[:, :columnas * 4].reshape(imagen.height(), columnas, 4).copy()


def _mascara_dem(ruta_dem, limites, columnas, filas):
    """True donde el DEM tiene dato, en la cuadrícula de la imagen."""
    ds = gdal.Warp("", ruta_dem, format="MEM", outputBounds=limites, width=columnas, height=filas,
                   resampleAlg="near", dstNodata=-9999.0, outputType=gdal.GDT_Float32)
    banda = ds.GetRasterBand(1)
    return banda.ReadAsArray() != banda.GetNoDataValue()


@_con_excepciones
def exportar_imagen(capa_fuente: QgsRasterLayer, capa_dem: QgsRasterLayer, ruta_tif: str,
                    resolucion_m: float = 0.5, recortar_al_dem: bool = True,
                    progreso: Optional[Callable[[float, str], None]] = None) -> int:
    """Guarda la capa dibujada sobre la extensión del DEM como GeoTIFF RGB con máscara.

    Fuera del contorno del DEM (si se pide) y donde la fuente no tiene imagen queda transparente.
    Devuelve el número de píxeles con imagen.
    """
    avisar = progreso or (lambda fraccion, texto: None)
    if resolucion_m <= 0:
        raise ValueError("La resolución debe ser positiva.")
    if capa_dem.crs().isGeographic():
        raise ValueError("El DEM debe estar en un sistema de coordenadas proyectado (metros).")
    ext = capa_dem.extent()
    x0 = math.floor(ext.xMinimum() / resolucion_m) * resolucion_m
    y1 = math.ceil(ext.yMaximum() / resolucion_m) * resolucion_m
    columnas = math.ceil((ext.xMaximum() - x0) / resolucion_m)
    filas = math.ceil((y1 - ext.yMinimum()) / resolucion_m)
    if columnas * filas > MAX_PIXELES:
        sugerida = math.ceil(math.sqrt(ext.width() * ext.height() / MAX_PIXELES) * 10) / 10
        raise ValueError(f"La imagen tendría {columnas * filas / 1e6:.0f} millones de píxeles. "
                         f"Use una resolución de {sugerida:g} m o más.")

    salida = gdal.GetDriverByName("GTiff").Create(
        ruta_tif, columnas, filas, 3, gdal.GDT_Byte,
        ["COMPRESS=JPEG", "PHOTOMETRIC=YCBCR", "JPEG_QUALITY=90", "TILED=YES", "BIGTIFF=IF_SAFER"])
    salida.SetGeoTransform((x0, resolucion_m, 0, y1, 0, -resolucion_m))
    salida.SetProjection(capa_dem.crs().toWkt())
    salida.CreateMaskBand(gdal.GMF_PER_DATASET)
    mascara = salida.GetRasterBand(1).GetMaskBand()
    bloques = [(c, f) for f in range(0, filas, LADO_BLOQUE) for c in range(0, columnas, LADO_BLOQUE)]
    con_imagen = 0
    for i, (c, f) in enumerate(bloques):
        avisar(i / len(bloques), f"Descargando la imagen (bloque {i + 1} de {len(bloques)})…")
        ancho, alto = min(LADO_BLOQUE, columnas - c), min(LADO_BLOQUE, filas - f)
        bx0, by1 = x0 + c * resolucion_m, y1 - f * resolucion_m
        bx1, by0 = bx0 + ancho * resolucion_m, by1 - alto * resolucion_m
        rgba = _dibujar(capa_fuente, capa_dem.crs(), QgsRectangle(bx0, by0, bx1, by1), ancho, alto)
        visible = rgba[:, :, 3] > 0
        if recortar_al_dem:
            visible &= _mascara_dem(capa_dem.source(), (bx0, by0, bx1, by1), ancho, alto)
        for banda in range(3):
            salida.GetRasterBand(banda + 1).WriteArray(rgba[:, :, banda], c, f)
        mascara.WriteArray(numpy.where(visible, 255, 0).astype(numpy.uint8), c, f)
        con_imagen += int(visible.sum())
    avisar(0.97, "Creando las vistas reducidas…")
    salida.BuildOverviews("AVERAGE", [2, 4, 8, 16, 32])
    salida.SetMetadataItem("FUENTE", capa_fuente.name())
    salida = None
    if not con_imagen:
        raise ValueError("La fuente no devolvió imagen para la zona del DEM.")
    return con_imagen


def imagen_para_dem(fuente, capa_dem: QgsRasterLayer, ruta_tif: str, resolucion_m: float = 0.5,
                    recortar_al_dem: bool = True, progreso=None) -> ResultadoImagen:
    """Imagen de una fuente de teselas (FuenteTeselas) o de una capa ráster del proyecto."""
    zoom = metros = None
    if isinstance(fuente, FuenteTeselas):
        (progreso or (lambda f, t: None))(0.0, f"Consultando el zoom disponible en «{fuente.nombre}»…")
        lon, lat = centro_geografico(capa_dem)
        zoom = zoom_disponible(fuente, lon, lat)
        metros = metros_por_pixel(lat, zoom)
        capa = fuente.capa(zoom)
    else:
        capa = fuente
    if not capa.isValid():
        raise ValueError(f"No se pudo abrir la fuente «{capa.name()}».")
    exportar_imagen(capa, capa_dem, ruta_tif, resolucion_m, recortar_al_dem, progreso)
    with gdal.ExceptionMgr(useExceptions=True):
        ds = gdal.Open(ruta_tif)
        columnas, filas = ds.RasterXSize, ds.RasterYSize
        ds = None
    return ResultadoImagen(ruta_tif, columnas, filas, resolucion_m, zoom, metros)


def configurar_terreno_3d(capa_dem: QgsRasterLayer, exageracion: float = 1.0):
    """Usa el DEM como terreno del proyecto (lo leen las vistas 3D nuevas)."""
    from qgis.core import QgsRasterDemTerrainProvider
    terreno = QgsRasterDemTerrainProvider()
    terreno.setLayer(capa_dem)
    terreno.setScale(exageracion)
    QgsProject.instance().elevationProperties().setTerrainProvider(terreno)
    return terreno


def abrir_vista_3d(iface, capa_dem: QgsRasterLayer, exageracion: float = 1.0):
    """Configura el terreno y abre una vista 3D con las capas visibles del mapa sobre él."""
    configurar_terreno_3d(capa_dem, exageracion)
    if not hasattr(iface, "createNewMapCanvas3D"):
        raise ValueError("Esta versión de QGIS no permite abrir la vista 3D desde un complemento. "
                         "Ábrala en Ver → Nueva vista de mapa 3D.")
    existentes = {lienzo.objectName() for lienzo in iface.mapCanvases3D()}
    nombre, n = "RiegoLibre 3D", 1
    while nombre in existentes:
        n += 1
        nombre = f"RiegoLibre 3D ({n})"
    lienzo = iface.createNewMapCanvas3D(nombre)
    if lienzo is None:
        raise ValueError("QGIS no pudo abrir la vista 3D (revise que el complemento 3D esté disponible).")
    return lienzo
