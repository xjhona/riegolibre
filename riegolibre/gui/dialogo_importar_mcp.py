# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Importar un diseño hecho con el servidor MCP (`mcp_riegolibre`) como un borrador para terminar en QGIS.

Se elige el «…_datos.json» que escribe «exportar_proyecto». Con esos datos se rehacen los bloques de goteo
con las herramientas del complemento (ver `integracion.importar_mcp`).
"""

import os

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                                 QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
                                 QVBoxLayout)

from ..nucleo import PresionInsuficiente
from .comunes import html_avisos, html_estado, html_tabla
from .tema import aplicar_tema

AJUSTE_CARPETA = "riegolibre/importar_mcp/carpeta"


class DialogoImportarMcp(QDialog):
    base_cambiada = pyqtSignal()  # se agregó la cinta del diseño a la base de datos

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        aplicar_tema(self)
        self.iface = iface
        self.datos = None
        self.cinta = None  # `CintaDelDiseno`
        self.resultado = None
        self.setWindowTitle("RiegoLibre · Importar diseño del MCP")
        self.resize(760, 620)

        grupo = QGroupBox("Diseño del servidor MCP")
        formulario = QFormLayout(grupo)
        self.edit_datos = QLineEdit()
        self.edit_datos.setPlaceholderText("«…_datos.json» que escribe «exportar_proyecto»")
        self.edit_datos.editingFinished.connect(self._leer)
        boton = QPushButton("Examinar…")
        boton.clicked.connect(self._elegir_datos)
        fila = QHBoxLayout()
        fila.addWidget(self.edit_datos)
        fila.addWidget(boton)
        formulario.addRow("Datos del diseño:", fila)
        self.edit_matriz = QLineEdit()
        self.edit_matriz.setPlaceholderText("Opcional: GeoJSON de líneas, si el diseño no trae «red.matriz»")
        self.edit_matriz.setToolTip("La tubería matriz trazada aparte. Se dibuja en la capa «Matriz» y las "
                                    "válvulas se unen a ella, como con «Conector de válvulas».")
        boton_matriz = QPushButton("Examinar…")
        boton_matriz.clicked.connect(self._elegir_matriz)
        fila = QHBoxLayout()
        fila.addWidget(self.edit_matriz)
        fila.addWidget(boton_matriz)
        formulario.addRow("Tubería matriz:", fila)
        self.check_cinta = QCheckBox()
        self.check_cinta.setVisible(False)
        self.check_cinta.setToolTip(
            "La cinta viene definida en el diseño y no está en la base de datos de materiales. Sin agregarla, se "
            "usa solo en esta importación: los lotes quedan calculados, pero para volver a calcularlos (ventana "
            "«Bloque de goteo», tabla de zonas) hará falta que esté en la base de datos.")
        formulario.addRow(self.check_cinta)

        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<h3>Importar un diseño del servidor MCP</h3>"
            "<p>El servidor MCP de RiegoLibre diseña un proyecto a partir de instrucciones. Aquí se toma su archivo "
            "<i>…_datos.json</i> y se rehace el diseño con las herramientas del complemento: los lotes (con sus "
            "parámetros del bloque de goteo), los laterales, portalaterales y válvulas, el DEM, la fuente, la "
            "tubería matriz y los turnos.</p><p>El resultado es un borrador como si se hubiera hecho a mano: se "
            "puede revisar cada lote con <b>Bloque de goteo</b>, cambiar los turnos, calcular la red y la bomba y "
            "sacar los materiales y la memoria.</p><p>Conviene importarlo en un proyecto nuevo y guardado: las "
            "capas quedan en el GeoPackage del proyecto.</p>")

        botones = QDialogButtonBox()
        self.boton_importar = QPushButton("Importar")
        self.boton_importar.setDefault(True)
        self.boton_importar.clicked.connect(self.importar)
        botones.addButton(self.boton_importar, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(grupo)
        principal.addWidget(self.texto, 1)
        principal.addWidget(botones)

    # ---------------------------------------------------------------- archivos

    def _carpeta(self):
        return QgsSettings().value(AJUSTE_CARPETA, "") or ""

    def _elegir_datos(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Datos del diseño del MCP", self._carpeta(),
                                              "Datos del diseño (*_datos.json);;JSON (*.json)")
        if ruta:
            QgsSettings().setValue(AJUSTE_CARPETA, os.path.dirname(ruta))
            self.edit_datos.setText(ruta)
            self._leer()

    def _elegir_matriz(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Tubería matriz", self._carpeta(), "GeoJSON (*.geojson *.json)")
        if ruta:
            self.edit_matriz.setText(ruta)

    def _leer(self):
        from ..integracion.importar_mcp import cinta_del_diseno, leer_datos
        ruta = self.edit_datos.text().strip()
        self.datos = self.cinta = None
        self.check_cinta.setVisible(False)
        if not ruta:
            return
        try:
            self.datos = leer_datos(ruta)
            self.cinta = cinta_del_diseno(self.datos)
        except ValueError as error:
            self.datos = None
            self.texto.setHtml(html_avisos([str(error)]))
            return
        d = self.datos
        con_matriz = bool((d.get("red") or {}).get("matriz"))
        self.edit_matriz.setEnabled(not con_matriz)
        if not con_matriz and not self.edit_matriz.text():
            vecino = os.path.join(os.path.dirname(ruta), "matriz_trazada.geojson")
            if os.path.exists(vecino):
                self.edit_matriz.setText(vecino)
        avisos = []
        if self.cinta is not None and not self.cinta.en_base:
            self.check_cinta.setText(f"Agregar la cinta «{self.cinta.cinta.nombre}» a la base de datos de materiales")
            self.check_cinta.setChecked(True)
            self.check_cinta.setVisible(True)
        elif self.cinta is not None and self.cinta.distinta:
            avisos.append(f"La cinta «{self.cinta.cinta.nombre}» ya está en la base de datos con otros datos: se "
                          "usan los de la base de datos.")
        goteo = d.get("goteo") or {}
        terreno = (d.get("terreno") or {}).get("tipo") or "llano"
        filas = [
            ("Proyecto", d.get("nombre", "—")),
            ("Lotes", f"{len(d['lotes'])}"),
            ("Sistema de coordenadas", f"EPSG:{d['epsg']}" if d.get("epsg") else "el del proyecto"),
            ("Lateral", self.cinta.cinta.nombre if self.cinta else f"{goteo.get('tuberia_lateral')} · "
                                                                  f"{goteo.get('emisor')}"),
            ("Terreno", terreno),
            ("Fuente", "sí" if d.get("fuente") else "no"),
            ("Tubería matriz", "en el diseño" if con_matriz else "no viene en el diseño"),
            ("Turnos", str((d.get("red") or {}).get("turnos", 1))),
        ]
        self.texto.setHtml("<h3>Diseño leído</h3>" + html_tabla(filas) + html_avisos(avisos)
                           + "<p>Pulse <b>Importar</b>.</p>")

    # ---------------------------------------------------------------- importar

    def importar(self):
        from ..integracion.importar_mcp import Catalogos, agregar_cinta_a_la_base, importar_diseno, matriz_de_geojson
        if self.datos is None:
            self._leer()
        if self.datos is None:
            QMessageBox.information(self, "RiegoLibre", "Elija el archivo «…_datos.json» del diseño.")
            return
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cinta = self.cinta.cinta if self.cinta else None
            solo_aqui = None
            if self.cinta is not None and not self.cinta.en_base:
                if self.check_cinta.isChecked():
                    agregar_cinta_a_la_base(cinta)
                    self.check_cinta.setVisible(False)
                    self.cinta.en_base = True
                    self.base_cambiada.emit()
                else:
                    solo_aqui = cinta
            matriz = None
            ruta_matriz = self.edit_matriz.text().strip()
            if self.edit_matriz.isEnabled() and ruta_matriz:
                matriz = matriz_de_geojson(ruta_matriz)

            def progreso(i, total, nombre):
                self.texto.setHtml(f"<p>Calculando el lote {nombre} ({i} de {total})…</p>")
                QApplication.processEvents()
            self.resultado = importar_diseno(
                self.datos, Catalogos.activos(solo_aqui), cinta, matriz,
                os.path.dirname(os.path.abspath(self.edit_datos.text().strip())), progreso)
        except (ValueError, OSError, PresionInsuficiente) as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "RiegoLibre", error)
            return
        self.texto.setHtml(self.informe(self.resultado, solo_aqui is not None))
        if self.iface is not None:
            self.iface.mapCanvas().setExtent(self.resultado.capa_lotes.extent())
            self.iface.mapCanvas().refresh()

    @staticmethod
    def informe(r, cinta_solo_aqui=False) -> str:
        from ..integracion.persistencia import aviso_html
        cumplen = sum(1 for l in r.lotes if not l.resultado["motivos"])
        resumen = html_tabla([
            ("Lotes calculados", f"{len(r.lotes)} · cumplen {cumplen}" + (f" · con error {len(r.errores)}"
                                                                          if r.errores else "")),
            ("Caudal total", f"{sum(l.resultado['caudal_m3h'] for l in r.lotes):.2f} m³/h"),
            ("Turnos", str(len({l.turno for l in r.lotes}))),
            ("Tubería matriz", f"{r.tuberias_matriz} líneas · {r.conectores} válvulas unidas" if r.tuberias_matriz
             else "no se dibujó"),
        ])
        tabla = ["<table cellpadding='4' border='0'><tr><th align='left'>Lote</th><th>Turno</th>"
                 "<th>Caudal (m³/h)</th><th>Presión válvula (m)</th><th align='left'>Portalateral</th>"
                 "<th align='left'>Resultado</th></tr>"]
        for l in r.lotes:
            res = l.resultado
            tabla.append(f"<tr><td>{l.nombre}</td><td align='right'>{l.turno}</td>"
                         f"<td align='right'>{res['caudal_m3h']:.2f}</td>"
                         f"<td align='right'>{res['presion_valvula_m']:.2f}</td><td>{res['portalateral']}</td>"
                         f"<td>{html_estado(not res['motivos'])}"
                         f"{'' if not res['motivos'] else ' ' + '; '.join(res['motivos'])}</td></tr>")
        tabla.append("</table>")
        avisos = list(r.avisos)
        if cinta_solo_aqui:
            avisos.append("La cinta del diseño no se agregó a la base de datos: para volver a calcular un lote "
                          "hará falta agregarla.")
        red = r.red
        pasos = ("<h3>Siguientes pasos</h3><ol><li>Revise cada lote con <b>Bloque de goteo</b> o en la tabla de "
                 "<b>Zonas</b>.</li><li>En <b>Red principal y bomba</b> calcule la red con los criterios del diseño: "
                 f"velocidad máxima {red['velocidad_max_ms']:g} m/s, presión mínima {red['presion_min_m']:g} m, "
                 f"pérdidas del cabezal {red['perdidas_cabezal_m']:g} m, altura de succión "
                 f"{red['altura_succion_m']:g} m, eficiencia de la bomba {red['eficiencia_bomba']:.0%}.</li>"
                 "<li>Saque la lista de materiales y la memoria de cálculo.</li></ol>")
        return ("<h3>Diseño importado</h3>" + resumen + "".join(tabla) + html_avisos(r.errores + avisos)
                + pasos + aviso_html(r.ruta_gpkg))
