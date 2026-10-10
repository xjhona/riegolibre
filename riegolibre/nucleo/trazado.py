"""Trazado automático de subunidades sobre un terreno de forma cualquiera.

Dado el contorno del terreno (un polígono, con huecos o varias partes) se decide
sin dibujar nada a mano:

- la dirección de los laterales (se prueban varias y se elige la mejor),
- cuántos portalaterales hacen falta y dónde van,
- qué laterales cuelgan de cada uno, recortados por el borde y sin cruzar huecos,
- cómo se parte el terreno en subunidades si el caudal por válvula está limitado.

El motor es Python puro: trabaja con anillos de puntos (x, y) en metros. Dentro de
cada orientación gira el terreno hasta que los laterales quedan horizontales; los
portalaterales son entonces rectas verticales y todo se resuelve recorriendo líneas.

Criterio de elección. Cada trazado recibe una puntuación en «metros equivalentes de
tubería» (menor es mejor): metros de lateral, metros de portalateral ponderados, un
costo fijo por válvula, una penalización por el terreno que queda sin regar, otra por
la pendiente a lo largo de los laterales y otra por subunidades de caudales muy
distintos. Los pesos están en `PesosTrazado` y se pueden cambiar.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

Punto = Tuple[float, float]
Anillo = Sequence[Punto]

LADOS_AMBOS, LADOS_UNO = "ambos", "uno"
EPS = 1e-9
PASOS_BANDA = 13  # posiciones probadas para cada portalateral
MAX_RONDAS_RESIDUO = 80


@dataclass(frozen=True)
class ParametrosTrazado:
    separacion_m: float  # entre laterales
    margen_m: float = 0.5  # entre el extremo de un lateral y el borde del terreno
    longitud_min_m: float = 3.0  # un lateral más corto no se traza
    lados: str = LADOS_AMBOS  # «ambos»: laterales a los dos lados del portalateral; «uno»: solo a un lado
    caudal_max_lh: Optional[float] = None  # máximo por subunidad; None = sin límite
    laterales_min: int = 3  # una subunidad con menos laterales no vale una válvula
    # Caudal de un lateral según su longitud. Sin él, el «caudal» es la longitud en metros.
    caudal_lateral: Optional[Callable[[float], float]] = field(default=None, compare=False)

    def __post_init__(self):
        if self.separacion_m <= 0:
            raise ValueError("La separación entre laterales debe ser mayor que cero.")
        if self.margen_m < 0 or self.longitud_min_m < 0:
            raise ValueError("El margen y la longitud mínima no pueden ser negativos.")
        if self.lados not in (LADOS_AMBOS, LADOS_UNO):
            raise ValueError(f"Lados no válidos: {self.lados!r}.")
        if self.caudal_max_lh is not None and self.caudal_max_lh <= 0:
            raise ValueError("El caudal máximo por subunidad debe ser mayor que cero.")
        if self.laterales_min < 1:
            raise ValueError("Cada subunidad necesita al menos un lateral.")

    def caudal(self, longitud_m):
        return self.caudal_lateral(longitud_m) if self.caudal_lateral else longitud_m


@dataclass(frozen=True)
class Orientacion:
    angulo_deg: float  # dirección de los laterales, antihoraria desde el eje x
    longitud_max_m: float  # alcance máximo de un lateral desde su portalateral
    pendiente: float = 0.0  # pendiente media (m/m, en valor absoluto) a lo largo de los laterales

    def __post_init__(self):
        if self.longitud_max_m <= 0:
            raise ValueError("La longitud máxima de los laterales debe ser mayor que cero.")


@dataclass(frozen=True)
class PesosTrazado:
    """Metros equivalentes de tubería de lateral que vale cada concepto."""
    portalateral: float = 2.0  # por metro de portalateral (diámetro mayor)
    valvula: float = 60.0  # por subunidad: válvula, conexión y tubería de la red principal
    sin_cubrir: float = 4.0  # por metro de lateral que habría regado el terreno que queda sin regar
    pendiente: float = 5.0  # por metro de lateral y por m/m de pendiente a lo largo de los laterales
    desbalance: float = 30.0  # por unidad de coeficiente de variación de los caudales de las subunidades


@dataclass
class LateralTrazado:
    inicio: Punto  # en el portalateral
    fin: Punto
    lado: str  # «A» a la izquierda del portalateral (según su sentido), «B» a la derecha
    conexion: int  # posición del lateral a lo largo del portalateral, desde 0
    distancia_m: float  # distancia desde el inicio del portalateral
    longitud_m: float


@dataclass
class SubunidadTrazada:
    numero: int
    portalateral: Tuple[Punto, Punto]  # del inicio (válvula) al final
    laterales: List[LateralTrazado]
    caudal: float  # según `ParametrosTrazado.caudal`

    @property
    def longitud_portalateral_m(self):
        (x1, y1), (x2, y2) = self.portalateral
        return math.hypot(x2 - x1, y2 - y1)

    @property
    def longitud_laterales_m(self):
        return sum(lat.longitud_m for lat in self.laterales)


@dataclass
class Trazado:
    orientacion: Orientacion
    separacion_m: float
    subunidades: List[SubunidadTrazada]
    area_terreno_m2: float
    puntuacion: float = 0.0
    # Lo que los laterales pueden regar: el terreno menos la franja del margen en sus extremos.
    area_alcanzable_m2: float = 0.0

    @property
    def numero_subunidades(self):
        return len(self.subunidades)

    @property
    def longitud_laterales_m(self):
        return sum(s.longitud_laterales_m for s in self.subunidades)

    @property
    def longitud_portalaterales_m(self):
        return sum(s.longitud_portalateral_m for s in self.subunidades)

    @property
    def area_regada_m2(self):
        return self.longitud_laterales_m * self.separacion_m

    @property
    def fraccion_sin_cubrir(self):
        if self.area_terreno_m2 <= 0:
            return 0.0
        return max(0.0, 1.0 - self.area_regada_m2 / self.area_terreno_m2)

    @property
    def caudales(self):
        return [s.caudal for s in self.subunidades]

    @property
    def azimut_laterales_grados(self):
        """Dirección de los laterales como azimut (desde el norte, horario), entre 0 y 180."""
        return (90.0 - self.orientacion.angulo_deg) % 180.0


# ------------------------------------------------------------------ geometría


def area_anillos(anillos: Sequence[Anillo]) -> float:
    """Área de un polígono con huecos y partes (regla par-impar entre anillos)."""
    total = 0.0
    for i, anillo in enumerate(anillos):
        if len(anillo) < 3:
            continue
        area = abs(_area_firmada(anillo))
        profundidad = sum(1 for j, otro in enumerate(anillos)
                          if j != i and len(otro) >= 3 and _punto_en_anillo(anillo[0], otro))
        total += area if profundidad % 2 == 0 else -area
    return max(total, 0.0)


def _area_firmada(anillo):
    suma = 0.0
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        suma += x1 * y2 - x2 * y1
    return suma / 2


def _punto_en_anillo(punto, anillo):
    x, y = punto
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        if (y1 <= y < y2 or y2 <= y < y1) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


def _intervalos(anillos, y):
    """Tramos de la recta horizontal `y` que quedan dentro del polígono (regla par-impar)."""
    xs = []
    for anillo in anillos:
        n = len(anillo)
        for i in range(n):
            x1, y1 = anillo[i]
            x2, y2 = anillo[(i + 1) % n]
            if y1 <= y < y2 or y2 <= y < y1:
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def _casco_convexo(puntos):
    puntos = sorted(set(puntos))
    if len(puntos) <= 2:
        return puntos

    def semicasco(secuencia):
        casco = []
        for p in secuencia:
            while len(casco) >= 2 and (
                    (casco[-1][0] - casco[-2][0]) * (p[1] - casco[-2][1])
                    - (casco[-1][1] - casco[-2][1]) * (p[0] - casco[-2][0])) <= 0:
                casco.pop()
            casco.append(p)
        return casco

    inferior, superior = semicasco(puntos), semicasco(reversed(puntos))
    return inferior[:-1] + superior[:-1]


def orientaciones_candidatas(anillos: Sequence[Anillo], paso_deg=15.0, maximo_bordes=4) -> List[float]:
    """Ángulos (grados, de 0 a 180) que vale la pena probar para los laterales.

    Una rejilla regular, los lados más largos del contorno y los ejes del rectángulo
    de menor área que lo envuelve (y sus perpendiculares).
    """
    angulos = [i * paso_deg for i in range(int(180 / paso_deg))]

    lados = []
    for anillo in anillos:
        n = len(anillo)
        for i in range(n):
            (x1, y1), (x2, y2) = anillo[i], anillo[(i + 1) % n]
            largo = math.hypot(x2 - x1, y2 - y1)
            if largo > 0:
                lados.append((largo, math.degrees(math.atan2(y2 - y1, x2 - x1))))
    lados.sort(reverse=True)
    for _, angulo in lados[:maximo_bordes]:
        angulos += [angulo, angulo + 90.0]

    casco = _casco_convexo([p for a in anillos for p in a])
    mejor = None
    for i in range(len(casco)):
        (x1, y1), (x2, y2) = casco[i], casco[(i + 1) % len(casco)]
        if (x1, y1) == (x2, y2):
            continue
        a = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(a), math.sin(a)
        us = [c * x + s * y for x, y in casco]
        vs = [-s * x + c * y for x, y in casco]
        area = (max(us) - min(us)) * (max(vs) - min(vs))
        if mejor is None or area < mejor[0]:
            mejor = (area, math.degrees(a))
    if mejor is not None:
        angulos += [mejor[1], mejor[1] + 90.0]

    resultado = []
    for a in sorted(x % 180.0 for x in angulos):
        if not resultado or a - resultado[-1] > 1.0:
            resultado.append(a)
    if len(resultado) > 1 and resultado[0] + 180.0 - resultado[-1] <= 1.0:
        resultado.pop()
    return resultado


# ------------------------------------------------------------ una orientación


class _Disposicion:
    """Disposición del terreno para una orientación: laterales horizontales, portalaterales verticales."""

    def __init__(self, anillos, orientacion, params, pesos, separacion):
        self.orientacion, self.params, self.pesos = orientacion, params, pesos
        self.separacion = separacion
        fi = math.radians(orientacion.angulo_deg)
        self.c, self.s = math.cos(fi), math.sin(fi)
        self.anillos = [[self.al_plano(p) for p in a] for a in anillos]
        puntos = [p for a in self.anillos for p in a]
        self.x_min, self.x_max = min(p[0] for p in puntos), max(p[0] for p in puntos)
        y_min, y_max = min(p[1] for p in puntos), max(p[1] for p in puntos)

        alto = y_max - y_min
        self.n = max(1, int(alto / separacion + 1e-9))
        arranque = y_min + (alto - (self.n - 1) * separacion) / 2
        self.ys = [arranque + k * separacion for k in range(self.n)]
        margen = params.margen_m
        self.libres = []
        for y in self.ys:
            tramos = [(a + margen, b - margen) for a, b in _intervalos(self.anillos, y) if b - a > 2 * margen]
            self.libres.append(tramos)
        self.area_alcanzable = separacion * sum(b - a for tramos in self.libres for a, b in tramos)
        self.alcance = orientacion.longitud_max_m
        self.piezas = []  # (xp, [(k, izq, der, caudal), ...])

    def al_plano(self, p):
        return self.c * p[0] + self.s * p[1], -self.s * p[0] + self.c * p[1]

    def al_terreno(self, p):
        return self.c * p[0] - self.s * p[1], self.s * p[0] + self.c * p[1]

    # --- evaluación de un portalateral candidato

    def _lateral_en(self, k, xp, lo, hi, lados):
        for fa, fb in self.libres[k]:
            if fa + EPS < xp < fb - EPS:
                izq = xp - max(fa, xp - self.alcance, lo)
                der = min(fb, xp + self.alcance, hi) - xp
                minimo = self.params.longitud_min_m
                izq = izq if "I" in lados and izq >= minimo else 0.0
                der = der if "D" in lados and der >= minimo else 0.0
                if izq == 0.0 and der == 0.0:
                    return None
                caudal = (self.params.caudal(izq) if izq else 0.0) + (self.params.caudal(der) if der else 0.0)
                return izq, der, caudal
        return None

    def _corridas(self, xp, lo, hi, lados):
        corridas, actual = [], []
        for k in range(self.n):
            linea = self._lateral_en(k, xp, lo, hi, lados)
            if linea is None:
                if actual:
                    corridas.append(actual)
                    actual = []
            else:
                actual.append((k,) + linea)
        if actual:
            corridas.append(actual)
        return corridas

    def _trocear(self, corrida):
        """Parte una corrida de laterales en subunidades de caudal parecido y menor que el máximo."""
        maximo = self.params.caudal_max_lh
        total = sum(t[3] for t in corrida)
        trozos = [corrida]
        if maximo and total > maximo * (1 + EPS):
            partes = math.ceil(total / maximo - EPS)
            objetivo = total / partes
            trozos, actual, acumulado = [], [], 0.0
            for linea in corrida:
                caudal = linea[3]
                if actual and (acumulado + caudal > maximo * (1 + EPS)
                               or (len(trozos) < partes - 1 and acumulado + caudal / 2 > objetivo)):
                    trozos.append(actual)
                    actual, acumulado = [], 0.0
                actual.append(linea)
                acumulado += caudal
            if actual:
                trozos.append(actual)
        minimo = self.params.laterales_min
        if len(trozos) > 1 and len(trozos[-1]) < minimo and (
                not maximo or sum(t[3] for t in trozos[-1] + trozos[-2]) <= maximo * (1 + EPS)):
            trozos[-2] = trozos[-2] + trozos.pop()
        return [t for t in trozos if len(t) >= minimo]

    def _ganancia(self, trozo):
        regado = sum(t[1] + t[2] for t in trozo)
        portalateral = len(trozo) * self.separacion
        p = self.pesos
        # El último término desempata a favor del portalateral centrado (laterales más cortos).
        return (regado * (p.sin_cubrir - 1.0) - p.portalateral * portalateral - p.valvula
                - 0.05 * sum(max(t[1], t[2]) for t in trozo))

    def _candidato(self, xp, lo, hi, lados):
        trozos = []
        for corrida in self._corridas(xp, lo, hi, lados):
            trozos += [t for t in self._trocear(corrida) if self._ganancia(t) > 0]
        return sum(self._ganancia(t) for t in trozos), trozos

    def _mejor_en(self, posiciones, lo, hi):
        mejor = (0.0, None, None, None)
        lados_a_probar = ["ID"] if self.params.lados == LADOS_AMBOS else ["I", "D"]
        for xp in posiciones:
            for lados in lados_a_probar:
                ganancia, trozos = self._candidato(xp, lo, hi, lados)
                if trozos and ganancia > mejor[0] + EPS:
                    mejor = (ganancia, xp, lados, trozos)
        return mejor

    def _aplicar(self, xp, trozos):
        for trozo in trozos:
            self.piezas.append((xp, trozo))
            for k, izq, der, _ in trozo:
                self._restar(k, xp - izq, xp + der)

    def _restar(self, k, a, b):
        nuevos = []
        for fa, fb in self.libres[k]:
            if b <= fa or a >= fb:
                nuevos.append((fa, fb))
                continue
            if a - fa > EPS:
                nuevos.append((fa, a))
            if fb - b > EPS:
                nuevos.append((b, fb))
        self.libres[k] = nuevos

    # --- construcción

    def _posiciones_en_bordes(self, lo, hi, maximo=30):
        """Posiciones pegadas a los bordes de lo que queda libre: portalaterales a lo largo del borde."""
        valores = sorted(x for tramos in self.libres for fa, fb in tramos
                         for x in (fa + 1e-6, fb - 1e-6) if lo < x < hi)
        elegidas = []
        for x in valores:
            if not elegidas or x - elegidas[-1] > self.separacion / 4:
                elegidas.append(x)
        if len(elegidas) > maximo:
            elegidas = [elegidas[int(i * (len(elegidas) - 1) / (maximo - 1))] for i in range(maximo)]
        return elegidas

    def construir(self):
        ancho = self.x_max - self.x_min
        paso_ancho = 2 * self.alcance if self.params.lados == LADOS_AMBOS else self.alcance
        bandas = max(1, math.ceil(ancho / paso_ancho - EPS))
        for j in range(bandas):
            lo = self.x_min + ancho * j / bandas
            hi = self.x_min + ancho * (j + 1) / bandas
            posiciones = [lo + (hi - lo) * (i + 0.5) / PASOS_BANDA for i in range(PASOS_BANDA)]
            posiciones += self._posiciones_en_bordes(lo, hi)
            ganancia, xp, _, trozos = self._mejor_en(posiciones, lo, hi)
            if trozos:
                self._aplicar(xp, trozos)

        # Lo que no alcanzó una banda (partes del contorno cóncavo, huecos, sobrantes).
        paso = max(self.separacion, ancho / 60)
        posiciones = [self.x_min + paso * (i + 0.5) for i in range(int(ancho / paso) + 1)]
        for _ in range(MAX_RONDAS_RESIDUO):
            ganancia, xp, _, trozos = self._mejor_en(posiciones, -math.inf, math.inf)
            if not trozos:
                break
            self._aplicar(xp, trozos)

    def subunidades(self, fuente=None):
        piezas = sorted(self.piezas, key=lambda p: (p[0], p[1][0][0]))
        resultado = []
        for numero, (xp, trozo) in enumerate(piezas, 1):
            media = self.separacion / 2
            y_bajo, y_alto = self.ys[trozo[0][0]] - media, self.ys[trozo[-1][0]] + media
            desde_abajo = True
            if fuente is not None:
                f = fuente
                d_bajo = math.dist(f, self.al_terreno((xp, y_bajo)))
                d_alto = math.dist(f, self.al_terreno((xp, y_alto)))
                desde_abajo = d_bajo <= d_alto
            y_inicio, y_fin = (y_bajo, y_alto) if desde_abajo else (y_alto, y_bajo)
            ordenadas = trozo if desde_abajo else list(reversed(trozo))
            laterales = []
            for conexion, (k, izq, der, _) in enumerate(ordenadas):
                y = self.ys[k]
                distancia = abs(y - y_inicio)
                for lado_plano, largo, signo in (("I", izq, -1), ("D", der, 1)):
                    if not largo:
                        continue
                    # Con el portalateral hacia +y, la derecha del plano (+x) queda a su derecha.
                    a_la_derecha = (signo > 0) == desde_abajo
                    laterales.append(LateralTrazado(
                        self.al_terreno((xp, y)), self.al_terreno((xp + signo * largo, y)),
                        "B" if a_la_derecha else "A", conexion, distancia, largo))
            resultado.append(SubunidadTrazada(
                numero, (self.al_terreno((xp, y_inicio)), self.al_terreno((xp, y_fin))), laterales,
                sum(t[3] for t in trozo)))
        return resultado


# ------------------------------------------------------------------ puntuación


def _puntuar(trazado, pesos):
    p = pesos
    lat, por = trazado.longitud_laterales_m, trazado.longitud_portalaterales_m
    sin_cubrir_m = max(0.0, trazado.area_alcanzable_m2 - trazado.area_regada_m2) / trazado.separacion_m
    caudales = trazado.caudales
    desbalance = 0.0
    if len(caudales) > 1:
        media = sum(caudales) / len(caudales)
        if media > 0:
            desbalance = math.sqrt(sum((q - media) ** 2 for q in caudales) / len(caudales)) / media
    return (lat + p.portalateral * por + p.valvula * len(caudales) + p.sin_cubrir * sin_cubrir_m
            + p.pendiente * trazado.orientacion.pendiente * lat + p.desbalance * desbalance)


def _trazar(anillos, params, orientacion, pesos, fuente, separacion, area):
    disposicion = _Disposicion(anillos, orientacion, params, pesos, separacion)
    disposicion.construir()
    trazado = Trazado(orientacion, separacion, disposicion.subunidades(fuente), area,
                      area_alcanzable_m2=disposicion.area_alcanzable)
    trazado.puntuacion = _puntuar(trazado, pesos)
    return trazado


def trazar(anillos: Sequence[Anillo], params: ParametrosTrazado, orientacion: Orientacion,
           pesos: PesosTrazado = PesosTrazado(), fuente: Optional[Punto] = None) -> Trazado:
    """Traza laterales y portalaterales para una dirección de laterales dada."""
    _verificar(anillos)
    return _trazar(anillos, params, orientacion, pesos, fuente, params.separacion_m, area_anillos(anillos))


def buscar_trazados(anillos: Sequence[Anillo], params: ParametrosTrazado,
                    orientaciones: Sequence[Orientacion], pesos: PesosTrazado = PesosTrazado(),
                    fuente: Optional[Punto] = None, cantidad=5,
                    separacion_minima_deg=8.0) -> List[Trazado]:
    """Prueba cada orientación y devuelve los mejores trazados, el primero es el mejor.

    Primero se descartan orientaciones con una pasada rápida (laterales más separados si
    el terreno es grande) y luego se trazan con la separación real las que quedan. Dos
    trazados con direcciones a menos de `separacion_minima_deg` cuentan como uno.
    """
    _verificar(anillos)
    if not orientaciones:
        raise ValueError("No hay orientaciones que probar.")
    area = area_anillos(anillos)
    puntos = [p for a in anillos for p in a]
    extension = max(max(p[0] for p in puntos) - min(p[0] for p in puntos),
                    max(p[1] for p in puntos) - min(p[1] for p in puntos))
    separacion_rapida = max(params.separacion_m, extension / 50)

    rapidos = [_trazar(anillos, params, o, pesos, fuente, separacion_rapida, area) for o in orientaciones]
    rapidos.sort(key=lambda t: t.puntuacion)
    elegidos = []
    for t in rapidos:
        if all(_distancia_angular(t.orientacion.angulo_deg, e.orientacion.angulo_deg) >= separacion_minima_deg
               for e in elegidos):
            elegidos.append(t)
        if len(elegidos) >= cantidad:
            break

    if separacion_rapida == params.separacion_m:
        finales = elegidos
    else:
        finales = [_trazar(anillos, params, t.orientacion, pesos, fuente, params.separacion_m, area)
                   for t in elegidos]
    finales.sort(key=lambda t: t.puntuacion)
    return finales


def _distancia_angular(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _verificar(anillos):
    if not any(len(a) >= 3 for a in anillos):
        raise ValueError("El terreno necesita al menos un contorno de tres vértices.")
