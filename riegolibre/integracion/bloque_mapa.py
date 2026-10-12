"""Bloque de goteo de un lote en el mapa: del polígono del lote al portalateral, los laterales, la
válvula y el cálculo de la subunidad; y la subdivisión de un lote en sub-bloques.

El motor (`nucleo.bloque`, `nucleo.subdivision`) trabaja con listas de puntos; aquí se convierten las
geometrías de QGIS, se leen las cotas del DEM y se crean las capas.
"""

from typing import List, Optional

from qgis.core import (Qgis, QgsFeature, QgsGeometry, QgsMarkerSymbol, QgsPointXY, QgsSingleSymbolRenderer,
                       QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor

from ..nucleo.bloque import Bloque, ParametrosBloque, trazar_bloque
from ..nucleo.subdivision import ParametrosSubdivision, subdividir
from .lotes import CAMPO_AREA, CAMPO_NOMBRE
from .subunidad_mapa import PROPIEDAD, LateralMapa, reemplazar_grupo
from .trazado_mapa import (anillos_de_geometria, funcion_cota, gradiente_del_terreno,
                           pendiente_a_lo_largo)

GRUPO_VISTA_PREVIA = "RiegoLibre · Vista previa del bloque"


def _punto(p):
    return QgsPointXY(p[0], p[1])


def trazar_en_lote(geometria, params: ParametrosBloque, crs, capa_dem=None, fuente=None,
                   alcance_m: Optional[float] = None) -> Bloque:
    """Traza el bloque en el polígono del lote (en el SRC dado, en metros)."""
    anillos = anillos_de_geometria(geometria)
    cota = pendiente = None
    if capa_dem is not None:
        cota = funcion_cota(capa_dem, crs)
        gradiente = gradiente_del_terreno(geometria, capa_dem, crs)
        if gradiente is not None:
            def pendiente(angulo):
                return pendiente_a_lo_largo(gradiente, angulo)
    bloque = trazar_bloque(anillos, params, cota=cota, fuente=fuente, pendiente=pendiente, alcance_m=alcance_m)
    if capa_dem is not None and bloque.desnivel_portalateral_m is None:
        bloque.avisos.append("El DEM no cubre los extremos del portalateral.")
    return bloque


def geometria_portalateral(bloque: Bloque) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([_punto(p) for p in bloque.portalateral])


def laterales_mapa(bloque: Bloque) -> List[LateralMapa]:
    return [LateralMapa(i, QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)]),
                        lat.distancia_m, lat.longitud_m)
            for i, lat in enumerate(bloque.laterales)]


def _capa(tipo, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "vista_previa")
    return capa


def vista_previa(bloques, crs):
    """Dibuja los bloques (sin calcular) en un grupo temporal que reemplaza al anterior.

    `bloques` es una lista de (nombre del lote, Bloque).
    """
    laterales = _capa("LineString", "field=lote:string(80)&field=longitud:double", "Laterales (vista previa)", crs)
    portas = _capa("LineString", "field=lote:string(80)&field=longitud:double", "Portalaterales (vista previa)", crs)
    valvulas = _capa("Point", "field=lote:string(80)", "Válvulas (vista previa)", crs)
    ent_lat, ent_porta, ent_valv = [], [], []
    for nombre, b in bloques:
        for lat in b.laterales:
            e = QgsFeature(laterales.fields())
            e.setGeometry(QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)]))
            e.setAttributes([nombre, round(lat.longitud_m, 2)])
            ent_lat.append(e)
        e = QgsFeature(portas.fields())
        e.setGeometry(geometria_portalateral(b))
        e.setAttributes([nombre, round(b.longitud_portalateral_m, 2)])
        ent_porta.append(e)
        e = QgsFeature(valvulas.fields())
        e.setGeometry(QgsGeometry.fromPointXY(_punto(b.valvula)))
        e.setAttributes([nombre])
        ent_valv.append(e)
    for capa, entidades in ((laterales, ent_lat), (portas, ent_porta), (valvulas, ent_valv)):
        capa.dataProvider().addFeatures(entidades)
        capa.updateExtents()
    simbolo = QgsSymbol.defaultSymbol(laterales.geometryType())
    simbolo.setColor(QColor("#3d7a3a"))
    simbolo.setWidth(0.3)
    laterales.setRenderer(QgsSingleSymbolRenderer(simbolo))
    simbolo = QgsSymbol.defaultSymbol(portas.geometryType())
    simbolo.setColor(QColor("#1565c0"))
    simbolo.setWidth(1.4)
    portas.setRenderer(QgsSingleSymbolRenderer(simbolo))
    valvulas.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "3", "outline_color": "#ffffff"})))
    return reemplazar_grupo(GRUPO_VISTA_PREVIA, [valvulas, portas, laterales])


