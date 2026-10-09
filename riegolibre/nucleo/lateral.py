"""Cálculo hidráulico de laterales de goteo, emisor por emisor.

El lateral se recorre desde el último emisor hacia la entrada (método paso a paso):
partiendo de una presión en el extremo final se acumulan caudales, pérdidas por
fricción y desniveles hasta llegar a la entrada. Así se consideran la variación
real del caudal de cada emisor y el perfil del terreno, sin usar el factor F de
Christiansen.

Convención de cotas: la pendiente es positiva cuando el terreno sube en el
sentido del flujo (de la entrada hacia el final del lateral).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .emisores import Emisor
from .hidraulica import (LH_A_M3S, PresionInsuficiente, interpolar_perfil,
                         resolver_creciente)
from .tuberias import Tuberia
from .uniformidad import uniformidad_emision_keller, variacion_caudal

CRITERIO_CAUDAL_MEDIO = "caudal_medio"
CRITERIO_PRESION_MINIMA = "presion_minima"


@dataclass
class ResultadoLateral:
    posiciones_m: List[float]
    cotas_m: List[float]  # relativas a la entrada del lateral
    presiones_m: List[float]
    caudales_lh: List[float]
    presion_entrada_m: float
    perdida_friccion_m: float
    velocidad_entrada_ms: float
    cv_emisor: float
    emisores_fuera_de_rango: int = 0

    @property
    def numero_emisores(self):
        return len(self.caudales_lh)

    @property
    def caudal_total_lh(self):
        return sum(self.caudales_lh)

    @property
    def presion_min_m(self):
        return min(self.presiones_m)

    @property
    def presion_max_m(self):
        return max(self.presiones_m)

    @property
    def presion_media_m(self):
        return sum(self.presiones_m) / len(self.presiones_m)

    @property
    def caudal_min_lh(self):
        return min(self.caudales_lh)

    @property
    def caudal_max_lh(self):
        return max(self.caudales_lh)

    @property
    def caudal_medio_lh(self):
        return self.caudal_total_lh / len(self.caudales_lh)

    @property
    def variacion_presion_m(self):
        return self.presion_max_m - self.presion_min_m

    @property
    def variacion_caudal(self):
        return variacion_caudal(self.caudal_max_lh, self.caudal_min_lh)

    @property
    def uniformidad_emision(self):
        return uniformidad_emision_keller(self.caudal_min_lh, self.caudal_medio_lh, self.cv_emisor)

    def cumple(self, variacion_caudal_max=0.10):
        return self.variacion_caudal <= variacion_caudal_max + 1e-9 and self.emisores_fuera_de_rango == 0


@dataclass
class Lateral:
    tuberia: Tuberia
    emisor: Emisor
    espaciamiento_m: float
    numero_emisores: int
    distancia_primer_emisor_m: Optional[float] = None  # por defecto = espaciamiento
    pendiente: float = 0.0  # m/m, positiva si sube en el sentido del flujo
    perfil: Optional[Sequence[Tuple[float, float]]] = None  # [(distancia, cota)], reemplaza la pendiente
    metodo: str = "darcy"
    _cotas: Optional[List[float]] = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.numero_emisores < 1:
            raise ValueError("El lateral debe tener al menos un emisor.")
        if self.espaciamiento_m <= 0:
            raise ValueError("El espaciamiento entre emisores debe ser mayor que cero.")
        if self.distancia_primer_emisor_m is None:
            self.distancia_primer_emisor_m = self.espaciamiento_m
        if self.perfil is not None:
            self.perfil = sorted((float(d), float(z)) for d, z in self.perfil)
            if len(self.perfil) < 2:
                raise ValueError("El perfil del terreno necesita al menos dos puntos.")

    @classmethod
    def desde_longitud(cls, tuberia, emisor, espaciamiento_m, longitud_m, **kwargs):
        """Crea un lateral con tantos emisores como quepan en la longitud dada."""
        d1 = kwargs.get("distancia_primer_emisor_m")
        if d1 is None:
            d1 = espaciamiento_m
        n = int((longitud_m - d1) / espaciamiento_m + 1e-9) + 1
        return cls(tuberia, emisor, espaciamiento_m, max(n, 1), **kwargs)

    @property
    def longitud_m(self):
        return self.distancia_primer_emisor_m + (self.numero_emisores - 1) * self.espaciamiento_m

    def posiciones(self):
        d1, s = self.distancia_primer_emisor_m, self.espaciamiento_m
        return [d1 + i * s for i in range(self.numero_emisores)]

    def cota(self, distancia):
        """Cota del terreno relativa a la entrada del lateral."""
        if self.perfil is not None:
            return interpolar_perfil(self.perfil, distancia) - interpolar_perfil(self.perfil, 0.0)
        return self.pendiente * distancia

    def cotas(self):
        if self._cotas is None:
            self._cotas = [self.cota(x) for x in self.posiciones()]
        return self._cotas

    # ------------------------------------------------------------------ cálculo

    def simular_desde_final(self, presion_final_m):
        """Calcula el lateral fijando la presión en el último emisor."""
        tuberia, emisor, metodo = self.tuberia, self.emisor, self.metodo
        n = self.numero_emisores
        z = self.cotas()
        tramo = self.espaciamiento_m + emisor.longitud_equivalente_m

        presiones = [0.0] * n
        caudales = [0.0] * n
        presiones[-1] = presion_final_m
        caudal_acumulado = 0.0  # L/h que circula aguas abajo del emisor actual
        perdida_total = 0.0
        for i in range(n - 1, -1, -1):
            if i < n - 1:
                hf = tuberia.perdida(caudal_acumulado * LH_A_M3S, tramo, metodo)
                perdida_total += hf
                presiones[i] = presiones[i + 1] + hf + (z[i + 1] - z[i])
            caudales[i] = emisor.caudal(presiones[i])
            caudal_acumulado += caudales[i]

        tramo_entrada = self.distancia_primer_emisor_m + emisor.longitud_equivalente_m
        hf = tuberia.perdida(caudal_acumulado * LH_A_M3S, tramo_entrada, metodo)
        perdida_total += hf
        presion_entrada = presiones[0] + hf + z[0]

        fuera = sum(1 for h in presiones if emisor.fuera_de_rango(h))
        return ResultadoLateral(
            posiciones_m=self.posiciones(),
            cotas_m=list(z),
            presiones_m=presiones,
            caudales_lh=caudales,
            presion_entrada_m=presion_entrada,
            perdida_friccion_m=perdida_total,
            velocidad_entrada_ms=tuberia.velocidad(caudal_acumulado * LH_A_M3S),
            cv_emisor=emisor.cv,
            emisores_fuera_de_rango=fuera,
        )

    def _resolver(self, extraer, objetivo):
        """Busca la presión final que hace extraer(resultado) == objetivo."""
        ultimo = {}

        def funcion(h_final):
            ultimo["r"] = self.simular_desde_final(h_final)
            return extraer(ultimo["r"])

        h_inicial = max(self.emisor.presion_nominal_m, 1.0)
        h_final = resolver_creciente(funcion, objetivo, 0.0, h_inicial, tolerancia=1e-4)
        resultado = ultimo["r"]
        if resultado.presiones_m[-1] != h_final:
            resultado = self.simular_desde_final(h_final)
        return resultado

    def simular(self, presion_entrada_m):
        """Calcula el lateral para una presión de entrada conocida."""
        try:
            return self._resolver(lambda r: r.presion_entrada_m, presion_entrada_m)
        except PresionInsuficiente:
            raise PresionInsuficiente(
                f"Con {presion_entrada_m:.2f} m en la entrada el lateral no llega a "
                "presurizarse por completo (el final queda sin presión).") from None

    def presion_entrada_requerida(self, criterio=None):
        """Presión de entrada necesaria según el criterio de diseño.

        - caudal_medio: el caudal medio de los emisores es igual al nominal
          (por defecto en emisores no compensados).
        - presion_minima: el emisor más desfavorecido recibe la presión mínima
          (inicio del rango de compensación o presión nominal). Por defecto en
          emisores autocompensados.
        """
        if criterio is None:
            criterio = CRITERIO_PRESION_MINIMA if self.emisor.autocompensado else CRITERIO_CAUDAL_MEDIO
        if criterio == CRITERIO_CAUDAL_MEDIO:
            return self._resolver(lambda r: r.caudal_medio_lh, self.emisor.caudal_nominal_lh)
        if criterio == CRITERIO_PRESION_MINIMA:
            return self._resolver(lambda r: r.presion_min_m, self.emisor.presion_compensacion_m)
        raise ValueError(f"Criterio desconocido: {criterio!r}")


def longitud_maxima(tuberia, emisor, espaciamiento_m, pendiente=0.0,
                    distancia_primer_emisor_m=None, variacion_caudal_max=0.10,
                    presion_entrada_max_m=None, longitud_limite_m=500.0,
                    metodo="darcy", criterio=None):
    """Longitud máxima de un lateral que cumple la variación de caudal admitida.

    Devuelve (longitud_m, ResultadoLateral) o (0.0, None) si ni el lateral más
    corto cumple. Para emisores autocompensados también se exige que todos los
    emisores queden dentro del rango de compensación.
    """
    if distancia_primer_emisor_m is None:
        distancia_primer_emisor_m = espaciamiento_m
    n_limite = int((longitud_limite_m - distancia_primer_emisor_m) / espaciamiento_m + 1e-9) + 1

    resultados = {}

    def evaluar(n):
        if n not in resultados:
            lateral = Lateral(tuberia, emisor, espaciamiento_m, n,
                              distancia_primer_emisor_m=distancia_primer_emisor_m,
                              pendiente=pendiente, metodo=metodo)
            try:
                r = lateral.presion_entrada_requerida(criterio)
            except PresionInsuficiente:
                resultados[n] = None
            else:
                ok = r.cumple(variacion_caudal_max) and (
                    presion_entrada_max_m is None or r.presion_entrada_m <= presion_entrada_max_m)
                resultados[n] = r if ok else None
        return resultados[n]

    # Barrido geométrico (la variación puede no ser monótona en terrenos en bajada)...
    grilla = []
    n = 1
    while n < n_limite:
        grilla.append(n)
        n = max(n + 1, int(n * 1.08))
    grilla.append(n_limite)

    mejor = None
    for indice, n in enumerate(grilla):
        if evaluar(n) is not None:
            mejor = indice
    if mejor is None:
        return 0.0, None

    # ...y refinamiento por bisección entre el último punto que cumple y el siguiente.
    bajo = grilla[mejor]
    if mejor + 1 < len(grilla):
        alto = grilla[mejor + 1]
        while alto - bajo > 1:
            medio = (bajo + alto) // 2
            if evaluar(medio) is not None:
                bajo = medio
            else:
                alto = medio
    resultado = resultados[bajo]
    return resultado.posiciones_m[-1], resultado
