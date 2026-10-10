"""Pruebas del trazado automático de subunidades (motor de Python puro)."""

import math
import unittest

from riegolibre.nucleo.trazado import (LADOS_UNO, Orientacion, ParametrosTrazado, area_anillos,
                                       buscar_trazados, orientaciones_candidatas, trazar)


def rectangulo(ancho, alto, x0=0.0, y0=0.0):
    return [(x0, y0), (x0 + ancho, y0), (x0 + ancho, y0 + alto), (x0, y0 + alto)]


def girar(anillo, grados, centro=(0.0, 0.0)):
    c, s = math.cos(math.radians(grados)), math.sin(math.radians(grados))
    return [(centro[0] + c * (x - centro[0]) - s * (y - centro[1]),
             centro[1] + s * (x - centro[0]) + c * (y - centro[1])) for x, y in anillo]


def dentro(punto, anillos, tolerancia=1e-6):
    """Punto dentro del polígono (par-impar), con una pequeña tolerancia en los bordes."""
    for dx, dy in ((0, 0), (tolerancia, 0), (-tolerancia, 0), (0, tolerancia), (0, -tolerancia)):
        x, y = punto[0] + dx, punto[1] + dy
        cruces = 0
        for anillo in anillos:
            for i in range(len(anillo)):
                (x1, y1), (x2, y2) = anillo[i], anillo[(i + 1) % len(anillo)]
                if (y1 <= y < y2 or y2 <= y < y1) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    cruces += 1
        if cruces % 2:
            return True
    return False


def puntos_del_lateral(lat, paso=0.5):
    n = max(1, int(lat.longitud_m / paso))
    return [(lat.inicio[0] + (lat.fin[0] - lat.inicio[0]) * i / n,
             lat.inicio[1] + (lat.fin[1] - lat.inicio[1]) * i / n) for i in range(n + 1)]


class PruebasGeometria(unittest.TestCase):
    def test_area_con_hueco_y_partes(self):
        exterior, hueco = rectangulo(100, 60), rectangulo(20, 20, 40, 20)
        self.assertAlmostEqual(area_anillos([exterior]), 6000)
        self.assertAlmostEqual(area_anillos([exterior, hueco]), 5600)
        self.assertAlmostEqual(area_anillos([exterior, hueco[::-1]]), 5600)
        self.assertAlmostEqual(area_anillos([exterior, rectangulo(10, 10, 200, 0)]), 6100)

    def test_orientaciones_incluyen_los_ejes_del_terreno(self):
        angulos = orientaciones_candidatas([girar(rectangulo(200, 40), 30)])
        for esperado in (30.0, 120.0):
            self.assertTrue(any(abs(a - esperado) < 0.5 for a in angulos), (esperado, angulos))
        self.assertTrue(all(0 <= a < 180 for a in angulos))
        self.assertEqual(angulos, sorted(angulos))

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            ParametrosTrazado(separacion_m=0)
        with self.assertRaises(ValueError):
            ParametrosTrazado(separacion_m=1, caudal_max_lh=-5)
        with self.assertRaises(ValueError):
            Orientacion(0, 0)
        with self.assertRaises(ValueError):
            trazar([[(0, 0), (1, 1)]], ParametrosTrazado(1.5), Orientacion(0, 30))


