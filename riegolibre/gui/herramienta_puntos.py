"""Herramienta de mapa para marcar puntos, con imán a los vértices y lados de unas geometrías.

La usa el bloque de goteo para fijar la dirección de los laterales con dos puntos, para colocar la
válvula y para dibujar el portalateral, como IRRICAD («Block Lateral: Enter First Point / Enter Second
Point», «Place a Point», «Manual»).
"""

from qgis.core import Qgis, QgsGeometry, QgsPointXY
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor

TOLERANCIA_PX = 12  # radio del imán, en píxeles de la pantalla


class HerramientaPuntos(QgsMapTool):
    """Pide `cuantos` puntos (1 o 2) y llama a `terminar(puntos)` con ellos, en el SRC del mapa.

    Con `cuantos=None` se dibuja una línea de dos o más puntos: termina con clic derecho, doble clic o
    Intro (el clic derecho antes del segundo punto cancela).

    `geometrias`: geometrías (en el SRC del mapa) cuyos vértices y lados atraen al cursor; también se usa
    el imán del proyecto si está activado. `mensajes`: un texto para la barra de estado por cada punto.
    Con Esc o clic derecho, o al elegir otra herramienta, se cancela y se llama a `cancelar()`; al terminar
    o cancelar con Esc el mapa queda sin herramienta (`canvas.mapTool()` es None).
    """

    def __init__(self, canvas, cuantos, geometrias, mensajes, terminar, cancelar, mostrar_estado=None):
        super().__init__(canvas)
        self.cuantos, self.geometrias, self.mensajes = cuantos, [g for g in geometrias if g], mensajes
        self.terminar, self.cancelar, self.mostrar_estado = terminar, cancelar, mostrar_estado
        self.puntos = []
        self._acabado = False
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.resaltado = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.resaltado.setColor(QColor(0, 200, 0, 30))
        self.resaltado.setStrokeColor(QColor(0, 200, 0))
        self.resaltado.setWidth(2)
        for geometria in self.geometrias:
            if geometria.type() == Qgis.GeometryType.Polygon:
                self.resaltado.addGeometry(geometria, None)
        self.linea = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.linea.setColor(QColor(230, 120, 0))
        self.linea.setWidth(2)
        self.iman = QgsVertexMarker(canvas)
        self.iman.setColor(QColor(230, 0, 230))
        self.iman.setPenWidth(2)
        self.iman.setIconSize(12)
        self.iman.hide()

    # ---------------------------------------------------------------- imán

    def punto_con_iman(self, punto_pantalla, punto_mapa):
        """(punto, tipo) con tipo «vértice», «lado» o None si no hubo imán."""
        tolerancia = TOLERANCIA_PX * self.canvas().mapUnitsPerPixel()
        coincidencia = self.canvas().snappingUtils().snapToMap(punto_pantalla)
        if coincidencia.isValid():
            return QgsPointXY(coincidencia.point()), "vértice" if coincidencia.hasVertex() else "lado"
        mejor = None
        for geometria in self.geometrias:
            vertice, _, _, _, d2 = geometria.closestVertex(punto_mapa)
            if 0 <= d2 <= tolerancia ** 2 and (mejor is None or d2 < mejor[0]):
                mejor = (d2, QgsPointXY(vertice), "vértice")
        if mejor is not None:
            return mejor[1], mejor[2]
        for geometria in self.geometrias:
            if geometria.type() == Qgis.GeometryType.Point:
                continue
            d2, cercano, _, _ = geometria.closestSegmentWithContext(punto_mapa)
            if 0 <= d2 <= tolerancia ** 2 and (mejor is None or d2 < mejor[0]):
                mejor = (d2, QgsPointXY(cercano), "lado")
        return (mejor[1], mejor[2]) if mejor else (punto_mapa, None)

    # ---------------------------------------------------------------- eventos

    def activate(self):
        super().activate()
        self._estado()

    def _estado(self):
        if self.mostrar_estado is None:
            return
        if self.cuantos is None:
            self.mostrar_estado(self.mensajes[min(len(self.puntos), len(self.mensajes) - 1)]
                                + " · clic derecho, doble clic o Intro para terminar · Esc para cancelar")
        elif len(self.puntos) < len(self.mensajes):
            self.mostrar_estado(self.mensajes[len(self.puntos)] + " · Esc o clic derecho para cancelar")

    def canvasMoveEvent(self, evento):  # noqa: N802 (nombre exigido por Qt)
        if self._acabado:
            return
        punto, tipo = self.punto_con_iman(evento.pos(), evento.mapPoint())
        if tipo is None:
            self.iman.hide()
        else:
            self.iman.setIconType(QgsVertexMarker.IconType.ICON_BOX if tipo == "vértice"
                                  else QgsVertexMarker.IconType.ICON_X)
            self.iman.setCenter(punto)
            self.iman.show()
        if self.puntos:
            self.linea.setToGeometry(QgsGeometry.fromPolylineXY(self.puntos + [punto]), None)

    def canvasReleaseEvent(self, evento):  # noqa: N802
        if self._acabado:
            return
        if evento.button() == Qt.MouseButton.RightButton:
            self._salir(cancelado=self.cuantos is not None or len(self.puntos) < 2)
            return
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        punto, _ = self.punto_con_iman(evento.pos(), evento.mapPoint())
        if self.puntos and punto == self.puntos[-1]:
            return  # doble clic en el mismo sitio
        self.puntos.append(punto)
        if self.cuantos is not None and len(self.puntos) >= self.cuantos:
            self._salir(cancelado=False)
        else:
            self._estado()

    def canvasDoubleClickEvent(self, evento):  # noqa: N802
        if self.cuantos is None and len(self.puntos) >= 2:
            self._salir(cancelado=False)

    def keyPressEvent(self, evento):  # noqa: N802
        if evento.key() == Qt.Key.Key_Escape:
            self._salir(cancelado=True)
        elif evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.cuantos is None:
            self._salir(cancelado=len(self.puntos) < 2)

    def deactivate(self):
        self._limpiar()
        super().deactivate()
        if not self._acabado:  # el usuario eligió otra herramienta: se avisa cuando ya esté activa
            self._acabado = True
            if self.mostrar_estado is not None:
                self.mostrar_estado("")
            QTimer.singleShot(0, self.cancelar)

    def _limpiar(self):
        for objeto in (self.resaltado, self.linea, self.iman):
            if objeto is not None:
                self.canvas().scene().removeItem(objeto)
        self.resaltado = self.linea = self.iman = None

    def _salir(self, cancelado):
        if self._acabado:
            return
        self._acabado = True
        if self.mostrar_estado is not None:
            self.mostrar_estado("")
        puntos = list(self.puntos)
        self.canvas().unsetMapTool(self)
        if cancelado:
            self.cancelar()
        else:
            self.terminar(puntos)
