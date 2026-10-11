"""Base de datos de materiales: tuberías, laterales con emisor integrado, válvulas y otros
elementos hidráulicos (filtros, reguladoras, etc.).

Es una sola base para todos los proyectos, guardada en un archivo JSON en la carpeta del
usuario (ver `ruta_base_usuario`). Mientras no exista, el programa usa los catálogos
genéricos de `nucleo/datos`.
"""

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional

from .emisores import Emisor
from .tuberias import Tuberia

VERSION = 1
VARIABLE_RUTA = "RIEGOLIBRE_BASE"
MATERIAL_CINTA = "Cinta"  # material de la tubería de un lateral con emisores integrados
EXPONENTE_AUTOCOMPENSADO = 0.05  # x menor o igual: emisor autocompensado


def _de_dict(clase, datos):
    """Construye un registro ignorando las claves que no conoce (bases de versiones futuras)."""
    nombres = {f.name for f in fields(clase)}
    return clase(**{k: v for k, v in datos.items() if k in nombres})


@dataclass
class RegistroTuberia:
    """Tubería de la pestaña «Tuberías»."""
    nombre: str
    diametro_interior_mm: float
    material: str = "PE"
    usos: List[str] = field(default_factory=list)  # lateral | portalateral | principal | lavado
    diametro_nominal_mm: Optional[float] = None
    rugosidad_mm: float = 0.0015
    c_hazen: float = 140.0
    presion_nominal_m: Optional[float] = None  # presión admisible
    etiqueta: str = ""
    codigo: str = ""  # código de almacén
    proveedor: str = ""
    costo_m: float = 0.0  # costo mayorista por metro
    precio_m: float = 0.0  # precio de venta por metro

    def tuberia(self) -> Tuberia:
        return Tuberia(nombre=self.nombre, diametro_interior_mm=self.diametro_interior_mm,
                       material=self.material, usos=list(self.usos),
                       diametro_nominal_mm=self.diametro_nominal_mm, rugosidad_mm=self.rugosidad_mm,
                       c_hazen=self.c_hazen, presion_nominal_m=self.presion_nominal_m)


@dataclass
class Cinta:
    """Lateral con emisores integrados (cinta o manguera con gotero), pestaña «Laterales».

    El emisor sigue q = k·h^x (q en L/h, h en m); con x = 0 es autocompensado y entrega k L/h.
    """
    nombre: str
    diametro_interior_mm: float
    k_emisor: float
    exponente_emisor: float
    espaciamiento_m: float
    diametro_nominal_mm: Optional[float] = None
    c_hazen: float = 140.0
    rugosidad_mm: float = 0.0015
    presion_nominal_m: Optional[float] = None  # presión admisible de la manguera
    longitud_equivalente_m: float = 0.0  # pérdida por la inserción de cada emisor («barb factor»)
    cv: float = 0.0  # coeficiente de variación de fabricación
    presion_entrada_m: float = 10.0  # presión de entrada por omisión
    presion_min_m: Optional[float] = None
    presion_max_m: Optional[float] = None
    presion_min_compensacion_m: Optional[float] = None  # desde donde compensa (autocompensados)
    tolerancia_sobre_pct: float = 0.0  # tolerancia de presión de la zona, por encima
    tolerancia_bajo_pct: float = 0.0  # y por debajo
    tipo_tuberia: str = ""  # tipo de tubería en IRRICAD (LDP, DLN…)
    seleccionable: bool = True
    etiqueta: str = ""
    codigo: str = ""
    proveedor: str = ""
    costo_m: float = 0.0
    precio_m: float = 0.0

    @property
    def autocompensado(self):
        return self.exponente_emisor <= EXPONENTE_AUTOCOMPENSADO

    @property
    def caudal_nominal_lh(self):
        if self.autocompensado:
            return self.k_emisor
        return self.k_emisor * self.presion_entrada_m ** self.exponente_emisor

    @property
    def caudal_por_metro_lhm(self):
        return self.caudal_nominal_lh / self.espaciamiento_m if self.espaciamiento_m > 0 else 0.0

    def tuberia(self) -> Tuberia:
        return Tuberia(nombre=self.nombre, diametro_interior_mm=self.diametro_interior_mm,
                       material=MATERIAL_CINTA, usos=["lateral"],
                       diametro_nominal_mm=self.diametro_nominal_mm, rugosidad_mm=self.rugosidad_mm,
                       c_hazen=self.c_hazen, presion_nominal_m=self.presion_nominal_m)

    def emisor(self) -> Emisor:
        if self.autocompensado:
            return Emisor(nombre=self.nombre, caudal_nominal_lh=self.k_emisor,
                          presion_nominal_m=self.presion_entrada_m, exponente=0.0, cv=self.cv,
                          autocompensado=True,
                          presion_min_m=self.presion_min_compensacion_m or self.presion_min_m,
                          presion_max_m=self.presion_max_m, tipo="cinta",
                          longitud_equivalente_m=self.longitud_equivalente_m)
        return Emisor(nombre=self.nombre, caudal_nominal_lh=self.caudal_nominal_lh,
                      presion_nominal_m=self.presion_entrada_m, exponente=self.exponente_emisor,
                      cv=self.cv, autocompensado=False, tipo="cinta",
                      longitud_equivalente_m=self.longitud_equivalente_m)


