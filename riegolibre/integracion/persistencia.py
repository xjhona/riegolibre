"""Guarda en un GeoPackage las capas que crea RiegoLibre, para que no se pierdan al cerrar QGIS.

Las capas nacen en memoria y se pasan a `<proyecto>_riegolibre.gpkg`, en la carpeta del
proyecto, en cuanto el proyecto tiene archivo (como «Hacer permanente» de QGIS, pero
automático). Las vistas previas siguen en memoria: se rehacen a cada rato.
"""

import os
import re
import unicodedata
from typing import List, Optional

from qgis.core import (QgsDataProvider, QgsProject, QgsProviderRegistry, QgsVectorFileWriter,
                       QgsVectorLayer)

from .subunidad_mapa import PROPIEDAD

TEMPORAL = "riegolibre/temporal"  # capas que no vale la pena guardar (vistas previas)
PROPIEDADES_PROPIAS = (PROPIEDAD, "red_automatica")  # cualquiera de ellas marca una capa de RiegoLibre


def ruta_gpkg(proyecto=None) -> Optional[str]:
    """GeoPackage de las capas del proyecto, o None si el proyecto aún no tiene archivo."""
    proyecto = proyecto or QgsProject.instance()
    archivo = proyecto.absoluteFilePath()
    if not archivo:
        return None
    base = os.path.splitext(os.path.basename(archivo))[0]
    return os.path.join(os.path.dirname(archivo), f"{base}_riegolibre.gpkg")


def nombre_tabla(nombre: str) -> str:
    """Nombre de tabla sin tildes ni símbolos: «Laterales · Lote 32» → «laterales_lote_32»."""
    texto = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_") or "capa"


def es_temporal_propia(capa) -> bool:
    """Capa en memoria creada por RiegoLibre que conviene guardar."""
    if not isinstance(capa, QgsVectorLayer) or capa.providerType() != "memory":
        return False
    if capa.customProperty(TEMPORAL) or capa.customProperty(PROPIEDAD) == "vista_previa":
        return False
    return any(capa.customProperty(p) for p in PROPIEDADES_PROPIAS)


def _tablas_en_uso(ruta, proyecto) -> set:
    """Tablas del GeoPackage que leen las capas del proyecto (no se pueden sobrescribir)."""
    ruta = os.path.normcase(os.path.abspath(ruta))
    usadas = set()
    for capa in proyecto.mapLayers().values():
        if not isinstance(capa, QgsVectorLayer) or capa.providerType() != "ogr":
            continue
        partes = QgsProviderRegistry.instance().decodeUri("ogr", capa.source())
        if os.path.normcase(os.path.abspath(partes.get("path", ""))) == ruta and partes.get("layerName"):
            usadas.add(partes["layerName"])
    return usadas


def hacer_permanente(capa, proyecto=None) -> bool:
    """Escribe la capa en el GeoPackage del proyecto y la cambia para que lea de allí.

    Conserva el estilo, las etiquetas y las propiedades de la capa. Devuelve False si el
    proyecto no tiene archivo o la capa se está editando (se guardará más adelante).
    """
    proyecto = proyecto or QgsProject.instance()
    ruta = ruta_gpkg(proyecto)
    if ruta is None or capa.isEditable():
        return False
    usadas = _tablas_en_uso(ruta, proyecto)
    base = nombre_tabla(capa.name())
    tabla, n = base, 1
    while tabla in usadas:
        n += 1
        tabla = f"{base}_{n}"
    opciones = QgsVectorFileWriter.SaveVectorOptions()
    opciones.driverName = "GPKG"
    opciones.layerName = tabla
    opciones.fileEncoding = "UTF-8"
    opciones.actionOnExistingFile = (QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
                                     if os.path.exists(ruta)
                                     else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
    error, mensaje, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(capa, ruta, proyecto.transformContext(), opciones)
    if error != QgsVectorFileWriter.WriterError.NoError:
        raise OSError(f"No se pudo guardar «{capa.name()}» en {ruta}: {mensaje}")
    capa.setDataSource(f"{ruta}|layername={tabla}", capa.name(), "ogr", QgsDataProvider.ProviderOptions())
    if not capa.isValid():
        raise OSError(f"Se guardó «{capa.name()}» en {ruta}, pero no se pudo abrir de nuevo.")
    return True


def guardar_capas_temporales(proyecto=None) -> List[str]:
    """Pasa al GeoPackage todas las capas temporales de RiegoLibre. Devuelve sus nombres."""
    proyecto = proyecto or QgsProject.instance()
    if ruta_gpkg(proyecto) is None:
        return []
    return [capa.name() for capa in list(proyecto.mapLayers().values())
            if es_temporal_propia(capa) and hacer_permanente(capa, proyecto)]


def guardar_capas_de_dibujo(capas, proyecto=None) -> Optional[str]:
    """Marca como de RiegoLibre las capas para dibujar (ya agregadas al proyecto) y las guarda.

    Hay que llamarla antes de activar la edición. Devuelve la ruta del GeoPackage, o None si
    quedaron en memoria porque el proyecto aún no tiene archivo (se guardarán al guardarlo).
    """
    proyecto = proyecto or QgsProject.instance()
    for capa in capas:
        capa.setCustomProperty(PROPIEDAD, "dibujo")
    guardadas = [hacer_permanente(capa, proyecto) for capa in capas]
    return ruta_gpkg(proyecto) if all(guardadas) else None


def aviso_html(ruta: Optional[str]) -> str:
    """Párrafo que dice dónde quedan guardadas las capas nuevas."""
    if ruta:
        return f"<p>Las capas se guardan en <i>{os.path.basename(ruta)}</i>, junto al proyecto.</p>"
    return ("<p>El proyecto aún no tiene archivo: las capas son temporales hasta que lo guarde; "
            "entonces pasan solas a un GeoPackage junto al proyecto.</p>")
