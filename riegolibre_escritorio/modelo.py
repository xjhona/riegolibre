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
import pickle
import tempfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Dict, List, Optional

from mcp_riegolibre import motor

from .capas import completar_estilos
from .edicion import anillos_lote

# Desde cuántos lotes por calcular conviene repartirlos entre procesos.
LOTES_MIN_PARALELO = 4

# Terreno de cada proceso que calcula lotes: se arma una sola vez al arrancar el proceso (leer el DEM tarda).
_TERRENO_TRABAJADOR: Optional[motor.Terreno] = None


def _iniciar_trabajador(datos_terreno: Optional[dict]):
    global _TERRENO_TRABAJADOR
    _TERRENO_TRABAJADOR = motor.Terreno(datos_terreno or None)


def _disenar_en_trabajador(lote: dict, goteo: dict, fuente):
    """Un lote calculado en otro proceso: (subunidades, None) o (None, mensaje de error)."""
    try:
        return motor.disenar_lote(lote, goteo, _TERRENO_TRABAJADOR, fuente), None
    except Exception as error:  # el lote puede venir con cualquier dato malo
        return None, str(error)

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
        self._curvas = (None, [])  # (archivo, curvas leídas) de las curvas de nivel
        self._dibujo = (None, [])  # (archivo, líneas leídas) de las líneas de referencia del DXF

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
            extension = os.path.splitext(origen)[1].lower()
            if extension not in (".asc", ".rdem"):
                raise ValueError("El DEM debe ser un ESRI ASCII Grid (.asc) o un DEM de RiegoLibre (.rdem).")
            with open(origen, "rb") as archivo:
                archivos["dem" + extension] = archivo.read()
            datos["terreno"] = {**terreno, "archivo": "dem" + extension}
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

    # ------------------------------------------------------------ topografía (curvas de nivel)

    def datos_con_curvas(self, rejilla: bytes, curvas_comprimidas: bytes, descripcion: dict) -> dict:
        """Datos del diseño con el terreno de unas curvas de nivel (DEM y curvas ya generados).

        Los archivos se guardan con un nombre por contenido, así deshacer vuelve al terreno anterior sin pisarlo.
        Devuelve los datos nuevos; el cambio lo aplica la ventana (con deshacer).
        """
        from .topografia import nombre_archivo

        nombre_dem = nombre_archivo("dem", rejilla, ".rdem")
        nombre_curvas = nombre_archivo("curvas", curvas_comprimidas, ".json.gz")
        self.archivos[nombre_dem] = rejilla
        self.archivos[nombre_curvas] = curvas_comprimidas
        datos = copy.deepcopy(self.datos)
        datos["terreno"] = {"tipo": "dem", "archivo": nombre_dem, "curvas": nombre_curvas, **descripcion}
        return datos

    @property
    def curvas(self) -> list:
        """[(cota, [(x, y)…])] de las curvas de nivel del terreno; [] si el terreno no viene de curvas."""
        nombre = (self.datos.get("terreno") or {}).get("curvas")
        if not nombre or nombre not in self.archivos:
            return []
        if self._curvas[0] != nombre:
            from .topografia import curvas_de_bytes
            self._curvas = (nombre, curvas_de_bytes(self.archivos[nombre]))
        return self._curvas[1]

    # ------------------------------------------------------------ líneas de referencia de un DXF

    def datos_con_dibujo(self, lineas, descripcion: dict, lotes=()) -> dict:
        """Datos del diseño con estas líneas de referencia (reemplazan a las de antes; [] las quita) y, si se dan,
        los lotes importados agregados. El archivo va con nombre por contenido, como el DEM."""
        from .dibujo_cad import lineas_a_bytes
        from .edicion import agregar_lotes
        from .topografia import nombre_archivo

        datos = agregar_lotes(self.datos, lotes) if lotes else copy.deepcopy(self.datos)
        if lineas:
            contenido = lineas_a_bytes(lineas)
            nombre = nombre_archivo("dibujo", contenido, ".json.gz")
            self.archivos[nombre] = contenido
            datos["dibujo_cad"] = {**descripcion, "archivo": nombre}
        else:
            datos.pop("dibujo_cad", None)
        return datos

    @property
    def dibujo(self) -> list:
        """[(capa del DXF, [(x, y)…])] de las líneas de referencia; [] si no hay."""
        nombre = (self.datos.get("dibujo_cad") or {}).get("archivo")
        if not nombre or nombre not in self.archivos:
            return []
        if self._dibujo[0] != nombre:
            from .dibujo_cad import lineas_de_bytes
            self._dibujo = (nombre, lineas_de_bytes(self.archivos[nombre]))
        return self._dibujo[1]

    # ------------------------------------------------------------ imagen satelital de fondo

    def datos_con_imagen(self, contenido: bytes, descripcion: dict, extension: str = ".jpg") -> dict:
        """Datos del diseño con una imagen de fondo (JPEG o PNG ya ubicado en UTM).

        `descripcion` lleva las esquinas UTM [xmin, ymin, xmax, ymax], la fuente, el zoom, la fecha y la
        atribución. La imagen se guarda con un nombre por contenido, como el DEM (deshacer vuelve a la anterior).
        """
        from .topografia import nombre_archivo

        nombre = nombre_archivo("imagen", contenido, extension)
        self.archivos[nombre] = contenido
        datos = copy.deepcopy(self.datos)
        datos["imagen"] = {**descripcion, "archivo": nombre}
        return datos

    @property
    def imagen(self) -> Optional[dict]:
        """`datos["imagen"]` si su archivo está en el proyecto; None si no hay imagen de fondo."""
        imagen = self.datos.get("imagen")
        if not imagen or imagen.get("archivo") not in self.archivos:
            return None
        return imagen

    def archivos_en_uso(self) -> Dict[str, bytes]:
        """Los archivos que usan los datos de ahora (los de terrenos e imágenes anteriores quedan solo para
        deshacer)."""
        terreno = self.datos.get("terreno") or {}
        nombres = {terreno.get("archivo"), terreno.get("curvas")} if terreno.get("tipo") == "dem" else set()
        nombres.add((self.datos.get("imagen") or {}).get("archivo"))
        nombres.add((self.datos.get("dibujo_cad") or {}).get("archivo"))
        return {k: v for k, v in self.archivos.items() if k in nombres}

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
        claves = [self._clave_lote(lote, goteo) for lote in self.datos["lotes"]]
        pendientes = {}
        for clave, lote in zip(claves, self.datos["lotes"]):
            if clave not in self._cache_lotes:
                pendientes.setdefault(clave, lote)
        fallidos = self._calcular_lotes(pendientes, goteo)
        usadas = {}
        for clave, lote in zip(claves, self.datos["lotes"]):
            if clave in fallidos:  # se informa y se sigue con los demás lotes
                self.errores.append(f"{lote.get('nombre', '?')}: {fallidos[clave]}")
                continue
            usadas[clave] = self._cache_lotes[clave]
            self.subunidades.extend(usadas[clave])
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

    def _calcular_lotes(self, pendientes: Dict[str, dict], goteo: dict) -> Dict[str, str]:
        """Calcula los lotes pendientes y los deja en la caché. Devuelve {clave: error} de los que fallaron.

        Cada lote es independiente de los demás, así que con varios se reparten entre procesos (uno por núcleo,
        menos uno para la ventana); el resultado es el mismo que calculándolos uno tras otro. Si los procesos
        no se pueden usar, se calculan aquí mismo. Con pocos lotes (al editar uno, por ejemplo) arrancar los
        procesos cuesta más de lo que ahorra.
        """
        fallidos = {}
        trabajadores = min(len(pendientes), max(1, (os.cpu_count() or 1) - 1))
        if len(pendientes) >= LOTES_MIN_PARALELO and trabajadores >= 2:
            try:
                with ProcessPoolExecutor(trabajadores, initializer=_iniciar_trabajador,
                                         initargs=(self.terreno.datos,)) as grupo:
                    tareas = {clave: grupo.submit(_disenar_en_trabajador, lote, goteo, self.fuente)
                              for clave, lote in pendientes.items()}
                    for clave, tarea in tareas.items():
                        subunidades, error = tarea.result()
                        if error is None:
                            self._cache_lotes[clave] = subunidades
                        else:
                            fallidos[clave] = error
                return fallidos
            except (OSError, BrokenProcessPool, pickle.PicklingError, AttributeError, TypeError):
                fallidos = {}  # sin procesos: se sigue abajo con los que falten
        for clave, lote in pendientes.items():
            if clave in self._cache_lotes:
                continue
            try:
                self._cache_lotes[clave] = motor.disenar_lote(lote, goteo, self.terreno, self.fuente)
            except Exception as error:  # el lote puede venir con cualquier dato malo
                fallidos[clave] = str(error)
        return fallidos

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
        """(xmin, ymin, xmax, ymax) de lotes, fuente, matriz y curvas; None si el proyecto está vacío.

        La imagen de fondo solo cuenta si no hay nada más (si no, cada descarga con margen agrandaría la zona)."""
        puntos = [p for lote in self.datos.get("lotes", []) for anillo in anillos_lote(lote) for p in anillo]
        puntos += [p for linea in self.matriz for p in linea]
        for _, linea in self.curvas + self.dibujo:
            puntos += [linea[0], min(linea), max(linea), min(linea, key=lambda p: p[1]), max(linea, key=lambda p: p[1])]
        if self.fuente:
            puntos.append(self.fuente)
        if not puntos and self.referencia:
            puntos.append(self.referencia)
        if not puntos and self.imagen:
            xmin, ymin, xmax, ymax = self.imagen["esquinas"]
            puntos += [(xmin, ymin), (xmax, ymax)]
        if not puntos:
            return None
        xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
        return min(xs), min(ys), max(xs), max(ys)

    def cerrar(self):
        if self._carpeta_archivos is not None:
            self._carpeta_archivos.cleanup()
            self._carpeta_archivos = None
