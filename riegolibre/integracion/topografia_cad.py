"""Topografía de un plano CAD (DXF): curvas de nivel → modelo de elevación (DEM) y lindero → polígono.

Las curvas son polilíneas con elevación: la `LWPOLYLINE` habitual guarda una sola cota para toda la
línea y la polilínea 3D una por vértice; GDAL entrega ambas como líneas con Z. El DEM se obtiene por
triangulación lineal (TIN) de los vértices de las curvas. Donde no hay curvas, la triangulación
tendería triángulos largos sobre zonas sin levantamiento (huecos, bordes cóncavos), así que se
descartan las celdas que quedan a más de una distancia dada de la curva más cercana.
"""

import functools
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from osgeo import gdal, ogr, osr

NODATA = -9999.0
MAX_CELDAS = 30_000_000  # unos 120 MB por cuadrícula de 4 bytes
FILAS_POR_BLOQUE = 512
CAPA_CURVAS = "curvas_nivel"
CAPA_LINDERO = "lindero"
TOLERANCIA_CIERRE_M = 0.5  # una polilínea del lindero que casi cierra se cierra si el hueco es menor


def _con_excepciones(funcion):
    """Activa las excepciones de GDAL solo durante la función, sin cambiar el modo global de QGIS."""
    @functools.wraps(funcion)
    def envoltura(*args, **kwargs):
        with gdal.ExceptionMgr(useExceptions=True), ogr.ExceptionMgr(useExceptions=True),                 osr.ExceptionMgr(useExceptions=True):
            return funcion(*args, **kwargs)
    return envoltura


@dataclass
class CapaCad:
    """Resumen de una capa del dibujo CAD."""

    nombre: str
    lineas: int = 0
    cerradas: int = 0
    con_cota: int = 0  # líneas con alguna Z distinta de 0
    cota_min: Optional[float] = None
    cota_max: Optional[float] = None

    @property
    def parece_curvas(self):
        return self.con_cota > 0


@dataclass
class ContenidoDxf:
    capas: List[CapaCad]
    extension: tuple  # (xmin, xmax, ymin, ymax) de las líneas

    @property
    def ancho(self):
        return self.extension[1] - self.extension[0]

    @property
    def alto(self):
        return self.extension[3] - self.extension[2]


@dataclass
class ResultadoTopografia:
    ruta_curvas: str  # GeoPackage con las curvas y, si se pidió, el lindero
    ruta_dem: str
    curvas: int
    paso_m: float
    columnas: int
    filas: int
    cota_min: float
    cota_max: float
    cobertura: float  # fracción de celdas del DEM con dato
    linderos: int = 0
    area_lindero_ha: float = 0.0
    avisos: List[str] = field(default_factory=list)


def _abrir_dxf(ruta):
    if not os.path.isfile(ruta):
        raise ValueError(f"No se encuentra el archivo:\n{ruta}")
    try:
        ds = gdal.OpenEx(ruta, gdal.OF_VECTOR, allowed_drivers=["DXF"])
    except RuntimeError as error:
        raise ValueError(f"No se pudo leer el DXF ({error}). Guárdelo de nuevo desde el CAD como "
                         "«AutoCAD DXF» (2013 o 2018, ASCII).") from error
    if ds is None or ds.GetLayerCount() == 0:
        raise ValueError("El archivo no tiene entidades que GDAL pueda leer.")
    return ds


def _lineas(geometria):
    """Listas de vértices (x, y, z) de las partes lineales de una geometría."""
    if geometria is None:
        return
    tipo = ogr.GT_Flatten(geometria.GetGeometryType())
    if tipo in (ogr.wkbLineString, ogr.wkbLinearRing):
        puntos = geometria.GetPoints() or []
        if len(puntos) >= 2:
            yield [(p[0], p[1], p[2] if len(p) > 2 else 0.0) for p in puntos]
    elif tipo in (ogr.wkbMultiLineString, ogr.wkbGeometryCollection):
        for i in range(geometria.GetGeometryCount()):
            yield from _lineas(geometria.GetGeometryRef(i))


