"""Bloque de goteo de un lote, con los parámetros que fija el proyectista (como el «Tape Irrigation
Block» de IRRICAD).

A diferencia del trazado automático (`nucleo.trazado`), que decide todo sobre un terreno entero, aquí
el lote ya es una subunidad (una válvula) y el proyectista elige:

- la dirección de los laterales (o la deja automática),
- la separación entre hileras y cuántos laterales lleva cada hilera (laterales dobles por cama),
- la cabecera (distancia libre en los extremos de los laterales) y los costados (del borde a la primera
  hilera),
- dónde va el portalateral (al inicio o al final de los laterales, al centro, a una distancia dada o en
  el borde más alto o más bajo del lote),
- dónde va la válvula a lo largo del portalateral (o la marca con un clic en el mapa).

El motor es Python puro: trabaja con anillos de puntos (x, y) en metros. Gira el lote hasta que los
laterales quedan horizontales (hacia +x); las hileras son entonces rectas horizontales y el
portalateral es una polilínea que cruza cada hilera una sola vez.
"""

import math
from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional, Sequence, Tuple

from .trazado import (EPS, Anillo, LateralTrazado, Punto, _intervalos, _verificar, area_anillos,
                      orientaciones_candidatas)

# Posición del portalateral respecto de los laterales
PORTA_INICIO, PORTA_FINAL, PORTA_CENTRO, PORTA_DISTANCIA = "inicio", "final", "centro", "distancia"
PORTA_ALTO, PORTA_BAJO = "alto", "bajo"  # en el borde más alto (laterales en bajada) o más bajo
PORTA_MANUAL = "manual"  # la línea que dibujó el proyectista en el mapa («Manual» de IRRICAD)
POSICIONES_PORTALATERAL = (PORTA_INICIO, PORTA_FINAL, PORTA_CENTRO, PORTA_DISTANCIA, PORTA_ALTO, PORTA_BAJO,
                           PORTA_MANUAL)

# Posición de la válvula a lo largo del portalateral
VALV_AUTO, VALV_ALTO, VALV_BAJO = "auto", "alto", "bajo"
VALV_INICIO, VALV_FINAL, VALV_CENTRO, VALV_PORCENTAJE = "inicio", "final", "centro", "porcentaje"
VALV_PUNTO = "punto"  # en el punto del portalateral más cercano al que marcó el proyectista
POSICIONES_VALVULA = (VALV_AUTO, VALV_ALTO, VALV_BAJO, VALV_INICIO, VALV_FINAL, VALV_CENTRO, VALV_PORCENTAJE,
                      VALV_PUNTO)

# Tipos de tramo de conexión
CONEXION_EXTREMO, CONEXION_LADO_VALVULA, CONEXION_RAMAL_VALVULA = "extremo", "lado_valvula", "ramal_valvula"
NOMBRES_CONEXION = {CONEXION_EXTREMO: "Prolongación del extremo", CONEXION_LADO_VALVULA: "Prolongación del lado de la válvula",
                    CONEXION_RAMAL_VALVULA: "Ramal de la válvula"}

TOLERANCIA_PORTALATERAL_M = 1.0  # para enderezar el portalateral que sigue un borde irregular


