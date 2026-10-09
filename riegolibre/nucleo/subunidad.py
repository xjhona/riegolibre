"""Subunidad de riego: uno o dos portalaterales alimentados desde la misma válvula.

Con la entrada en un extremo hay un solo portalateral; con la entrada en el
centro hay dos ramas que reciben la misma presión (una suele ir en subida y la
otra en bajada). También incluye la selección automática del diámetro del
portalateral según los criterios de diseño.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .hidraulica import PresionInsuficiente, interpolar_perfil, resolver_creciente
from .lateral import CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA
from .portalateral import (ConexionLateral, EstadisticasEmisores, Portalateral,
                           ResultadoPortalateral, corregir_presion_minima,
                           criterio_por_defecto, presion_minima_requerida)

ENTRADA_EXTREMO = "extremo"
ENTRADA_CENTRO = "centro"


@dataclass
class ResultadoSubunidad(EstadisticasEmisores):
    ramas: List[ResultadoPortalateral]
    presion_entrada_m: float

    def _unir(self, atributo):
        return [v for rama in self.ramas for v in getattr(rama, atributo)]

    @property
    def caudales_lh(self):
        return self._unir("caudales_lh")

    @property
    def h_min_m(self):
        return self._unir("h_min_m")

    @property
    def h_max_m(self):
        return self._unir("h_max_m")

    @property
    def q_min_lh(self):
        return self._unir("q_min_lh")

    @property
    def q_max_lh(self):
        return self._unir("q_max_lh")

    @property
    def fuera_de_rango(self):
        return self._unir("fuera_de_rango")

    @property
    def numero_emisores(self):
        return sum(r.numero_emisores for r in self.ramas)

    @property
    def cv(self):
        return max(r.cv for r in self.ramas)

    @property
    def laterales(self):
        if any(r.laterales is None for r in self.ramas):
            return None
        return self._unir("laterales")

    @property
    def velocidad_max_ms(self):
        return max(r.velocidad_entrada_ms for r in self.ramas)

    @property
    def perdida_friccion_max_m(self):
        return max(r.perdida_friccion_m for r in self.ramas)

    @property
    def presion_max_portalateral_m(self):
        return max([self.presion_entrada_m] + self._unir("presiones_m"))


@dataclass
class Subunidad:
    ramas: List[Portalateral]

    @property
    def laterales(self):
        return [lat for rama in self.ramas for lat in rama.laterales]

    @property
    def numero_emisores(self):
        return sum(rama.numero_emisores for rama in self.ramas)

    def simular(self, presion_entrada_m, detallado=True):
        ramas = [rama.simular(presion_entrada_m, detallado) for rama in self.ramas]
        return ResultadoSubunidad(ramas, presion_entrada_m)

    def presion_entrada_requerida(self, criterio=None, detallado=True):
        criterio = criterio or criterio_por_defecto(self.laterales)
        if len(self.ramas) == 1:
            r = self.ramas[0].presion_entrada_requerida(criterio, detallado)
            return ResultadoSubunidad([r], r.presion_entrada_m)

        if criterio == CRITERIO_PRESION_MINIMA:
            # La rama más exigente fija la presión; la otra recibe algo más.
            presion = max(rama.presion_entrada_requerida(criterio, detallado=False).presion_entrada_m
                          for rama in self.ramas)
            r = self.simular(presion, detallado)
            if detallado:
                r = corregir_presion_minima(r, presion_minima_requerida(self.laterales), self.simular)
            return r

        if criterio == CRITERIO_CAUDAL_MEDIO:
            objetivo = sum(lat.emisor.caudal_nominal_lh * lat.numero_emisores for lat in self.laterales)
            minimo = max(rama.simular_desde_final(0.0).presion_entrada_m for rama in self.ramas)

            def caudal_total(h):
                return sum(rama.simular(h, detallado=False).caudal_total_lh for rama in self.ramas)

            presion = resolver_creciente(caudal_total, objetivo, minimo, max(minimo + 10.0, 10.0),
                                         tolerancia=1e-3)
            return self.simular(presion, detallado)

        raise ValueError(f"Criterio desconocido: {criterio!r}")


def _perfil_rama(perfil, centro, sentido):
    """Perfil visto desde la entrada central: sentido +1 hacia el final, -1 hacia el inicio."""
    if perfil is None:
        return None
    puntos = [(0.0, interpolar_perfil(perfil, centro))]
    for x, z in perfil:
        d = (x - centro) * sentido
        if d > 0:
            puntos.append((d, z))
    if len(puntos) < 2:
        puntos.append((1.0, puntos[0][1]))
    return puntos


def subunidad_rectangular(tuberia, lateral_a, lateral_b, separacion_laterales_m, numero_laterales,
                          posicion_entrada=ENTRADA_EXTREMO, pendiente=0.0, perfil=None,
                          metodo="darcy", distancia_primera_conexion_m=None):
    """Subunidad rectangular con laterales equidistantes a uno o ambos lados.

    - lateral_a / lateral_b: laterales de cada lado del portalateral (uno puede ser None).
      Si el terreno tiene pendiente transversal, cada lado lleva su propia pendiente.
    - pendiente / perfil: terreno a lo largo del portalateral, desde su inicio.
    - posicion_entrada: "extremo" (al inicio del portalateral) o "centro".
    """
    laterales = [lat for lat in (lateral_a, lateral_b) if lat is not None]
    if not laterales:
        raise ValueError("Indique al menos un lateral.")
    if numero_laterales < 1:
        raise ValueError("La subunidad necesita al menos una posición de laterales.")
    if distancia_primera_conexion_m is None:
        distancia_primera_conexion_m = separacion_laterales_m / 2
    posiciones = [distancia_primera_conexion_m + i * separacion_laterales_m
                  for i in range(numero_laterales)]
    comunes = dict(metodo=metodo)

    if posicion_entrada == ENTRADA_EXTREMO:
        conexiones = [ConexionLateral(x, laterales) for x in posiciones]
        return Subunidad([Portalateral(tuberia, conexiones, pendiente=pendiente, perfil=perfil, **comunes)])

    if posicion_entrada != ENTRADA_CENTRO:
        raise ValueError(f"Posición de entrada desconocida: {posicion_entrada!r}")
    longitud = posiciones[-1] + distancia_primera_conexion_m
    centro = longitud / 2
    ramas = []
    for sentido in (1, -1):
        conexiones = [ConexionLateral((x - centro) * sentido, laterales)
                      for x in posiciones if (x - centro) * sentido > 0 or (sentido == 1 and x == centro)]
        if conexiones:
            ramas.append(Portalateral(tuberia, conexiones, pendiente=pendiente * sentido,
                                      perfil=_perfil_rama(perfil, centro, sentido), **comunes))
    return Subunidad(ramas)


# ------------------------------------------------------------------ selección


@dataclass
class CriteriosDiseno:
    variacion_caudal_max: float = 0.10  # en toda la subunidad
    velocidad_max_ms: float = 2.0  # en el portalateral
    presion_entrada_max_m: Optional[float] = None


def incumplimientos(resultado, criterios, tuberia_portalateral=None):
    """Lista de motivos por los que la subunidad no cumple (vacía si cumple)."""
    motivos = []
    if resultado.variacion_caudal > criterios.variacion_caudal_max + 1e-9:
        motivos.append(f"variación de caudal {resultado.variacion_caudal:.1%} "
                       f"> {criterios.variacion_caudal_max:.0%}")
    if resultado.hay_emisores_fuera_de_rango:
        motivos.append("emisores fuera del rango de compensación")
    if resultado.velocidad_max_ms > criterios.velocidad_max_ms + 1e-9:
        motivos.append(f"velocidad {resultado.velocidad_max_ms:.2f} m/s "
                       f"> {criterios.velocidad_max_ms:g} m/s")
    if (criterios.presion_entrada_max_m is not None
            and resultado.presion_entrada_m > criterios.presion_entrada_max_m + 1e-9):
        motivos.append(f"presión de entrada {resultado.presion_entrada_m:.1f} m "
                       f"> {criterios.presion_entrada_max_m:g} m")
    pn = getattr(tuberia_portalateral, "presion_nominal_m", None)
    if pn and resultado.presion_max_portalateral_m > pn:
        motivos.append(f"supera la presión nominal de la tubería ({pn:g} m)")
    return motivos


@dataclass
class EvaluacionDiametro:
    tuberia: object
    resultado: Optional[ResultadoSubunidad]
    motivos: List[str] = field(default_factory=list)

    @property
    def cumple(self):
        return self.resultado is not None and not self.motivos


def evaluar_diametros(construir: Callable, tuberias, criterios, criterio=None,
                      presion_entrada_m=None):
    """Evalúa cada tubería candidata para el portalateral (cálculo rápido, sin detalle).

    construir(tuberia) debe devolver la Subunidad con esa tubería en el portalateral.
    Si se da presion_entrada_m se evalúa con esa presión; si no, con la requerida.
    Devuelve (evaluaciones ordenadas por diámetro, índice de la más pequeña que cumple
    o None).
    """
    evaluaciones = []
    for tuberia in sorted(tuberias, key=lambda t: t.diametro_interior_mm):
        try:
            subunidad = construir(tuberia)
            if presion_entrada_m is None:
                r = subunidad.presion_entrada_requerida(criterio, detallado=False)
            else:
                r = subunidad.simular(presion_entrada_m, detallado=False)
        except (PresionInsuficiente, ValueError) as error:
            evaluaciones.append(EvaluacionDiametro(tuberia, None, [str(error)]))
            continue
        evaluaciones.append(EvaluacionDiametro(tuberia, r, incumplimientos(r, criterios, tuberia)))
    elegida = next((i for i, e in enumerate(evaluaciones) if e.cumple), None)
    return evaluaciones, elegida
