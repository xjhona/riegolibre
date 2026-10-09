import unittest

from riegolibre.nucleo import (ConexionLateral, Emisor, Lateral, Portalateral,
                               Tuberia, portalateral_uniforme)

PE16 = Tuberia("PE 16", 13.6)
PVC63 = Tuberia("PVC 63", 59.8, material="PVC", c_hazen=150)
NO_COMP = Emisor("2 L/h", 2.0, 10.0, exponente=0.5, cv=0.05)
COMP = Emisor("2 L/h PC", 2.0, 10.0, exponente=0.0, cv=0.03, autocompensado=True,
              presion_min_m=5.0, presion_max_m=40.0)


class PruebasPortalateral(unittest.TestCase):
    def test_un_lateral_equivale_al_lateral_solo(self):
        lat = Lateral(PE16, NO_COMP, 0.3, 200)
        porta = Portalateral(PVC63, [ConexionLateral(0.0, [lat])])
        r = porta.simular(12.0)
        solo = lat.simular(12.0)
        self.assertAlmostEqual(r.caudal_total_lh, solo.caudal_total_lh, delta=0.01)

    def test_balance_y_criterio_caudal_medio(self):
        lat = Lateral(PE16, NO_COMP, 0.3, 160)
        porta = portalateral_uniforme(PVC63, lat, lat, 1.5, 30)
        r = porta.presion_entrada_requerida()
        n = porta.numero_emisores
        self.assertEqual(n, 2 * 160 * 30)
        self.assertAlmostEqual(r.caudal_total_lh / n, 2.0, delta=0.01)
        self.assertAlmostEqual(sum(r.caudales_emisores_lh), r.caudal_total_lh, delta=1e-6)
        self.assertGreater(r.uniformidad_emision, 80)
        self.assertGreater(r.presion_entrada_m, r.presiones_m[-1])

    def test_curva_coherente_con_detalle(self):
        lat = Lateral(PE16, NO_COMP, 0.3, 160)
        porta = portalateral_uniforme(PVC63, lat, lat, 1.5, 30)
        aprox = porta.simular(15.0, detallado=False)
        exacto = porta.simular(15.0, detallado=True)
        self.assertAlmostEqual(aprox.caudal_total_lh / exacto.caudal_total_lh, 1.0, delta=0.002)

    def test_autocompensado_presion_minima(self):
        lat = Lateral(PE16, COMP, 0.5, 120)
        porta = portalateral_uniforme(PVC63, lat, lat, 1.5, 40, pendiente=0.01)
        r = porta.presion_entrada_requerida()
        self.assertAlmostEqual(min(r.presiones_emisores_m), 5.0, delta=0.02)
        self.assertEqual(r.emisores_fuera_de_rango, 0)
        self.assertAlmostEqual(r.caudal_total_lh, porta.numero_emisores * 2.0, delta=1.0)

    def test_laterales_distintos_por_lado(self):
        subida = Lateral(PE16, NO_COMP, 0.3, 150, pendiente=0.01)
        bajada = Lateral(PE16, NO_COMP, 0.3, 150, pendiente=-0.01)
        porta = portalateral_uniforme(PVC63, subida, bajada, 1.5, 20)
        r = porta.simular(14.0)
        sube, baja = r.laterales[0]
        self.assertLess(sube.caudal_total_lh, baja.caudal_total_lh)


if __name__ == "__main__":
    unittest.main()
