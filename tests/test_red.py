import unittest

from riegolibre.nucleo import (CriteriosRed, DatosBomba, Red, TramoRed, Tuberia, Valvula,
                               cargar_catalogo_tuberias, dimensionar_red, punto_bomba)
from riegolibre.nucleo.hidraulica import LH_A_M3S

PVC110 = Tuberia("PVC 110", 104.6, material="PVC", c_hazen=150, presion_nominal_m=50)
SIN_MENORES = CriteriosRed(factor_perdidas_menores=0.0, presion_min_m=0.0)


def red_en_y(turno_v2=2, cota_v2=102.0):
    """Fuente F → nodo A → válvulas V1 y V2 (en Y)."""
    cotas = {"F": 100.0, "A": 101.0, "V1": 105.0, "V2": cota_v2}
    tramos = [TramoRed("FA", "F", "A", 200.0), TramoRed("AV1", "A", "V1", 100.0),
              TramoRed("AV2", "A", "V2", 150.0)]
    valvulas = [Valvula("v1", "V1", 36000.0, 15.0, turno=1, perdida_m=2.0),
                Valvula("v2", "V2", 18000.0, 12.0, turno=turno_v2, perdida_m=2.0)]
    return Red(cotas, tramos, valvulas, "F")


def todas(tuberia, red):
    return {t.id: tuberia for t in red.tramos}


class PruebasRed(unittest.TestCase):
    def test_linea_simple(self):
        red = Red({"F": 100.0, "V": 105.0}, [TramoRed("FV", "F", "V", 300.0)],
                  [Valvula("v", "V", 36000.0, 15.0, perdida_m=2.0)], "F")
        criterios = CriteriosRed(factor_perdidas_menores=0.10, presion_min_m=0.0)
        r = red.calcular_turno(todas(PVC110, red), 1, criterios)
        hf = PVC110.perdida(36000 * LH_A_M3S, 300.0) * 1.10
        self.assertAlmostEqual(r.carga_fuente_m, 105 + 15 + 2 + hf, places=9)
        self.assertAlmostEqual(r.presion_entrada_red_m, 22 + hf, places=9)
        self.assertEqual(r.critico, "válvula v")
        self.assertAlmostEqual(r.presion_disponible["v"], 15.0, places=9)
        self.assertAlmostEqual(r.tramos["FV"].perdida_unitaria_m100, hf / 3, places=9)

    def test_caudales_por_turno(self):
        red = red_en_y()
        self.assertEqual(red.turnos, [1, 2])
        self.assertEqual(red.caudales(1), {"FA": 36000.0, "AV1": 36000.0, "AV2": 0.0})
        self.assertEqual(red.caudales(2), {"FA": 18000.0, "AV1": 0.0, "AV2": 18000.0})
        self.assertEqual(red.caudales_maximos(), {"FA": 36000.0, "AV1": 36000.0, "AV2": 18000.0})

    def test_mismo_turno_la_valvula_critica_manda(self):
        red = red_en_y(turno_v2=1)
        r = red.calcular_turno(todas(PVC110, red), 1, SIN_MENORES)
        self.assertEqual(r.caudal_total_lh, 54000.0)
        self.assertEqual(r.tramos["FA"].caudal_lh, 54000.0)
        self.assertEqual(r.critico, "válvula v1")  # más alta y con más presión requerida
        v1, v2 = red.valvulas
        self.assertAlmostEqual(r.exceso(v1), 0.0, places=9)
        self.assertGreater(r.exceso(v2), 0.0)

    def test_tramos_dibujados_al_reves(self):
        normal = red_en_y()
        cotas = {"F": 100.0, "A": 101.0, "V1": 105.0, "V2": 102.0}
        al_reves = Red(cotas, [TramoRed("FA", "A", "F", 200.0), TramoRed("AV1", "V1", "A", 100.0),
                               TramoRed("AV2", "A", "V2", 150.0)], normal.valvulas, "F")
        for turno in (1, 2):
            a = normal.calcular_turno(todas(PVC110, normal), turno, SIN_MENORES)
            b = al_reves.calcular_turno(todas(PVC110, al_reves), turno, SIN_MENORES)
            self.assertAlmostEqual(a.carga_fuente_m, b.carga_fuente_m, places=9)

    def test_perfil_se_invierte_con_el_tramo(self):
        tramo = TramoRed("t", "A", "B", 100.0, perfil=[(10.0, 1.0), (40.0, 4.0)])
        self.assertEqual(tramo.invertido().perfil, [(60.0, 4.0), (90.0, 1.0)])

    def test_punto_alto_fija_la_carga(self):
        # Una loma de 140 m en medio del tramo exige más carga que la válvula.
        red = Red({"F": 100.0, "V": 105.0},
                  [TramoRed("FV", "F", "V", 300.0, perfil=[(150.0, 140.0)])],
                  [Valvula("v", "V", 36000.0, 15.0)], "F")
        criterios = CriteriosRed(factor_perdidas_menores=0.0, presion_min_m=2.0)
        r = red.calcular_turno(todas(PVC110, red), 1, criterios)
        self.assertEqual(r.critico, "punto alto del tramo FV")
        self.assertAlmostEqual(r.tramos["FV"].presion_min_m, 2.0, places=9)
        self.assertGreater(r.exceso(red.valvulas[0]), 0)

    def test_circuito_cerrado(self):
        with self.assertRaisesRegex(ValueError, "circuito cerrado"):
            Red({"F": 0, "A": 0, "B": 0},
                [TramoRed("1", "F", "A", 10), TramoRed("2", "A", "B", 10), TramoRed("3", "B", "F", 10)],
                [Valvula("v", "B", 1000, 10)], "F")

    def test_valvula_sin_conexion(self):
        with self.assertRaisesRegex(ValueError, "no están conectadas"):
            Red({"F": 0, "A": 0, "B": 0}, [TramoRed("1", "F", "A", 10)],
                [Valvula("v", "B", 1000, 10)], "F")

    def test_tramo_suelto_genera_aviso(self):
        red = Red({"F": 0, "A": 0, "X": 0, "Y": 0},
                  [TramoRed("1", "F", "A", 10), TramoRed("2", "X", "Y", 10)],
                  [Valvula("v", "A", 1000, 10)], "F")
        self.assertIn("no están conectados", red.avisos[0])


