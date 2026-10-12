"""Diámetros de los portalaterales por velocidad, para todos los lotes diseñados (o los seleccionados).

Con el portalateral y la válvula de cada lote ya ubicados (herramienta «Bloque de goteo»), se vuelve a
calcular cada bloque con sus parámetros guardados, pero con los diámetros del portalateral elegidos por
velocidad: cada tramo entre laterales lleva la tubería más pequeña de la serie que no pasa la velocidad
máxima, agrupando los tramos en pocos diámetros.
"""

from qgis.core import Qgis, QgsProject
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                                 QGroupBox, QMessageBox, QPushButton, QRadioButton, QSpinBox, QSplitter,
                                 QTextBrowser, QVBoxLayout, QWidget)

from ..integracion.bloque_mapa import (DIMENSIONADO_VELOCIDAD, RESULTADO, metros_por_tuberia,
                                       quitar_vista_previa, recalcular_lote, resumen_resultado)
from ..integracion.lotes import CAMPO_NOMBRE, capas_de_lotes, guardar_parametros, parametros_guardados
from ..nucleo import PresionInsuficiente, cargar_catalogo_emisores, cargar_catalogo_tuberias
from ..nucleo.diametros_velocidad import serie_por_defecto, series_de_tuberias
from ..nucleo.memoria import descripcion_telescopico
from ..nucleo.subunidad import incumplimientos
from ..nucleo.tuberias import clave_economica
from .comunes import html_avisos, html_estado, html_tabla, spin


