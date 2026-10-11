"""Trazado de la red principal sobre un mapa de costos: evita zonas, sigue caminos y tiene en cuenta el relieve.

Cuando el terreno tiene restricciones (`Terreno`), la red se busca sobre una cuadrícula con el
método de camino de menor costo (A*). La lógica es la misma del trazado sin restricciones: las
válvulas se conectan una a una al árbol ya construido, en el punto (cualquier celda de una
tubería existente) que menos aumenta el costo total, contando lo que encarece subir el
caudal por las tuberías que ya existen.

El costo de cada paso entre dos celdas, en metros equivalentes de tubería, es

    largo × factor de la zona × (1 + (pendiente / pendiente_duplica)²)  +  costo_subida × subida

donde la subida se cuenta solo en el sentido del flujo (cuesta energía de bombeo). Al final cada
tubería se endereza: en el modo directo con líneas rectas cuando no cuestan más que el camino
de celdas, y en el ortogonal con quiebres en ángulo recto.
"""

import heapq
import math
from typing import Dict, List, Optional, Sequence, Tuple

from .terreno import INFINITO, Terreno
from .trazado_red import (EPS, ORTOGONAL, ParametrosRed, RedTrazada, ValvulaDestino, _Arbol, _a_red,
                          _alineados, _Nodo, _ordenes)

MAX_CELDAS = 400_000
MARGENES = (0.25, 0.6, 1.2)  # holgura de la cuadrícula alrededor del predio, en veces su lado mayor
TOLERANCIA_ENDEREZADO = 1.02  # un tramo recto puede costar hasta un 2 % más que el camino de celdas

MOV4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]
MOV8 = MOV4 + [(1, 1), (1, -1), (-1, 1), (-1, -1)]
RAIZ2_MENOS_1 = math.sqrt(2) - 1

Punto = Tuple[float, float]


class _SinCamino(ValueError):
    pass


def _marco(fuente: Punto, angulo_grados: float):
    """Funciones del sistema original al marco girado (origen en la fuente) y de vuelta."""
    c, s = math.cos(math.radians(angulo_grados)), math.sin(math.radians(angulo_grados))

    def ida(p):
        return (p[0] - fuente[0]) * c + (p[1] - fuente[1]) * s, -(p[0] - fuente[0]) * s + (p[1] - fuente[1]) * c

    def vuelta(u, v):
        return fuente[0] + u * c - v * s, fuente[1] + u * s + v * c

    return ida, vuelta


