"""Red principal ramificada: caudales por turno, pérdidas, presiones, diámetros y bomba.

La red es un árbol que parte de la fuente (bomba + cabezal) y llega a las
válvulas de las subunidades. En cada turno de riego solo funcionan las válvulas
de ese turno. Para cada turno se calcula la carga necesaria en la fuente para
que la válvula más desfavorecida reciba su presión y para que ningún punto de la
red (incluidos los puntos altos del terreno) baje de la presión mínima.

Cargas (H) en m sobre el mismo plano de referencia que las cotas; presiones en
m.c.a.; caudales en L/h.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .hidraulica import LH_A_M3S
from .tuberias import Tuberia, clave_economica


@dataclass
class TramoRed:
    id: str
    desde: str
    hasta: str
    longitud_m: float
    perfil: Optional[Sequence[Tuple[float, float]]] = None  # [(distancia desde «desde», cota)]
    tuberia: Optional[Tuberia] = None  # fija; None = la elige el dimensionamiento

    def invertido(self):
        perfil = None
        if self.perfil is not None:
            perfil = [(self.longitud_m - d, z) for d, z in reversed(self.perfil)]
        return TramoRed(self.id, self.hasta, self.desde, self.longitud_m, perfil, self.tuberia)


@dataclass
class Valvula:
    """Válvula de una subunidad: demanda de caudal y presión en un nodo de la red."""
    id: str
    nodo: str
    caudal_lh: float
    presion_requerida_m: float  # a la entrada de la subunidad (aguas abajo de la válvula)
    turno: int = 1
    perdida_m: float = 0.0  # pérdida en la propia válvula y accesorios


@dataclass
class CriteriosRed:
    velocidad_max_ms: float = 1.5
    perdida_unitaria_max_m100: Optional[float] = None  # m cada 100 m
    presion_min_m: float = 2.0  # en cualquier punto de la red funcionando
    factor_perdidas_menores: float = 0.10  # fracción de la pérdida por fricción
    metodo: str = "darcy"


@dataclass
class ResultadoTramo:
    caudal_lh: float
    velocidad_ms: float
    perdida_m: float  # fricción + pérdidas menores
    perdida_unitaria_m100: float
    presion_inicio_m: float
    presion_fin_m: float
    presion_min_m: float  # a lo largo del tramo (con el perfil del terreno, si existe)
    presion_max_m: float


@dataclass
class ResultadoTurno:
    turno: int
    caudal_total_lh: float
    carga_fuente_m: float  # cota piezométrica necesaria a la salida del cabezal
    presion_entrada_red_m: float
    critico: str  # qué fija la carga: una válvula o un punto de la red
    tramos: Dict[str, ResultadoTramo]
    cargas: Dict[str, float]  # cota piezométrica en cada nodo
    presiones: Dict[str, float]  # presión en cada nodo
    presion_disponible: Dict[str, float]  # por válvula activa, aguas abajo de la válvula

    def exceso(self, valvula):
        return self.presion_disponible[valvula.id] - valvula.presion_requerida_m


class Red:
    def __init__(self, cotas: Dict[str, float], tramos: List[TramoRed], valvulas: List[Valvula],
                 fuente: str):
        if fuente not in cotas:
            raise ValueError("La fuente no está en la red.")
        self.cotas = dict(cotas)
        self.fuente = fuente
        self.valvulas = list(valvulas)
        self.avisos: List[str] = []
        self._orientar(tramos)
        sin_conexion = [v.id for v in self.valvulas if v.nodo not in self.orden_set]
        if sin_conexion:
            raise ValueError("Estas válvulas no están conectadas a la fuente por la red: "
                             + ", ".join(sin_conexion))
        if not self.valvulas:
            raise ValueError("La red no tiene válvulas.")

    def _orientar(self, tramos):
        """Recorre la red desde la fuente y orienta cada tramo en el sentido del flujo."""
        adyacentes: Dict[str, List[TramoRed]] = {}
        for t in tramos:
            if t.desde == t.hasta:
                continue
            adyacentes.setdefault(t.desde, []).append(t)
            adyacentes.setdefault(t.hasta, []).append(t)
        self.padre: Dict[str, TramoRed] = {}  # nodo -> tramo que lo alimenta (orientado)
        self.hijos: Dict[str, List[TramoRed]] = {}
        self.orden: List[str] = [self.fuente]
        usados = set()
        cola = deque([self.fuente])
        while cola:
            nodo = cola.popleft()
            for t in adyacentes.get(nodo, []):
                if t.id in usados:
                    continue
                usados.add(t.id)
                orientado = t if t.desde == nodo else t.invertido()
                if orientado.hasta in self.padre or orientado.hasta == self.fuente:
                    raise ValueError(
                        f"La red tiene un circuito cerrado (tramo {t.id}). Por ahora RiegoLibre "
                        "calcula solo redes ramificadas.")
                self.padre[orientado.hasta] = orientado
                self.hijos.setdefault(nodo, []).append(orientado)
                self.orden.append(orientado.hasta)
                cola.append(orientado.hasta)
        self.orden_set = set(self.orden)
        self.tramos = [self.padre[n] for n in self.orden[1:]]
        sueltos = [t.id for t in tramos if t.id not in usados]
        if sueltos:
            self.avisos.append(f"{len(sueltos)} tramos no están conectados a la fuente y no se calcularon.")

    @property
    def turnos(self):
        return sorted({v.turno for v in self.valvulas})

    def camino(self, nodo):
        """Tramos desde la fuente hasta el nodo, en orden."""
        tramos = []
        while nodo != self.fuente:
            tramo = self.padre[nodo]
            tramos.append(tramo)
            nodo = tramo.desde
        return list(reversed(tramos))

    def caudales(self, turno):
        """Caudal (L/h) que circula por cada tramo en un turno."""
        demanda: Dict[str, float] = {}
        for v in self.valvulas:
            if v.turno == turno:
                demanda[v.nodo] = demanda.get(v.nodo, 0.0) + v.caudal_lh
        acumulado: Dict[str, float] = {}
        for nodo in reversed(self.orden):
            q = demanda.get(nodo, 0.0) + sum(acumulado[h.hasta] for h in self.hijos.get(nodo, []))
            acumulado[nodo] = q
        return {t.id: acumulado[t.hasta] for t in self.tramos}

    def caudales_maximos(self):
        maximos: Dict[str, float] = {t.id: 0.0 for t in self.tramos}
        for turno in self.turnos:
            for id_tramo, q in self.caudales(turno).items():
                maximos[id_tramo] = max(maximos[id_tramo], q)
        return maximos

    def calcular_turno(self, asignacion: Dict[str, Tuberia], turno, criterios=CriteriosRed()):
        caudal = self.caudales(turno)
        perdida: Dict[str, float] = {}
        for t in self.tramos:
            tuberia = asignacion[t.id]
            perdida[t.id] = (tuberia.perdida(caudal[t.id] * LH_A_M3S, t.longitud_m, criterios.metodo)
                             * (1 + criterios.factor_perdidas_menores))
        perdida_hasta = {self.fuente: 0.0}
        for nodo in self.orden[1:]:
            t = self.padre[nodo]
            perdida_hasta[nodo] = perdida_hasta[t.desde] + perdida[t.id]

        # Carga necesaria en la fuente para cada exigencia; manda la mayor.
        exigencias: List[Tuple[float, str]] = []
        activas = [v for v in self.valvulas if v.turno == turno]
        for v in activas:
            exigencias.append((self.cotas[v.nodo] + v.presion_requerida_m + v.perdida_m
                               + perdida_hasta[v.nodo], f"válvula {v.id}"))
        for nodo in self.orden:
            exigencias.append((self.cotas[nodo] + criterios.presion_min_m + perdida_hasta[nodo],
                               f"presión mínima en el nodo {nodo}"))
        for t in self.tramos:
            for x, z in t.perfil or ():
                pendiente_h = perdida[t.id] / t.longitud_m if t.longitud_m else 0.0
                exigencias.append((z + criterios.presion_min_m + perdida_hasta[t.desde] + pendiente_h * x,
                                   f"punto alto del tramo {t.id}"))
        carga_fuente, critico = max(exigencias, key=lambda e: e[0])

        cargas = {n: carga_fuente - perdida_hasta[n] for n in self.orden}
        presiones = {n: cargas[n] - self.cotas[n] for n in self.orden}
        tramos = {}
        for t in self.tramos:
            tuberia = asignacion[t.id]
            q = caudal[t.id]
            puntos = [(0.0, self.cotas[t.desde])] + list(t.perfil or ()) + [(t.longitud_m, self.cotas[t.hasta])]
            j = perdida[t.id] / t.longitud_m if t.longitud_m else 0.0
            presiones_tramo = [cargas[t.desde] - j * x - z for x, z in puntos]
            tramos[t.id] = ResultadoTramo(
                caudal_lh=q,
                velocidad_ms=tuberia.velocidad(q * LH_A_M3S),
                perdida_m=perdida[t.id],
                perdida_unitaria_m100=100 * j,
                presion_inicio_m=presiones[t.desde],
                presion_fin_m=presiones[t.hasta],
                presion_min_m=min(presiones_tramo),
                presion_max_m=max(presiones_tramo),
            )
        disponible = {v.id: presiones[v.nodo] - v.perdida_m for v in activas}
        return ResultadoTurno(
            turno=turno,
            caudal_total_lh=sum(v.caudal_lh for v in activas),
            carga_fuente_m=carga_fuente,
            presion_entrada_red_m=carga_fuente - self.cotas[self.fuente],
            critico=critico,
            tramos=tramos,
            cargas=cargas,
            presiones=presiones,
            presion_disponible=disponible,
        )


# ---------------------------------------------------------- dimensionamiento


def motivos_tuberia(tuberia, caudal_lh, presion_max_m, criterios):
    """Lista de criterios que la tubería no cumple para un caudal y una presión dados."""
    motivos = []
    q = caudal_lh * LH_A_M3S
    v = tuberia.velocidad(q)
    if v > criterios.velocidad_max_ms + 1e-9:
        motivos.append(f"velocidad {v:.2f} m/s > {criterios.velocidad_max_ms:g} m/s")
    if criterios.perdida_unitaria_max_m100 is not None:
        j = tuberia.perdida(q, 100.0, criterios.metodo)
        if j > criterios.perdida_unitaria_max_m100 + 1e-9:
            motivos.append(f"pérdida {j:.2f} m/100 m > {criterios.perdida_unitaria_max_m100:g}")
    if tuberia.presion_nominal_m is not None and presion_max_m > tuberia.presion_nominal_m + 1e-9:
        motivos.append(f"presión {presion_max_m:.1f} m > nominal {tuberia.presion_nominal_m:g} m")
    return motivos


def elegir_tuberia(candidatas, caudal_lh, presion_max_m, criterios):
    """La tubería más económica que cumple; si ninguna cumple, la mejor posible."""
    ordenadas = sorted(candidatas, key=clave_economica)
    for tuberia in ordenadas:
        if not motivos_tuberia(tuberia, caudal_lh, presion_max_m, criterios):
            return tuberia
    resisten = [t for t in candidatas
                if t.presion_nominal_m is None or t.presion_nominal_m >= presion_max_m]
    return max(resisten or candidatas, key=lambda t: t.diametro_interior_mm)


@dataclass
class ResultadoRed:
    red: Red
    asignacion: Dict[str, Tuberia]
    turnos: List[ResultadoTurno]
    criterios: CriteriosRed
    motivos: Dict[str, List[str]] = field(default_factory=dict)  # tramos que no cumplen
    avisos: List[str] = field(default_factory=list)
    sin_caudal: List[str] = field(default_factory=list)  # tramos sin válvulas aguas abajo

    def observaciones(self, id_tramo):
        if id_tramo in self.sin_caudal:
            return "sin caudal en ningún turno"
        return "; ".join(self.motivos.get(id_tramo, []))

    @property
    def turno_critico(self):
        return max(self.turnos, key=lambda r: r.presion_entrada_red_m)

    def turno(self, numero):
        return next(r for r in self.turnos if r.turno == numero)

    def peor_tramo(self, id_tramo):
        """Para un tramo: (caudal máximo, presión mínima y máxima en todos los turnos)."""
        resultados = [r.tramos[id_tramo] for r in self.turnos]
        return (max(r.caudal_lh for r in resultados), min(r.presion_min_m for r in resultados),
                max(r.presion_max_m for r in resultados))


def dimensionar_red(red, candidatas, criterios=CriteriosRed(), max_iteraciones=30,
                    candidatas_por_tramo=None):
    """Elige la tubería de cada tramo y calcula todos los turnos.

    Primero se dimensiona por caudal (velocidad y pérdida unitaria); luego, con las
    presiones resultantes, se sube la clase de presión donde haga falta y se repite
    hasta que ninguna tubería cambia. La presión exigida a cada tramo solo aumenta,
    de modo que el proceso termina.

    candidatas_por_tramo: {tramo: tuberías} para limitar la elección de algunos
    tramos (p. ej. a un diámetro nominal); los demás eligen entre todas.
    """
    if not candidatas:
        raise ValueError("No hay tuberías candidatas para la red principal.")
    candidatas_por_tramo = candidatas_por_tramo or {}
    caudal_max = red.caudales_maximos()
    presion_exigida = {t.id: 0.0 for t in red.tramos}
    asignacion: Dict[str, Tuberia] = {}
    resultados = []
    for _ in range(max_iteraciones):
        nueva = {t.id: t.tuberia or elegir_tuberia(candidatas_por_tramo.get(t.id, candidatas),
                                                   caudal_max[t.id], presion_exigida[t.id], criterios)
                 for t in red.tramos}
        resultados = [red.calcular_turno(nueva, turno, criterios) for turno in red.turnos]
        cambio = nueva != asignacion
        asignacion = nueva
        for t in red.tramos:
            presion = max(r.tramos[t.id].presion_max_m for r in resultados)
            if presion > presion_exigida[t.id] + 1e-6:
                presion_exigida[t.id] = presion
                cambio = True
        if not cambio:
            break

    resultado = ResultadoRed(red, asignacion, resultados, criterios, avisos=list(red.avisos),
                             sin_caudal=[t.id for t in red.tramos if caudal_max[t.id] <= 0])
    if resultado.sin_caudal:
        resultado.avisos.append("Tramos sin caudal en ningún turno (no llevan a ninguna válvula): "
                                + ", ".join(resultado.sin_caudal) + ".")
    for t in red.tramos:
        q, p_min, p_max = resultado.peor_tramo(t.id)
        motivos = motivos_tuberia(asignacion[t.id], q, p_max, criterios)
        if p_min < criterios.presion_min_m - 1e-6:
            motivos.append(f"presión mínima {p_min:.1f} m < {criterios.presion_min_m:g} m")
        if motivos:
            resultado.motivos[t.id] = motivos
    return resultado


# --------------------------------------------------------------------- bomba


@dataclass
class DatosBomba:
    perdidas_cabezal_m: float = 7.0  # filtros, fertirriego, medidor, válvulas del cabezal
    altura_succion_m: float = 2.0  # desnivel del agua hasta la bomba + pérdidas en la succión
    eficiencia: float = 0.70


@dataclass
class PuntoBomba:
    turno: int
    caudal_lh: float
    carga_dinamica_total_m: float
    potencia_kw: float

    @property
    def caudal_ls(self):
        return self.caudal_lh / 3600

    @property
    def caudal_m3h(self):
        return self.caudal_lh / 1000

    @property
    def potencia_hp(self):
        return self.potencia_kw / 0.7457


def punto_bomba(resultado_turno, datos=DatosBomba()):
    cdt = resultado_turno.presion_entrada_red_m + datos.perdidas_cabezal_m + datos.altura_succion_m
    q = resultado_turno.caudal_total_lh * LH_A_M3S
    potencia = 9.81 * q * cdt / datos.eficiencia  # kW (ρ·g = 9.81 kN/m³)
    return PuntoBomba(resultado_turno.turno, resultado_turno.caudal_total_lh, cdt, potencia)


def bomba_critica(bombas):
    """El punto de bomba de mayor CDT (a igual CDT, el de mayor caudal)."""
    return max(bombas, key=lambda b: (b.carga_dinamica_total_m, b.caudal_lh))


@dataclass
class PerfilRuta:
    """Terreno y línea piezométrica desde la fuente hasta una válvula."""
    turno: int
    valvula: str
    distancias_m: List[float]
    terreno_m: List[float]
    piezometrica_m: List[float]
    carga_requerida_m: float  # cota piezométrica necesaria antes de la válvula
    carga_fuente_m: float


def perfil_ruta_critica(red, turno):
    """Perfil hasta la válvula con menos exceso de presión de un turno (ResultadoTurno)."""
    activas = [v for v in red.valvulas if v.turno == turno.turno]
    valvula = min(activas, key=turno.exceso)
    x, terreno, piezometrica = [], [], []
    inicio = 0.0
    for t in red.camino(valvula.nodo):
        r = turno.tramos[t.id]
        j = r.perdida_m / t.longitud_m if t.longitud_m else 0.0
        puntos = [(0.0, red.cotas[t.desde])] + list(t.perfil or ()) + [(t.longitud_m, red.cotas[t.hasta])]
        for d, z in puntos:
            x.append(inicio + d)
            terreno.append(z)
            piezometrica.append(turno.cargas[t.desde] - j * d)
        inicio += t.longitud_m
    requerida = red.cotas[valvula.nodo] + valvula.presion_requerida_m + valvula.perdida_m
    return PerfilRuta(turno.turno, valvula.id, x, terreno, piezometrica, requerida, turno.carga_fuente_m)
