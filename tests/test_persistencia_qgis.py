"""Pruebas del guardado automático de las capas en el GeoPackage del proyecto (requieren QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import (QgsFeature, QgsGeometry, QgsGraduatedSymbolRenderer, QgsPointXY, QgsProject,
                           QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer)

    from riegolibre.integracion import persistencia
    from riegolibre.integracion.subunidad_mapa import PROPIEDAD


def _capa(nombre, propiedad="resultado"):
    capa = QgsVectorLayer("LineString?crs=EPSG:32717&field=tuberia:string(80)&field=longitud:double",
                          nombre, "memory")
    entidades = []
    for i in range(3):
        e = QgsFeature(capa.fields())
        e.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(X0, Y0 + i), QgsPointXY(X0 + 50, Y0 + i)]))
        e.setAttributes([f"PE 16 mm · {i}", 50.0 + i])
        entidades.append(e)
    capa.dataProvider().addFeatures(entidades)
    capa.setRenderer(QgsGraduatedSymbolRenderer("longitud"))
    if propiedad:
        capa.setCustomProperty(PROPIEDAD, propiedad)
    return capa


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasPersistencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # OGR deja abierto el gpkg
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()
        self.proyecto.setFileName(os.path.join(self.carpeta.name, "diseño fruveg.qgz"))

    def tearDown(self):
        self.proyecto.clear()
        self.carpeta.cleanup()

    def test_nombre_de_tabla(self):
        self.assertEqual(persistencia.nombre_tabla("Laterales · Lote 32"), "laterales_lote_32")
        self.assertEqual(persistencia.nombre_tabla("Válvula · Lote 32"), "valvula_lote_32")
        self.assertEqual(persistencia.nombre_tabla("···"), "capa")

    def test_guarda_las_capas_de_riegolibre_con_su_estilo(self):
        capa = _capa("Laterales · Lote 32")
        capa.setCustomProperty("riegolibre/laterales", "{}")
        ajena = _capa("Mi capa", propiedad=None)
        previa = _capa("Laterales (vista previa)", propiedad="vista_previa")
        self.proyecto.addMapLayers([capa, ajena, previa])

        self.assertEqual(persistencia.guardar_capas_temporales(), ["Laterales · Lote 32"])
        ruta = os.path.join(self.carpeta.name, "diseño fruveg_riegolibre.gpkg")
        self.assertTrue(os.path.exists(ruta))
        self.assertEqual(capa.providerType(), "ogr")
        self.assertIn("layername=laterales_lote_32", capa.source())
        self.assertEqual(capa.name(), "Laterales · Lote 32")
        self.assertEqual(capa.featureCount(), 3)
        self.assertEqual(sorted(e["longitud"] for e in capa.getFeatures()), [50.0, 51.0, 52.0])
        self.assertIsInstance(capa.renderer(), QgsGraduatedSymbolRenderer)
        self.assertEqual(capa.customProperty(PROPIEDAD), "resultado")
        self.assertEqual(capa.customProperty("riegolibre/laterales"), "{}")
        self.assertEqual(ajena.providerType(), "memory")
        self.assertEqual(previa.providerType(), "memory")
        self.assertEqual(persistencia.guardar_capas_temporales(), [])  # ya no queda nada en memoria

    def test_sin_archivo_de_proyecto_no_guarda(self):
        self.proyecto.setFileName("")
        capa = _capa("Laterales · Lote 1")
        self.proyecto.addMapLayer(capa)
        self.assertEqual(persistencia.guardar_capas_temporales(), [])
        self.assertEqual(capa.providerType(), "memory")

    def test_no_sobrescribe_una_tabla_en_uso_y_si_una_libre(self):
        primera = _capa("Válvula · Lote 5")
        self.proyecto.addMapLayer(primera)
        persistencia.guardar_capas_temporales()
        segunda = _capa("Válvula · Lote 5")
        self.proyecto.addMapLayer(segunda)
        persistencia.guardar_capas_temporales()
        self.assertIn("layername=valvula_lote_5_2", segunda.source())
        self.assertEqual(primera.featureCount(), 3)

        # Al recalcular, el grupo anterior se quita y la tabla queda libre para la capa nueva.
        self.proyecto.removeMapLayer(primera.id())
        tercera = _capa("Válvula · Lote 5")
        self.proyecto.addMapLayer(tercera)
        persistencia.guardar_capas_temporales()
        self.assertIn("layername=valvula_lote_5|", tercera.source() + "|")
        self.assertEqual(tercera.featureCount(), 3)

    def test_capas_de_dibujo(self):
        capa = QgsVectorLayer("Polygon?crs=EPSG:32717&field=nombre:string(50)", "Bloques", "memory")
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        capa.setRenderer(QgsSingleSymbolRenderer(simbolo))
        self.proyecto.addMapLayer(capa)
        ruta = persistencia.guardar_capas_de_dibujo([capa])
        self.assertTrue(ruta.endswith("_riegolibre.gpkg"))
        self.assertEqual(capa.providerType(), "ogr")
        self.assertTrue(capa.startEditing())
        e = QgsFeature(capa.fields())
        e["nombre"] = "B1"
        e.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(X0, Y0), QgsPointXY(X0 + 10, Y0),
                                                  QgsPointXY(X0 + 10, Y0 + 10)]]))
        self.assertTrue(capa.addFeature(e))
        self.assertTrue(capa.commitChanges())
        self.assertEqual(capa.featureCount(), 1)
        self.assertIn("Las capas se guardan", persistencia.aviso_html(ruta))


if __name__ == "__main__":
    unittest.main()
