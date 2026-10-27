"""Turnos de riego en el mapa: bloques bajo el clic, asignación, guardado y ventana de la red (requieren QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsRectangle, QgsVectorLayer

    from riegolibre.integracion import persistencia, turnos_mapa
    from riegolibre.integracion.subunidad_mapa import PROPIEDAD

LOTES = {"A": (10, -45, 90, -5), "B": (100, -45, 190, -5)}  # 80 × 40 m y 90 × 40 m
# Trazado automático «T»: dos subunidades; sus válvulas quedan en el borde, fuera de los polígonos.
SUBUNIDADES = {1: (10, 10, 60, 40), 2: (70, 10, 120, 40)}
VALVULAS = {"A": ((50, -3), 36000.0), "B": ((145, -3), 18000.0), "T 1": ((35, 42), 9000.0),
            "T 2": ((95, 42), 9000.0), "suelta": ((300, 0), 5000.0)}


def _p(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _poligono(x0, y0, x1, y1):
    return QgsGeometry.fromPolygonXY([[_p(x0, y0), _p(x1, y0), _p(x1, y1), _p(x0, y1), _p(x0, y0)]])


def _capa_poligonos(nombre, campos, filas, propiedad):
    capa = QgsVectorLayer(f"Polygon?crs=EPSG:32718&{campos}", nombre, "memory")
    entidades = []
    for atributos, caja in filas:
        entidad = QgsFeature(capa.fields())
        entidad.setGeometry(_poligono(*caja))
        entidad.setAttributes(atributos)
        entidades.append(entidad)
    capa.dataProvider().addFeatures(entidades)
    capa.setCustomProperty(PROPIEDAD, propiedad)
    return capa


def _capa_valvula(nombre, punto, caudal_lh):
    capa = QgsVectorLayer("Point?crs=EPSG:32718&field=presion:double&field=caudal_lh:double",
                          f"Válvula · {nombre}", "memory")
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(_p(*punto)))
    entidad.setAttributes([12.0, caudal_lh])
    capa.dataProvider().addFeatures([entidad])
    return capa


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasTurnosMapa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()
        self.proyecto.setFileName("")
        self.crs = self.proyecto.crs()
        lotes = _capa_poligonos("Lotes", "field=nombre:string&field=bloque:string",
                                [([n, None], caja) for n, caja in LOTES.items()], "lotes")
        bloques = _capa_poligonos("Bloques · T", "field=subunidad:integer",
                                  [([n], caja) for n, caja in SUBUNIDADES.items()], "trazado")
        self.valvulas = [_capa_valvula(n, p, q) for n, (p, q) in VALVULAS.items()]
        self.proyecto.addMapLayers([lotes, bloques] + self.valvulas)
        from qgis.core import QgsCoordinateReferenceSystem
        self.crs = QgsCoordinateReferenceSystem("EPSG:32718")

    def tearDown(self):
        self.proyecto.clear()

    def _bloque(self, x, y):
        return turnos_mapa.bloque_en(_p(x, y), self.crs, 5.0)

    # ------------------------------------------------------------------ qué hay bajo el clic

    def test_clic_en_un_lote_da_su_valvula_por_el_nombre(self):
        bloque = self._bloque(50, -25)
        self.assertEqual(bloque.nombre, "A")
        self.assertEqual([v.id for v in bloque.valvulas], ["A"])  # la válvula está fuera del lote: se halla por nombre

    def test_clic_en_un_bloque_del_trazado_da_la_valvula_de_su_subunidad(self):
        bloque = self._bloque(90, 25)
        self.assertEqual(bloque.nombre, "T 2")
        self.assertEqual([v.id for v in bloque.valvulas], ["T 2"])

    def test_clic_en_una_valvula_suelta_la_marca_con_un_circulo(self):
        bloque = self._bloque(302, 2)
        self.assertEqual([v.id for v in bloque.valvulas], ["suelta"])
        self.assertGreater(bloque.geometria.area(), 0)

    def test_clic_en_un_sitio_vacio_no_da_nada(self):
        self.assertIsNone(self._bloque(250, 100))

    def test_un_lote_oculto_no_se_toca(self):
        capa = self.proyecto.mapLayersByName("Lotes")[0]
        self.proyecto.layerTreeRoot().findLayer(capa.id()).setItemVisibilityChecked(False)
        self.assertIsNone(self._bloque(50, -25))

    def test_rectangulo_marca_todos_los_bloques_que_toca(self):
        rect = QgsRectangle(_p(0, -50), _p(200, 50))
        nombres = sorted(b.nombre for b in turnos_mapa.bloques_en(rect, self.crs, 5.0))
        self.assertEqual(nombres, ["A", "B", "T 1", "T 2"])

    def test_rectangulo_incluye_las_valvulas_sueltas_dentro(self):
        rect = QgsRectangle(_p(280, -20), _p(320, 20))
        self.assertEqual([b.nombre for b in turnos_mapa.bloques_en(rect, self.crs, 5.0)], ["suelta"])

    def test_rectangulo_no_repite_valvulas(self):
        rect = QgsRectangle(_p(0, -50), _p(200, 50))
        ids = [v.id for b in turnos_mapa.bloques_en(rect, self.crs, 5.0) for v in b.valvulas]
        self.assertEqual(len(ids), len(set(ids)))

    # ------------------------------------------------------------------ asignar

    def test_asignar_pinta_el_bloque_y_guarda_el_turno(self):
        self.assertEqual(turnos_mapa.asignar([self._bloque(50, -25), self._bloque(150, -25)], 2, self.crs), 2)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 2, "B": 2})
        capa = turnos_mapa.capa_de_turnos()
        self.assertEqual(capa.featureCount(), 2)
        self.assertEqual(capa.customProperty(PROPIEDAD), turnos_mapa.PROPIEDAD_TURNOS)
        self.assertIn(capa.id(), self.proyecto.mapLayers())

    def test_volver_a_asignar_cambia_el_turno_sin_duplicar(self):
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        turnos_mapa.asignar([self._bloque(50, -25)], 3, self.crs)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 3})
        self.assertEqual(turnos_mapa.capa_de_turnos().featureCount(), 1)

    def test_los_turnos_no_tocan_otros_bloques(self):
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        turnos_mapa.asignar([self._bloque(150, -25)], 2, self.crs)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 1, "B": 2})

    def test_la_capa_de_turnos_no_cuenta_como_bloque_ni_como_valvula(self):
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        from riegolibre.integracion.red_mapa import capas_de_bloques, capas_de_valvulas
        self.assertNotIn(turnos_mapa.capa_de_turnos(), capas_de_bloques())
        self.assertNotIn(turnos_mapa.capa_de_turnos(), capas_de_valvulas())

    def test_quitar_despinta_solo_las_indicadas(self):
        turnos_mapa.asignar([self._bloque(50, -25), self._bloque(150, -25)], 1, self.crs)
        self.assertEqual(turnos_mapa.quitar(["A"]), 1)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"B": 1})
        self.assertEqual(turnos_mapa.quitar(["A"]), 0)

    def test_quitar_todos(self):
        turnos_mapa.asignar([self._bloque(50, -25), self._bloque(150, -25)], 1, self.crs)
        self.assertEqual(turnos_mapa.quitar_todos(), 2)
        self.assertEqual(turnos_mapa.turnos_asignados(), {})

    def test_sin_capa_de_turnos_no_hay_turnos(self):
        self.assertEqual(turnos_mapa.turnos_asignados(), {})
        self.assertEqual(turnos_mapa.quitar(["A"]), 0)
        self.assertEqual(turnos_mapa.quitar_todos(), 0)

    def test_el_poligono_se_guarda_en_el_sistema_de_la_capa_de_turnos(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        capa = turnos_mapa.capa_de_turnos()
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        bloque = self._bloque(150, -25)
        geometria = QgsGeometry(bloque.geometria)
        geometria.transform(QgsCoordinateTransform(self.crs, wgs, self.proyecto))
        bloque.geometria = geometria
        turnos_mapa.asignar([bloque], 2, wgs)  # la capa ya está en UTM: se reproyecta al guardar
        self.assertEqual(capa.crs().authid(), "EPSG:32718")
        caja = {e["valvula"]: e.geometry().boundingBox() for e in capa.getFeatures()}["B"]
        self.assertAlmostEqual(caja.xMinimum(), X0 + 100, delta=1.0)  # el lote B, ya en metros
        self.assertAlmostEqual(caja.xMaximum(), X0 + 190, delta=1.0)

    # ------------------------------------------------------------------ cambiar turnos desde la tabla

    def test_cambiar_un_turno_pintado_solo_cambia_su_atributo(self):
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        turnos_mapa.cambiar_turnos({"A": 4}, self.crs)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 4})
        self.assertEqual(turnos_mapa.capa_de_turnos().featureCount(), 1)

    def test_cambiar_un_turno_sin_pintar_lo_pinta_con_su_bloque(self):
        turnos_mapa.cambiar_turnos({"T 1": 2}, self.crs)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"T 1": 2})
        entidad = next(turnos_mapa.capa_de_turnos().getFeatures())
        self.assertEqual(round(entidad.geometry().area()), 50 * 30)  # el bloque «T 1», no un círculo

    def test_cambiar_el_turno_de_una_valvula_suelta_la_pinta_con_un_circulo(self):
        turnos_mapa.cambiar_turnos({"suelta": 3}, self.crs)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"suelta": 3})

    # ------------------------------------------------------------------ hacia la red

    def test_aplicar_turnos_pone_lo_pintado_y_cuenta_las_que_faltan(self):
        from riegolibre.integracion.red_mapa import capas_de_valvulas, leer_valvulas
        turnos_mapa.asignar([self._bloque(50, -25)], 2, self.crs)
        valvulas = leer_valvulas(capas_de_valvulas(), self.crs)
        sin = turnos_mapa.aplicar_turnos(valvulas, por_defecto={"B": 5})
        por_id = {v.id: v.turno for v in valvulas}
        self.assertEqual(por_id["A"], 2)
        self.assertEqual(por_id["B"], 5)  # no pintada: conserva el de la tabla
        self.assertEqual(por_id["T 1"], 1)  # ni pintada ni en la tabla: turno 1
        self.assertEqual(sin, len(valvulas) - 1)

    def test_resumen_del_proyecto_separa_turnos_y_sin_asignar(self):
        turnos_mapa.asignar([self._bloque(50, -25)], 1, self.crs)
        turnos_mapa.asignar([self._bloque(150, -25)], 2, self.crs)
        resumen = turnos_mapa.resumen_del_proyecto(self.crs)
        self.assertEqual([(t.turno, t.valvulas, t.caudal_lh) for t in resumen.turnos],
                         [(1, 1, 36000.0), (2, 1, 18000.0)])
        self.assertEqual(resumen.sin_asignar, 3)

    # ------------------------------------------------------------------ guardado con el proyecto

    def test_la_capa_de_turnos_se_guarda_en_el_geopackage_y_sigue_funcionando(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as carpeta:
            self.proyecto.setFileName(os.path.join(carpeta, "riego.qgz"))
            turnos_mapa.asignar([self._bloque(50, -25)], 2, self.crs)
            self.assertTrue(persistencia.es_temporal_propia(turnos_mapa.capa_de_turnos()))
            self.assertIn("Turnos de riego", persistencia.guardar_capas_temporales())
            capa = turnos_mapa.capa_de_turnos()
            self.assertEqual(capa.providerType(), "ogr")
            self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 2})
            # Sobre la capa ya guardada (con su campo fid) se puede seguir pintando y quitando.
            turnos_mapa.asignar([self._bloque(150, -25)], 3, self.crs)
            turnos_mapa.cambiar_turnos({"A": 1}, self.crs)
            self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 1, "B": 3})
            turnos_mapa.quitar(["A"])
            self.assertEqual(turnos_mapa.turnos_asignados(), {"B": 3})
            self.proyecto.clear()

    def test_el_estilo_usa_el_color_de_cada_turno(self):
        from riegolibre.nucleo.turnos import PALETA
        turnos_mapa.asignar([self._bloque(50, -25)], 2, self.crs)
        expresion = turnos_mapa.expresion_de_color()
        for color in PALETA:
            self.assertIn(color, expresion)
        capa = turnos_mapa.capa_de_turnos()
        propiedad = capa.renderer().symbol().symbolLayer(0).dataDefinedProperties().property(
            turnos_mapa.QgsSymbolLayer.Property.PropertyFillColor)
        self.assertTrue(propiedad.isActive())
        self.assertTrue(capa.labelsEnabled())


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasHerramientaTurnos(unittest.TestCase):
    """La herramienta con un lienzo real (sin pantalla): clic, arrastre, asignar con el panel."""

    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        from qgis.core import QgsCoordinateReferenceSystem
        from qgis.gui import QgsMapCanvas
        from riegolibre.gui.herramienta_turnos import HerramientaTurnos, PanelTurnos
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()
        self.proyecto.setFileName("")
        lotes = _capa_poligonos("Lotes", "field=nombre:string&field=bloque:string",
                                [([n, None], caja) for n, caja in LOTES.items()], "lotes")
        self.proyecto.addMapLayers([lotes] + [_capa_valvula(n, p, q) for n, (p, q) in VALVULAS.items()
                                              if n in LOTES])
        self.canvas = QgsMapCanvas()
        self.canvas.resize(800, 400)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
        self.canvas.setExtent(QgsRectangle(_p(0, -60), _p(200, 20)))
        self.panel = PanelTurnos()
        self.avisos = []
        self.panel.avisar = self.avisos.append
        self.herramienta = HerramientaTurnos(self.canvas, self.panel)
        self.canvas.setMapTool(self.herramienta)

    def tearDown(self):
        self.herramienta.limpiar()
        self.canvas.unsetMapTool(self.herramienta)
        self.panel.deleteLater()
        self.canvas.deleteLater()
        self.proyecto.clear()

    def _pixel(self, x, y):
        punto = self.canvas.getCoordinateTransform().transform(_p(x, y))
        from qgis.PyQt.QtCore import QPoint
        return QPoint(round(punto.x()), round(punto.y()))

    def _evento(self, tipo, x, y):
        from qgis.gui import QgsMapMouseEvent
        from qgis.PyQt.QtCore import QEvent, QPointF, Qt
        from qgis.PyQt.QtGui import QMouseEvent
        qt_tipo = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                   "release": QEvent.Type.MouseButtonRelease}[tipo]
        boton = Qt.MouseButton.NoButton if tipo == "move" else Qt.MouseButton.LeftButton
        pixel = self._pixel(x, y)
        return QgsMapMouseEvent(self.canvas, QMouseEvent(qt_tipo, QPointF(pixel), boton, boton,
                                                         Qt.KeyboardModifier.NoModifier))

    def _clic(self, x, y):
        self.herramienta.canvasPressEvent(self._evento("press", x, y))
        self.herramienta.canvasReleaseEvent(self._evento("release", x, y))

    def _arrastrar(self, de, a):
        self.herramienta.canvasPressEvent(self._evento("press", *de))
        self.herramienta.canvasMoveEvent(self._evento("move", *a))
        self.herramienta.canvasReleaseEvent(self._evento("release", *a))

    def test_clic_marca_y_otro_clic_desmarca(self):
        self._clic(50, -25)
        self.assertEqual(list(self.herramienta.seleccion), ["A"])
        self.assertEqual(len(self.herramienta.bandas), 1)
        self.assertIn("1 bloques", self.panel.etiqueta_seleccion.text())
        self._clic(50, -25)
        self.assertEqual(self.herramienta.seleccion, {})
        self.assertEqual(self.herramienta.bandas, {})
        self.assertFalse(self.panel.boton_asignar.isEnabled())

    def test_clic_en_un_sitio_vacio_avisa(self):
        self._clic(95, 10)
        self.assertEqual(self.herramienta.seleccion, {})
        self.assertEqual(len(self.avisos), 1)

    def test_arrastrar_un_rectangulo_marca_varios(self):
        self._arrastrar((5, -50), (195, 0))
        self.assertEqual(sorted(self.herramienta.seleccion), ["A", "B"])
        self.assertIn("2 bloques · 2 válvulas · 15.00 L/s", self.panel.etiqueta_seleccion.text())
        self.assertIsNone(self.herramienta.banda_rect)  # el rectángulo de arrastre desaparece al soltar

    def test_un_arrastre_no_desmarca_lo_ya_marcado(self):
        self._clic(50, -25)
        self._arrastrar((5, -50), (195, 0))
        self.assertEqual(sorted(self.herramienta.seleccion), ["A", "B"])
        self.assertEqual(len(self.herramienta.bandas), 2)

    def test_asignar_pinta_limpia_la_seleccion_y_avanza_al_turno_siguiente(self):
        cambios = []
        self.panel.cambio.connect(lambda: cambios.append(1))
        self._arrastrar((5, -50), (195, 0))
        self.panel.spin_turno.setValue(1)
        self.panel.boton_asignar.click()
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 1, "B": 1})
        self.assertEqual(self.herramienta.seleccion, {})
        self.assertEqual(self.panel.spin_turno.value(), 2)  # el siguiente grupo va al turno 2
        self.assertEqual(cambios, [1])
        self.assertEqual(self.panel.tabla.rowCount(), 1)
        self.assertEqual(self.panel.tabla.item(0, 1).text(), "2")
        self._clic(50, -25)  # se puede volver a marcar un bloque ya pintado para cambiarle el turno
        self.panel.boton_asignar.click()
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 2, "B": 1})
        self.assertEqual(self.panel.tabla.rowCount(), 2)

    def test_quitar_el_turno_a_lo_marcado(self):
        turnos_mapa.asignar([turnos_mapa.bloque_en(_p(50, -25), self.canvas.mapSettings().destinationCrs(), 5)], 1,
                            self.canvas.mapSettings().destinationCrs())
        self._clic(50, -25)
        self.panel.boton_quitar.click()
        self.assertEqual(turnos_mapa.turnos_asignados(), {})
        self.assertEqual(self.herramienta.seleccion, {})

    def test_limpiar_no_toca_los_turnos(self):
        self._clic(50, -25)
        self.panel.boton_limpiar.click()
        self.assertEqual(self.herramienta.seleccion, {})
        self.assertEqual(turnos_mapa.turnos_asignados(), {})

    def test_intro_asigna_y_escape_limpia(self):
        from qgis.PyQt.QtCore import QEvent, Qt
        from qgis.PyQt.QtGui import QKeyEvent

        def tecla(clave):
            self.herramienta.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, clave, Qt.KeyboardModifier.NoModifier))

        self._clic(50, -25)
        tecla(Qt.Key.Key_Escape)
        self.assertEqual(self.herramienta.seleccion, {})
        self._clic(50, -25)
        self.panel.spin_turno.setValue(3)
        tecla(Qt.Key.Key_Return)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"A": 3})

    def test_al_desactivar_se_limpia_la_seleccion(self):
        self._clic(50, -25)
        self.canvas.unsetMapTool(self.herramienta)
        self.assertEqual(self.herramienta.seleccion, {})
        self.assertEqual(self.herramienta.bandas, {})

    def test_clic_en_la_tabla_elige_ese_turno(self):
        turnos_mapa.asignar([turnos_mapa.bloque_en(_p(50, -25), self.canvas.mapSettings().destinationCrs(), 5)], 4,
                            self.canvas.mapSettings().destinationCrs())
        self.panel.refrescar(self.canvas.mapSettings().destinationCrs())
        self.panel.spin_turno.setValue(1)
        self.panel.tabla.cellClicked.emit(0, 0)
        self.assertEqual(self.panel.spin_turno.value(), 4)


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasTurnosEnLaVentanaDeLaRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()
        self.proyecto.setFileName("")
        lotes = _capa_poligonos("Lotes", "field=nombre:string&field=bloque:string",
                                [([n, None], caja) for n, caja in LOTES.items()], "lotes")
        self.valvulas = [_capa_valvula(n, p, q) for n, (p, q) in VALVULAS.items() if n in LOTES]
        tuberias = QgsVectorLayer("LineString?crs=EPSG:32718", "Red principal", "memory")
        self.proyecto.addMapLayers([lotes, tuberias] + self.valvulas)
        from riegolibre.gui.dialogo_red import DialogoRed
        self.dialogo = DialogoRed(iface=None)
        self.dialogo.combo_tuberias.setLayer(tuberias)
        self.crs = tuberias.crs()

    def tearDown(self):
        self.dialogo.deleteLater()
        self.proyecto.clear()

    def _fila(self, id_valvula):
        return [v.id for v in self.dialogo.valvulas].index(id_valvula)

    def _turno_en_tabla(self, id_valvula):
        return self.dialogo.tabla_valvulas.cellWidget(self._fila(id_valvula), 3).value()

    def test_buscar_valvulas_toma_los_turnos_pintados_en_el_mapa(self):
        bloque = turnos_mapa.bloque_en(_p(150, -25), self.crs, 5.0)
        turnos_mapa.asignar([bloque], 3, self.crs)
        self.dialogo.buscar_valvulas()
        self.assertEqual(self._turno_en_tabla("A"), 1)
        self.assertEqual(self._turno_en_tabla("B"), 3)
        self.assertEqual([v.turno for v in self.dialogo.valvulas if v.id == "B"], [3])

    def test_pintar_con_la_ventana_abierta_actualiza_la_tabla(self):
        self.dialogo.buscar_valvulas()
        turnos_mapa.asignar([turnos_mapa.bloque_en(_p(50, -25), self.crs, 5.0)], 2, self.crs)
        self.dialogo.cargar_turnos_del_mapa()
        self.assertEqual(self._turno_en_tabla("A"), 2)
        self.assertEqual(self.dialogo.valvulas[self._fila("A")].turno, 2)
        self.assertIn("Desbalance", self.dialogo.etiqueta_turnos.text())

    def test_quitar_en_el_mapa_devuelve_la_valvula_al_turno_1(self):
        self.dialogo.buscar_valvulas()
        turnos_mapa.asignar([turnos_mapa.bloque_en(_p(50, -25), self.crs, 5.0)], 2, self.crs)
        self.dialogo.cargar_turnos_del_mapa()
        turnos_mapa.quitar(["A"])
        self.dialogo.cargar_turnos_del_mapa()
        self.assertEqual(self._turno_en_tabla("A"), 1)

    def test_cambiar_el_turno_en_la_tabla_pinta_el_bloque_en_el_mapa(self):
        self.dialogo.buscar_valvulas()
        self.dialogo.tabla_valvulas.cellWidget(self._fila("B"), 3).setValue(4)
        self.assertEqual(turnos_mapa.turnos_asignados(), {"B": 4})
        self.assertEqual(self.dialogo.valvulas[self._fila("B")].turno, 4)

    def test_volver_a_buscar_conserva_los_turnos(self):
        self.dialogo.buscar_valvulas()
        self.dialogo.tabla_valvulas.cellWidget(self._fila("A"), 3).setValue(2)
        self.dialogo.buscar_valvulas()
        self.assertEqual(self._turno_en_tabla("A"), 2)

    def test_el_nombre_de_la_valvula_lleva_el_color_de_su_turno(self):
        from riegolibre.nucleo.turnos import color_de_turno
        self.dialogo.buscar_valvulas()
        self.dialogo.tabla_valvulas.cellWidget(self._fila("A"), 3).setValue(2)
        color = self.dialogo.tabla_valvulas.item(self._fila("A"), 0).background().color()
        self.assertEqual(color.name(), color_de_turno(2))

    def test_el_boton_del_mapa_llama_a_la_herramienta(self):
        llamadas = []
        self.dialogo.abrir_turnos = lambda: llamadas.append(1)
        self.dialogo.boton_turnos_mapa.click()
        self.assertEqual(llamadas, [1])


if __name__ == "__main__":
    unittest.main()
