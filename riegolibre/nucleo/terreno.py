"""Mapa de costos del terreno para el trazado de la red: zonas, caminos, barreras y relieve.

Es una cuadrícula alineada con los ejes, en coordenadas planas (m). Cada celda guarda un factor
que multiplica el costo por metro de tubería que la cruza:

- 1: terreno normal;
- mayor que 1: zona que conviene evitar (o una barrera que cuesta cruzar);
- menor que 1: camino o zanja existente que conviene seguir;
- infinito: no se puede cruzar.

Si hay un modelo de elevación, cada celda guarda además su cota.
"""

import math
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

INFINITO = math.inf
MAX_CELDAS = 1_500_000
Punto = Tuple[float, float]


def celda_automatica(puntos: Sequence[Punto], celdas_por_lado=100, minima_m=1.0) -> float:
    """Tamaño de celda con el que el lado mayor del predio queda en unas `celdas_por_lado` celdas."""
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    lado = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    return max(minima_m, float(f"{lado / celdas_por_lado:.2g}"))


def celdas_de_segmento(a: Punto, b: Punto):
    """Celdas unitarias (i, j) que toca el segmento a-b, en unidades de celda.

    Las celdas consecutivas comparten un lado (nunca solo una esquina), de modo que una línea
    marcada así no deja pasos en diagonal.
    """
    x, y = a
    i, j = math.floor(x), math.floor(y)
    i_fin, j_fin = math.floor(b[0]), math.floor(b[1])
    dx, dy = b[0] - x, b[1] - y
    paso_i = 1 if dx > 0 else -1
    paso_j = 1 if dy > 0 else -1
    if dx != 0:
        t_x = (i + (1 if dx > 0 else 0) - x) / dx
        d_x = abs(1.0 / dx)
    else:
        t_x = d_x = INFINITO
    if dy != 0:
        t_y = (j + (1 if dy > 0 else 0) - y) / dy
        d_y = abs(1.0 / dy)
    else:
        t_y = d_y = INFINITO
    yield i, j
    while (i, j) != (i_fin, j_fin):
        if i == i_fin:
            j += paso_j
            t_y += d_y
        elif j == j_fin:
            i += paso_i
            t_x += d_x
        elif t_x < t_y:
            i += paso_i
            t_x += d_x
        elif t_y < t_x:
            j += paso_j
            t_y += d_y
        else:  # pasa justo por una esquina: se toma también una de las celdas laterales
            yield i + paso_i, j
            i += paso_i
            j += paso_j
            t_x += d_x
            t_y += d_y
        yield i, j


