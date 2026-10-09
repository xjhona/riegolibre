"""Red principal dibujada en el mapa: topología, válvulas, cotas y capas de resultado.

Las tuberías se dibujan como líneas sin necesidad de cortarlas en las uniones:
los extremos de cada línea, la fuente y las válvulas se convierten en nodos, y
cada línea se divide en tramos allí donde la toca un nodo (uniones en T).
"""

from dataclasses import dataclass
from typing import Dict, List

from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsFeature, QgsGeometry,
                       QgsMarkerSymbol, QgsProject, QgsRendererCategory,
                       QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor

from ..nucleo import Red, TramoRed, Valvula
from .perfil_terreno import linea_simple, perfil_de_geometria
from .subunidad_mapa import PROPIEDAD, geometria_en

CAMPOS_VALVULA = ("presion", "caudal_lh")
PREFIJO_VALVULA = "Válvula · "


@dataclass
class ValvulaMapa:
    id: str
    punto: object  # QgsPointXY en el SRC de la red
    caudal_lh: float
    presion_m: float
    turno: int = 1


def capas_de_valvulas(proyecto=None):
    """Capas de puntos del proyecto con los campos de una válvula (presion, caudal_lh)."""
    proyecto = proyecto or QgsProject.instance()
    capas = []
    for capa in proyecto.mapLayers().values():
        if (isinstance(capa, QgsVectorLayer) and capa.geometryType() == Qgis.GeometryType.Point
                and all(capa.fields().indexOf(c) >= 0 for c in CAMPOS_VALVULA)):
            capas.append(capa)
    return sorted(capas, key=lambda c: c.name())


def leer_valvulas(capas, crs):
    """Lee todas las válvulas de las capas dadas (transformadas al SRC de la red)."""
    valvulas = []
    for capa in capas:
        base = capa.name()
        if base.startswith(PREFIJO_VALVULA):
            base = base[len(PREFIJO_VALVULA):]
        entidades = list(capa.getFeatures())
        for entidad in entidades:
            if entidad["presion"] is None or entidad["caudal_lh"] is None:
                continue
            nombre = base if len(entidades) == 1 else f"{base} #{entidad.id()}"
            punto = geometria_en(capa, entidad, crs).asPoint()
            valvulas.append(ValvulaMapa(nombre, punto, float(entidad["caudal_lh"]), float(entidad["presion"])))
    return valvulas


@dataclass
class RedMapa:
    red: Red
    geometrias: Dict[str, QgsGeometry]  # tramo -> geometría
    puntos: Dict[str, object]  # nodo -> QgsPointXY
    sin_dem: bool


def construir_red(capa_tuberias, punto_fuente, valvulas: List[ValvulaMapa], crs, muestreador=None,
                  tolerancia_m=0.5, paso_perfil_m=5.0, perdida_valvula_m=0.0):
    """Construye la red (nodos, tramos con perfil y válvulas) a partir del mapa."""
    lineas = []
    for entidad in capa_tuberias.getFeatures():
        geometria = geometria_en(capa_tuberias, entidad, crs)
        if geometria.isEmpty():
            continue
        try:
            lineas.append((entidad.id(), linea_simple(geometria)))
        except ValueError:
            raise ValueError(f"La tubería {entidad.id()} tiene varias partes; sepárelas.") from None
    if not lineas:
        raise ValueError(f"La capa «{capa_tuberias.name()}» no tiene tuberías.")

    puntos: List[object] = []

    def nodo_de(punto):
        for i, existente in enumerate(puntos):
            if existente.distance(punto) <= tolerancia_m:
                return f"N{i}"
        puntos.append(punto)
        return f"N{len(puntos) - 1}"

    fuente = nodo_de(punto_fuente)
    nodos_valvula = [nodo_de(v.punto) for v in valvulas]
    for _, geometria in lineas:
        vertices = geometria.asPolyline()
        nodo_de(vertices[0])
        nodo_de(vertices[-1])

    tramos, geometrias = [], {}
    for id_linea, geometria in lineas:
        posiciones = set()
        for i, punto in enumerate(puntos):
            punto_geom = QgsGeometry.fromPointXY(punto)
            if geometria.distance(punto_geom) <= tolerancia_m:
                posiciones.add((round(geometria.lineLocatePoint(punto_geom), 6), f"N{i}"))
        ordenadas = sorted(posiciones)
        for k, ((a, nodo_a), (b, nodo_b)) in enumerate(zip(ordenadas, ordenadas[1:])):
            if b - a <= 1e-6 or nodo_a == nodo_b:
                continue
            tramo_geom = QgsGeometry(geometria.constGet().curveSubstring(a, b))
            id_tramo = f"{id_linea}.{k + 1}"
            perfil = None
            if muestreador is not None:
                _, perfil = perfil_de_geometria(tramo_geom, crs, muestreador, paso_perfil_m)
            tramos.append(TramoRed(id_tramo, nodo_a, nodo_b, b - a, perfil))
            geometrias[id_tramo] = tramo_geom

    cotas = {}
    for i, punto in enumerate(puntos):
        cota = muestreador.cota(punto) if muestreador is not None else 0.0
        if cota is None:
            raise ValueError("El DEM no cubre toda la red (falta la cota de un nodo).")
        cotas[f"N{i}"] = cota

    lista = [Valvula(v.id, nodo, v.caudal_lh, v.presion_m, v.turno, perdida_valvula_m)
             for v, nodo in zip(valvulas, nodos_valvula)]
    try:
        red = Red(cotas, tramos, lista, fuente)
    except ValueError as error:
        if "no están conectadas" in str(error):
            raise ValueError(f"{error}. Compruebe que la tubería pasa a menos de {tolerancia_m:g} m "
                             "de cada válvula y de la fuente.") from None
        raise
    return RedMapa(red, geometrias, {f"N{i}": p for i, p in enumerate(puntos)}, muestreador is None)


