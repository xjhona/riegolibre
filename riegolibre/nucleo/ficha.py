"""Fichas de información de un objeto del diseño (lateral, portalateral, tubería, válvula, bomba).

Dan el mismo tipo de datos que «Object Info» de IRRICAD: coordenadas, longitud, ángulo,
tubería y una tabla con presiones, pérdida de carga, desnivel, caudal y velocidad. Son
funciones de texto sin dependencias de QGIS; la lectura de las capas está en
`integracion/info_objeto.py`.

Convenciones: presiones y pérdidas en m; desnivel en m positivo si el terreno sube en el
sentido del flujo; caudales de laterales en L/h y de portalaterales, tuberías y válvulas
en m³/h; velocidad en m/s.
"""

import math
from dataclasses import dataclass
from typing import Sequence, Tuple

SIN_DATO = "—"
ANCHO = 120


@dataclass
class Ficha:
    titulo: str
    texto: str


def numero(valor, decimales=2):
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return SIN_DATO
    return f"{valor:.{decimales}f}"


def angulo_grados(p1, p2):
    """Ángulo de la línea P1→P2, antihorario desde el eje x, entre 0 y 360°."""
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0])) % 360.0


def _punto(etiqueta, p):
    return f"{etiqueta}: x = {p[0]:.2f} m, y = {p[1]:.2f} m"


def _geometria(p1, p2, longitud):
    return [_punto("P1", p1), _punto("P2", p2),
            f"Longitud = {longitud:.2f} m,  Ángulo = {angulo_grados(p1, p2):.2f} °"]


def tabla(columnas: Sequence[Tuple[str, str]], filas: Sequence[Tuple[str, Sequence]], ancho_etiqueta=None):
    """Tabla de texto de ancho fijo.

    columnas: [(título, unidad)]. filas: [(etiqueta, [valores ya formateados])].
    """
    ancho_etiqueta = ancho_etiqueta or max([len(e) for e, _ in filas] + [8])
    anchos = []
    for i, (titulo, unidad) in enumerate(columnas):
        anchos.append(max([len(titulo), len(unidad)] + [len(valores[i]) for _, valores in filas]) + 2)
    regla = "-" * min(ANCHO, ancho_etiqueta + sum(anchos) + 2)
    lineas = [regla,
              " " * ancho_etiqueta + "".join(t.rjust(a) for (t, _), a in zip(columnas, anchos)),
              " " * ancho_etiqueta + "".join(f"({u})".rjust(a) if u else " " * a
                                              for (_, u), a in zip(columnas, anchos)),
              regla]
    for etiqueta, valores in filas:
        lineas.append(etiqueta.ljust(ancho_etiqueta) + "".join(v.rjust(a) for v, a in zip(valores, anchos)))
    lineas.append("=" * len(regla))
    return lineas


def _m3h(lh):
    return None if lh is None else lh / 1000.0


# ------------------------------------------------------------------ lateral


def ficha_lateral(d) -> Ficha:
    """d: capa, id, p1, p2, longitud, subunidad, conexion, dist_porta, tuberia, emisor, emisores,
    p_entrada, p_final, perdida_m, desnivel_m, caudal_lh, velocidad, p_min, p_max, q_min, q_max,
    var_caudal, fuera_rango (los datos que falten se muestran con «—»)."""
    texto = ["LATERAL · polilínea 2D", f"Capa = {d['capa']},  Id = {d['id']}"]
    texto += _geometria(d["p1"], d["p2"], d["longitud"])
    texto.append("")
    if d.get("subunidad"):
        posicion = (f",  conexión n.º {d['conexion'] + 1} a {d['dist_porta']:.2f} m del inicio del portalateral"
                    if d.get("conexion") is not None and d.get("dist_porta") is not None else "")
        texto.append(f"Subunidad = {d['subunidad']}{posicion}")
    texto.append(f"Tubería = {d.get('tuberia') or SIN_DATO}")
    texto.append(f"Emisor = {d.get('emisor') or SIN_DATO}  ({d.get('emisores') or SIN_DATO} emisores)")
    caudal = d.get("caudal_lh")
    if caudal is not None and d["longitud"] > 0:
        texto.append(f"Caudal por cada 100 m = {caudal / d['longitud'] * 100:.2f} L/h")
    texto.append("")
    texto += tabla(
        [("Presión P1", "m"), ("Presión P2", "m"), ("Pérdida", "m"), ("Desnivel", "m"),
         ("Caudal entrada", "L/h"), ("Velocidad", "m/s")],
        [("Lateral", [numero(d.get("p_entrada")), numero(d.get("p_final")), numero(d.get("perdida_m")),
                      numero(d.get("desnivel_m")), numero(caudal, 1), numero(d.get("velocidad"))])])
    texto.append("P2 es la presión en el último emisor. Pérdida = presión P1 − presión P2 − desnivel.")
    texto.append("")
    texto.append("Emisores del lateral")
    texto.append(f"  Presión mín. / máx. = {numero(d.get('p_min'))} / {numero(d.get('p_max'))} m")
    texto.append(f"  Caudal mín. / máx. = {numero(d.get('q_min'), 3)} / {numero(d.get('q_max'), 3)} L/h")
    texto.append(f"  Variación de caudal = {numero(d.get('var_caudal'), 1)} %,  "
                 f"emisores fuera de rango = {d.get('fuera_rango') if d.get('fuera_rango') is not None else SIN_DATO}")
    return Ficha(f"Lateral {d['id']} · {d.get('subunidad') or d['capa']}", "\n".join(texto))


