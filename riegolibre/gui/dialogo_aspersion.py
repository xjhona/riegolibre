# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Calculadora de lateral de aspersión: aspersor con elevador, marco de riego, pluviometría y tiempo de riego."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                                 QSpinBox, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import PresionInsuficiente, cargar_catalogo_tuberias
from ..nucleo.aspersion import (DISPOSICION_RECTANGULAR, DISPOSICION_TRIANGULAR, Elevador, LateralAspersion,
                                Marco, Riego, cargar_catalogo_aspersores, numero_maximo_aspersores)
from .comunes import M_POR_BAR, Figure, FigureCanvasQTAgg, html_avisos, html_estado, html_tabla
from .comunes import spin as _spin
from .tema import aplicar_tema, pintar_figura

# Elevadores habituales: (texto, diámetro interior en mm o None si no se cuenta su pérdida)
ELEVADORES = (
    ("Sin pérdida por fricción", None),
    ("1/2\" galvanizado (DI 15.8 mm)", 15.8),
    ("3/4\" galvanizado (DI 20.9 mm)", 20.9),
    ("1\" galvanizado (DI 26.6 mm)", 26.6),
)
DIAMETRO_MIN_LATERAL_MM = 25.0  # las mangueras de goteo no sirven como lateral de aspersión
DIAMETRO_INICIAL_MM = 35.0  # tubería que se propone al abrir (PE 40 mm o la que le siga)


def descripcion_aspersor(a):
    texto = f"{a.caudal_nominal_m3h:.3f} m³/h a {a.presion_nominal_m:g} m · diámetro mojado {a.diametro_mojado_m:g} m"
    if a.boquilla_mm:
        texto += f" · boquilla {a.boquilla_mm:g} mm"
    if a.presion_min_m is not None and a.presion_max_m is not None:
        texto += f" · trabaja entre {a.presion_min_m:g} y {a.presion_max_m:g} m"
    return texto


