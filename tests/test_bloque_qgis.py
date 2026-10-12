"""Lotes de CAD y bloque de goteo en el mapa (requieren el Python de QGIS)."""

import os
import tempfile
import unittest
from unittest import mock

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _crear_dem, _iniciar_qgis
from tests.test_topografia_qgis import _lwpolyline, _wkt_utm

if HAY_QGIS:
    from qgis.core import QgsPointXY, QgsProject, QgsRasterLayer

LOTE_A = [(10, -45), (90, -45), (90, -5), (10, -5)]  # 80 × 40 m
LOTE_B = [(100, -45), (190, -45), (190, -5), (100, -5)]  # 90 × 40 m, con el texto «M7. 6»


def _texto(capa, x, y, texto):
    return ["0", "TEXT", "100", "AcDbEntity", "8", capa, "100", "AcDbText",
            "10", f"{X0 + x}", "20", f"{Y0 + y}", "30", "0", "40", "2", "1", texto, "100", "AcDbText"]


def _escribir_dxf(ruta):
    codigos = ["0", "SECTION", "2", "ENTITIES"]
    codigos += _lwpolyline("_bloques", LOTE_A, cerrada=True)
    codigos += _lwpolyline("_bloques", LOTE_B, cerrada=True)
    codigos += _lwpolyline("_bloques", [(0, 0), (50, 0)])  # abierta: no es un lote
    codigos += _lwpolyline("OTRA", [(0, 0), (5, 0), (5, 5), (0, 5)], cerrada=True)
    codigos += _texto("TEXTOS", 140, -25, "M7. 6")
    codigos += ["0", "ENDSEC", "0", "EOF"]
    with open(ruta, "w", encoding="ascii") as archivo:
        archivo.write("\n".join(codigos) + "\n")


