# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
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

    def _capa_lineas(self, nombre, y, campos=""):
        capa = QgsVectorLayer(f"LineString?crs=EPSG:32718{campos}", nombre, "memory")
        entidad = QgsFeature(capa.fields())
        entidad.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(X0 + 10, y), QgsPointXY(X0 + 110, y)]))
        capa.dataProvider().addFeatures([entidad])
        capa.updateExtents()
        QgsProject.instance().addMapLayer(capa)
        self.addCleanup(QgsProject.instance().removeMapLayer, capa.id())
        return capa

    def test_linea_en_punto_prefiere_los_laterales(self):
        from qgis.core import QgsCoordinateReferenceSystem
        from riegolibre.integracion.info_objeto import linea_en_punto
        crs = QgsCoordinateReferenceSystem("EPSG:32718")
        calculado = self._capa_lineas(
            "Laterales · Lote 1", Y0 - 40, "&field=emisores:integer&field=p_entrada:double&field=longitud:double")
        curva = self._capa_lineas("Curvas", Y0 - 41)
        sin_preferir = linea_en_punto(QgsPointXY(X0 + 50, Y0 - 41), crs, 5.0)
        self.assertIs(sin_preferir[0], calculado)  # aunque la curva pase justo por el clic
        self.assertIs(linea_en_punto(QgsPointXY(X0 + 50, Y0 - 44), crs, 3.5)[0], curva)  # el lateral queda lejos
        self.assertIsNone(linea_en_punto(QgsPointXY(X0 + 50, Y0 - 500), crs, 5.0))

        QgsProject.instance().layerTreeRoot().findLayer(calculado.id()).setItemVisibilityChecked(False)
        self.assertIs(linea_en_punto(QgsPointXY(X0 + 50, Y0 - 41), crs, 5.0)[0], curva)  # capa apagada: no cuenta

    def test_elegir_lateral_en_el_mapa(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle
        from qgis.gui import QgsMapCanvas
        from riegolibre.gui.dialogo_lateral import DialogoLateral
        from riegolibre.gui.herramienta_puntos import HerramientaPuntos

        class IfaceFalsa:
            def __init__(self):
                self.lienzo = QgsMapCanvas()
                self.lienzo.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
                self.lienzo.setExtent(QgsRectangle(X0, Y0 - 50, X0 + 200, Y0))
                self.mensajes = []

            def mapCanvas(self):  # noqa: N802
                return self.lienzo

            def statusBarIface(self):  # noqa: N802
                return self

            def showMessage(self, _texto):  # noqa: N802
                pass

            def messageBar(self):  # noqa: N802
                return self

            def pushMessage(self, _titulo, texto, *_):  # noqa: N802
                self.mensajes.append(texto)

        def clic(herramienta, x, y):
            herramienta.puntos = [QgsPointXY(x, y)]
            herramienta._salir(cancelado=False)

        iface = IfaceFalsa()
        otra = self._capa_lineas("Otro lote", Y0 - 35)
        self.addCleanup(self.lineas.removeSelection)
        dialogo = DialogoLateral(iface=iface)
        dialogo.combo_linea.setLayer(otra)
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.show()

        dialogo.elegir_en_mapa()
        self.assertFalse(dialogo.isVisible())
        herramienta = iface.lienzo.mapTool()
        self.assertIsInstance(herramienta, HerramientaPuntos)

        # Clic en un sitio sin líneas: avisa y sigue esperando, con la ventana escondida.
        clic(herramienta, X0 + 190, Y0 - 5)
        self.assertFalse(dialogo.isVisible())
        self.assertIsNot(iface.lienzo.mapTool(), herramienta)
        self.assertIn("No hay ninguna línea", iface.mensajes[-1])
        self.assertFalse(dialogo.check_terreno.isChecked())

        # Clic sobre una línea de otra capa: cambia la capa, la selecciona y calcula.
        clic(iface.lienzo.mapTool(), X0 + 50, Y0 - 25)
        self.assertTrue(dialogo.isVisible())
        self.assertIs(dialogo.combo_linea.currentLayer(), self.lineas)
        self.assertEqual(self.lineas.selectedFeatureCount(), 1)
        self.assertTrue(dialogo.check_terreno.isChecked())
        self.assertAlmostEqual(dialogo.spin_longitud.value(), 100.0, places=1)
        self.assertIn("Presión de entrada", dialogo.texto.toHtml())
        self.assertIn("laterales", dialogo.nota_linea.text())

        # Esc: vuelve sin cambiar nada; y una elección nueva quita la selección de la anterior.
        dialogo.elegir_en_mapa()
        iface.lienzo.mapTool()._salir(cancelado=True)
        self.assertTrue(dialogo.isVisible())
        self.assertEqual(self.lineas.selectedFeatureCount(), 1)
        dialogo.elegir_en_mapa()
        clic(iface.lienzo.mapTool(), X0 + 50, Y0 - 35)
        self.assertIs(dialogo.combo_linea.currentLayer(), otra)
        self.assertEqual(self.lineas.selectedFeatureCount(), 0)
        self.assertEqual(otra.selectedFeatureCount(), 1)
        dialogo.hide()

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
        from qgis.gui import QgsMapCanvas
        from qgis.PyQt import sip
        from qgis.PyQt.QtCore import QCoreApplication, QEvent
        from qgis.PyQt.QtWidgets import QMainWindow, QToolButton
        from riegolibre import classFactory

        class IfaceFalsa:
            def __init__(self):
                self.ventana = QMainWindow()
                self.lienzo = QgsMapCanvas()
                self.ayuda = self.ventana.menuBar().addMenu("Ayuda")
                self.mensajes = []

            def mapCanvas(self):  # noqa: N802
                return self.lienzo

            def mainWindow(self):  # noqa: N802
                return self.ventana

            def firstRightStandardMenu(self):  # noqa: N802
                return self.ayuda

            def addToolBar(self, nombre):  # noqa: N802
                return self.ventana.addToolBar(nombre)

            def messageBar(self):  # noqa: N802
                return self

            def pushMessage(self, titulo, texto, *_):  # noqa: N802
                self.mensajes.append(texto)

        iface = IfaceFalsa()
        plugin = classFactory(iface)
        plugin.initGui()
        # Todo cuelga de un solo menú, antes de «Ayuda», y la barra propia lleva el mismo orden.
        acciones_menu = iface.ventana.menuBar().actions()
        self.assertEqual([a.text() for a in acciones_menu], ["&RiegoLibre", "Ayuda"])
        principales = ["Terreno y lotes", "Diseño de goteo",
                       "Bloque de goteo (clic en un lote; Ctrl + clic para eliminar su bloque)", "",
                       "Red principal y bomba…",
                       "Turnos de riego (marcar bloques en el mapa y asignarles un turno)", "",
                       "Información del objeto (clic en un lateral, tubería o válvula)",
                       "Presión mínima y máxima", "", "Materiales y documentos", "", "Ayuda"]
        self.assertEqual([a.text() for a in plugin.menu.actions()], principales)
        self.assertEqual([a.text() for a in plugin.barra.actions()], principales)
        grupos = {a.text(): [b.text() for b in a.menu().actions()] for a in plugin.barra.actions() if a.menu()}
        self.assertEqual(grupos, {
            "Terreno y lotes": ["Topografía: curvas de CAD, imagen satelital y 3D…", "Importar lotes de CAD…",
                                "Zonas: tabla de diseño de los lotes…"],
            "Diseño de goteo": ["Calculadora de lateral (goteo)…", "Subunidad de riego (goteo)…",
                                "Diseño de subunidad en el mapa (goteo)…",
                                "Trazado automático de subunidades (goteo)…",
                                "Diámetros de portalaterales por velocidad…"],
            "Presión mínima y máxima": ["Todas las válvulas", "Válvulas seleccionadas", "Borrar marcadores"],
            "Materiales y documentos": ["Base de datos de materiales…", "Lista de materiales y costos…",
                                        "Memoria de cálculo…"],
            "Ayuda": ["Acerca de RiegoLibre…"]})
        for accion in plugin.barra.actions():
            if accion.menu():  # un clic despliega el grupo; los botones del grupo no quedan sueltos en la barra
                self.assertEqual(plugin.barra.widgetForAction(accion).popupMode(),
                                 QToolButton.ToolButtonPopupMode.InstantPopup)
                self.assertFalse(accion.icon().isNull())
        self.assertEqual(len(plugin.acciones), 19)
        self.assertTrue(all(not a.icon().isNull() for a in plugin.acciones))

        def accion(inicio):
            return next(a for a in plugin.acciones if a.text().startswith(inicio))

        accion("Acerca de").trigger()
        acerca = plugin.dialogos["acerca"]
        self.assertTrue(acerca.isVisible())
        self.assertIn("RiegoLibre, creado por Jhonatan Chilet", acerca.etiqueta.text())
        self.assertIn("SIN NINGUNA GARANTÍA", acerca.etiqueta.text())
        self.assertEqual(acerca.pestanas.count(), 3)
        self.assertIn("sección 7 de la GPL-3.0", acerca.pestanas.widget(1).toPlainText())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", acerca.pestanas.widget(2).toPlainText())
        accion("Topografía").trigger()
        self.assertTrue(plugin.dialogos["topografia"].isVisible())
        accion("Subunidad de riego").trigger()
        self.assertTrue(plugin.dialogos["subunidad"].isVisible())
        accion("Importar lotes").trigger()
        self.assertTrue(plugin.dialogos["lotes"].isVisible())
        # La herramienta «Bloque de goteo» se activa desde su botón; sin lotes, solo avisa.
        accion("Bloque de goteo").setChecked(True)
        self.assertIs(iface.mapCanvas().mapTool(), plugin.herramienta_bloque)
        iface.mapCanvas().unsetMapTool(plugin.herramienta_bloque)
        self.assertFalse(accion("Bloque de goteo").isChecked())
        accion("Zonas").trigger()
        self.assertTrue(plugin.dialogos["zonas"].isVisible())
        self.assertIsNotNone(plugin.dialogos["zonas"].abrir_lote)
        accion("Diámetros").trigger()
        self.assertTrue(plugin.dialogos["diametros"].isVisible())
        accion("Trazado").trigger()
        self.assertTrue(plugin.dialogos["trazado"].isVisible())
        # La herramienta «Turnos de riego» abre su panel; la ventana de la red la activa con su botón.
        accion("Turnos").setChecked(True)
        self.assertIs(iface.mapCanvas().mapTool(), plugin.herramienta_turnos)
        self.assertTrue(plugin.panel_turnos.isVisible())
        iface.mapCanvas().unsetMapTool(plugin.herramienta_turnos)
        self.assertFalse(accion("Turnos").isChecked())
        accion("Red principal").trigger()
        self.assertIsNotNone(plugin.dialogos["red"].abrir_turnos)
        plugin.dialogos["red"].boton_turnos_mapa.click()
        self.assertIs(iface.mapCanvas().mapTool(), plugin.herramienta_turnos)
        iface.mapCanvas().unsetMapTool(plugin.herramienta_turnos)
        accion("Memoria").trigger()  # sin resultados en el proyecto: la memoria lo indica
        self.assertIn("No hay resultados", plugin.dialogos["memoria"].etiqueta_estado.text())
        # La herramienta «Información del objeto» se activa y se desactiva desde su botón.
        accion("Información").setChecked(True)
        self.assertIs(iface.mapCanvas().mapTool(), plugin.herramienta_info)
        iface.mapCanvas().unsetMapTool(plugin.herramienta_info)
        self.assertFalse(accion("Información").isChecked())
        # Sin marcadores de presión, borrar solo lo avisa.
        accion("Borrar marcadores").trigger()
        self.assertEqual(iface.mensajes[-1], "No hay marcadores.")
        # Al cambiar la base de datos, las ventanas se rehacen para leer los catálogos nuevos:
        # las cerradas de inmediato y las abiertas cuando se vuelven a abrir.
        accion("Base de datos").trigger()
        base = plugin.dialogos["base_datos"]
        plugin.dialogos["topografia"].hide()
        subunidad = plugin.dialogos["subunidad"]
        base.base_cambiada.emit()
        self.assertNotIn("topografia", plugin.dialogos)
        plugin.abrir("subunidad")
        self.assertIs(plugin.dialogos["subunidad"], subunidad)  # sigue abierta
        subunidad.hide()
        plugin.abrir("subunidad")
        self.assertIsNot(plugin.dialogos["subunidad"], subunidad)
        self.assertIs(plugin.dialogos["base_datos"], base)
        # Al descargar no queda nada: ni el menú ni la barra (si no, se duplican al recargar el complemento).
        barra, menu = plugin.barra, plugin.menu
        plugin.unload()
        self.assertEqual([a.text() for a in iface.ventana.menuBar().actions()], ["Ayuda"])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(sip.isdeleted(barra))
        self.assertTrue(sip.isdeleted(menu))


if __name__ == "__main__":
    unittest.main()
