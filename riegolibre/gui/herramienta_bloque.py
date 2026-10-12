"""Herramienta de mapa «Bloque de goteo»: un clic en un lote abre su ventana de diseño.

Ctrl + clic en un lote elimina su bloque (previa confirmación), como en IRRICAD; Ctrl + Z lo recupera.
"""

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject, QgsRectangle
from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence

from ..integracion.lotes import capas_de_lotes


def lote_en(punto, crs_mapa):
    """(capa, entidad) del lote visible que contiene el punto del mapa, o None."""
    raiz = QgsProject.instance().layerTreeRoot()
    for capa in capas_de_lotes():
        nodo = raiz.findLayer(capa.id())
        if nodo is not None and not nodo.isVisible():
            continue
        transformacion = QgsCoordinateTransform(crs_mapa, capa.crs(), QgsProject.instance())
        p = transformacion.transform(punto)
        geometria_punto = QgsGeometry.fromPointXY(p)
        for entidad in capa.getFeatures(QgsRectangle(p.x(), p.y(), p.x(), p.y())):
            if entidad.geometry().contains(geometria_punto):
                return capa, entidad
    return None


class HerramientaBloque(QgsMapTool):
    def __init__(self, canvas, abrir, avisar, eliminar=None, deshacer=None):
        super().__init__(canvas)
        self.abrir, self.avisar, self.eliminar, self.deshacer = abrir, avisar, eliminar, deshacer
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def canvasReleaseEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        encontrado = lote_en(evento.mapPoint(), self.canvas().mapSettings().destinationCrs())
        if encontrado is None:
            if not capas_de_lotes():
                self.avisar("No hay una capa de lotes en el proyecto. Use primero «Importar lotes de CAD».")
            else:
                self.avisar("No hay un lote visible en ese punto. Haga clic dentro de un lote.")
            return
        if self.eliminar is not None and evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.eliminar(*encontrado)
        else:
            self.abrir(*encontrado)

    def keyPressEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        """Ctrl + Z recupera el último bloque eliminado."""
        if self.deshacer is not None and evento.matches(QKeySequence.StandardKey.Undo):
            evento.accept()
            self.deshacer()
        else:
            evento.ignore()
