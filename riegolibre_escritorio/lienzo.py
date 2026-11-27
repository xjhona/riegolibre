# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Lienzo del mapa propio, sobre `QGraphicsView`: capas del diseño, zoom con la rueda y desplazamiento.

Las coordenadas del proyecto (metros, UTM) se pasan a la escena restando un origen cercano y cambiando el signo
de la Y (en la escena la Y crece hacia abajo); así los textos y símbolos quedan derechos y no se pierde
precisión con números como 8 650 000. Los trazos son «cosméticos»: tienen el mismo grosor en pantalla con
cualquier zoom.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QStyleOptionGraphicsItem)

from riegolibre.nucleo.turnos import PALETA as PALETA_TURNOS

from . import dibujos
from .capas import CAPAS
from .edicion import nodos_matriz, tramos_en_nodo

FACTOR_ZOOM = 1.25
PAUSA_ZOOM_MS = 250  # tras tanto sin zoom, las curvas de nivel dejan el borrador y se pintan con calidad completa
RADIO_ESCENA_M = 200_000.0  # el mapa se puede recorrer hasta esta distancia del origen (aunque esté vacío)
Z_IMAGEN = -10.0  # la imagen de fondo, debajo de todo (las curvas de nivel van en -1)

TIPOS_LINEA = {"solida": Qt.PenStyle.SolidLine, "discontinua": Qt.PenStyle.DashLine,
               "punteada": Qt.PenStyle.DotLine, "punto_raya": Qt.PenStyle.DashDotLine}
# Diámetros de la red, del menor al mayor
PALETA_DIAMETROS = ["#fdd835", "#fb8c00", "#e53935", "#8e24aa", "#3949ab", "#00897b", "#6d4c41", "#212121"]


def color_turno(turno: int) -> str:
    return PALETA_TURNOS[(max(1, int(turno)) - 1) % len(PALETA_TURNOS)]


@dataclass
class Capa:
    """Una capa del lienzo: sus elementos gráficos y su estilo (color, línea, grosor, visible, imprimir)."""
    nombre: str
    estilo: dict
    elementos: List[QGraphicsItem] = field(default_factory=list)

    @property
    def visible(self) -> bool:
        return bool(self.estilo["visible"])

    @property
    def color(self) -> str:
        return self.estilo["color"]

    @property
    def ancho(self) -> float:
        return float(self.estilo["ancho"])

    @property
    def linea(self):
        return TIPOS_LINEA.get(self.estilo["linea"], Qt.PenStyle.SolidLine)

    def mostrar(self, visible: bool):
        self.estilo["visible"] = bool(visible)
        for elemento in self.elementos:
            elemento.setVisible(visible)


def _pluma(color, ancho, estilo=Qt.PenStyle.SolidLine):
    pluma = QPen(QColor(color), ancho, estilo)
    pluma.setCosmetic(True)
    pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
    pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pluma