class _Rejilla:
    """Cuadrícula de trabajo, en el marco girado, con el costo de cada paso entre celdas."""

    def __init__(self, terreno: Terreno, params: ParametrosRed, vuelta, extremos: Sequence[Punto],
                 ortogonal: bool, margen_relativo: float):
        self.terreno, self.params, self.ortogonal = terreno, params, ortogonal
        self.celda = c = terreno.paso
        us, vs = [p[0] for p in extremos], [p[1] for p in extremos]
        margen = max(margen_relativo * max(max(us) - min(us), max(vs) - min(vs)), 8 * c)
        self.ou, self.ov = min(us) - margen, min(vs) - margen
        self.nx = int(math.ceil((max(us) + margen - self.ou) / c)) + 1
        self.ny = int(math.ceil((max(vs) + margen - self.ov) / c)) + 1
        self.n = self.nx * self.ny
        if self.n > MAX_CELDAS:
            raise ValueError(f"La cuadrícula del trazado tendría {self.n:,} celdas; aumente el tamaño de celda.")

        self.fac = [1.0] * self.n
        self.z: Optional[List[float]] = [math.nan] * self.n if terreno.cotas is not None else None
        for j in range(self.ny):
            v = self.ov + (j + 0.5) * c
            base = j * self.nx
            for i in range(self.nx):
                x, y = vuelta(self.ou + (i + 0.5) * c, v)
                self.fac[base + i] = terreno.factor_en(x, y)
                if self.z is not None:
                    self.z[base + i] = terreno.cota_en(x, y)
        for u, v in extremos:
            self._despejar(u, v)
        libres = [f for f in self.fac if f != INFINITO]
        self.minfac = min(libres) if libres else 1.0
        self.movs = MOV4 if ortogonal else MOV8
        self._e: Dict[Tuple[int, int], List[float]] = {}
        self.desplazamiento = {m: m[1] * self.nx + m[0] for m in self.movs}

    def _despejar(self, u, v):
        """Las celdas junto a la fuente y a cada válvula quedan libres aunque caigan en una zona prohibida."""
        i0, j0 = math.floor((u - self.ou) / self.celda), math.floor((v - self.ov) / self.celda)
        for j in range(max(0, j0 - 2), min(self.ny, j0 + 3)):
            for i in range(max(0, i0 - 2), min(self.nx, i0 + 3)):
                cu, cv = self.ou + (i + 0.5) * self.celda, self.ov + (j + 0.5) * self.celda
                if math.hypot(cu - u, cv - v) <= 1.5 * self.celda and self.fac[j * self.nx + i] == INFINITO:
                    self.fac[j * self.nx + i] = 1.0

    # ------------------------------------------------------------ celdas

    def celda_en(self, u: float, v: float) -> Optional[int]:
        i, j = math.floor((u - self.ou) / self.celda), math.floor((v - self.ov) / self.celda)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return j * self.nx + i
        return None

    def celda_de_punto(self, p: Punto) -> int:
        celda = self.celda_en(*p)
        if celda is None:
            raise ValueError("Un punto del trazado quedó fuera de la cuadrícula.")
        return celda

    def centro(self, celda: int) -> Punto:
        j, i = divmod(celda, self.nx)
        return self.ou + (i + 0.5) * self.celda, self.ov + (j + 0.5) * self.celda

    def z_en(self, u: float, v: float) -> float:
        """Cota interpolada entre los centros de celda (NaN sin dato)."""
        fi, fj = (u - self.ou) / self.celda - 0.5, (v - self.ov) / self.celda - 0.5
        i0, j0 = math.floor(fi), math.floor(fj)
        a, b = fi - i0, fj - j0
        nx = self.nx
        i1 = min(max(i0 + 1, 0), nx - 1)
        i0 = min(max(i0, 0), nx - 1)
        j1 = min(max(j0 + 1, 0), self.ny - 1)
        j0 = min(max(j0, 0), self.ny - 1)
        z = self.z
        z00, z10, z01, z11 = z[j0 * nx + i0], z[j0 * nx + i1], z[j1 * nx + i0], z[j1 * nx + i1]
        suma = z00 + z10 + z01 + z11
        if suma != suma:  # alguna celda sin dato
            return math.nan
        return (z00 * (1 - a) + z10 * a) * (1 - b) + (z01 * (1 - a) + z11 * a) * b

    # ------------------------------------------------------------- costos

    def _multiplicador_pendiente(self, pendiente: float) -> float:
        referencia = self.params.pendiente_duplica
        return 1.0 + (pendiente / referencia) ** 2 if referencia else 1.0

    def costos(self, mov: Tuple[int, int]) -> List[float]:
        """Costo, por unidad de ponderación, de pasar de cada celda a la vecina en la dirección `mov`."""
        if mov in self._e:
            return self._e[mov]
        dx, dy = mov
        nx, ny, fac, z = self.nx, self.ny, self.fac, self.z
        d = math.hypot(dx, dy) * self.celda
        subida = self.params.costo_subida
        diagonal = dx != 0 and dy != 0
        off = dy * nx + dx
        e = [INFINITO] * self.n
        for j in range(max(0, -dy), min(ny, ny - dy)):
            base = j * nx
            for i in range(max(0, -dx), min(nx, nx - dx)):
                u = base + i
                v = u + off
                fu, fv = fac[u], fac[v]
                if fu == INFINITO or fv == INFINITO:
                    continue
                if diagonal and (fac[u + dx] == INFINITO or fac[u + dy * nx] == INFINITO):
                    continue  # no se corta por la esquina de una zona prohibida
                c = d * 0.5 * (fu + fv)
                if z is not None:
                    dz = z[v] - z[u]
                    if dz == dz:  # no es NaN
                        c *= self._multiplicador_pendiente(abs(dz) / d)
                        if dz > 0:
                            c += subida * dz
                e[u] = c
        self._e[mov] = e
        return e

    def costo_trazo(self, a: Punto, b: Punto, limite=INFINITO) -> float:
        """Costo, por unidad de ponderación, de una tubería recta de a hacia b (INFINITO si cruza algo prohibido)."""
        largo = math.dist(a, b)
        if largo < 1e-12:
            return 0.0
        n = max(1, int(math.ceil(largo / (self.celda / 3))))
        du, dv = (b[0] - a[0]) / n, (b[1] - a[1]) / n
        ds = largo / n
        con_cotas = self.z is not None
        z_ant = self.z_en(*a) if con_cotas else math.nan
        total = 0.0
        for k in range(n):
            celda = self.celda_en(a[0] + du * (k + 0.5), a[1] + dv * (k + 0.5))
            f = 1.0 if celda is None else self.fac[celda]
            if f == INFINITO:
                return INFINITO
            c = ds * f
            if con_cotas:
                z_sig = self.z_en(a[0] + du * (k + 1), a[1] + dv * (k + 1))
                dz = z_sig - z_ant
                if dz == dz:
                    c *= self._multiplicador_pendiente(abs(dz) / ds)
                    if dz > 0:
                        c += self.params.costo_subida * dz
                z_ant = z_sig
            total += c
            if total > limite:
                return total
        return total

    def costo_polilinea(self, puntos: Sequence[Punto], limite=INFINITO) -> float:
        total = 0.0
        for a, b in zip(puntos, puntos[1:]):
            total += self.costo_trazo(a, b, limite - total)
            if total > limite:
                return total
        return total


