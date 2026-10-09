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


if __name__ == "__main__":
    unittest.main()
