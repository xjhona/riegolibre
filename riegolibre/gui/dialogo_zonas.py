"""Tabla de las zonas (lotes con bloque de goteo), como «Zone Design Configuration» de IRRICAD.

Una fila por lote de la capa de lotes, con lo que se puede cambiar para cada zona (procesar o no,
presión en la válvula, presiones permitidas en los emisores, diámetros del portalateral) y el último
resultado calculado (caudal, presión real en la válvula, presión mínima y máxima de los emisores,
variación de caudal, velocidad). «Calcular las zonas marcadas» vuelve a calcular esas zonas con sus
parámetros guardados más los cambios de la tabla, y lo guarda todo en el lote.
"""

from qgis.core import Qgis, QgsProject
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
                                 QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                                 QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
                                 QWidget)

from ..integracion.bloque_mapa import (DIMENSIONADO_VELOCIDAD, PERMITIDA_MAX, PERMITIDA_MIN, RESULTADO,
                                       quitar_vista_previa, recalcular_lote, resumen_resultado)
from ..integracion.lotes import CAMPO_NOMBRE, capas_de_lotes, guardar_parametros, parametros_guardados
from ..nucleo import PresionInsuficiente, cargar_catalogo_emisores, cargar_catalogo_tuberias
from ..nucleo.subunidad import limites_presion_emisor
from ..nucleo.tuberias import clave_economica
from .comunes import html_avisos, spin_diametros_por_rama

# Columnas
(C_ZONA, C_PROCESAR, C_CAUDAL, C_VALVULA_DESEADA, C_VALVULA_REAL, C_EMISORES, C_PERMITIDA_MIN, C_PERMITIDA_MAX,
 C_DIAMETROS, C_VARIACION, C_VELOCIDAD, C_RESULTADO) = range(12)
ENCABEZADOS = {
    C_ZONA: ("Zona", "Nombre del lote. Doble clic: acercar el mapa al lote."),
    C_PROCESAR: ("Procesar", "Marque las zonas que se calculan con «Calcular las zonas marcadas»."),
    C_CAUDAL: ("Caudal\n(m³/h)", "Caudal de la zona en el último cálculo."),
    C_VALVULA_DESEADA: ("Presión válvula\ndeseada (m)", "Presión aguas abajo de la válvula. Vacía: la que "
                        "requiere la zona (se calcula)."),
    C_VALVULA_REAL: ("Presión válvula\nreal (m)", "Presión en la válvula en el último cálculo."),
    C_EMISORES: ("Presión emisores\nmín – máx (m)", "Presión mínima y máxima de los emisores en el último "
                 "cálculo."),
    C_PERMITIDA_MIN: ("Mínima\npermitida (m)", "Presión mínima permitida en los emisores. Vacía: la de la "
                      "base de datos (inicio del rango de compensación), en gris."),
    C_PERMITIDA_MAX: ("Máxima\npermitida (m)", "Presión máxima permitida en los emisores. Vacía: la de la "
                      "base de datos (fin del rango de compensación), en gris."),
    C_DIAMETROS: ("Diámetros\nportalateral", "Tuberías distintas en el portalateral, como máximo (por rama "
                  "si se dimensiona por velocidad; «Todos» baja hasta el menor diámetro de la serie)."),
    C_VARIACION: ("Variación\nde caudal", "Variación de caudal de los emisores en el último cálculo."),
    C_VELOCIDAD: ("Velocidad\nmáx. (m/s)", "Velocidad máxima en el portalateral en el último cálculo."),
    C_RESULTADO: ("Resultado", "Si la zona cumple los criterios de diseño (pase el ratón para ver por qué no)."),
}
VERDE, ROJO, GRIS = QColor("#2e7d32"), QColor("#c62828"), QColor("#9e9e9e")
CLAVE_ID = Qt.ItemDataRole.UserRole


def _numero(texto):
    texto = texto.strip().replace(",", ".")
    return float(texto) if texto else None


def _texto(valor, decimales=2):
    return "" if valor is None else f"{valor:.{decimales}f}"