def quitar_vista_previa():
    from qgis.core import QgsProject
    proyecto = QgsProject.instance()
    grupo = proyecto.layerTreeRoot().findGroup(GRUPO_VISTA_PREVIA)
    if grupo is not None:
        for nodo in grupo.findLayers():
            proyecto.removeMapLayer(nodo.layerId())
        proyecto.layerTreeRoot().removeChildNode(grupo)


def calcular_bloque(nombre, crs, bloque: Bloque, geometria_lote, config, avisos=None):
    """Calcula la subunidad del bloque y deja sus capas en el grupo «RiegoLibre · nombre»."""
    from dataclasses import replace

    from .calculo_subunidad import calcular_subunidad
    config = replace(config, entrada_m=bloque.valvula_m)
    return calcular_subunidad(nombre, crs, geometria_portalateral(bloque), geometria_lote, laterales_mapa(bloque),
                              config, list(avisos or []) + list(bloque.avisos))


# ------------------------------------------------------------------ subdivisión


def subdividir_en_lote(geometria, bloque: ParametrosBloque, angulo_deg: float,
                       params: ParametrosSubdivision):
    """Sub-bloques del lote: lista de (geometría, SubBloque), ya cortados con el polígono del lote."""
    partes = subdividir(anillos_de_geometria(geometria), bloque, angulo_deg, params)
    resultado = []
    for parte in partes:
        rectangulo = QgsGeometry.fromPolygonXY([[_punto(p) for p in parte.anillo + parte.anillo[:1]]])
        corte = geometria.intersection(rectangulo)
        poligonos = [g for g in corte.asGeometryCollection()
                     if g.type() == Qgis.GeometryType.Polygon and g.area() >= 1.0]
        if not poligonos:
            continue
        corte = QgsGeometry.unaryUnion(poligonos) if len(poligonos) > 1 else poligonos[0]
        resultado.append((corte, parte))
    return resultado


def vista_previa_subdivision(partes, crs):
    capa = _capa("Polygon", "field=parte:integer&field=hileras:integer&field=caudal:double&field=area_m2:double",
                 "Sub-bloques (vista previa)", crs)
    entidades = []
    for i, (geometria, parte) in enumerate(partes, 1):
        e = QgsFeature(capa.fields())
        e.setGeometry(geometria)
        e.setAttributes([i, parte.hileras, round(parte.caudal, 1), round(parte.area_m2, 1)])
        entidades.append(e)
    capa.dataProvider().addFeatures(entidades)
    capa.updateExtents()
    from qgis.core import QgsFillSymbol
    capa.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "255,160,0,70", "outline_color": "230,81,0", "outline_width": "0.6"})))
    return reemplazar_grupo(GRUPO_VISTA_PREVIA, [capa])


def reemplazar_lote_por_partes(capa, entidad, partes, nombres: List[str]) -> List[int]:
    """Reemplaza el lote por sus sub-bloques en la capa de lotes (con los mismos parámetros del bloque)."""
    nuevas = []
    campos = capa.fields()
    for (geometria, _), nombre in zip(partes, nombres):
        nueva = QgsFeature(campos)
        if capa.wkbType() != geometria.wkbType():
            geometria = QgsGeometry(geometria)
            geometria.convertToMultiType()
        nueva.setGeometry(geometria)
        for i in range(campos.count()):
            nombre_campo = campos.at(i).name()
            if nombre_campo == CAMPO_NOMBRE:
                nueva.setAttribute(i, nombre)
            elif nombre_campo == CAMPO_AREA:
                nueva.setAttribute(i, round(geometria.area() / 10000, 4))
            elif nombre_campo.lower() != "fid":  # el GeoPackage numera las entidades nuevas
                nueva.setAttribute(i, entidad[nombre_campo])
        nuevas.append(nueva)
    if capa.isEditable():
        if not capa.addFeatures(nuevas) or not capa.deleteFeature(entidad.id()):
            raise ValueError("No se pudo reemplazar el lote por sus sub-bloques.")
        return [f.id() for f in nuevas]
    proveedor = capa.dataProvider()
    ok, agregadas = proveedor.addFeatures(nuevas)
    if not ok or not proveedor.deleteFeatures([entidad.id()]):
        raise ValueError(f"No se pudo modificar la capa «{capa.name()}». ¿Es de solo lectura?")
    capa.updateExtents()
    capa.triggerRepaint()
    return [f.id() for f in agregadas]