# --------------------------------------------------------------------- árbol


class _ArbolRejilla(_Arbol):
    """Árbol de tuberías cuyos nodos son celdas de la cuadrícula (el primero es la fuente)."""

    def __init__(self, rejilla: _Rejilla, params: ParametrosRed, caudal_ref: float):
        super().__init__((0.0, 0.0), params, caudal_ref, rejilla.ortogonal)
        self.rej = rejilla
        inicio = rejilla.celda_de_punto((0.0, 0.0))
        self.celdas = [inicio]  # celda de cada nodo
        self.e_arista = [0.0]  # costo, por unidad de ponderación, del tramo del padre al nodo
        self.por_celda = {inicio: 0}
        self.en_arbol = bytearray(rejilla.n)
        self.en_arbol[inicio] = 1

    def _subir(self, turno, q):
        """Para cada nodo: costo de subir `q` más por las tuberías hasta la fuente."""
        subir = [0.0] * len(self.nodos)
        for i in range(1, len(self.nodos)):
            n = self.nodos[i]
            subir[i] = subir[n.padre] + self.e_arista[i] * self.incremento_m(n.flujos, turno, q)
        return subir

    def agregar(self, nombre, punto: Punto, turno, q):
        rej = self.rej
        destino = rej.celda_de_punto(punto)
        if self.en_arbol[destino]:
            camino, union = [], destino
        else:
            camino, union = self._buscar(nombre, destino, self.costo_m(q), self._subir(turno, q))
        self._conectar(nombre, punto, turno, q, union, camino)

    def _buscar(self, nombre, destino, w, subir):
        """Camino de menor costo desde el árbol hasta la celda destino: (celdas, celda del árbol donde se une)."""
        rej = self.rej
        nx = rej.nx
        ti, tj = destino % nx, destino // nx
        k = w * rej.minfac * rej.celda
        if rej.ortogonal:
            def h(celda):
                j, i = divmod(celda, nx)
                return k * (abs(i - ti) + abs(j - tj))
        else:
            def h(celda):
                j, i = divmod(celda, nx)
                dx, dy = abs(i - ti), abs(j - tj)
                return k * (max(dx, dy) + RAIZ2_MENOS_1 * min(dx, dy))

        dist = [INFINITO] * rej.n
        previo = [-1] * rej.n
        cola = []
        for celda, nodo in self.por_celda.items():
            dist[celda] = subir[nodo]
            cola.append((subir[nodo] + h(celda), subir[nodo], celda))
        heapq.heapify(cola)
        movs = [(rej.desplazamiento[m], rej.costos(m)) for m in rej.movs]
        en_arbol = self.en_arbol
        alcanzado = False
        while cola:
            _, g, u = heapq.heappop(cola)
            if g > dist[u]:
                continue
            if u == destino:
                alcanzado = True
                break
            for desplazamiento, e in movs:
                c = e[u]
                if c == INFINITO:
                    continue
                v = u + desplazamiento
                if en_arbol[v]:
                    continue
                nuevo = g + w * c
                if nuevo < dist[v]:
                    dist[v] = nuevo
                    previo[v] = u
                    heapq.heappush(cola, (nuevo + h(v), nuevo, v))
        if not alcanzado:
            raise _SinCamino(f"No hay camino hasta la válvula «{nombre}»: la fuente o la válvula quedó "
                             "rodeada de zonas que no se pueden cruzar.")
        camino = []
        celda = destino
        while not en_arbol[celda]:
            camino.append(celda)
            celda = previo[celda]
        camino.reverse()
        return camino, celda

    def _conectar(self, nombre, punto: Punto, turno, q, union, camino):
        rej = self.rej
        padre = self.por_celda[union]
        anterior = union
        for k, celda in enumerate(camino):
            ultima = k == len(camino) - 1
            x, y = punto if ultima else rej.centro(celda)
            ja, ia = divmod(anterior, rej.nx)
            jb, ib = divmod(celda, rej.nx)
            self.nodos.append(_Nodo(x, y, padre, nombre if ultima else None))
            self.celdas.append(celda)
            self.e_arista.append(rej.costos((ib - ia, jb - ja))[anterior])
            padre = len(self.nodos) - 1
            self.por_celda[celda] = padre
            self.en_arbol[celda] = 1
            anterior = celda
        if not camino:  # la válvula cae en una celda que ya tiene tubería
            a = self.nodos[padre]
            if a.nombre is None and a.padre is not None:
                a.nombre = nombre
                a.x, a.y = punto
            else:
                self.nodos.append(_Nodo(punto[0], punto[1], padre, nombre))
                self.celdas.append(union)
                self.e_arista.append(0.0)
                padre = len(self.nodos) - 1
        j = padre
        while self.nodos[j].padre is not None:
            f = self.nodos[j].flujos
            f[turno] = f.get(turno, 0.0) + q
            j = self.nodos[j].padre

    def costo_celdas(self):
        """Costo del árbol medido sobre las celdas (sirve para comparar alternativas)."""
        return sum(self.e_arista[i] * self.costo_m(self.capacidad(n.flujos))
                   for i, n in enumerate(self.nodos) if n.padre is not None)


