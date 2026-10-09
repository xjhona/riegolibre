"""Emisores (goteros y cintas) y su ecuación caudal-presión q = k·h^x."""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

RUTA_CATALOGO = os.path.join(os.path.dirname(__file__), "datos", "emisores.json")


@dataclass
class Emisor:
    nombre: str
    caudal_nominal_lh: float
    presion_nominal_m: float
    exponente: float = 0.5
    cv: float = 0.05  # coeficiente de variación de fabricación
    autocompensado: bool = False
    presion_min_m: Optional[float] = None  # inicio del rango de compensación
    presion_max_m: Optional[float] = None  # fin del rango de compensación
    tipo: str = "gotero"  # gotero | cinta
    longitud_equivalente_m: float = 0.0  # pérdida por la inserción del emisor

    @property
    def k(self):
        return self.caudal_nominal_lh / self.presion_nominal_m ** self.exponente

    @property
    def presion_compensacion_m(self):
        """Presión a partir de la cual el emisor autocompensado entrega su caudal nominal."""
        return self.presion_min_m if self.presion_min_m is not None else self.presion_nominal_m

    def caudal(self, presion_m):
        """Caudal (L/h) a una presión dada (m.c.a.)."""
        if presion_m <= 0:
            return 0.0
        if self.autocompensado:
            h_min = self.presion_compensacion_m
            if presion_m >= h_min:
                return self.caudal_nominal_lh
            # Por debajo del rango de compensación se comporta como un orificio.
            return self.caudal_nominal_lh * (presion_m / h_min) ** 0.5
        return self.k * presion_m ** self.exponente

    def presion_para_caudal(self, caudal_lh):
        """Presión necesaria (m) para entregar un caudal (solo emisores no compensados)."""
        if self.autocompensado:
            return self.presion_compensacion_m
        return (caudal_lh / self.k) ** (1.0 / self.exponente)

    def fuera_de_rango(self, presion_m, tolerancia=0.01):
        """True si la presión está fuera del rango de compensación del emisor."""
        if not self.autocompensado:
            return False
        if presion_m < self.presion_compensacion_m - tolerancia:
            return True
        return self.presion_max_m is not None and presion_m > self.presion_max_m + tolerancia


def cargar_catalogo_emisores(ruta=RUTA_CATALOGO):
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    return [Emisor(**item) for item in datos["emisores"]]


def guardar_catalogo_emisores(emisores, ruta):
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump({"emisores": [asdict(e) for e in emisores]}, archivo,
                  ensure_ascii=False, indent=2)
