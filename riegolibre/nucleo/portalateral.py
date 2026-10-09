"""Cálculo de portalaterales (tubería terciaria que alimenta a los laterales).

Cada conexión del portalateral alimenta uno o dos laterales (por ejemplo, a cada
lado). Dentro de la iteración del portalateral cada lateral se representa con su
curva presión-caudal (ver CurvaLateral); con la solución final, y si se pide el
cálculo detallado, se calcula cada lateral emisor por emisor.

El portalateral puede ser telescópico: a partir de ciertas distancias desde la
entrada cambia a una tubería de menor diámetro (reducciones).
"""

import math
from dataclasses import dataclass, field
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
class SeccionPortalateral:
    """Tramo del portalateral con una misma tubería."""
    tuberia: Tuberia
    desde_m: float  # desde la entrada
    hasta_m: float
    presion_max_m: float
    velocidad_max_ms: float

    @property
    def longitud_m(self):
        return self.hasta_m - self.desde_m


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
    velocidad_max_ms: float = 0.0  # en todo el portalateral (en uno telescópico puede no ser la de entrada)
    secciones: List[SeccionPortalateral] = field(default_factory=list)


@dataclass
class Portalateral:
    tuberia: Tuberia  # la de la entrada
    conexiones: List[ConexionLateral]
    pendiente: float = 0.0  # m/m, positiva si sube en el sentido del flujo
    perfil: Optional[Sequence[Tuple[float, float]]] = None
    metodo: str = "darcy"
    longitud_equivalente_conexion_m: float = 0.0
    sentido: int = 1  # +1 si avanza en el sentido del portalateral dibujado, -1 si retrocede
    # Portalateral telescópico: [(distancia desde la entrada, tubería desde allí hacia el final)].
    reducciones: Sequence[Tuple[float, Tuberia]] = ()

    def __post_init__(self):
        if not self.conexiones:
            raise ValueError("El portalateral necesita al menos una conexión.")
        self.conexiones = sorted(self.conexiones, key=lambda c: c.distancia_m)
        if self.perfil is not None:
            self.perfil = sorted((float(d), float(z)) for d, z in self.perfil)
        self.reducciones = sorted(((float(d), t) for d, t in self.reducciones), key=lambda r: r[0])
        self._tramos = None

    @property
    def tuberias(self):
        """Tuberías usadas, de la entrada al final."""
        return [self.tuberia] + [t for _, t in self.reducciones]

    def tuberia_en(self, distancia):
        """Tubería en un punto (distancia desde la entrada); en una reducción, la de aguas abajo."""
        tuberia = self.tuberia
        for desde, t in self.reducciones:
            if distancia >= desde - 1e-9:
                tuberia = t
        return tuberia

    def piezas(self, desde, hasta):
        """[(tubería, inicio, fin)] entre dos distancias desde la entrada."""
        inicios = [0.0] + [d for d, _ in self.reducciones]
        piezas = []
        for i, tuberia in enumerate(self.tuberias):
            fin = inicios[i + 1] if i + 1 < len(inicios) else math.inf
            a, b = max(desde, inicios[i]), min(hasta, fin)
            if b > a + 1e-9:
                piezas.append((tuberia, a, b))
        return piezas

    def _tramos_hidraulicos(self):
        """Por cada tramo (entrada → conexión 0, conexión i → i+1): [(tubería, longitud)].

        La longitud equivalente de la conexión se suma a la primera pieza del tramo.
        """
        if self._tramos is None:
            distancias = [0.0] + [c.distancia_m for c in self.conexiones]
            self._tramos = []
            for a, b in zip(distancias, distancias[1:]):
                piezas = [[t, fin - inicio] for t, inicio, fin in self.piezas(a, b)] or [[self.tuberia_en(a), 0.0]]
                piezas[0][1] += self.longitud_equivalente_conexion_m
                self._tramos.append([tuple(p) for p in piezas])
        return self._tramos

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

    def simular_desde_final(self, presion_final_m, detallado=False, con_secciones=False):
        conexiones = self.conexiones
        tramos = self._tramos_hidraulicos()
        metodo = self.metodo
        velocidad_max = 0.0
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
                q = acumulado * LH_A_M3S
                hf = 0.0
                for tuberia, longitud in tramos[i + 1]:
                    hf += tuberia.perdida(q, longitud, metodo)
                    velocidad_max = max(velocidad_max, tuberia.velocidad(q))
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
        q = acumulado * LH_A_M3S
        hf = 0.0
        for tuberia, longitud in tramos[0]:
            hf += tuberia.perdida(q, longitud, metodo)
            velocidad_max = max(velocidad_max, tuberia.velocidad(q))
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

        presion_entrada = presiones[0] + hf + z[0]
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
            presion_entrada_m=presion_entrada,
            perdida_friccion_m=perdida_total,
            velocidad_entrada_ms=self.tuberia.velocidad(acumulado * LH_A_M3S),
            numero_emisores=self.numero_emisores,
            cv=max(lat.emisor.cv for lat in self.laterales),
            laterales=detalle,
            sentido=self.sentido,
            velocidad_max_ms=velocidad_max,
            secciones=(self._secciones(distancias, presiones, caudales, presion_entrada)
                       if detallado or con_secciones else []),
        )

    def _secciones(self, distancias, presiones, caudales, presion_entrada):
        """Presión y velocidad máximas en cada tramo de una misma tubería."""
        perfil = [(0.0, presion_entrada)] + list(zip(distancias, presiones))
        secciones = []
        for tuberia, desde, hasta in self.piezas(0.0, self.longitud_m):
            puntos = [desde, hasta] + [d for d in distancias if desde < d < hasta]
            presion = max(interpolar_perfil(perfil, d) for d in puntos)
            # El mayor caudal de la sección es el que entra en ella: el de las conexiones
            # aguas abajo de su inicio (una conexión justo en la reducción toma el agua antes).
            q = sum(c for d, c in zip(distancias, caudales) if desde == 0.0 or d > desde + 1e-9)
            secciones.append(SeccionPortalateral(tuberia, desde, hasta, presion,
                                                 tuberia.velocidad(q * LH_A_M3S)))
        return secciones

    def _resolver(self, extraer, objetivo, detallado):
        h_final = resolver_creciente(
            lambda h: extraer(self.simular_desde_final(h)), objetivo, 0.0, 10.0, tolerancia=1e-4)
        return self.simular_desde_final(h_final, detallado=detallado, con_secciones=True)

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
