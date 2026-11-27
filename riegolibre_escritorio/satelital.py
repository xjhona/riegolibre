# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Imagen satelital de fondo del programa de escritorio: teselas XYZ reproyectadas a la cuadrícula UTM. Sin Qt.

Lo mismo que hace el complemento con QGIS (`riegolibre/integracion/imagen_satelital.py`), sin QGIS ni pyproj:

- UTM ↔ geográficas con las series de Krüger de la Mercator transversa (precisión mucho mejor que un centímetro
  dentro de la zona), sobre el elipsoide WGS 84;
- índices de las teselas (Web Mercator, 256 píxeles) y prueba del mayor zoom con imagen real en el centro;
- descarga con `urllib` (varias a la vez), mosaico y reproyección bilineal a la cuadrícula UTM con numpy.

Leer y escribir JPEG o PNG no se puede con la biblioteca estándar ni con numpy: la ventana pasa una función
`decodificar(bytes) -> matriz filas × columnas × 3` (con Qt).
"""

import datetime
import json
import math
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

LADO_TESELA = 256
ZOOM_MINIMO_PRUEBA = 14
MAX_PIXELES = 40_000_000  # de la imagen final (en memoria como mapa de bits de la ventana: ~160 MB)
MAX_TESELAS = 3000
DESCARGAS_A_LA_VEZ = 8
ESPERA_S = 20
FILAS_POR_BLOQUE = 512  # filas de la imagen final que se reproyectan de una vez (acota la memoria)
USUARIO = "RiegoLibre (programa de escritorio de diseño de riego)"  # genérico: sin datos del usuario
GRIS_SIN_IMAGEN = 224  # donde el servicio no tiene tesela


class Cancelado(Exception):
    """El usuario canceló la descarga."""


@dataclass(frozen=True)
class FuenteTeselas:
    nombre: str
    url: str  # con {x}, {y} y {z}
    zoom_max: int
    atribucion: str
    url_disponibilidad: str = ""  # Esri: dice si la tesela tiene imagen real


# Las mismas del complemento (riegolibre/integracion/imagen_satelital.py)
FUENTES = (
    FuenteTeselas("Google Satélite", "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", 20, "© Google"),
    FuenteTeselas("Esri World Imagery",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                  19, "© Esri, Maxar, Earthstar Geographics",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tilemap/{z}/{y}/{x}/1/1"),
)


def fuente_por_nombre(nombre: str) -> FuenteTeselas:
    for fuente in FUENTES:
        if fuente.nombre == nombre:
            return fuente
    raise ValueError(f"Fuente de imagen desconocida: «{nombre}».")


# ------------------------------------------------------------------ UTM ↔ geográficas (WGS 84)

A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
K0 = 0.9996
FALSO_ESTE = 500000.0
FALSO_NORTE_SUR = 10000000.0

_N = F_WGS84 / (2 - F_WGS84)
_A = A_WGS84 / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64 + _N ** 6 / 256)
_E = math.sqrt(F_WGS84 * (2 - F_WGS84))  # excentricidad
# Series de Krüger hasta n⁶ (Karney, «Transverse Mercator with an accuracy of a few nanometers», 2011)
_ALFA = (
    _N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16 + 41 * _N ** 4 / 180 - 127 * _N ** 5 / 288 + 7891 * _N ** 6 / 37800,
    13 * _N ** 2 / 48 - 3 * _N ** 3 / 5 + 557 * _N ** 4 / 1440 + 281 * _N ** 5 / 630 - 1983433 * _N ** 6 / 1935360,
    61 * _N ** 3 / 240 - 103 * _N ** 4 / 140 + 15061 * _N ** 5 / 26880 + 167603 * _N ** 6 / 181440,
    49561 * _N ** 4 / 161280 - 179 * _N ** 5 / 168 + 6601661 * _N ** 6 / 7257600,
    34729 * _N ** 5 / 80640 - 3418889 * _N ** 6 / 1995840,
    212378941 * _N ** 6 / 319334400,
)
_BETA = (
    _N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360 - 81 * _N ** 5 / 512 + 96199 * _N ** 6 / 604800,
    _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440 + 46 * _N ** 5 / 105 - 1118711 * _N ** 6 / 3870720,
    17 * _N ** 3 / 480 - 37 * _N ** 4 / 840 - 209 * _N ** 5 / 4480 + 5569 * _N ** 6 / 90720,
    4397 * _N ** 4 / 161280 - 11 * _N ** 5 / 504 - 830251 * _N ** 6 / 7257600,
    4583 * _N ** 5 / 161280 - 108847 * _N ** 6 / 3991680,
    20648693 * _N ** 6 / 638668800,
)


def _np():
    import numpy
    return numpy


def meridiano_central(zona: int) -> float:
    return -183.0 + 6.0 * zona


def _latitud_de_tau(tau_prima, np):
    """Latitud (radianes) desde tan χ de la latitud conforme, por Newton (Karney, ec. 19-21)."""
    tau = tau_prima
    for _ in range(5):
        raiz = np.sqrt(1 + tau * tau)
        sigma = np.sinh(_E * np.arctanh(_E * tau / raiz))
        tau_p = tau * np.sqrt(1 + sigma * sigma) - sigma * raiz
        derivada = (1 - _E ** 2) * np.sqrt(1 + tau_p * tau_p) * raiz / ((1 - _E ** 2) * tau * tau + 1)
        tau = tau + (tau_prima - tau_p) / derivada
    return np.arctan(tau)


def geograficas_a_utm(lon, lat, zona: int, sur: bool):
    """(este, norte) en metros de puntos en grados (números o matrices de numpy)."""
    np = _np()
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    fi = np.radians(lat)
    lam = np.radians(lon - meridiano_central(zona))
    tau = np.tan(fi)
    sigma = np.sinh(_E * np.arctanh(_E * np.sin(fi)))
    tau_p = tau * np.sqrt(1 + sigma * sigma) - sigma * np.sqrt(1 + tau * tau)  # tan de la latitud conforme
    xi_p = np.arctan2(tau_p, np.cos(lam))
    eta_p = np.arcsinh(np.sin(lam) / np.hypot(tau_p, np.cos(lam)))
    xi, eta = xi_p.copy(), eta_p.copy()
    for j, alfa in enumerate(_ALFA, 1):
        xi = xi + alfa * np.sin(2 * j * xi_p) * np.cosh(2 * j * eta_p)
        eta = eta + alfa * np.cos(2 * j * xi_p) * np.sinh(2 * j * eta_p)
    este = FALSO_ESTE + K0 * _A * eta
    norte = K0 * _A * xi + (FALSO_NORTE_SUR if sur else 0.0)
    return _escalar(este), _escalar(norte)


def utm_a_geograficas(este, norte, zona: int, sur: bool):
    """(lon, lat) en grados de puntos UTM (números o matrices de numpy)."""
    np = _np()
    este, norte = np.asarray(este, float), np.asarray(norte, float)
    xi = (norte - (FALSO_NORTE_SUR if sur else 0.0)) / (K0 * _A)
    eta = (este - FALSO_ESTE) / (K0 * _A)
    xi_p, eta_p = xi.copy(), eta.copy()
    for j, beta in enumerate(_BETA, 1):
        xi_p = xi_p - beta * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta_p = eta_p - beta * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    tau_p = np.sin(xi_p) / np.hypot(np.sinh(eta_p), np.cos(xi_p))
    lam = np.arctan2(np.sinh(eta_p), np.cos(xi_p))
    fi = _latitud_de_tau(tau_p, np)
    return _escalar(np.degrees(lam) + meridiano_central(zona)), _escalar(np.degrees(fi))


def _escalar(valor):
    return float(valor) if getattr(valor, "ndim", 1) == 0 else valor


# ------------------------------------------------------------------ teselas (Web Mercator)

LAT_MAX = 85.05112878


def pixel_global(lon, lat, zoom: int):
    """Posición en píxeles del mundo entero a ese zoom (256 · 2^zoom de lado), con decimales."""
    np = _np()
    lado = LADO_TESELA * 2 ** zoom
    lat = np.clip(np.asarray(lat, float), -LAT_MAX, LAT_MAX)
    x = (np.asarray(lon, float) + 180.0) / 360.0 * lado
    y = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * lado
    return _escalar(x), _escalar(y)


def tesela(lon: float, lat: float, zoom: int) -> Tuple[int, int]:
    """Índices (x, y) de la tesela XYZ que contiene el punto."""
    n = 2 ** zoom
    x, y = pixel_global(lon, lat, zoom)
    return min(int(x // LADO_TESELA), n - 1), min(int(y // LADO_TESELA), n - 1)


def metros_por_pixel(lat: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** zoom


def zoom_para_resolucion(lat: float, resolucion_m: float, zoom_max: int) -> int:
    """El menor zoom cuya imagen tiene píxeles de `resolucion_m` o menos (sin pasar de `zoom_max`)."""
    for zoom in range(0, zoom_max + 1):
        if metros_por_pixel(lat, zoom) <= resolucion_m:
            return zoom
    return zoom_max


@dataclass
class Cuadricula:
    """Cuadrícula UTM de la imagen final: esquina superior izquierda, tamaño del píxel, columnas y filas."""
    xmin: float
    ymax: float
    resolucion_m: float
    columnas: int
    filas: int

    @property
    def esquinas(self):
        """[xmin, ymin, xmax, ymax]"""
        return [self.xmin, self.ymax - self.filas * self.resolucion_m, self.xmin + self.columnas * self.resolucion_m,
                self.ymax]

    @property
    def pixeles(self) -> int:
        return self.columnas * self.filas


def cuadricula(zona_utm, resolucion_m: float) -> Cuadricula:
    """Cuadrícula que cubre (xmin, ymin, xmax, ymax), con los bordes en múltiplos de la resolución."""
    if resolucion_m <= 0:
        raise ValueError("La resolución debe ser positiva.")
    xmin, ymin, xmax, ymax = zona_utm
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("La zona de la imagen está vacía.")
    x0 = math.floor(xmin / resolucion_m) * resolucion_m
    y1 = math.ceil(ymax / resolucion_m) * resolucion_m
    columnas = max(1, math.ceil((xmax - x0) / resolucion_m - 1e-9))
    filas = max(1, math.ceil((y1 - ymin) / resolucion_m - 1e-9))
    return Cuadricula(x0, y1, resolucion_m, columnas, filas)


def _nodos(c: Cuadricula, zona: int, sur: bool, zoom: int, filas=None):
    """Posición en píxeles globales (a ese zoom) del centro de cada píxel de la cuadrícula (o de unas filas)."""
    np = _np()
    f0, f1 = filas if filas else (0, c.filas)
    xs = c.xmin + (np.arange(c.columnas) + 0.5) * c.resolucion_m
    ys = c.ymax - (np.arange(f0, f1) + 0.5) * c.resolucion_m
    este, norte = np.meshgrid(xs, ys)
    lon, lat = utm_a_geograficas(este, norte, zona, sur)
    return pixel_global(lon, lat, zoom)


def teselas_necesarias(c: Cuadricula, zona: int, sur: bool, zoom: int):
    """(tx0, ty0, tx1, ty1): rango de teselas (inclusive) que cubre la cuadrícula a ese zoom."""
    np = _np()
    # El borde de la cuadrícula basta: la proyección no tiene extremos adentro de una zona tan chica
    esquinas_x = [c.xmin, c.xmin + c.columnas * c.resolucion_m]
    esquinas_y = [c.ymax - c.filas * c.resolucion_m, c.ymax]
    pasos = 32
    xs = np.concatenate([np.linspace(*esquinas_x, pasos), np.linspace(*esquinas_x, pasos),
                         np.full(pasos, esquinas_x[0]), np.full(pasos, esquinas_x[1])])
    ys = np.concatenate([np.full(pasos, esquinas_y[0]), np.full(pasos, esquinas_y[1]),
                         np.linspace(*esquinas_y, pasos), np.linspace(*esquinas_y, pasos)])
    lon, lat = utm_a_geograficas(xs, ys, zona, sur)
    px, py = pixel_global(lon, lat, zoom)
    n = 2 ** zoom - 1
    limitar = lambda v: int(min(n, max(0, v // LADO_TESELA)))  # noqa: E731
    return limitar(px.min()), limitar(py.min()), limitar(px.max()), limitar(py.max())


def reproyectar(mosaico, tx0: int, ty0: int, zoom: int, c: Cuadricula, zona: int, sur: bool,
                al_avanzar: Optional[Callable[[float], None]] = None):
    """Imagen en la cuadrícula UTM (filas × columnas × canales, del tipo del mosaico) desde el mosaico de
    teselas, con interpolación bilineal. `tx0, ty0` es la tesela de la esquina superior izquierda del mosaico."""
    np = _np()
    entero = mosaico.dtype == np.uint8
    salida = np.empty((c.filas, c.columnas) + mosaico.shape[2:], mosaico.dtype)
    alto, ancho = mosaico.shape[:2]
    for f0 in range(0, c.filas, FILAS_POR_BLOQUE):
        f1 = min(c.filas, f0 + FILAS_POR_BLOQUE)
        px, py = _nodos(c, zona, sur, zoom, (f0, f1))
        # Centro del píxel (i, j) del mosaico en (i + 0.5, j + 0.5)
        u = px - tx0 * LADO_TESELA - 0.5
        v = py - ty0 * LADO_TESELA - 0.5
        u = np.clip(u, 0, ancho - 1)
        v = np.clip(v, 0, alto - 1)
        i0 = np.minimum(np.floor(u).astype(np.int64), ancho - 2 if ancho > 1 else 0)
        j0 = np.minimum(np.floor(v).astype(np.int64), alto - 2 if alto > 1 else 0)
        du = (u - i0)[..., None]
        dv = (v - j0)[..., None]
        i1 = np.minimum(i0 + 1, ancho - 1)
        j1 = np.minimum(j0 + 1, alto - 1)
        arriba = mosaico[j0, i0] * (1 - du) + mosaico[j0, i1] * du
        abajo = mosaico[j1, i0] * (1 - du) + mosaico[j1, i1] * du
        valor = arriba * (1 - dv) + abajo * dv
        salida[f0:f1] = np.clip(np.rint(valor), 0, 255).astype(np.uint8) if entero else valor
        if al_avanzar:
            al_avanzar(f1 / c.filas)
    return salida


# ------------------------------------------------------------------ red

def descargar(url: str) -> Tuple[Optional[bytes], str]:
    """(contenido, tipo) de la dirección; (None, "") si el servidor dice que no existe (404).

    Lanza OSError si no hubo respuesta (sin internet, servidor caído)."""
    peticion = urllib.request.Request(url, headers={"User-Agent": USUARIO})
    try:
        with urllib.request.urlopen(peticion, timeout=ESPERA_S) as respuesta:
            return respuesta.read(), respuesta.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        if error.code in (404, 204):
            return None, ""
        raise OSError(f"el servidor respondió {error.code}") from None


def tiene_imagen(fuente: FuenteTeselas, lon: float, lat: float, zoom: int) -> Optional[bool]:
    """True/False según el servicio tenga imagen en ese zoom; None si no hubo respuesta."""
    x, y = tesela(lon, lat, zoom)
    try:
        if fuente.url_disponibilidad:
            contenido, _ = descargar(fuente.url_disponibilidad.format(x=x, y=y, z=zoom))
            if contenido is None:
                return False
            try:
                return json.loads(contenido.decode("utf-8")).get("data", [0])[0] == 1
            except (ValueError, IndexError, AttributeError):
                return None
        contenido, tipo = descargar(fuente.url.format(x=x, y=y, z=zoom))
    except OSError:
        return None
    if contenido is None:
        return False  # Google responde 404 donde no hay imagen
    return tipo.startswith("image/") and len(contenido) > 0


def zoom_disponible(fuente: FuenteTeselas, lon: float, lat: float, zoom_max: Optional[int] = None) -> int:
    """Mayor zoom (hasta `zoom_max`) con imagen real en el punto. ValueError si el servicio no responde."""
    respondio = False
    for zoom in range(min(zoom_max or fuente.zoom_max, fuente.zoom_max), ZOOM_MINIMO_PRUEBA - 1, -1):
        hay = tiene_imagen(fuente, lon, lat, zoom)
        respondio = respondio or hay is not None
        if hay:
            return zoom
    if not respondio:
        raise ValueError(f"No hubo respuesta de «{fuente.nombre}». Revise la conexión a internet.")
    raise ValueError(f"«{fuente.nombre}» no tiene imagen de esta zona.")


# ------------------------------------------------------------------ todo junto

@dataclass
class ImagenDescargada:
    pixeles: object  # matriz numpy filas × columnas × 3 (uint8), la fila 0 al norte
    cuadricula: Cuadricula
    fuente: FuenteTeselas
    zoom: int
    metros_por_pixel_fuente: float
    teselas: int
    faltantes: int  # teselas que el servicio no tenía (quedan en gris)
    avisos: list = field(default_factory=list)

    def descripcion(self, archivo: str) -> dict:
        """Lo que se guarda en `datos["imagen"]`."""
        return {"archivo": archivo, "esquinas": [round(v, 3) for v in self.cuadricula.esquinas],
                "columnas": self.cuadricula.columnas, "filas": self.cuadricula.filas,
                "resolucion_m": self.cuadricula.resolucion_m, "fuente": self.fuente.nombre, "zoom": self.zoom,
                "fecha": datetime.date.today().isoformat(), "atribucion": self.fuente.atribucion}


def estimar(zona_utm, resolucion_m: float, zona: int, sur: bool, zoom: int) -> Tuple[int, int]:
    """(píxeles de la imagen final, teselas por descargar) para avisar antes de descargar."""
    c = cuadricula(zona_utm, resolucion_m)
    tx0, ty0, tx1, ty1 = teselas_necesarias(c, zona, sur, zoom)
    return c.pixeles, (tx1 - tx0 + 1) * (ty1 - ty0 + 1)


def descargar_imagen(fuente: FuenteTeselas, zona_utm, resolucion_m: float, zona: int, sur: bool,
                     decodificar: Callable[[bytes], object],
                     avance: Optional[Callable[[float, str], bool]] = None) -> ImagenDescargada:
    """Descarga y reproyecta la imagen de la zona (xmin, ymin, xmax, ymax) en UTM.

    `decodificar(bytes)` devuelve la tesela como matriz 256 × 256 × 3 (uint8). `avance(fracción, texto)`
    devuelve False si el usuario canceló (se lanza `Cancelado`). Errores de red: ValueError con el mensaje.
    """
    np = _np()

    def avisar(fraccion, texto):
        if avance is not None and avance(fraccion, texto) is False:
            raise Cancelado()

    c = cuadricula(zona_utm, resolucion_m)
    if c.pixeles > MAX_PIXELES:
        sugerida = math.ceil(math.sqrt(c.pixeles / MAX_PIXELES) * resolucion_m * 10) / 10
        raise ValueError(f"La imagen tendría {c.pixeles / 1e6:.0f} millones de píxeles. "
                         f"Use una resolución de {sugerida:g} m o más, o una zona más chica.")
    xmin, ymin, xmax, ymax = c.esquinas
    lon, lat = utm_a_geograficas((xmin + xmax) / 2, (ymin + ymax) / 2, zona, sur)
    avisar(0.0, f"Consultando el zoom disponible en «{fuente.nombre}»…")
    buscado = zoom_para_resolucion(lat, resolucion_m, fuente.zoom_max)
    # El menor entre el zoom que da la resolución pedida y el mayor con imagen real en el centro
    zoom = min(buscado, zoom_disponible(fuente, lon, lat, max(buscado, ZOOM_MINIMO_PRUEBA)))
    avisos = []
    if metros_por_pixel(lat, zoom) > resolucion_m * 1.5:
        avisos.append(f"«{fuente.nombre}» llega hasta el zoom {zoom} en esta zona: la imagen tiene píxeles de "
                      f"{metros_por_pixel(lat, zoom):.2f} m, más gruesos que los {resolucion_m:g} m pedidos.")
    tx0, ty0, tx1, ty1 = teselas_necesarias(c, zona, sur, zoom)
    indices = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    if len(indices) > MAX_TESELAS:
        raise ValueError(f"Habría que descargar {len(indices)} teselas: use una resolución más gruesa o una "
                         "zona más chica.")

    mosaico = np.full(((ty1 - ty0 + 1) * LADO_TESELA, (tx1 - tx0 + 1) * LADO_TESELA, 3), GRIS_SIN_IMAGEN, np.uint8)
    faltantes, sin_respuesta = 0, 0
    resultados: Dict[Tuple[int, int], Optional[bytes]] = {}

    def bajar(indice):
        tx, ty = indice
        try:
            return indice, descargar(fuente.url.format(x=tx, y=ty, z=zoom))[0], None
        except OSError as error:
            return indice, None, error

    with ThreadPoolExecutor(DESCARGAS_A_LA_VEZ) as grupo:
        tareas = [grupo.submit(bajar, i) for i in indices]
        try:
            for hechas, tarea in enumerate(tareas, 1):
                indice, contenido, error = tarea.result()
                if error is not None:
                    sin_respuesta += 1
                resultados[indice] = contenido
                avisar(0.05 + 0.75 * hechas / len(indices), f"Descargando las teselas ({hechas} de {len(indices)}, "
                                                           f"zoom {zoom})…")
        except Cancelado:
            for tarea in tareas:
                tarea.cancel()
            raise
    if sin_respuesta == len(indices) or sin_respuesta > len(indices) // 4:
        raise ValueError(f"No hubo respuesta de «{fuente.nombre}» ({sin_respuesta} de {len(indices)} teselas). "
                         "Revise la conexión a internet.")
    for (tx, ty), contenido in resultados.items():
        teselita = None
        if contenido:
            try:
                teselita = decodificar(contenido)
            except ValueError:
                teselita = None
        if teselita is None or teselita.shape[:2] != (LADO_TESELA, LADO_TESELA):
            faltantes += 1
            continue
        f, k = (ty - ty0) * LADO_TESELA, (tx - tx0) * LADO_TESELA
        mosaico[f:f + LADO_TESELA, k:k + LADO_TESELA] = teselita[:, :, :3]
    if faltantes == len(indices):
        raise ValueError(f"«{fuente.nombre}» no devolvió imagen para esta zona.")
    if faltantes:
        avisos.append(f"{faltantes} de {len(indices)} teselas no tenían imagen (quedan en gris).")
    avisar(0.8, "Ubicando la imagen en la cuadrícula UTM…")
    pixeles = reproyectar(mosaico, tx0, ty0, zoom, c, zona, sur,
                          lambda f: avisar(0.8 + 0.15 * f, "Ubicando la imagen en la cuadrícula UTM…"))
    return ImagenDescargada(pixeles, c, fuente, zoom, metros_por_pixel(lat, zoom), len(indices), faltantes, avisos)


# ------------------------------------------------------------------ imagen propia (archivo de mundo)

EXTENSIONES_MUNDO = {".jpg": ".jgw", ".jpeg": ".jgw", ".png": ".pgw"}


def ruta_archivo_mundo(ruta_imagen: str) -> Optional[str]:
    """El archivo de mundo junto a la imagen (.jgw, .pgw o .wld); None si no hay."""
    base, extension = os.path.splitext(ruta_imagen)
    candidatos = [EXTENSIONES_MUNDO.get(extension.lower(), ""), ".wld",
                  extension[:2] + extension[-1:] + "w" if len(extension) == 4 else ""]
    for candidato in candidatos:
        for variante in (candidato, candidato.upper()):
            if variante and os.path.exists(base + variante):
                return base + variante
    return None


def leer_archivo_mundo(texto: str, columnas: int, filas: int):
    """Esquinas [xmin, ymin, xmax, ymax] de la imagen a partir de su archivo de mundo (6 números)."""
    try:
        a, d, b, e, c, f = [float(linea) for linea in texto.split()[:6]]
    except ValueError:
        raise ValueError("El archivo de mundo no tiene los seis números esperados.") from None
    if abs(d) > 1e-9 or abs(b) > 1e-9:
        raise ValueError("La imagen está girada en su archivo de mundo: no se puede usar como fondo.")
    if a <= 0 or e >= 0:
        raise ValueError("El archivo de mundo tiene un tamaño de píxel no válido.")
    xmin, ymax = c - a / 2, f - e / 2  # (c, f) es el centro del píxel de arriba a la izquierda
    return [xmin, ymax + e * filas, xmin + a * columnas, ymax]
