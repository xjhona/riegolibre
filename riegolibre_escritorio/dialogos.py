# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Cuadros pequeños del programa: proyecto nuevo, turnos de riego, ficha de un objeto y tabla de atributos."""

import math
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                               QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from . import edicion
from .edicion import epsg_utm, zona_de_epsg


def _numero(minimo, maximo, decimales, sufijo=""):
    caja = QDoubleSpinBox()
    caja.setRange(minimo, maximo)
    caja.setDecimals(decimales)
    caja.setGroupSeparatorShown(True)
    if sufijo:
        caja.setSuffix(sufijo)
    return caja


class DialogoNuevo(QDialog):
    """Proyecto desde cero: nombre, sistema de coordenadas (zona UTM), terreno y dónde empezar a dibujar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Proyecto nuevo")
        self.edit_nombre = QLineEdit("Proyecto nuevo")

        self.caja_zona = QSpinBox()
        self.caja_zona.setRange(1, 60)
        self.caja_zona.setValue(18)
        self.combo_hemisferio = QComboBox()
        self.combo_hemisferio.addItems(["Sur", "Norte"])
        self.caja_epsg = QSpinBox()
        self.caja_epsg.setRange(1024, 999999)
        self.caja_zona.valueChanged.connect(self._zona_a_epsg)
        self.combo_hemisferio.currentIndexChanged.connect(self._zona_a_epsg)
        self.caja_epsg.valueChanged.connect(self._epsg_a_zona)
        self._zona_a_epsg()
        fila_zona = QHBoxLayout()
        fila_zona.addWidget(self.caja_zona)
        fila_zona.addWidget(self.combo_hemisferio)
        src = QGroupBox("Sistema de coordenadas (UTM, WGS 84)")
        f = QFormLayout(src)
        f.addRow("Zona UTM:", fila_zona)
        f.addRow("EPSG:", self.caja_epsg)

        self.caja_este = _numero(0, 1_000_000, 1, " m")
        self.caja_este.setValue(500_000)
        self.caja_norte = _numero(0, 10_000_000, 1, " m")
        self.caja_norte.setValue(8_650_000)
        referencia = QGroupBox("Dónde empezar a dibujar")
        f = QFormLayout(referencia)
        f.addRow("Este:", self.caja_este)
        f.addRow("Norte:", self.caja_norte)
        f.addRow(QLabel("El mapa se abre alrededor de este punto (coordenadas UTM del fundo)."))

        self.radio_llano = QRadioButton("Llano (sin cotas)")
        self.radio_plano = QRadioButton("Plano inclinado")
        self.radio_llano.setChecked(True)
        self.caja_cota = _numero(-500, 9000, 2, " m")
        self.caja_cota.setValue(100)
        self.caja_px = _numero(-50, 50, 3, " %")
        self.caja_py = _numero(-50, 50, 3, " %")
        terreno = QGroupBox("Terreno")
        f = QFormLayout(terreno)
        f.addRow(self.radio_llano)
        f.addRow(self.radio_plano)
        f.addRow("Cota en el punto de inicio:", self.caja_cota)
        f.addRow("Pendiente hacia el este:", self.caja_px)
        f.addRow("Pendiente hacia el norte:", self.caja_py)
        f.addRow(QLabel("Para las curvas de nivel de un plano de CAD: menú Terreno → «Importar curvas de nivel (DXF)…»."))
        self.radio_plano.toggled.connect(self._terreno)
        self._terreno()

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        principal = QVBoxLayout(self)
        formulario = QFormLayout()
        formulario.addRow("Nombre:", self.edit_nombre)
        principal.addLayout(formulario)
        for grupo in (src, referencia, terreno):
            principal.addWidget(grupo)
        principal.addWidget(botones)

    def _zona_a_epsg(self):
        epsg = epsg_utm(self.caja_zona.value(), self.combo_hemisferio.currentIndex() == 0)
        if self.caja_epsg.value() != epsg:
            self.caja_epsg.setValue(epsg)

    def _epsg_a_zona(self):
        zona = zona_de_epsg(self.caja_epsg.value())
        if zona:
            self.caja_zona.blockSignals(True)
            self.combo_hemisferio.blockSignals(True)
            self.caja_zona.setValue(zona[0])
            self.combo_hemisferio.setCurrentIndex(0 if zona[1] else 1)
            self.caja_zona.blockSignals(False)
            self.combo_hemisferio.blockSignals(False)

    def _terreno(self):
        for caja in (self.caja_cota, self.caja_px, self.caja_py):
            caja.setEnabled(self.radio_plano.isChecked())

    def valores(self) -> dict:
        """Argumentos de `ProyectoRiego.nuevo`."""
        referencia = (self.caja_este.value(), self.caja_norte.value())
        terreno = None
        if self.radio_plano.isChecked():
            terreno = {"tipo": "plano", "cota_m": self.caja_cota.value(), "origen": list(referencia),
                       "pendiente_x": self.caja_px.value() / 100, "pendiente_y": self.caja_py.value() / 100}
        return {"nombre": self.edit_nombre.text(), "epsg": self.caja_epsg.value(), "terreno": terreno,
                "referencia": referencia}


class DialogoTurnos(QDialog):
    """Número de turnos y turno de cada lote (automático: se reparte por caudal)."""

    def __init__(self, datos: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Turnos de riego")
        red = datos.get("red") or {}
        self.fijos = dict(red.get("turnos_fijos") or {})
        self.lotes = [str(l.get("nombre")) for l in datos.get("lotes", [])]
        self.caja_turnos = QSpinBox()
        self.caja_turnos.setRange(1, 50)
        self.caja_turnos.setValue(max(1, int(red.get("turnos", 1))))
        self.caja_turnos.valueChanged.connect(self._llenar)
        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Lote", "Turno"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        formulario = QFormLayout()
        formulario.addRow("Número de turnos:", self.caja_turnos)
        capa.addLayout(formulario)
        capa.addWidget(QLabel("Los lotes en «Automático» se reparten solos: cada uno al turno con menos caudal."))
        capa.addWidget(self.tabla)
        capa.addWidget(botones)
        self.resize(420, 480)
        self._llenar()

    def _llenar(self):
        actuales = self.turnos_fijos() if self.tabla.rowCount() else self.fijos
        n = self.caja_turnos.value()
        self.tabla.setRowCount(len(self.lotes))
        for i, nombre in enumerate(self.lotes):
            item = QTableWidgetItem(nombre)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tabla.setItem(i, 0, item)
            combo = QComboBox()
            combo.addItem("Automático", 0)
            for t in range(1, n + 1):
                combo.addItem(f"Turno {t}", t)
            turno = int(actuales.get(nombre, 0))
            combo.setCurrentIndex(max(0, combo.findData(turno if turno <= n else 0)))
            self.tabla.setCellWidget(i, 1, combo)

    def turnos_fijos(self) -> Dict[str, int]:
        fijos = {}
        for i, nombre in enumerate(self.lotes):
            combo = self.tabla.cellWidget(i, 1)
            if combo is not None and combo.currentData():
                fijos[nombre] = int(combo.currentData())
        return fijos


class DialogoFicha(QDialog):
    """Ficha de texto de un objeto («Object Info»), en letra de ancho fijo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Información del objeto")
        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        fuente = QFont("Consolas")
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        fuente.setPointSize(9)
        self.texto.setFont(fuente)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.close)
        capa = QVBoxLayout(self)
        capa.addWidget(self.texto)
        capa.addWidget(botones)
        self.resize(760, 460)

    def mostrar(self, ficha):
        self.setWindowTitle(f"Información del objeto · {ficha.titulo}")
        self.texto.setPlainText(ficha.texto)


