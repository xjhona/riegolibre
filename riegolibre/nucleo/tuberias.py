"""Tuberías y catálogo de tuberías."""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import List, Optional

from . import hidraulica

METODOS = ("darcy", "hazen")

RUTA_CATALOGO = os.path.join(os.path.dirname(__file__), "datos", "tuberias.json")


@dataclass
class Tuberia:
    nombre: str
    diametro_interior_mm: float
    material: str = "PE"
    usos: List[str] = field(default_factory=lambda: ["lateral"])  # lateral | portalateral | principal
    diametro_nominal_mm: Optional[float] = None
    rugosidad_mm: float = 0.0015
    c_hazen: float = 140.0
    presion_nominal_m: Optional[float] = None

    @property
    def diametro_m(self):
        return self.diametro_interior_mm / 1000.0

    def perdida(self, caudal_m3s, longitud_m, metodo="darcy"):
        """Pérdida por fricción (m) para un caudal en m³/s."""
        if metodo == "darcy":
            return hidraulica.perdida_darcy(
                caudal_m3s, self.diametro_m, longitud_m, self.rugosidad_mm / 1000.0)
        if metodo == "hazen":
            return hidraulica.perdida_hazen_williams(
                caudal_m3s, self.diametro_m, longitud_m, self.c_hazen)
        raise ValueError(f"Método desconocido: {metodo!r}. Use uno de {METODOS}.")

    def funcion_perdida(self, longitud_m, metodo="darcy"):
        """Función caudal (m³/s, >= 0) -> pérdida (m) para un tramo de longitud fija.

        Equivale a perdida() con las constantes precalculadas; se usa en los
        bucles del cálculo emisor por emisor, donde se llama miles de veces.
        """
        d = self.diametro_m
        if metodo == "hazen":
            k = 10.674 * longitud_m / (self.c_hazen ** 1.852 * d ** 4.871)
            return lambda q: k * q ** 1.852 if q > 0 else 0.0
        if metodo != "darcy":
            raise ValueError(f"Método desconocido: {metodo!r}. Use uno de {METODOS}.")
        area = hidraulica.area(d)
        a_reynolds = d / (area * hidraulica.VISCOSIDAD_CINEMATICA_20C)  # Re = a·q
        a_energia = longitud_m / d / (2 * hidraulica.G * area * area)  # hf = f·a·q²
        rr = self.rugosidad_mm / 1000.0 / d
        friccion = hidraulica.factor_friccion

        def perdida(q):
            if q <= 0:
                return 0.0
            return friccion(a_reynolds * q, rr) * a_energia * q * q
        return perdida

    def velocidad(self, caudal_m3s):
        return hidraulica.velocidad(caudal_m3s, self.diametro_m)


def clave_economica(tuberia):
    """Orden de preferencia: menor diámetro nominal y, dentro de él, la clase de presión más baja.

    Entre tubos del mismo diámetro nominal, la clase más baja tiene la pared más
    delgada: más diámetro interior y menor precio.
    """
    return (tuberia.diametro_nominal_mm or tuberia.diametro_interior_mm,
            tuberia.presion_nominal_m or 0.0, -tuberia.diametro_interior_mm)


def cargar_catalogo_tuberias(ruta=RUTA_CATALOGO, uso=None):
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    tuberias = [Tuberia(**item) for item in datos["tuberias"]]
    if uso is not None:
        tuberias = [t for t in tuberias if uso in t.usos]
    return tuberias


def guardar_catalogo_tuberias(tuberias, ruta):
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump({"tuberias": [asdict(t) for t in tuberias]}, archivo,
                  ensure_ascii=False, indent=2)