class DialogoDiametros(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Diámetros de portalaterales por velocidad")
        self.resize(1100, 720)
        self.tuberias_lateral = cargar_catalogo_tuberias(uso="lateral")
        self.emisores = cargar_catalogo_emisores()
        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica)

        lotes = QGroupBox("Lotes")
        formulario = QFormLayout(lotes)
        self.combo_capa = QComboBox()
        formulario.addRow("Capa de lotes:", self.combo_capa)
        self.radio_todos = QRadioButton("Todos los lotes con bloque diseñado")
        self.radio_seleccion = QRadioButton("Solo los lotes seleccionados")
        self.radio_todos.setChecked(True)
        formulario.addRow(self.radio_todos)
        formulario.addRow(self.radio_seleccion)

        criterio = QGroupBox("Dimensionado")
        formulario_c = QFormLayout(criterio)
        self.combo_serie = QComboBox()
        series = series_de_tuberias(self.tuberias_portalateral)
        for serie in series:
            self.combo_serie.addItem(serie.nombre, serie.clave)
        if series:
            self.combo_serie.setCurrentIndex(self.combo_serie.findData(serie_por_defecto(series).clave))
        formulario_c.addRow("Serie de tuberías:", self.combo_serie)
        self.spin_velocidad = spin(0.3, 5, 1.5, 0.1, sufijo="m/s")
        self.spin_velocidad.setToolTip("Velocidad máxima del agua en cualquier tramo del portalateral.")
        formulario_c.addRow("Velocidad máxima:", self.spin_velocidad)
        self.spin_diametros = QSpinBox()
        self.spin_diametros.setRange(1, 6)
        self.spin_diametros.setValue(3)
        formulario_c.addRow("Diámetros por rama, máximo:", self.spin_diametros)
        self.spin_tramo = spin(0, 100, 6, 1, decimales=1, sufijo="m")
        self.spin_tramo.setToolTip("Largo mínimo de cada diámetro (por ejemplo, el de un tubo).")
        formulario_c.addRow("Largo mínimo de cada diámetro:", self.spin_tramo)
        self.check_ajustar = QCheckBox("Bajar la velocidad si no se cumple la variación de caudal")
        self.check_ajustar.setChecked(True)
        formulario_c.addRow(self.check_ajustar)

        terreno = QGroupBox("Terreno")
        formulario_t = QFormLayout(terreno)
        self.combo_dem = QgsMapLayerComboBox()
        self.combo_dem.setFilters(Qgis.LayerFilter.RasterLayer)
        self.combo_dem.setAllowEmptyLayer(True)
        self.combo_dem.setToolTip("Se usa en los lotes que no tienen un DEM guardado.")
        formulario_t.addRow("DEM:", self.combo_dem)

        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.addWidget(lotes)
        capa_izq.addWidget(criterio)
        capa_izq.addWidget(terreno)
        capa_izq.addStretch()
        izquierda.setMaximumWidth(460)

        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<h3>Diámetros de portalaterales por velocidad</h3>"
            "<p>Primero ubique el portalateral y la válvula de cada lote con la herramienta <b>Bloque de "
            "goteo</b>. Aquí se vuelve a calcular cada lote con sus parámetros, pero con los diámetros del "
            "portalateral elegidos por velocidad:</p><ul>"
            "<li>cada tramo entre laterales lleva la tubería más pequeña de la serie que no pasa la velocidad "
            "máxima con el caudal que circula por él;</li>"
            "<li>los tramos se agrupan en pocos diámetros (con un largo mínimo cada uno), con el menor costo;</li>"
            "<li>con la válvula al centro, cada rama lleva sus propios diámetros;</li>"
            "<li>si se pide, cuando la subunidad no cumple la variación de caudal se baja la velocidad de diseño "
            "de a 0.1 m/s.</li></ul>"
            "<p>La elección queda guardada en cada lote (pestaña Bloque, «Diámetros: por velocidad»).</p>")

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(izquierda)
        divisor.addWidget(self.texto)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_calcular = QPushButton("Calcular diámetros")
        self.boton_calcular.setDefault(True)
        botones.addButton(self.boton_calcular, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_calcular.clicked.connect(self.calcular)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)

    def showEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        self._llenar_capas()
        if self.combo_dem.currentLayer() is None:
            for capa in QgsProject.instance().mapLayers().values():
                nombre = capa.name().lower()
                if capa.type() == Qgis.LayerType.Raster and "dem" in nombre and "3d" not in nombre:
                    self.combo_dem.setLayer(capa)
                    break
        super().showEvent(evento)

    def _llenar_capas(self):
        actual = self.combo_capa.currentData()
        self.combo_capa.clear()
        for capa in capas_de_lotes():
            self.combo_capa.addItem(capa.name(), capa.id())
        indice = self.combo_capa.findData(actual)
        if indice >= 0:
            self.combo_capa.setCurrentIndex(indice)

    def opciones(self):
        """Valores que reemplazan a los guardados en cada lote."""
        return {"dimensionado": DIMENSIONADO_VELOCIDAD, "serie": self.combo_serie.currentData(),
                "velocidad_max_ms": self.spin_velocidad.value(), "diametros_velocidad": self.spin_diametros.value(),
                "tramo_min_m": self.spin_tramo.value(), "ajustar_variacion": self.check_ajustar.isChecked()}

    def calcular(self):
        capa = QgsProject.instance().mapLayer(self.combo_capa.currentData() or "")
        if capa is None:
            QMessageBox.information(self, "RiegoLibre", "No hay una capa de lotes en el proyecto.")
            return
        entidades = capa.selectedFeatures() if self.radio_seleccion.isChecked() else list(capa.getFeatures())
        if not entidades:
            QMessageBox.information(self, "RiegoLibre", "No hay lotes que calcular (¿seleccionó alguno?).")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            html = self.calcular_lotes(capa, entidades)
        finally:
            QApplication.restoreOverrideCursor()
        self.texto.setHtml(html)
        if self.iface is not None:
            self.iface.mapCanvas().refresh()

    def calcular_lotes(self, capa, entidades):
        """Recalcula los lotes y devuelve el informe en HTML."""
        quitar_vista_previa()
        opciones = self.opciones()
        filas, fallos, sin_bloque, metros = [], [], [], {}
        entidades = sorted(entidades, key=lambda e: str(e[CAMPO_NOMBRE]))
        for i, entidad in enumerate(entidades, 1):
            nombre = str(entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}")
            guardados = parametros_guardados(entidad)
            if not guardados:
                sin_bloque.append(nombre)
                continue
            self.texto.setHtml(f"<p>Calculando el lote {nombre} ({i} de {len(entidades)})…</p>")
            QApplication.processEvents()
            valores = dict(guardados, **opciones)
            try:
                r, config = recalcular_lote(capa, entidad, valores, self.tuberias_lateral, self.emisores,
                                            self.tuberias_portalateral, self.combo_dem.currentLayer())
            except (ValueError, PresionInsuficiente) as e:
                fallos.append(f"{nombre}: {e}")
                continue
            valores[RESULTADO] = resumen_resultado(r, config, valores)
            guardar_parametros(capa, entidad.id(), valores)
            for tubo, largo in metros_por_tuberia(r.diseno).items():
                metros[tubo] = metros.get(tubo, 0.0) + largo
            res = r.diseno.resultado
            motivos = incumplimientos(res, config.criterios, r.diseno.tuberia)
            filas.append((nombre, res, r.diseno, motivos))
        return self._informe(filas, fallos, sin_bloque, metros, opciones)

    def _informe(self, filas, fallos, sin_bloque, metros, opciones):
        tabla = ["<table cellpadding='4' border='0'><tr><th align='left'>Lote</th><th>Caudal (m³/h)</th>"
                 "<th align='left'>Portalateral (desde la válvula)</th><th>Velocidad máx. (m/s)</th>"
                 "<th>Variación</th><th>Presión válvula (m)</th><th align='left'>Resultado</th></tr>"]
        for nombre, res, diseno, motivos in filas:
            tubos = descripcion_telescopico(diseno) if diseno.telescopico else diseno.tuberia.nombre
            tabla.append(
                f"<tr><td>{nombre}</td><td align='right'>{res.caudal_total_lh / 1000:.2f}</td><td>{tubos}</td>"
                f"<td align='right'>{res.velocidad_max_ms:.2f}</td><td align='right'>{res.variacion_caudal:.1%}</td>"
                f"<td align='right'>{res.presion_entrada_m:.1f}</td><td>{html_estado(not motivos)}"
                f"{'' if not motivos else ' ' + '; '.join(motivos)}"
                f"{'' if not diseno.avisos else ' · ' + ' '.join(diseno.avisos)}</td></tr>")
        tabla.append("</table>")
        cumplen = sum(1 for *_, m in filas if not m)
        resumen = html_tabla([
            ("Lotes calculados", f"{len(filas)} · cumplen {cumplen}"),
            ("Criterio", f"velocidad ≤ {opciones['velocidad_max_ms']:g} m/s · hasta {opciones['diametros_velocidad']} "
                         f"diámetros por rama · {opciones['tramo_min_m']:g} m como mínimo cada uno"),
        ])
        orden = sorted(metros.items(), key=lambda kv: next(
            (clave_economica(t) for t in self.tuberias_portalateral if t.nombre == kv[0]), (0,)))
        resumen_metros = html_tabla([(nombre, f"{largo:,.1f} m") for nombre, largo in orden])
        avisos = list(fallos)
        if sin_bloque:
            avisos.append(f"{len(sin_bloque)} lotes no tienen bloque diseñado y se saltaron: "
                          + ", ".join(sin_bloque[:10]) + ("…" if len(sin_bloque) > 10 else "")
                          + ". Diséñelos primero con la herramienta «Bloque de goteo».")
        return ("<h3>Diámetros por velocidad</h3>" + resumen + "<h3>Metros de portalateral por tubería</h3>"
                + resumen_metros + "<h3>Lotes</h3>" + "".join(tabla) + html_avisos(avisos))
