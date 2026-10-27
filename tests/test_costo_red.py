"""Pruebas del costo por metro de la red automática ajustado a la lista de precios (Python puro)."""

import unittest

from riegolibre.nucleo.costo_red import ajustar_costo_a_precios, ajustar_costo_de_valvulas
from riegolibre.nucleo.trazado_red import ParametrosRed, ValvulaDestino, trazar_red
from riegolibre.nucleo.tuberias import Tuberia

# Diámetro interior (mm) y precio por metro de una serie de PVC.
SERIE = [(57, 3.0), (69, 4.2), (84, 6.0), (103, 9.0), (150, 18.0), (190, 28.0)]
TUBERIAS = [Tuberia(f"PVC {d}", d, "PVC", ["principal"], d) for d, _ in SERIE]
PRECIOS = {f"PVC {d}": p for d, p in SERIE}


class PruebasCostoRed(unittest.TestCase):
    def test_la_curva_sube_con_el_caudal(self):
        a = ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, PRECIOS, 1.5)
        self.assertTrue(0 < a.exponente < 1)
        self.assertGreaterEqual(a.costo_fijo, 0)
        self.assertLess(a.precio_m(20_000), a.precio_m(100_000))
        self.assertLess(a.precio_m(100_000), a.precio_m(200_000))
        self.assertLess(a.error_relativo, 0.25)
        # El ajuste reproduce el orden de magnitud de los precios reales en los extremos.
        self.assertAlmostEqual(a.precio_m(200_000) / PRECIOS["PVC 190"], 1.0, delta=0.35)

    def test_elige_la_tuberia_mas_barata_que_cumple_la_velocidad(self):
        a = ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, PRECIOS, 1.5)
        # 200 m³/h a 1.5 m/s necesita 217 mm interior como mínimo: ninguna sirve, queda la mayor.
        self.assertEqual(a.muestras[-1][1], "PVC 190")
        # 20 m³/h a 1.5 m/s necesita 69 mm interior.
        self.assertEqual(a.muestras[0][1], "PVC 69")
        con_mas_velocidad = ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, PRECIOS, 3.0)
        self.assertEqual(con_mas_velocidad.muestras[0][1], "PVC 57")

    def test_la_zanja_sube_el_costo_fijo(self):
        sin = ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, PRECIOS, 1.5, zanja_m=0.0)
        con = ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, PRECIOS, 1.5, zanja_m=10.0)
        self.assertGreater(con.costo_fijo, sin.costo_fijo)
        self.assertGreaterEqual(con.precio_fijo, 10.0)

    def test_precios_proporcionales_dan_costo_fijo_pequeno(self):
        # Una tubería que cuesta justo lo que su caudal: la curva casi no tiene parte fija.
        tuberias = [Tuberia(f"T{k}", 50 + 20 * k, "PVC", ["principal"], 50 + 20 * k) for k in range(8)]
        precios = {t.nombre: (t.diametro_interior_mm / 100) ** 2 * 10 for t in tuberias}
        a = ajustar_costo_a_precios(150_000, 15_000, tuberias, precios, 1.5)
        self.assertLess(a.costo_fijo, 0.5)

    def test_sin_precios_suficientes(self):
        with self.assertRaises(ValueError):
            ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, {"PVC 57": 3.0}, 1.5)
        with self.assertRaises(ValueError):
            ajustar_costo_a_precios(200_000, 20_000, TUBERIAS, {t.nombre: 5.0 for t in TUBERIAS}, 1.5)
        with self.assertRaises(ValueError):
            ajustar_costo_a_precios(0, 0, TUBERIAS, PRECIOS, 1.5)

    def test_con_las_valvulas_y_los_turnos(self):
        valvulas = [ValvulaDestino("A", 100, 0, 30_000, 1), ValvulaDestino("B", 0, 100, 30_000, 1),
                    ValvulaDestino("C", 100, 100, 30_000, 2)]
        a = ajustar_costo_de_valvulas(valvulas, TUBERIAS, PRECIOS, 1.5)
        self.assertEqual(a.caudal_ref_lh, 60_000)  # el mayor turno
        self.assertAlmostEqual(a.muestras[0][0], 30_000, delta=1)

    def test_el_trazado_usa_los_parametros_ajustados(self):
        valvulas = [ValvulaDestino("A", 300, 0, 30_000), ValvulaDestino("B", 300, 20, 30_000)]
        a = ajustar_costo_de_valvulas(valvulas, TUBERIAS, PRECIOS, 1.5)
        red = trazar_red((0, 0), valvulas, ParametrosRed(costo_fijo=a.costo_fijo, exponente=a.exponente))
        self.assertEqual({t.hasta for t in red.tramos} - {"A", "B"}, set(red.uniones))
        self.assertGreater(red.costo, 0)


if __name__ == "__main__":
    unittest.main()
