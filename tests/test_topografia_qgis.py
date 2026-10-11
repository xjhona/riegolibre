"""Importación de topografía desde un DXF (requieren el Python de QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _iniciar_qgis

if HAY_QGIS:
    from osgeo import gdal, ogr, osr
    from qgis.core import QgsCoordinateReferenceSystem, QgsProject

PENDIENTE = 0.02  # el plano de las curvas sube 2 cm por metro hacia el este
X_CURVAS = list(range(0, 201, 25)) + [600]  # entre 200 y 600 m no hay curvas


def _lwpolyline(capa, puntos, elevacion=None, cerrada=False):
    """LWPOLYLINE como la escribe AutoCAD: la cota va en el código 38, una sola para toda la línea."""
    codigos = ["0", "LWPOLYLINE", "100", "AcDbEntity", "8", capa, "100", "AcDbPolyline",
               "90", str(len(puntos)), "70", "1" if cerrada else "0"]
    if elevacion is not None:
        codigos += ["38", f"{elevacion}"]
    for x, y in puntos:
        codigos += ["10", f"{X0 + x}", "20", f"{Y0 + y}"]
    return codigos


def _escribir_dxf(ruta):
    codigos = ["0", "SECTION", "2", "ENTITIES"]
    for x in X_CURVAS:
        codigos += _lwpolyline("C-TOPO", [(x, 0), (x, 50), (x, 100)], 100 + PENDIENTE * x)
    codigos += _lwpolyline("C-TOPO", [(5, 5), (60, 5)])  # sin elevación: se descarta
    codigos += _lwpolyline("LINDERO", [(10, 10), (190, 10), (190, 90), (10, 90)], cerrada=True)
    codigos += _lwpolyline("COTAS", [(0, -10), (200, -10)])
    codigos += ["0", "ENDSEC", "0", "EOF"]
    with open(ruta, "w", encoding="ascii") as archivo:
        archivo.write("\n".join(codigos) + "\n")


def _cota(ruta_dem, x, y):
    ds = gdal.Open(ruta_dem)
    gt = ds.GetGeoTransform()
    columna, fila = int((X0 + x - gt[0]) / gt[1]), int((Y0 + y - gt[3]) / gt[5])
    banda = ds.GetRasterBand(1)
    valor = float(banda.ReadAsArray(columna, fila, 1, 1)[0, 0])
    return None if valor == banda.GetNoDataValue() else valor


def _wkt_utm():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32718)
    return srs.ExportToWkt()


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasTopografiaCad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.dxf = os.path.join(cls.carpeta.name, "plano prueba.dxf")
        _escribir_dxf(cls.dxf)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.carpeta.cleanup()

    def _salida(self, nombre):
        return os.path.join(self.carpeta.name, nombre)

    def test_leer_capas_y_cotas(self):
        from riegolibre.integracion.topografia_cad import leer_dxf, parecen_coordenadas_planas
        contenido = leer_dxf(self.dxf)
        capas = {c.nombre: c for c in contenido.capas}
        self.assertEqual(set(capas), {"C-TOPO", "LINDERO", "COTAS"})
        self.assertEqual((capas["C-TOPO"].lineas, capas["C-TOPO"].con_cota), (11, 10))
        self.assertAlmostEqual(capas["C-TOPO"].cota_min, 100.0)
        self.assertAlmostEqual(capas["C-TOPO"].cota_max, 112.0)
        self.assertTrue(capas["C-TOPO"].parece_curvas)
        self.assertEqual((capas["LINDERO"].cerradas, capas["LINDERO"].con_cota), (1, 0))
        self.assertFalse(capas["COTAS"].parece_curvas)
        self.assertAlmostEqual(contenido.ancho, 600)
        self.assertTrue(parecen_coordenadas_planas(contenido.extension))

    def test_dem_reproduce_el_plano_y_descarta_zonas_sin_curvas(self):
        from riegolibre.integracion.topografia_cad import generar_topografia
        carpeta = self._salida("dem")
        r = generar_topografia(self.dxf, ["C-TOPO"], _wkt_utm(), carpeta, paso_m=1.0,
                               distancia_max_m=30, capa_lindero="LINDERO")
        self.assertEqual(r.curvas, 10)
        self.assertTrue(any("sin elevación" in a or "no tienen elevación" in a for a in r.avisos), r.avisos)
        self.assertAlmostEqual(r.cota_min, 100.0, places=1)
        self.assertAlmostEqual(r.cota_max, 112.0, places=1)
        # Centro de la celda (110.5, 50.5): el TIN de curvas paralelas reproduce el plano.
        self.assertAlmostEqual(_cota(r.ruta_dem, 110.5, 50.5), 100 + PENDIENTE * 110.5, places=3)
        # A 200 m de la curva más cercana no hay dato; a 20 m sí.
        self.assertIsNone(_cota(r.ruta_dem, 400.5, 50.5))
        self.assertAlmostEqual(_cota(r.ruta_dem, 220.5, 50.5), 100 + PENDIENTE * 220.5, places=3)
        self.assertTrue(r.ruta_dem.endswith("plano prueba_dem.tif"))
        self.assertEqual(osr.SpatialReference(gdal.Open(r.ruta_dem).GetProjection()).GetAuthorityCode(None),
                         "32718")

        # Lindero: polígono cerrado de 180 × 80 m.
        self.assertEqual(r.linderos, 1)
        self.assertAlmostEqual(r.area_lindero_ha, 1.44, places=4)
        gpkg = ogr.Open(r.ruta_curvas)
        self.assertEqual(gpkg.GetLayerByName("lindero").GetFeatureCount(), 1)
        cotas = sorted(f.GetField("cota") for f in gpkg.GetLayerByName("curvas_nivel"))
        self.assertAlmostEqual(cotas[0], 100.0)
        self.assertAlmostEqual(cotas[-1], 112.0)

    def test_mayor_distancia_rellena_el_hueco(self):
        from riegolibre.integracion.topografia_cad import generar_topografia
        r = generar_topografia(self.dxf, ["C-TOPO"], _wkt_utm(), self._salida("hueco"), paso_m=2.0,
                               distancia_max_m=250)
        self.assertAlmostEqual(_cota(r.ruta_dem, 401, 51), 100 + PENDIENTE * 401, places=3)
        self.assertEqual(r.linderos, 0)

    def test_errores_claros(self):
        from riegolibre.integracion.topografia_cad import generar_topografia, leer_dxf
        geograficas = osr.SpatialReference()
        geograficas.ImportFromEPSG(4326)
        with self.assertRaisesRegex(ValueError, "proyectado"):
            generar_topografia(self.dxf, ["C-TOPO"], geograficas.ExportToWkt(), self._salida("e1"))
        with self.assertRaisesRegex(ValueError, "elevación"):
            generar_topografia(self.dxf, ["COTAS"], _wkt_utm(), self._salida("e2"))
        with self.assertRaisesRegex(ValueError, "No se encuentra"):
            leer_dxf(self._salida("no_existe.dxf"))

    def test_ventana_importa_y_agrega_capas(self):
        from qgis.gui import QgsMapCanvas

        from riegolibre.gui.dialogo_topografia import USO_CURVAS, USO_LINDERO, DialogoTopografia

        class Iface:
            lienzo = QgsMapCanvas()

            def mapCanvas(self):  # noqa: N802
                return self.lienzo

        dialogo = DialogoTopografia(Iface())
        dialogo.edit_dxf.setText(self.dxf)
        dialogo.edit_carpeta.setText(self._salida("ventana"))
        dialogo._leer()
        usos = {dialogo.tabla.item(i, 0).text(): dialogo.tabla.cellWidget(i, 3).currentText()
                for i in range(dialogo.tabla.rowCount())}
        self.assertEqual(usos["C-TOPO"], USO_CURVAS)
        self.assertEqual(usos["LINDERO"], USO_LINDERO)
        self.assertFalse(dialogo.boton_importar.isEnabled())  # falta el sistema de coordenadas
        dialogo.selector_crs.setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
        self.assertTrue(dialogo.boton_importar.isEnabled())

        dialogo.importar()
        proyecto = QgsProject.instance()
        grupo = proyecto.layerTreeRoot().findGroup("Topografía · plano prueba")
        self.assertIsNotNone(grupo)
        self.assertEqual(sorted(n.layer().name() for n in grupo.findLayers()),
                         ["Curvas de nivel", "DEM (curvas del CAD)", "Lindero"])
        self.assertIn("Topografía importada", dialogo.etiqueta_resultado.text())
        dem = proyecto.mapLayersByName("DEM (curvas del CAD)")[0]
        self.assertTrue(dem.isValid())
        self.assertEqual(dem.crs().authid(), "EPSG:32718")
