"""Costo por metro de la red principal automática ajustado a la lista de precios.

El trazado automático (trazado_red.py) compara recorridos con un costo por metro relativo
`costo_fijo + (q/Qref)^exponente`. Aquí se calculan esas dos constantes a partir de las tuberías y sus
precios: para una serie de caudales, entre el de la válvula más chica y el total de un turno, se busca
la tubería más barata cuya velocidad no pasa de la máxima y se ajusta la curva `a + b·(q/Qref)^e` a sus
precios por metro. El costo de zanja y montaje, que la lista no trae, se suma a la parte fija a.
Dividiendo entre b queda `costo_fijo = a/b`.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .hidraulica import LH_A_M3S
from .trazado_red import ValvulaDestino
from .tuberias import Tuberia

MUESTRAS = 24  # caudales (repartidos en escala logarítmica) con que se ajusta la curva
EXPONENTES = [round(0.05 + 0.01 * k, 2) for k in range(91)]  # 0.05 … 0.95


@dataclass(frozen=True)
class AjusteCosto:
    costo_fijo: float  # relativo al término variable: lo que usa `ParametrosRed`
    exponente: float
    precio_fijo: float  # moneda por metro que no depende del caudal (zanja + parte fija del precio)
    precio_variable: float  # moneda por metro que se suma a la tubería del caudal de referencia
    caudal_ref_lh: float
    error_relativo: float  # raíz del error cuadrático medio entre el precio medio
    muestras: Tuple[Tuple[float, str, float], ...]  # (caudal L/h, tubería elegida, su precio por metro)

    def precio_m(self, caudal_lh):
        """Precio por metro, zanja incluida, que da la curva ajustada para un caudal."""
        return self.precio_fijo + self.precio_variable * (caudal_lh / self.caudal_ref_lh) ** self.exponente


def _ajustar_recta(x: Sequence[float], y: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """Mínimos cuadrados de y = a + b·x con a ≥ 0 y b > 0: (a, b, suma de errores al cuadrado) o None."""
    n = len(x)
    sx, sy = sum(x), sum(y)
    sxx = sum(v * v for v in x)
    sxy = sum(u * v for u, v in zip(x, y))
    den = n * sxx - sx * sx
    b = (n * sxy - sx * sy) / den if den > 1e-12 else 0.0
    a = (sy - b * sx) / n
    if a < 0:
        a = 0.0
        b = sxy / sxx if sxx > 0 else 0.0
    if b <= 0:
        return None
    return a, b, sum((a + b * u - v) ** 2 for u, v in zip(x, y))


def _tuberia_para(caudal_lh, candidatas: Sequence[Tuberia], precios: Dict[str, float], velocidad_max_ms):
    """La más barata que no pasa la velocidad máxima (o, si ninguna sirve, la de mayor diámetro)."""
    validas = [t for t in candidatas if t.velocidad(caudal_lh * LH_A_M3S) <= velocidad_max_ms + 1e-9]
    if not validas:
        return candidatas[-1]
    return min(validas, key=lambda t: (precios[t.nombre], t.diametro_interior_mm))


def ajustar_costo_a_precios(caudal_ref_lh: float, caudal_min_lh: float, tuberias: Sequence[Tuberia],
                            precios: Dict[str, float], velocidad_max_ms: float = 1.5,
                            zanja_m: float = 0.0) -> AjusteCosto:
    """Ajusta el costo por metro del trazado a los precios de las tuberías.

    `caudal_ref_lh` es el mayor caudal que pasa por la red (el total de un turno) y `caudal_min_lh`
    el de la válvula más pequeña; `precios` es {nombre de la tubería: precio por metro}; `zanja_m`
    es el costo por metro de zanja y montaje que se suma al de cualquier tubería.
    """
    if caudal_ref_lh <= 0:
        raise ValueError("El caudal de la red debe ser mayor que cero.")
    if velocidad_max_ms <= 0:
        raise ValueError("La velocidad máxima debe ser mayor que cero.")
    if zanja_m < 0:
        raise ValueError("El costo de la zanja no puede ser negativo.")
    candidatas = sorted((t for t in tuberias if (precios.get(t.nombre) or 0) > 0),
                        key=lambda t: t.diametro_interior_mm)
    if len({precios[t.nombre] for t in candidatas}) < 2:
        raise ValueError("Para ajustar el costo hacen falta al menos dos tuberías de la red con precios "
                         "distintos en la lista de precios.")

    minimo = caudal_min_lh if 0 < caudal_min_lh < 0.99 * caudal_ref_lh else caudal_ref_lh / 4
    caudales = [minimo * (caudal_ref_lh / minimo) ** (i / (MUESTRAS - 1)) for i in range(MUESTRAS)]
    elegidas = [_tuberia_para(q, candidatas, precios, velocidad_max_ms) for q in caudales]
    y = [precios[t.nombre] for t in elegidas]
    if len(set(y)) < 2:
        raise ValueError("Con la velocidad máxima dada todos los caudales de la red llevan la misma "
                         "tubería: el precio no cambia con el caudal y no se puede ajustar la curva.")

    mejor = None
    for e in EXPONENTES:
        x = [(q / caudal_ref_lh) ** e for q in caudales]
        ajuste = _ajustar_recta(x, y)
        if ajuste is not None and (mejor is None or ajuste[2] < mejor[3] - 1e-12):
            mejor = (e, ajuste[0], ajuste[1], ajuste[2])
    if mejor is None:
        raise ValueError("Los precios bajan al aumentar el caudal: no se puede ajustar el costo.")
    e, a, b, sse = mejor
    error = math.sqrt(sse / MUESTRAS) / (sum(y) / MUESTRAS)
    muestras = tuple((q, t.nombre, precio) for q, t, precio in zip(caudales, elegidas, y))
    a += zanja_m  # la zanja no depende del caudal: se suma a la parte fija, no entra en el ajuste
    return AjusteCosto(a / b, e, a, b, caudal_ref_lh, error, muestras)


def ajustar_costo_de_valvulas(valvulas: Sequence[ValvulaDestino], tuberias: Sequence[Tuberia],
                              precios: Dict[str, float], velocidad_max_ms: float = 1.5,
                              zanja_m: float = 0.0) -> AjusteCosto:
    """Lo mismo que `ajustar_costo_a_precios`, con los caudales que dan las válvulas y sus turnos."""
    por_turno: Dict[int, float] = {}
    for v in valvulas:
        por_turno[v.turno] = por_turno.get(v.turno, 0.0) + v.caudal_lh
    return ajustar_costo_a_precios(max(por_turno.values(), default=0.0),
                                   min((v.caudal_lh for v in valvulas), default=0.0),
                                   tuberias, precios, velocidad_max_ms, zanja_m)
