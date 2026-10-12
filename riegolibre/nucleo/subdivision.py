"""Subdivisión de un lote en sub-bloques (una válvula cada uno), como la ventana «Subdivision» de IRRICAD.

Con los laterales girados hacia +x (ver `nucleo.bloque`):

- las **franjas** («slices») parten el lote con rectas paralelas a los laterales: agrupan hileras
  enteras, de modo que ningún lateral queda cortado;
- los **cortes** («cuts») lo parten con rectas perpendiculares a los laterales: acortan los laterales.

Entre dos partes puede quedar un hueco (un camino) sin regar. En modo automático, los cortes se ponen
para que ningún lateral pase de una longitud máxima, y las franjas para que cada sub-bloque no pase de
un caudal o un área, o para obtener un número de sub-bloques; las franjas reparten el caudal por igual.

El resultado son rectángulos en coordenadas del terreno; el sub-bloque es la intersección de cada uno
con el lote (eso lo hace quien llama, por ejemplo con QGIS).
"""

import math
from dataclasses import dataclass
from typing import List, Sequence

from .bloque import PORTA_CENTRO, ParametrosBloque, _Plano, _desplazamientos, ejes_de_hileras
from .trazado import Anillo, Punto

NINGUNO, DISTANCIA, NUMERO, HILERAS = "ninguno", "distancia", "numero", "hileras"
AUTO_CAUDAL, AUTO_AREA, AUTO_NUMERO = "caudal", "area", "numero"
LEJOS = math.inf  # los rectángulos de los extremos se alargan hasta cubrir el borde del lote


@dataclass(frozen=True)
class ParametrosSubdivision:
    automatica: bool = False
    longitud_max_lateral_m: float = 100.0  # automática: los cortes dejan laterales de este largo o menos
    criterio: str = AUTO_CAUDAL  # automática: cómo se reparten las franjas
    caudal_max: float = 0.0  # con AUTO_CAUDAL, en las unidades de `ParametrosBloque.caudal`
    area_max_m2: float = 0.0  # con AUTO_AREA
    numero: int = 1  # con AUTO_NUMERO: sub-bloques en total
    franjas: str = NINGUNO  # NINGUNO, DISTANCIA (m), NUMERO o HILERAS
    franjas_valor: float = 0.0
    franjas_hueco: float = 0.0  # m; con HILERAS, en hileras
    cortes: str = NINGUNO  # NINGUNO, DISTANCIA (m) o NUMERO
    cortes_valor: float = 0.0
    cortes_hueco_m: float = 0.0

    def __post_init__(self):
        if self.franjas not in (NINGUNO, DISTANCIA, NUMERO, HILERAS):
            raise ValueError(f"Tipo de franjas no válido: {self.franjas!r}.")
        if self.cortes not in (NINGUNO, DISTANCIA, NUMERO):
            raise ValueError(f"Tipo de cortes no válido: {self.cortes!r}.")
        if self.criterio not in (AUTO_CAUDAL, AUTO_AREA, AUTO_NUMERO):
            raise ValueError(f"Criterio no válido: {self.criterio!r}.")
        if self.franjas_hueco < 0 or self.cortes_hueco_m < 0:
            raise ValueError("Los huecos no pueden ser negativos.")
        if self.automatica:
            if self.longitud_max_lateral_m <= 0:
                raise ValueError("La longitud máxima de lateral debe ser mayor que cero.")
            if self.criterio == AUTO_CAUDAL and self.caudal_max <= 0:
                raise ValueError("El caudal máximo por sub-bloque debe ser mayor que cero.")
            if self.criterio == AUTO_AREA and self.area_max_m2 <= 0:
                raise ValueError("El área máxima por sub-bloque debe ser mayor que cero.")
            if self.criterio == AUTO_NUMERO and self.numero < 1:
                raise ValueError("El número de sub-bloques debe ser al menos 1.")
        else:
            if self.franjas != NINGUNO and self.franjas_valor <= 0:
                raise ValueError("El valor de las franjas debe ser mayor que cero.")
            if self.cortes != NINGUNO and self.cortes_valor <= 0:
                raise ValueError("El valor de los cortes debe ser mayor que cero.")


@dataclass
class SubBloque:
    anillo: List[Punto]  # rectángulo en coordenadas del terreno (cortarlo con el lote)
    hileras: int
    caudal: float  # estimado, en las unidades de `ParametrosBloque.caudal`
    area_m2: float  # regada, estimada


def _piezas_x(x_min, x_max, modo, valor, hueco, cantidad=None):
    """Intervalos (x0, x1) a lo largo de los laterales."""
    ancho = x_max - x_min
    if cantidad is None:
        if modo == DISTANCIA:
            cantidad = max(1, math.ceil((ancho + hueco) / (valor + hueco) - 1e-9))
        elif modo == NUMERO:
            cantidad = max(1, int(round(valor)))
        else:
            cantidad = 1
    if cantidad == 1:
        return [(-LEJOS, LEJOS)]
    if modo == DISTANCIA:
        largo = valor
    else:
        largo = (ancho - (cantidad - 1) * hueco) / cantidad
        if largo <= 0:
            raise ValueError("Los huecos entre los cortes no dejan espacio para los sub-bloques.")
    piezas = []
    for i in range(cantidad):
        x0 = x_min + i * (largo + hueco)
        x1 = x0 + largo
        piezas.append((-LEJOS if i == 0 else x0, LEJOS if i == cantidad - 1 else x1))
    return piezas