class Terreno:
    """Cuadrícula de factores de costo (y cotas) del terreno."""

    def __init__(self, x0: float, y0: float, paso: float, nx: int, ny: int):
        if paso <= 0 or nx < 1 or ny < 1:
            raise ValueError("La cuadrícula del terreno necesita un paso positivo y al menos una celda.")
        self.x0, self.y0, self.paso, self.nx, self.ny = x0, y0, paso, nx, ny
        self.factor: List[float] = [1.0] * (nx * ny)
        self.cotas: Optional[List[float]] = None  # NaN donde no hay dato

    @classmethod
    def cubriendo(cls, puntos: Sequence[Punto], paso: float) -> "Terreno":
        """Cuadrícula centrada en los puntos y con holgura para rodear obstáculos con el trazado girado."""
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        ancho, alto = max(xs) - min(xs), max(ys) - min(ys)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        margen = max(1.2 * max(ancho, alto), 8 * paso)  # la mayor holgura que usa el trazado (MARGENES)
        semilado = 1.5 * (0.5 * math.hypot(ancho, alto) + margen)
        n = int(math.ceil(2 * semilado / paso))
        if n * n > MAX_CELDAS:
            raise ValueError(f"La cuadrícula del terreno tendría {n * n:,} celdas con celdas de {paso:g} m; "
                             "aumente el tamaño de celda.")
        return cls(cx - n * paso / 2, cy - n * paso / 2, paso, n, n)

    # ------------------------------------------------------------- consultas

    def celda_de(self, x: float, y: float) -> Optional[int]:
        i = math.floor((x - self.x0) / self.paso)
        j = math.floor((y - self.y0) / self.paso)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return j * self.nx + i
        return None

    def factor_en(self, x: float, y: float) -> float:
        celda = self.celda_de(x, y)
        return 1.0 if celda is None else self.factor[celda]

    def cota_en(self, x: float, y: float) -> float:
        """Cota de la celda que contiene el punto (NaN si no hay dato)."""
        celda = self.celda_de(x, y)
        if celda is None or self.cotas is None:
            return math.nan
        return self.cotas[celda]

    @property
    def tiene_efecto(self) -> bool:
        return self.cotas is not None or any(f != 1.0 for f in self.factor)

    # ------------------------------------------------------------ restricciones

    def penalizar_poligono(self, anillos: Sequence[Sequence[Punto]], factor: Optional[float]):
        """Encarece (factor ≥ 1) o prohíbe (factor None) cruzar un polígono; los anillos interiores son huecos."""
        f = INFINITO if factor is None else float(factor)
        if f < 1:
            raise ValueError("El factor de una zona a evitar no puede ser menor que 1.")
        for celda in self._celdas_de_poligono(anillos):
            if f > self.factor[celda]:
                self.factor[celda] = f

    def descontar_linea(self, vertices: Sequence[Punto], factor: float):
        """Abarata (0 < factor ≤ 1) el tendido a lo largo de una línea, como un camino o una zanja."""
        if not 0 < factor <= 1:
            raise ValueError("El factor de un camino a seguir debe estar entre 0 y 1.")
        for celda in self._celdas_de_linea(vertices):
            if self.factor[celda] != INFINITO:
                self.factor[celda] *= factor

    def barrera_linea(self, vertices: Sequence[Punto], costo_cruce_m: Optional[float]):
        """Una línea que cuesta cruzar `costo_cruce_m` metros de tubería (None: no se puede cruzar)."""
        if costo_cruce_m is None:
            f = INFINITO
        elif costo_cruce_m < 0:
            raise ValueError("El costo de cruce no puede ser negativo.")
        else:
            f = 1.0 + costo_cruce_m / self.paso
        for celda in self._celdas_de_linea(vertices):
            if f > self.factor[celda]:
                self.factor[celda] = f

    def poner_cotas(self, cotas: Sequence[float]):
        """Asigna las cotas de todas las celdas (en el orden de la cuadrícula; NaN si no hay dato)."""
        if len(cotas) != self.nx * self.ny:
            raise ValueError("Las cotas no coinciden con el tamaño de la cuadrícula.")
        self.cotas = [math.nan if c is None else float(c) for c in cotas]

    def cargar_cotas(self, cota: Callable[[float, float], Optional[float]]):
        """Pide la cota del centro de cada celda a una función (x, y) → cota o None."""
        cotas = []
        for j in range(self.ny):
            y = self.y0 + (j + 0.5) * self.paso
            for i in range(self.nx):
                cotas.append(cota(self.x0 + (i + 0.5) * self.paso, y))
        self.poner_cotas(cotas)

    def medir(self, vertices: Sequence[Punto]) -> Tuple[float, float]:
        """Metros de una línea que pasan por zonas con factor > 1 y por zonas con factor < 1."""
        mas = menos = 0.0
        for a, b in zip(vertices, vertices[1:]):
            largo = math.dist(a, b)
            n = max(1, int(math.ceil(largo / (self.paso / 3))))
            for k in range(n):
                t = (k + 0.5) / n
                f = self.factor_en(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if f > 1 + 1e-9:
                    mas += largo / n
                elif f < 1 - 1e-9:
                    menos += largo / n
        return mas, menos

    # --------------------------------------------------------------- celdas

    def _en_celdas(self, p: Punto):
        return (p[0] - self.x0) / self.paso, (p[1] - self.y0) / self.paso

    def _celdas_de_linea(self, vertices: Sequence[Punto]) -> Iterable[int]:
        tocadas = set()
        puntos = [self._en_celdas(p) for p in vertices]
        if len(puntos) == 1:
            puntos = puntos * 2
        for a, b in zip(puntos, puntos[1:]):
            for i, j in celdas_de_segmento(a, b):
                if 0 <= i < self.nx and 0 <= j < self.ny:
                    tocadas.add(j * self.nx + i)
        return tocadas

    def _celdas_de_poligono(self, anillos: Sequence[Sequence[Punto]]) -> Iterable[int]:
        """Celdas con el centro dentro del polígono (regla par-impar) más las que toca su borde."""
        aristas = []
        for anillo in anillos:
            for a, b in zip(anillo, list(anillo[1:]) + [anillo[0]]):
                if a != b:
                    aristas.append((a, b))
        if not aristas:
            return set()
        celdas = set()
        for a, b in aristas:
            celdas.update(self._celdas_de_linea([a, b]))
        y_min = min(min(a[1], b[1]) for a, b in aristas)
        y_max = max(max(a[1], b[1]) for a, b in aristas)
        j0 = max(0, math.floor((y_min - self.y0) / self.paso))
        j1 = min(self.ny - 1, math.floor((y_max - self.y0) / self.paso))
        for j in range(j0, j1 + 1):
            y = self.y0 + (j + 0.5) * self.paso
            cortes = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                            for a, b in aristas if (a[1] <= y) != (b[1] <= y))
            for k in range(0, len(cortes) - 1, 2):
                i0 = max(0, math.ceil((cortes[k] - self.x0) / self.paso - 0.5))
                i1 = min(self.nx - 1, math.ceil((cortes[k + 1] - self.x0) / self.paso - 0.5) - 1)
                celdas.update(range(j * self.nx + i0, j * self.nx + i1 + 1))
        return celdas
