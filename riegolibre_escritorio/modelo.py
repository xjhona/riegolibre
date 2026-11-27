# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Proyecto del programa de escritorio: datos del diseño, subunidades calculadas y red principal.

Sin Qt ni QGIS. La geometría (bloques, subdivisión, unión de las válvulas a la matriz) sale de
`mcp_riegolibre.motor` y todo el cálculo hidráulico de `riegolibre.nucleo`; aquí solo se ordenan los pasos
como en el programa: primero se diseñan los lotes y después, con los parámetros que elija el usuario, la red
principal y la bomba.

Los datos del diseño tienen el mismo formato que el `…_datos.json` del servidor MCP (lotes, fuente, terreno,
goteo, red), de modo que un diseño del servidor se abre tal cual y lo que se dibuje en el programa queda en el
mismo formato.
"""

import copy
import json
import os
import tempfile
from typing import Dict, List, Optional

from mcp_riegolibre import motor

from .capas import completar_estilos
from .edicion import anillos_lote

# Parámetros de «Red principal y bomba» y sus valores iniciales: los del servidor, salvo la pérdida en cada
# válvula, que empieza en 2 m como en la ventana del complemento (el servidor usa 0 m si el diseño no la da).
PARAMETROS_RED = {
    "velocidad_max_ms": 1.5,
    "presion_min_m": 2.0,
    "factor_perdidas_menores": 0.10,
    "perdida_valvula_m": 2.0,
    "perdidas_cabezal_m": 7.0,
    "altura_succion_m": 2.0,
    "eficiencia_bomba": 0.70,
    "largo_max_conector_m": 100.0,
    "tolerancia_m": 0.5,
}


def _ruta_existente(ruta: str, carpeta: str) -> str:
    """La ruta tal cual si existe; si no, relativa a la carpeta del archivo de datos."""
    if os.path.isabs(ruta) and os.path.exists(ruta):
        return ruta
    candidata = os.path.normpath(os.path.join(carpeta, ruta))
    if os.path.exists(candidata):
        return candidata
    if os.path.exists(ruta):
        return os.path.abspath(ruta)
    raise ValueError(f"No se encuentra el archivo «{ruta}» (ni junto a los datos, en {carpeta}).")


class ProyectoRiego:
    """Un proyecto abierto en el programa."""

    def __init__(self, datos: Optional[dict] = None, archivos: Optional[Dict[str, bytes]] = None):
        self.datos: dict = copy.deepcopy(datos) if datos else {"nombre": "Proyecto nuevo", "lotes": []}
        self.archivos: Dict[str, bytes] = dict(archivos or {})  # archivos guardados dentro del proyecto (DEM)
        self.parametros_red: dict = self._parametros_iniciales()
        self.estilos_capas: Dict[str, dict] = completar_estilos(None)  # barra de capas: color, línea, grosor…
        self.subunidades: List[motor.Subunidad] = []
        self.red: Optional[motor.RedCalculada] = None
        self.errores: List[str] = []
        self.error_red: Optional[str] = None
        self.terreno = motor.Terreno(None)
        self.ruta: Optional[str] = None
        self._carpeta_archivos: Optional[tempfile.TemporaryDirectory] = None
        self._cache_lotes: Dict[str, list] = {}  # lotes ya calculados, por sus datos (editar y deshacer es rápido)

    # ------------------------------------------------------------ datos

    @property
    def nombre(self) -> str:
        return self.datos.get("nombre") or "Proyecto"

    @property
    def epsg(self) -> Optional[int]:
        return int(self.datos["epsg"]) if self.datos.get("epsg") else None

    @property
    def fuente(self):
        return tuple(self.datos["fuente"]) if self.datos.get("fuente") else None

    @property
    def matriz(self) -> List[List[tuple]]:
        return [[(float(p[0]), float(p[1])) for p in linea] for linea in (self.datos.get("red") or {}).get("matriz") or []]

    @property
    def turnos(self) -> int:
        return max(1, int((self.datos.get("red") or {}).get("turnos", 1)))

    def _parametros_iniciales(self) -> dict:
        red = self.datos.get("red") or {}
        return {clave: float(red.get(clave, valor)) for clave, valor in PARAMETROS_RED.items()}

    @classmethod
    def importar_mcp(cls, ruta: str) -> "ProyectoRiego":
        """Proyecto a partir del `…_datos.json` que escribe `exportar_proyecto` del servidor MCP.

        Los lotes de un GeoJSON aparte pasan a los datos y el DEM se guarda dentro del proyecto, para que el
        archivo del programa no dependa de otros.
        """
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        if not isinstance(datos, dict) or not (datos.get("lotes") or datos.get("lotes_geojson")):
            raise ValueError("El archivo no es un diseño del servidor MCP: le faltan los «lotes».")
        carpeta = os.path.dirname(os.path.abspath(ruta))
        archivos = {}
        if datos.get("lotes_geojson"):
            lotes = motor.lotes_de_geojson(_ruta_existente(datos["lotes_geojson"], carpeta),
                                           datos.get("campo_nombre", "nombre"))
            ajustes = {l["nombre"]: l for l in datos.get("lotes", [])}
            datos["lotes"] = [{**lote, **{k: v for k, v in ajustes.get(lote["nombre"], {}).items() if k != "nombre"}}
                              for lote in lotes]
            del datos["lotes_geojson"]
            datos.pop("campo_nombre", None)
        terreno = datos.get("terreno") or {}
        if terreno.get("tipo") == "dem":
            origen = _ruta_existente(terreno["archivo"], carpeta)
            if not origen.lower().endswith(".asc"):
                raise ValueError("Por ahora el DEM debe ser un ESRI ASCII Grid (.asc).")
            with open(origen, "rb") as archivo:
                archivos["dem.asc"] = archivo.read()
            datos["terreno"] = {**terreno, "archivo": "dem.asc"}
        proyecto = cls(datos, archivos)
        proyecto.disenar()
        return proyecto

    # ------------------------------------------------------------ cálculo

    def _terreno(self) -> motor.Terreno:
        terreno = self.datos.get("terreno")
        if terreno and terreno.get("tipo") == "dem":
            nombre = terreno["archivo"]
            if nombre not in self.archivos:
                raise ValueError(f"El proyecto no tiene el DEM «{nombre}».")
            if self._carpeta_archivos is None:
                self._carpeta_archivos = tempfile.TemporaryDirectory(prefix="riegolibre_", ignore_cleanup_errors=True)
            ruta = os.path.join(self._carpeta_archivos.name, nombre)
            if not os.path.exists(ruta):
                with open(ruta, "wb") as archivo:
                    archivo.write(self.archivos[nombre])
            terreno = {**terreno, "archivo": ruta}
        return motor.Terreno(terreno)

    @classmethod
    def nuevo(cls, nombre: str, epsg: Optional[int], terreno: Optional[dict] = None,
              referencia=None) -> "ProyectoRiego":
        """Proyecto vacío para dibujarlo desde cero. `referencia` (E, N) es dónde se abre el mapa."""
        datos = {"nombre": nombre.strip() or "Proyecto nuevo", "lotes": []}
        if epsg:
            datos["epsg"] = int(epsg)
        if terreno:
            datos["terreno"] = dict(terreno)
        if referencia:
            datos["referencia"] = [float(referencia[0]), float(referencia[1])]
        return cls(datos)

    @property
    def referencia(self):
        return tuple(self.datos["referencia"]) if self.datos.get("referencia") else None

    def _clave_lote(self, lote: dict, goteo: dict) -> str:
        """Lo que decide el cálculo de un lote: sus datos, el goteo, el terreno y (válvula automática) la fuente."""
        try:
            automatica = motor._config_goteo(goteo, lote)["valvula"] == "auto"
        except ValueError:
            automatica = True
        return json.dumps([lote, goteo, self.datos.get("terreno"), self.fuente if automatica else None],
                          sort_keys=True, default=str)

    def disenar(self, forzar: bool = False):
        """Traza y calcula el bloque de goteo de cada lote y reparte los turnos. Borra la red calculada.

        Los lotes cuyos datos no cambiaron no se vuelven a calcular (salvo con `forzar`, por ejemplo si cambió
        la base de datos de materiales).
        """
        self.red, self.error_red = None, None
        self.subunidades, self.errores = [], []
        if forzar:
            self._cache_lotes = {}
        if not self.datos.get("lotes"):
            return
        self.terreno = self._terreno()
        goteo = self.datos.get("goteo", {})
        usadas = {}
        for lote in self.datos["lotes"]:
            clave = self._clave_lote(lote, goteo)
            try:
                if clave not in self._cache_lotes:
                    self._cache_lotes[clave] = motor.disenar_lote(lote, goteo, self.terreno, self.fuente)
                usadas[clave] = self._cache_lotes[clave]
                self.subunidades.extend(usadas[clave])
            except Exception as error:  # se informa y se sigue con los demás lotes
                self.errores.append(f"{lote.get('nombre', '?')}: {error}")
        # Se guardan los de ahora y algunos de antes (para deshacer sin esperar)
        antiguos = [c for c in self._cache_lotes if c not in usadas][-3 * max(1, len(usadas)):]
        self._cache_lotes = {**{c: self._cache_lotes[c] for c in antiguos}, **usadas}
        nombres = [s.nombre for s in self.subunidades]
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        if repetidos:
            self.subunidades = []
            raise ValueError("Hay lotes con el mismo nombre: " + ", ".join(repetidos))
        red = self.datos.get("red") or {}
        motor.repartir_turnos(self.subunidades, self.turnos, dict(red.get("turnos_fijos", {})))

    def calcular_red(self, parametros: Optional[dict] = None):
        """Une las válvulas a la matriz, dimensiona la red y calcula la bomba. Lanza ValueError si no se puede."""
        if parametros:
            desconocidos = set(parametros) - set(PARAMETROS_RED)
            if desconocidos:
                raise ValueError("Parámetros de la red desconocidos: " + ", ".join(sorted(desconocidos)))
            self.parametros_red.update({k: float(v) for k, v in parametros.items()})
        self.red, self.error_red = None, None
        if not self.subunidades:
            raise ValueError("No hay subunidades calculadas: dibuje o importe los lotes.")
        if self.fuente is None:
            raise ValueError("Falta la fuente de agua (el punto de la bomba y el cabezal).")
        if not self.matriz:
            raise ValueError("Falta la tubería matriz: dibújela desde la fuente (herramienta «Tubería matriz»).")
        cfg = dict(motor.RED_POR_OMISION)
        cfg.update(self.datos.get("red") or {})
        cfg.update(self.parametros_red)
        try:
            self.red = motor.disenar_red(self.subunidades, self.fuente, cfg, self.terreno)
        except ValueError as error:
            self.error_red = str(error)
            raise
        return self.red

    # ------------------------------------------------------------ resultados

    def _proyecto_motor(self) -> motor.Proyecto:
        errores = list(self.errores) + ([f"Red principal: {self.error_red}"] if self.error_red else [])
        return motor.Proyecto(self.datos, self.subunidades, self.red, self.terreno, errores)

    def resumen(self) -> dict:
        """Mismo resumen que el servidor MCP (subunidades, turnos, red, bomba, metrados)."""
        return self._proyecto_motor().resumen()

    def geojson(self) -> dict:
        return self._proyecto_motor().geojson()

    def memoria_html(self) -> str:
        return self._proyecto_motor().memoria_html()

    def extension(self):
        """(xmin, ymin, xmax, ymax) de lotes, fuente y matriz; None si el proyecto está vacío."""
        puntos = [p for lote in self.datos.get("lotes", []) for anillo in anillos_lote(lote) for p in anillo]
        puntos += [p for linea in self.matriz for p in linea]
        if self.fuente:
            puntos.append(self.fuente)
        if not puntos and self.referencia:
            puntos.append(self.referencia)
        if not puntos:
            return None
        xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
        return min(xs), min(ys), max(xs), max(ys)

    def cerrar(self):
        if self._carpeta_archivos is not None:
            self._carpeta_archivos.cleanup()
            self._carpeta_archivos = None
