"""Memoria de cálculo: resúmenes de los resultados y documento para el cliente.

Los resúmenes son diccionarios sencillos que se pueden guardar como JSON (en las
capas de resultado del proyecto). memoria_html arma con ellos el documento, en
un HTML sencillo que entienden tanto los navegadores como QTextDocument (con el
que se exporta a PDF y ODT).
"""

import html
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .graficos import (dibujar_perfil_red, dibujar_perfil_subunidad, png,
                       puntos_perfil_subunidad, referencia_emisor)
from .materiales import resumen_por_categoria, total
from .red import bomba_critica, perfil_ruta_critica
from .subunidad import incumplimientos

VERSION_RESUMEN = 1
M_POR_BAR = 10.197
NOMBRES_METODO = {"darcy": "Darcy-Weisbach", "hazen": "Hazen-Williams"}
POTENCIAS_COMERCIALES_HP = (0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 5.5, 7.5, 10, 12.5, 15, 20, 25, 30, 40,
                            50, 60, 75, 100, 125, 150, 200, 250, 300)
MARGEN_MOTOR = 0.10  # margen de servicio sobre la potencia al eje


def potencia_comercial_hp(potencia_hp, margen=MARGEN_MOTOR):
    """Menor potencia comercial de motor que cubre la potencia al eje más el margen."""
    necesaria = potencia_hp * (1 + margen)
    return next((p for p in POTENCIAS_COMERCIALES_HP if p >= necesaria - 1e-9), None)


def _r(valor, decimales=3):
    return None if valor is None else round(valor, decimales)


def nombre_rama(numero_ramas, sentido):
    if numero_ramas == 1:
        return "única"
    return "hacia el final" if sentido > 0 else "hacia el inicio"


def descripcion_telescopico(diseno):
    """Tuberías del portalateral con sus distancias desde la válvula, p. ej. «A (0–38 m) → B (38–70 m)»."""
    largo = max(rama.longitud_m for rama in diseno.subunidad.ramas)
    inicios = [0.0] + [d for d, _ in diseno.reducciones]
    tubos = [diseno.tuberia] + [t for _, t in diseno.reducciones]
    fines = inicios[1:] + [largo]
    return " → ".join(f"{t.nombre} ({a:.1f}–{b:.1f} m)" for t, a, b in zip(tubos, inicios, fines))


# ------------------------------------------------------------------ avisos


def avisos_subunidad(diseno, criterios, tuberia_lateral, avisos=()):
    """Incumplimientos y avisos del diseño de una subunidad, como frases."""
    r = diseno.resultado
    lista = [m[0].upper() + m[1:] + "." for m in incumplimientos(r, criterios, diseno.tuberia)]
    lista += list(diseno.avisos) + list(avisos)
    presiones = [p for rama in r.ramas for p in rama.presiones_m]
    if tuberia_lateral.presion_nominal_m and max(presiones) > tuberia_lateral.presion_nominal_m:
        lista.append(f"La presión en la entrada de algunos laterales ({max(presiones):.1f} m) "
                     f"supera la nominal de la tubería lateral ({tuberia_lateral.presion_nominal_m:g} m).")
    return lista


def avisos_red(resultado, bombas, sin_dem=False):
    """Tramos que no cumplen y otros avisos del cálculo de la red principal."""
    avisos = list(resultado.avisos)
    for id_tramo, motivos in resultado.motivos.items():
        avisos.append(f"Tramo {id_tramo}: " + "; ".join(motivos) + ".")
    if sin_dem:
        avisos.append("Sin DEM: la red se calculó con el terreno plano.")
    critica = bomba_critica(bombas)
    caudal_max = max(b.caudal_lh for b in bombas)
    if len(bombas) > 1 and abs(caudal_max - critica.caudal_lh) > 1:
        avisos.append(f"El caudal máximo ({caudal_max / 3600:.2f} L/s) no coincide con el del turno "
                      "crítico: verifique la curva de la bomba en ambos puntos (ver la tabla de turnos).")
    return avisos


# --------------------------------------------------------------- resúmenes


