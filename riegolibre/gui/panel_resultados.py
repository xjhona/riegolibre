"""Panel de resultados de una subunidad: resumen, gráfico, diámetros y laterales."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (QAbstractItemView, QHeaderView, QLabel,
                                 QSplitter, QTableWidget, QTableWidgetItem,
                                 QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import incumplimientos
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
        avisos = [m[0].upper() + m[1:] + "." for m in motivos] + list(diseno.avisos) + list(avisos)
        presiones_laterales = [p for rama in r.ramas for p in rama.presiones_m]
        if tuberia_lateral.presion_nominal_m and max(presiones_laterales) > tuberia_lateral.presion_nominal_m:
            avisos.append(f"La presión en la entrada de algunos laterales ({max(presiones_laterales):.1f} m) "
                          f"supera la nominal de la tubería lateral ({tuberia_lateral.presion_nominal_m:g} m).")

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
        puntos = []
        for rama in r.ramas:
            for i, d in enumerate(rama.distancias_m):
                puntos.append((rama.sentido * d, rama.presiones_m[i], rama.h_min_m[i],
                               rama.h_max_m[i], rama.cotas_m[i]))
        puntos.append((0.0, r.presion_entrada_m, None, None, 0.0))
        puntos.sort(key=lambda p: p[0])
        x = [p[0] for p in puntos]
        con_emisores = [p for p in puntos if p[2] is not None]

        self.figura.clear()
        ejes = self.figura.add_subplot(111)
        ejes.plot(x, [p[1] for p in puntos], color="#1e88e5", label="Presión en el portalateral")
        ejes.fill_between([p[0] for p in con_emisores], [p[2] for p in con_emisores],
                          [p[3] for p in con_emisores], color="#43a047", alpha=0.25,
                          label="Presión en emisores (mín.–máx.)")
        ejes.plot([0], [r.presion_entrada_m], "o", color="#c62828", label="Entrada (válvula)")
        if emisor.autocompensado:
            ejes.axhline(emisor.presion_compensacion_m, color="#43a047", linestyle=":",
                         label="Inicio de compensación")
        else:
            ejes.axhline(emisor.presion_nominal_m, color="#43a047", linestyle=":", label="Presión nominal")
        ejes.set_xlabel("Posición a lo largo del portalateral, desde la entrada (m)")
        ejes.set_ylabel("Presión (m.c.a.)")
        ejes.grid(True, alpha=0.3)

        terreno = ejes.twinx()
        terreno.plot(x, [p[4] for p in puntos], color="#6d4c41", linewidth=1, label="Terreno (relativo)")
        terreno.set_ylabel("Cota relativa (m)")
        lineas = ejes.get_legend_handles_labels()
        lineas_t = terreno.get_legend_handles_labels()
        ejes.legend(lineas[0] + lineas_t[0], lineas[1] + lineas_t[1], loc="best", fontsize=8)
        self.lienzo.draw()
