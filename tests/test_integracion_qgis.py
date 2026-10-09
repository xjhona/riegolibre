"""Pruebas que necesitan QGIS (se omiten si no está disponible).

Ejecutar con el Python de QGIS, por ejemplo:
    "C:\\Program Files\\QGIS 3.40.6\\bin\\python-qgis-ltr.bat" -m unittest discover -s tests -t .
"""

import os
import tempfile
import unittest

try:
    from osgeo import gdal, osr
    from qgis.core import (QgsApplication, QgsFeature, QgsGeometry, QgsPointXY,
                           QgsProject, QgsRasterLayer, QgsVectorLayer)
    HAY_QGIS = True
except ImportError:
    HAY_QGIS = False

X0, Y0 = 500000.0, 8500000.0  # origen del DEM (UTM 18S)
PENDIENTE_ESTE = 0.02


def _iniciar_qgis():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], True)
        app.initQgis()
    return app


def _crear_dem(ruta, columnas=200, filas=50):
    """DEM de 1 m que sube 2 cm por metro hacia el este."""
    ds = gdal.GetDriverByName("GTiff").Create(ruta, columnas, filas, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((X0, 1.0, 0, Y0, 0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32718)
    ds.SetProjection(srs.ExportToWkt())
    import numpy
    columnas_centro = numpy.arange(columnas) + 0.5
    datos = numpy.tile(100.0 + PENDIENTE_ESTE * columnas_centro, (filas, 1)).astype("float32")
    ds.GetRasterBand(1).WriteArray(datos)
    ds.FlushCache()
    ds = None


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasIntegracionQgis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta_dem = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta_dem)
        cls.dem = QgsRasterLayer(ruta_dem, "dem")
        assert cls.dem.isValid()

        cls.lineas = QgsVectorLayer("LineString?crs=EPSG:32718", "laterales", "memory")
        entidad = QgsFeature()
        entidad.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(X0 + 10, Y0 - 25), QgsPointXY(X0 + 110, Y0 - 25)]))
        cls.lineas.dataProvider().addFeatures([entidad])
        cls.lineas.updateExtents()
        QgsProject.instance().addMapLayers([cls.dem, cls.lineas])

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def test_extraer_perfil(self):
        from riegolibre.integracion.perfil_terreno import entidad_unica, extraer_perfil
        longitud, perfil = extraer_perfil(self.lineas, entidad_unica(self.lineas), self.dem, paso_m=1.0)
        self.assertAlmostEqual(longitud, 100.0, places=6)
        self.assertEqual(len(perfil), 101)
        for distancia, cota in perfil[1:-1]:
            self.assertAlmostEqual(cota, 100 + PENDIENTE_ESTE * (10 + distancia), delta=0.011)

    def test_dialogo_con_dem(self):
        from riegolibre.gui.dialogo_lateral import DialogoLateral
        from riegolibre.nucleo import Lateral
        dialogo = DialogoLateral(iface=None)
        dialogo.check_terreno.setChecked(True)
        dialogo.combo_linea.setLayer(self.lineas)
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.calcular()
        html = dialogo.texto.toHtml()
        self.assertIn("Presión de entrada", html)
        self.assertAlmostEqual(dialogo.spin_longitud.value(), 100.0, places=1)

        # Con el DEM debe dar lo mismo que con una pendiente uniforme del 2 %.
        lateral = dialogo._crear_lateral()
        con_pendiente = Lateral(lateral.tuberia, lateral.emisor, lateral.espaciamiento_m,
                                lateral.numero_emisores, pendiente=PENDIENTE_ESTE)
        a = lateral.presion_entrada_requerida().presion_entrada_m
        b = con_pendiente.presion_entrada_requerida().presion_entrada_m
        self.assertAlmostEqual(a, b, delta=0.03)

    def test_dialogo_longitud_maxima(self):
        from riegolibre.gui.dialogo_lateral import DialogoLateral
        dialogo = DialogoLateral(iface=None)
        dialogo.calcular_longitud_maxima()
        self.assertIn("Longitud máxima", dialogo.texto.toHtml())

    def test_subunidad_seleccion_automatica(self):
        from riegolibre.gui.dialogo_subunidad import DialogoSubunidad
        dialogo = DialogoSubunidad(iface=None)
        self.assertIsNone(dialogo.combo_tuberia_porta.tuberia())
        dialogo.calcular()
        html = dialogo.panel.texto.toHtml()
        self.assertIn("automática", html)
        self.assertIn("Cumple", html)
        tabla = dialogo.panel.tabla_diametros
        self.assertEqual(tabla.rowCount(), len(dialogo.tuberias_portalateral))
        estados = [tabla.item(f, 6).text() for f in range(tabla.rowCount())]
        primera = next(i for i, e in enumerate(estados) if e.startswith("✔"))
        self.assertTrue(all(e.startswith("✘") for e in estados[:primera]))
        self.assertEqual(dialogo.panel.tabla_laterales.rowCount(), 40)

        # Doble clic en la primera fila: fija esa tubería (que no cumple) y recalcula.
        dialogo.panel._doble_clic_diametro(0, 0)
        self.assertIs(dialogo.combo_tuberia_porta.tuberia(), dialogo.tuberias_portalateral[0])
        self.assertIn("No cumple", dialogo.panel.texto.toHtml())

    def test_subunidad_con_dem_y_entrada_central(self):
        from riegolibre.gui.dialogo_subunidad import DialogoSubunidad
        from riegolibre.nucleo import ENTRADA_CENTRO
        dialogo = DialogoSubunidad(iface=None)
        dialogo.grupo_laterales.combo_emisor.setCurrentIndex(1)  # autocompensado
        dialogo.combo_entrada.setCurrentIndex(dialogo.combo_entrada.findData(ENTRADA_CENTRO))
        dialogo.check_terreno.setChecked(True)
        dialogo.combo_linea.setLayer(self.lineas)
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.calcular()
        self.assertEqual(dialogo.spin_numero.value(), round(100 / 1.5))
        tabla = dialogo.panel.tabla_laterales
        self.assertEqual(tabla.rowCount(), round(100 / 1.5))
        ramas = {tabla.item(f, 0).text() for f in range(tabla.rowCount())}
        self.assertEqual(ramas, {"Hacia el final", "Hacia el inicio"})
        self.assertEqual(dialogo.panel.resultado.emisores_fuera_de_rango, 0)
        self.assertAlmostEqual(dialogo.panel.resultado.presion_min_emisor_m, 5.0, delta=0.01)
        self.assertIn("✔ Cumple", dialogo.panel.texto.toPlainText())

    def test_registro_en_qgis(self):
        from qgis.PyQt.QtWidgets import QMainWindow
        from riegolibre import classFactory

        class IfaceFalsa:
            def __init__(self):
                self.ventana = QMainWindow()
                self.menu, self.barra = [], []

            def mainWindow(self):  # noqa: N802
                return self.ventana

            def addPluginToMenu(self, _menu, accion):  # noqa: N802
                self.menu.append(accion)

            def removePluginMenu(self, _menu, accion):  # noqa: N802
                self.menu.remove(accion)

            def addToolBarIcon(self, accion):  # noqa: N802
                self.barra.append(accion)

            def removeToolBarIcon(self, accion):  # noqa: N802
                self.barra.remove(accion)

        iface = IfaceFalsa()
        plugin = classFactory(iface)
        plugin.initGui()
        self.assertEqual([a.text() for a in iface.menu],
                         ["Calculadora de lateral (goteo)…", "Subunidad de riego (goteo)…",
                          "Diseño de subunidad en el mapa (goteo)…", "Red principal y bomba…"])
        self.assertTrue(all(not a.icon().isNull() for a in iface.menu))
        iface.menu[1].trigger()
        self.assertTrue(plugin.dialogos["subunidad"].isVisible())
        plugin.unload()
        self.assertEqual(iface.menu, [])


if __name__ == "__main__":
    unittest.main()
