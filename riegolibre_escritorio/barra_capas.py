# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Barra de capas, como la «Layer Bar» de IRRICAD: una fila compacta por capa (ver, imprimir) y, debajo, las
propiedades de la capa elegida (color, tipo de línea y grosor; en la imagen de fondo, su transparencia)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHeaderView, QLabel,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .capas import CAPAS, CAPAS_IMAGEN, TIPOS_LINEA

COL_COLOR, COL_NOMBRE, COL_VER, COL_IMPRIMIR = range(4)
ALTO_FILA = 18


def _muestra(color, ancho=12, alto=12) -> QIcon:
    pixmap = QPixmap(ancho, alto)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class BarraCapas(QWidget):
    """Emite `visibilidad(capa, visible)` al marcar «ver» y `estilo_cambiado(capa)` al cambiar el resto."""

    visibilidad = Signal(str, bool)
    estilo_cambiado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.estilos = {}
        self._cargando = False

        self.tabla = QTableWidget(len(CAPAS), 4)
        self.tabla.setHorizontalHeaderLabels(["", "Nombre", "👁", "🖨"])
        self.tabla.horizontalHeaderItem(COL_VER).setToolTip("Se ve en el dibujo")
        self.tabla.horizontalHeaderItem(COL_IMPRIMIR).setToolTip("Se imprime en los planos")
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(ALTO_FILA)
        self.tabla.verticalHeader().setMinimumSectionSize(ALTO_FILA)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(COL_NOMBRE, QHeaderView.ResizeMode.Stretch)
        for columna in (COL_COLOR, COL_VER, COL_IMPRIMIR):
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.Fixed)
            self.tabla.setColumnWidth(columna, 24)
        self.tabla.setShowGrid(False)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setStyleSheet("QTableWidget { padding: 0px; } QTableWidget::item { padding: 0px 2px; }")
        for fila, (nombre, (_, _, _, descripcion)) in enumerate(CAPAS.items()):
            item = QTableWidgetItem(nombre)
            item.setToolTip(descripcion)
            item.setData(Qt.ItemDataRole.UserRole, nombre)
            self.tabla.setItem(fila, COL_NOMBRE, item)
            self.tabla.setItem(fila, COL_COLOR, QTableWidgetItem())
            for columna in (COL_VER, COL_IMPRIMIR):
                casilla = QTableWidgetItem()
                casilla.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                                 | Qt.ItemFlag.ItemIsSelectable)
                self.tabla.setItem(fila, columna, casilla)
        self.tabla.setFixedHeight(self.tabla.horizontalHeader().height() + ALTO_FILA * len(CAPAS) + 26)
        self.tabla.itemChanged.connect(self._casilla_cambiada)
        self.tabla.currentCellChanged.connect(lambda *_: self._mostrar_propiedades())

        self.descripcion = QLabel()
        self.descripcion.setWordWrap(True)
        self.boton_color = QPushButton()
        self.boton_color.setToolTip("Color de la capa")
        self.boton_color.clicked.connect(self._elegir_color)
        self.combo_linea = QComboBox()
        for clave, texto in TIPOS_LINEA.items():
            self.combo_linea.addItem(texto, clave)
        self.combo_linea.currentIndexChanged.connect(lambda _: self._cambiar("linea", self.combo_linea.currentData()))
        self.caja_ancho = QDoubleSpinBox()
        self.caja_ancho.setRange(0.1, 12.0)
        self.caja_ancho.setSingleStep(0.2)
        self.caja_ancho.setDecimals(1)
        self.caja_ancho.setSuffix(" px")
        self.caja_ancho.valueChanged.connect(lambda v: self._cambiar("ancho", round(v, 1)))
        self.caja_transparencia = QSpinBox()
        self.caja_transparencia.setRange(0, 95)
        self.caja_transparencia.setSingleStep(10)
        self.caja_transparencia.setSuffix(" %")
        self.caja_transparencia.setToolTip("0 %: la imagen se ve entera; más, se aclara y resaltan las líneas")
        self.caja_transparencia.valueChanged.connect(lambda v: self._cambiar("transparencia", int(v)))
        formulario = QFormLayout()
        formulario.addRow("Color:", self.boton_color)
        formulario.addRow("Tipo de línea:", self.combo_linea)
        formulario.addRow("Grosor:", self.caja_ancho)
        formulario.addRow("Transparencia:", self.caja_transparencia)
        formulario.addRow(self.descripcion)
        self.formulario = formulario
        self.grupo = QGroupBox("Propiedades de la capa")
        self.grupo.setLayout(formulario)

        disposicion = QVBoxLayout(self)
        disposicion.setContentsMargins(2, 2, 2, 2)
        disposicion.addWidget(self.tabla)
        disposicion.addStretch(1)
        disposicion.addWidget(self.grupo)
        self.tabla.setCurrentCell(0, COL_NOMBRE)

    # ------------------------------------------------------------ datos

    def cargar(self, estilos: dict, diametros=(), texto_imagen: str = ""):
        """Muestra los estilos del proyecto (el diccionario se modifica en el sitio al cambiar algo).

        `texto_imagen` (fuente y fecha de la imagen de fondo) se suma a la descripción de su capa."""
        self.estilos = estilos
        self._cargando = True
        for fila, nombre in enumerate(CAPAS):
            estilo = estilos[nombre]
            self.tabla.item(fila, COL_COLOR).setIcon(QIcon() if nombre in CAPAS_IMAGEN else _muestra(estilo["color"]))
            self.tabla.item(fila, COL_VER).setCheckState(
                Qt.CheckState.Checked if estilo["visible"] else Qt.CheckState.Unchecked)
            self.tabla.item(fila, COL_IMPRIMIR).setCheckState(
                Qt.CheckState.Checked if estilo["imprimir"] else Qt.CheckState.Unchecked)
        fila_red = list(CAPAS).index("RED_PRINCIPAL")
        texto = CAPAS["RED_PRINCIPAL"][3]
        if diametros:
            texto += "\n" + "\n".join(f"■ {nombre}" for nombre, _ in diametros)
        self.tabla.item(fila_red, COL_NOMBRE).setToolTip(texto)
        for nombre in CAPAS_IMAGEN:
            texto = CAPAS[nombre][3] + "\n" + (texto_imagen or "Sin imagen")
            self.tabla.item(list(CAPAS).index(nombre), COL_NOMBRE).setToolTip(texto)
        self._cargando = False
        self._mostrar_propiedades()

    def fijar_visible(self, nombre: str, visible: bool):
        """Marca o desmarca «ver» de la capa, como si se hiciera en la tabla (emite `visibilidad`)."""
        self.tabla.item(list(CAPAS).index(nombre), COL_VER).setCheckState(
            Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)

    def capa_actual(self):
        fila = self.tabla.currentRow()
        return list(CAPAS)[fila] if 0 <= fila < len(CAPAS) else None

    def _mostrar_propiedades(self):
        nombre = self.capa_actual()
        if nombre is None or not self.estilos:
            self.grupo.setEnabled(False)
            return
        estilo = self.estilos[nombre]
        self._cargando = True
        self.grupo.setEnabled(True)
        self.grupo.setTitle(f"Propiedades de la capa · {nombre}")
        self.boton_color.setIcon(_muestra(estilo["color"], 40, 12))
        self.boton_color.setText(estilo["color"])
        self.combo_linea.setCurrentIndex(max(0, self.combo_linea.findData(estilo["linea"])))
        self.caja_ancho.setValue(float(estilo["ancho"]))
        es_imagen = nombre in CAPAS_IMAGEN
        for campo in (self.boton_color, self.combo_linea, self.caja_ancho):
            self.formulario.setRowVisible(campo, not es_imagen)
        self.formulario.setRowVisible(self.caja_transparencia, es_imagen)
        if es_imagen:
            self.caja_transparencia.setValue(int(estilo.get("transparencia", 0)))
        self.descripcion.setText(CAPAS[nombre][3])
        self._cargando = False

    # ------------------------------------------------------------ cambios

    def _casilla_cambiada(self, item):
        if self._cargando or not self.estilos or item.column() not in (COL_VER, COL_IMPRIMIR):
            return
        nombre = list(CAPAS)[item.row()]
        marcado = item.checkState() == Qt.CheckState.Checked
        if item.column() == COL_VER:
            self.estilos[nombre]["visible"] = marcado
            self.visibilidad.emit(nombre, marcado)
        else:
            self.estilos[nombre]["imprimir"] = marcado
            self.estilo_cambiado.emit(nombre)

    def _cambiar(self, clave, valor):
        nombre = self.capa_actual()
        if self._cargando or nombre is None or not self.estilos or self.estilos[nombre][clave] == valor:
            return
        self.estilos[nombre][clave] = valor
        if clave == "color":
            self.tabla.item(list(CAPAS).index(nombre), COL_COLOR).setIcon(_muestra(valor))
            self._mostrar_propiedades()
        self.estilo_cambiado.emit(nombre)

    def _elegir_color(self):
        nombre = self.capa_actual()
        if nombre is None:
            return
        color = QColorDialog.getColor(QColor(self.estilos[nombre]["color"]), self, f"Color de la capa {nombre}")
        if color.isValid():
            self._cambiar("color", color.name())