# ------------------------------------------------------- tramo de portalateral


def ficha_tramo_portalateral(d) -> Ficha:
    """d: capa, id, p1, p2, longitud, subunidad, rama, desde_m, hasta_m, tuberia, p_inicio, p_fin,
    perdida_m, desnivel_m, caudal_lh, caudal_sale_lh, velocidad."""
    texto = ["PORTALATERAL · línea 2D", f"Capa = {d['capa']},  Id = {d['id']}"]
    texto += _geometria(d["p1"], d["p2"], d["longitud"])
    texto.append("")
    if d.get("subunidad"):
        texto.append(f"Subunidad = {d['subunidad']},  rama = {d.get('rama') or SIN_DATO}")
    texto.append(f"Posición en el portalateral = de {numero(d.get('desde_m'), 1)} a {numero(d.get('hasta_m'), 1)} m "
                 "(el flujo va de P1 a P2)")
    texto.append(f"Tubería = {d.get('tuberia') or SIN_DATO}")
    texto.append("")
    texto += tabla(
        [("Presión P1", "m"), ("Presión P2", "m"), ("Pérdida", "m"), ("Desnivel", "m"),
         ("Caudal entrada", "m³/h"), ("Caudal salida", "m³/h"), ("Velocidad", "m/s")],
        [("Tramo", [numero(d.get("p_inicio")), numero(d.get("p_fin")), numero(d.get("perdida_m")),
                    numero(d.get("desnivel_m")), numero(_m3h(d.get("caudal_lh"))),
                    numero(_m3h(d.get("caudal_sale_lh"))), numero(d.get("velocidad"))])])
    texto.append("Pérdida = presión P1 − presión P2 − desnivel. La diferencia entre el caudal de entrada y el de "
                 "salida es lo que toman los laterales conectados al final del tramo.")
    return Ficha(f"Portalateral · {d.get('subunidad') or d['capa']}", "\n".join(texto))


# ------------------------------------------------------------ tubería de la red


def ficha_tramo_red(d) -> Ficha:
    """d: capa, id, p1, p2, longitud, tuberia, dn_mm, pn_m, j_m100, desnivel_m, observ, turnos
    (lista de [turno, p_inicio, p_fin, perdida_m, caudal_lh, velocidad]; vacía si no se calculó)."""
    texto = ["TUBERÍA DE LA RED PRINCIPAL · línea 2D", f"Capa = {d['capa']},  Id = {d['id']}"]
    texto += _geometria(d["p1"], d["p2"], d["longitud"])
    texto.append("")
    texto.append(f"Tubería = {d.get('tuberia') or SIN_DATO}")
    texto.append(f"Presión nominal = {numero(d.get('pn_m'), 1)} m,  desnivel P1→P2 = {numero(d.get('desnivel_m'))} m")
    if d.get("observ"):
        texto.append(f"Observaciones = {d['observ']}")
    texto.append("")
    filas = [(f"Turno {int(t[0])}", [numero(t[1]), numero(t[2]), numero(t[3]), numero(d.get("desnivel_m")),
                                      numero(_m3h(t[4])), numero(t[5])])
             for t in d.get("turnos") or []]
    if filas:
        texto += tabla([("Presión P1", "m"), ("Presión P2", "m"), ("Pérdida", "m"), ("Desnivel", "m"),
                        ("Caudal", "m³/h"), ("Velocidad", "m/s")], filas)
        texto.append("La pérdida incluye la fricción y las pérdidas menores. El flujo va de P1 a P2; "
                     "en los turnos en que el tramo no lleva agua el caudal es cero.")
    else:
        texto.append("Sin resultados por turno: vuelva a calcular la red principal.")
    return Ficha(f"Tubería {d['id']} · red principal", "\n".join(texto))


