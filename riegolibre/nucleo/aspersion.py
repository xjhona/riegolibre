# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Riego por aspersión: aspersor con su elevador, marco de riego y lateral de aspersores.

El aspersor cumple la misma ecuación que un gotero, q = k·hᵇ (h: presión en la boquilla), así que el
lateral se calcula con el mismo motor paso a paso del goteo (`lateral.Lateral`). La diferencia es el
elevador: entre la tubería lateral y la boquilla se pierden la altura del elevador y su fricción, de modo
que el aspersor, visto desde el lateral, se comporta como un emisor cuya presión útil es

    h_boquilla = h_lateral − altura_elevador − hf_elevador(q)

Unidades: caudales del aspersor en m³/h (el motor del lateral trabaja en L/h), presiones en m.c.a.,
intensidad de aplicación (pluviometría) en mm/h.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from .hidraulica import G, PresionInsuficiente, area, perdida_darcy, perdida_localizada
from .lateral import CRITERIO_CAUDAL_MEDIO, Lateral

RUTA_CATALOGO = os.path.join(os.path.dirname(__file__), "datos", "aspersores.json")

DISPOSICION_RECTANGULAR = "rectangular"  # también el cuadrado
DISPOSICION_TRIANGULAR = "triangular"  # aspersores de laterales vecinos desfasados medio espaciamiento

# Separación máxima entre aspersores (y entre laterales) como fracción del diámetro mojado, según el viento.
# Valores habituales de los manuales de aspersión; por confirmar con el usuario.
FACTORES_SOLAPE = {
    DISPOSICION_RECTANGULAR: ((2.0, 0.60), (4.0, 0.50), (None, 0.40)),
    DISPOSICION_TRIANGULAR: ((2.0, 0.65), (4.0, 0.55), (None, 0.45)),
}

VARIACION_PRESION_ADMISIBLE = 0.20  # regla de Christiansen: Δh ≤ 20 % de la presión nominal (Δq ≈ 10 %)
RUGOSIDAD_ELEVADOR_MM = 0.15  # acero galvanizado
K_ELEVADOR = 1.0  # te de salida y rosca del aspersor


@dataclass
class Elevador:
    """Tubo vertical entre el lateral y el aspersor («riser»)."""
    altura_m: float = 0.0
    diametro_interior_mm: Optional[float] = None  # None: sin pérdidas por fricción
    rugosidad_mm: float = RUGOSIDAD_ELEVADOR_MM
    k_local: float = K_ELEVADOR

    def perdida(self, caudal_m3h):
        """Pérdida de carga (m) en el elevador: fricción a lo largo de su altura más la localizada."""
        if self.diametro_interior_mm is None or caudal_m3h <= 0:
            return 0.0
        q = caudal_m3h / 3600.0
        d = self.diametro_interior_mm / 1000.0
        return (perdida_darcy(q, d, self.altura_m, self.rugosidad_mm / 1000.0)
                + perdida_localizada(q, d, self.k_local))

    def velocidad(self, caudal_m3h):
        if self.diametro_interior_mm is None:
            return 0.0
        return caudal_m3h / 3600.0 / area(self.diametro_interior_mm / 1000.0)


@dataclass
class Aspersor:
    nombre: str
    caudal_nominal_m3h: float
    presion_nominal_m: float
    diametro_mojado_m: float
    exponente: float = 0.5
    boquilla_mm: Optional[float] = None
    presion_min_m: Optional[float] = None  # rango de trabajo del fabricante
    presion_max_m: Optional[float] = None
    cv: float = 0.0  # variación de fabricación (en aspersión casi no se usa)

    @property
    def k(self):
        """q (m³/h) = k·hᵇ."""
        return self.caudal_nominal_m3h / self.presion_nominal_m ** self.exponente

    def caudal_m3h(self, presion_boquilla_m):
        if presion_boquilla_m <= 0:
            return 0.0
        return self.k * presion_boquilla_m ** self.exponente

    def presion_para_caudal(self, caudal_m3h):
        return (caudal_m3h / self.k) ** (1.0 / self.exponente)

    @property
    def radio_m(self):
        return self.diametro_mojado_m / 2.0

    def fuera_de_rango(self, presion_boquilla_m, tolerancia=0.01):
        if self.presion_min_m is not None and presion_boquilla_m < self.presion_min_m - tolerancia:
            return True
        return self.presion_max_m is not None and presion_boquilla_m > self.presion_max_m + tolerancia


