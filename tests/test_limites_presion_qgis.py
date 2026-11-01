"""Marcadores de presión mínima y máxima de las subunidades (requieren el Python de QGIS)."""

import os
import tempfile
import unittest
from unittest import mock

from tests.test_bloque_qgis import _escribir_dxf, _fallar
from tests.test_integracion_qgis import HAY_QGIS, _crear_dem, _iniciar_qgis
from tests.test_topografia_qgis import _wkt_utm

if HAY_QGIS:
    from qgis.core import QgsGeometry, QgsProject, QgsRasterLayer


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasLimitesDePresion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.ruta_dxf = os.path.join(cls.carpeta.name, "bloques.dxf")
        _escribir_dxf(cls.ruta_dxf)
        ruta_dem = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta_dem)
        cls.dem = QgsRasterLayer(ruta_dem, "DEM (curvas del CAD)")
        QgsProject.instance().addMapLayer(cls.dem)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.dem = None
        cls.carpeta.cleanup()

    def _lotes_calculados(self):
        """Importa los dos lotes y los calcula con el DEM (el terreno sube al este: las presiones varían)."""
        from riegolibre.gui import dialogo_bloque
        from riegolibre.integracion.lotes import agregar_al_mapa, importar_lotes

        ruta = os.path.join(self.carpeta.name, "limites.gpkg")
        capa = agregar_al_mapa(importar_lotes(self.ruta_dxf, ["_bloques"], _wkt_utm(), ruta).ruta)
        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(None)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.radio_usuario.setChecked(True)
            dialogo.spin_azimut.setValue(90.0)
            dialogo.combo_dem.setLayer(self.dem)
            dialogo.abrir_lote(capa, next(capa.getFeatures()))
            html = dialogo._aplicar_varios(list(capa.getFeatures()))
        self.assertIn("2 de 2", html)
        return capa

    def test_marcadores_de_todas_las_subunidades_y_de_las_seleccionadas(self):
        from riegolibre.integracion import limites_presion as lp

        capa = self._lotes_calculados()
        subunidades = lp.subunidades_calculadas()
        self.assertEqual(sorted(s.nombre for s in subunidades), ["Lote 1", "M7. 6"])

        resumen = lp.mostrar()
        self.assertEqual((resumen.subunidades, resumen.marcadores, resumen.sin_resultados), (2, 4, []))
        marcadores = lp.capa_de_marcadores()
        self.assertEqual(marcadores.featureCount(), 4)
        for sub in subunidades:
            propios = {e["tipo"]: e for e in marcadores.getFeatures() if e["subunidad"] == sub.nombre}
            self.assertEqual(set(propios), {lp.MINIMA, lp.MAXIMA})
            minima = min(e["p_min"] for e in sub.laterales.getFeatures())
            maxima = max(e["p_max"] for e in sub.laterales.getFeatures())
            self.assertAlmostEqual(propios[lp.MINIMA]["presion"], minima, places=2)
            self.assertAlmostEqual(propios[lp.MAXIMA]["presion"], maxima, places=2)
            self.assertLessEqual(propios[lp.MINIMA]["presion"], propios[lp.MAXIMA]["presion"])
            self.assertEqual(propios[lp.MAXIMA]["rotulo"], f"Máx: {maxima:.1f} m")
            # Cada marcador está sobre un lateral de su subunidad
            for entidad in propios.values():
                self.assertTrue(any(entidad.geometry().distance(lateral.geometry()) < 1e-3
                                    for lateral in sub.laterales.getFeatures()))

        # Repetir no duplica
        lp.mostrar()
        self.assertEqual(marcadores.featureCount(), 4)

        # Solo las seleccionadas: sin selección avisa; con un lote seleccionado marca solo ese
        lp.borrar()
        self.assertIsNone(lp.capa_de_marcadores())
        with self.assertRaisesRegex(ValueError, "Seleccione"):
            lp.mostrar(solo_seleccionadas=True)
        lote = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
        capa.selectByIds([lote.id()])
        resumen = lp.mostrar(solo_seleccionadas=True)
        self.assertEqual((resumen.subunidades, resumen.marcadores), (1, 2))
        self.assertEqual({e["subunidad"] for e in lp.capa_de_marcadores().getFeatures()}, {"M7. 6"})
        capa.removeSelection()

        # También por la válvula seleccionada
        valvula = next(s.valvula for s in subunidades if s.nombre == "Lote 1")
        valvula.selectAll()
        resumen = lp.mostrar(solo_seleccionadas=True)
        self.assertEqual(resumen.subunidades, 1)
        self.assertEqual({e["subunidad"] for e in lp.capa_de_marcadores().getFeatures()}, {"M7. 6", "Lote 1"})
        valvula.removeSelection()

        self.assertEqual(lp.borrar(), 4)
        self.assertEqual(lp.borrar(), 0)

    def test_sin_subunidades_calculadas(self):
        from riegolibre.integracion import limites_presion as lp

        for capa in list(QgsProject.instance().mapLayers().values()):
            if capa is not self.dem:
                QgsProject.instance().removeMapLayer(capa.id())
        with self.assertRaisesRegex(ValueError, "No hay subunidades calculadas"):
            lp.mostrar()
        self.assertEqual(lp.borrar(), 0)


if __name__ == "__main__":
    unittest.main()
