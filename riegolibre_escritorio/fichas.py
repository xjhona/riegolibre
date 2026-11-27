# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""«Información del objeto» del programa (como «Object Info» de IRRICAD), sin Qt.

Busca qué hay bajo el cursor (tramo de la red calculada, válvula, fuente, tubería matriz dibujada o lote) y
arma su ficha con las mismas funciones de texto del complemento (`riegolibre.nucleo.ficha`).
"""

import math
from typing import Dict, Optional, Tuple

from riegolibre.nucleo import ficha as texto
from riegolibre.nucleo.ficha import Ficha
from riegolibre.nucleo.red import bomba_critica

from . import dibujos, edicion


def _desde_hasta(red) -> Dict[str, Tuple[tuple, tuple]]:
    """(P1, P2) de cada tramo de la red calculada, en el sentido del flujo."""
    coordenadas = {red.red.fuente: red.puntos["fuente"]}
    resultado = {}
    for tramo in red.red.tramos:  # en orden desde la fuente
        geometria = red.geometrias[tramo.id]
        origen = coordenadas.get(tramo.desde)
        if origen is not None and math.dist(origen, geometria[-1]) < math.dist(origen, geometria[0]):
            geometria = list(reversed(geometria))
        resultado[tramo.id] = (tuple(geometria[0]), tuple(geometria[-1]))
        coordenadas.setdefault(tramo.hasta, tuple(geometria[-1]))
    return resultado


def _ficha_tramo(proyecto, id_tramo) -> Ficha:
    red = proyecto.red
    r = red.resultado
    tramo = next(t for t in red.red.tramos if t.id == id_tramo)
    p1, p2 = _desde_hasta(red)[id_tramo]
    tuberia = r.asignacion[id_tramo]
    turnos = []
    for t in r.turnos:
        x = t.tramos.get(id_tramo)
        if x is not None:
            turnos.append([t.turno, x.presion_inicio_m, x.presion_fin_m, x.perdida_m, x.caudal_lh, x.velocidad_ms])
    caudal_max = max((x[4] for x in turnos), default=0.0)
    j = None
    if caudal_max and tramo.longitud_m:
        perdida = max(x[3] for x in turnos if x[4] == caudal_max)
        j = perdida / tramo.longitud_m * 100
    t = proyecto.terreno
    return texto.ficha_tramo_red({
        "capa": "RED_PRINCIPAL (" + ("conector de válvula" if red.capas.get(id_tramo) == "conector" else "matriz") + ")",
        "id": id_tramo, "p1": p1, "p2": p2, "longitud": tramo.longitud_m, "tuberia": tuberia.nombre,
        "dn_mm": tuberia.diametro_nominal_mm, "pn_m": tuberia.presion_nominal_m, "j_m100": j,
        "desnivel_m": t.cota_o_cero(*p2) - t.cota_o_cero(*p1), "observ": r.observaciones(id_tramo),
        "turnos": turnos})


def _emisores(resultado):
    try:
        return len(resultado.caudales_emisores_lh)
    except (ValueError, TypeError):
        return None


def _ficha_valvula(proyecto, s) -> Ficha:
    r = s.diseno.resultado
    b = s.bloque
    datos = {"nombre": s.nombre, "p1": tuple(b.valvula), "capas": ["VÁLVULAS"],
             "cota": proyecto.terreno.cota_o_cero(*b.valvula) if proyecto.terreno.tiene_cotas else None,
             "turno": s.turno, "turnos": [],
             "subunidad": {"presion_m": r.presion_entrada_m, "caudal_lh": r.caudal_total_lh,
                           "tuberia": s.resumen()["portalateral"], "area_m2": b.area_regada_m2,
                           "laterales": len(b.laterales), "emisores": _emisores(r),
                           "variacion": r.variacion_caudal, "uniformidad": getattr(r, "uniformidad_emision", None),
                           "cumple": not s.motivos}}
    red = proyecto.red
    if red is not None:
        valvula = next((v for v in red.red.valvulas if v.id == s.nombre), None)
        if valvula is not None:
            for t in red.resultado.turnos:
                datos["turnos"].append([t.turno, t.presiones.get(valvula.nodo), valvula.presion_requerida_m,
                                        valvula.perdida_m, valvula.caudal_lh if valvula.turno == t.turno else 0.0])
    ficha = texto.ficha_valvula(datos)
    extra = [f"Lote = {s.lote}"]
    if s.motivos:
        extra.append("No cumple: " + "; ".join(s.motivos))
    avisos = s.resumen()["avisos"]
    if avisos:
        extra.append("Avisos: " + "; ".join(avisos))
    return Ficha(ficha.titulo, ficha.texto + "\n\n" + "\n".join(extra))


def _ficha_fuente(proyecto) -> Ficha:
    p = proyecto.fuente
    if proyecto.red is None:
        return Ficha("Fuente de agua", "\n".join([
            "FUENTE DE AGUA · símbolo 2D", "Capa = FUENTE", f"P1: x = {p[0]:.2f} m, y = {p[1]:.2f} m", "",
            "La bomba se calcula con «Red principal y bomba»."]))
    b = bomba_critica(proyecto.red.bombas)
    return texto.ficha_bomba({"capa": "FUENTE", "p1": p,
                              "cota": proyecto.terreno.cota_o_cero(*p) if proyecto.terreno.tiene_cotas else None,
                              "turno": b.turno, "caudal_ls": b.caudal_ls, "cdt_m": b.carga_dinamica_total_m,
                              "potencia_kw": b.potencia_kw, "potencia_hp": b.potencia_hp})


def _numero_nodo(nodos, p) -> str:
    return next((str(k + 1) for k, q in enumerate(nodos) if math.dist(p, q) <= edicion.EPS_NODO), "?")


def _cota(terreno, p) -> str:
    return f", cota = {terreno.cota_o_cero(*p):.2f} m" if terreno.tiene_cotas else ""


def _ficha_matriz(proyecto, i) -> Ficha:
    tramo = edicion.matriz(proyecto.datos)[i]
    nodos = edicion.nodos_matriz(proyecto.datos)
    lineas = ["TRAMO DE TUBERÍA MATRIZ DIBUJADA · línea 2D", "Capa = MATRIZ_DIBUJADA", f"Tramo = {i + 1}",
              f"Longitud = {edicion.longitud(tramo):.2f} m", ""]
    for nombre, p in zip(("Desde", "Hasta"), tramo):
        lineas.append(f"  {nombre} el nodo {_numero_nodo(nodos, p)}: x = {p[0]:.2f} m, y = {p[1]:.2f} m"
                      + _cota(proyecto.terreno, p))
    lineas += ["", "Diámetro = selección automática al calcular «Red principal y bomba»."]
    return Ficha(f"Tubería matriz, tramo {i + 1}", "\n".join(lineas))


def _ficha_nodo(proyecto, i) -> Ficha:
    p = edicion.nodos_matriz(proyecto.datos)[i]
    llegan = sorted(j + 1 for j, _k in edicion.tramos_en_nodo(edicion.matriz(proyecto.datos), p))
    lineas = ["NODO DE LA TUBERÍA MATRIZ · punto 2D", "Capa = NODOS_MATRIZ", f"Nodo = {i + 1}",
              f"  x = {p[0]:.2f} m, y = {p[1]:.2f} m" + _cota(proyecto.terreno, p), "",
              "Tramos que llegan = " + ", ".join(map(str, llegan))]
    return Ficha(f"Nodo {i + 1} de la matriz", "\n".join(lineas))


def _ficha_lote_sin_calcular(proyecto, i) -> Ficha:
    lote = proyecto.datos["lotes"][i]
    nombre = str(lote.get("nombre"))
    anillos = edicion.anillos_lote(lote)
    errores = [e for e in proyecto.errores if e.startswith(nombre + ":")]
    lineas = ["LOTE · polígono 2D", "Capa = LOTES", f"Nombre = {nombre}",
              f"Vértices = {len(anillos[0]) if anillos else 0},  área = "
              f"{(edicion.area(anillos[0]) - sum(edicion.area(h) for h in anillos[1:])) / 10000:.3f} ha", "",
              "Sin calcular." + (" " + "; ".join(errores) if errores else "")]
    return Ficha(f"Lote {nombre}", "\n".join(lineas))


def _ficha_dibujo(proyecto, i) -> Ficha:
    e = dibujos.lista(proyecto.datos)[i]
    lineas = ["Capa: DIBUJO (no entra en el cálculo)"] + [f"{k}: {v}" for k, v in dibujos.medidas(e)]
    titulo = edicion.nombre_objeto(proyecto.datos, ("dibujo", i))
    return Ficha(titulo[0].upper() + titulo[1:], "\n".join(lineas))


def ficha_en(proyecto, p, tolerancia: float) -> Optional[Ficha]:
    """La ficha del objeto bajo el punto p (coordenadas del proyecto), o None si no hay nada."""
    if proyecto.fuente and math.dist(p, proyecto.fuente) <= tolerancia:
        return _ficha_fuente(proyecto)
    for s in proyecto.subunidades:
        if math.dist(p, s.bloque.valvula) <= tolerancia:
            return _ficha_valvula(proyecto, s)
    if proyecto.red is not None:
        mejor = None
        for id_tramo, geometria in proyecto.red.geometrias.items():
            d = min((edicion._cercano_en_segmento(p, a, b)[0] for a, b in zip(geometria, geometria[1:])),
                    default=math.inf)
            if d <= tolerancia and (mejor is None or d < mejor[0]):
                mejor = (d, id_tramo)
        if mejor and any(t.id == mejor[1] for t in proyecto.red.red.tramos):
            return _ficha_tramo(proyecto, mejor[1])
    objeto = edicion.objeto_en(proyecto.datos, p, tolerancia)
    if objeto and objeto[0] == "dibujo":
        return _ficha_dibujo(proyecto, objeto[1])
    if objeto and objeto[0] == "nodo":
        return _ficha_nodo(proyecto, objeto[1])
    if objeto and objeto[0] == "matriz":
        return _ficha_matriz(proyecto, objeto[1])
    # La subunidad que contiene el punto (un lote subdividido tiene varias)
    for s in sorted(proyecto.subunidades, key=lambda s: s.bloque.area_regada_m2):
        if any(edicion.dentro(p, a) for a in s.anillos[:1]) and not any(edicion.dentro(p, h) for h in s.anillos[1:]):
            return _ficha_valvula(proyecto, s)
    if objeto and objeto[0] == "lote":
        return _ficha_lote_sin_calcular(proyecto, objeto[1])
    return None
