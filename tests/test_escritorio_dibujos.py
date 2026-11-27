# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Dibujo libre en la capa DIBUJO del programa de escritorio: geometría, cambios con deshacer, selección e imán,
y en la ventana el botón desplegable de figuras."""

import math
import os
import unittest
from unittest import mock

from riegolibre_escritorio import dibujos, edicion, fichas
from riegolibre_escritorio.capas import CAPAS
from riegolibre_escritorio.modelo import ProyectoRiego
from tests.test_escritorio import X0, Y0, datos_prueba
from tests.test_escritorio_edicion import HAY_PYSIDE


class PruebasGeometria(unittest.TestCase):
    def test_circulo_por_tres_puntos(self):
        (cx, cy), r = dibujos.circulo_por_tres((0, 0), (10, 0), (5, 5))
        self.assertAlmostEqual(cx, 5)
        self.assertAlmostEqual(cy, 0)
        self.assertAlmostEqual(r, 5)
        self.assertIsNone(dibujos.circulo_por_tres((0, 0), (1, 1), (2, 2)))

    def test_arco_sigue_el_punto_intermedio(self):
        # Semicircunferencia superior (antihoraria de (10,0) a (-10,0)) y la inferior (horaria)
        for medio, signo in (((0, 10), 1), ((0, -10), -1)):
            centro, r, inicio, barrido = dibujos.barrido_arco((10, 0), medio, (-10, 0))
            self.assertAlmostEqual(r, 10)
            self.assertAlmostEqual(barrido, signo * math.pi)
            geom = dibujos.geometria({"tipo": "arco", "puntos": [(10, 0), medio, (-10, 0)]})
            self.assertAlmostEqual(geom[0][0], 10)
            self.assertAlmostEqual(geom[-1][0], -10)
            self.assertTrue(all(abs(math.dist(p, centro) - 10) < 1e-9 for p in geom))
            self.assertTrue(all(signo * p[1] >= -1e-9 for p in geom))
        # Arco de 270°: el punto intermedio queda del lado largo
        _c, _r, _i, barrido = dibujos.barrido_arco((10, 0), (-10, 0), (0, -10))
        self.assertAlmostEqual(barrido, 1.5 * math.pi)

    def test_medidas(self):
        circulo = {"tipo": "circulo", "puntos": [(0, 0), (3, 4)]}
        medidas = dict(dibujos.medidas(circulo))
        self.assertEqual(medidas["Radio"], "5.00 m")
        self.assertEqual(medidas["Área"], f"{math.pi * 25:.2f} m²")
        geom = dibujos.geometria(circulo)
        largo = sum(math.dist(a, b) for a, b in zip(geom, geom[1:]))
        self.assertAlmostEqual(largo, 2 * math.pi * 5, delta=0.05)  # 72 lados
        rect = dict(dibujos.medidas({"tipo": "rectangulo", "puntos": dibujos.esquinas_rectangulo((0, 0), (20, 10))}))
        self.assertEqual(rect["Perímetro"], "60.00 m")
        self.assertEqual(rect["Área"], "200.00 m²")


class PruebasCambios(unittest.TestCase):
    def test_agregar_cada_figura(self):
        datos = {}
        datos = dibujos.agregar(datos, "polilinea", [(0, 0), (10, 0), (10, 10)])
        datos = dibujos.agregar(datos, "linea", [(0, 0), (5, 5)])
        datos = dibujos.agregar(datos, "poligono", [(0, 0), (10, 0), (10, 10), (0, 0)])  # el cierre se quita
        datos = dibujos.agregar(datos, "rectangulo", [(0, 0), (20, 10)])
        datos = dibujos.agregar(datos, "circulo", [(50, 50), (55, 50)])
        datos = dibujos.agregar(datos, "arco", [(10, 0), (0, 10), (-10, 0)])
        tipos = [e["tipo"] for e in datos["dibujos"]]
        self.assertEqual(tipos, ["polilinea", "linea", "poligono", "rectangulo", "circulo", "arco"])
        self.assertEqual(len(datos["dibujos"][2]["puntos"]), 3)
        self.assertEqual(datos["dibujos"][3]["puntos"], [[0, 0], [20, 0], [20, 10], [0, 10]])

    def test_figuras_invalidas(self):
        for tipo, puntos in (("circulo", [(1, 1), (1, 1)]), ("arco", [(0, 0), (1, 1), (2, 2)]),
                             ("rectangulo", [(0, 0), (5, 0)]), ("poligono", [(0, 0), (1, 0), (2, 0)]),
                             ("polilinea", [(0, 0)]), ("linea", [(3, 3), (3, 3)])):
            with self.subTest(tipo=tipo), self.assertRaises(ValueError):
                dibujos.agregar({}, tipo, puntos)

    def test_editar_con_las_funciones_de_edicion(self):
        datos = dibujos.agregar(datos_prueba(), "circulo", [(X0 + 200, Y0), (X0 + 210, Y0)])
        datos = dibujos.agregar(datos, "polilinea", [(X0 + 300, Y0), (X0 + 320, Y0)])
        circulo, linea = ("dibujo", 0), ("dibujo", 1)
        self.assertEqual(edicion.nombre_objeto(datos, circulo), "circunferencia 1 del dibujo")
        # Clic sobre la circunferencia (no en el centro) la encuentra; dentro, lejos del trazo, no
        self.assertEqual(edicion.objeto_en(datos, (X0 + 200, Y0 + 10.2), 0.5), circulo)
        self.assertIsNone(edicion.objeto_en(datos, (X0 + 202, Y0 + 1), 0.5))
        # Mover el centro arrastra la figura; mover el otro punto cambia el radio
        movido = edicion.mover_vertice(datos, circulo, (0, 0), (X0 + 205, Y0 + 5))
        self.assertEqual(movido["dibujos"][0]["puntos"], [[X0 + 205, Y0 + 5], [X0 + 215, Y0 + 5]])
        radio = edicion.mover_vertice(datos, circulo, (0, 1), (X0 + 200, Y0 + 20))
        self.assertEqual(dict(dibujos.medidas(dibujos.lista(radio)[0]))["Radio"], "20.00 m")
        # Polilínea: agregar y quitar vértices; no menos de dos
        borde = edicion.borde_en(datos, linea, (X0 + 310, Y0 + 0.1), 0.5)
        self.assertEqual(borde[:2], (0, 0))
        con_tres = edicion.insertar_vertice(datos, linea, 0, 0, (X0 + 310, Y0 + 5))
        self.assertEqual(len(con_tres["dibujos"][1]["puntos"]), 3)
        self.assertEqual(len(edicion.borrar_vertice(con_tres, linea, (0, 1))["dibujos"][1]["puntos"]), 2)
        with self.assertRaises(ValueError):
            edicion.borrar_vertice(datos, linea, (0, 0))
        with self.assertRaises(ValueError):
            edicion.borrar_vertice(datos, circulo, (0, 0))
        self.assertIsNone(edicion.borde_en(datos, circulo, (X0 + 210, Y0), 0.5))
        # Borrar
        sin_circulo = edicion.borrar(datos, circulo)
        self.assertEqual([e["tipo"] for e in sin_circulo["dibujos"]], ["polilinea"])
        self.assertNotIn("dibujos", edicion.borrar(sin_circulo, ("dibujo", 0)))
        # Los lotes no cambian
        self.assertEqual(sin_circulo["lotes"], datos["lotes"])

    def test_rectangulo_editado_pasa_a_poligono(self):
        datos = dibujos.agregar({}, "rectangulo", [(0, 0), (20, 10)])
        movido = edicion.mover_vertice(datos, ("dibujo", 0), (0, 2), (25, 15))
        self.assertEqual(movido["dibujos"][0]["tipo"], "poligono")

    def test_iman_y_seleccion_con_lote_debajo(self):
        datos = datos_prueba()
        lote = datos["lotes"][0]["contorno"]
        xs, ys = [p[0] for p in lote], [p[1] for p in lote]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        self.assertEqual(edicion.objeto_en(datos, (cx, cy), 0.5)[0], "lote")
        # Una línea dibujada dentro del lote se elige antes que el lote
        datos = dibujos.agregar(datos, "linea", [(cx - 5, cy), (cx + 5, cy)])
        self.assertEqual(edicion.objeto_en(datos, (cx, cy + 0.2), 0.5), ("dibujo", 0))
        self.assertEqual(edicion.objeto_en(datos, (cx, cy + 3), 0.5)[0], "lote")
        # El imán se pega a sus vértices
        p, tipo = edicion.imantar((cx + 5.3, cy + 0.2), datos, 1.0)
        self.assertEqual((p, tipo), ((cx + 5, cy), edicion.VERTICE))

    def test_proyecto_capa_ficha_y_extension(self):
        self.assertIn("DIBUJO", CAPAS)
        datos = dibujos.agregar(datos_prueba(), "circulo", [(X0 + 1000, Y0), (X0 + 1010, Y0)])
        proyecto = ProyectoRiego(datos)
        self.assertGreaterEqual(proyecto.extension()[2], X0 + 1010 - 1e-6)
        ficha = fichas.ficha_en(proyecto, (X0 + 1010, Y0), 0.5)
        self.assertEqual(ficha.titulo, "Circunferencia 1 del dibujo")
        self.assertIn("Radio: 10.00 m", ficha.texto)


@unittest.skipUnless(HAY_PYSIDE, "requiere PySide6 (Python normal, no el de QGIS)")
class PruebasVentanaDibujo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from riegolibre_escritorio import ventana
        parche = mock.patch.object(ventana, "QMessageBox")
        parche.start()
        self.addCleanup(parche.stop)
        self.v = ventana.VentanaPrincipal()
        self.v.resize(1000, 700)
        self.v.show()
        self.addCleanup(self.v.deleteLater)
        self.v.nuevo({"nombre": "Dibujo", "epsg": 32717, "terreno": None, "referencia": (X0, Y0)})
        lienzo = self.v.lienzo
        lienzo.resetTransform()
        lienzo.scale(2, 2)
        lienzo.centerOn(lienzo.a_escena(X0, Y0))
        self.app.processEvents()

    def clic(self, x, y):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        punto = self.v.lienzo.mapFromScene(self.v.lienzo.a_escena(x, y))
        QTest.mouseClick(self.v.lienzo.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, punto)

    def test_boton_desplegable_y_figuras(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        v = self.v
        boton = v.boton_dibujo
        nombres = [a.text() for a in boton.menu().actions()]
        self.assertEqual(len(nombres), 6)
        self.assertIn("Polilínea", boton.defaultAction().text())
        # Circunferencia desde el menú del botón: el botón pasa a mostrarla
        circulo = next(a for a in boton.menu().actions() if "Circunferencia" in a.text())
        circulo.trigger()
        self.assertIs(boton.defaultAction(), circulo)
        self.assertTrue(circulo.isChecked())
        self.clic(X0, Y0)
        self.clic(X0 + 30, Y0)
        self.assertEqual(dibujos.lista(v.proyecto.datos)[0]["tipo"], "circulo")
        self.assertAlmostEqual(math.dist(*dibujos.lista(v.proyecto.datos)[0]["puntos"]), 30, delta=1)
        # Polilínea con Intro
        v.usar_herramienta("dibujo_polilinea")
        for p in ((X0 - 80, Y0 + 60), (X0 - 40, Y0 + 70), (X0 - 10, Y0 + 90)):
            self.clic(*p)
        QTest.keyClick(v.lienzo, Qt.Key.Key_Return)
        self.assertEqual([e["tipo"] for e in dibujos.lista(v.proyecto.datos)], ["circulo", "polilinea"])
        self.assertEqual(len(v.lienzo.capas["DIBUJO"].elementos), 2)
        # Deshacer quita la polilínea
        v.deshacer()
        self.assertEqual(len(dibujos.lista(v.proyecto.datos)), 1)
        # Seleccionar la circunferencia y borrarla con Supr
        v.usar_herramienta("seleccion")
        self.clic(X0 - 30, Y0)
        self.assertEqual(v.seleccion, ("dibujo", 0))
        QTest.keyClick(v.lienzo, Qt.Key.Key_Delete)
        self.assertNotIn("dibujos", v.proyecto.datos)


if __name__ == "__main__":
    unittest.main()
