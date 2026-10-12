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


# Diámetro exterior comercial (mm) de los tubos que en el plano se rotulan en pulgadas.
PULGADAS = ((21.0, "½"), (26.5, "¾"), (33.0, "1"), (42.0, "1¼"), (48.0, "1½"), (60.0, "2"))
PULGADAS_HASTA_MM = 63.0  # desde este diámetro el rótulo va en milímetros
TOLERANCIA_PULGADAS_MM = 3.0


def diametro_en_plano(diametro_nominal_mm):
    """«1½"» para los tubos menores de 63 mm (32 mm → 1", 48 o 50 mm → 1½"); «63» para los demás.

    Si el diámetro no se parece a ninguna medida comercial en pulgadas se deja en milímetros.
    """
    if diametro_nominal_mm < PULGADAS_HASTA_MM:
        exterior, pulgadas = min(PULGADAS, key=lambda p: abs(p[0] - diametro_nominal_mm))
        if abs(exterior - diametro_nominal_mm) <= TOLERANCIA_PULGADAS_MM:
            return f'{pulgadas}"'
    return f"{diametro_nominal_mm:g}"


def rotulo_corto(tuberia):
    """Rótulo de plano «diámetro nominal/clase», p. ej. «63/5» (PVC C-5) o «1"/4» (PE 32 mm PN4).

    Menores de 63 mm en pulgadas. La clase es la presión nominal en bar (10 m ≈ 1 bar).
    Sin diámetro nominal se usa el nombre.
    """
    if not tuberia.diametro_nominal_mm:
        return tuberia.nombre
    texto = diametro_en_plano(tuberia.diametro_nominal_mm)
    if tuberia.presion_nominal_m:
        texto += f"/{round(tuberia.presion_nominal_m / 10, 1):g}"
    return texto


def cargar_catalogo_tuberias(ruta=None, uso=None):
    """Catálogo de tuberías, todas o las de un uso (lateral, portalateral, principal).

    Sin ruta se usa la base de datos del usuario (ver `base_datos`), si existe y tiene
    tuberías para ese uso; si no, el catálogo genérico. Pedidas todas (uso=None), se añaden
    las genéricas que no estén en la base, para reconocer los proyectos hechos con ellas.
    """
    if ruta is None:
        from .base_datos import base_activa
        base = base_activa()
        if base is not None:
            tuberias = base.tuberias_motor(uso)
            if uso is None:
                nombres = {t.nombre for t in tuberias}
                return tuberias + [t for t in cargar_catalogo_tuberias(RUTA_CATALOGO)
                                   if t.nombre not in nombres]
            if tuberias:
                return tuberias
        ruta = RUTA_CATALOGO
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
