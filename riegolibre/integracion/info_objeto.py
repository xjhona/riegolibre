"""Información de un objeto del mapa («Object Info»): busca el elemento calculado y arma su ficha.

Lee los resultados que RiegoLibre guarda en las capas (laterales, tramos del portalateral,
tuberías de la red principal, válvulas y bomba). Las capas calculadas con una versión anterior
no tienen todos los campos: lo que falta se muestra como «—» (vuelva a calcular).
"""

import json
from dataclasses import dataclass
from typing import List, Optional

from qgis.core import (QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsPointXY,
                       QgsProject, QgsRectangle, QgsVectorLayer)

from ..nucleo import Emisor, Lateral, PresionInsuficiente
from ..nucleo import ficha as texto
from ..nucleo.tuberias import Tuberia
from .calculo_subunidad import PROPIEDAD_LATERAL
from .memoria_mapa import PROPIEDAD_RESUMEN
from .perfil_terreno import MuestreadorDem, perfil_de_geometria
from .subunidad_mapa import PROPIEDAD

LATERALES, PORTALATERAL, TUBERIA_RED, VALVULA, VALVULA_RED, BOMBA = (
    "lateral", "portalateral", "tuberia_red", "valvula", "valvula_red", "bomba")
PUNTUALES = (VALVULA, VALVULA_RED, BOMBA)
DISTANCIA_UNION_M = 1.0  # válvula de la subunidad y válvula de la red: el mismo punto


def tipo_de_capa(capa) -> Optional[str]:
    """Qué contiene una capa de resultados de RiegoLibre, según sus campos."""
    campos = set(capa.fields().names())
    if {"emisores", "p_entrada", "longitud"} <= campos:
        return LATERALES
    if {"rama", "desde_m", "hasta_m", "tuberia"} <= campos:
        return PORTALATERAL
    if {"tramo", "tuberia", "dn_mm"} <= campos:
        return TUBERIA_RED
    if {"valvula", "p_requerida", "p_disponible"} <= campos:
        return VALVULA_RED
    if "cdt_m" in campos:
        return BOMBA
    if {"presion", "caudal_lh", "caudal_ls"} <= campos:
        return VALVULA
    return None


def capas_con_resultados(proyecto=None, solo_visibles=True) -> List[QgsVectorLayer]:
    proyecto = proyecto or QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    capas = []
    for capa in proyecto.mapLayers().values():
        if not isinstance(capa, QgsVectorLayer) or capa.customProperty(PROPIEDAD) != "resultado":
            continue
        if tipo_de_capa(capa) is None:
            continue
        nodo = raiz.findLayer(capa.id())
        if solo_visibles and nodo is not None and not nodo.isVisible():
            continue
        capas.append(capa)
    return capas


@dataclass
class Candidato:
    capa: QgsVectorLayer
    entidad: object
    tipo: str
    distancia: float


def buscar(punto, crs_punto, tolerancia, proyecto=None, solo_visibles=True) -> List[Candidato]:
    """Objetos calculados a menos de `tolerancia` (en unidades de `crs_punto`) del punto, el más cercano primero.

    Las válvulas y la bomba van antes que las líneas, porque quedan sobre ellas.
    """
    proyecto = proyecto or QgsProject.instance()
    punto = QgsPointXY(punto)
    candidatos = []
    for capa in capas_con_resultados(proyecto, solo_visibles):
        transformacion = QgsCoordinateTransform(crs_punto, capa.crs(), proyecto)
        p = transformacion.transform(punto)
        tol = transformacion.transform(QgsPointXY(punto.x() + tolerancia, punto.y())).distance(p)
        zona = QgsRectangle(p.x() - tol, p.y() - tol, p.x() + tol, p.y() + tol)
        geometria_punto = QgsGeometry.fromPointXY(p)
        for entidad in capa.getFeatures(QgsFeatureRequest().setFilterRect(zona)):
            distancia = entidad.geometry().distance(geometria_punto)
            if distancia <= tol:
                candidatos.append(Candidato(capa, entidad, tipo_de_capa(capa), distancia))
    candidatos.sort(key=lambda c: (c.tipo not in PUNTUALES, c.distancia))
    return candidatos


# -------------------------------------------------------------------- lectura


def _valor(entidad, campo, defecto=None):
    if entidad.fields().indexOf(campo) < 0:
        return defecto
    valor = entidad[campo]
    if valor is None or (hasattr(valor, "isNull") and valor.isNull()):
        return defecto
    return valor


