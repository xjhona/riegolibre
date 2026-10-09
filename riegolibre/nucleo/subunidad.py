"""Subunidad de riego: uno o dos portalaterales alimentados desde la misma válvula.

Con la entrada en un extremo hay un solo portalateral; con la entrada en el
centro hay dos ramas que reciben la misma presión (una suele ir en subida y la
otra en bajada). También incluye la selección automática del diámetro del
portalateral según los criterios de diseño, uniforme o telescópico.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .hidraulica import PresionInsuficiente, interpolar_perfil, resolver_creciente
from .lateral import CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA
from .portalateral import (ConexionLateral, EstadisticasEmisores, Portalateral,
                           ResultadoPortalateral, corregir_presion_minima,
                           criterio_por_defecto, presion_minima_requerida)
from .tuberias import clave_economica

ENTRADA_EXTREMO = "extremo"
ENTRADA_CENTRO = "centro"


@dataclass
class ResultadoSubunidad(EstadisticasEmisores):
    ramas: List[ResultadoPortalateral]
    presion_entrada_m: float

    def _unir(self, atributo):
        return [v for rama in self.ramas for v in getattr(rama, atributo)]

    @property
    def caudales_lh(self):
        return self._unir("caudales_lh")

    @property
    def h_min_m(self):
        return self._unir("h_min_m")

    @property
    def h_max_m(self):
        return self._unir("h_max_m")

    @property
    def q_min_lh(self):
        return self._unir("q_min_lh")

    @property
    def q_max_lh(self):
        return self._unir("q_max_lh")

    @property
    def fuera_de_rango(self):
        return self._unir("fuera_de_rango")

    @property
    def numero_emisores(self):
        return sum(r.numero_emisores for r in self.ramas)

    @property
    def cv(self):
        return max(r.cv for r in self.ramas)

    @property
    def laterales(self):
        if any(r.laterales is None for r in self.ramas):
            return None
        return self._unir("laterales")

    @property
    def velocidad_max_ms(self):
        return max(r.velocidad_max_ms or r.velocidad_entrada_ms for r in self.ramas)

    @property
    def secciones(self):
        """Tramos de una misma tubería de todas las ramas (vacío si no se calcularon)."""
        return self._unir("secciones")

    @property
    def perdida_friccion_max_m(self):
        return max(r.perdida_friccion_m for r in self.ramas)

    @property
    def presion_max_portalateral_m(self):
        return max([self.presion_entrada_m] + self._unir("presiones_m"))


@dataclass
class Subunidad:
    ramas: List[Portalateral]

    @property
    def laterales(self):
        return [lat for rama in self.ramas for lat in rama.laterales]

    @property
    def numero_emisores(self):
        return sum(rama.numero_emisores for rama in self.ramas)

    def simular(self, presion_entrada_m, detallado=True):
        ramas = [rama.simular(presion_entrada_m, detallado) for rama in self.ramas]
        return ResultadoSubunidad(ramas, presion_entrada_m)

    def presion_entrada_requerida(self, criterio=None, detallado=True):
        criterio = criterio or criterio_por_defecto(self.laterales)
        if len(self.ramas) == 1:
            r = self.ramas[0].presion_entrada_requerida(criterio, detallado)
            return ResultadoSubunidad([r], r.presion_entrada_m)

        if criterio == CRITERIO_PRESION_MINIMA:
            # La rama más exigente fija la presión; la otra recibe algo más.
            presion = max(rama.presion_entrada_requerida(criterio, detallado=False).presion_entrada_m
                          for rama in self.ramas)
            r = self.simular(presion, detallado)
            if detallado:
                r = corregir_presion_minima(r, presion_minima_requerida(self.laterales), self.simular)
            return r

        if criterio == CRITERIO_CAUDAL_MEDIO:
            objetivo = sum(lat.emisor.caudal_nominal_lh * lat.numero_emisores for lat in self.laterales)
            minimo = max(rama.simular_desde_final(0.0).presion_entrada_m for rama in self.ramas)

            def caudal_total(h):
                return sum(rama.simular(h, detallado=False).caudal_total_lh for rama in self.ramas)

            presion = resolver_creciente(caudal_total, objetivo, minimo, max(minimo + 10.0, 10.0),
                                         tolerancia=1e-3)
            return self.simular(presion, detallado)

        raise ValueError(f"Criterio desconocido: {criterio!r}")


def _perfil_rama(perfil, entrada, sentido):
    """Perfil visto desde la entrada: sentido +1 hacia el final, -1 hacia el inicio."""
    if perfil is None:
        return None
    puntos = [(0.0, interpolar_perfil(perfil, entrada))]
    for x, z in perfil:
        d = (x - entrada) * sentido
        if d > 0:
            puntos.append((d, z))
    if len(puntos) < 2:
        puntos.append((1.0, puntos[0][1]))
    return puntos


def subunidad_desde_conexiones(tuberia, conexiones, distancia_entrada_m=0.0, pendiente=0.0,
                               perfil=None, metodo="darcy", reducciones=()):
    """Subunidad a partir de conexiones medidas desde el inicio del portalateral.

    La válvula está a distancia_entrada_m del inicio; las conexiones situadas
    después forman la rama que avanza (sentido +1) y las situadas antes, la que
    retrocede (sentido -1). Cada conexión puede llevar laterales distintos.
    reducciones: portalateral telescópico, con distancias medidas desde la válvula
    (valen para las dos ramas).
    """
    if not conexiones:
        raise ValueError("La subunidad no tiene laterales.")
    ramas = []
    for sentido in (1, -1):
        propias = [ConexionLateral((c.distancia_m - distancia_entrada_m) * sentido, c.laterales)
                   for c in conexiones
                   if (c.distancia_m - distancia_entrada_m) * sentido > 0
                   or (sentido == 1 and c.distancia_m == distancia_entrada_m)]
        if propias:
            ramas.append(Portalateral(tuberia, propias, pendiente=pendiente * sentido,
                                      perfil=_perfil_rama(perfil, distancia_entrada_m, sentido),
                                      metodo=metodo, sentido=sentido, reducciones=reducciones))
    return Subunidad(ramas)


def subunidad_rectangular(tuberia, lateral_a, lateral_b, separacion_laterales_m, numero_laterales,
                          posicion_entrada=ENTRADA_EXTREMO, pendiente=0.0, perfil=None,
                          metodo="darcy", distancia_primera_conexion_m=None, reducciones=()):
    """Subunidad rectangular con laterales equidistantes a uno o ambos lados.

    - lateral_a / lateral_b: laterales de cada lado del portalateral (uno puede ser None).
      Si el terreno tiene pendiente transversal, cada lado lleva su propia pendiente.
    - pendiente / perfil: terreno a lo largo del portalateral, desde su inicio.
    - posicion_entrada: "extremo" (al inicio del portalateral) o "centro".
    - reducciones: portalateral telescópico (distancias desde la válvula).
    """
    laterales = [lat for lat in (lateral_a, lateral_b) if lat is not None]
    if not laterales:
        raise ValueError("Indique al menos un lateral.")
    if numero_laterales < 1:
        raise ValueError("La subunidad necesita al menos una posición de laterales.")
    if distancia_primera_conexion_m is None:
        distancia_primera_conexion_m = separacion_laterales_m / 2
    conexiones = [ConexionLateral(distancia_primera_conexion_m + i * separacion_laterales_m, laterales)
                  for i in range(numero_laterales)]
    if posicion_entrada == ENTRADA_EXTREMO:
        entrada = 0.0
    elif posicion_entrada == ENTRADA_CENTRO:
        entrada = (conexiones[-1].distancia_m + distancia_primera_conexion_m) / 2
    else:
        raise ValueError(f"Posición de entrada desconocida: {posicion_entrada!r}")
    return subunidad_desde_conexiones(tuberia, conexiones, entrada, pendiente=pendiente,
                                      perfil=perfil, metodo=metodo, reducciones=reducciones)


# ------------------------------------------------------------------ selección


@dataclass
class CriteriosDiseno:
    variacion_caudal_max: float = 0.10  # en toda la subunidad
    velocidad_max_ms: float = 2.0  # en el portalateral
    presion_entrada_max_m: Optional[float] = None


def incumplimientos(resultado, criterios, tuberia_portalateral=None):
    """Lista de motivos por los que la subunidad no cumple (vacía si cumple)."""
    motivos = []
    if resultado.variacion_caudal > criterios.variacion_caudal_max + 1e-9:
        motivos.append(f"variación de caudal {resultado.variacion_caudal:.1%} "
                       f"> {criterios.variacion_caudal_max:.0%}")
    if resultado.hay_emisores_fuera_de_rango:
        motivos.append("emisores fuera del rango de compensación")
    if resultado.velocidad_max_ms > criterios.velocidad_max_ms + 1e-9:
        motivos.append(f"velocidad {resultado.velocidad_max_ms:.2f} m/s "
                       f"> {criterios.velocidad_max_ms:g} m/s")
    if (criterios.presion_entrada_max_m is not None
            and resultado.presion_entrada_m > criterios.presion_entrada_max_m + 1e-9):
        motivos.append(f"presión de entrada {resultado.presion_entrada_m:.1f} m "
                       f"> {criterios.presion_entrada_max_m:g} m")
    secciones = getattr(resultado, "secciones", None)
    if secciones:
        excedidas = {}
        for s in secciones:
            pn = s.tuberia.presion_nominal_m
            if pn and s.presion_max_m > pn:
                excedidas[s.tuberia.nombre] = pn
        for nombre, pn in excedidas.items():
            motivos.append(f"supera la presión nominal de la tubería ({pn:g} m)"
                           if len({s.tuberia.nombre for s in secciones}) == 1
                           else f"supera la presión nominal de {nombre} ({pn:g} m)")
    else:
        pn = getattr(tuberia_portalateral, "presion_nominal_m", None)
        if pn and resultado.presion_max_portalateral_m > pn:
            motivos.append(f"supera la presión nominal de la tubería ({pn:g} m)")
    return motivos


@dataclass
class EvaluacionDiametro:
    tuberia: object
    resultado: Optional[ResultadoSubunidad]
    motivos: List[str] = field(default_factory=list)

    @property
    def cumple(self):
        return self.resultado is not None and not self.motivos


def evaluar_diametros(construir: Callable, tuberias, criterios, criterio=None,
                      presion_entrada_m=None):
    """Evalúa cada tubería candidata para el portalateral (cálculo rápido, sin detalle).

    construir(tuberia) debe devolver la Subunidad con esa tubería en el portalateral.
    Si se da presion_entrada_m se evalúa con esa presión; si no, con la requerida.
    Devuelve (evaluaciones en orden de preferencia —ver clave_economica—, índice de
    la primera que cumple o None).
    """
    evaluaciones = [_evaluar(construir(tuberia), tuberia, criterios, criterio, presion_entrada_m)
                    for tuberia in sorted(tuberias, key=clave_economica)]
    elegida = next((i for i, e in enumerate(evaluaciones) if e.cumple), None)
    return evaluaciones, elegida


def _evaluar(subunidad, tuberia, criterios, criterio=None, presion_entrada_m=None):
    try:
        if presion_entrada_m is None:
            r = subunidad.presion_entrada_requerida(criterio, detallado=False)
        else:
            r = subunidad.simular(presion_entrada_m, detallado=False)
    except (PresionInsuficiente, ValueError) as error:
        return EvaluacionDiametro(tuberia, None, [str(error)])
    return EvaluacionDiametro(tuberia, r, incumplimientos(r, criterios, tuberia))


def _diametro(tuberia):
    return tuberia.diametro_nominal_mm or tuberia.diametro_interior_mm


def costo_relativo(tuberia):
    """Costo aproximado por metro: proporcional al área de la sección (material del tubo)."""
    return _diametro(tuberia) ** 2


def telescopizar(construir: Callable, tuberia, tuberias, criterios, diametros_max=2, criterio=None,
                 presion_entrada_m=None, costo=costo_relativo):
    """Reducciones del portalateral telescópico que empieza con la tubería dada.

    construir(tuberia, reducciones) debe devolver la Subunidad. Hacia el final del
    portalateral el caudal disminuye, así que allí basta una tubería menor. En cada
    paso se prueba cada tubería de menor diámetro para el tramo final y se busca el
    punto de cambio más cercano a la válvula que sigue cumpliendo todos los
    criterios (búsqueda binaria entre las conexiones). Se elige la combinación de
    menor costo y se repite hasta llegar a diametros_max tuberías o hasta que
    ninguna reducción cumpla. Devuelve [(distancia desde la válvula, tubería)].
    """
    base = construir(tuberia, ())
    longitudes = [rama.longitud_m for rama in base.ramas]
    # Puntos de cambio posibles: en las conexiones, sin contar el final del portalateral.
    posiciones = sorted({round(c.distancia_m, 6) for rama in base.ramas for c in rama.conexiones
                         if 1e-9 < c.distancia_m < max(longitudes) - 1e-9})

    def cumple(reducciones):
        return _evaluar(construir(tuberia, reducciones), tuberia, criterios, criterio,
                        presion_entrada_m).cumple

    def costo_total(reducciones):
        inicios = [0.0] + [d for d, _ in reducciones]
        tubos = [tuberia] + [t for _, t in reducciones]
        total = 0.0
        for i, t in enumerate(tubos):
            fin = inicios[i + 1] if i + 1 < len(inicios) else float("inf")
            total += costo(t) * sum(max(0.0, min(fin, largo) - inicios[i]) for largo in longitudes)
        return total

    reducciones, actual, inicio = [], tuberia, 0.0
    por_diametro = {}
    for t in sorted(tuberias, key=clave_economica):  # de la clase más baja a la más alta
        por_diametro.setdefault(_diametro(t), []).append(t)
    while len(reducciones) + 1 < diametros_max:
        opciones = [p for p in posiciones if p > inicio + 1e-9]
        mejor = None
        for d, clases in sorted(por_diametro.items()):
            if d >= _diametro(actual) or not opciones:
                continue
            # La clase más baja que cumple en el tramo final más corto posible.
            menor = next((t for t in clases if cumple(reducciones + [(opciones[-1], t)])), None)
            if menor is None:
                continue
            bajo, alto = -1, len(opciones) - 1  # opciones[alto] cumple
            while alto - bajo > 1:
                medio = (bajo + alto) // 2
                if cumple(reducciones + [(opciones[medio], menor)]):
                    alto = medio
                else:
                    bajo = medio
            prueba = reducciones + [(opciones[alto], menor)]
            if mejor is None or costo_total(prueba) < costo_total(mejor):
                mejor = prueba
        if mejor is None or costo_total(mejor) >= costo_total(reducciones):
            break
        reducciones = mejor
        inicio, actual = reducciones[-1]
    return reducciones


@dataclass
class Diseno:
    """Resultado de diseñar una subunidad (ver disenar_subunidad)."""
    subunidad: Subunidad
    resultado: ResultadoSubunidad
    tuberia: object  # la de la entrada del portalateral
    evaluaciones: List[EvaluacionDiametro]
    elegida: Optional[int]
    avisos: List[str]
    automatica: bool
    reducciones: list = field(default_factory=list)  # portalateral telescópico: [(distancia, tubería)]

    @property
    def telescopico(self):
        return bool(self.reducciones)


def disenar_subunidad(construir: Callable, tuberias, criterios, tuberia_fija=None,
                      presion_entrada_m=None, criterio=None, diametros_max=1):
    """Evalúa los diámetros, elige la tubería y calcula la subunidad en detalle.

    Con tuberia_fija=None se usa la menor tubería que cumple; si ninguna cumple,
    la de mayor diámetro (con un aviso).

    Con diametros_max > 1 el portalateral puede ser telescópico (ver telescopizar):
    la tubería elegida va en la entrada y hacia el final se reduce el diámetro.
    En ese caso construir debe aceptar construir(tuberia, reducciones).
    """
    if diametros_max > 1:
        construir_con = construir

        def construir(tuberia):  # noqa: F811 — misma subunidad, sin reducciones
            return construir_con(tuberia, ())
    evaluaciones, elegida = evaluar_diametros(construir, tuberias, criterios, criterio,
                                              presion_entrada_m)
    avisos = []
    if tuberia_fija is not None:
        tuberia = tuberia_fija
    elif elegida is not None:
        tuberia = evaluaciones[elegida].tuberia
    else:
        calculables = [e for e in evaluaciones if e.resultado is not None]
        if not calculables:
            raise ValueError("No se pudo calcular la subunidad con ninguna tubería: "
                             + evaluaciones[-1].motivos[0])
        mayor = calculables[-1]
        tuberia = mayor.tuberia
        avisos.append("Ningún diámetro del catálogo cumple todos los criterios; "
                      "se muestra el de mayor diámetro.")
        if mayor.resultado.variacion_caudal > criterios.variacion_caudal_max:
            avisos.append("Incluso con el mayor diámetro la variación de caudal no cumple: se debe a "
                          "los laterales o al desnivel del terreno, no al portalateral. Considere "
                          "emisores autocompensados, laterales más cortos o de mayor diámetro, "
                          "o dividir el bloque en más subunidades.")
    reducciones = []
    if diametros_max > 1 and (tuberia_fija is not None or elegida is not None):
        reducciones = telescopizar(construir_con, tuberia, tuberias, criterios, diametros_max, criterio,
                                   presion_entrada_m)
        subunidad = construir_con(tuberia, reducciones)
    else:
        subunidad = construir(tuberia)
    if presion_entrada_m is None:
        resultado = subunidad.presion_entrada_requerida(criterio, detallado=True)
    else:
        resultado = subunidad.simular(presion_entrada_m, detallado=True)
    return Diseno(subunidad, resultado, tuberia, evaluaciones, elegida, avisos, tuberia_fija is None,
                  reducciones)