def resumen_subunidad(nombre, diseno, criterios, metodo, area_m2=0.0, longitudes_laterales_m=None,
                      presion_conocida_m=None, avisos=()):
    """Datos de una subunidad diseñada (Diseno) para la memoria de cálculo."""
    r, tuberia = diseno.resultado, diseno.tuberia
    laterales = [lat for rama in diseno.subunidad.ramas for c in rama.conexiones for lat in c.laterales]
    lateral = laterales[0]
    emisor = lateral.emisor
    longitudes = list(longitudes_laterales_m or [lat.longitud_m for lat in laterales])
    presiones_laterales = [p for rama in r.ramas for p in rama.presiones_m]
    secciones = [{"rama": nombre_rama(len(r.ramas), rama.sentido), "tuberia": s.tuberia.nombre,
                  "di_mm": s.tuberia.diametro_interior_mm, "desde_m": _r(s.desde_m, 2),
                  "hasta_m": _r(s.hasta_m, 2), "velocidad_max_ms": _r(s.velocidad_max_ms),
                  "presion_max_m": _r(s.presion_max_m)}
                 for rama in r.ramas for s in rama.secciones]
    evaluaciones = []
    for e in diseno.evaluaciones:
        er = e.resultado
        evaluaciones.append({
            "tuberia": e.tuberia.nombre, "di_mm": e.tuberia.diametro_interior_mm,
            "presion_entrada_m": _r(er.presion_entrada_m) if er else None,
            "velocidad_ms": _r(er.velocidad_max_ms) if er else None,
            "variacion_caudal": _r(er.variacion_caudal, 5) if er else None,
            "uniformidad_emision": _r(er.uniformidad_emision, 2) if er else None,
            "cumple": e.cumple, "motivos": list(e.motivos), "elegida": e.tuberia is tuberia,
        })
    return {
        "version": VERSION_RESUMEN,
        "nombre": nombre,
        "area_m2": _r(area_m2, 2),
        "metodo": metodo,
        "criterios": {"variacion_caudal_max": criterios.variacion_caudal_max,
                      "velocidad_max_ms": criterios.velocidad_max_ms,
                      "presion_entrada_max_m": criterios.presion_entrada_max_m},
        "presion_conocida_m": presion_conocida_m,
        "lateral": {
            "tuberia": lateral.tuberia.nombre, "di_mm": lateral.tuberia.diametro_interior_mm,
            "espaciamiento_m": lateral.espaciamiento_m, "numero": len(laterales),
            "longitud_min_m": _r(min(longitudes), 2), "longitud_max_m": _r(max(longitudes), 2),
            "longitud_media_m": _r(sum(longitudes) / len(longitudes), 2),
            "longitud_total_m": _r(sum(longitudes), 2),
        },
        "emisor": {
            "nombre": emisor.nombre, "caudal_nominal_lh": emisor.caudal_nominal_lh,
            "presion_nominal_m": emisor.presion_nominal_m, "exponente": emisor.exponente,
            "k": _r(emisor.k, 5), "cv": emisor.cv, "autocompensado": emisor.autocompensado,
            "presion_min_m": emisor.presion_compensacion_m if emisor.autocompensado else None,
            "presion_max_m": emisor.presion_max_m if emisor.autocompensado else None,
        },
        "portalateral": {
            "tuberia": tuberia.nombre, "di_mm": tuberia.diametro_interior_mm,
            "automatica": diseno.automatica, "ramas": len(r.ramas),
            "longitud_m": _r(sum(max(rama.distancias_m) for rama in r.ramas), 2),
            "telescopico": diseno.telescopico,
            "descripcion": descripcion_telescopico(diseno) if diseno.telescopico else diseno.tuberia.nombre,
            "secciones": secciones,
        },
        "resultados": {
            "presion_entrada_m": _r(r.presion_entrada_m), "caudal_lh": _r(r.caudal_total_lh, 1),
            "numero_emisores": r.numero_emisores, "velocidad_max_ms": _r(r.velocidad_max_ms),
            "perdida_friccion_max_m": _r(r.perdida_friccion_max_m),
            "presion_lateral_min_m": _r(min(presiones_laterales)),
            "presion_lateral_max_m": _r(max(presiones_laterales)),
            "presion_emisor_min_m": _r(r.presion_min_emisor_m),
            "presion_emisor_max_m": _r(r.presion_max_emisor_m),
            "caudal_emisor_min_lh": _r(r.caudal_min_lh, 4),
            "caudal_emisor_medio_lh": _r(r.caudal_medio_lh, 4),
            "caudal_emisor_max_lh": _r(r.caudal_max_lh, 4),
            "variacion_caudal": _r(r.variacion_caudal, 5),
            "uniformidad_emision": _r(r.uniformidad_emision, 2),
            "emisores_fuera_de_rango": r.emisores_fuera_de_rango,
        },
        "evaluaciones": evaluaciones,
        "perfil": [[_r(v) for v in punto] for punto in puntos_perfil_subunidad(r)],
        "referencia": list(referencia_emisor(emisor)),
        "cumple": not incumplimientos(r, criterios, tuberia),
        "avisos": avisos_subunidad(diseno, criterios, lateral.tuberia, avisos),
    }


def resumen_economia(optimizacion, moneda="", lista_precios=""):
    """Datos de la elección de diámetros por costo total (ResultadoOptimizacion)."""
    e = optimizacion.economicos

    def costos(c):
        return {"tuberia": _r(c.tuberia, 2), "energia_kwh_anual": _r(c.energia_kwh_anual, 1),
                "energia_anual": _r(c.energia_anual, 2),
                "energia_valor_presente": _r(c.energia_valor_presente, 2), "total": _r(c.total, 2)}
    return {
        "precio_energia_kwh": e.precio_energia_kwh, "horas_bombeo_anio": e.horas_bombeo_anio,
        "vida_util_anios": e.vida_util_anios, "tasa_interes": e.tasa_interes,
        "eficiencia_motor": e.eficiencia_motor, "factor_valor_presente": _r(e.factor_valor_presente, 4),
        "moneda": moneda, "lista_precios": lista_precios,
        "optimo": costos(optimizacion.costos), "referencia": costos(optimizacion.costos_referencia),
        "tramos_cambiados": list(optimizacion.tramos_cambiados),
    }


