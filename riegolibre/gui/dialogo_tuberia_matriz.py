"""Cuadro previo a dibujar (o editar) la tubería matriz, como «Mainline Pipe» de IRRICAD.

Pide la capa donde se dibuja y el diámetro: uno del catálogo o «Elegida por el programa»
(«Computer Selected»), que deja el diámetro por dimensionar hasta que se calcula la red.
"""

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                                 QLabel, QMessageBox, QVBoxLayout)

from ..nucleo.tuberias import clave_economica

TEXTO_POR_PROGRAMA = "Elegida por el programa (por dimensionar)"


class DialogoTuberiaMatriz(QDialog):
    """`catalogo`: tuberías para elegir. `capa`: la capa que se propone. `elegida`: la tubería que
    queda marcada (None = «Elegida por el programa»). Con `edicion` no se pide la capa."""

    def __init__(self, catalogo, capa=None, elegida=None, edicion=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RiegoLibre · Editar tubería matriz" if edicion else "RiegoLibre · Tubería matriz")
        self.setMinimumWidth(420)
        principal = QVBoxLayout(self)

        self.combo_capa = None
        if not edicion:
            grupo = QGroupBox("Propiedades del dibujo")
            formulario = QFormLayout(grupo)
            self.combo_capa = QgsMapLayerComboBox()
            self.combo_capa.setFilters(Qgis.LayerFilter.LineLayer)
            self.combo_capa.setLayer(capa)
            self.combo_capa.setToolTip("Capa de líneas donde queda cada tubería dibujada. Si no la tiene, se "
                                       "le agrega el campo «tuberia» con el diámetro.")
            formulario.addRow("Capa:", self.combo_capa)
            principal.addWidget(grupo)

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

    def capa(self):
        return self.combo_capa.currentLayer() if self.combo_capa is not None else None

    def tuberia(self):
        """La tubería elegida del catálogo, o None si la elige el programa."""
        return self.combo_tuberia.currentData()

    def accept(self):
        if self.combo_capa is not None and self.combo_capa.currentLayer() is None:
            QMessageBox.warning(self, "RiegoLibre", "Elija la capa de líneas donde dibujar la tubería.")
            return
        super().accept()