class Lienzo(QGraphicsView):
    """Vista del mapa. Emite `coordenadas(x, y)` al mover el ratón, en las coordenadas del proyecto, y
    `menu_contextual(x, y, posición global)` con el clic derecho (el menú lo arma la ventana)."""

    coordenadas = Signal(float, float)
    menu_contextual = Signal(float, float, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.escena = QGraphicsScene(self)
        self.setScene(self.escena)
        self.origen = (0.0, 0.0)
        self.capas: Dict[str, Capa] = {}
        self.diametros: List[tuple] = []  # (tubería, color) de la red calculada
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.herramienta = None  # herramientas.Herramienta activa
        self.texto_imagen = ""  # fuente y fecha de la imagen de fondo (para la barra de capas)
        self._pixmap = (None, None)  # (archivo, QPixmap) de la imagen de fondo: no se vuelve a leer al redibujar
        self._paneo = None  # posición del botón central al desplazar
        self._fin_zoom = QTimer(self)  # al dejar de hacer zoom, las curvas se repintan con calidad completa
        self._fin_zoom.setSingleShot(True)
        self._fin_zoom.setInterval(PAUSA_ZOOM_MS)
        self._fin_zoom.timeout.connect(self._zoom_terminado)
        self._fijar_rect_escena()

    def _fijar_rect_escena(self):
        r = RADIO_ESCENA_M
        self.escena.setSceneRect(QRectF(-r, -r, 2 * r, 2 * r))

    def fijar_herramienta(self, herramienta):
        if self.herramienta is not None:
            self.herramienta.desactivar()
        self.herramienta = herramienta
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if herramienta is None or herramienta.arrastrar_mapa
                         else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(herramienta.cursor if herramienta is not None else Qt.CursorShape.OpenHandCursor)
        if herramienta is not None:
            herramienta.activar()

    # ------------------------------------------------------------ coordenadas

    def a_escena(self, x: float, y: float) -> QPointF:
        return QPointF(x - self.origen[0], self.origen[1] - y)

    def de_escena(self, punto: QPointF):
        return punto.x() + self.origen[0], self.origen[1] - punto.y()

    def _poligono(self, puntos) -> QPolygonF:
        return QPolygonF([self.a_escena(*p) for p in puntos])

    # ------------------------------------------------------------ capas

    def limpiar(self, origen=(0.0, 0.0)):
        self.escena.clear()
        self.capas = {}
        self.origen = (float(origen[0]), float(origen[1]))
        self._fijar_rect_escena()

    def nueva_capa(self, nombre: str, estilo: dict) -> Capa:
        capa = Capa(nombre, estilo)
        self.capas[nombre] = capa
        return capa

    def _agregar(self, capa: Capa, elemento: QGraphicsItem, z: float):
        elemento.setZValue(z)
        elemento.setVisible(capa.visible)
        self.escena.addItem(elemento)
        capa.elementos.append(elemento)
        return elemento

    def poligono(self, capa: Capa, anillos, color_borde, color_relleno=None, ancho=1.2, z=0.0, info=None,
                 estilo=Qt.PenStyle.SolidLine):
        camino = QPainterPath()
        camino.setFillRule(Qt.FillRule.OddEvenFill)
        for anillo in anillos:
            camino.addPolygon(self._poligono(list(anillo) + [anillo[0]]))
        elemento = QGraphicsPathItem(camino)
        elemento.setPen(_pluma(color_borde, ancho, estilo))
        elemento.setBrush(QBrush(QColor(color_relleno)) if color_relleno else QBrush(Qt.BrushStyle.NoBrush))
        if info:
            elemento.setToolTip(info)
        return self._agregar(capa, elemento, z)

    def lineas(self, capa: Capa, polilineas, color, ancho=1.0, z=1.0, estilo=Qt.PenStyle.SolidLine, info=None):
        """Varias polilíneas en un solo elemento (miles de laterales se dibujan rápido)."""
        camino = QPainterPath()
        for linea in polilineas:
            if len(linea) < 2:
                continue
            camino.moveTo(self.a_escena(*linea[0]))
            for p in linea[1:]:
                camino.lineTo(self.a_escena(*p))
        elemento = QGraphicsPathItem(camino)
        elemento.setPen(_pluma(color, ancho, estilo))
        if info:
            elemento.setToolTip(info)
        return self._agregar(capa, elemento, z)

    def simbolo(self, capa: Capa, x, y, color, forma="circulo", lado=9.0, z=5.0, info=None):
        """Símbolo de tamaño fijo en pantalla (válvulas, fuente)."""
        rect = QRectF(-lado / 2, -lado / 2, lado, lado)
        elemento = QGraphicsRectItem(rect) if forma == "cuadrado" else QGraphicsEllipseItem(rect)
        elemento.setPen(_pluma("#ffffff", 1.2))
        elemento.setBrush(QBrush(QColor(color)))
        elemento.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        elemento.setPos(self.a_escena(x, y))
        if info:
            elemento.setToolTip(info)
        return self._agregar(capa, elemento, z)

    def rotulo(self, capa: Capa, x, y, texto, color="#212121", tamano=9, negrita=False, z=6.0, arriba_px=0.0):
        """Texto centrado en (x, y), de tamaño fijo en pantalla; `arriba_px` lo sube esos píxeles."""
        elemento = QGraphicsSimpleTextItem(texto)
        fuente = QFont()
        fuente.setPointSizeF(tamano)
        fuente.setBold(negrita)
        elemento.setFont(fuente)
        elemento.setBrush(QBrush(QColor(color)))
        elemento.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        elemento.setPos(self.a_escena(x, y))
        caja = elemento.boundingRect()
        # Con ItemIgnoresTransformations la transformación propia va en píxeles: se corre medio texto
        elemento.setTransform(elemento.transform().translate(-caja.width() / 2, -caja.height() / 2 - arriba_px))
        return self._agregar(capa, elemento, z)

    def imagen(self, capa: Capa, nombre: str, contenido: bytes, esquinas, opacidad=1.0, info=None):
        """Imagen de fondo (JPEG o PNG) estirada sobre las esquinas UTM [xmin, ymin, xmax, ymax]."""
        if self._pixmap[0] != nombre:
            pixmap = QPixmap()
            if not pixmap.loadFromData(contenido):
                return None
            self._pixmap = (nombre, pixmap)
        pixmap = self._pixmap[1]
        xmin, ymin, xmax, ymax = (float(v) for v in esquinas)
        elemento = QGraphicsPixmapItem(pixmap)
        elemento.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        elemento.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        # La fila 0 de la imagen es el norte: en la escena (Y hacia abajo) queda arriba sin voltearla
        elemento.setPos(self.a_escena(xmin, ymax))
        elemento.setTransform(QTransform.fromScale((xmax - xmin) / pixmap.width(), (ymax - ymin) / pixmap.height()))
        elemento.setOpacity(max(0.0, min(1.0, opacidad)))
        if info:
            elemento.setToolTip(info)
        return self._agregar(capa, elemento, Z_IMAGEN)

    def mostrar_capa(self, nombre: str, visible: bool):
        if nombre in self.capas:
            self.capas[nombre].mostrar(visible)

    # ------------------------------------------------------------ navegación

    def ver_todo(self):
        caja = self.escena.itemsBoundingRect()
        if caja.isEmpty():  # proyecto vacío: unos 500 m alrededor del punto de referencia
            caja = QRectF(-250, -250, 500, 500)
        margen = max(caja.width(), caja.height()) * 0.05 + 1.0
        self.fitInView(caja.adjusted(-margen, -margen, margen, margen), Qt.AspectRatioMode.KeepAspectRatio)

    def acercar(self, factor=FACTOR_ZOOM):
        """Zoom; mientras se sigue girando la rueda las curvas se pintan en borrador (ver `ElementoCurvas`)."""
        curvas = self._elementos_curvas()
        for elemento in curvas:
            elemento.borrador = True
        self.scale(factor, factor)
        if curvas:
            self._fin_zoom.start()

    def _elementos_curvas(self):
        capa = self.capas.get("CURVAS_NIVEL")
        return [e for e in capa.elementos if isinstance(e, ElementoCurvas)] if capa else []

    def _zoom_terminado(self):
        for elemento in self._elementos_curvas():
            if elemento.borrador:
                elemento.borrador = False
                elemento.update()

    def alejar(self):
        self.acercar(1 / FACTOR_ZOOM)

    def metros_por_pixel(self) -> float:
        escala = math.hypot(self.transform().m11(), self.transform().m12())
        return 1.0 / escala if escala else 0.0

    def wheelEvent(self, evento):  # noqa: N802 (Qt)
        pasos = evento.angleDelta().y() / 120.0
        if pasos:
            self.acercar(FACTOR_ZOOM ** pasos)
        evento.accept()

    def _xy(self, evento):
        return self.de_escena(self.mapToScene(evento.position().toPoint()))

    def mousePressEvent(self, evento):  # noqa: N802 (Qt)
        if evento.button() == Qt.MouseButton.MiddleButton:
            self._paneo = evento.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            evento.accept()
            return
        if self.herramienta is not None and self.herramienta.presionar(evento, *self._xy(evento)):
            evento.accept()
            return
        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento):  # noqa: N802 (Qt)
        x, y = self._xy(evento)
        self.coordenadas.emit(x, y)
        if self._paneo is not None:
            delta = evento.position() - self._paneo
            self._paneo = evento.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            return
        if self.herramienta is not None and self.herramienta.mover(evento, x, y):
            return
        super().mouseMoveEvent(evento)

    def mouseReleaseEvent(self, evento):  # noqa: N802 (Qt)
        if evento.button() == Qt.MouseButton.MiddleButton and self._paneo is not None:
            self._paneo = None
            self.viewport().setCursor(self.herramienta.cursor if self.herramienta else Qt.CursorShape.OpenHandCursor)
            return
        if self.herramienta is not None and self.herramienta.soltar(evento, *self._xy(evento)):
            return
        super().mouseReleaseEvent(evento)
        if self.herramienta is not None:  # ScrollHandDrag cambia el cursor
            self.viewport().setCursor(self.herramienta.cursor)

    def mouseDoubleClickEvent(self, evento):  # noqa: N802 (Qt)
        if self.herramienta is not None and self.herramienta.doble_clic(evento, *self._xy(evento)):
            return
        super().mouseDoubleClickEvent(evento)

    def keyPressEvent(self, evento):  # noqa: N802 (Qt)
        if self.herramienta is not None and self.herramienta.tecla(evento):
            return
        super().keyPressEvent(evento)

    def contextMenuEvent(self, evento):  # noqa: N802 (Qt) — clic derecho: menú como el de IRRICAD
        evento.accept()
        self.menu_contextual.emit(*self.de_escena(self.mapToScene(evento.pos())), evento.globalPos())


