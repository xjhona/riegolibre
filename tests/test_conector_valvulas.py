# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas del conector de válvulas: el cálculo geométrico (Python puro) y su dibujo en el mapa (QGIS)."""

import unittest
from math import sqrt
from unittest import mock

from riegolibre.nucleo.conector_valvulas import conectar_valvulas, punto_mas_cercano
from tests.test_integracion_qgis import HAY_QGIS, X0, Y0

if HAY_QGIS:
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsProject
    from qgis.PyQt.QtWidgets import QDialog

PRINCIPAL = [(0, 0), (100, 0)]
LATERAL_QUEBRADA = [(0, 50), (0, 100), (100, 100)]


class PruebasConectorNucleo(unittest.TestCase):
    def test_punto_mas_cercano_cae_en_el_lado_o_en_el_vertice(self):
        distancia, punto = punto_mas_cercano(PRINCIPAL, (30, 8))
        self.assertAlmostEqual(distancia, 8.0)
        self.assertEqual(punto, (30.0, 0.0))
        distancia, punto = punto_mas_cercano(PRINCIPAL, (-3, 4))  # más allá del extremo: el extremo
        self.assertAlmostEqual(distancia, 5.0)
        self.assertEqual(punto, (0.0, 0.0))
        distancia, _ = punto_mas_cercano([(0, 0), (4, 3)], (4, 0))  # lado inclinado: 12/5
        self.assertAlmostEqual(distancia, 2.4)

    def test_polilinea_degenerada(self):
        with self.assertRaises(ValueError):
            punto_mas_cercano([(0, 0)], (1, 1))

    def test_une_con_el_punto_mas_cercano_de_la_tubería_mas_cercana(self):
        lineas = [("a", PRINCIPAL), ("b", LATERAL_QUEBRADA)]
        resultado = conectar_valvulas(lineas, [("V1", (40, 12)), ("V2", (60, 80))], 100)
        self.assertEqual([c.valvula for c in resultado.conectores], ["V1", "V2"])
        primero, segundo = resultado.conectores
        self.assertEqual((primero.linea, primero.hasta), ("a", (40.0, 0.0)))
        self.assertAlmostEqual(primero.largo_m, 12.0)
        self.assertEqual((segundo.linea, segundo.hasta), ("b", (60.0, 100.0)))
        self.assertAlmostEqual(segundo.largo_m, 20.0)
        self.assertEqual(primero.desde, (40, 12))

    def test_respeta_la_longitud_maxima(self):
        resultado = conectar_valvulas([("a", PRINCIPAL)], [("cerca", (50, 10)), ("lejos", (50, 10.5))], 10)
        self.assertEqual([c.valvula for c in resultado.conectores], ["cerca"])  # justo en el límite se conecta
        self.assertEqual(resultado.fuera_de_alcance, [("lejos", 10.5)])

    def test_la_valvula_sobre_la_matriz_ya_esta_conectada(self):
        resultado = conectar_valvulas([("a", PRINCIPAL)], [("V", (50, 0.3)), ("W", (100, 0))], 100, 0.5)
        self.assertEqual(resultado.ya_conectadas, ["V", "W"])
        self.assertEqual(resultado.conectores, [])

    def test_sin_tuberias_nada_se_conecta(self):
        resultado = conectar_valvulas([], [("V", (1, 1))], 100)
        self.assertEqual(resultado.conectores, [])
        self.assertEqual(resultado.fuera_de_alcance[0][0], "V")
        self.assertEqual(resultado.fuera_de_alcance[0][1], float("inf"))

    def test_largo_diagonal(self):
        resultado = conectar_valvulas([("a", [(0, 0), (10, 10)])], [("V", (10, 0))], 100)
        self.assertAlmostEqual(resultado.conectores[0].largo_m, 10 / sqrt(2))
        self.assertAlmostEqual(resultado.conectores[0].hasta[0], 5.0)