def _construir(rej: _Rejilla, ida, valvulas: Sequence[ValvulaDestino], params: ParametrosRed,
               orden: Sequence[ValvulaDestino]) -> _ArbolRejilla:
    por_turno: Dict[int, float] = {}
    for v in valvulas:
        por_turno[v.turno] = por_turno.get(v.turno, 0.0) + v.caudal_lh
    arbol = _ArbolRejilla(rej, params, max(por_turno.values(), default=1.0))
    for v in orden:
        arbol.agregar(v.id, ida((v.x, v.y)), v.turno, v.caudal_lh)
    return arbol


# --------------------------------------------------------------- enderezado


def _distancia_a_la_recta(p: Punto, a: Punto, b: Punto):
    largo = math.dist(a, b)
    if largo < EPS:
        return math.dist(p, a)
    return abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / largo


def _enderezar_directo(rej: _Rejilla, puntos: List[Punto]) -> List[Punto]:
    """Quita vértices del camino de celdas mientras el tramo recto no cueste más (con una pequeña tolerancia)."""
    n = len(puntos)
    if n <= 2:
        return puntos
    acumulado = [0.0]
    for a, b in zip(puntos, puntos[1:]):
        acumulado.append(acumulado[-1] + rej.costo_trazo(a, b))
    if acumulado[-1] == INFINITO:
        return puntos
    quedan = {0, n - 1}
    pila = [(0, n - 1)]
    while pila:
        i, j = pila.pop()
        if j - i < 2:
            continue
        presupuesto = (acumulado[j] - acumulado[i]) * TOLERANCIA_ENDEREZADO + 1e-9
        if rej.costo_trazo(puntos[i], puntos[j], presupuesto) <= presupuesto:
            continue
        m = max(range(i + 1, j), key=lambda k: _distancia_a_la_recta(puntos[k], puntos[i], puntos[j]))
        quedan.add(m)
        pila.append((i, m))
        pila.append((m, j))
    return [puntos[k] for k in sorted(quedan)]


def _sin_alineados(puntos: List[Punto]) -> List[Punto]:
    limpios = [puntos[0]]
    for p in puntos[1:]:
        if math.dist(p, limpios[-1]) < 1e-9:
            continue
        if len(limpios) >= 2 and _alineados(limpios[-2], limpios[-1], p):
            limpios[-1] = p
        else:
            limpios.append(p)
    if len(limpios) == 1:
        limpios.append(limpios[0])
    return limpios


def _esquinas(a: Punto, b: Punto):
    return [(b[0], a[1]), (a[0], b[1])]


def _ortogonalizar(rej: _Rejilla, puntos: List[Punto]) -> List[Punto]:
    """Agrega un quiebre en ángulo recto donde dos puntos consecutivos no están alineados con los ejes."""
    salida = [puntos[0]]
    for p in puntos[1:]:
        a = salida[-1]
        if abs(a[0] - p[0]) > 1e-9 and abs(a[1] - p[1]) > 1e-9:
            esquina = min(_esquinas(a, p), key=lambda e: rej.costo_polilinea([a, e, p]))
            salida.append(esquina)
        salida.append(p)
    return salida