CADA_MAESTRA = 5  # una curva maestra cada cinco equidistancias, como en los planos topográficos


VERTICES_TRAMO = 256  # las curvas se parten en tramos de hasta tantos vértices: solo se pintan los que se ven
# Tolerancias (m) de las versiones simplificadas de las curvas; 0 = la curva original
TOLERANCIAS_M = (0.0,) + tuple(0.25 * 2 ** k for k in range(14))
TOLERANCIA_PX = 0.5  # error admitido al simplificar, en píxeles de pantalla (no se nota)
CERCANIA_PX = 5.0  # distancia del ratón a una curva para mostrar su cota


def simplificar(puntos, tolerancia: float):
    """Polilínea con un vértice por celda de `tolerancia` m que recorre (más el primero y el último).

    Rápido (numpy) y con un error menor que la diagonal de la celda: sirve para dibujar alejado.
    """
    import numpy as np

    if tolerancia <= 0 or len(puntos) <= 2:
        return puntos
    celdas = np.floor(puntos / tolerancia)
    quedan = np.ones(len(puntos), dtype=bool)
    quedan[1:-1] = np.any(celdas[1:-1] != celdas[:-2], axis=1)  # el vértice entra a otra celda
    return puntos[quedan]


def poligono_de(puntos) -> QPolygonF:
    """QPolygonF de un ndarray (n, 2): se copia la memoria de una vez (punto a punto, un millón tarda un segundo)."""
    import numpy as np

    puntos = np.ascontiguousarray(puntos, dtype=np.float64)
    poligono = QPolygonF()
    try:
        import shiboken6

        poligono.resize(len(puntos))
        memoria = shiboken6.VoidPtr(poligono.data(), puntos.nbytes, True)
        np.frombuffer(memoria, dtype=np.float64).reshape(-1, 2)[:] = puntos
    except Exception:  # noqa: BLE001 — sin acceso a la memoria: el camino lento
        poligono = QPolygonF([QPointF(x, y) for x, y in puntos.tolist()])
    return poligono


