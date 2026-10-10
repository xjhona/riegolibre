"""Trazado automático en el mapa: del polígono del terreno a las subunidades con sus laterales.

El motor (`nucleo.trazado`) trabaja con listas de puntos; aquí se convierten las
geometrías de QGIS, se estima la pendiente con el DEM, se calcula el alcance hidráulico
de los laterales y se crean las capas editables del trazado.
"""

import math
from typing import Callable, List, Optional, Tuple

from qgis.core import (Qgis, QgsFeature, QgsFillSymbol, QgsGeometry, QgsMarkerSymbol,
                       QgsPointXY, QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor

from ..nucleo import longitud_maxima
from ..nucleo.trazado import Orientacion, orientaciones_candidatas
from .perfil_terreno import MuestreadorDem
from .subunidad_mapa import PROPIEDAD, LateralMapa

PROPIEDAD_TRAZADO = "trazado"
# Parte de la variación de caudal admisible que se reserva para los laterales; el resto es del
# portalateral. Es la regla práctica corriente (55 % laterales, 45 % portalateral).
REPARTO_VARIACION_LATERAL = 0.55
PENDIENTE_MINIMA_CONTORNO = 0.003  # por debajo, el terreno se considera plano


# ------------------------------------------------------------- geometrías


def anillos_de_geometria(geometria) -> List[List[Tuple[float, float]]]:
    """Contornos (exterior y huecos) de un polígono o multipolígono, sin repetir el primer punto."""
    if geometria.type() != Qgis.GeometryType.Polygon:
        raise ValueError("El terreno debe ser un polígono.")
    partes = geometria.asMultiPolygon() if geometria.isMultipart() else [geometria.asPolygon()]
    anillos = []
    for poligono in partes:
        for anillo in poligono:
            puntos = [(p.x(), p.y()) for p in anillo]
            if len(puntos) > 1 and puntos[0] == puntos[-1]:
                puntos.pop()
            if len(puntos) >= 3:
                anillos.append(puntos)
    if not anillos:
        raise ValueError("El polígono del terreno está vacío.")
    return anillos


def punto_de_entidad(capa, crs):
    """Primer punto de la capa (o de la selección), en el SRC dado."""
    from .subunidad_mapa import geometria_en
    entidades = capa.selectedFeatures() or list(capa.getFeatures())
    if not entidades:
        raise ValueError(f"La capa «{capa.name()}» no tiene entidades.")
    geometria = geometria_en(capa, entidades[0], crs)
    punto = geometria.centroid().asPoint() if geometria.type() != Qgis.GeometryType.Point else geometria.asPoint()
    return punto.x(), punto.y()


# ----------------------------------------------------------- terreno y DEM


def gradiente_del_terreno(geometria, capa_dem, crs, lado_rejilla=25) -> Optional[Tuple[float, float]]:
    """Pendiente media del terreno como gradiente (dz/dx, dz/dy) en m/m, ajustando un plano al DEM.

    Devuelve None si el DEM no cubre el terreno.
    """
    muestreador = MuestreadorDem(capa_dem, crs)
    caja = geometria.boundingBox()
    puntos = []
    for i in range(lado_rejilla):
        for j in range(lado_rejilla):
            p = QgsPointXY(caja.xMinimum() + caja.width() * (i + 0.5) / lado_rejilla,
                           caja.yMinimum() + caja.height() * (j + 0.5) / lado_rejilla)
            if not geometria.contains(QgsGeometry.fromPointXY(p)):
                continue
            z = muestreador.cota(p)
            if z is not None:
                puntos.append((p.x(), p.y(), z))
    if len(puntos) < 6:
        return None
    n = len(puntos)
    mx, my, mz = (sum(p[k] for p in puntos) / n for k in range(3))
    sxx = sum((p[0] - mx) ** 2 for p in puntos)
    syy = sum((p[1] - my) ** 2 for p in puntos)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in puntos)
    sxz = sum((p[0] - mx) * (p[2] - mz) for p in puntos)
    syz = sum((p[1] - my) * (p[2] - mz) for p in puntos)
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-9:
        return None
    return (sxz * syy - syz * sxy) / det, (syz * sxx - sxz * sxy) / det


def pendiente_a_lo_largo(gradiente, angulo_deg):
    """Pendiente (m/m, valor absoluto) del terreno en la dirección dada (antihoraria desde el eje x)."""
    if gradiente is None:
        return 0.0
    a = math.radians(angulo_deg)
    return abs(gradiente[0] * math.cos(a) + gradiente[1] * math.sin(a))