def _repartir(pesos, partes):
    """Grupos contiguos de índices con pesos parecidos (cortes donde el acumulado pasa por k/partes)."""
    n = len(pesos)
    partes = max(1, min(partes, n))
    total = sum(pesos)
    if partes == 1 or total <= 0:
        return [list(range(n))]
    limites, acumulado, k = [], 0.0, 1
    for i, p in enumerate(pesos):
        antes = acumulado
        acumulado += p
        while k < partes and acumulado >= total * k / partes:
            objetivo = total * k / partes
            corte = i + 1 if (acumulado - objetivo) <= (objetivo - antes) else i
            limites.append(corte)
            k += 1
    grupos, inicio = [], 0
    for corte in limites + [n]:
        if corte > inicio:
            grupos.append(list(range(inicio, corte)))
            inicio = corte
    return grupos


def _quitar_huecos(grupos, hueco_hileras):
    """Deja sin regar las `hueco_hileras` primeras hileras de cada grupo, salvo del primero."""
    if hueco_hileras <= 0:
        return grupos
    resultado = [grupos[0]]
    for g in grupos[1:]:
        resto = g[hueco_hileras:]
        if resto:
            resultado.append(resto)
    return resultado


def _por_cantidad(n, por_grupo, hueco):
    grupos, i = [], 0
    while i < n:
        grupos.append(list(range(i, min(n, i + por_grupo))))
        i += por_grupo + hueco
    return grupos


def subdividir(anillos: Sequence[Anillo], bloque: ParametrosBloque, angulo_deg: float,
               params: ParametrosSubdivision) -> List[SubBloque]:
    """Rectángulos de los sub-bloques del lote, para los laterales en la dirección dada."""
    plano = _Plano(anillos, angulo_deg)
    sep = bloque.separacion_m
    ejes = ejes_de_hileras(plano.y_min, plano.y_max, sep, bloque.costados)
    if not ejes:
        raise ValueError("No caben hileras en el lote con esta separación y estos costados.")
    desplazamientos = _desplazamientos(bloque)
    tramos = [[t for d in desplazamientos for t in plano.tramos(y + d, bloque.cabecera_m)] for y in ejes]

    x_min = min((t[0] for ts in tramos for t in ts), default=plano.x_min)
    x_max = max((t[1] for ts in tramos for t in ts), default=plano.x_max)
    if params.automatica:
        factor = 2 if bloque.portalateral == PORTA_CENTRO else 1
        cantidad = max(1, math.ceil((x_max - x_min) / (factor * params.longitud_max_lateral_m) - 1e-9))
        piezas = _piezas_x(x_min, x_max, NUMERO, cantidad, params.cortes_hueco_m, cantidad)
    else:
        piezas = _piezas_x(x_min, x_max, params.cortes, params.cortes_valor, params.cortes_hueco_m)

    def medidas(x0, x1):
        largos, caudales = [], []
        for ts in tramos:
            partes = [min(b, x1) - max(a, x0) for a, b in ts if min(b, x1) > max(a, x0)]
            largos.append(sum(partes))
            caudales.append(sum(bloque.caudal(p) for p in partes))
        return largos, caudales

    por_pieza = [(x0, x1) + medidas(x0, x1) for x0, x1 in piezas]
    caudal_total = sum(sum(c) for *_, c in por_pieza)
    hueco_hileras = (int(round(params.franjas_hueco)) if params.franjas == HILERAS
                     else int(round(params.franjas_hueco / sep)))

    resultado = []
    for x0, x1, largos, caudales in por_pieza:
        con_riego = [i for i, largo in enumerate(largos) if largo > 0]
        if not con_riego:
            continue
        primera, ultima = con_riego[0], con_riego[-1]
        indices = list(range(primera, ultima + 1))
        n = len(indices)
        if params.automatica:
            caudal = sum(caudales)
            if params.criterio == AUTO_CAUDAL:
                partes = math.ceil(caudal / params.caudal_max - 1e-9)
                pesos = [caudales[i] for i in indices]
            elif params.criterio == AUTO_AREA:
                area = sum(largos) * sep / len(desplazamientos)
                partes = math.ceil(area / params.area_max_m2 - 1e-9)
                pesos = [largos[i] for i in indices]
            else:
                partes = max(1, round(params.numero * caudal / caudal_total)) if caudal_total else 1
                pesos = [caudales[i] for i in indices]
            grupos = _quitar_huecos(_repartir(pesos, partes), hueco_hileras)
        elif params.franjas == DISTANCIA:
            grupos = _por_cantidad(n, max(1, int(round(params.franjas_valor / sep))), hueco_hileras)
        elif params.franjas == HILERAS:
            grupos = _por_cantidad(n, max(1, int(round(params.franjas_valor))), hueco_hileras)
        elif params.franjas == NUMERO:
            grupos = _quitar_huecos(_repartir([1.0] * n, int(round(params.franjas_valor))), hueco_hileras)
        else:
            grupos = [list(range(n))]

        for j, grupo in enumerate(grupos):
            filas = [indices[i] for i in grupo]
            y0 = -LEJOS if j == 0 else ejes[filas[0]] - sep / 2
            y1 = LEJOS if j == len(grupos) - 1 else ejes[filas[-1]] + sep / 2
            esquinas = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            # Los rectángulos de los extremos se recortan a la caja del lote (más un metro).
            esquinas = [(min(max(x, plano.x_min - 1), plano.x_max + 1), min(max(y, plano.y_min - 1), plano.y_max + 1))
                        for x, y in esquinas]
            resultado.append(SubBloque(
                [plano.al_terreno(p) for p in esquinas], len(filas), sum(caudales[i] for i in filas),
                sum(largos[i] for i in filas) * sep / len(desplazamientos)))
    if not resultado:
        raise ValueError("La subdivisión no deja ningún sub-bloque con laterales.")
    return resultado

