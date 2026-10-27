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

    def test_diametros_por_velocidad(self):
        from riegolibre.gui import dialogo_bloque
        from riegolibre.gui.dialogo_diametros import DialogoDiametros
        from riegolibre.integracion.bloque_mapa import DIMENSIONADO_VELOCIDAD
        from riegolibre.integracion.lotes import parametros_guardados
        from riegolibre.nucleo.bloque import PORTA_CENTRO, VALV_CENTRO

        _, capa = self._importar("velocidad.gpkg")
        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar),                 mock.patch.object(clase, "_leer_ultimos", return_value={}),                 mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(None)
            dialogo.spin_separacion.setValue(1.0)  # muchos laterales: caudal alto en el portalateral
            dialogo.radio_usuario.setChecked(True)
            dialogo.spin_azimut.setValue(0.0)  # laterales hacia el norte: portalateral a lo largo de x
            dialogo.combo_porta.setCurrentIndex(dialogo.combo_porta.findData(PORTA_CENTRO))
            dialogo.combo_valvula.setCurrentIndex(dialogo.combo_valvula.findData(VALV_CENTRO))
            dialogo.combo_dem.setLayer(self.dem)
            lote_b = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
            dialogo.abrir_lote(capa, lote_b)
            # En la ventana del bloque: diámetros por velocidad
            dialogo.combo_dimensionado.setCurrentIndex(dialogo.combo_dimensionado.findData(DIMENSIONADO_VELOCIDAD))
            self.assertTrue(dialogo.combo_serie.isEnabled())
            self.assertFalse(dialogo.combo_tuberia_porta.isEnabled())
            dialogo.grupo_criterios.spin_velocidad.setValue(1.0)
            dialogo.aplicar()
            self.assertIn("calculado", dialogo.texto.toPlainText())
            self.assertEqual(parametros_guardados(capa.getFeature(lote_b.id()))["dimensionado"], DIMENSIONADO_VELOCIDAD)

        # La herramienta aparte: todos los lotes diseñados (el lote A no lo está y se salta)
        herramienta = DialogoDiametros(None)
        self.assertTrue(herramienta.combo_serie.currentData().startswith("PVC|"))
        herramienta.spin_velocidad.setValue(0.8)
        herramienta.spin_diametros.setValue(2)
        herramienta.spin_tramo.setValue(0.0)
        herramienta.check_ajustar.setChecked(False)
        html = herramienta.calcular_lotes(capa, list(capa.getFeatures()))
        texto = html
        self.assertIn("Metros de portalateral por tubería", texto)
        self.assertIn("se saltaron", texto)
        datos = parametros_guardados(capa.getFeature(lote_b.id()))
        self.assertAlmostEqual(datos["velocidad_max_ms"], 0.8)
        self.assertEqual(datos["diametros_velocidad"], 2)
        self.assertEqual(datos["direccion"], "usuario")
        raiz = QgsProject.instance().layerTreeRoot()
        tramos = next(n.layer() for n in raiz.findGroup("RiegoLibre · M7. 6").findLayers()
                      if n.layer().name().startswith("Portalateral"))
        velocidades = [f["velocidad"] for f in tramos.getFeatures()]
        self.assertTrue(velocidades)
        self.assertLessEqual(max(velocidades), 0.8 * 1.15)  # con caudales nominales; el real varía poco
        tubos = {f["tuberia"] for f in tramos.getFeatures()}
        self.assertGreaterEqual(len(tubos), 2)  # telescópico
        ramas = {f["rama"] for f in tramos.getFeatures()}
        self.assertEqual(len(ramas), 2)  # válvula al centro


    def test_direccion_y_valvula_marcadas_en_el_mapa(self):
        """Como en IRRICAD: dos puntos fijan la dirección de los laterales y un clic coloca la válvula."""
        from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
        from qgis.PyQt.QtCore import QEvent, QPoint, Qt
        from riegolibre.gui import dialogo_bloque
        from riegolibre.gui.herramienta_puntos import HerramientaPuntos
        from riegolibre.integracion.lotes import parametros_guardados
        from riegolibre.nucleo.bloque import PORTA_INICIO, VALV_AUTO, VALV_PUNTO

        _, capa = self._importar("puntos.gpkg")
        lote_a = next(e for e in capa.getFeatures() if e["nombre"] == "Lote 1")
        canvas = QgsMapCanvas()
        canvas.resize(800, 600)
        canvas.setDestinationCrs(capa.crs())
        canvas.setExtent(capa.extent().buffered(10))
        anterior = HerramientaPuntos(canvas, 1, [], [""], lambda p: None, lambda: None)
        canvas.setMapTool(anterior)

        def clic(x, y, boton=Qt.MouseButton.LeftButton):
            pantalla = canvas.getCoordinateTransform().transform(QgsPointXY(X0 + x, Y0 + y))
            posicion = QPoint(round(pantalla.x()), round(pantalla.y()))
            evento = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, posicion, boton)
            canvas.mapTool().canvasReleaseEvent(evento)

        iface = mock.MagicMock()
        iface.mapCanvas.return_value = canvas
        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(iface)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.spin_costados.setValue(1.0)
            dialogo.spin_cabecera.setValue(0.0)
            dialogo.combo_porta.setCurrentIndex(dialogo.combo_porta.findData(PORTA_INICIO))
            dialogo.combo_dem.setLayer(None)
            dialogo.abrir_lote(capa, lote_a)

            # Dirección: del vértice (90, -45) al (90, -5) del lado este, con clics algo corridos (imán)
            dialogo.marcar_direccion()
            self.assertIsInstance(canvas.mapTool(), HerramientaPuntos)
            self.assertIsNot(canvas.mapTool(), anterior)
            self.assertTrue(dialogo.isHidden())
            clic(89.6, -44.7)
            clic(90.3, -5.4)
            self.assertIs(canvas.mapTool(), anterior)  # vuelve la herramienta que estaba
            self.assertFalse(dialogo.isHidden())
            self.assertTrue(dialogo.radio_usuario.isChecked())
            self.assertAlmostEqual(dialogo.spin_azimut.value(), 0.0)  # hacia el norte
            b = dialogo.bloque
            self.assertAlmostEqual(b.lateral_mas_largo_m, 40.0, places=3)
            self.assertTrue(all(abs(lat.inicio[1] - (Y0 - 45)) < 1e-6 for lat in b.laterales))  # portalateral al sur

            # Válvula: un clic cerca del portalateral (sur, de x = 11 a 89), a 30 m de su extremo oeste
            dialogo.marcar_valvula()
            clic(41.0, -43.0)
            self.assertEqual(dialogo.combo_valvula.currentData(), VALV_PUNTO)
            self.assertAlmostEqual(dialogo.bloque.valvula[0], X0 + 41.0, delta=0.3)  # un píxel
            self.assertAlmostEqual(dialogo.bloque.valvula[1], Y0 - 45.0, places=3)

            # Esc cancela sin cambiar nada
            dialogo.marcar_direccion()
            clic(10.0, -45.0)
            clic(0, 0, Qt.MouseButton.RightButton)
            self.assertIs(canvas.mapTool(), anterior)
            self.assertAlmostEqual(dialogo.spin_azimut.value(), 0.0)

            dialogo.edit_nombre.setText("A-puntos")
            dialogo.aplicar()
            datos = parametros_guardados(capa.getFeature(lote_a.id()))
            self.assertEqual(datos["valvula"], VALV_PUNTO)
            self.assertAlmostEqual(datos["punto_valvula"][0], X0 + 41.0, delta=0.3)
            # Otro lote nuevo no hereda el punto; varios lotes a la vez: válvula automática
            self.assertEqual(dialogo_bloque._sin_punto_de_valvula(datos)["valvula"], VALV_AUTO)
            lote_b = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
            dialogo.abrir_lote(capa, lote_b)
            self.assertIsNone(dialogo.punto_valvula)
        canvas.unsetMapTool(anterior)

    def test_portalateral_dibujado_en_el_mapa(self):
        """Como el «Manual» de IRRICAD: clics en los vértices del portalateral; clic derecho termina."""
        from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
        from qgis.PyQt.QtCore import QEvent, QPoint, Qt
        from riegolibre.gui import dialogo_bloque
        from riegolibre.gui.herramienta_puntos import HerramientaPuntos
        from riegolibre.integracion.lotes import parametros_guardados
        from riegolibre.nucleo.bloque import PORTA_INICIO, PORTA_MANUAL

        _, capa = self._importar("manual.gpkg")
        lote_a = next(e for e in capa.getFeatures() if e["nombre"] == "Lote 1")
        canvas = QgsMapCanvas()
        canvas.resize(800, 600)
        canvas.setDestinationCrs(capa.crs())
        canvas.setExtent(capa.extent().buffered(10))
        anterior = HerramientaPuntos(canvas, 1, [], [""], lambda p: None, lambda: None)
        canvas.setMapTool(anterior)

        def clic(x, y, boton=Qt.MouseButton.LeftButton):
            pantalla = canvas.getCoordinateTransform().transform(QgsPointXY(X0 + x, Y0 + y))
            posicion = QPoint(round(pantalla.x()), round(pantalla.y()))
            evento = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, posicion, boton)
            canvas.mapTool().canvasReleaseEvent(evento)

        iface = mock.MagicMock()
        iface.mapCanvas.return_value = canvas
        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(iface)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.spin_costados.setValue(1.0)
            dialogo.spin_cabecera.setValue(0.0)
            dialogo.combo_porta.setCurrentIndex(dialogo.combo_porta.findData(PORTA_INICIO))
            dialogo.combo_dem.setLayer(None)
            dialogo.abrir_lote(capa, lote_a)

            # Un solo punto y clic derecho: se cancela
            dialogo.dibujar_portalateral()
            self.assertIsInstance(canvas.mapTool(), HerramientaPuntos)
            self.assertIsNone(canvas.mapTool().cuantos)
            self.assertTrue(dialogo.isHidden())
            clic(50.0, -45.0)
            clic(0, 0, Qt.MouseButton.RightButton)
            self.assertIs(canvas.mapTool(), anterior)
            self.assertFalse(dialogo.isHidden())
            self.assertIsNone(dialogo.puntos_portalateral)
            self.assertNotEqual(dialogo.combo_porta.currentData(), PORTA_MANUAL)

            # Línea vertical por x = 50 de sur a norte
            dialogo.dibujar_portalateral()
            clic(50.0, -44.0)
            clic(50.0, -6.0)
            clic(0, 0, Qt.MouseButton.RightButton)
            self.assertIs(canvas.mapTool(), anterior)
            self.assertEqual(dialogo.combo_porta.currentData(), PORTA_MANUAL)
            self.assertEqual(len(dialogo.puntos_portalateral), 2)
            b = dialogo.bloque
            self.assertIsNotNone(b)
            # Laterales perpendiculares a la línea (los clics caen en píxeles enteros: casi vertical)
            self.assertLess(min(b.angulo_deg % 180.0, 180.0 - b.angulo_deg % 180.0), 1.0)
            self.assertEqual({lat.lado for lat in b.laterales}, {"A", "B"})
            self.assertTrue(all(abs(lat.inicio[0] - (X0 + 50.0)) < 0.6 for lat in b.laterales))
            self.assertAlmostEqual(b.longitud_portalateral_m, 40.0, delta=0.6)  # el imán la lleva a los bordes

            dialogo.edit_nombre.setText("A-manual")
            dialogo.aplicar()
            datos = parametros_guardados(capa.getFeature(lote_a.id()))
            self.assertEqual(datos["portalateral"], PORTA_MANUAL)
            self.assertEqual(len(datos["puntos_portalateral"]), 2)
            # Otros lotes no heredan la línea
            otros = dialogo_bloque._sin_punto_de_valvula(datos)
            self.assertEqual(otros["portalateral"], PORTA_INICIO)
            self.assertIsNone(otros["puntos_portalateral"])
            lote_b = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
            dialogo.abrir_lote(capa, lote_b)
            self.assertIsNone(dialogo.puntos_portalateral)
            # Volver al primero recupera su línea
            dialogo.abrir_lote(capa, capa.getFeature(lote_a.id()))
            self.assertEqual(len(dialogo.puntos_portalateral), 2)
        canvas.unsetMapTool(anterior)

    def test_tramos_de_conexion_en_el_mapa(self):
        """«Stub Length», «Submain Stub» y «Valve Stub»: se dibujan y entran en el metrado, sin cambiar el cálculo."""
        from riegolibre.gui import dialogo_bloque
        from riegolibre.integracion import materiales_mapa
        from riegolibre.integracion.lotes import parametros_guardados
        from riegolibre.nucleo.bloque import CONEXION_RAMAL_VALVULA, PORTA_INICIO, VALV_CENTRO, VALV_INICIO

        _, capa = self._importar("conexiones.gpkg")
        lote_a = next(e for e in capa.getFeatures() if e["nombre"] == "Lote 1")
        clase = dialogo_bloque.DialogoBloque
        raiz = QgsProject.instance().layerTreeRoot()

        def capas_del_grupo():
            return {n.layer().name().split(" · ")[0]: n.layer()
                    for n in raiz.findGroup("RiegoLibre · A-conex").findLayers()}

        def metros_portalateral():
            partidas, _ = materiales_mapa.partidas_del_proyecto()
            return sum(p.cantidad for p in partidas if p.categoria == "Portalaterales")

        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(None)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.spin_costados.setValue(1.0)
            dialogo.spin_cabecera.setValue(0.0)
            dialogo.radio_usuario.setChecked(True)
            dialogo.spin_azimut.setValue(0.0)  # laterales al norte: el portalateral va por el este
            dialogo.combo_porta.setCurrentIndex(dialogo.combo_porta.findData(PORTA_INICIO))
            dialogo.combo_valvula.setCurrentIndex(dialogo.combo_valvula.findData(VALV_INICIO))
            dialogo.combo_dem.setLayer(None)
            dialogo.abrir_lote(capa, lote_a)
            dialogo.edit_nombre.setText("A-conex")
            dialogo.aplicar()
            self.assertNotIn("Conexiones", capas_del_grupo())
            presion = next(capas_del_grupo()["Válvula"].getFeatures())["presion"]
            sin_tramos = metros_portalateral()
            valvula_sin = next(capas_del_grupo()["Válvula"].getFeatures()).geometry().asPoint()

            dialogo.spin_prolongacion_extremo.setValue(1.0)
            dialogo.spin_prolongacion_valvula.setValue(0.5)
            dialogo.spin_ramal_valvula.setValue(2.0)
            dialogo.aplicar()
            capas = capas_del_grupo()
            self.assertIn("Conexiones", capas)
            self.assertEqual(materiales_mapa._tipo(capas["Conexiones"]), "conexiones")
            conexiones = list(capas["Conexiones"].getFeatures())
            self.assertEqual(len(conexiones), 3)
            self.assertAlmostEqual(sum(f["longitud"] for f in conexiones), 3.5, places=3)
            self.assertTrue(all(f["tuberia"] for f in conexiones))
            ramal = next(f for f in conexiones if f["conexion_tipo"] == CONEXION_RAMAL_VALVULA)
            # Con los laterales al norte, el portalateral va de este (extremo 1, donde está la válvula) a oeste: la
            # prolongación sale hacia el este y el ramal hacia la izquierda del sentido, el sur
            valvula = next(capas["Válvula"].getFeatures()).geometry().asPoint()
            self.assertAlmostEqual(valvula.y(), valvula_sin.y() - 2.0, places=3)
            self.assertAlmostEqual(valvula.x(), valvula_sin.x() + 0.5, places=3)
            self.assertAlmostEqual(ramal.geometry().length(), 2.0, places=3)
            # No cambia el cálculo y sí el metrado
            self.assertAlmostEqual(next(capas["Válvula"].getFeatures())["presion"], presion, places=6)
            self.assertAlmostEqual(metros_portalateral() - sin_tramos, 3.5, places=3)
            datos = parametros_guardados(capa.getFeature(lote_a.id()))
            self.assertEqual(datos["ramal_valvula_m"], 2.0)
            # Con la válvula al centro, la prolongación del lado de la válvula no aplica
            dialogo.combo_valvula.setCurrentIndex(dialogo.combo_valvula.findData(VALV_CENTRO))
            dialogo._actualizar()
            self.assertFalse(dialogo.spin_prolongacion_valvula.isEnabled())
            dialogo.aplicar()
            self.assertEqual(len(list(capas_del_grupo()["Conexiones"].getFeatures())), 3)  # 2 extremos + ramal

    def test_eliminar_bloque_con_ctrl_clic(self):
        """Como en IRRICAD: Ctrl + clic en el lote elimina su bloque; un clic normal lo abre."""
        from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
        from qgis.PyQt.QtCore import QEvent, QPoint, Qt
        from qgis.PyQt.QtGui import QKeyEvent
        from riegolibre.gui import dialogo_bloque
        from riegolibre.gui.herramienta_bloque import HerramientaBloque
        from riegolibre.integracion import bloque_mapa
        from riegolibre.integracion.lotes import capas_de_lotes, parametros_guardados

        bloque_mapa._eliminados.clear()
        _, capa = self._importar("eliminar.gpkg")
        raiz = QgsProject.instance().layerTreeRoot()
        otras = [raiz.findLayer(c.id()) for c in capas_de_lotes() if c is not capa]
        for nodo in otras:  # los lotes de otras pruebas están en el mismo lugar
            nodo.setItemVisibilityChecked(False)
        lote_a = next(e for e in capa.getFeatures() if e["nombre"] == "Lote 1")
        canvas = QgsMapCanvas()
        canvas.resize(800, 600)
        canvas.setDestinationCrs(capa.crs())
        canvas.setExtent(capa.extent().buffered(10))

        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            dialogo = clase(None)
            dialogo.spin_separacion.setValue(2.0)
            dialogo.combo_dem.setLayer(None)
            abiertos = []
            herramienta = HerramientaBloque(canvas, lambda c, e: abiertos.append(e["nombre"]), _fallar,
                                            dialogo.confirmar_eliminar)

            def clic(x, y, ctrl):
                pantalla = canvas.getCoordinateTransform().transform(QgsPointXY(X0 + x, Y0 + y))
                evento = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease,
                                          QPoint(round(pantalla.x()), round(pantalla.y())), Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier)
                herramienta.canvasReleaseEvent(evento)

            def disenar():
                dialogo.abrir_lote(capa, capa.getFeature(lote_a.id()))
                dialogo.edit_nombre.setText("E1")
                dialogo.aplicar()
                self.assertIsNotNone(raiz.findGroup("RiegoLibre · E1"))

            disenar()
            clic(50, -25, ctrl=False)
            self.assertEqual(abiertos, ["E1"])

            # Cancelar no cambia nada; mientras se pregunta, el lote queda seleccionado (resaltado)
            capa.selectByIds([])
            vistos = []

            def responder(eleccion):
                def preguntar(nombre, grupo, padre):
                    vistos.append((nombre, grupo, capa.selectedFeatureIds()))
                    return eleccion
                return preguntar

            with mock.patch.object(dialogo, "_preguntar_eliminar", side_effect=responder(None)):
                clic(50, -25, ctrl=True)
            self.assertEqual(vistos, [("E1", "RiegoLibre · E1", [lote_a.id()])])
            self.assertEqual(capa.selectedFeatureIds(), [])
            self.assertIsNotNone(raiz.findGroup("RiegoLibre · E1"))

            # Eliminar solo el bloque: el lote queda, sin diseñar
            with mock.patch.object(dialogo, "_preguntar_eliminar",
                                   side_effect=responder(dialogo_bloque.ELIMINAR_BLOQUE)):
                clic(50, -25, ctrl=True)
            self.assertIsNone(raiz.findGroup("RiegoLibre · E1"))
            lote = capa.getFeature(lote_a.id())
            self.assertTrue(lote.isValid())
            self.assertIsNone(parametros_guardados(lote))
            self.assertIn("sin diseñar", dialogo.etiqueta_lote.text())
            self.assertEqual(len(abiertos), 1)  # Ctrl + clic no abre la ventana

            # Deshacer (Ctrl + Z en la ventana): vuelven las mismas capas y los parámetros
            self.assertEqual(dialogo.deshacer(), "Se recuperó el bloque de goteo del lote «E1».")
            grupo = raiz.findGroup("RiegoLibre · E1")
            self.assertEqual(sorted(n.layer().name().split(" · ")[0] for n in grupo.findLayers()),
                             ["Laterales", "Portalateral", "Válvula"])
            self.assertEqual(parametros_guardados(capa.getFeature(lote_a.id()))["separacion_m"], 2.0)
            self.assertNotIn("sin diseñar", dialogo.etiqueta_lote.text())
            self.assertIsNone(dialogo.deshacer())  # no queda nada por deshacer

            # Eliminar el bloque y el lote, y recuperarlos con Ctrl + Z en el mapa
            with mock.patch.object(dialogo, "_preguntar_eliminar",
                                   side_effect=responder(dialogo_bloque.ELIMINAR_CON_LOTE)):
                dialogo.eliminar()  # botón «Eliminar bloque…» de la ventana
            self.assertIsNone(raiz.findGroup("RiegoLibre · E1"))
            self.assertFalse(capa.getFeature(lote_a.id()).isValid())
            self.assertEqual(sorted(e["nombre"] for e in capa.getFeatures()), ["M7. 6"])
            self.assertIsNone(dialogo.capa)
            self.assertIn("y el lote", dialogo.texto.toPlainText())
            herramienta.deshacer = dialogo.deshacer
            herramienta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z,
                                                Qt.KeyboardModifier.ControlModifier))
            self.assertEqual(sorted(e["nombre"] for e in capa.getFeatures()), ["E1", "M7. 6"])
            recuperado = next(e for e in capa.getFeatures() if e["nombre"] == "E1")
            self.assertAlmostEqual(recuperado.geometry().area(), 80 * 40, places=3)
            self.assertEqual(parametros_guardados(recuperado)["separacion_m"], 2.0)
            self.assertIsNotNone(raiz.findGroup("RiegoLibre · E1"))

            # Si el lote se volvió a calcular después de eliminarlo, deshacer no pisa el bloque nuevo
            lote_a = recuperado
            with mock.patch.object(dialogo, "_preguntar_eliminar",
                                   side_effect=responder(dialogo_bloque.ELIMINAR_BLOQUE)):
                clic(50, -25, ctrl=True)
            disenar()
            with self.assertRaisesRegex(ValueError, "ya tiene otra vez un bloque"):
                bloque_mapa.deshacer_eliminacion()
        for nodo in otras:
            nodo.setItemVisibilityChecked(True)

    def test_tabla_de_zonas(self):
        """Como «Zone Design Configuration» de IRRICAD: todas las zonas, con cambios por zona y su resultado."""
        from qgis.PyQt.QtCore import Qt
        from riegolibre.gui import dialogo_bloque, dialogo_zonas
        from riegolibre.gui.dialogo_zonas import (C_DIAMETROS, C_PERMITIDA_MAX, C_PERMITIDA_MIN, C_PROCESAR,
                                                  C_RESULTADO, C_VALVULA_DESEADA, C_VALVULA_REAL, C_ZONA)
        from riegolibre.integracion.lotes import parametros_guardados

        _, capa = self._importar("zonas.gpkg")
        lote_b = next(e for e in capa.getFeatures() if e["nombre"] == "M7. 6")
        clase = dialogo_bloque.DialogoBloque
        with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                mock.patch.object(clase, "_guardar_ultimos"):
            bloque = clase(None)
            bloque.spin_separacion.setValue(2.0)
            bloque.radio_usuario.setChecked(True)
            bloque.spin_azimut.setValue(90.0)
            bloque.combo_dem.setLayer(None)
            bloque.abrir_lote(capa, lote_b)
            bloque.aplicar()  # solo el lote B queda diseñado
        guardado = parametros_guardados(capa.getFeature(lote_b.id()))
        self.assertIn("resultado", guardado)

        with mock.patch.object(dialogo_zonas.QMessageBox, "warning", side_effect=_fallar):
            zonas = dialogo_zonas.DialogoZonas(None)
            zonas.combo_capa.addItem(capa.name(), capa.id())
            zonas.combo_capa.setCurrentIndex(zonas.combo_capa.findData(capa.id()))
            zonas.llenar()
            t = zonas.tabla
            self.assertEqual(t.rowCount(), 2)
            filas = {t.item(f, C_ZONA).text(): f for f in range(t.rowCount())}
            a, b = filas["Lote 1"], filas["M7. 6"]
            self.assertIn("sin diseñar", t.item(a, C_RESULTADO).text())
            self.assertFalse(t.item(a, C_PROCESAR).flags() & Qt.ItemFlag.ItemIsUserCheckable)
            self.assertEqual(t.item(b, C_PROCESAR).checkState(), Qt.CheckState.Checked)
            real = float(t.item(b, C_VALVULA_REAL).text())
            self.assertAlmostEqual(real, guardado["resultado"]["presion_valvula_m"])
            # La mínima permitida viene de la base de datos (gris) y no cuenta como cambio
            emisor = zonas._emisor(guardado["emisor"])
            if emisor.presion_min_m is not None:
                self.assertEqual(float(t.item(b, C_PERMITIDA_MIN).text()), emisor.presion_min_m)
            self.assertIsNone(zonas.cambios(b)["presion_permitida_min_m"])

            # Cambios de la zona: presión deseada en la válvula, máxima permitida baja y 2 diámetros
            t.item(b, C_VALVULA_DESEADA).setText(f"{real + 5:.2f}")
            t.item(b, C_PERMITIDA_MAX).setText("1")
            t.item(b, C_PERMITIDA_MIN).setText("0,5")
            t.cellWidget(b, C_DIAMETROS).setValue(2)
            cambios = zonas.cambios(b)
            self.assertAlmostEqual(cambios["presion_permitida_min_m"], 0.5)
            fallos = zonas.calcular_filas(capa, {b: cambios})
            self.assertEqual(fallos, [])
            datos = parametros_guardados(capa.getFeature(lote_b.id()))
            self.assertAlmostEqual(datos["presion_conocida_m"], real + 5, places=2)
            self.assertEqual(datos["presion_permitida_max_m"], 1.0)
            self.assertEqual(datos["diametros_max"], 2)
            self.assertAlmostEqual(datos["resultado"]["presion_valvula_m"], real + 5, places=1)
            self.assertTrue(any("permitida" in m for m in datos["resultado"]["motivos"]))
            self.assertTrue(t.item(b, C_RESULTADO).text().startswith("✘"))
            self.assertIsNotNone(QgsProject.instance().layerTreeRoot().findGroup("RiegoLibre · M7. 6"))

            # Un número malo se avisa con el nombre de la zona
            t.item(b, C_PERMITIDA_MAX).setText("abc")
            with self.assertRaises(ValueError) as error:
                zonas.cambios(b)
            self.assertIn("M7. 6", str(error.exception))

            # La ventana del bloque conserva las claves de la tabla al volver a aplicar
            with mock.patch.object(dialogo_bloque.QMessageBox, "warning", side_effect=_fallar), \
                    mock.patch.object(clase, "_leer_ultimos", return_value={}), \
                    mock.patch.object(clase, "_guardar_ultimos"):
                otra = clase(None)
                otra.abrir_lote(capa, capa.getFeature(lote_b.id()))
                otra.aplicar()
            self.assertEqual(parametros_guardados(capa.getFeature(lote_b.id()))["presion_permitida_max_m"], 1.0)

if __name__ == "__main__":
    unittest.main()
