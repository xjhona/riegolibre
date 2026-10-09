"""Cálculo de portalaterales (tubería terciaria) y de la subunidad de riego.

Cada conexión del portalateral alimenta uno o dos laterales (por ejemplo, a cada
lado). Para no recalcular cada lateral emisor por emisor dentro de la iteración
del portalateral, primero se construye la curva caudal-presión de entrada de cada
lateral distinto; con la solución final se calcula cada lateral en detalle.
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


class CurvaLateral:
    """Relación caudal total - presión de entrada de un lateral (tabla interpolada)."""

    def __init__(self, lateral, presion_final_max_m=120.0, puntos=80):
        presiones_finales = [0.0] + [
            0.05 * (presion_final_max_m / 0.05) ** (i / (puntos - 1)) for i in range(puntos)]
        tabla = []
        for h in presiones_finales:
            r = lateral.simular_desde_final(h)
            tabla.append((r.presion_entrada_m, r.caudal_total_lh))
        tabla.sort()
        self.tabla = []
        for h, q in tabla:
            if not self.tabla or (h > self.tabla[-1][0] and q >= self.tabla[-1][1]):
                self.tabla.append((h, q))

    def caudal(self, presion_entrada_m):
        tabla = self.tabla
        h0, q0 = tabla[0]
        if presion_entrada_m <= h0:
            if presion_entrada_m <= 0 or h0 <= 0:
                return 0.0 if presion_entrada_m <= 0 else q0
            return q0 * (presion_entrada_m / h0) ** 0.5
        if presion_entrada_m >= tabla[-1][0]:
            (h1, q1), (h2, q2) = tabla[-2], tabla[-1]
            if q1 <= 0 or q2 <= q1:
                return q2
            exponente = math.log(q2 / q1) / math.log(h2 / h1)
            return q2 * (presion_entrada_m / h2) ** exponente
        return interpolar_perfil(tabla, presion_entrada_m)


@dataclass
class ConexionLateral:
    distancia_m: float  # desde la entrada del portalateral
    laterales: List[Lateral]


@dataclass
class ResultadoSubunidad:
    distancias_m: List[float]
    cotas_m: List[float]
    presiones_m: List[float]  # en cada conexión del portalateral
    caudales_lh: List[float]  # caudal entregado en cada conexión
    presion_entrada_m: float
    perdida_friccion_m: float
    velocidad_entrada_ms: float
    laterales: Optional[List[List[ResultadoLateral]]] = None  # detalle por conexión

    @property
    def caudal_total_lh(self):
        return sum(self.caudales_lh)

    def _todos(self, atributo):
        if self.laterales is None:
            raise ValueError("Calcule la subunidad con detallado=True para ver los emisores.")
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
    def variacion_caudal(self):
        q = self.caudales_emisores_lh
        return variacion_caudal(max(q), min(q))

    @property
    def variacion_presion_m(self):
        h = self.presiones_emisores_m
        return max(h) - min(h)

    @property
    def emisores_fuera_de_rango(self):
        return sum(r.emisores_fuera_de_rango for conexion in self.laterales for r in conexion)

    @property
    def uniformidad_emision(self):
        q = self.caudales_emisores_lh
        cv = max(r.cv_emisor for conexion in self.laterales for r in conexion)
        return uniformidad_emision_keller(min(q), sum(q) / len(q), cv)

    def cumple(self, variacion_caudal_max=0.20):
        return self.variacion_caudal <= variacion_caudal_max + 1e-9 and self.emisores_fuera_de_rango == 0


@dataclass
class Portalateral:
    tuberia: Tuberia
    conexiones: List[ConexionLateral]
    pendiente: float = 0.0  # m/m, positiva si sube en el sentido del flujo
    perfil: Optional[Sequence[Tuple[float, float]]] = None
    metodo: str = "darcy"
    longitud_equivalente_conexion_m: float = 0.0
    _curvas: dict = field(default_factory=dict, init=False, repr=False, compare=False)

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

    def _curva(self, lateral):
        clave = id(lateral)
        if clave not in self._curvas:
            self._curvas[clave] = (lateral, CurvaLateral(lateral))
        return self._curvas[clave][1]

    def _caudal_conexion(self, conexion, presion):
        return sum(self._curva(lat).caudal(presion) for lat in conexion.laterales)

    @property
    def numero_emisores(self):
        return sum(lat.numero_emisores for c in self.conexiones for lat in c.laterales)

    def simular_desde_final(self, presion_final_m, detallado=False):
        conexiones = self.conexiones
        n = len(conexiones)
        distancias = [c.distancia_m for c in conexiones]
        z = [self.cota(d) for d in distancias]
        presiones = [0.0] * n
        caudales = [0.0] * n
        presiones[-1] = presion_final_m
        acumulado = 0.0
        perdida_total = 0.0
        for i in range(n - 1, -1, -1):
            if i < n - 1:
                tramo = distancias[i + 1] - distancias[i] + self.longitud_equivalente_conexion_m
                hf = self.tuberia.perdida(acumulado * LH_A_M3S, tramo, self.metodo)
                perdida_total += hf
                presiones[i] = presiones[i + 1] + hf + (z[i + 1] - z[i])
            caudales[i] = self._caudal_conexion(conexiones[i], presiones[i])
            acumulado += caudales[i]
        hf = self.tuberia.perdida(acumulado * LH_A_M3S,
                                  distancias[0] + self.longitud_equivalente_conexion_m, self.metodo)
        perdida_total += hf

        detalle = None
        if detallado:
            detalle = []
            for conexion, h in zip(conexiones, presiones):
                detalle.append([lat.simular(h) for lat in conexion.laterales])
            caudales = [sum(r.caudal_total_lh for r in fila) for fila in detalle]
            acumulado = sum(caudales)

        return ResultadoSubunidad(
            distancias_m=distancias,
            cotas_m=z,
            presiones_m=presiones,
            caudales_lh=caudales,
            presion_entrada_m=presiones[0] + hf + z[0],
            perdida_friccion_m=perdida_total,
            velocidad_entrada_ms=self.tuberia.velocidad(acumulado * LH_A_M3S),
            laterales=detalle,
        )

    def _resolver(self, extraer, objetivo, detallado):
        h_final = resolver_creciente(
            lambda h: extraer(self.simular_desde_final(h)), objetivo, 0.0, 10.0, tolerancia=1e-4)
        return self.simular_desde_final(h_final, detallado=detallado)

    def simular(self, presion_entrada_m, detallado=True):
        """Calcula la subunidad para una presión conocida en la entrada del portalateral."""
        try:
            return self._resolver(lambda r: r.presion_entrada_m, presion_entrada_m, detallado)
        except PresionInsuficiente:
            raise PresionInsuficiente(
                f"Con {presion_entrada_m:.2f} m en la entrada el portalateral no llega a "
                "presurizarse por completo.") from None

    def presion_entrada_requerida(self, criterio=None, detallado=True):
        """Presión en la entrada del portalateral según el criterio de diseño.

        - caudal_medio: el caudal medio de todos los emisores es el nominal.
        - presion_minima: el lateral más desfavorecido recibe justo la presión
          que necesita para que su emisor más desfavorecido alcance la presión
          mínima (emisores autocompensados).
        """
        emisores = {id(lat.emisor): lat.emisor for c in self.conexiones for lat in c.laterales}
        if criterio is None:
            todos_compensados = all(e.autocompensado for e in emisores.values())
            criterio = CRITERIO_PRESION_MINIMA if todos_compensados else CRITERIO_CAUDAL_MEDIO

        if criterio == CRITERIO_CAUDAL_MEDIO:
            objetivo = sum(lat.emisor.caudal_nominal_lh * lat.numero_emisores
                           for c in self.conexiones for lat in c.laterales)
            return self._resolver(lambda r: r.caudal_total_lh, objetivo, detallado)

        if criterio == CRITERIO_PRESION_MINIMA:
            requeridas = {}
            for c in self.conexiones:
                for lat in c.laterales:
                    if id(lat) not in requeridas:
                        requeridas[id(lat)] = lat.presion_entrada_requerida(
                            CRITERIO_PRESION_MINIMA).presion_entrada_m
            necesidad = [max(requeridas[id(lat)] for lat in c.laterales) for c in self.conexiones]

            def margen_minimo(r):
                return min(h - req for h, req in zip(r.presiones_m, necesidad))

            return self._resolver(margen_minimo, 0.0, detallado)

        raise ValueError(f"Criterio desconocido: {criterio!r}")


def portalateral_uniforme(tuberia, lateral_izquierdo, lateral_derecho, separacion_laterales_m,
                          numero_conexiones, distancia_primera_conexion_m=None, **kwargs):
    """Portalateral con conexiones equidistantes y los mismos laterales en cada una.

    Cualquiera de los dos laterales puede ser None (portalateral en un extremo).
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