def alcance_hidraulico(tuberia, emisor, espaciamiento_m, primer_emisor_m, variacion_caudal_max, metodo="darcy",
                       presion_entrada_max_m=None) -> Callable[[float], float]:
    """Función pendiente → longitud máxima de un lateral que cumple la variación de caudal.

    A los laterales se les reserva `REPARTO_VARIACION_LATERAL` de la variación admisible
    de la subunidad. Los resultados se guardan por pendiente (con paso de 0.5 %).
    """
    memoria = {}

    def alcance(pendiente):
        clave = round(pendiente / 0.005)
        if clave not in memoria:
            largo, _ = longitud_maxima(
                tuberia, emisor, espaciamiento_m, pendiente=clave * 0.005,
                distancia_primer_emisor_m=primer_emisor_m,
                variacion_caudal_max=variacion_caudal_max * REPARTO_VARIACION_LATERAL,
                presion_entrada_max_m=presion_entrada_max_m, metodo=metodo)
            memoria[clave] = largo
        return memoria[clave]

    return alcance


def construir_orientaciones(anillos, gradiente, alcance: Callable[[float], float], paso_deg=15.0,
                            usar_curvas_de_nivel=True) -> List[Orientacion]:
    """Orientaciones a probar, con el alcance hidráulico de los laterales en cada una.

    Con un DEM se añade la dirección de las curvas de nivel (laterales a nivel).
    Una orientación en la que ni el lateral más corto cumple se descarta.
    """
    angulos = orientaciones_candidatas(anillos, paso_deg)
    if usar_curvas_de_nivel and gradiente is not None and math.hypot(*gradiente) >= PENDIENTE_MINIMA_CONTORNO:
        nivel = (math.degrees(math.atan2(gradiente[1], gradiente[0])) + 90.0) % 180.0
        if all(min(abs(nivel - a) % 180, 180 - abs(nivel - a) % 180) > 1.0 for a in angulos):
            angulos.append(nivel)
    orientaciones = []
    for angulo in angulos:
        pendiente = pendiente_a_lo_largo(gradiente, angulo)
        largo = alcance(pendiente)
        if largo > 0:
            orientaciones.append(Orientacion(angulo, largo, pendiente))
    if not orientaciones:
        raise ValueError(
            "Con estos laterales y emisores, ni un lateral corto cumple la variación de caudal "
            "admisible. Pruebe otro emisor, un diámetro de lateral mayor o una variación mayor.")
    return orientaciones


def funcion_caudal(emisor, espaciamiento_m, primer_emisor_m) -> Callable[[float], float]:
    """Caudal (L/h) de un lateral según su longitud."""
    def caudal(longitud_m):
        if longitud_m < primer_emisor_m:
            return 0.0
        n = int((longitud_m - primer_emisor_m) / espaciamiento_m + 1e-9) + 1
        return n * emisor.caudal_nominal_lh
    return caudal


# ------------------------------------------------------------------ capas


def _punto(p):
    return QgsPointXY(p[0], p[1])


def bloque_de_subunidad(subunidad, separacion_m) -> QgsGeometry:
    """Terreno que riega una subunidad: la franja de `separacion_m` alrededor de cada lateral."""
    medio = separacion_m / 2 * 1.0005  # un poco más ancho para que las franjas vecinas se fundan
    franjas = [QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)]).buffer(
        medio, 1, Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 2.0) for lat in subunidad.laterales]
    return QgsGeometry.unaryUnion(franjas)


def _capa(tipo, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, PROPIEDAD_TRAZADO)
    return capa