class ElementoCurvas(QGraphicsItem):
    """Todas las curvas de nivel en un solo elemento, pensado para cientos de miles de vértices.

    Cada curva se parte en tramos con su caja: al pintar solo se recorren los tramos que se ven. Según el zoom se
    dibuja una versión simplificada (error de medio píxel), así alejar no repinta millones de vértices. El
    elemento guarda lo pintado en una imagen del tamaño de la pantalla (`DeviceCoordinateCache`): al desplazar
    el mapa no se vuelve a pintar, solo la franja que aparece. Mientras se hace zoom (`borrador`), las curvas van
    sin suavizado y de un píxel: una línea más gruesa cuesta decenas de veces más (Qt la contornea vértice a
    vértice); al detenerse, el lienzo las repinta con calidad completa.
    """

    def __init__(self, curvas_escena, pluma: QPen, pluma_maestra: QPen):
        """`curvas_escena`: [(cota, maestra, ndarray (n, 2) en coordenadas de la escena)]."""
        import numpy as np

        super().__init__()
        self.plumas = (pluma, pluma_maestra)
        self.plumas_borrador = tuple(self._delgada(p) for p in self.plumas)
        self.borrador = False
        self.cotas = []  # (cota, maestra) de cada curva
        tramos, cajas, curva_de = [], [], []
        for i, (cota, maestra, puntos) in enumerate(curvas_escena):
            self.cotas.append((cota, maestra))
            for inicio in range(0, max(1, len(puntos) - 1), VERTICES_TRAMO - 1):
                tramo = puntos[inicio:inicio + VERTICES_TRAMO]
                if len(tramo) < 2:
                    continue
                tramos.append(tramo)
                cajas.append((tramo[:, 0].min(), tramo[:, 1].min(), tramo[:, 0].max(), tramo[:, 1].max()))
                curva_de.append(i)
        self.tramos = tramos
        self.cajas = np.asarray(cajas, dtype=float).reshape(-1, 4)
        self.curva_de = np.asarray(curva_de, dtype=int)
        self.maestra = np.asarray([self.cotas[i][1] for i in curva_de], dtype=bool)
        self._poligonos: Dict[int, list] = {}  # nivel de detalle: QPolygonF de cada tramo (se arman al usarlos)
        if len(self.cajas):
            x0, y0 = self.cajas[:, :2].min(axis=0)
            x1, y1 = self.cajas[:, 2:].max(axis=0)
            margen = max(x1 - x0, y1 - y0) * 0.01 + 1.0
            self._caja = QRectF(x0 - margen, y0 - margen, x1 - x0 + 2 * margen, y1 - y0 + 2 * margen)
        else:
            self._caja = QRectF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setAcceptHoverEvents(True)

    @staticmethod
    def _delgada(pluma: QPen) -> QPen:
        delgada = QPen(pluma)
        delgada.setWidthF(min(1.0, pluma.widthF()))
        return delgada

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt)
        return self._caja

    def _poligono(self, nivel: int, indice: int) -> QPolygonF:
        poligonos = self._poligonos.setdefault(nivel, [None] * len(self.tramos))
        if poligonos[indice] is None:
            poligonos[indice] = poligono_de(simplificar(self.tramos[indice], TOLERANCIAS_M[nivel]))
        return poligonos[indice]

    @staticmethod
    def nivel_para(pixeles_por_metro: float) -> int:
        """El nivel más simplificado cuyo error queda bajo `TOLERANCIA_PX` con ese zoom."""
        if pixeles_por_metro <= 0:
            return len(TOLERANCIAS_M) - 1
        admitido = TOLERANCIA_PX / pixeles_por_metro
        return max(i for i, t in enumerate(TOLERANCIAS_M) if t <= admitido)

    def paint(self, painter, opcion, widget=None):
        import numpy as np

        if not len(self.cajas):
            return
        zoom = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        nivel = self.nivel_para(zoom / 2 if self.borrador else zoom)  # en borrador, error de un píxel
        plumas = self.plumas_borrador if self.borrador else self.plumas
        if self.borrador:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        r = opcion.exposedRect
        c = self.cajas
        vistos = (c[:, 2] >= r.left()) & (c[:, 0] <= r.right()) & (c[:, 3] >= r.top()) & (c[:, 1] <= r.bottom())
        for maestra in (False, True):
            indices = np.nonzero(vistos & (self.maestra == maestra))[0]
            if len(indices):
                painter.setPen(plumas[maestra])
                for i in indices.tolist():
                    painter.drawPolyline(self._poligono(nivel, i))

    def cota_cerca(self, x: float, y: float, distancia: float):
        """(cota, maestra) de la curva más cercana al punto de la escena (x, y), a menos de `distancia`; si no, None."""
        import numpy as np

        if not len(self.cajas):
            return None
        c = self.cajas
        cerca = np.nonzero((c[:, 0] - distancia <= x) & (c[:, 2] + distancia >= x)
                           & (c[:, 1] - distancia <= y) & (c[:, 3] + distancia >= y))[0]
        mejor, elegido = distancia, None
        for i in cerca.tolist():
            p = self.tramos[i]
            a, b = p[:-1], p[1:]
            ab = b - a
            largo2 = np.einsum("ij,ij->i", ab, ab)
            t = np.clip(np.einsum("ij,ij->i", np.array([x, y]) - a, ab) / np.where(largo2 > 0, largo2, 1), 0, 1)
            d = float(np.min(np.hypot(a[:, 0] + t * ab[:, 0] - x, a[:, 1] + t * ab[:, 1] - y)))
            if d <= mejor:
                mejor, elegido = d, int(self.curva_de[i])
        return None if elegido is None else self.cotas[elegido]

    def hoverMoveEvent(self, evento):  # noqa: N802 (Qt): la cota de la curva bajo el ratón, como descripción
        vistas = self.scene().views() if self.scene() else []
        escala = math.hypot(vistas[0].transform().m11(), vistas[0].transform().m12()) if vistas else 1.0
        p = evento.pos()
        cerca = self.cota_cerca(p.x(), p.y(), CERCANIA_PX / (escala or 1.0))
        self.setToolTip("" if cerca is None else texto_curva(*cerca))
        super().hoverMoveEvent(evento)


