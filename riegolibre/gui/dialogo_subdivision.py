"""Subdivisión de un lote en sub-bloques (como la ventana «Subdivision» de IRRICAD).

Franjas: paralelas a los laterales (agrupan hileras enteras). Cortes: perpendiculares a los laterales
(los acortan). Entre partes puede quedar un hueco (camino). En modo automático los cortes limitan el
largo de los laterales y las franjas reparten el caudal (o el área, o el número de sub-bloques).
"""

import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QGridLayout,
                                 QGroupBox, QLabel, QMessageBox, QPushButton, QRadioButton, QVBoxLayout)

from ..nucleo.subdivision import (AUTO_AREA, AUTO_CAUDAL, AUTO_NUMERO, DISTANCIA, HILERAS, NINGUNO, NUMERO,
                                  ParametrosSubdivision)
from .comunes import html_tabla, spin


class DialogoSubdivision(QDialog):
    def __init__(self, parent, capa, entidad, params_bloque, angulo_deg, nombre, valores_bloque):
        super().__init__(parent)
        self.capa, self.entidad = capa, entidad
        self.params_bloque, self.angulo = params_bloque, angulo_deg
        self.nombre = nombre or "Lote"
        self.nuevas, self.informe = [], ""
        self.partes = None
        self.setWindowTitle(f"RiegoLibre · Subdividir · {self.nombre}")

        self.etiqueta_info = QLabel()
        self.etiqueta_info.setTextFormat(Qt.TextFormat.RichText)

        # --- automática
        self.grupo_auto = QGroupBox("Automática")
        self.grupo_auto.setCheckable(True)
        self.grupo_auto.setChecked(False)
        rejilla = QGridLayout(self.grupo_auto)
        self.spin_largo_max = spin(5, 2000, 100, 5, decimales=0, sufijo="m")
        self.spin_largo_max.setToolTip("Los cortes perpendiculares a los laterales dejan laterales de este largo o menos.")
        rejilla.addWidget(QLabel("Largo máximo de lateral:"), 0, 0)
        rejilla.addWidget(self.spin_largo_max, 0, 1)
        self.radio_caudal = QRadioButton("Mismo caudal, máximo:")
        self.radio_area = QRadioButton("Misma área, máxima:")
        self.radio_numero = QRadioButton("Número de sub-bloques:")
        self.radio_caudal.setChecked(True)
        self.grupo_criterio = QButtonGroup(self)
        self.spin_caudal = spin(0.1, 10000, 50, 1, decimales=1, sufijo="m³/h")
        self.spin_area = spin(0.01, 1000, 5, 0.1, decimales=2, sufijo="ha")
        self.spin_numero = spin(1, 500, 4, 1, decimales=0)
        for fila, (radio, control) in enumerate(((self.radio_caudal, self.spin_caudal),
                                                 (self.radio_area, self.spin_area),
                                                 (self.radio_numero, self.spin_numero)), 1):
            self.grupo_criterio.addButton(radio)
            rejilla.addWidget(radio, fila, 0)
            rejilla.addWidget(control, fila, 1)

        # --- franjas (paralelas a los laterales)
        self.grupo_franjas = QGroupBox("Franjas (paralelas a los laterales)")
        rejilla = QGridLayout(self.grupo_franjas)
        rejilla.addWidget(QLabel("Hueco"), 0, 2)
        self.franjas = QButtonGroup(self)
        self.radio_f_ninguna = QRadioButton("Ninguna")
        self.radio_f_distancia = QRadioButton("Ancho (m):")
        self.radio_f_numero = QRadioButton("Número:")
        self.radio_f_hileras = QRadioButton("Hileras:")
        self.spin_f_distancia = spin(1, 5000, 100, 5, decimales=1)
        self.spin_f_numero = spin(1, 200, 4, 1, decimales=0)
        self.spin_f_hileras = spin(1, 2000, 50, 1, decimales=0)
        self.spin_f_hueco = spin(0, 100, 5, 0.5, decimales=1, sufijo="m")
        self.spin_f_hueco.setToolTip("Camino entre franjas: se dejan sin regar las hileras que caen en él.")
        self.spin_f_hueco_hileras = spin(0, 100, 2, 1, decimales=0, sufijo="hileras")
        self.radio_f_ninguna.setChecked(True)
        for fila, (radio, control) in enumerate(((self.radio_f_ninguna, None),
                                                 (self.radio_f_distancia, self.spin_f_distancia),
                                                 (self.radio_f_numero, self.spin_f_numero),
                                                 (self.radio_f_hileras, self.spin_f_hileras)), 1):
            self.franjas.addButton(radio)
            rejilla.addWidget(radio, fila, 0)
            if control is not None:
                rejilla.addWidget(control, fila, 1)
        rejilla.addWidget(self.spin_f_hueco, 2, 2, 2, 1)
        rejilla.addWidget(self.spin_f_hueco_hileras, 4, 2)

        # --- cortes (perpendiculares a los laterales)
        self.grupo_cortes = QGroupBox("Cortes (perpendiculares a los laterales)")
        rejilla = QGridLayout(self.grupo_cortes)
        rejilla.addWidget(QLabel("Hueco"), 0, 2)
        self.cortes = QButtonGroup(self)
        self.radio_c_ninguno = QRadioButton("Ninguno")
        self.radio_c_distancia = QRadioButton("Largo (m):")
        self.radio_c_numero = QRadioButton("Número:")
        self.spin_c_distancia = spin(1, 5000, 100, 5, decimales=1)
        self.spin_c_numero = spin(1, 200, 2, 1, decimales=0)
        self.spin_c_hueco = spin(0, 100, 5, 0.5, decimales=1, sufijo="m")
        self.radio_c_ninguno.setChecked(True)
        for fila, (radio, control) in enumerate(((self.radio_c_ninguno, None),
                                                 (self.radio_c_distancia, self.spin_c_distancia),
                                                 (self.radio_c_numero, self.spin_c_numero)), 1):
            self.cortes.addButton(radio)
            rejilla.addWidget(radio, fila, 0)
            if control is not None:
                rejilla.addWidget(control, fila, 1)
        rejilla.addWidget(self.spin_c_hueco, 2, 2, 2, 1)

        self.etiqueta_resultado = QLabel()
        self.etiqueta_resultado.setWordWrap(True)
        self.etiqueta_resultado.setTextFormat(Qt.TextFormat.RichText)

        botones = QDialogButtonBox()
        boton_previa = QPushButton("Vista previa")
        boton_previa.clicked.connect(self.vista_previa)
        botones.addButton(boton_previa, QDialogButtonBox.ButtonRole.ActionRole)
        boton_ok = botones.addButton(QDialogButtonBox.StandardButton.Ok)
        boton_ok.setText("Subdividir")
        botones.addButton(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        for control in (self.grupo_auto,):
            control.toggled.connect(self._actualizar)
        for grupo in (self.grupo_criterio, self.franjas, self.cortes):
            grupo.buttonToggled.connect(self._actualizar)

        capa = QVBoxLayout(self)
        capa.addWidget(self.etiqueta_info)
        capa.addWidget(self.grupo_auto)
        capa.addWidget(self.grupo_franjas)
        capa.addWidget(self.grupo_cortes)
        capa.addWidget(self.etiqueta_resultado)
        capa.addWidget(botones)
        self._info_lote()
        self._actualizar()

    def _info_lote(self):
        from ..integracion.bloque_mapa import subdividir_en_lote
        try:
            partes = subdividir_en_lote(self.entidad.geometry(), self.params_bloque, self.angulo,
                                        ParametrosSubdivision())
        except ValueError as e:
            self.etiqueta_info.setText(f"<b>{self.nombre}</b>: {e}")
            return
        parte = partes[0][1] if partes else None
        if parte is None:
            return
        self.etiqueta_info.setText(f"<b>{self.nombre}</b><br>" + html_tabla([
            ("Área regada", f"{parte.area_m2 / 10000:.2f} ha"),
            ("Hileras", str(parte.hileras)),
            ("Caudal total", f"{parte.caudal / 1000:.2f} m³/h"),
        ]))

    def _actualizar(self, *_):
        auto = self.grupo_auto.isChecked()
        self.grupo_franjas.setEnabled(not auto)
        self.spin_caudal.setEnabled(self.radio_caudal.isChecked())
        self.spin_area.setEnabled(self.radio_area.isChecked())
        self.spin_numero.setEnabled(self.radio_numero.isChecked())
        self.spin_f_distancia.setEnabled(self.radio_f_distancia.isChecked())
        self.spin_f_numero.setEnabled(self.radio_f_numero.isChecked())
        self.spin_f_hileras.setEnabled(self.radio_f_hileras.isChecked())
        self.spin_f_hueco.setEnabled(self.radio_f_distancia.isChecked() or self.radio_f_numero.isChecked())
        self.spin_f_hueco_hileras.setEnabled(self.radio_f_hileras.isChecked())
        for radio in (self.radio_c_ninguno, self.radio_c_distancia, self.radio_c_numero):
            radio.setEnabled(not auto)
        self.spin_c_distancia.setEnabled(not auto and self.radio_c_distancia.isChecked())
        self.spin_c_numero.setEnabled(not auto and self.radio_c_numero.isChecked())
        self.spin_c_hueco.setEnabled(auto or not self.radio_c_ninguno.isChecked())

    def parametros(self) -> ParametrosSubdivision:
        if self.radio_f_distancia.isChecked():
            franjas, valor, hueco = DISTANCIA, self.spin_f_distancia.value(), self.spin_f_hueco.value()
        elif self.radio_f_numero.isChecked():
            franjas, valor, hueco = NUMERO, self.spin_f_numero.value(), self.spin_f_hueco.value()
        elif self.radio_f_hileras.isChecked():
            franjas, valor, hueco = HILERAS, self.spin_f_hileras.value(), self.spin_f_hueco_hileras.value()
        else:
            franjas, valor, hueco = NINGUNO, 0.0, 0.0
        if self.radio_c_distancia.isChecked():
            cortes, valor_c = DISTANCIA, self.spin_c_distancia.value()
        elif self.radio_c_numero.isChecked():
            cortes, valor_c = NUMERO, self.spin_c_numero.value()
        else:
            cortes, valor_c = NINGUNO, 0.0
        criterio = AUTO_CAUDAL if self.radio_caudal.isChecked() else (
            AUTO_AREA if self.radio_area.isChecked() else AUTO_NUMERO)
        auto = self.grupo_auto.isChecked()
        return ParametrosSubdivision(
            automatica=auto, longitud_max_lateral_m=self.spin_largo_max.value(), criterio=criterio,
            caudal_max=self.spin_caudal.value() * 1000, area_max_m2=self.spin_area.value() * 10000,
            numero=int(self.spin_numero.value()),
            franjas=franjas, franjas_valor=valor, franjas_hueco=hueco if not auto else self.spin_f_hueco.value(),
            cortes=cortes, cortes_valor=valor_c, cortes_hueco_m=self.spin_c_hueco.value())

    def _calcular(self):
        from ..integracion.bloque_mapa import subdividir_en_lote
        return subdividir_en_lote(self.entidad.geometry(), self.params_bloque, self.angulo, self.parametros())

    def vista_previa(self):
        from ..integracion.bloque_mapa import vista_previa_subdivision
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.partes = self._calcular()
            vista_previa_subdivision(self.partes, self.capa.crs())
        except ValueError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", str(e))
            return False
        QApplication.restoreOverrideCursor()
        filas = [(f"{self.nombre}-{i}", f"{p.hileras} hileras · {p.area_m2 / 10000:.2f} ha · "
                                        f"{p.caudal / 1000:.2f} m³/h")
                 for i, (_, p) in enumerate(self.partes, 1)]
        self.etiqueta_resultado.setText(f"<b>{len(self.partes)} sub-bloques</b>" + html_tabla(filas))
        parent = self.parent()
        if parent is not None and getattr(parent, "iface", None) is not None:
            parent.iface.mapCanvas().refresh()
        return True

    def accept(self):
        from ..integracion.bloque_mapa import quitar_vista_previa, reemplazar_lote_por_partes
        if not self.vista_previa():
            return
        if len(self.partes) < 2:
            QMessageBox.information(self, "RiegoLibre", "Con estos valores el lote queda en una sola parte.")
            return
        respuesta = QMessageBox.question(
            self, "RiegoLibre", f"El lote «{self.nombre}» se reemplazará por {len(self.partes)} sub-bloques "
            f"(«{self.nombre}-1», «{self.nombre}-2»…) en la capa «{self.capa.name()}». ¿Continuar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        nombres = [f"{self.nombre}-{i}" for i in range(1, len(self.partes) + 1)]
        try:
            self.nuevas = reemplazar_lote_por_partes(self.capa, self.entidad, self.partes, nombres)
        except ValueError as e:
            QMessageBox.warning(self, "RiegoLibre", str(e))
            return
        quitar_vista_previa()
        from .dialogo_trazado import eliminar_grupos
        eliminar_grupos(re.escape(f"RiegoLibre · {self.nombre}"))  # resultados del lote entero
        self.informe = (f"<h3>Lote «{self.nombre}» subdividido</h3>" + self.etiqueta_resultado.text()
                        + "<p>Los sub-bloques heredaron los parámetros del bloque. Calcule cada uno con un clic, o "
                        "todos con <b>Aplicar a los lotes seleccionados</b>.</p>")
        super().accept()

    def reject(self):
        from ..integracion.bloque_mapa import quitar_vista_previa
        quitar_vista_previa()
        super().reject()
