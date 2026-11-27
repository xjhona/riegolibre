# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Edición en el mapa del programa de escritorio (etapa 2): imán, cambios en los datos, caché de lotes,
fichas de información, y en la ventana: dibujar un proyecto desde cero con las herramientas, deshacer,
bloque de goteo por lote, turnos, guardar y abrir.
"""

import copy
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

from mcp_riegolibre import motor
from riegolibre_escritorio import archivo, edicion, fichas
from riegolibre_escritorio.edicion import epsg_utm, zona_de_epsg
from riegolibre_escritorio.modelo import ProyectoRiego
from tests.test_escritorio import GOTEO, X0, Y0, datos_prueba, rectangulo

try:
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules
except ImportError:
    HAY_PYSIDE = False


class PruebasEdicion(unittest.TestCase):
    def test_imantar_vertice_antes_que_borde(self):
        datos = datos_prueba()
        # Cerca de la esquina del lote A: vértice
        p, tipo = edicion.imantar((X0 + 0.3, Y0 - 0.2), datos, 1.0)
        self.assertEqual(tipo, edicion.VERTICE)
        self.assertEqual(p, (X0, Y0))
        # Cerca del borde inferior de A, lejos de vértices: punto sobre el borde
        p, tipo = edicion.imantar((X0 + 30, Y0 + 0.4), datos, 1.0)
        self.assertEqual(tipo, edicion.BORDE)
        self.assertAlmostEqual(p[1], Y0)
        self.assertAlmostEqual(p[0], X0 + 30)
        # La fuente y la matriz también atraen
        self.assertEqual(edicion.imantar((X0 - 20.5, Y0 - 19.6), datos, 1.0), ((X0 - 20, Y0 - 20), edicion.VERTICE))
        p, tipo = edicion.imantar((X0 + 100, Y0 + 40.3), datos, 1.0)
        self.assertEqual((tipo, round(p[1], 6)), (edicion.BORDE, Y0 + 40))
        # Lejos de todo: no cambia
        self.assertEqual(edicion.imantar((X0 + 30, Y0 + 15), datos, 1.0), ((X0 + 30, Y0 + 15), None))
        # Puntos propios del trazo en curso
        self.assertEqual(edicion.imantar((5.2, 5), {}, 1.0, puntos_extra=[(5, 5)]), ((5, 5), edicion.VERTICE))

    def test_objeto_en(self):
        datos = datos_prueba()
        self.assertEqual(edicion.objeto_en(datos, (X0 - 20.3, Y0 - 20), 1.0), ("fuente", 0))
        self.assertEqual(edicion.objeto_en(datos, (X0 - 20.3, Y0 + 10), 1.0), ("matriz", 0))
        self.assertEqual(edicion.objeto_en(datos, (X0 + 80, Y0 + 15), 1.0), ("lote", 1))
        self.assertIsNone(edicion.objeto_en(datos, (X0 + 65, Y0 + 15), 1.0))
        # Lote dentro de otro: gana el más pequeño; un hueco no es del lote
        datos["lotes"].append({"nombre": "Grande", "contorno": rectangulo(-10, -10, 300, 45),
                               "huecos": [rectangulo(200, 0, 10, 10)]})
        self.assertEqual(edicion.objeto_en(datos, (X0 + 80, Y0 + 15), 1.0), ("lote", 1))
        self.assertEqual(edicion.objeto_en(datos, (X0 + 195, Y0 + 15), 1.0), ("lote", 3))
        self.assertIsNone(edicion.objeto_en(datos, (X0 + 205, Y0 + 5), 1.0))

    def test_cambios_devuelven_copias(self):
        datos = datos_prueba()
        original = copy.deepcopy(datos)
        nuevo = edicion.agregar_lote(datos, rectangulo(0, 50, 20, 20))
        self.assertEqual(datos, original)
        self.assertEqual(nuevo["lotes"][-1]["nombre"], "Lote 1")
        self.assertEqual(edicion.nombre_libre(nuevo), "Lote 2")
        with self.assertRaisesRegex(ValueError, "Ya hay"):
            edicion.agregar_lote(datos, rectangulo(0, 50, 20, 20), "A")
        with self.assertRaisesRegex(ValueError, "tres"):
            edicion.agregar_lote(datos, [(0, 0), (1, 1), (2, 2)])

        nuevo = edicion.fijar_fuente(datos, (X0 + 1, Y0 + 2))
        self.assertEqual(nuevo["fuente"], [X0 + 1, Y0 + 2])
        nuevo = edicion.agregar_matriz(datos, [(X0, Y0), (X0, Y0), (X0 + 5, Y0)])
        self.assertEqual(nuevo["red"]["matriz"][-1], [[X0, Y0], [X0 + 5, Y0]])
        with self.assertRaisesRegex(ValueError, "dos puntos"):
            edicion.agregar_matriz(datos, [(X0, Y0), (X0, Y0)])

        nuevo = edicion.mover_vertice(datos, ("lote", 0), (0, 2), (X0 + 70, Y0 + 40))
        self.assertEqual(nuevo["lotes"][0]["contorno"][2], [X0 + 70, Y0 + 40])
        nuevo = edicion.mover_vertice(datos, ("matriz", 0), (0, 1), (X0, Y0 + 50))
        self.assertEqual(nuevo["red"]["matriz"][0][1], [X0, Y0 + 50])
        nuevo = edicion.insertar_vertice(datos, ("lote", 0), 0, 0, (X0 + 30, Y0 - 5))
        self.assertEqual(len(nuevo["lotes"][0]["contorno"]), 5)
        self.assertEqual(nuevo["lotes"][0]["contorno"][1], [X0 + 30, Y0 - 5])
        self.assertEqual(len(edicion.borrar_vertice(nuevo, ("lote", 0), (0, 1))["lotes"][0]["contorno"]), 4)
        with self.assertRaisesRegex(ValueError, "menos de 3"):
            edicion.borrar_vertice(edicion.borrar_vertice(datos, ("lote", 0), (0, 0)), ("lote", 0), (0, 0))
        self.assertNotIn("fuente", edicion.borrar(datos, ("fuente", 0)))
        self.assertNotIn("matriz", edicion.borrar(edicion.borrar(datos, ("matriz", 0)), ("matriz", 0))["red"])
        self.assertEqual([l["nombre"] for l in edicion.borrar(datos, ("lote", 1))["lotes"]], ["A", "C"])
        self.assertEqual(datos, original)

    def test_matriz_en_tramos_y_nodos(self):
        """Como IRRICAD: un tramo por cada par de clics y un nodo en cada extremo, compartido entre tramos."""
        a, b, c, d, e = (X0, Y0), (X0 + 10, Y0), (X0 + 20, Y0 + 5), (X0 + 30, Y0 + 5), (X0 + 45, Y0)
        datos = edicion.agregar_matriz({}, [a, b, c, d, e])  # 5 clics: 4 tramos y 5 nodos
        self.assertEqual(edicion.matriz(datos), [[a, b], [b, c], [c, d], [d, e]])
        self.assertEqual(edicion.nodos_matriz(datos), [a, b, c, d, e])
        self.assertEqual(datos["red"]["matriz"][1], [list(b), list(c)])
        # Una polilínea del MCP se lee en tramos
        self.assertEqual(edicion.matriz({"red": {"matriz": [[a, b, c]]}}), [[a, b], [b, c]])

        # Un ramal que empieza sobre el medio de un tramo lo parte: nodo compartido (una T)
        medio = (X0 + 5, Y0)
        t = edicion.agregar_matriz(datos, [medio, (X0 + 5, Y0 - 30)])
        self.assertEqual(len(edicion.matriz(t)), 6)
        self.assertEqual(len(edicion.tramos_en_nodo(edicion.matriz(t), medio)), 3)
        with self.assertRaisesRegex(ValueError, "une 3 tramos"):
            edicion.quitar_nodo(t, medio)

        # Mover un nodo arrastra los dos tramos que llegan a él
        nuevo = edicion.mover_vertice(datos, ("nodo", 2), (0, 0), (X0 + 20, Y0 + 9))
        self.assertEqual(edicion.matriz(nuevo)[1][1], (X0 + 20, Y0 + 9))
        self.assertEqual(edicion.matriz(nuevo)[2][0], (X0 + 20, Y0 + 9))
        nuevo = edicion.mover_vertice(datos, ("matriz", 0), (0, 1), (X0 + 10, Y0 + 2))  # extremo de un tramo
        self.assertEqual(edicion.matriz(nuevo)[1][0], (X0 + 10, Y0 + 2))
        # El imán no toma el nodo que se mueve, pero sí los otros extremos de sus tramos
        sin, otros = edicion.datos_para_iman(datos, ("nodo", 2), (0, 0))
        self.assertEqual(sorted(otros), sorted([b, d]))
        self.assertNotIn(c, edicion.nodos_matriz(sin))

        # Partir un tramo agrega un nodo; quitarlo une los dos tramos
        q = (X0 + 37.5, Y0 + 2.5)
        partido = edicion.insertar_vertice(datos, ("matriz", 3), 0, 0, q)
        self.assertEqual(edicion.matriz(partido)[3:], [[d, q], [q, e]])
        self.assertEqual(edicion.matriz(edicion.quitar_nodo(partido, q)), edicion.matriz(datos))
        unido = edicion.borrar(datos, ("nodo", 1))
        self.assertEqual(edicion.matriz(unido), [[a, c], [c, d], [d, e]])
        # Quitar un extremo suelto borra su tramo; Ctrl + clic en el extremo de un tramo quita ese nodo
        self.assertEqual(edicion.matriz(edicion.borrar(datos, ("nodo", 0))), [[b, c], [c, d], [d, e]])
        self.assertEqual(edicion.borrar_vertice(datos, ("matriz", 0), (0, 1)), unido)
        # Clic: el nodo antes que el tramo
        self.assertEqual(edicion.objeto_en(datos, (X0 + 10.2, Y0), 1.0), ("nodo", 1))
        self.assertEqual(edicion.objeto_en(datos, (X0 + 5, Y0 + 0.3), 1.0), ("matriz", 0))

    def test_lote_con_anillos_se_normaliza_al_editar(self):
        datos = {"lotes": [{"nombre": "X", "anillos": [rectangulo(0, 0, 10, 10) + [rectangulo(0, 0, 10, 10)[0]]]}]}
        nuevo = edicion.mover_vertice(datos, ("lote", 0), (0, 1), (X0 + 12, Y0))
        self.assertNotIn("anillos", nuevo["lotes"][0])
        self.assertEqual(len(nuevo["lotes"][0]["contorno"]), 4)
        self.assertEqual(nuevo["lotes"][0]["contorno"][1], [X0 + 12, Y0])

    def test_cambiar_lote_nombre_turno_y_parametros(self):
        datos = edicion.fijar_turnos(datos_prueba(), 2, {"A": 2})
        nuevo = edicion.cambiar_lote(datos, 0, {"nombre": "A1", "turno": 1, "portalateral": "final",
                                                "valvula": None})
        lote = nuevo["lotes"][0]
        self.assertEqual(lote["nombre"], "A1")
        self.assertEqual(lote["portalateral"], "final")
        self.assertEqual(nuevo["red"]["turnos_fijos"], {"A1": 1})
        nuevo = edicion.cambiar_lote(nuevo, 0, {"turno": None})
        self.assertNotIn("turnos_fijos", nuevo["red"])
        with self.assertRaisesRegex(ValueError, "Ya hay"):
            edicion.cambiar_lote(datos, 0, {"nombre": "B"})
        with self.assertRaisesRegex(ValueError, "nombre"):
            edicion.cambiar_lote(datos, 0, {"nombre": "  "})
        # Borrar un lote quita su turno fijo
        self.assertNotIn("turnos_fijos", edicion.borrar(datos, ("lote", 0))["red"])
        with self.assertRaisesRegex(ValueError, "fuera de rango"):
            edicion.fijar_turnos(datos, 2, {"A": 3})
        self.assertEqual(edicion.cambiar_goteo(datos, {"cabecera_m": 1.0, "emisor": None})["goteo"].get("emisor"), None)

    def test_zona_utm(self):
        self.assertEqual(epsg_utm(17, True), 32717)
        self.assertEqual(epsg_utm(18, False), 32618)
        self.assertEqual(zona_de_epsg(32718), (18, True))
        self.assertIsNone(zona_de_epsg(4326))
        with self.assertRaises(ValueError):
            epsg_utm(61, True)


class PruebasModeloEditable(unittest.TestCase):
    def test_cache_de_lotes_igual_que_calcular_de_cero(self):
        p = ProyectoRiego(datos_prueba())
        p.disenar()
        llamadas = []
        original = motor.disenar_lote

        def contar(lote, *args):
            llamadas.append(lote["nombre"])
            return original(lote, *args)

        with mock.patch.object(motor, "disenar_lote", side_effect=contar):
            p.datos = edicion.mover_vertice(p.datos, ("lote", 1), (0, 2), (X0 + 125, Y0 + 35))
            p.disenar()
            self.assertEqual(llamadas, ["B"])  # A y C no cambiaron
            nuevo = ProyectoRiego(copy.deepcopy(p.datos))
            nuevo.disenar()
            self.assertEqual(p.resumen()["subunidades"], nuevo.resumen()["subunidades"])
            # Deshacer (volver a los datos de antes) no recalcula
            llamadas.clear()
            p.datos = datos_prueba()
            p.disenar()
            self.assertEqual(llamadas, [])
            # Con válvula automática la fuente cuenta; con válvula fija, no
            datos = datos_prueba()
            datos["lotes"][2]["valvula"] = "auto"
            p.datos = datos
            p.disenar()
            llamadas.clear()
            p.datos = edicion.fijar_fuente(datos, (X0 + 300, Y0 - 20))
            p.disenar()
            self.assertEqual(llamadas, ["C"])

    def test_proyecto_nuevo_dibujado_desde_cero(self):
        p = ProyectoRiego.nuevo("Desde cero", 32718, {"tipo": "plano", "cota_m": 50, "origen": [X0, Y0],
                                                      "pendiente_y": 0.005}, (X0, Y0))
        self.assertEqual((p.nombre, p.epsg, p.referencia), ("Desde cero", 32718, (X0, Y0)))
        self.assertEqual(p.extension(), (X0, Y0, X0, Y0))
        d = edicion.cambiar_goteo(p.datos, GOTEO)
        d = edicion.agregar_lote(d, rectangulo(0, 0, 60, 30), "A")
        d = edicion.agregar_lote(d, rectangulo(70, 0, 50, 30))
        d = edicion.fijar_fuente(d, (X0 - 20, Y0 - 20))
        d = edicion.agregar_matriz(d, [(X0 - 20, Y0 - 20), (X0 - 20, Y0 + 40), (X0 + 130, Y0 + 40)])
        d = edicion.fijar_turnos(d, 2)
        p.datos = d
        p.disenar()
        self.assertEqual(p.errores, [])
        p.calcular_red()
        # El mismo diseño por el servidor MCP da lo mismo (pérdida en válvula igual en ambos)
        mcp = dict(d, red=dict(d["red"], perdida_valvula_m=p.parametros_red["perdida_valvula_m"]))
        esperado = motor.disenar_proyecto(mcp).resumen()
        for clave in ("subunidades", "red", "bomba", "turnos"):
            self.assertEqual(p.resumen()[clave], esperado[clave], clave)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as carpeta:
            ruta = os.path.join(carpeta, "cero.riegolibre")
            archivo.guardar(p, ruta)
            q = archivo.abrir(ruta)
            self.assertEqual(q.datos, p.datos)
            self.assertEqual(q.resumen(), p.resumen())
            q.cerrar()


class PruebasFichas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = ProyectoRiego(datos_prueba())
        cls.p.disenar()

    def test_fichas_sin_red_y_con_red(self):
        p = self.p
        p.red = None
        s = p.subunidades[0]
        ficha = fichas.ficha_en(p, s.bloque.valvula, 0.5)
        self.assertIn(f"Válvula {s.nombre}", ficha.titulo)
        self.assertIn("Las presiones por turno aparecen", ficha.texto)
        self.assertIn("Fuente de agua", fichas.ficha_en(p, p.fuente, 0.5).titulo)
        self.assertIn("Tubería matriz, tramo 1", fichas.ficha_en(p, (X0 - 20, Y0 + 10), 0.5).titulo)
        ficha = fichas.ficha_en(p, (X0 - 20, Y0 + 40), 0.5)  # el codo de la matriz es un nodo
        self.assertIn("Nodo 2 de la matriz", ficha.titulo)
        self.assertIn("Tramos que llegan = 1, 2", ficha.texto)
        self.assertIn("Válvula B", fichas.ficha_en(p, (X0 + 75, Y0 + 3), 0.5).titulo)  # dentro del lote B
        self.assertIsNone(fichas.ficha_en(p, (X0 + 500, Y0 + 500), 0.5))

        p.calcular_red()
        ficha = fichas.ficha_en(p, s.bloque.valvula, 0.5)
        self.assertIn("Turno 1", ficha.texto)
        self.assertIn("Turno 2", ficha.texto)
        self.assertIn("Bomba", fichas.ficha_en(p, p.fuente, 0.5).titulo)
        ficha = fichas.ficha_en(p, (X0 - 20, Y0 + 10), 0.5)
        self.assertIn("red principal", ficha.titulo)
        # P1 es el extremo aguas arriba: el de la fuente
        self.assertIn(f"P1: x = {X0 - 20:.2f} m, y = {Y0 - 20:.2f} m", ficha.texto)

    def test_tramo_aguas_abajo_orientado(self):
        p = self.p
        p.calcular_red()
        sentido = fichas._desde_hasta(p.red)
        fuente = p.fuente
        for id_tramo, (p1, p2) in sentido.items():
            if id_tramo.startswith("M"):  # sobre la matriz el agua se aleja de la fuente
                self.assertLessEqual(math.dist(fuente, p1), math.dist(fuente, p2) + 1e-6, id_tramo)


@unittest.skipUnless(HAY_PYSIDE, "requiere PySide6 (Python normal, no el de QGIS)")
class PruebasVentanaEdicion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from riegolibre_escritorio import ventana
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        parche = mock.patch.object(ventana, "QMessageBox")
        self.mensajes = parche.start()
        self.addCleanup(parche.stop)
        self.v = ventana.VentanaPrincipal()
        self.v.resize(1000, 700)
        self.v.show()
        self.addCleanup(self.v.deleteLater)
        self.v.nuevo({"nombre": "Fundo de prueba", "epsg": 32717, "terreno": None, "referencia": (X0 + 50, Y0)})
        self.v.aplicar(edicion.cambiar_goteo(self.v.proyecto.datos, GOTEO), "Goteo")
        lienzo = self.v.lienzo
        lienzo.resetTransform()
        lienzo.scale(2, 2)  # 2 píxeles por metro: tolerancia del imán = 5 m
        lienzo.centerOn(lienzo.a_escena(X0 + 60, Y0 + 10))
        self.app.processEvents()

    # -------- ratón y teclado sobre el lienzo, en coordenadas del proyecto

    def _px(self, x, y):
        return self.v.lienzo.mapFromScene(self.v.lienzo.a_escena(x, y))

    def clic(self, x, y, boton=None, modificadores=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.v.lienzo.viewport(), boton or Qt.MouseButton.LeftButton,
                         modificadores or Qt.KeyboardModifier.NoModifier, self._px(x, y))

    def arrastrar(self, desde, hasta):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        vista = self.v.lienzo.viewport()
        for tipo, (x, y), botones in ((QMouseEvent.Type.MouseButtonPress, desde, Qt.MouseButton.LeftButton),
                                      (QMouseEvent.Type.MouseMove, hasta, Qt.MouseButton.LeftButton),
                                      (QMouseEvent.Type.MouseButtonRelease, hasta, Qt.MouseButton.NoButton)):
            punto = QPointF(self._px(x, y))
            evento = QMouseEvent(tipo, punto, vista.mapToGlobal(punto), Qt.MouseButton.LeftButton, botones,
                                 Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(vista, evento)

    def tecla(self, tecla):
        from PySide6.QtTest import QTest
        QTest.keyClick(self.v.lienzo, tecla)

    def accion_menu(self, x, y, texto):
        """La acción del menú del clic derecho en (x, y) con ese texto (busca en los submenús)."""
        from riegolibre_escritorio.menu_mapa import armar_menu
        pendientes = [armar_menu(self.v, x, y)]
        while pendientes:
            menu = pendientes.pop()
            for accion in menu.actions():
                if accion.menu():
                    pendientes.append(accion.menu())
                elif accion.text() == texto:
                    return accion
        self.fail(f"No está «{texto}» en el menú")

    def dibujar(self, herramienta, puntos, terminar="menu"):
        from PySide6.QtCore import Qt
        self.v.usar_herramienta(herramienta)
        for x, y in puntos:
            self.clic(x, y)
        if terminar == "menu":  # clic derecho → «Terminar el trazo»
            self.accion_menu(*puntos[-1], "Terminar el trazo").trigger()
        elif terminar == "intro":
            self.tecla(Qt.Key.Key_Return)

    def test_dibujar_calcular_deshacer_guardar(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog
        from riegolibre_escritorio import dialogo_bloque
        v = self.v
        self.assertEqual(v.proyecto.epsg, 32717)
        self.assertTrue(v.acciones_herramientas["lote"].isChecked())  # proyecto nuevo: a dibujar lotes

        # Lote A: al cerrarlo se abre su bloque de goteo (se acepta sin cambios)
        with mock.patch.object(dialogo_bloque.DialogoBloque, "exec", return_value=QDialog.DialogCode.Accepted):
            self.dibujar("lote", [(X0, Y0), (X0 + 60, Y0), (X0 + 60, Y0 + 30), (X0, Y0 + 30)])
            # Lote B con Intro; su primer vértice está a 1.5 m del borde de A: el imán lo pega
            self.dibujar("lote", [(X0 + 61.5, Y0 + 10), (X0 + 120, Y0 + 10), (X0 + 120, Y0 + 30), (X0 + 70, Y0 + 30)],
                         terminar="intro")
        self.mensajes.warning.assert_not_called()
        lotes = v.proyecto.datos["lotes"]
        self.assertEqual([l["nombre"] for l in lotes], ["Lote 1", "Lote 2"])
        self.assertEqual(lotes[1]["contorno"][0], [X0 + 60, Y0 + 10])
        self.assertEqual(set(lotes[0]), {"nombre", "contorno"})  # sin parámetros propios: los del proyecto
        self.assertEqual(len(v.proyecto.subunidades), 2)
        self.assertEqual(v.tabla_atributos.tabla_lotes.rowCount(), 2)
        self.assertEqual(v.tabla_subunidades.rowCount(), 2)

        # Esc cancela un trazo a medias
        self.v.usar_herramienta("lote")
        self.clic(X0 + 10, Y0 + 50)
        self.clic(X0 + 20, Y0 + 50)
        self.tecla(Qt.Key.Key_Escape)
        self.assertEqual(len(v.proyecto.datos["lotes"]), 2)

        # Fuente (dos veces: queda una) y matriz que empieza en ella por el imán
        self.dibujar("fuente", [(X0 + 10, Y0 - 25)], terminar=None)
        self.dibujar("fuente", [(X0 - 20, Y0 - 20)], terminar=None)
        self.assertEqual(v.proyecto.fuente, (X0 - 20, Y0 - 20))
        self.dibujar("matriz", [(X0 - 18, Y0 - 19), (X0 - 20, Y0 + 40), (X0 + 130, Y0 + 40)])
        # Un tramo por cada par de clics, y tres nodos en su capa
        self.assertEqual(v.proyecto.matriz, [[(X0 - 20, Y0 - 20), (X0 - 20, Y0 + 40)],
                                             [(X0 - 20, Y0 + 40), (X0 + 130, Y0 + 40)]])
        self.assertEqual(len(v.lienzo.capas["NODOS_MATRIZ"].elementos), 3)
        self.assertEqual(len(v.lienzo.capas["MATRIZ_DIBUJADA"].elementos), 2)
        self.assertEqual(v.tabla_atributos.tabla_nodos.rowCount(), 3)

        # Red principal
        v.abrir_red()
        v.dialogo_red.calcular()
        self.mensajes.warning.assert_not_called()
        self.assertIsNotNone(v.proyecto.red)
        cdt = v.proyecto.resumen()["bomba"]

        # Mover un vértice de la matriz: la red se vuelve a calcular sola
        v.usar_herramienta("seleccion")
        self.clic(X0 + 50, Y0 + 40)
        self.assertEqual(v.seleccion, ("matriz", 1))
        self.arrastrar((X0 + 130, Y0 + 40), (X0 + 140, Y0 + 45))
        self.assertEqual(v.proyecto.matriz[1][1], (X0 + 140, Y0 + 45))
        self.assertIsNotNone(v.proyecto.red)
        self.assertNotEqual(v.proyecto.resumen()["metrados_m"], {})

        # Borrar el lote 2 con Supr; deshacer lo trae de vuelta; rehacer lo borra otra vez
        self.clic(X0 + 100, Y0 + 20)
        self.assertEqual(v.seleccion, ("lote", 1))
        self.tecla(Qt.Key.Key_Delete)
        self.assertEqual(len(v.proyecto.datos["lotes"]), 1)
        self.assertEqual(len(v.proyecto.subunidades), 1)
        v.deshacer()
        self.assertEqual(len(v.proyecto.subunidades), 2)
        v.rehacer()
        self.assertEqual(len(v.proyecto.subunidades), 1)
        v.deshacer()
        v.deshacer()  # también el vértice de la matriz
        self.assertEqual(v.proyecto.matriz[1][1], (X0 + 130, Y0 + 40))
        self.assertEqual(v.proyecto.resumen()["bomba"], cdt)
        self.assertIn("Deshacer", v.acciones["deshacer"].text())

        # Doble clic en un borde agrega un vértice; Ctrl + clic en él lo quita
        self.clic(X0 + 30, Y0 + 15)
        self.assertEqual(v.seleccion, ("lote", 0))
        from PySide6.QtTest import QTest
        QTest.mouseDClick(v.lienzo.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                          self._px(X0 + 30, Y0))
        self.assertEqual(len(v.proyecto.datos["lotes"][0]["contorno"]), 5)
        self.clic(X0 + 30, Y0, modificadores=Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(v.proyecto.datos["lotes"][0]["contorno"]), 4)

        # Guardar y abrir
        ruta = os.path.join(self.carpeta.name, "Fundo de prueba.riegolibre")
        self.assertTrue(v._guardar_en(ruta))
        datos = copy.deepcopy(v.proyecto.datos)
        v.nuevo({"nombre": "Otro", "epsg": 32718, "terreno": None, "referencia": None})
        self.assertFalse(v.pila.canUndo())
        v.abrir(ruta)
        self.mensajes.warning.assert_not_called()
        self.assertEqual(v.proyecto.datos, datos)
        self.assertIsNotNone(v.proyecto.red)

    def test_menu_del_clic_derecho(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtWidgets import QApplication
        from riegolibre_escritorio import ventana
        v = self.v
        datos = edicion.agregar_lote(v.proyecto.datos, rectangulo(0, 0, 60, 30))
        datos = edicion.fijar_fuente(datos, (X0 - 20, Y0 - 20))
        v.aplicar(edicion.agregar_matriz(datos, [(X0 - 20, Y0 - 20), (X0 - 20, Y0 + 40), (X0 + 130, Y0 + 40)]),
                  "Diseño")
        v.usar_herramienta("seleccion")

        # El clic derecho abre el menú en el punto (no termina ni selecciona nada por sí solo)
        with mock.patch.object(ventana, "armar_menu") as armar:
            evento = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, self._px(X0 + 30, Y0 + 15), QPoint(5, 5))
            QApplication.sendEvent(v.lienzo.viewport(), evento)
        (_v, x, y), _ = armar.call_args
        self.assertAlmostEqual(x, X0 + 30, delta=0.6)
        self.assertAlmostEqual(y, Y0 + 15, delta=0.6)
        armar.return_value.exec.assert_called_once()

        # Seleccionar objeto y quitar la selección
        self.assertFalse(self.accion_menu(X0 + 30, Y0 + 15, "Quitar la selección").isEnabled())
        self.accion_menu(X0 + 30, Y0 + 15, "Seleccionar objeto").trigger()
        self.assertEqual(v.seleccion, ("lote", 0))
        self.accion_menu(X0 + 500, Y0 + 500, "Quitar la selección").trigger()
        self.assertIsNone(v.seleccion)
        self.assertFalse(self.accion_menu(X0 + 500, Y0 + 500, "Seleccionar objeto").isEnabled())

        # Capas: ocultar la de nodos
        self.accion_menu(X0, Y0, "NODOS_MATRIZ").trigger()
        self.assertFalse(v.proyecto.estilos_capas["NODOS_MATRIZ"]["visible"])
        self.assertFalse(v.lienzo.capas["NODOS_MATRIZ"].elementos[0].isVisible())

        # Modificar: partir un tramo y quitar el nodo; borrar un tramo; deshacer
        self.accion_menu(X0 + 50, Y0 + 40, "Partir el tramo aquí (nodo nuevo)").trigger()
        self.assertEqual(len(v.proyecto.matriz), 3)
        self.accion_menu(X0 + 50, Y0 + 40, "Quitar el nodo (une sus tramos)").trigger()
        self.assertEqual(len(v.proyecto.matriz), 2)
        self.accion_menu(X0 - 20, Y0 + 10, "Borrar el tramo 1 de la tubería matriz").trigger()
        self.assertEqual(v.proyecto.matriz, [[(X0 - 20, Y0 + 40), (X0 + 130, Y0 + 40)]])
        v.deshacer()
        self.assertEqual(len(v.proyecto.matriz), 2)

        # Información del objeto y zoom al objeto
        self.accion_menu(X0 - 20, Y0 + 40, "Información del objeto").trigger()
        self.assertIn("Nodo 2", v.dialogo_ficha.windowTitle())
        self.accion_menu(X0 - 20, Y0 + 10, "Al objeto").trigger()

        # Terminar y Reiniciar solo mientras se dibuja
        self.assertFalse(self.accion_menu(X0, Y0, "Terminar el trazo").isEnabled())
        v.usar_herramienta("matriz")
        self.clic(X0 + 130, Y0 + 40)
        self.clic(X0 + 130, Y0 + 90)
        self.accion_menu(X0 + 130, Y0 + 90, "Reiniciar el trazo").trigger()
        self.assertFalse(v.herramientas["matriz"].trazando)
        self.assertEqual(len(v.proyecto.matriz), 2)
        self.clic(X0 + 130, Y0 + 40)
        self.clic(X0 + 130, Y0 + 90)
        self.accion_menu(X0 + 130, Y0 + 90, "Terminar el trazo").trigger()
        self.assertEqual(len(v.proyecto.matriz), 3)
        self.assertEqual(len(edicion.nodos_matriz(v.proyecto.datos)), 4)

    def test_bloque_de_goteo_por_lote_y_turnos(self):
        from PySide6.QtWidgets import QDialog
        from riegolibre_escritorio import dialogo_bloque
        from riegolibre_escritorio.dialogos import DialogoTurnos
        v = self.v
        datos = v.proyecto.datos
        for x in (0, 70):
            datos = edicion.agregar_lote(datos, rectangulo(x, 0, 60, 30))
        v.aplicar(datos, "Dos lotes")

        cuadro = dialogo_bloque.DialogoBloque(v.proyecto.datos, 1)
        self.assertEqual(cuadro.combo_emisor.currentText(), GOTEO["emisor"])
        self.assertAlmostEqual(cuadro.caja_azimut.value(), 90.0)
        self.assertFalse(cuadro.casilla_proyecto.isChecked())  # el proyecto ya tiene emisor
        goteo, lote = cuadro.cambios()
        self.assertEqual({k: v_ for k, v_ in lote.items() if v_ is not None}, {"nombre": "Lote 2"})
        # Portalateral al final, válvula al inicio, 3 m entre hileras, turno 2 fijo
        cuadro.combo_porta.setCurrentIndex(cuadro.combo_porta.findData("final"))
        cuadro.combo_valvula.setCurrentIndex(cuadro.combo_valvula.findData("inicio"))
        cuadro.caja_hileras.setValue(2.5)
        cuadro.edit_nombre.setText("Palto")
        goteo, lote = cuadro.cambios()
        self.assertTrue(all(valor is None for valor in goteo.values()) or not goteo)
        v.aplicar_bloque(1, goteo, lote)
        lote = v.proyecto.datos["lotes"][1]
        self.assertEqual((lote["nombre"], lote["portalateral"], lote["valvula"], lote["separacion_hileras_m"]),
                         ("Palto", "final", "inicio", 2.5))
        s = next(s for s in v.proyecto.subunidades if s.lote == "Palto")
        self.assertEqual(s.resumen()["portalateral_m"] > 0, True)
        self.assertEqual(s.config["separacion_hileras_m"], 2.5)
        self.assertEqual(s.config["portalateral"], "final")
        # El otro lote sigue con los valores del proyecto
        otro = next(s for s in v.proyecto.subunidades if s.lote == "Lote 1")
        self.assertEqual(otro.config["separacion_hileras_m"], GOTEO["separacion_hileras_m"])

        # «Usar también como valores del proyecto»: pasa al goteo y el lote queda sin propios
        cuadro = dialogo_bloque.DialogoBloque(v.proyecto.datos, 1)
        cuadro.casilla_proyecto.setChecked(True)
        v.aplicar_bloque(1, *cuadro.cambios())
        self.assertEqual(v.proyecto.datos["goteo"]["separacion_hileras_m"], 2.5)
        self.assertEqual(set(v.proyecto.datos["lotes"][1]), {"nombre", "contorno"})

        # Turnos: dos turnos y el lote «Palto» fijo en el 1
        cuadro = DialogoTurnos(v.proyecto.datos)
        cuadro.caja_turnos.setValue(2)
        combo = cuadro.tabla.cellWidget(1, 1)
        combo.setCurrentIndex(combo.findData(1))
        with mock.patch("riegolibre_escritorio.ventana.DialogoTurnos") as clase:
            clase.return_value = cuadro
            with mock.patch.object(cuadro, "exec", return_value=QDialog.DialogCode.Accepted):
                v.editar_turnos()
        self.assertEqual(v.proyecto.datos["red"]["turnos"], 2)
        self.assertEqual(v.proyecto.datos["red"]["turnos_fijos"], {"Palto": 1})
        turnos = {s.lote: s.turno for s in v.proyecto.subunidades}
        self.assertEqual(turnos, {"Lote 1": 2, "Palto": 1})
        v.deshacer()
        self.assertEqual(v.proyecto.turnos, 1)

    def test_informacion_y_tabla(self):
        v = self.v
        datos = edicion.agregar_lote(v.proyecto.datos, rectangulo(0, 0, 60, 30), "A")
        v.aplicar(datos, "Lote")
        v.usar_herramienta("info")
        self.clic(X0 + 30, Y0 + 15)
        self.assertIsNotNone(v.dialogo_ficha)
        self.assertIn("Válvula A", v.dialogo_ficha.windowTitle())
        self.assertIn("Lote = A", v.dialogo_ficha.texto.toPlainText())
        # Clic en la tabla de atributos: selecciona en el mapa
        v.tabla_atributos.elegido.emit(("lote", 0))
        self.assertEqual(v.seleccion, ("lote", 0))
        self.assertTrue(v.acciones["bloque"].isEnabled())

    def test_filtro_del_mcp_solo_datos(self):
        from riegolibre_escritorio import ventana
        self.assertEqual(ventana.FILTRO_MCP, "Diseño del servidor MCP (*_datos.json)")


if __name__ == "__main__":
    unittest.main()
