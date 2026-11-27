# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana «Red principal y bomba» del programa: parámetros, cálculo y resultados por tramo, turno y válvula.

Los criterios y valores iniciales son los de la ventana del complemento; el cálculo es el del núcleo
(`riegolibre.nucleo.red`), a través de `ProyectoRiego.calcular_red`.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from riegolibre.nucleo.memoria import avisos_red, resumen_red
from riegolibre.nucleo.red import bomba_critica

from .estilo import ROJO, html_avisos, html_estado

# clave: (texto, mínimo, máximo, paso, decimales, sufijo, factor de la caja al valor guardado)
CAMPOS = [
    ("velocidad_max_ms", "Velocidad máxima:", 0.3, 5.0, 0.1, 2, " m/s", 1.0),
    ("presion_min_m", "Presión mínima en la red:", 0.0, 50.0, 0.5, 1, " m", 1.0),
    ("factor_perdidas_menores", "Pérdidas menores:", 0.0, 100.0, 1.0, 0, " %", 0.01),
    ("perdida_valvula_m", "Pérdida en cada válvula:", 0.0, 30.0, 0.5, 2, " m", 1.0),
    ("perdidas_cabezal_m", "Pérdidas en el cabezal:", 0.0, 50.0, 0.5, 2, " m", 1.0),
    ("altura_succion_m", "Altura de succión:", -20.0, 100.0, 0.5, 2, " m", 1.0),
    ("eficiencia_bomba", "Eficiencia de la bomba:", 10.0, 100.0, 1.0, 0, " %", 0.01),
    ("largo_max_conector_m", "Largo máx. del conector:", 1.0, 2000.0, 5.0, 0, " m", 1.0),
    ("tolerancia_m", "Tolerancia de los nodos:", 0.01, 10.0, 0.1, 2, " m", 1.0),
]
AYUDAS = {
    "perdida_valvula_m": "Pérdida fija en la válvula de cada subunidad y sus accesorios.",
    "perdidas_cabezal_m": "Filtros, fertirriego, medidor y válvulas del cabezal.",
    "altura_succion_m": "Desnivel desde el nivel del agua hasta la bomba más las pérdidas en la succión.",
    "largo_max_conector_m": "Tramo más largo con que se une cada válvula a la tubería matriz.",
}


def _celda(valor, decimales=None, color=None):
    if isinstance(valor, float) and decimales is not None:
        texto = f"{valor:.{decimales}f}"
    else:
        texto = "" if valor is None else str(valor)
    item = QTableWidgetItem(texto)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if isinstance(valor, (int, float)):
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        item.setForeground(QColor(color))
    return item


def _tabla(encabezados):
    tabla = QTableWidget(0, len(encabezados))
    tabla.setHorizontalHeaderLabels(encabezados)
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tabla.horizontalHeader().setStretchLastSection(True)
    tabla.setAlternatingRowColors(True)
    return tabla


def _llenar(tabla, filas):
    tabla.setRowCount(len(filas))
    for i, fila in enumerate(filas):
        for j, valor in enumerate(fila):
            tabla.setItem(i, j, valor if isinstance(valor, QTableWidgetItem) else _celda(valor))