def resumen_red(red, resultado, bombas, datos_bomba, sin_dem=False, economia=None):
    """Datos de la red principal dimensionada y de la bomba para la memoria de cálculo.

    economia: resumen_economia(), si los diámetros se eligieron por costo total.
    """
    critica = bomba_critica(bombas)
    turno = resultado.turno(critica.turno)
    tramos = []
    for t in red.tramos:
        tuberia = resultado.asignacion[t.id]
        q, p_min, p_max = resultado.peor_tramo(t.id)
        peores = [r.tramos[t.id] for r in resultado.turnos]
        tramos.append({
            "id": t.id, "tuberia": tuberia.nombre, "dn_mm": tuberia.diametro_nominal_mm,
            "pn_m": tuberia.presion_nominal_m, "longitud_m": _r(t.longitud_m, 2), "caudal_lh": _r(q, 1),
            "velocidad_ms": _r(max(r.velocidad_ms for r in peores)),
            "j_m100": _r(max(r.perdida_unitaria_m100 for r in peores)),
            "presion_min_m": _r(p_min, 2), "presion_max_m": _r(p_max, 2),
            "observaciones": resultado.observaciones(t.id),
        })
    turnos = []
    for b in bombas:
        rt = resultado.turno(b.turno)
        turnos.append({
            "turno": b.turno, "valvulas": [v.id for v in red.valvulas if v.turno == b.turno],
            "caudal_lh": _r(b.caudal_lh, 1), "presion_entrada_red_m": _r(rt.presion_entrada_red_m),
            "cdt_m": _r(b.carga_dinamica_total_m), "potencia_kw": _r(b.potencia_kw), "critico": rt.critico,
        })
    valvulas = []
    for v in red.valvulas:
        rt = resultado.turno(v.turno)
        valvulas.append({
            "id": v.id, "turno": v.turno, "caudal_lh": _r(v.caudal_lh, 1),
            "presion_requerida_m": _r(v.presion_requerida_m), "perdida_m": _r(v.perdida_m),
            "presion_disponible_m": _r(rt.presion_disponible[v.id]), "exceso_m": _r(rt.exceso(v)),
        })
    perfil = asdict(perfil_ruta_critica(red, turno))
    for clave in ("distancias_m", "terreno_m", "piezometrica_m"):
        perfil[clave] = [_r(v) for v in perfil[clave]]
    c = resultado.criterios
    return {
        "version": VERSION_RESUMEN,
        "metodo": c.metodo,
        "criterios": {"velocidad_max_ms": c.velocidad_max_ms,
                      "perdida_unitaria_max_m100": c.perdida_unitaria_max_m100,
                      "presion_min_m": c.presion_min_m,
                      "factor_perdidas_menores": c.factor_perdidas_menores},
        "bomba": {
            "turno": critica.turno, "caudal_lh": _r(critica.caudal_lh, 1),
            "cdt_m": _r(critica.carga_dinamica_total_m), "potencia_kw": _r(critica.potencia_kw),
            "potencia_hp": _r(critica.potencia_hp), "presion_entrada_red_m": _r(turno.presion_entrada_red_m),
            "perdidas_cabezal_m": datos_bomba.perdidas_cabezal_m,
            "altura_succion_m": datos_bomba.altura_succion_m, "eficiencia": datos_bomba.eficiencia,
            "critico": turno.critico, "potencia_comercial_hp": potencia_comercial_hp(critica.potencia_hp),
        },
        "tramos": tramos,
        "turnos": turnos,
        "valvulas": valvulas,
        "perfil": perfil,
        "sin_dem": sin_dem,
        "economia": economia,
        "cumple": not resultado.motivos,
        "avisos": avisos_red(resultado, bombas, sin_dem),
    }


# ---------------------------------------------------------------- documento


@dataclass
class Presupuesto:
    partidas: list  # Partida, con su artículo asignado
    desperdicio: float = 0.0
    moneda: str = ""
    lista_precios: str = ""  # nombre del archivo de la lista de precios
    detalle: bool = True  # incluir todas las partidas, no solo el resumen por categoría


@dataclass
class DatosMemoria:
    titulo: str = "Memoria de cálculo del sistema de riego por goteo"
    proyecto: str = ""
    cliente: str = ""
    ubicacion: str = ""
    proyectista: str = ""
    fecha: str = ""
    notas: str = ""
    subunidades: List[dict] = field(default_factory=list)
    red: Optional[dict] = None
    presupuesto: Optional[Presupuesto] = None
    avisos: List[str] = field(default_factory=list)  # avisos generales (p. ej. resultados sin datos)
    version: str = ""  # versión de RiegoLibre


def graficos_memoria(datos) -> Dict[str, bytes]:
    """Gráficos PNG de la memoria: perfil de cada subunidad y ruta crítica de la red."""
    imagenes = {}
    for i, s in enumerate(datos.subunidades):
        if s.get("perfil"):
            imagen = png(dibujar_perfil_subunidad, s["perfil"], s["resultados"]["presion_entrada_m"],
                         *s["referencia"])
            if imagen:
                imagenes[f"subunidad_{i}"] = imagen
    if datos.red and datos.red.get("perfil"):
        imagen = png(dibujar_perfil_red, datos.red["perfil"])
        if imagen:
            imagenes["red_perfil"] = imagen
    return imagenes


ESTILO = """
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #212121; }
h1 { font-size: 18pt; color: #1b5e20; margin-bottom: 2px; }
h2 { font-size: 13.5pt; color: #1b5e20; margin-top: 18px; border-bottom: 1px solid #1b5e20; }
h3 { font-size: 11pt; color: #2e7d32; margin-top: 12px; }
p { margin-top: 4px; margin-bottom: 4px; }
table.datos { border-collapse: collapse; border-color: #9e9e9e; margin-top: 4px; margin-bottom: 6px; }
table.datos th { background-color: #2e7d32; color: #ffffff; font-weight: bold; font-size: 9pt; }
table.datos td { font-size: 9pt; }
table.datos td.n { text-align: right; }
table.kv td.k { color: #424242; font-weight: bold; }
tr.elegida td { font-weight: bold; background-color: #e8f5e9; }
tr.total td { font-weight: bold; background-color: #f1f8e9; }
.ok { color: #2e7d32; font-weight: bold; }
.mal { color: #c62828; font-weight: bold; }
.aviso { color: #c62828; }
.nota { color: #616161; font-size: 9pt; }
.subtitulo { font-size: 12pt; color: #424242; }
.pie { color: #616161; font-size: 9pt; }
"""


def _e(texto):
    return html.escape(str(texto))


def _n(valor, decimales=2, sufijo=""):
    if valor is None:
        return "—"
    return f"{valor:,.{decimales}f}{sufijo}"


def _pc(fraccion, decimales=1):
    return "—" if fraccion is None else f"{100 * fraccion:.{decimales}f} %"


def _estado(cumple):
    return "<span class='ok'>✔ Cumple</span>" if cumple else "<span class='mal'>✘ No cumple</span>"


def _kv(filas):
    """Tabla de dos columnas (dato, valor). Los valores ya vienen en HTML."""
    celdas = "".join(f"<tr><td class='k'>{k}</td><td>{v}</td></tr>" for k, v in filas if v not in (None, ""))
    return f"<table class='kv' cellpadding='3' cellspacing='0'>{celdas}</table>"


