import unittest

from riegolibre.nucleo import (Emisor, Lateral, PresionInsuficiente, Tuberia,
                               cargar_catalogo_emisores, cargar_catalogo_tuberias,
                               factor_christiansen, longitud_maxima,
                               uniformidad_emision_keller)
from riegolibre.nucleo.hidraulica import LH_A_M3S

PE16 = Tuberia("PE 16", 13.6)
NO_COMP = Emisor("2 L/h", 2.0, 10.0, exponente=0.5, cv=0.05)
COMP = Emisor("2 L/h PC", 2.0, 10.0, exponente=0.0, cv=0.03, autocompensado=True,
              presion_min_m=5.0, presion_max_m=40.0)


class PruebasEmisor(unittest.TestCase):
    def test_ecuacion(self):
        self.assertAlmostEqual(NO_COMP.k, 2.0 / 10 ** 0.5)
        self.assertAlmostEqual(NO_COMP.caudal(10.0), 2.0)
        self.assertAlmostEqual(NO_COMP.caudal(40.0), 4.0)
        self.assertAlmostEqual(NO_COMP.presion_para_caudal(2.0), 10.0)
        self.assertEqual(NO_COMP.caudal(-1), 0.0)

    def test_autocompensado(self):
        self.assertEqual(COMP.caudal(5.0), 2.0)
        self.assertEqual(COMP.caudal(35.0), 2.0)
        self.assertLess(COMP.caudal(3.0), 2.0)
        self.assertTrue(COMP.fuera_de_rango(4.0))
        self.assertTrue(COMP.fuera_de_rango(45.0))
        self.assertFalse(COMP.fuera_de_rango(20.0))

    def test_uniformidad_keller(self):
        self.assertAlmostEqual(uniformidad_emision_keller(0.95, 1.0, 0.05), 100 * (1 - 0.0635) * 0.95)


class PruebasLateral(unittest.TestCase):
    def test_balance_de_masa(self):
        lat = Lateral(PE16, NO_COMP, 0.3, 200)
        r = lat.simular(12.0)
        self.assertAlmostEqual(r.presion_entrada_m, 12.0, places=3)
        self.assertEqual(r.numero_emisores, 200)
        q_entrada = r.velocidad_entrada_ms * 3.14159265 * 0.0136 ** 2 / 4 / LH_A_M3S
        self.assertAlmostEqual(q_entrada, r.caudal_total_lh, delta=0.5)

    def test_compensado_vs_christiansen(self):
        # Con caudal constante por emisor y Hazen-Williams, la pérdida total debe
        # coincidir con hf(Q total, L) · F de Christiansen.
        n, s = 150, 0.5
        lat = Lateral(PE16, COMP, s, n, metodo="hazen")
        r = lat.simular(20.0)
        q_total = 2.0 * n * LH_A_M3S
        esperado = PE16.perdida(q_total, n * s, "hazen") * factor_christiansen(n, 1.852)
        self.assertAlmostEqual(r.perdida_friccion_m, esperado, delta=0.01 * esperado)
        self.assertAlmostEqual(r.presion_entrada_m - r.presiones_m[-1], esperado, delta=0.01 * esperado)

    def test_solo_desnivel(self):
        # Tubería enorme: casi sin fricción, las presiones siguen el desnivel.
        grande = Tuberia("grande", 500.0)
        lat = Lateral(grande, NO_COMP, 1.0, 50, pendiente=-0.02)  # en bajada
        r = lat.simular(10.0)
        for x, h in zip(r.posiciones_m, r.presiones_m):
            self.assertAlmostEqual(h, 10.0 + 0.02 * x, places=3)

    def test_perfil_equivale_a_pendiente(self):
        con_pendiente = Lateral(PE16, NO_COMP, 0.4, 100, pendiente=0.01).simular(12.0)
        con_perfil = Lateral(PE16, NO_COMP, 0.4, 100,
                             perfil=[(0, 250.0), (100, 251.0)]).simular(12.0)
        for a, b in zip(con_pendiente.presiones_m, con_perfil.presiones_m):
            self.assertAlmostEqual(a, b, places=4)

    def test_criterio_caudal_medio(self):
        r = Lateral(PE16, NO_COMP, 0.3, 250).presion_entrada_requerida()
        self.assertAlmostEqual(r.caudal_medio_lh, 2.0, places=3)
        self.assertGreater(r.presion_entrada_m, 10.0)

    def test_criterio_presion_minima(self):
        r = Lateral(PE16, COMP, 0.3, 250).presion_entrada_requerida()
        self.assertAlmostEqual(r.presion_min_m, 5.0, places=3)
        self.assertEqual(r.emisores_fuera_de_rango, 0)
        self.assertAlmostEqual(r.variacion_caudal, 0.0)

    def test_desde_longitud(self):
        lat = Lateral.desde_longitud(PE16, NO_COMP, 0.3, 100.0)
        self.assertEqual(lat.numero_emisores, 333)
        self.assertLessEqual(lat.longitud_m, 100.0)

    def test_presion_insuficiente(self):
        lat = Lateral(PE16, NO_COMP, 0.3, 100, pendiente=0.2)  # 6 m de subida en 30 m
        with self.assertRaises(PresionInsuficiente):
            lat.simular(5.0)

    def test_longitud_maxima(self):
        longitud, r = longitud_maxima(PE16, NO_COMP, 0.3, variacion_caudal_max=0.10)
        self.assertTrue(r.cumple(0.10))
        mas_largo = Lateral(PE16, NO_COMP, 0.3, r.numero_emisores + 1).presion_entrada_requerida()
        self.assertFalse(mas_largo.cumple(0.10))
        self.assertGreater(longitud, 30)
        self.assertLess(longitud, 150)

    def test_longitud_maxima_autocompensado_limitada_por_presion(self):
        longitud, r = longitud_maxima(PE16, COMP, 0.5, presion_entrada_max_m=15.0)
        self.assertLessEqual(r.presion_entrada_m, 15.0)
        self.assertEqual(r.emisores_fuera_de_rango, 0)


class PruebasCatalogos(unittest.TestCase):
    def test_cargan(self):
        self.assertTrue(cargar_catalogo_emisores())
        laterales = cargar_catalogo_tuberias(uso="lateral")
        self.assertTrue(laterales)
        self.assertTrue(all("lateral" in t.usos for t in laterales))
        self.assertTrue(cargar_catalogo_tuberias(uso="portalateral"))


if __name__ == "__main__":
    unittest.main()
