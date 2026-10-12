"""Lotes del proyecto: importación desde un plano CAD (DXF) y parámetros del bloque de goteo de cada uno.

Cada lote es una polilínea cerrada del CAD. Su nombre se toma del texto que tenga dentro (si el plano
trae textos); si no, se numeran. Los lotes se guardan en un GeoPackage con los campos:

- `nombre`: nombre del lote (también el de su subunidad y su grupo de resultados),
- `area_ha`: área del polígono,
- `capa_cad`: capa del CAD de donde salió,
- `bloque`: parámetros del bloque de goteo (JSON), para volver a abrirlo con los mismos valores.
"""

import json
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional

from osgeo import ogr

from .topografia_cad import (_abrir_dxf, _borrar, _cerrar_anillo, _con_excepciones, _lineas, _srs)

CAPA_LOTES = "lotes"
PROPIEDAD_LOTES = "lotes"  # valor de `subunidad_mapa.PROPIEDAD` en la capa de lotes
CAMPO_NOMBRE, CAMPO_AREA, CAMPO_BLOQUE = "nombre", "area_ha", "bloque"
BANDA_ORDEN_M = 40.0  # al numerar, los lotes cuyo centro está en la misma franja de este alto van en una fila


@dataclass
class ResultadoLotes:
    ruta: str
    lotes: int
    area_ha: float
    con_nombre: int  # lotes que tomaron el nombre de un texto del plano
    avisos: List[str] = field(default_factory=list)


def _textos(ds):
    """(x, y, texto) de los textos del plano."""
    textos = []
    capa = ds.GetLayer(0)
    capa.ResetReading()
    for entidad in capa:
        geometria = entidad.GetGeometryRef()
        texto = entidad.GetField("Text") if entidad.GetFieldIndex("Text") >= 0 else None
        if not texto or geometria is None or ogr.GT_Flatten(geometria.GetGeometryType()) != ogr.wkbPoint:
            continue
        texto = " ".join(texto.replace("\\P", " ").split())
        if texto:
            textos.append((geometria.GetX(), geometria.GetY(), texto))
    return textos


def _nombre_dentro(poligono, textos):
    """El texto dentro del polígono más cercano a su centro, o None."""
    centro = poligono.Centroid()
    mejor = None
    for x, y, texto in textos:
        punto = ogr.Geometry(ogr.wkbPoint)
        punto.AddPoint_2D(x, y)
        if poligono.Contains(punto):
            d = math.hypot(x - centro.GetX(), y - centro.GetY())
            if mejor is None or d < mejor[0]:
                mejor = (d, texto)
    return mejor[1] if mejor else None


@_con_excepciones
def importar_lotes(ruta_dxf: str, capas_cad, crs_wkt: str, ruta_gpkg: str, usar_textos=True) -> ResultadoLotes:
    """Convierte las polilíneas cerradas de las capas dadas en lotes y los guarda en un GeoPackage."""
    srs = _srs(crs_wkt)
    if srs.IsGeographic():
        raise ValueError("Elija un sistema de coordenadas proyectado en metros (UTM).")
    ds = _abrir_dxf(ruta_dxf)
    capas_cad = set(capas_cad)
    poligonos, abiertas = [], 0
    capa_ogr = ds.GetLayer(0)
    for entidad in capa_ogr:
        nombre_capa = entidad.GetField("Layer") or "0"
        if nombre_capa not in capas_cad:
            continue
        for puntos in _lineas(entidad.GetGeometryRef()):
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
                poligono = poligono.MakeValid() if hasattr(poligono, "MakeValid") else poligono.Buffer(0)
            if poligono is None or poligono.IsEmpty() or poligono.GetArea() <= 0:
                continue
            poligonos.append((poligono, nombre_capa))
    if not poligonos:
        raise ValueError("Las capas elegidas no tienen polilíneas cerradas.")

    textos = _textos(ds) if usar_textos else []
    lotes = []
    for poligono, nombre_capa in poligonos:
        centro = poligono.Centroid()
        lotes.append([poligono, nombre_capa, _nombre_dentro(poligono, textos) if textos else None,
                      centro.GetX(), centro.GetY()])
    # Numeración de arriba abajo y de izquierda a derecha
    lotes.sort(key=lambda lote: (-math.floor(lote[4] / BANDA_ORDEN_M), lote[3]))
    digitos = len(str(len(lotes)))
    usados, con_nombre = set(), 0
    for i, lote in enumerate(lotes, 1):
        nombre = lote[2]
        if nombre:
            con_nombre += 1
        else:
            nombre = f"Lote {i:0{digitos}d}"
        base, n = nombre, 2
        while nombre in usados:
            nombre = f"{base} ({n})"
            n += 1
        usados.add(nombre)
        lote[2] = nombre

    _borrar(ruta_gpkg)
    salida = ogr.GetDriverByName("GPKG").CreateDataSource(ruta_gpkg)
    capa = salida.CreateLayer(CAPA_LOTES, srs, ogr.wkbMultiPolygon)
    capa.CreateField(ogr.FieldDefn(CAMPO_NOMBRE, ogr.OFTString))
    capa.CreateField(ogr.FieldDefn(CAMPO_AREA, ogr.OFTReal))
    capa.CreateField(ogr.FieldDefn("capa_cad", ogr.OFTString))
    capa.CreateField(ogr.FieldDefn(CAMPO_BLOQUE, ogr.OFTString))
    area_total = 0.0
    try:
        salida.StartTransaction()
        for poligono, nombre_capa, nombre, _, _ in lotes:
            entidad = ogr.Feature(capa.GetLayerDefn())
            entidad.SetGeometry(ogr.ForceToMultiPolygon(poligono))
            area = poligono.GetArea() / 10000
            area_total += area
            entidad.SetField(CAMPO_NOMBRE, nombre)
            entidad.SetField(CAMPO_AREA, round(area, 4))
            entidad.SetField("capa_cad", nombre_capa)
            capa.CreateFeature(entidad)
        salida.CommitTransaction()
    finally:
        capa = salida = None

    avisos = []
    if abiertas:
        avisos.append(f"{abiertas} polilíneas de las capas elegidas no están cerradas y no se importaron.")
    if usar_textos and not textos:
        avisos.append("El plano no tiene textos: los lotes se numeraron de arriba abajo y de izquierda a "
                      "derecha. Puede cambiar el nombre de cada uno en la pestaña «Área» del bloque o en la "
                      "tabla de atributos.")
    elif textos and con_nombre < len(lotes):
        avisos.append(f"{len(lotes) - con_nombre} lotes no tienen un texto dentro y se numeraron.")
    return ResultadoLotes(ruta_gpkg, len(lotes), area_total, con_nombre, avisos)