def _tabla(encabezados, filas, numericas=(), clases=None, anchos=None):
    """Tabla con encabezado.

    filas: listas de celdas en HTML; clases: {fila: clase CSS}; anchos: {columna: % del ancho}.
    """
    partes = ["<table class='datos' width='100%' border='1' cellspacing='0' cellpadding='3'><tr>"]
    for j, h in enumerate(encabezados):
        ancho = (anchos or {}).get(j)
        partes.append(f"<th width='{ancho}%'>{h}</th>" if ancho else f"<th>{h}</th>")
    partes.append("</tr>")
    for i, fila in enumerate(filas):
        clase = (clases or {}).get(i)
        partes.append(f"<tr class='{clase}'>" if clase else "<tr>")
        for j, celda in enumerate(fila):
            partes.append(f"<td class='n'>{celda}</td>" if j in numericas else f"<td>{celda}</td>")
        partes.append("</tr>")
    partes.append("</table>")
    return "".join(partes)


def _avisos(avisos):
    if not avisos:
        return ""
    return "<p class='aviso'>" + "<br>".join("⚠ " + _e(a) for a in avisos) + "</p>"


def _figura(imagenes, clave, pie, ancho=600):
    if clave not in imagenes:
        return ""
    return (f"<p align='center'><img src='{_e(imagenes[clave])}' width='{ancho}'><br>"
            f"<span class='pie'>{_e(pie)}</span></p>")


class _Numeracion:
    def __init__(self):
        self.seccion = 0

    def h2(self, titulo, nueva_pagina=False):
        self.seccion += 1
        estilo = " style='page-break-before: always'" if nueva_pagina else ""
        return f"<h2{estilo}>{self.seccion}. {_e(titulo)}</h2>"


def _descripcion_emisor(e):
    if e["autocompensado"]:
        rango = f"entre {e['presion_min_m']:g} y {e['presion_max_m']:g} m" if e["presion_max_m"] else \
            f"desde {e['presion_min_m']:g} m"
        return (f"{_e(e['nombre'])} — autocompensado, {e['caudal_nominal_lh']:g} L/h {rango}; "
                f"CV de fabricación {e['cv']:g}")
    return (f"{_e(e['nombre'])} — q = {e['k']:.4f}·h<sup>{e['exponente']:g}</sup> "
            f"({e['caudal_nominal_lh']:g} L/h a {e['presion_nominal_m']:g} m); CV de fabricación {e['cv']:g}")


def _seccion_resumen(datos, num):
    subs = datos.subunidades
    filas = []
    if subs:
        area = sum(s["area_m2"] or 0.0 for s in subs)
        caudal = sum(s["resultados"]["caudal_lh"] for s in subs)
        filas += [
            ("Subunidades de riego", f"{len(subs)}" + (f" · área total {area / 10000:,.2f} ha" if area else "")),
            ("Laterales / emisores", f"{sum(s['lateral']['numero'] for s in subs):,} / "
                                     f"{sum(s['resultados']['numero_emisores'] for s in subs):,}"),
            ("Caudal de todas las subunidades", f"{caudal / 3600:,.2f} L/s ({caudal / 1000:,.1f} m³/h)"),
        ]
    red = datos.red
    if red:
        b = red["bomba"]
        filas += [
            ("Turnos de riego", f"{len(red['turnos'])}"),
            ("Punto de diseño de la bomba", f"<b>{b['caudal_lh'] / 3600:.2f} L/s</b> "
                                            f"({b['caudal_lh'] / 1000:.1f} m³/h) a <b>{b['cdt_m']:.1f} m</b> de CDT"),
            ("Potencia al eje", f"{b['potencia_kw']:.2f} kW ({b['potencia_hp']:.1f} HP)"
             + (f" · motor comercial sugerido: {b['potencia_comercial_hp']:g} HP"
                if b.get("potencia_comercial_hp") else "")),
        ]
        e = red.get("economia")
        if e:
            filas.append(("Energía de bombeo", f"{e['optimo']['energia_kwh_anual']:,.0f} kWh/año · "
                                               f"{e['optimo']['energia_anual']:,.2f} {_e(e['moneda'])}/año"))
    if datos.presupuesto is not None:
        p = datos.presupuesto
        filas.append(("Costo estimado de materiales",
                      f"<b>{total(p.partidas, p.desperdicio):,.2f} {_e(p.moneda)}</b>"))
    estados = [s["cumple"] for s in subs] + ([red["cumple"]] if red else [])
    if estados:
        filas.append(("Criterios de diseño", "<span class='ok'>✔ Se cumplen en todo el sistema</span>"
                      if all(estados) else
                      f"<span class='mal'>✘ {estados.count(False)} elementos no cumplen (ver detalle)</span>"))
    return num.h2("Resumen del proyecto") + _kv(filas) + _avisos(datos.avisos)


