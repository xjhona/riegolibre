"""Elementos de interfaz compartidos por las ventanas de RiegoLibre."""

from qgis.PyQt.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QRadioButton)

from ..nucleo import CriteriosDiseno

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
except ImportError:  # QGIS sin matplotlib: se muestran solo los resultados en texto
    FigureCanvasQTAgg = None
    Figure = None

M_POR_BAR = 10.197


def spin(minimo, maximo, valor, paso, decimales=2, sufijo=""):
    control = QDoubleSpinBox()
    control.setRange(minimo, maximo)
    control.setDecimals(decimales)
    control.setSingleStep(paso)
    control.setValue(valor)
    if sufijo:
        control.setSuffix(f" {sufijo}")
    return control


def combo():
    """Lista desplegable que no ensancha el panel con nombres largos."""
    control = QComboBox()
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    control.setMinimumContentsLength(18)
    control.currentTextChanged.connect(control.setToolTip)
    return control


def descripcion_emisor(e):
    if e.autocompensado:
        return (f"Autocompensado: {e.caudal_nominal_lh:g} L/h entre {e.presion_compensacion_m:g} "
                f"y {e.presion_max_m:g} m · CV {e.cv:g}")
    return (f"q = {e.k:.4f}·h^{e.exponente:g}  ({e.caudal_nominal_lh:g} L/h a "
            f"{e.presion_nominal_m:g} m) · CV {e.cv:g}")


def html_estado(cumple):
    if cumple:
        return "<span style='color:#2e7d32'><b>✔ Cumple</b></span>"
    return "<span style='color:#c62828'><b>✘ No cumple</b></span>"


def html_tabla(filas):
    html = ["<table cellpadding='3'>"]
    html += [f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in filas]
    html.append("</table>")
    return "".join(html)


def html_avisos(avisos):
    if not avisos:
        return ""
    return "<p style='color:#c62828'>" + "<br>".join("⚠ " + a for a in avisos) + "</p>"


class GrupoLaterales(QGroupBox):
    """Tubería, emisor y espaciamiento de los laterales.

    Las ventanas pueden añadir más filas a `formulario`.
    """

    def __init__(self, tuberias, emisores, titulo="Laterales"):
        super().__init__(titulo)
        self.tuberias, self.emisores = tuberias, emisores
        self.formulario = QFormLayout(self)
        self.combo_tuberia = combo()
        for t in tuberias:
            self.combo_tuberia.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)")
        self.formulario.addRow("Tubería:", self.combo_tuberia)

        self.combo_emisor = combo()
        for e in emisores:
            self.combo_emisor.addItem(e.nombre)
        self.combo_emisor.currentIndexChanged.connect(self._actualizar_emisor)
        self.formulario.addRow("Emisor:", self.combo_emisor)
        self.etiqueta_emisor = QLabel()
        self.etiqueta_emisor.setWordWrap(True)
        self.formulario.addRow("", self.etiqueta_emisor)

        self.spin_espaciamiento = spin(0.05, 10, 0.30, 0.05, sufijo="m")
        self.formulario.addRow("Espaciamiento entre emisores:", self.spin_espaciamiento)
        self.spin_primer = spin(0.0, 10, 0.30, 0.05, sufijo="m")
        self.formulario.addRow("Distancia al primer emisor:", self.spin_primer)
        self._actualizar_emisor()

    def _actualizar_emisor(self):
        self.etiqueta_emisor.setText(descripcion_emisor(self.emisor()))

    def tuberia(self):
        return self.tuberias[self.combo_tuberia.currentIndex()]

    def emisor(self):
        return self.emisores[self.combo_emisor.currentIndex()]


class ComboTuberiaPortalateral(QComboBox):
    """Tuberías de portalateral, con la opción de selección automática en primer lugar."""

    AUTOMATICA = -1

    def __init__(self, tuberias):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(18)
        self.currentTextChanged.connect(self.setToolTip)
        self.tuberias = tuberias
        self.addItem("Automática (menor diámetro que cumple)", self.AUTOMATICA)
        for i, t in enumerate(tuberias):
            self.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)", i)

    def tuberia(self):
        """Tubería elegida, o None si la selección es automática."""
        indice = self.currentData()
        return None if indice == self.AUTOMATICA else self.tuberias[indice]

    def elegir(self, tuberia):
        self.setCurrentIndex(self.findData(self.tuberias.index(tuberia)))


class ComboDiametros(QComboBox):
    """Número máximo de diámetros del portalateral (más de uno: telescópico)."""

    def __init__(self):
        super().__init__()
        self.addItem("Uno (uniforme)", 1)
        self.addItem("Hasta dos (telescópico)", 2)
        self.addItem("Hasta tres (telescópico)", 3)
        self.setToolTip("Portalateral telescópico: la tubería de la entrada es la que cumpliría sola; "
                        "hacia el final, donde el caudal es menor, se reduce el diámetro mientras se "
                        "sigan cumpliendo los criterios.")

    def maximo(self):
        return self.currentData()


class GrupoCriterios(QGroupBox):
    """Modo de cálculo, fórmula de pérdidas y criterios de diseño de la subunidad."""

    def __init__(self, titulo="Criterios de diseño"):
        super().__init__(titulo)
        formulario = QFormLayout(self)
        self.radio_requerida = QRadioButton("Calcular la presión de entrada necesaria")
        self.radio_conocida = QRadioButton("Presión de entrada conocida:")
        self.radio_requerida.setChecked(True)
        self.radio_requerida.toggled.connect(self._actualizar_modo)
        formulario.addRow(self.radio_requerida)
        fila = QHBoxLayout()
        self.spin_presion = spin(0.5, 150, 15, 0.5, sufijo="m")
        fila.addWidget(self.radio_conocida)
        fila.addWidget(self.spin_presion)
        formulario.addRow(fila)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Darcy-Weisbach", "darcy")
        self.combo_metodo.addItem("Hazen-Williams", "hazen")
        formulario.addRow("Fórmula de pérdidas:", self.combo_metodo)
        self.spin_variacion = spin(1, 50, 10, 1, decimales=1, sufijo="%")
        self.spin_variacion.setToolTip("Variación de caudal entre todos los emisores de la subunidad.")
        formulario.addRow("Variación de caudal admisible:", self.spin_variacion)
        self.spin_velocidad = spin(0.3, 5, 1.5, 0.1, sufijo="m/s")
        formulario.addRow("Velocidad máxima en portalateral:", self.spin_velocidad)
        self.spin_presion_max = spin(0, 150, 0, 1, decimales=1, sufijo="m")
        self.spin_presion_max.setSpecialValueText("sin límite")
        formulario.addRow("Presión de entrada máxima:", self.spin_presion_max)
        self._actualizar_modo()

    def _actualizar_modo(self):
        self.spin_presion.setEnabled(self.radio_conocida.isChecked())

    def metodo(self):
        return self.combo_metodo.currentData()

    def presion_conocida(self):
        return self.spin_presion.value() if self.radio_conocida.isChecked() else None

    def criterios(self):
        return CriteriosDiseno(
            variacion_caudal_max=self.spin_variacion.value() / 100,
            velocidad_max_ms=self.spin_velocidad.value(),
            presion_entrada_max_m=self.spin_presion_max.value() or None,
        )
