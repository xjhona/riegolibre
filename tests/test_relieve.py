"""Pruebas del relieve del terreno medido en una rejilla (sin QGIS)."""

import math
import unittest

from riegolibre.nucleo.relieve import relieve_desde_rejilla


def _rejilla(funcion, n=12):
    return {(i, j): funcion(i * 5.0, j * 5.0) for i in range(n) for j in range(n)}


class PruebasRelieve(unittest.TestCase):
    def test_plano_inclinado_al_este(self):
        relieve = relieve_desde_rejilla(_rejilla(lambda x, y: 100 + 0.02 * x), 5.0, 5.0)
        self.assertAlmostEqual(relieve.pendiente_a_lo_largo(0), 0.02, places=9)
        self.assertAlmostEqual(relieve.pendiente_a_lo_largo(90), 0.0, places=9)
        self.assertAlmostEqual(relieve.pendiente_a_lo_largo(45), 0.02 * math.cos(math.radians(45)), places=9)
        self.assertAlmostEqual(relieve.gradiente_medio[0], 0.02, places=9)
        angulo, coherencia = relieve.direccion_de_curvas()
        self.assertAlmostEqual(angulo, 90.0, places=6)  # las curvas van de norte a sur
        self.assertAlmostEqual(coherencia, 1.0, places=9)

    def test_plano_inclinado_al_noroeste(self):
        relieve = relieve_desde_rejilla(_rejilla(lambda x, y: 0.01 * (y - x)), 5.0, 5.0)
        angulo, _ = relieve.direccion_de_curvas()
        self.assertAlmostEqual(angulo, 45.0, places=6)  # el gradiente apunta a 135°; la curva, a 45°

    def test_un_lomo_que_el_plano_no_ve(self):
        # Ondulaciones este-oeste: el terreno sube y baja, así que un plano ajustado tiene pendiente
        # media casi cero, pero un lateral tendido hacia el este ve pendientes fuertes.
        relieve = relieve_desde_rejilla(_rejilla(lambda x, y: 2.0 * math.sin(x / 10.0), n=40), 5.0, 5.0)
        self.assertLess(abs(relieve.gradiente_medio[0]), 0.02)
        self.assertGreater(relieve.pendiente_a_lo_largo(0), 0.1)
        self.assertLess(relieve.pendiente_a_lo_largo(90), 1e-9)  # hacia el norte va a nivel
        angulo, coherencia = relieve.direccion_de_curvas()
        self.assertAlmostEqual(angulo, 90.0, places=6)
        self.assertGreater(coherencia, 0.99)

    def test_terreno_plano_no_tiene_curvas(self):
        relieve = relieve_desde_rejilla(_rejilla(lambda x, y: 50.0), 5.0, 5.0)
        self.assertIsNone(relieve.direccion_de_curvas())
        self.assertEqual(relieve.pendiente_a_lo_largo(30), 0.0)

    def test_un_cerro_no_tiene_direccion_dominante(self):
        relieve = relieve_desde_rejilla(
            _rejilla(lambda x, y: -0.001 * ((x - 30) ** 2 + (y - 30) ** 2), n=13), 5.0, 5.0)
        _, coherencia = relieve.direccion_de_curvas()
        self.assertLess(coherencia, 0.2)

    def test_bordes_y_puntos_insuficientes(self):
        cotas = {(i, j): 100 + 0.02 * i * 5.0 for i in range(3) for j in range(3)}
        relieve = relieve_desde_rejilla(cotas, 5.0, 5.0)
        self.assertEqual(len(relieve.gradientes), 9)  # los bordes usan diferencias de un solo lado
        self.assertAlmostEqual(relieve.pendiente_a_lo_largo(0), 0.02, places=9)
        # Solo cuentan los puntos de 'interior' (los demás sirven de vecinos); con menos de 6, no hay relieve.
        self.assertIsNone(relieve_desde_rejilla(cotas, 5.0, 5.0, interior=lambda i, j: i == 1 and j == 1))
        self.assertEqual(len(relieve_desde_rejilla(cotas, 5.0, 5.0, interior=lambda i, j: i > 0).gradientes), 6)


if __name__ == "__main__":
    unittest.main()
