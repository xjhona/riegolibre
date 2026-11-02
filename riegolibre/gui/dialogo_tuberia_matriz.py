# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Cuadro previo a dibujar (o editar) la tubería matriz, como «Mainline Pipe» de IRRICAD.

Pide el diámetro: uno del catálogo o «Elegida por el programa» («Computer Selected»), que deja el
diámetro por dimensionar hasta que se calcula la red. La capa («Matriz») la pone el programa solo.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                                 QLabel, QVBoxLayout)

from ..nucleo.tuberias import clave_economica

TEXTO_POR_PROGRAMA = "Elegida por el programa (por dimensionar)"


class DialogoTuberiaMatriz(QDialog):
    """`catalogo`: tuberías para elegir. `elegida`: la tubería que queda marcada (None = «Elegida por el
    programa»). Con `edicion` el título dice que se cambia el diámetro de tuberías ya dibujadas."""

    def __init__(self, catalogo, elegida=None, edicion=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RiegoLibre · Editar tubería matriz" if edicion else "RiegoLibre · Tubería matriz")
        self.setMinimumWidth(420)
        principal = QVBoxLayout(self)

        grupo = QGroupBox("Propiedades de la tubería")
        formulario = QFormLayout(grupo)
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
        ayuda = QLabel("Con «Elegida por el programa» el diámetro queda sin fijar: se calcula al pulsar "
                       "<b>Calcular</b>, el menor que cumple la velocidad máxima y la presión. Con un "
                       "diámetro del catálogo, el cálculo lo respeta.")
        ayuda.setWordWrap(True)
        formulario.addRow(ayuda)
        principal.addWidget(grupo)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Aceptar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        principal.addWidget(botones)

    def tuberia(self):
        """La tubería elegida del catálogo, o None si la elige el programa."""
        return self.combo_tuberia.currentData()