def _un_atajo_ortogonal(rej: _Rejilla, p: List[Punto]) -> Optional[List[Punto]]:
    """Primer tramo escalonado de la línea que puede sustituirse por una L sin costar más; None si no hay."""
    acumulado = [0.0]
    for a, b in zip(p, p[1:]):
        acumulado.append(acumulado[-1] + rej.costo_trazo(a, b))
    for i in range(len(p) - 2):
        for j in range(len(p) - 1, i + 1, -1):
            original = acumulado[j] - acumulado[i]
            if original == INFINITO:
                continue
            limite = original * (1 + 1e-9) + 1e-9
            if rej.minfac * (abs(p[j][0] - p[i][0]) + abs(p[j][1] - p[i][1])) > limite:
                continue  # ni en el mejor de los casos una L cuesta menos
            for esquina in _esquinas(p[i], p[j]):
                costo = rej.costo_polilinea([p[i], esquina, p[j]], limite)
                if j - i == 2:
                    mejora = costo < original * (1 - 1e-9)  # solo cambia de esquina si sale más barata
                else:
                    mejora = costo <= limite
                if mejora:
                    return _sin_alineados(p[:i + 1] + [esquina] + p[j:])
    return None


def _enderezar_ortogonal(rej: _Rejilla, puntos: List[Punto]) -> List[Punto]:
    """Sustituye tramos escalonados por una L cuando esta no cuesta más ni cruza nada prohibido."""
    p = _sin_alineados(_ortogonalizar(rej, puntos))
    while len(p) > 2:
        nuevo = _un_atajo_ortogonal(rej, p)
        if nuevo is None:
            break
        p = nuevo
    return p


class _Compacto:
    """Árbol sin las celdas intermedias: solo fuente, válvulas, uniones y los quiebres del enderezado."""

    capacidad = staticmethod(_Arbol.capacidad)

    def __init__(self, nodos: List[_Nodo], rej: _Rejilla, base: _ArbolRejilla):
        self.nodos, self.rej, self.base = nodos, rej, base

    def _costo_arista(self, i):
        n = self.nodos[i]
        p = self.nodos[n.padre]
        return self.base.costo_m(self.capacidad(n.flujos)) * self.rej.costo_trazo((p.x, p.y), (n.x, n.y))

    def centrar_uniones(self, barridos=6):
        """Acerca cada unión al punto que minimiza el costo de los tramos que se juntan en ella.

        Es el punto de Fermat ponderado (con el costo por metro de cada tramo como peso). Como no
        considera el terreno, cada movimiento solo se acepta si el costo medido sobre el mapa baja.
        Solo en el trazado directo.
        """
        nodos = self.nodos
        hijos: Dict[int, List[int]] = {}
        for i, n in enumerate(nodos):
            if n.padre is not None:
                hijos.setdefault(n.padre, []).append(i)
        uniones = [i for i, n in enumerate(nodos)
                   if n.nombre is None and n.padre is not None and len(hijos.get(i, [])) >= 2]
        for _ in range(barridos):
            mayor_cambio = 0.0
            for i in uniones:
                n = nodos[i]
                aristas = [i] + hijos[i]
                vecinos = [nodos[n.padre]] + [nodos[h] for h in hijos[i]]
                pesos = [self.base.costo_m(self.capacidad(nodos[k].flujos)) for k in aristas]
                x, y = _Arbol._punto_de_fermat([(v.x, v.y) for v in vecinos], pesos, (n.x, n.y))
                actual = sum(self._costo_arista(k) for k in aristas)
                x0, y0 = n.x, n.y
                for t in (1.0, 0.5, 0.25):
                    n.x, n.y = x0 + (x - x0) * t, y0 + (y - y0) * t
                    if sum(self._costo_arista(k) for k in aristas) < actual - 1e-9:
                        mayor_cambio = max(mayor_cambio, math.hypot(n.x - x0, n.y - y0))
                        break
                    n.x, n.y = x0, y0
            if mayor_cambio < 1e-3:
                break

    def costo_total(self):
        total = 0.0
        for n in self.nodos:
            if n.padre is not None:
                p = self.nodos[n.padre]
                total += self.base.costo_m(self.capacidad(n.flujos)) * self.rej.costo_trazo((p.x, p.y), (n.x, n.y))
        return total


