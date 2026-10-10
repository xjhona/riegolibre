"""Pruebas del trazado automático de la red principal (motor de Python puro)."""

import math
import random
import unittest

from riegolibre.nucleo.trazado_red import (DIRECTO, ORTOGONAL, ParametrosRed, ValvulaDestino,
                                           trazar_red)


def valvula(id, x, y, caudal=10000.0, turno=1):
    return ValvulaDestino(id, x, y, caudal, turno)


def hijos_de(red):
    """{nodo: [tramos que salen de él]}"""
    salen = {}
    for t in red.tramos:
        salen.setdefault(t.desde, []).append(t)
    return salen


def caudal_aguas_abajo(red, nodo, valvulas, turno):
    salen = hijos_de(red)
    total = sum(v.caudal_lh for v in valvulas if v.id == nodo and v.turno == turno)
    return total + sum(caudal_aguas_abajo(red, t.hasta, valvulas, turno) for t in salen.get(nodo, []))


def verificar_arbol(caso, red, valvulas):
    """Toda válvula está conectada a la fuente, sin ciclos ni tramos sueltos."""
    salen = hijos_de(red)
    alcanzados, pila = {"fuente"}, ["fuente"]
    while pila:
        for t in salen.get(pila.pop(), []):
            caso.assertNotIn(t.hasta, alcanzados, "ciclo o tramo repetido")
            alcanzados.add(t.hasta)
            pila.append(t.hasta)
    caso.assertEqual({v.id for v in valvulas} - alcanzados, set())
    caso.assertEqual(alcanzados - {v.id for v in valvulas} - {"fuente"}, set(red.uniones))
    posiciones = {"fuente": red.fuente, **red.uniones, **{v.id: (v.x, v.y) for v in valvulas}}
    for t in red.tramos:
        caso.assertAlmostEqual(math.dist(t.vertices[0], posiciones[t.desde]), 0, places=6)
        caso.assertAlmostEqual(math.dist(t.vertices[-1], posiciones[t.hasta]), 0, places=6)


