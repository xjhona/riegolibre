# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Importa un diseño hecho con el servidor MCP (`mcp_riegolibre`) como capas propias del complemento.

El servidor MCP diseña un proyecto completo a partir de instrucciones y exporta, entre otros,
`<nombre>_datos.json`: los datos de entrada del diseño (lotes, goteo, terreno, fuente, red). Aquí no se
copian las geometrías que calculó el servidor: con esos mismos datos se vuelven a ejecutar las funciones del
complemento («Bloque de goteo»: `bloque_mapa.trazar_en_lote` y `calcular_bloque`), así el resultado son las
capas de siempre —lotes con sus parámetros guardados, grupo «RiegoLibre · lote» con laterales,
portalateral y válvula, «Fuente», «Matriz» y «Turnos de riego»— y todas las herramientas trabajan sobre
ellas igual que sobre un bloque hecho a mano.
"""

import json
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsProject, QgsRasterLayer, QgsVectorLayer)

from ..nucleo import PresionInsuficiente, cargar_catalogo_emisores, cargar_catalogo_tuberias
from ..nucleo.base_datos import Cinta, base_activa, cintas_activas, guardar_base, ruta_base_usuario
from ..nucleo.tuberias import clave_economica

# Valores por omisión del goteo y de la red del servidor MCP: deben ser los de `GOTEO_POR_OMISION` y
# `RED_POR_OMISION` de `mcp_riegolibre/motor.py` (el complemento se instala sin esa carpeta; una prueba
# comprueba que coinciden).
GOTEO_POR_OMISION = {
    "emisor": None, "tuberia_lateral": None, "cinta": None, "espaciamiento_emisores_m": None,
    "primer_emisor_m": None, "separacion_hileras_m": None, "laterales_por_hilera": 1,
    "separacion_en_hilera_m": 1.0, "cabecera_m": 0.5, "costados_m": None, "azimut_laterales_deg": None,
    "portalateral": "inicio", "distancia_portalateral_m": 0.0, "valvula": "auto", "porcentaje_valvula": 50.0,
    "variacion_caudal_max_pct": 10.0, "velocidad_max_portalateral_ms": 1.5, "presion_entrada_max_m": None,
    "diametros_max_portalateral": 2, "tuberia_portalateral": None, "metodo": "darcy", "subdivision": None,
}
RED_POR_OMISION = {
    "matriz": None, "largo_max_conector_m": 100.0, "tolerancia_m": 0.5, "turnos": 1, "velocidad_max_ms": 1.5,
    "presion_min_m": 2.0, "factor_perdidas_menores": 0.10, "perdida_valvula_m": 0.0, "perdidas_cabezal_m": 7.0,
    "altura_succion_m": 2.0, "eficiencia_bomba": 0.70,
}
NOMBRE_DEM = "DEM (diseño del MCP)"
CELDAS_MAX_DEM = 1_500_000  # DEM que se genera para un terreno «plano» o «puntos»


# ------------------------------------------------------------------ lectura del archivo


def _ruta_existente(ruta, carpeta):
    """La ruta tal cual o, si no existe (el proyecto se copió a otra carpeta), el archivo del mismo nombre
    junto al JSON."""
    if not ruta or os.path.exists(ruta):
        return ruta
    vecina = os.path.join(carpeta, os.path.basename(ruta.replace("\\", "/")))
    return vecina if os.path.exists(vecina) else ruta


def lotes_de_geojson(ruta: str, campo_nombre: str = "nombre") -> List[dict]:
    """Lotes a partir de los polígonos de un GeoJSON, como `lotes_de_geojson` del servidor MCP."""
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


def leer_datos(ruta: str) -> dict:
    """Lee `<nombre>_datos.json` del servidor MCP. Los lotes de `lotes_geojson` quedan en `lotes`."""
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError) as error:
        raise ValueError(f"No se pudo leer «{ruta}»: {error}") from error
    if not isinstance(datos, dict) or not isinstance(datos.get("goteo"), dict):
        raise ValueError("El archivo no es un diseño del servidor MCP: falta «goteo». Elija el "
                         "«…_datos.json» que escribe «exportar_proyecto».")
    carpeta = os.path.dirname(os.path.abspath(ruta))
    datos = dict(datos)
    if isinstance(datos.get("terreno"), dict) and datos["terreno"].get("archivo"):
        datos["terreno"] = dict(datos["terreno"], archivo=_ruta_existente(datos["terreno"]["archivo"], carpeta))
    if datos.get("lotes_geojson"):
        datos["lotes_geojson"] = _ruta_existente(datos["lotes_geojson"], carpeta)
    tienen_contorno = datos.get("lotes") and all("anillos" in l or "contorno" in l for l in datos["lotes"])
    if datos.get("lotes_geojson") and not tienen_contorno:
        if not os.path.exists(datos["lotes_geojson"]):
            raise ValueError(f"No se encuentra el archivo de lotes «{datos['lotes_geojson']}».")
        lotes = lotes_de_geojson(datos["lotes_geojson"], datos.get("campo_nombre", "nombre"))
        ajustes = {l.get("nombre"): l for l in datos.get("lotes", [])}  # parámetros propios de algunos lotes
        datos["lotes"] = [{**lote, **{k: v for k, v in ajustes.get(lote["nombre"], {}).items() if k != "nombre"}}
                          for lote in lotes]
    if not datos.get("lotes"):
        raise ValueError("El diseño no tiene lotes.")
    return datos


def anillos_del_lote(lote: dict) -> List[List[Tuple[float, float]]]:
    if "anillos" in lote:
        anillos = lote["anillos"]
    elif "contorno" in lote:
        anillos = [lote["contorno"]] + list(lote.get("huecos", []))
    else:
        raise ValueError(f"El lote «{lote.get('nombre', '?')}» no tiene contorno.")
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


# ------------------------------------------------------------------ materiales


def buscar(lista, texto, que):
    """El objeto cuyo nombre es `texto`, o el único que lo contiene (como el servidor MCP)."""
    exactos = [o for o in lista if o.nombre == texto]
    if exactos:
        return exactos[0]
    t = str(texto).lower()
    parecidos = [o for o in lista if t in o.nombre.lower()]
    if len(parecidos) == 1:
        return parecidos[0]
    if not parecidos:
        raise ValueError(f"{que} «{texto}» no está en la base de datos de materiales.")
    raise ValueError(f"{que} «{texto}» es ambiguo: " + "; ".join(o.nombre for o in parecidos[:8]))


@dataclass
class CintaDelDiseno:
    """La cinta (lateral con gotero integrado) que pide el diseño."""
    cinta: Cinta
    en_base: bool  # ya está en la base de datos activa con ese nombre
    distinta: bool = False  # está en la base, pero con otros datos


def cinta_del_diseno(datos: dict) -> Optional[CintaDelDiseno]:
    """La cinta de «goteo» (por nombre en la base de datos, o definida en el diseño), o None si no hay."""
    dato = (datos.get("goteo") or {}).get("cinta")
    if not dato:
        return None
    activas = cintas_activas()
    if not isinstance(dato, dict):
        return CintaDelDiseno(buscar(list(activas.values()), dato, "La cinta"), True)
    campos = set(Cinta.__dataclass_fields__)
    desconocidos = set(dato) - campos
    if desconocidos:
        raise ValueError("Campos de «cinta» desconocidos: " + ", ".join(sorted(desconocidos)))
    try:
        cinta = Cinta(**dato)
    except TypeError as error:
        raise ValueError(f"«cinta» incompleta: {error}") from error
    existente = activas.get(cinta.nombre)
    if existente is None:
        return CintaDelDiseno(cinta, False)
    return CintaDelDiseno(existente, True, distinta=existente != cinta)


def agregar_cinta_a_la_base(cinta: Cinta) -> str:
    """Agrega la cinta a la base de datos del usuario (la crea si no hay). Devuelve la ruta del archivo."""
    from ..nucleo.edicion_base import base_nueva, guardar_registro, validar
    base = base_activa() or base_nueva()
    errores = validar(base, "cintas", cinta)
    if errores:
        raise ValueError(f"No se pudo agregar «{cinta.nombre}» a la base de datos: " + " ".join(errores))
    guardar_registro(base, "cintas", cinta)
    ruta = ruta_base_usuario()
    guardar_base(base, ruta)
    return ruta


@dataclass
class Catalogos:
    tuberias_lateral: list
    emisores: list
    tuberias_portalateral: list

    @classmethod
    def activos(cls, cinta_solo_aqui: Optional[Cinta] = None):
        """Los de la base de datos (como la ventana «Bloque de goteo»); con `cinta_solo_aqui`, la cinta se
        suma solo para esta importación."""
        laterales = cargar_catalogo_tuberias(uso="lateral")
        emisores = cargar_catalogo_emisores()
        if cinta_solo_aqui is not None:
            laterales = [t for t in laterales if t.nombre != cinta_solo_aqui.nombre] + [cinta_solo_aqui.tuberia()]
            emisores = [e for e in emisores if e.nombre != cinta_solo_aqui.nombre] + [cinta_solo_aqui.emisor()]
        return cls(laterales, emisores, sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica))


# ------------------------------------------------------------------ parámetros del bloque


def configuracion_goteo(goteo: dict, lote: dict) -> dict:
    """«goteo» con los valores por omisión del servidor MCP y lo propio del lote encima."""
    desconocidas = set(goteo) - set(GOTEO_POR_OMISION)
    if desconocidas:
        raise ValueError("Claves de «goteo» desconocidas: " + ", ".join(sorted(desconocidas)))
    c = dict(GOTEO_POR_OMISION)
    c.update({k: v for k, v in goteo.items() if v is not None})
    c.update({k: v for k, v in lote.items() if k in GOTEO_POR_OMISION and v is not None})
    return c


def valores_del_bloque(c: dict, catalogos: Catalogos, cinta: Optional[Cinta] = None) -> dict:
    """Los valores que guarda la ventana «Bloque de goteo» en el lote (ver `DialogoBloque.valores`), a partir
    de la configuración del goteo del servidor MCP (`configuracion_goteo`)."""
    from ..integracion.bloque_mapa import DIMENSIONADO_COSTO
    if c.get("cinta"):
        if cinta is None:
            raise ValueError("Falta la cinta del diseño.")
        tuberia = buscar(catalogos.tuberias_lateral, cinta.nombre, "La cinta")
        emisor = buscar(catalogos.emisores, cinta.nombre, "La cinta")
        espaciamiento = float(c["espaciamiento_emisores_m"] or cinta.espaciamiento_m)
    else:
        if not c.get("emisor") or not c.get("tuberia_lateral"):
            raise ValueError("Falta «emisor» y «tuberia_lateral» (o una «cinta») en «goteo».")
        if not c.get("espaciamiento_emisores_m"):
            raise ValueError("Falta «espaciamiento_emisores_m» en «goteo».")
        emisor = buscar(catalogos.emisores, c["emisor"], "El emisor")
        tuberia = buscar(catalogos.tuberias_lateral, c["tuberia_lateral"], "La tubería lateral")
        espaciamiento = float(c["espaciamiento_emisores_m"])
    if not c.get("separacion_hileras_m"):
        raise ValueError("Falta «separacion_hileras_m» en «goteo».")
    separacion = float(c["separacion_hileras_m"])
    porta = None
    if c.get("tuberia_portalateral"):
        porta = buscar(catalogos.tuberias_portalateral, c["tuberia_portalateral"], "La tubería del portalateral")
    automatica = c.get("azimut_laterales_deg") is None
    presion_max = c.get("presion_entrada_max_m")
    return {
        "tuberia": tuberia.nombre, "emisor": emisor.nombre, "espaciamiento_m": espaciamiento,
        "primer_emisor_m": float(c["primer_emisor_m"] if c.get("primer_emisor_m") is not None
                                 else espaciamiento / 2),
        "separacion_m": separacion, "laterales_por_hilera": int(c["laterales_por_hilera"]),
        "separacion_en_hilera_m": float(c["separacion_en_hilera_m"]),
        "direccion": "auto" if automatica else "usuario",
        "azimut_deg": 0.0 if automatica else float(c["azimut_laterales_deg"]) % 360.0,
        "cabecera_m": float(c["cabecera_m"]),
        "costados_m": separacion / 2 if c.get("costados_m") is None else float(c["costados_m"]),
        "portalateral": c["portalateral"], "distancia_portalateral_m": float(c["distancia_portalateral_m"]),
        "tuberia_portalateral": porta.nombre if porta else None,
        "diametros_max": int(c["diametros_max_portalateral"]),
        "dimensionado": DIMENSIONADO_COSTO, "serie": None, "diametros_velocidad": 0, "tramo_min_m": 6.0,
        "ajustar_variacion": True, "dem": None, "fuente": None,
        "valvula": c["valvula"], "porcentaje_valvula": float(c["porcentaje_valvula"]),
        "prolongacion_extremo_m": 0.0, "prolongacion_valvula_m": 0.0, "ramal_valvula_m": 0.0,
        "punto_valvula": None, "puntos_portalateral": None, "presion_conocida_m": None, "metodo": c["metodo"],
        "variacion_caudal_pct": float(c["variacion_caudal_max_pct"]),
        "velocidad_max_ms": float(c["velocidad_max_portalateral_ms"]),
        "presion_entrada_max_m": None if presion_max is None else float(presion_max),
        "intensidad_max_mmh": 0.0, "lamina_mm": 0.0,
    }


def repartir_turnos(caudales: List[Tuple[str, str, float]], turnos: int, fijos: Dict[str, int]) -> Dict[str, int]:
    """{subunidad: turno}, como el servidor MCP: cada válvula al turno con menos caudal (de la mayor a la
    menor), salvo las que tienen turno fijo (por el nombre de la subunidad o el de su lote).

    `caudales`: [(subunidad, lote, caudal)].
    """
    carga = {t: 0.0 for t in range(1, max(1, int(turnos)) + 1)}
    asignados = {}
    for nombre, lote, caudal in caudales:
        if nombre in fijos or lote in fijos:
            asignados[nombre] = int(fijos.get(nombre, fijos.get(lote)))
            carga[asignados[nombre]] = carga.get(asignados[nombre], 0.0) + caudal
    for nombre, lote, caudal in sorted((x for x in caudales if x[0] not in asignados), key=lambda x: -x[2]):
        asignados[nombre] = min(carga, key=lambda t: (carga[t], t))
        carga[asignados[nombre]] += caudal
    return asignados


# ------------------------------------------------------------------ terreno


def _funcion_terreno(terreno: dict) -> Optional[Callable[[float, float], float]]:
    """Cota de un terreno «plano» o «puntos» del servidor MCP (para escribirlo como DEM)."""
    tipo = terreno.get("tipo")
    if tipo == "plano":
        z0 = float(terreno.get("cota_m", 100.0))
        x0, y0 = terreno.get("origen", (0.0, 0.0))
        px, py = float(terreno.get("pendiente_x", 0.0)), float(terreno.get("pendiente_y", 0.0))
        return lambda x, y: z0 + px * (x - x0) + py * (y - y0)
    if tipo == "puntos":
        puntos = [(float(p[0]), float(p[1]), float(p[2])) for p in terreno["puntos"]]
        if len(puntos) < 3:
            raise ValueError("El terreno por puntos necesita al menos tres puntos acotados.")

        def cota(x, y, vecinos=12):  # IDW, como el servidor MCP
            cercanos = sorted((math.hypot(px - x, py - y), z) for px, py, z in puntos)[:vecinos]
            if cercanos[0][0] < 1e-6:
                return cercanos[0][1]
            pesos = [(1 / d ** 2, z) for d, z in cercanos]
            return sum(w * z for w, z in pesos) / sum(w for w, _ in pesos)
        return cota
    return None


def escribir_dem(terreno: dict, extension: Tuple[float, float, float, float], ruta: str) -> str:
    """Escribe en ASCII Grid (.asc) el terreno «plano» o «puntos» del diseño, sobre la extensión dada
    (xmin, ymin, xmax, ymax) con un margen de 20 m. El complemento lee las cotas de un DEM."""
    cota = _funcion_terreno(terreno)
    if cota is None:
        raise ValueError(f"Terreno desconocido: «{terreno.get('tipo')}».")
    xmin, ymin, xmax, ymax = extension
    xmin, ymin, xmax, ymax = xmin - 20, ymin - 20, xmax + 20, ymax + 20
    celda = 1.0
    while ((xmax - xmin) / celda) * ((ymax - ymin) / celda) > CELDAS_MAX_DEM:
        celda *= 2
    if terreno.get("tipo") == "puntos":
        celda = max(celda, 2.0)
    columnas = int(math.ceil((xmax - xmin) / celda))
    filas = int(math.ceil((ymax - ymin) / celda))
    with open(ruta, "w", encoding="ascii") as archivo:
        archivo.write(f"ncols {columnas}\nnrows {filas}\nxllcorner {xmin:.3f}\nyllcorner {ymin:.3f}\n"
                      f"cellsize {celda:g}\nNODATA_value -9999\n")
        for j in range(filas - 1, -1, -1):
            y = ymin + (j + 0.5) * celda
            archivo.write(" ".join(f"{cota(xmin + (i + 0.5) * celda, y):.3f}" for i in range(columnas)) + "\n")
    return ruta


def _extension(datos: dict) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for lote in datos["lotes"]:
        for anillo in anillos_del_lote(lote):
            xs += [p[0] for p in anillo]
            ys += [p[1] for p in anillo]
    for p in ([datos["fuente"]] if datos.get("fuente") else []) + [
            p for linea in ((datos.get("red") or {}).get("matriz") or []) for p in linea]:
        xs.append(float(p[0]))
        ys.append(float(p[1]))
    return min(xs), min(ys), max(xs), max(ys)


def matriz_de_geojson(ruta: str) -> List[List[Tuple[float, float]]]:
    """Polilíneas de la tubería matriz a partir de un GeoJSON de líneas (por ejemplo, el que se trazó
    aparte para el servidor MCP)."""
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    entidades = datos["features"] if datos.get("type") == "FeatureCollection" else [datos]
    lineas = []
    for entidad in entidades:
        geometria = entidad.get("geometry") or entidad
        if geometria.get("type") == "LineString":
            lineas.append(geometria["coordinates"])
        elif geometria.get("type") == "MultiLineString":
            lineas += geometria["coordinates"]
    lineas = [[(float(p[0]), float(p[1])) for p in linea] for linea in lineas if len(linea) >= 2]
    if not lineas:
        raise ValueError(f"El archivo {ruta} no tiene líneas.")
    return lineas


# ------------------------------------------------------------------ importación


@dataclass
class LoteImportado:
    nombre: str
    lote: str  # lote del diseño (distinto de `nombre` si se subdividió)
    resultado: dict  # `bloque_mapa.resumen_resultado`
    azimut_deg: float
    turno: int = 1


@dataclass
class ResultadoImportacion:
    capa_lotes: object
    lotes: List[LoteImportado] = field(default_factory=list)
    errores: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    capa_dem: Optional[object] = None
    capa_fuente: Optional[object] = None
    tuberias_matriz: int = 0
    conectores: int = 0
    ruta_gpkg: Optional[str] = None
    red: dict = field(default_factory=dict)  # «red» del diseño, con los valores por omisión


def _geometria(anillos, multiparte=True) -> QgsGeometry:
    geometria = QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in a + a[:1]] for a in anillos])
    if not geometria.isGeosValid():
        geometria = geometria.makeValid()
    if multiparte:
        geometria.convertToMultiType()
    return geometria


def _crear_capa_lotes(nombre, crs):
    from .lotes import CAMPO_AREA, CAMPO_BLOQUE, CAMPO_NOMBRE, preparar_capa
    capa = QgsVectorLayer(f"MultiPolygon?field={CAMPO_NOMBRE}:string(80)&field={CAMPO_AREA}:double"
                          f"&field=capa_cad:string(80)&field={CAMPO_BLOQUE}:string(0)", nombre, "memory")
    capa.setCrs(crs)
    preparar_capa(capa)  # marca la capa como de lotes (`PROPIEDAD`): se guarda en el GeoPackage del proyecto
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    grupo = raiz.findGroup("Lotes") or raiz.insertGroup(0, "Lotes")
    proyecto.addMapLayer(capa, False)
    grupo.addLayer(capa)
    return capa


def _agregar_lote(capa, nombre, geometria) -> int:
    from .lotes import CAMPO_AREA, CAMPO_NOMBRE
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(geometria)
    entidad[CAMPO_NOMBRE] = nombre  # por nombre: la capa puede estar ya en el GeoPackage (campo «fid»)
    entidad[CAMPO_AREA] = round(geometria.area() / 10000, 4)
    entidad["capa_cad"] = "MCP"
    ok, agregadas = capa.dataProvider().addFeatures([entidad])
    if not ok:
        raise ValueError(f"No se pudo escribir en la capa «{capa.name()}».")
    capa.updateExtents()
    return agregadas[0].id()


def _transformar(crs_origen, crs_destino):
    if crs_origen == crs_destino:
        return lambda x, y: QgsPointXY(x, y)
    t = QgsCoordinateTransform(crs_origen, crs_destino, QgsProject.instance())
    return lambda x, y: t.transform(QgsPointXY(x, y))


def _cargar_dem(datos, crs, carpeta_salida, avisos):
    terreno = datos.get("terreno") or {}
    tipo = terreno.get("tipo")
    if not terreno or tipo == "llano":
        avisos.append("El diseño no tiene terreno: se calculó con el terreno plano.")
        return None
    if tipo == "dem":
        ruta = terreno.get("archivo")
        if not ruta or not os.path.exists(ruta):
            raise ValueError(f"No se encuentra el DEM del diseño «{ruta}». Cópielo junto al archivo de datos.")
    else:
        os.makedirs(carpeta_salida, exist_ok=True)
        base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(datos.get("nombre", "diseno")))
        ruta = escribir_dem(terreno, _extension(datos), os.path.join(carpeta_salida, f"{base}_dem_{tipo}.asc"))
        avisos.append(f"El terreno «{tipo}» del diseño se escribió como DEM en {ruta}.")
    capa = QgsRasterLayer(ruta, NOMBRE_DEM)
    if not capa.isValid():
        raise ValueError(f"No se pudo abrir el DEM «{ruta}».")
    if not capa.crs().isValid() or (datos.get("epsg") and capa.crs().authid() != crs.authid()):
        capa.setCrs(crs)  # el .asc no siempre trae su sistema de coordenadas; el del diseño manda
    QgsProject.instance().addMapLayer(capa)
    return capa


def _colocar_fuente(datos, crs, avisos):
    from .fuente_mapa import capa_de_fuente, colocar_fuente, crear_capa_fuente
    if not datos.get("fuente"):
        avisos.append("El diseño no tiene fuente: colóquela con «Fuente de agua» antes de calcular la red.")
        return None
    capa = capa_de_fuente()
    if capa is None:
        capa, _ = crear_capa_fuente()
    elif capa.featureCount():
        avisos.append("La fuente del diseño reemplazó a la que había en la capa «Fuente».")
    x, y = (float(v) for v in datos["fuente"][:2])
    colocar_fuente(capa, _transformar(crs, capa.crs())(x, y))
    return capa


def _dibujar_matriz(lineas, crs, cfg, resultado):
    """La matriz del diseño en la capa «Matriz» (con un nodo en cada vértice) y, como el servidor MCP, las
    válvulas unidas a ella («Conector de válvulas»)."""
    from .red_mapa import (agregar_nodos, agregar_tuberia, capas_de_valvulas, conectar_valvulas_a_la_matriz,
                           crear_capas_de_matriz, leer_valvulas)
    matriz, nodos, _ = crear_capas_de_matriz()
    if matriz.featureCount():
        resultado.avisos.append(f"La capa «{matriz.name()}» ya tenía tuberías: las del diseño se sumaron a ellas.")
    a_matriz = _transformar(crs, matriz.crs())
    tolerancia = float(cfg["tolerancia_m"])
    for linea in lineas:
        puntos = [a_matriz(float(p[0]), float(p[1])) for p in linea]
        agregar_tuberia(matriz, puntos)
        agregar_nodos(nodos, puntos, tolerancia)
        resultado.tuberias_matriz += 1
    nombres = {l.nombre for l in resultado.lotes}
    valvulas = [v for v in leer_valvulas(capas_de_valvulas(), matriz.crs()) if v.id in nombres]
    conexion = conectar_valvulas_a_la_matriz(matriz, nodos, valvulas, float(cfg["largo_max_conector_m"]),
                                             tolerancia)
    resultado.conectores = len(conexion.conectores)
    if conexion.fuera_de_alcance:
        resultado.avisos.append(
            "Válvulas demasiado lejos de la matriz (únalas con «Conector de válvulas» o dibuje la tubería): "
            + ", ".join(f"{v} a {d:.0f} m" for v, d in conexion.fuera_de_alcance))


def _pintar_turnos(resultado, crs, cfg):
    from .red_mapa import capas_de_valvulas, leer_valvulas
    from .turnos_mapa import asignar, bloques_de_valvulas
    turnos = max(1, int(cfg.get("turnos") or 1))
    fijos = dict(cfg.get("turnos_fijos") or {})
    por_nombre = repartir_turnos([(l.nombre, l.lote, l.resultado["caudal_m3h"]) for l in resultado.lotes],
                                 turnos, fijos)
    for l in resultado.lotes:
        l.turno = por_nombre[l.nombre]
    if turnos <= 1 and not fijos:
        return  # todo en un turno: no hace falta pintar los bloques
    valvulas = {v.id: v for v in leer_valvulas(capas_de_valvulas(), crs)}
    for turno in sorted(set(por_nombre.values())):
        elegidas = [valvulas[n] for n, t in por_nombre.items() if t == turno and n in valvulas]
        if elegidas:
            asignar(bloques_de_valvulas(elegidas, crs), turno, crs)


def importar_diseno(datos: dict, catalogos: Catalogos, cinta: Optional[Cinta] = None, matriz=None,
                    carpeta_salida: Optional[str] = None, progreso: Optional[Callable[[int, int, str], None]] = None
                    ) -> ResultadoImportacion:
    """Rehace en el mapa, con las herramientas del complemento, el diseño del servidor MCP (`leer_datos`).

    `cinta`: la de «goteo» si la hay (`cinta_del_diseno`), ya presente en `catalogos`. `matriz`: polilíneas de
    la tubería matriz cuando el diseño no trae «red.matriz» (por ejemplo, de `matriz_de_geojson`).
    `carpeta_salida`: dónde escribir el DEM de un terreno «plano» o «puntos». Los lotes que no se pueden
    calcular quedan en `errores` y se sigue con los demás, como en el servidor MCP.
    """
    from .bloque_mapa import (RESULTADO, calcular_bloque, config_de, parametros_de, resumen_resultado,
                              subdividir_en_lote, trazar_en_lote)
    from .lotes import guardar_parametros, lotes_con_nombre
    from .persistencia import guardar_capas_temporales, ruta_gpkg
    from .subunidad_mapa import verificar_crs_metrico
    from .trazado_mapa import alcance_hidraulico

    proyecto = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem(f"EPSG:{int(datos['epsg'])}") if datos.get("epsg") else proyecto.crs()
    verificar_crs_metrico(crs, "del diseño (epsg)")
    if not proyecto.crs().isValid() or not proyecto.mapLayers():
        proyecto.setCrs(crs)
    verificar_crs_metrico(proyecto.crs(), "del proyecto")

    nombre_proyecto = str(datos.get("nombre") or "MCP")
    cfg_red = dict(RED_POR_OMISION)
    cfg_red.update(datos.get("red") or {})
    lotes = datos["lotes"]
    nombres = [str(l.get("nombre") or f"Lote {i}") for i, l in enumerate(lotes, 1)]
    repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidos:
        raise ValueError("Hay lotes con el mismo nombre: " + ", ".join(repetidos))
    ya = [n for n in nombres if lotes_con_nombre(n)]
    if ya:
        raise ValueError("El proyecto ya tiene lotes con estos nombres (sus resultados se pisarían): "
                         + ", ".join(ya[:10]) + ("…" if len(ya) > 10 else "")
                         + ". Elimínelos o importe el diseño en un proyecto nuevo.")

    avisos = []
    carpeta = carpeta_salida or (os.path.dirname(proyecto.absoluteFilePath()) if proyecto.absoluteFilePath()
                                 else os.path.dirname(os.path.abspath(datos.get("lotes_geojson") or ".")))
    dem = _cargar_dem(datos, crs, carpeta, avisos)
    capa_fuente = _colocar_fuente(datos, crs, avisos)
    fuente = tuple(float(v) for v in datos["fuente"][:2]) if datos.get("fuente") else None
    capa = _crear_capa_lotes(f"Lotes · {nombre_proyecto}", crs)
    resultado = ResultadoImportacion(capa, avisos=avisos, capa_dem=dem, capa_fuente=capa_fuente, red=cfg_red)
    goteo = datos.get("goteo") or {}

    for i, (lote, nombre) in enumerate(zip(lotes, nombres), 1):
        if progreso is not None:
            progreso(i, len(lotes), nombre)
        try:
            c = configuracion_goteo(goteo, lote)
            valores = valores_del_bloque(c, catalogos, cinta)
            valores.update(dem=dem.id() if dem is not None else None,
                           fuente=capa_fuente.id() if capa_fuente is not None else None)
            config = config_de(valores, catalogos.tuberias_lateral, catalogos.emisores,
                               catalogos.tuberias_portalateral, dem)
            params = parametros_de(valores, config.emisor)
            alcance = None
            if valores["direccion"] == "auto":  # como la ventana: solo sirve para elegir la dirección
                try:
                    alcance = alcance_hidraulico(config.tuberia_lateral, config.emisor, config.espaciamiento_m,
                                                 config.primer_emisor_m, config.criterios.variacion_caudal_max,
                                                 config.metodo, config.criterios.presion_entrada_max_m)(0.0) or None
                except (ValueError, PresionInsuficiente):
                    alcance = None
            geometria = _geometria(anillos_del_lote(lote), multiparte=False)
            partes = [(nombre, geometria, params)]
            if c.get("subdivision"):
                partes = _subdividir(nombre, geometria, params, crs, dem, fuente, alcance, c["subdivision"],
                                     trazar_en_lote, subdividir_en_lote)
        except (ValueError, PresionInsuficiente) as error:
            resultado.errores.append(f"{nombre}: {error}")
            continue
        for nombre_parte, geometria_parte, params_parte in partes:
            id_lote = _agregar_lote(capa, nombre_parte, _geometria_multi(geometria_parte))
            datos_lote = dict(valores)
            try:
                bloque = trazar_en_lote(geometria_parte, params_parte, crs, dem, fuente,
                                        alcance if params_parte.angulo_deg is None else None)
                r = calcular_bloque(nombre_parte, crs, bloque, geometria_parte, config)
            except (ValueError, PresionInsuficiente) as error:
                resultado.errores.append(f"{nombre_parte}: {error}")
                if params_parte is not params:  # sub-bloque: hereda la dirección del lote
                    datos_lote.update(direccion="usuario", azimut_deg=round((90.0 - params_parte.angulo_deg) % 360, 3))
                guardar_parametros(capa, id_lote, datos_lote)  # queda el lote con sus parámetros, sin calcular
                continue
            datos_lote["azimut_usado_deg"] = round(bloque.azimut_laterales_grados, 3)
            if params_parte is not params:
                datos_lote.update(direccion="usuario", azimut_deg=datos_lote["azimut_usado_deg"])
            datos_lote[RESULTADO] = resumen_resultado(r, config, datos_lote)
            guardar_parametros(capa, id_lote, datos_lote)
            resultado.lotes.append(LoteImportado(nombre_parte, nombre, datos_lote[RESULTADO],
                                                 bloque.azimut_laterales_grados))
    capa.triggerRepaint()
    if not resultado.lotes:
        guardar_capas_temporales()
        raise ValueError("No se pudo calcular ningún lote: " + " | ".join(resultado.errores[:10]))

    _pintar_turnos(resultado, crs, cfg_red)
    lineas = (cfg_red.get("matriz") or matriz) or None
    if lineas:
        _dibujar_matriz(lineas, crs, cfg_red, resultado)
    else:
        avisos.append("El diseño no trae la tubería matriz: dibújela con «Red principal y bomba» → «Dibujar "
                      "la tubería matriz» y una las válvulas con «Conector de válvulas».")
    guardar_capas_temporales()
    resultado.ruta_gpkg = ruta_gpkg()
    return resultado


def _geometria_multi(geometria):
    geometria = QgsGeometry(geometria)
    geometria.convertToMultiType()
    return geometria


def _subdividir(nombre, geometria, params, crs, dem, fuente, alcance, sub, trazar_en_lote, subdividir_en_lote):
    """Sub-bloques del lote, como hace el servidor MCP con «subdivision»: [(nombre-i, geometría, parámetros
    con la dirección del lote entero)]."""
    from dataclasses import replace

    from ..nucleo.subdivision import AUTO_AREA, AUTO_CAUDAL, AUTO_NUMERO, ParametrosSubdivision
    bloque = trazar_en_lote(geometria, params, crs, dem, fuente, alcance if params.angulo_deg is None else None)
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
    fijo = replace(params, angulo_deg=bloque.angulo_deg)
    partes = subdividir_en_lote(geometria, params, bloque.angulo_deg, psub)
    if not partes:
        raise ValueError("la subdivisión no dejó ningún sub-bloque.")
    return [(f"{nombre}-{i}", g, fijo) for i, (g, _) in enumerate(partes, 1)]