class PruebasDimensionamiento(unittest.TestCase):
    def setUp(self):
        self.catalogo = cargar_catalogo_tuberias(uso="principal")

    def test_diametro_por_velocidad(self):
        red = red_en_y()
        criterios = CriteriosRed(velocidad_max_ms=1.5)
        resultado = dimensionar_red(red, self.catalogo, criterios)
        self.assertEqual(resultado.motivos, {})
        for t in red.tramos:
            elegida = resultado.asignacion[t.id]
            q = red.caudales_maximos()[t.id] * LH_A_M3S
            self.assertLessEqual(elegida.velocidad(q), 1.5)
            # Ningún diámetro nominal menor cumple la velocidad.
            menores = [c for c in self.catalogo if c.diametro_nominal_mm < elegida.diametro_nominal_mm]
            self.assertTrue(all(c.velocidad(q) > 1.5 for c in menores))
            self.assertEqual(elegida.presion_nominal_m, 50)  # basta la clase más baja

    def test_clase_por_presion_en_bajada(self):
        # La válvula está 70 m más abajo que la fuente: el tramo final soporta mucha presión.
        cotas = {"F": 200.0, "A": 160.0, "V": 130.0}
        red = Red(cotas, [TramoRed("FA", "F", "A", 400.0), TramoRed("AV", "A", "V", 400.0)],
                  [Valvula("v", "V", 30000.0, 15.0)], "F")
        # Se exige además una presión de entrada alta (p. ej. otra válvula en otro turno).
        red.valvulas.append(Valvula("alta", "F", 1000.0, 20.0, turno=2))
        resultado = dimensionar_red(red, self.catalogo, CriteriosRed())
        self.assertEqual(resultado.motivos, {})
        for t in red.tramos:
            _, _, p_max = resultado.peor_tramo(t.id)
            self.assertGreaterEqual(resultado.asignacion[t.id].presion_nominal_m, p_max)
        self.assertGreater(resultado.asignacion["AV"].presion_nominal_m, 50)

    def test_tramo_sin_caudal(self):
        red = red_en_y()
        cotas = dict(red.cotas, X=101.0)
        red = Red(cotas, [TramoRed(t.id, t.desde, t.hasta, t.longitud_m) for t in red.tramos]
                  + [TramoRed("AX", "A", "X", 50.0)], red.valvulas, "F")
        resultado = dimensionar_red(red, self.catalogo)
        self.assertEqual(resultado.sin_caudal, ["AX"])
        self.assertEqual(resultado.observaciones("AX"), "sin caudal en ningún turno")
        self.assertIn("AX", resultado.avisos[-1])

    def test_tuberia_fija_se_respeta(self):
        red = red_en_y()
        red.tramos[0].tuberia = PVC110
        resultado = dimensionar_red(red, self.catalogo)
        self.assertIs(resultado.asignacion["FA"], PVC110)

    def test_sin_tuberia_suficiente(self):
        pequena = [Tuberia("PVC 63", 59.8, presion_nominal_m=50)]
        resultado = dimensionar_red(red_en_y(), pequena, CriteriosRed(velocidad_max_ms=1.5))
        self.assertIn("velocidad", resultado.motivos["FA"][0])

    def test_turno_critico_y_bomba(self):
        resultado = dimensionar_red(red_en_y(), self.catalogo)
        critico = resultado.turno_critico
        self.assertEqual(critico.turno, max(resultado.turnos, key=lambda r: r.presion_entrada_red_m).turno)
        datos = DatosBomba(perdidas_cabezal_m=7.0, altura_succion_m=3.0, eficiencia=0.7)
        bomba = punto_bomba(critico, datos)
        self.assertAlmostEqual(bomba.carga_dinamica_total_m, critico.presion_entrada_red_m + 10.0)
        esperado = 9.81 * critico.caudal_total_lh / 3.6e6 * bomba.carga_dinamica_total_m / 0.7
        self.assertAlmostEqual(bomba.potencia_kw, esperado)
        self.assertAlmostEqual(bomba.potencia_hp, esperado / 0.7457)


if __name__ == "__main__":
    unittest.main()