def _cerrada(puntos, tolerancia=1e-6):
    return len(puntos) >= 4 and math.hypot(puntos[0][0] - puntos[-1][0],
                                           puntos[0][1] - puntos[-1][1]) <= tolerancia


@_con_excepciones
def leer_dxf(ruta) -> ContenidoDxf:
    """Capas del DXF con el número de líneas y el rango de cotas de cada una."""
    ds = _abrir_dxf(ruta)
    capas: Dict[str, CapaCad] = {}
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    capa_ogr = ds.GetLayer(0)
    for entidad in capa_ogr:
        for puntos in _lineas(entidad.GetGeometryRef()):
            nombre = entidad.GetField("Layer") or "0"
            capa = capas.setdefault(nombre, CapaCad(nombre))
            capa.lineas += 1
            if _cerrada(puntos):
                capa.cerradas += 1
            zs = [p[2] for p in puntos]
            if any(z != 0 for z in zs):
                capa.con_cota += 1
                capa.cota_min = min(zs) if capa.cota_min is None else min(capa.cota_min, min(zs))
                capa.cota_max = max(zs) if capa.cota_max is None else max(capa.cota_max, max(zs))
            xs = [p[0] for p in puntos]
            ys = [p[1] for p in puntos]
            xmin, xmax = min(xmin, min(xs)), max(xmax, max(xs))
            ymin, ymax = min(ymin, min(ys)), max(ymax, max(ys))
    if not capas:
        raise ValueError("El DXF no tiene líneas ni polilíneas.")
    return ContenidoDxf(sorted(capas.values(), key=lambda c: c.nombre.lower()), (xmin, xmax, ymin, ymax))


def parecen_coordenadas_planas(extension):
    """True si las coordenadas no caben en grados (por ejemplo, UTM)."""
    xmin, xmax, ymin, ymax = extension
    return max(abs(xmin), abs(xmax)) > 360 or max(abs(ymin), abs(ymax)) > 90


def celdas_estimadas(extension, paso_m):
    xmin, xmax, ymin, ymax = extension
    return (math.ceil((xmax - xmin) / paso_m) + 1) * (math.ceil((ymax - ymin) / paso_m) + 1)


def _borrar(ruta):
    if os.path.exists(ruta):
        try:
            os.remove(ruta)
        except OSError as error:
            raise ValueError(f"No se puede reemplazar «{os.path.basename(ruta)}»: está abierto en otro "
                             "programa o en este proyecto. Quite la capa del mapa o elija otra carpeta."
                             ) from error


def _srs(crs_wkt):
    srs = osr.SpatialReference()
    try:
        srs.ImportFromWkt(crs_wkt)
    except RuntimeError as error:
        raise ValueError("El sistema de coordenadas elegido no es válido.") from error
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def _cerrar_anillo(puntos):
    """Anillo 2D cerrado, o None si la polilínea no cierra dentro de la tolerancia."""
    if len(puntos) < 3:
        return None
    if not _cerrada(puntos, TOLERANCIA_CIERRE_M):
        return None
    anillo = [(p[0], p[1]) for p in puntos]
    if anillo[0] != anillo[-1]:
        anillo.append(anillo[0])
    return anillo if len(anillo) >= 4 else None


