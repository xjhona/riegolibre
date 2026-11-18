# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Aspersión: aspersor y elevador, marco de riego y lateral de aspersores contra valores teóricos."""

import math
import unittest

from riegolibre.nucleo.aspersion import (DISPOSICION_TRIANGULAR, Aspersor, Elevador, LateralAspersion, Marco,
                                         Riego, SalidaAspersor, caudal_orificio_m3h, cargar_catalogo_aspersores,
                                         numero_maximo_aspersores)
from riegolibre.nucleo.hidraulica import G, factor_christiansen, perdida_darcy, perdida_hazen_williams
from riegolibre.nucleo.tuberias import Tuberia

ASPERSOR = Aspersor("Prueba", caudal_nominal_m3h=1.2, presion_nominal_m=30.0, diametro_mojado_m=26.0,
                    presion_min_m=20.0, presion_max_m=40.0)
PE40 = Tuberia("PE 40", 35.6, usos=["portalateral"], c_hazen=150.0)
MARCO = Marco(12.0, 12.0)


class TestAspersor(unittest.TestCase):
    def test_ecuacion_del_aspersor(self):
        self.assertAlmostEqual(ASPERSOR.caudal_m3h(30.0), 1.2)
        self.assertAlmostEqual(ASPERSOR.caudal_m3h(120.0), 2.4)  # b = 0.5: 4 veces la presión, el doble de caudal
        self.assertAlmostEqual(ASPERSOR.presion_para_caudal(0.6), 7.5)
        self.assertEqual(ASPERSOR.caudal_m3h(0), 0.0)
        self.assertTrue(ASPERSOR.fuera_de_rango(15.0))
        self.assertFalse(ASPERSOR.fuera_de_rango(30.0))

    def test_caudal_de_orificio(self):
        # q = 0.95 · π·0.004²/4 · √(2·9.81·30) = 2.897e-4 m³/s = 1.043 m³/h
        esperado = 0.95 * math.pi * 0.004 ** 2 / 4 * math.sqrt(2 * G * 30) * 3600
        self.assertAlmostEqual(caudal_orificio_m3h(4.0, 30.0), esperado)
        self.assertAlmostEqual(esperado, 1.0428, places=3)

    def test_elevador_sin_friccion_resta_su_altura(self):
        salida = SalidaAspersor(ASPERSOR, Elevador(altura_m=1.0))
        self.assertAlmostEqual(salida.presion_boquilla(31.0), 30.0)
        self.assertAlmostEqual(salida.caudal(31.0), 1200.0)  # L/h
        self.assertAlmostEqual(salida.presion_nominal_m, 31.0)
        self.assertEqual(salida.caudal(0.8), 0.0)  # la presión no alcanza a subir el agua

    def test_perdida_del_elevador(self):
        elevador = Elevador(altura_m=1.0, diametro_interior_mm=20.9)  # 3/4" galvanizado
        q = 1.2 / 3600
        v = q / (math.pi * 0.0209 ** 2 / 4)
        esperado = perdida_darcy(q, 0.0209, 1.0, 0.00015) + 1.0 * v * v / (2 * G)
        self.assertAlmostEqual(elevador.perdida(1.2), esperado)
        salida = SalidaAspersor(ASPERSOR, elevador)
        # Presión en el lateral para 30 m en la boquilla, y vuelta a la boquilla
        h_lateral = 30.0 + 1.0 + esperado
        self.assertAlmostEqual(salida.presion_nominal_m, h_lateral)
        self.assertAlmostEqual(salida.presion_boquilla(h_lateral), 30.0, places=4)
        self.assertAlmostEqual(salida.caudal(h_lateral), 1200.0, places=1)


class TestMarco(unittest.TestCase):
    def test_pluviometria(self):
        # 1.2 m³/h en 12 × 12 m = 1200 L/h / 144 m² = 8.33 mm/h
        self.assertAlmostEqual(MARCO.intensidad_mm_h(1.2), 1200 / 144)
        self.assertAlmostEqual(Marco(12, 18, DISPOSICION_TRIANGULAR).intensidad_mm_h(1.2), 1200 / 216)
        self.assertAlmostEqual(MARCO.aspersores_por_ha(), 10000 / 144)

    def test_solape_segun_viento(self):
        self.assertAlmostEqual(MARCO.separacion_maxima_m(26.0, 1.0), 0.60 * 26)
        self.assertAlmostEqual(MARCO.separacion_maxima_m(26.0, 3.0), 0.50 * 26)
        self.assertAlmostEqual(MARCO.separacion_maxima_m(26.0, 5.0), 0.40 * 26)
        self.assertTrue(MARCO.solape_suficiente(26.0, 3.0))  # 12 ≤ 13
        self.assertFalse(Marco(12, 18).solape_suficiente(26.0, 3.0))  # 18 > 13
        self.assertAlmostEqual(Marco(12, 12, DISPOSICION_TRIANGULAR).separacion_maxima_m(26.0, 1.0), 0.65 * 26)

    def test_tiempo_de_riego(self):
        riego = Riego(lamina_neta_mm=30.0, eficiencia=0.75, infiltracion_basica_mm_h=10.0)
        self.assertAlmostEqual(riego.lamina_bruta_mm, 40.0)
        self.assertAlmostEqual(riego.tiempo_riego_h(8.0), 5.0)

    def test_espaciamiento_invalido(self):
        with self.assertRaises(ValueError):
            Marco(0, 12)


