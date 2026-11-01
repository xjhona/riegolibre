"""Presión mínima y máxima de cada subunidad, marcadas en el mapa («Pressure Limits» de IRRICAD).

Para cada subunidad calculada (capas «Válvula · nombre» y «Laterales · nombre») se busca el emisor con
la presión más baja y el de la más alta, y se pone un marcador en cada uno, con su valor, en la capa
«Presión mínima y máxima». Se puede hacer con todas las subunidades o solo con las de las válvulas (o
lotes) seleccionados, y borrar los marcadores.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsCoordinateTransform, QgsFeature, QgsGeometry,
                       QgsMarkerSymbol, QgsPalLayerSettings, QgsPointXY, QgsProject, QgsProperty,
                       QgsRendererCategory, QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from .bloque_mapa import nombre_del_lote
from .info_objeto import (LATERALES, VALVULA, Candidato, _nombre_sin_prefijo, _valor, capas_con_resultados,
                          perfil_lateral, tipo_de_capa)
from .lotes import capas_de_lotes
from .red_mapa import capas_de_bloques
from .subunidad_mapa import PROPIEDAD

NOMBRE_CAPA = "Presión mínima y máxima"
PROPIEDAD_LIMITES = "limites_presion"  # valor de `subunidad_mapa.PROPIEDAD` en la capa de marcadores
MINIMA, MAXIMA = "Mín", "Máx"
COLORES = {MINIMA: "#1565c0", MAXIMA: "#c62828"}
CAMPOS = ("tipo:string(10)", "presion:double", "subunidad:string(120)", "rotulo:string(60)")


@dataclass
class Subunidad:
    nombre: str
    valvula: QgsVectorLayer
    laterales: QgsVectorLayer


@dataclass
class ResumenMarcadores:
    subunidades: int = 0
    marcadores: int = 0
    sin_resultados: List[str] = field(default_factory=list)  # subunidades sin laterales calculados


def subunidades_calculadas(proyecto=None) -> List[Subunidad]:
    """Subunidades con sus capas de válvula y de laterales (las dos de la misma subunidad), por nombre."""
    capas: Dict[str, Dict[str, QgsVectorLayer]] = {}
    for capa in capas_con_resultados(proyecto, solo_visibles=False):
        tipo = tipo_de_capa(capa)
        if tipo in (VALVULA, LATERALES):
            capas.setdefault(_nombre_sin_prefijo(capa), {})[tipo] = capa
    return [Subunidad(nombre, c[VALVULA], c[LATERALES]) for nombre, c in sorted(capas.items())
            if VALVULA in c and LATERALES in c]


# ------------------------------------------------------------------ cuáles se marcan


def _poligonos_seleccionados(crs_destino, proyecto):
    """[(nombre del lote o None, geometría)] de los lotes y bloques seleccionados, en `crs_destino`."""
    poligonos = []
    for capa in capas_de_lotes() + capas_de_bloques(proyecto):
        if not capa.selectedFeatureCount():
            continue
        transformacion = QgsCoordinateTransform(capa.crs(), crs_destino, proyecto)
        es_lote = capa in capas_de_lotes()
        for entidad in capa.selectedFeatures():
            geometria = QgsGeometry(entidad.geometry())
            geometria.transform(transformacion)
            poligonos.append((nombre_del_lote(entidad) if es_lote else None, geometria))
    return poligonos


def seleccionadas(subunidades: List[Subunidad], proyecto=None) -> List[Subunidad]:
    """Las subunidades cuya válvula está seleccionada, o cuyo lote (o bloque) está seleccionado."""
    proyecto = proyecto or QgsProject.instance()
    elegidas = []
    for sub in subunidades:
        puntos = list(sub.valvula.getFeatures())
        if any(e.id() in sub.valvula.selectedFeatureIds() for e in puntos):
            elegidas.append(sub)
            continue
        for nombre, poligono in _poligonos_seleccionados(sub.valvula.crs(), proyecto):
            if nombre == sub.nombre or any(poligono.intersects(e.geometry()) for e in puntos):
                elegidas.append(sub)
                break
    return elegidas


# ------------------------------------------------------------------ dónde están los extremos


def _punto_del_extremo(capa, entidad, tipo) -> QgsPointXY:
    """Punto del lateral donde está su emisor de menor (o mayor) presión.

    Se reconstruye el lateral como en la ficha del objeto. Si no se puede (capa calculada con una versión
    anterior), se toma el extremo aguas abajo para la mínima y la entrada para la máxima.
    """
    geometria = entidad.geometry()
    perfil = perfil_lateral(Candidato(capa, entidad, LATERALES, 0.0))
    if perfil is not None and perfil.resultado.presiones_m:
        presiones = perfil.resultado.presiones_m
        i = presiones.index(min(presiones) if tipo == MINIMA else max(presiones))
        distancia = perfil.resultado.posiciones_m[i]
    else:
        distancia = geometria.length() if tipo == MINIMA else 0.0
    return geometria.interpolate(distancia).asPoint()


def extremos_de(sub: Subunidad) -> List[Tuple[str, QgsPointXY, float]]:
    """[(tipo, punto en el SRC de los laterales, presión en m)] con el mínimo y el máximo de la subunidad."""
    mejores: Dict[str, Optional[Tuple[QgsFeature, float]]] = {MINIMA: None, MAXIMA: None}
    for entidad in sub.laterales.getFeatures():
        for tipo, campo, mejor in ((MINIMA, "p_min", min), (MAXIMA, "p_max", max)):
            valor = _valor(entidad, campo)
            if valor is not None and (mejores[tipo] is None or mejor(valor, mejores[tipo][1]) == valor):
                mejores[tipo] = (entidad, float(valor))
    extremos = []
    for tipo, par in mejores.items():
        if par is not None:
            entidad, presion = par
            extremos.append((tipo, _punto_del_extremo(sub.laterales, entidad, tipo), presion))
    return extremos


# ------------------------------------------------------------------ la capa de marcadores


def capa_de_marcadores(crear=False, crs=None) -> Optional[QgsVectorLayer]:
    for capa in QgsProject.instance().mapLayers().values():
        if isinstance(capa, QgsVectorLayer) and capa.customProperty(PROPIEDAD) == PROPIEDAD_LIMITES:
            return capa
    if not crear:
        return None
    capa = QgsVectorLayer("Point?" + "&".join(f"field={c}" for c in CAMPOS), NOMBRE_CAPA, "memory")
    capa.setCrs(crs or QgsProject.instance().crs())
    capa.setCustomProperty(PROPIEDAD, PROPIEDAD_LIMITES)
    dar_estilo(capa)
    QgsProject.instance().addMapLayer(capa)
    return capa


def dar_estilo(capa):
    """Círculo azul (mínima) o rojo (máxima) con su valor al lado: «Máx: 21.0 m»."""
    categorias = [QgsRendererCategory(tipo, QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": color, "size": "3.4", "outline_color": "#ffffff", "outline_width": "0.4"}), tipo)
        for tipo, color in COLORES.items()]
    capa.setRenderer(QgsCategorizedSymbolRenderer("tipo", categorias))
    etiquetas = QgsPalLayerSettings()
    etiquetas.fieldName = "rotulo"
    etiquetas.placement = Qgis.LabelPlacement.AroundPoint
    etiquetas.dist = 1.5
    etiquetas.priority = 10
    colocacion = etiquetas.placementSettings()
    colocacion.setOverlapHandling(Qgis.LabelOverlapHandling.AllowOverlapIfRequired)
    etiquetas.setPlacementSettings(colocacion)
    formato = QgsTextFormat()
    formato.setSize(9)
    formato.setForcedBold(True)
    fondo = QgsTextBufferSettings()
    fondo.setEnabled(True)
    fondo.setSize(1.0)
    formato.setBuffer(fondo)
    etiquetas.setFormat(formato)
    # El color del texto sigue al del marcador
    etiquetas.dataDefinedProperties().setProperty(
        QgsPalLayerSettings.Property.Color,
        QgsProperty.fromExpression(f"CASE WHEN \"tipo\" = '{MAXIMA}' THEN '{COLORES[MAXIMA]}' "
                                   f"ELSE '{COLORES[MINIMA]}' END"))
    capa.setLabeling(QgsVectorLayerSimpleLabeling(etiquetas))
    capa.setLabelsEnabled(True)


def _quitar_de(capa, nombres):
    ids = [e.id() for e in capa.getFeatures() if str(e["subunidad"]) in nombres]
    if ids:
        capa.dataProvider().deleteFeatures(ids)


# ------------------------------------------------------------------ lo que usa la interfaz


def mostrar(solo_seleccionadas=False, proyecto=None) -> ResumenMarcadores:
    """Pone los marcadores de presión mínima y máxima de todas las subunidades (o de las seleccionadas).

    Los marcadores que ya tenían esas subunidades se reemplazan. ValueError si no hay nada que marcar.
    """
    proyecto = proyecto or QgsProject.instance()
    subunidades = subunidades_calculadas(proyecto)
    if not subunidades:
        raise ValueError("No hay subunidades calculadas. Diseñe y calcule los lotes con «Bloque de goteo».")
    if solo_seleccionadas:
        subunidades = seleccionadas(subunidades, proyecto)
        if not subunidades:
            raise ValueError("Seleccione primero una válvula o un lote (con «Seleccionar entidades») que tenga "
                             "su bloque calculado.")
    resumen = ResumenMarcadores()
    capa = capa_de_marcadores(crear=True, crs=subunidades[0].laterales.crs())
    nuevas = []
    for sub in subunidades:
        extremos = extremos_de(sub)
        if not extremos:
            resumen.sin_resultados.append(sub.nombre)
            continue
        transformacion = QgsCoordinateTransform(sub.laterales.crs(), capa.crs(), proyecto)
        for tipo, punto, presion in extremos:
            entidad = QgsFeature(capa.fields())
            entidad.setGeometry(QgsGeometry.fromPointXY(transformacion.transform(punto)))
            entidad.setAttributes([tipo, round(presion, 3), sub.nombre, f"{tipo}: {presion:.1f} m"])
            nuevas.append(entidad)
        resumen.subunidades += 1
    _quitar_de(capa, {s.nombre for s in subunidades})
    capa.dataProvider().addFeatures(nuevas)
    capa.updateExtents()
    capa.triggerRepaint()
    resumen.marcadores = len(nuevas)
    return resumen


def borrar(proyecto=None) -> int:
    """Quita la capa de marcadores del proyecto. Devuelve cuántos marcadores tenía."""
    proyecto = proyecto or QgsProject.instance()
    capa = capa_de_marcadores()
    if capa is None:
        return 0
    cantidad = capa.featureCount()
    proyecto.removeMapLayer(capa.id())
    return cantidad
