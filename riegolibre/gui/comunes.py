"""Elementos de interfaz compartidos por las ventanas de RiegoLibre."""

from qgis.PyQt.QtWidgets import QComboBox, QDoubleSpinBox

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