@dataclass(frozen=True)
class ParametrosBloque:
    separacion_m: float  # entre hileras (ejes de los grupos de laterales)
    laterales_por_hilera: int = 1
    separacion_en_hilera_m: float = 1.0  # entre los laterales de una misma hilera
    cabecera_m: float = 0.2  # libre entre el extremo de cada lateral y el borde del lote («headlands»)
    costados_m: Optional[float] = None  # del borde al eje de la primera hilera («sidelands»); None: media separación
    angulo_deg: Optional[float] = None  # sentido de los laterales, antihorario desde el eje x; None: automático
    portalateral: str = PORTA_INICIO
    distancia_portalateral_m: float = 0.0  # desde el inicio de los laterales, con PORTA_DISTANCIA
    puntos_portalateral: Tuple[Punto, ...] = ()  # con PORTA_MANUAL: vértices de la línea, en el SRC del lote
    valvula: str = VALV_AUTO
    porcentaje_valvula: float = 50.0  # con VALV_PORCENTAJE, desde el extremo más alto (o el inicio sin cotas)
    punto_valvula: Optional[Punto] = None  # con VALV_PUNTO; sin él, la válvula es automática
    # Tramos de conexión que solo se dibujan y se cuentan en la lista de materiales (no entran en el cálculo)
    prolongacion_extremo_m: float = 0.0  # «Stub Length»: el portalateral sigue más allá del último lateral
    prolongacion_valvula_m: float = 0.0  # «Submain Stub»: lo mismo del lado de la válvula (válvula en un extremo)
    ramal_valvula_m: float = 0.0  # «Valve Stub»: tubería perpendicular del portalateral a la válvula
    longitud_min_m: float = 1.0  # un lateral más corto no se traza
    # Caudal de un lateral según su longitud. Sin él, el «caudal» es la longitud en metros.
    caudal_lateral: Optional[Callable[[float], float]] = field(default=None, compare=False)

    def __post_init__(self):
        if self.separacion_m <= 0:
            raise ValueError("La separación entre hileras debe ser mayor que cero.")
        if self.laterales_por_hilera < 1:
            raise ValueError("Cada hilera necesita al menos un lateral.")
        if self.laterales_por_hilera > 1 and self.separacion_en_hilera_m <= 0:
            raise ValueError("La separación entre los laterales de una hilera debe ser mayor que cero.")
        if self.laterales_por_hilera > 1 and \
                (self.laterales_por_hilera - 1) * self.separacion_en_hilera_m >= self.separacion_m:
            raise ValueError("Los laterales de una hilera no caben en la separación entre hileras.")
        if self.cabecera_m < 0 or (self.costados_m is not None and self.costados_m < 0):
            raise ValueError("La cabecera y los costados no pueden ser negativos.")
        if self.portalateral not in POSICIONES_PORTALATERAL:
            raise ValueError(f"Posición del portalateral no válida: {self.portalateral!r}.")
        if self.portalateral == PORTA_MANUAL and len({tuple(p) for p in self.puntos_portalateral}) < 2:
            raise ValueError("Dibuje el portalateral en el mapa: hacen falta al menos dos puntos distintos.")
        if self.valvula not in POSICIONES_VALVULA:
            raise ValueError(f"Posición de la válvula no válida: {self.valvula!r}.")
        if min(self.prolongacion_extremo_m, self.prolongacion_valvula_m, self.ramal_valvula_m) < 0:
            raise ValueError("Los tramos de conexión no pueden ser negativos.")
        if not 0 <= self.porcentaje_valvula <= 100:
            raise ValueError("El porcentaje de la válvula debe estar entre 0 y 100.")

    @property
    def costados(self):
        return self.separacion_m / 2 if self.costados_m is None else self.costados_m

    def caudal(self, longitud_m):
        return self.caudal_lateral(longitud_m) if self.caudal_lateral else longitud_m


