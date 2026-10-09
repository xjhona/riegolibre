import math
import unittest

from riegolibre.nucleo import hidraulica as h


def colebrook(re, rr):
    f = 0.02
    for _ in range(100):
        f = (-2 * math.log10(rr / 3.7 + 2.51 / (re * math.sqrt(f)))) ** -2
    return f


class PruebasFriccion(unittest.TestCase):
    def test_laminar(self):
        self.assertAlmostEqual(h.factor_friccion(1000), 0.064)

    def test_swamee_jain_vs_colebrook(self):
        for re in (5e3, 2e4, 1e5, 1e6):
            for rr in (0.0, 1e-5, 1e-3):
                self.assertAlmostEqual(h.factor_friccion(re, rr) / colebrook(re, rr), 1.0, delta=0.02)

    def test_continuidad_en_transicion(self):
        self.assertAlmostEqual(h.factor_friccion(1999.999), h.factor_friccion(2000.0), places=4)
        self.assertAlmostEqual(h.factor_friccion(3999.999), h.factor_friccion(4000.0), places=4)

    def test_hazen_williams_valor_conocido(self):
        # Comparación con la forma en velocidad: V = 0.849·C·R^0.63·S^0.54
        q, d, c = 0.010, 0.100, 150
        v = q / (math.pi * d * d / 4)
        s = (v / (0.849 * c * (d / 4) ** 0.63)) ** (1 / 0.54)
        hf = h.perdida_hazen_williams(q, d, 100, c)
        self.assertAlmostEqual(hf, 100 * s, delta=0.005 * hf)

    def test_darcy_valor_conocido(self):
        # 10 L/s en 100 mm liso, 100 m: v = 1.273 m/s, Re ≈ 1.27e5, f ≈ 0.0171 → hf ≈ 1.41 m
        hf = h.perdida_darcy(0.010, 0.100, 100, 0.0)
        self.assertAlmostEqual(hf, 1.41, delta=0.03)

    def test_signo_del_caudal(self):
        self.assertAlmostEqual(h.perdida_darcy(-0.01, 0.1, 100), -h.perdida_darcy(0.01, 0.1, 100))


class PruebasChristiansen(unittest.TestCase):
    def test_coincide_con_suma_exacta(self):
        m = 1.852
        for n in (5, 20, 100):
            exacto = sum(i ** m for i in range(1, n + 1)) / (n ** (m + 1))
            self.assertAlmostEqual(h.factor_christiansen(n, m), exacto, delta=0.002)

    def test_limite_infinito(self):
        self.assertAlmostEqual(h.factor_christiansen(10000, 1.852), 1 / 2.852, places=3)


class PruebasUtilidades(unittest.TestCase):
    def test_interpolar_perfil(self):
        perfil = [(0, 100), (10, 101), (30, 99)]
        self.assertAlmostEqual(h.interpolar_perfil(perfil, 5), 100.5)
        self.assertAlmostEqual(h.interpolar_perfil(perfil, 20), 100.0)
        self.assertAlmostEqual(h.interpolar_perfil(perfil, -5), 100)
        self.assertAlmostEqual(h.interpolar_perfil(perfil, 50), 99)

    def test_resolver_creciente(self):
        x = h.resolver_creciente(lambda x: x ** 3, 27.0, 0.0, 1.0, tolerancia=1e-9)
        self.assertAlmostEqual(x, 3.0, places=6)

    def test_resolver_sin_solucion(self):
        with self.assertRaises(h.PresionInsuficiente):
            h.resolver_creciente(lambda x: x + 10, 5.0, 0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
