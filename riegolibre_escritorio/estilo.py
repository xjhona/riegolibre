# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Tema visual del programa: el mismo de las ventanas del complemento (`riegolibre.gui.tema`), con PySide6.

De `riegolibre.gui.tema` solo se usan la paleta y la hoja de estilo, que no importan QGIS. Los colores de estado
(verde «cumple», rojo «no cumple») y los de los turnos no pasan por aquí.
"""

import html

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtGui import QFontDatabase

from riegolibre.gui.tema import FUENTES, PALETAS, hoja_de_estilo

CLAVE = "tema"
TEMAS = {"claro": "Claro", "oscuro": "Oscuro"}
VERDE, ROJO = "#2e7d32", "#c62828"


def traducir_qt(aplicacion):
    """Textos propios de Qt en español (botones «Cerrar», «Guardar», «Cancelar» de los cuadros estándar)."""
    QLocale.setDefault(QLocale(QLocale.Language.Spanish))
    traductor = QTranslator(aplicacion)
    if traductor.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        aplicacion.installTranslator(traductor)
    return traductor


def ajustes() -> QSettings:
    return QSettings("RiegoLibre", "RiegoLibre escritorio")


def familia_tipografica() -> str:
    instaladas = set(QFontDatabase.families())
    return next((f for f in FUENTES if f in instaladas), FUENTES[-1])


def tema_actual() -> str:
    nombre = ajustes().value(CLAVE, "claro")
    return nombre if nombre in TEMAS else "claro"


def hoja_actual(nombre=None) -> str:
    return hoja_de_estilo(nombre or tema_actual(), familia_tipografica())


def aplicar_tema(aplicacion, nombre=None):
    """Aplica el tema a toda la aplicación (y lo recuerda si se da `nombre`)."""
    if nombre is not None:
        if nombre not in TEMAS:
            raise ValueError(f"Tema desconocido: {nombre!r}")
        ajustes().setValue(CLAVE, nombre)
    aplicacion.setStyleSheet(hoja_actual(nombre))


def paleta(nombre=None) -> dict:
    return PALETAS[nombre or tema_actual()]


def html_estado(cumple: bool) -> str:
    if cumple:
        return f"<span style='color:{VERDE}'><b>✔ Cumple</b></span>"
    return f"<span style='color:{ROJO}'><b>✘ No cumple</b></span>"


def html_avisos(avisos) -> str:
    if not avisos:
        return ""
    return f"<p style='color:{ROJO}'>" + "<br>".join("⚠ " + html.escape(a) for a in avisos) + "</p>"