class SalidaAspersor:
    """Un aspersor sobre su elevador, visto desde el lateral: tiene la interfaz de `emisores.Emisor`.

    Recibe la presión en la tubería lateral y devuelve el caudal en L/h, resolviendo la presión en la
    boquilla con la altura y la pérdida del elevador.
    """

    autocompensado = False
    longitud_equivalente_m = 0.0
    tipo = "aspersor"

    def __init__(self, aspersor, elevador=None):
        self.aspersor = aspersor
        self.elevador = elevador or Elevador()
        self.nombre = aspersor.nombre
        self.exponente = aspersor.exponente
        self.cv = aspersor.cv
        self.presion_max_m = None

    @property
    def caudal_nominal_lh(self):
        return self.aspersor.caudal_nominal_m3h * 1000.0

    @property
    def presion_nominal_m(self):
        return self.presion_en_lateral(self.aspersor.presion_nominal_m)

    @property
    def presion_compensacion_m(self):
        """Presión en el lateral con la que la boquilla recibe su presión nominal."""
        return self.presion_nominal_m

    def presion_en_lateral(self, presion_boquilla_m):
        q = self.aspersor.caudal_m3h(presion_boquilla_m)
        return presion_boquilla_m + self.elevador.altura_m + self.elevador.perdida(q)

    def presion_boquilla(self, presion_lateral_m):
        """Presión en la boquilla (m) para una presión dada en la tubería lateral."""
        disponible = presion_lateral_m - self.elevador.altura_m
        if disponible <= 0:
            return 0.0
        if self.elevador.diametro_interior_mm is None:
            return disponible
        bajo, alto = 0.0, disponible  # h + hf(q(h)) crece con h: bisección
        for _ in range(60):
            medio = (bajo + alto) / 2
            if self.presion_en_lateral(medio) > presion_lateral_m:
                alto = medio
            else:
                bajo = medio
            if alto - bajo < 1e-6:
                break
        return (bajo + alto) / 2

    def caudal(self, presion_lateral_m):
        """Caudal (L/h) del aspersor con una presión dada en el lateral."""
        return self.aspersor.caudal_m3h(self.presion_boquilla(presion_lateral_m)) * 1000.0

    def presion_para_caudal(self, caudal_lh):
        return self.presion_en_lateral(self.aspersor.presion_para_caudal(caudal_lh / 1000.0))

    def fuera_de_rango(self, presion_lateral_m, tolerancia=0.01):
        return self.aspersor.fuera_de_rango(self.presion_boquilla(presion_lateral_m), tolerancia)


# --------------------------------------------------------------------------- marco de riego

def factor_solape(viento_ms, disposicion=DISPOSICION_RECTANGULAR):
    for limite, factor in FACTORES_SOLAPE[disposicion]:
        if limite is None or viento_ms < limite:
            return factor
    return FACTORES_SOLAPE[disposicion][-1][1]


@dataclass
class Marco:
    """Disposición de los aspersores en el campo."""
    espaciamiento_aspersores_m: float  # a lo largo del lateral
    espaciamiento_laterales_m: float
    disposicion: str = DISPOSICION_RECTANGULAR

    def __post_init__(self):
        if self.espaciamiento_aspersores_m <= 0 or self.espaciamiento_laterales_m <= 0:
            raise ValueError("Los espaciamientos del marco deben ser mayores que cero.")
        if self.disposicion not in FACTORES_SOLAPE:
            raise ValueError(f"Disposición desconocida: {self.disposicion!r}.")

    @property
    def area_m2(self):
        """Superficie que riega cada aspersor (la misma en marco rectangular o triangular)."""
        return self.espaciamiento_aspersores_m * self.espaciamiento_laterales_m

    def intensidad_mm_h(self, caudal_m3h):
        """Intensidad de aplicación o pluviometría media (mm/h)."""
        return caudal_m3h * 1000.0 / self.area_m2

    def aspersores_por_ha(self):
        return 10000.0 / self.area_m2

    def separacion_maxima_m(self, diametro_mojado_m, viento_ms=0.0):
        return factor_solape(viento_ms, self.disposicion) * diametro_mojado_m

    def solape_suficiente(self, diametro_mojado_m, viento_ms=0.0):
        maxima = self.separacion_maxima_m(diametro_mojado_m, viento_ms)
        return max(self.espaciamiento_aspersores_m, self.espaciamiento_laterales_m) <= maxima + 1e-9


