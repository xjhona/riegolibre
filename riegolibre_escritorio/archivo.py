# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Archivo de proyecto del programa (`.riegolibre`): una base SQLite con todo adentro.

Tablas:

- `metadatos` (clave, valor): formato, versión del formato, fecha de guardado;
- `datos` (clave, json): `diseno` (los datos del diseño, formato del servidor MCP), `parametros_red`,
  `estilos_capas` (la barra de capas) y, si la red
  se calculó, `resumen` (el resumen de resultados, para leerlo sin volver a calcular);
- `archivos` (nombre, contenido): archivos que el proyecto necesita, como el DEM;
- `entidades` (capa, geometria, propiedades): las geometrías calculadas en GeoJSON, para que otro programa
  pueda leerlas.

Al abrir se vuelve a calcular el diseño a partir de los datos: lo guardado como resultado es solo una copia.
"""

import datetime
import json
import os
import sqlite3

from .capas import completar_estilos
from .modelo import ProyectoRiego

FORMATO = "riegolibre-escritorio"
VERSION_FORMATO = 1
EXTENSION = ".riegolibre"


def guardar(proyecto: ProyectoRiego, ruta: str):
    """Escribe el proyecto en `ruta` (primero en un archivo temporal, para no dejar uno a medias)."""
    temporal = ruta + ".tmp"
    if os.path.exists(temporal):
        os.remove(temporal)
    conexion = sqlite3.connect(temporal)
    try:
        with conexion:
            conexion.executescript(
                "CREATE TABLE metadatos (clave TEXT PRIMARY KEY, valor TEXT);"
                "CREATE TABLE datos (clave TEXT PRIMARY KEY, json TEXT NOT NULL);"
                "CREATE TABLE archivos (nombre TEXT PRIMARY KEY, contenido BLOB NOT NULL);"
                "CREATE TABLE entidades (id INTEGER PRIMARY KEY, capa TEXT, geometria TEXT, propiedades TEXT);")
            conexion.executemany("INSERT INTO metadatos VALUES (?, ?)", [
                ("formato", FORMATO), ("version", str(VERSION_FORMATO)),
                ("guardado", datetime.datetime.now().isoformat(timespec="seconds"))])
            datos = {"diseno": proyecto.datos, "parametros_red": proyecto.parametros_red,
                     "estilos_capas": proyecto.estilos_capas, "red_calculada": proyecto.red is not None}
            if proyecto.subunidades:
                datos["resumen"] = proyecto.resumen()
            conexion.executemany("INSERT INTO datos VALUES (?, ?)",
                                 [(k, json.dumps(v, ensure_ascii=False)) for k, v in datos.items()])
            conexion.executemany("INSERT INTO archivos VALUES (?, ?)", list(proyecto.archivos.items()))
            if proyecto.subunidades:
                filas = []
                for entidad in proyecto.geojson()["features"]:
                    propiedades = dict(entidad["properties"])
                    filas.append((propiedades.pop("capa"), json.dumps(entidad["geometry"]),
                                  json.dumps(propiedades, ensure_ascii=False)))
                conexion.executemany("INSERT INTO entidades (capa, geometria, propiedades) VALUES (?, ?, ?)", filas)
    finally:
        conexion.close()
    os.replace(temporal, ruta)
    proyecto.ruta = ruta


def abrir(ruta: str) -> ProyectoRiego:
    """Lee un `.riegolibre`, vuelve a diseñar los lotes y, si estaba calculada, la red."""
    if not os.path.exists(ruta):
        raise ValueError(f"No existe el archivo {ruta}.")
    conexion = sqlite3.connect(ruta)
    try:
        try:
            meta = dict(conexion.execute("SELECT clave, valor FROM metadatos"))
            datos = {k: json.loads(v) for k, v in conexion.execute("SELECT clave, json FROM datos")}
            archivos = dict(conexion.execute("SELECT nombre, contenido FROM archivos"))
        except sqlite3.DatabaseError:
            raise ValueError(f"{os.path.basename(ruta)} no es un proyecto de RiegoLibre.") from None
    finally:
        conexion.close()
    if meta.get("formato") != FORMATO:
        raise ValueError(f"{os.path.basename(ruta)} no es un proyecto de RiegoLibre.")
    if int(meta.get("version", 0)) > VERSION_FORMATO:
        raise ValueError("El proyecto se guardó con una versión más nueva de RiegoLibre; actualice el programa.")
    proyecto = ProyectoRiego(datos["diseno"], archivos)
    proyecto.parametros_red.update(datos.get("parametros_red", {}))
    proyecto.estilos_capas = completar_estilos(datos.get("estilos_capas"))
    proyecto.ruta = ruta
    proyecto.disenar()
    if datos.get("red_calculada"):
        try:
            proyecto.calcular_red()
        except ValueError:
            pass  # queda en proyecto.error_red y se muestra en la ventana
    return proyecto
