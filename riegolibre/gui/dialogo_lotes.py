"""Importación de los lotes de un plano CAD (DXF): polilíneas cerradas → capa de polígonos «Lotes»."""

import os

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..integracion.lotes import agregar_al_mapa, importar_lotes, ruta_por_defecto
from ..integracion.topografia_cad import capas_que_usan, leer_dxf
from .comunes import html_avisos, html_tabla
from .dialogo_topografia import AJUSTE_CARPETA, AJUSTE_CRS, _nota


class DialogoLotes(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.contenido = None
        self.setWindowTitle("RiegoLibre · Importar lotes de CAD")
        self.resize(640, 560)

        grupo_archivo = QGroupBox("Plano CAD")
        capa_archivo = QVBoxLayout(grupo_archivo)
        fila = QHBoxLayout()
        self.edit_dxf = QLineEdit()
        self.edit_dxf.setPlaceholderText("Archivo .dxf con los lotes (polilíneas cerradas)")
        self.edit_dxf.editingFinished.connect(self._leer)
        boton_dxf = QPushButton("Examinar…")
        boton_dxf.clicked.connect(self._elegir_dxf)
        fila.addWidget(self.edit_dxf)
        fila.addWidget(boton_dxf)
        capa_archivo.addLayout(fila)

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Capa del CAD", "Polilíneas cerradas"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        capa_archivo.addWidget(_nota("Marque las capas del CAD que tienen los lotes:"))
        capa_archivo.addWidget(self.tabla)

        grupo_opciones = QGroupBox("Opciones")
        formulario = QFormLayout(grupo_opciones)
        self.selector_crs = QgsProjectionSelectionWidget()
        self.selector_crs.setCrs(self._crs_inicial())
        formulario.addRow("Sistema de coordenadas del plano:", self.selector_crs)
        self.check_textos = QCheckBox("Tomar el nombre de cada lote del texto que tenga dentro")
        self.check_textos.setChecked(True)
        formulario.addRow(self.check_textos)
        fila_salida = QHBoxLayout()
        self.edit_salida = QLineEdit()
        self.edit_salida.setPlaceholderText("Junto al DXF: «nombre_lotes.gpkg»")
        boton_salida = QPushButton("…")
        boton_salida.setMaximumWidth(32)
        boton_salida.clicked.connect(self._elegir_salida)
        fila_salida.addWidget(self.edit_salida)
        fila_salida.addWidget(boton_salida)
        formulario.addRow("Archivo de salida:", fila_salida)

        self.etiqueta = QLabel()
        self.etiqueta.setWordWrap(True)
        self.etiqueta.setTextFormat(Qt.TextFormat.RichText)
        self.etiqueta.setText(
            "<p>Cada polilínea cerrada se convierte en un lote. Después, active la herramienta "
            "<b>Bloque de goteo</b> y haga clic en un lote para diseñarlo.</p>")

        botones = QHBoxLayout()
        botones.addStretch()
        self.boton_importar = QPushButton("Importar")
        self.boton_importar.setEnabled(False)
        self.boton_importar.clicked.connect(self.importar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)
        botones.addWidget(self.boton_importar)
        botones.addWidget(boton_cerrar)

        principal = QVBoxLayout(self)
        principal.addWidget(grupo_archivo, 1)
        principal.addWidget(grupo_opciones)
        principal.addWidget(self.etiqueta)
        principal.addLayout(botones)

    def _crs_inicial(self):
        proyecto = QgsProject.instance().crs()
        if proyecto.isValid() and not proyecto.isGeographic():
            return proyecto
        guardado = QgsCoordinateReferenceSystem(QgsSettings().value(AJUSTE_CRS, ""))
        return guardado if guardado.isValid() else QgsCoordinateReferenceSystem()

    def _elegir_dxf(self):
        inicio = self.edit_dxf.text() or QgsSettings().value(AJUSTE_CARPETA, "")
        ruta, _ = QFileDialog.getOpenFileName(self, "Plano CAD con los lotes", inicio, "Dibujo DXF (*.dxf *.DXF)")
        if ruta:
            self.edit_dxf.setText(ruta)
            QgsSettings().setValue(AJUSTE_CARPETA, os.path.dirname(ruta))
            self._leer()

    def _elegir_salida(self):
        inicio = self.edit_salida.text() or ruta_por_defecto(self.edit_dxf.text() or "lotes.dxf")
        ruta, _ = QFileDialog.getSaveFileName(self, "Archivo de lotes", inicio, "GeoPackage (*.gpkg)")
        if ruta:
            self.edit_salida.setText(ruta)

    def _leer(self):
        ruta = self.edit_dxf.text().strip()
        self.contenido = None
        self.tabla.setRowCount(0)
        self.boton_importar.setEnabled(False)
        if not ruta:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.contenido = leer_dxf(ruta)
        except ValueError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        QApplication.restoreOverrideCursor()
        capas = [c for c in self.contenido.capas if c.cerradas]
        self.tabla.setRowCount(len(capas))
        mayor = max(capas, key=lambda c: c.cerradas, default=None)
        for i, capa in enumerate(capas):
            item = QTableWidgetItem(capa.nombre)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if capa is mayor else Qt.CheckState.Unchecked)
            self.tabla.setItem(i, 0, item)
            numero = QTableWidgetItem(str(capa.cerradas))
            numero.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(i, 1, numero)
        if not capas:
            QMessageBox.warning(self, "RiegoLibre", "El plano no tiene polilíneas cerradas.")
        self.boton_importar.setEnabled(bool(capas))

    def _capas_marcadas(self):
        return [self.tabla.item(i, 0).text() for i in range(self.tabla.rowCount())
                if self.tabla.item(i, 0).checkState() == Qt.CheckState.Checked]

    def importar(self):
        capas = self._capas_marcadas()
        crs = self.selector_crs.crs()
        if not capas:
            QMessageBox.information(self, "RiegoLibre", "Marque al menos una capa del CAD.")
            return
        if not crs.isValid() or crs.isGeographic():
            QMessageBox.information(self, "RiegoLibre", "Elija el sistema de coordenadas proyectado (UTM) del plano.")
            return
        ruta_dxf = self.edit_dxf.text().strip()
        salida = self.edit_salida.text().strip() or ruta_por_defecto(ruta_dxf)
        abiertas = capas_que_usan([salida])
        if abiertas:
            respuesta = QMessageBox.question(
                self, "RiegoLibre", f"El archivo «{os.path.basename(salida)}» ya está en el mapa y se va a "
                "reemplazar (se pierden los parámetros de los bloques guardados en él). ¿Continuar?")
            if respuesta != QMessageBox.StandardButton.Yes:
                return
            for capa in abiertas:
                QgsProject.instance().removeMapLayer(capa.id())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resultado = importar_lotes(ruta_dxf, capas, crs.toWkt(), salida, self.check_textos.isChecked())
            capa = agregar_al_mapa(resultado.ruta)
        except ValueError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        QApplication.restoreOverrideCursor()
        QgsSettings().setValue(AJUSTE_CRS, crs.authid() or crs.toWkt())
        if not QgsProject.instance().crs().isValid():
            QgsProject.instance().setCrs(crs)
        if self.iface is not None:
            self.iface.mapCanvas().setExtent(self.iface.mapCanvas().mapSettings().layerExtentToOutputExtent(
                capa, capa.extent()))
            self.iface.mapCanvas().refresh()
        self.etiqueta.setText(
            "<h3>Lotes importados</h3>" + html_tabla([
                ("Lotes", str(resultado.lotes)),
                ("Área total", f"{resultado.area_ha:,.2f} ha"),
                ("Con nombre del plano", str(resultado.con_nombre)),
                ("Archivo", os.path.basename(resultado.ruta)),
            ]) + html_avisos(resultado.avisos)
            + "<p>Siguiente paso: active la herramienta <b>Bloque de goteo</b> y haga clic en un lote.</p>")