def _json(entidad, campo):
    cadena = _valor(entidad, campo)
    try:
        return json.loads(cadena) if cadena else []
    except (TypeError, ValueError):
        return []


def _nombre_sin_prefijo(capa):
    return capa.name().split(" · ", 1)[-1]


def _extremos(capa, entidad):
    vertices = entidad.geometry().asPolyline() if not entidad.geometry().isMultipart() else \
        entidad.geometry().asMultiPolyline()[0]
    return (vertices[0].x(), vertices[0].y()), (vertices[-1].x(), vertices[-1].y())


def _punto_de(entidad):
    p = entidad.geometry().asPoint()
    return p.x(), p.y()


def _datos_lateral(c):
    e = c.entidad
    p1, p2 = _extremos(c.capa, e)
    return {
        "capa": c.capa.name(), "id": e.id(), "p1": p1, "p2": p2, "longitud": e.geometry().length(),
        "subunidad": _nombre_sin_prefijo(c.capa), "conexion": _valor(e, "conexion"),
        "dist_porta": _valor(e, "dist_porta"), "tuberia": _valor(e, "tuberia"), "emisor": _valor(e, "emisor"),
        "emisores": _valor(e, "emisores"), "p_entrada": _valor(e, "p_entrada"), "p_final": _valor(e, "p_final"),
        "perdida_m": _valor(e, "perdida_m"), "desnivel_m": _valor(e, "desnivel_m"),
        "caudal_lh": _valor(e, "caudal_lh"), "velocidad": _valor(e, "velocidad"), "p_min": _valor(e, "p_min"),
        "p_max": _valor(e, "p_max"), "q_min": _valor(e, "q_min"), "q_max": _valor(e, "q_max"),
        "var_caudal": _valor(e, "var_caudal"), "fuera_rango": _valor(e, "fuera_rango")}


def _datos_portalateral(c):
    e = c.entidad
    p1, p2 = _extremos(c.capa, e)
    return {
        "capa": c.capa.name(), "id": e.id(), "p1": p1, "p2": p2, "longitud": e.geometry().length(),
        "subunidad": _nombre_sin_prefijo(c.capa), "rama": _valor(e, "rama"), "desde_m": _valor(e, "desde_m"),
        "hasta_m": _valor(e, "hasta_m"), "tuberia": _valor(e, "tuberia"), "p_inicio": _valor(e, "p_inicio"),
        "p_fin": _valor(e, "p_fin"), "perdida_m": _valor(e, "perdida_m"), "desnivel_m": _valor(e, "desnivel_m"),
        "caudal_lh": _valor(e, "caudal_lh"), "caudal_sale_lh": _valor(e, "caudal_sale_lh"),
        "velocidad": _valor(e, "velocidad")}


def _datos_tuberia_red(c):
    e = c.entidad
    p1, p2 = _extremos(c.capa, e)
    return {
        "capa": c.capa.name(), "id": _valor(e, "tramo", e.id()), "p1": p1, "p2": p2,
        "longitud": e.geometry().length(), "tuberia": _valor(e, "tuberia"), "dn_mm": _valor(e, "dn_mm"),
        "pn_m": _valor(e, "pn_m"), "j_m100": _valor(e, "j_m100"), "desnivel_m": _valor(e, "desnivel_m"),
        "observ": _valor(e, "observ"), "turnos": _json(e, "turnos")}


def _resumen(capa):
    try:
        resumen = json.loads(capa.customProperty(PROPIEDAD_RESUMEN) or "")
    except (TypeError, ValueError):
        return None
    return resumen if isinstance(resumen, dict) else None


def _datos_subunidad(c):
    e = c.entidad
    datos = {"presion_m": _valor(e, "presion"), "caudal_lh": _valor(e, "caudal_lh"), "tuberia": _valor(e, "tuberia")}
    resumen = _resumen(c.capa)
    if resumen:
        r = resumen.get("resultados", {})
        datos.update(area_m2=resumen.get("area_m2"), laterales=resumen.get("lateral", {}).get("numero"),
                     emisores=r.get("numero_emisores"), variacion=r.get("variacion_caudal"),
                     uniformidad=r.get("uniformidad_emision"), cumple=resumen.get("cumple"))
        descripcion = resumen.get("portalateral", {}).get("descripcion")
        if descripcion:
            datos["tuberia"] = descripcion
    return datos


def _hermana(candidato, candidatos_cerca, tipo):
    """La válvula del otro tipo (subunidad o red) en el mismo punto, si existe."""
    return next((c for c in candidatos_cerca if c.tipo == tipo and c is not candidato), None)


