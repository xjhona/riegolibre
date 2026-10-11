"""Pruebas del mapa de costos del terreno (motor de Python puro)."""

import math
import unittest

from riegolibre.nucleo.terreno import INFINITO, Terreno, celda_automatica, celdas_de_segmento


def terreno(lado=100, paso=10):
    n = lado // paso
    return Terreno(0.0, 0.0, float(paso), n, n)


def celdas_con(t, valor):
    return {(k % t.nx, k // t.nx) for k, f in enumerate(t.factor) if f == valor}


class PruebasSegmentos(unittest.TestCase):
    def test_las_celdas_consecutivas_comparten_un_lado(self):
        for a, b in [((0.5, 0.5), (7.5, 3.2)), ((0.0, 0.0), (5.0, 5.0)), ((6.3, 1.1), (0.2, 4.9)),
                     ((2.5, 0.5), (2.5, 6.5)), ((0.5, 3.5), (8.5, 3.5)), ((1.0, 1.0), (4.0, 2.0))]:
            celdas = list(celdas_de_segmento(a, b))
            self.assertEqual(celdas[0], (math.floor(a[0]), math.floor(a[1])))
            self.assertEqual(celdas[-1], (math.floor(b[0]), math.floor(b[1])))
            for (i, j), (k, l) in zip(celdas, celdas[1:]):
                self.assertEqual(abs(i - k) + abs(j - l), 1, f"{a} → {b}: {celdas}")

    def test_una_diagonal_exacta_no_deja_pasos_en_diagonal(self):
        celdas = list(celdas_de_segmento((0.0, 0.0), (4.0, 4.0)))
        self.assertGreaterEqual(len(celdas), 5)
        self.assertEqual(celdas[-1], (4, 4))

    def test_segmento_dentro_de_una_celda(self):
        self.assertEqual(list(celdas_de_segmento((2.2, 3.1), (2.8, 3.9))), [(2, 3)])


class PruebasTerreno(unittest.TestCase):
    def test_poligono_marca_las_celdas_con_el_centro_dentro(self):
        t = terreno()
        t.penalizar_poligono([[(20, 20), (60, 20), (60, 50), (20, 50)]], 5.0)
        marcadas = celdas_con(t, 5.0)
        for i in range(2, 6):
            for j in range(2, 5):
                self.assertIn((i, j), marcadas)
        self.assertNotIn((7, 7), marcadas)
        self.assertNotIn((0, 0), marcadas)

    def test_los_anillos_interiores_son_huecos(self):
        t = terreno(200, 10)
        t.penalizar_poligono([[(20, 20), (180, 20), (180, 180), (20, 180)],
                              [(80, 80), (120, 80), (120, 120), (80, 120)]], 3.0)
        self.assertEqual(t.factor_en(100, 100), 1.0)  # el hueco
        self.assertEqual(t.factor_en(50, 50), 3.0)

    def test_una_zona_prohibida_vale_infinito(self):
        t = terreno()
        t.penalizar_poligono([[(20, 20), (60, 20), (60, 60), (20, 60)]], None)
        self.assertEqual(t.factor_en(40, 40), INFINITO)
        self.assertTrue(t.tiene_efecto)

    def test_el_factor_de_una_zona_no_puede_ser_menor_que_uno(self):
        with self.assertRaises(ValueError):
            terreno().penalizar_poligono([[(0, 0), (10, 0), (10, 10)]], 0.5)

    def test_zonas_que_se_traslapan_toman_el_mayor_factor(self):
        t = terreno()
        t.penalizar_poligono([[(20, 20), (60, 20), (60, 60), (20, 60)]], 4.0)
        t.penalizar_poligono([[(40, 40), (80, 40), (80, 80), (40, 80)]], 2.0)
        self.assertEqual(t.factor_en(50, 50), 4.0)
        self.assertEqual(t.factor_en(70, 70), 2.0)

    def test_un_camino_abarata_una_sola_vez_cada_celda(self):
        t = terreno()
        t.descontar_linea([(5, 55), (95, 55), (5, 55)], 0.5)  # ida y vuelta por las mismas celdas
        self.assertEqual(t.factor_en(50, 55), 0.5)
        self.assertEqual(t.factor_en(50, 25), 1.0)

    def test_el_camino_dentro_de_una_zona_prohibida_sigue_prohibido(self):
        t = terreno()
        t.penalizar_poligono([[(20, 20), (60, 20), (60, 60), (20, 60)]], None)
        t.descontar_linea([(10, 40), (90, 40)], 0.5)
        self.assertEqual(t.factor_en(40, 40), INFINITO)
        self.assertEqual(t.factor_en(80, 40), 0.5)

    def test_barrera_cuesta_lo_que_se_pide_por_cruzarla(self):
        t = terreno()
        t.barrera_linea([(55, 0), (55, 100)], 30.0)
        self.assertAlmostEqual(t.factor_en(55, 50), 1 + 30.0 / 10)
        t.barrera_linea([(25, 0), (25, 100)], None)
        self.assertEqual(t.factor_en(25, 50), INFINITO)

    def test_una_barrera_en_diagonal_no_se_puede_cruzar_por_la_esquina(self):
        t = terreno()
        t.barrera_linea([(0, 0), (100, 100)], None)
        bloqueadas = celdas_con(t, INFINITO)
        for i in range(9):
            # la línea es una escalera de celdas unidas por un lado: no deja huecos por los que
            # pase un paso en diagonal
            self.assertIn((i, i), bloqueadas)
            self.assertTrue((i + 1, i) in bloqueadas or (i, i + 1) in bloqueadas)

    def test_cotas(self):
        t = terreno()
        self.assertTrue(math.isnan(t.cota_en(5, 5)))
        t.cargar_cotas(lambda x, y: x + 2 * y)
        self.assertAlmostEqual(t.cota_en(25, 35), 25 + 70)
        t.cargar_cotas(lambda x, y: None)
        self.assertTrue(math.isnan(t.cota_en(25, 35)))
        with self.assertRaises(ValueError):
            t.poner_cotas([1.0, 2.0])

    def test_fuera_de_la_cuadricula_no_hay_efecto(self):
        t = terreno()
        t.penalizar_poligono([[(0, 0), (100, 0), (100, 100), (0, 100)]], 9.0)
        self.assertEqual(t.factor_en(500, 500), 1.0)
        self.assertTrue(math.isnan(t.cota_en(500, 500)))

    def test_sin_restricciones_no_tiene_efecto(self):
        self.assertFalse(terreno().tiene_efecto)

    def test_medir_metros_en_zonas_y_en_caminos(self):
        t = terreno(200, 10)
        t.penalizar_poligono([[(50, 0), (100, 0), (100, 200), (50, 200)]], 2.0)
        t.descontar_linea([(0, 15), (200, 15)], 0.5)
        mas, menos = t.medir([(0, 105), (200, 105)])
        self.assertAlmostEqual(mas, 50, delta=20)  # las celdas del borde cuentan como parte de la zona
        self.assertEqual(menos, 0)
        mas, menos = t.medir([(0, 15), (200, 15)])
        self.assertGreater(menos, 100)

    def test_celda_automatica_y_cobertura(self):
        puntos = [(0, 0), (500, 300), (200, -100)]
        paso = celda_automatica(puntos)
        self.assertAlmostEqual(paso, 5.0)
        t = Terreno.cubriendo(puntos, paso)
        for x, y in puntos:
            self.assertIsNotNone(t.celda_de(x, y))
        self.assertGreater(t.nx * paso, 1000)
        self.assertEqual(celda_automatica([(0, 0), (10, 5)]), 1.0)  # no baja de la mínima


if __name__ == "__main__":
    unittest.main()
