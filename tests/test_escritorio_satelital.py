# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Imagen satelital de fondo del programa de escritorio, sin red: UTM ↔ geográficas contra PROJ, teselas,
reproyección, descarga simulada (`mock`), imagen dentro del proyecto (deshacer, guardar y abrir) y la capa
IMAGEN_SATELITAL de la ventana.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

from riegolibre_escritorio import archivo
from riegolibre_escritorio.capas import CAPAS
from riegolibre_escritorio.modelo import ProyectoRiego
from tests.test_escritorio import X0, Y0, datos_prueba

try:
    import numpy as np
    HAY_NUMPY = True
except ImportError:
    HAY_NUMPY = False

try:
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules
except ImportError:
    HAY_PYSIDE = False

# (lon, lat, zona, sur, este, norte): valores de PROJ 9 (pyproj 3.8, EPSG:4326 → EPSG:327xx / 326xx)
REFERENCIAS = [
    (-80.95, -8.85, 17, True, 505497.9452093709, 9021730.968547013),
    (-81.0, -0.5, 17, True, 500000.0, 9944734.96285735),
    (-83.9, -15.0, 17, True, 188112.22086132225, 8339629.871097693),  # 2.9° al oeste del meridiano central
    (-74.0, 4.6, 18, False, 610924.517533402, 508526.8063466239),
    (-77.5, 12.0, 18, False, 227772.82073268626, 1327789.0187308986),
]


@unittest.skipUnless(HAY_NUMPY, "requiere numpy")
class PruebasConversion(unittest.TestCase):
    def test_geograficas_a_utm_contra_proj(self):
        from riegolibre_escritorio.satelital import geograficas_a_utm
        for lon, lat, zona, sur, este, norte in REFERENCIAS:
            e, n = geograficas_a_utm(lon, lat, zona, sur)
            self.assertAlmostEqual(e, este, delta=0.001)
            self.assertAlmostEqual(n, norte, delta=0.001)

    def test_utm_a_geograficas_contra_proj(self):
        from riegolibre_escritorio.satelital import utm_a_geograficas
        for lon, lat, zona, sur, este, norte in REFERENCIAS:
            lo, la = utm_a_geograficas(este, norte, zona, sur)
            # 1e-8° son ~1 mm
            self.assertAlmostEqual(lo, lon, delta=1e-8)
            self.assertAlmostEqual(la, lat, delta=1e-8)

    def test_ida_y_vuelta_con_matrices(self):
        from riegolibre_escritorio.satelital import geograficas_a_utm, utm_a_geograficas
        este, norte = np.meshgrid(np.linspace(300000, 700000, 9), np.linspace(8.5e6, 9.9e6, 7))
        lon, lat = utm_a_geograficas(este, norte, 17, True)
        e2, n2 = geograficas_a_utm(lon, lat, 17, True)
        self.assertLess(np.abs(e2 - este).max(), 0.001)
        self.assertLess(np.abs(n2 - norte).max(), 0.001)


