# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana «Acerca de RiegoLibre»: autoría, versión, garantía y licencia (avisos de la sección 5 d de la GPL)."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QTabWidget, QVBoxLayout

from ..nucleo.autoria import ATRIBUCION, COPYRIGHT, REPOSITORIO, USO_DE_IA
from .dialogo_memoria import version_complemento
from .tema import aplicar_tema

CARPETA = os.path.dirname(os.path.dirname(__file__))


def _leer(nombre):
    with open(os.path.join(CARPETA, nombre), encoding="utf-8") as archivo:
        return archivo.read()


def _texto_fijo(texto):
    caja = QPlainTextEdit(texto)
    caja.setReadOnly(True)
    return caja


class DialogoAcerca(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        aplicar_tema(self)
        self.setWindowTitle("Acerca de RiegoLibre")
        self.resize(620, 460)
        principal = QVBoxLayout(self)

        self.etiqueta = QLabel(
            f"<h2>RiegoLibre {version_complemento()}</h2>"
            f"<p><b>{ATRIBUCION}</b><br>{COPYRIGHT}</p>"
            f"<p><a href='{REPOSITORIO}'>{REPOSITORIO}</a></p>"
            "<p>Software libre: puede redistribuirlo y modificarlo según la licencia GPL-3.0 y las condiciones "
            "adicionales del aviso. Se distribuye SIN NINGUNA GARANTÍA; los resultados deben ser revisados por "
            "el proyectista.</p>"
            f"<p>{USO_DE_IA}</p>")
        self.etiqueta.setTextFormat(Qt.TextFormat.RichText)
        self.etiqueta.setWordWrap(True)
        self.etiqueta.setOpenExternalLinks(True)
        self.etiqueta.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.pestanas = QTabWidget()
        self.pestanas.addTab(self.etiqueta, "Acerca de")
        self.pestanas.addTab(_texto_fijo(_leer("NOTICE")), "Autoría y condiciones")
        self.pestanas.addTab(_texto_fijo(_leer("LICENSE")), "Licencia GPL-3.0")
        principal.addWidget(self.pestanas)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        principal.addWidget(botones)
