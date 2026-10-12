"""Diámetros del portalateral por velocidad (como el dimensionado por velocidad de IRRICAD).

Con el portalateral y la válvula ya ubicados, cada rama (de la válvula hacia un extremo) se parte en
tramos entre conexiones de laterales. El caudal de un tramo es el de todos los laterales que quedan
aguas abajo, así que disminuye hacia el final. A cada tramo le corresponde la tubería más pequeña de la
serie elegida cuya velocidad no pasa de la máxima, hasta el menor diámetro de la serie. Con un número
máximo de diámetros por rama (el «Number of Submain Sizes» de IRRICAD) se usan los diámetros consecutivos
de la serie desde el de la entrada: con 90 mm en la válvula y 3 diámetros, 90, 75 y 63 mm. Luego los
tramos se agrupan en secciones de un mismo diámetro, con un largo mínimo por sección (un tubo), eligiendo
la agrupación de menor costo (programación dinámica). Cada sección lleva la tubería que exige su primer
tramo, así que en ningún tramo se pasa la velocidad máxima.

Las ramas se dimensionan por separado: con la válvula al centro, cada una lleva sus diámetros.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .portalateral import LH_A_M3S
from .subunidad import (Diseno, _evaluar, costo_relativo, incumplimientos)
from .tuberias import Tuberia, clave_economica

PASO_AJUSTE_MS = 0.1  # al ajustar por la variación de caudal, la velocidad baja de a esto
VELOCIDAD_MINIMA_AJUSTE_MS = 0.3


@dataclass(frozen=True)
class CriterioVelocidad:
    velocidad_max_ms: float = 1.5
    diametros_max: int = 3  # tuberías distintas por rama, consecutivas en la serie; 0 = sin límite
    tramo_min_m: float = 6.0  # largo mínimo de una sección de un mismo diámetro
    ajustar_variacion: bool = True  # bajar la velocidad hasta cumplir los criterios de la subunidad

    def __post_init__(self):
        if self.velocidad_max_ms <= 0:
            raise ValueError("La velocidad máxima debe ser mayor que cero.")
        if self.diametros_max < 0:
            raise ValueError("El número de diámetros no puede ser negativo (0 = sin límite).")
        if self.tramo_min_m < 0:
            raise ValueError("El largo mínimo de una sección no puede ser negativo.")


@dataclass
class RamaDimensionada:
    tuberia: Tuberia  # la de la válvula
    reducciones: List[Tuple[float, Tuberia]]  # [(distancia desde la válvula, tubería desde allí)]
    velocidad_max_ms: float  # con los caudales nominales
    insuficiente: bool = False  # ni la mayor tubería de la serie baja de la velocidad máxima


# ------------------------------------------------------------------ series


@dataclass
class Serie:
    clave: str
    nombre: str
    tuberias: List[Tuberia] = field(default_factory=list)  # de menor a mayor diámetro


TODAS_LAS_CLASES = "*"


def clave_serie(tuberia: Tuberia) -> str:
    return f"{tuberia.material}|{tuberia.presion_nominal_m or 0:g}"


def _orden_serie(clave):
    material, pn = clave.split("|")
    return material, -1.0 if pn == TODAS_LAS_CLASES else float(pn)


def _nombre_serie(material, pn, lista):
    diametros = [t.diametro_nominal_mm or t.diametro_interior_mm for t in lista]
    rango = f"{len(lista)} diámetros ({min(diametros):g}–{max(diametros):g} mm)"
    if pn == TODAS_LAS_CLASES:
        return f"{material} · {rango} · la clase más baja de cada uno"
    return f"{material}" + (f" PN {float(pn):g} m" if float(pn) else "") + f" · {rango}"


def series_de_tuberias(tuberias: Sequence[Tuberia]) -> List[Serie]:
    """Tuberías agrupadas por material y presión nominal (p. ej. PVC C-5), de menor a mayor diámetro.

    Dentro de una serie, si hay dos con el mismo diámetro nominal se queda la de mayor diámetro interior.
    Si un material tiene varias clases se añade además la serie de todas ellas (clave «PVC|*»): cada
    diámetro de la base de datos con su clase más baja. Así, como en IRRICAD, el portalateral baja hasta el
    menor diámetro marcado para ese uso aunque sea de otra clase (p. ej. PVC 63–110 mm C-5 y 1½" C-7.5).
    """
    grupos: Dict[str, Dict[float, Tuberia]] = {}
    for t in tuberias:
        d = t.diametro_nominal_mm or t.diametro_interior_mm
        por_diametro = grupos.setdefault(clave_serie(t), {})
        if d not in por_diametro or t.diametro_interior_mm > por_diametro[d].diametro_interior_mm:
            por_diametro[d] = t
        todas = grupos.setdefault(f"{t.material}|{TODAS_LAS_CLASES}", {})
        if d not in todas or clave_economica(t) < clave_economica(todas[d]):
            todas[d] = t
    series = []
    for clave, por_diametro in grupos.items():
        material, pn = clave.split("|")
        if pn == TODAS_LAS_CLASES and len({clave_serie(t) for t in tuberias if t.material == material}) < 2:
            continue  # una sola clase: sería la misma serie
        lista = sorted(por_diametro.values(), key=lambda t: t.diametro_interior_mm)
        series.append(Serie(clave, _nombre_serie(material, pn, lista), lista))
    series.sort(key=lambda s: _orden_serie(s.clave))
    return series


def serie_por_defecto(series: Sequence[Serie]) -> Optional[Serie]:
    """La de PVC con todas sus clases (o la única clase de PVC) o, si no hay PVC, la primera."""
    return next((s for s in series if s.clave.upper().startswith("PVC|")), series[0] if series else None)


# ------------------------------------------------------------------ una rama


def _tubo_para(caudal_lh, tuberias, velocidad_max):
    """Índice de la tubería más pequeña que no pasa la velocidad (o la mayor, y False)."""
    for i, t in enumerate(tuberias):
        if t.velocidad(caudal_lh * LH_A_M3S) <= velocidad_max + 1e-9:
            return i, True
    return len(tuberias) - 1, False


def dimensionar_rama(distancias_m: Sequence[float], caudales_lh: Sequence[float], tuberias: Sequence[Tuberia],
                     criterio: CriterioVelocidad,
                     costo: Callable[[Tuberia], float] = costo_relativo) -> RamaDimensionada:
    """Diámetros de una rama.

    `distancias_m` son las de las conexiones desde la válvula (crecientes) y `caudales_lh` lo que sale
    en cada una. `tuberias` es la serie, de menor a mayor diámetro.
    """
    if not distancias_m:
        raise ValueError("La rama no tiene conexiones.")
    tuberias = sorted(tuberias, key=lambda t: t.diametro_interior_mm)
    n = len(distancias_m)
    largos = [distancias_m[0]] + [distancias_m[k] - distancias_m[k - 1] for k in range(1, n)]
    aguas_abajo = [sum(caudales_lh[k:]) for k in range(n)]
    requeridos, suficiente = [], True
    for q in aguas_abajo:
        i, ok = _tubo_para(q, tuberias, criterio.velocidad_max_ms)
        requeridos.append(i)
        suficiente = suficiente and ok

    minimo = criterio.tramo_min_m  # una rama más corta queda de una sola tubería (la sección completa vale)
    secciones_max = criterio.diametros_max or len(tuberias)
    # Diámetros consecutivos desde el de la entrada: con 3 y 90 mm en la válvula no se baja de 63 mm.
    menor = max(0, max(requeridos) - secciones_max + 1)
    requeridos = [max(i, menor) for i in requeridos]
    infinito = math.inf
    # mejor[j][s]: costo de cubrir los tramos 0..j-1 con s secciones; desde[j][s]: inicio de la última
    mejor = [[infinito] * (secciones_max + 1) for _ in range(n + 1)]
    desde = [[None] * (secciones_max + 1) for _ in range(n + 1)]
    mejor[0][0] = 0.0
    for j in range(1, n + 1):
        largo, mayor = 0.0, -1
        for i in range(j - 1, -1, -1):  # la sección cubre los tramos i..j-1
            largo += largos[i]
            mayor = max(mayor, requeridos[i])
            if largo < minimo - 1e-9 and not (i == 0 and j == n):
                continue
            precio = largo * costo(tuberias[mayor])
            for s in range(1, secciones_max + 1):
                if mejor[i][s - 1] + precio < mejor[j][s] - 1e-12:
                    mejor[j][s] = mejor[i][s - 1] + precio
                    desde[j][s] = (i, mayor)
    s = min(range(1, secciones_max + 1), key=lambda k: mejor[n][k])
    if mejor[n][s] == infinito:  # el largo mínimo no deja partir: una sola tubería
        i_mayor = max(requeridos)
        secciones = [(0, i_mayor)]
    else:
        secciones, j = [], n
        while j > 0:
            i, indice = desde[j][s]
            secciones.append((i, indice))
            j, s = i, s - 1
        secciones.reverse()
    # Secciones vecinas con la misma tubería se unen.
    unidas = []
    for i, indice in secciones:
        if not unidas or unidas[-1][1] != indice:
            unidas.append((i, indice))
    inicio = [0.0] + list(distancias_m)
    tuberia = tuberias[unidas[0][1]]
    reducciones = [(inicio[i], tuberias[indice]) for i, indice in unidas[1:]]
    # Velocidad máxima con la tubería asignada a cada tramo
    asignada, velocidad = 0, 0.0
    for k in range(n):
        while asignada + 1 < len(unidas) and unidas[asignada + 1][0] <= k:
            asignada += 1
        velocidad = max(velocidad, tuberias[unidas[asignada][1]].velocidad(aguas_abajo[k] * LH_A_M3S))
    return RamaDimensionada(tuberia, reducciones, velocidad, not suficiente)


# ------------------------------------------------------------------ subunidad


def caudal_nominal(conexion) -> float:
    return sum(lat.numero_emisores * lat.emisor.caudal_nominal_lh for lat in conexion.laterales)


def ramas_de(conexiones, distancia_entrada_m):
    """{sentido: [(distancia desde la válvula, caudal nominal)]}, como en `subunidad_desde_conexiones`."""
    ramas = {}
    for sentido in (1, -1):
        propias = [((c.distancia_m - distancia_entrada_m) * sentido, caudal_nominal(c)) for c in conexiones
                   if (c.distancia_m - distancia_entrada_m) * sentido > 0
                   or (sentido == 1 and c.distancia_m == distancia_entrada_m)]
        if propias:
            ramas[sentido] = sorted(propias)
    return ramas


def dimensionar_por_velocidad(conexiones, distancia_entrada_m, tuberias, criterio: CriterioVelocidad,
                              costo=costo_relativo) -> Dict[int, RamaDimensionada]:
    resultado = {}
    for sentido, puntos in ramas_de(conexiones, distancia_entrada_m).items():
        resultado[sentido] = dimensionar_rama([d for d, _ in puntos], [q for _, q in puntos], tuberias,
                                              criterio, costo)
    return resultado


def disenar_por_velocidad(construir: Callable, conexiones, distancia_entrada_m, tuberias, criterio: CriterioVelocidad,
                          criterios, presion_entrada_m=None, costo=costo_relativo) -> Diseno:
    """Dimensiona el portalateral por velocidad y calcula la subunidad.

    `construir(por_rama)` debe devolver la Subunidad, con por_rama = {sentido: (tubería, reducciones)}.
    Con `criterio.ajustar_variacion`, si la subunidad no cumple los criterios (variación de caudal,
    emisores fuera de rango…) se baja la velocidad máxima de a 0.1 m/s y se repite.
    """
    if not tuberias:
        raise ValueError("No hay tuberías en la serie elegida para el portalateral.")
    tuberias = sorted(tuberias, key=lambda t: t.diametro_interior_mm)
    avisos = []
    velocidad = criterio.velocidad_max_ms
    actual = criterio
    while True:
        ramas = dimensionar_por_velocidad(conexiones, distancia_entrada_m, tuberias, actual, costo)
        por_rama = {s: (r.tuberia, r.reducciones) for s, r in ramas.items()}
        subunidad = construir(por_rama)
        entrada = max((r.tuberia for r in ramas.values()), key=clave_economica)
        evaluacion = _evaluar(subunidad, entrada, criterios, None, presion_entrada_m)
        if not criterio.ajustar_variacion or evaluacion.cumple:
            break
        motivos_velocidad = [m for m in evaluacion.motivos if m.startswith("velocidad")]
        if evaluacion.resultado is not None and motivos_velocidad == evaluacion.motivos:
            break  # solo falla la velocidad: bajar la velocidad de diseño no lo arregla
        if all(r.tuberia is tuberias[-1] and not r.reducciones for r in ramas.values()):
            break  # ya es la mayor tubería en todo el portalateral
        nueva = round(velocidad - PASO_AJUSTE_MS, 6)
        if nueva < VELOCIDAD_MINIMA_AJUSTE_MS - 1e-9:
            break
        velocidad = nueva
        actual = CriterioVelocidad(velocidad, criterio.diametros_max, criterio.tramo_min_m, False)

    if velocidad < criterio.velocidad_max_ms - 1e-9:
        avisos.append(f"Para cumplir los criterios de la subunidad se dimensionó con {velocidad:.1f} m/s "
                      f"en lugar de {criterio.velocidad_max_ms:g} m/s.")
    if any(r.insuficiente for r in ramas.values()):
        avisos.append(f"Ni la mayor tubería de la serie ({tuberias[-1].nombre}) baja de "
                      f"{actual.velocidad_max_ms:g} m/s en la entrada: elija una serie con diámetros mayores, "
                      "mueva la válvula al centro o subdivida el lote.")
    if presion_entrada_m is None:
        resultado = subunidad.presion_entrada_requerida(None, detallado=True)
    else:
        resultado = subunidad.simular(presion_entrada_m, detallado=True)
    motivos = incumplimientos(resultado, criterios, entrada)
    if motivos and criterio.ajustar_variacion and not any(r.insuficiente for r in ramas.values()):
        avisos.append("Incluso con los diámetros mayores la subunidad no cumple: revise los laterales, el "
                      "emisor o el tamaño del lote.")
    principal = max(ramas.values(), key=lambda r: clave_economica(r.tuberia))
    return Diseno(subunidad, resultado, entrada, [evaluacion], 0 if evaluacion.cumple else None, avisos, True,
                  list(principal.reducciones))
