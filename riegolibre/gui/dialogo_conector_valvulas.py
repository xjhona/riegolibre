# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Cuadro previo a conectar las válvulas a la matriz, como «Valve Connector» de IRRICAD.

Pide la longitud máxima del tramo de conexión y su diámetro: igual al de la tubería más cercana, uno del
catálogo o «Elegida por el programa» («Computer Selected»). El tramo se dibuja siempre en la capa «Matriz».
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFormLayout, QGroupBox, QVBoxLayout)

from ..nucleo.tuberias import clave_economica
from .dialogo_tuberia_matriz import TEXTO_POR_PROGRAMA
from .tema import aplicar_tema

LARGO_MAXIMO_POR_DEFECTO_M = 100.0


class DialogoConectorValvulas(QDialog):
    """`catalogo`: tuberías para elegir cuando no se iguala a la más cercana. `elegida`: la que queda marcada."""

    def __init__(self, catalogo, elegida=None, parent=None):
        super().__init__(parent)
        aplicar_tema(self)
        self.setWindowTitle("RiegoLibre · Conectar válvulas a la matriz")
        self.setMinimumWidth(440)
        principal = QVBoxLayout(self)

        conexion = QGroupBox("Propiedades de la conexión")
        formulario = QFormLayout(conexion)
        self.check_igualar = QCheckBox("Igualar a la tubería más cercana")
        self.check_igualar.setChecked(True)
        self.check_igualar.setToolTip("El tramo toma el diámetro de la tubería de la matriz a la que se une.")
        formulario.addRow(self.check_igualar)
        self.spin_largo = QDoubleSpinBox()
        self.spin_largo.setRange(0.1, 10000)
        self.spin_largo.setDecimals(1)
        self.spin_largo.setValue(LARGO_MAXIMO_POR_DEFECTO_M)
        self.spin_largo.setSuffix(" m")
        self.spin_largo.setToolTip("Una válvula más lejos que esto de la matriz no se conecta.")
        formulario.addRow("Longitud máxima del tramo de conexión:", self.spin_largo)
        principal.addWidget(conexion)

        self.grupo_tuberia = QGroupBox("Propiedades de la tubería")
        formulario = QFormLayout(self.grupo_tuberia)
        self.combo_tuberia = QComboBox()
        self.combo_tuberia.addItem(TEXTO_POR_PROGRAMA, None)
        for tuberia in sorted(catalogo, key=clave_economica):
            self.combo_tuberia.addItem(tuberia.nombre, tuberia)
            self.combo_tuberia.setItemData(self.combo_tuberia.count() - 1,
                                           f"Diámetro interior {tuberia.diametro_interior_mm:g} mm",
                                           Qt.ItemDataRole.ToolTipRole)
        indice = next((i for i in range(1, self.combo_tuberia.count())
                       if elegida is not None and self.combo_tuberia.itemData(i).nombre == elegida.nombre), 0)
        self.combo_tuberia.setCurrentIndex(indice)
        formulario.addRow("Tubería:", self.combo_tuberia)
        principal.addWidget(self.grupo_tuberia)
        self.check_igualar.toggled.connect(lambda igualar: self.grupo_tuberia.setEnabled(not igualar))
        self.grupo_tuberia.setEnabled(False)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Aceptar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        principal.addWidget(botones)

    def igualar(self):
        """True si el tramo toma el diámetro de la tubería más cercana."""
        return self.check_igualar.isChecked()

    def largo_max_m(self):
        return self.spin_largo.value()

    def tuberia(self):
        """La tubería elegida del catálogo, o None si la elige el programa (solo vale sin `igualar`)."""
        return self.combo_tuberia.currentData()