@dataclass
class Bloque:
    angulo_deg: float  # sentido de los laterales (del inicio al final), antihorario desde el eje x
    portalateral: List[Punto]  # polilínea del extremo 1 al extremo 2
    laterales: List[LateralTrazado]  # `distancia_m`: posición de la conexión a lo largo del portalateral
    valvula_m: float  # posición de la válvula a lo largo del portalateral
    hileras: int
    area_lote_m2: float
    separacion_m: float  # entre hileras
    caudal: float  # según `ParametrosBloque.caudal`
    # Cota del extremo 2 menos la del extremo 1 del portalateral (None sin cotas)
    desnivel_portalateral_m: Optional[float] = None
    pendiente_laterales: Optional[float] = None  # media desde el portalateral, m/m; positiva si suben
    avisos: List[str] = field(default_factory=list)
    laterales_por_hilera: int = 1
    # Tramos de conexión: (tipo, polilínea) y dónde queda la válvula si tiene ramal (ver `conectar_valvula`)
    conexiones: List[Tuple[str, List[Punto]]] = field(default_factory=list)
    valvula_final: Optional[Punto] = None

    @property
    def longitud_conexiones_m(self):
        return sum(_longitud(linea) for _, linea in self.conexiones)

    @property
    def longitud_portalateral_m(self):
        return _longitud(self.portalateral)

    @property
    def longitud_laterales_m(self):
        return sum(lat.longitud_m for lat in self.laterales)

    @property
    def lateral_mas_largo_m(self):
        return max((lat.longitud_m for lat in self.laterales), default=0.0)

    @property
    def area_regada_m2(self):
        """Largo de las hileras por su separación (los laterales de una hilera riegan la misma franja)."""
        return self.longitud_laterales_m * self.separacion_m / self.laterales_por_hilera

    @property
    def valvula(self) -> Punto:
        return punto_en(self.portalateral, self.valvula_m)

    @property
    def punto_de_la_valvula(self) -> Punto:
        """Donde se dibuja la válvula: al final de su ramal, o sobre el portalateral si no tiene."""
        return self.valvula_final if self.valvula_final is not None else self.valvula

    @property
    def azimut_laterales_grados(self):
        """Sentido de los laterales como azimut (desde el norte, horario), entre 0 y 360."""
        return (90.0 - self.angulo_deg) % 360.0


# ------------------------------------------------------------------ polilíneas


def _longitud(puntos):
    return sum(math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1))


def punto_en(puntos, distancia):
    """Punto de la polilínea a la distancia dada desde su inicio."""
    restante = max(0.0, distancia)
    for i in range(len(puntos) - 1):
        tramo = math.dist(puntos[i], puntos[i + 1])
        if restante <= tramo or i == len(puntos) - 2:
            t = 0.0 if tramo == 0 else min(1.0, restante / tramo)
            return (puntos[i][0] + t * (puntos[i + 1][0] - puntos[i][0]),
                    puntos[i][1] + t * (puntos[i + 1][1] - puntos[i][1]))
        restante -= tramo
    return puntos[-1]


