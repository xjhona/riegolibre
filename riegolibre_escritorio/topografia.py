# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Curvas de nivel de un DXF y el DEM que sale de ellas, sin QGIS ni GDAL. Sin Qt.

Hace lo mismo que la topografía del complemento (`riegolibre/integracion/topografia_cad.py`): las polilíneas con
elevación de las capas elegidas se triangulan (TIN, interpolación lineal) en una cuadrícula y se descartan las
celdas a más de cierta distancia de la curva más cercana. Usa ezdxf para leer el DXF y numpy/scipy para el TIN.

El DEM se guarda en el formato binario del motor (`.rdem`, ver `mcp_riegolibre.motor.rejilla_a_bytes`): un
plano de varios km a 1 m tiene millones de celdas y en ASCII Grid pesaría cientos de MB. Las curvas se guardan en
JSON comprimido para dibujarlas.
"""

import gzip
import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from mcp_riegolibre.motor import rejilla_a_bytes

NODATA = -9999.0
MAX_CELDAS = 30_000_000  # igual que el complemento
TIPOS = "LWPOLYLINE POLYLINE LINE SPLINE"
APLANADO_M = 0.1  # tolerancia para pasar arcos (bulge) y splines a tramos rectos

Curva = Tuple[float, List[Tuple[float, float]]]  # (cota, vértices); cota None si varía en la línea


@dataclass
class CapaCad:
    """Resumen de una capa del dibujo CAD."""

    nombre: str
    lineas: int = 0
    con_cota: int = 0  # líneas con alguna Z distinta de 0
    cota_min: Optional[float] = None
    cota_max: Optional[float] = None

    @property
    def parece_curvas(self):
        return self.con_cota > 0


@dataclass
class ContenidoDxf:
    capas: List[CapaCad]
    extension: tuple  # (xmin, xmax, ymin, ymax) de las líneas

    @property
    def ancho(self):
        return self.extension[1] - self.extension[0]

    @property
    def alto(self):
        return self.extension[3] - self.extension[2]


@dataclass
class ResultadoDem:
    rejilla: bytes  # el DEM en el formato binario del motor (`.rdem`)
    curvas: List[Tuple[float, List[Tuple[float, float]]]]  # (cota, vértices) de cada curva usada
    paso_m: float
    columnas: int
    filas: int
    cota_min: float
    cota_max: float
    cobertura: float  # fracción de celdas con dato
    avisos: List[str] = field(default_factory=list)


def parecen_coordenadas_planas(extension):
    """True si las coordenadas no caben en grados (por ejemplo, UTM)."""
    xmin, xmax, ymin, ymax = extension
    return max(abs(xmin), abs(xmax)) > 360 or max(abs(ymin), abs(ymax)) > 90


def celdas_estimadas(extension, paso_m):
    xmin, xmax, ymin, ymax = extension
    return (math.floor((xmax - xmin) / paso_m) + 2) * (math.floor((ymax - ymin) / paso_m) + 2)


# ------------------------------------------------------------------ lectura del DXF


def _abrir(ruta):
    import ezdxf
    from ezdxf import recover

    if not os.path.isfile(ruta):
        raise ValueError(f"No se encuentra el archivo:\n{ruta}")
    try:
        return ezdxf.readfile(ruta)
    except ezdxf.DXFStructureError:
        try:  # un DXF algo dañado: ezdxf intenta repararlo
            doc, _ = recover.readfile(ruta)
            return doc
        except (ezdxf.DXFStructureError, OSError) as error:
            raise ValueError(f"No se pudo leer el DXF ({error}). Guárdelo de nuevo desde el CAD como "
                             "«AutoCAD DXF» (2013 o 2018).") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"No se pudo leer el DXF ({error}).") from error


def _lineas(doc, capas: Optional[Sequence[str]] = None):
    """(capa, [(x, y, z)…]) de cada línea del espacio modelo, en coordenadas del dibujo (WCS)."""
    from ezdxf import path as caminos

    elegidas = None if capas is None else set(capas)
    for entidad in doc.modelspace().query(TIPOS):
        capa = entidad.dxf.layer or "0"
        if elegidas is not None and capa not in elegidas:
            continue
        try:
            camino = caminos.make_path(entidad)
        except (TypeError, ValueError):
            continue
        puntos = [(v.x, v.y, v.z) for v in camino.flattening(APLANADO_M)]
        if len(puntos) >= 2:
            yield capa, puntos


def leer_dxf(ruta) -> ContenidoDxf:
    """Capas del DXF con el número de líneas y el rango de cotas de cada una."""
    doc = _abrir(ruta)
    capas = {}
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    for nombre, puntos in _lineas(doc):
        capa = capas.setdefault(nombre, CapaCad(nombre))
        capa.lineas += 1
        zs = [p[2] for p in puntos]
        if any(z != 0 for z in zs):
            capa.con_cota += 1
            capa.cota_min = min(zs) if capa.cota_min is None else min(capa.cota_min, min(zs))
            capa.cota_max = max(zs) if capa.cota_max is None else max(capa.cota_max, max(zs))
        xmin, xmax = min(xmin, min(p[0] for p in puntos)), max(xmax, max(p[0] for p in puntos))
        ymin, ymax = min(ymin, min(p[1] for p in puntos)), max(ymax, max(p[1] for p in puntos))
    if not capas:
        raise ValueError("El DXF no tiene líneas ni polilíneas en el espacio modelo.")
    return ContenidoDxf(sorted(capas.values(), key=lambda c: c.nombre.lower()), (xmin, xmax, ymin, ymax))


# ------------------------------------------------------------------ DEM


def generar_dem(ruta_dxf: str, capas_curvas: Sequence[str], paso_m: float = 1.0, distancia_max_m: float = 30.0,
                progreso: Optional[Callable[[float, str], None]] = None) -> ResultadoDem:
    """DEM por TIN de las curvas de las capas elegidas, con celdas de `paso_m`.

    Las celdas a más de `distancia_max_m` de la curva más cercana quedan sin dato (NODATA), como en el complemento.
    """
    import numpy as np
    from scipy.ndimage import distance_transform_edt
    from scipy.spatial import Delaunay, QhullError

    if not capas_curvas:
        raise ValueError("Elija al menos una capa de curvas de nivel.")
    if paso_m <= 0 or distancia_max_m <= 0:
        raise ValueError("El tamaño de celda y la distancia máxima deben ser positivos.")
    avisar = progreso or (lambda fraccion, texto: None)
    avisos: List[str] = []

    avisar(0.0, "Leyendo las curvas del DXF…")
    doc = _abrir(ruta_dxf)
    curvas, vertices, sin_cota = [], [], 0
    for _, puntos in _lineas(doc, capas_curvas):
        zs = [p[2] for p in puntos]
        if not any(z != 0 for z in zs):
            sin_cota += 1
            continue
        cota = zs[0] if max(zs) - min(zs) < 1e-6 else None
        curvas.append((cota, [(p[0], p[1]) for p in puntos]))
        vertices.extend(puntos)
    del doc
    if not curvas:
        raise ValueError("Las capas elegidas no tienen líneas con elevación. Revise en el CAD que las curvas "
                         "sean polilíneas con su cota (propiedad «Elevación»).")
    if sin_cota:
        avisos.append(f"{sin_cota} líneas sin elevación (Z = 0) no se usaron.")

    xyz = np.unique(np.asarray(vertices, dtype=float), axis=0)
    # El mismo punto con dos cotas (curvas que se tocan): se queda una, si no Qhull rechaza el TIN
    _, unicos = np.unique(np.round(xyz[:, :2], 4), axis=0, return_index=True)
    xyz = xyz[np.sort(unicos)]
    if len(np.unique(xyz[:, 2])) < 2:
        raise ValueError("Las curvas tienen todas la misma cota: no forman superficie.")
    xmin, ymin = xyz[:, 0].min(), xyz[:, 1].min()
    xmax, ymax = xyz[:, 0].max(), xyz[:, 1].max()
    x0 = math.floor(xmin / paso_m) * paso_m
    y1 = math.ceil(ymax / paso_m) * paso_m
    columnas = math.floor((xmax - x0) / paso_m) + 1  # +1: la curva del borde queda dentro de una celda
    filas = math.floor((y1 - ymin) / paso_m) + 1
    if columnas * filas > MAX_CELDAS:
        sugerido = math.ceil(math.sqrt((xmax - xmin) * (ymax - ymin) / MAX_CELDAS) * 4) / 4
        raise ValueError(f"El DEM tendría {columnas * filas / 1e6:.0f} millones de celdas. Use una celda de "
                         f"{sugerido:g} m o más, o recorte el dibujo a la zona del proyecto.")

    avisar(0.15, "Triangulando las curvas (TIN)…")
    try:
        triangulos = Delaunay(xyz[:, :2]).simplices
    except QhullError as error:
        raise ValueError(f"No se pudo triangular las curvas ({error}).") from None
    # Celdas a menos de la distancia máxima de una curva: se marcan las celdas que tocan las curvas (puntos cada
    # media celda a lo largo de ellas) y se mide la distancia a la marca más cercana, como GDAL ComputeProximity
    avisar(0.3, "Midiendo la distancia a las curvas…")
    lineas = [np.asarray(puntos, dtype=float) for _, puntos in curvas]
    a = np.concatenate([p[:-1] for p in lineas])
    b = np.concatenate([p[1:] for p in lineas])
    partes = np.maximum(1, np.ceil(np.hypot(*(b - a).T) / (paso_m / 2)).astype(np.int64))
    tramo = np.repeat(np.arange(len(partes)), partes)
    t = (np.arange(partes.sum()) - np.repeat(np.cumsum(partes) - partes, partes)) / partes[tramo]
    muestras = np.concatenate([a[tramo] + (b - a)[tramo] * t[:, None]] + [p[-1:] for p in lineas])
    marcas = np.zeros((filas, columnas), dtype=bool)
    marcas[np.clip(((y1 - muestras[:, 1]) / paso_m).astype(np.int64), 0, filas - 1),
           np.clip(((muestras[:, 0] - x0) / paso_m).astype(np.int64), 0, columnas - 1)] = True
    cerca = distance_transform_edt(~marcas, sampling=paso_m) <= distancia_max_m
    del marcas, muestras

    avisar(0.4, "Interpolando el DEM…")
    cotas = _rasterizar_tin(xyz, triangulos, x0, y1, paso_m, columnas, filas,
                            lambda f: avisar(0.4 + 0.45 * f, "Interpolando el DEM…"), cerca)
    cotas[~cerca] = NODATA
    del cerca

    con_dato = cotas != NODATA
    if not con_dato.any():
        raise ValueError("El DEM quedó vacío: las curvas no forman superficie.")
    # Solo el recuadro con datos
    filas_con = np.nonzero(con_dato.any(axis=1))[0]
    columnas_con = np.nonzero(con_dato.any(axis=0))[0]
    f0, f1, c0, c1 = filas_con[0], filas_con[-1] + 1, columnas_con[0], columnas_con[-1] + 1
    cotas = np.ascontiguousarray(cotas[f0:f1, c0:c1])
    x0, y1 = x0 + c0 * paso_m, y1 - f0 * paso_m
    filas, columnas = cotas.shape
    validas = cotas[cotas != NODATA]
    avisar(0.9, "Guardando el DEM…")
    rejilla = rejilla_a_bytes(cotas.astype("<f4").tobytes(), columnas, filas, x0, y1 - filas * paso_m, paso_m,
                              NODATA)
    avisar(1.0, "Listo")
    return ResultadoDem(rejilla, curvas, paso_m, columnas, filas, float(validas.min()), float(validas.max()),
                        validas.size / cotas.size, avisos)


def _rasterizar_tin(xyz, triangulos, x0, y1, paso_m, columnas, filas, avance=None, cerca=None):
    """Cota lineal de cada triángulo en los centros de celda que cubre (NODATA fuera del TIN).

    Es lo que hace `gdal_grid -a linear`. Buscar el triángulo de cada celda (LinearNDInterpolator) se atasca con
    los triángulos largos y finos que dejan las curvas de nivel; aquí se recorre al revés: cada triángulo marca
    sus celdas. Los triángulos se agrupan por el tamaño de su recuadro para hacerlo con numpy por bloques. Con
    `cerca` (celdas que interesan) se saltan los triángulos cuyo recuadro no toca ninguna.
    """
    import numpy as np

    cotas = np.full((filas, columnas), NODATA)
    u = (xyz[:, 0] - x0) / paso_m - 0.5  # columna del centro de celda, en decimales
    v = (y1 - xyz[:, 1]) / paso_m - 0.5  # fila
    tu, tv, tz = u[triangulos], v[triangulos], xyz[:, 2][triangulos]
    cmin = np.clip(np.ceil(tu.min(axis=1)), 0, columnas).astype(np.int64)
    cmax = np.clip(np.floor(tu.max(axis=1)), -1, columnas - 1).astype(np.int64)
    rmin = np.clip(np.ceil(tv.min(axis=1)), 0, filas).astype(np.int64)
    rmax = np.clip(np.floor(tv.max(axis=1)), -1, filas - 1).astype(np.int64)
    ancho, alto = cmax - cmin + 1, rmax - rmin + 1
    det = (tv[:, 1] - tv[:, 2]) * (tu[:, 0] - tu[:, 2]) + (tu[:, 2] - tu[:, 1]) * (tv[:, 0] - tv[:, 2])
    utiles = (ancho > 0) & (alto > 0) & (np.abs(det) > 1e-12)
    if cerca is not None:  # suma acumulada 2D: celdas cercanas dentro de cada recuadro en O(1)
        integral = np.zeros((filas + 1, columnas + 1), dtype=np.int64)
        integral[1:, 1:] = cerca.cumsum(axis=0).cumsum(axis=1)
        f0, f1 = np.clip(rmin, 0, filas), np.clip(rmax + 1, 0, filas)
        k0, k1 = np.clip(cmin, 0, columnas), np.clip(cmax + 1, 0, columnas)
        utiles &= (integral[f1, k1] - integral[f0, k1] - integral[f1, k0] + integral[f0, k0]) > 0
        del integral
    lado = np.maximum(ancho, alto)
    hechos, total = 0, int(utiles.sum()) or 1
    anterior = 0
    for tope in (1, 2, 4, 8, 16, 32, 64, math.inf):
        grupo = np.nonzero(utiles & (lado > anterior) & (lado <= tope))[0]
        anterior = tope
        if not grupo.size:
            continue
        if tope == math.inf:  # triángulos enormes (bordes del TIN): pocos, de a uno y por filas
            for i in grupo:
                _rasterizar_uno(cotas, tu[i], tv[i], tz[i], det[i], cmin[i], cmax[i], rmin[i], rmax[i])
            continue
        por_bloque = max(1, 4_000_000 // (tope * tope))
        dc, dr = np.meshgrid(np.arange(tope), np.arange(tope))
        dc, dr = dc.ravel(), dr.ravel()
        for inicio in range(0, grupo.size, por_bloque):
            t = grupo[inicio:inicio + por_bloque]
            c = cmin[t][:, None] + dc[None, :]
            r = rmin[t][:, None] + dr[None, :]
            dentro_recuadro = (c <= cmax[t][:, None]) & (r <= rmax[t][:, None])
            a, b, z = tu[t], tv[t], tz[t]
            l1 = ((b[:, 1:2] - b[:, 2:3]) * (c - a[:, 2:3]) + (a[:, 2:3] - a[:, 1:2]) * (r - b[:, 2:3])) / det[t][:, None]
            l2 = ((b[:, 2:3] - b[:, 0:1]) * (c - a[:, 2:3]) + (a[:, 0:1] - a[:, 2:3]) * (r - b[:, 2:3])) / det[t][:, None]
            l3 = 1.0 - l1 - l2
            dentro = dentro_recuadro & (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            valor = l1 * z[:, 0:1] + l2 * z[:, 1:2] + l3 * z[:, 2:3]
            cotas[r[dentro], c[dentro]] = valor[dentro]
            hechos += t.size
            if avance:
                avance(min(1.0, hechos / total))
    return cotas


def _rasterizar_uno(cotas, a, b, z, det, cmin, cmax, rmin, rmax):
    """Un triángulo grande: en cada fila, solo el tramo que cae dentro de él (todo con numpy)."""
    import numpy as np

    r = np.arange(rmin, rmax + 1, dtype=float)
    desde = np.full(r.shape, np.inf)
    hasta = np.full(r.shape, -np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if b[i] == b[j]:
            continue
        cruza = (b[i] - r) * (b[j] - r) <= 0
        u = a[i] + (r - b[i]) * (a[j] - a[i]) / (b[j] - b[i])
        desde = np.where(cruza, np.minimum(desde, u), desde)
        hasta = np.where(cruza, np.maximum(hasta, u), hasta)
    validas = np.isfinite(desde)
    c0 = np.maximum(cmin, np.ceil(desde[validas] - 1e-9)).astype(np.int64)
    c1 = np.minimum(cmax, np.floor(hasta[validas] + 1e-9)).astype(np.int64)
    largo = np.maximum(0, c1 - c0 + 1)
    if not largo.sum():
        return
    filas = np.repeat(r[validas].astype(np.int64), largo)
    c = np.repeat(c0, largo) + (np.arange(largo.sum()) - np.repeat(np.cumsum(largo) - largo, largo))
    l1 = ((b[1] - b[2]) * (c - a[2]) + (a[2] - a[1]) * (filas - b[2])) / det
    l2 = ((b[2] - b[0]) * (c - a[2]) + (a[0] - a[2]) * (filas - b[2])) / det
    cotas[filas, c] = l1 * z[0] + l2 * z[1] + (1.0 - l1 - l2) * z[2]


# ------------------------------------------------------------------ curvas guardadas en el proyecto


def curvas_a_bytes(curvas) -> bytes:
    datos = [[None if c is None else round(c, 3), [[round(x, 2), round(y, 2)] for x, y in puntos]]
             for c, puntos in curvas]
    return gzip.compress(json.dumps(datos, separators=(",", ":")).encode("utf-8"), 6)


def curvas_de_bytes(contenido: bytes) -> List[Curva]:
    return [(c, [(x, y) for x, y in puntos]) for c, puntos in json.loads(gzip.decompress(contenido))]


def nombre_archivo(prefijo: str, contenido: bytes, extension: str) -> str:
    """Nombre por contenido: dos terrenos distintos no se pisan (deshacer vuelve al anterior)."""
    return f"{prefijo}_{hashlib.sha1(contenido).hexdigest()[:10]}{extension}"


def equidistancia(curvas) -> Optional[float]:
    """La separación más común entre cotas vecinas (para marcar las curvas maestras); None si no se sabe."""
    cotas = sorted({round(c, 3) for c, _ in curvas if c is not None})
    saltos = Counter(round(b - a, 3) for a, b in zip(cotas, cotas[1:]) if b - a > 1e-6)
    return saltos.most_common(1)[0][0] if saltos else None
