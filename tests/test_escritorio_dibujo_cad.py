# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Lotes y líneas de referencia de un DXF en el programa de escritorio: lectura, lotes con huecos y nombres de los
textos, guardado en el proyecto, imán y el menú Terreno de la ventana.

El DXF de prueba: dos lotes rectangulares (uno con un hueco y una isla dentro del hueco), sus nombres en una capa
de textos, una línea abierta en la capa de lotes, un camino, un canal cerrado y una curva de nivel.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

from tests.test_escritorio import X0, Y0, datos_prueba

try:
    import ezdxf  # noqa: F401
    HAY_EZDXF = True
except ImportError:
    HAY_EZDXF = False

try:
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules
except ImportError:
    HAY_PYSIDE = False

DX = 1000.0  # los lotes del DXF quedan al este de los del proyecto de prueba


def rectangulo(x0, y0, ancho, alto):
    return [(x0, y0), (x0 + ancho, y0), (x0 + ancho, y0 + alto), (x0, y0 + alto)]


def escribir_dxf(ruta):
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    x, y = X0 + DX, Y0
    msp.add_lwpolyline(rectangulo(x, y, 100, 50), close=True, dxfattribs={"layer": "LOTES"})
    msp.add_lwpolyline(rectangulo(x + 40, y + 10, 30, 30), close=True, dxfattribs={"layer": "LOTES"})  # hueco
    msp.add_lwpolyline(rectangulo(x + 50, y + 20, 10, 10), close=True, dxfattribs={"layer": "LOTES"})  # isla
    # Segundo lote cerrado repitiendo el primer vértice al final (sin la marca de cerrada)
    msp.add_lwpolyline(rectangulo(x, y + 60, 80, 40) + [(x, y + 60)], dxfattribs={"layer": "LOTES"})
    msp.add_lwpolyline([(x, y - 10), (x + 100, y - 10)], dxfattribs={"layer": "LOTES"})  # abierta: no es lote
    msp.add_text("Norte", dxfattribs={"layer": "NOMBRES"}).set_placement((x + 30, y + 80))
    msp.add_text("Sur", dxfattribs={"layer": "NOMBRES"}).set_placement((x + 10, y + 25))
    msp.add_mtext("Lejos", dxfattribs={"layer": "NOMBRES", "insert": (x + 500, y)})
    msp.add_lwpolyline([(x - 20, y - 20), (x + 150, y - 20), (x + 150, y + 120)], dxfattribs={"layer": "CAMINO"})
    msp.add_line((x - 30, y), (x - 30, y + 100), dxfattribs={"layer": "CAMINO"})
    msp.add_lwpolyline(rectangulo(x + 200, y, 5, 100), close=True, dxfattribs={"layer": "CANAL"})
    msp.add_lwpolyline([(x, y + 200), (x + 100, y + 200)], dxfattribs={"layer": "CV", "elevation": 120.0})
    doc.saveas(ruta)
    return ruta


