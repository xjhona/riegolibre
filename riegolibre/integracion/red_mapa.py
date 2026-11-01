"""Red principal dibujada en el mapa: topología, válvulas, cotas y capas de resultado.

Las tuberías se dibujan como líneas sin necesidad de cortarlas en las uniones:
los extremos de cada línea, la fuente y las válvulas se convierten en nodos, y
cada línea se divide en tramos allí donde la toca un nodo (uniones en T).
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from qgis.core import (Qgis, QgsFeature, QgsField, QgsGeometry,
                       QgsMarkerSymbol, QgsPointXY, QgsProject,
                       QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from ..nucleo import Red, TramoRed, Valvula
from ..nucleo.tuberias import rotulo_corto
from .perfil_terreno import linea_simple, perfil_de_geometria
from .subunidad_mapa import PROPIEDAD, estilo_por_tuberia, geometria_en, rotular_tuberia

CAMPOS_VALVULA = ("presion", "caudal_lh")
PREFIJO_VALVULA = "Válvula · "


@dataclass
class ValvulaMapa:
    id: str
    punto: object  # QgsPointXY en el SRC de la red
    caudal_lh: float
    presion_m: float
    turno: int = 1
    elemento: Optional[object] = None  # ElementoHidraulico opcional


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
                  tolerancia_m=0.5, paso_perfil_m=5.0, perdida_valvula_m=0.0, elemento_valvula=None,
                  catalogo=()):
    """Construye la red (nodos, tramos con perfil y válvulas) a partir del mapa.

    Las líneas con el campo `tuberia` lleno fijan ese diámetro (se busca por nombre en el `catalogo`)
    en todos sus tramos; las demás lo elige el dimensionamiento.
    """
    por_nombre = {t.nombre: t for t in catalogo}
    hay_campo = capa_tuberias.fields().indexOf(CAMPO_TUBERIA) >= 0
    lineas = []
    for entidad in capa_tuberias.getFeatures():
        geometria = geometria_en(capa_tuberias, entidad, crs)
        if geometria.isEmpty():
            continue
        try:
            linea = linea_simple(geometria)
        except ValueError:
            raise ValueError(f"La tubería {entidad.id()} tiene varias partes; sepárelas.") from None
        nombre = entidad[CAMPO_TUBERIA] if hay_campo else None
        tuberia = None
        if isinstance(nombre, str) and nombre.strip():  # un campo vacío llega como NULL, que no es texto
            tuberia = por_nombre.get(nombre.strip())
            if tuberia is None:
                raise ValueError(f"La tubería {entidad.id()} usa «{nombre}», que no está en el catálogo de "
                                 "tuberías de la red principal. Cámbiele el diámetro o agréguela a la base "
                                 "de datos.")
        lineas.append((entidad.id(), linea, tuberia))
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
    for _, geometria, _ in lineas:
        vertices = geometria.asPolyline()
        nodo_de(vertices[0])
        nodo_de(vertices[-1])

    tramos, geometrias = [], {}
    for id_linea, geometria, tuberia in lineas:
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
            tramos.append(TramoRed(id_tramo, nodo_a, nodo_b, b - a, perfil, tuberia))
            geometrias[id_tramo] = tramo_geom

    cotas = {}
    for i, punto in enumerate(puntos):
        cota = muestreador.cota(punto) if muestreador is not None else 0.0
        if cota is None:
            raise ValueError("El DEM no cubre toda la red (falta la cota de un nodo).")
        cotas[f"N{i}"] = cota

    lista = [Valvula(v.id, nodo, v.caudal_lh, v.presion_m, v.turno, perdida_valvula_m,
                     v.elemento or elemento_valvula)
             for v, nodo in zip(valvulas, nodos_valvula)]
    try:
        red = Red(cotas, tramos, lista, fuente)
    except ValueError as error:
        if "no están conectadas" in str(error):
            raise ValueError(f"{error}. Compruebe que la tubería pasa a menos de {tolerancia_m:g} m "
                             "de cada válvula y de la fuente.") from None
        raise
    return RedMapa(red, geometrias, {f"N{i}": p for i, p in enumerate(puntos)}, muestreador is None)


# --------------------------------------------------- tubería matriz dibujada

NOMBRE_CAPA_RED = "Red principal"
CAMPO_TUBERIA = "tuberia"  # nombre de la tubería del catálogo; vacío = la elige el cálculo («Computer Selected»)
TEXTO_POR_DIMENSIONAR = "Por dimensionar"
NOMBRE_CAPA_BLOQUES = "Bloques"


def capas_de_bloques(proyecto=None):
    """Capas de polígonos «Bloques» del diseño: la dibujada a mano y las «Bloques · nombre» del trazado."""
    proyecto = proyecto or QgsProject.instance()
    capas = []
    for capa in proyecto.mapLayers().values():
        if (isinstance(capa, QgsVectorLayer) and capa.geometryType() == Qgis.GeometryType.Polygon
                and capa.customProperty(PROPIEDAD) in ("dibujo", "trazado")
                and (capa.name() == NOMBRE_CAPA_BLOQUES or capa.name().startswith(NOMBRE_CAPA_BLOQUES + " · "))):
            capas.append(capa)
    return sorted(capas, key=lambda c: c.name())


def asegurar_campo_tuberia(capa):
    """Agrega a la capa el campo de la tubería si no lo tiene (las capas dibujadas antes no lo traen)."""
    if capa.fields().indexOf(CAMPO_TUBERIA) < 0:
        capa.dataProvider().addAttributes([QgsField(CAMPO_TUBERIA, QMetaType.Type.QString)])
        capa.updateFields()


def estilo_red_dibujada(capa):
    """Línea azul con la tubería de cada tramo escrita encima («Por dimensionar» si la elige el cálculo)."""
    simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
    simbolo.setColor(QColor("#1565c0"))
    simbolo.setWidth(0.8)
    capa.setRenderer(QgsSingleSymbolRenderer(simbolo))
    rotular_tuberia(capa, f"coalesce(nullif(\"{CAMPO_TUBERIA}\", ''), '{TEXTO_POR_DIMENSIONAR}')", expresion=True)


def agregar_tuberia(capa, puntos, tuberia=None):
    """Agrega a la capa una tubería con los vértices dados (en el SRC de la capa) y el diámetro elegido.

    `tuberia`: una `Tuberia` del catálogo, o None si la elige el cálculo. Devuelve la entidad agregada.
    """
    asegurar_campo_tuberia(capa)
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(p) for p in puntos]))
    # Por nombre: si la capa ya se guardó en el GeoPackage, el primer campo es «fid».
    entidad[CAMPO_TUBERIA] = tuberia.nombre if tuberia is not None else None
    if capa.isEditable():  # con la edición activa va al búfer, para que el usuario pueda deshacer o descartar
        capa.addFeature(entidad)
    else:
        _, agregadas = capa.dataProvider().addFeatures([entidad])
        entidad = agregadas[0]
        capa.updateExtents()
    capa.triggerRepaint()
    return entidad


def cambiar_tuberia(capa, ids, tuberia=None):
    """Cambia el diámetro de las tuberías de la capa con los ids dados (None: lo elige el cálculo)."""
    asegurar_campo_tuberia(capa)
    indice = capa.fields().indexOf(CAMPO_TUBERIA)
    valor = tuberia.nombre if tuberia is not None else None
    if capa.isEditable():
        for id_entidad in ids:
            capa.changeAttributeValue(id_entidad, indice, valor)
    else:
        capa.dataProvider().changeAttributeValues({id_entidad: {indice: valor} for id_entidad in ids})
    capa.triggerRepaint()



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
        "&field=p_min:double&field=p_max:double&field=observ:string(200)"
        "&field=desnivel_m:double&field=turnos:string(4000)&field=rotulo:string(80)",
        "Red principal · tuberías", crs)
    entidades = []
    for t in red.tramos:
        tuberia = resultado.asignacion[t.id]
        q, p_min, p_max = resultado.peor_tramo(t.id)
        peores = [r.tramos[t.id] for r in resultado.turnos]
        entidad = QgsFeature(tramos.fields())
        entidad.setGeometry(_en_sentido_del_flujo(red_mapa.geometrias[t.id], red_mapa.puntos[t.desde]))
        por_turno = [[r.turno, round(r.tramos[t.id].presion_inicio_m, 2), round(r.tramos[t.id].presion_fin_m, 2),
                      round(r.tramos[t.id].perdida_m, 3), round(r.tramos[t.id].caudal_lh, 1),
                      round(r.tramos[t.id].velocidad_ms, 3)] for r in resultado.turnos]
        entidad.setAttributes([
            t.id, tuberia.nombre, tuberia.diametro_nominal_mm, tuberia.presion_nominal_m,
            round(t.longitud_m, 2), round(q, 1), round(max(r.velocidad_ms for r in peores), 3),
            round(max(r.perdida_unitaria_m100 for r in peores), 3), round(p_min, 2), round(p_max, 2),
            resultado.observaciones(t.id), round(red.cotas[t.hasta] - red.cotas[t.desde], 3),
            json.dumps(por_turno, separators=(",", ":")),
            f"{t.longitud_m:.0f} m\n{rotulo_corto(tuberia)}"])
        entidades.append(entidad)
    tramos.dataProvider().addFeatures(entidades)
    estilo_por_tuberia(tramos, resultado.asignacion.values())
    # Un rótulo por tramo (de nodo a nodo), sin unir tramos vecinos aunque tengan el mismo texto.
    rotular_tuberia(tramos, color="#c62828", tamano=9, unir=False)

    valvulas = _capa(
        "Point",
        "field=valvula:string(80)&field=turno:integer&field=caudal_lh:double&field=p_requerida:double"
        "&field=p_disponible:double&field=exceso:double&field=cota_m:double&field=perdida_valvula_m:double"
        "&field=turnos:string(4000)",
        "Red principal · válvulas", crs)
    entidades = []
    for v in red.valvulas:
        r = resultado.turno(v.turno)
        entidad = QgsFeature(valvulas.fields())
        entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[v.nodo]))
        # Por cada turno: presión aguas arriba de la válvula, la requerida, su pérdida y su caudal.
        por_turno = [[t.turno, round(t.presiones[v.nodo], 2),
                      round(v.presion_requerida_m, 2) if t.turno == v.turno else 0.0,
                      round(v.perdida_m, 2) if t.turno == v.turno else 0.0,
                      round(v.caudal_lh, 1) if t.turno == v.turno else 0.0] for t in resultado.turnos]
        entidad.setAttributes([v.id, v.turno, round(v.caudal_lh, 1), round(v.presion_requerida_m, 2),
                               round(r.presion_disponible[v.id], 2), round(r.exceso(v), 2),
                               round(red.cotas[v.nodo], 2), round(v.perdida_m, 2),
                               json.dumps(por_turno, separators=(",", ":"))])
        entidades.append(entidad)
    valvulas.dataProvider().addFeatures(entidades)
    valvulas.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "3", "outline_color": "#ffffff"})))

    capa_bomba = _capa(
        "Point",
        "field=turno:integer&field=caudal_ls:double&field=cdt_m:double&field=potencia_kw:double"
        "&field=potencia_hp:double&field=cota_m:double",
        "Red principal · bomba", crs)
    entidad = QgsFeature(capa_bomba.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[red.fuente]))
    entidad.setAttributes([bomba.turno, round(bomba.caudal_ls, 3), round(bomba.carga_dinamica_total_m, 2),
                           round(bomba.potencia_kw, 2), round(bomba.potencia_hp, 2),
                           round(red.cotas[red.fuente], 2)])
    capa_bomba.dataProvider().addFeatures([entidad])
    capa_bomba.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": "#1565c0", "size": "5", "outline_color": "#ffffff"})))

    for capa in (tramos, valvulas, capa_bomba):
        capa.updateExtents()
    return [capa_bomba, valvulas, tramos]


def _en_sentido_del_flujo(geometria, punto_inicial):
    """La línea orientada de modo que empiece en el nodo de aguas arriba (P1) del tramo."""
    vertices = geometria.asPolyline()
    if vertices[0].distance(punto_inicial) <= vertices[-1].distance(punto_inicial):
        return geometria
    return QgsGeometry.fromPolylineXY(list(reversed(vertices)))