class TestLateralAspersion(unittest.TestCase):
    def test_un_aspersor_en_terreno_plano(self):
        lateral = LateralAspersion(PE40, ASPERSOR, MARCO, 1)
        r = lateral.presion_entrada_requerida()
        self.assertAlmostEqual(r.caudales_m3h[0], 1.2, places=3)
        hf = perdida_darcy(1.2 / 3600, 0.0356, 6.0, PE40.rugosidad_mm / 1000)  # primer aspersor a Se/2
        self.assertAlmostEqual(r.presion_entrada_m, 30.0 + hf, places=3)
        self.assertEqual(lateral.distancia_primer_aspersor_m, 6.0)

    def test_friccion_contra_christiansen(self):
        """Con aspersores casi iguales (Δh ≈ 6 %), la pérdida del paso a paso ≈ F·hf(Q total, L) (Hazen-Williams).

        Con mucha pérdida el F de Christiansen sobrestima: los aspersores de aguas arriba dan más caudal.
        """
        n = 8
        pe50 = Tuberia("PE 50", 44.6, usos=["portalateral"], c_hazen=150.0)
        lateral = LateralAspersion(pe50, ASPERSOR, MARCO, n, metodo="hazen")
        r = lateral.presion_entrada_requerida()
        longitud = 6.0 + (n - 1) * 12.0
        q_total = r.caudal_total_m3h / 3600
        f = factor_christiansen(n, 1.852, primera_salida_a_medio_espaciamiento=True)
        teorica = f * perdida_hazen_williams(q_total, 0.0446, longitud, 150.0)
        self.assertAlmostEqual(r.lateral.perdida_friccion_m, teorica, delta=0.015 * teorica)
        self.assertAlmostEqual(r.caudal_medio_m3h, 1.2, places=3)  # criterio: presión media = nominal

    def test_regla_del_veinte_por_ciento(self):
        n, r = numero_maximo_aspersores(PE40, ASPERSOR, MARCO)
        self.assertGreater(n, 1)
        self.assertLessEqual(r.variacion_presion, 0.20 + 1e-9)
        siguiente = LateralAspersion(PE40, ASPERSOR, MARCO, n + 1).presion_entrada_requerida()
        self.assertGreater(siguiente.variacion_presion, 0.20)

    def test_elevador_suma_a_la_presion_de_entrada(self):
        sin = LateralAspersion(PE40, ASPERSOR, MARCO, 6).presion_entrada_requerida()
        con = LateralAspersion(PE40, ASPERSOR, MARCO, 6, elevador=Elevador(1.0)).presion_entrada_requerida()
        self.assertAlmostEqual(con.presion_entrada_m - sin.presion_entrada_m, 1.0, places=3)
        self.assertAlmostEqual(con.presiones_boquilla_m[0], sin.presiones_boquilla_m[0], places=3)

    def test_pendiente_en_bajada_compensa_la_friccion(self):
        plano = LateralAspersion(PE40, ASPERSOR, MARCO, 10).presion_entrada_requerida()
        bajada = LateralAspersion(PE40, ASPERSOR, MARCO, 10, pendiente=-0.01).presion_entrada_requerida()
        self.assertLess(bajada.variacion_presion, plano.variacion_presion)

    def test_presion_conocida(self):
        lateral = LateralAspersion(PE40, ASPERSOR, MARCO, 8)
        requerida = lateral.presion_entrada_requerida()
        r = lateral.simular(requerida.presion_entrada_m)
        self.assertAlmostEqual(r.caudal_total_m3h, requerida.caudal_total_m3h, places=3)

    def test_desde_longitud(self):
        lateral = LateralAspersion.desde_longitud(PE40, ASPERSOR, MARCO, 100.0)
        self.assertEqual(lateral.numero_aspersores, 8)  # a 6, 18, …, 90 m (el siguiente, a 102 m, no cabe)
        self.assertAlmostEqual(lateral.longitud_m, 6 + 7 * 12)

    def test_avisos(self):
        riego = Riego(lamina_neta_mm=20, infiltracion_basica_mm_h=5.0)
        r = LateralAspersion(PE40, ASPERSOR, Marco(12, 18), 3, riego=riego, viento_ms=3.0).presion_entrada_requerida()
        avisos = " ".join(r.avisos())
        self.assertIn("escorrentía", avisos)
        self.assertIn("marco es muy abierto", avisos)
        self.assertFalse(r.cumple())
        self.assertAlmostEqual(r.tiempo_riego_h, riego.lamina_bruta_mm / r.intensidad_mm_h)


class TestCatalogo(unittest.TestCase):
    def test_catalogo_generico(self):
        aspersores = cargar_catalogo_aspersores()
        self.assertGreaterEqual(len(aspersores), 3)
        for a in aspersores:
            self.assertAlmostEqual(a.caudal_nominal_m3h, caudal_orificio_m3h(a.boquilla_mm, a.presion_nominal_m),
                                   places=2)
            self.assertLessEqual(a.presion_min_m, a.presion_nominal_m)
            self.assertGreaterEqual(a.presion_max_m, a.presion_nominal_m)


if __name__ == "__main__":
    unittest.main()
