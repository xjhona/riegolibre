"""Importación de la topografía de un plano CAD (DXF): curvas de nivel → DEM y lindero → polígono."""

import os

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                                 QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                                 QTableWidgetItem, QVBoxLayout)

from ..integracion.topografia_cad import (agregar_al_mapa, capas_que_usan, celdas_estimadas,
                                          generar_topografia, leer_dxf, parecen_coordenadas_planas)
from .comunes import html_avisos, html_tabla, spin

AJUSTE_CARPETA = "RiegoLibre/topografia_carpeta"
USO_NINGUNO, USO_CURVAS, USO_LINDERO = "No usar", "Curvas de nivel", "Lindero"


def _formato_cotas(capa):
    if capa.cota_min is None:
        return "sin elevación"
    if capa.cota_min == capa.cota_max:
        return f"{capa.cota_min:g} m"
    return f"{capa.cota_min:g} – {capa.cota_max:g} m"


class DialogoTopografia(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.contenido = None
        self.setWindowTitle("RiegoLibre · Importar topografía de CAD (DXF)")
        self.resize(760, 760)

        grupo_archivo = QGroupBox("Plano CAD")
        capa_archivo = QVBoxLayout(grupo_archivo)
        fila = QHBoxLayout()
        self.edit_dxf = QLineEdit()
        self.edit_dxf.setPlaceholderText("Archivo .dxf con las curvas de nivel (polilíneas con elevación)")
        self.edit_dxf.editingFinished.connect(self._leer)
        boton_dxf = QPushButton("Examinar…")
        boton_dxf.clicked.connect(self._elegir_dxf)
        fila.addWidget(self.edit_dxf)
        fila.addWidget(boton_dxf)
        capa_archivo.addLayout(fila)
        nota = QLabel("Si el plano está en DWG, guárdelo desde el CAD como «AutoCAD DXF» (2013 o 2018).")
        nota.setWordWrap(True)
        capa_archivo.addWidget(nota)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Capa del CAD", "Líneas", "Cotas", "Uso"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setMinimumHeight(150)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for columna in (1, 2, 3):
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        capa_archivo.addWidget(self.tabla)
        self.etiqueta_contenido = QLabel()
        self.etiqueta_contenido.setWordWrap(True)
        capa_archivo.addWidget(self.etiqueta_contenido)

        grupo_opciones = QGroupBox("Modelo de elevación")
        formulario = QFormLayout(grupo_opciones)
        self.selector_crs = QgsProjectionSelectionWidget()
        self.selector_crs.setCrs(QgsProject.instance().crs())
        self.selector_crs.crsChanged.connect(self._actualizar_resumen)
        formulario.addRow("Sistema de coordenadas del plano:", self.selector_crs)
        self.spin_paso = spin(0.1, 50, 1.0, 0.5, sufijo="m")
        self.spin_paso.setToolTip("Lado de la celda del DEM. 1 m basta para curvas cada 0.5–1 m; "
                                  "celdas menores no agregan precisión a unas curvas.")
        self.spin_paso.valueChanged.connect(self._actualizar_resumen)
        formulario.addRow("Tamaño de celda:", self.spin_paso)
        self.spin_distancia = spin(1, 1000, 30, 5, decimales=0, sufijo="m")
        self.spin_distancia.setToolTip(
            "Las celdas más lejos que esto de cualquier curva quedan sin dato. Evita que la triangulación "
            "invente terreno en huecos y bordes sin levantamiento. Auméntela si el terreno es muy plano "
            "y las curvas quedan muy separadas.")
        formulario.addRow("Distancia máxima a una curva:", self.spin_distancia)
        fila_carpeta = QHBoxLayout()
        self.edit_carpeta = QLineEdit()
        self.edit_carpeta.setPlaceholderText("La carpeta del DXF")
        boton_carpeta = QPushButton("…")
        boton_carpeta.setMaximumWidth(32)
        boton_carpeta.clicked.connect(self._elegir_carpeta)
        fila_carpeta.addWidget(self.edit_carpeta)
        fila_carpeta.addWidget(boton_carpeta)
        formulario.addRow("Carpeta de salida:", fila_carpeta)

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setVisible(False)
        self.etiqueta_resultado = QLabel()
        self.etiqueta_resultado.setWordWrap(True)
        self.etiqueta_resultado.setTextFormat(Qt.TextFormat.RichText)

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
        principal.addWidget(self.barra)
        principal.addWidget(self.etiqueta_resultado)
        principal.addLayout(botones)

    # ------------------------------------------------------------- lectura

    def _elegir_dxf(self):
        inicio = self.edit_dxf.text() or QgsSettings().value(AJUSTE_CARPETA, "")
        ruta, _ = QFileDialog.getOpenFileName(self, "Plano CAD", inicio, "Dibujo DXF (*.dxf *.DXF)")
        if ruta:
            self.edit_dxf.setText(ruta)
            QgsSettings().setValue(AJUSTE_CARPETA, os.path.dirname(ruta))
            self._leer()

    def _elegir_carpeta(self):
        inicio = self.edit_carpeta.text() or os.path.dirname(self.edit_dxf.text())
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida", inicio)
        if carpeta:
            self.edit_carpeta.setText(carpeta)

    def _leer(self):
        ruta = self.edit_dxf.text().strip()
        self.contenido = None
        self.tabla.setRowCount(0)
        self.etiqueta_resultado.clear()
        if not ruta:
            self._actualizar_resumen()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.contenido = leer_dxf(ruta)
        except ValueError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            self._actualizar_resumen()
            return
        QApplication.restoreOverrideCursor()

        candidatas_lindero = [c for c in self.contenido.capas if not c.parece_curvas and c.cerradas]
        self.tabla.setRowCount(len(self.contenido.capas))
        for i, capa in enumerate(self.contenido.capas):
            self.tabla.setItem(i, 0, QTableWidgetItem(capa.nombre))
            lineas = QTableWidgetItem(f"{capa.lineas}" + (f" ({capa.cerradas} cerradas)" if capa.cerradas else ""))
            lineas.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(i, 1, lineas)
            self.tabla.setItem(i, 2, QTableWidgetItem(_formato_cotas(capa)))
            uso = QComboBox()
            uso.addItems([USO_NINGUNO, USO_CURVAS, USO_LINDERO])
            if capa.parece_curvas:
                uso.setCurrentText(USO_CURVAS)
            elif len(candidatas_lindero) == 1 and capa is candidatas_lindero[0]:
                uso.setCurrentText(USO_LINDERO)
            uso.currentTextChanged.connect(lambda texto, combo=uso: self._cambio_uso(combo, texto))
            self.tabla.setCellWidget(i, 3, uso)

        crs = self.selector_crs.crs()
        if parecen_coordenadas_planas(self.contenido.extension) and (not crs.isValid() or crs.isGeographic()):
            self.selector_crs.setCrs(QgsCoordinateReferenceSystem())
        self._actualizar_resumen()

    def _cambio_uso(self, combo, texto):
        if texto == USO_LINDERO:  # un solo lindero
            for i in range(self.tabla.rowCount()):
                otro = self.tabla.cellWidget(i, 3)
                if otro is not combo and otro.currentText() == USO_LINDERO:
                    otro.setCurrentText(USO_NINGUNO)
        self._actualizar_resumen()

    def _capas_con_uso(self, uso):
        return [self.tabla.item(i, 0).text() for i in range(self.tabla.rowCount())
                if self.tabla.cellWidget(i, 3).currentText() == uso]

    def _actualizar_resumen(self, *_):
        if self.contenido is None:
            self.etiqueta_contenido.setText("")
            self.boton_importar.setEnabled(False)
            return
        c = self.contenido
        celdas = celdas_estimadas(c.extension, self.spin_paso.value())
        filas = [("Tamaño del dibujo:", f"{c.ancho:,.0f} × {c.alto:,.0f} m".replace(",", " ")),
                 ("Celdas del DEM (aprox.):", f"{celdas / 1e6:.1f} millones")]
        faltantes = []  # impiden importar
        crs = self.selector_crs.crs()
        if not crs.isValid():
            faltantes.append("Elija el sistema de coordenadas del plano (por ejemplo, WGS 84 / UTM de la zona "
                             "del proyecto). El DXF no lo indica.")
        elif crs.isGeographic():
            faltantes.append("El sistema elegido está en grados; las coordenadas del plano están en metros.")
        if not self._capas_con_uso(USO_CURVAS):
            faltantes.append("Marque al menos una capa como «Curvas de nivel».")
        avisos = list(faltantes)
        if c.ancho < 1 or c.ancho > 100_000:
            avisos.append("El tamaño del dibujo no parece estar en metros: revise las unidades del CAD.")
        self.etiqueta_contenido.setText(html_tabla(filas) + html_avisos(avisos))
        self.boton_importar.setEnabled(not faltantes)

    # ------------------------------------------------------------- importación

    def importar(self):
        ruta = self.edit_dxf.text().strip()
        carpeta = self.edit_carpeta.text().strip() or os.path.dirname(ruta)
        base = os.path.splitext(os.path.basename(ruta))[0]
        salidas = [os.path.join(carpeta, f"{base}_curvas.gpkg"), os.path.join(carpeta, f"{base}_dem.tif")]
        existentes = [s for s in salidas if os.path.exists(s)]
        if existentes:
            respuesta = QMessageBox.question(
                self, "RiegoLibre", "Ya existen estos archivos y se reemplazarán:\n\n"
                + "\n".join(os.path.basename(s) for s in existentes) + "\n\n¿Continuar?")
            if respuesta != QMessageBox.StandardButton.Yes:
                return
            proyecto = QgsProject.instance()
            for capa in capas_que_usan(existentes):
                proyecto.removeMapLayer(capa.id())

        linderos = self._capas_con_uso(USO_LINDERO)
        self.barra.setValue(0)
        self.barra.setVisible(True)
        self.boton_importar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def progreso(fraccion, texto):
            self.barra.setValue(int(fraccion * 100))
            self.barra.setFormat(f"{texto} %p %")
            QApplication.processEvents()

        try:
            resultado = generar_topografia(
                ruta, self._capas_con_uso(USO_CURVAS), self.selector_crs.crs().toWkt(), carpeta,
                paso_m=self.spin_paso.value(), distancia_max_m=self.spin_distancia.value(),
                capa_lindero=linderos[0] if linderos else None, nombre_base=base, progreso=progreso)
        except (ValueError, RuntimeError) as error:
            QApplication.restoreOverrideCursor()
            self.barra.setVisible(False)
            self.boton_importar.setEnabled(True)
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        if not QgsProject.instance().crs().isValid():
            QgsProject.instance().setCrs(self.selector_crs.crs())
        curvas, _, _ = agregar_al_mapa(resultado, f"Topografía · {base}")
        lienzo = self.iface.mapCanvas()
        lienzo.setExtent(lienzo.mapSettings().layerExtentToOutputExtent(curvas, curvas.extent()))
        lienzo.refresh()
        QApplication.restoreOverrideCursor()
        self.barra.setVisible(False)
        self.boton_importar.setEnabled(True)

        filas = [("Curvas importadas:", f"{resultado.curvas}"),
                 ("Cotas:", f"{resultado.cota_min:.2f} – {resultado.cota_max:.2f} m"),
                 ("DEM:", f"{resultado.columnas} × {resultado.filas} celdas de {resultado.paso_m:g} m "
                          f"({resultado.cobertura * 100:.0f} % con dato)")]
        if resultado.linderos:
            filas.append(("Lindero:", f"{resultado.linderos} polígono(s), {resultado.area_lindero_ha:.2f} ha"))
        filas.append(("Archivos:", f"{os.path.basename(resultado.ruta_dem)}<br>"
                                   f"{os.path.basename(resultado.ruta_curvas)}"))
        self.etiqueta_resultado.setText(
            "<b>Topografía importada.</b> Elija la capa «DEM (curvas del CAD)» como modelo de elevación "
            "en las demás ventanas de RiegoLibre." + html_tabla(filas) + html_avisos(resultado.avisos))
