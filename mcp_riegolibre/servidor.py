# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Servidor MCP de RiegoLibre: diseño de riego por goteo a partir de instrucciones.

Expone el motor de `riegolibre.nucleo` (sin QGIS) como herramientas para un asistente. El asistente
decide (dirección, subdivisión, turnos, tuberías) y el núcleo hace todos los cálculos.

Ejecutar (con uv, que instala el SDK de MCP en un entorno aparte):

    uv run --no-project --with "mcp>=2.3,<3" python mcp_riegolibre/servidor.py
"""

import functools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from mcp_riegolibre import motor  # noqa: E402
from riegolibre.nucleo.memoria import resumen_subunidad  # noqa: E402

servidor = MCPServer("riegolibre", instructions=(
    "Diseño de riego por goteo con el motor de cálculo de RiegoLibre. Flujo recomendado: "
    "1) ver_catalogo para conocer emisores y tuberías; 2) disenar_proyecto con los lotes, la fuente y "
    "los parámetros (la tubería matriz se dibuja: usted propone sus polilíneas desde la fuente, por caminos o "
    "bordes de los lotes, y las válvulas se conectan solas); 3) si alguna subunidad no cumple, cambie parámetros (subdivisión, portalateral al "
    "centro, otro emisor, más turnos…) y vuelva a diseñar; 4) exportar_proyecto. No invente cifras "
    "hidráulicas: todas deben salir de estas herramientas. Coordenadas en metros (UTM)."))

_proyectos = {}  # id -> motor.Proyecto (solo mientras el servidor esté abierto)
MAX_PROYECTOS = 20


def _json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, default=str)


def _con_mensaje(funcion):
    """Los errores de datos (ValueError, PresionInsuficiente…) llegan al asistente con su texto."""
    @functools.wraps(funcion)
    def envoltura(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as error:
            raise ToolError(f"{type(error).__name__}: {error}") from error
    return envoltura


@servidor.tool()
@_con_mensaje
def ver_catalogo() -> str:
    """Emisores, tuberías (lateral, portalateral, red principal) y laterales con gotero («cintas») disponibles,
    con los valores por omisión de los parámetros. Si el usuario importó su base de datos de IRRICAD en el
    complemento, se usan esos materiales."""
    return _json(motor.catalogo())


@servidor.tool()
@_con_mensaje
def disenar_proyecto(proyecto: dict) -> str:
    """Diseña el sistema completo: bloques de goteo, subunidades, red principal y bomba.

    `proyecto` (coordenadas en metros, sistema proyectado):
    - nombre, epsg (p. ej. 32718), cliente, ubicacion: opcionales.
    - fuente: [x, y] del cabezal (sin fuente no se diseña la red ni la bomba).
    - terreno (opcional; sin él, llano):
        {"tipo": "plano", "cota_m", "origen": [x, y], "pendiente_x", "pendiente_y"}  (m/m)
        {"tipo": "puntos", "puntos": [[x, y, z], ...]}  (interpolación IDW)
        {"tipo": "dem", "archivo": "ruta.asc"}  (ESRI ASCII Grid)
    - lotes: [{"nombre", "contorno": [[x, y], ...], "huecos": [[[x, y], ...]] opcional, y cualquier clave de
      «goteo» para cambiarla solo en ese lote}]. O bien lotes_geojson: ruta a un GeoJSON de polígonos
      (campo_nombre: atributo con el nombre); entonces «lotes» solo lleva ajustes por nombre.
    - goteo (para todos los lotes):
        emisor + tuberia_lateral (nombre o parte única del nombre), o cinta (de la base de datos) o definida
        aquí como dict con los campos de «Edit Tape» de IRRICAD: nombre, diametro_interior_mm, k_emisor,
        exponente_emisor, espaciamiento_m, y opcionales c_hazen, cv, longitud_equivalente_m (barb factor),
        presion_entrada_m, presion_min_m, presion_max_m, presion_min_compensacion_m, presion_nominal_m;
        espaciamiento_emisores_m, primer_emisor_m (por omisión, medio espaciamiento);
        separacion_hileras_m, laterales_por_hilera, separacion_en_hilera_m, cabecera_m, costados_m;
        azimut_laterales_deg (None: automático);
        portalateral: inicio | final | centro | distancia | alto | bajo (distancia_portalateral_m);
        valvula: auto | alto | bajo | inicio | final | centro | porcentaje (porcentaje_valvula);
        variacion_caudal_max_pct (10), velocidad_max_portalateral_ms (1.5), presion_entrada_max_m;
        diametros_max_portalateral (2: telescópico), tuberia_portalateral (fija), metodo (darcy | hazen);
        subdivision: {"longitud_max_lateral_m", y uno de "caudal_max_m3h" | "area_max_ha" | "numero", "hueco_m"}.
    - red: matriz (obligatoria para la red y la bomba): polilíneas [[[x, y], ...], ...] de la tubería matriz,
      como se dibujan a mano en IRRICAD; una debe empezar en la fuente. Cada válvula se une a la matriz con un
      tramo recto si está a menos de largo_max_conector_m (100). Conviene llevarla por caminos o bordes, entre
      los lotes y cerca de las válvulas (valvula_xy del resumen: diseñe primero sin matriz para verlas).
      turnos (1), turnos_fijos {"lote o subunidad": turno}, tolerancia_m (0.5), velocidad_max_ms, presion_min_m, factor_perdidas_menores, perdida_valvula_m,
      perdidas_cabezal_m (7), altura_succion_m (2), eficiencia_bomba (0.7).

    Devuelve el id del diseño y su resumen: cada subunidad (caudal, presión en la válvula, variación de caudal,
    portalateral, si cumple y por qué no), turnos, tramos de la red, bomba (caudal, CDT, potencia),
    metrados y errores. Los lotes que fallan se listan en «errores» y no detienen el resto.
    """
    p = motor.disenar_proyecto(proyecto)
    id_proyecto = f"{len(_proyectos) + 1}"
    _proyectos[id_proyecto] = p
    for viejo in list(_proyectos)[:-MAX_PROYECTOS]:
        del _proyectos[viejo]
    return _json({"id": id_proyecto, **p.resumen()})


def _proyecto(id_proyecto):
    if id_proyecto not in _proyectos:
        raise ValueError(f"No hay un diseño con id «{id_proyecto}». Diseños abiertos: {', '.join(_proyectos) or 'ninguno'}.")
    return _proyectos[id_proyecto]


@servidor.tool()
@_con_mensaje
def detalle_subunidad(id_proyecto: str, subunidad: str) -> str:
    """Todo el cálculo de una subunidad: diámetros evaluados (con los motivos por los que no cumplen),
    tramos del portalateral, presiones por rama, laterales y emisor. Úselo para decidir qué cambiar."""
    p = _proyecto(id_proyecto)
    s = next((s for s in p.subunidades if s.nombre == subunidad), None)
    if s is None:
        raise ValueError(f"No existe la subunidad «{subunidad}». Hay: {', '.join(x.nombre for x in p.subunidades)}.")
    detalle = resumen_subunidad(s.nombre, s.diseno, s.criterios, s.metodo, s.bloque.area_regada_m2,
                                [lat.longitud_m for lat in s.bloque.laterales], None, s.avisos)
    return _json({"resumen": s.resumen(), "calculo": detalle})


@servidor.tool()
@_con_mensaje
def exportar_proyecto(id_proyecto: str, carpeta: str) -> str:
    """Guarda en `carpeta`: el GeoJSON del diseño (bloques, laterales, portalaterales, válvulas, matriz, conectores y fuente;
    se abre en QGIS), la memoria de cálculo en HTML, el resumen y los datos de entrada (para repetir el diseño)."""
    return _json(_proyecto(id_proyecto).exportar(os.path.abspath(carpeta)))


if __name__ == "__main__":
    servidor.run()