# ------------------------------------------------------------------- válvula


def ficha_valvula(d) -> Ficha:
    """d: nombre, p1, cota, capas (lista de nombres), subunidad (dict opcional con presion_m, caudal_lh,
    tuberia, area_m2, laterales, emisores, variacion, uniformidad, cumple), turno (o None) y turnos
    (lista de [turno, p_aguas_arriba, requerida, perdida_valvula, caudal_lh]; vacía si no se corrió la red)."""
    texto = ["VÁLVULA · símbolo 2D", f"Capa = {', '.join(d['capas'])}", _punto("P1", d["p1"]),
             f"Cota = {numero(d.get('cota'))} m", f"Nombre = {d['nombre']}"]
    s = d.get("subunidad")
    if s:
        texto.append("")
        texto.append("Subunidad diseñada")
        texto.append(f"  Portalateral = {s.get('tuberia') or SIN_DATO}")
        texto.append(f"  Presión necesaria a la entrada = {numero(s.get('presion_m'))} m,  "
                     f"caudal = {numero(_m3h(s.get('caudal_lh')), 2)} m³/h")
        if s.get("area_m2"):
            texto.append(f"  Área = {s['area_m2'] / 10000:.3f} ha,  laterales = {s.get('laterales', SIN_DATO)},  "
                         f"emisores = {s.get('emisores', SIN_DATO)}")
        if s.get("variacion") is not None:
            texto.append(f"  Variación de caudal = {s['variacion'] * 100:.1f} %,  "
                         f"uniformidad de emisión = {numero(s.get('uniformidad'), 1)} %,  "
                         f"{'cumple los criterios' if s.get('cumple') else 'NO cumple los criterios'}")
    texto.append("")
    filas = [(f"Turno {int(t[0])}", [numero(t[1]), numero(t[2]), numero(t[3]), numero(_m3h(t[4]))])
             for t in d.get("turnos") or []]
    if filas:
        texto.append(f"Turno de riego asignado = {d.get('turno') if d.get('turno') is not None else SIN_DATO}")
        texto += tabla([("Presión aguas arriba", "m"), ("Requerida", "m"), ("Pérdida válvula", "m"),
                        ("Caudal", "m³/h")], filas)
        texto.append("Requerida = presión que necesita la subunidad aguas abajo. La válvula solo tiene caudal "
                     "en su turno.")
    else:
        texto.append("Las presiones por turno aparecen cuando se asignan los turnos de riego y se calcula "
                     "la red principal («Red principal y bomba»).")
    return Ficha(f"Válvula {d['nombre']}", "\n".join(texto))


# --------------------------------------------------------------------- bomba


def ficha_bomba(d) -> Ficha:
    """d: capa, p1, cota, turno, caudal_ls, cdt_m, potencia_kw, potencia_hp."""
    texto = ["BOMBA / CABEZAL · símbolo 2D", f"Capa = {d['capa']}", _punto("P1", d["p1"]),
             f"Cota = {numero(d.get('cota'))} m", "",
             "Punto de diseño (turno crítico)",
             f"  Turno = {d.get('turno') if d.get('turno') is not None else SIN_DATO}",
             f"  Caudal = {numero(d.get('caudal_ls'), 3)} L/s ({numero(d.get('caudal_ls') * 3.6 if d.get('caudal_ls') is not None else None, 2)} m³/h)",
             f"  Carga dinámica total = {numero(d.get('cdt_m'))} m",
             f"  Potencia = {numero(d.get('potencia_kw'))} kW ({numero(d.get('potencia_hp'))} HP)"]
    return Ficha("Bomba", "\n".join(texto))