class PruebasTrazadoRectangular(unittest.TestCase):
    def test_alcance_corto_obliga_a_varios_portalaterales(self):
        # 100 × 60 m con laterales de hasta 40 m por lado: hacen falta dos bandas de 50 m.
        t = trazar([rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=0.0), Orientacion(0, 40))
        self.assertEqual(t.numero_subunidades, 2)
        self.assertAlmostEqual(t.longitud_laterales_m, 30 * 100)
        self.assertAlmostEqual(t.fraccion_sin_cubrir, 0.0)
        xs = sorted(s.portalateral[0][0] for s in t.subunidades)
        self.assertAlmostEqual(xs[0], 25.0, places=3)  # centrados en su banda
        self.assertAlmostEqual(xs[1], 75.0, places=3)
        for s in t.subunidades:
            self.assertEqual(len(s.laterales), 60)
            self.assertAlmostEqual(s.longitud_portalateral_m, 60.0)
            self.assertTrue(all(abs(lat.longitud_m - 25.0) < 1e-6 for lat in s.laterales))

    def test_un_solo_portalateral_centrado(self):
        t = trazar([rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=0.0), Orientacion(0, 60))
        self.assertEqual(t.numero_subunidades, 1)
        self.assertAlmostEqual(t.subunidades[0].portalateral[0][0], 50.0, places=3)

    def test_margen_recorta_los_extremos(self):
        t = trazar([rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=1.0), Orientacion(0, 60))
        largos = [lat.longitud_m for lat in t.subunidades[0].laterales]
        self.assertAlmostEqual(max(largos), 49.0, places=3)
        self.assertAlmostEqual(min(largos), 49.0, places=3)

    def test_caudal_maximo_parte_la_subunidad_en_trozos_iguales(self):
        # Por defecto el «caudal» es la longitud: 30 laterales de 100 m son 3000 m.
        params = ParametrosTrazado(2.0, margen_m=0.0, caudal_max_lh=1100)
        t = trazar([rectangulo(100, 60)], params, Orientacion(0, 60))
        self.assertEqual(t.numero_subunidades, 3)
        for s in t.subunidades:
            self.assertAlmostEqual(s.caudal, 1000.0)
            self.assertAlmostEqual(s.longitud_portalateral_m, 20.0)
            self.assertEqual(len({lat.conexion for lat in s.laterales}), 10)
        # Portalaterales seguidos sobre la misma recta, sin traslape.
        tramos = sorted((min(s.portalateral[0][1], s.portalateral[1][1]),
                         max(s.portalateral[0][1], s.portalateral[1][1])) for s in t.subunidades)
        self.assertAlmostEqual(tramos[0][1], tramos[1][0])
        self.assertAlmostEqual(tramos[1][1], tramos[2][0])

    def test_caudal_del_lateral_personalizado(self):
        # Un emisor cada 0.3 m con 1.6 L/h: el caudal de un lateral crece con su longitud.
        params = ParametrosTrazado(2.0, margen_m=0.0, caudal_max_lh=6000,
                                   caudal_lateral=lambda largo: (int(largo / 0.3) + 1) * 1.6)
        t = trazar([rectangulo(100, 60)], params, Orientacion(0, 60))
        self.assertEqual(t.numero_subunidades, 3)  # 30 laterales dobles de 534 L/h = 16 000 L/h
        self.assertTrue(all(s.caudal <= 6000 for s in t.subunidades))
        self.assertAlmostEqual(sum(s.caudal for s in t.subunidades), 30 * 2 * (int(50 / 0.3) + 1) * 1.6)

    def test_un_lado(self):
        params = ParametrosTrazado(2.0, margen_m=0.0, lados=LADOS_UNO)
        t = trazar([rectangulo(100, 60)], params, Orientacion(0, 60))
        self.assertEqual(t.numero_subunidades, 2)  # 100 m con 60 m de alcance por portalateral
        self.assertLess(t.fraccion_sin_cubrir, 1e-4)
        for s in t.subunidades:
            self.assertEqual(len({lat.lado for lat in s.laterales}), 1)

    def test_lados_a_y_b_segun_el_sentido_del_portalateral(self):
        t = trazar([rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=0.0), Orientacion(0, 60))
        s = t.subunidades[0]
        (x1, y1), (x2, y2) = s.portalateral
        d = (x2 - x1, y2 - y1)
        self.assertEqual({lat.lado for lat in s.laterales}, {"A", "B"})
        for lat in s.laterales:
            v = (lat.fin[0] - lat.inicio[0], lat.fin[1] - lat.inicio[1])
            producto = d[0] * v[1] - d[1] * v[0]  # > 0: el lateral queda a la izquierda
            self.assertEqual(lat.lado, "A" if producto > 0 else "B")
            self.assertAlmostEqual(lat.distancia_m, abs(lat.inicio[1] - y1), places=6)

    def test_inicio_del_portalateral_cerca_de_la_fuente(self):
        terreno, params = [rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=0.0)
        abajo = trazar(terreno, params, Orientacion(0, 60), fuente=(50.0, -100.0)).subunidades[0]
        arriba = trazar(terreno, params, Orientacion(0, 60), fuente=(50.0, 200.0)).subunidades[0]
        self.assertLess(abajo.portalateral[0][1], abajo.portalateral[1][1])
        self.assertGreater(arriba.portalateral[0][1], arriba.portalateral[1][1])
        # La primera conexión queda a media separación del inicio y la numeración sigue al sentido.
        self.assertAlmostEqual(min(lat.distancia_m for lat in arriba.laterales), 1.0)
        self.assertEqual(min(lat.conexion for lat in arriba.laterales), 0)

    def test_terreno_pequeno_sin_laterales_suficientes(self):
        t = trazar([rectangulo(10, 3)], ParametrosTrazado(1.5, margen_m=0.5), Orientacion(0, 30))
        self.assertEqual(t.numero_subunidades, 0)
        self.assertAlmostEqual(t.fraccion_sin_cubrir, 1.0)