def _seccion_bases(datos, num):
    metodos = {s["metodo"] for s in datos.subunidades}
    if datos.red:
        metodos.add(datos.red["metodo"])
    partes = [num.h2("Bases de cálculo", nueva_pagina=True), "<h3>Pérdidas de carga por fricción</h3>"]
    if "darcy" in metodos or not metodos:
        partes.append(
            "<p><b>Darcy-Weisbach:</b> h<sub>f</sub> = f · (L/D) · V²/(2g). El factor de fricción f se "
            "obtiene con la ecuación de Swamee-Jain en régimen turbulento (Re &gt; 4000), con 64/Re en "
            "régimen laminar (Re &lt; 2000) y por interpolación en la transición. Viscosidad del agua a 20 °C.</p>")
    if "hazen" in metodos:
        partes.append(
            "<p><b>Hazen-Williams:</b> h<sub>f</sub> = 10.67 · L · Q<sup>1.852</sup> / "
            "(C<sup>1.852</sup> · D<sup>4.87</sup>), con Q en m³/s y D en m.</p>")
    partes.append(
        "<h3>Emisores y uniformidad</h3>"
        "<p>Caudal de los emisores: q = k · h<sup>x</sup>. Los emisores autocompensados entregan su "
        "caudal nominal dentro del rango de compensación; por debajo de él se comportan como un orificio.</p>"
        "<p>Variación de caudal en la subunidad: q<sub>var</sub> = (q<sub>máx</sub> − q<sub>mín</sub>) / "
        "q<sub>máx</sub>. Uniformidad de emisión (Keller y Karmeli): EU = 100 · (1 − 1.27 · CV / √e) · "
        "q<sub>mín</sub> / q<sub>medio</sub>, con e = 1 emisor por planta.</p>"
        "<h3>Laterales y portalaterales</h3>"
        "<p>Los laterales y portalaterales se calculan tramo a tramo, desde el extremo final hacia la "
        "entrada, sumando en cada tramo la pérdida por fricción, el desnivel del terreno (perfil del DEM, "
        "si existe) y el caudal de cada salida. La presión de entrada se obtiene por iteración: con "
        "emisores no compensados, para que el caudal medio sea el nominal; con autocompensados, para que "
        "el emisor más desfavorecido reciba la presión de inicio de compensación. El diámetro del "
        "portalateral es el más económico del catálogo que cumple todos los criterios.</p>")
    if any(s["portalateral"].get("telescopico") for s in datos.subunidades):
        partes.append(
            "<p><b>Portalateral telescópico:</b> la tubería de la entrada es la que cumpliría sola en todo el "
            "portalateral. Hacia el final, donde el caudal es menor, se prueba cada diámetro menor y se busca "
            "el punto de cambio más cercano a la válvula que sigue cumpliendo los criterios (variación de "
            "caudal, velocidad en cada tramo, presiones nominales). Entre las alternativas se elige la de "
            "menos material (longitud × diámetro²).</p>")
    if datos.red:
        partes.append(
            "<h3>Red principal y bomba</h3>"
            "<p>La red es ramificada. En cada turno funcionan solo sus válvulas; los caudales se acumulan "
            "desde las válvulas hacia la fuente. "
            + ("Los diámetros se eligen por el menor costo total: costo de las tuberías más el valor "
               "presente de la energía de bombeo durante la vida útil, VP = E<sub>anual</sub> · "
               "(1 − (1 + i)<sup>−n</sup>) / i. La energía de cada turno es P<sub>eje</sub> / "
               "η<sub>motor</sub> por sus horas de bombeo (las horas del año se reparten por igual entre los "
               "turnos). La búsqueda parte del menor diámetro que cumple y prueba, tramo a tramo, el diámetro "
               "inmediato superior e inferior hasta que ningún cambio reduce el costo. Todos los diámetros "
               "respetan la velocidad máxima (y la pérdida unitaria máxima, si se fijó). "
               if datos.red.get("economia") else
               "El diámetro de cada tramo es el menor que respeta la velocidad máxima (y la pérdida unitaria "
               "máxima, si se fijó) con el caudal máximo de todos los turnos. ")
            + "La clase de presión se eleva donde la presión máxima de trabajo lo exige. Las "
            "pérdidas menores (codos, tes, válvulas) se toman como un porcentaje de la fricción.</p>"
            "<p>La carga necesaria en la fuente es la mayor entre la que requiere la válvula más "
            "desfavorecida (presión de la subunidad + pérdida en la válvula) y la que mantiene la presión "
            "mínima en todos los puntos de la red, incluidos los puntos altos del terreno.</p>"
            "<p>Carga dinámica total: CDT = presión a la entrada de la red + pérdidas en el cabezal + "
            "altura de succión. Potencia al eje: P = γ · Q · CDT / η, con γ = 9.81 kN/m³.</p>")
    return "".join(partes)


