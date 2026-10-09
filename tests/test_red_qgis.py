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
        excesos = {f["valvula"]: f["exceso"] for f in capas["Red principal · válvulas"].getFeatures()}
        self.assertAlmostEqual(min(excesos.values()), 0.0, places=2)
        self.assertIn("Punto de diseño de la bomba", dialogo.texto.toPlainText())


if __name__ == "__main__":
    unittest.main()