def _item(valor, decimales=None):
    texto = f"{valor:.{decimales}f}" if decimales is not None and isinstance(valor, (int, float)) else str(valor)
    item = QTableWidgetItem(texto)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if isinstance(valor, (int, float)):
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class TablaAtributos(QTabWidget):
    """Lotes, tramos y nodos de la matriz dibujada. Clic: selecciona en el mapa; doble clic en un lote: su bloque."""

    elegido = Signal(object)  # objeto de `edicion` («lote», i), («matriz», i) o («nodo», i)
    abrir_lote = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabla_lotes = self._tabla(["Lote", "Vértices", "Área (ha)", "Turno", "Parámetros propios"])
        self.tabla_matriz = self._tabla(["Tramo", "Longitud (m)", "Nodo inicial", "Nodo final", "Desde", "Hasta"])
        self.tabla_nodos = self._tabla(["Nodo", "Este (m)", "Norte (m)", "Tramos"])
        self.addTab(self.tabla_lotes, "Lotes")
        self.addTab(self.tabla_matriz, "Tubería matriz")
        self.addTab(self.tabla_nodos, "Nodos de la matriz")
        self.tabla_nodos.cellClicked.connect(lambda fila, _c: self.elegido.emit(("nodo", fila)))
        self.tabla_lotes.cellClicked.connect(lambda fila, _c: self.elegido.emit(("lote", fila)))
        self.tabla_lotes.cellDoubleClicked.connect(lambda fila, _c: self.abrir_lote.emit(fila))
        self.tabla_matriz.cellClicked.connect(lambda fila, _c: self.elegido.emit(("matriz", fila)))

    @staticmethod
    def _tabla(encabezados):
        tabla = QTableWidget(0, len(encabezados))
        tabla.setHorizontalHeaderLabels(encabezados)
        tabla.verticalHeader().setVisible(False)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tabla.horizontalHeader().setStretchLastSection(True)
        return tabla

    def cargar(self, datos: dict):
        from mcp_riegolibre.motor import GOTEO_POR_OMISION
        fijos = (datos.get("red") or {}).get("turnos_fijos") or {}
        lotes = datos.get("lotes", [])
        self.tabla_lotes.setRowCount(len(lotes))
        for i, lote in enumerate(lotes):
            anillos = edicion.anillos_lote(lote)
            area = (edicion.area(anillos[0]) - sum(edicion.area(h) for h in anillos[1:])) if anillos and anillos[0] else 0
            propios = ", ".join(sorted(k for k in lote if k in GOTEO_POR_OMISION))
            nombre = str(lote.get("nombre"))
            for j, valor in enumerate([nombre, len(anillos[0]) if anillos else 0, area / 10000,
                                       fijos.get(nombre, "automático"), propios or "—"]):
                self.tabla_lotes.setItem(i, j, _item(valor, 3 if j == 2 else None))
        tramos = edicion.matriz(datos)
        nodos = edicion.nodos_matriz(datos)

        def numero(p):
            return next(k + 1 for k, q in enumerate(nodos) if math.dist(p, q) <= edicion.EPS_NODO)

        self.tabla_matriz.setRowCount(len(tramos))
        for i, (a, b) in enumerate(tramos):
            valores = [i + 1, edicion.longitud([a, b]), numero(a), numero(b), f"{a[0]:.1f}, {a[1]:.1f}",
                       f"{b[0]:.1f}, {b[1]:.1f}"]
            for j, valor in enumerate(valores):
                self.tabla_matriz.setItem(i, j, _item(valor, 2 if j == 1 else None))
        self.tabla_nodos.setRowCount(len(nodos))
        for i, p in enumerate(nodos):
            llegan = sorted(j + 1 for j, _k in edicion.tramos_en_nodo(tramos, p))
            for j, valor in enumerate([i + 1, p[0], p[1], ", ".join(map(str, llegan))]):
                self.tabla_nodos.setItem(i, j, _item(valor, 2 if j in (1, 2) else None))

    def marcar(self, objeto: Optional[tuple]):
        tablas = {"lote": self.tabla_lotes, "matriz": self.tabla_matriz, "nodo": self.tabla_nodos}
        for tabla in tablas.values():
            tabla.blockSignals(True)
            tabla.clearSelection()
            tabla.blockSignals(False)
        if objeto and objeto[0] in tablas:
            tabla = tablas[objeto[0]]
            if objeto[1] < tabla.rowCount():
                tabla.blockSignals(True)
                tabla.selectRow(objeto[1])
                tabla.blockSignals(False)
