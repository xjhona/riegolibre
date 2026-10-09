"""Pruebas de la herramienta de diseño en el mapa (requieren el Python de QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import (HAY_QGIS, PENDIENTE_ESTE, X0, Y0, _crear_dem,
                                         _iniciar_qgis)

if HAY_QGIS:
    from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                           QgsRasterLayer, QgsVectorLayer)

# Bloque de 100 m (este-oeste) × 46 m (norte-sur) y portalateral por el medio, hacia el este.
BLOQUE = [(10, -48), (110, -48), (110, -2), (10, -2)]
PORTALATERAL = [(10, -25), (110, -25)]


def _punto(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _capa(tipo, puntos, nombre):
    capa = QgsVectorLayer(f"{tipo}?crs=EPSG:32718", nombre, "memory")
    entidad = QgsFeature()
    if tipo == "Polygon":
        entidad.setGeometry(QgsGeometry.fromPolygonXY([[_punto(*p) for p in puntos]]))
    else:
        entidad.setGeometry(QgsGeometry.fromPolylineXY([_punto(*p) for p in puntos]))
    capa.dataProvider().addFeatures([entidad])
    capa.updateExtents()
    return capa


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasGeneracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.bloque = QgsGeometry.fromPolygonXY([[_punto(*p) for p in BLOQUE]])
        cls.portalateral = QgsGeometry.fromPolylineXY([_punto(*p) for p in PORTALATERAL])

    def test_laterales_a_ambos_lados(self):
        from riegolibre.integracion.subunidad_mapa import generar_laterales
        laterales = generar_laterales(self.bloque, self.portalateral, 1.5, margen_m=0.5)
        self.assertEqual(len(laterales), 2 * 67)
        for lat in laterales:
            self.assertAlmostEqual(lat.longitud_m, 22.5, places=6)
            inicio, fin = lat.geometria.asPolyline()
            self.assertAlmostEqual(inicio.y(), Y0 - 25, places=6)
            # El lado A queda a la izquierda de un portalateral dibujado hacia el este: al norte.
            esperado = Y0 - 25 + (22.5 if lat.lado == "A" else -22.5)
            self.assertAlmostEqual(fin.y(), esperado, places=6)
            self.assertAlmostEqual(fin.x(), inicio.x(), places=6)
        self.assertAlmostEqual(laterales[0].distancia_m, 0.75)

    def test_portalateral_en_el_borde(self):
        from riegolibre.integracion.subunidad_mapa import generar_laterales
        borde = QgsGeometry.fromPolylineXY([_punto(10, -48), _punto(110, -48)])
        laterales = generar_laterales(self.bloque, borde, 2.0, margen_m=0.0)
        self.assertEqual({lat.lado for lat in laterales}, {"A"})
        self.assertTrue(all(abs(lat.longitud_m - 46.0) < 1e-6 for lat in laterales))

    def test_longitud_maxima_y_azimut(self):
        from riegolibre.integracion.subunidad_mapa import generar_laterales
        laterales = generar_laterales(self.bloque, self.portalateral, 1.5, longitud_max_m=10,
                                      lados=("A",), azimut_grados=0)
        self.assertTrue(all(abs(lat.longitud_m - 10) < 1e-6 for lat in laterales))
        inicio, fin = laterales[0].geometria.asPolyline()
        self.assertAlmostEqual(fin.y() - inicio.y(), 10, places=6)

    def test_bloque_concavo(self):
        # Bloque en «U»: los laterales hacia el norte se cortan en la escotadura.
        from riegolibre.integracion.subunidad_mapa import generar_laterales
        u = QgsGeometry.fromPolygonXY([[_punto(*p) for p in [
            (10, -48), (110, -48), (110, -2), (70, -2), (70, -15), (50, -15), (50, -2), (10, -2)]]])
        laterales = generar_laterales(u, self.portalateral, 2.0, lados=("A",))
        for lat in laterales:
            x = lat.geometria.asPolyline()[0].x() - X0
            self.assertAlmostEqual(lat.longitud_m, 10.0 if 50 < x < 70 else 23.0, places=6)

    def test_portalateral_diagonal(self):
        # Longitud con decimales: no debe pedirse un punto más allá del final de la línea.
        from riegolibre.integracion.subunidad_mapa import generar_laterales
        diagonal = QgsGeometry.fromPolylineXY([_punto(12, -40), _punto(107.3, -9.1)])
        laterales = generar_laterales(self.bloque, diagonal, diagonal.length() / 7, distancia_primero_m=0)
        self.assertEqual(len({lat.conexion for lat in laterales}), 8)
        for lat in laterales:
            inicio, fin = lat.geometria.asPolyline()
            direccion = (fin.x() - inicio.x(), fin.y() - inicio.y())
            producto = direccion[0] * (107.3 - 12) + direccion[1] * (-9.1 + 40)
            self.assertAlmostEqual(producto, 0.0, places=4)  # perpendicular al portalateral

    def test_leer_laterales_orienta_desde_el_portalateral(self):
        from riegolibre.integracion.subunidad_mapa import leer_laterales
        capa = QgsVectorLayer("LineString?crs=EPSG:32718", "laterales", "memory")
        al_reves = QgsFeature()
        al_reves.setGeometry(QgsGeometry.fromPolylineXY([_punto(30, -5), _punto(30, -25.3)]))
        lejano = QgsFeature()
        lejano.setGeometry(QgsGeometry.fromPolylineXY([_punto(60, -10), _punto(60, -20)]))
        capa.dataProvider().addFeatures([al_reves, lejano])
        laterales, avisos = leer_laterales(capa, self.portalateral, capa.crs())
        self.assertEqual(len(laterales), 1)
        self.assertAlmostEqual(laterales[0].distancia_m, 20.0, places=6)
        self.assertAlmostEqual(laterales[0].geometria.asPolyline()[0].y(), Y0 - 25.3, places=6)
        self.assertIn("no llegan al portalateral", avisos[0])


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasDialogoMapa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta_dem = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta_dem)
        cls.dem = QgsRasterLayer(ruta_dem, "dem")
        cls.bloque = _capa("Polygon", BLOQUE, "bloque")
        cls.porta = _capa("LineString", PORTALATERAL, "portalateral")
        QgsProject.instance().addMapLayers([cls.dem, cls.bloque, cls.porta])

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def _dialogo(self):
        from riegolibre.gui.dialogo_mapa import DialogoMapa
        dialogo = DialogoMapa(iface=None)
        dialogo.combo_bloque.setLayer(self.bloque)
        dialogo.combo_portalateral.setLayer(self.porta)
        dialogo.spin_separacion.setValue(1.5)
        dialogo.spin_margen.setValue(0.5)
        return dialogo

    def test_generar_y_calcular_coincide_con_subunidad_rectangular(self):
        from riegolibre.nucleo import Lateral, subunidad_rectangular
        dialogo = self._dialogo()
        dialogo.generar_laterales()
        capa = dialogo.combo_laterales.currentLayer()
        self.assertEqual(capa.featureCount(), 134)

        dialogo.combo_dem.setLayer(self.dem)
        dialogo.calcular()
        grupo = QgsProject.instance().layerTreeRoot().findGroup("RiegoLibre · Subunidad 1")
        self.assertIsNotNone(grupo)
        capas = {nodo.layer().name(): nodo.layer() for nodo in grupo.findLayers()}
        self.assertEqual(capas["Laterales · Subunidad 1"].featureCount(), 134)
        self.assertEqual(capas["Portalateral · Subunidad 1"].featureCount(), 67)
        self.assertEqual(capas["Válvula · Subunidad 1"].featureCount(), 1)
        mapa = dialogo.panel.resultado

        # El mismo caso como subunidad rectangular: el DEM sube 2 % hacia el este (a lo
        # largo del portalateral) y es plano en la dirección de los laterales.
        grupo_lat = dialogo.grupo_laterales
        lateral = Lateral.desde_longitud(grupo_lat.tuberia(), grupo_lat.emisor(), 0.3, 22.5)
        rectangular = subunidad_rectangular(dialogo.panel.diseno.tuberia, lateral, lateral, 1.5, 67,
                                            pendiente=PENDIENTE_ESTE).presion_entrada_requerida()
        self.assertAlmostEqual(mapa.presion_entrada_m, rectangular.presion_entrada_m, delta=0.02)
        self.assertAlmostEqual(mapa.caudal_total_lh, rectangular.caudal_total_lh, delta=1.0)

        valvula = next(capas["Válvula · Subunidad 1"].getFeatures())
        self.assertAlmostEqual(valvula["presion"], mapa.presion_entrada_m, places=2)
        presiones = [f["p_entrada"] for f in capas["Laterales · Subunidad 1"].getFeatures()]
        self.assertAlmostEqual(max(presiones), max(r.presion_entrada_m
                                                   for c in mapa.laterales for r in c), places=2)

    def test_laterales_editados_y_entrada_central(self):
        dialogo = self._dialogo()
        dialogo.edit_nombre.setText("Editada")
        dialogo.generar_laterales()
        capa = dialogo.combo_laterales.currentLayer()
        # Se borran los laterales del lado B en la mitad oeste.
        borrar = [f.id() for f in capa.getFeatures() if f["lado"] == "B" and f["dist_porta"] < 50]
        capa.dataProvider().deleteFeatures(borrar)
        dialogo.combo_entrada.setCurrentIndex(1)  # centro
        dialogo.calcular()
        resultado = dialogo.panel.resultado
        self.assertEqual(len(resultado.ramas), 2)
        grupo = QgsProject.instance().layerTreeRoot().findGroup("RiegoLibre · Editada")
        laterales = next(n.layer() for n in grupo.findLayers() if n.layer().name().startswith("Laterales"))
        self.assertEqual(laterales.featureCount(), 134 - len(borrar))
        tramos = next(n.layer() for n in grupo.findLayers() if n.layer().name().startswith("Portalateral"))
        caudales = {f["rama"] for f in tramos.getFeatures()}
        self.assertEqual(caudales, {"hacia el final", "hacia el inicio"})

    def test_recalcular_reemplaza_el_grupo(self):
        dialogo = self._dialogo()
        dialogo.edit_nombre.setText("Repetida")
        dialogo.generar_laterales()
        dialogo.calcular()
        dialogo.calcular()
        raiz = QgsProject.instance().layerTreeRoot()
        grupos = [g for g in raiz.children() if g.name() == "RiegoLibre · Repetida"]
        self.assertEqual(len(grupos), 1)
        self.assertEqual(len(grupos[0].findLayers()), 3)


if __name__ == "__main__":
    unittest.main()
