# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Edición del diseño en el mapa, sin Qt: imán, búsqueda del objeto bajo el cursor y cambios en los datos.

Los datos son los del `…_datos.json` del servidor MCP (lotes con `contorno` y `huecos`, `fuente`, `red.matriz`,
`goteo`). Cada cambio devuelve una copia nueva de los datos: así deshacer es volver a la copia anterior.

Un objeto se nombra con una tupla: `("lote", i)`, `("matriz", i)` (la i-ésima polilínea) o `("fuente", 0)`.
Un vértice, con `(anillo, k)`; en la matriz el anillo es siempre 0.
"""

import copy
import math
from typing import Dict, List, Optional, Sequence, Tuple

Punto = Tuple[float, float]
Objeto = Tuple[str, int]

VERTICE, BORDE = "vértice", "borde"


# ------------------------------------------------------------------ sistema de coordenadas


def epsg_utm(zona: int, sur: bool) -> int:
    """EPSG de la zona UTM con datum WGS 84 (327xx al sur del ecuador, 326xx al norte)."""
    if not 1 <= int(zona) <= 60:
        raise ValueError("La zona UTM va de 1 a 60.")
    return (32700 if sur else 32600) + int(zona)


def zona_de_epsg(epsg: int):
    """(zona, sur) si el EPSG es UTM WGS 84; si no, None."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, False
    if 32701 <= epsg <= 32760:
        return epsg - 32700, True
    return None


# ------------------------------------------------------------------ geometría


def _cercano_en_segmento(p: Punto, a: Punto, b: Punto) -> Tuple[float, Punto]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / largo2))
    c = (a[0] + t * dx, a[1] + t * dy)
    return math.dist(p, c), c


def dentro(p: Punto, anillo: Sequence[Punto]) -> bool:
    """Punto dentro del polígono (regla par-impar)."""
    x, y = p
    adentro = False
    n = len(anillo)
    for i in range(n):
        (x1, y1), (x2, y2) = anillo[i], anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            adentro = not adentro
    return adentro