def capas_trazado(trazado, crs, nombre, con_bloques=True):
    """Capas del trazado: laterales, portalaterales y bloques (cada entidad lleva su número de subunidad).

    Devuelve (laterales, portalaterales, bloques o None, {número de subunidad: [LateralMapa]},
    {número de subunidad: geometría del portalateral}, {número de subunidad: geometría del bloque}).
    """
    laterales = _capa(
        "LineString", "field=subunidad:integer&field=lado:string(1)&field=conexion:integer"
        "&field=dist_porta:double&field=longitud:double&index=yes", f"Laterales · {nombre}", crs)
    portalaterales = _capa(
        "LineString", "field=subunidad:integer&field=longitud:double&field=laterales:integer"
        "&field=caudal_lh:double", f"Portalaterales · {nombre}", crs)
    bloques = _capa("Polygon", "field=subunidad:integer&field=area_m2:double&field=laterales:integer",
                    f"Bloques · {nombre}", crs) if con_bloques else None

    entidades_lat, por_subunidad, entidades_porta, entidades_bloque = [], [], [], []
    geometrias_porta, geometrias_bloque = {}, {}
    for s in trazado.subunidades:
        for lat in s.laterales:
            entidad = QgsFeature(laterales.fields())
            geometria = QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)])
            entidad.setGeometry(geometria)
            entidad.setAttributes([s.numero, lat.lado, lat.conexion, round(lat.distancia_m, 3),
                                   round(lat.longitud_m, 3)])
            entidades_lat.append(entidad)
            por_subunidad.append((s.numero, geometria, lat))
        geometria = QgsGeometry.fromPolylineXY([_punto(s.portalateral[0]), _punto(s.portalateral[1])])
        geometrias_porta[s.numero] = geometria
        entidad = QgsFeature(portalaterales.fields())
        entidad.setGeometry(geometria)
        entidad.setAttributes([s.numero, round(s.longitud_portalateral_m, 2), len(s.laterales),
                               round(s.caudal, 1)])
        entidades_porta.append(entidad)
        if bloques is not None:
            bloque = bloque_de_subunidad(s, trazado.separacion_m)
            geometrias_bloque[s.numero] = bloque
            entidad = QgsFeature(bloques.fields())
            entidad.setGeometry(bloque)
            entidad.setAttributes([s.numero, round(bloque.area(), 1), len(s.laterales)])
            entidades_bloque.append(entidad)

    _, agregadas = laterales.dataProvider().addFeatures(entidades_lat)
    portalaterales.dataProvider().addFeatures(entidades_porta)
    laterales_de = {s.numero: [] for s in trazado.subunidades}
    for (numero, geometria, lat), entidad in zip(por_subunidad, agregadas):
        laterales_de[numero].append(LateralMapa(entidad.id(), geometria, lat.distancia_m, lat.longitud_m))
    capas = [laterales, portalaterales]
    if bloques is not None:
        bloques.dataProvider().addFeatures(entidades_bloque)
        capas.append(bloques)
    for capa in capas:
        capa.updateExtents()

    simbolo = QgsSymbol.defaultSymbol(laterales.geometryType())
    simbolo.setColor(QColor("#3d7a3a"))
    simbolo.setWidth(0.4)
    laterales.setRenderer(QgsSingleSymbolRenderer(simbolo))
    simbolo = QgsSymbol.defaultSymbol(portalaterales.geometryType())
    simbolo.setColor(QColor("#1565c0"))
    simbolo.setWidth(1.6)
    portalaterales.setRenderer(QgsSingleSymbolRenderer(simbolo))
    if bloques is not None:
        bloques.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
            {"color": "80,170,80,40", "outline_color": "40,120,40", "outline_width": "0.5"})))
    return (laterales, portalaterales, bloques if con_bloques else None, laterales_de, geometrias_porta,
            geometrias_bloque)


def capa_emisores(trazado, crs, nombre, espaciamiento_m, primer_emisor_m):
    """Un punto por emisor, a lo largo de cada lateral del trazado."""
    capa = _capa("Point", "field=subunidad:integer&field=conexion:integer", f"Emisores · {nombre}", crs)
    entidades = []
    for s in trazado.subunidades:
        for lat in s.laterales:
            geometria = QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)])
            distancia = primer_emisor_m
            while distancia <= lat.longitud_m + 1e-9:
                entidad = QgsFeature(capa.fields())
                entidad.setGeometry(geometria.interpolate(min(distancia, lat.longitud_m)))
                entidad.setAttributes([s.numero, lat.conexion])
                entidades.append(entidad)
                distancia += espaciamiento_m
    capa.dataProvider().addFeatures(entidades)
    capa.updateExtents()
    capa.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#0277bd", "size": "0.6", "outline_style": "no"})))
    return capa


def vista_previa(trazado, crs, nombre_grupo):
    """Muestra el trazado (sin bloques) en un grupo temporal que reemplaza al anterior."""
    from .subunidad_mapa import reemplazar_grupo
    laterales, portalaterales, *_ = capas_trazado(trazado, crs, "vista previa", con_bloques=False)
    return reemplazar_grupo(nombre_grupo, [portalaterales, laterales])


def cantidad_de_emisores(trazado, espaciamiento_m, primer_emisor_m):
    contar = funcion_caudal(_UnEmisor, espaciamiento_m, primer_emisor_m)
    return int(round(sum(contar(lat.longitud_m) for s in trazado.subunidades for lat in s.laterales)))


class _UnEmisor:
    caudal_nominal_lh = 1.0  # para contar emisores con `funcion_caudal`
