"""Pruebas del motor de turnos de riego: colores, resumen por turno y balance."""

import unittest

from riegolibre.nucleo.turnos import (COLOR_SELECCION, PALETA, TURNO_MAXIMO, color_de_turno,
                                      resumen_turnos, siguiente_turno, texto_balance)


class PruebasColores(unittest.TestCase):
    def test_cada_turno_tiene_su_color_y_se_repiten_al_acabar_la_paleta(self):
        self.assertEqual(color_de_turno(1), PALETA[0])
        self.assertEqual(color_de_turno(2), PALETA[1])
        self.assertEqual(color_de_turno(len(PALETA) + 1), PALETA[0])
        self.assertNotEqual(color_de_turno(1), color_de_turno(2))

    def test_ningun_turno_usa_el_rojo_de_la_seleccion(self):
        self.assertNotIn(COLOR_SELECCION, PALETA)

    def test_turno_invalido_no_rompe(self):
        self.assertEqual(color_de_turno(0), PALETA[0])


class PruebasSiguienteTurno(unittest.TestCase):
    def test_sin_turnos_empieza_en_1(self):
        self.assertEqual(siguiente_turno([]), 1)

    def test_sigue_al_mayor_usado(self):
        self.assertEqual(siguiente_turno([1, 2, 3]), 4)
        self.assertEqual(siguiente_turno([1, 3]), 4)

    def test_no_pasa_del_maximo(self):
        self.assertEqual(siguiente_turno([TURNO_MAXIMO]), TURNO_MAXIMO)


class PruebasResumen(unittest.TestCase):
    VALVULAS = [("A", 36000.0, 1), ("B", 18000.0, 1), ("C", 54000.0, 2), ("D", 9000.0, None)]

    def test_suma_valvulas_y_caudal_por_turno(self):
        r = resumen_turnos(self.VALVULAS)
        self.assertEqual([(t.turno, t.valvulas, t.caudal_lh) for t in r.turnos],
                         [(1, 2, 54000.0), (2, 1, 54000.0)])
        self.assertAlmostEqual(r.turnos[0].caudal_ls, 15.0)

    def test_las_sin_turno_se_cuentan_aparte(self):
        r = resumen_turnos(self.VALVULAS)
        self.assertEqual(r.sin_asignar, 1)
        self.assertEqual(r.caudal_sin_asignar_lh, 9000.0)

    def test_desbalance_entre_el_mayor_y_el_menor(self):
        r = resumen_turnos([("A", 100.0, 1), ("B", 60.0, 2), ("C", 80.0, 3)])
        self.assertAlmostEqual(r.desbalance, 0.4)
        self.assertEqual(r.turno_mayor.turno, 1)

    def test_turnos_iguales_no_tienen_desbalance(self):
        self.assertEqual(resumen_turnos(self.VALVULAS).desbalance, 0.0)

    def test_con_un_solo_turno_no_hay_desbalance(self):
        r = resumen_turnos([("A", 100.0, 1), ("B", 50.0, 1)])
        self.assertIsNone(r.desbalance)

    def test_sin_valvulas(self):
        r = resumen_turnos([])
        self.assertEqual(r.turnos, [])
        self.assertIsNone(r.turno_mayor)
        self.assertIsNone(r.desbalance)

    def test_ordena_por_numero_de_turno(self):
        r = resumen_turnos([("A", 1.0, 3), ("B", 1.0, 1), ("C", 1.0, 2)])
        self.assertEqual([t.turno for t in r.turnos], [1, 2, 3])


class PruebasTextoBalance(unittest.TestCase):
    def test_sin_turnos(self):
        self.assertIn("Ningún turno", texto_balance(resumen_turnos([])))

    def test_nombra_el_turno_que_manda_y_el_desbalance(self):
        texto = texto_balance(resumen_turnos([("A", 36000.0, 1), ("B", 18000.0, 2)]))
        self.assertIn("turno 1", texto)
        self.assertIn("10.00 L/s", texto)
        self.assertIn("50 %", texto)

    def test_avisa_de_las_valvulas_sin_turno(self):
        texto = texto_balance(resumen_turnos([("A", 100.0, 1), ("B", 100.0, None), ("C", 100.0, None)]))
        self.assertIn("2 válvulas sin turno", texto)

    def test_un_solo_turno(self):
        self.assertEqual(texto_balance(resumen_turnos([("A", 100.0, 1)])), "Un solo turno.")


if __name__ == "__main__":
    unittest.main()
