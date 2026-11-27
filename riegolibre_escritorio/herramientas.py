# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Herramientas del mapa (la barra vertical de la izquierda, como en IRRICAD).

- Seleccionar: clic en un lote, un tramo de la matriz o la fuente; arrastrar un vértice lo mueve; doble clic
  en un borde agrega un vértice; Ctrl + clic en un vértice lo quita; Supr borra el objeto; doble clic dentro
  de un lote abre su bloque de goteo. Arrastrar en un lugar vacío desplaza el mapa.
- Lote: polígono con clics; clic derecho, doble clic o Intro termina; Esc cancela; Retroceso quita el último.
- Fuente de agua: un clic; reemplaza la anterior («Water Supply»).
- Tubería matriz: polilínea, igual que el lote («Mainline Pipe»).
- Información: clic en un objeto muestra su ficha («Object Info»).

Todas usan el imán: el punto se pega al vértice (cuadro) o al borde (rombo) más cercano a menos de
`TOLERANCIA_PX` píxeles; con Mayús apretada no se usa el imán.

La herramienta no cambia el proyecto: le pasa los datos nuevos al `editor` (la ventana), que los guarda con
deshacer. El editor da: `datos()`, `aplicar(datos, texto)`, `editar_lote(i)`, `mostrar_ficha(x, y, tolerancia)`
y `mensaje(texto)`.
"""

import math
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem

from . import dibujos, edicion

TOLERANCIA_PX = 10
COLOR_DIBUJO = "#ff6f00"
COLOR_IMAN = "#d500f9"
Z_DIBUJO = 50


def _pluma(color, ancho, estilo=Qt.PenStyle.SolidLine):
    pluma = QPen(QColor(color), ancho, estilo)
    pluma.setCosmetic(True)
    return pluma


class Herramienta:
    """Base: recibe los eventos del lienzo en coordenadas del proyecto. Devuelve True si usó el evento."""

    nombre = ""
    cursor = Qt.CursorShape.CrossCursor
    arrastrar_mapa = False  # True: arrastrar con el botón izquierdo desplaza el mapa

    def __init__(self, lienzo, editor):
        self.lienzo, self.editor = lienzo, editor
        self._elementos: List[QGraphicsItem] = []
        self._marca: Optional[QGraphicsItem] = None

    # ----------------------------------------------------- ciclo de vida

    def activar(self):
        self.editor.mensaje(self.ayuda())

    def desactivar(self):
        self.cancelar()
        self._quitar_marca()

    def ayuda(self) -> str:
        return ""

    def cancelar(self):
        self._limpiar()

    def redibujar(self):
        """El lienzo se borró (se redibujó el proyecto): volver a poner lo propio."""
        self._elementos, self._marca = [], None

    # ----------------------------------------------------- utilidades

    @property
    def tolerancia(self) -> float:
        return TOLERANCIA_PX * self.lienzo.metros_por_pixel()

    def imantar(self, evento, x, y, datos=None, puntos_extra=(), segmentos_extra=()):
        """El punto con imán y la marca en pantalla."""
        if evento is not None and evento.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._quitar_marca()
            return (x, y)
        iman_extra = getattr(self.editor, "iman_extra", None)  # las líneas de referencia del DXF
        if iman_extra is not None:
            puntos_cad, segmentos_cad = iman_extra((x, y), self.tolerancia)
            puntos_extra, segmentos_extra = list(puntos_extra) + puntos_cad, list(segmentos_extra) + segmentos_cad
        p, tipo = edicion.imantar((x, y), self.editor.datos() if datos is None else datos, self.tolerancia,
                                  puntos_extra, segmentos_extra)
        self._poner_marca(p, tipo)
        return p

    def _poner_marca(self, p, tipo):
        self._quitar_marca()
        if tipo is None:
            return
        lado = 10.0
        marca = QGraphicsRectItem(QRectF(-lado / 2, -lado / 2, lado, lado))
        marca.setPen(_pluma(COLOR_IMAN, 2))
        marca.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        marca.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if tipo == edicion.BORDE:
            marca.setRotation(45)
        marca.setPos(self.lienzo.a_escena(*p))
        marca.setZValue(Z_DIBUJO + 5)
        marca.setToolTip(tipo)
        self.lienzo.escena.addItem(marca)
        self._marca = marca

    def _quitar_marca(self):
        if self._marca is not None and self._marca.scene() is not None:
            self.lienzo.escena.removeItem(self._marca)
        self._marca = None

    def _limpiar(self):
        for elemento in self._elementos:
            if elemento.scene() is not None:
                self.lienzo.escena.removeItem(elemento)
        self._elementos = []

    def _camino(self, puntos, cerrar=False) -> QPainterPath:
        camino = QPainterPath()
        if puntos:
            camino.addPolygon(QPolygonF([self.lienzo.a_escena(*p) for p in puntos]))
            if cerrar and len(puntos) > 2:
                camino.closeSubpath()
        return camino

    def _trazo(self, puntos, color=COLOR_DIBUJO, ancho=2.0, cerrar=False, estilo=Qt.PenStyle.SolidLine,
               relleno=None):
        elemento = QGraphicsPathItem(self._camino(puntos, cerrar))
        elemento.setPen(_pluma(color, ancho, estilo))
        if relleno:
            elemento.setBrush(QBrush(QColor(relleno)))
        elemento.setZValue(Z_DIBUJO)
        self.lienzo.escena.addItem(elemento)
        self._elementos.append(elemento)
        return elemento

    def _vertices(self, puntos, color=COLOR_DIBUJO, lado=7.0):
        for p in puntos:
            cuadro = QGraphicsRectItem(QRectF(-lado / 2, -lado / 2, lado, lado))
            cuadro.setPen(_pluma("#ffffff", 1))
            cuadro.setBrush(QBrush(QColor(color)))
            cuadro.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            cuadro.setPos(self.lienzo.a_escena(*p))
            cuadro.setZValue(Z_DIBUJO + 1)
            self.lienzo.escena.addItem(cuadro)
            self._elementos.append(cuadro)

    def _aplicar(self, funcion, *args, texto=""):
        try:
            datos = funcion(self.editor.datos(), *args)
        except ValueError as error:
            self.editor.mensaje(str(error))
            return False
        self.editor.aplicar(datos, texto)
        return True

    # ----------------------------------------------------- eventos (True = usado)

    def presionar(self, evento, x, y) -> bool:
        return False

    def mover(self, evento, x, y) -> bool:
        return False

    def soltar(self, evento, x, y) -> bool:
        return False

    def doble_clic(self, evento, x, y) -> bool:
        return False

    def tecla(self, evento) -> bool:
        if evento.key() == Qt.Key.Key_Escape:
            self.cancelar()
            self.editor.mensaje(self.ayuda())
            return True
        return False


# --------------------------------------------------------------------- dibujo


class HerramientaTrazo(Herramienta):
    """Polígono (lote) o polilínea (matriz) con clics."""

    cerrado = False
    minimo = 2
    que = ""

    def __init__(self, lienzo, editor):
        super().__init__(lienzo, editor)
        self.puntos: List[tuple] = []
        self.cursor_xy: Optional[tuple] = None

    def ayuda(self):
        if not self.puntos:
            return f"{self.que}: indique el primer punto."
        return (f"{self.que}: indique el siguiente punto ({len(self.puntos)} hasta ahora). Clic derecho, doble clic "
                "o Intro termina; Retroceso quita el último; Esc cancela. Mayús: sin imán.")

    def cancelar(self):
        self.puntos, self.cursor_xy = [], None
        super().cancelar()

    def redibujar(self):
        super().redibujar()
        self._pintar()

    def _pintar(self):
        self._limpiar()
        if not self.puntos:
            return
        puntos = self.puntos + ([self.cursor_xy] if self.cursor_xy else [])
        relleno = QColor(COLOR_DIBUJO)
        relleno.setAlpha(40)
        self._trazo(puntos, cerrar=self.cerrado, relleno=relleno if self.cerrado else None)
        self._vertices(self.puntos)

    def _imantar(self, evento, x, y):
        segmentos = list(zip(self.puntos, self.puntos[1:]))
        return self.imantar(evento, x, y, puntos_extra=self.puntos, segmentos_extra=segmentos)

    def presionar(self, evento, x, y):
        if evento.button() == Qt.MouseButton.LeftButton:
            p = self._imantar(evento, x, y)
            if not self.puntos or math.dist(p, self.puntos[-1]) > 1e-9:
                self.puntos.append(p)
            self._pintar()
            self.editor.mensaje(self.ayuda())
            return True
        if evento.button() == Qt.MouseButton.RightButton:
            self.terminar()
            return True
        return False

    def mover(self, evento, x, y):
        p = self._imantar(evento, x, y)
        if self.puntos:
            self.cursor_xy = p
            self._pintar()
        return False

    def doble_clic(self, evento, x, y):
        if evento.button() == Qt.MouseButton.LeftButton:
            self.terminar()
            return True
        return False

    def tecla(self, evento):
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.terminar()
            return True
        if evento.key() == Qt.Key.Key_Backspace and self.puntos:
            self.puntos.pop()
            self._pintar()
            self.editor.mensaje(self.ayuda())
            return True
        return super().tecla(evento)

    def terminar(self):
        puntos = [p for k, p in enumerate(self.puntos) if k == 0 or math.dist(p, self.puntos[k - 1]) > 1e-9]
        if self.cerrado and len(puntos) > 1 and math.dist(puntos[0], puntos[-1]) <= 1e-9:
            puntos.pop()
        if not puntos:
            return
        if len(puntos) < self.minimo:
            self.editor.mensaje(f"{self.que}: hacen falta al menos {self.minimo} puntos.")
            return
        self.cancelar()
        self._quitar_marca()
        self.crear(puntos)

    def crear(self, puntos):
        raise NotImplementedError


class HerramientaLote(HerramientaTrazo):
    nombre = "lote"
    cerrado = True
    minimo = 3
    que = "Lote"

    def crear(self, puntos):
        datos = self.editor.datos()
        if self._aplicar(edicion.agregar_lote, puntos, texto="Dibujar lote"):
            self.editor.editar_lote(len(datos.get("lotes", [])))


class HerramientaMatriz(HerramientaTrazo):
    nombre = "matriz"
    que = "Tubería matriz"

    def ayuda(self):
        texto = super().ayuda()
        if not self.puntos and not self.editor.datos().get("fuente"):
            texto += " Ubique antes la fuente de agua: la matriz debe salir de ella."
        elif not self.puntos and not edicion.matriz(self.editor.datos()):
            texto += " Empiece en la fuente de agua (el imán la toma)."
        return texto

    def crear(self, puntos):
        self._aplicar(edicion.agregar_matriz, puntos, texto="Dibujar tubería matriz")


class HerramientaFuente(Herramienta):
    nombre = "fuente"

    def ayuda(self):
        return "Fuente de agua: indique el punto de la bomba y el cabezal (reemplaza la fuente anterior)."

    def mover(self, evento, x, y):
        self.imantar(evento, x, y)
        return False

    def presionar(self, evento, x, y):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False
        p = self.imantar(evento, x, y)
        self._quitar_marca()
        self._aplicar(edicion.fijar_fuente, p, texto="Ubicar la fuente de agua")
        return True


class HerramientaInfo(Herramienta):
    nombre = "info"
    cursor = Qt.CursorShape.WhatsThisCursor

    def ayuda(self):
        return "Información del objeto: haga clic en un lote, una válvula, un tramo o la fuente."

    def presionar(self, evento, x, y):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False
        self.editor.mostrar_ficha(x, y, self.tolerancia)
        return True


# --------------------------------------------------------------------- selección


class HerramientaSeleccion(Herramienta):
    nombre = "seleccion"
    cursor = Qt.CursorShape.ArrowCursor
    arrastrar_mapa = True

    def __init__(self, lienzo, editor):
        super().__init__(lienzo, editor)
        self.seleccion: Optional[edicion.Objeto] = None
        self._arrastre = None  # (vértice, punto nuevo)

    def ayuda(self):
        if self.seleccion is None:
            return "Seleccionar: haga clic en un lote, un tramo de la matriz o la fuente. Arrastre para mover el mapa."
        return (f"Seleccionado: {edicion.nombre_objeto(self.editor.datos(), self.seleccion)}. Arrastre un vértice "
                "para moverlo; doble clic en un borde agrega un vértice; Ctrl + clic en un vértice lo quita; Supr "
                "borra; doble clic dentro de un lote abre su bloque de goteo.")

    def seleccionar(self, objeto):
        self.seleccion = objeto
        self._arrastre = None
        self._pintar()
        self.editor.mensaje(self.ayuda())
        if hasattr(self.editor, "seleccion_cambiada"):
            self.editor.seleccion_cambiada(objeto)

    def cancelar(self):
        self._arrastre = None
        super().cancelar()

    def desactivar(self):
        self.seleccion = None
        super().desactivar()

    def redibujar(self):
        super().redibujar()
        datos = self.editor.datos()
        if self.seleccion is not None:
            tipo, i = self.seleccion
            validos = {"dibujo": len(dibujos.lista(datos)), "lote": len(datos.get("lotes", [])), "matriz": len(edicion.matriz(datos)),
                       "fuente": 1 if datos.get("fuente") else 0}
            if i >= validos.get(tipo, i + 1):
                self.seleccion = None
        self._pintar()

    def _geometria(self, datos=None):
        datos = self.editor.datos() if datos is None else datos
        anillos = [list(a) for a in edicion.vertices(datos, self.seleccion)]
        if self._arrastre:
            (a, k), p = self._arrastre
            anillos[a][k] = p
        return anillos

    def _pintar(self):
        self._limpiar()
        if self.seleccion is None:
            return
        tipo = self.seleccion[0]
        anillos = self._geometria()
        if tipo == "dibujo":  # la figura (circunferencia, arco…) y sus puntos de control
            original = dibujos.lista(self.editor.datos())[self.seleccion[1]]
            puntos = anillos[0]
            if original["tipo"] == "circulo" and self._arrastre and self._arrastre[0][1] == 0:
                (cx, cy), (x0, y0) = puntos[0], original["puntos"][0]
                puntos = [puntos[0], (original["puntos"][1][0] + cx - x0, original["puntos"][1][1] + cy - y0)]
            self._trazo(dibujos.geometria({"tipo": original["tipo"], "puntos": puntos}), ancho=3.0)
            self._vertices(puntos)
            return
        for anillo in anillos:
            if tipo == "fuente":
                self._vertices(anillo, lado=12)
            else:
                self._trazo(anillo, ancho=3.0, cerrar=tipo == "lote")
                self._vertices(anillo)

    def presionar(self, evento, x, y):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False
        datos = self.editor.datos()
        if self.seleccion is not None:
            vertice = edicion.vertice_en(datos, self.seleccion, (x, y), self.tolerancia)
            if vertice is not None:
                if evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._aplicar(edicion.borrar_vertice, self.seleccion, vertice, texto="Quitar vértice")
                else:
                    self._arrastre = (vertice, edicion.vertices(datos, self.seleccion)[vertice[0]][vertice[1]])
                return True
        objeto = edicion.objeto_en(datos, (x, y), self.tolerancia)
        if objeto != self.seleccion:
            self.seleccionar(objeto)
        if objeto is not None and objeto[0] == "fuente":  # la fuente se arrastra directamente
            self._arrastre = ((0, 0), edicion.fuente(datos))
            return True
        return False  # arrastrar desde un lote o la matriz sigue desplazando el mapa

    def mover(self, evento, x, y):
        if not self._arrastre:
            return False
        datos = self.editor.datos()
        (a, k), _ = self._arrastre
        # El imán no debe tomar el propio vértice: se busca sin el objeto, más sus otros vértices
        otros = [p for j, anillo in enumerate(edicion.vertices(datos, self.seleccion)) for m, p in enumerate(anillo)
                 if (j, m) != (a, k)]
        p = self.imantar(evento, x, y, datos=edicion.borrar(datos, self.seleccion), puntos_extra=otros)
        self._arrastre = ((a, k), p)
        self._pintar()
        return True

    def soltar(self, evento, x, y):
        if not self._arrastre or evento.button() != Qt.MouseButton.LeftButton:
            return False
        vertice, p = self._arrastre
        self._arrastre = None
        self._quitar_marca()
        original = edicion.vertices(self.editor.datos(), self.seleccion)[vertice[0]][vertice[1]]
        if math.dist(original, p) > 1e-9:
            texto = "Mover la fuente" if self.seleccion[0] == "fuente" else "Mover vértice"
            self._aplicar(edicion.mover_vertice, self.seleccion, vertice, p, texto=texto)
        else:
            self._pintar()
        return True

    def doble_clic(self, evento, x, y):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False
        datos = self.editor.datos()
        if self.seleccion is not None and self.seleccion[0] != "fuente":
            borde = edicion.borde_en(datos, self.seleccion, (x, y), self.tolerancia)
            if borde is not None and edicion.vertice_en(datos, self.seleccion, (x, y), self.tolerancia) is None:
                anillo, k, p = borde
                self._aplicar(edicion.insertar_vertice, self.seleccion, anillo, k, p, texto="Agregar vértice")
                return True
        objeto = edicion.objeto_en(datos, (x, y), self.tolerancia)
        if objeto is not None and objeto[0] == "lote":
            self.editor.editar_lote(objeto[1])
            return True
        return False

    def tecla(self, evento):
        if evento.key() == Qt.Key.Key_Delete and self.seleccion is not None:
            objeto = self.seleccion
            texto = "Borrar " + edicion.nombre_objeto(self.editor.datos(), objeto)
            self.seleccion = None
            self._limpiar()
            self._aplicar(edicion.borrar, objeto, texto=texto)
            return True
        if evento.key() == Qt.Key.Key_Escape and self.seleccion is not None:
            self.seleccionar(None)
            return True
        return super().tecla(evento)


HERRAMIENTAS = [HerramientaSeleccion, HerramientaLote, HerramientaFuente, HerramientaMatriz, HerramientaInfo]
