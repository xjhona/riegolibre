"""Pruebas del trazado de la red sobre un mapa de costos (zonas, caminos, barreras y relieve)."""

import math
import random
import unittest

from riegolibre.nucleo.terreno import Terreno, celda_automatica
from riegolibre.nucleo.trazado_red import (DIRECTO, ORTOGONAL, ParametrosRed,
                                           trazar_red)
from tests.test_trazado_red import caudal_aguas_abajo, valvula, verificar_arbol


def terreno_para(fuente, valvulas):
    puntos = [fuente] + [(v.x, v.y) for v in valvulas]
    return Terreno.cubriendo(puntos, celda_automatica(puntos))


def rectangulo(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def puntos_de(red, paso=1.0):
    """Puntos a lo largo de todas las tuberías, cada `paso` metros."""
    for t in red.tramos:
        for a, b in zip(t.vertices, t.vertices[1:]):
            n = max(1, int(math.dist(a, b) / paso))
            for k in range(n + 1):
                yield a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n


def cruza(red, x0, y0, x1, y1):
    return any(x0 < x < x1 and y0 < y < y1 for x, y in puntos_de(red))


class PruebasRejilla(unittest.TestCase):
    def test_un_terreno_sin_restricciones_usa_el_trazado_libre(self):
        valvulas = [valvula("A", 300, 400)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), terreno_para((0, 0), valvulas))
        self.assertAlmostEqual(red.longitud_m, 500.0)
        self.assertEqual(len(red.tramos[0].vertices), 2)

    def test_directo_rodea_una_zona_prohibida(self):
        valvulas = [valvula("A", 200, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(80, -50, 120, 60)], None)
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        verificar_arbol(self, red, valvulas)
        self.assertFalse(cruza(red, 80, -50, 120, 60))
        self.assertGreater(red.longitud_m, 200 + 20)  # hay desvío
        self.assertLess(red.longitud_m, 245)  # pero rodea por el lado más corto
        self.assertEqual(red.m_penalizados, 0.0)

    def test_ortogonal_rodea_una_zona_prohibida_con_quiebres_a_90_grados(self):
        valvulas = [valvula("A", 200, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(80, -50, 120, 60)], None)
        red = trazar_red((0, 0), valvulas, ParametrosRed(angulo_grados=0), t)
        verificar_arbol(self, red, valvulas)
        self.assertFalse(cruza(red, 80, -50, 120, 60))
        for tramo in red.tramos:
            for a, b in zip(tramo.vertices, tramo.vertices[1:]):
                self.assertLess(min(abs(a[0] - b[0]), abs(a[1] - b[1])), 1e-6)
        self.assertLess(red.longitud_m, 200 + 2 * 60 + 10)

    def test_una_zona_que_solo_encarece_se_cruza_si_el_desvio_sale_mas_caro(self):
        valvulas = [valvula("A", 200, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(90, -300, 110, 300)], 1.2)  # franja larga: rodearla es carísimo
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        self.assertAlmostEqual(red.longitud_m, 200.0, delta=2.0)
        self.assertAlmostEqual(red.m_penalizados, 20.0, delta=8.0)

    def test_una_zona_que_encarece_mucho_se_evita(self):
        valvulas = [valvula("A", 200, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(80, -50, 120, 60)], 50.0)
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        self.assertFalse(cruza(red, 80, -50, 120, 60))
        self.assertEqual(red.m_penalizados, 0.0)

    def test_sigue_un_camino_paralelo_cuando_abarata_el_tendido(self):
        valvulas = [valvula("A", 400, 0)]
        sin_camino = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), self._con_zona_lejana(valvulas))
        t = terreno_para((0, 0), valvulas)
        camino = [(0, 40), (150, 40), (150, 0), (400, 0)]
        t.descontar_linea(camino, 0.2)
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        verificar_arbol(self, red, valvulas)
        self.assertAlmostEqual(sin_camino.longitud_m, 400.0, delta=1.0)
        self.assertGreater(red.m_descontados, 150)
        # La red usa el camino aunque sea más largo que la recta.
        self.assertGreater(red.longitud_m, 400.0)

    @staticmethod
    def _con_zona_lejana(valvulas):
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(5000, 5000, 5010, 5010)], 2.0)
        t.factor[0] = 1.0 + 1e-9  # basta con que haya algo para que se use la cuadrícula
        return t

    def test_una_barrera_cara_se_rodea_y_una_barata_se_cruza(self):
        valvulas = [valvula("A", 200, 0)]
        for costo, debe_cruzar in ((10.0, True), (None, False), (5000.0, False)):
            t = terreno_para((0, 0), valvulas)
            t.barrera_linea([(100, -60), (100, 50)], costo)  # canal de 110 m con la recta atravesándolo
            red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
            verificar_arbol(self, red, valvulas)
            cruza_canal = any(abs(x - 100) < 1.0 and -60 < y < 50 for x, y in puntos_de(red, 0.5))
            self.assertEqual(cruza_canal, debe_cruzar, f"costo de cruce {costo}")

    def test_una_barrera_diagonal_prohibida_no_se_cruza_por_la_esquina(self):
        # Una pared en diagonal que separa la fuente de la válvula y se extiende más allá del predio:
        # si el trazado pudiera pasar en diagonal entre dos celdas de la pared, la cruzaría.
        valvulas = [valvula("A", 100, 100)]
        t = terreno_para((0, 0), valvulas)
        t.barrera_linea([(-300, 400), (400, -300)], None)  # la recta x + y = 100
        for modo in (DIRECTO, ORTOGONAL):
            with self.assertRaisesRegex(ValueError, "No hay camino"):
                trazar_red((0, 0), valvulas, ParametrosRed(modo=modo), t)

    def test_una_barrera_diagonal_con_el_extremo_libre_se_rodea(self):
        valvulas = [valvula("A", 100, 100)]
        t = terreno_para((0, 0), valvulas)
        t.barrera_linea([(0, 100), (100, 0)], None)  # pared corta entre la fuente y la válvula
        for modo in (DIRECTO, ORTOGONAL):
            red = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo), t)
            verificar_arbol(self, red, valvulas)
            self.assertFalse(any(abs(x + y - 100) < 0.5 and 0 < x < 100 for x, y in puntos_de(red, 0.25)))

    def test_la_valvula_rodeada_de_zonas_prohibidas_da_un_error_claro(self):
        valvulas = [valvula("A", 100, 0)]
        t = terreno_para((0, 0), valvulas)
        # un anillo cerrado alrededor de la válvula
        t.penalizar_poligono([rectangulo(60, -60, 140, 60), rectangulo(80, -40, 120, 40)], None)
        with self.assertRaisesRegex(ValueError, "No hay camino hasta la válvula «A»"):
            trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)

    def test_la_valvula_en_el_borde_de_una_zona_prohibida_se_alcanza(self):
        valvulas = [valvula("A", 100, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(100, -50, 200, 50)], None)  # la válvula queda justo en el borde
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        verificar_arbol(self, red, valvulas)
        self.assertAlmostEqual(red.longitud_m, 100.0, delta=2.0)

    def test_hay_que_rodear_una_zona_mas_grande_que_el_predio(self):
        valvulas = [valvula("A", 200, 0)]
        t = terreno_para((0, 0), valvulas)
        t.penalizar_poligono([rectangulo(80, -150, 120, 90)], None)  # sobrepasa el margen inicial de la cuadrícula
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO), t)
        self.assertFalse(cruza(red, 80, -150, 120, 90))
        self.assertLess(red.longitud_m, 200 + 2 * 100)

    def test_dos_valvulas_en_el_mismo_punto_o_sobre_la_fuente(self):
        for valvulas in ([valvula("A", 100, 100), valvula("B", 100, 100)],
                         [valvula("A", 0, 0), valvula("B", 100, 0)]):
            for modo in (DIRECTO, ORTOGONAL):
                t = terreno_para((0, 0), valvulas)
                t.penalizar_poligono([rectangulo(40, 30, 60, 50)], None)
                red = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo), t)
                verificar_arbol(self, red, valvulas)

    def test_el_costo_es_parecido_al_del_trazado_libre_cuando_nada_estorba(self):
        azar = random.Random(5)
        valvulas = [valvula(f"V{i}", azar.uniform(100, 700), azar.uniform(-200, 200),
                            azar.uniform(5000, 30000)) for i in range(30)]
        for modo in (DIRECTO, ORTOGONAL):
            libre = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo))
            en_rejilla = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo),
                                    self._con_zona_lejana(valvulas))
            verificar_arbol(self, en_rejilla, valvulas)
            self.assertLess(en_rejilla.costo, libre.costo * 1.06, modo)

    def test_el_caudal_de_cada_tramo_es_lo_que_pasa_aguas_abajo(self):
        azar = random.Random(11)
        valvulas = [valvula(f"V{i}", azar.uniform(0, 500), azar.uniform(0, 400),
                            azar.uniform(5000, 20000), 1 + i % 3) for i in range(30)]
        valvulas = [v for v in valvulas if not (190 < v.x < 310 and 90 < v.y < 260)]
        for modo in (DIRECTO, ORTOGONAL):
            t = terreno_para((50, 20), valvulas)
            t.penalizar_poligono([rectangulo(200, 100, 300, 250)], None)
            red = trazar_red((50, 20), valvulas, ParametrosRed(modo=modo), t)
            verificar_arbol(self, red, valvulas)
            self.assertFalse(cruza(red, 200, 100, 300, 250))
            for tramo in red.tramos:
                esperado = max(caudal_aguas_abajo(red, tramo.hasta, valvulas, turno) for turno in (1, 2, 3))
                self.assertAlmostEqual(tramo.caudal_lh, esperado, places=4)

    def test_ortogonal_con_angulo_fijo_solo_tiene_tramos_paralelos_a_los_ejes(self):
        azar = random.Random(3)
        valvulas = [valvula(f"V{i}", azar.uniform(0, 500), azar.uniform(0, 500)) for i in range(15)]
        t = terreno_para((10, 10), valvulas)
        t.penalizar_poligono([rectangulo(150, 150, 250, 300)], None)
        angulo = 20.0
        red = trazar_red((10, 10), valvulas, ParametrosRed(angulo_grados=angulo), t)
        verificar_arbol(self, red, valvulas)
        c, s = math.cos(math.radians(angulo)), math.sin(math.radians(angulo))
        for tramo in red.tramos:
            for a, b in zip(tramo.vertices, tramo.vertices[1:]):
                u = (b[0] - a[0]) * c + (b[1] - a[1]) * s
                v = -(b[0] - a[0]) * s + (b[1] - a[1]) * c
                self.assertLess(min(abs(u), abs(v)), 1e-6)