def texto_curva(cota, maestra) -> str:
    return "Curva de nivel" + ("" if cota is None else f" {cota:g} m") + (" (maestra)" if maestra else "")


def dibujar_curvas(lienzo: Lienzo, capa: Capa, curvas):
    """Curvas de nivel en un solo `ElementoCurvas` (con la cota bajo el ratón); las maestras, al doble."""
    if not curvas:
        return
    import numpy as np

    from .topografia import equidistancia

    paso = equidistancia(curvas)
    preparadas = []
    for cota, linea in curvas:
        if len(linea) < 2:
            continue
        cota = None if cota is None else round(cota, 3)
        maestra = cota is not None and paso is not None and abs(cota / (paso * CADA_MAESTRA)
                                                                - round(cota / (paso * CADA_MAESTRA))) < 1e-6
        puntos = np.asarray(linea, dtype=float)[:, :2]
        puntos = np.column_stack((puntos[:, 0] - lienzo.origen[0], lienzo.origen[1] - puntos[:, 1]))
        preparadas.append((cota, maestra, puntos))
    plumas = [_pluma(capa.color, capa.ancho * factor, capa.linea) for factor in (1, 2)]
    for pluma in plumas:  # extremos y uniones redondos triplican el tiempo de las líneas gruesas y no se notan aquí
        pluma.setCapStyle(Qt.PenCapStyle.FlatCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
    elemento = ElementoCurvas(preparadas, *plumas)
    lienzo._agregar(capa, elemento, -1)


def dibujar_lineas_cad(lienzo: Lienzo, capa: Capa, lineas):
    """Líneas de referencia de un DXF: un elemento por capa del dibujo, con su nombre como descripción."""
    por_capa: Dict[str, list] = {}
    for nombre, linea in lineas:
        por_capa.setdefault(nombre, []).append(linea)
    for nombre, polilineas in por_capa.items():
        lienzo.lineas(capa, polilineas, capa.color, capa.ancho, z=-0.5, estilo=capa.linea,
                      info=f"Dibujo CAD: capa «{nombre}»")


def dibujar_imagen(lienzo: Lienzo, capa: Capa, proyecto):
    """Imagen satelital (o propia) de fondo, con la transparencia de su capa.

    Sin descripción emergente (taparía todo el mapa): su fuente y fecha quedan en `lienzo.texto_imagen`, que la
    barra de capas muestra en la fila de la capa."""
    imagen = proyecto.imagen
    lienzo.texto_imagen = ""
    if imagen is None:
        return None
    texto = f"Imagen de fondo: {imagen.get('fuente', '')}"
    if imagen.get("zoom") is not None:
        texto += f" (zoom {imagen['zoom']})"
    if imagen.get("fecha"):
        texto += f", descargada el {imagen['fecha']}"
    if imagen.get("atribucion"):
        texto += "\n" + imagen["atribucion"]
    lienzo.texto_imagen = texto
    opacidad = 1.0 - float(capa.estilo.get("transparencia", 0)) / 100.0
    return lienzo.imagen(capa, imagen["archivo"], proyecto.archivos[imagen["archivo"]], imagen["esquinas"],
                         opacidad)


def dibujar_proyecto(lienzo: Lienzo, proyecto, conservar_vista=False) -> Dict[str, Capa]:
    """Dibuja el proyecto en el lienzo con los estilos de capa del proyecto (`proyecto.estilos_capas`)."""
    from mcp_riegolibre.motor import _anillos_de

    transformacion = lienzo.transform()
    centro_proyecto = lienzo.de_escena(lienzo.mapToScene(lienzo.viewport().rect().center()))
    extension = proyecto.extension()
    if conservar_vista:  # el mismo origen: lo que se está dibujando no se corre
        lienzo.limpiar(lienzo.origen)
    else:
        lienzo.limpiar(((extension[0] + extension[2]) / 2, (extension[1] + extension[3]) / 2) if extension else (0, 0))
    estilos = proyecto.estilos_capas
    capas = {nombre: lienzo.nueva_capa(nombre, estilos[nombre]) for nombre in CAPAS}
    texto, fuente, valvulas = capas["TEXTO"], capas["FUENTE"], capas["VÁLVULAS"]
    red, matriz, porta = capas["RED_PRINCIPAL"], capas["MATRIZ_DIBUJADA"], capas["PORTALATERALES"]
    nodos = capas["NODOS_MATRIZ"]
    laterales, lotes = capas["LATERALES"], capas["LOTES"]
    dibujar_imagen(lienzo, capas["IMAGEN_SATELITAL"], proyecto)
    dibujar_curvas(lienzo, capas["CURVAS_NIVEL"], proyecto.curvas)
    dibujar_lineas_cad(lienzo, capas["DIBUJO_CAD"], proyecto.dibujo)
    dibujos.pintar(lienzo, capas["DIBUJO"], proyecto.datos)

    # Lotes sin subunidad calculada (por ejemplo, con error): solo el contorno, en rojo
    subunidades = proyecto.subunidades
    calculados = {s.lote for s in subunidades}
    for lote in proyecto.datos.get("lotes", []):
        if lote.get("nombre") not in calculados:
            try:
                anillos = _anillos_de(lote)
            except ValueError:
                continue
            lienzo.poligono(lotes, anillos, "#c62828", None, lotes.ancho, z=0,
                            info=f"{lote.get('nombre')}: sin calcular", estilo=lotes.linea)
    for s in subunidades:
        relleno = QColor(color_turno(s.turno))
        relleno.setAlpha(55)
        r = s.resumen()
        info = (f"{s.nombre} · turno {s.turno}\n{r['area_ha']:.2f} ha · {r['caudal_m3h']:.2f} m³/h\n"
                f"Presión en la válvula {r['presion_valvula_m']:.2f} m\nPortalateral: {r['portalateral']}\n"
                + ("Cumple" if r["cumple"] else "No cumple: " + "; ".join(r["motivos"])))
        lienzo.poligono(lotes, s.anillos, lotes.color, relleno.name(QColor.NameFormat.HexArgb), lotes.ancho, z=0,
                        info=info, estilo=lotes.linea)
        b = s.bloque
        lienzo.lineas(laterales, [[lat.inicio, lat.fin] for lat in b.laterales], laterales.color, laterales.ancho,
                      z=1, estilo=laterales.linea)
        lienzo.lineas(porta, [b.portalateral], porta.color, porta.ancho, z=2, estilo=porta.linea,
                      info=f"Portalateral {s.nombre}")
        lienzo.simbolo(valvulas, *b.valvula, valvulas.color, "cuadrado", 9, z=6, info=info)
        xs = [p[0] for a in s.anillos for p in a]
        ys = [p[1] for a in s.anillos for p in a]
        lienzo.rotulo(texto, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, f"{s.nombre}  T{s.turno}",
                      texto.color, negrita=True, z=7)
    tramos = proyecto.matriz
    for i, tramo in enumerate(tramos):
        lienzo.lineas(matriz, [tramo], matriz.color, matriz.ancho, z=3, estilo=matriz.linea,
                      info=f"Tubería matriz · tramo {i + 1} · {math.dist(*tramo):.1f} m")
    for i, p in enumerate(nodos_matriz(proyecto.datos)):
        llegan = len(tramos_en_nodo(tramos, p))
        lienzo.simbolo(nodos, *p, nodos.color, "cuadrado", 6 + nodos.ancho, z=3.5,
                       info=f"Nodo {i + 1} de la matriz · {llegan} tramo{'s' if llegan != 1 else ''}")
    lienzo.diametros = []
    if proyecto.red is not None:
        r = proyecto.red.resultado
        tuberias = sorted({t.nombre: t for t in r.asignacion.values()}.values(), key=lambda t: t.diametro_interior_mm)
        colores = {t.nombre: PALETA_DIAMETROS[min(i, len(PALETA_DIAMETROS) - 1)] for i, t in enumerate(tuberias)}
        lienzo.diametros = [(t.nombre, colores[t.nombre]) for t in tuberias]
        for tramo in proyecto.red.red.tramos:
            tuberia = r.asignacion[tramo.id]
            caudal = r.peor_tramo(tramo.id)[0]
            velocidad = max(x.tramos[tramo.id].velocidad_ms for x in r.turnos)
            info = (f"Tramo {tramo.id} · {tuberia.nombre}\n{tramo.longitud_m:.1f} m · {caudal / 1000:.2f} m³/h · "
                    f"{velocidad:.2f} m/s" + (f"\n{r.observaciones(tramo.id)}" if r.observaciones(tramo.id) else ""))
            lienzo.lineas(red, [proyecto.red.geometrias[tramo.id]], colores[tuberia.nombre], red.ancho, z=4,
                          estilo=red.linea, info=info)
    if proyecto.fuente:
        lienzo.simbolo(fuente, *proyecto.fuente, fuente.color, "circulo", 14, z=8, info="Fuente de agua")
        lienzo.rotulo(texto, proyecto.fuente[0], proyecto.fuente[1], "Fuente", fuente.color, 9, True, z=9,
                      arriba_px=16)

    if conservar_vista:
        lienzo.setTransform(transformacion)
        lienzo.centerOn(lienzo.a_escena(*centro_proyecto))
    else:
        lienzo.ver_todo()
    if lienzo.herramienta is not None:
        lienzo.herramienta.redibujar()
    return capas
