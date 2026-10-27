"""Pruebas de la red principal dibujada en el mapa (requieren el Python de QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _crear_dem, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                           QgsRasterLayer, QgsVectorLayer)

FUENTE = (5, -45)
# Tubería principal con un quiebre y una rama en T (dibujada al revés, desde la válvula).
PRINCIPAL = [(5, -45), (150, -45), (150, -10)]
RAMA = [(80, -10), (80, -45)]
VALVULAS = {"A": ((150, -10), 20000.0, 12.0), "B": ((80, -10), 15000.0, 10.0)}


def _p(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _capa_lineas(lineas, nombre="Red principal"):
    capa = QgsVectorLayer("LineString?crs=EPSG:32718", nombre, "memory")
    entidades = []
    for puntos in lineas:
        entidad = QgsFeature()
        entidad.setGeometry(QgsGeometry.fromPolylineXY([_p(*p) for p in puntos]))
        entidades.append(entidad)
    capa.dataProvider().addFeatures(entidades)
    return capa


def _capa_punto(punto, nombre, campos="", valores=()):
    capa = QgsVectorLayer(f"Point?crs=EPSG:32718{campos}", nombre, "memory")
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(_p(*punto)))
    if valores:
        entidad.setAttributes(list(valores))
    capa.dataProvider().addFeatures([entidad])
    return capa


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasRedMapa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        QgsProject.instance().removeAllMapLayers()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta)
        cls.dem = QgsRasterLayer(ruta, "dem")
        cls.tuberias = _capa_lineas([PRINCIPAL, RAMA])
        cls.fuente = _capa_punto(FUENTE, "Fuente")
        cls.capas_valvula = [
            _capa_punto(p, f"Válvula · {nombre}", "&field=presion:double&field=caudal_lh:double", (pr, q))
            for nombre, (p, q, pr) in VALVULAS.items()]
        QgsProject.instance().addMapLayers([cls.dem, cls.tuberias, cls.fuente] + cls.capas_valvula)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def _red(self, muestreador=True, tolerancia=0.5, turnos=None):
        from riegolibre.integracion.perfil_terreno import MuestreadorDem
        from riegolibre.integracion.red_mapa import capas_de_valvulas, construir_red, leer_valvulas
        crs = self.tuberias.crs()
        valvulas = leer_valvulas(capas_de_valvulas(), crs)
        for v in valvulas:
            v.turno = (turnos or {}).get(v.id, 1)
        return construir_red(self.tuberias, _p(*FUENTE), valvulas, crs,
                             MuestreadorDem(self.dem, crs) if muestreador else None,
                             tolerancia_m=tolerancia, perdida_valvula_m=2.0)

    def test_topologia_con_union_en_t(self):
        red_mapa = self._red()
        red = red_mapa.red
        self.assertEqual(sorted(v.id for v in red.valvulas), ["A", "B"])
        longitudes = sorted(round(t.longitud_m, 6) for t in red.tramos)
        self.assertEqual(longitudes, [35.0, 75.0, 105.0])
        # La rama se dibujó desde la válvula: debe quedar orientada desde la unión.
        rama = red.padre[next(v.nodo for v in red.valvulas if v.id == "B")]
        self.assertAlmostEqual(rama.longitud_m, 35.0)
        self.assertEqual(red.padre[rama.desde].desde, red.fuente)
        self.assertAlmostEqual(red.cotas[red.fuente], 100 + 0.02 * 5.5, places=4)

    def test_carga_igual_al_calculo_manual(self):
        from riegolibre.nucleo import CriteriosRed, cargar_catalogo_tuberias, dimensionar_red
        from riegolibre.nucleo.hidraulica import LH_A_M3S
        red = self._red(turnos={"A": 1, "B": 2}).red
        criterios = CriteriosRed(presion_min_m=0.0, factor_perdidas_menores=0.1)
        resultado = dimensionar_red(red, cargar_catalogo_tuberias(uso="principal"), criterios)
        valvula_a = next(v for v in red.valvulas if v.id == "A")
        turno = resultado.turno(1)
        perdidas = sum(resultado.asignacion[t.id].perdida(20000 * LH_A_M3S, t.longitud_m) * 1.1
                       for t in red.camino(valvula_a.nodo))
        esperado = red.cotas[valvula_a.nodo] + 12.0 + 2.0 + perdidas
        self.assertAlmostEqual(turno.carga_fuente_m, esperado, places=6)
        self.assertEqual(turno.critico, "válvula A")
        self.assertEqual(resultado.motivos, {})

    def test_valvula_lejos_de_la_tuberia(self):
        from riegolibre.integracion.red_mapa import ValvulaMapa, construir_red
        lejana = ValvulaMapa("Lejana", _p(120, -30), 1000.0, 10.0)
        with self.assertRaisesRegex(ValueError, "Lejana.*0.5 m"):
            construir_red(self.tuberias, _p(*FUENTE), [lejana], self.tuberias.crs())

    def test_trazado_automatico_conecta_y_se_calcula(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        from riegolibre.integracion.red_mapa import NOMBRE_CAPA_AUTOMATICA
        dialogo = DialogoRed(iface=None)
        dialogo.combo_fuente.setLayer(self.fuente)
        dialogo.combo_tuberias.setLayer(self.tuberias)
        dialogo.buscar_valvulas()
        dialogo.trazar_red_automatica()
        capa = dialogo.combo_tuberias.currentLayer()
        self.assertEqual(capa.name(), NOMBRE_CAPA_AUTOMATICA)
        self.assertGreater(capa.featureCount(), 1)
        # Repetir el trazado reutiliza la misma capa.
        dialogo.trazar_red_automatica()
        self.assertEqual(sum(1 for c in QgsProject.instance().mapLayers().values()
                             if c.name() == NOMBRE_CAPA_AUTOMATICA), 1)
        # La red trazada se calcula sin cambios y conecta las dos válvulas.
        dialogo.calcular()
        self.assertIsNotNone(dialogo.resultado)
        self.assertEqual({v.id for v in dialogo.resultado.red.valvulas}, {"A", "B"})
        self.assertEqual(dialogo.resultado.motivos, {})
        QgsProject.instance().removeMapLayer(capa.id())

    # ------------------------------------------- trazado con restricciones

    @staticmethod
    def _capa_zona(x0, y0, x1, y1):
        capa = QgsVectorLayer("Polygon?crs=EPSG:32718", "zona", "memory")
        entidad = QgsFeature()
        entidad.setGeometry(QgsGeometry.fromPolygonXY(
            [[_p(x0, y0), _p(x1, y0), _p(x1, y1), _p(x0, y1), _p(x0, y0)]]))
        capa.dataProvider().addFeatures([entidad])
        return capa

    def _trazar_con(self, restricciones, modo):
        from riegolibre.integracion.red_mapa import (capas_de_valvulas, leer_valvulas,
                                                     trazar_red_en_mapa)
        crs = self.tuberias.crs()
        valvulas = leer_valvulas(capas_de_valvulas(), crs)
        capa, red = trazar_red_en_mapa(_p(*FUENTE), valvulas, crs, modo, restricciones=restricciones)
        self.addCleanup(QgsProject.instance().removeMapLayer, capa.id())
        return capa, red

    def test_trazado_rodea_una_zona_prohibida(self):
        from riegolibre.integracion.red_mapa import RestriccionesTrazado
        from riegolibre.nucleo.trazado_red import DIRECTO, ORTOGONAL
        zona = self._capa_zona(40, -60, 100, -30)  # tapa el paso a lo largo de la fuente
        poligono = next(zona.getFeatures()).geometry()
        libre, _ = self._trazar_con(None, DIRECTO)
        largo_libre = sum(f.geometry().length() for f in libre.getFeatures())
        for modo in (DIRECTO, ORTOGONAL):
            capa, red = self._trazar_con(RestriccionesTrazado(capa_zonas=zona, factor_zonas=None), modo)
            self.assertGreater(capa.featureCount(), 1)
            for entidad in capa.getFeatures():
                self.assertLess(entidad.geometry().intersection(poligono).length(), 0.5)
            self.assertLess(red.m_penalizados, red.celda_m)  # solo el redondeo de la cuadrícula
            self.assertIsNotNone(red.celda_m)
        self.assertGreater(sum(f.geometry().length() for f in capa.getFeatures()), largo_libre)

    def test_trazado_con_relieve_lee_el_dem(self):
        from riegolibre.integracion.red_mapa import RestriccionesTrazado, construir_terreno
        from riegolibre.nucleo.trazado_red import DIRECTO
        crs = self.tuberias.crs()
        puntos = [(X0 + 5, Y0 - 45), (X0 + 150, Y0 - 10)]
        terreno = construir_terreno(puntos, crs, RestriccionesTrazado(capa_dem=self.dem))
        # El DEM sube 2 cm por metro hacia el este (y vale 100 m en el origen).
        self.assertAlmostEqual(terreno.cota_en(X0 + 50.4, Y0 - 25.4), 100 + 0.02 * 50.5, delta=0.1)
        self.assertAlmostEqual(terreno.cota_en(X0 + 150.4, Y0 - 25.4), 100 + 0.02 * 150.5, delta=0.1)
        capa, red = self._trazar_con(RestriccionesTrazado(capa_dem=self.dem), DIRECTO)
        self.assertGreater(capa.featureCount(), 1)

    def test_dialogo_traza_con_zona_y_relieve(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        zona = self._capa_zona(40, -60, 100, -30)
        QgsProject.instance().addMapLayer(zona)
        try:
            dialogo = DialogoRed(iface=None)
            dialogo.combo_fuente.setLayer(self.fuente)
            dialogo.combo_tuberias.setLayer(self.tuberias)
            dialogo.combo_zonas.setLayer(zona)
            dialogo.check_zonas_prohibidas.setChecked(True)
            dialogo.combo_dem.setLayer(self.dem)
            dialogo.check_relieve.setChecked(True)
            dialogo.buscar_valvulas()
            dialogo.trazar_red_automatica()
            capa = dialogo.combo_tuberias.currentLayer()
            poligono = next(zona.getFeatures()).geometry()
            for entidad in capa.getFeatures():
                self.assertLess(entidad.geometry().intersection(poligono).length(), 0.5)
            self.assertIn("Mapa de costos", dialogo.texto.toPlainText())
            dialogo.calcular()
            self.assertIsNotNone(dialogo.resultado)
            QgsProject.instance().removeMapLayer(capa.id())
        finally:
            QgsProject.instance().removeMapLayer(zona.id())

    def test_dialogo_sin_capas_no_hay_restricciones(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        dialogo = DialogoRed(iface=None)
        dialogo.combo_dem.setLayer(None)
        self.assertIsNone(dialogo.restricciones_de_trazado())
        dialogo.check_relieve.setChecked(True)
        self.assertIsNone(dialogo.restricciones_de_trazado())  # sin DEM elegido no hay nada que aplicar
        dialogo.combo_dem.setLayer(self.dem)
        self.assertIsNotNone(dialogo.restricciones_de_trazado())

    def test_dialogo_calcula_y_crea_capas(self):
        from riegolibre.gui.dialogo_red import NOMBRE_GRUPO, DialogoRed
        dialogo = DialogoRed(iface=None)
        dialogo.combo_tuberias.setLayer(self.tuberias)
        dialogo.combo_fuente.setLayer(self.fuente)
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.buscar_valvulas()
        self.assertEqual(dialogo.tabla_valvulas.rowCount(), 2)
        fila_b = [v.id for v in dialogo.valvulas].index("B")
        dialogo.tabla_valvulas.cellWidget(fila_b, 3).setValue(2)
        dialogo.calcular()

        resultado = dialogo.resultado
        self.assertEqual([r.turno for r in resultado.turnos], [1, 2])
        self.assertEqual(dialogo.tabla_turnos.rowCount(), 2)
        self.assertEqual(dialogo.tabla_tramos.rowCount(), 3)
        grupo = QgsProject.instance().layerTreeRoot().findGroup(NOMBRE_GRUPO)
        capas = {n.layer().name(): n.layer() for n in grupo.findLayers()}
        self.assertEqual(set(capas), {"Red principal · tuberías", "Red principal · válvulas",
                                      "Red principal · bomba"})
        bomba = next(capas["Red principal · bomba"].getFeatures())
        critico = resultado.turno_critico
        self.assertAlmostEqual(bomba["cdt_m"], critico.presion_entrada_red_m + 7.0 + 2.0, places=2)
        from riegolibre.integracion.memoria_mapa import resumenes_del_proyecto
        _subunidades, red, _avisos = resumenes_del_proyecto()
        self.assertAlmostEqual(red["bomba"]["cdt_m"], bomba["cdt_m"], places=2)
        self.assertEqual(len(red["tramos"]), 3)
        excesos = {f["valvula"]: f["exceso"] for f in capas["Red principal · válvulas"].getFeatures()}
        self.assertAlmostEqual(min(excesos.values()), 0.0, places=2)
        self.assertIn("Punto de diseño de la bomba", dialogo.texto.toPlainText())

    def test_dialogo_con_equipos_de_la_base_sin_caudal_minimo(self):
        # La base importada de IRRICAD puede traer el caudal mínimo vacío: la ventana no debe caerse.
        from unittest import mock

        from riegolibre.gui.dialogo_red import DialogoRed, _texto_rango
        from riegolibre.nucleo.base_datos import (VARIABLE_RUTA, BaseDatos, ElementoHidraulico,
                                                  guardar_base)
        valvula = ElementoHidraulico('Válvula 2"', k=0.004, n=2.0, c=1.5, caudal_max_m3h=25.0)
        filtro = ElementoHidraulico("Filtro anillas", k=0.002, n=2.0, c=1.0,
                                    caudal_min_m3h=5.0, caudal_max_m3h=25.0)
        sin_rango = ElementoHidraulico("Hidrociclón", k=0.001, n=2.0)
        self.assertEqual(_texto_rango(valvula), " (0–25 m³/h)")
        self.assertEqual(_texto_rango(filtro), " (5–25 m³/h)")
        self.assertEqual(_texto_rango(sin_rango), "")
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "base_datos.json")
            guardar_base(BaseDatos(valvulas=[valvula], hidraulicos=[filtro, sin_rango]), ruta)
            with mock.patch.dict(os.environ, {VARIABLE_RUTA: ruta}):
                dialogo = DialogoRed(iface=None)
                self.assertEqual(dialogo.combo_valvula_base.itemText(1), 'Válvula 2" (0–25 m³/h)')
                self.assertEqual(dialogo.combo_hidraulico_cabezal.itemText(1), "Filtro anillas (5–25 m³/h)")
                self.assertEqual(dialogo.combo_hidraulico_cabezal.itemText(2), "Hidrociclón")
                dialogo.combo_valvula_base.setCurrentIndex(1)
                dialogo.combo_hidraulico_cabezal.setCurrentIndex(1)
                dialogo.combo_tuberias.setLayer(self.tuberias)
                dialogo.combo_fuente.setLayer(self.fuente)
                dialogo.combo_dem.setLayer(self.dem)
                dialogo.buscar_valvulas()
                dialogo.calcular()
                critico = dialogo.resultado.turno_critico
                cabezal = 7.0 + 0.002 * (critico.caudal_total_lh / 1000) ** 2 + 1.0
                self.assertIn(f"cabezal {cabezal:.1f}", dialogo.texto.toPlainText())


if __name__ == "__main__":
    unittest.main()