@dataclass
class Riego:
    """Necesidad de riego y suelo, para el tiempo de riego y la comprobación de escorrentía."""
    lamina_neta_mm: float = 0.0
    eficiencia: float = 0.75
    infiltracion_basica_mm_h: Optional[float] = None

    @property
    def lamina_bruta_mm(self):
        return self.lamina_neta_mm / self.eficiencia if self.eficiencia > 0 else 0.0

    def tiempo_riego_h(self, intensidad_mm_h):
        return self.lamina_bruta_mm / intensidad_mm_h if intensidad_mm_h > 0 else 0.0


# --------------------------------------------------------------------------- lateral de aspersión

@dataclass
class ResultadoAspersion:
    lateral: object  # ResultadoLateral (caudales en L/h, presiones en la tubería lateral)
    presiones_boquilla_m: List[float]
    caudales_m3h: List[float]
    aspersor: Aspersor
    elevador: Elevador
    marco: Marco
    riego: Riego = field(default_factory=Riego)
    viento_ms: float = 0.0
    variacion_admisible: float = VARIACION_PRESION_ADMISIBLE
    aspersores_fuera_de_rango: int = 0

    @property
    def numero_aspersores(self):
        return len(self.caudales_m3h)

    @property
    def presion_entrada_m(self):
        return self.lateral.presion_entrada_m

    @property
    def caudal_total_m3h(self):
        return sum(self.caudales_m3h)

    @property
    def caudal_medio_m3h(self):
        return self.caudal_total_m3h / self.numero_aspersores

    @property
    def presion_boquilla_min_m(self):
        return min(self.presiones_boquilla_m)

    @property
    def presion_boquilla_max_m(self):
        return max(self.presiones_boquilla_m)

    @property
    def variacion_presion(self):
        """Δh en las boquillas como fracción de la presión nominal del aspersor."""
        return (self.presion_boquilla_max_m - self.presion_boquilla_min_m) / self.aspersor.presion_nominal_m

    @property
    def variacion_caudal(self):
        return self.lateral.variacion_caudal

    @property
    def intensidad_mm_h(self):
        return self.marco.intensidad_mm_h(self.caudal_medio_m3h)

    @property
    def tiempo_riego_h(self):
        return self.riego.tiempo_riego_h(self.intensidad_mm_h)

    @property
    def velocidad_elevador_ms(self):
        return self.elevador.velocidad(max(self.caudales_m3h))

    @property
    def solape_suficiente(self):
        return self.marco.solape_suficiente(self.aspersor.diametro_mojado_m, self.viento_ms)

    @property
    def escorrentia(self):
        """True si la pluviometría supera la infiltración básica del suelo."""
        i = self.riego.infiltracion_basica_mm_h
        return i is not None and i > 0 and self.intensidad_mm_h > i + 1e-9

    def avisos(self, presion_entrada_max_m=None):
        avisos = []
        if self.variacion_presion > self.variacion_admisible + 1e-9:
            avisos.append(f"La variación de presión en las boquillas ({self.variacion_presion:.1%} de la nominal) "
                          f"supera el {self.variacion_admisible:.0%} admitido.")
        if self.aspersores_fuera_de_rango:
            avisos.append(f"{self.aspersores_fuera_de_rango} aspersores trabajan fuera del rango de presión "
                          "del fabricante.")
        if not self.solape_suficiente:
            maxima = self.marco.separacion_maxima_m(self.aspersor.diametro_mojado_m, self.viento_ms)
            avisos.append(f"El marco es muy abierto para el diámetro mojado: con este viento la separación "
                          f"máxima es {maxima:.1f} m.")
        if self.escorrentia:
            avisos.append(f"La pluviometría ({self.intensidad_mm_h:.1f} mm/h) supera la infiltración básica del "
                          f"suelo ({self.riego.infiltracion_basica_mm_h:g} mm/h): habrá escorrentía.")
        if presion_entrada_max_m is not None and self.presion_entrada_m > presion_entrada_max_m + 1e-9:
            avisos.append(f"La presión de entrada supera los {presion_entrada_max_m:g} m indicados.")
        return avisos

    def cumple(self, presion_entrada_max_m=None):
        return not self.avisos(presion_entrada_max_m)


