# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Lotes y líneas de referencia de un DXF, sin QGIS ni GDAL. Sin Qt.

Cada capa del dibujo se importa como «Lotes» (sus polilíneas cerradas pasan a ser lotes del diseño; una cerrada
dentro de otra es un hueco del lote, y una dentro del hueco, otro lote) o como «Líneas de referencia» (caminos,
canales, linderos…: se dibujan de fondo en la capa DIBUJO_CAD y el imán se pega a ellas). El nombre de cada lote
puede salir de los textos de una capa del dibujo que caen dentro de él.

Las líneas de referencia se guardan dentro del proyecto en JSON comprimido, como las curvas de nivel.
"""

import gzip
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .topografia import _abrir, _lineas

Punto = Tuple[float, float]
Linea = Tuple[str, List[Punto]]  # (capa del DXF, vértices)

CIERRE_M = 0.01  # una línea cuyo último vértice queda a menos de esto del primero es cerrada
AREA_MIN_M2 = 1.0  # polígonos más chicos (basura del dibujo) no son lotes
TIPOS_TEXTO = "TEXT MTEXT"
CELDA_IMAN_M = 25.0


@dataclass
class CapaDibujo:
    nombre: str
    lineas: int = 0
    cerradas: int = 0
    con_cota: int = 0  # líneas con alguna Z distinta de 0 (seguramente curvas de nivel)

    @property
    def parece_curvas(self):
        return self.con_cota > 0 and self.con_cota == self.lineas


@dataclass
class ContenidoDibujo:
    capas: List[CapaDibujo]
    textos: Dict[str, int]  # capa: número de textos (TEXT y MTEXT)
    extension: tuple  # (xmin, xmax, ymin, ymax) de las líneas

    @property
    def ancho(self):
        return self.extension[1] - self.extension[0]

    @property
    def alto(self):
        return self.extension[3] - self.extension[2]


@dataclass
class ResultadoDibujo:
    lotes: List[dict]  # {"nombre" (None si no tiene texto), "contorno", "huecos"?}
    lineas: List[Linea]
    avisos: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ geometría


def es_cerrada(puntos) -> bool:
    return len(puntos) >= 4 and math.dist(puntos[0][:2], puntos[-1][:2]) <= CIERRE_M


def _limpiar(puntos) -> List[Punto]:
    """Vértices 2D sin repetidos seguidos ni el de cierre."""
    limpio = []
    for p in puntos:
        q = (round(float(p[0]), 3), round(float(p[1]), 3))
        if not limpio or math.dist(q, limpio[-1]) > 1e-3:
            limpio.append(q)
    if len(limpio) > 1 and math.dist(limpio[0], limpio[-1]) <= CIERRE_M:
        limpio.pop()
    return limpio


def area(anillo: Sequence[Punto]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(anillo, list(anillo[1:]) + [anillo[0]]))) / 2


def dentro(p: Punto, anillo: Sequence[Punto]) -> bool:
    x, y = p
    adentro = False
    n = len(anillo)
    for i in range(n):
        (x1, y1), (x2, y2) = anillo[i], anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            adentro = not adentro
    return adentro


def _contiene(grande: Sequence[Punto], chico: Sequence[Punto]) -> bool:
    """True si el polígono chico está dentro del grande (la mayoría de sus vértices adentro: tolera que
    compartan algún vértice o un borde)."""
    muestra = chico if len(chico) <= 50 else chico[::max(1, len(chico) // 50)]
    return sum(dentro(p, grande) for p in muestra) * 2 > len(muestra)


def poligonos_a_lotes(anillos: List[List[Punto]]) -> List[dict]:
    """Lotes a partir de polígonos sueltos: uno dentro de otro es su hueco; uno dentro de un hueco, otro lote."""
    orden = sorted(range(len(anillos)), key=lambda i: -area(anillos[i]))
    profundidad, padre = {}, {}
    for posicion, i in enumerate(orden):
        contenedores = [j for j in orden[:posicion] if _contiene(anillos[j], anillos[i])]
        if contenedores:
            padre[i] = min(contenedores, key=lambda j: area(anillos[j]))
            profundidad[i] = profundidad[padre[i]] + 1
        else:
            profundidad[i] = 0
    lotes, de_anillo = [], {}
    for i in orden:
        if profundidad[i] % 2 == 0:
            de_anillo[i] = len(lotes)
            lotes.append({"nombre": None, "contorno": [list(p) for p in anillos[i]]})
        else:
            lotes[de_anillo[padre[i]]].setdefault("huecos", []).append([list(p) for p in anillos[i]])
    return lotes


def _centro(anillo: Sequence[Punto]) -> Punto:
    xs, ys = [p[0] for p in anillo], [p[1] for p in anillo]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def nombrar_lotes(lotes: List[dict], textos: List[Tuple[str, Punto]]):
    """Pone a cada lote el texto que cae dentro de él (fuera de sus huecos); con varios, el más cercano a su
    centro. Cada texto sirve a un solo lote."""
    usados = set()
    for lote in sorted(lotes, key=lambda l: area(l["contorno"])):  # primero los chicos (un texto en un hueco)
        contorno = [tuple(p) for p in lote["contorno"]]
        huecos = [[tuple(p) for p in h] for h in lote.get("huecos", [])]
        centro = _centro(contorno)
        candidatos = [(math.dist(p, centro), k) for k, (texto, p) in enumerate(textos)
                      if k not in usados and texto and dentro(p, contorno) and not any(dentro(p, h) for h in huecos)]
        if candidatos:
            k = min(candidatos)[1]
            usados.add(k)
            lote["nombre"] = textos[k][0]


# ------------------------------------------------------------------ DXF


def _texto(entidad) -> str:
    if entidad.dxftype() == "MTEXT":
        texto = entidad.plain_text()
    else:
        texto = entidad.plain_text() if hasattr(entidad, "plain_text") else entidad.dxf.text
    return " ".join(str(texto).split())


def _textos(doc, capa: str) -> List[Tuple[str, Punto]]:
    textos = []
    for entidad in doc.modelspace().query(TIPOS_TEXTO):
        if (entidad.dxf.layer or "0") != capa:
            continue
        p = entidad.dxf.insert
        if entidad.dxftype() == "TEXT" and entidad.dxf.hasattr("align_point") and \
                entidad.dxf.get("halign", 0) + entidad.dxf.get("valign", 0) > 0:
            p = entidad.dxf.align_point  # texto justificado: el punto de alineación es el que se ve
        textos.append((_texto(entidad), (float(p[0]), float(p[1]))))
    return textos


def leer_dibujo(ruta) -> ContenidoDibujo:
    """Capas del DXF con sus líneas (cuántas cerradas y cuántas con cota) y las capas con textos."""
    doc = _abrir(ruta)
    capas = {}
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    for nombre, puntos in _lineas(doc):
        capa = capas.setdefault(nombre, CapaDibujo(nombre))
        capa.lineas += 1
        capa.cerradas += es_cerrada(puntos)
        capa.con_cota += any(p[2] != 0 for p in puntos)
        xmin, xmax = min(xmin, min(p[0] for p in puntos)), max(xmax, max(p[0] for p in puntos))
        ymin, ymax = min(ymin, min(p[1] for p in puntos)), max(ymax, max(p[1] for p in puntos))
    if not capas:
        raise ValueError("El DXF no tiene líneas ni polilíneas en el espacio modelo.")
    textos = defaultdict(int)
    for entidad in doc.modelspace().query(TIPOS_TEXTO):
        textos[entidad.dxf.layer or "0"] += 1
    return ContenidoDibujo(sorted(capas.values(), key=lambda c: c.nombre.lower()), dict(textos),
                           (xmin, xmax, ymin, ymax))


def importar_dibujo(ruta, capas_lotes: Sequence[str] = (), capas_lineas: Sequence[str] = (),
                    capa_nombres: Optional[str] = None) -> ResultadoDibujo:
    """Lotes (polilíneas cerradas de `capas_lotes`) y líneas de referencia (todas las de `capas_lineas`)."""
    capas_lotes, capas_lineas = set(capas_lotes), set(capas_lineas)
    if not capas_lotes and not capas_lineas:
        raise ValueError("Elija al menos una capa para importar.")
    doc = _abrir(ruta)
    anillos, lineas, avisos = [], [], []
    abiertas = pequenas = 0
    for capa, puntos in _lineas(doc, capas_lotes | capas_lineas):
        if capa in capas_lineas:
            linea = _limpiar(puntos)
            if es_cerrada(puntos) and len(linea) >= 3:
                linea.append(linea[0])  # _limpiar quita el vértice de cierre; aquí se dibuja
            if len(linea) >= 2:
                lineas.append((capa, linea))
        if capa in capas_lotes:
            if not es_cerrada(puntos):
                abiertas += 1
                continue
            anillo = _limpiar(puntos)
            if len(anillo) < 3 or area(anillo) < AREA_MIN_M2:
                pequenas += 1
                continue
            anillos.append(anillo)
    lotes = poligonos_a_lotes(anillos)
    if capa_nombres:
        nombrar_lotes(lotes, _textos(doc, capa_nombres))
    if capas_lotes and not lotes:
        avisos.append("Las capas de lotes no tienen polilíneas cerradas.")
    if abiertas:
        avisos.append(f"{abiertas} línea(s) abierta(s) de las capas de lotes no se usaron: un lote debe ser una "
                      "polilínea cerrada.")
    if pequenas:
        avisos.append(f"{pequenas} polígono(s) de menos de {AREA_MIN_M2:g} m² no se usaron.")
    if capa_nombres and lotes and not any(l["nombre"] for l in lotes):
        avisos.append(f"Ningún texto de la capa «{capa_nombres}» cae dentro de un lote: se numeraron.")
    return ResultadoDibujo(lotes, lineas, avisos)


# ------------------------------------------------------------------ guardar en el proyecto


def lineas_a_bytes(lineas: Sequence[Linea]) -> bytes:
    datos = [[capa, [[round(x, 3), round(y, 3)] for x, y in puntos]] for capa, puntos in lineas]
    return gzip.compress(json.dumps(datos, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 6)


def lineas_de_bytes(contenido: bytes) -> List[Linea]:
    return [(capa, [(x, y) for x, y in puntos]) for capa, puntos in json.loads(gzip.decompress(contenido))]


# ------------------------------------------------------------------ imán


class IndiceIman:
    """Vértices y tramos de las líneas de referencia en una cuadrícula, para el imán: buscar lo cercano al cursor
    sin recorrer miles de tramos en cada movimiento del ratón."""

    def __init__(self, lineas: Sequence[Linea], celda: float = CELDA_IMAN_M):
        self.celda = celda
        self.vertices = defaultdict(list)
        self.tramos = defaultdict(list)
        for _, linea in lineas:
            for p in linea:
                self.vertices[self._clave(p)].append(p)
            for a, b in zip(linea, linea[1:]):
                i0, j0 = self._clave((min(a[0], b[0]), min(a[1], b[1])))
                i1, j1 = self._clave((max(a[0], b[0]), max(a[1], b[1])))
                if (i1 - i0 + 1) * (j1 - j0 + 1) > 400:  # tramo muy largo: lo partimos
                    n = math.ceil(math.dist(a, b) / celda)
                    partes = [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
                    for c, d in zip(partes, partes[1:]):
                        self._poner_tramo(c, d, a, b)
                else:
                    for i in range(i0, i1 + 1):
                        for j in range(j0, j1 + 1):
                            self.tramos[(i, j)].append((a, b))

    def _poner_tramo(self, c, d, a, b):
        for clave in {self._clave(c), self._clave(d)}:
            self.tramos[clave].append((a, b))

    def _clave(self, p):
        return math.floor(p[0] / self.celda), math.floor(p[1] / self.celda)

    def cerca(self, p: Punto, tolerancia: float) -> Tuple[List[Punto], List[Tuple[Punto, Punto]]]:
        """Vértices y tramos de las celdas a menos de `tolerancia` de p (puede traer alguno más lejos)."""
        i0, j0 = self._clave((p[0] - tolerancia, p[1] - tolerancia))
        i1, j1 = self._clave((p[0] + tolerancia, p[1] + tolerancia))
        if (i1 - i0 + 1) * (j1 - j0 + 1) > 100:  # muy alejado: el imán no sirve a esta escala
            return [], []
        vertices, tramos = [], set()
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                vertices += self.vertices.get((i, j), [])
                tramos.update(self.tramos.get((i, j), []))
        return vertices, list(tramos)
