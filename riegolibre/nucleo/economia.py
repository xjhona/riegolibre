"""Diámetros de la red principal por costo total: tubería + energía de bombeo.

Un diámetro mayor cuesta más, pero pierde menos carga: la bomba trabaja con una
CDT menor y gasta menos energía durante toda la vida del sistema. El costo total
que se compara es

    costo total = costo de las tuberías + valor presente de la energía de bombeo

La energía de cada turno es la potencia eléctrica (potencia al eje / eficiencia
del motor) por las horas de bombeo del turno; las horas del año se reparten por
igual entre los turnos y cada turno se bombea con su propia CDT. El valor
presente usa el factor de una serie uniforme: (1 − (1 + i)^−n) / i.

En una red ramificada los caudales de cada turno no dependen de los diámetros,
así que cada combinación se evalúa con el cálculo normal de la red. La búsqueda
parte del diseño por velocidad (el menor diámetro que cumple) y, tramo a tramo,
prueba el diámetro nominal inmediato superior e inferior; aplica el cambio que
más reduce el costo total y repite hasta que ningún cambio lo reduce. En cada
combinación la clase de presión se ajusta como en el dimensionamiento normal.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .red import CriteriosRed, DatosBomba, dimensionar_red, punto_bomba


@dataclass
class DatosEconomicos:
    precio_energia_kwh: float = 0.15  # en la moneda de la lista de precios
    horas_bombeo_anio: float = 2000.0  # de todos los turnos; se reparten por igual entre ellos
    vida_util_anios: int = 20
    tasa_interes: float = 0.10  # anual
    eficiencia_motor: float = 0.90

    @property
    def factor_valor_presente(self):
        """Valor presente de 1 por año durante la vida útil."""
        n, i = self.vida_util_anios, self.tasa_interes
        if i <= 0:
            return float(n)
        return (1 - (1 + i) ** -n) / i


@dataclass
class CostosRed:
    tuberia: float  # compra de las tuberías de la red principal
    energia_kwh_anual: float
    energia_anual: float
    factor_valor_presente: float
    sin_precio: List[str] = field(default_factory=list)  # tuberías usadas sin precio (no suman)

    @property
    def energia_valor_presente(self):
        return self.energia_anual * self.factor_valor_presente

    @property
    def total(self):
        return self.tuberia + self.energia_valor_presente


def costos_red(resultado, precios_m: Dict[str, float], datos_bomba=DatosBomba(),
               economicos=DatosEconomicos()):
    """Costo de las tuberías y de la energía de bombeo de una red dimensionada (ResultadoRed)."""
    tuberia, sin_precio = 0.0, set()
    for t in resultado.red.tramos:
        nombre = resultado.asignacion[t.id].nombre
        if nombre in precios_m:
            tuberia += precios_m[nombre] * t.longitud_m
        else:
            sin_precio.add(nombre)
    horas = economicos.horas_bombeo_anio / len(resultado.turnos)
    kwh = sum(punto_bomba(r, datos_bomba).potencia_kw / economicos.eficiencia_motor * horas
              for r in resultado.turnos)
    return CostosRed(tuberia, kwh, kwh * economicos.precio_energia_kwh,
                     economicos.factor_valor_presente, sorted(sin_precio))


@dataclass
class ResultadoOptimizacion:
    resultado: object  # ResultadoRed de menor costo total
    costos: CostosRed
    referencia: object  # ResultadoRed por velocidad: el menor diámetro que cumple
    costos_referencia: CostosRed
    economicos: DatosEconomicos
    evaluaciones: int = 0  # combinaciones calculadas
    tramos_cambiados: List[str] = field(default_factory=list)  # con otro diámetro que la referencia

    @property
    def ahorro(self):
        return self.costos_referencia.total - self.costos.total


def optimizar_red(red, candidatas, precios_m: Dict[str, float], criterios=CriteriosRed(),
                  datos_bomba=DatosBomba(), economicos=DatosEconomicos(), max_iteraciones=1000):
    """Elige el diámetro de cada tramo para que el costo total sea mínimo.

    Solo se usan las candidatas con precio (precios_m: nombre de la tubería ->
    precio por metro). Ninguna solución puede tener más tramos que no cumplen
    los criterios que el diseño por velocidad.
    """
    con_precio = [t for t in candidatas if t.nombre in precios_m]
    if not con_precio:
        raise ValueError("Ninguna tubería de la red principal tiene precio en la lista de precios.")
    por_dn: Dict[float, list] = {}
    for t in con_precio:
        por_dn.setdefault(t.diametro_nominal_mm or t.diametro_interior_mm, []).append(t)
    diametros = sorted(por_dn)

    def dn(tuberia):
        return tuberia.diametro_nominal_mm or tuberia.diametro_interior_mm

    evaluadas: Dict[tuple, tuple] = {}

    def evaluar(dns: Dict[str, float]):
        clave = tuple(sorted(dns.items()))
        if clave not in evaluadas:
            resultado = dimensionar_red(red, con_precio, criterios,
                                        candidatas_por_tramo={i: por_dn[d] for i, d in dns.items()})
            costos = costos_red(resultado, precios_m, datos_bomba, economicos)
            evaluadas[clave] = ((len(resultado.motivos), costos.total), resultado, costos)
        return evaluadas[clave]

    referencia = dimensionar_red(red, con_precio, criterios)
    caudal_max = red.caudales_maximos()
    variables = [t.id for t in red.tramos if t.tuberia is None and caudal_max[t.id] > 0]
    actual = {i: dn(referencia.asignacion[i]) for i in variables}
    evaluacion = evaluar(actual)
    for _ in range(max_iteraciones):
        mejor: Optional[tuple] = None  # (diámetros, evaluación)
        for i in variables:
            k = diametros.index(actual[i])
            for j in (k - 1, k + 1):
                if not 0 <= j < len(diametros):
                    continue
                prueba = dict(actual)
                prueba[i] = diametros[j]
                candidata = evaluar(prueba)
                if _mejora(candidata[0], (mejor[1] if mejor else evaluacion)[0]):
                    mejor = (prueba, candidata)
        if mejor is None:
            break
        actual, evaluacion = mejor
    _, resultado, costos = evaluacion
    return ResultadoOptimizacion(
        resultado, costos, referencia, costos_red(referencia, precios_m, datos_bomba, economicos),
        economicos, len(evaluadas),
        [i for i in variables if resultado.asignacion[i].nombre != referencia.asignacion[i].nombre])


def _mejora(nueva, actual):
    """True si (tramos que no cumplen, costo total) mejora de verdad (no por redondeo)."""
    if nueva[0] != actual[0]:
        return nueva[0] < actual[0]
    return nueva[1] < actual[1] - 1e-6 * max(1.0, abs(actual[1]))