def _compactar(arbol: _ArbolRejilla) -> _Compacto:
    nodos, rej = arbol.nodos, arbol.rej
    hijos = [0] * len(nodos)
    for n in nodos:
        if n.padre is not None:
            hijos[n.padre] += 1
    singulares = [i for i, n in enumerate(nodos) if i == 0 or n.nombre is not None or hijos[i] != 1]
    es_singular = set(singulares)
    nuevos: List[_Nodo] = []
    numero = {}
    for i in singulares:
        numero[i] = len(nuevos)
        nuevos.append(_Nodo(nodos[i].x, nodos[i].y, None, nodos[i].nombre, dict(nodos[i].flujos)))
    enderezar = _enderezar_ortogonal if rej.ortogonal else _enderezar_directo
    for i in singulares:
        if i == 0:
            continue
        cadena = [i]
        j = nodos[i].padre
        while j not in es_singular:
            cadena.append(j)
            j = nodos[j].padre
        cadena.append(j)
        cadena.reverse()  # de aguas arriba hacia la válvula
        puntos = enderezar(rej, [(nodos[k].x, nodos[k].y) for k in cadena])
        previo = numero[j]
        for x, y in puntos[1:-1]:
            nuevos.append(_Nodo(x, y, previo, None, dict(nodos[i].flujos)))
            previo = len(nuevos) - 1
        nuevos[numero[i]].padre = previo
    return _Compacto(nuevos, rej, arbol)


# ------------------------------------------------------------------ resultado


def trazar_en_rejilla(fuente: Punto, valvulas: Sequence[ValvulaDestino], params: ParametrosRed,
                      terreno: Terreno) -> RedTrazada:
    """Traza la red de la fuente a las válvulas sobre el mapa de costos del terreno.

    La cuadrícula rodea el predio con una holgura limitada. Si la red resulta cruzando zonas que
    encarecen el tendido, o si hay relieve, se repite con más holgura por si conviene rodearlas, y
    se queda con la de menor costo (hasta que una holgura mayor deja de mejorar el costo en un 1 %).
    """
    mejor = error = None
    for margen in MARGENES:
        try:
            red = _trazar(fuente, valvulas, params, terreno, margen)
        except _SinCamino as e:
            error = e
            continue
        previo = mejor
        if mejor is None or red.costo < mejor.costo - EPS:
            mejor = red
        sin_mejora = previo is not None and red.costo > previo.costo * 0.99
        if sin_mejora or (red.m_penalizados == 0 and terreno.cotas is None):
            break
    if mejor is None:
        raise ValueError(str(error))
    return mejor


def _trazar(fuente: Punto, valvulas: Sequence[ValvulaDestino], params: ParametrosRed, terreno: Terreno,
            margen_relativo: float) -> RedTrazada:
    """Una pasada con la holgura dada alrededor del predio."""
    ortogonal = params.modo == ORTOGONAL
    if not ortogonal:
        angulos = [0.0]
    elif params.angulo_grados is not None:
        angulos = [params.angulo_grados % 90.0]
    else:
        n = max(1, int(round(90.0 / params.paso_angulo_grados)))
        angulos = [90.0 * k / n for k in range(n)]
    ordenes = _ordenes(fuente, valvulas)

    def terminar(rej, ida, orden):
        arbol = _construir(rej, ida, valvulas, params, orden)
        compacto = _compactar(arbol)
        if not ortogonal:
            compacto.centrar_uniones()
        return compacto.costo_total(), compacto

    mejor = None  # (costo, árbol compacto, ida, vuelta, ángulo)
    for angulo in angulos:
        ida, vuelta = _marco(fuente, angulo)
        extremos = [(0.0, 0.0)] + [ida((v.x, v.y)) for v in valvulas]
        rej = _Rejilla(terreno, params, vuelta, extremos, ortogonal, margen_relativo)
        for orden in ordenes:
            costo, compacto = terminar(rej, ida, orden)
            if mejor is None or costo < mejor[0] - EPS:
                mejor = (costo, compacto, ida, vuelta, angulo)
    _, compacto, _, vuelta, angulo = mejor
    red = _a_red(compacto, fuente, lambda n: vuelta(n.x, n.y), angulo if ortogonal else None, params.modo)
    red.celda_m = terreno.paso
    for t in red.tramos:
        mas, menos = terreno.medir(t.vertices)
        red.m_penalizados += mas
        red.m_descontados += menos
    return red
