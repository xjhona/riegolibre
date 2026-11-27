# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Curvas de nivel de un DXF en el programa de escritorio: lectura con ezdxf, DEM por TIN (numpy/scipy), DEM
binario del motor (`.rdem`), terreno del proyecto (deshacer, guardar y abrir) y el menú Terreno de la ventana.

El DXF de prueba son curvas de un plano inclinado (z = 100 + 2 % · (y − Y0)): un TIN lineal de un plano lo
reproduce exacto, así que las cotas del DEM se comparan con el valor teórico.
"""

import os
import random
import sys
import tempfile
import unittest
from array import array
from unittest import mock

from mcp_riegolibre import motor
from tests.test_escritorio import X0, Y0, datos_prueba

try:
    import ezdxf  # noqa: F401
    import numpy  # noqa: F401
    import scipy  # noqa: F401
    HAY_LIBRERIAS = True
except ImportError:
    HAY_LIBRERIAS = False

try:
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules
except ImportError:
    HAY_PYSIDE = False

PENDIENTE = 0.02
COTA_0 = 100.0


def cota_plano(x, y):
    return COTA_0 + PENDIENTE * (y - Y0)


def escribir_dxf(ruta, largo=300.0, alto=100.0, equidistancia=0.5):
    """Curvas horizontales del plano cada `equidistancia` m de cota (capas CV y CVD, maestras cada 2.5 m), una
    polilínea 3D en otra capa, el lindero sin cota y un texto."""
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    n = int(round(alto * PENDIENTE / equidistancia))
    for i in range(n + 1):
        z = COTA_0 + i * equidistancia
        y = Y0 + (z - COTA_0) / PENDIENTE
        capa = "CVD" if abs(z / 2.5 - round(z / 2.5)) < 1e-9 else "CV"
        puntos = [(X0 + largo * k / 6, y) for k in range(7)]
        msp.add_lwpolyline(puntos, dxfattribs={"layer": capa, "elevation": z})
    msp.add_polyline3d([(X0 + largo + 5, Y0, cota_plano(0, Y0)), (X0 + largo + 5, Y0 + alto, cota_plano(0, Y0 + alto))],
                       dxfattribs={"layer": "CV3D"})
    msp.add_lwpolyline([(X0, Y0), (X0 + largo, Y0), (X0 + largo, Y0 + alto), (X0, Y0 + alto)], close=True,
                       dxfattribs={"layer": "LINDERO"})
    msp.add_text("Fundo", dxfattribs={"layer": "TEXTO"}).set_placement((X0, Y0))
    doc.saveas(ruta)
    return ruta


class PruebasRejillaBinaria(unittest.TestCase):
    """El DEM binario del motor (solo biblioteca estándar): mismas cotas que el ASCII Grid."""

    def test_rdem_igual_que_asc(self):
        ncols, nrows, celda, x0, y0 = 7, 5, 2.0, 1000.0, 5000.0
        valores = [100.0 + 0.5 * i - 0.25 * j for j in range(nrows) for i in range(ncols)]
        valores[3] = -9999.0  # una celda sin dato (fila de arriba)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as carpeta:
            ruta_asc = os.path.join(carpeta, "dem.asc")
            with open(ruta_asc, "w", encoding="utf-8") as salida:
                salida.write(f"ncols {ncols}\nnrows {nrows}\nxllcorner {x0}\nyllcorner {y0}\ncellsize {celda}\n"
                             "NODATA_value -9999\n")
                for j in range(nrows):
                    salida.write(" ".join(f"{v:g}" for v in valores[j * ncols:(j + 1) * ncols]) + "\n")
            binario = array("f", valores)
            if sys.byteorder != "little":
                binario.byteswap()
            ruta_rdem = os.path.join(carpeta, "dem.rdem")
            with open(ruta_rdem, "wb") as salida:
                salida.write(motor.rejilla_a_bytes(binario.tobytes(), ncols, nrows, x0, y0, celda))
            asc = motor.Terreno({"tipo": "dem", "archivo": ruta_asc})
            rdem = motor.Terreno({"tipo": "dem", "archivo": ruta_rdem})
            for x in (1000.5, 1003.3, 1007.9, 1013.0, 999.0, 1020.0):
                for y in (5000.2, 5004.4, 5008.7, 5009.9, 5011.0):
                    self.assertEqual(asc.cota(x, y), rdem.cota(x, y), (x, y))
            self.assertIsNone(rdem.cota(1020.0, 5004.0))
        with self.assertRaisesRegex(ValueError, "una cota por celda"):
            motor.rejilla_a_bytes(b"\0" * 8, 3, 1, 0, 0, 1)


@unittest.skipUnless(HAY_LIBRERIAS, "requiere ezdxf, numpy y scipy")
class PruebasTopografia(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        self.ruta = escribir_dxf(os.path.join(self.carpeta.name, "curvas.dxf"))

    def terreno(self, resultado):
        ruta = os.path.join(self.carpeta.name, "dem.rdem")
        with open(ruta, "wb") as salida:
            salida.write(resultado.rejilla)
        return motor.Terreno({"tipo": "dem", "archivo": ruta})

    def test_leer_dxf(self):
        from riegolibre_escritorio.topografia import leer_dxf

        contenido = leer_dxf(self.ruta)
        capas = {c.nombre: c for c in contenido.capas}
        self.assertEqual(set(capas), {"CV", "CVD", "CV3D", "LINDERO"})  # el texto no es una línea
        self.assertEqual((capas["CV"].lineas + capas["CVD"].lineas, capas["CVD"].lineas), (5, 1))
        self.assertEqual((capas["CVD"].cota_min, capas["CVD"].cota_max), (100.0, 100.0))
        self.assertEqual((capas["CV"].cota_min, capas["CV"].cota_max), (100.5, 102.0))
        self.assertTrue(capas["CV3D"].parece_curvas)
        self.assertFalse(capas["LINDERO"].parece_curvas)
        self.assertAlmostEqual(contenido.ancho, 305.0)
        self.assertAlmostEqual(contenido.alto, 100.0)
        with self.assertRaisesRegex(ValueError, "No se encuentra"):
            leer_dxf(os.path.join(self.carpeta.name, "no_existe.dxf"))

    def test_dem_de_un_plano_es_exacto(self):
        from riegolibre_escritorio.topografia import NODATA, generar_dem

        avances = []
        r = generar_dem(self.ruta, ["CV", "CVD"], paso_m=1.0, distancia_max_m=30.0,
                        progreso=lambda f, texto: avances.append(f))
        self.assertEqual(avances[-1], 1.0)
        self.assertEqual(sorted(avances), avances)
        self.assertEqual(len(r.curvas), 5)
        self.assertEqual(sorted(c for c, _ in r.curvas), [100.0, 100.5, 101.0, 101.5, 102.0])
        self.assertAlmostEqual(r.cota_min, 100.0, delta=0.02)
        self.assertAlmostEqual(r.cota_max, 102.0, delta=0.02)
        self.assertEqual(r.avisos, [])
        terreno = self.terreno(r)
        azar = random.Random(7)
        for _ in range(300):
            x, y = X0 + azar.uniform(1, 299), Y0 + azar.uniform(1, 99)
            self.assertAlmostEqual(terreno.cota(x, y), cota_plano(x, y), delta=1e-3, msg=(x, y))
        # Fuera de las curvas (más allá del TIN o lejos): sin cota
        self.assertIsNone(terreno.cota(X0 + 150, Y0 + 140))
        self.assertIsNone(terreno.cota(X0 - 50, Y0 + 50))
        self.assertNotEqual(NODATA, terreno.cota(X0 + 150, Y0 + 50))

    def test_distancia_maxima(self):
        """Con curvas cada 25 m y 5 m de distancia máxima, el medio entre dos curvas queda sin cota."""
        from riegolibre_escritorio.topografia import generar_dem

        r = generar_dem(self.ruta, ["CV", "CVD"], paso_m=1.0, distancia_max_m=5.0)
        terreno = self.terreno(r)
        self.assertIsNone(terreno.cota(X0 + 150, Y0 + 12.5))
        self.assertAlmostEqual(terreno.cota(X0 + 150, Y0 + 2.5), cota_plano(0, Y0 + 2.5), delta=1e-3)
        self.assertLess(r.cobertura, 0.6)

    def test_polilinea_3d_y_errores(self):
        from riegolibre_escritorio.topografia import generar_dem

        r = generar_dem(self.ruta, ["CV", "CVD", "CV3D"], paso_m=2.0, distancia_max_m=30.0)
        self.assertIn(None, [c for c, _ in r.curvas])  # la polilínea 3D no tiene una sola cota
        self.assertAlmostEqual(self.terreno(r).cota(X0 + 302, Y0 + 50), cota_plano(0, Y0 + 50), delta=1e-3)
        with self.assertRaisesRegex(ValueError, "no tienen líneas con elevación"):
            generar_dem(self.ruta, ["LINDERO"])
        with self.assertRaisesRegex(ValueError, "al menos una capa"):
            generar_dem(self.ruta, [])
        with self.assertRaisesRegex(ValueError, "misma cota"):
            generar_dem(self.ruta, ["CVD"])
        with self.assertRaisesRegex(ValueError, "millones de celdas"):
            generar_dem(self.ruta, ["CV", "CVD"], paso_m=0.01)

    def test_curvas_comprimidas_y_equidistancia(self):
        from riegolibre_escritorio.topografia import curvas_a_bytes, curvas_de_bytes, equidistancia, generar_dem

        r = generar_dem(self.ruta, ["CV", "CVD"], paso_m=2.0)
        vuelta = curvas_de_bytes(curvas_a_bytes(r.curvas))
        self.assertEqual([c for c, _ in vuelta], [c for c, _ in r.curvas])
        self.assertEqual(len(vuelta[0][1]), len(r.curvas[0][1]))
        self.assertAlmostEqual(vuelta[0][1][3][0], r.curvas[0][1][3][0], delta=0.005)
        self.assertEqual(equidistancia(r.curvas), 0.5)
        self.assertIsNone(equidistancia([(100.0, [])]))


@unittest.skipUnless(HAY_LIBRERIAS, "requiere ezdxf, numpy y scipy")
class PruebasProyectoConCurvas(unittest.TestCase):
    def setUp(self):
        from riegolibre_escritorio.topografia import curvas_a_bytes, generar_dem

        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        ruta = escribir_dxf(os.path.join(self.carpeta.name, "curvas.dxf"))
        r = generar_dem(ruta, ["CV", "CVD"], paso_m=1.0)
        self.rejilla, self.curvas = r.rejilla, curvas_a_bytes(r.curvas)

    def proyecto(self, datos=None, archivos=None):
        from riegolibre_escritorio.modelo import ProyectoRiego

        p = ProyectoRiego(datos or datos_prueba(), archivos)
        self.addCleanup(p.cerrar)
        return p

    def test_lotes_con_el_dem_de_las_curvas(self):
        from riegolibre_escritorio import archivo

        p = self.proyecto()
        p.datos = p.datos_con_curvas(self.rejilla, self.curvas, {"origen": "curvas.dxf"})
        terreno = p.datos["terreno"]
        self.assertEqual(terreno["tipo"], "dem")
        self.assertTrue(terreno["archivo"].endswith(".rdem") and terreno["curvas"].endswith(".json.gz"))
        p.disenar()
        self.assertEqual(p.errores, [])
        self.assertAlmostEqual(p.terreno.cota(X0 + 30, Y0 + 15), cota_plano(0, Y0 + 15), delta=1e-3)
        self.assertEqual(len(p.curvas), 5)
        # Las mismas presiones que con el plano exacto del motor
        plano = self.proyecto({**datos_prueba(), "terreno": {"tipo": "plano", "cota_m": COTA_0, "origen": [X0, Y0],
                                                             "pendiente_y": PENDIENTE}})
        plano.disenar()
        for a, b in zip(p.subunidades, plano.subunidades):
            self.assertAlmostEqual(a.resumen()["presion_valvula_m"], b.resumen()["presion_valvula_m"], delta=0.01)
        # La extensión incluye las curvas (300 m de ancho, más que los lotes)
        self.assertGreaterEqual(p.extension()[2], X0 + 300)

        # Guardar: solo los archivos del terreno de ahora
        p.archivos["dem_viejo.rdem"] = b"x"
        ruta = os.path.join(self.carpeta.name, "con_curvas.riegolibre")
        archivo.guardar(p, ruta)
        abierto = archivo.abrir(ruta)
        self.addCleanup(abierto.cerrar)
        self.assertEqual(set(abierto.archivos), {terreno["archivo"], terreno["curvas"]})
        self.assertEqual(len(abierto.curvas), 5)
        self.assertEqual([s.resumen() for s in abierto.subunidades], [s.resumen() for s in p.subunidades])

    def test_sin_curvas(self):
        p = self.proyecto()
        self.assertEqual(p.curvas, [])
        self.assertEqual(p.archivos_en_uso(), {})


@unittest.skipUnless(HAY_LIBRERIAS and HAY_PYSIDE, "requiere ezdxf, numpy, scipy y PySide6")
class PruebasVentanaTerreno(unittest.TestCase):
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
        self.ruta = escribir_dxf(os.path.join(self.carpeta.name, "curvas.dxf"))

    def test_dialogo_marca_las_capas_con_cota(self):
        from riegolibre_escritorio.dialogo_terreno import DialogoCurvas
        from riegolibre_escritorio.topografia import leer_dxf
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialogButtonBox

        dialogo = DialogoCurvas(self.ruta, leer_dxf(self.ruta), self.v.proyecto.extension())
        self.addCleanup(dialogo.deleteLater)
        self.assertEqual(set(dialogo.capas_elegidas()), {"CV", "CVD", "CV3D"})
        aceptar = dialogo.botones.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(aceptar.isEnabled())
        for fila in range(dialogo.tabla.rowCount()):
            dialogo.tabla.item(fila, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(aceptar.isEnabled())
        self.assertIn("al menos una capa", dialogo.aviso.text())
        # Un dibujo en otra zona UTM: aviso
        lejos = DialogoCurvas(self.ruta, leer_dxf(self.ruta), (X0 + 900_000, Y0, X0 + 900_100, Y0 + 100))
        self.addCleanup(lejos.deleteLater)
        self.assertIn("misma zona UTM", lejos.aviso.text())

    def test_importar_curvas_y_deshacer(self):
        from PySide6.QtWidgets import QDialog

        v = self.v
        presiones_llano = [s.resumen()["presion_valvula_m"] for s in v.proyecto.subunidades]
        with mock.patch.object(self.ventana_modulo.DialogoCurvas, "exec", return_value=QDialog.DialogCode.Accepted):
            v.importar_curvas(self.ruta)
        self.mensajes.warning.assert_not_called()
        terreno = v.proyecto.datos["terreno"]
        self.assertEqual((terreno["tipo"], terreno["origen"]), ("dem", "curvas.dxf"))
        self.assertEqual(set(terreno["capas"]), {"CV", "CVD", "CV3D"})
        self.assertEqual(len(v.proyecto.curvas), 6)
        from riegolibre_escritorio.lienzo import texto_curva

        curvas = v.lienzo.capas["CURVAS_NIVEL"].elementos
        self.assertEqual(len(curvas), 1)  # todas en un solo elemento
        self.assertEqual(len(curvas[0].cotas), 6)  # una por cota, más la polilínea 3D
        sobre = v.lienzo.a_escena(X0 + 150, Y0 + 0.3)  # la curva de 100 m pasa por y = Y0
        cerca = curvas[0].cota_cerca(sobre.x(), sobre.y(), 1.0)
        self.assertEqual(texto_curva(*cerca), "Curva de nivel 100 m (maestra)")
        self.assertIsNone(curvas[0].cota_cerca(sobre.x(), sobre.y() - 10, 1.0))  # entre dos curvas, lejos
        self.assertIn("Curvas de nivel: 6 curvas", v.statusBar().currentMessage())
        self.assertNotEqual([s.resumen()["presion_valvula_m"] for s in v.proyecto.subunidades], presiones_llano)

        v.deshacer()
        self.assertNotEqual((v.proyecto.datos.get("terreno") or {}).get("tipo"), "dem")
        self.assertEqual(v.lienzo.capas["CURVAS_NIVEL"].elementos, [])
        v.rehacer()
        self.assertEqual(v.proyecto.datos["terreno"], terreno)
        self.assertEqual(len(v.lienzo.capas["CURVAS_NIVEL"].elementos[0].cotas), 6)

        v.quitar_terreno()
        self.assertNotIn("terreno", v.proyecto.datos)
        self.assertEqual(v.lienzo.capas["CURVAS_NIVEL"].elementos, [])

    def test_dxf_que_no_se_lee(self):
        malo = os.path.join(self.carpeta.name, "malo.dxf")
        with open(malo, "w", encoding="utf-8") as salida:
            salida.write("esto no es un DXF")
        self.v.importar_curvas(malo)
        self.mensajes.warning.assert_called_once()
        self.assertIn("No se pudo leer el DXF", self.mensajes.warning.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
