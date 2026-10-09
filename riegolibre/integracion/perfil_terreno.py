"""Extracción del perfil del terreno a lo largo de una línea, a partir de un DEM."""

import math

from qgis.core import (Qgis, QgsCoordinateTransform, QgsDistanceArea, QgsGeometry,
                       QgsPointXY, QgsProject, QgsUnitTypes)


def entidad_unica(capa):
    """Devuelve la línea a usar: la única seleccionada, o la única de la capa."""
    seleccion = capa.selectedFeatures()
    if len(seleccion) == 1:
        return seleccion[0]
    if not seleccion and capa.featureCount() == 1:
        return next(capa.getFeatures())
    raise ValueError(
        f"Seleccione una sola línea en la capa «{capa.name()}» "
        f"(hay {len(seleccion)} seleccionadas).")


def _linea_simple(geometria):
    if geometria.isMultipart():
        partes = geometria.asMultiPolyline()
        if len(partes) != 1:
            raise ValueError("La línea seleccionada tiene varias partes; use una línea simple.")
        return QgsGeometry.fromPolylineXY(partes[0])
    return geometria


def medidor_distancias(crs):
    proyecto = QgsProject.instance()
    medidor = QgsDistanceArea()
    medidor.setSourceCrs(crs, proyecto.transformContext())
    elipsoide = proyecto.ellipsoid()
    if not elipsoide or elipsoide == "NONE":
        elipsoide = "EPSG:7030" if crs.isGeographic() else "NONE"
    medidor.setEllipsoid(elipsoide)
    return medidor


def longitud_en_metros(geometria, crs):
    medidor = medidor_distancias(crs)
    longitud = medidor.measureLength(geometria)
    factor = QgsUnitTypes.fromUnitToUnitFactor(medidor.lengthUnits(), Qgis.DistanceUnit.Meters)
    return longitud * factor


def extraer_perfil(capa_linea, entidad, capa_dem, paso_m=1.0, banda=1):
    """Muestrea el DEM a lo largo de la línea.

    El primer vértice de la línea se toma como la entrada (punto de alimentación).
    Devuelve (longitud_m, [(distancia_m, cota_m), ...]).
    """
    geometria = _linea_simple(entidad.geometry())
    longitud_m = longitud_en_metros(geometria, capa_linea.crs())
    if longitud_m <= 0:
        raise ValueError("La línea tiene longitud cero.")
    unidades_por_metro = geometria.length() / longitud_m

    transformacion = QgsCoordinateTransform(capa_linea.crs(), capa_dem.crs(), QgsProject.instance())
    proveedor = capa_dem.dataProvider()

    n = max(2, int(math.ceil(longitud_m / paso_m)) + 1)
    perfil = []
    for i in range(n):
        distancia = longitud_m * i / (n - 1)
        punto = geometria.interpolate(distancia * unidades_por_metro).asPoint()
        punto_dem = transformacion.transform(QgsPointXY(punto))
        valor, ok = proveedor.sample(punto_dem, banda)
        if not ok or valor is None or math.isnan(valor):
            raise ValueError(
                f"El DEM «{capa_dem.name()}» no tiene datos a {distancia:.1f} m del inicio de la línea.")
        perfil.append((distancia, float(valor)))
    return longitud_m, perfil