def distancia_sobre_polilinea(puntos, p) -> Tuple[float, float]:
    """(distancia desde el inicio de la polilínea hasta su punto más cercano a p, separación entre ambos)."""
    mejor, recorrido = (0.0, math.inf), 0.0
    for a, b in zip(puntos, puntos[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        tramo2 = dx * dx + dy * dy
        t = 0.0 if tramo2 == 0 else min(1.0, max(0.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / tramo2))
        separacion = math.dist(p, (a[0] + t * dx, a[1] + t * dy))
        if separacion < mejor[1]:
            mejor = (recorrido + t * math.sqrt(tramo2), separacion)
        recorrido += math.sqrt(tramo2)
    return mejor


def direccion_en(puntos, distancia) -> Punto:
    """Vector unitario del sentido de la polilínea en el punto a la distancia dada (en un vértice, el del
    tramo que sigue; en el final, el del último tramo)."""
    restante = max(0.0, distancia)
    for a, b in zip(puntos, puntos[1:]):
        tramo = math.dist(a, b)
        if tramo > EPS and restante < tramo - EPS:
            return ((b[0] - a[0]) / tramo, (b[1] - a[1]) / tramo)
        restante -= tramo
    for a, b in zip(reversed(puntos[:-1]), reversed(puntos[1:])):
        tramo = math.dist(a, b)
        if tramo > EPS:
            return ((b[0] - a[0]) / tramo, (b[1] - a[1]) / tramo)
    raise ValueError("El portalateral no tiene largo.")


def conectar_valvula(portalateral, valvula_m, params: ParametrosBloque, avisos=None):
    """Tramos de conexión del portalateral y dónde queda la válvula. Devuelve (conexiones, punto de la válvula).

    Con la válvula en un extremo del portalateral, `prolongacion_valvula_m` lo alarga por ese lado y
    `prolongacion_extremo_m` por el otro. Con la válvula en medio, solo vale `prolongacion_extremo_m`, en
    los dos extremos. El ramal de la válvula sale perpendicular desde donde conecta la válvula, hacia la
    izquierda del sentido del portalateral (del extremo 1 al 2). Punto de la válvula: None si no hay ramal.
    """
    avisos = avisos if avisos is not None else []
    largo = _longitud(portalateral)
    inicio, final = portalateral[0], portalateral[-1]
    d_inicio = direccion_en(portalateral, 0.0)
    d_final = direccion_en(portalateral, largo)
    salida_inicio = (-d_inicio[0], -d_inicio[1])  # sentido hacia fuera en cada extremo
    salida_final = d_final

    def alargar(punto, salida, longitud):
        return (punto[0] + salida[0] * longitud, punto[1] + salida[1] * longitud)

    conexiones = []
    en_inicio, en_final = valvula_m <= EPS, valvula_m >= largo - EPS
    conexion = punto_en(portalateral, valvula_m)
    direccion = direccion_en(portalateral, valvula_m)
    if en_inicio or en_final:
        valvula_extremo, otro_extremo = (inicio, final) if en_inicio else (final, inicio)
        salida_valvula, salida_otro = (salida_inicio, salida_final) if en_inicio else (salida_final, salida_inicio)
        if params.prolongacion_valvula_m > 0:
            conexion = alargar(valvula_extremo, salida_valvula, params.prolongacion_valvula_m)
            conexiones.append((CONEXION_LADO_VALVULA, [valvula_extremo, conexion]))
            direccion = d_inicio if en_inicio else d_final
        if params.prolongacion_extremo_m > 0:
            conexiones.append((CONEXION_EXTREMO, [otro_extremo, alargar(otro_extremo, salida_otro,
                                                                       params.prolongacion_extremo_m)]))
    else:
        if params.prolongacion_valvula_m > 0:
            avisos.append("La válvula no está en un extremo del portalateral: no se agrega la prolongación del "
                          "lado de la válvula.")
        if params.prolongacion_extremo_m > 0:
            conexiones.append((CONEXION_EXTREMO, [inicio, alargar(inicio, salida_inicio, params.prolongacion_extremo_m)]))
            conexiones.append((CONEXION_EXTREMO, [final, alargar(final, salida_final, params.prolongacion_extremo_m)]))
    valvula = None
    if params.ramal_valvula_m > 0:
        valvula = (conexion[0] - direccion[1] * params.ramal_valvula_m,
                   conexion[1] + direccion[0] * params.ramal_valvula_m)
        conexiones.append((CONEXION_RAMAL_VALVULA, [conexion, valvula]))
    return conexiones, valvula


def azimut_entre(desde: Punto, hacia: Punto) -> float:
    """Azimut (grados desde el norte, horario, entre 0 y 360) de la recta que va de un punto al otro."""
    if math.dist(desde, hacia) < EPS:
        raise ValueError("Los dos puntos de la dirección coinciden.")
    return math.degrees(math.atan2(hacia[0] - desde[0], hacia[1] - desde[1])) % 360.0


def _simplificar(puntos, tolerancia):
    """Douglas-Peucker: conserva los extremos y los vértices que se apartan más que la tolerancia."""
    if len(puntos) <= 2:
        return list(puntos)
    (x1, y1), (x2, y2) = puntos[0], puntos[-1]
    largo = math.hypot(x2 - x1, y2 - y1)
    peor, indice = -1.0, 0
    for i in range(1, len(puntos) - 1):
        x, y = puntos[i]
        if largo == 0:
            d = math.hypot(x - x1, y - y1)
        else:
            d = abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / largo
        if d > peor:
            peor, indice = d, i
    if peor <= tolerancia:
        return [puntos[0], puntos[-1]]
    return _simplificar(puntos[:indice + 1], tolerancia)[:-1] + _simplificar(puntos[indice:], tolerancia)


def _x_en(polilinea, y):
    """x de la polilínea (monótona en y) a la altura y; fuera de su rango, la del extremo más cercano."""
    if y <= polilinea[0][1]:
        return polilinea[0][0]
    for (xa, ya), (xb, yb) in zip(polilinea, polilinea[1:]):
        if y <= yb:
            return xa if yb == ya else xa + (y - ya) * (xb - xa) / (yb - ya)
    return polilinea[-1][0]


def _distancia_sobre(polilinea, y):
    """Distancia desde el inicio de la polilínea (monótona en y) hasta su punto a la altura y."""
    recorrido = 0.0
    for (xa, ya), (xb, yb) in zip(polilinea, polilinea[1:]):
        if y <= yb or (xb, yb) == polilinea[-1]:
            if yb == ya:
                return recorrido
            t = min(1.0, max(0.0, (y - ya) / (yb - ya)))
            return recorrido + t * math.hypot(xb - xa, yb - ya)
        recorrido += math.hypot(xb - xa, yb - ya)
    return recorrido


# ------------------------------------------------------------------ disposición


class _Plano:
    """El lote girado para que los laterales vayan hacia +x."""

    def __init__(self, anillos, angulo_deg):
        fi = math.radians(angulo_deg)
        self.c, self.s = math.cos(fi), math.sin(fi)
        self.anillos = [[self.al_plano(p) for p in a] for a in anillos]
        puntos = [p for a in self.anillos for p in a]
        self.x_min, self.x_max = min(p[0] for p in puntos), max(p[0] for p in puntos)
        self.y_min, self.y_max = min(p[1] for p in puntos), max(p[1] for p in puntos)

    def al_plano(self, p):
        return self.c * p[0] + self.s * p[1], -self.s * p[0] + self.c * p[1]

    def al_terreno(self, p):
        return self.c * p[0] - self.s * p[1], self.s * p[0] + self.c * p[1]

    def tramos(self, y, cabecera):
        return [(a + cabecera, b - cabecera) for a, b in _intervalos(self.anillos, y) if b - a > 2 * cabecera]


def ejes_de_hileras(y_min, y_max, separacion, costados):
    """Ordenadas de los ejes de las hileras: la primera a `costados` del borde y luego cada `separacion`."""
    ejes, y = [], y_min + costados
    while y <= y_max - costados + 1e-6:
        ejes.append(y)
        y += separacion
    return ejes


def _desplazamientos(params):
    n = params.laterales_por_hilera
    return [(j - (n - 1) / 2) * params.separacion_en_hilera_m for j in range(n)]


def _tramo_principal(tramos):
    return max(tramos, key=lambda t: t[1] - t[0]) if tramos else None


def _cota_media(plano, puntos, cota):
    valores = [cota(*plano.al_terreno(p)) for p in puntos]
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


def _anclas(plano, ejes, params, cota):
    """Puntos (x, y) del plano por donde pasa el portalateral, uno por hilera, y avisos."""
    avisos = []
    principales = [(y, _tramo_principal(plano.tramos(y, params.cabecera_m))) for y in ejes]
    principales = [(y, t) for y, t in principales if t is not None]
    if not principales:
        return [], avisos
    posicion = params.portalateral
    if posicion in (PORTA_ALTO, PORTA_BAJO):
        z_inicio = _cota_media(plano, [(t[0], y) for y, t in principales], cota) if cota else None
        z_final = _cota_media(plano, [(t[1], y) for y, t in principales], cota) if cota else None
        if z_inicio is None or z_final is None:
            avisos.append("Sin cotas del DEM en el lote: el portalateral va al inicio de los laterales.")
            posicion = PORTA_INICIO
        else:
            inicio_es_alto = z_inicio >= z_final
            posicion = PORTA_INICIO if inicio_es_alto == (posicion == PORTA_ALTO) else PORTA_FINAL
    anclas = []
    for y, (a, b) in principales:
        if posicion == PORTA_INICIO:
            x = a
        elif posicion == PORTA_FINAL:
            x = b
        elif posicion == PORTA_CENTRO:
            x = (a + b) / 2
        else:
            x = min(b, a + params.distancia_portalateral_m)
        anclas.append((x, y))
    if posicion == PORTA_DISTANCIA and any(a + params.distancia_portalateral_m > b for _, (a, b) in principales):
        avisos.append("En algunas hileras la distancia del portalateral es mayor que el largo del lote: "
                      "allí queda en el final de los laterales.")
    return anclas, avisos


def angulo_para_portalateral(puntos: Sequence[Punto]) -> float:
    """Sentido de los laterales (grados, antihorario desde +x) perpendicular a la cuerda de un portalateral
    dibujado: del primer al último punto, el portalateral avanza hacia +y del plano."""
    p, q = puntos[0], puntos[-1]
    if math.dist(p, q) < EPS:
        raise ValueError("El primer y el último punto del portalateral coinciden.")
    return (math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) - 90.0) % 360.0


def _portalateral_manual(plano, params):
    """La línea dibujada, en el plano y orientada hacia +y. Devuelve (puntos, avisos)."""
    puntos = []
    for p in params.puntos_portalateral:
        q = plano.al_plano(p)
        if not puntos or math.dist(q, puntos[-1]) > EPS:
            puntos.append(q)
    if len(puntos) < 2:
        raise ValueError("Dibuje el portalateral en el mapa: hacen falta al menos dos puntos distintos.")
    if puntos[0][1] > puntos[-1][1]:
        puntos.reverse()
    if any(b[1] < a[1] - EPS for a, b in zip(puntos, puntos[1:])):
        raise ValueError("El portalateral dibujado vuelve atrás respecto de la dirección perpendicular a los "
                         "laterales: dibújelo de un extremo al otro sin retroceder, o cambie la dirección de los "
                         "laterales.")
    if puntos[-1][1] - puntos[0][1] < EPS:
        raise ValueError("El portalateral dibujado es paralelo a los laterales: cámbielo o cambie su dirección.")
    return puntos, []


def _disponer(plano, params, cota=None):
    """Portalateral y laterales en el plano. Devuelve (portalateral, laterales, hileras, avisos).

    Cada lateral es (y, x_portalateral, x_extremo, índice de hilera).
    """
    ejes = ejes_de_hileras(plano.y_min, plano.y_max, params.separacion_m, params.costados)
    tolerancia = min(TOLERANCIA_PORTALATERAL_M, params.separacion_m / 2)
    manual = params.portalateral == PORTA_MANUAL
    if manual:
        portalateral, avisos = _portalateral_manual(plano, params)
        # Solo llevan laterales las hileras que quedan a lo largo de la línea (con media separación de holgura)
        holgura = params.separacion_m / 2
        ejes = [y for y in ejes if portalateral[0][1] - holgura <= y <= portalateral[-1][1] + holgura]
        if not ejes:
            avisos.append("El portalateral dibujado no pasa por ninguna hilera de laterales.")
            return [], [], 0, avisos
    else:
        anclas, avisos = _anclas(plano, ejes, params, cota)
        if len(anclas) == 0:
            return [], [], 0, avisos
        portalateral = _simplificar(anclas, tolerancia)
    desplazamientos = _desplazamientos(params)
    laterales, hileras = [], set()
    for k, y_eje in enumerate(ejes):
        for d in desplazamientos:
            y = y_eje + d
            xp = _x_en(portalateral, y)
            tramos = plano.tramos(y, params.cabecera_m)
            tramo = next((t for t in tramos if t[0] - tolerancia <= xp <= t[1] + tolerancia), None)
            if tramo is None:
                continue
            a, b = tramo
            for extremo in (a, b):
                if abs(extremo - xp) >= max(params.longitud_min_m, EPS):
                    laterales.append((y, xp, extremo, k))
                    hileras.add(k)
    if manual and laterales and len(hileras) < len(ejes):
        avisos.append(f"En {len(ejes) - len(hileras)} hileras el portalateral dibujado queda fuera del lote: "
                      "allí no hay laterales.")
    if len(desplazamientos) > 1 and laterales:
        # El portalateral llega hasta los laterales de las hileras de los extremos.
        y_bajo = min(lat[0] for lat in laterales)
        y_alto = max(lat[0] for lat in laterales)
        if y_bajo < portalateral[0][1]:
            portalateral.insert(0, (portalateral[0][0], y_bajo))
        if y_alto > portalateral[-1][1]:
            portalateral.append((portalateral[-1][0], y_alto))
    return portalateral, laterales, len(hileras), avisos


def _puntuar(plano, params, portalateral, laterales, pendiente, alcance):
    """Metros equivalentes de tubería (menor es mejor), como en el trazado automático."""
    largo = sum(abs(x2 - x1) for _, x1, x2, _ in laterales)
    alcanzable = 0.0
    for y in ejes_de_hileras(plano.y_min, plano.y_max, params.separacion_m, params.costados):
        alcanzable += sum(b - a for a, b in plano.tramos(y, params.cabecera_m)) * params.laterales_por_hilera
    sin_regar = max(0.0, alcanzable - largo)
    exceso = sum(max(0.0, abs(x2 - x1) - alcance) for _, x1, x2, _ in laterales) if alcance else 0.0
    return largo + 2.0 * _longitud(portalateral) + 4.0 * sin_regar + 5.0 * pendiente * largo + 20.0 * exceso


def direcciones_candidatas(anillos: Sequence[Anillo]) -> List[float]:
    """Direcciones (grados, de 0 a 180) que se prueban en modo automático: las hileras van paralelas o
    perpendiculares a uno de los lados largos del lote, o a los ejes de su rectángulo envolvente."""
    candidatas = orientaciones_candidatas(anillos, paso_deg=180.0)  # sin la rejilla, salvo el 0°
    lados = [math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
             for anillo in anillos for a, b in zip(anillo, list(anillo[1:]) + [anillo[0]]) if a != b]
    sin_rejilla = [c for c in candidatas if c != 0.0 or any(_distancia_angular(c, l) < 1.0 or
                                                           _distancia_angular(c + 90.0, l) < 1.0 for l in lados)]
    return sin_rejilla or candidatas


def _distancia_angular(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def trazar_bloque(anillos: Sequence[Anillo], params: ParametrosBloque,
                  cota: Optional[Callable[[float, float], Optional[float]]] = None,
                  fuente: Optional[Punto] = None,
                  pendiente: Optional[Callable[[float], float]] = None,
                  alcance_m: Optional[float] = None,
                  peso_subida: float = 5.0) -> Bloque:
    """Laterales, portalateral y válvula de un lote.

    `cota(x, y)` da la cota del terreno (None sin dato): con ella se ubican el borde alto o bajo y
    la válvula automática. `pendiente(ángulo)` da la pendiente (m/m, valor absoluto) en una dirección
    y `alcance_m` la longitud máxima de un lateral: los dos solo sirven para elegir la dirección
    automática. `fuente` es el punto de agua más cercano (para la válvula automática).
    """
    _verificar(anillos)
    area = area_anillos(anillos)
    avisos = []
    angulo_fijo = params.angulo_deg
    if angulo_fijo is None and params.portalateral == PORTA_MANUAL:
        angulo_fijo = angulo_para_portalateral(params.puntos_portalateral)  # laterales perpendiculares a la línea
    if angulo_fijo is not None:
        angulo = angulo_fijo % 360.0
        plano = _Plano(anillos, angulo)
        portalateral, laterales, hileras, avisos_disp = _disponer(plano, params, cota)
    else:
        mejor = None
        for candidato in direcciones_candidatas(anillos):
            plano_c = _Plano(anillos, candidato)
            disp = _disponer(plano_c, params, cota)
            if not disp[1]:
                continue
            puntos = _puntuar(plano_c, params, disp[0], disp[1], pendiente(candidato) if pendiente else 0.0,
                              alcance_m)
            if mejor is None or puntos < mejor[0] - EPS:
                mejor = (puntos, candidato, plano_c, disp)
        if mejor is None:
            raise ValueError("No caben laterales en el lote con estos parámetros (revise la cabecera, "
                             "los costados y la separación).")
        _, angulo, plano, (portalateral, laterales, hileras, avisos_disp) = mejor
    avisos += avisos_disp
    if not laterales:
        raise ValueError("No caben laterales en el lote con estos parámetros (revise la dirección, la "
                         "cabecera, los costados y la separación).")

    # Extremos del portalateral y sus cotas
    extremo_1, extremo_2 = plano.al_terreno(portalateral[0]), plano.al_terreno(portalateral[-1])
    z1 = z2 = None
    if cota is not None:
        z1, z2 = cota(*extremo_1), cota(*extremo_2)
        if z1 is None or z2 is None:
            z1 = z2 = None
    largo_porta = _longitud(portalateral)
    portalateral_terreno = [plano.al_terreno(p) for p in portalateral]
    if params.valvula == VALV_PUNTO and params.punto_valvula is not None:
        valvula_m, separacion = distancia_sobre_polilinea(portalateral_terreno, params.punto_valvula)
        if separacion > max(5.0, 2 * params.separacion_m):
            avisos.append(f"El punto marcado para la válvula está a {separacion:.1f} m del portalateral: la "
                          "válvula va en el punto del portalateral más cercano.")
    else:
        if params.valvula == VALV_PUNTO:
            avisos.append("No se ha marcado la válvula en el mapa: va en la posición automática.")
            params = replace(params, valvula=VALV_AUTO)
        valvula_m = _posicion_valvula(params, largo_porta, extremo_1, extremo_2, z1, z2, fuente, peso_subida,
                                      avisos)

    resultado = []
    for y, xp, extremo, k in sorted(laterales, key=lambda lat: (lat[0], lat[2])):
        distancia = _distancia_sobre(portalateral, y)
        # Con el portalateral hacia +y, lo que queda hacia +x está a su derecha.
        lado = "B" if extremo > xp else "A"
        resultado.append(LateralTrazado(plano.al_terreno((xp, y)), plano.al_terreno((extremo, y)), lado, k,
                                        distancia, abs(extremo - xp)))
    caudal = sum(params.caudal(lat.longitud_m) for lat in resultado)

    pendiente_lat = None
    if cota is not None:
        subidas = []
        for lat in resultado:
            za, zb = cota(*lat.inicio), cota(*lat.fin)
            if za is not None and zb is not None and lat.longitud_m > 0:
                subidas.append((zb - za) / lat.longitud_m)
        if subidas:
            pendiente_lat = sum(subidas) / len(subidas)
    conexiones, valvula_final = conectar_valvula(portalateral_terreno, valvula_m, params, avisos)
    return Bloque(angulo, portalateral_terreno, resultado, valvula_m, hileras, area, params.separacion_m, caudal,
                  None if z1 is None else z2 - z1, pendiente_lat, avisos,
                  params.laterales_por_hilera, conexiones, valvula_final)


def _posicion_valvula(params, largo, extremo_1, extremo_2, z1, z2, fuente, peso_subida, avisos):
    modo = params.valvula
    if modo in (VALV_ALTO, VALV_BAJO) and z1 is None:
        avisos.append("Sin cotas del DEM en los extremos del portalateral: la válvula va en su extremo 1.")
        return 0.0
    if modo == VALV_ALTO:
        return 0.0 if z1 >= z2 else largo
    if modo == VALV_BAJO:
        return 0.0 if z1 < z2 else largo
    if modo == VALV_INICIO:
        return 0.0
    if modo == VALV_FINAL:
        return largo
    if modo == VALV_CENTRO:
        return largo / 2
    if modo == VALV_PORCENTAJE:
        fraccion = params.porcentaje_valvula / 100
        desde_2 = z1 is not None and z2 > z1  # se mide desde el extremo más alto
        return largo * (1 - fraccion) if desde_2 else largo * fraccion
    # Automática: el extremo más barato según la distancia a la fuente y lo que sube el agua.
    costo_1 = costo_2 = 0.0
    if fuente is not None:
        costo_1, costo_2 = math.dist(fuente, extremo_1), math.dist(fuente, extremo_2)
    if z1 is not None:
        costo_1 += peso_subida * max(0.0, z2 - z1)
        costo_2 += peso_subida * max(0.0, z1 - z2)
    return 0.0 if costo_1 <= costo_2 else largo


def plano_del_bloque(anillos: Sequence[Anillo], angulo_deg: float) -> Tuple[Callable, Callable]:
    """Funciones (al_plano, al_terreno) para la dirección de laterales dada."""
    plano = _Plano(anillos, angulo_deg)
    return plano.al_plano, plano.al_terreno