@dataclass
class LateralAspersion:
    tuberia: object  # tuberias.Tuberia
    aspersor: Aspersor
    marco: Marco
    numero_aspersores: int
    elevador: Elevador = field(default_factory=Elevador)
    distancia_primer_aspersor_m: Optional[float] = None  # por defecto, medio espaciamiento
    pendiente: float = 0.0
    perfil: Optional[list] = None
    metodo: str = "darcy"
    riego: Riego = field(default_factory=Riego)
    viento_ms: float = 0.0
    variacion_admisible: float = VARIACION_PRESION_ADMISIBLE

    def __post_init__(self):
        if self.distancia_primer_aspersor_m is None:
            self.distancia_primer_aspersor_m = self.marco.espaciamiento_aspersores_m / 2.0
        self.salida = SalidaAspersor(self.aspersor, self.elevador)
        self.lateral = Lateral(self.tuberia, self.salida, self.marco.espaciamiento_aspersores_m,
                               self.numero_aspersores, distancia_primer_emisor_m=self.distancia_primer_aspersor_m,
                               pendiente=self.pendiente, perfil=self.perfil, metodo=self.metodo)

    @classmethod
    def desde_longitud(cls, tuberia, aspersor, marco, longitud_m, **kwargs):
        d1 = kwargs.get("distancia_primer_aspersor_m")
        if d1 is None:
            d1 = marco.espaciamiento_aspersores_m / 2.0
        n = int((longitud_m - d1) / marco.espaciamiento_aspersores_m + 1e-9) + 1
        return cls(tuberia, aspersor, marco, max(n, 1), **kwargs)

    @property
    def longitud_m(self):
        return self.lateral.longitud_m

    def _resultado(self, r):
        boquillas = [self.salida.presion_boquilla(h) for h in r.presiones_m]
        return ResultadoAspersion(
            lateral=r, presiones_boquilla_m=boquillas, caudales_m3h=[q / 1000.0 for q in r.caudales_lh],
            aspersor=self.aspersor, elevador=self.elevador, marco=self.marco, riego=self.riego,
            viento_ms=self.viento_ms, variacion_admisible=self.variacion_admisible,
            aspersores_fuera_de_rango=sum(1 for h in boquillas if self.aspersor.fuera_de_rango(h)))

    def presion_entrada_requerida(self, criterio=CRITERIO_CAUDAL_MEDIO):
        """Por defecto, el caudal medio de los aspersores es el nominal (presión media = nominal)."""
        return self._resultado(self.lateral.presion_entrada_requerida(criterio))

    def simular(self, presion_entrada_m):
        return self._resultado(self.lateral.simular(presion_entrada_m))


def numero_maximo_aspersores(tuberia, aspersor, marco, elevador=None, limite=200, presion_entrada_max_m=None,
                             **kwargs):
    """Mayor número de aspersores del lateral que cumple la variación de presión (y la presión de entrada máxima).

    Devuelve (n, ResultadoAspersion) o (0, None). Solo cuentan la hidráulica del lateral: el marco, el viento y
    el suelo no dependen del largo.
    """
    def cumple(n):
        lateral = LateralAspersion(tuberia, aspersor, marco, n, elevador=elevador or Elevador(), **kwargs)
        try:
            r = lateral.presion_entrada_requerida()
        except PresionInsuficiente:
            return None
        ok = (r.variacion_presion <= lateral.variacion_admisible + 1e-9 and not r.aspersores_fuera_de_rango
              and (presion_entrada_max_m is None or r.presion_entrada_m <= presion_entrada_max_m + 1e-9))
        return r if ok else None

    mejor_n, mejor = 0, None
    for n in range(1, limite + 1):  # con pendiente la variación no siempre crece con el largo
        r = cumple(n)
        if r is not None:
            mejor_n, mejor = n, r
        elif mejor is not None and n > mejor_n + 5:
            break
    return mejor_n, mejor


# --------------------------------------------------------------------------- catálogo

def cargar_catalogo_aspersores(ruta=None):
    with open(ruta or RUTA_CATALOGO, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    return [Aspersor(**item) for item in datos["aspersores"]]


def guardar_catalogo_aspersores(aspersores, ruta):
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump({"aspersores": [asdict(a) for a in aspersores]}, archivo, ensure_ascii=False, indent=2)


def caudal_orificio_m3h(boquilla_mm, presion_m, coeficiente=0.95):
    """Caudal teórico de una boquilla circular: q = Cd·A·√(2gh)."""
    return coeficiente * area(boquilla_mm / 1000.0) * (2 * G * presion_m) ** 0.5 * 3600.0