class DialogoAspersion(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        aplicar_tema(self)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Calculadora de lateral de aspersión")
        self.resize(1150, 720)

        self.aspersores = cargar_catalogo_aspersores()
        self.tuberias = sorted((t for t in cargar_catalogo_tuberias()
                                if DIAMETRO_MIN_LATERAL_MM <= t.diametro_interior_mm <= 160),
                               key=lambda t: (t.diametro_interior_mm, t.nombre))

        panel = QWidget()
        izquierda = QVBoxLayout(panel)
        izquierda.addWidget(self._grupo_aspersor())
        izquierda.addWidget(self._grupo_marco())
        izquierda.addWidget(self._grupo_lateral())
        izquierda.addWidget(self._grupo_riego())
        izquierda.addWidget(self._grupo_calculo())
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(panel)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(440)
        desplazable.setMaximumWidth(520)

        self.texto = QTextBrowser()
        derecha = QSplitter(Qt.Orientation.Vertical)
        derecha.addWidget(self.texto)
        self.figura = None
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(6, 3.2), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            derecha.addWidget(self.lienzo)
        derecha.setSizes([340, 340])

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(desplazable)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_calcular = QPushButton("Calcular")
        self.boton_calcular.setDefault(True)
        self.boton_maximo = QPushButton("Número máximo de aspersores")
        self.boton_maximo.setToolTip("El lateral más largo cuya variación de presión en las boquillas no pasa la "
                                     "admisible (y, si se indica, la presión de entrada máxima).")
        botones.addButton(self.boton_calcular, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(self.boton_maximo, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_calcular.clicked.connect(self.calcular)
        self.boton_maximo.clicked.connect(self.calcular_maximo)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)

        self._actualizar_aspersor()
        self._actualizar_modo()
        self.texto.setHtml(
            "<p>Elija el aspersor, el marco y la tubería del lateral, y pulse <b>Calcular</b>.</p>"
            "<p>La presión de entrada se calcula para que el caudal medio de los aspersores sea el nominal "
            "(presión media igual a la nominal). El lateral cumple si la diferencia de presión entre las "
            "boquillas no pasa el 20 % de la nominal (regla de Christiansen, unos 10 % de caudal).</p>"
            "<p>Los aspersores del catálogo son genéricos (boquilla de orificio); los de IRRICAD se podrán "
            "importar cuando se agreguen las pestañas <i>Outlets</i> y <i>Nozzles</i> a la base de datos.</p>")

    # ---------------------------------------------------------------- interfaz

    def _grupo_aspersor(self):
        grupo = QGroupBox("Aspersor")
        formulario = QFormLayout(grupo)
        self.combo_aspersor = QComboBox()
        for a in self.aspersores:
            self.combo_aspersor.addItem(a.nombre)
        self.combo_aspersor.currentIndexChanged.connect(self._actualizar_aspersor)
        formulario.addRow("Aspersor:", self.combo_aspersor)
        self.etiqueta_aspersor = QLabel()
        self.etiqueta_aspersor.setWordWrap(True)
        formulario.addRow("", self.etiqueta_aspersor)
        self.spin_altura = _spin(0, 5, 0.6, 0.1, sufijo="m")
        self.spin_altura.setToolTip("Altura del elevador sobre la tubería lateral: se resta de la presión en la "
                                    "boquilla.")
        formulario.addRow("Altura del elevador:", self.spin_altura)
        self.combo_elevador = QComboBox()
        for texto, diametro in ELEVADORES:
            self.combo_elevador.addItem(texto, diametro)
        self.combo_elevador.setCurrentIndex(2)
        formulario.addRow("Tubo del elevador:", self.combo_elevador)
        return grupo

    def _grupo_marco(self):
        grupo = QGroupBox("Marco de riego")
        formulario = QFormLayout(grupo)
        self.spin_se = _spin(1, 60, 12, 0.5, decimales=1, sufijo="m")
        formulario.addRow("Entre aspersores (en el lateral):", self.spin_se)
        self.spin_sl = _spin(1, 60, 12, 0.5, decimales=1, sufijo="m")
        formulario.addRow("Entre laterales:", self.spin_sl)
        self.combo_disposicion = QComboBox()
        self.combo_disposicion.addItem("Rectangular o cuadrado", DISPOSICION_RECTANGULAR)
        self.combo_disposicion.addItem("Triangular (al tresbolillo)", DISPOSICION_TRIANGULAR)
        formulario.addRow("Disposición:", self.combo_disposicion)
        self.spin_viento = _spin(0, 15, 2, 0.5, decimales=1, sufijo="m/s")
        self.spin_viento.setToolTip("Con más viento el marco debe ser más cerrado: menos de 2 m/s, 60 % del "
                                    "diámetro mojado; de 2 a 4 m/s, 50 %; más de 4 m/s, 40 % (triangular: +5 %).")
        formulario.addRow("Viento:", self.spin_viento)
        return grupo

    def _grupo_lateral(self):
        grupo = QGroupBox("Lateral")
        formulario = QFormLayout(grupo)
        self.combo_tuberia = QComboBox()
        for t in self.tuberias:
            self.combo_tuberia.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)")
        inicial = next((i for i, t in enumerate(self.tuberias) if t.diametro_interior_mm >= DIAMETRO_INICIAL_MM), 0)
        self.combo_tuberia.setCurrentIndex(inicial)
        formulario.addRow("Tubería:", self.combo_tuberia)
        self.spin_numero = QSpinBox()
        self.spin_numero.setRange(1, 500)
        self.spin_numero.setValue(8)
        formulario.addRow("Número de aspersores:", self.spin_numero)
        self.spin_primer = _spin(0, 60, 6, 0.5, decimales=1, sufijo="m")
        self.spin_primer.setToolTip("Distancia de la entrada al primer aspersor; lo habitual es medio espaciamiento.")
        formulario.addRow("Distancia al primer aspersor:", self.spin_primer)
        self.spin_se.valueChanged.connect(lambda v: self.spin_primer.setValue(v / 2))
        self.etiqueta_longitud = QLabel()
        formulario.addRow("Longitud del lateral:", self.etiqueta_longitud)
        for control in (self.spin_numero, self.spin_primer, self.spin_se):
            control.valueChanged.connect(self._actualizar_longitud)
        self.spin_pendiente = _spin(-50, 50, 0, 0.5, sufijo="%")
        self.spin_pendiente.setToolTip("Positiva si el terreno sube desde la entrada hacia el final.")
        formulario.addRow("Pendiente:", self.spin_pendiente)
        self._actualizar_longitud()
        return grupo

    def _grupo_riego(self):
        grupo = QGroupBox("Suelo y riego")
        formulario = QFormLayout(grupo)
        self.spin_infiltracion = _spin(0, 200, 0, 1, decimales=1, sufijo="mm/h")
        self.spin_infiltracion.setSpecialValueText("sin dato")
        self.spin_infiltracion.setToolTip("Infiltración básica del suelo: la pluviometría no debe superarla.")
        formulario.addRow("Infiltración básica:", self.spin_infiltracion)
        self.spin_lamina = _spin(0, 300, 0, 1, decimales=1, sufijo="mm")
        self.spin_lamina.setSpecialValueText("sin dato")
        formulario.addRow("Lámina neta por riego:", self.spin_lamina)
        self.spin_eficiencia = _spin(30, 100, 75, 1, decimales=0, sufijo="%")
        formulario.addRow("Eficiencia de aplicación:", self.spin_eficiencia)
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
        self.spin_presion = _spin(1, 150, 35, 0.5, sufijo="m")
        fila.addWidget(self.radio_conocida)
        fila.addWidget(self.spin_presion)
        formulario.addRow(fila)
        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Darcy-Weisbach", "darcy")
        self.combo_metodo.addItem("Hazen-Williams", "hazen")
        formulario.addRow("Fórmula de pérdidas:", self.combo_metodo)
        self.spin_variacion = _spin(5, 50, 20, 1, decimales=0, sufijo="%")
        self.spin_variacion.setToolTip("Diferencia de presión admitida entre las boquillas, en % de la nominal.")
        formulario.addRow("Variación de presión admisible:", self.spin_variacion)
        self.spin_presion_max = _spin(0, 150, 0, 1, decimales=1, sufijo="m")
        self.spin_presion_max.setSpecialValueText("sin límite")
        formulario.addRow("Presión de entrada máxima:", self.spin_presion_max)
        return grupo

    def _actualizar_aspersor(self):
        self.etiqueta_aspersor.setText(descripcion_aspersor(self.aspersor()))

    def _actualizar_modo(self):
        self.spin_presion.setEnabled(self.radio_conocida.isChecked())

    def _actualizar_longitud(self):
        longitud = self.spin_primer.value() + (self.spin_numero.value() - 1) * self.spin_se.value()
        self.etiqueta_longitud.setText(f"{longitud:.1f} m")

    # ------------------------------------------------------------------ datos

    def aspersor(self):
        return self.aspersores[self.combo_aspersor.currentIndex()]

    def tuberia(self):
        return self.tuberias[self.combo_tuberia.currentIndex()]

    def _parametros(self):
        return dict(
            elevador=Elevador(self.spin_altura.value(), self.combo_elevador.currentData()),
            distancia_primer_aspersor_m=self.spin_primer.value(),
            pendiente=self.spin_pendiente.value() / 100,
            metodo=self.combo_metodo.currentData(),
            riego=Riego(self.spin_lamina.value(), self.spin_eficiencia.value() / 100,
                        self.spin_infiltracion.value() or None),
            viento_ms=self.spin_viento.value(),
            variacion_admisible=self.spin_variacion.value() / 100,
        )

    def marco(self):
        return Marco(self.spin_se.value(), self.spin_sl.value(), self.combo_disposicion.currentData())

    def crear_lateral(self, numero=None):
        return LateralAspersion(self.tuberia(), self.aspersor(), self.marco(), numero or self.spin_numero.value(),
                                **self._parametros())

    # ---------------------------------------------------------------- acciones

    def calcular(self):
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lateral = self.crear_lateral()
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
            return None
        self._mostrar(lateral, resultado)
        return resultado

    def calcular_maximo(self):
        parametros = self._parametros()
        presion_max = self.spin_presion_max.value() or None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n, resultado = numero_maximo_aspersores(self.tuberia(), self.aspersor(), self.marco(),
                                                    presion_entrada_max_m=presion_max, **parametros)
        finally:
            QApplication.restoreOverrideCursor()
        if resultado is None:
            QMessageBox.warning(self, "RiegoLibre", "Ni un solo aspersor cumple los criterios indicados.")
            return None
        self.spin_numero.setValue(n)
        self.radio_requerida.setChecked(True)
        self._mostrar(self.crear_lateral(n), resultado, titulo=f"Número máximo: {n} aspersores")
        return resultado

    # --------------------------------------------------------------- resultados

    def _mostrar(self, lateral, r, titulo="Resultados del lateral de aspersión"):
        presion_max = self.spin_presion_max.value() or None
        avisos = r.avisos(presion_max)  # criterios de diseño: deciden si cumple
        observaciones = []  # recomendaciones que no cambian el estado
        l = r.lateral
        if l.velocidad_entrada_ms > 2.0:
            observaciones.append(f"La velocidad a la entrada del lateral ({l.velocidad_entrada_ms:.2f} m/s) supera "
                                 "2 m/s: conviene una tubería más gruesa.")
        if r.velocidad_elevador_ms > 3.0:
            observaciones.append(f"La velocidad en el elevador ({r.velocidad_elevador_ms:.1f} m/s) es alta: use un tubo "
                          "más grueso.")
        tuberia = lateral.tuberia
        if tuberia.presion_nominal_m and l.presion_max_m > tuberia.presion_nominal_m:
            observaciones.append(f"La presión supera la nominal de la tubería ({tuberia.presion_nominal_m:g} m).")
        marco = r.marco
        filas = [
            ("Longitud del lateral", f"{lateral.longitud_m:.1f} m ({r.numero_aspersores} aspersores)"),
            ("Presión de entrada",
             f"<b>{r.presion_entrada_m:.2f} m</b> ({r.presion_entrada_m / M_POR_BAR:.2f} bar)"),
            ("Caudal del lateral", f"<b>{r.caudal_total_m3h:.2f} m³/h</b> ({r.caudal_total_m3h / 3.6:.2f} L/s)"),
            ("Velocidad en la entrada", f"{l.velocidad_entrada_ms:.2f} m/s"),
            ("Pérdida por fricción", f"{l.perdida_friccion_m:.2f} m"),
            ("Desnivel entrada → final", f"{l.cotas_m[-1]:+.2f} m"),
            ("Presión en boquilla mín. / máx.", f"{r.presion_boquilla_min_m:.2f} / {r.presion_boquilla_max_m:.2f} m"),
            ("Variación de presión", f"{r.variacion_presion:.1%} de la nominal"),
            ("Caudal por aspersor mín. / medio / máx.",
             f"{min(r.caudales_m3h):.3f} / {r.caudal_medio_m3h:.3f} / {max(r.caudales_m3h):.3f} m³/h"),
            ("Variación de caudal", f"{r.variacion_caudal:.1%}"),
            ("Marco", f"{marco.espaciamiento_aspersores_m:g} × {marco.espaciamiento_laterales_m:g} m "
                      f"({self.combo_disposicion.currentText().lower()}), "
                      f"{marco.aspersores_por_ha():.0f} aspersores/ha"),
            ("Separación máxima por el viento",
             f"{marco.separacion_maxima_m(r.aspersor.diametro_mojado_m, r.viento_ms):.1f} m"),
            ("Pluviometría media", f"<b>{r.intensidad_mm_h:.2f} mm/h</b>"),
            ("Caudal por hectárea", f"{r.caudal_medio_m3h * marco.aspersores_por_ha():.1f} m³/h·ha"),
        ]
        if r.riego.lamina_neta_mm > 0:
            filas.append(("Lámina bruta / tiempo de riego",
                          f"{r.riego.lamina_bruta_mm:.1f} mm / <b>{r.tiempo_riego_h:.2f} h</b>"))
        estado = html_estado(not avisos)
        notas = ("<p>" + "<br>".join("ℹ " + o for o in observaciones) + "</p>") if observaciones else ""
        self.texto.setHtml(f"<h3>{titulo} — {estado}</h3>" + html_tabla(filas) + html_avisos(avisos) + notas)
        self._graficar(r)

    def _graficar(self, r):
        if self.figura is None:
            return
        self.figura.clear()
        ejes = self.figura.add_subplot(111)
        posiciones = r.lateral.posiciones_m
        ejes.plot(posiciones, r.presiones_boquilla_m, color="#1e88e5", marker="o", markersize=3,
                  label="Presión en la boquilla")
        a = r.aspersor
        ejes.axhline(a.presion_nominal_m, color="#1e88e5", linestyle=":", label="Presión nominal")
        if a.presion_min_m is not None and a.presion_max_m is not None:
            ejes.axhspan(a.presion_min_m, a.presion_max_m, color="#1e88e5", alpha=0.06,
                         label="Rango de trabajo del aspersor")
        ejes.set_xlabel("Distancia desde la entrada (m)")
        ejes.set_ylabel("Presión (m.c.a.)")
        ejes.grid(True, alpha=0.3)
        terreno = ejes.twinx()
        terreno.plot(posiciones, r.lateral.cotas_m, color="#6d4c41", linewidth=1, label="Terreno (relativo)")
        terreno.set_ylabel("Cota relativa (m)")
        lineas, lineas_t = ejes.get_legend_handles_labels(), terreno.get_legend_handles_labels()
        ejes.legend(lineas[0] + lineas_t[0], lineas[1] + lineas_t[1], loc="best", fontsize=8)
        pintar_figura(self.figura)
        self.lienzo.draw()
