# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana «Importar curvas de nivel (DXF)»: elegir las capas de curvas, la celda del DEM y la distancia máxima.

Como la ventana de topografía del complemento (`riegolibre/gui/dialogo_topografia.py`), sin la imagen satelital
ni el lindero: aquí solo se leen las curvas.
"""

import math
import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .topografia import MAX_CELDAS, ContenidoDxf, celdas_estimadas, parecen_coordenadas_planas

LEJOS_M = 50_000  # dibujo y proyecto a más de esto: seguramente otras coordenadas (otra zona, otro origen)


def _numero(minimo, maximo, decimales, sufijo, valor):
    caja = QDoubleSpinBox()
    caja.setRange(minimo, maximo)
    caja.setDecimals(decimales)
    caja.setSuffix(sufijo)
    caja.setValue(valor)
    return caja


def _cotas(capa):
    if capa.cota_min is None:
        return "—"
    return f"{capa.cota_min:g} – {capa.cota_max:g} m"


class DialogoCurvas(QDialog):
    def __init__(self, ruta: str, contenido: ContenidoDxf, extension_proyecto=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar curvas de nivel (DXF)")
        self.contenido = contenido
        self.resize(560, 520)

        archivo = QLabel(f"<b>{os.path.basename(ruta)}</b><br>Dibujo de {contenido.ancho:,.0f} × "
                         f"{contenido.alto:,.0f} m".replace(",", " "))
        archivo.setTextFormat(Qt.TextFormat.RichText)

        self.tabla = QTableWidget(len(contenido.capas), 4)
        self.tabla.setHorizontalHeaderLabels(["Capa", "Líneas", "Con cota", "Cotas"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for fila, capa in enumerate(contenido.capas):
            nombre = QTableWidgetItem(capa.nombre)
            nombre.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            nombre.setCheckState(Qt.CheckState.Checked if capa.parece_curvas else Qt.CheckState.Unchecked)
            self.tabla.setItem(fila, 0, nombre)
            for columna, texto in enumerate((str(capa.lineas), str(capa.con_cota), _cotas(capa)), 1):
                celda = QTableWidgetItem(texto)
                celda.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(fila, columna, celda)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for columna in (1, 2, 3):
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.itemChanged.connect(lambda _: self._revisar())
        capas = QGroupBox("Capas con las curvas de nivel")
        v = QVBoxLayout(capas)
        v.addWidget(self.tabla)
        v.addWidget(QLabel("Se marcan solas las capas con líneas que tienen elevación (Z distinta de 0)."))

        self.caja_paso = _numero(0.1, 50, 2, " m", 1.0)
        self.caja_distancia = _numero(1, 1000, 0, " m", 30.0)
        self.caja_paso.valueChanged.connect(lambda _: self._revisar())
        dem = QGroupBox("DEM (modelo digital de elevación)")
        f = QFormLayout(dem)
        f.addRow("Tamaño de celda:", self.caja_paso)
        f.addRow("Distancia máxima a una curva:", self.caja_distancia)
        f.addRow(QLabel("Las curvas se triangulan (TIN) y la cota de cada celda se interpola en su triángulo. "
                        "Las celdas más lejos de una curva que la distancia máxima quedan sin cota."))
        for etiqueta in dem.findChildren(QLabel):
            etiqueta.setWordWrap(True)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Importar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(archivo)
        principal.addWidget(capas, 1)
        principal.addWidget(dem)
        principal.addWidget(self.aviso)
        principal.addWidget(self.botones)
        self._avisos_fijos = self._avisos_de_coordenadas(extension_proyecto)
        self._revisar()

    def _avisos_de_coordenadas(self, extension_proyecto) -> List[str]:
        avisos = []
        if not parecen_coordenadas_planas(self.contenido.extension):
            avisos.append("Las coordenadas del dibujo parecen grados, no metros: el plano debe estar en UTM.")
        elif extension_proyecto:
            xmin, xmax, ymin, ymax = self.contenido.extension
            ex0, ey0, ex1, ey1 = extension_proyecto
            dx = max(0.0, ex0 - xmax, xmin - ex1)
            dy = max(0.0, ey0 - ymax, ymin - ey1)
            if math.hypot(dx, dy) > LEJOS_M:
                avisos.append(f"El dibujo queda a {math.hypot(dx, dy) / 1000:,.0f} km de los lotes del proyecto: "
                              "¿está en la misma zona UTM?")
        return avisos

    def capas_elegidas(self) -> List[str]:
        return [self.tabla.item(fila, 0).text() for fila in range(self.tabla.rowCount())
                if self.tabla.item(fila, 0).checkState() == Qt.CheckState.Checked]

    def valores(self) -> dict:
        return {"capas_curvas": self.capas_elegidas(), "paso_m": self.caja_paso.value(),
                "distancia_max_m": self.caja_distancia.value()}

    def _revisar(self) -> Optional[str]:
        """Muestra los avisos y apaga «Importar» si no se puede."""
        problema = None
        elegidas = set(self.capas_elegidas())
        if not elegidas:
            problema = "Marque al menos una capa de curvas."
        elif not any(c.con_cota for c in self.contenido.capas if c.nombre in elegidas):
            problema = "Las capas marcadas no tienen líneas con elevación."
        celdas = celdas_estimadas(self.contenido.extension, self.caja_paso.value())
        if not problema and celdas > MAX_CELDAS:
            problema = (f"El DEM tendría unos {celdas / 1e6:.0f} millones de celdas: use una celda más grande.")
        textos = list(self._avisos_fijos)
        if problema:
            textos.insert(0, problema)
        else:
            textos.append(f"Hasta {celdas / 1e6:.1f} millones de celdas (se guardan solo las que tienen cota).")
        self.aviso.setText("\n".join(textos))
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(problema is None)
        return problema