def _escribir_capas(ds_dxf, ruta_gpkg, srs, capas_curvas, capa_lindero, avisos):
    """Copia las curvas (y el lindero) del DXF al GeoPackage. Devuelve (curvas, linderos, área_ha)."""
    _borrar(ruta_gpkg)
    salida = ogr.GetDriverByName("GPKG").CreateDataSource(ruta_gpkg)
    curvas = salida.CreateLayer(CAPA_CURVAS, srs, ogr.wkbLineString25D)
    curvas.CreateField(ogr.FieldDefn("cota", ogr.OFTReal))
    curvas.CreateField(ogr.FieldDefn("capa_cad", ogr.OFTString))
    lindero = None
    if capa_lindero:
        lindero = salida.CreateLayer(CAPA_LINDERO, srs, ogr.wkbPolygon)
        lindero.CreateField(ogr.FieldDefn("area_ha", ogr.OFTReal))
        lindero.CreateField(ogr.FieldDefn("capa_cad", ogr.OFTString))

    try:
        salida.StartTransaction()
        n_curvas, n_linderos, abiertas, sin_cota, area_ha = _copiar_entidades(
            ds_dxf, curvas, lindero, set(capas_curvas), capa_lindero)
        salida.CommitTransaction()
    finally:
        curvas = lindero = salida = None

    if sin_cota:
        avisos.append(f"Se descartaron {sin_cota} líneas de las capas de curvas que no tienen elevación (Z = 0).")
    if abiertas:
        avisos.append(f"{abiertas} polilíneas de la capa «{capa_lindero}» no están cerradas "
                      f"(hueco mayor que {TOLERANCIA_CIERRE_M:g} m) y no se convirtieron en polígono.")
    if capa_lindero and not n_linderos:
        avisos.append(f"La capa «{capa_lindero}» no tiene polilíneas cerradas: no se creó el lindero.")
    return n_curvas, n_linderos, area_ha


def _copiar_entidades(ds_dxf, curvas, lindero, seleccion, capa_lindero):
    n_curvas = sin_cota = n_linderos = abiertas = 0
    area_ha = 0.0
    capa_ogr = ds_dxf.GetLayer(0)
    capa_ogr.ResetReading()
    for entidad in capa_ogr:
        nombre = entidad.GetField("Layer") or "0"
        if nombre not in seleccion and nombre != capa_lindero:
            continue
        for puntos in _lineas(entidad.GetGeometryRef()):
            if nombre in seleccion:
                zs = [p[2] for p in puntos]
                if all(z == 0 for z in zs):
                    sin_cota += 1
                    continue
                linea = ogr.Geometry(ogr.wkbLineString25D)
                for x, y, z in puntos:
                    linea.AddPoint(x, y, z)
                nueva = ogr.Feature(curvas.GetLayerDefn())
                nueva.SetGeometry(linea)
                if max(zs) - min(zs) < 1e-6:
                    nueva.SetField("cota", zs[0])
                nueva.SetField("capa_cad", nombre)
                curvas.CreateFeature(nueva)
                n_curvas += 1
            if nombre == capa_lindero:
                anillo = _cerrar_anillo(puntos)
                if anillo is None:
                    abiertas += 1
                    continue
                geometria_anillo = ogr.Geometry(ogr.wkbLinearRing)
                for x, y in anillo:
                    geometria_anillo.AddPoint_2D(x, y)
                poligono = ogr.Geometry(ogr.wkbPolygon)
                poligono.AddGeometry(geometria_anillo)
                if not poligono.IsValid():
                    poligono = poligono.MakeValid() or poligono
                nueva = ogr.Feature(lindero.GetLayerDefn())
                nueva.SetGeometry(poligono)
                area = poligono.GetArea() / 10000.0
                nueva.SetField("area_ha", round(area, 4))
                nueva.SetField("capa_cad", nombre)
                lindero.CreateFeature(nueva)
                n_linderos += 1
                area_ha += area
    return n_curvas, n_linderos, abiertas, sin_cota, area_ha