def _valvulas_en(punto_capa, crs, proyecto):
    """Válvulas de ambos tipos a menos de `DISTANCIA_UNION_M` de un punto."""
    return buscar(punto_capa, crs, DISTANCIA_UNION_M, proyecto, solo_visibles=False)


def _datos_valvula(candidato, proyecto):
    punto = _punto_de(candidato.entidad)
    cerca = [c for c in _valvulas_en(QgsPointXY(*punto), candidato.capa.crs(), proyecto)
             if c.tipo in (VALVULA, VALVULA_RED)]
    sub = candidato if candidato.tipo == VALVULA else _hermana(candidato, cerca, VALVULA)
    red = candidato if candidato.tipo == VALVULA_RED else _hermana(candidato, cerca, VALVULA_RED)
    capas = [c.capa.name() for c in (sub, red) if c is not None]
    nombre = (_nombre_sin_prefijo(sub.capa) if sub else _valor(red.entidad, "valvula", "válvula"))
    datos = {"nombre": nombre, "p1": punto, "capas": capas, "cota": None, "turno": None, "turnos": []}
    if sub:
        datos["subunidad"] = _datos_subunidad(sub)
    if red:
        datos["cota"] = _valor(red.entidad, "cota_m")
        datos["turno"] = _valor(red.entidad, "turno")
        datos["turnos"] = _json(red.entidad, "turnos")
    return datos


def _datos_bomba(c):
    e = c.entidad
    return {"capa": c.capa.name(), "p1": _punto_de(e), "cota": _valor(e, "cota_m"), "turno": _valor(e, "turno"),
            "caudal_ls": _valor(e, "caudal_ls"), "cdt_m": _valor(e, "cdt_m"),
            "potencia_kw": _valor(e, "potencia_kw"), "potencia_hp": _valor(e, "potencia_hp")}


def ficha_de(candidato, proyecto=None) -> texto.Ficha:
    proyecto = proyecto or QgsProject.instance()
    if candidato.tipo == LATERALES:
        return texto.ficha_lateral(_datos_lateral(candidato))
    if candidato.tipo == PORTALATERAL:
        return texto.ficha_tramo_portalateral(_datos_portalateral(candidato))
    if candidato.tipo == TUBERIA_RED:
        return texto.ficha_tramo_red(_datos_tuberia_red(candidato))
    if candidato.tipo == BOMBA:
        return texto.ficha_bomba(_datos_bomba(candidato))
    return texto.ficha_valvula(_datos_valvula(candidato, proyecto))


def consultar(punto, crs_punto, tolerancia, proyecto=None):
    """Ficha del objeto más cercano al punto, junto con su candidato (para resaltarlo); None si no hay."""
    candidatos = buscar(punto, crs_punto, tolerancia, proyecto)
    if not candidatos:
        return None
    primero = candidatos[0]
    return ficha_de(primero, proyecto), primero


@dataclass
class PerfilLateral:
    resultado: object  # ResultadoLateral
    emisor: object


def perfil_lateral(candidato, proyecto=None) -> Optional[PerfilLateral]:
    """Reconstruye un lateral calculado (presión y caudal en cada emisor) para dibujar su perfil.

    Usa la configuración guardada en la capa y el DEM con el que se calculó; con la misma
    presión de entrada da el mismo resultado. Devuelve None si la capa no la tiene (se calculó
    con una versión anterior) o si no se puede reconstruir.
    """
    if candidato.tipo != LATERALES:
        return None
    proyecto = proyecto or QgsProject.instance()
    try:
        config = json.loads(candidato.capa.customProperty(PROPIEDAD_LATERAL) or "")
        tuberia, emisor = Tuberia(**config["tuberia"]), Emisor(**config["emisor"])
        entidad = candidato.entidad
        p_entrada = _valor(entidad, "p_entrada")
        if p_entrada is None:
            return None
        geometria = entidad.geometry()
        perfil = None
        dem = proyecto.mapLayer(config["dem"]) if config.get("dem") else None
        if dem is not None:
            _, perfil = perfil_de_geometria(geometria, candidato.capa.crs(), MuestreadorDem(dem, candidato.capa.crs()),
                                            config["paso_perfil_m"])
        lateral = Lateral.desde_longitud(
            tuberia, emisor, config["espaciamiento_m"], geometria.length(),
            distancia_primer_emisor_m=config["primer_emisor_m"], perfil=perfil, metodo=config["metodo"])
        return PerfilLateral(lateral.simular(p_entrada), emisor)
    except (ValueError, KeyError, TypeError, PresionInsuficiente):
        return None