@unittest.skipUnless(HAY_NUMPY, "requiere numpy")
class PruebasTeselas(unittest.TestCase):
    def test_indices_de_tesela(self):
        from riegolibre_escritorio.satelital import tesela
        self.assertEqual(tesela(0.0, 0.0, 1), (1, 1))
        self.assertEqual(tesela(-179.99, 85.0, 5), (0, 0))
        self.assertEqual(tesela(-80.95, -8.85, 18), (72126, 137542))
        self.assertEqual(tesela(-77.03, -12.04, 15), (9372, 17488))

    def test_resolucion_y_zoom(self):
        from riegolibre_escritorio.satelital import metros_por_pixel, zoom_para_resolucion
        self.assertAlmostEqual(metros_por_pixel(0.0, 0), 156543.03392)
        self.assertAlmostEqual(metros_por_pixel(60.0, 1), 156543.03392 / 4, places=4)
        zoom = zoom_para_resolucion(-8.85, 0.5, 20)
        self.assertLessEqual(metros_por_pixel(-8.85, zoom), 0.5)
        self.assertGreater(metros_por_pixel(-8.85, zoom - 1), 0.5)
        self.assertEqual(zoom_para_resolucion(-8.85, 0.01, 19), 19)  # no pasa del zoom de la fuente

    def test_cuadricula_y_teselas_necesarias(self):
        from riegolibre_escritorio.satelital import cuadricula, teselas_necesarias, tesela, utm_a_geograficas
        c = cuadricula((505000.3, 9021000.2, 506000.1, 9022000.0), 0.5)
        self.assertEqual((c.xmin, c.ymax, c.columnas, c.filas), (505000.0, 9022000.0, 2001, 2000))
        self.assertEqual(c.esquinas, [505000.0, 9021000.0, 506000.5, 9022000.0])
        tx0, ty0, tx1, ty1 = teselas_necesarias(c, 17, True, 17)
        for este, norte in ((505000, 9021000), (506000.5, 9022000), (505500, 9021500)):
            tx, ty = tesela(*utm_a_geograficas(este, norte, 17, True), 17)
            self.assertTrue(tx0 <= tx <= tx1 and ty0 <= ty <= ty1)
        self.assertLessEqual((tx1 - tx0 + 1) * (ty1 - ty0 + 1), 16)  # 1 km a ~1.2 m por píxel: 3.3 teselas
        with self.assertRaises(ValueError):
            cuadricula((1, 1, 1, 2), 0.5)

    def test_reproyeccion_ubica_cada_pixel(self):
        """Mosaico cuyo valor es la coordenada global de cada píxel: la imagen UTM debe tener, en cada píxel,
        la coordenada Web Mercator de su centro (bilineal de una función lineal: exacto)."""
        from riegolibre_escritorio import satelital as s
        zoom, zona, sur = 18, 17, True
        c = s.cuadricula((505400, 9021650, 505600, 9021800), 0.5)
        tx0, ty0, tx1, ty1 = s.teselas_necesarias(c, zona, sur, zoom)
        alto, ancho = (ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256
        gy, gx = np.mgrid[0:alto, 0:ancho].astype(float)
        mosaico = np.dstack([gx + tx0 * 256 + 0.5, gy + ty0 * 256 + 0.5, np.zeros_like(gx)])
        salida = s.reproyectar(mosaico, tx0, ty0, zoom, c, zona, sur)
        self.assertEqual(salida.shape, (c.filas, c.columnas, 3))
        # El punto de referencia de PROJ (-80.95, -8.85) cae en el píxel de 505497.95, 9021730.97
        col = int((505497.9452093709 - c.xmin) / c.resolucion_m)
        fila = int((c.ymax - 9021730.968547013) / c.resolucion_m)
        centro_e, centro_n = c.xmin + (col + 0.5) * 0.5, c.ymax - (fila + 0.5) * 0.5
        lon, lat = s.utm_a_geograficas(centro_e, centro_n, zona, sur)
        lado = 256 * 2 ** zoom
        esperado_x = (lon + 180) / 360 * lado
        esperado_y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * lado
        self.assertAlmostEqual(salida[fila, col, 0], esperado_x, delta=1e-4)
        self.assertAlmostEqual(salida[fila, col, 1], esperado_y, delta=1e-4)
        # Y el punto de PROJ queda a menos de medio píxel UTM del centro de ese píxel
        px, py = s.pixel_global(-80.95, -8.85, zoom)
        metros = s.metros_por_pixel(-8.85, zoom)
        self.assertLess(math.hypot(px - esperado_x, py - esperado_y) * metros, 0.5 * math.sqrt(2) * 0.5 + 0.01)
        # Norte arriba: las filas de abajo tienen Y de Web Mercator mayor (más al sur)
        self.assertTrue((np.diff(salida[:, 0, 1]) > 0).all())
        self.assertTrue((np.diff(salida[0, :, 0]) > 0).all())

    def test_archivo_de_mundo(self):
        from riegolibre_escritorio.satelital import leer_archivo_mundo
        esquinas = leer_archivo_mundo("0.5\n0\n0\n-0.5\n600000.25\n9000099.75\n", 400, 200)
        self.assertEqual(esquinas, [600000.0, 9000000.0, 600200.0, 9000100.0])
        with self.assertRaises(ValueError):
            leer_archivo_mundo("0.5\n0.1\n0\n-0.5\n600000\n9000000\n", 10, 10)  # girada
        with self.assertRaises(ValueError):
            leer_archivo_mundo("hola", 10, 10)


def tesela_falsa(tx, ty):
    """Contenido de una tesela simulada: su índice, para que el decodificador falso la pinte."""
    return f"{tx},{ty}".encode()


def decodificar_falso(contenido):
    tx, ty = (int(v) for v in contenido.decode().split(","))
    tesela = np.zeros((256, 256, 3), np.uint8)
    tesela[:, :, 0] = tx % 256
    tesela[:, :, 1] = ty % 256
    tesela[:, :, 2] = 100
    return tesela


class ServidorFalso:
    """Simula Google (imagen hasta `zoom_max`, 404 más allá) o Esri (tilemap)."""

    def __init__(self, zoom_max=19, sin_red=False, faltan=()):
        self.zoom_max, self.sin_red, self.faltan = zoom_max, sin_red, set(faltan)
        self.pedidas = []

    def __call__(self, url):
        self.pedidas.append(url)
        if self.sin_red:
            raise OSError("sin conexión")
        if "tilemap" in url:
            z = int(url.split("/tilemap/")[1].split("/")[0])
            return json.dumps({"data": [1 if z <= self.zoom_max else 0]}).encode(), "application/json"
        if "mt1.google.com" in url:
            partes = dict(p.split("=") for p in url.split("/vt/")[1].split("&"))
            tx, ty, z = int(partes["x"]), int(partes["y"]), int(partes["z"])
        else:
            z, ty, tx = (int(v) for v in url.rsplit("/tile/", 1)[1].split("/"))
        if z > self.zoom_max or (tx, ty) in self.faltan:
            return None, ""
        return tesela_falsa(tx, ty), "image/jpeg"


ZONA_PRUEBA = (X0, Y0, X0 + 300, Y0 + 200)  # cerca de -80.1°, -8.95° (zona 17 sur)


@unittest.skipUnless(HAY_NUMPY, "requiere numpy")
class PruebasDescarga(unittest.TestCase):
    def descargar(self, servidor, fuente=0, resolucion=0.5, avance=None):
        from riegolibre_escritorio import satelital as s
        with mock.patch.object(s, "descargar", servidor):
            return s.descargar_imagen(s.FUENTES[fuente], ZONA_PRUEBA, resolucion, 17, True, decodificar_falso,
                                      avance)

    def test_descarga_google_y_esri(self):
        from riegolibre_escritorio import satelital as s
        for fuente in (0, 1):
            servidor = ServidorFalso(zoom_max=18)
            imagen = self.descargar(servidor, fuente)
            self.assertEqual(imagen.zoom, 18)  # 0.5 m pediría el 19, pero solo hay hasta el 18
            self.assertTrue(imagen.avisos is not None)
            self.assertEqual(imagen.pixeles.shape, (400, 600, 3))
            self.assertEqual(imagen.faltantes, 0)
            self.assertTrue((imagen.pixeles[:, :, 2] == 100).all())
            # La esquina noroeste de la imagen es de la tesela que contiene ese punto
            tx, ty = s.tesela(*s.utm_a_geograficas(X0 + 0.25, Y0 + 199.75, 17, True), 18)
            self.assertEqual(tuple(imagen.pixeles[0, 0, :2]), (tx % 256, ty % 256))
            descripcion = imagen.descripcion("imagen.jpg")
            self.assertEqual(descripcion["esquinas"], [X0, Y0, X0 + 300, Y0 + 200])
            self.assertEqual((descripcion["zoom"], descripcion["fuente"]), (18, s.FUENTES[fuente].nombre))
            self.assertIn("©", descripcion["atribucion"])
            for url in servidor.pedidas:
                self.assertTrue(url.startswith("https://"))

    def test_resolucion_gruesa_pide_menos_zoom(self):
        imagen = self.descargar(ServidorFalso(zoom_max=19), resolucion=4.0)
        self.assertEqual(imagen.zoom, 16)  # 2.36 m por píxel; el 15 tendría 4.7 m
        self.assertEqual(imagen.avisos, [])

    def test_teselas_que_faltan_quedan_en_gris(self):
        from riegolibre_escritorio import satelital as s
        tx, ty = s.tesela(*s.utm_a_geograficas(X0 + 1, Y0 + 199, 17, True), 18)
        imagen = self.descargar(ServidorFalso(zoom_max=18, faltan=[(tx, ty)]))
        self.assertEqual(imagen.faltantes, 1)
        self.assertEqual(tuple(imagen.pixeles[0, 0]), (s.GRIS_SIN_IMAGEN,) * 3)
        self.assertIn("no tenían imagen", imagen.avisos[-1])

    def test_sin_internet(self):
        with self.assertRaises(ValueError) as error:
            self.descargar(ServidorFalso(sin_red=True))
        self.assertIn("Revise la conexión a internet", str(error.exception))

    def test_sin_imagen_en_la_zona(self):
        with self.assertRaises(ValueError) as error:
            self.descargar(ServidorFalso(zoom_max=10))
        self.assertIn("no tiene imagen de esta zona", str(error.exception))

    def test_cancelar(self):
        from riegolibre_escritorio import satelital as s
        avances = []

        def avance(fraccion, texto):
            avances.append(fraccion)
            return "teselas (2 de" not in texto  # cancela en la segunda tesela

        with self.assertRaises(s.Cancelado):
            self.descargar(ServidorFalso(), avance=avance)
        self.assertTrue(avances)

    def test_imagen_demasiado_grande(self):
        from riegolibre_escritorio import satelital as s
        with self.assertRaises(ValueError) as error:
            s.descargar_imagen(s.FUENTES[0], (0, 0, 10000, 10000), 0.1, 17, True, decodificar_falso)
        self.assertIn("millones de píxeles", str(error.exception))

    def test_descargar_sin_red_real(self):
        """`descargar` convierte el 404 en None y los demás errores en OSError."""
        import urllib.error
        from riegolibre_escritorio import satelital as s

        def falla(codigo):
            def abrir(peticion, timeout):
                self.assertNotIn("@", peticion.get_header("User-agent"))  # sin datos del usuario
                raise urllib.error.HTTPError(peticion.full_url, codigo, "x", {}, None)
            return abrir

        with mock.patch("urllib.request.urlopen", falla(404)):
            self.assertEqual(s.descargar("https://ejemplo/1"), (None, ""))
        with mock.patch("urllib.request.urlopen", falla(500)):
            with self.assertRaises(OSError):
                s.descargar("https://ejemplo/1")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaises(OSError):
                s.descargar("https://ejemplo/1")


class PruebasProyectoConImagen(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)

    def test_imagen_en_el_proyecto_guardar_y_abrir(self):
        p = ProyectoRiego(datos_prueba())
        p.disenar()
        contenido = b"\xff\xd8 imagen jpeg de prueba"
        descripcion = {"esquinas": list(ZONA_PRUEBA), "fuente": "Google Satélite", "zoom": 19,
                       "fecha": "2026-11-27", "atribucion": "© Google"}
        datos = p.datos_con_imagen(contenido, descripcion)
        self.assertIsNone(p.imagen)  # los datos nuevos los aplica la ventana
        nombre = datos["imagen"]["archivo"]
        self.assertTrue(nombre.startswith("imagen_") and nombre.endswith(".jpg"))
        self.assertNotIn(nombre, p.archivos_en_uso())
        p.datos = datos
        self.assertEqual(p.imagen["fuente"], "Google Satélite")
        self.assertEqual(p.archivos_en_uso()[nombre], contenido)
        self.assertEqual(p.extension(), ProyectoRiego(datos_prueba()).extension())  # la imagen no la agranda

        ruta = os.path.join(self.carpeta.name, "con_imagen.riegolibre")
        p.estilos_capas["IMAGEN_SATELITAL"]["transparencia"] = 40
        archivo.guardar(p, ruta)
        abierto = archivo.abrir(ruta)
        self.addCleanup(abierto.cerrar)
        self.assertEqual(abierto.datos["imagen"], datos["imagen"])
        self.assertEqual(abierto.archivos[nombre], contenido)
        self.assertEqual(abierto.estilos_capas["IMAGEN_SATELITAL"]["transparencia"], 40)

        # Otra imagen: la anterior queda para deshacer, pero no se guarda
        p.datos = p.datos_con_imagen(b"otra", descripcion, ".png")
        self.assertNotIn(nombre, p.archivos_en_uso())
        self.assertIn(nombre, p.archivos)

    def test_proyecto_solo_con_imagen(self):
        p = ProyectoRiego({"nombre": "Vacío", "lotes": [], "epsg": 32717})
        p.datos = p.datos_con_imagen(b"x", {"esquinas": list(ZONA_PRUEBA)})
        self.assertEqual(p.extension(), ZONA_PRUEBA)


@unittest.skipUnless(HAY_NUMPY and HAY_PYSIDE, "requiere numpy y PySide6")
class PruebasVentanaImagen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from riegolibre_escritorio import satelital, ventana
        from riegolibre_escritorio.dialogo_satelital import codificar_jpeg

        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        parche = mock.patch.object(ventana, "QMessageBox")
        self.mensajes = parche.start()
        self.addCleanup(parche.stop)
        self.ventana_modulo = ventana
        self.v = ventana.VentanaPrincipal()
        self.addCleanup(self.v.deleteLater)
        self.v._cambiar_proyecto(ProyectoRiego(datos_prueba()), False)

        # Teselas de verdad (JPEG de Qt) con un color por tesela
        cache = {}

        def servidor(url):
            contenido, tipo = ServidorFalso(zoom_max=18)(url)
            if contenido and tipo == "image/jpeg":
                if contenido not in cache:
                    cache[contenido] = codificar_jpeg(decodificar_falso(contenido), 95)
                contenido = cache[contenido]
            return contenido, tipo

        parche = mock.patch.object(satelital, "descargar", servidor)
        parche.start()
        self.addCleanup(parche.stop)

    def descargar(self):
        from PySide6.QtWidgets import QDialog
        with mock.patch.object(self.ventana_modulo.DialogoSatelital, "exec",
                               return_value=QDialog.DialogCode.Accepted):
            self.v.imagen_satelital()
        self.mensajes.warning.assert_not_called()

    def test_dialogo(self):
        from riegolibre_escritorio.dialogo_satelital import DialogoSatelital
        from PySide6.QtWidgets import QDialogButtonBox

        extension = self.v.proyecto.extension()
        dialogo = DialogoSatelital(extension, 17, True)
        self.addCleanup(dialogo.deleteLater)
        zona = dialogo.zona_utm()
        self.assertEqual(zona, (extension[0] - 50, extension[1] - 50, extension[2] + 50, extension[3] + 50))
        dialogo.caja_margen.setValue(100)
        self.assertEqual(dialogo.zona_utm()[0], extension[0] - 100)
        self.assertIn("teselas", dialogo.aviso.text())
        aceptar = dialogo.botones.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(aceptar.isEnabled())
        dialogo.cajas_zona[2].setValue(extension[0] + 50_000)
        dialogo.caja_resolucion.setValue(0.1)
        self.assertFalse(aceptar.isEnabled())
        self.assertIn("millones de píxeles", dialogo.aviso.text())

    def test_descargar_ocultar_transparencia_deshacer_y_quitar(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QGraphicsPixmapItem

        v = self.v
        self.assertFalse(v.acciones["quitar_imagen"].isEnabled())
        self.descargar()
        imagen = v.proyecto.imagen
        self.assertIsNotNone(imagen)
        self.assertEqual(imagen["zoom"], 18)
        self.assertIn("Imagen de «Google Satélite», zoom 18", v.statusBar().currentMessage())
        self.assertTrue(v.acciones["quitar_imagen"].isEnabled())
        self.assertEqual(list(v.lienzo.capas)[-1], "IMAGEN_SATELITAL")
        elementos = v.lienzo.capas["IMAGEN_SATELITAL"].elementos
        self.assertEqual(len(elementos), 1)
        item = elementos[0]
        self.assertIsInstance(item, QGraphicsPixmapItem)
        self.assertLess(item.zValue(), min(e.zValue() for c in v.lienzo.capas.values() for e in c.elementos
                                           if e is not item))
        # En su lugar: las esquinas de la escena son las esquinas UTM de la imagen
        xmin, ymin, xmax, ymax = imagen["esquinas"]
        caja = item.sceneBoundingRect()
        for punto_escena, esperado in ((caja.topLeft(), (xmin, ymax)), (caja.bottomRight(), (xmax, ymin))):
            x, y = v.lienzo.de_escena(punto_escena)
            self.assertAlmostEqual(x, esperado[0], delta=1e-6)
            self.assertAlmostEqual(y, esperado[1], delta=1e-6)
        lotes = v.proyecto.extension()
        self.assertTrue(xmin <= lotes[0] and ymin <= lotes[1] and xmax >= lotes[2] and ymax >= lotes[3])
        self.assertIn("Google Satélite",
                      v.barra_capas.tabla.item(list(CAPAS).index("IMAGEN_SATELITAL"), 1).toolTip())

        # Ojo de la barra de capas
        barra = v.barra_capas
        fila = list(CAPAS).index("IMAGEN_SATELITAL")
        barra.tabla.item(fila, 2).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(item.isVisible())
        barra.tabla.item(fila, 2).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(v.lienzo.capas["IMAGEN_SATELITAL"].elementos[0].isVisible())
        barra.tabla.item(fila, 3).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(v.proyecto.estilos_capas["IMAGEN_SATELITAL"]["imprimir"])

        # Transparencia en «Propiedades de la capa» (sin color ni grosor)
        barra.tabla.setCurrentCell(fila, 1)
        self.assertFalse(barra.formulario.isRowVisible(barra.boton_color))
        self.assertTrue(barra.formulario.isRowVisible(barra.caja_transparencia))
        barra.caja_transparencia.setValue(60)
        self.assertEqual(v.proyecto.estilos_capas["IMAGEN_SATELITAL"]["transparencia"], 60)
        self.assertAlmostEqual(v.lienzo.capas["IMAGEN_SATELITAL"].elementos[0].opacity(), 0.4, places=6)
        barra.tabla.setCurrentCell(list(CAPAS).index("LOTES"), 1)
        self.assertTrue(barra.formulario.isRowVisible(barra.boton_color))
        self.assertFalse(barra.formulario.isRowVisible(barra.caja_transparencia))

        # Guardar y abrir sin internet
        ruta = os.path.join(self.carpeta.name, "imagen.riegolibre")
        self.assertTrue(v._guardar_en(ruta))
        from riegolibre_escritorio import satelital
        with mock.patch.object(satelital, "descargar", side_effect=AssertionError("no debe usar la red")):
            v.abrir(ruta)
        self.mensajes.warning.assert_not_called()
        self.assertEqual(v.proyecto.imagen, imagen)
        self.assertEqual(len(v.lienzo.capas["IMAGEN_SATELITAL"].elementos), 1)
        self.assertAlmostEqual(v.lienzo.capas["IMAGEN_SATELITAL"].elementos[0].opacity(), 0.4, places=6)

        # Deshacer, rehacer y quitar
        self.descargar()  # otra vez, para tener algo que deshacer en el proyecto abierto
        v.quitar_imagen()
        self.assertIsNone(v.proyecto.imagen)
        self.assertEqual(v.lienzo.capas["IMAGEN_SATELITAL"].elementos, [])
        v.deshacer()
        self.assertEqual(len(v.lienzo.capas["IMAGEN_SATELITAL"].elementos), 1)
        v.deshacer()  # la segunda descarga (igual a la primera): vuelve la del archivo
        v.deshacer()
        self.assertEqual(v.proyecto.imagen, imagen)
        v.rehacer()
        v.rehacer()
        self.assertIsNone(v.proyecto.imagen)

    def test_error_de_red(self):
        from riegolibre_escritorio import satelital
        with mock.patch.object(satelital, "descargar", side_effect=OSError("sin red")):
            from PySide6.QtWidgets import QDialog
            with mock.patch.object(self.ventana_modulo.DialogoSatelital, "exec",
                                   return_value=QDialog.DialogCode.Accepted):
                self.v.imagen_satelital()
        self.mensajes.warning.assert_called_once()
        self.assertIn("Revise la conexión a internet", self.mensajes.warning.call_args[0][2])
        self.assertIsNone(self.v.proyecto.imagen)

    def test_sin_zona_utm(self):
        self.v._cambiar_proyecto(ProyectoRiego({"nombre": "Sin EPSG", "lotes": []}), False)
        self.v.imagen_satelital()
        self.assertIn("zona UTM", self.mensajes.warning.call_args[0][2])

    def test_imagen_propia_con_archivo_de_mundo(self):
        from PySide6.QtGui import QColor, QImage

        ruta = os.path.join(self.carpeta.name, "dron.png")
        imagen = QImage(40, 20, QImage.Format.Format_RGB32)
        imagen.fill(QColor("#336699"))
        self.assertTrue(imagen.save(ruta))
        with open(os.path.join(self.carpeta.name, "dron.pgw"), "w", encoding="utf-8") as mundo:
            mundo.write(f"2.5\n0\n0\n-2.5\n{X0 + 1.25}\n{Y0 + 48.75}\n")
        self.v.imagen_propia(ruta)
        self.mensajes.warning.assert_not_called()
        imagen = self.v.proyecto.imagen
        self.assertEqual(imagen["esquinas"], [X0, Y0, X0 + 100, Y0 + 50])
        self.assertTrue(imagen["archivo"].endswith(".png"))
        caja = self.v.lienzo.capas["IMAGEN_SATELITAL"].elementos[0].sceneBoundingRect()
        self.assertAlmostEqual(caja.width(), 100)
        self.assertAlmostEqual(caja.height(), 50)

        sin_mundo = os.path.join(self.carpeta.name, "suelta.png")
        QImage(4, 4, QImage.Format.Format_RGB32).save(sin_mundo)
        self.v.imagen_propia(sin_mundo)
        self.assertIn("archivo de mundo", self.mensajes.warning.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
