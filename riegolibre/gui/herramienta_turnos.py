"""Herramienta de mapa «Turnos de riego»: se marcan bloques con el ratón y se les asigna un turno.

Un clic marca un bloque (en rojo) o lo desmarca; arrastrar un rectángulo marca todos los que toca. Con los
bloques marcados se elige el turno y se pulsa «Asignar»: quedan pintados con el color del turno. Luego se
repite con otro turno. Esc limpia la selección e Intro asigna.
"""

from qgis.core import Qgis, QgsGeometry, QgsPointXY, QgsRectangle
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                                 QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..integracion import turnos_mapa
from ..nucleo.turnos import (COLOR_SELECCION, TURNO_MAXIMO, color_de_turno, siguiente_turno, texto_balance)

TOLERANCIA_PIXELES = 8  # distancia a una válvula suelta para marcarla
ARRASTRE_PIXELES = 5  # menos que esto es un clic, no un rectángulo

AYUDA = ("<b>Clic</b> en un bloque lo marca (rojo); otro clic lo desmarca. <b>Arrastre</b> un rectángulo para "
         "marcar varios. Elija el turno y pulse <b>Asignar</b>: los bloques se pintan con el color del turno. "
         "Repita con otro turno. <i>Esc</i> limpia la selección; <i>Intro</i> asigna.")


def _color(texto, alfa=255):
    color = QColor(texto)
    color.setAlpha(alfa)
    return color


