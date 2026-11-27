# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Rendimiento del lienzo del programa de escritorio: curvas de nivel simplificadas según el zoom, partidas en
tramos (solo se pintan las que se ven) y en borrador mientras se hace zoom."""

import math
import os
import sys
import unittest

try:
    import numpy as np
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules
except ImportError:
    HAY_PYSIDE = False


def distancia_a_polilinea(p, linea):
    a, b = linea[:-1], linea[1:]
    ab = b - a
    largo2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
    t = np.clip(((p - a) * ab).sum(axis=1) / largo2, 0, 1)
    return float(np.min(np.hypot(*(a + t[:, None] * ab - p).T)))


@unittest.skipUnless(HAY_PYSIDE, "requiere PySide6 y numpy (Python normal, no el de QGIS)")
class PruebasCurvasRapidas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def circulo(self, radio=100.0, n=4000):
        t = np.linspace(0, 2 * math.pi, n)
        return np.column_stack((radio * np.cos(t), radio * np.sin(t)))

    def test_simplificar_respeta_la_tolerancia(self):
        from riegolibre_escritorio.lienzo import simplificar

        linea = self.circulo()
        for tolerancia in (0.5, 2.0, 8.0):
            corta = simplificar(linea, tolerancia)
            self.assertLess(len(corta), len(linea))
            self.assertTrue(np.array_equal(corta[0], linea[0]) and np.array_equal(corta[-1], linea[-1]))
            # Cada vértice original queda a menos de la diagonal de una celda de la polilínea simplificada
            peor = max(distancia_a_polilinea(p, corta) for p in linea[::37])
            self.assertLessEqual(peor, tolerancia * math.sqrt(2))
        self.assertIs(simplificar(linea, 0.0), linea)

    def test_poligono_de_copia_los_vertices(self):
        from riegolibre_escritorio.lienzo import poligono_de

        linea = self.circulo(n=1001)
        poligono = poligono_de(linea)
        self.assertEqual(poligono.size(), 1001)
        for i in (0, 500, 1000):
            self.assertAlmostEqual(poligono.at(i).x(), linea[i, 0])
            self.assertAlmostEqual(poligono.at(i).y(), linea[i, 1])

    def test_nivel_de_detalle_segun_zoom(self):
        from riegolibre_escritorio.lienzo import TOLERANCIA_PX, TOLERANCIAS_M, ElementoCurvas

        self.assertEqual(ElementoCurvas.nivel_para(100.0), 0)  # muy cerca: la curva original
        anterior = 0
        for pixeles_por_metro in (4.0, 1.0, 0.25, 0.05):
            nivel = ElementoCurvas.nivel_para(pixeles_por_metro)
            self.assertGreaterEqual(nivel, anterior)  # más lejos, más simplificada
            self.assertLessEqual(TOLERANCIAS_M[nivel] * pixeles_por_metro, TOLERANCIA_PX)
            anterior = nivel
        self.assertGreater(anterior, 0)

    def test_tramos_y_cota_bajo_el_raton(self):
        from PySide6.QtGui import QPen

        from riegolibre_escritorio.lienzo import VERTICES_TRAMO, ElementoCurvas

        curvas = [(100.0 + i, i % 5 == 0, self.circulo(100.0 + 10 * i)) for i in range(3)]
        elemento = ElementoCurvas(curvas, QPen(), QPen())
        self.assertEqual(len(elemento.cotas), 3)
        self.assertGreater(len(elemento.tramos), 3 * (4000 // VERTICES_TRAMO))
        # Los tramos de cada curva, unidos, son la curva entera (comparten el vértice de unión)
        primera = [t for t, c in zip(elemento.tramos, elemento.curva_de) if c == 0]
        self.assertEqual(sum(len(t) for t in primera) - (len(primera) - 1), 4000)
        self.assertEqual(elemento.cota_cerca(0.0, 110.5, 2.0), (101.0, False))
        self.assertEqual(elemento.cota_cerca(-99.0, 0.0, 2.0), (100.0, True))
        self.assertIsNone(elemento.cota_cerca(0.0, 105.0, 2.0))
        self.assertGreaterEqual(elemento.boundingRect().width(), 240.0)

    def test_borrador_mientras_se_hace_zoom(self):
        from riegolibre_escritorio.capas import estilos_por_omision
        from riegolibre_escritorio.lienzo import ElementoCurvas, Lienzo, dibujar_curvas

        lienzo = Lienzo()
        self.addCleanup(lienzo.deleteLater)
        lienzo.resize(400, 300)
        estilos = estilos_por_omision()
        capa = lienzo.nueva_capa("CURVAS_NIVEL", estilos["CURVAS_NIVEL"])
        dibujar_curvas(lienzo, capa, [(100.0 + i, [tuple(p) for p in self.circulo(50.0 + 5 * i, 500)])
                                      for i in range(6)])
        elemento = capa.elementos[0]
        self.assertIsInstance(elemento, ElementoCurvas)
        self.assertEqual(elemento.plumas[1].widthF(), 2 * elemento.plumas[0].widthF())  # maestra (100 m) al doble
        self.assertLessEqual(elemento.plumas_borrador[1].widthF(), 1.0)
        lienzo.ver_todo()
        self.assertFalse(elemento.borrador)
        lienzo.alejar()
        self.assertTrue(elemento.borrador)
        self.assertTrue(lienzo._fin_zoom.isActive())
        lienzo.viewport().grab()  # pinta en borrador sin fallar
        lienzo._fin_zoom.timeout.emit()
        self.assertFalse(elemento.borrador)
        self.assertFalse(lienzo.viewport().grab().isNull())


if __name__ == "__main__":
    unittest.main()
