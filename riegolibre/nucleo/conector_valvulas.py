# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Conector de válvulas: tramo de derivación entre la tubería matriz y cada válvula.

Como «Valve Connector» de IRRICAD: cada válvula que no toca la matriz se une con un tramo recto a su
punto más cercano, siempre que no pase de una longitud máxima. Geometría en metros (SRC proyectado).
"""

from dataclasses import dataclass, field
from math import hypot
from typing import Hashable, List, Sequence, Tuple

Punto = Tuple[float, float]


@dataclass
class Conector:
    valvula: str
    desde: Punto  # la válvula
    hasta: Punto  # el punto de la matriz más cercano a ella
    linea: Hashable  # id de la tubería de la matriz donde cae `hasta`
    largo_m: float


@dataclass
class ResultadoConexion:
    conectores: List[Conector] = field(default_factory=list)
    ya_conectadas: List[str] = field(default_factory=list)  # la matriz ya pasa a menos de la tolerancia
    fuera_de_alcance: List[Tuple[str, float]] = field(default_factory=list)  # (válvula, distancia a la matriz)


def punto_mas_cercano(polilinea: Sequence[Punto], punto: Punto) -> Tuple[float, Punto]:
    """(distancia, punto) de la polilínea más cercano al punto dado."""
    px, py = punto
    mejor = None
    for (ax, ay), (bx, by) in zip(polilinea, polilinea[1:]):
        dx, dy = bx - ax, by - ay
        largo2 = dx * dx + dy * dy
        t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
        cx, cy = ax + t * dx, ay + t * dy
        distancia = hypot(px - cx, py - cy)
        if mejor is None or distancia < mejor[0]:
            mejor = (distancia, (cx, cy))
    if mejor is None:
        raise ValueError("La polilínea necesita al menos dos vértices.")
    return mejor


def conectar_valvulas(lineas: Sequence[Tuple[Hashable, Sequence[Punto]]],
                      valvulas: Sequence[Tuple[str, Punto]],
                      largo_max_m: float, tolerancia_m: float = 0.5) -> ResultadoConexion:
    """Decide qué tramo une cada válvula con la matriz.

    `lineas`: (id, vértices) de las tuberías de la matriz. `valvulas`: (id, punto).
    La que ya está a menos de `tolerancia_m` de una tubería no necesita tramo; la que está a más de
    `largo_max_m` queda fuera de alcance. Volver a ejecutarlo no repite los tramos ya hechos.
    """
    resultado = ResultadoConexion()
    for id_valvula, punto in valvulas:
        mejor = None
        for id_linea, vertices in lineas:
            if len(vertices) < 2:
                continue
            distancia, cercano = punto_mas_cercano(vertices, punto)
            if mejor is None or distancia < mejor[0]:
                mejor = (distancia, cercano, id_linea)
        if mejor is None:
            resultado.fuera_de_alcance.append((id_valvula, float("inf")))
        elif mejor[0] <= tolerancia_m:
            resultado.ya_conectadas.append(id_valvula)
        elif mejor[0] <= largo_max_m:
            resultado.conectores.append(Conector(id_valvula, punto, mejor[1], mejor[2], mejor[0]))
        else:
            resultado.fuera_de_alcance.append((id_valvula, mejor[0]))
    return resultado
