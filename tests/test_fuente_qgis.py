# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas de la herramienta «Fuente de agua» (requieren el Python de QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _iniciar_qgis
from tests.test_red_qgis import _HerramientaFalsa

if HAY_QGIS:
    from unittest import mock

    from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                           QgsVectorLayer)
    from qgis.PyQt.QtWidgets import QMessageBox

    from riegolibre.gui.herramienta_fuente import ColocarFuente
    from riegolibre.integracion import fuente_mapa
    from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, agregar_tuberia, estilo_red_dibujada
    from riegolibre.integracion.subunidad_mapa import PROPIEDAD


def _p(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _puntos(capa):
    return [(round(e.geometry().asPoint().x() - X0, 3), round(e.geometry().asPoint().y() - Y0, 3))
            for e in capa.getFeatures()]


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasFuente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # OGR deja abierto el gpkg
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()
        self.proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))

    def tearDown(self):
        self.proyecto.clear()
        self.carpeta.cleanup()

    def _interfaz(self, anterior=None):
        """Interfaz y lienzo simulados (un lienzo real deja inestable la suite)."""
        canvas = mock.Mock()
        canvas.mapTool.return_value = anterior
        canvas.mapSettings.return_value.destinationCrs.return_value = QgsCoordinateReferenceSystem("EPSG:32718")
        iface = mock.Mock()
        iface.mapCanvas.return_value = canvas
        iface.mainWindow.return_value = None  # un Mock no sirve de ventana madre de un cuadro de Qt
        return iface, canvas

    def _iniciar(self, colocador):
        _HerramientaFalsa.creadas = []
        with mock.patch("riegolibre.gui.herramienta_fuente.HerramientaPuntos", _HerramientaFalsa):
            iniciada = colocador.iniciar()
        return iniciada, (_HerramientaFalsa.creadas[-1] if _HerramientaFalsa.creadas else None)

    def test_se_crea_la_capa_con_su_simbolo_y_rotulo(self):
        self.assertIsNone(fuente_mapa.capa_de_fuente())
        capa, ruta = fuente_mapa.crear_capa_fuente()
        self.assertIsNone(ruta)  # el proyecto aún no tiene archivo
        self.assertIs(fuente_mapa.capa_de_fuente(), capa)
        self.assertEqual(capa.name(), "Fuente")
        self.assertEqual(capa.crs().authid(), "EPSG:32718")
        self.assertEqual(capa.customProperty(PROPIEDAD), "dibujo")
        self.assertEqual(capa.renderer().symbol().symbolLayer(0).shape().name, "Square")
        self.assertEqual(capa.renderer().symbol().color().name(), "#1565c0")
        self.assertTrue(capa.labelsEnabled())
        self.assertEqual(capa.labeling().settings().fieldName, "'Fuente'")
        self.assertFalse(fuente_mapa.tiene_fuente(capa))

    def test_el_crs_del_proyecto_debe_ser_metrico(self):
        self.proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        with self.assertRaises(ValueError):
            fuente_mapa.crear_capa_fuente()
        self.assertIsNone(fuente_mapa.capa_de_fuente())

    def test_colocar_otra_vez_reemplaza_el_punto(self):
        capa, _ = fuente_mapa.crear_capa_fuente()
        fuente_mapa.colocar_fuente(capa, _p(10, 20))
        fuente_mapa.colocar_fuente(capa, _p(30, 40))
        self.assertEqual(_puntos(capa), [(30.0, 40.0)])
        self.assertEqual(next(capa.getFeatures())["nombre"], "Fuente")

    def test_con_la_capa_en_edicion_se_confirma_y_sigue_editable(self):
        capa, _ = fuente_mapa.crear_capa_fuente()
        capa.startEditing()
        fuente_mapa.colocar_fuente(capa, _p(1, 2))
        fuente_mapa.colocar_fuente(capa, _p(3, 4))
        self.assertTrue(capa.isEditable())
        self.assertFalse(capa.isModified())
        self.assertEqual(_puntos(capa), [(3.0, 4.0)])
        capa.rollBack()
        self.assertEqual(_puntos(capa), [(3.0, 4.0)])

    def test_en_el_geopackage_del_proyecto(self):
        self.proyecto.setFileName(os.path.join(self.carpeta.name, "riego.qgz"))
        capa, ruta = fuente_mapa.crear_capa_fuente()
        self.assertTrue(ruta.endswith("riego_riegolibre.gpkg"))
        self.assertEqual(capa.providerType(), "ogr")
        self.assertTrue(capa.labelsEnabled())  # el estilo sobrevive al guardado
        fuente_mapa.colocar_fuente(capa, _p(10, 20))
        fuente_mapa.colocar_fuente(capa, _p(30, 40))
        self.assertEqual(capa.featureCount(), 1)
        self.assertEqual(_puntos(capa), [(30.0, 40.0)])
        self.assertEqual(next(capa.getFeatures())["nombre"], "Fuente")

    def test_el_iman_ofrece_las_tuberias_y_las_valvulas(self):
        crs = QgsCoordinateReferenceSystem("EPSG:32718")
        red = QgsVectorLayer("LineString?crs=EPSG:32718&field=nombre:string(50)&field=" + CAMPO_TUBERIA
                             + ":string(80)", "Red principal", "memory")
        estilo_red_dibujada(red)
        self.proyecto.addMapLayer(red)
        agregar_tuberia(red, [_p(0, 0), _p(50, 0)])
        valvulas = QgsVectorLayer("Point?crs=EPSG:32718&field=presion:double&field=caudal_lh:double",
                                  "Válvula · A", "memory")
        entidad = QgsFeature(valvulas.fields())
        entidad.setGeometry(QgsGeometry.fromPointXY(_p(50, 10)))
        entidad["presion"], entidad["caudal_lh"] = 10.0, 5000.0
        valvulas.dataProvider().addFeatures([entidad])
        self.proyecto.addMapLayer(valvulas)
        geometrias = fuente_mapa.geometrias_de_iman(crs)
        self.assertEqual(len(geometrias), 2)

    def test_un_clic_coloca_la_fuente_y_crea_la_capa(self):
        iface, canvas = self._interfaz()
        alertas = []
        colocador = ColocarFuente(iface, None, alertas.append, lambda: alertas.append("fin"))
        iniciada, herramienta = self._iniciar(colocador)
        self.assertTrue(iniciada)
        self.assertEqual(herramienta.cuantos, 1)
        self.assertIs(canvas.setMapTool.call_args[0][0], herramienta)
        self.assertIn("Fuente de agua", herramienta.mensajes[0])
        herramienta.terminar([_p(12, 34)])
        capa = fuente_mapa.capa_de_fuente()
        self.assertEqual(_puntos(capa), [(12.0, 34.0)])
        self.assertEqual(alertas[0], "fin")  # la herramienta se suelta antes de avisar de la capa
        self.assertIs(alertas[1], capa)
        self.assertIsNone(colocador.herramienta)

    def test_al_terminar_vuelve_a_la_herramienta_anterior(self):
        anterior = object()
        iface, canvas = self._interfaz(anterior=anterior)
        colocador = ColocarFuente(iface, None)
        _, herramienta = self._iniciar(colocador)
        canvas.mapTool.return_value = None  # al terminar la herramienta de puntos deja el mapa sin herramienta
        herramienta.terminar([_p(1, 1)])
        self.assertIs(canvas.setMapTool.call_args[0][0], anterior)

    def test_si_ya_hay_fuente_pregunta_y_la_reemplaza(self):
        capa, _ = fuente_mapa.crear_capa_fuente()
        fuente_mapa.colocar_fuente(capa, _p(5, 5))
        iface, _ = self._interfaz()
        colocador = ColocarFuente(iface, None)
        # Dice que no: no se activa nada y la fuente sigue donde estaba.
        with mock.patch("riegolibre.gui.herramienta_fuente.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.No) as pregunta:
            iniciada, herramienta = self._iniciar(colocador)
        self.assertEqual(pregunta.call_count, 1)
        self.assertFalse(iniciada)
        self.assertIsNone(herramienta)
        self.assertEqual(_puntos(capa), [(5.0, 5.0)])
        # Dice que sí: el clic la reemplaza y sigue siendo un solo punto en la misma capa.
        with mock.patch("riegolibre.gui.herramienta_fuente.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes):
            iniciada, herramienta = self._iniciar(colocador)
        self.assertTrue(iniciada)
        herramienta.terminar([_p(70, 80)])
        self.assertEqual(_puntos(capa), [(70.0, 80.0)])
        self.assertEqual(len([c for c in self.proyecto.mapLayers().values() if c.name() == "Fuente"]), 1)

    def test_con_la_capa_vacia_no_pregunta(self):
        fuente_mapa.crear_capa_fuente()
        iface, _ = self._interfaz()
        with mock.patch("riegolibre.gui.herramienta_fuente.QMessageBox.question") as pregunta:
            iniciada, _ = self._iniciar(ColocarFuente(iface, None))
        self.assertTrue(iniciada)
        pregunta.assert_not_called()

    def test_cancelar_con_esc_no_cambia_nada(self):
        iface, _ = self._interfaz()
        fin = []
        colocador = ColocarFuente(iface, None, None, lambda: fin.append(True))
        _, herramienta = self._iniciar(colocador)
        herramienta.cancelar()
        self.assertEqual(fin, [True])
        self.assertIsNone(fuente_mapa.capa_de_fuente())

    def test_con_el_crs_en_grados_avisa_y_no_activa(self):
        self.proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        iface, canvas = self._interfaz()
        with mock.patch("riegolibre.gui.herramienta_fuente.QMessageBox.warning") as aviso:
            iniciada, herramienta = self._iniciar(ColocarFuente(iface, None))
        self.assertFalse(iniciada)
        self.assertIn("sistema de coordenadas proyectado", aviso.call_args[0][2])
        canvas.setMapTool.assert_not_called()

    def test_el_boton_de_la_ventana_de_la_red_esconde_la_ventana_y_la_deja_apuntando_a_la_fuente(self):
        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QAction

        from riegolibre.gui.dialogo_red import DialogoRed
        from riegolibre.plugin import RiegoLibrePlugin
        iface, _ = self._interfaz()
        plugin = RiegoLibrePlugin(iface)
        plugin.accion_fuente = QAction(QIcon(), "Fuente de agua")
        plugin.accion_fuente.setCheckable(True)
        plugin.accion_fuente.toggled.connect(plugin._activar_fuente)
        red = plugin.dialogos["red"] = DialogoRed(iface=iface)
        red.abrir_fuente = plugin._fuente_desde_red
        self.addCleanup(red.hide)
        red.show()
        _HerramientaFalsa.creadas = []
        with mock.patch("riegolibre.gui.herramienta_fuente.HerramientaPuntos", _HerramientaFalsa):
            red.boton_fuente.click()
        self.assertFalse(red.isVisible())  # se esconde mientras se marca en el mapa
        self.assertTrue(plugin.accion_fuente.isChecked())
        _HerramientaFalsa.creadas[-1].terminar([_p(8, 9)])
        capa = fuente_mapa.capa_de_fuente()
        self.assertEqual(_puntos(capa), [(8.0, 9.0)])
        self.assertTrue(red.isVisible())
        self.assertFalse(plugin.accion_fuente.isChecked())
        self.assertIs(red.combo_fuente.currentLayer(), capa)
        # Si no se pudo activar (SRC en grados), el botón se suelta y la ventana vuelve.
        self.proyecto.removeAllMapLayers()
        self.proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        with mock.patch("riegolibre.gui.herramienta_fuente.QMessageBox.warning"):
            red.boton_fuente.click()
        self.assertTrue(red.isVisible())
        self.assertFalse(plugin.accion_fuente.isChecked())

    def test_la_ventana_de_la_red_calcula_con_la_fuente_sin_tocar_nada_mas(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        from tests.test_red_qgis import PRINCIPAL, RAMA, VALVULAS, _capa_lineas
        tuberias = _capa_lineas([PRINCIPAL, RAMA])
        self.proyecto.addMapLayer(tuberias)
        for nombre, (punto, caudal, presion) in VALVULAS.items():
            capa = QgsVectorLayer("Point?crs=EPSG:32718&field=presion:double&field=caudal_lh:double",
                                  f"Válvula · {nombre}", "memory")
            entidad = QgsFeature(capa.fields())
            entidad.setGeometry(QgsGeometry.fromPointXY(_p(*punto)))
            entidad["presion"], entidad["caudal_lh"] = presion, caudal
            capa.dataProvider().addFeatures([entidad])
            self.proyecto.addMapLayer(capa)
        dialogo = DialogoRed(iface=None)
        self.addCleanup(dialogo.hide)
        dialogo.combo_tuberias.setLayer(tuberias)
        dialogo.combo_dem.setLayer(None)
        dialogo.buscar_valvulas()
        # Sin fuente colocada, calcular lo dice con claridad.
        capa, _ = fuente_mapa.crear_capa_fuente()
        dialogo.combo_fuente.setLayer(capa)
        with mock.patch("riegolibre.gui.dialogo_red.QMessageBox.warning") as aviso:
            dialogo.calcular()
        self.assertIn("Fuente de agua", aviso.call_args[0][2])
        # Con el clic de la herramienta, el combo apunta a la capa y se calcula sin más pasos.
        iface, _ = self._interfaz()
        colocador = ColocarFuente(iface, None, lambda c: dialogo.combo_fuente.setLayer(c))
        _, herramienta = self._iniciar(colocador)
        herramienta.terminar([_p(5, -45)])
        self.assertIs(dialogo.combo_fuente.currentLayer(), capa)
        dialogo.calcular()
        self.assertIsNotNone(dialogo.resultado)
        self.assertEqual(len(dialogo.resultado.red.valvulas), 2)


if __name__ == "__main__":
    unittest.main()