class DialogoZonas(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.abrir_lote = None  # función (capa, entidad) para abrir un lote en «Bloque de goteo»
        self.setWindowTitle("RiegoLibre · Zonas (configuración del diseño)")
        self.resize(1300, 720)
        self.tuberias_lateral = cargar_catalogo_tuberias(uso="lateral")
        self.emisores = cargar_catalogo_emisores()
        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica)

        self.combo_capa = QComboBox()
        self.combo_capa.currentIndexChanged.connect(self.llenar)
        self.combo_dem = QgsMapLayerComboBox()
        self.combo_dem.setFilters(Qgis.LayerFilter.RasterLayer)
        self.combo_dem.setAllowEmptyLayer(True)
        self.combo_dem.setToolTip("Se usa en las zonas que no tienen un DEM guardado.")
        arriba = QFormLayout()
        arriba.addRow("Capa de lotes:", self.combo_capa)
        arriba.addRow("DEM:", self.combo_dem)

        self.tabla = QTableWidget(0, len(ENCABEZADOS))
        for columna, (titulo, ayuda) in ENCABEZADOS.items():
            item = QTableWidgetItem(titulo)
            item.setToolTip(ayuda)
            self.tabla.setHorizontalHeaderItem(columna, item)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        encabezado = self.tabla.horizontalHeader()
        encabezado.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setSectionResizeMode(C_RESULTADO, QHeaderView.ResizeMode.Stretch)
        self.tabla.cellDoubleClicked.connect(self._doble_clic)
        self.tabla.itemChanged.connect(self._editada)

        marcas = QHBoxLayout()
        for texto, funcion in (("Marcar todas", lambda: self.marcar(True)),
                               ("Desmarcar todas", lambda: self.marcar(False)),
                               ("Marcar las seleccionadas en el mapa", self.marcar_seleccionadas),
                               ("Abrir en «Bloque de goteo»", self._abrir_en_bloque)):
            boton = QPushButton(texto)
            boton.clicked.connect(funcion)
            marcas.addWidget(boton)
        marcas.addStretch()
        self.etiqueta_total = QLabel()
        marcas.addWidget(self.etiqueta_total)

        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<p>Una fila por lote. Diseñe cada lote con la herramienta <b>Bloque de goteo</b>; aquí se ven "
            "todas las zonas juntas. Edite las celdas blancas (doble clic), marque las zonas en "
            "<b>Procesar</b> y pulse <b>Calcular las zonas marcadas</b>. Doble clic en el nombre acerca el "
            "mapa a la zona.</p>")

        centro = QWidget()
        capa_centro = QVBoxLayout(centro)
        capa_centro.setContentsMargins(0, 0, 0, 0)
        capa_centro.addLayout(arriba)
        capa_centro.addWidget(self.tabla)
        capa_centro.addLayout(marcas)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(centro)
        divisor.addWidget(self.texto)
        divisor.setStretchFactor(0, 4)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_calcular = QPushButton("Calcular las zonas marcadas")
        self.boton_calcular.setDefault(True)
        self.boton_calcular.clicked.connect(self.calcular)
        botones.addButton(self.boton_calcular, QDialogButtonBox.ButtonRole.ActionRole)
        boton_recargar = QPushButton("Recargar")
        boton_recargar.setToolTip("Vuelve a leer los lotes (se pierden los cambios no calculados).")
        boton_recargar.clicked.connect(self.llenar)
        botones.addButton(boton_recargar, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)

    # ---------------------------------------------------------------- lectura

    def showEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        self._llenar_capas()
        if self.combo_dem.currentLayer() is None:
            for capa in QgsProject.instance().mapLayers().values():
                nombre = capa.name().lower()
                if capa.type() == Qgis.LayerType.Raster and "dem" in nombre and "3d" not in nombre:
                    self.combo_dem.setLayer(capa)
                    break
        self.llenar()
        super().showEvent(evento)

    def _llenar_capas(self):
        actual = self.combo_capa.currentData()
        self.combo_capa.blockSignals(True)
        self.combo_capa.clear()
        for capa in capas_de_lotes():
            self.combo_capa.addItem(capa.name(), capa.id())
        indice = self.combo_capa.findData(actual)
        if indice >= 0:
            self.combo_capa.setCurrentIndex(indice)
        self.combo_capa.blockSignals(False)

    def capa(self):
        return QgsProject.instance().mapLayer(self.combo_capa.currentData() or "")

    def _emisor(self, nombre):
        return next((e for e in self.emisores if e.nombre == nombre), None)

    def llenar(self):
        """Una fila por lote, ordenadas por nombre; las de lotes sin diseñar quedan en gris."""
        self.tabla.setRowCount(0)
        capa = self.capa()
        if capa is None:
            self._total()
            return
        entidades = sorted(capa.getFeatures(), key=lambda e: str(e[CAMPO_NOMBRE] or ""))
        self.tabla.setRowCount(len(entidades))
        for fila, entidad in enumerate(entidades):
            self._poner_fila(fila, entidad, parametros_guardados(entidad))
        self._total()

    def _item(self, fila, columna, texto="", editable=False, color=None, ayuda=None):
        item = QTableWidgetItem(texto)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        else:
            item.setBackground(QBrush(QColor(0, 0, 0, 12)))
        item.setFlags(flags)
        if columna != C_ZONA:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if color is not None:
            item.setForeground(QBrush(color))
        if ayuda:
            item.setToolTip(ayuda)
        self.tabla.setItem(fila, columna, item)
        return item

    def _poner_fila(self, fila, entidad, v):
        nombre = str(entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}")
        zona = self._item(fila, C_ZONA, nombre)
        zona.setData(CLAVE_ID, entidad.id())
        procesar = self._item(fila, C_PROCESAR)
        if not v:
            procesar.setFlags(Qt.ItemFlag.NoItemFlags)
            zona.setForeground(QBrush(GRIS))
            self._item(fila, C_RESULTADO, "sin diseñar (use «Bloque de goteo»)", color=GRIS)
            for columna in range(C_CAUDAL, C_RESULTADO):
                self._item(fila, columna)
            return
        procesar.setFlags(procesar.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        procesar.setCheckState(Qt.CheckState.Checked)
        self._item(fila, C_VALVULA_DESEADA, _texto(v.get("presion_conocida_m")), editable=True)
        emisor = self._emisor(v.get("emisor"))
        base_min, base_max = limites_presion_emisor(emisor) if emisor else (None, None)
        for columna, clave, base in ((C_PERMITIDA_MIN, PERMITIDA_MIN, base_min),
                                     (C_PERMITIDA_MAX, PERMITIDA_MAX, base_max)):
            propia = v.get(clave)
            item = self._item(fila, columna, _texto(propia), editable=True)
            if propia is None and base is not None:  # se muestra la de la base de datos
                item.setText(_texto(base))
                item.setForeground(QBrush(GRIS))
                item.setData(CLAVE_ID, ("base", item.text()))
        if v.get("dimensionado") == DIMENSIONADO_VELOCIDAD:  # como el «Number of Submain Sizes» de IRRICAD
            diametros = spin_diametros_por_rama(int(v.get("diametros_velocidad", 0)))
        else:
            diametros = QSpinBox()
            diametros.setRange(1, 6)
            diametros.setValue(int(v.get("diametros_max", 1)))
            diametros.setToolTip("En todo el portalateral (telescópico si es más de 1)")
        self._item(fila, C_DIAMETROS)
        self.tabla.setCellWidget(fila, C_DIAMETROS, diametros)
        self._poner_resultado(fila, v.get(RESULTADO))

    @staticmethod
    def _editada(item):
        """Una presión permitida que venía de la base de datos pasa a ser propia al editarla."""
        base = item.data(CLAVE_ID)
        if item.column() in (C_PERMITIDA_MIN, C_PERMITIDA_MAX) and (isinstance(base, (tuple, list))
                                                                 and item.text() != base[1]):
            item.setData(CLAVE_ID, None)
            item.setForeground(QBrush())

    def _poner_resultado(self, fila, r):
        if not r:
            for columna in (C_CAUDAL, C_VALVULA_REAL, C_EMISORES, C_VARIACION, C_VELOCIDAD):
                self._item(fila, columna)
            self._item(fila, C_RESULTADO, "sin calcular", color=GRIS)
            return
        motivos = r.get("motivos") or []
        self._item(fila, C_CAUDAL, _texto(r.get("caudal_m3h")))
        self._item(fila, C_VALVULA_REAL, _texto(r.get("presion_valvula_m")), color=VERDE)
        self._item(fila, C_EMISORES, f"{_texto(r.get('h_emisor_min_m'))} – {_texto(r.get('h_emisor_max_m'))}",
                   color=QColor("#1565c0"))
        variacion = r.get("variacion_caudal")
        self._item(fila, C_VARIACION, "" if variacion is None else f"{variacion:.1%}")
        self._item(fila, C_VELOCIDAD, _texto(r.get("velocidad_max_ms")))
        texto = "✔ Cumple" if not motivos else "✘ " + "; ".join(motivos)
        ayuda = f"Portalateral: {r.get('portalateral', '')}" + ("" if not motivos else "\n" + "\n".join(motivos))
        item = self._item(fila, C_RESULTADO, texto, color=VERDE if not motivos else ROJO, ayuda=ayuda)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _total(self):
        zonas = cumplen = 0
        caudal = 0.0
        for fila in range(self.tabla.rowCount()):
            resultado = self.tabla.item(fila, C_RESULTADO)
            if resultado is None or not self.tabla.item(fila, C_CAUDAL).text():
                continue
            zonas += 1
            cumplen += resultado.text().startswith("✔")
            caudal += float(self.tabla.item(fila, C_CAUDAL).text())
        self.etiqueta_total.setText(f"{self.tabla.rowCount()} lotes · {zonas} calculados · cumplen {cumplen} · "
                                    f"caudal total {caudal:.2f} m³/h")

    # ---------------------------------------------------------------- marcas

    def _procesar(self, fila):
        item = self.tabla.item(fila, C_PROCESAR)
        return item if item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable else None

    def marcar(self, si):
        for fila in range(self.tabla.rowCount()):
            item = self._procesar(fila)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if si else Qt.CheckState.Unchecked)

    def marcar_seleccionadas(self):
        capa = self.capa()
        if capa is None:
            return
        elegidas = set(capa.selectedFeatureIds())
        if not elegidas:
            QMessageBox.information(self, "RiegoLibre", f"No hay lotes seleccionados en la capa «{capa.name()}».")
            return
        for fila in range(self.tabla.rowCount()):
            item = self._procesar(fila)
            if item is not None:
                dentro = self.tabla.item(fila, C_ZONA).data(CLAVE_ID) in elegidas
                item.setCheckState(Qt.CheckState.Checked if dentro else Qt.CheckState.Unchecked)

    def _entidad(self, fila):
        capa = self.capa()
        if capa is None or fila < 0:
            return None, None
        entidad = capa.getFeature(self.tabla.item(fila, C_ZONA).data(CLAVE_ID))
        return capa, (entidad if entidad.isValid() else None)

    def _doble_clic(self, fila, columna):
        if columna != C_ZONA or self.iface is None:
            return
        capa, entidad = self._entidad(fila)
        if entidad is None:
            return
        from qgis.core import QgsCoordinateTransform
        canvas = self.iface.mapCanvas()
        transformacion = QgsCoordinateTransform(capa.crs(), canvas.mapSettings().destinationCrs(),
                                                QgsProject.instance())
        extension = transformacion.transformBoundingBox(entidad.geometry().boundingBox())
        canvas.setExtent(extension.buffered(max(extension.width(), extension.height()) * 0.3))
        capa.selectByIds([entidad.id()])
        canvas.refresh()

    def _abrir_en_bloque(self):
        capa, entidad = self._entidad(self.tabla.currentRow())
        if entidad is None:
            QMessageBox.information(self, "RiegoLibre", "Elija una fila de la tabla.")
            return
        if self.abrir_lote is not None:
            self.abrir_lote(capa, entidad)

    # ---------------------------------------------------------------- cálculo

    def cambios(self, fila):
        """Valores de la fila que reemplazan a los guardados en el lote (ValueError si hay un número malo)."""
        nombre = self.tabla.item(fila, C_ZONA).text()
        cambios = {}
        for columna, clave in ((C_VALVULA_DESEADA, "presion_conocida_m"), (C_PERMITIDA_MIN, PERMITIDA_MIN),
                               (C_PERMITIDA_MAX, PERMITIDA_MAX)):
            item = self.tabla.item(fila, columna)
            base = item.data(CLAVE_ID)
            if isinstance(base, (tuple, list)) and item.text() == base[1]:
                cambios[clave] = None  # sigue siendo la de la base de datos
                continue
            try:
                valor = _numero(item.text())
            except ValueError:
                raise ValueError(f"{nombre}: «{item.text()}» no es un número "
                                 f"({ENCABEZADOS[columna][0].replace(chr(10), ' ')}).") from None
            if valor is not None and valor <= 0:
                raise ValueError(f"{nombre}: la presión debe ser mayor que cero.")
            cambios[clave] = valor
        if (cambios[PERMITIDA_MIN] is not None and cambios[PERMITIDA_MAX] is not None
                and cambios[PERMITIDA_MIN] >= cambios[PERMITIDA_MAX]):
            raise ValueError(f"{nombre}: la presión mínima permitida debe ser menor que la máxima.")
        return cambios

    def calcular(self):
        capa = self.capa()
        if capa is None:
            QMessageBox.information(self, "RiegoLibre", "No hay una capa de lotes en el proyecto.")
            return
        filas = [f for f in range(self.tabla.rowCount())
                 if self._procesar(f) is not None and self._procesar(f).checkState() == Qt.CheckState.Checked]
        if not filas:
            QMessageBox.information(self, "RiegoLibre", "Marque en «Procesar» las zonas que quiere calcular.")
            return
        try:
            cambios = {f: self.cambios(f) for f in filas}
        except ValueError as e:
            QMessageBox.warning(self, "RiegoLibre", str(e))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            avisos = self.calcular_filas(capa, cambios)
        finally:
            QApplication.restoreOverrideCursor()
        self.texto.setHtml(f"<p>Se calcularon {len(filas) - len(avisos)} de {len(filas)} zonas.</p>"
                           + html_avisos(avisos))
        if self.iface is not None:
            self.iface.mapCanvas().refresh()

    def calcular_filas(self, capa, cambios):
        """Calcula las filas {fila: cambios}, guarda en cada lote y actualiza la tabla. Devuelve los fallos."""
        quitar_vista_previa()
        fallos = []
        for i, (fila, cambio) in enumerate(cambios.items(), 1):
            _, entidad = self._entidad(fila)
            nombre = self.tabla.item(fila, C_ZONA).text()
            guardados = parametros_guardados(entidad) if entidad is not None else None
            if not guardados:
                fallos.append(f"{nombre}: el lote ya no existe o no tiene bloque diseñado.")
                continue
            self.texto.setHtml(f"<p>Calculando la zona {nombre} ({i} de {len(cambios)})…</p>")
            QApplication.processEvents()
            valores = dict(guardados, **cambio)
            widget = self.tabla.cellWidget(fila, C_DIAMETROS)
            if widget is not None:
                clave = ("diametros_velocidad" if valores.get("dimensionado") == DIMENSIONADO_VELOCIDAD
                         else "diametros_max")
                valores[clave] = widget.value()
            try:
                r, config = recalcular_lote(capa, entidad, valores, self.tuberias_lateral, self.emisores,
                                            self.tuberias_portalateral, self.combo_dem.currentLayer())
            except (ValueError, PresionInsuficiente) as e:
                fallos.append(f"{nombre}: {e}")
                continue
            valores[RESULTADO] = resumen_resultado(r, config, valores)
            guardar_parametros(capa, entidad.id(), valores)
            self._poner_resultado(fila, valores[RESULTADO])
        self._total()
        return fallos