def _seccion_subunidades(datos, num, imagenes):
    subs = datos.subunidades
    partes = [num.h2("Subunidades de riego", nueva_pagina=True)]
    filas = []
    for s in subs:
        r = s["resultados"]
        filas.append([_e(s["nombre"]), _n(s["area_m2"] / 10000, 3) if s["area_m2"] else "—",
                      f"{s['lateral']['numero']:,}", f"{r['numero_emisores']:,}", _n(r["caudal_lh"] / 3600),
                      _n(r["presion_entrada_m"]), _e(s["portalateral"]["tuberia"]),
                      _pc(r["variacion_caudal"]), _n(r["uniformidad_emision"], 1), _estado(s["cumple"])])
    partes.append(_tabla(["Subunidad", "Área (ha)", "Laterales", "Emisores", "Caudal (L/s)",
                          "Presión en válvula (m)", "Portalateral", "Var. caudal", "EU (%)", "Estado"],
                         filas, numericas=(1, 2, 3, 4, 5, 7, 8), anchos={0: 14, 6: 17, 9: 11}))

    for i, s in enumerate(subs):
        r, lat, porta, c = s["resultados"], s["lateral"], s["portalateral"], s["criterios"]
        partes.append(f"<h3>{num.seccion}.{i + 1} {_e(s['nombre'])} — {_estado(s['cumple'])}</h3>")
        entrada = "en un extremo (una rama)" if porta["ramas"] == 1 else "intermedia (dos ramas)"
        presion = (f"conocida: {s['presion_conocida_m']:g} m" if s.get("presion_conocida_m") is not None
                   else "calculada (la necesaria para cumplir el criterio del emisor)")
        criterios = (f"variación de caudal ≤ {_pc(c['variacion_caudal_max'], 0)}; velocidad en portalateral "
                     f"≤ {c['velocidad_max_ms']:g} m/s")
        if c.get("presion_entrada_max_m"):
            criterios += f"; presión de entrada ≤ {c['presion_entrada_max_m']:g} m"
        partes.append("<p><b>Datos de diseño</b></p>" + _kv([
            ("Área", f"{s['area_m2'] / 10000:,.3f} ha" if s["area_m2"] else "—"),
            ("Laterales", f"{lat['numero']:,} × {_e(lat['tuberia'])} (DI {lat['di_mm']:g} mm) · longitud "
                          f"{lat['longitud_min_m']:.1f} / {lat['longitud_media_m']:.1f} / "
                          f"{lat['longitud_max_m']:.1f} m (mín. / media / máx.)"),
            ("Emisor", _descripcion_emisor(s["emisor"])),
            ("Espaciamiento de emisores", f"{lat['espaciamiento_m']:g} m"),
            ("Portalateral", (f"telescópico: {_e(porta['descripcion'])} desde la válvula"
                              if porta.get("telescopico") else
                              f"{_e(porta['tuberia'])} (DI {porta['di_mm']:g} mm)")
                             + f" · {'selección automática' if porta['automatica'] else 'elegida por el proyectista'}"
                             f" · {porta['longitud_m']:,.1f} m · entrada {entrada}"),
            ("Fórmula de pérdidas", NOMBRES_METODO.get(s["metodo"], _e(s["metodo"]))),
            ("Presión de entrada", presion),
            ("Criterios", criterios),
        ]))
        q = r["caudal_lh"]
        partes.append("<p><b>Resultados</b></p>" + _kv([
            ("Presión en la entrada (válvula)",
             f"<b>{r['presion_entrada_m']:.2f} m</b> ({r['presion_entrada_m'] / M_POR_BAR:.2f} bar)"),
            ("Caudal de la subunidad", f"<b>{q:,.0f} L/h</b> ({q / 3600:.2f} L/s · {q / 1000:.2f} m³/h)"),
            ("Emisores", f"{r['numero_emisores']:,}"),
            ("Precipitación horaria", f"{q / s['area_m2']:.2f} mm/h" if s["area_m2"] else ""),
            ("Velocidad máxima en el portalateral", f"{r['velocidad_max_ms']:.2f} m/s"),
            ("Pérdida por fricción en el portalateral", f"{r['perdida_friccion_max_m']:.2f} m"),
            ("Presión en la entrada de los laterales",
             f"{r['presion_lateral_min_m']:.2f} – {r['presion_lateral_max_m']:.2f} m"),
            ("Presión en los emisores (mín. / máx.)",
             f"{r['presion_emisor_min_m']:.2f} / {r['presion_emisor_max_m']:.2f} m"),
            ("Caudal de los emisores (mín. / medio / máx.)",
             f"{r['caudal_emisor_min_lh']:.3f} / {r['caudal_emisor_medio_lh']:.3f} / "
             f"{r['caudal_emisor_max_lh']:.3f} L/h"),
            ("Variación de caudal", f"<b>{_pc(r['variacion_caudal'])}</b>"),
            ("Uniformidad de emisión (EU)", f"<b>{r['uniformidad_emision']:.1f} %</b>"),
            ("Emisores fuera del rango de compensación", f"{r['emisores_fuera_de_rango']:,}"),
        ]))
        if porta.get("telescopico"):
            filas = [[_e(x["rama"]), _n(x["desde_m"], 1), _n(x["hasta_m"], 1), _e(x["tuberia"]),
                      _n(x["di_mm"], 1), _n(x["velocidad_max_ms"]), _n(x["presion_max_m"])]
                     for x in porta["secciones"]]
            partes.append("<p><b>Tramos del portalateral telescópico</b> (distancias desde la válvula)</p>"
                          + _tabla(["Rama", "Desde (m)", "Hasta (m)", "Tubería", "DI (mm)", "V máx. (m/s)",
                                    "P máx. (m)"], filas, numericas=(1, 2, 4, 5, 6), anchos={3: 30}))
        if s["evaluaciones"]:
            evaluaciones = s["evaluaciones"]
            elegida = next((j for j, e in enumerate(evaluaciones) if e["elegida"]), None)
            if elegida is not None and elegida + 3 < len(evaluaciones):
                evaluaciones = evaluaciones[:elegida + 3]
            filas, clases = [], {}
            for j, e in enumerate(evaluaciones):
                if e["elegida"]:
                    clases[j] = "elegida"
                filas.append([_e(e["tuberia"]), _n(e["di_mm"], 1), _n(e["presion_entrada_m"]),
                              _n(e["velocidad_ms"]), _pc(e["variacion_caudal"]),
                              _n(e["uniformidad_emision"], 1),
                              "✔ cumple" if e["cumple"] else "✘ " + _e("; ".join(e["motivos"]))])
            partes.append("<p><b>Selección del diámetro del portalateral</b></p>"
                          + _tabla(["Tubería", "DI (mm)", "Presión entrada (m)", "Velocidad (m/s)",
                                    "Var. caudal", "EU (%)", "Resultado"], filas,
                                   numericas=(1, 2, 3, 4, 5), clases=clases, anchos={0: 22, 6: 33})
                          + "<p class='nota'>Tuberías ordenadas de la más económica a la más cara "
                            "(diámetro nominal y clase), con un solo diámetro en todo el portalateral; "
                          + ("en negrita, la de la entrada del portalateral telescópico"
                             if porta.get("telescopico") else "en negrita, la usada")
                          + (f". Se omiten {len(s['evaluaciones']) - len(evaluaciones)} alternativas más caras."
                             if len(evaluaciones) < len(s["evaluaciones"]) else ".") + "</p>")
        partes.append(_figura(imagenes, f"subunidad_{i}",
                              f"Presiones a lo largo del portalateral de «{s['nombre']}»"))
        partes.append(_avisos(s["avisos"]))
    return "".join(partes)