class DialogoRed(QDialog):
    """Emite `calculada` cuando la red cambia (para redibujar el mapa)."""

    calculada = Signal()

    def __init__(self, proyecto, parent=None):
        super().__init__(parent)
        self.proyecto = proyecto
        self.setWindowTitle("Red principal y bomba")
        self.resize(1050, 640)

        self.cajas = {}
        formulario = QFormLayout()
        for clave, texto, minimo, maximo, paso, decimales, sufijo, factor in CAMPOS:
            caja = QDoubleSpinBox()
            caja.setRange(minimo, maximo)
            caja.setSingleStep(paso)
            caja.setDecimals(decimales)
            caja.setSuffix(sufijo)
            caja.setValue(proyecto.parametros_red[clave] / factor)
            if clave in AYUDAS:
                caja.setToolTip(AYUDAS[clave])
            formulario.addRow(texto, caja)
            self.cajas[clave] = (caja, factor)
        grupo = QGroupBox("Criterios")
        grupo.setLayout(formulario)
        self.boton_calcular = QPushButton("Calcular")
        self.boton_calcular.setDefault(True)
        self.boton_calcular.clicked.connect(self.calcular)
        izquierda = QVBoxLayout()
        izquierda.addWidget(grupo)
        izquierda.addWidget(self.boton_calcular)
        izquierda.addStretch(1)
        panel = QWidget()
        panel.setLayout(izquierda)
        panel.setMaximumWidth(380)

        self.texto = QTextBrowser()
        self.tabla_tramos = _tabla(["Tramo", "Tubería", "Longitud (m)", "Caudal (m³/h)", "Velocidad (m/s)",
                                    "J (m/100 m)", "P mín (m)", "P máx (m)", "Observaciones"])
        self.tabla_turnos = _tabla(["Turno", "Válvulas", "Caudal (L/s)", "P entrada red (m)", "CDT (m)",
                                    "Potencia (kW)", "Crítico"])
        self.tabla_valvulas = _tabla(["Válvula", "Turno", "Caudal (m³/h)", "P requerida (m)", "Pérdida válvula (m)",
                                      "P disponible (m)", "Exceso (m)"])
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self.texto, "Resumen")
        self.pestanas.addTab(self.tabla_tramos, "Tramos")
        self.pestanas.addTab(self.tabla_turnos, "Turnos")
        self.pestanas.addTab(self.tabla_valvulas, "Válvulas")

        cuerpo = QHBoxLayout()
        cuerpo.addWidget(panel)
        cuerpo.addWidget(self.pestanas, 1)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        principal = QVBoxLayout(self)
        principal.addLayout(cuerpo, 1)
        principal.addWidget(botones)
        self.mostrar()

    def parametros(self) -> dict:
        return {clave: caja.value() * factor for clave, (caja, factor) in self.cajas.items()}

    def calcular(self):
        try:
            self.proyecto.calcular_red(self.parametros())
        except ValueError as error:
            self.mostrar()
            self.calculada.emit()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        self.mostrar()
        self.calculada.emit()

    # ------------------------------------------------------------ resultados

    def mostrar(self):
        red = self.proyecto.red
        for tabla in (self.tabla_tramos, self.tabla_turnos, self.tabla_valvulas):
            tabla.setRowCount(0)
        if red is None:
            texto = ("<h3>Red principal y bomba</h3><p>Revise los criterios y pulse <b>Calcular</b>. Las válvulas "
                     "se unen solas a la tubería matriz dibujada (como «Valve Connector» de IRRICAD) y se elige el "
                     "diámetro de cada tramo.</p>")
            if self.proyecto.error_red:
                texto += f"<p style='color:{ROJO}'>⚠ {self.proyecto.error_red}</p>"
            self.texto.setHtml(texto)
            return
        r = red.resultado
        sin_dem = not self.proyecto.terreno.tiene_cotas
        datos = resumen_red(red.red, r, red.bombas, red.datos_bomba, sin_dem)
        critica = bomba_critica(red.bombas)
        longitud = sum(t.longitud_m for t in red.red.tramos)
        metros = {}
        for t in red.red.tramos:
            nombre = r.asignacion[t.id].nombre
            metros[nombre] = metros.get(nombre, 0.0) + t.longitud_m
        orden = sorted(metros, key=lambda n: next(t.diametro_interior_mm for t in r.asignacion.values() if t.nombre == n))
        filas_metros = "".join(f"<tr><td>{n}</td><td align='right'>{metros[n]:.1f} m</td></tr>" for n in orden)
        cumple = not r.motivos
        self.texto.setHtml(
            f"<h3>Red principal y bomba</h3><p>{html_estado(cumple)}</p>"
            "<table cellpadding='3'>"
            f"<tr><td>Turno crítico</td><td align='right'><b>{critica.turno}</b></td></tr>"
            f"<tr><td>Caudal de la bomba</td><td align='right'><b>{critica.caudal_ls:.2f} L/s</b> "
            f"({critica.caudal_m3h:.2f} m³/h)</td></tr>"
            f"<tr><td>Carga dinámica total (CDT)</td><td align='right'><b>{critica.carga_dinamica_total_m:.2f} m</b>"
            "</td></tr>"
            f"<tr><td>Potencia</td><td align='right'><b>{critica.potencia_kw:.2f} kW</b> "
            f"({critica.potencia_hp:.2f} HP)</td></tr>"
            f"<tr><td>Pérdidas en el cabezal</td><td align='right'>{critica.perdida_cabezal_m:.2f} m</td></tr>"
            f"<tr><td>Longitud de la red</td><td align='right'>{longitud:.1f} m en {len(red.red.tramos)} tramos "
            f"({len(red.conexion.conectores)} conectores de válvula)</td></tr></table>"
            f"<h4>Tuberías de la red principal</h4><table cellpadding='3'>{filas_metros}</table>"
            + html_avisos(avisos_red(r, red.bombas, sin_dem, red.datos_bomba)))
        _llenar(self.tabla_tramos, [
            [t["id"], t["tuberia"], _celda(t["longitud_m"], 1), _celda(t["caudal_lh"] / 1000, 2),
             _celda(t["velocidad_ms"], 2), _celda(t["j_m100"], 2), _celda(t["presion_min_m"], 2),
             _celda(t["presion_max_m"], 2), _celda(t["observaciones"], color=ROJO if t["observaciones"] else None)]
            for t in datos["tramos"]])
        _llenar(self.tabla_turnos, [
            [t["turno"], ", ".join(t["valvulas"]), _celda(t["caudal_lh"] / 3600, 2),
             _celda(t["presion_entrada_red_m"], 2), _celda(t["cdt_m"], 2), _celda(t["potencia_kw"], 2), t["critico"]]
            for t in datos["turnos"]])
        _llenar(self.tabla_valvulas, [
            [v["id"], v["turno"], _celda(v["caudal_lh"] / 1000, 2), _celda(v["presion_requerida_m"], 2),
             _celda(v["perdida_m"], 2), _celda(v["presion_disponible_m"], 2),
             _celda(v["exceso_m"], 2, ROJO if v["exceso_m"] < -0.005 else None)]
            for v in datos["valvulas"]])
