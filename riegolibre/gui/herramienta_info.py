"""Herramienta de mapa «Información del objeto» y su ventana de ficha."""

from qgis.core import Qgis
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QPlainTextEdit,
                                 QPushButton, QSplitter, QVBoxLayout)

from ..integracion import info_objeto
from ..nucleo.graficos import dibujar_perfil_lateral, referencia_emisor
from .comunes import Figure, FigureCanvasQTAgg

TOLERANCIA_PIXELES = 10
AYUDA = ("No hay ningún objeto calculado de RiegoLibre en ese punto.\n\n"
         "Haga clic sobre un lateral, un tramo de portalateral, una tubería de la red principal, una "
         "válvula o la bomba. Solo se consultan las capas de resultado visibles (grupos «RiegoLibre · …» "
         "y «Red principal»); si aún no calculó, use primero las ventanas de diseño.")


class DialogoInfo(QDialog):
    """Ficha de un objeto, en texto de ancho fijo; se queda abierta mientras se consultan otros objetos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RiegoLibre · Información del objeto")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(900, 760)
        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        fuente = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        self.texto.setFont(fuente)
        self.figura = self.lienzo = None
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.texto)
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(7, 4), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            divisor.addWidget(self.lienzo)
            self.lienzo.hide()
        botones = QDialogButtonBox()
        self.boton_copiar = QPushButton("Copiar")
        botones.addButton(self.boton_copiar, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.hide)
        self.boton_copiar.clicked.connect(self.copiar)
        capa = QVBoxLayout(self)
        capa.addWidget(divisor)
        capa.addWidget(botones)

    def mostrar(self, ficha=None, perfil=None):
        """Muestra la ficha; con `perfil` (PerfilLateral) dibuja además la presión y el caudal del lateral."""
        self._dibujar(perfil, ficha)
        if ficha is None:
            self.setWindowTitle("RiegoLibre · Información del objeto")
            self.texto.setPlainText(AYUDA)
        else:
            self.setWindowTitle(f"RiegoLibre · {ficha.titulo}")
            self.texto.setPlainText(ficha.texto)
        self.show()
        self.raise_()

    def _dibujar(self, perfil, ficha):
        if self.lienzo is None:
            return
        if perfil is None:
            self.lienzo.hide()
            return
        referencia, etiqueta = referencia_emisor(perfil.emisor)
        dibujar_perfil_lateral(self.figura, perfil.resultado, referencia, etiqueta,
                               ficha.titulo if ficha else None)
        self.lienzo.show()
        self.lienzo.draw()

    def copiar(self):
        QApplication.clipboard().setText(self.texto.toPlainText())


class HerramientaInfo(QgsMapTool):
    """Un clic sobre un objeto calculado abre su ficha y lo resalta en el mapa."""

    def __init__(self, canvas, dialogo):
        super().__init__(canvas)
        self.dialogo = dialogo
        self.resaltado = None
        self.setCursor(Qt.CursorShape.WhatsThisCursor)

    def canvasReleaseEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        if evento.button() == Qt.MouseButton.LeftButton:
            self.consultar(evento.mapPoint())

    def consultar(self, punto):
        """Muestra la ficha del objeto más cercano al punto del mapa (en el SRC del lienzo)."""
        canvas = self.canvas()
        tolerancia = TOLERANCIA_PIXELES * canvas.mapUnitsPerPixel()
        encontrado = info_objeto.consultar(punto, canvas.mapSettings().destinationCrs(), tolerancia)
        self._quitar_resaltado()
        if encontrado is None:
            self.dialogo.mostrar(None)
            return None
        ficha, candidato = encontrado
        self._resaltar(candidato)
        self.dialogo.mostrar(ficha, info_objeto.perfil_lateral(candidato))
        return ficha

    def _resaltar(self, candidato):
        tipo = candidato.capa.geometryType()
        banda = QgsRubberBand(self.canvas(), Qgis.GeometryType.Point if tipo == Qgis.GeometryType.Point
                              else Qgis.GeometryType.Line)
        banda.setColor(QColor(255, 193, 7, 220))
        banda.setWidth(5 if tipo != Qgis.GeometryType.Point else 12)
        banda.setToGeometry(candidato.entidad.geometry(), candidato.capa)
        self.resaltado = banda

    def _quitar_resaltado(self):
        if self.resaltado is not None:
            self.resaltado.reset()
            self.canvas().scene().removeItem(self.resaltado)
            self.resaltado = None

    def deactivate(self):
        self._quitar_resaltado()
        super().deactivate()
