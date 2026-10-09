"""Extracción del perfil del terreno a lo largo de una línea, a partir de un DEM."""

import math

from qgis.core import (Qgis, QgsCoordinateTransform, QgsDistanceArea, QgsGeometry,
                       QgsPointXY, QgsProject, QgsUnitTypes)


def entidad_unica(capa):
    """Devuelve la entidad a usar: la única seleccionada, o la única de la capa."""
    seleccion = capa.selectedFeatures()
    if len(seleccion) == 1:
        return seleccion[0]
    if not seleccion and capa.featureCount() == 1:
        return next(capa.getFeatures())
    raise ValueError(
        f"Seleccione una sola entidad en la capa «{capa.name()}» "
        f"(hay {len(seleccion)} seleccionadas de {capa.featureCount()}).")


def linea_simple(geometria):
    """Convierte una multilínea de una sola parte en línea simple."""
    if geometria.isMultipart():
        partes = geometria.asMultiPolyline()
        if len(partes) != 1:
            raise ValueError("La línea tiene varias partes; use una línea simple.")
        return QgsGeometry.fromPolylineXY(partes[0])
    return QgsGeometry(geometria)


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


class MuestreadorDem:
    """Lee cotas de un DEM en puntos dados en otro sistema de coordenadas."""

    def __init__(self, capa_dem, crs_origen, banda=1):
        self.capa = capa_dem
        self.banda = banda
        self.proveedor = capa_dem.dataProvider()
        self.transformacion = QgsCoordinateTransform(crs_origen, capa_dem.crs(), QgsProject.instance())

    def cota(self, punto):
        valor, ok = self.proveedor.sample(self.transformacion.transform(QgsPointXY(punto)), self.banda)
        if not ok or valor is None or math.isnan(valor):
            return None
        return float(valor)


def perfil_de_geometria(geometria, crs, muestreador, paso_m=1.0):
    """Perfil [(distancia_m, cota_m), ...] desde el primer vértice de la línea.

    Devuelve (longitud_m, perfil). Lanza ValueError si el DEM no cubre la línea.
    """
    geometria = linea_simple(geometria)
    longitud_m = longitud_en_metros(geometria, crs)
    if longitud_m <= 0:
        raise ValueError("La línea tiene longitud cero.")
    longitud_crs = geometria.length()
    unidades_por_metro = longitud_crs / longitud_m
    n = max(2, int(math.ceil(longitud_m / paso_m)) + 1)
    perfil = []
    for i in range(n):
        distancia = longitud_m * i / (n - 1)
        # min(): el redondeo no debe pedir un punto más allá del final de la línea.
        punto = geometria.interpolate(min(distancia * unidades_por_metro, longitud_crs)).asPoint()
        cota = muestreador.cota(punto)
        if cota is None:
            raise ValueError(
                f"El DEM «{muestreador.capa.name()}» no tiene datos a {distancia:.1f} m "
                "del inicio de la línea.")
        perfil.append((distancia, cota))
    return longitud_m, perfil


def extraer_perfil(capa_linea, entidad, capa_dem, paso_m=1.0, banda=1):
    """Muestrea el DEM a lo largo de una entidad de línea.

    El primer vértice de la línea se toma como la entrada (punto de alimentación).
    Devuelve (longitud_m, [(distancia_m, cota_m), ...]).
    """
    muestreador = MuestreadorDem(capa_dem, capa_linea.crs(), banda)
    return perfil_de_geometria(entidad.geometry(), capa_linea.crs(), muestreador, paso_m)
