"""Subunidad dibujada en el mapa: generación de laterales, modelo hidráulico y capas de resultado.

Todas las geometrías se trabajan en el sistema de coordenadas del portalateral,
que debe ser proyectado y en metros (por ejemplo UTM).
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from qgis.core import (Qgis, QgsClassificationEqualInterval, QgsCoordinateTransform,
                       QgsFeature, QgsGeometry, QgsGraduatedSymbolRenderer,
                       QgsMarkerSymbol, QgsPointXY, QgsProject,
                       QgsSingleSymbolRenderer, QgsStyle, QgsSymbol, QgsVectorLayer)

from qgis.PyQt.QtGui import QColor

from ..nucleo import ConexionLateral
from .perfil_terreno import MuestreadorDem, linea_simple, perfil_de_geometria

LADO_A, LADO_B = "A", "B"  # A: a la izquierda del portalateral (según su sentido de dibujo)
LADOS_AMBOS = (LADO_A, LADO_B)
TOLERANCIA_M = 0.05
PROPIEDAD = "riegolibre/tipo"


def verificar_crs_metrico(crs, nombre_capa):
    if not crs.isValid() or crs.isGeographic() or crs.mapUnits() != Qgis.DistanceUnit.Meters:
        raise ValueError(
            f"La capa «{nombre_capa}» debe estar en un sistema de coordenadas proyectado en metros "
            f"(por ejemplo UTM); ahora usa {crs.authid() or crs.description()}.")


def geometria_en(capa, entidad, crs_destino):
    geometria = QgsGeometry(entidad.geometry())
    if capa.crs() != crs_destino:
        geometria.transform(QgsCoordinateTransform(capa.crs(), crs_destino, QgsProject.instance()))
    return geometria


# ------------------------------------------------------------- generación


@dataclass
class LateralTrazado:
    geometria: QgsGeometry  # desde el portalateral hacia el final del lateral
    lado: str
    conexion: int  # número de posición a lo largo del portalateral
    distancia_m: float  # posición de la conexión a lo largo del portalateral
    longitud_m: float


def _direccion(portalateral, distancia, azimut_grados):
    """Vector unitario hacia el lado A: izquierda del portalateral, o el azimut fijo dado."""
    if azimut_grados is not None:
        a = math.radians(azimut_grados)
        return math.sin(a), math.cos(a)
    a = portalateral.interpolateAngle(distancia)  # radianes, horario desde el norte
    return -math.cos(a), math.sin(a)


def _alcance_dentro(poligono, punto, dx, dy, alcance):
    """Longitud del tramo del rayo punto→(dx, dy) que queda dentro del polígono desde el punto."""
    rayo = QgsGeometry.fromPolylineXY(
        [punto, QgsPointXY(punto.x() + dx * alcance, punto.y() + dy * alcance)])
    interseccion = rayo.intersection(poligono)
    if interseccion.isEmpty():
        return 0.0
    for parte in interseccion.asGeometryCollection():
        if parte.type() != Qgis.GeometryType.Line:
            continue
        vertices = parte.asPolyline()
        if len(vertices) < 2:
            continue
        cerca, lejos = sorted((punto.distance(vertices[0]), punto.distance(vertices[-1])))
        if cerca <= TOLERANCIA_M:
            return lejos
    return 0.0


def generar_laterales(poligono, portalateral, separacion_m, distancia_primero_m=None, margen_m=0.0,
                      longitud_max_m=None, lados=LADOS_AMBOS, azimut_grados=None,
                      longitud_min_m=1.0) -> List[LateralTrazado]:
    """Traza laterales cada `separacion_m` a lo largo del portalateral, recortados por el bloque.

    - Los laterales salen perpendiculares al portalateral (o con un azimut fijo) hacia
      uno o ambos lados y llegan hasta el borde del bloque menos `margen_m`.
    - Solo se trazan en los puntos del portalateral que están dentro del bloque o en su borde.
    """
    portalateral = linea_simple(portalateral)
    longitud = portalateral.length()
    if separacion_m <= 0:
        raise ValueError("La separación entre laterales debe ser mayor que cero.")
    if distancia_primero_m is None:
        distancia_primero_m = separacion_m / 2
    caja = poligono.boundingBox()
    caja.combineExtentWith(portalateral.boundingBox())
    alcance = math.hypot(caja.width(), caja.height()) + 1.0

    laterales = []
    conexion = 0
    distancia = distancia_primero_m
    while distancia <= longitud + 1e-9:
        punto = portalateral.interpolate(min(distancia, longitud)).asPoint()
        if poligono.distance(QgsGeometry.fromPointXY(punto)) <= TOLERANCIA_M:
            ux, uy = _direccion(portalateral, distancia, azimut_grados)
            for lado in lados:
                signo = 1 if lado == LADO_A else -1
                largo = _alcance_dentro(poligono, punto, signo * ux, signo * uy, alcance) - margen_m
                if longitud_max_m:
                    largo = min(largo, longitud_max_m)
                if largo >= longitud_min_m:
                    fin = QgsPointXY(punto.x() + signo * ux * largo, punto.y() + signo * uy * largo)
                    laterales.append(LateralTrazado(QgsGeometry.fromPolylineXY([punto, fin]),
                                                    lado, conexion, distancia, largo))
        conexion += 1
        distancia = distancia_primero_m + conexion * separacion_m
    return laterales


def capa_laterales(laterales, crs, nombre):
    capa = QgsVectorLayer(
        "LineString?field=lado:string(1)&field=conexion:integer&field=dist_porta:double"
        "&field=longitud:double&index=yes", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "laterales")
    entidades = []
    for lat in laterales:
        entidad = QgsFeature(capa.fields())
        entidad.setGeometry(lat.geometria)
        entidad.setAttributes([lat.lado, lat.conexion, round(lat.distancia_m, 3), round(lat.longitud_m, 3)])
        entidades.append(entidad)
    capa.dataProvider().addFeatures(entidades)
    capa.updateExtents()
    simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
    simbolo.setColor(QColor("#3d7a3a"))
    capa.setRenderer(QgsSingleSymbolRenderer(simbolo))
    return capa


# ---------------------------------------------------------------- lectura


@dataclass
class LateralMapa:
    id_entidad: int
    geometria: QgsGeometry  # orientada desde el portalateral
    distancia_m: float  # posición de su conexión en el portalateral
    longitud_m: float


def leer_laterales(capa, portalateral, crs, tolerancia_m=1.0):
    """Lee los laterales de una capa (los seleccionados o todos) y los ubica en el portalateral.

    Cada lateral se orienta desde el extremo más cercano al portalateral. Devuelve
    (laterales, avisos); se descartan los que quedan a más de `tolerancia_m`.
    """
    entidades = capa.selectedFeatures() or list(capa.getFeatures())
    laterales, lejanos = [], 0
    for entidad in entidades:
        geometria = linea_simple(geometria_en(capa, entidad, crs))
        vertices = geometria.asPolyline()
        if len(vertices) < 2:
            continue
        d_inicio = portalateral.distance(QgsGeometry.fromPointXY(vertices[0]))
        d_fin = portalateral.distance(QgsGeometry.fromPointXY(vertices[-1]))
        if d_fin < d_inicio:
            vertices.reverse()
            geometria = QgsGeometry.fromPolylineXY(vertices)
            d_inicio = d_fin
        if d_inicio > tolerancia_m:
            lejanos += 1
            continue
        distancia = portalateral.lineLocatePoint(QgsGeometry.fromPointXY(vertices[0]))
        laterales.append(LateralMapa(entidad.id(), geometria, distancia, geometria.length()))
    avisos = []
    if lejanos:
        avisos.append(f"{lejanos} laterales no llegan al portalateral (a más de {tolerancia_m:g} m) "
                      "y no se calcularon.")
    if not laterales:
        raise ValueError(f"La capa «{capa.name()}» no tiene laterales conectados al portalateral.")
    return laterales, avisos


# ------------------------------------------------------------------ modelo


@dataclass
class ModeloMapa:
    conexiones: List[ConexionLateral]
    origen: List[List[LateralMapa]]  # mismo orden que conexiones[i].laterales
    perfil_portalateral: Optional[list]
    descartados: List[LateralMapa]


def construir_modelo(laterales_mapa, crear_lateral, portalateral, crs, capa_dem=None,
                     paso_perfil_m=1.0, tolerancia_conexion_m=0.05):
    """Agrupa los laterales por conexión y les asigna su perfil del terreno.

    crear_lateral(longitud_m, perfil) debe devolver un Lateral, o None si el lateral
    es demasiado corto. Los laterales iguales (misma longitud y terreno) comparten
    el mismo objeto para no repetir cálculos.
    """
    muestreador = MuestreadorDem(capa_dem, crs) if capa_dem is not None else None
    perfil_porta = None
    if muestreador is not None:
        _, perfil_porta = perfil_de_geometria(portalateral, crs, muestreador, paso_perfil_m)

    unicos = {}
    conexiones, origen, descartados = [], [], []
    for lat_mapa in sorted(laterales_mapa, key=lambda lat: lat.distancia_m):
        perfil = None
        if muestreador is not None:
            _, perfil = perfil_de_geometria(lat_mapa.geometria, crs, muestreador, paso_perfil_m)
        clave = (round(lat_mapa.longitud_m, 2),
                 tuple((round(d, 1), round(z - perfil[0][1], 2)) for d, z in perfil) if perfil else None)
        if clave not in unicos:
            unicos[clave] = crear_lateral(lat_mapa.longitud_m, perfil)
        lateral = unicos[clave]
        if lateral is None:
            descartados.append(lat_mapa)
            continue
        if conexiones and abs(conexiones[-1].distancia_m - lat_mapa.distancia_m) <= tolerancia_conexion_m:
            conexiones[-1].laterales.append(lateral)
            origen[-1].append(lat_mapa)
        else:
            conexiones.append(ConexionLateral(lat_mapa.distancia_m, [lateral]))
            origen.append([lat_mapa])
    if not conexiones:
        raise ValueError("Todos los laterales son más cortos que la distancia al primer emisor.")
    return ModeloMapa(conexiones, origen, perfil_porta, descartados)


def indices_por_rama(conexiones, distancia_entrada_m, sentido):
    """Índices de las conexiones de una rama, en el orden en que las recorre la rama."""
    if sentido > 0:
        return [i for i, c in enumerate(conexiones)
                if c.distancia_m > distancia_entrada_m or c.distancia_m == distancia_entrada_m]
    return [i for i, c in reversed(list(enumerate(conexiones))) if c.distancia_m < distancia_entrada_m]


# --------------------------------------------------------------- resultados


def _capa(tipo_geometria, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo_geometria}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "resultado")
    return capa


def capas_resultado(diseno, modelo, portalateral, distancia_entrada_m, crs, nombre):
    """Crea las capas de resultado: laterales, tramos del portalateral y válvula."""
    r = diseno.resultado
    tuberia = diseno.tuberia

    laterales = _capa(
        "LineString",
        "field=id_origen:integer&field=conexion:integer&field=dist_porta:double"
        "&field=longitud:double&field=emisores:integer&field=p_entrada:double&field=caudal_lh:double"
        "&field=p_min:double&field=p_max:double&field=q_min:double&field=q_max:double"
        "&field=var_caudal:double&field=fuera_rango:integer&field=tuberia:string(80)"
        "&field=emisor:string(80)",
        f"Laterales · {nombre}", crs)
    tramos = _capa(
        "LineString",
        "field=rama:string(20)&field=desde_m:double&field=hasta_m:double&field=caudal_lh:double"
        "&field=velocidad:double&field=p_inicio:double&field=p_fin:double&field=tuberia:string(80)",
        f"Portalateral · {nombre}", crs)
    valvula = _capa(
        "Point",
        "field=presion:double&field=caudal_lh:double&field=caudal_ls:double&field=tuberia:string(80)",
        f"Válvula · {nombre}", crs)

    entidades_lat, entidades_tramo = [], []
    for rama_r, rama in zip(r.ramas, diseno.subunidad.ramas):
        indices = indices_por_rama(modelo.conexiones, distancia_entrada_m, rama.sentido)
        nombre_rama = "única" if len(r.ramas) == 1 else ("hacia el final" if rama.sentido > 0 else "hacia el inicio")
        caudal_aguas_abajo = sum(rama_r.caudales_lh)
        anterior, presion_anterior = 0.0, r.presion_entrada_m
        for j, i in enumerate(indices):
            for lat_mapa, lateral, res in zip(modelo.origen[i], modelo.conexiones[i].laterales,
                                              rama_r.laterales[j]):
                entidad = QgsFeature(laterales.fields())
                entidad.setGeometry(lat_mapa.geometria)
                entidad.setAttributes([
                    lat_mapa.id_entidad, i, round(lat_mapa.distancia_m, 3), round(lat_mapa.longitud_m, 2),
                    res.numero_emisores, round(res.presion_entrada_m, 3), round(res.caudal_total_lh, 2),
                    round(res.presion_min_m, 3), round(res.presion_max_m, 3), round(res.caudal_min_lh, 4),
                    round(res.caudal_max_lh, 4), round(100 * res.variacion_caudal, 2),
                    res.emisores_fuera_de_rango, lateral.tuberia.nombre, lateral.emisor.nombre])
                entidades_lat.append(entidad)

            actual = rama_r.distancias_m[j]
            desde = distancia_entrada_m + rama.sentido * anterior
            hasta = distancia_entrada_m + rama.sentido * actual
            if abs(hasta - desde) > 1e-6:
                tramo = QgsFeature(tramos.fields())
                tramo.setGeometry(QgsGeometry(portalateral.constGet().curveSubstring(min(desde, hasta),
                                                                                    max(desde, hasta))))
                tramo.setAttributes([
                    nombre_rama, round(desde, 2), round(hasta, 2), round(caudal_aguas_abajo, 1),
                    round(tuberia.velocidad(caudal_aguas_abajo / 3.6e6), 3), round(presion_anterior, 3),
                    round(rama_r.presiones_m[j], 3), tuberia.nombre])
                entidades_tramo.append(tramo)
            caudal_aguas_abajo -= rama_r.caudales_lh[j]
            anterior, presion_anterior = actual, rama_r.presiones_m[j]

    punto = QgsFeature(valvula.fields())
    punto.setGeometry(portalateral.interpolate(distancia_entrada_m))
    punto.setAttributes([round(r.presion_entrada_m, 3), round(r.caudal_total_lh, 1),
                         round(r.caudal_total_lh / 3600, 3), tuberia.nombre])

    for capa, entidades in ((laterales, entidades_lat), (tramos, entidades_tramo), (valvula, [punto])):
        capa.dataProvider().addFeatures(entidades)
        capa.updateExtents()

    _estilo_graduado(laterales, "p_min", ancho=0.6)
    _estilo_graduado(tramos, "p_fin", ancho=1.8)
    valvula.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "4", "outline_color": "#ffffff"})))
    return [valvula, tramos, laterales]


def _estilo_graduado(capa, campo, ancho, clases=5):
    simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
    simbolo.setWidth(ancho)
    renderizador = QgsGraduatedSymbolRenderer(campo)
    renderizador.setSourceSymbol(simbolo)
    renderizador.setClassificationMethod(QgsClassificationEqualInterval())
    rampa = QgsStyle.defaultStyle().colorRamp("RdYlGn")
    if rampa is not None:
        renderizador.setSourceColorRamp(rampa)
    renderizador.updateClasses(capa, clases)
    capa.setRenderer(renderizador)


def reemplazar_grupo(nombre_grupo, capas):
    """Coloca las capas en un grupo del proyecto, reemplazando el grupo anterior del mismo nombre."""
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    anterior = raiz.findGroup(nombre_grupo)
    if anterior is not None:
        for nodo in anterior.findLayers():
            proyecto.removeMapLayer(nodo.layerId())
        raiz.removeChildNode(anterior)
    grupo = raiz.insertGroup(0, nombre_grupo)
    for capa in capas:
        proyecto.addMapLayer(capa, False)
        grupo.addLayer(capa)
    return grupo
