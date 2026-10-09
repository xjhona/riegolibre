"""Panel de resultados de una subunidad: resumen, gráfico, diámetros y laterales."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (QAbstractItemView, QHeaderView, QLabel,
                                 QSplitter, QTableWidget, QTableWidgetItem,
                                 QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import incumplimientos
from ..nucleo.graficos import (dibujar_perfil_subunidad, puntos_perfil_subunidad,
                               referencia_emisor)
from ..nucleo.memoria import avisos_subunidad
from .comunes import (M_POR_BAR, Figure, FigureCanvasQTAgg, html_avisos,
                      html_estado, html_tabla)


def nombre_rama(resultado, rama):
    if len(resultado.ramas) == 1:
        return "Única"
    return "Hacia el final" if rama.sentido > 0 else "Hacia el inicio"


def _tabla(columnas):
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tabla.horizontalHeader().setStretchLastSection(True)
    return tabla


class PanelResultadosSubunidad(QTabWidget):
    # Se emite con la tubería de la fila al hacer doble clic en la tabla de diámetros.
    tuberia_elegida = pyqtSignal(object)

    def __init__(self, texto_inicial=""):
        super().__init__()
        self.diseno = None
        self.texto = QTextBrowser()
        self.texto.setHtml(texto_inicial)
        resumen = QSplitter(Qt.Orientation.Vertical)
        resumen.addWidget(self.texto)
        self.figura = None
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(6, 3.2), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            resumen.addWidget(self.lienzo)
        resumen.setSizes([330, 330])
        self.addTab(resumen, "Resumen")

        self.tabla_diametros = _tabla([
            "Tubería", "DI (mm)", "Presión entrada (m)", "Velocidad (m/s)",
            "Var. caudal", "EU (%)", "Resultado"])
        self.tabla_diametros.cellDoubleClicked.connect(self._doble_clic_diametro)
        pestana = QWidget()
        capa = QVBoxLayout(pestana)
        capa.addWidget(QLabel("Doble clic en una fila para calcular la subunidad con esa tubería."))
        capa.addWidget(self.tabla_diametros)
        self.addTab(pestana, "Diámetros del portalateral")

        self.tabla_laterales = _tabla([
            "Rama", "Posición (m)", "Laterales", "Presión portalateral (m)", "Caudal (L/h)",
            "Presión mín. emisor (m)", "Presión máx. emisor (m)", "Caudal mín. emisor (L/h)",
            "Fuera de rango"])
        self.addTab(self.tabla_laterales, "Laterales")

    @property
    def resultado(self):
        return self.diseno.resultado if self.diseno else None

    def mostrar(self, diseno, criterios, tuberia_lateral, area_m2, texto_area, avisos=()):
        self.diseno = diseno
        r, tuberia = diseno.resultado, diseno.tuberia
        motivos = incumplimientos(r, criterios, tuberia)
        avisos = avisos_subunidad(diseno, criterios, tuberia_lateral, avisos)
        presiones_laterales = [p for rama in r.ramas for p in rama.presiones_m]

        q = r.caudal_total_lh
        numero_laterales = sum(len(c.laterales) for rama in diseno.subunidad.ramas for c in rama.conexiones)
        modo = "automática" if diseno.automatica else "elegida"
        filas = [
            ("Tubería del portalateral", f"<b>{tuberia.nombre}</b> ({modo})"),
            ("Presión en la entrada (válvula)",
             f"<b>{r.presion_entrada_m:.2f} m</b> ({r.presion_entrada_m / M_POR_BAR:.2f} bar)"),
            ("Caudal de la subunidad",
             f"<b>{q:,.0f} L/h</b> ({q / 3600:.2f} L/s · {q / 1000:.2f} m³/h)"),
            ("Laterales / emisores", f"{numero_laterales} / {r.numero_emisores:,}"),
            ("Área", f"{area_m2 / 10000:.3f} ha ({texto_area})"),
            ("Precipitación horaria", f"{q / area_m2:.2f} mm/h" if area_m2 else "—"),
            ("Velocidad máxima en portalateral", f"{r.velocidad_max_ms:.2f} m/s"),
            ("Pérdida por fricción en portalateral", f"{r.perdida_friccion_max_m:.2f} m"),
            ("Presión en entrada de laterales",
             f"{min(presiones_laterales):.2f} – {max(presiones_laterales):.2f} m"),
            ("Presión en emisores (mín. / máx.)",
             f"{r.presion_min_emisor_m:.2f} / {r.presion_max_emisor_m:.2f} m"),
            ("Caudal de emisores (mín. / medio / máx.)",
             f"{r.caudal_min_lh:.3f} / {r.caudal_medio_lh:.3f} / {r.caudal_max_lh:.3f} L/h"),
            ("Variación de caudal", f"{r.variacion_caudal:.1%}"),
            ("Uniformidad de emisión (EU)", f"{r.uniformidad_emision:.1f} %"),
            ("Emisores fuera de rango", f"{r.emisores_fuera_de_rango}"),
        ]
        self.texto.setHtml(f"<h3>Subunidad — {html_estado(not motivos)}</h3>"
                           + html_tabla(filas) + html_avisos(avisos))
        self._llenar_diametros(diseno)
        self._llenar_laterales(r)
        self._graficar(r, diseno.subunidad.laterales[0].emisor)
        self.setCurrentIndex(0)

    def _llenar_diametros(self, diseno):
        tabla = self.tabla_diametros
        tabla.setRowCount(len(diseno.evaluaciones))
        for fila, e in enumerate(diseno.evaluaciones):
            r = e.resultado
            valores = [e.tuberia.nombre, f"{e.tuberia.diametro_interior_mm:.1f}"]
            if r is None:
                valores += ["—"] * 4
            else:
                valores += [f"{r.presion_entrada_m:.2f}", f"{r.velocidad_max_ms:.2f}",
                            f"{r.variacion_caudal:.1%}", f"{r.uniformidad_emision:.1f}"]
            valores.append("✔ cumple" if e.cumple else "✘ " + "; ".join(e.motivos))
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if e.cumple:
                    item.setForeground(QBrush(QColor("#2e7d32")))
                if e.tuberia is diseno.tuberia:
                    fuente = QFont()
                    fuente.setBold(True)
                    item.setFont(fuente)
                if fila == diseno.elegida:
                    item.setBackground(QBrush(QColor(46, 125, 50, 40)))
                tabla.setItem(fila, columna, item)

    def _doble_clic_diametro(self, fila, _columna):
        if self.diseno is not None:
            self.tuberia_elegida.emit(self.diseno.evaluaciones[fila].tuberia)

    def _llenar_laterales(self, r):
        filas = []
        for rama in r.ramas:
            nombre = nombre_rama(r, rama)
            for i, d in enumerate(rama.distancias_m):
                n = len(rama.laterales[i]) if rama.laterales else ""
                filas.append((rama.sentido * d, [
                    nombre, f"{rama.sentido * d:.1f}", f"{n}", f"{rama.presiones_m[i]:.2f}",
                    f"{rama.caudales_lh[i]:.1f}", f"{rama.h_min_m[i]:.2f}", f"{rama.h_max_m[i]:.2f}",
                    f"{rama.q_min_lh[i]:.3f}", "Sí" if rama.fuera_de_rango[i] else "No"]))
        filas.sort(key=lambda f: f[0])
        tabla = self.tabla_laterales
        tabla.setRowCount(len(filas))
        for fila, (_, valores) in enumerate(filas):
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if 0 < columna < 8:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tabla.setItem(fila, columna, item)

    def _graficar(self, r, emisor):
        if self.figura is None:
            return
        dibujar_perfil_subunidad(self.figura, puntos_perfil_subunidad(r), r.presion_entrada_m,
                                 *referencia_emisor(emisor))
        self.lienzo.draw()