@dataclass
class ElementoHidraulico:
    """Válvula u otro elemento hidráulico (filtro, reguladora, hidrociclón…).

    Pérdida de carga: H = K·Q^n + C, con H en m y Q en m³/h.
    """
    nombre: str
    k: float = 0.0
    n: float = 2.0
    c: float = 0.0
    diametro_entrada_mm: Optional[float] = None
    diametro_salida_mm: Optional[float] = None
    conexion_entrada: str = ""
    conexion_salida: str = ""
    caudal_min_m3h: Optional[float] = None
    caudal_max_m3h: Optional[float] = None
    seleccionable: bool = True
    etiqueta: str = ""
    codigo: str = ""
    proveedor: str = ""
    costo: float = 0.0
    precio: float = 0.0

    def perdida(self, caudal_m3h):
        """Pérdida de carga (m) para un caudal en m³/h."""
        if caudal_m3h <= 0:
            return 0.0
        return self.k * caudal_m3h ** self.n + self.c

    def fuera_de_rango(self, caudal_m3h):
        return ((self.caudal_min_m3h is not None and caudal_m3h < self.caudal_min_m3h) or
                (self.caudal_max_m3h is not None and self.caudal_max_m3h > 0 and caudal_m3h > self.caudal_max_m3h))


@dataclass
class BaseDatos:
    tuberias: List[RegistroTuberia] = field(default_factory=list)
    cintas: List[Cinta] = field(default_factory=list)
    valvulas: List[ElementoHidraulico] = field(default_factory=list)
    hidraulicos: List[ElementoHidraulico] = field(default_factory=list)
    emisores: Optional[List[Emisor]] = None  # emisores sueltos; None: los del catálogo genérico
    origen: str = ""

    def tuberias_motor(self, uso=None) -> List[Tuberia]:
        """Tuberías para el cálculo: las de la pestaña Tuberías y las de los laterales con gotero."""
        tuberias = [c.tuberia() for c in self.cintas if c.seleccionable]
        tuberias += [t.tuberia() for t in self.tuberias]
        if uso is not None:
            tuberias = [t for t in tuberias if uso in t.usos]
        return tuberias

    def emisores_motor(self, genericos=()) -> List[Emisor]:
        """Emisores sueltos (o los genéricos) seguidos de los de los laterales con gotero."""
        sueltos = list(self.emisores) if self.emisores is not None else list(genericos)
        return sueltos + [c.emisor() for c in self.cintas if c.seleccionable]

    def resumen(self):
        return {"Tuberías": len(self.tuberias), "Laterales con gotero": len(self.cintas),
                "Válvulas": len(self.valvulas), "Otros hidráulicos": len(self.hidraulicos)}


def guardar_base(base: BaseDatos, ruta, respaldo=True):
    """Guarda la base en JSON. Si ya existía un archivo, lo deja como respaldo «.bak»."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    if respaldo and os.path.exists(ruta):
        shutil.copyfile(ruta, ruta + ".bak")
    datos = {"version": VERSION, "origen": base.origen,
             "tuberias": [asdict(t) for t in base.tuberias],
             "cintas": [asdict(c) for c in base.cintas],
             "valvulas": [asdict(v) for v in base.valvulas],
             "hidraulicos": [asdict(h) for h in base.hidraulicos]}
    if base.emisores is not None:
        datos["emisores"] = [asdict(e) for e in base.emisores]
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)
    _cache.clear()


def cargar_base(ruta) -> BaseDatos:
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    emisores = datos.get("emisores")
    return BaseDatos(
        tuberias=[_de_dict(RegistroTuberia, t) for t in datos.get("tuberias", [])],
        cintas=[_de_dict(Cinta, c) for c in datos.get("cintas", [])],
        valvulas=[_de_dict(ElementoHidraulico, v) for v in datos.get("valvulas", [])],
        hidraulicos=[_de_dict(ElementoHidraulico, h) for h in datos.get("hidraulicos", [])],
        emisores=None if emisores is None else [_de_dict(Emisor, e) for e in emisores],
        origen=datos.get("origen", ""))


def ruta_base_usuario():
    """Archivo de la base del usuario.

    Se puede cambiar con la variable de entorno RIEGOLIBRE_BASE; si no, en Windows es
    %APPDATA%/RiegoLibre/base_datos.json y en otros sistemas ~/.config/riegolibre/base_datos.json.
    """
    ruta = os.environ.get(VARIABLE_RUTA)
    if ruta:
        return ruta
    if os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "RiegoLibre", "base_datos.json")
    configuracion = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(configuracion, "riegolibre", "base_datos.json")


_cache = {}


def base_activa() -> Optional[BaseDatos]:
    """La base del usuario, o None si todavía no ha importado ni creado ninguna."""
    ruta = ruta_base_usuario()
    try:
        marca = os.path.getmtime(ruta)
    except OSError:
        return None
    if _cache.get("clave") != (ruta, marca):
        _cache.update(clave=(ruta, marca), base=cargar_base(ruta))
    return _cache["base"]


def cintas_activas():
    """Laterales con gotero de la base activa, por nombre ({} si no hay base)."""
    base = base_activa()
    return {} if base is None else {c.nombre: c for c in base.cintas if c.seleccionable}


def desactivar_base():
    """Vuelve al catálogo genérico: la base del usuario queda guardada como «.bak»."""
    ruta = ruta_base_usuario()
    if os.path.exists(ruta):
        os.replace(ruta, ruta + ".bak")
    _cache.clear()