# --------------------------------------------------------------- resultados


def _capa(tipo, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "resultado")
    return capa


def capas_resultado(red_mapa, resultado, bomba, crs):
    """Capas de tramos (por tubería), válvulas (presión disponible) y bomba."""
    red = red_mapa.red
    tramos = _capa(
        "LineString",
        "field=tramo:string(20)&field=tuberia:string(80)&field=dn_mm:double&field=pn_m:double"
        "&field=longitud:double&field=caudal_lh:double&field=velocidad:double&field=j_m100:double"
        "&field=p_min:double&field=p_max:double&field=observ:string(200)",
        "Red principal · tuberías", crs)
    entidades = []
    for t in red.tramos:
        tuberia = resultado.asignacion[t.id]
        q, p_min, p_max = resultado.peor_tramo(t.id)
        peores = [r.tramos[t.id] for r in resultado.turnos]
        entidad = QgsFeature(tramos.fields())
        entidad.setGeometry(red_mapa.geometrias[t.id])
        entidad.setAttributes([
            t.id, tuberia.nombre, tuberia.diametro_nominal_mm, tuberia.presion_nominal_m,
            round(t.longitud_m, 2), round(q, 1), round(max(r.velocidad_ms for r in peores), 3),
            round(max(r.perdida_unitaria_m100 for r in peores), 3), round(p_min, 2), round(p_max, 2),
            resultado.observaciones(t.id)])
        entidades.append(entidad)
    tramos.dataProvider().addFeatures(entidades)
    _estilo_por_tuberia(tramos, resultado)

    valvulas = _capa(
        "Point",
        "field=valvula:string(80)&field=turno:integer&field=caudal_lh:double&field=p_requerida:double"
        "&field=p_disponible:double&field=exceso:double",
        "Red principal · válvulas", crs)
    entidades = []
    for v in red.valvulas:
        r = resultado.turno(v.turno)
        entidad = QgsFeature(valvulas.fields())
        entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[v.nodo]))
        entidad.setAttributes([v.id, v.turno, round(v.caudal_lh, 1), round(v.presion_requerida_m, 2),
                               round(r.presion_disponible[v.id], 2), round(r.exceso(v), 2)])
        entidades.append(entidad)
    valvulas.dataProvider().addFeatures(entidades)
    valvulas.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "3", "outline_color": "#ffffff"})))

    capa_bomba = _capa(
        "Point",
        "field=turno:integer&field=caudal_ls:double&field=cdt_m:double&field=potencia_kw:double"
        "&field=potencia_hp:double",
        "Red principal · bomba", crs)
    entidad = QgsFeature(capa_bomba.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[red.fuente]))
    entidad.setAttributes([bomba.turno, round(bomba.caudal_ls, 3), round(bomba.carga_dinamica_total_m, 2),
                           round(bomba.potencia_kw, 2), round(bomba.potencia_hp, 2)])
    capa_bomba.dataProvider().addFeatures([entidad])
    capa_bomba.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": "#1565c0", "size": "5", "outline_color": "#ffffff"})))

    for capa in (tramos, valvulas, capa_bomba):
        capa.updateExtents()
    return [capa_bomba, valvulas, tramos]


PALETA = ["#1565c0", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f", "#ad1457", "#558b2f", "#4e342e"]


def _estilo_por_tuberia(capa, resultado):
    """Una categoría por tubería usada; el grosor crece con el diámetro."""
    usadas = sorted({t.nombre: t for t in resultado.asignacion.values()}.values(),
                    key=lambda t: (t.diametro_nominal_mm or t.diametro_interior_mm, t.presion_nominal_m or 0))
    categorias = []
    for i, tuberia in enumerate(usadas):
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        simbolo.setColor(QColor(PALETA[i % len(PALETA)]))
        simbolo.setWidth(0.6 + 0.012 * (tuberia.diametro_nominal_mm or tuberia.diametro_interior_mm))
        categorias.append(QgsRendererCategory(tuberia.nombre, simbolo, tuberia.nombre))
    capa.setRenderer(QgsCategorizedSymbolRenderer("tuberia", categorias))
