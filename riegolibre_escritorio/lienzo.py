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
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView)

from riegolibre.nucleo.turnos import PALETA as PALETA_TURNOS

from .capas import CAPAS

FACTOR_ZOOM = 1.25
RADIO_ESCENA_M = 200_000.0  # el mapa se puede recorrer hasta esta distancia del origen (aunque esté vacío)

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
    """Vista del mapa. Emite `coordenadas(x, y)` al mover el ratón, en las coordenadas del proyecto."""

    coordenadas = Signal(float, float)

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
        self._paneo = None  # posición del botón central al desplazar
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
        self.scale(factor, factor)

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

    def contextMenuEvent(self, evento):  # noqa: N802 (Qt) — el clic derecho lo usan las herramientas
        evento.accept()


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
    laterales, lotes = capas["LATERALES"], capas["LOTES"]

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
    if proyecto.matriz:
        lienzo.lineas(matriz, proyecto.matriz, matriz.color, matriz.ancho, z=3, estilo=matriz.linea,
                      info="Tubería matriz dibujada")
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