class PruebasGeometria(unittest.TestCase):
    """Sin ezdxf: armado de lotes, nombres e imán."""

    def test_huecos_e_islas(self):
        from riegolibre_escritorio.dibujo_cad import poligonos_a_lotes

        lotes = poligonos_a_lotes([rectangulo(40, 10, 30, 30), rectangulo(0, 0, 100, 50),
                                   rectangulo(50, 20, 10, 10), rectangulo(200, 0, 10, 10)])
        self.assertEqual(len(lotes), 3)
        grande = lotes[0]
        self.assertEqual(grande["contorno"][0], [0, 0])
        self.assertEqual(len(grande["huecos"]), 1)
        self.assertEqual(grande["huecos"][0][0], [40, 10])
        self.assertNotIn("huecos", lotes[1])
        self.assertEqual({tuple(l["contorno"][0]) for l in lotes[1:]}, {(50, 20), (200, 0)})

    def test_nombres_por_texto(self):
        from riegolibre_escritorio.dibujo_cad import nombrar_lotes, poligonos_a_lotes

        lotes = poligonos_a_lotes([rectangulo(0, 0, 100, 50), rectangulo(40, 10, 30, 30), rectangulo(50, 20, 10, 10)])
        nombrar_lotes(lotes, [("En el hueco", (45, 15)), ("Isla", (55, 25)), ("Grande", (10, 10)),
                              ("Otro grande", (90, 45)), ("", (5, 5))])
        nombres = {tuple(l["contorno"][0]): l["nombre"] for l in lotes}
        self.assertEqual(nombres[(50, 20)], "Isla")
        self.assertEqual(nombres[(0, 0)], "Grande")  # el más cercano al centro; el del hueco no cuenta

    def test_agregar_lotes_con_nombres_repetidos(self):
        from riegolibre_escritorio import edicion

        datos = {"lotes": [{"nombre": "Norte", "contorno": rectangulo(0, 0, 10, 10)},
                           {"nombre": "Lote 1", "contorno": rectangulo(20, 0, 10, 10)}]}
        nuevo = edicion.agregar_lotes(datos, [
            {"nombre": "Norte", "contorno": rectangulo(0, 20, 10, 10)},
            {"nombre": None, "contorno": rectangulo(0, 40, 10, 10), "huecos": [rectangulo(2, 42, 2, 2)]},
            {"nombre": "Norte", "contorno": rectangulo(0, 60, 10, 10)},
            {"nombre": "Raya", "contorno": [(0, 0), (1, 0), (2, 0)]},  # sin área: se salta
        ])
        self.assertEqual([l["nombre"] for l in nuevo["lotes"]], ["Norte", "Lote 1", "Norte (2)", "Lote 2", "Norte (3)"])
        self.assertEqual(len(nuevo["lotes"][3]["huecos"]), 1)
        self.assertEqual(len(datos["lotes"]), 2)  # no toca los datos de antes

    def test_indice_iman(self):
        from riegolibre_escritorio import edicion
        from riegolibre_escritorio.dibujo_cad import IndiceIman

        indice = IndiceIman([("CAMINO", [(0.0, 0.0), (1000.0, 0.0)]), ("CANAL", [(0.0, 50.0), (10.0, 50.0)])])
        puntos, tramos = indice.cerca((500.0, 1.0), 2.0)
        self.assertEqual(puntos, [])
        self.assertEqual(tramos, [((0.0, 0.0), (1000.0, 0.0))])
        p, tipo = edicion.imantar((500.0, 1.0), {"lotes": []}, 2.0, puntos, tramos)
        self.assertEqual((p, tipo), ((500.0, 0.0), edicion.BORDE))
        puntos, _ = indice.cerca((10.5, 50.5), 2.0)
        self.assertIn((10.0, 50.0), puntos)
        self.assertEqual(indice.cerca((500.0, 300.0), 2.0), ([], []))