def _seccion_red(red, num, imagenes):
    c = red["criterios"]
    partes = [num.h2("Red principal de conducción", nueva_pagina=True)]
    partes.append("<p><b>Criterios de diseño</b></p>" + _kv([
        ("Fórmula de pérdidas", NOMBRES_METODO.get(red["metodo"], _e(red["metodo"]))),
        ("Velocidad máxima", f"{c['velocidad_max_ms']:g} m/s"),
        ("Pérdida unitaria máxima", f"{c['perdida_unitaria_max_m100']:g} m/100 m"
         if c.get("perdida_unitaria_max_m100") else "sin límite"),
        ("Presión mínima en la red", f"{c['presion_min_m']:g} m"),
        ("Pérdidas menores", f"{100 * c['factor_perdidas_menores']:g} % de la fricción"),
        ("Terreno", "plano (sin DEM)" if red.get("sin_dem") else "cotas del DEM"),
        ("Elección de diámetros", "menor costo total (tubería + energía de bombeo)" if red.get("economia")
         else "menor diámetro que cumple los criterios"),
    ]))
    if red.get("economia"):
        partes.append(_seccion_economia(red["economia"]))
    filas = [[_e(t["id"]), _e(t["tuberia"]), _n(t["longitud_m"], 1), _n(t["caudal_lh"] / 3600),
              _n(t["velocidad_ms"]), _n(t["j_m100"]), _n(t["presion_min_m"], 1), _n(t["presion_max_m"], 1),
              _e(t["observaciones"])] for t in red["tramos"]]
    partes.append("<p><b>Tuberías por tramo</b> (valores extremos de todos los turnos)</p>"
                  + _tabla(["Tramo", "Tubería", "Long. (m)", "Q máx. (L/s)", "V máx. (m/s)",
                            "J máx. (m/100 m)", "P mín. (m)", "P máx. (m)", "Observaciones"], filas,
                           numericas=(2, 3, 4, 5, 6, 7), anchos={1: 20, 8: 18}))
    metros = {}
    for t in red["tramos"]:
        metros[t["tuberia"]] = metros.get(t["tuberia"], 0.0) + t["longitud_m"]
    partes.append("<p><b>Longitud por tubería</b></p>" + _tabla(
        ["Tubería", "Longitud (m)"], [[_e(n), _n(m, 1)] for n, m in sorted(metros.items())], numericas=(1,)))
    filas = [[_e(v["id"]), str(v["turno"]), _n(v["caudal_lh"] / 3600), _n(v["presion_requerida_m"]),
              _n(v["perdida_m"]), _n(v["presion_disponible_m"]), _n(v["exceso_m"])] for v in red["valvulas"]]
    partes.append("<p><b>Válvulas de las subunidades</b></p>" + _tabla(
        ["Válvula", "Turno", "Caudal (L/s)", "Presión requerida (m)", "Pérdida en válvula (m)",
         "Presión disponible (m)", "Exceso (m)"], filas, numericas=(1, 2, 3, 4, 5, 6))
        + "<p class='nota'>El exceso de presión se disipa con la regulación de la válvula de cada subunidad.</p>")
    perfil = red.get("perfil") or {}
    partes.append(_figura(imagenes, "red_perfil",
                          f"Terreno y línea piezométrica hasta la válvula {perfil.get('valvula', '')} "
                          f"(turno {perfil.get('turno', '')})"))
    partes.append(_avisos(red["avisos"]))
    return "".join(partes)


def _seccion_economia(e):
    moneda = _e(e["moneda"])
    partes = ["<p><b>Elección de diámetros por costo total</b></p>", _kv([
        ("Lista de precios", _e(e["lista_precios"])),
        ("Precio de la energía", f"{e['precio_energia_kwh']:g} {moneda}/kWh"),
        ("Horas de bombeo al año", f"{e['horas_bombeo_anio']:,.0f} h (repartidas por igual entre los turnos)"),
        ("Vida útil / tasa de interés", f"{e['vida_util_anios']} años / {_pc(e['tasa_interes'])}"),
        ("Factor de valor presente", f"{e['factor_valor_presente']:.3f}"),
        ("Eficiencia del motor", _pc(e["eficiencia_motor"], 0)),
    ])]
    o, r = e["optimo"], e["referencia"]
    filas = [[nombre, _n(r[clave], decimales), _n(o[clave], decimales), _n(o[clave] - r[clave], decimales)]
             for nombre, clave, decimales in (
                 (f"Tuberías ({moneda})", "tuberia", 2),
                 ("Energía anual (kWh)", "energia_kwh_anual", 0),
                 (f"Energía anual ({moneda})", "energia_anual", 2),
                 (f"Energía en la vida útil, valor presente ({moneda})", "energia_valor_presente", 2),
                 (f"Costo total ({moneda})", "total", 2))]
    partes.append(_tabla(["Concepto", "Menor diámetro que cumple", "Menor costo total (elegido)",
                          "Diferencia"], filas, numericas=(1, 2, 3), clases={len(filas) - 1: "total"},
                         anchos={0: 40}))
    cambiados = e["tramos_cambiados"]
    partes.append("<p class='nota'>" + (
        f"{len(cambiados)} tramos llevan un diámetro mayor que el mínimo ({_e(', '.join(cambiados))}): el "
        "ahorro de energía paga la tubería más grande." if cambiados else
        "El menor diámetro que cumple es también el de menor costo total.")
        + " El costo de tuberías incluye el desperdicio de la lista de materiales.</p>")
    return "".join(partes)


