"""Listas de precios: lectura del CSV e identificación de tuberías por su descripción.

El CSV debe tener las columnas codigo, descripcion, unidad y precio. Se acepta
coma o punto y coma como separador y coma o punto como separador decimal.

Las descripciones de tuberías se interpretan con reglas sencillas, por ejemplo:
    "PVC PIPE UF 63mm C-5 x 6 METERS"      -> PVC, 63 mm, clase 5, tubo de 6 m
    "MANGUERA CIEGA 16/40 500m"             -> manguera PE, 16 mm, precio por metro
    "MANGUERA DE POLIETILENO HDPE 90 mm PN-8" -> PE, 90 mm, PN 8
Un precio es por pieza cuando la descripción indica un largo corto («x 6 METERS»,
«6m»); los largos de bobina («500m», «B-450M», «x100m») indican precio por metro.
"""

import csv
import re
import statistics
from dataclasses import dataclass
from typing import List, Optional

LARGO_MAXIMO_PIEZA_M = 12.0
# Palabras que indican un accesorio (no una tubería) en descripciones de PE.
ACCESORIO = re.compile(
    r"\b(?:CODO|UNI[OÓ]N|TEE|TE|ADAPT\w*|TAPA|TAP[OÓ]N|REDUC\w*|BRIDA|COLLAR\w*|ABRAZADERA|ENLACE|"
    r"CONECT\w*|V[AÁ]LVULA|VALVE|ELBOW|COUPLING|SADDLE|CAP|SOLDADORA|NIPLE|CRUZ|ESPIGA)\b")


@dataclass
class Articulo:
    codigo: str
    descripcion: str
    unidad: str
    precio: float
    longitud_pieza_m: Optional[float] = None  # si el precio es por tubo de este largo

    @property
    def por_pieza(self):
        return self.longitud_pieza_m is not None

    @property
    def precio_m(self):
        """Precio por metro (para tuberías)."""
        return self.precio / self.longitud_pieza_m if self.por_pieza else self.precio


@dataclass
class DescripcionTuberia:
    material: str  # PVC | PE | MANGUERA
    dn_mm: float
    clase: Optional[float] = None  # C-5, C-7.5… en PVC; PN en bar en PE


def _numero(texto):
    return float(texto.replace(",", "."))


def longitud_pieza(descripcion):
    """Largo de la pieza (m) si el precio es por tubo; None si es por metro o por unidad."""
    largos = [_numero(n) for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:m|mts|metros|meters)\b",
                                            descripcion, re.IGNORECASE)]
    cortos = [n for n in largos if 0 < n <= LARGO_MAXIMO_PIEZA_M]
    return cortos[0] if cortos else None


def interpretar_tuberia(descripcion) -> Optional[DescripcionTuberia]:
    """Material, diámetro nominal y clase de una tubería a partir de su descripción."""
    texto = descripcion.upper()
    if re.search(r"\bPVC\s+PIPE\b", texto):
        dn = re.search(r"\b(\d{2,3})\s*MM\b", texto) or re.search(r"PIPE\s+(?:UF\s+|SP\s+)?(\d{2,3})\b", texto)
        if not dn:
            return None  # p. ej. tuberías en pulgadas
        clase = (re.search(r"\bC(?:LASS)?\s*-?\s*(\d+(?:[.,]\d+)?)", texto[dn.end():])
                 or re.search(r"\b\d{2,3}\s*-\s*(\d+(?:[.,]\d+)?)\b", texto))
        return DescripcionTuberia("PVC", float(dn.group(1)), _numero(clase.group(1)) if clase else None)
    if re.search(r"MANGUERA\s+(?:PE\s+)?CIEGA|MANGUERA\s+CIEGA", texto):
        dn = re.search(r"CIEGA\s+(?:DE\s+P\.?E\.?\s+|NEGRA\s+)?(\d{2})", texto)
        return DescripcionTuberia("MANGUERA", float(dn.group(1))) if dn else None
    if re.search(r"POLIETILENO|HDPE|\bPE\s+(?:IRRIGATION\s+)?PIPE", texto) and not ACCESORIO.search(texto):
        dn = re.search(r"\b(\d{2,3})\s*MM\b", texto)
        pn = re.search(r"\b(?:PN|C)\s*-?\s*(\d+(?:[.,]\d+)?)", texto)
        return DescripcionTuberia("PE", float(dn.group(1)), _numero(pn.group(1)) if pn else None) if dn else None
    return None


