# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Programa independiente (`riegolibre_app`): la ventana propia carga el complemento y maneja el proyecto."""

import json
import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasAplicacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        from riegolibre_app.ventana import VentanaPrincipal
        QgsProject.instance().clear()
        self.carpeta = tempfile.TemporaryDirectory()
        self.ventana = VentanaPrincipal()

    def tearDown(self):
        proyecto = QgsProject.instance()
        proyecto.setDirty(False)  # que el cierre no pregunte
        self.ventana.liberar()  # una ventana escondida no siempre recibe el cierre
        self.ventana.close()
        self.ventana.deleteLater()
        proyecto.clear()
        self.carpeta.cleanup()

    def _geojson(self):
        ruta = os.path.join(self.carpeta.name, "lote.geojson")
        anillo = [[X0, Y0], [X0 + 100, Y0], [X0 + 100, Y0 + 50], [X0, Y0 + 50], [X0, Y0]]
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump({"type": "FeatureCollection",
                       "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32718"}},
                       "features": [{"type": "Feature", "properties": {"nombre": "L1"},
                                     "geometry": {"type": "Polygon", "coordinates": [anillo]}}]}, archivo)
        return ruta

    def test_la_ventana_carga_el_complemento(self):
        ventana = self.ventana
        menus = [a.text() for a in ventana.menuBar().actions()]
        self.assertEqual(menus, ["&Proyecto", "&Capas", "&Ver", "&RiegoLibre", "Ayuda"])
        self.assertIs(ventana.mapCanvas(), ventana.lienzo)
        self.assertIs(ventana.mainWindow(), ventana)
        ventana.statusBarIface().showMessage("hola")
        barras = [b.windowTitle() for b in ventana.findChildren(type(ventana.navegacion))]
        self.assertIn("RiegoLibre", barras)
        self.assertEqual(len(ventana.complemento.acciones), 22)
        ventana.menu_ayuda.actions()[0].trigger()
        self.assertTrue(ventana.complemento.dialogos["acerca"].isVisible())
        ventana.complemento.dialogos["acerca"].close()

    def test_la_primera_capa_da_el_src_y_se_agrega_una_entidad(self):
        from qgis.gui import QgsMapToolDigitizeFeature
        ventana = self.ventana
        capa = ventana.agregar_vector(self._geojson())
        self.assertIsNotNone(capa)
        self.assertEqual(QgsProject.instance().crs().authid(), "EPSG:32718")
        self.assertEqual(ventana.boton_src.text(), "EPSG:32718")
        self.assertIs(ventana.activeLayer(), capa)
        self.assertIsNone(ventana.agregar_vector(os.path.join(self.carpeta.name, "no_existe.gpkg")))
        ventana.actionAddFeature().trigger()  # como lo hace «Diseño de subunidad en el mapa»
        self.assertIsInstance(ventana.lienzo.mapTool(), QgsMapToolDigitizeFeature)
        self.assertTrue(capa.isEditable())
        capa.rollBack()

    def test_la_capa_nueva_entra_junto_a_la_elegida(self):
        """Como en QGIS: una capa nueva entra encima de la capa elegida en el panel, dentro de su grupo."""
        ventana = self.ventana
        raiz = QgsProject.instance().layerTreeRoot()
        grupo = raiz.insertGroup(0, "Grupo")
        abajo = QgsVectorLayer("Point?crs=EPSG:32718", "abajo", "memory")
        QgsProject.instance().addMapLayer(abajo, False)
        grupo.addLayer(abajo)
        ventana.setActiveLayer(abajo)
        nueva = QgsVectorLayer("Point?crs=EPSG:32718", "nueva", "memory")
        QgsProject.instance().addMapLayer(nueva)
        self.assertEqual([n.name() for n in grupo.children()], ["nueva", "abajo"])
        self.assertIs(ventana.activeLayer(), nueva)  # la que entra queda elegida, como en QGIS
        # Un grupo insertado arriba no desplaza el punto: la capa siguiente sigue entrando junto a la elegida.
        raiz.insertGroup(0, "Arriba")
        tercera = QgsVectorLayer("Point?crs=EPSG:32718", "tercera", "memory")
        QgsProject.instance().addMapLayer(tercera)
        self.assertEqual([n.name() for n in grupo.children()], ["tercera", "nueva", "abajo"])
        ventana.arbol.setCurrentIndex(ventana.arbol.node2index(raiz))  # nada elegido: arriba de todo
        ventana.arbol.setCurrentLayer(None)
        otra = QgsVectorLayer("Point?crs=EPSG:32718", "otra", "memory")
        QgsProject.instance().addMapLayer(otra)
        self.assertEqual(raiz.children()[0].name(), "otra")
        # Cerrada la ventana, ya no decide dónde entran las capas (no debe afectar a quien use el proyecto luego).
        ventana.setActiveLayer(abajo)
        ventana.liberar()
        ultima = QgsVectorLayer("Point?crs=EPSG:32718", "ultima", "memory")
        QgsProject.instance().addMapLayer(ultima)
        self.assertEqual(raiz.children()[0].name(), "ultima")

    def test_guardar_y_abrir_el_proyecto(self):
        from qgis.core import QgsPointXY
        from qgis.PyQt.QtCore import QCoreApplication

        from riegolibre.integracion.red_mapa import agregar_tuberia, crear_capas_de_matriz
        ventana = self.ventana
        ventana.agregar_vector(self._geojson())
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
        matriz, _nodos, _ruta = crear_capas_de_matriz(QgsProject.instance())
        agregar_tuberia(matriz, [QgsPointXY(X0, Y0), QgsPointXY(X0 + 100, Y0)])
        self.assertEqual(matriz.providerType(), "memory")  # aún no hay archivo del proyecto
        ruta = os.path.join(self.carpeta.name, "fundo.qgz")
        self.assertTrue(ventana.guardar_en(ruta))
        QCoreApplication.processEvents()  # el complemento reescribe el .qgz cuando QGIS termina de comprimirlo
        self.assertTrue(os.path.exists(ruta))
        # El complemento pasa sus capas temporales al GeoPackage junto al proyecto al guardarlo.
        guardada = QgsProject.instance().mapLayersByName("Matriz")[0]
        self.assertEqual(guardada.providerType(), "ogr")
        self.assertIn("fundo — RiegoLibre", ventana.windowTitle())

        self.assertTrue(ventana.nuevo_proyecto(preguntar=False))
        self.assertEqual(QgsProject.instance().count(), 0)
        self.assertIn("Proyecto sin título", ventana.windowTitle())
        self.assertTrue(ventana.abrir_proyecto(ruta))
        self.assertEqual(len(ventana.lienzo.layers()), QgsProject.instance().count())  # el mapa las dibuja
        nombres = sorted(c.name() for c in QgsProject.instance().mapLayers().values())
        self.assertIn("lote", nombres)
        self.assertIn("Matriz", nombres)
        releida = QgsProject.instance().mapLayersByName("Matriz")[0]
        self.assertIsInstance(releida, QgsVectorLayer)
        # La primera vez que se guarda un .qgz, la matriz ya debe leerse del GeoPackage, con su tubería.
        self.assertEqual(releida.providerType(), "ogr")
        self.assertEqual(releida.featureCount(), 1)
        self.assertEqual(ventana.boton_src.text(), "EPSG:32718")


if __name__ == "__main__":
    unittest.main()