class PruebasTrazadoRed(unittest.TestCase):
    def test_una_valvula_en_linea_recta(self):
        red = trazar_red((0, 0), [valvula("A", 300, 400)], ParametrosRed(modo=DIRECTO))
        self.assertEqual(len(red.tramos), 1)
        self.assertAlmostEqual(red.longitud_m, 500.0)
        self.assertEqual(red.uniones, {})

    def test_ortogonal_una_valvula_hace_una_ele(self):
        red = trazar_red((0, 0), [valvula("A", 300, 400)], ParametrosRed(angulo_grados=0))
        self.assertEqual(len(red.tramos), 1)
        self.assertEqual(len(red.tramos[0].vertices), 3)
        self.assertAlmostEqual(red.longitud_m, 700.0)
        for a, b in zip(red.tramos[0].vertices, red.tramos[0].vertices[1:]):
            self.assertTrue(abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9)

    def test_ortogonal_dos_valvulas_comparten_la_troncal(self):
        valvulas = [valvula("A", 100, 50), valvula("B", 100, -50)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(angulo_grados=0))
        verificar_arbol(self, red, valvulas)
        self.assertAlmostEqual(red.longitud_m, 200.0)  # troncal de 100 m y dos ramas de 50 m
        self.assertEqual(list(red.uniones.values()), [(100.0, 0.0)])
        troncal = next(t for t in red.tramos if t.hasta.startswith("Unión"))
        self.assertAlmostEqual(troncal.caudal_lh, 20000.0)

    def test_directo_forma_una_union_en_y(self):
        valvulas = [valvula("A", 100, 20), valvula("B", 100, -20)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO))
        verificar_arbol(self, red, valvulas)
        sin_union = 2 * math.hypot(100, 20)
        self.assertEqual(len(red.uniones), 1)
        self.assertLess(red.longitud_m, sin_union - 5)
        x, y = next(iter(red.uniones.values()))
        self.assertAlmostEqual(y, 0.0, places=3)  # por simetría, la unión queda sobre el eje
        self.assertTrue(0 < x < 100)

    def test_union_en_el_punto_de_fermat_ponderado(self):
        # Con tres pesos iguales (costo por metro igual) la unión forma ángulos de 120°.
        # Se verifica el equilibrio de fuerzas: la suma de los vectores unitarios ponderados es cero.
        valvulas = [valvula("A", 100, 60, 10000), valvula("B", 100, -60, 10000)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO))
        verificar_arbol(self, red, valvulas)
        self.assertEqual(len(red.uniones), 1)
        union = next(iter(red.uniones.values()))
        fuerza = [0.0, 0.0]
        for t in red.tramos:
            if t.hasta.startswith("Unión"):
                vecino = t.vertices[0]
            elif t.desde.startswith("Unión"):
                vecino = t.vertices[-1]
            else:
                continue
            w = 0.2 + (t.caudal_lh / 20000.0) ** 0.7  # costo por metro, con el caudal total de referencia
            d = math.dist(union, vecino)
            fuerza[0] += w * (vecino[0] - union[0]) / d
            fuerza[1] += w * (vecino[1] - union[1]) / d
        self.assertAlmostEqual(math.hypot(*fuerza), 0.0, places=3)

    def test_valvula_sobre_otro_tramo_no_agrega_tuberia(self):
        valvulas = [valvula("A", 200, 0), valvula("B", 120, 0)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO))
        verificar_arbol(self, red, valvulas)
        self.assertAlmostEqual(red.longitud_m, 200.0)
        self.assertEqual(red.uniones, {})
        self.assertEqual({t.hasta for t in red.tramos}, {"A", "B"})

    def test_turnos_distintos_no_suman_caudal(self):
        valvulas = [valvula("A", 100, 50, 10000, 1), valvula("B", 100, -50, 15000, 2)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(angulo_grados=0))
        troncal = next(t for t in red.tramos if t.hasta.startswith("Unión"))
        self.assertAlmostEqual(troncal.caudal_lh, 15000.0)

    def test_el_caudal_de_cada_tramo_es_lo_que_pasa_aguas_abajo(self):
        azar = random.Random(7)
        valvulas = [valvula(f"V{i}", azar.uniform(0, 600), azar.uniform(-300, 300),
                            azar.uniform(5000, 30000)) for i in range(25)]
        for modo in (ORTOGONAL, DIRECTO):
            red = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo))
            verificar_arbol(self, red, valvulas)
            for t in red.tramos:
                self.assertAlmostEqual(t.caudal_lh, caudal_aguas_abajo(red, t.hasta, valvulas, 1), places=4)

    def test_con_varios_turnos_el_arbol_sigue_siendo_valido(self):
        azar = random.Random(11)
        valvulas = [valvula(f"V{i}", azar.uniform(0, 500), azar.uniform(0, 400),
                            azar.uniform(5000, 20000), 1 + i % 3) for i in range(20)]
        for modo in (ORTOGONAL, DIRECTO):
            red = trazar_red((50, 20), valvulas, ParametrosRed(modo=modo))
            verificar_arbol(self, red, valvulas)
            for t in red.tramos:
                esperado = max(caudal_aguas_abajo(red, t.hasta, valvulas, turno) for turno in (1, 2, 3))
                self.assertAlmostEqual(t.caudal_lh, esperado, places=4)

    def test_ortogonal_solo_tiene_tramos_paralelos_a_los_ejes(self):
        azar = random.Random(3)
        valvulas = [valvula(f"V{i}", azar.uniform(0, 500), azar.uniform(0, 500)) for i in range(15)]
        angulo = 20.0
        red = trazar_red((10, 10), valvulas, ParametrosRed(angulo_grados=angulo))
        verificar_arbol(self, red, valvulas)
        c, s = math.cos(math.radians(angulo)), math.sin(math.radians(angulo))
        for t in red.tramos:
            for a, b in zip(t.vertices, t.vertices[1:]):
                u = (b[0] - a[0]) * c + (b[1] - a[1]) * s
                v = -(b[0] - a[0]) * s + (b[1] - a[1]) * c
                self.assertLess(min(abs(u), abs(v)), 1e-6)

    def test_la_red_es_mas_corta_que_una_estrella(self):
        azar = random.Random(5)
        valvulas = [valvula(f"V{i}", azar.uniform(100, 700), azar.uniform(-200, 200)) for i in range(30)]
        estrella = sum(math.dist((0, 0), (v.x, v.y)) for v in valvulas)
        for modo in (ORTOGONAL, DIRECTO):
            red = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo))
            self.assertLess(red.longitud_m, estrella * (0.6 if modo == DIRECTO else 0.75))

    def test_angulo_automatico_sigue_la_cuadricula_del_terreno(self):
        angulo = 30.0
        c, s = math.cos(math.radians(angulo)), math.sin(math.radians(angulo))
        valvulas = [valvula(f"V{i}{j}", 80 + 60 * i, -80 + 40 * j + 0.0) for i in range(6) for j in range(5)]
        girado = [valvula(v.id, v.x * c - v.y * s, v.x * s + v.y * c) for v in valvulas]
        automatica = trazar_red((0, 0), girado)
        fija = trazar_red((0, 0), girado, ParametrosRed(angulo_grados=0))
        self.assertAlmostEqual(automatica.angulo_grados, angulo, delta=1e-6)
        self.assertLess(automatica.longitud_m, fija.longitud_m)

    def test_con_economia_de_escala_se_prefiere_compartir_tuberia(self):
        # Dos válvulas lejanas y juntas: en lugar de dos tuberías paralelas, una troncal y una T.
        valvulas = [valvula("A", 400, 30, 20000), valvula("B", 400, -30, 20000)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO))
        self.assertEqual(len(red.uniones), 1)
        self.assertLess(red.longitud_m, 2 * math.hypot(400, 30) - 20)

    def test_valores_invalidos(self):
        with self.assertRaises(ValueError):
            trazar_red((0, 0), [])
        with self.assertRaisesRegex(ValueError, "no tienen caudal.*A"):
            trazar_red((0, 0), [valvula("A", 10, 10, 0)])
        with self.assertRaises(ValueError):
            ParametrosRed(modo="curvo")
        with self.assertRaises(ValueError):
            ParametrosRed(exponente=1.0)

    def test_valvula_sobre_la_fuente(self):
        valvulas = [valvula("A", 0, 0), valvula("B", 100, 0)]
        red = trazar_red((0, 0), valvulas, ParametrosRed(modo=DIRECTO))
        self.assertAlmostEqual(red.longitud_m, 100.0)

    def test_dos_valvulas_en_el_mismo_punto(self):
        valvulas = [valvula("A", 100, 100), valvula("B", 100, 100)]
        for modo in (ORTOGONAL, DIRECTO):
            red = trazar_red((0, 0), valvulas, ParametrosRed(modo=modo))
            verificar_arbol(self, red, valvulas)


if __name__ == "__main__":
    unittest.main()
