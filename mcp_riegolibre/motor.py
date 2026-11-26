# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Diseño completo de un proyecto de riego por goteo con el núcleo de RiegoLibre, sin QGIS.

Recorre los mismos pasos que el complemento en el mapa:

1. cada lote se traza como un bloque de goteo (`nucleo.bloque`), y si se pide se subdivide antes
   (`nucleo.subdivision`);
2. cada bloque se calcula como subunidad y se elige el diámetro del portalateral (`nucleo.subunidad`);
3. las válvulas se reparten en turnos y se unen a la tubería matriz dibujada (`nucleo.conector_valvulas`,
   como «Valve Connector» de IRRICAD; la matriz no se traza sola, igual que en el complemento);
4. se dimensiona la red y se calcula la bomba (`nucleo.red`);
5. se arma el resumen, la memoria de cálculo y el GeoJSON.

Aquí no se hace ningún cálculo hidráulico propio: todo sale de `riegolibre.nucleo`. Este módulo solo
convierte los datos de entrada (un diccionario JSON) en objetos del núcleo y junta los resultados.
Las coordenadas van en metros, en un sistema proyectado (por ejemplo UTM).
"""

import json
import math
import os
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from riegolibre.nucleo import (ConexionLateral, CriteriosDiseno, CriteriosRed, DatosBomba,  # noqa: E402
                               DatosMemoria, Lateral, Red, TramoRed, Valvula, cargar_catalogo_emisores,
                               cargar_catalogo_tuberias, dimensionar_red, disenar_subunidad, longitud_maxima,
                               memoria_html, punto_bomba, resumen_red, resumen_subunidad,
                               subunidad_desde_conexiones)
from riegolibre.nucleo.base_datos import cintas_activas  # noqa: E402
from riegolibre.nucleo.bloque import Bloque, ParametrosBloque, distancia_sobre_polilinea, trazar_bloque  # noqa: E402
from riegolibre.nucleo.conector_valvulas import conectar_valvulas, punto_mas_cercano  # noqa: E402
from riegolibre.nucleo.memoria import descripcion_telescopico  # noqa: E402
from riegolibre.nucleo.red import bomba_critica  # noqa: E402
from riegolibre.nucleo.subdivision import AUTO_AREA, AUTO_CAUDAL, AUTO_NUMERO, ParametrosSubdivision, subdividir  # noqa: E402
from riegolibre.nucleo.subunidad import incumplimientos  # noqa: E402

Punto = Tuple[float, float]
Anillo = List[Punto]

REPARTO_VARIACION_LATERAL = 0.55  # como en el complemento: 55 % de la variación para los laterales
TOLERANCIA_CONEXION_M = 0.05

# Valores por omisión del goteo (todos se pueden cambiar en «goteo» o en cada lote)
GOTEO_POR_OMISION = {
    "emisor": None,  # nombre (o parte del nombre) de un emisor del catálogo
    "tuberia_lateral": None,  # nombre (o parte) de la manguera del lateral
    "cinta": None,  # o un lateral con gotero integrado de la base de datos (reemplaza emisor y manguera)
    "espaciamiento_emisores_m": None,  # obligatorio salvo con «cinta»
    "primer_emisor_m": None,  # por omisión, medio espaciamiento
    "separacion_hileras_m": None,  # obligatorio
    "laterales_por_hilera": 1,
    "separacion_en_hilera_m": 1.0,
    "cabecera_m": 0.5,
    "costados_m": None,
    "azimut_laterales_deg": None,  # None: dirección automática
    "portalateral": "inicio",  # inicio, final, centro, distancia, alto, bajo
    "distancia_portalateral_m": 0.0,
    "valvula": "auto",  # auto, alto, bajo, inicio, final, centro, porcentaje
    "porcentaje_valvula": 50.0,
    "variacion_caudal_max_pct": 10.0,
    "velocidad_max_portalateral_ms": 1.5,
    "presion_entrada_max_m": None,
    "diametros_max_portalateral": 2,  # 1: un solo diámetro; 2 o 3: telescópico
    "tuberia_portalateral": None,  # None: la menor que cumple
    "metodo": "darcy",  # darcy o hazen
    "subdivision": None,  # {"longitud_max_lateral_m": …, "caudal_max_m3h" | "area_max_ha" | "numero": …}
}

RED_POR_OMISION = {
    "matriz": None,  # tubería matriz dibujada: lista de polilíneas [[x, y], ...]; una debe pasar por la fuente
    "largo_max_conector_m": 100.0,  # tramo más largo para unir una válvula a la matriz
    "tolerancia_m": 0.5,  # distancia a la que dos puntos se consideran el mismo nodo
    "turnos": 1,
    "velocidad_max_ms": 1.5,
    "presion_min_m": 2.0,
    "factor_perdidas_menores": 0.10,
    "perdida_valvula_m": 0.0,
    "perdidas_cabezal_m": 7.0,
    "altura_succion_m": 2.0,
    "eficiencia_bomba": 0.70,
}


# ------------------------------------------------------------------ terreno


class Terreno:
    """Cotas del terreno: plano inclinado, puntos acotados (IDW) o un DEM en ASCII Grid (.asc)."""

    def __init__(self, datos: Optional[dict]):
        self.datos = datos or {}
        self.tipo = self.datos.get("tipo", "llano" if not datos else None)
        self._cota: Optional[Callable[[float, float], Optional[float]]] = None
        if self.tipo == "llano":
            return
        if self.tipo == "plano":
            z0 = float(self.datos.get("cota_m", 100.0))
            x0, y0 = self.datos.get("origen", (0.0, 0.0))
            px, py = float(self.datos.get("pendiente_x", 0.0)), float(self.datos.get("pendiente_y", 0.0))
            self._cota = lambda x, y: z0 + px * (x - x0) + py * (y - y0)
        elif self.tipo == "puntos":
            puntos = [(float(p[0]), float(p[1]), float(p[2])) for p in self.datos["puntos"]]
            if len(puntos) < 3:
                raise ValueError("El terreno por puntos necesita al menos tres puntos acotados.")
            self._cota = _idw(puntos)
        elif self.tipo == "dem":
            self._cota = _leer_asc(self.datos["archivo"])
        else:
            raise ValueError("terreno.tipo debe ser «plano», «puntos» o «dem» (o no dar terreno: llano).")

    @property
    def tiene_cotas(self):
        return self._cota is not None

    def cota(self, x, y) -> Optional[float]:
        return None if self._cota is None else self._cota(x, y)

    def cota_o_cero(self, x, y) -> float:
        z = self.cota(x, y)
        return 0.0 if z is None else z

    def perfil(self, puntos: List[Punto], paso_m: float) -> Optional[List[Tuple[float, float]]]:
        """[(distancia, cota)] a lo largo de una polilínea; None si no hay cotas en toda ella."""
        if self._cota is None:
            return None
        largo = sum(math.dist(a, b) for a, b in zip(puntos, puntos[1:]))
        if largo <= 0:
            return None
        n = max(2, int(math.ceil(largo / paso_m)) + 1)
        perfil = []
        for i in range(n):
            d = largo * i / (n - 1)
            x, y = _punto_en(puntos, d)
            z = self._cota(x, y)
            if z is None:
                return None
            perfil.append((d, z))
        return perfil

    def gradiente(self, anillos: List[Anillo], lado=20) -> Optional[Tuple[float, float]]:
        """Pendiente media (dz/dx, dz/dy) ajustando un plano a cotas dentro del lote."""
        if self._cota is None:
            return None
        xs = [p[0] for a in anillos for p in a]
        ys = [p[1] for a in anillos for p in a]
        muestras = []
        for i in range(lado):
            for j in range(lado):
                x = min(xs) + (max(xs) - min(xs)) * (i + 0.5) / lado
                y = min(ys) + (max(ys) - min(ys)) * (j + 0.5) / lado
                if _dentro(anillos, (x, y)):
                    z = self._cota(x, y)
                    if z is not None:
                        muestras.append((x, y, z))
        if len(muestras) < 6:
            return None
        n = len(muestras)
        mx, my, mz = (sum(p[k] for p in muestras) / n for k in range(3))
        sxx = sum((p[0] - mx) ** 2 for p in muestras)
        syy = sum((p[1] - my) ** 2 for p in muestras)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in muestras)
        sxz = sum((p[0] - mx) * (p[2] - mz) for p in muestras)
        syz = sum((p[1] - my) * (p[2] - mz) for p in muestras)
        det = sxx * syy - sxy * sxy
        if abs(det) < 1e-9:
            return None
        return (sxz * syy - syz * sxy) / det, (syz * sxx - sxz * sxy) / det


def _idw(puntos, potencia=2.0, vecinos=12):
    def cota(x, y):
        cercanos = sorted(((math.hypot(px - x, py - y), z) for px, py, z in puntos))[:vecinos]
        if cercanos[0][0] < 1e-6:
            return cercanos[0][1]
        pesos = [(1 / d ** potencia, z) for d, z in cercanos]
        return sum(w * z for w, z in pesos) / sum(w for w, _ in pesos)
    return cota


def _leer_asc(ruta):
    """DEM en formato ESRI ASCII Grid (QGIS lo exporta con «Guardar como… → Arc/Info ASCII Grid»)."""
    cabecera, valores = {}, []
    with open(ruta, encoding="utf-8") as archivo:
        for linea in archivo:
            partes = linea.split()
            if not partes:
                continue
            if partes[0][0].isalpha() and not valores:  # ncols, nrows, xllcorner…, NODATA_value
                cabecera[partes[0].lower()] = float(partes[1])
            else:
                valores.extend(float(v) for v in partes)
    ncols, nrows, celda = int(cabecera["ncols"]), int(cabecera["nrows"]), cabecera["cellsize"]
    sin_dato = cabecera.get("nodata_value", -9999.0)
    if "xllcenter" in cabecera:
        x0, y0 = cabecera["xllcenter"], cabecera["yllcenter"]
    else:
        x0, y0 = cabecera["xllcorner"] + celda / 2, cabecera["yllcorner"] + celda / 2
    if len(valores) != ncols * nrows:
        raise ValueError(f"El DEM {ruta} tiene {len(valores)} valores; se esperaban {ncols * nrows}.")

    def valor(i, j):  # i columna, j fila desde abajo
        v = valores[(nrows - 1 - j) * ncols + i]
        return None if v == sin_dato else v

    def cota(x, y):
        fx, fy = (x - x0) / celda, (y - y0) / celda
        i, j = int(math.floor(fx)), int(math.floor(fy))
        if not (0 <= i < ncols - 1 and 0 <= j < nrows - 1):
            if 0 <= round(fx) < ncols and 0 <= round(fy) < nrows:
                return valor(int(round(fx)), int(round(fy)))
            return None
        tx, ty = fx - i, fy - j
        esquinas = [valor(i, j), valor(i + 1, j), valor(i, j + 1), valor(i + 1, j + 1)]
        if any(v is None for v in esquinas):
            return valor(int(round(fx)), int(round(fy)))
        a, b, c, d = esquinas
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    return cota


# ------------------------------------------------------------------ geometría


def _punto_en(puntos, distancia):
    restante = max(0.0, distancia)
    for a, b in zip(puntos, puntos[1:]):
        tramo = math.dist(a, b)
        if restante <= tramo:
            t = 0.0 if tramo == 0 else restante / tramo
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        restante -= tramo
    return puntos[-1]


def _dentro(anillos, p):
    """Regla par-impar con todos los anillos (los huecos restan)."""
    x, y = p
    dentro = False
    for anillo in anillos:
        for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                dentro = not dentro
    return dentro


def _area(anillo):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(anillo, anillo[1:] + anillo[:1]))) / 2


def _recortar(anillo: Anillo, rectangulo: Anillo) -> Anillo:
    """Sutherland-Hodgman: el anillo recortado por un polígono convexo (el rectángulo de un sub-bloque)."""
    orientacion = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(rectangulo, rectangulo[1:] + rectangulo[:1]))
    signo = 1 if orientacion > 0 else -1

    def adentro(p, a, b):
        return signo * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) >= -1e-9

    def cruce(p, q, a, b):
        dx1, dy1 = q[0] - p[0], q[1] - p[1]
        dx2, dy2 = b[0] - a[0], b[1] - a[1]
        den = dx1 * dy2 - dy1 * dx2
        if abs(den) < 1e-12:
            return q
        t = ((a[0] - p[0]) * dy2 - (a[1] - p[1]) * dx2) / den
        return p[0] + t * dx1, p[1] + t * dy1

    salida = list(anillo)
    for a, b in zip(rectangulo, rectangulo[1:] + rectangulo[:1]):
        entrada, salida = salida, []
        if not entrada:
            break
        previo = entrada[-1]
        for actual in entrada:
            if adentro(actual, a, b):
                if not adentro(previo, a, b):
                    salida.append(cruce(previo, actual, a, b))
                salida.append(actual)
            elif adentro(previo, a, b):
                salida.append(cruce(previo, actual, a, b))
            previo = actual
    return salida


def _anillos_de(lote: dict) -> List[Anillo]:
    if "anillos" in lote:
        anillos = lote["anillos"]
    elif "contorno" in lote:
        anillos = [lote["contorno"]] + list(lote.get("huecos", []))
    else:
        raise ValueError(f"El lote «{lote.get('nombre', '?')}» no tiene «contorno» (lista de [x, y]).")
    resultado = []
    for anillo in anillos:
        puntos = [(float(p[0]), float(p[1])) for p in anillo]
        if len(puntos) > 1 and puntos[0] == puntos[-1]:
            puntos.pop()
        if len(puntos) >= 3:
            resultado.append(puntos)
    if not resultado:
        raise ValueError(f"El contorno del lote «{lote.get('nombre', '?')}» necesita al menos tres vértices.")
    return resultado


# ------------------------------------------------------------------ catálogo


def _buscar(lista, texto, que):
    """El objeto cuyo nombre es `texto`, o el único que lo contiene (sin distinguir mayúsculas)."""
    exactos = [o for o in lista if o.nombre == texto]
    if exactos:
        return exactos[0]
    t = texto.lower()
    parecidos = [o for o in lista if t in o.nombre.lower()]
    if len(parecidos) == 1:
        return parecidos[0]
    if not parecidos:
        raise ValueError(f"{que} «{texto}» no está en el catálogo. Use la herramienta del catálogo para ver los nombres.")
    raise ValueError(f"{que} «{texto}» es ambiguo: " + "; ".join(o.nombre for o in parecidos[:8]))


def catalogo() -> dict:
    """Emisores y tuberías disponibles (los de la base de datos del usuario, si la importó)."""
    def tubos(uso):
        return [{"nombre": t.nombre, "material": t.material, "dn_mm": t.diametro_nominal_mm,
                 "di_mm": t.diametro_interior_mm, "pn_m": t.presion_nominal_m}
                for t in cargar_catalogo_tuberias(uso=uso)]
    cintas = cintas_activas()
    return {
        "emisores": [{"nombre": e.nombre, "caudal_lh": e.caudal_nominal_lh, "autocompensado": e.autocompensado,
                      "exponente": e.exponente, "presion_nominal_m": e.presion_nominal_m,
                      "presion_min_m": e.presion_min_m, "presion_max_m": e.presion_max_m}
                     for e in cargar_catalogo_emisores()],
        "tuberias_lateral": tubos("lateral"),
        "tuberias_portalateral": tubos("portalateral"),
        "tuberias_principal": tubos("principal"),
        "cintas": [{"nombre": c.nombre, "caudal_lh": round(c.caudal_nominal_lh, 3),
                    "espaciamiento_m": c.espaciamiento_m, "di_mm": c.diametro_interior_mm,
                    "autocompensado": c.autocompensado} for c in cintas.values()],
        "valores_por_omision": {"goteo": GOTEO_POR_OMISION, "red": RED_POR_OMISION},
    }


# ------------------------------------------------------------------ subunidades


@dataclass
class Subunidad:
    nombre: str
    lote: str
    anillos: List[Anillo]
    bloque: Bloque
    diseno: object
    criterios: CriteriosDiseno
    config: dict
    metodo: str
    avisos: List[str]
    turno: int = 1

    @property
    def caudal_lh(self):
        return self.diseno.resultado.caudal_total_lh

    @property
    def presion_valvula_m(self):
        return self.diseno.resultado.presion_entrada_m

    @property
    def motivos(self):
        return incumplimientos(self.diseno.resultado, self.criterios, self.diseno.tuberia)

    def resumen(self) -> dict:
        r = self.diseno.resultado
        b = self.bloque
        return {
            "nombre": self.nombre, "lote": self.lote, "turno": self.turno,
            "area_ha": round(b.area_regada_m2 / 10000, 3),
            "hileras": b.hileras, "laterales": len(b.laterales),
            "lateral_mas_largo_m": round(b.lateral_mas_largo_m, 1),
            "azimut_laterales_deg": round(b.azimut_laterales_grados, 1),
            "portalateral_m": round(b.longitud_portalateral_m, 1),
            "portalateral": (descripcion_telescopico(self.diseno) if self.diseno.telescopico
                             else self.diseno.tuberia.nombre),
            "valvula_xy": [round(c, 2) for c in b.valvula],
            "caudal_m3h": round(r.caudal_total_lh / 1000, 3),
            "presion_valvula_m": round(r.presion_entrada_m, 2),
            "presion_emisor_min_m": round(r.presion_min_emisor_m, 2),
            "presion_emisor_max_m": round(r.presion_max_emisor_m, 2),
            "variacion_caudal_pct": round(r.variacion_caudal * 100, 2),
            "velocidad_max_ms": round(r.velocidad_max_ms, 2),
            "cumple": not self.motivos, "motivos": self.motivos,
            "avisos": self.avisos + list(self.diseno.avisos),
        }


def _config_goteo(goteo: dict, lote: dict) -> dict:
    c = dict(GOTEO_POR_OMISION)
    c.update({k: v for k, v in goteo.items() if v is not None})
    c.update({k: v for k, v in lote.items() if k in GOTEO_POR_OMISION and v is not None})
    desconocidas = set(goteo) - set(GOTEO_POR_OMISION)
    if desconocidas:
        raise ValueError("Claves de «goteo» desconocidas: " + ", ".join(sorted(desconocidas)))
    return c


def _lateral_y_emisor(c: dict):
    if c["cinta"]:
        cinta = _buscar(list(cintas_activas().values()), c["cinta"], "La cinta")
        espaciamiento = float(c["espaciamiento_emisores_m"] or cinta.espaciamiento_m)
        return cinta.tuberia(), cinta.emisor(), espaciamiento
    if not c["emisor"] or not c["tuberia_lateral"]:
        raise ValueError("Indique «emisor» y «tuberia_lateral» (o una «cinta» de la base de datos).")
    if not c["espaciamiento_emisores_m"]:
        raise ValueError("Falta «espaciamiento_emisores_m».")
    emisor = _buscar(cargar_catalogo_emisores(), c["emisor"], "El emisor")
    tuberia = _buscar(cargar_catalogo_tuberias(uso="lateral"), c["tuberia_lateral"], "La tubería lateral")
    return tuberia, emisor, float(c["espaciamiento_emisores_m"])


def _caudal_lateral(emisor, espaciamiento, primero):
    def caudal(longitud_m):
        if longitud_m < primero:
            return 0.0
        return (int((longitud_m - primero) / espaciamiento + 1e-9) + 1) * emisor.caudal_nominal_lh
    return caudal


def _parametros_bloque(c: dict, emisor, espaciamiento, primero, angulo=None) -> ParametrosBloque:
    if not c["separacion_hileras_m"]:
        raise ValueError("Falta «separacion_hileras_m».")
    if angulo is None and c["azimut_laterales_deg"] is not None:
        angulo = (90.0 - float(c["azimut_laterales_deg"])) % 360.0
    return ParametrosBloque(
        separacion_m=float(c["separacion_hileras_m"]), laterales_por_hilera=int(c["laterales_por_hilera"]),
        separacion_en_hilera_m=float(c["separacion_en_hilera_m"]), cabecera_m=float(c["cabecera_m"]),
        costados_m=None if c["costados_m"] is None else float(c["costados_m"]), angulo_deg=angulo,
        portalateral=c["portalateral"], distancia_portalateral_m=float(c["distancia_portalateral_m"]),
        valvula=c["valvula"], porcentaje_valvula=float(c["porcentaje_valvula"]),
        caudal_lateral=_caudal_lateral(emisor, espaciamiento, primero))


def _calcular(nombre, lote, anillos, bloque, c, tuberia_lat, emisor, espaciamiento, primero, terreno,
              avisos) -> Subunidad:
    metodo = c["metodo"]
    criterios = CriteriosDiseno(variacion_caudal_max=float(c["variacion_caudal_max_pct"]) / 100,
                                velocidad_max_ms=float(c["velocidad_max_portalateral_ms"]),
                                presion_entrada_max_m=c["presion_entrada_max_m"])
    paso = max(espaciamiento, 1.0)
    unicos, conexiones, descartados = {}, [], 0
    for lat in sorted(bloque.laterales, key=lambda lat: lat.distancia_m):
        perfil = terreno.perfil([lat.inicio, lat.fin], paso)
        clave = (round(lat.longitud_m, 2),
                 tuple((round(d, 1), round(z - perfil[0][1], 2)) for d, z in perfil) if perfil else None)
        if clave not in unicos:
            unicos[clave] = (None if lat.longitud_m < primero else Lateral.desde_longitud(
                tuberia_lat, emisor, espaciamiento, lat.longitud_m, distancia_primer_emisor_m=primero,
                perfil=perfil, metodo=metodo))
        lateral = unicos[clave]
        if lateral is None:
            descartados += 1
            continue
        if conexiones and abs(conexiones[-1].distancia_m - lat.distancia_m) <= TOLERANCIA_CONEXION_M:
            conexiones[-1].laterales.append(lateral)
        else:
            conexiones.append(ConexionLateral(lat.distancia_m, [lateral]))
    if not conexiones:
        raise ValueError(f"«{nombre}»: todos los laterales son más cortos que la distancia al primer emisor.")
    if descartados:
        avisos.append(f"{descartados} laterales más cortos que la distancia al primer emisor no se calcularon.")
    if not terreno.tiene_cotas:
        avisos.append("Sin cotas: se calculó con el terreno llano.")
    perfil_porta = terreno.perfil(bloque.portalateral, paso)

    def construir(tuberia, reducciones=()):
        return subunidad_desde_conexiones(tuberia, conexiones, bloque.valvula_m, perfil=perfil_porta,
                                          metodo=metodo, reducciones=reducciones)

    tubos = cargar_catalogo_tuberias(uso="portalateral")
    fija = _buscar(tubos, c["tuberia_portalateral"], "La tubería del portalateral") if c["tuberia_portalateral"] else None
    diseno = disenar_subunidad(construir, tubos, criterios, tuberia_fija=fija,
                               diametros_max=int(c["diametros_max_portalateral"]))
    return Subunidad(nombre, lote, anillos, bloque, diseno, criterios, c, metodo, avisos)


def disenar_lote(lote: dict, goteo: dict, terreno: Terreno, fuente: Optional[Punto]) -> List[Subunidad]:
    """Bloque(s) de goteo de un lote, ya calculados. Con «subdivision» el lote se parte en sub-bloques."""
    nombre = str(lote.get("nombre") or "Lote")
    anillos = _anillos_de(lote)
    c = _config_goteo(goteo, lote)
    tuberia_lat, emisor, espaciamiento = _lateral_y_emisor(c)
    primero = float(c["primer_emisor_m"] if c["primer_emisor_m"] is not None else espaciamiento / 2)

    pendiente = None
    gradiente = terreno.gradiente(anillos)
    if gradiente is not None:
        def pendiente(angulo):
            a = math.radians(angulo)
            return abs(gradiente[0] * math.cos(a) + gradiente[1] * math.sin(a))
    alcance, _ = longitud_maxima(tuberia_lat, emisor, espaciamiento, pendiente=0.0,
                                 distancia_primer_emisor_m=primero,
                                 variacion_caudal_max=float(c["variacion_caudal_max_pct"]) / 100 * REPARTO_VARIACION_LATERAL,
                                 presion_entrada_max_m=c["presion_entrada_max_m"], metodo=c["metodo"])
    params = _parametros_bloque(c, emisor, espaciamiento, primero)
    bloque = trazar_bloque(anillos, params, cota=terreno.cota if terreno.tiene_cotas else None, fuente=fuente,
                           pendiente=pendiente, alcance_m=alcance or None)

    sub = c["subdivision"]
    if not sub:
        return [_calcular(nombre, nombre, anillos, bloque, c, tuberia_lat, emisor, espaciamiento, primero, terreno,
                          list(bloque.avisos))]

    # Subdivisión automática, con la dirección que se eligió para el lote entero
    if "caudal_max_m3h" in sub:
        criterio, extra = AUTO_CAUDAL, {"caudal_max": float(sub["caudal_max_m3h"]) * 1000}
    elif "area_max_ha" in sub:
        criterio, extra = AUTO_AREA, {"area_max_m2": float(sub["area_max_ha"]) * 10000}
    elif "numero" in sub:
        criterio, extra = AUTO_NUMERO, {"numero": int(sub["numero"])}
    else:
        criterio, extra = AUTO_CAUDAL, {"caudal_max": 1e12}  # solo cortes por largo de lateral
    psub = ParametrosSubdivision(automatica=True, criterio=criterio,
                                 longitud_max_lateral_m=float(sub.get("longitud_max_lateral_m", 1e6)),
                                 cortes_hueco_m=float(sub.get("hueco_m", 0.0)), **extra)
    partes = subdividir(anillos, params, bloque.angulo_deg, psub)
    fijo = replace(params, angulo_deg=bloque.angulo_deg)
    resultado = []
    for i, parte in enumerate(partes, 1):
        recortes = [r for r in (_recortar(a, parte.anillo) for a in anillos) if len(r) >= 3 and _area(r) >= 1.0]
        if not recortes:
            continue
        nombre_parte = f"{nombre}-{i}"
        try:
            b = trazar_bloque(recortes, fijo, cota=terreno.cota if terreno.tiene_cotas else None, fuente=fuente)
        except ValueError:
            continue
        resultado.append(_calcular(nombre_parte, nombre, recortes, b, c, tuberia_lat, emisor, espaciamiento,
                                   primero, terreno, list(b.avisos)))
    if not resultado:
        raise ValueError(f"La subdivisión del lote «{nombre}» no dejó ningún sub-bloque con laterales.")
    return resultado


# ------------------------------------------------------------------ red principal


def repartir_turnos(subunidades: List[Subunidad], turnos: int, fijos: Dict[str, int]):
    """Cada válvula al turno con menos caudal (de la mayor a la menor), salvo las que tienen turno fijo."""
    carga = {t: 0.0 for t in range(1, turnos + 1)}
    for s in subunidades:
        if s.nombre in fijos or s.lote in fijos:
            s.turno = int(fijos.get(s.nombre, fijos.get(s.lote)))
            carga[s.turno] = carga.get(s.turno, 0.0) + s.caudal_lh
    for s in sorted((s for s in subunidades if s.nombre not in fijos and s.lote not in fijos),
                    key=lambda s: -s.caudal_lh):
        s.turno = min(carga, key=lambda t: (carga[t], t))
        carga[s.turno] += s.caudal_lh


@dataclass
class RedCalculada:
    conexion: object  # ResultadoConexion: tramos válvula-matriz agregados
    red: Red
    resultado: object
    bombas: list
    datos_bomba: DatosBomba
    puntos: Dict[str, Punto]
    geometrias: Dict[str, List[Punto]] = field(default_factory=dict)
    capas: Dict[str, str] = field(default_factory=dict)  # tramo -> «matriz» o «conector»


def _subpolilinea(puntos: List[Punto], a: float, b: float) -> List[Punto]:
    """Trozo de la polilínea entre las distancias a < b desde su inicio."""
    trozo, recorrido = [_punto_en(puntos, a)], 0.0
    for p, q in zip(puntos, puntos[1:]):
        recorrido += math.dist(p, q)
        if a < recorrido < b:
            trozo.append(q)
    trozo.append(_punto_en(puntos, b))
    return trozo


def disenar_red(subunidades: List[Subunidad], fuente: Punto, cfg: dict, terreno: Terreno) -> RedCalculada:
    """Une las válvulas a la matriz dibujada, corta la matriz en los nodos y dimensiona la red."""
    if not cfg.get("matriz"):
        raise ValueError("Falta «red.matriz»: la tubería matriz se dibuja (como «Mainline Pipe» de IRRICAD). "
                         "Dé una o más polilíneas [[x, y], ...] que salgan de la fuente y pasen cerca de las válvulas.")
    tolerancia = float(cfg["tolerancia_m"])
    lineas = []
    for i, linea in enumerate(cfg["matriz"], 1):
        vertices = [(float(p[0]), float(p[1])) for p in linea]
        if len(vertices) < 2:
            raise ValueError(f"La línea {i} de la matriz necesita al menos dos vértices.")
        lineas.append((f"M{i}", vertices))
    distancia_fuente = min(punto_mas_cercano(v, fuente)[0] for _, v in lineas)
    if distancia_fuente > tolerancia:
        raise ValueError(f"La matriz pasa a {distancia_fuente:.1f} m de la fuente: debe empezar en ella.")
    conexion = conectar_valvulas(lineas, [(s.nombre, s.bloque.valvula) for s in subunidades],
                                 float(cfg["largo_max_conector_m"]), tolerancia)
    if conexion.fuera_de_alcance:
        raise ValueError("Válvulas demasiado lejos de la matriz (prolongue la matriz o suba largo_max_conector_m): "
                         + ", ".join(f"{v} a {d:.0f} m" for v, d in conexion.fuera_de_alcance))
    lineas += [(f"C-{c.valvula}", [c.desde, c.hasta]) for c in conexion.conectores]

    # Nodos: fuente, válvulas y extremos de las líneas (los conectores terminan sobre la matriz)
    puntos: List[Punto] = []

    def nodo_de(p):
        for i, existente in enumerate(puntos):
            if math.dist(existente, p) <= tolerancia:
                return f"N{i}"
        puntos.append(p)
        return f"N{len(puntos) - 1}"

    nodo_fuente = nodo_de(fuente)
    nodo_valvula = {s.nombre: nodo_de(s.bloque.valvula) for s in subunidades}
    for _, vertices in lineas:
        nodo_de(vertices[0])
        nodo_de(vertices[-1])

    tramos, geometrias, capas = [], {}, {}
    for id_linea, vertices in lineas:
        posiciones = set()
        for i, p in enumerate(puntos):
            distancia, separacion = distancia_sobre_polilinea(vertices, p)
            if separacion <= tolerancia:
                posiciones.add((round(distancia, 6), f"N{i}"))
        ordenadas = sorted(posiciones)
        for k, ((a, nodo_a), (b, nodo_b)) in enumerate(zip(ordenadas, ordenadas[1:]), 1):
            if b - a <= 1e-6 or nodo_a == nodo_b:
                continue
            id_tramo = f"{id_linea}.{k}"
            trozo = _subpolilinea(vertices, a, b)
            tramos.append(TramoRed(id_tramo, nodo_a, nodo_b, b - a, terreno.perfil(trozo, 5.0)))
            geometrias[id_tramo] = trozo
            capas[id_tramo] = "conector" if id_linea.startswith("C-") else "matriz"
    cotas = {f"N{i}": terreno.cota_o_cero(*p) for i, p in enumerate(puntos)}
    valvulas = [Valvula(s.nombre, nodo_valvula[s.nombre], s.caudal_lh, s.presion_valvula_m, s.turno,
                        float(cfg["perdida_valvula_m"])) for s in subunidades]
    red = Red(cotas, tramos, valvulas, nodo_fuente)
    criterios = CriteriosRed(velocidad_max_ms=float(cfg["velocidad_max_ms"]),
                             presion_min_m=float(cfg["presion_min_m"]),
                             factor_perdidas_menores=float(cfg["factor_perdidas_menores"]),
                             metodo=subunidades[0].metodo)
    resultado = dimensionar_red(red, cargar_catalogo_tuberias(uso="principal"), criterios)
    datos_bomba = DatosBomba(float(cfg["perdidas_cabezal_m"]), float(cfg["altura_succion_m"]),
                             float(cfg["eficiencia_bomba"]))
    bombas = [punto_bomba(t, datos_bomba) for t in resultado.turnos]
    return RedCalculada(conexion, red, resultado, bombas, datos_bomba, {"fuente": fuente}, geometrias, capas)


# ------------------------------------------------------------------ proyecto


@dataclass
class Proyecto:
    datos: dict
    subunidades: List[Subunidad]
    red: Optional[RedCalculada]
    terreno: Terreno
    errores: List[str]

    @property
    def nombre(self):
        return self.datos.get("nombre", "Proyecto")

    def metrados(self) -> Dict[str, float]:
        metros: Dict[str, float] = {}

        def sumar(nombre, m):
            metros[nombre] = metros.get(nombre, 0.0) + m
        for s in self.subunidades:
            tubo_lat = s.diseno.subunidad.ramas[0].conexiones[0].laterales[0].tuberia.nombre
            sumar(f"{tubo_lat} (laterales)", s.bloque.longitud_laterales_m)
            for rama in s.diseno.subunidad.ramas:
                for tuberia, a, b in rama.piezas(0.0, rama.longitud_m):
                    sumar(f"{tuberia.nombre} (portalateral)", b - a)
        if self.red is not None:
            for t in self.red.red.tramos:
                sumar(f"{self.red.resultado.asignacion[t.id].nombre} (red principal)", t.longitud_m)
        return {k: round(v, 1) for k, v in sorted(metros.items())}

    def resumen(self) -> dict:
        subs = [s.resumen() for s in self.subunidades]
        salida = {
            "proyecto": self.nombre,
            "area_regada_ha": round(sum(s.bloque.area_regada_m2 for s in self.subunidades) / 10000, 3),
            "subunidades": subs,
            "no_cumplen": [s["nombre"] for s in subs if not s["cumple"]],
            "errores": self.errores,
            "metrados_m": self.metrados(),
        }
        if self.red is not None:
            r = self.red.resultado
            critica = bomba_critica(self.red.bombas)
            salida["turnos"] = [{
                "turno": t.turno, "caudal_m3h": round(t.caudal_total_lh / 1000, 2),
                "valvulas": [s.nombre for s in self.subunidades if s.turno == t.turno],
                "presion_entrada_red_m": round(t.presion_entrada_red_m, 2), "critico": t.critico}
                for t in r.turnos]
            salida["red"] = {
                "longitud_m": round(sum(t.longitud_m for t in self.red.red.tramos), 1),
                "tramos": [{"id": t.id, "desde": t.desde, "hasta": t.hasta, "longitud_m": round(t.longitud_m, 1),
                            "tuberia": r.asignacion[t.id].nombre,
                            "caudal_m3h": round(r.peor_tramo(t.id)[0] / 1000, 2),
                            "velocidad_ms": round(max(x.tramos[t.id].velocidad_ms for x in r.turnos), 2),
                            "observaciones": r.observaciones(t.id)} for t in self.red.red.tramos],
                "no_cumplen": r.motivos, "avisos": r.avisos,
            }
            salida["bomba"] = {"turno_critico": critica.turno, "caudal_m3h": round(critica.caudal_lh / 1000, 2),
                               "cdt_m": round(critica.carga_dinamica_total_m, 2),
                               "potencia_kw": round(critica.potencia_kw, 2)}
        return salida

    def memoria_html(self) -> str:
        subs = []
        for s in self.subunidades:
            subs.append(resumen_subunidad(s.nombre, s.diseno, s.criterios, s.metodo, s.bloque.area_regada_m2,
                                          [lat.longitud_m for lat in s.bloque.laterales], None, s.avisos))
        red = None
        if self.red is not None:
            red = resumen_red(self.red.red, self.red.resultado, self.red.bombas, self.red.datos_bomba,
                              sin_dem=not self.terreno.tiene_cotas)
        datos = DatosMemoria(proyecto=self.nombre, cliente=self.datos.get("cliente", ""),
                             ubicacion=self.datos.get("ubicacion", ""), subunidades=subs, red=red,
                             avisos=list(self.errores), version="MCP (prototipo)")
        return memoria_html(datos)

    def geojson(self) -> dict:
        entidades = []

        def agregar(capa, tipo, coordenadas, **propiedades):
            entidades.append({"type": "Feature", "geometry": {"type": tipo, "coordinates": coordenadas},
                              "properties": {"capa": capa, **propiedades}})
        for s in self.subunidades:
            b = s.bloque
            agregar("bloque", "Polygon", [[list(p) for p in a + a[:1]] for a in s.anillos],
                    subunidad=s.nombre, lote=s.lote, turno=s.turno, caudal_m3h=round(s.caudal_lh / 1000, 3))
            agregar("portalateral", "LineString", [list(p) for p in b.portalateral], subunidad=s.nombre,
                    tuberia=s.resumen()["portalateral"])
            for lat in b.laterales:
                agregar("lateral", "LineString", [list(lat.inicio), list(lat.fin)], subunidad=s.nombre,
                        longitud_m=round(lat.longitud_m, 2))
            agregar("valvula", "Point", list(b.valvula), subunidad=s.nombre, turno=s.turno,
                    presion_m=round(s.presion_valvula_m, 2))
        if self.red is not None:
            agregar("fuente", "Point", list(self.red.puntos["fuente"]))
            for t in self.red.red.tramos:
                agregar(self.red.capas[t.id], "LineString", [list(p) for p in self.red.geometrias[t.id]], tramo=t.id,
                        tuberia=self.red.resultado.asignacion[t.id].nombre, longitud_m=round(t.longitud_m, 2))
        salida = {"type": "FeatureCollection", "features": entidades}
        if self.datos.get("epsg"):
            salida["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{int(self.datos['epsg'])}"}}
        return salida

    def exportar(self, carpeta: str) -> Dict[str, str]:
        os.makedirs(carpeta, exist_ok=True)
        base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.nombre) or "proyecto"
        rutas = {"geojson": os.path.join(carpeta, f"{base}.geojson"),
                 "memoria": os.path.join(carpeta, f"{base}_memoria.html"),
                 "resumen": os.path.join(carpeta, f"{base}_resumen.json"),
                 "datos": os.path.join(carpeta, f"{base}_datos.json")}
        contenidos = {"geojson": self.geojson(), "resumen": self.resumen(), "datos": self.datos}
        for clave, contenido in contenidos.items():
            with open(rutas[clave], "w", encoding="utf-8") as archivo:
                json.dump(contenido, archivo, ensure_ascii=False, indent=1)
        with open(rutas["memoria"], "w", encoding="utf-8") as archivo:
            archivo.write(self.memoria_html())
        return rutas


def lotes_de_geojson(ruta: str, campo_nombre: str = "nombre") -> List[dict]:
    """Lotes a partir de los polígonos de un GeoJSON (en metros). El nombre sale de `campo_nombre`."""
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    entidades = datos["features"] if datos.get("type") == "FeatureCollection" else [datos]
    lotes = []
    for i, entidad in enumerate(entidades, 1):
        geometria = entidad.get("geometry") or {}
        propiedades = entidad.get("properties") or {}
        poligonos = ([geometria["coordinates"]] if geometria.get("type") == "Polygon"
                     else geometria.get("coordinates", []) if geometria.get("type") == "MultiPolygon" else [])
        base = str(propiedades.get(campo_nombre) or f"Lote {i}")
        for j, anillos in enumerate(poligonos, 1):
            lotes.append({"nombre": base if len(poligonos) == 1 else f"{base}.{j}", "anillos": anillos})
    if not lotes:
        raise ValueError(f"El archivo {ruta} no tiene polígonos.")
    return lotes


def disenar_proyecto(datos: dict) -> Proyecto:
    """Diseña todo el proyecto a partir de su descripción (ver la herramienta del servidor MCP)."""
    if datos.get("lotes_geojson"):
        datos = dict(datos)
        lotes = lotes_de_geojson(datos["lotes_geojson"], datos.get("campo_nombre", "nombre"))
        ajustes = {l["nombre"]: l for l in datos.get("lotes", [])}  # parámetros propios de algunos lotes
        datos["lotes"] = [{**lote, **{k: v for k, v in ajustes.get(lote["nombre"], {}).items() if k != "nombre"}}
                          for lote in lotes]
    if not datos.get("lotes"):
        raise ValueError("El proyecto necesita al menos un lote en «lotes».")
    terreno = Terreno(datos.get("terreno"))
    fuente = tuple(datos["fuente"]) if datos.get("fuente") else None
    goteo = datos.get("goteo", {})
    subunidades, errores = [], []
    for lote in datos["lotes"]:
        try:
            subunidades.extend(disenar_lote(lote, goteo, terreno, fuente))
        except Exception as error:  # se informa y se sigue con los demás lotes
            errores.append(f"{lote.get('nombre', '?')}: {error}")
    if not subunidades:
        raise ValueError("No se pudo diseñar ningún lote: " + " | ".join(errores))
    nombres = [s.nombre for s in subunidades]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    if repetidos:
        raise ValueError("Hay lotes con el mismo nombre: " + ", ".join(sorted(repetidos)))

    red = None
    cfg = dict(RED_POR_OMISION)
    cfg.update(datos.get("red", {}))
    desconocidas = set(datos.get("red", {})) - set(RED_POR_OMISION) - {"turnos_fijos"}
    if desconocidas:
        raise ValueError("Claves de «red» desconocidas: " + ", ".join(sorted(desconocidas)))
    repartir_turnos(subunidades, max(1, int(cfg["turnos"])), dict(cfg.get("turnos_fijos", {})))
    if fuente is not None:
        try:
            red = disenar_red(subunidades, fuente, cfg, terreno)
        except Exception as error:
            errores.append(f"Red principal: {error}")
    else:
        errores.append("Sin «fuente» no se diseña la red principal ni la bomba.")
    return Proyecto(datos, subunidades, red, terreno, errores)