def area(anillo: Sequence[Punto]) -> float:
    s = 0.0
    for i in range(len(anillo)):
        (x1, y1), (x2, y2) = anillo[i], anillo[(i + 1) % len(anillo)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def longitud(linea: Sequence[Punto]) -> float:
    return sum(math.dist(a, b) for a, b in zip(linea, linea[1:]))


# ------------------------------------------------------------------ acceso a los datos


def _puntos(lista) -> List[Punto]:
    return [(float(p[0]), float(p[1])) for p in lista]


def anillos_lote(lote: dict) -> List[List[Punto]]:
    """Contorno y huecos del lote (sin repetir el primer vértice al final)."""
    if "anillos" in lote:
        anillos = list(lote["anillos"])
    else:
        anillos = [lote.get("contorno") or []] + list(lote.get("huecos") or [])
    resultado = []
    for anillo in anillos:
        puntos = _puntos(anillo)
        if len(puntos) > 1 and puntos[0] == puntos[-1]:
            puntos.pop()
        resultado.append(puntos)
    return resultado


def _fijar_anillos(lote: dict, anillos: List[List[Punto]]):
    lote.pop("anillos", None)
    lote["contorno"] = [list(p) for p in anillos[0]]
    if len(anillos) > 1:
        lote["huecos"] = [[list(p) for p in a] for a in anillos[1:]]
    else:
        lote.pop("huecos", None)


def matriz(datos: dict) -> List[List[Punto]]:
    return [_puntos(linea) for linea in (datos.get("red") or {}).get("matriz") or []]


def _fijar_matriz(datos: dict, lineas: List[List[Punto]]):
    red = datos.setdefault("red", {})
    if lineas:
        red["matriz"] = [[list(p) for p in linea] for linea in lineas]
    else:
        red.pop("matriz", None)


def fuente(datos: dict) -> Optional[Punto]:
    return (float(datos["fuente"][0]), float(datos["fuente"][1])) if datos.get("fuente") else None


def vertices(datos: dict, objeto: Objeto) -> List[List[Punto]]:
    """Los anillos (lote) o la polilínea (matriz, como un solo anillo) del objeto."""
    tipo, i = objeto
    if tipo == "lote":
        return anillos_lote(datos["lotes"][i])
    if tipo == "matriz":
        return [matriz(datos)[i]]
    return [[fuente(datos)]] if fuente(datos) else []


def nombre_objeto(datos: dict, objeto: Objeto) -> str:
    tipo, i = objeto
    if tipo == "lote":
        return f"lote «{datos['lotes'][i].get('nombre', '?')}»"
    if tipo == "matriz":
        return f"tramo {i + 1} de la tubería matriz"
    return "fuente de agua"


# ------------------------------------------------------------------ imán y búsqueda


def puntos_iman(datos: dict) -> List[Punto]:
    puntos = [p for lote in datos.get("lotes", []) for anillo in anillos_lote(lote) for p in anillo]
    puntos += [p for linea in matriz(datos) for p in linea]
    if fuente(datos):
        puntos.append(fuente(datos))
    return puntos


def segmentos_iman(datos: dict) -> List[Tuple[Punto, Punto]]:
    segmentos = []
    for lote in datos.get("lotes", []):
        for anillo in anillos_lote(lote):
            segmentos += [(anillo[k], anillo[(k + 1) % len(anillo)]) for k in range(len(anillo))] if len(anillo) > 1 else []
    for linea in matriz(datos):
        segmentos += list(zip(linea, linea[1:]))
    return segmentos


def imantar(p: Punto, datos: dict, tolerancia: float, puntos_extra: Sequence[Punto] = (),
            segmentos_extra: Sequence[Tuple[Punto, Punto]] = ()) -> Tuple[Punto, Optional[str]]:
    """El punto pegado al vértice más cercano (primero) o al borde más cercano, si están a menos de `tolerancia`.

    Devuelve (punto, VERTICE | BORDE | None).
    """
    mejor = None
    for q in list(puntos_extra) + puntos_iman(datos):
        d = math.dist(p, q)
        if d <= tolerancia and (mejor is None or d < mejor[0]):
            mejor = (d, q)
    if mejor:
        return mejor[1], VERTICE
    for a, b in list(segmentos_extra) + segmentos_iman(datos):
        d, c = _cercano_en_segmento(p, a, b)
        if d <= tolerancia and (mejor is None or d < mejor[0]):
            mejor = (d, c)
    if mejor:
        return mejor[1], BORDE
    return p, None


def objeto_en(datos: dict, p: Punto, tolerancia: float) -> Optional[Objeto]:
    """El objeto bajo el cursor: la fuente, luego la matriz (a menos de `tolerancia`), luego el lote más pequeño
    que contiene el punto (o cuyo borde está a menos de `tolerancia`)."""
    if fuente(datos) and math.dist(p, fuente(datos)) <= tolerancia:
        return ("fuente", 0)
    mejor = None
    for i, linea in enumerate(matriz(datos)):
        d = min((_cercano_en_segmento(p, a, b)[0] for a, b in zip(linea, linea[1:])), default=math.inf)
        if d <= tolerancia and (mejor is None or d < mejor[0]):
            mejor = (d, ("matriz", i))
    if mejor:
        return mejor[1]
    candidatos = []
    for i, lote in enumerate(datos.get("lotes", [])):
        anillos = anillos_lote(lote)
        if not anillos or len(anillos[0]) < 3:
            continue
        en_borde = any(_cercano_en_segmento(p, a[k], a[(k + 1) % len(a)])[0] <= tolerancia
                       for a in anillos for k in range(len(a)))
        adentro = dentro(p, anillos[0]) and not any(dentro(p, h) for h in anillos[1:])
        if en_borde or adentro:
            candidatos.append((area(anillos[0]), i))
    return ("lote", min(candidatos)[1]) if candidatos else None


def vertice_en(datos: dict, objeto: Objeto, p: Punto, tolerancia: float) -> Optional[Tuple[int, int]]:
    """(anillo, k) del vértice del objeto a menos de `tolerancia`, el más cercano."""
    mejor = None
    for a, anillo in enumerate(vertices(datos, objeto)):
        for k, q in enumerate(anillo):
            d = math.dist(p, q)
            if d <= tolerancia and (mejor is None or d < mejor[0]):
                mejor = (d, (a, k))
    return mejor[1] if mejor else None


def borde_en(datos: dict, objeto: Objeto, p: Punto, tolerancia: float) -> Optional[Tuple[int, int, Punto]]:
    """(anillo, k, punto) del borde del objeto a menos de `tolerancia`: el nuevo vértice iría tras el k."""
    tipo = objeto[0]
    mejor = None
    for a, anillo in enumerate(vertices(datos, objeto)):
        n = len(anillo)
        tramos = range(n) if tipo == "lote" else range(n - 1)
        for k in tramos:
            d, c = _cercano_en_segmento(p, anillo[k], anillo[(k + 1) % n])
            if d <= tolerancia and (mejor is None or d < mejor[0]):
                mejor = (d, (a, k, c))
    return mejor[1] if mejor else None


# ------------------------------------------------------------------ cambios (devuelven datos nuevos)


def nombre_libre(datos: dict, base="Lote") -> str:
    usados = {str(l.get("nombre")) for l in datos.get("lotes", [])}
    n = 1
    while f"{base} {n}" in usados:
        n += 1
    return f"{base} {n}"


def agregar_lote(datos: dict, contorno: Sequence[Punto], nombre: Optional[str] = None) -> dict:
    puntos = _puntos(contorno)
    if len(puntos) > 1 and puntos[0] == puntos[-1]:
        puntos.pop()
    if len(puntos) < 3 or area(puntos) <= 1e-6:
        raise ValueError("El lote necesita al menos tres vértices que encierren un área.")
    nuevo = copy.deepcopy(datos)
    nombre = nombre or nombre_libre(nuevo)
    if any(str(l.get("nombre")) == nombre for l in nuevo.get("lotes", [])):
        raise ValueError(f"Ya hay un lote llamado «{nombre}».")
    nuevo.setdefault("lotes", []).append({"nombre": nombre, "contorno": [list(p) for p in puntos]})
    return nuevo


def agregar_lotes(datos: dict, lotes: Sequence[dict]) -> dict:
    """Varios lotes de golpe (importados de un DXF): {"nombre" o None, "contorno", "huecos"?}.

    Un nombre que ya existe pasa a «nombre (2)»; sin nombre, «Lote n»."""
    nuevo = copy.deepcopy(datos)
    lista = nuevo.setdefault("lotes", [])
    usados = {str(l.get("nombre")) for l in lista}
    for lote in lotes:
        anillos = anillos_lote(lote)
        if not anillos or len(anillos[0]) < 3 or area(anillos[0]) <= 1e-6:
            continue
        base = str(lote.get("nombre") or "").strip()
        if not base:
            nombre = nombre_libre(nuevo)
        else:
            nombre, n = base, 2
            while nombre in usados:
                nombre, n = f"{base} ({n})", n + 1
        usados.add(nombre)
        agregado = {"nombre": nombre}
        _fijar_anillos(agregado, [a for a in anillos if len(a) >= 3])
        lista.append(agregado)
    return nuevo


def fijar_fuente(datos: dict, p: Punto) -> dict:
    """Una sola fuente: la nueva reemplaza a la anterior (como «Water Supply» de IRRICAD)."""
    nuevo = copy.deepcopy(datos)
    nuevo["fuente"] = [float(p[0]), float(p[1])]
    return nuevo


def agregar_matriz(datos: dict, linea: Sequence[Punto]) -> dict:
    puntos = _puntos(linea)
    puntos = [q for k, q in enumerate(puntos) if k == 0 or q != puntos[k - 1]]
    if len(puntos) < 2:
        raise ValueError("La tubería matriz necesita al menos dos puntos distintos.")
    nuevo = copy.deepcopy(datos)
    _fijar_matriz(nuevo, matriz(nuevo) + [puntos])
    return nuevo


def mover_vertice(datos: dict, objeto: Objeto, vertice: Tuple[int, int], p: Punto) -> dict:
    nuevo = copy.deepcopy(datos)
    tipo, i = objeto
    a, k = vertice
    if tipo == "fuente":
        nuevo["fuente"] = [float(p[0]), float(p[1])]
    elif tipo == "lote":
        anillos = anillos_lote(nuevo["lotes"][i])
        anillos[a][k] = (float(p[0]), float(p[1]))
        _fijar_anillos(nuevo["lotes"][i], anillos)
    else:
        lineas = matriz(nuevo)
        lineas[i][k] = (float(p[0]), float(p[1]))
        _fijar_matriz(nuevo, lineas)
    return nuevo


def insertar_vertice(datos: dict, objeto: Objeto, anillo: int, despues_de: int, p: Punto) -> dict:
    nuevo = copy.deepcopy(datos)
    tipo, i = objeto
    q = (float(p[0]), float(p[1]))
    if tipo == "lote":
        anillos = anillos_lote(nuevo["lotes"][i])
        anillos[anillo].insert(despues_de + 1, q)
        _fijar_anillos(nuevo["lotes"][i], anillos)
    elif tipo == "matriz":
        lineas = matriz(nuevo)
        lineas[i].insert(despues_de + 1, q)
        _fijar_matriz(nuevo, lineas)
    return nuevo


def borrar_vertice(datos: dict, objeto: Objeto, vertice: Tuple[int, int]) -> dict:
    tipo, i = objeto
    a, k = vertice
    minimo = 3 if tipo == "lote" else 2
    actuales = vertices(datos, objeto)[a]
    if len(actuales) <= minimo:
        raise ValueError(f"No se puede quitar el vértice: el {nombre_objeto(datos, objeto)} quedaría con menos de "
                         f"{minimo}.")
    nuevo = copy.deepcopy(datos)
    if tipo == "lote":
        anillos = anillos_lote(nuevo["lotes"][i])
        del anillos[a][k]
        _fijar_anillos(nuevo["lotes"][i], anillos)
    else:
        lineas = matriz(nuevo)
        del lineas[i][k]
        _fijar_matriz(nuevo, lineas)
    return nuevo


def borrar(datos: dict, objeto: Objeto) -> dict:
    nuevo = copy.deepcopy(datos)
    tipo, i = objeto
    if tipo == "fuente":
        nuevo.pop("fuente", None)
    elif tipo == "matriz":
        lineas = matriz(nuevo)
        del lineas[i]
        _fijar_matriz(nuevo, lineas)
    else:
        nombre = nuevo["lotes"][i].get("nombre")
        del nuevo["lotes"][i]
        red = nuevo.get("red") or {}
        if nombre in (red.get("turnos_fijos") or {}):
            del red["turnos_fijos"][nombre]
            if not red["turnos_fijos"]:
                del red["turnos_fijos"]
    return nuevo


def cambiar_lote(datos: dict, indice: int, cambios: Dict[str, object]) -> dict:
    """Cambia los parámetros propios de un lote; un valor None quita el parámetro (vale el del proyecto).

    «nombre» renombra el lote (y su turno fijo); «turno» fija su turno (None: automático).
    """
    nuevo = copy.deepcopy(datos)
    lote = nuevo["lotes"][indice]
    red = nuevo.setdefault("red", {})
    fijos = dict(red.get("turnos_fijos") or {})
    anterior = str(lote.get("nombre"))
    cambios = dict(cambios)
    if "nombre" in cambios:
        nombre = str(cambios.pop("nombre") or "").strip()
        if not nombre:
            raise ValueError("El lote necesita un nombre.")
        if nombre != anterior:
            if any(str(l.get("nombre")) == nombre for j, l in enumerate(nuevo["lotes"]) if j != indice):
                raise ValueError(f"Ya hay un lote llamado «{nombre}».")
            lote["nombre"] = nombre
            if anterior in fijos:
                fijos[nombre] = fijos.pop(anterior)
    if "turno" in cambios:
        turno = cambios.pop("turno")
        if turno:
            fijos[str(lote["nombre"])] = int(turno)
        else:
            fijos.pop(str(lote["nombre"]), None)
    for clave, valor in cambios.items():
        if valor is None:
            lote.pop(clave, None)
        else:
            lote[clave] = valor
    if fijos:
        red["turnos_fijos"] = fijos
    else:
        red.pop("turnos_fijos", None)
    return nuevo


def cambiar_goteo(datos: dict, cambios: Dict[str, object]) -> dict:
    """Valores del bloque de goteo de todo el proyecto («goteo»); None quita el valor."""
    nuevo = copy.deepcopy(datos)
    goteo = nuevo.setdefault("goteo", {})
    for clave, valor in cambios.items():
        if valor is None:
            goteo.pop(clave, None)
        else:
            goteo[clave] = valor
    return nuevo


def fijar_turnos(datos: dict, turnos: int, fijos: Optional[Dict[str, int]] = None) -> dict:
    """Número de turnos y turnos fijos por lote (los demás se reparten solos por caudal)."""
    if int(turnos) < 1:
        raise ValueError("Debe haber al menos un turno.")
    nuevo = copy.deepcopy(datos)
    red = nuevo.setdefault("red", {})
    red["turnos"] = int(turnos)
    if fijos is not None:
        fijos = {str(k): int(v) for k, v in fijos.items() if v}
        fuera = [k for k, v in fijos.items() if not 1 <= v <= int(turnos)]
        if fuera:
            raise ValueError("Turnos fijos fuera de rango: " + ", ".join(fuera))
        if fijos:
            red["turnos_fijos"] = fijos
        else:
            red.pop("turnos_fijos", None)
    return nuevo
