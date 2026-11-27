# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Dibujo libre de la capa DIBUJO (la «DRAWING» de IRRICAD): líneas, polilíneas, polígonos, rectángulos,
circunferencias y arcos que no entran en el cálculo. Sin Qt.

Se guardan en los datos del diseño, en `datos["dibujos"]`, como {"tipo", "puntos"}:
- "linea" y "polilinea": la línea abierta por sus vértices;
- "poligono" y "rectangulo": el polígono cerrado (sin repetir el primer vértice; el rectángulo, sus 4 esquinas);
- "circulo": [centro, un punto de la circunferencia];
- "arco": [inicio, un punto intermedio, fin] (el arco de circunferencia que pasa por los tres).

Como en el resto de la edición, cada cambio devuelve una copia nueva de los datos (deshacer).
"""

import copy
import math
from typing import List, Optional, Sequence, Tuple

Punto = Tuple[float, float]

TIPOS = {"linea": "línea", "polilinea": "polilínea", "poligono": "polígono", "rectangulo": "rectángulo",
         "circulo": "circunferencia", "arco": "arco"}
CERRADOS = {"poligono", "rectangulo"}
MINIMO = {"linea": 2, "polilinea": 2, "poligono": 3, "rectangulo": 4, "circulo": 2, "arco": 3}
PASO_ARCO = math.pi / 36  # 5°: un segmento de la circunferencia o del arco
EPS = 1e-6


# ------------------------------------------------------------------ geometría


def _distancia_segmento(p: Punto, a: Punto, b: Punto) -> Tuple[float, Punto]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / largo2))
    c = (a[0] + t * dx, a[1] + t * dy)
    return math.dist(p, c), c


def circulo_por_tres(a: Punto, b: Punto, c: Punto) -> Optional[Tuple[Punto, float]]:
    """(centro, radio) de la circunferencia que pasa por a, b y c; None si están alineados."""
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    escala = max(math.dist(a, b), math.dist(b, c), math.dist(a, c), EPS)
    if abs(d) <= 1e-9 * escala * escala:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy), math.dist((ux, uy), a)


def barrido_arco(a: Punto, m: Punto, b: Punto) -> Optional[Tuple[Punto, float, float, float]]:
    """(centro, radio, ángulo inicial, barrido con signo) del arco de a a b que pasa por m; None si alineados."""
    circulo = circulo_por_tres(a, m, b)
    if circulo is None:
        return None
    (cx, cy), r = circulo
    ta, tm, tb = (math.atan2(p[1] - cy, p[0] - cx) for p in (a, m, b))
    antihorario = (tb - ta) % (2 * math.pi)
    barrido = antihorario if (tm - ta) % (2 * math.pi) <= antihorario else antihorario - 2 * math.pi
    return (cx, cy), r, ta, barrido


def _puntos_arco(centro: Punto, r: float, inicio: float, barrido: float) -> List[Punto]:
    n = max(2, math.ceil(abs(barrido) / PASO_ARCO))
    return [(centro[0] + r * math.cos(inicio + barrido * k / n), centro[1] + r * math.sin(inicio + barrido * k / n))
            for k in range(n + 1)]


def geometria(entidad: dict) -> List[Punto]:
    """La línea que se dibuja en pantalla (los cerrados repiten el primer punto al final)."""
    tipo, puntos = entidad.get("tipo"), _puntos(entidad.get("puntos") or [])
    if tipo == "circulo" and len(puntos) >= 2:
        r = math.dist(puntos[0], puntos[1])
        return _puntos_arco(puntos[0], r, 0.0, 2 * math.pi)
    if tipo == "arco" and len(puntos) >= 3:
        arco = barrido_arco(*puntos[:3])
        return puntos[:3] if arco is None else _puntos_arco(*arco)
    if tipo in CERRADOS and len(puntos) > 2:
        return puntos + [puntos[0]]
    return puntos


def esquinas_rectangulo(a: Punto, b: Punto) -> List[Punto]:
    return [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])]


def medidas(entidad: dict) -> List[Tuple[str, str]]:
    """(etiqueta, valor) para la ficha y la descripción emergente."""
    tipo, puntos = entidad["tipo"], _puntos(entidad["puntos"])
    if tipo == "circulo":
        r = math.dist(puntos[0], puntos[1])
        return [("Centro", f"{puntos[0][0]:.2f}, {puntos[0][1]:.2f}"), ("Radio", f"{r:.2f} m"),
                ("Perímetro", f"{2 * math.pi * r:.2f} m"), ("Área", f"{math.pi * r * r:.2f} m²")]
    geom = geometria(entidad)
    largo = sum(math.dist(p, q) for p, q in zip(geom, geom[1:]))
    if tipo in CERRADOS:
        s = sum(puntos[k][0] * puntos[(k + 1) % len(puntos)][1] - puntos[(k + 1) % len(puntos)][0] * puntos[k][1]
                for k in range(len(puntos)))
        return [("Vértices", str(len(puntos))), ("Perímetro", f"{largo:.2f} m"), ("Área", f"{abs(s) / 2:.2f} m²")]
    if tipo == "arco":
        arco = barrido_arco(*puntos)
        if arco is not None:
            return [("Centro", f"{arco[0][0]:.2f}, {arco[0][1]:.2f}"), ("Radio", f"{arco[1]:.2f} m"),
                    ("Ángulo", f"{abs(math.degrees(arco[3])):.1f}°"), ("Longitud", f"{largo:.2f} m")]
    return [("Vértices", str(len(puntos))), ("Longitud", f"{largo:.2f} m")]


# ------------------------------------------------------------------ acceso a los datos


def _puntos(lista) -> List[Punto]:
    return [(float(p[0]), float(p[1])) for p in lista]


def lista(datos: dict) -> List[dict]:
    """Las entidades del dibujo con puntos en tuplas (se saltan las de tipo desconocido o incompletas)."""
    entidades = []
    for e in datos.get("dibujos") or []:
        if isinstance(e, dict) and e.get("tipo") in TIPOS and len(e.get("puntos") or []) >= MINIMO[e["tipo"]]:
            entidades.append({"tipo": e["tipo"], "puntos": _puntos(e["puntos"])})
    return entidades


def _fijar(datos: dict, entidades: List[dict]):
    if entidades:
        datos["dibujos"] = [{"tipo": e["tipo"], "puntos": [list(p) for p in e["puntos"]]} for e in entidades]
    else:
        datos.pop("dibujos", None)


def nombre(datos: dict, i: int) -> str:
    return f"{TIPOS[lista(datos)[i]['tipo']]} {i + 1} del dibujo"


def vertices(datos: dict, i: int) -> List[List[Punto]]:
    return [lista(datos)[i]["puntos"]]


def puntos_iman(datos: dict) -> List[Punto]:
    """Vértices (y centros de las circunferencias) a los que se pega el imán."""
    return [p for e in lista(datos) for p in (e["puntos"][:1] if e["tipo"] == "circulo" else e["puntos"])]


def segmentos_iman(datos: dict) -> List[Tuple[Punto, Punto]]:
    return [s for e in lista(datos) for s in zip(geometria(e), geometria(e)[1:])]


def objeto_en(datos: dict, p: Punto, tolerancia: float) -> Optional[int]:
    """La entidad cuyo trazo pasa a menos de `tolerancia` de p (la más cercana)."""
    mejor = None
    for i, e in enumerate(lista(datos)):
        geom = geometria(e)
        d = min((_distancia_segmento(p, a, b)[0] for a, b in zip(geom, geom[1:])), default=math.inf)
        if d <= tolerancia and (mejor is None or d < mejor[0]):
            mejor = (d, i)
    return mejor[1] if mejor else None


def borde_en(datos: dict, i: int, p: Punto, tolerancia: float) -> Optional[Tuple[int, int, Punto]]:
    """(0, k, punto) del lado de una polilínea o polígono donde iría un vértice nuevo (tras el k)."""
    e = lista(datos)[i]
    if e["tipo"] in ("circulo", "arco"):
        return None
    puntos = e["puntos"]
    n = len(puntos)
    mejor = None
    for k in range(n if e["tipo"] in CERRADOS else n - 1):
        d, c = _distancia_segmento(p, puntos[k], puntos[(k + 1) % n])
        if d <= tolerancia and (mejor is None or d < mejor[0]):
            mejor = (d, (0, k, c))
    return mejor[1] if mejor else None


# ------------------------------------------------------------------ cambios (devuelven datos nuevos)


def _validar(tipo: str, puntos: List[Punto]):
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de dibujo desconocido: {tipo}.")
    if len(puntos) < MINIMO[tipo]:
        raise ValueError(f"{TIPOS[tipo].capitalize()}: hacen falta al menos {MINIMO[tipo]} puntos.")
    if tipo == "circulo" and math.dist(puntos[0], puntos[1]) <= EPS:
        raise ValueError("La circunferencia necesita un radio mayor que cero.")
    if tipo == "arco" and barrido_arco(*puntos[:3]) is None:
        raise ValueError("Los tres puntos del arco no pueden estar alineados.")
    if tipo in CERRADOS:
        s = sum(puntos[k][0] * puntos[(k + 1) % len(puntos)][1] - puntos[(k + 1) % len(puntos)][0] * puntos[k][1]
                for k in range(len(puntos)))
        if abs(s) / 2 <= EPS:
            raise ValueError(f"{TIPOS[tipo].capitalize()}: los vértices deben encerrar un área.")
    if tipo in ("linea", "polilinea") and all(math.dist(puntos[0], q) <= EPS for q in puntos[1:]):
        raise ValueError(f"{TIPOS[tipo].capitalize()}: los puntos no pueden coincidir.")


def agregar(datos: dict, tipo: str, puntos: Sequence[Punto]) -> dict:
    """Agrega una entidad. El rectángulo puede venir por dos esquinas opuestas."""
    puntos = _puntos(puntos)
    if tipo == "rectangulo" and len(puntos) == 2:
        puntos = esquinas_rectangulo(*puntos)
    if tipo in CERRADOS and len(puntos) > 1 and math.dist(puntos[0], puntos[-1]) <= EPS:
        puntos.pop()
    if tipo == "linea":
        puntos = puntos[:2]
    _validar(tipo, puntos)
    nuevo = copy.deepcopy(datos)
    _fijar(nuevo, lista(nuevo) + [{"tipo": tipo, "puntos": puntos}])
    return nuevo


def borrar(datos: dict, i: int) -> dict:
    nuevo = copy.deepcopy(datos)
    entidades = lista(nuevo)
    del entidades[i]
    _fijar(nuevo, entidades)
    return nuevo


def mover_vertice(datos: dict, i: int, k: int, p: Punto) -> dict:
    """Mueve el vértice k. En la circunferencia, el centro arrastra toda la figura y el otro punto cambia el radio."""
    nuevo = copy.deepcopy(datos)
    entidades = lista(nuevo)
    e = entidades[i]
    p = (float(p[0]), float(p[1]))
    if e["tipo"] == "circulo" and k == 0:
        dx, dy = p[0] - e["puntos"][0][0], p[1] - e["puntos"][0][1]
        e["puntos"] = [(x + dx, y + dy) for x, y in e["puntos"]]
    else:
        e["puntos"][k] = p
    if e["tipo"] == "rectangulo":  # mover una esquina sola lo deja de ser
        e["tipo"] = "poligono"
    _validar(e["tipo"], e["puntos"])
    _fijar(nuevo, entidades)
    return nuevo


def insertar_vertice(datos: dict, i: int, despues_de: int, p: Punto) -> dict:
    nuevo = copy.deepcopy(datos)
    entidades = lista(nuevo)
    e = entidades[i]
    if e["tipo"] in ("circulo", "arco"):
        raise ValueError(f"No se pueden agregar vértices: {TIPOS[e['tipo']]}.")
    e["puntos"].insert(despues_de + 1, (float(p[0]), float(p[1])))
    e["tipo"] = {"linea": "polilinea", "rectangulo": "poligono"}.get(e["tipo"], e["tipo"])
    _fijar(nuevo, entidades)
    return nuevo


def borrar_vertice(datos: dict, i: int, k: int) -> dict:
    nuevo = copy.deepcopy(datos)
    entidades = lista(nuevo)
    e = entidades[i]
    if e["tipo"] in ("circulo", "arco"):
        raise ValueError(f"No se pueden quitar vértices: {TIPOS[e['tipo']]}.")
    tipo = "poligono" if e["tipo"] == "rectangulo" else ("polilinea" if e["tipo"] == "linea" else e["tipo"])
    if len(e["puntos"]) <= MINIMO[tipo]:
        raise ValueError(f"No se puede quitar el vértice: la figura quedaría con menos de {MINIMO[tipo]}.")
    del e["puntos"][k]
    e["tipo"] = tipo
    _validar(tipo, e["puntos"])
    _fijar(nuevo, entidades)
    return nuevo


def pintar(lienzo, capa, datos: dict):
    """Pone las entidades en la capa DIBUJO del lienzo (una por elemento, con sus medidas en la descripción)."""
    for i, e in enumerate(lista(datos)):
        info = f"Dibujo · {TIPOS[e['tipo']]} {i + 1} · " + " · ".join(f"{k}: {v}" for k, v in medidas(e))
        lienzo.lineas(capa, [geometria(e)], capa.color, capa.ancho, z=6.5, estilo=capa.linea, info=info)