def _seccion_bomba(red, num):
    b = red["bomba"]
    partes = [num.h2("Equipo de bombeo")]
    hidraulica = b["potencia_kw"] * b["eficiencia"]
    partes.append(_kv([
        ("Turno crítico", f"{b['turno']} · lo determina la {_e(b['critico'])}"),
        ("Caudal de diseño", f"<b>{b['caudal_lh'] / 3600:.2f} L/s</b> ({b['caudal_lh'] / 1000:.1f} m³/h)"),
        ("Presión a la entrada de la red", f"{b['presion_entrada_red_m']:.2f} m"),
        ("Pérdidas en el cabezal (filtros, fertirriego, medidor)", f"{b['perdidas_cabezal_m']:.2f} m"),
        ("Altura de succión", f"{b['altura_succion_m']:.2f} m"),
        ("Carga dinámica total (CDT)", f"<b>{b['cdt_m']:.2f} m</b> ({b['cdt_m'] / M_POR_BAR:.2f} bar)"),
        ("Eficiencia de la bomba", f"{100 * b['eficiencia']:.0f} %"),
        ("Potencia hidráulica", f"{hidraulica:.2f} kW"),
        ("Potencia al eje", f"<b>{b['potencia_kw']:.2f} kW ({b['potencia_hp']:.1f} HP)</b>"),
        ("Motor comercial sugerido", f"{b['potencia_comercial_hp']:g} HP (con {MARGEN_MOTOR:.0%} de margen)"
         if b.get("potencia_comercial_hp") else ""),
    ]))
    filas = [[str(t["turno"]), _e(", ".join(t["valvulas"])), _n(t["caudal_lh"] / 3600),
              _n(t["presion_entrada_red_m"]), _n(t["cdt_m"]), _n(t["potencia_kw"]), _e(t["critico"])]
             for t in red["turnos"]]
    partes.append("<p><b>Turnos de riego</b></p>" + _tabla(
        ["Turno", "Válvulas", "Caudal (L/s)", "Presión entrada red (m)", "CDT (m)", "Potencia (kW)",
         "Determina la carga"], filas, numericas=(0, 2, 3, 4, 5), anchos={1: 22, 6: 20}))
    partes.append("<p class='nota'>Verifique en la curva del fabricante que la bomba entregue el caudal "
                  "de cada turno a su CDT con buena eficiencia.</p>")
    return "".join(partes)


def _seccion_presupuesto(p, num):
    moneda = _e(p.moneda)
    partes = [num.h2("Presupuesto de materiales", nueva_pagina=True)]
    partes.append(_kv([
        ("Lista de precios", _e(p.lista_precios)),
        ("Moneda", moneda),
        ("Desperdicio aplicado a tuberías", f"{p.desperdicio:.0%}"),
    ]))
    resumen = resumen_por_categoria(p.partidas, p.desperdicio)
    filas = [[_e(c), _n(s), str(n) if n else ""] for c, s, n in resumen]
    filas.append(["Total", _n(total(p.partidas, p.desperdicio)), ""])
    partes.append("<p><b>Resumen por categoría</b></p>" + _tabla(
        ["Categoría", f"Subtotal ({moneda})", "Partidas sin precio"], filas, numericas=(1, 2),
        clases={len(filas) - 1: "total"}))
    if p.detalle:
        filas = []
        for partida in p.partidas:
            a = partida.articulo
            metros = partida.unidad == "m"
            piezas = partida.piezas(p.desperdicio)
            unitario = a.precio if piezas is not None else partida.precio_unitario()
            filas.append([
                _e(partida.categoria), _e(partida.material),
                _n(partida.cantidad_compra(p.desperdicio), 1 if metros else 0), _e(partida.unidad),
                f"{piezas:,}" if piezas is not None else "",
                _e(f"{a.descripcion} [{a.codigo}]") if a else "<span class='aviso'>sin precio</span>",
                _n(unitario, 4) if a else "", _n(partida.costo(p.desperdicio)) if a else ""])
        partes.append("<p><b>Detalle de partidas</b></p>" + _tabla(
            ["Categoría", "Material", "Cant.", "Und.", "Tubos", "Artículo", "P. unit.", "Subtotal"],
            filas, numericas=(2, 4, 6, 7), anchos={0: 13, 1: 22, 3: 6, 4: 7, 5: 26, 7: 10}))
    sin_precio = sum(1 for partida in p.partidas if partida.articulo is None)
    nota = ("Precios referenciales de la lista indicada; no incluyen mano de obra, transporte, obras "
            "civiles, accesorios de unión ni impuestos.")
    if sin_precio:
        nota += f" {sin_precio} partidas sin precio no están incluidas en el total."
    partes.append(f"<p class='nota'>{nota}</p>")
    return "".join(partes)


def memoria_html(datos: DatosMemoria, imagenes: Optional[Dict[str, str]] = None) -> str:
    """Documento HTML de la memoria de cálculo.

    imagenes: clave -> dirección de la imagen («mapa», «red_perfil», «subunidad_<i>»);
    las que falten simplemente no se incluyen.
    """
    imagenes = imagenes or {}
    num = _Numeracion()
    partes = [f"<html><head><meta charset='utf-8'><title>{_e(datos.titulo)}</title>"
              f"<style>{ESTILO}</style></head><body>",
              f"<h1>{_e(datos.titulo)}</h1>"]
    if datos.proyecto:
        partes.append(f"<p class='subtitulo'>{_e(datos.proyecto)}</p>")
    partes.append(_kv([("Proyecto", _e(datos.proyecto)), ("Cliente", _e(datos.cliente)),
                       ("Ubicación", _e(datos.ubicacion)), ("Proyectista", _e(datos.proyectista)),
                       ("Fecha", _e(datos.fecha))]))
    partes.append(_seccion_resumen(datos, num))
    if "mapa" in imagenes:
        partes.append(num.h2("Plano general"))
        partes.append(_figura(imagenes, "mapa", "Subunidades, laterales y red principal del proyecto"))
    partes.append(_seccion_bases(datos, num))
    if datos.subunidades:
        partes.append(_seccion_subunidades(datos, num, imagenes))
    if datos.red:
        partes.append(_seccion_red(datos.red, num, imagenes))
        partes.append(_seccion_bomba(datos.red, num))
    if datos.presupuesto is not None:
        partes.append(_seccion_presupuesto(datos.presupuesto, num))
    if datos.notas.strip():
        partes.append(num.h2("Observaciones"))
        partes.append("<p>" + "<br>".join(_e(linea) for linea in datos.notas.strip().splitlines()) + "</p>")
    version = f" {_e(datos.version)}" if datos.version else ""
    partes.append(f"<p class='nota' align='center'><br>Documento generado con RiegoLibre{version}, "
                  "software libre (GPL-3.0). Los resultados deben ser revisados por el proyectista.</p>")
    partes.append("</body></html>")
    return "\n".join(partes)
