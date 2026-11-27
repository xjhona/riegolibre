# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Herramientas de dibujo libre en la capa DIBUJO (el botón desplegable «Dibujo» de la barra vertical, como la
barra «Draw» de IRRICAD: Polyline, Line, Rectangle, Circle, Arc…). Lo dibujado no entra en el cálculo.

- Polilínea y polígono: clics en los vértices; clic derecho, doble clic o Intro termina (como el lote).
- Línea: dos clics. Rectángulo: dos esquinas opuestas. Circunferencia: centro y un punto de ella.
- Arco: inicio, un punto intermedio y fin.

Todas usan el imán (Mayús: sin imán) y se editan luego con «Seleccionar» (ver `dibujos.py`).
"""

import math
from typing import List, Optional

from PySide6.QtCore import Qt

from . import dibujos
from .herramientas import COLOR_DIBUJO, Herramienta, HerramientaTrazo


class HerramientaPolilinea(HerramientaTrazo):
    nombre = "dibujo_polilinea"
    tipo = "polilinea"
    que = "Polilínea"

    def crear(self, puntos):
        self._aplicar(dibujos.agregar, self.tipo, puntos, texto=f"Dibujar {dibujos.TIPOS[self.tipo]}")


class HerramientaPoligono(HerramientaPolilinea):
    nombre = "dibujo_poligono"
    tipo = "poligono"
    que = "Polígono"
    cerrado = True
    minimo = 3


class HerramientaPuntosFijos(Herramienta):
    """Figuras de un número fijo de clics; entre clic y clic se ve cómo queda con el cursor."""

    tipo = ""
    pasos: List[str] = []  # qué pide cada clic

    def __init__(self, lienzo, editor):
        super().__init__(lienzo, editor)
        self.puntos: List[tuple] = []
        self.cursor_xy: Optional[tuple] = None

    def ayuda(self):
        nombre = dibujos.TIPOS[self.tipo].capitalize()
        return f"{nombre}: indique {self.pasos[len(self.puntos)]}. Esc cancela; Mayús: sin imán."

    def cancelar(self):
        self.puntos, self.cursor_xy = [], None
        super().cancelar()

    def redibujar(self):
        super().redibujar()
        self._pintar()

    def _figura(self, puntos) -> List[tuple]:
        """La línea provisional con los puntos dados (el último puede ser el cursor)."""
        if self.tipo == "rectangulo" and len(puntos) == 2:
            esquinas = dibujos.esquinas_rectangulo(*puntos)
            return esquinas + [esquinas[0]]
        if self.tipo == "arco" and len(puntos) == 2:
            return puntos
        return dibujos.geometria({"tipo": self.tipo, "puntos": puntos})

    def _pintar(self):
        self._limpiar()
        if not self.puntos:
            return
        puntos = self.puntos + ([self.cursor_xy] if self.cursor_xy else [])
        if len(puntos) >= 2:
            self._trazo(self._figura(puntos))
            if self.tipo == "circulo":  # el radio
                self._trazo(puntos[:2], ancho=1.0, estilo=Qt.PenStyle.DashLine)
        self._vertices(self.puntos)

    def _imantar(self, evento, x, y):
        return self.imantar(evento, x, y, puntos_extra=self.puntos)

    def presionar(self, evento, x, y):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False  # el clic derecho abre el menú del mapa
        p = self._imantar(evento, x, y)
        if self.puntos and math.dist(p, self.puntos[-1]) <= 1e-9:
            return True
        self.puntos.append(p)
        if len(self.puntos) < len(self.pasos):
            self._pintar()
            self.editor.mensaje(self.ayuda())
            return True
        puntos = self.puntos
        self.cancelar()
        self._quitar_marca()
        if self._aplicar(dibujos.agregar, self.tipo, puntos, texto=f"Dibujar {dibujos.TIPOS[self.tipo]}"):
            self.editor.mensaje(self.ayuda())
        return True

    def mover(self, evento, x, y):
        p = self._imantar(evento, x, y)
        if self.puntos:
            self.cursor_xy = p
            self._pintar()
            if self.tipo == "circulo":
                self.editor.mensaje(f"{self.ayuda()}  Radio: {math.dist(self.puntos[0], p):.2f} m")
        return False

    def tecla(self, evento):
        if evento.key() == Qt.Key.Key_Backspace and self.puntos:
            self.puntos.pop()
            self._pintar()
            self.editor.mensaje(self.ayuda())
            return True
        return super().tecla(evento)


class HerramientaLinea(HerramientaPuntosFijos):
    nombre = "dibujo_linea"
    tipo = "linea"
    pasos = ["el primer punto", "el punto final"]


class HerramientaRectangulo(HerramientaPuntosFijos):
    nombre = "dibujo_rectangulo"
    tipo = "rectangulo"
    pasos = ["una esquina", "la esquina opuesta"]


class HerramientaCirculo(HerramientaPuntosFijos):
    nombre = "dibujo_circulo"
    tipo = "circulo"
    pasos = ["el centro", "un punto de la circunferencia (da el radio)"]


class HerramientaArco(HerramientaPuntosFijos):
    nombre = "dibujo_arco"
    tipo = "arco"
    pasos = ["el inicio del arco", "un punto intermedio", "el final del arco"]


# (clase, texto del menú, ayuda)
HERRAMIENTAS_DIBUJO = [
    (HerramientaPolilinea, "⌇  Polilínea", "Dibujar una polilínea en la capa DIBUJO: clics en sus vértices"),
    (HerramientaLinea, "╱  Línea", "Dibujar una línea recta en la capa DIBUJO: dos clics"),
    (HerramientaPoligono, "⬠  Polígono", "Dibujar un polígono cerrado en la capa DIBUJO: clics en sus vértices"),
    (HerramientaRectangulo, "▭  Rectángulo", "Dibujar un rectángulo en la capa DIBUJO: dos esquinas opuestas"),
    (HerramientaCirculo, "◯  Circunferencia", "Dibujar una circunferencia en la capa DIBUJO: centro y radio"),
    (HerramientaArco, "◠  Arco", "Dibujar un arco en la capa DIBUJO: inicio, punto intermedio y final"),
]
