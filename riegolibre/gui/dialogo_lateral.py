"""Calculadora de lateral de goteo."""

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QMessageBox, QPushButton,
                                 QRadioButton, QSplitter, QTextBrowser,
                                 QVBoxLayout, QWidget)

from ..nucleo import (Lateral, PresionInsuficiente, cargar_catalogo_emisores,
                      cargar_catalogo_tuberias, longitud_maxima)
from .comunes import (M_POR_BAR, Figure, FigureCanvasQTAgg, descripcion_emisor,
                      html_avisos, html_estado, html_tabla)
from .comunes import spin as _spin


class DialogoLateral(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Calculadora de lateral (goteo)")
        self.resize(1100, 680)

        self.tuberias = cargar_catalogo_tuberias(uso="lateral")
        self.emisores = cargar_catalogo_emisores()

        panel = QWidget()
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(480)
        izquierda = QVBoxLayout(panel)
        izquierda.addWidget(self._grupo_lateral())
        izquierda.addWidget(self._grupo_terreno())
        izquierda.addWidget(self._grupo_calculo())
        izquierda.addStretch()

        self.texto = QTextBrowser()
        derecha = QSplitter(Qt.Orientation.Vertical)
        derecha.addWidget(self.texto)
        self.figura = None
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(6, 3.2), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            derecha.addWidget(self.lienzo)
        derecha.setSizes([300, 360])

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(panel)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_calcular = QPushButton("Calcular")
        self.boton_calcular.setDefault(True)
        self.boton_longitud = QPushButton("Longitud máxima")
        botones.addButton(self.boton_calcular, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(self.boton_longitud, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_calcular.clicked.connect(self.calcular)
        self.boton_longitud.clicked.connect(self.calcular_longitud_maxima)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)

        self._actualizar_emisor()
        self._actualizar_modo()
        self._actualizar_terreno()
        self.texto.setHtml(
            "<p>Configure el lateral y pulse <b>Calcular</b>.</p>"
            "<p><b>Longitud máxima</b> busca el lateral más largo que cumple la variación "
            "de caudal admisible (y, si lo indica, la presión de entrada máxima).</p>")

    # ---------------------------------------------------------------- interfaz

    def _grupo_lateral(self):
        grupo = QGroupBox("Lateral")
        formulario = QFormLayout(grupo)

        self.combo_tuberia = QComboBox()
        for t in self.tuberias:
            self.combo_tuberia.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)")
        formulario.addRow("Tubería:", self.combo_tuberia)

        self.combo_emisor = QComboBox()
        for e in self.emisores:
            self.combo_emisor.addItem(e.nombre)
        self.combo_emisor.currentIndexChanged.connect(self._actualizar_emisor)
        formulario.addRow("Emisor:", self.combo_emisor)
        self.etiqueta_emisor = QLabel()
        self.etiqueta_emisor.setWordWrap(True)
        formulario.addRow("", self.etiqueta_emisor)

        self.spin_espaciamiento = _spin(0.05, 10, 0.30, 0.05, sufijo="m")
        formulario.addRow("Espaciamiento entre emisores:", self.spin_espaciamiento)
        self.spin_primer = _spin(0.0, 10, 0.30, 0.05, sufijo="m")
        formulario.addRow("Distancia al primer emisor:", self.spin_primer)
        self.spin_longitud = _spin(1, 2000, 100, 5, decimales=1, sufijo="m")
        formulario.addRow("Longitud del lateral:", self.spin_longitud)
        self.spin_pendiente = _spin(-50, 50, 0, 0.5, sufijo="%")
        self.spin_pendiente.setToolTip("Positiva si el terreno sube desde la entrada hacia el final.")
        formulario.addRow("Pendiente:", self.spin_pendiente)
        return grupo

    def _grupo_terreno(self):
        grupo = QGroupBox("Perfil del terreno desde el mapa")
        formulario = QFormLayout(grupo)
        self.check_terreno = QCheckBox("Usar una línea dibujada y un DEM")
        self.check_terreno.toggled.connect(self._actualizar_terreno)
        formulario.addRow(self.check_terreno)

        self.combo_linea = QgsMapLayerComboBox()
        self.combo_linea.setFilters(Qgis.LayerFilter.LineLayer)
        formulario.addRow("Capa de líneas:", self.combo_linea)
        self.combo_dem = QgsMapLayerComboBox()
        self.combo_dem.setFilters(Qgis.LayerFilter.RasterLayer)
        formulario.addRow("DEM:", self.combo_dem)
        nota = QLabel("Se usa la línea seleccionada; su primer vértice es la entrada del lateral.")
        nota.setWordWrap(True)
        formulario.addRow(nota)
        return grupo

    def _grupo_calculo(self):
        grupo = QGroupBox("Cálculo")
        formulario = QFormLayout(grupo)

        self.radio_requerida = QRadioButton("Calcular la presión de entrada necesaria")
        self.radio_conocida = QRadioButton("Presión de entrada conocida:")
        self.radio_requerida.setChecked(True)
        self.radio_requerida.toggled.connect(self._actualizar_modo)
        formulario.addRow(self.radio_requerida)
        fila = QHBoxLayout()
        self.spin_presion = _spin(0.5, 100, 12, 0.5, sufijo="m")
        fila.addWidget(self.radio_conocida)
        fila.addWidget(self.spin_presion)
        formulario.addRow(fila)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Darcy-Weisbach", "darcy")
        self.combo_metodo.addItem("Hazen-Williams", "hazen")
        formulario.addRow("Fórmula de pérdidas:", self.combo_metodo)

        self.spin_variacion = _spin(1, 50, 10, 1, decimales=1, sufijo="%")
        formulario.addRow("Variación de caudal admisible:", self.spin_variacion)
        self.spin_presion_max = _spin(0, 100, 0, 1, decimales=1, sufijo="m")
        self.spin_presion_max.setSpecialValueText("sin límite")
        formulario.addRow("Presión de entrada máxima:", self.spin_presion_max)
        return grupo

    def _actualizar_emisor(self):
        self.etiqueta_emisor.setText(descripcion_emisor(self.emisor()))

    def _actualizar_modo(self):
        self.spin_presion.setEnabled(self.radio_conocida.isChecked())

    def _actualizar_terreno(self):
        usar = self.check_terreno.isChecked()
        self.combo_linea.setEnabled(usar)
        self.combo_dem.setEnabled(usar)
        self.spin_longitud.setEnabled(not usar)
        self.spin_pendiente.setEnabled(not usar)

    # ------------------------------------------------------------------ datos

    def tuberia(self):
        return self.tuberias[self.combo_tuberia.currentIndex()]

    def emisor(self):
        return self.emisores[self.combo_emisor.currentIndex()]

    def _crear_lateral(self):
        comunes = dict(
            distancia_primer_emisor_m=self.spin_primer.value(),
            metodo=self.combo_metodo.currentData(),
        )
        espaciamiento = self.spin_espaciamiento.value()
        if self.check_terreno.isChecked():
            from ..integracion.perfil_terreno import entidad_unica, extraer_perfil
            capa_linea, capa_dem = self.combo_linea.currentLayer(), self.combo_dem.currentLayer()
            if capa_linea is None or capa_dem is None:
                raise ValueError("Elija una capa de líneas y un DEM.")
            longitud, perfil = extraer_perfil(
                capa_linea, entidad_unica(capa_linea), capa_dem, paso_m=max(espaciamiento, 0.5))
            self.spin_longitud.setValue(longitud)
            return Lateral.desde_longitud(self.tuberia(), self.emisor(), espaciamiento, longitud,
                                          perfil=perfil, **comunes)
        return Lateral.desde_longitud(self.tuberia(), self.emisor(), espaciamiento,
                                      self.spin_longitud.value(),
                                      pendiente=self.spin_pendiente.value() / 100, **comunes)

    # ---------------------------------------------------------------- acciones

    def calcular(self):
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lateral = self._crear_lateral()
            if self.radio_conocida.isChecked():
                resultado = lateral.simular(self.spin_presion.value())
            else:
                resultado = lateral.presion_entrada_requerida()
        except (ValueError, PresionInsuficiente) as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "RiegoLibre", error)
            return
        self._mostrar(lateral, resultado)

    def calcular_longitud_maxima(self):
        if self.check_terreno.isChecked():
            QMessageBox.information(
                self, "RiegoLibre",
                "La longitud máxima se calcula con la pendiente uniforme indicada en «Pendiente», "
                "no con el perfil del DEM.")
        presion_max = self.spin_presion_max.value() or None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            longitud, resultado = longitud_maxima(
                self.tuberia(), self.emisor(), self.spin_espaciamiento.value(),
                pendiente=self.spin_pendiente.value() / 100,
                distancia_primer_emisor_m=self.spin_primer.value(),
                variacion_caudal_max=self.spin_variacion.value() / 100,
                presion_entrada_max_m=presion_max,
                longitud_limite_m=2000.0,
                metodo=self.combo_metodo.currentData())
        finally:
            QApplication.restoreOverrideCursor()
        if resultado is None:
            QMessageBox.warning(self, "RiegoLibre", "Ningún lateral cumple los criterios indicados.")
            return
        if not self.check_terreno.isChecked():
            self.spin_longitud.setValue(longitud)
        lateral = Lateral(self.tuberia(), self.emisor(), self.spin_espaciamiento.value(),
                          resultado.numero_emisores,
                          distancia_primer_emisor_m=self.spin_primer.value(),
                          pendiente=self.spin_pendiente.value() / 100,
                          metodo=self.combo_metodo.currentData())
        self._mostrar(lateral, resultado, titulo=f"Longitud máxima: {longitud:.1f} m")

    # --------------------------------------------------------------- resultados

    def _mostrar(self, lateral, r, titulo="Resultados del lateral"):
        variacion_max = self.spin_variacion.value() / 100
        presion_max = self.spin_presion_max.value() or None
        cumple = r.cumple(variacion_max) and (presion_max is None or r.presion_entrada_m <= presion_max)
        estado = html_estado(cumple)
        avisos = []
        if r.emisores_fuera_de_rango:
            avisos.append(f"{r.emisores_fuera_de_rango} emisores fuera del rango de compensación.")
        if r.variacion_caudal > variacion_max:
            avisos.append(f"La variación de caudal supera el {variacion_max:.0%} admitido.")
        if presion_max is not None and r.presion_entrada_m > presion_max:
            avisos.append(f"La presión de entrada supera los {presion_max:g} m indicados.")
        if r.velocidad_entrada_ms > 2.0:
            avisos.append("La velocidad a la entrada supera 2 m/s.")
        tuberia = lateral.tuberia
        if tuberia.presion_nominal_m and r.presion_max_m > tuberia.presion_nominal_m:
            avisos.append(f"La presión supera la nominal de la tubería ({tuberia.presion_nominal_m:g} m).")

        filas = [
            ("Longitud del lateral", f"{lateral.longitud_m:.1f} m ({r.numero_emisores} emisores)"),
            ("Presión de entrada", f"<b>{r.presion_entrada_m:.2f} m</b> ({r.presion_entrada_m / M_POR_BAR:.2f} bar)"),
            ("Caudal del lateral", f"<b>{r.caudal_total_lh:.1f} L/h</b> ({r.caudal_total_lh / 3600:.3f} L/s)"),
            ("Velocidad en la entrada", f"{r.velocidad_entrada_ms:.2f} m/s"),
            ("Pérdida por fricción", f"{r.perdida_friccion_m:.2f} m"),
            ("Desnivel entrada → final", f"{r.cotas_m[-1]:+.2f} m"),
            ("Presión mín. / media / máx.",
             f"{r.presion_min_m:.2f} / {r.presion_media_m:.2f} / {r.presion_max_m:.2f} m"),
            ("Caudal mín. / medio / máx.",
             f"{r.caudal_min_lh:.3f} / {r.caudal_medio_lh:.3f} / {r.caudal_max_lh:.3f} L/h"),
            ("Variación de presión", f"{r.variacion_presion_m:.2f} m"),
            ("Variación de caudal", f"{r.variacion_caudal:.1%}"),
            ("Uniformidad de emisión (EU)", f"{r.uniformidad_emision:.1f} %"),
        ]
        self.texto.setHtml(f"<h3>{titulo} — {estado}</h3>" + html_tabla(filas) + html_avisos(avisos))
        self._graficar(lateral, r)

    def _graficar(self, lateral, r):
        if self.figura is None:
            return
        self.figura.clear()
        ejes = self.figura.add_subplot(111)
        ejes.plot(r.posiciones_m, r.presiones_m, color="#1e88e5", label="Presión en el emisor")
        e = lateral.emisor
        if e.autocompensado:
            ejes.axhspan(e.presion_compensacion_m, e.presion_max_m or max(r.presiones_m),
                         color="#1e88e5", alpha=0.08, label="Rango de compensación")
        else:
            ejes.axhline(e.presion_nominal_m, color="#1e88e5", linestyle=":", label="Presión nominal")
        ejes.set_xlabel("Distancia desde la entrada (m)")
        ejes.set_ylabel("Presión (m.c.a.)")
        ejes.grid(True, alpha=0.3)

        terreno = ejes.twinx()
        terreno.plot(r.posiciones_m, r.cotas_m, color="#6d4c41", linewidth=1, label="Terreno (relativo)")
        terreno.set_ylabel("Cota relativa (m)")

        lineas = ejes.get_legend_handles_labels()
        lineas_t = terreno.get_legend_handles_labels()
        ejes.legend(lineas[0] + lineas_t[0], lineas[1] + lineas_t[1], loc="best", fontsize=8)
        self.lienzo.draw()
