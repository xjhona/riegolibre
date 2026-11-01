# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Fuente de agua en el mapa: la capa «Fuente» con un solo punto, donde están la bomba y el cabezal.

Es el «Water Supply» de IRRICAD: de ese punto arranca la tubería matriz. La capa se crea la primera
vez, en el SRC del proyecto, y colocar la fuente otra vez reemplaza el punto anterior.
"""

from qgis.core import (Qgis, QgsFeature, QgsGeometry, QgsMarkerSymbol, QgsPalLayerSettings, QgsPointXY,
                       QgsProject, QgsSingleSymbolRenderer, QgsTextBufferSettings, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from .persistencia import guardar_capas_de_dibujo
from .red_mapa import NOMBRE_CAPA_RED, capas_de_valvulas, leer_valvulas
from .subunidad_mapa import PROPIEDAD, geometria_en, verificar_crs_metrico

NOMBRE_CAPA_FUENTE = "Fuente"
COLOR_FUENTE = "#1565c0"  # el azul del cuadro de la bomba en los resultados de la red


def capa_de_fuente(proyecto=None):
    """La capa de puntos «Fuente» del proyecto, o None. Si hay varias, gana la que creó RiegoLibre."""
    proyecto = proyecto or QgsProject.instance()
    capas = [c for c in proyecto.mapLayers().values()
             if isinstance(c, QgsVectorLayer) and c.name() == NOMBRE_CAPA_FUENTE
             and c.geometryType() == Qgis.GeometryType.Point]
    capas.sort(key=lambda c: (c.customProperty(PROPIEDAD) != "dibujo", c.id()))
    return capas[0] if capas else None


def tiene_fuente(capa):
    return capa is not None and capa.featureCount() > 0


def estilo_fuente(capa):
    """Cuadro azul, como la bomba de los resultados, con el rótulo «Fuente»."""
    capa.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": COLOR_FUENTE, "size": "5", "outline_color": "#ffffff"})))
    etiquetas = QgsPalLayerSettings()
    etiquetas.fieldName = f"'{NOMBRE_CAPA_FUENTE}'"
    etiquetas.isExpression = True
    etiquetas.placement = Qgis.LabelPlacement.AroundPoint
    etiquetas.dist = 1.5  # mm entre el cuadro y el texto
    formato = QgsTextFormat()
    formato.setColor(QColor(COLOR_FUENTE))
    formato.setSize(9)
    fondo = QgsTextBufferSettings()
    fondo.setEnabled(True)
    fondo.setSize(0.7)
    formato.setBuffer(fondo)
    etiquetas.setFormat(formato)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(etiquetas))
    capa.setLabelsEnabled(True)


def crear_capa_fuente(proyecto=None):
    """Crea la capa «Fuente» (un punto) en el SRC del proyecto y la guarda en el GeoPackage.

    Devuelve (capa, ruta del GeoPackage o None si el proyecto aún no tiene archivo). Lanza ValueError
    si el SRC del proyecto no es métrico.
    """
    proyecto = proyecto or QgsProject.instance()
    verificar_crs_metrico(proyecto.crs(), "del proyecto")
    capa = QgsVectorLayer("Point?field=nombre:string(50)", NOMBRE_CAPA_FUENTE, "memory")
    capa.setCrs(proyecto.crs())
    estilo_fuente(capa)
    proyecto.addMapLayer(capa)
    ruta = guardar_capas_de_dibujo([capa], proyecto)
    return capa, ruta


def colocar_fuente(capa, punto):
    """Deja en la capa un solo punto, el dado (en el SRC de la capa), y quita los que hubiera.

    Con la capa en edición el cambio se confirma en el acto, sin cerrar la edición.
    """
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(punto)))
    # Por nombre: si la capa ya se guardó en el GeoPackage, el primer campo es «fid».
    if capa.fields().indexOf("nombre") >= 0:
        entidad["nombre"] = NOMBRE_CAPA_FUENTE
    anteriores = [e.id() for e in capa.getFeatures()]
    if capa.isEditable():
        capa.deleteFeatures(anteriores)
        capa.addFeature(entidad)
        if not capa.commitChanges(False):
            raise OSError(f"No se pudo guardar la fuente en «{capa.name()}»: {'; '.join(capa.commitErrors())}")
    else:
        capa.dataProvider().deleteFeatures(anteriores)
        capa.dataProvider().addFeatures([entidad])
        capa.updateExtents()
    capa.triggerRepaint()


def geometrias_de_iman(crs_mapa, proyecto=None):
    """Tuberías de la red y válvulas (en el SRC del mapa): permiten fijar la fuente sobre un extremo existente."""
    proyecto = proyecto or QgsProject.instance()
    geometrias = []
    for capa in proyecto.mapLayers().values():
        if (isinstance(capa, QgsVectorLayer) and capa.name() == NOMBRE_CAPA_RED
                and capa.geometryType() == Qgis.GeometryType.Line):
            geometrias += [geometria_en(capa, e, crs_mapa) for e in capa.getFeatures()]
    geometrias += [QgsGeometry.fromPointXY(v.punto) for v in leer_valvulas(capas_de_valvulas(proyecto), crs_mapa)]
    return [g for g in geometrias if not g.isEmpty()]
