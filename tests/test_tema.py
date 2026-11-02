# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Tema visual: contraste de las paletas, que no pise los colores de estado y turno, y su aplicación (requiere QGIS)."""

import re
import unittest
from unittest import mock

from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis

from riegolibre.gui import tema


def _luminancia(hexa):
    canales = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestPaletas(unittest.TestCase):
    def test_paletas_monocromaticas(self):
        for nombre, paleta in tema.PALETAS.items():
            for clave, color in paleta.items():
                r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                self.assertEqual(r, g, f"{nombre}/{clave} no es gris")
                self.assertEqual(g, b, f"{nombre}/{clave} no es gris")

    def test_alto_contraste(self):
        for nombre, p in tema.PALETAS.items():
            self.assertGreaterEqual(_contraste(p["texto"], p["fondo"]), 15, nombre)
            self.assertGreaterEqual(_contraste(p["texto"], p["superficie"]), 12, nombre)
            self.assertGreaterEqual(_contraste(p["suave"], p["fondo"]), 7, nombre)  # AAA
            self.assertGreaterEqual(_contraste(p["sobre_acento"], p["acento"]), 15, nombre)

    def test_la_hoja_no_toca_colores_de_estado_ni_turnos(self):
        for nombre in tema.PALETAS:
            hoja = tema.hoja_de_estilo(nombre, familia="Prueba")
            usados = set(re.findall(r"#[0-9a-fA-F]{6}", hoja))
            self.assertLessEqual(usados, set(tema.PALETAS[nombre].values()), nombre)
            self.assertNotIn("#2e7d32", hoja.lower())  # verde de «cumple»
            self.assertNotIn("#c62828", hoja.lower())  # rojo de «no cumple»

    def test_tema_qgis_no_agrega_estilo(self):
        self.assertEqual(tema.hoja_de_estilo("qgis"), "")

    def test_tema_desconocido(self):
        with self.assertRaises(ValueError):
            tema.hoja_de_estilo("neon")
        with self.assertRaises(ValueError):
            tema.cambiar_tema("neon")


class TestCobertura(unittest.TestCase):
    """Toda ventana (QDialog) de la carpeta gui debe tomar el tema; así las nuevas no se quedan sin él."""

    def test_todo_dialogo_llama_aplicar_tema(self):
        import ast
        import pathlib
        carpeta = pathlib.Path(tema.__file__).parent
        sin_tema = []
        for ruta in sorted(carpeta.glob("*.py")):
            for nodo in ast.parse(ruta.read_text(encoding="utf-8")).body:
                if isinstance(nodo, ast.ClassDef) and any(getattr(b, "id", "") == "QDialog" for b in nodo.bases):
                    if "aplicar_tema(self)" not in ast.get_source_segment(ruta.read_text(encoding="utf-8"), nodo):
                        sin_tema.append(f"{ruta.name}:{nodo.name}")
        self.assertEqual(sin_tema, [])

    def test_todo_lienzo_se_pinta_con_el_tema(self):
        import pathlib
        carpeta = pathlib.Path(tema.__file__).parent
        sin_pintar = []
        for ruta in sorted(carpeta.glob("*.py")):
            lineas = ruta.read_text(encoding="utf-8").splitlines()
            for i, linea in enumerate(lineas):
                if linea.strip() == "self.lienzo.draw()" and "pintar_figura" not in lineas[i - 1]:
                    sin_pintar.append(f"{ruta.name}:{i + 1}")
        self.assertEqual(sin_pintar, [])


@unittest.skipUnless(HAY_QGIS, "requiere QGIS")
class TestAplicacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def _con_tema(self, nombre):
        return mock.patch.object(tema, "tema_actual", return_value=nombre)

    def test_aplicar_y_cambiar(self):
        from qgis.PyQt.QtWidgets import QDialog
        ventana = QDialog()
        with self._con_tema("oscuro"):
            tema.aplicar_tema(ventana)
        self.assertIn(tema.PALETAS["oscuro"]["fondo"], ventana.styleSheet())
        with mock.patch("qgis.PyQt.QtCore.QSettings"):
            tema.cambiar_tema("claro")
            self.assertIn(tema.PALETAS["claro"]["fondo"], ventana.styleSheet())
            tema.cambiar_tema("qgis")
            self.assertEqual(ventana.styleSheet(), "")

    def test_un_estilo_propio_gana_al_del_tema(self):
        """La muestra de color de los turnos fija su fondo; el tema no se lo cambia."""
        from qgis.PyQt.QtGui import QColor
        from qgis.PyQt.QtWidgets import QDialog, QLabel, QVBoxLayout
        ventana = QDialog()
        muestra = QLabel("  ")
        muestra.setStyleSheet("background:#ff8800; border:1px solid #444;")
        QVBoxLayout(ventana).addWidget(muestra)
        with self._con_tema("oscuro"):
            tema.aplicar_tema(ventana)
        ventana.show()
        self.app.processEvents()
        color = muestra.grab().toImage().pixelColor(muestra.width() // 2, muestra.height() // 2)
        self.assertEqual(color.name(), QColor("#ff8800").name())
        ventana.close()

    def test_pintar_figura(self):
        try:
            from matplotlib.figure import Figure
        except ImportError:
            self.skipTest("sin matplotlib")
        figura = Figure()
        figura.add_subplot(111).plot([0, 1], [0, 1], color="#1e88e5")
        with self._con_tema("oscuro"):
            tema.pintar_figura(figura)
        self.assertEqual(figura.get_facecolor()[:3], (10 / 255, 10 / 255, 10 / 255))
        linea = figura.axes[0].lines[0]
        self.assertEqual(linea.get_color(), "#1e88e5")  # las series conservan su color


if __name__ == "__main__":
    unittest.main()