class PanelTurnos(QDialog):
    """Ventana flotante con el turno a asignar, lo marcado y el resumen de caudales por turno."""

    cambio = pyqtSignal()  # se asignaron o quitaron turnos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RiegoLibre · Turnos de riego")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(440, 600)
        self.herramienta = None
        self.crs = None
        self.resumen = None  # ResumenTurnos del proyecto, tal como se vio la última vez
        capa = QVBoxLayout(self)
        ayuda = QLabel(AYUDA)
        ayuda.setWordWrap(True)
        capa.addWidget(ayuda)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Turno:"))
        self.spin_turno = QSpinBox()
        self.spin_turno.setRange(1, TURNO_MAXIMO)
        self.spin_turno.valueChanged.connect(self._pintar_muestra)
        fila.addWidget(self.spin_turno)
        self.muestra = QLabel()
        self.muestra.setFixedSize(28, 20)
        fila.addWidget(self.muestra)
        fila.addStretch(1)
        capa.addLayout(fila)

        self.etiqueta_seleccion = QLabel()
        capa.addWidget(self.etiqueta_seleccion)
        self.boton_asignar = QPushButton()
        self.boton_asignar.clicked.connect(self._asignar)
        capa.addWidget(self.boton_asignar)
        fila = QHBoxLayout()
        self.boton_limpiar = QPushButton("Limpiar la selección")
        self.boton_limpiar.clicked.connect(self._limpiar)
        self.boton_quitar = QPushButton("Quitar el turno a lo marcado")
        self.boton_quitar.setToolTip("Despinta los bloques marcados: quedan sin turno asignado.")
        self.boton_quitar.clicked.connect(self._quitar)
        fila.addWidget(self.boton_limpiar)
        fila.addWidget(self.boton_quitar)
        capa.addLayout(fila)

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Turno", "Válvulas", "Caudal (L/s)"])
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setToolTip("Un clic en un turno lo elige para asignar más bloques a él.")
        self.tabla.cellClicked.connect(self._elegir_de_tabla)
        capa.addWidget(self.tabla, 1)
        self.etiqueta_balance = QLabel()
        self.etiqueta_balance.setWordWrap(True)
        capa.addWidget(self.etiqueta_balance)

        fila = QHBoxLayout()
        self.boton_borrar = QPushButton("Borrar todos los turnos…")
        self.boton_borrar.clicked.connect(self._borrar_todos)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.hide)
        fila.addWidget(self.boton_borrar)
        fila.addStretch(1)
        fila.addWidget(boton_cerrar)
        capa.addLayout(fila)
        self._pintar_muestra()
        self.mostrar_seleccion(0, 0, 0.0)

    # ------------------------------------------------------------------ vista

    def _pintar_muestra(self, *_):
        turno = self.spin_turno.value()
        self.muestra.setStyleSheet(f"background:{color_de_turno(turno)}; border:1px solid #444;")
        self.boton_asignar.setText(f"Asignar lo marcado al turno {turno}")

    def _elegir_de_tabla(self, fila, _columna):
        item = self.tabla.item(fila, 0)
        if item is not None:
            self.spin_turno.setValue(int(item.data(Qt.ItemDataRole.UserRole)))

    def mostrar_seleccion(self, bloques, valvulas, caudal_lh):
        if bloques:
            self.etiqueta_seleccion.setText(
                f"<b style='color:{COLOR_SELECCION}'>Marcados:</b> {bloques} bloques · {valvulas} válvulas · "
                f"{caudal_lh / 3600:.2f} L/s")
        else:
            self.etiqueta_seleccion.setText("Ningún bloque marcado.")
        for boton in (self.boton_asignar, self.boton_limpiar, self.boton_quitar):
            boton.setEnabled(bool(bloques))

    def refrescar(self, crs=None):
        """Vuelve a leer el resumen por turno del proyecto."""
        self.crs = crs or self.crs
        if self.crs is None:
            return
        resumen = turnos_mapa.resumen_del_proyecto(self.crs)
        self.tabla.setRowCount(len(resumen.turnos))
        for fila, t in enumerate(resumen.turnos):
            item = QTableWidgetItem(f"Turno {t.turno}")
            item.setData(Qt.ItemDataRole.UserRole, t.turno)
            item.setBackground(_color(color_de_turno(t.turno), 140))
            self.tabla.setItem(fila, 0, item)
            for columna, texto in ((1, str(t.valvulas)), (2, f"{t.caudal_ls:.2f}")):
                celda = QTableWidgetItem(texto)
                celda.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(fila, columna, celda)
        self.etiqueta_balance.setText(texto_balance(resumen))
        self.boton_borrar.setEnabled(bool(resumen.turnos))
        self.resumen = resumen

    def turno_siguiente(self):
        """Deja elegido el turno que sigue al mayor ya usado."""
        self.spin_turno.setValue(siguiente_turno(t.turno for t in self.resumen.turnos) if self.resumen else 1)

    # ------------------------------------------------------------------ acciones

    def _asignar(self):
        if self.herramienta is not None:
            self.herramienta.asignar(self.spin_turno.value())

    def _limpiar(self):
        if self.herramienta is not None:
            self.herramienta.limpiar()

    def _quitar(self):
        if self.herramienta is not None:
            self.herramienta.quitar()

    def _borrar_todos(self):
        respuesta = QMessageBox.question(self, "RiegoLibre", "¿Quitar el turno a todas las válvulas del proyecto?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        turnos_mapa.quitar_todos()
        self.refrescar()
        self.cambio.emit()

    def avisar(self, texto):
        QMessageBox.warning(self, "RiegoLibre", texto)


class HerramientaTurnos(QgsMapTool):
    """Marca bloques con clic o rectángulo; el panel asigna el turno a lo marcado."""

    def __init__(self, canvas, panel):
        super().__init__(canvas)
        self.panel = panel
        panel.herramienta = self
        self.seleccion = {}  # clave -> BloqueTurno
        self.bandas = {}  # clave -> QgsRubberBand
        self.inicio = None  # píxel donde empezó el arrastre
        self.banda_rect = None
        self.arrastrando = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------ ratón

    def _crs(self):
        return self.canvas().mapSettings().destinationCrs()

    def _tolerancia(self):
        return TOLERANCIA_PIXELES * self.canvas().mapUnitsPerPixel()

    def canvasPressEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        if evento.button() == Qt.MouseButton.LeftButton:
            self.inicio = evento.pos()
            self.arrastrando = False

    def canvasMoveEvent(self, evento):  # noqa: N802
        if self.inicio is None:
            return
        if not self.arrastrando:
            if (evento.pos() - self.inicio).manhattanLength() < ARRASTRE_PIXELES:
                return
            self.arrastrando = True
            self.banda_rect = QgsRubberBand(self.canvas(), Qgis.GeometryType.Polygon)
            self.banda_rect.setColor(_color(COLOR_SELECCION, 220))
            self.banda_rect.setFillColor(_color(COLOR_SELECCION, 40))
            self.banda_rect.setWidth(2)
        a = self.toMapCoordinates(self.inicio)
        b = self.toMapCoordinates(evento.pos())
        self.banda_rect.setToGeometry(QgsGeometry.fromRect(QgsRectangle(a, b)), None)

    def canvasReleaseEvent(self, evento):  # noqa: N802
        if evento.button() != Qt.MouseButton.LeftButton or self.inicio is None:
            return
        try:
            if self.arrastrando:
                rect = QgsRectangle(self.toMapCoordinates(self.inicio), self.toMapCoordinates(evento.pos()))
                self._marcar_varios(turnos_mapa.bloques_en(rect, self._crs(), self._tolerancia()))
            else:
                self._clic(evento.mapPoint())
        finally:
            self.inicio = None
            self.arrastrando = False
            self._quitar_banda_rect()

    def _clic(self, punto: QgsPointXY):
        bloque = turnos_mapa.bloque_en(punto, self._crs(), self._tolerancia())
        if bloque is None:
            self.panel.avisar(
                "No hay un bloque ni una válvula en ese punto. Los bloques salen de las capas de lotes y de "
                "«Bloques»; cada uno necesita su válvula calculada (capa «Válvula · …»).")
            return
        if bloque.clave in self.seleccion:
            self._desmarcar(bloque.clave)
        else:
            self._marcar(bloque)
        self._actualizar_panel()

    def _marcar_varios(self, bloques):
        for bloque in bloques:
            if bloque.clave not in self.seleccion:
                self._marcar(bloque)
        self._actualizar_panel()

    # ------------------------------------------------------------------ selección

    def _marcar(self, bloque):
        banda = QgsRubberBand(self.canvas(), Qgis.GeometryType.Polygon)
        banda.setColor(_color(COLOR_SELECCION, 230))
        banda.setFillColor(_color(COLOR_SELECCION, 110))
        banda.setWidth(3)
        banda.setToGeometry(bloque.geometria, None)
        self.seleccion[bloque.clave] = bloque
        self.bandas[bloque.clave] = banda

    def _desmarcar(self, clave):
        self.seleccion.pop(clave, None)
        self._quitar_banda(self.bandas.pop(clave, None))

    def _quitar_banda(self, banda):
        if banda is not None:
            banda.reset()
            self.canvas().scene().removeItem(banda)

    def _quitar_banda_rect(self):
        self._quitar_banda(self.banda_rect)
        self.banda_rect = None

    def _actualizar_panel(self):
        bloques = list(self.seleccion.values())
        self.panel.mostrar_seleccion(len(bloques), sum(len(b.valvulas) for b in bloques),
                                     sum(b.caudal_lh for b in bloques))

    def limpiar(self):
        for banda in self.bandas.values():
            self._quitar_banda(banda)
        self.bandas.clear()
        self.seleccion.clear()
        self._actualizar_panel()

    # ------------------------------------------------------------------ asignar

    def asignar(self, turno):
        if not self.seleccion:
            return
        try:
            cuantas = turnos_mapa.asignar(list(self.seleccion.values()), turno, self._crs())
        except ValueError as error:
            self.panel.avisar(str(error))
            return
        self.limpiar()
        self.panel.refrescar(self._crs())
        self.panel.turno_siguiente()
        self.canvas().refresh()
        self.panel.cambio.emit()
        return cuantas

    def quitar(self):
        if not self.seleccion:
            return
        ids = [v.id for b in self.seleccion.values() for v in b.valvulas]
        try:
            turnos_mapa.quitar(ids)
        except ValueError as error:
            self.panel.avisar(str(error))
            return
        self.limpiar()
        self.panel.refrescar(self._crs())
        self.canvas().refresh()
        self.panel.cambio.emit()

    # ------------------------------------------------------------------ teclado y ciclo de vida

    def keyPressEvent(self, evento):  # noqa: N802
        if evento.key() == Qt.Key.Key_Escape:
            evento.accept()
            self.limpiar()
        elif evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            evento.accept()
            self.asignar(self.panel.spin_turno.value())
        else:
            evento.ignore()

    def activate(self):
        super().activate()
        self.panel.refrescar(self._crs())
        self.panel.turno_siguiente()
        self.panel.mostrar_seleccion(0, 0, 0.0)
        self.panel.show()
        self.panel.raise_()

    def deactivate(self):
        self.limpiar()
        self._quitar_banda_rect()
        super().deactivate()