def cargar_lista_precios(ruta) -> List[Articulo]:
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        muestra = archivo.read(4096)
        archivo.seek(0)
        separador = ";" if muestra.count(";") > muestra.count(",") else ","
        lector = csv.DictReader(archivo, delimiter=separador)
        columnas = {c.strip().lower(): c for c in lector.fieldnames or []}
        faltan = {"codigo", "descripcion", "precio"} - set(columnas)
        if faltan:
            raise ValueError("A la lista de precios le faltan las columnas: " + ", ".join(sorted(faltan)))
        articulos = []
        for fila in lector:
            texto_precio = (fila[columnas["precio"]] or "").strip()
            if not texto_precio:
                continue
            if separador == ";":
                texto_precio = texto_precio.replace(".", "").replace(",", ".") if "," in texto_precio else texto_precio
            try:
                precio = float(texto_precio)
            except ValueError:
                continue
            descripcion = (fila[columnas["descripcion"]] or "").strip()
            unidad = (fila.get(columnas.get("unidad", ""), "") or "").strip()
            articulos.append(Articulo(fila[columnas["codigo"]].strip(), descripcion, unidad, precio,
                                      longitud_pieza(descripcion)))
    return articulos


def clase_de(tuberia):
    """Clase de una tubería del catálogo: «C-7.5» en el nombre o, si no, PN en bar."""
    encontrado = re.search(r"\bC-(\d+(?:\.\d+)?)", tuberia.nombre)
    if encontrado:
        return float(encontrado.group(1))
    if tuberia.presion_nominal_m:
        return round(tuberia.presion_nominal_m / 10.0, 1)
    return None


def _material_buscado(tuberia):
    nombre = tuberia.nombre.lower()
    if tuberia.material.upper() == "PVC":
        return "PVC"
    if "manguera" in nombre:
        return "MANGUERA"
    if "cinta" in nombre:
        return None  # las cintas llevan los emisores incorporados: se eligen a mano
    return "PE"


def candidatos_tuberia(tuberia, articulos):
    """Artículos de la lista equivalentes a una tubería del catálogo, del más barato al más caro."""
    material = _material_buscado(tuberia)
    dn = tuberia.diametro_nominal_mm
    if material is None or dn is None:
        return []
    clase = clase_de(tuberia)
    encontrados = []
    for articulo in articulos:
        d = interpretar_tuberia(articulo.descripcion)
        if d is None or d.material != material or abs(d.dn_mm - dn) > 0.5:
            continue
        if material == "PVC" and (d.clase is None or clase is None or abs(d.clase - clase) > 1e-6):
            continue
        encontrados.append(articulo)
    return sorted(encontrados, key=lambda a: a.precio_m)


def candidatos_conector(dn_mm, articulos):
    """Conectores iniciales para mangueras de un diámetro (p. ej. «CONECTOR INICIAL 16MM …»)."""
    patron_dn = re.compile(rf"\b{dn_mm:g}\s*(?:MM)?\b")
    encontrados = [a for a in articulos
                   if re.search(r"CONEC\w*\.?\s+INICIAL", a.descripcion, re.IGNORECASE)
                   and not re.search(r"LAY\s*FLAT", a.descripcion, re.IGNORECASE)
                   and patron_dn.search(a.descripcion.upper())]
    return sorted(encontrados, key=lambda a: a.precio)


def precio_representativo(candidatos):
    """El artículo de precio central (mediana) entre los candidatos."""
    if not candidatos:
        return None
    mediana = statistics.median_low([a.precio_m for a in candidatos])
    return next(a for a in candidatos if a.precio_m == mediana)


def buscar(articulos, texto, limite=200):
    """Artículos cuya descripción o código contiene todas las palabras del texto."""
    palabras = texto.upper().split()
    resultado = []
    for articulo in articulos:
        objetivo = f"{articulo.codigo} {articulo.descripcion}".upper()
        if all(p in objetivo for p in palabras):
            resultado.append(articulo)
            if len(resultado) >= limite:
                break
    return resultado
