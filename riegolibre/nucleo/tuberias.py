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

    def velocidad(self, caudal_m3s):
        return hidraulica.velocidad(caudal_m3s, self.diametro_m)


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
