"""Turnos de riego: colores, resumen por turno y balance de caudales.

Un turno es el grupo de válvulas que riegan a la vez. Aquí no hay mapa ni QGIS: solo la paleta que
usa el mapa para pintar los bloques y las cuentas que se muestran al asignar (cuántas válvulas y qué
caudal lleva cada turno, y cuánto se desbalancean).
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

TURNO_POR_DEFECTO = 1
TURNO_MAXIMO = 50
COLOR_SELECCION = "#e53935"  # rojo: bloques elegidos que aún no tienen turno (ningún turno usa este color)

# Colores bien distintos entre sí y del rojo de la selección; se repiten pasado el último.
PALETA = ("#1e88e5", "#fb8c00", "#43a047", "#8e24aa", "#00acc1", "#6d4c41", "#d81b60", "#7cb342",
          "#3949ab", "#fdd835", "#00897b", "#5e35b1")


def color_de_turno(turno: int) -> str:
    """Color (#rrggbb) con que se pinta un turno en el mapa."""
    return PALETA[(max(int(turno), 1) - 1) % len(PALETA)]


def siguiente_turno(usados: Iterable[int]) -> int:
    """El turno que sigue al mayor ya usado (para el siguiente grupo que se va a pintar)."""
    usados = [t for t in usados if t]
    return min((max(usados) + 1) if usados else TURNO_POR_DEFECTO, TURNO_MAXIMO)


@dataclass
class ResumenTurno:
    turno: int
    valvulas: int
    caudal_lh: float

    @property
    def caudal_ls(self) -> float:
        return self.caudal_lh / 3600.0


@dataclass
class ResumenTurnos:
    turnos: List[ResumenTurno]
    sin_asignar: int  # válvulas sin turno elegido; el cálculo las toma en el turno por defecto
    caudal_sin_asignar_lh: float

    @property
    def desbalance(self) -> Optional[float]:
        """(mayor − menor) / mayor entre los caudales de los turnos; None si hay menos de dos."""
        caudales = [t.caudal_lh for t in self.turnos if t.valvulas]
        if len(caudales) < 2 or max(caudales) <= 0:
            return None
        return (max(caudales) - min(caudales)) / max(caudales)

    @property
    def turno_mayor(self) -> Optional[ResumenTurno]:
        """El turno de más caudal: el que manda el diámetro de la red y la bomba."""
        con_caudal = [t for t in self.turnos if t.valvulas]
        return max(con_caudal, key=lambda t: t.caudal_lh) if con_caudal else None


def resumen_turnos(valvulas: Iterable[Tuple[str, float, Optional[int]]]) -> ResumenTurnos:
    """Resume (id, caudal L/h, turno o None) de cada válvula por turno.

    Las válvulas con turno None no están asignadas: se cuentan aparte porque el cálculo de la red
    las toma en el turno por defecto.
    """
    por_turno: Dict[int, List[float]] = {}
    sin = []
    for _, caudal, turno in valvulas:
        if turno is None:
            sin.append(caudal)
        else:
            por_turno.setdefault(int(turno), []).append(caudal)
    turnos = [ResumenTurno(t, len(q), sum(q)) for t, q in sorted(por_turno.items())]
    return ResumenTurnos(turnos, len(sin), sum(sin))


def texto_balance(resumen: ResumenTurnos) -> str:
    """Una frase con el balance entre turnos, para el panel del mapa y la ventana de la red."""
    if not resumen.turnos:
        return "Ningún turno asignado todavía."
    partes = []
    mayor = resumen.turno_mayor
    if mayor is not None and len(resumen.turnos) > 1:
        partes.append(f"El turno {mayor.turno} ({mayor.caudal_ls:.2f} L/s) es el que manda los diámetros y la bomba.")
    if resumen.desbalance is not None:
        partes.append(f"Desbalance entre turnos: {100 * resumen.desbalance:.0f} %.")
    if resumen.sin_asignar:
        partes.append(f"{resumen.sin_asignar} válvulas sin turno se calculan en el turno {TURNO_POR_DEFECTO}.")
    return " ".join(partes) or "Un solo turno."