@unittest.skipUnless(HAY_EZDXF, "requiere ezdxf")
class PruebasDxf(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        self.ruta = escribir_dxf(os.path.join(self.carpeta.name, "plano.dxf"))

    def test_leer(self):
        from riegolibre_escritorio.dibujo_cad import leer_dibujo
        from riegolibre_escritorio.dialogo_terreno import LINEAS, LOTES, NO_IMPORTAR, uso_inicial

        contenido = leer_dibujo(self.ruta)
        capas = {c.nombre: c for c in contenido.capas}
        self.assertEqual(set(capas), {"LOTES", "CAMINO", "CANAL", "CV"})
        self.assertEqual((capas["LOTES"].lineas, capas["LOTES"].cerradas), (5, 4))
        self.assertEqual((capas["CAMINO"].lineas, capas["CAMINO"].cerradas), (2, 0))
        self.assertEqual(contenido.textos, {"NOMBRES": 3})
        self.assertEqual([uso_inicial(capas[n]) for n in ("LOTES", "CAMINO", "CANAL", "CV")],
                         [LOTES, LINEAS, LINEAS, NO_IMPORTAR])

    def test_importar(self):
        from riegolibre_escritorio.dibujo_cad import importar_dibujo

        r = importar_dibujo(self.ruta, ["LOTES"], ["CAMINO", "CANAL"], "NOMBRES")
        self.assertEqual(len(r.lotes), 3)  # dos rectángulos y la isla
        nombres = sorted(str(l["nombre"]) for l in r.lotes)
        self.assertEqual(nombres, ["None", "Norte", "Sur"])
        sur = next(l for l in r.lotes if l["nombre"] == "Sur")
        self.assertEqual(len(sur["huecos"]), 1)
        self.assertEqual(len(sur["contorno"]), 4)  # sin el vértice de cierre
        norte = next(l for l in r.lotes if l["nombre"] == "Norte")
        self.assertEqual(len(norte["contorno"]), 4)
        self.assertEqual(sorted(c for c, _ in r.lineas), ["CAMINO", "CAMINO", "CANAL"])
        canal = next(linea for c, linea in r.lineas if c == "CANAL")
        self.assertEqual(canal[0], canal[-1])  # la cerrada se dibuja cerrada
        self.assertEqual(len(r.avisos), 1)
        self.assertIn("1 línea(s) abierta(s)", r.avisos[0])

        solo_lineas = importar_dibujo(self.ruta, [], ["CANAL"])
        self.assertEqual((solo_lineas.lotes, len(solo_lineas.lineas)), ([], 1))
        with self.assertRaisesRegex(ValueError, "al menos una capa"):
            importar_dibujo(self.ruta, [], [])
        sin_cerradas = importar_dibujo(self.ruta, ["CAMINO"], [])
        self.assertIn("no tienen polilíneas cerradas", sin_cerradas.avisos[0])

    def test_proyecto_guarda_las_lineas(self):
        from riegolibre_escritorio import archivo
        from riegolibre_escritorio.dibujo_cad import importar_dibujo
        from riegolibre_escritorio.modelo import ProyectoRiego

        r = importar_dibujo(self.ruta, ["LOTES"], ["CAMINO", "CANAL"], "NOMBRES")
        p = ProyectoRiego(datos_prueba())
        self.addCleanup(p.cerrar)
        antes = len(p.datos["lotes"])
        p.datos = p.datos_con_dibujo(r.lineas, {"origenes": ["plano.dxf"], "capas": ["CAMINO", "CANAL"]}, r.lotes)
        self.assertEqual(len(p.datos["lotes"]), antes + 3)
        self.assertEqual(len(p.dibujo), 3)
        self.assertGreaterEqual(p.extension()[2], X0 + DX + 205)  # el canal agranda la extensión
        ruta = os.path.join(self.carpeta.name, "con_dibujo.riegolibre")
        archivo.guardar(p, ruta)
        abierto = archivo.abrir(ruta)
        self.addCleanup(abierto.cerrar)
        self.assertEqual(abierto.dibujo, p.dibujo)
        self.assertEqual(set(abierto.archivos), {p.datos["dibujo_cad"]["archivo"]})
        sin = abierto.datos_con_dibujo([], {})
        self.assertNotIn("dibujo_cad", sin)


@unittest.skipUnless(HAY_EZDXF and HAY_PYSIDE, "requiere ezdxf y PySide6")
class PruebasVentanaDibujo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from riegolibre_escritorio import ventana
        from riegolibre_escritorio.modelo import ProyectoRiego

        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        parche = mock.patch.object(ventana, "QMessageBox")
        self.mensajes = parche.start()
        self.addCleanup(parche.stop)
        self.ventana_modulo = ventana
        self.v = ventana.VentanaPrincipal()
        self.addCleanup(self.v.deleteLater)
        self.v._cambiar_proyecto(ProyectoRiego(datos_prueba()), False)
        self.v.proyecto.disenar()
        self.ruta = escribir_dxf(os.path.join(self.carpeta.name, "plano.dxf"))

    def test_dialogo(self):
        from PySide6.QtWidgets import QDialogButtonBox

        from riegolibre_escritorio.dialogo_terreno import NO_IMPORTAR, DialogoDibujo
        from riegolibre_escritorio.dibujo_cad import leer_dibujo

        dialogo = DialogoDibujo(self.ruta, leer_dibujo(self.ruta), self.v.proyecto.extension())
        self.addCleanup(dialogo.deleteLater)
        self.assertEqual(dialogo.valores(), {"capas_lotes": ["LOTES"], "capas_lineas": ["CAMINO", "CANAL"],
                                             "capa_nombres": "NOMBRES"})
        aceptar = dialogo.botones.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(aceptar.isEnabled())
        self.assertIn("hasta 4 lotes y 3 líneas de referencia", dialogo.aviso.text())
        for capa in ("LOTES", "CAMINO", "CANAL"):
            dialogo.fijar_uso(capa, NO_IMPORTAR)
        self.assertFalse(aceptar.isEnabled())
        self.assertIn("al menos una capa", dialogo.aviso.text())

    def test_importar_deshacer_y_quitar(self):
        from PySide6.QtWidgets import QDialog

        v = self.v
        antes = [l["nombre"] for l in v.proyecto.datos["lotes"]]
        self.assertFalse(v.acciones["quitar_dibujo"].isEnabled())
        with mock.patch.object(self.ventana_modulo.DialogoDibujo, "exec", return_value=QDialog.DialogCode.Accepted):
            v.importar_dibujo(self.ruta)
        self.mensajes.warning.assert_not_called()
        nombres = [l["nombre"] for l in v.proyecto.datos["lotes"]]
        self.assertEqual(nombres[:len(antes)], antes)
        nuevos = nombres[len(antes):]
        self.assertEqual(len(nuevos), 3)
        self.assertTrue({"Sur", "Norte"} <= set(nuevos))
        self.assertEqual(len(set(nombres)), len(nombres))  # la isla recibe un nombre libre
        self.assertEqual(len(v.proyecto.dibujo), 3)
        self.assertEqual(len(v.lienzo.capas["DIBUJO_CAD"].elementos), 2)  # un elemento por capa del DXF
        self.assertTrue(v.acciones["quitar_dibujo"].isEnabled())
        self.assertIn("3 lotes y 3 líneas de referencia", v.statusBar().currentMessage())
        # Imán: el camino pasa por y = Y0 − 20
        puntos, tramos = v.iman_extra((X0 + DX + 60, Y0 - 19.5), 1.0)
        self.assertTrue(tramos)

        v.deshacer()
        self.assertEqual([l["nombre"] for l in v.proyecto.datos["lotes"]], antes)
        self.assertEqual(v.proyecto.dibujo, [])
        self.assertEqual(v.lienzo.capas["DIBUJO_CAD"].elementos, [])
        v.rehacer()
        self.assertEqual(len(v.proyecto.dibujo), 3)

        # Una segunda importación suma líneas
        with mock.patch.object(self.ventana_modulo.DialogoDibujo, "exec", return_value=QDialog.DialogCode.Accepted), \
                mock.patch.object(self.ventana_modulo.DialogoDibujo, "valores",
                                  return_value={"capas_lotes": [], "capas_lineas": ["CANAL"], "capa_nombres": None}):
            v.importar_dibujo(self.ruta)
        self.assertEqual(len(v.proyecto.dibujo), 4)
        self.assertEqual(v.proyecto.datos["dibujo_cad"]["origenes"], ["plano.dxf"])

        v.quitar_dibujo()
        self.assertNotIn("dibujo_cad", v.proyecto.datos)
        self.assertEqual(v.lienzo.capas["DIBUJO_CAD"].elementos, [])
        self.assertEqual(len(v.proyecto.datos["lotes"]), len(antes) + 3)  # los lotes importados quedan


if __name__ == "__main__":
    unittest.main()