def _p(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasConectorMapa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_integracion_qgis import _iniciar_qgis
        cls.app = _iniciar_qgis()

    def setUp(self):
        from riegolibre.integracion.red_mapa import crear_capas_de_matriz
        self.proyecto = QgsProject.instance()
        crs_anterior = self.proyecto.crs()
        self.proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
        self.addCleanup(self.proyecto.setCrs, crs_anterior)
        antes = set(self.proyecto.mapLayers())
        self.matriz, self.nodos, _ruta = crear_capas_de_matriz(self.proyecto)
        self.addCleanup(lambda: [self.proyecto.removeMapLayer(i) for i in set(self.proyecto.mapLayers()) - antes])

    def _catalogo(self):
        from riegolibre.nucleo import cargar_catalogo_tuberias
        return cargar_catalogo_tuberias(uso="principal")

    def _valvulas(self, *datos):
        from riegolibre.integracion.red_mapa import ValvulaMapa
        return [ValvulaMapa(nombre, _p(x, y), 20000.0, 12.0) for nombre, x, y in datos]

    def test_dibuja_el_tramo_con_el_diametro_de_la_tuberia_cercana_y_sus_nodos(self):
        from riegolibre.integracion.red_mapa import (CAMPO_TUBERIA, agregar_tuberia,
                                                     conectar_valvulas_a_la_matriz)
        tubo = self._catalogo()[-1]
        agregar_tuberia(self.matriz, [_p(*p) for p in PRINCIPAL], tubo)
        resultado = conectar_valvulas_a_la_matriz(self.matriz, self.nodos,
                                                  self._valvulas(("A", 30, 20), ("B", 70, 0.2), ("C", 50, 400)))
        self.assertEqual([c.valvula for c in resultado.conectores], ["A"])
        self.assertEqual(resultado.ya_conectadas, ["B"])
        self.assertEqual([n for n, _ in resultado.fuera_de_alcance], ["C"])
        tramos = {round(e.geometry().length(), 6): e for e in self.matriz.getFeatures()}
        self.assertEqual(sorted(tramos), [20.0, 100.0])
        self.assertEqual(tramos[20.0][CAMPO_TUBERIA], tubo.nombre)
        extremos = {(round(p.x() - X0, 6), round(p.y() - Y0, 6))
                    for e in self.nodos.getFeatures() for p in [e.geometry().asPoint()]}
        self.assertEqual(extremos, {(30.0, 20.0), (30.0, 0.0)})

    def test_repetir_no_duplica_y_el_tramo_nuevo_no_atrae_a_otra_valvula(self):
        from riegolibre.integracion.red_mapa import agregar_tuberia, conectar_valvulas_a_la_matriz
        agregar_tuberia(self.matriz, [_p(*p) for p in PRINCIPAL])
        valvulas = self._valvulas(("A", 30, 20), ("B", 33, 25))
        conectar_valvulas_a_la_matriz(self.matriz, self.nodos, valvulas)
        self.assertEqual(self.matriz.featureCount(), 3)
        largos = sorted(round(e.geometry().length(), 3) for e in self.matriz.getFeatures())
        self.assertEqual(largos, [20.0, 25.0, 100.0])  # B va a la principal, no al tramo de A
        repetido = conectar_valvulas_a_la_matriz(self.matriz, self.nodos, valvulas)
        self.assertEqual((repetido.conectores, len(repetido.ya_conectadas)), ([], 2))
        self.assertEqual(self.matriz.featureCount(), 3)

    def test_sin_igualar_usa_la_tuberia_elegida_o_la_deja_por_dimensionar(self):
        from riegolibre.integracion.red_mapa import (CAMPO_TUBERIA, agregar_tuberia,
                                                     conectar_valvulas_a_la_matriz)
        catalogo = self._catalogo()
        agregar_tuberia(self.matriz, [_p(*p) for p in PRINCIPAL], catalogo[-1])
        conectar_valvulas_a_la_matriz(self.matriz, None, self._valvulas(("A", 30, 20)), igualar=False,
                                      tuberia=catalogo[0])
        conectar_valvulas_a_la_matriz(self.matriz, None, self._valvulas(("B", 80, -15)), igualar=False)
        por_largo = {round(e.geometry().length()): e[CAMPO_TUBERIA] for e in self.matriz.getFeatures()}
        self.assertEqual(por_largo[20], catalogo[0].nombre)
        self.assertFalse(por_largo[15])  # sin diámetro: lo elige el cálculo

    def test_el_tramo_conecta_la_red_para_el_calculo(self):
        from riegolibre.integracion.red_mapa import agregar_tuberia, conectar_valvulas_a_la_matriz, construir_red
        agregar_tuberia(self.matriz, [_p(*p) for p in PRINCIPAL])
        valvulas = self._valvulas(("A", 30, 20), ("B", 80, -15))
        with self.assertRaisesRegex(ValueError, "Conectar válvulas a la matriz"):
            construir_red(self.matriz, _p(0, 0), valvulas, self.matriz.crs())
        conectar_valvulas_a_la_matriz(self.matriz, self.nodos, valvulas)
        red = construir_red(self.matriz, _p(0, 0), valvulas, self.matriz.crs()).red
        self.assertEqual(sorted(v.id for v in red.valvulas), ["A", "B"])
        self.assertAlmostEqual(sum(t.longitud_m for t in red.tramos), 100 + 20 + 15)

    def test_boton_de_la_ventana_de_la_red(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        from riegolibre.integracion.red_mapa import agregar_tuberia
        from tests.test_red_qgis import _capa_punto
        iface = mock.Mock()
        dialogo = DialogoRed(iface=iface)
        with mock.patch("riegolibre.gui.dialogo_red.QMessageBox.information") as aviso:
            dialogo.conectar_valvulas()  # todavía no hay matriz
        self.assertIn("Todavía no hay tubería matriz", aviso.call_args[0][2])
        agregar_tuberia(self.matriz, [_p(*p) for p in PRINCIPAL])
        with mock.patch("riegolibre.gui.dialogo_red.QMessageBox.information") as aviso:
            dialogo.conectar_valvulas()  # hay matriz pero no válvulas
        self.assertIn("No se encontraron válvulas", aviso.call_args[0][2])
        capas = [_capa_punto((30, 20), "Válvula · A", "&field=presion:double&field=caudal_lh:double", (12.0, 20000.0)),
                 _capa_punto((70, 500), "Válvula · B", "&field=presion:double&field=caudal_lh:double", (12.0, 9000.0))]
        self.proyecto.addMapLayers(capas)
        self.addCleanup(lambda: [self.proyecto.removeMapLayer(c.id()) for c in capas])
        with mock.patch("riegolibre.gui.dialogo_conector_valvulas.DialogoConectorValvulas.exec",
                        return_value=QDialog.DialogCode.Accepted):
            dialogo.conectar_valvulas()
        self.assertEqual(self.matriz.featureCount(), 2)
        texto = dialogo.texto.toPlainText()
        self.assertIn("Se dibujaron 1 tramo", texto)
        self.assertIn("Sin conectar", texto)
        self.assertIn("B: a 500.0 m", texto)

    def test_cuadro_de_propiedades(self):
        from riegolibre.gui.dialogo_conector_valvulas import DialogoConectorValvulas
        catalogo = self._catalogo()
        dialogo = DialogoConectorValvulas(catalogo)
        self.assertTrue(dialogo.igualar())
        self.assertEqual(dialogo.largo_max_m(), 100.0)
        self.assertTrue(dialogo.grupo_tuberia.isHidden() or not dialogo.grupo_tuberia.isEnabled())
        dialogo.check_igualar.setChecked(False)
        self.assertTrue(dialogo.grupo_tuberia.isEnabled())
        self.assertIsNone(dialogo.tuberia())  # «Elegida por el programa»
        dialogo = DialogoConectorValvulas(catalogo, elegida=catalogo[1])
        self.assertEqual(dialogo.tuberia().nombre, catalogo[1].nombre)


if __name__ == "__main__":
    unittest.main()