@_con_excepciones
def generar_topografia(ruta_dxf: str, capas_curvas: Sequence[str], crs_wkt: str, carpeta_salida: str,
                       paso_m: float = 1.0, distancia_max_m: float = 30.0, capa_lindero: Optional[str] = None,
                       nombre_base: Optional[str] = None,
                       progreso: Optional[Callable[[float, str], None]] = None) -> ResultadoTopografia:
    """Crea `<nombre>_curvas.gpkg` (curvas y lindero) y `<nombre>_dem.tif` en la carpeta de salida.

    `progreso(fraccion, texto)` se llama durante el cálculo, con la fracción entre 0 y 1.
    """
    if not capas_curvas:
        raise ValueError("Elija al menos una capa de curvas de nivel.")
    if paso_m <= 0 or distancia_max_m <= 0:
        raise ValueError("El tamaño de celda y la distancia máxima deben ser positivos.")
    avisar = progreso or (lambda fraccion, texto: None)
    srs = _srs(crs_wkt)
    if srs.IsGeographic():
        raise ValueError("Elija un sistema de coordenadas proyectado en metros (por ejemplo, la zona "
                         "UTM del proyecto): las coordenadas del CAD están en metros, no en grados.")
    os.makedirs(carpeta_salida, exist_ok=True)
    base = nombre_base or os.path.splitext(os.path.basename(ruta_dxf))[0]
    ruta_gpkg = os.path.join(carpeta_salida, f"{base}_curvas.gpkg")
    ruta_dem = os.path.join(carpeta_salida, f"{base}_dem.tif")
    avisos: List[str] = []

    avisar(0.0, "Leyendo las curvas del DXF…")
    ds_dxf = _abrir_dxf(ruta_dxf)
    n_curvas, n_linderos, area_ha = _escribir_capas(ds_dxf, ruta_gpkg, srs, capas_curvas, capa_lindero, avisos)
    ds_dxf = None
    if n_curvas == 0:
        raise ValueError("Las capas elegidas no tienen líneas con elevación. Revise en el CAD que las "
                         "curvas sean polilíneas con su cota (propiedad «Elevación»).")

    curvas_ds = gdal.OpenEx(ruta_gpkg, gdal.OF_VECTOR)
    xmin, xmax, ymin, ymax = curvas_ds.GetLayerByName(CAPA_CURVAS).GetExtent()
    x0 = math.floor(xmin / paso_m) * paso_m
    y1 = math.ceil(ymax / paso_m) * paso_m
    columnas = math.floor((xmax - x0) / paso_m) + 1  # +1: la curva del borde queda dentro de una celda
    filas = math.floor((y1 - ymin) / paso_m) + 1
    if columnas * filas > MAX_CELDAS:
        sugerido = math.ceil(math.sqrt((xmax - xmin) * (ymax - ymin) / MAX_CELDAS) * 4) / 4
        raise ValueError(f"El DEM tendría {columnas * filas / 1e6:.0f} millones de celdas. Use una celda de "
                         f"{sugerido:g} m o más, o recorte el dibujo a la zona del proyecto.")

    avisar(0.05, "Triangulando las curvas (TIN)…")
    _borrar(ruta_dem)

    def avance_grid(fraccion, *_):
        avisar(0.05 + 0.75 * fraccion, "Triangulando las curvas (TIN)…")
        return 1

    dem = gdal.Grid(ruta_dem, curvas_ds, layers=[CAPA_CURVAS], format="GTiff",
                    algorithm=f"linear:radius=0:nodata={NODATA:g}",
                    outputBounds=[x0, y1, x0 + columnas * paso_m, y1 - filas * paso_m],
                    width=columnas, height=filas, outputType=gdal.GDT_Float32, outputSRS=srs.ExportToWkt(),
                    creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"], callback=avance_grid)
    if dem is None:
        raise ValueError("No se pudo crear el DEM.")
    dem = None

    avisar(0.82, "Descartando las zonas sin curvas…")
    dem = gdal.Open(ruta_dem, gdal.GA_Update)
    banda = dem.GetRasterBand(1)
    banda.SetNoDataValue(NODATA)
    memoria = gdal.GetDriverByName("MEM")
    marcas = memoria.Create("", columnas, filas, 1, gdal.GDT_Byte)
    marcas.SetGeoTransform(dem.GetGeoTransform())
    marcas.SetProjection(dem.GetProjection())
    gdal.RasterizeLayer(marcas, [1], curvas_ds.GetLayerByName(CAPA_CURVAS), burn_values=[1],
                        options=["ALL_TOUCHED=TRUE"])
    curvas_ds = None
    distancia = memoria.Create("", columnas, filas, 1, gdal.GDT_Float32)
    distancia.SetGeoTransform(dem.GetGeoTransform())
    banda_distancia = distancia.GetRasterBand(1)
    banda_distancia.SetNoDataValue(-1)
    gdal.ComputeProximity(marcas.GetRasterBand(1), banda_distancia,
                          ["VALUES=1", "DISTUNITS=GEO", f"MAXDIST={distancia_max_m}", "NODATA=-1"])
    marcas = None

    con_dato = 0
    cota_min, cota_max = math.inf, -math.inf
    for fila in range(0, filas, FILAS_POR_BLOQUE):
        n = min(FILAS_POR_BLOQUE, filas - fila)
        cotas = banda.ReadAsArray(0, fila, columnas, n)
        lejos = banda_distancia.ReadAsArray(0, fila, columnas, n) < 0
        cotas[lejos] = NODATA
        banda.WriteArray(cotas, 0, fila)
        validas = cotas[cotas != NODATA]
        if validas.size:
            con_dato += int(validas.size)
            cota_min = min(cota_min, float(validas.min()))
            cota_max = max(cota_max, float(validas.max()))
        avisar(0.85 + 0.15 * (fila + n) / filas, "Descartando las zonas sin curvas…")
    distancia = None
    banda.ComputeStatistics(False)
    banda = None
    dem = None
    if not con_dato:
        raise ValueError("El DEM quedó vacío: las curvas no forman superficie (¿una sola cota?).")
    return ResultadoTopografia(ruta_gpkg, ruta_dem, n_curvas, paso_m, columnas, filas, cota_min, cota_max,
                               con_dato / (columnas * filas), n_linderos, area_ha, avisos)


def agregar_al_mapa(resultado: ResultadoTopografia, nombre_grupo: str):
    """Añade el DEM, las curvas y el lindero al proyecto, dentro de un grupo.

    Devuelve (curvas, dem, lindero); lindero es None si no se importó.
    """
    from qgis.core import (QgsColorRampShader, QgsLineSymbol, QgsProject, QgsRasterLayer,
                           QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsStyle, QgsVectorLayer)
    from qgis.PyQt.QtGui import QColor

    proyecto = QgsProject.instance()
    dem = QgsRasterLayer(resultado.ruta_dem, "DEM (curvas del CAD)")
    rampa = QgsStyle.defaultStyle().colorRamp("Spectral")
    if rampa is not None:
        rampa.invert()
        sombreador = QgsColorRampShader(resultado.cota_min, resultado.cota_max, rampa)
        sombreador.classifyColorRamp(10)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(sombreador)
        dem.setRenderer(QgsSingleBandPseudoColorRenderer(dem.dataProvider(), 1, shader))
    curvas = QgsVectorLayer(f"{resultado.ruta_curvas}|layername={CAPA_CURVAS}", "Curvas de nivel", "ogr")
    curvas.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "120,84,52", "width": "0.15"}))
    capas = [curvas, dem]
    if resultado.linderos:
        lindero = QgsVectorLayer(f"{resultado.ruta_curvas}|layername={CAPA_LINDERO}", "Lindero", "ogr")
        simbolo = lindero.renderer().symbol()
        simbolo.symbolLayer(0).setFillColor(QColor(0, 0, 0, 0))
        simbolo.symbolLayer(0).setStrokeColor(QColor(198, 40, 40))
        simbolo.symbolLayer(0).setStrokeWidth(0.6)
        capas.insert(0, lindero)

    raiz = proyecto.layerTreeRoot()
    grupo = raiz.findGroup(nombre_grupo) or raiz.insertGroup(0, nombre_grupo)
    for capa in capas:
        proyecto.addMapLayer(capa, False)
        grupo.addLayer(capa)
    return curvas, dem, (capas[0] if resultado.linderos else None)


def capas_que_usan(rutas):
    """Capas del proyecto que leen alguno de los archivos dados (para quitarlas antes de reemplazarlos)."""
    from qgis.core import QgsProject

    normalizadas = {os.path.normcase(os.path.abspath(r)) for r in rutas}
    encontradas = []
    for capa in QgsProject.instance().mapLayers().values():
        fuente = capa.source().split("|")[0]
        if os.path.normcase(os.path.abspath(fuente)) in normalizadas:
            encontradas.append(capa)
    return encontradas