class PruebasRelieve(unittest.TestCase):
    @staticmethod
    def cerro(x, y):
        return 40 * math.exp(-((x - 300) ** 2 + y ** 2) / (2 * 70 ** 2))

    def trazar(self, relieve=True, **parametros):
        valvulas = [valvula("A", 600, 0)]
        t = terreno_para((0, 0), valvulas)
        if relieve:
            t.cargar_cotas(self.cerro)
        else:
            t.factor[0] = 1.0 + 1e-9
        return trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO, **parametros), t)

    def test_rodea_el_cerro_en_lugar_de_subirlo(self):
        red = self.trazar()
        self.assertGreater(red.longitud_m, 610)
        self.assertLess(max(self.cerro(x, y) for x, y in puntos_de(red, 5)), 12)

    def test_sin_penalizar_el_relieve_va_en_linea_recta(self):
        red = self.trazar(costo_subida=0.0, pendiente_duplica=None)
        self.assertAlmostEqual(red.longitud_m, 600.0, delta=3.0)

    def test_solo_cuesta_subir_en_el_sentido_del_flujo(self):
        # Con una pendiente uniforme, bajar es gratis (solo cuenta la pendiente) y subir cuesta más.
        def trazar(signo):
            valvulas = [valvula("A", 300, 0)]
            t = terreno_para((0, 0), valvulas)
            t.cargar_cotas(lambda x, y: signo * 0.1 * x)
            return trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO, pendiente_duplica=None), t)

        sube, baja = trazar(1), trazar(-1)
        self.assertGreater(sube.costo, baja.costo * 1.3)
        self.assertAlmostEqual(sube.longitud_m, baja.longitud_m, delta=1.0)  # mismo recorrido

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            ParametrosRed(costo_subida=-1)
        with self.assertRaises(ValueError):
            ParametrosRed(pendiente_duplica=0)


if __name__ == "__main__":
    unittest.main()
