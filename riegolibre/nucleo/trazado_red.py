"""Trazado automático de la red principal: árbol de tuberías de la fuente a las válvulas.

El motor trabaja con coordenadas planas (m) y no conoce QGIS. Construye un árbol que une
la fuente con cada válvula minimizando un costo por metro que crece con el caudal
(economía de escala: una tubería gruesa sale más barata por litro que dos delgadas), de
modo que las válvulas tienden a compartir tuberías y a formar troncales.

Las válvulas se conectan una a una al árbol ya construido, en el punto (que puede estar a
mitad de un tramo, formando una unión en T) que menos aumenta el costo total. Hay dos
formas de tender la rama nueva:

- «ortogonal»: en un sistema de ejes girado un ángulo dado, solo con tramos paralelos a
  esos ejes (como la red de un predio cuadriculado). El ángulo puede probarse en varios
  valores y quedarse con el mejor.
- «directo»: en línea recta, con uniones donde el trayecto resulta más corto.

Con varios turnos, el caudal de un tramo es el máximo de lo que pasa en cada turno.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

ORTOGONAL = "ortogonal"
DIRECTO = "directo"

EXPONENTE_COSTO = 0.7  # costo por metro ∝ caudal^exponente (0 < e < 1: economía de escala)
COSTO_FIJO = 0.2  # costo por metro que no depende del caudal (zanja, mano de obra), en caudales totales
EPS = 1e-9

Punto = Tuple[float, float]


@dataclass
class ValvulaDestino:
    id: str
    x: float
    y: float
    caudal_lh: float
    turno: int = 1


@dataclass
class ParametrosRed:
    modo: str = ORTOGONAL
    angulo_grados: Optional[float] = None  # ortogonal: ángulo de los ejes; None = probar varios
    paso_angulo_grados: float = 15.0
    exponente: float = EXPONENTE_COSTO
    costo_fijo: float = COSTO_FIJO

    def __post_init__(self):
        if self.modo not in (ORTOGONAL, DIRECTO):
            raise ValueError(f"Modo de trazado desconocido: {self.modo}.")
        if not 0 < self.exponente < 1:
            raise ValueError("El exponente del costo debe estar entre 0 y 1 (sin incluirlos).")
        if self.costo_fijo < 0:
            raise ValueError("El costo fijo no puede ser negativo.")
        if self.paso_angulo_grados <= 0:
            raise ValueError("El paso del ángulo debe ser positivo.")


@dataclass
class TramoTrazado:
    """Tubería entre dos puntos singulares (fuente, válvula o unión), con sus quiebres.

    Una válvula que cae justo sobre otro punto singular lleva un tramo de longitud cero.
    """
    desde: str
    hasta: str
    vertices: List[Punto]  # de «desde» a «hasta», en el sistema original
    caudal_lh: float  # el mayor de los turnos

    @property
    def longitud_m(self):
        return sum(math.dist(a, b) for a, b in zip(self.vertices, self.vertices[1:]))


@dataclass
class RedTrazada:
    fuente: Punto
    tramos: List[TramoTrazado]
    uniones: Dict[str, Punto]  # puntos de unión añadidos (T), por nombre
    modo: str
    angulo_grados: Optional[float]  # ortogonal: el ángulo usado
    costo: float  # costo relativo del trazado (para comparar alternativas)

    @property
    def longitud_m(self):
        return sum(t.longitud_m for t in self.tramos)

    def longitud_por_caudal(self):
        return sum(t.longitud_m * t.caudal_lh for t in self.tramos)


# --------------------------------------------------------------------- árbol


@dataclass
class _Nodo:
    x: float
    y: float
    padre: Optional[int] = None
    nombre: Optional[str] = None  # fuente o válvula; None = unión o quiebre
    flujos: Dict[int, float] = field(default_factory=dict)  # turno -> caudal que pasa por el tramo al padre


class _Arbol:
    def __init__(self, fuente: Punto, params: ParametrosRed, caudal_ref: float, ortogonal: bool):
        self.nodos: List[_Nodo] = [_Nodo(fuente[0], fuente[1], None, "fuente")]
        self.params = params
        self.caudal_ref = max(caudal_ref, 1e-9)
        self.ortogonal = ortogonal

    # costo por metro de una tubería que lleva el caudal q
    def costo_m(self, q):
        if q <= 0:
            return 0.0
        return self.params.costo_fijo + (q / self.caudal_ref) ** self.params.exponente

    @staticmethod
    def capacidad(flujos):
        return max(flujos.values(), default=0.0)

    def incremento_m(self, flujos, turno, q):
        """Aumento del costo por metro de un tramo cuando su turno `turno` recibe `q` más."""
        antes = self.capacidad(flujos)
        despues = max(antes, flujos.get(turno, 0.0) + q)
        return self.costo_m(despues) - self.costo_m(antes)

    def distancia(self, a: Punto, b: Punto):
        if self.ortogonal:
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        return math.dist(a, b)

    def largo(self, i):
        n = self.nodos[i]
        p = self.nodos[n.padre]
        return math.hypot(n.x - p.x, n.y - p.y)

    def costo_hacia_la_raiz(self, turno, q):
        """Para cada nodo: costo de subir `q` más por el camino hasta la fuente."""
        costo: Dict[int, float] = {0: 0.0}
        # Un padre puede haberse creado después que su hijo (al partir un tramo), así que
        # cada nodo se resuelve subiendo con una pila hasta uno ya calculado.
        for i in range(len(self.nodos)):
            pila = []
            j = i
            while j not in costo:
                pila.append(j)
                j = self.nodos[j].padre
            for k in reversed(pila):
                n = self.nodos[k]
                costo[k] = costo[n.padre] + self.largo(k) * self.incremento_m(n.flujos, turno, q)
        return costo

    def mejor_conexion(self, punto: Punto, turno, q):
        """El punto del árbol que menos encarece conectar `punto`: (costo, nodo, distancia desde el padre)."""
        w = self.costo_m(q)
        subir = self.costo_hacia_la_raiz(turno, q)
        mejor = None
        for i, n in enumerate(self.nodos):
            costo = w * self.distancia(punto, (n.x, n.y)) + subir[i]
            if mejor is None or costo < mejor[0] - EPS:
                mejor = (costo, i, None)
        for i, n in enumerate(self.nodos):
            if n.padre is None:
                continue
            p = self.nodos[n.padre]
            largo = math.hypot(n.x - p.x, n.y - p.y)
            if largo < EPS:
                continue
            ux, uy = (n.x - p.x) / largo, (n.y - p.y) / largo
            s0 = (punto[0] - p.x) * ux + (punto[1] - p.y) * uy  # proyección sobre el tramo
            h = abs(-(punto[0] - p.x) * uy + (punto[1] - p.y) * ux)  # distancia perpendicular
            delta = self.incremento_m(n.flujos, turno, q)
            r = delta / w if w > 0 else 1.0
            if r < 1 - 1e-12:
                if self.ortogonal:
                    s = s0
                else:
                    s = s0 - h * r / math.sqrt(1 - r * r)
            else:
                s = 0.0
            s = min(max(s, 0.0), largo)
            if s < EPS or s > largo - EPS:
                continue  # los extremos ya se evaluaron como nodos
            a = (p.x + ux * s, p.y + uy * s)
            costo = w * self.distancia(punto, a) + delta * s + subir[n.padre]
            if costo < mejor[0] - EPS:
                mejor = (costo, i, s)
        return mejor

    def conectar(self, nombre, punto: Punto, turno, q, eleccion):
        _, i, s = eleccion
        if s is None:
            destino = i
        else:  # partir el tramo en un nodo de unión
            n = self.nodos[i]
            p = self.nodos[n.padre]
            largo = math.hypot(n.x - p.x, n.y - p.y)
            self.nodos.append(_Nodo(p.x + (n.x - p.x) * s / largo, p.y + (n.y - p.y) * s / largo, n.padre,
                                    None, dict(n.flujos)))
            destino = len(self.nodos) - 1
            n.padre = destino
        a = self.nodos[destino]
        cadena = self._camino(punto, (a.x, a.y), self._direccion_de(destino))
        padre = destino
        for k, (x, y) in enumerate(cadena):
            self.nodos.append(_Nodo(x, y, padre, nombre if k == len(cadena) - 1 else None))
            padre = len(self.nodos) - 1
        if not cadena:  # la válvula cae justo sobre un nodo del árbol
            if a.nombre is None:
                a.nombre = nombre
            else:
                self.nodos.append(_Nodo(a.x, a.y, destino, nombre))
                padre = len(self.nodos) - 1
        # el caudal sube por todos los tramos hasta la fuente
        j = padre
        while self.nodos[j].padre is not None:
            f = self.nodos[j].flujos
            f[turno] = f.get(turno, 0.0) + q
            j = self.nodos[j].padre

    def _direccion_de(self, i) -> Optional[Tuple[float, float]]:
        """Longitud en x y en y del tramo que llega al nodo (None si es la fuente)."""
        n = self.nodos[i]
        if n.padre is None:
            return None
        p = self.nodos[n.padre]
        return abs(n.x - p.x), abs(n.y - p.y)

    def _camino(self, desde: Punto, hasta: Punto, direccion):
        """Vértices de la rama nueva, del punto de unión (excluido) a la válvula (incluida)."""
        if math.dist(desde, hasta) < EPS:
            return []
        if not self.ortogonal or abs(desde[0] - hasta[0]) < EPS or abs(desde[1] - hasta[1]) < EPS:
            return [desde]
        # Quiebre en ángulo recto: el último tramo sigue la línea del tramo al que se une
        # (si es horizontal, la rama sale de la válvula en vertical), de modo que las troncales
        # se mantengan rectas.
        horizontal = direccion is None or direccion[0] >= direccion[1]
        esquina = (desde[0], hasta[1]) if horizontal else (hasta[0], desde[1])
        return [esquina, desde]

    def quitar_uniones_sobrantes(self):
        """Elimina los nodos sin nombre que quedaron con una sola rama (no son uniones ni quiebres)."""
        cuenta = [0] * len(self.nodos)
        for n in self.nodos:
            if n.padre is not None:
                cuenta[n.padre] += 1
        sobran = {i for i, n in enumerate(self.nodos) if n.nombre is None and cuenta[i] == 1}
        if not sobran:
            return
        for i, n in enumerate(self.nodos):
            if i in sobran:
                continue
            while n.padre in sobran:
                n.padre = self.nodos[n.padre].padre
        nuevo = {}
        for i in range(len(self.nodos)):
            if i not in sobran:
                nuevo[i] = len(nuevo)
        self.nodos = [n for i, n in enumerate(self.nodos) if i not in sobran]
        for n in self.nodos:
            if n.padre is not None:
                n.padre = nuevo[n.padre]

    @staticmethod
    def _punto_de_fermat(puntos, pesos, inicio, iteraciones=2000, tolerancia=1e-8):
        """Punto que minimiza la suma ponderada de distancias a `puntos` (Weiszfeld)."""
        x, y = inicio
        for _ in range(iteraciones):
            num_x = num_y = den = 0.0
            for (px, py), w in zip(puntos, pesos):
                d = max(math.hypot(x - px, y - py), 1e-9)
                num_x += w * px / d
                num_y += w * py / d
                den += w / d
            nuevo = (num_x / den, num_y / den)
            movimiento = math.hypot(nuevo[0] - x, nuevo[1] - y)
            x, y = nuevo
            if movimiento < tolerancia:
                break
        return x, y

    def insertar_uniones(self, vecinos=6, rondas=200):
        """Reúne en una unión dos ramas que salen del mismo nodo cuando eso abarata la red.

        El trazado por conexiones sucesivas deja ramas separadas que nacen juntas en un nodo
        (típicamente la fuente); si dos de ellas van en direcciones parecidas, compartir
        un tramo antes de separarse cuesta menos. Solo en el trazado directo.
        """
        for _ in range(rondas):
            hijos: Dict[int, List[int]] = {}
            for i, n in enumerate(self.nodos):
                if n.padre is not None:
                    hijos.setdefault(n.padre, []).append(i)
            candidatas = []
            for nodo, lista in hijos.items():
                if len(lista) < 2:
                    continue
                pares = {(min(a, b), max(a, b)) for a in lista for b in self._vecinos_cercanos(a, lista, vecinos)}
                for a, b in pares:
                    ahorro, posicion, flujos = self._ganancia_union(nodo, a, b)
                    if ahorro > 1e-6:
                        candidatas.append((ahorro, nodo, a, b, posicion, flujos))
            if not candidatas:
                return
            candidatas.sort(reverse=True)
            usadas = set()
            for _, nodo, a, b, posicion, flujos in candidatas:
                if a in usadas or b in usadas:
                    continue
                usadas.update((a, b))
                self.nodos.append(_Nodo(posicion[0], posicion[1], nodo, None, flujos))
                union = len(self.nodos) - 1
                self.nodos[a].padre = union
                self.nodos[b].padre = union

    def _vecinos_cercanos(self, a, lista, k):
        orden = sorted((b for b in lista if b != a),
                       key=lambda b: math.hypot(self.nodos[a].x - self.nodos[b].x,
                                                self.nodos[a].y - self.nodos[b].y))
        return orden[:k]

    def _ganancia_union(self, nodo, a, b):
        """Ahorro de unir las ramas a y b de `nodo` en una nueva unión: (ahorro, posición, caudales)."""
        n, na, nb = self.nodos[nodo], self.nodos[a], self.nodos[b]
        flujos = {t: na.flujos.get(t, 0.0) + nb.flujos.get(t, 0.0) for t in set(na.flujos) | set(nb.flujos)}
        w_a, w_b = self.costo_m(self.capacidad(na.flujos)), self.costo_m(self.capacidad(nb.flujos))
        w_n = self.costo_m(self.capacidad(flujos))
        actual = w_a * math.hypot(n.x - na.x, n.y - na.y) + w_b * math.hypot(n.x - nb.x, n.y - nb.y)
        puntos = [(n.x, n.y), (na.x, na.y), (nb.x, nb.y)]
        inicio = ((n.x + na.x + nb.x) / 3, (n.y + na.y + nb.y) / 3)
        u = self._punto_de_fermat(puntos, [w_n, w_a, w_b], inicio)
        nuevo = sum(w * math.hypot(u[0] - p[0], u[1] - p[1]) for p, w in zip(puntos, [w_n, w_a, w_b]))
        return actual - nuevo, u, flujos

    def centrar_uniones(self, barridos=8):
        """Mueve cada unión al punto que minimiza el costo de los tres tramos que se juntan en ella.

        Es el punto de Fermat ponderado, con el costo por metro de cada tramo como peso.
        Solo en el trazado directo; la topología y los caudales no cambian.
        """
        hijos: Dict[int, List[int]] = {}
        for i, n in enumerate(self.nodos):
            if n.padre is not None:
                hijos.setdefault(n.padre, []).append(i)
        uniones = [i for i, n in enumerate(self.nodos)
                   if n.nombre is None and n.padre is not None and len(hijos.get(i, [])) == 2]
        for _ in range(barridos):
            mayor_cambio = 0.0
            for i in uniones:
                n = self.nodos[i]
                vecinos = [(self.nodos[n.padre], self.costo_m(self.capacidad(n.flujos)))]
                vecinos += [(self.nodos[h], self.costo_m(self.capacidad(self.nodos[h].flujos))) for h in hijos[i]]
                x, y = self._punto_de_fermat([(v.x, v.y) for v, _ in vecinos], [w for _, w in vecinos],
                                             (n.x, n.y))
                mayor_cambio = max(mayor_cambio, math.hypot(x - n.x, y - n.y))
                n.x, n.y = x, y
            if mayor_cambio < 1e-6:
                break

    def costo_total(self):
        total = 0.0
        for i, n in enumerate(self.nodos):
            if n.padre is not None:
                total += self.largo(i) * self.costo_m(self.capacidad(n.flujos))
        return total


def _construir(fuente: Punto, valvulas: Sequence[ValvulaDestino], params: ParametrosRed, ortogonal: bool,
               orden: Sequence[ValvulaDestino]):
    por_turno: Dict[int, float] = {}
    for v in valvulas:
        por_turno[v.turno] = por_turno.get(v.turno, 0.0) + v.caudal_lh
    arbol = _Arbol(fuente, params, max(por_turno.values(), default=1.0), ortogonal)
    for v in orden:
        punto = (v.x, v.y)
        arbol.conectar(v.id, punto, v.turno, v.caudal_lh, arbol.mejor_conexion(punto, v.turno, v.caudal_lh))
    return arbol


# ------------------------------------------------------------------- resultado


def _a_red(arbol: _Arbol, fuente: Punto, giro, angulo, modo) -> RedTrazada:
    """Convierte el árbol en tramos entre puntos singulares (fuente, válvulas y uniones)."""
    nodos = arbol.nodos
    hijos: Dict[int, List[int]] = {}
    for i, n in enumerate(nodos):
        if n.padre is not None:
            hijos.setdefault(n.padre, []).append(i)
    nombres: Dict[int, str] = {}
    contador = 0
    for i, n in enumerate(nodos):
        if n.nombre is not None:
            nombres[i] = n.nombre
        elif len(hijos.get(i, [])) >= 2:
            contador += 1
            nombres[i] = f"Unión {contador}"
    uniones = {nombres[i]: giro(nodos[i]) for i in nombres if nodos[i].nombre is None}

    tramos = []
    for i in nombres:
        if nodos[i].padre is None:
            continue
        vertices = [i]
        j = nodos[i].padre
        while j not in nombres:
            vertices.append(j)
            j = nodos[j].padre
        vertices.append(j)
        vertices.reverse()  # de la fuente hacia la válvula
        puntos = [giro(nodos[k]) for k in vertices]
        # quitar vértices repetidos o alineados
        limpios = [puntos[0]]
        for k in range(1, len(puntos)):
            if math.dist(puntos[k], limpios[-1]) < 1e-6:
                continue
            if len(limpios) >= 2 and _alineados(limpios[-2], limpios[-1], puntos[k]):
                limpios[-1] = puntos[k]
            else:
                limpios.append(puntos[k])
        if len(limpios) < 2:  # válvula en el mismo punto que su nodo de aguas arriba
            limpios = [puntos[0], puntos[0]]
        tramos.append(TramoTrazado(nombres[j], nombres[i], limpios, arbol.capacidad(nodos[i].flujos)))
    return RedTrazada(fuente, tramos, uniones, modo, angulo, arbol.costo_total())


def _alineados(a: Punto, b: Punto, c: Punto):
    cruz = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    punto = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
    return abs(cruz) < 1e-6 * max(1.0, math.dist(a, c)) and punto > 0


def _ordenes(fuente, valvulas):
    por_distancia = sorted(valvulas, key=lambda v: math.dist(fuente, (v.x, v.y)))
    return [por_distancia, por_distancia[::-1]]


def trazar_red(fuente: Punto, valvulas: Sequence[ValvulaDestino], params: ParametrosRed = ParametrosRed()) -> RedTrazada:
    """Traza la red principal de la fuente a todas las válvulas."""
    if not valvulas:
        raise ValueError("No hay válvulas que conectar a la fuente.")
    sin_caudal = [v.id for v in valvulas if v.caudal_lh <= 0]
    if sin_caudal:
        raise ValueError("Estas válvulas no tienen caudal: " + ", ".join(sin_caudal) + ".")
    if params.modo == DIRECTO:
        mejor = None
        for orden in _ordenes(fuente, valvulas):
            arbol = _construir(fuente, valvulas, params, False, orden)
            arbol.insertar_uniones()
            arbol.quitar_uniones_sobrantes()
            arbol.centrar_uniones()
            if mejor is None or arbol.costo_total() < mejor.costo_total() - EPS:
                mejor = arbol
        return _a_red(mejor, fuente, lambda n: (n.x, n.y), None, DIRECTO)

    if params.angulo_grados is not None:
        angulos = [params.angulo_grados % 90.0]
    else:
        n = max(1, int(round(90.0 / params.paso_angulo_grados)))
        angulos = [90.0 * k / n for k in range(n)]
    mejor = None
    for angulo in angulos:
        ida, vuelta = _giro(fuente, angulo)
        giradas = [ValvulaDestino(v.id, *ida((v.x, v.y)), v.caudal_lh, v.turno) for v in valvulas]
        for orden in _ordenes((0.0, 0.0), giradas):
            arbol = _construir((0.0, 0.0), giradas, params, True, orden)
            costo = arbol.costo_total()
            if mejor is None or costo < mejor[0] - EPS:
                mejor = (costo, arbol, vuelta, angulo)
    _, arbol, vuelta, angulo = mejor
    return _a_red(arbol, fuente, lambda n: vuelta(n), angulo, ORTOGONAL)


def _giro(fuente: Punto, angulo_grados):
    """Funciones al sistema de ejes girado (con origen en la fuente) y de vuelta al original."""
    c, s = math.cos(math.radians(angulo_grados)), math.sin(math.radians(angulo_grados))

    def ida(p):
        return (p[0] - fuente[0]) * c + (p[1] - fuente[1]) * s, -(p[0] - fuente[0]) * s + (p[1] - fuente[1]) * c

    def vuelta(n):
        return fuente[0] + n.x * c - n.y * s, fuente[1] + n.x * s + n.y * c

    return ida, vuelta