def _fallar(*args):
    raise AssertionError(f"La ventana mostró un mensaje: {args[2] if len(args) > 2 else args}")


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasLotesYBloque(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # QGIS retiene el GeoPackage
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

    def _importar(self, nombre="lotes.gpkg"):
        from riegolibre.integracion.lotes import agregar_al_mapa, importar_lotes
        ruta = os.path.join(self.carpeta.name, nombre)
        resultado = importar_lotes(self.ruta_dxf, ["_bloques"], _wkt_utm(), ruta)
        return resultado, agregar_al_mapa(resultado.ruta)

    def test_importar_lotes(self):
        from riegolibre.integracion.lotes import capas_de_lotes, es_capa_de_lotes
        resultado, capa = self._importar("importar.gpkg")
        self.assertEqual(resultado.lotes, 2)
        self.assertEqual(resultado.con_nombre, 1)
        self.assertAlmostEqual(resultado.area_ha, (80 * 40 + 90 * 40) / 10000, places=4)
        self.assertTrue(any("no están cerradas" in a for a in resultado.avisos))
        self.assertTrue(es_capa_de_lotes(capa))
        self.assertIn(capa, capas_de_lotes())
        nombres = sorted(e["nombre"] for e in capa.getFeatures())
        self.assertEqual(nombres, ["Lote 1", "M7. 6"])
        with self.assertRaises(ValueError):
            from riegolibre.integracion.lotes import importar_lotes
            importar_lotes(self.ruta_dxf, ["NO_EXISTE"], _wkt_utm(), os.path.join(self.carpeta.name, "x.gpkg"))

    def test_bloque_en_la_ventana_y_subdivision(self):
        from riegolibre.gui import dialogo_bloque
        from riegolibre.gui.herramienta_bloque import lote_en
        from riegolibre.integracion.bloque_mapa import (reemplazar_lote_por_partes, subdividir_en_lote)
        from riegolibre.integracion.lotes import parametros_guardados
        from riegolibre.nucleo.bloque import PORTA_ALTO, VALV_CENTRO
        from riegolibre.nucleo.subdivision import NUMERO, ParametrosSubdivision

        _, capa = self._importar("bloque.gpkg")
        encontrado = lote_en(QgsPointXY(X0 + 50, Y0 - 25), capa.crs())
        self.assertIsNotNone(encontrado)
        _, lote_a = encontrado
        self.assertEqual(lote_a["nombre"], "Lote 1")
        self.assertIsNone(lote_en(QgsPointXY(X0 + 95, Y0 - 25), capa.crs()))

        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar),                 mock.patch.object(clase, "_leer_ultimos", return_value={}),                 mock.patch.object(clase, "_guardar_ultimos"):  # sin tocar los ajustes de QGIS
            dialogo = dialogo_bloque.DialogoBloque(None)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.spin_costados.setValue(1.0)
            dialogo.spin_cabecera.setValue(0.5)
            dialogo.radio_usuario.setChecked(True)
            dialogo.spin_azimut.setValue(90.0)  # laterales hacia el este (el DEM sube 2 % al este)
            dialogo.combo_porta.setCurrentIndex(dialogo.combo_porta.findData(PORTA_ALTO))
            dialogo.combo_valvula.setCurrentIndex(dialogo.combo_valvula.findData(VALV_CENTRO))
            dialogo.combo_dem.setLayer(self.dem)
            dialogo.abrir_lote(capa, lote_a)
            self.assertIsNotNone(dialogo.bloque)
            b = dialogo.bloque
            self.assertEqual(b.hileras, 20)
            self.assertAlmostEqual(b.lateral_mas_largo_m, 79.0, places=3)
            # El borde alto es el este: los laterales salen de x = 89.5 hacia el oeste, en bajada.
            self.assertTrue(all(abs(lat.inicio[0] - (X0 + 89.5)) < 1e-6 for lat in b.laterales))
            self.assertLess(b.pendiente_laterales, 0)
            self.assertAlmostEqual(b.valvula_m, b.longitud_portalateral_m / 2)
            self.assertIn("vista previa", dialogo.texto.toPlainText().lower())

            dialogo.edit_nombre.setText("A1")
            dialogo.aplicar()
            self.assertIn("calculado", dialogo.texto.toPlainText())
            raiz = QgsProject.instance().layerTreeRoot()
            self.assertIsNotNone(raiz.findGroup("RiegoLibre · A1"))
            guardado = capa.getFeature(lote_a.id())
            self.assertEqual(guardado["nombre"], "A1")
            datos = parametros_guardados(guardado)
            self.assertEqual(datos["portalateral"], PORTA_ALTO)
            self.assertAlmostEqual(datos["azimut_usado_deg"], 90.0)

            # Otra ventana recupera los parámetros guardados en el lote
            otra = dialogo_bloque.DialogoBloque(None)
            otra.abrir_lote(capa, guardado)
            self.assertAlmostEqual(otra.spin_separacion.value(), 2.0)
            self.assertEqual(otra.combo_valvula.currentData(), VALV_CENTRO)
            self.assertTrue(otra.radio_usuario.isChecked())

            # Los dos lotes a la vez
            html = dialogo._aplicar_varios(list(capa.getFeatures()))
            self.assertIn("2 de 2", html)
            self.assertIsNotNone(raiz.findGroup("RiegoLibre · M7. 6"))

        # Subdivisión del lote B en dos cortes con un camino de 4 m
        lote_b = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
        params = dialogo.parametros()
        partes = subdividir_en_lote(lote_b.geometry(), params, params.angulo_deg,
                                    ParametrosSubdivision(cortes=NUMERO, cortes_valor=2, cortes_hueco_m=4))
        self.assertEqual(len(partes), 2)
        self.assertAlmostEqual(sum(g.area() for g, _ in partes), 90 * 40 - 4 * 40, delta=1.0)
        nuevas = reemplazar_lote_por_partes(capa, lote_b, partes, ["M7. 6-1", "M7. 6-2"])
        self.assertEqual(len(nuevas), 2)
        nombres = sorted(e["nombre"] for e in capa.getFeatures())
        self.assertEqual(nombres, ["A1", "M7. 6-1", "M7. 6-2"])
        hija = capa.getFeature(nuevas[0])
        self.assertEqual(parametros_guardados(hija)["separacion_m"], 2.0)
        self.assertAlmostEqual(hija["area_ha"], 43 * 40 / 10000, places=3)


if __name__ == "__main__":
    unittest.main()
