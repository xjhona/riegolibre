"""Relieve de un terreno a partir de cotas muestreadas en una rejilla.

Un plano ajustado a todo el terreno esconde las ondulaciones: un lomo que sube y baja
da pendiente media cero aunque cada lateral tendido a lo largo de él vea pendientes
fuertes. Aquí se guarda el gradiente local de cada punto de la rejilla y la pendiente
en una dirección es el promedio de su valor absoluto en esa dirección.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Gradiente = Tuple[float, float]  # (dz/dx, dz/dy) en m/m
MIN_PUNTOS = 6


@dataclass
class Relieve:
    gradientes: List[Gradiente] = field(default_factory=list)

    @property
    def gradiente_medio(self) -> Gradiente:
        """Gradiente promedio (la pendiente del plano que mejor se ajusta, si el relieve es regular)."""
        n = len(self.gradientes)
        return (sum(g[0] for g in self.gradientes) / n, sum(g[1] for g in self.gradientes) / n) if n else (0.0, 0.0)

    @property
    def pendiente_media(self) -> float:
        """Módulo medio del gradiente (m/m)."""
        n = len(self.gradientes)
        return sum(math.hypot(*g) for g in self.gradientes) / n if n else 0.0

    def pendiente_a_lo_largo(self, angulo_deg: float) -> float:
        """Pendiente media (m/m, valor absoluto) al andar en la dirección dada (antihoraria desde el este)."""
        if not self.gradientes:
            return 0.0
        a = math.radians(angulo_deg)
        c, s = math.cos(a), math.sin(a)
        return sum(abs(gx * c + gy * s) for gx, gy in self.gradientes) / len(self.gradientes)

    def direccion_de_curvas(self) -> Optional[Tuple[float, float]]:
        """(ángulo en grados entre 0 y 180, coherencia entre 0 y 1) de las curvas de nivel dominantes.

        Cada punto aporta la dirección de su curva de nivel (perpendicular al gradiente) con
        peso igual a su pendiente; las direcciones se promedian como ejes (un eje y su
        opuesto son lo mismo). Coherencia 1: todas las curvas van igual; cerca de 0: el relieve
        no tiene una dirección dominante. None si el terreno es plano.
        """
        sx = sy = total = 0.0
        for gx, gy in self.gradientes:
            modulo = math.hypot(gx, gy)
            if modulo <= 0:
                continue
            doble = 2 * math.atan2(gy, gx)
            sx += modulo * math.cos(doble)
            sy += modulo * math.sin(doble)
            total += modulo
        if total <= 0:
            return None
        # El gradiente apunta cuesta arriba; la curva de nivel es perpendicular (+90°).
        eje = (math.degrees(math.atan2(sy, sx)) / 2 + 90.0) % 180.0
        return eje, math.hypot(sx, sy) / total


def relieve_desde_rejilla(cotas: Dict[Tuple[int, int], float], paso_x: float, paso_y: float,
                          interior=None) -> Optional[Relieve]:
    """Relieve a partir de cotas en una rejilla {(i, j): cota} con pasos (m) entre columnas y filas.

    `interior(i, j)` dice si el punto cuenta (está dentro del terreno); los vecinos pueden estar
    fuera para no perder los bordes. Devuelve None si hay menos de `MIN_PUNTOS` gradientes.
    """
    gradientes = []
    for (i, j), z in cotas.items():
        if interior is not None and not interior(i, j):
            continue
        gx = _derivada(cotas, i, j, 1, 0, paso_x, z)
        gy = _derivada(cotas, i, j, 0, 1, paso_y, z)
        if gx is not None and gy is not None:
            gradientes.append((gx, gy))
    return Relieve(gradientes) if len(gradientes) >= MIN_PUNTOS else None


def _derivada(cotas, i, j, di, dj, paso, z):
    delante, detras = cotas.get((i + di, j + dj)), cotas.get((i - di, j - dj))
    if delante is not None and detras is not None:
        return (delante - detras) / (2 * paso)
    if delante is not None:
        return (delante - z) / paso
    if detras is not None:
        return (z - detras) / paso
    return None