class PruebasFormasIrregulares(unittest.TestCase):
    def _verificar_dentro(self, trazado, anillos):
        for s in trazado.subunidades:
            for lat in s.laterales:
                for p in puntos_del_lateral(lat):
                    self.assertTrue(dentro(p, anillos), f"fuera del terreno: {p}")

    def test_hueco_no_se_cruza(self):
        anillos = [rectangulo(100, 60), rectangulo(20, 20, 40, 20)]
        t = trazar(anillos, ParametrosTrazado(2.0, margen_m=0.5), Orientacion(0, 60))
        self._verificar_dentro(t, anillos)
        sin_hueco = trazar([rectangulo(100, 60)], ParametrosTrazado(2.0, margen_m=0.5), Orientacion(0, 60))
        self.assertLess(t.longitud_laterales_m, sin_hueco.longitud_laterales_m - 150)  # 10 laterales × ~20 m
        self.assertAlmostEqual(t.area_terreno_m2, 5600)

    def test_terreno_en_l_queda_cubierto_sin_salirse(self):
        l = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
        t = trazar([l], ParametrosTrazado(2.0, margen_m=0.5), Orientacion(0, 60))
        self._verificar_dentro(t, [l])
        self.assertAlmostEqual(t.area_terreno_m2, 100 * 40 + 40 * 60)
        self.assertLess(t.fraccion_sin_cubrir, 0.05)

    def test_terreno_en_u_necesita_un_portalateral_por_brazo(self):
        u = [(0, 0), (100, 0), (100, 100), (70, 100), (70, 30), (30, 30), (30, 100), (0, 100)]
        t = trazar([u], ParametrosTrazado(2.0, margen_m=0.5), Orientacion(0, 60))
        self._verificar_dentro(t, [u])
        self.assertGreaterEqual(t.numero_subunidades, 2)
        self.assertLess(t.fraccion_sin_cubrir, 0.06)

    def test_los_laterales_de_subunidades_distintas_no_se_traslapan(self):
        l = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
        t = trazar([l], ParametrosTrazado(2.0, margen_m=0.5), Orientacion(0, 30))
        por_linea = {}
        for s in t.subunidades:
            for lat in s.laterales:
                y = round(lat.inicio[1], 6)
                a, b = sorted((lat.inicio[0], lat.fin[0]))
                for otro_a, otro_b in por_linea.get(y, []):
                    self.assertTrue(b <= otro_a + 1e-6 or a >= otro_b - 1e-6, (y, (a, b), (otro_a, otro_b)))
                por_linea.setdefault(y, []).append((a, b))

    def test_terreno_girado_y_laterales_no_horizontales(self):
        anillo = girar(rectangulo(120, 50, 10, 10), 37, (50, 50))
        t = trazar([anillo], ParametrosTrazado(2.0, margen_m=0.5), Orientacion(37, 70))
        self._verificar_dentro(t, [anillo])
        self.assertEqual(t.numero_subunidades, 1)
        self.assertLess(t.fraccion_sin_cubrir, 0.04)
        lat = t.subunidades[0].laterales[0]
        angulo = math.degrees(math.atan2(lat.fin[1] - lat.inicio[1], lat.fin[0] - lat.inicio[0])) % 180
        self.assertAlmostEqual(angulo, 37.0, places=4)


class PruebasBusqueda(unittest.TestCase):
    def test_elige_laterales_cortos_a_traves_del_terreno_alargado(self):
        # Rectángulo de 200 × 40 m girado 30°: lo mejor es tender los laterales a lo ancho (120°).
        anillo = girar(rectangulo(200, 40), 30)
        orientaciones = [Orientacion(a, 25.0) for a in orientaciones_candidatas([anillo])]
        trazados = buscar_trazados([anillo], ParametrosTrazado(2.0, margen_m=0.5), orientaciones)
        mejor = trazados[0]
        self.assertAlmostEqual(mejor.orientacion.angulo_deg, 120.0, delta=1.0)
        self.assertEqual(mejor.numero_subunidades, 1)
        self.assertLess(mejor.fraccion_sin_cubrir, 0.05)
        self.assertAlmostEqual(mejor.azimut_laterales_grados, (90 - 120) % 180, delta=1.0)
        self.assertEqual(trazados, sorted(trazados, key=lambda x: x.puntuacion))
        angulos = [t.orientacion.angulo_deg for t in trazados]
        for i, a in enumerate(angulos):  # alternativas realmente distintas
            for b in angulos[i + 1:]:
                self.assertGreaterEqual(min(abs(a - b) % 180, 180 - abs(a - b) % 180), 8.0)

    def test_la_pendiente_a_lo_largo_de_los_laterales_penaliza(self):
        anillo = rectangulo(100, 100)
        params = ParametrosTrazado(2.0, margen_m=0.5)
        plano = [Orientacion(0, 60, 0.0), Orientacion(90, 60, 0.0)]
        con_pendiente = [Orientacion(0, 60, 0.05), Orientacion(90, 60, 0.0)]
        self.assertEqual(buscar_trazados([anillo], params, plano)[0].orientacion.angulo_deg in (0, 90), True)
        mejor = buscar_trazados([anillo], params, con_pendiente)[0]
        self.assertEqual(mejor.orientacion.angulo_deg, 90)

    def test_terreno_grande_usa_pasada_rapida_y_resultado_final_exacto(self):
        anillo = rectangulo(600, 400)
        orientaciones = [Orientacion(a, 80.0) for a in (0, 45, 90)]
        trazados = buscar_trazados([anillo], ParametrosTrazado(1.5, margen_m=0.5), orientaciones, cantidad=2)
        self.assertEqual(len(trazados), 2)
        for t in trazados:
            self.assertEqual(t.separacion_m, 1.5)
            self.assertLess(t.fraccion_sin_cubrir, 0.05)

    def test_sin_orientaciones(self):
        with self.assertRaises(ValueError):
            buscar_trazados([rectangulo(10, 10)], ParametrosTrazado(1.5), [])


if __name__ == "__main__":
    unittest.main()
