"""Cálculo de portalaterales (tubería terciaria que alimenta a los laterales).

Cada conexión del portalateral alimenta uno o dos laterales (por ejemplo, a cada
lado). Dentro de la iteración del portalateral cada lateral se representa con su
curva presión-caudal (ver CurvaLateral); con la solución final, y si se pide el
cálculo detallado, se calcula cada lateral emisor por emisor.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .hidraulica import (LH_A_M3S, PresionInsuficiente, interpolar_perfil,
                         resolver_creciente)
from .lateral import (CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA, Lateral,
                      ResultadoLateral)
from .tuberias import Tuberia
from .uniformidad import uniformidad_emision_keller, variacion_caudal


@dataclass
class ConexionLateral:
    distancia_m: float  # desde la entrada del portalateral
    laterales: List[Lateral]


class EstadisticasEmisores:
    """Indicadores comunes a portalaterales y subunidades.

    Requiere las listas por conexión: caudales_lh, h_min_m, h_max_m, q_min_lh,
    q_max_lh, fuera_de_rango; y los atributos numero_emisores, cv y laterales.
    """

    @property
    def caudal_total_lh(self):
        return sum(self.caudales_lh)

    @property
    def caudal_medio_lh(self):
        return self.caudal_total_lh / self.numero_emisores

    @property
    def caudal_min_lh(self):
        return min(self.q_min_lh)

    @property
    def caudal_max_lh(self):
        return max(self.q_max_lh)

    @property
    def presion_min_emisor_m(self):
        return min(self.h_min_m)

    @property
    def presion_max_emisor_m(self):
        return max(self.h_max_m)

    @property
    def variacion_caudal(self):
        return variacion_caudal(self.caudal_max_lh, self.caudal_min_lh)

    @property
    def variacion_presion_m(self):
        return self.presion_max_emisor_m - self.presion_min_emisor_m

    @property
    def uniformidad_emision(self):
        return uniformidad_emision_keller(self.caudal_min_lh, self.caudal_medio_lh, self.cv)

    @property
    def hay_emisores_fuera_de_rango(self):
        return any(self.fuera_de_rango)

    # Solo con cálculo detallado (emisor por emisor):

    def _todos(self, atributo):
        if self.laterales is None:
            raise ValueError("Calcule con detallado=True para ver cada emisor.")
        valores = []
        for conexion in self.laterales:
            for r in conexion:
                valores.extend(getattr(r, atributo))
        return valores

    @property
    def caudales_emisores_lh(self):
        return self._todos("caudales_lh")

    @property
    def presiones_emisores_m(self):
        return self._todos("presiones_m")

    @property
    def emisores_fuera_de_rango(self):
        if self.laterales is None:
            raise ValueError("Calcule con detallado=True para contar los emisores fuera de rango.")
        return sum(r.emisores_fuera_de_rango for conexion in self.laterales for r in conexion)

    def cumple(self, variacion_caudal_max=0.10):
        return (self.variacion_caudal <= variacion_caudal_max + 1e-9
                and not self.hay_emisores_fuera_de_rango)


@dataclass
class ResultadoPortalateral(EstadisticasEmisores):
    distancias_m: List[float]
    cotas_m: List[float]  # relativas a la entrada
    presiones_m: List[float]  # en el portalateral, en cada conexión
    caudales_lh: List[float]  # caudal entregado en cada conexión
    h_min_m: List[float]  # presión mínima de emisor de los laterales de cada conexión
    h_max_m: List[float]
    q_min_lh: List[float]
    q_max_lh: List[float]
    fuera_de_rango: List[bool]
    presion_entrada_m: float
    perdida_friccion_m: float
    velocidad_entrada_ms: float
    numero_emisores: int
    cv: float
    laterales: Optional[List[List[ResultadoLateral]]] = None  # detalle por conexión
    sentido: int = 1  # +1 si avanza en el sentido del portalateral, -1 si retrocede


@dataclass
class Portalateral:
    tuberia: Tuberia
    conexiones: List[ConexionLateral]
    pendiente: float = 0.0  # m/m, positiva si sube en el sentido del flujo
    perfil: Optional[Sequence[Tuple[float, float]]] = None
    metodo: str = "darcy"
    longitud_equivalente_conexion_m: float = 0.0
    sentido: int = 1  # +1 si avanza en el sentido del portalateral dibujado, -1 si retrocede

    def __post_init__(self):
        if not self.conexiones:
            raise ValueError("El portalateral necesita al menos una conexión.")
        self.conexiones = sorted(self.conexiones, key=lambda c: c.distancia_m)
        if self.perfil is not None:
            self.perfil = sorted((float(d), float(z)) for d, z in self.perfil)

    def cota(self, distancia):
        if self.perfil is not None:
            return interpolar_perfil(self.perfil, distancia) - interpolar_perfil(self.perfil, 0.0)
        return self.pendiente * distancia

    @property
    def longitud_m(self):
        return self.conexiones[-1].distancia_m

    @property
    def laterales(self):
        return [lat for c in self.conexiones for lat in c.laterales]

    @property
    def numero_emisores(self):
        return sum(lat.numero_emisores for lat in self.laterales)

    def simular_desde_final(self, presion_final_m, detallado=False):
        conexiones = self.conexiones
        n = len(conexiones)
        distancias = [c.distancia_m for c in conexiones]
        z = [self.cota(d) for d in distancias]
        presiones = [0.0] * n
        caudales = [0.0] * n
        h_min, h_max = [0.0] * n, [0.0] * n
        q_min, q_max = [0.0] * n, [0.0] * n
        fuera = [False] * n
        presiones[-1] = presion_final_m
        acumulado = 0.0
        perdida_total = 0.0
        for i in range(n - 1, -1, -1):
            if i < n - 1:
                tramo = distancias[i + 1] - distancias[i] + self.longitud_equivalente_conexion_m
                hf = self.tuberia.perdida(acumulado * LH_A_M3S, tramo, self.metodo)
                perdida_total += hf
                presiones[i] = presiones[i + 1] + hf + (z[i + 1] - z[i])
            caudal = 0.0
            minimos, maximos = [], []
            for lat in conexiones[i].laterales:
                q, hmin, hmax = lat.curva().estado(presiones[i])
                caudal += q
                minimos.append((hmin, lat.emisor))
                maximos.append((hmax, lat.emisor))
            caudales[i] = caudal
            h_min[i] = min(h for h, _ in minimos)
            h_max[i] = max(h for h, _ in maximos)
            q_min[i] = min(e.caudal(h) for h, e in minimos)
            q_max[i] = max(e.caudal(h) for h, e in maximos)
            fuera[i] = any(e.fuera_de_rango(h) for h, e in minimos + maximos)
            acumulado += caudal
        hf = self.tuberia.perdida(acumulado * LH_A_M3S,
                                  distancias[0] + self.longitud_equivalente_conexion_m, self.metodo)
        perdida_total += hf

        detalle = None
        if detallado:
            detalle = []
            for i, (conexion, h) in enumerate(zip(conexiones, presiones)):
                fila = [lat.simular(h) for lat in conexion.laterales]
                detalle.append(fila)
                caudales[i] = sum(r.caudal_total_lh for r in fila)
                h_min[i] = min(r.presion_min_m for r in fila)
                h_max[i] = max(r.presion_max_m for r in fila)
                q_min[i] = min(r.caudal_min_lh for r in fila)
                q_max[i] = max(r.caudal_max_lh for r in fila)
                fuera[i] = any(r.emisores_fuera_de_rango for r in fila)
            acumulado = sum(caudales)

        return ResultadoPortalateral(
            distancias_m=distancias,
            cotas_m=z,
            presiones_m=presiones,
            caudales_lh=caudales,
            h_min_m=h_min,
            h_max_m=h_max,
            q_min_lh=q_min,
            q_max_lh=q_max,
            fuera_de_rango=fuera,
            presion_entrada_m=presiones[0] + hf + z[0],
            perdida_friccion_m=perdida_total,
            velocidad_entrada_ms=self.tuberia.velocidad(acumulado * LH_A_M3S),
            numero_emisores=self.numero_emisores,
            cv=max(lat.emisor.cv for lat in self.laterales),
            laterales=detalle,
            sentido=self.sentido,
        )

    def _resolver(self, extraer, objetivo, detallado):
        h_final = resolver_creciente(
            lambda h: extraer(self.simular_desde_final(h)), objetivo, 0.0, 10.0, tolerancia=1e-4)
        return self.simular_desde_final(h_final, detallado=detallado)

    def simular(self, presion_entrada_m, detallado=True):
        """Calcula el portalateral para una presión conocida en su entrada."""
        try:
            return self._resolver(lambda r: r.presion_entrada_m, presion_entrada_m, detallado)
        except PresionInsuficiente:
            raise PresionInsuficiente(
                f"Con {presion_entrada_m:.2f} m en la entrada el portalateral no llega a "
                "presurizarse por completo.") from None

    def presion_entrada_requerida(self, criterio=None, detallado=True):
        """Presión en la entrada del portalateral según el criterio de diseño.

        - caudal_medio: el caudal medio de todos los emisores es el nominal.
        - presion_minima: el emisor más desfavorecido recibe la presión mínima
          (emisores autocompensados).
        """
        criterio = criterio or criterio_por_defecto(self.laterales)
        if criterio == CRITERIO_CAUDAL_MEDIO:
            objetivo = sum(lat.emisor.caudal_nominal_lh * lat.numero_emisores for lat in self.laterales)
            return self._resolver(lambda r: r.caudal_total_lh, objetivo, detallado)
        if criterio == CRITERIO_PRESION_MINIMA:
            minima = presion_minima_requerida(self.laterales)
            r = self._resolver(lambda r: r.presion_min_emisor_m, minima, detallado)
            return corregir_presion_minima(r, minima, self.simular) if detallado else r
        raise ValueError(f"Criterio desconocido: {criterio!r}")


def presion_minima_requerida(laterales):
    return min(lat.emisor.presion_compensacion_m for lat in laterales)


def corregir_presion_minima(resultado, minima, simular, tolerancia=0.002):
    """Ajusta la presión de entrada con el cálculo detallado.

    La solución con curvas interpoladas puede dejar al emisor más desfavorecido
    unos milímetros por debajo de la presión mínima; como las presiones de los
    emisores siguen casi 1:1 a la de entrada, se sube lo que falte.
    """
    for _ in range(5):
        deficit = minima - resultado.presion_min_emisor_m
        if deficit <= 0:
            break
        resultado = simular(resultado.presion_entrada_m + deficit + tolerancia, detallado=True)
    return resultado


def criterio_por_defecto(laterales):
    if all(lat.emisor.autocompensado for lat in laterales):
        return CRITERIO_PRESION_MINIMA
    return CRITERIO_CAUDAL_MEDIO


def portalateral_uniforme(tuberia, lateral_izquierdo, lateral_derecho, separacion_laterales_m,
                          numero_conexiones, distancia_primera_conexion_m=None, **kwargs):
    """Portalateral con conexiones equidistantes y los mismos laterales en cada una.

    Cualquiera de los dos laterales puede ser None (portalateral en un borde).
    """
    if distancia_primera_conexion_m is None:
        distancia_primera_conexion_m = separacion_laterales_m / 2
    laterales = [lat for lat in (lateral_izquierdo, lateral_derecho) if lat is not None]
    if not laterales:
        raise ValueError("Indique al menos un lateral.")
    conexiones = [
        ConexionLateral(distancia_primera_conexion_m + i * separacion_laterales_m, laterales)
        for i in range(numero_conexiones)
    ]
    return Portalateral(tuberia, conexiones, **kwargs)