# ------------------------------------------------------------------ QGIS


def agregar_al_mapa(ruta_gpkg, nombre_grupo="Lotes"):
    """Agrega la capa de lotes al proyecto, con etiquetas con el nombre de cada lote."""
    from qgis.core import QgsProject, QgsVectorLayer
    capa = QgsVectorLayer(f"{ruta_gpkg}|layername={CAPA_LOTES}", "Lotes", "ogr")
    if not capa.isValid():
        raise ValueError(f"No se pudo abrir la capa de lotes de «{ruta_gpkg}».")
    preparar_capa(capa)
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    grupo = raiz.findGroup(nombre_grupo) or raiz.insertGroup(0, nombre_grupo)
    proyecto.addMapLayer(capa, False)
    grupo.addLayer(capa)
    return capa


def preparar_capa(capa):
    """Marca la capa como de lotes y le da estilo: borde rojo y etiqueta con el nombre."""
    from qgis.core import (QgsFillSymbol, QgsPalLayerSettings, QgsSingleSymbolRenderer, QgsTextBufferSettings,
                           QgsTextFormat, QgsVectorLayerSimpleLabeling)
    from qgis.PyQt.QtGui import QColor
    from .subunidad_mapa import PROPIEDAD

    capa.setCustomProperty(PROPIEDAD, PROPIEDAD_LOTES)
    capa.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "211,47,47", "outline_width": "0.5"})))
    etiquetas = QgsPalLayerSettings()
    etiquetas.fieldName = CAMPO_NOMBRE
    formato = QgsTextFormat()
    formato.setColor(QColor(183, 28, 28))
    formato.setSize(9)
    fondo = QgsTextBufferSettings()
    fondo.setEnabled(True)
    fondo.setSize(0.8)
    formato.setBuffer(fondo)
    etiquetas.setFormat(formato)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(etiquetas))
    capa.setLabelsEnabled(True)


def es_capa_de_lotes(capa):
    from qgis.core import QgsVectorLayer
    from .subunidad_mapa import PROPIEDAD
    if not isinstance(capa, QgsVectorLayer) or capa.fields().indexOf(CAMPO_NOMBRE) < 0 \
            or capa.fields().indexOf(CAMPO_BLOQUE) < 0:
        return False
    return capa.customProperty(PROPIEDAD) == PROPIEDAD_LOTES or capa.name().lower().startswith("lotes")


def capas_de_lotes():
    from qgis.core import QgsProject
    return [c for c in QgsProject.instance().mapLayers().values() if es_capa_de_lotes(c)]


def parametros_guardados(entidad) -> Optional[dict]:
    valor = entidad[CAMPO_BLOQUE]
    if not valor or not isinstance(valor, str):
        return None
    try:
        datos = json.loads(valor)
    except ValueError:
        return None
    return datos if isinstance(datos, dict) else None


def guardar_parametros(capa, id_entidad, datos: dict, nombre: Optional[str] = None):
    """Guarda los parámetros del bloque (y el nombre, si se da) en la entidad del lote."""
    cambios = {capa.fields().indexOf(CAMPO_BLOQUE): json.dumps(datos, ensure_ascii=False)}
    if nombre is not None:
        cambios[capa.fields().indexOf(CAMPO_NOMBRE)] = nombre
    if capa.isEditable():
        for indice, valor in cambios.items():
            capa.changeAttributeValue(id_entidad, indice, valor)
        return
    if not capa.dataProvider().changeAttributeValues({id_entidad: cambios}):
        raise ValueError(f"No se pudieron guardar los parámetros en la capa «{capa.name()}».")
    capa.triggerRepaint()


def ruta_por_defecto(ruta_dxf):
    base, _ = os.path.splitext(ruta_dxf)
    return base + "_lotes.gpkg"
