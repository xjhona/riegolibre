# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventanas «Importar curvas de nivel (DXF)» (capas de curvas, celda del DEM y distancia máxima) e «Importar
lotes y líneas (DXF)» (qué hacer con cada capa y de dónde salen los nombres de los lotes).

La de curvas es como la ventana de topografía del complemento (`riegolibre/gui/dialogo_topografia.py`), sin la
imagen satelital ni el lindero.
"""

import math
import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
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


def avisos_de_coordenadas(extension, extension_proyecto) -> List[str]:
    """Avisos si el dibujo parece en grados o queda lejos del proyecto (otra zona UTM)."""
    avisos = []
    if not parecen_coordenadas_planas(extension):
        avisos.append("Las coordenadas del dibujo parecen grados, no metros: el plano debe estar en UTM.")
    elif extension_proyecto:
        xmin, xmax, ymin, ymax = extension
        ex0, ey0, ex1, ey1 = extension_proyecto
        dx = max(0.0, ex0 - xmax, xmin - ex1)
        dy = max(0.0, ey0 - ymax, ymin - ey1)
        if math.hypot(dx, dy) > LEJOS_M:
            avisos.append(f"El dibujo queda a {math.hypot(dx, dy) / 1000:,.0f} km de los lotes del proyecto: "
                          "¿está en la misma zona UTM?")
    return avisos


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
        return avisos_de_coordenadas(self.contenido.extension, extension_proyecto)

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


# ------------------------------------------------------------------ lotes y líneas de un DXF

NO_IMPORTAR, LOTES, LINEAS = "No importar", "Lotes", "Líneas de referencia"
PISTAS_LOTES = ("lote", "parcela", "sector", "cuartel", "campo", "bloque", "area", "área", "turno")
SIN_NOMBRES = "(numerarlos: Lote 1, Lote 2…)"


def _parece(nombre: str, pistas) -> bool:
    nombre = nombre.lower()
    return any(p in nombre for p in pistas)


def uso_inicial(capa) -> str:
    """Qué hacer por omisión con una capa del DXF: las curvas de nivel no se importan (van por su propio menú);
    las capas con polilíneas cerradas y nombre de lote, como lotes; lo demás, como líneas de referencia."""
    if capa.parece_curvas:
        return NO_IMPORTAR
    if capa.cerradas and _parece(capa.nombre, PISTAS_LOTES):
        return LOTES
    return LINEAS


class DialogoDibujo(QDialog):
    """«Importar lotes y líneas (DXF)»: qué hacer con cada capa del dibujo y de dónde salen los nombres."""

    def __init__(self, ruta: str, contenido, extension_proyecto=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar lotes y líneas (DXF)")
        self.contenido = contenido
        self.resize(620, 560)

        archivo = QLabel(f"<b>{os.path.basename(ruta)}</b><br>Dibujo de {contenido.ancho:,.0f} × "
                         f"{contenido.alto:,.0f} m".replace(",", " "))
        archivo.setTextFormat(Qt.TextFormat.RichText)

        self.tabla = QTableWidget(len(contenido.capas), 4)
        self.tabla.setHorizontalHeaderLabels(["Capa", "Líneas", "Cerradas", "Importar como"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.usos = []
        for fila, capa in enumerate(contenido.capas):
            nombre = QTableWidgetItem(capa.nombre)
            if capa.parece_curvas:
                nombre.setToolTip("Sus líneas tienen elevación: parecen curvas de nivel (menú Terreno → "
                                  "«Importar curvas de nivel (DXF)…»)")
            self.tabla.setItem(fila, 0, nombre)
            for columna, texto in enumerate((str(capa.lineas), str(capa.cerradas)), 1):
                celda = QTableWidgetItem(texto)
                celda.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(fila, columna, celda)
            uso = QComboBox()
            uso.addItems([NO_IMPORTAR, LOTES, LINEAS])
            uso.setCurrentText(uso_inicial(capa))
            uso.currentTextChanged.connect(lambda _: self._revisar())
            self.tabla.setCellWidget(fila, 3, uso)
            self.usos.append(uso)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for columna in (1, 2, 3):
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        capas = QGroupBox("Capas del dibujo")
        v = QVBoxLayout(capas)
        v.addWidget(self.tabla)
        explicacion = QLabel("«Lotes»: cada polilínea cerrada pasa a ser un lote (una dentro de otra es su hueco). "
                             "«Líneas de referencia»: caminos, canales, linderos… se dibujan de fondo en la capa "
                             "DIBUJO_CAD y el imán se pega a ellas al dibujar.")
        explicacion.setWordWrap(True)
        v.addWidget(explicacion)

        self.caja_nombres = QComboBox()
        self.caja_nombres.addItem(SIN_NOMBRES, None)
        for capa, n in sorted(contenido.textos.items(), key=lambda c: c[0].lower()):
            self.caja_nombres.addItem(f"Textos de la capa «{capa}» ({n})", capa)
        for indice in range(1, self.caja_nombres.count()):  # una capa de textos con nombre de lote
            if _parece(self.caja_nombres.itemData(indice), PISTAS_LOTES + ("nombre", "texto", "rotulo", "rótulo")):
                self.caja_nombres.setCurrentIndex(indice)
                break
        nombres = QGroupBox("Nombres de los lotes")
        f = QFormLayout(nombres)
        f.addRow("Tomarlos de:", self.caja_nombres)
        ayuda = QLabel("Cada lote toma el texto que cae dentro de él. Un nombre que ya existe en el proyecto se "
                       "importa como «nombre (2)».")
        ayuda.setWordWrap(True)
        f.addRow(ayuda)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Importar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(archivo)
        principal.addWidget(capas, 1)
        principal.addWidget(nombres)
        principal.addWidget(self.aviso)
        principal.addWidget(self.botones)
        self._avisos_fijos = avisos_de_coordenadas(contenido.extension, extension_proyecto)
        self._revisar()

    def capas_con(self, uso: str) -> List[str]:
        return [capa.nombre for capa, caja in zip(self.contenido.capas, self.usos) if caja.currentText() == uso]

    def fijar_uso(self, capa: str, uso: str):
        for c, caja in zip(self.contenido.capas, self.usos):
            if c.nombre == capa:
                caja.setCurrentText(uso)

    def valores(self) -> dict:
        lotes = self.capas_con(LOTES)
        return {"capas_lotes": lotes, "capas_lineas": self.capas_con(LINEAS),
                "capa_nombres": self.caja_nombres.currentData() if lotes else None}

    def _revisar(self) -> Optional[str]:
        problema = None
        lotes, lineas = self.capas_con(LOTES), self.capas_con(LINEAS)
        de_capa = {c.nombre: c for c in self.contenido.capas}
        if not lotes and not lineas:
            problema = "Elija al menos una capa para importar."
        elif lotes and not any(de_capa[c].cerradas for c in lotes):
            problema = "Las capas de lotes no tienen polilíneas cerradas."
        textos = list(self._avisos_fijos)
        if problema:
            textos.insert(0, problema)
        else:
            partes = []
            if lotes:
                partes.append(f"hasta {sum(de_capa[c].cerradas for c in lotes)} lotes")
            if lineas:
                partes.append(f"{sum(de_capa[c].lineas for c in lineas)} líneas de referencia")
            textos.append("Se importarán " + " y ".join(partes) + ".")
        self.caja_nombres.setEnabled(bool(lotes) and self.caja_nombres.count() > 1)
        self.aviso.setText("\n".join(textos))
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(problema is None)
        return problema
