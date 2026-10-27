"""Pruebas del bloque de goteo de un lote y de su subdivisión (motor de Python puro)."""

import math
import unittest

from riegolibre.nucleo.bloque import (CONEXION_EXTREMO, CONEXION_LADO_VALVULA, CONEXION_RAMAL_VALVULA, PORTA_ALTO,
                                      PORTA_BAJO, PORTA_CENTRO, PORTA_DISTANCIA, PORTA_FINAL, PORTA_MANUAL,
                                      VALV_ALTO, VALV_BAJO, VALV_CENTRO, VALV_FINAL, VALV_INICIO, VALV_PORCENTAJE,
                                      VALV_PUNTO, ParametrosBloque, azimut_entre, distancia_sobre_polilinea,
                                      punto_en, trazar_bloque)
from riegolibre.nucleo.subdivision import (AUTO_AREA, AUTO_CAUDAL, AUTO_NUMERO, DISTANCIA, HILERAS, NUMERO,
                                           ParametrosSubdivision, subdividir)
from tests.test_trazado import dentro, girar, puntos_del_lateral, rectangulo


def cota_hacia_x(x, y):
    """Terreno que baja 1 % hacia +x."""
    return 100.0 - 0.01 * x


def recortar(anillo, caja):
    """Caja (x0, y0, x1, y1) que envuelve el anillo, recortada a otra caja: basta para rectángulos alineados."""
    xs, ys = [p[0] for p in anillo], [p[1] for p in anillo]
    return (max(min(xs), caja[0]), max(min(ys), caja[1]), min(max(xs), caja[2]), min(max(ys), caja[3]))


class PruebasBloque(unittest.TestCase):
    def setUp(self):
        self.lote = [rectangulo(90, 80)]  # laterales a lo largo de x: 90 m

    def test_rectangulo_portalateral_al_inicio(self):
        params = ParametrosBloque(separacion_m=2.0, cabecera_m=0.5, costados_m=1.0, angulo_deg=0.0)
        b = trazar_bloque(self.lote, params)
        self.assertEqual(b.hileras, 40)  # y = 1, 3, …, 79
        self.assertEqual(len(b.laterales), 40)
        for lat in b.laterales:
            self.assertAlmostEqual(lat.longitud_m, 89.0)
            self.assertAlmostEqual(lat.inicio[0], 0.5)
            self.assertAlmostEqual(lat.fin[0], 89.5)
            self.assertEqual(lat.lado, "B")
        self.assertAlmostEqual(b.portalateral[0][0], 0.5)
        self.assertAlmostEqual(b.portalateral[0][1], 1.0)
        self.assertAlmostEqual(b.portalateral[-1][1], 79.0)
        self.assertAlmostEqual(b.longitud_portalateral_m, 78.0)
        self.assertAlmostEqual(b.area_regada_m2, 40 * 89.0 * 2.0)
        distancias = sorted(lat.distancia_m for lat in b.laterales)
        self.assertAlmostEqual(distancias[0], 0.0)
        self.assertAlmostEqual(distancias[1], 2.0)

    def test_costados_por_defecto_media_separacion(self):
        b = trazar_bloque(self.lote, ParametrosBloque(separacion_m=4.0, angulo_deg=0.0))
        ys = sorted({round(lat.inicio[1], 6) for lat in b.laterales})
        self.assertAlmostEqual(ys[0], 2.0)
        self.assertEqual(len(ys), 20)

    def test_portalateral_al_final_y_al_centro(self):
        final = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                                          portalateral=PORTA_FINAL))
        self.assertTrue(all(abs(lat.inicio[0] - 90.0) < 1e-6 and lat.fin[0] < lat.inicio[0]
                            for lat in final.laterales))
        centro = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                                           portalateral=PORTA_CENTRO))
        self.assertEqual(len(centro.laterales), 80)
        self.assertTrue(all(abs(lat.longitud_m - 45.0) < 1e-6 for lat in centro.laterales))
        self.assertEqual({lat.lado for lat in centro.laterales}, {"A", "B"})

    def test_portalateral_a_una_distancia(self):
        b = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                                      portalateral=PORTA_DISTANCIA, distancia_portalateral_m=30))
        largos = sorted({round(lat.longitud_m, 6) for lat in b.laterales})
        self.assertEqual(largos, [30.0, 60.0])

    def test_sentido_contrario_de_los_laterales(self):
        b = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=180.0))
        self.assertTrue(all(abs(lat.inicio[0] - 90.0) < 1e-6 for lat in b.laterales))
        self.assertAlmostEqual(b.azimut_laterales_grados, 270.0)

    def test_laterales_dobles_por_hilera(self):
        params = ParametrosBloque(separacion_m=3.0, laterales_por_hilera=2, separacion_en_hilera_m=1.0,
                                  angulo_deg=0.0, cabecera_m=0.0)
        b = trazar_bloque(self.lote, params)
        ys = sorted(lat.inicio[1] for lat in b.laterales)
        self.assertAlmostEqual(ys[0], 1.0)  # eje de la primera hilera a 1.5 m, lateral medio metro abajo
        self.assertAlmostEqual(ys[1], 2.0)
        self.assertEqual(b.hileras, 26)
        self.assertEqual(len(b.laterales), 52)
        self.assertAlmostEqual(b.area_regada_m2, 26 * 90 * 3.0)
        # El portalateral llega a los laterales de las hileras de los extremos.
        self.assertAlmostEqual(b.portalateral[0][1], ys[0])
        self.assertAlmostEqual(b.portalateral[-1][1], ys[-1])
        with self.assertRaises(ValueError):
            ParametrosBloque(separacion_m=2.0, laterales_por_hilera=3, separacion_en_hilera_m=1.0)

    def test_paralelogramo_portalateral_sigue_el_borde(self):
        lote = [[(0, 0), (90, 0), (120, 80), (30, 80)]]  # bordes de inicio y final inclinados
        b = trazar_bloque(lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0))
        self.assertEqual(len(b.portalateral), 2)  # recto, a lo largo del borde inclinado
        for lat in b.laterales:
            self.assertAlmostEqual(lat.longitud_m, 90.0, places=6)
            self.assertAlmostEqual(lat.inicio[0], lat.inicio[1] * 30 / 80, places=6)

    def test_lote_girado_y_direccion_automatica(self):
        lote = [girar(rectangulo(160, 40), 35, (80, 20))]
        b = trazar_bloque(lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.5))
        self.assertAlmostEqual(min(abs(b.angulo_deg - 35) % 180, 180 - abs(b.angulo_deg - 35) % 180), 0.0, places=3)
        for lat in b.laterales:
            for p in puntos_del_lateral(lat):
                self.assertTrue(dentro(p, lote, 1e-6))
        # Con un alcance corto conviene que los laterales vayan a lo ancho
        corto = trazar_bloque(lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.5), alcance_m=45)
        self.assertAlmostEqual(min(abs(corto.angulo_deg - 125) % 180, 180 - abs(corto.angulo_deg - 125) % 180),
                               0.0, places=3)

    def test_direccion_automatica_paralela_a_un_lado(self):
        from riegolibre.nucleo.bloque import direcciones_candidatas
        trapecio = [[(0, 0), (100, 0), (100, 60), (0, 90)]]  # lados a 0°, 90° y -16.7°
        for angulo in direcciones_candidatas(trapecio):
            self.assertTrue(any(min(abs(angulo - lado) % 180, 180 - abs(angulo - lado) % 180) < 1.0
                                for lado in (0.0, 90.0, 163.3, 73.3)), angulo)
        b = trazar_bloque(trapecio, ParametrosBloque(separacion_m=3.0), pendiente=lambda a: 0.0)
        self.assertIn(round(b.angulo_deg) % 180, (0, 90, 163, 73))

    def test_borde_alto_y_bajo(self):
        alto = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                                         portalateral=PORTA_ALTO), cota=cota_hacia_x)
        self.assertTrue(all(abs(lat.inicio[0]) < 1e-6 for lat in alto.laterales))
        self.assertLess(alto.pendiente_laterales, 0)  # en bajada
        bajo = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                                         portalateral=PORTA_BAJO), cota=cota_hacia_x)
        self.assertTrue(all(abs(lat.inicio[0] - 90) < 1e-6 for lat in bajo.laterales))
        self.assertGreater(bajo.pendiente_laterales, 0)
        sin_dem = trazar_bloque(self.lote, ParametrosBloque(separacion_m=2.0, angulo_deg=0.0, portalateral=PORTA_ALTO))
        self.assertTrue(sin_dem.avisos)

    def test_posicion_de_la_valvula(self):
        def cota_hacia_y(x, y):
            return 100.0 - 0.02 * y  # baja hacia +y: el extremo 1 del portalateral (y bajo) es el alto

        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_ALTO), cota=cota_hacia_y)
        self.assertAlmostEqual(b.valvula_m, 0.0)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_BAJO), cota=cota_hacia_y)
        self.assertAlmostEqual(b.valvula_m, b.longitud_portalateral_m)
        self.assertLess(b.desnivel_portalateral_m, 0)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_CENTRO))
        self.assertAlmostEqual(b.valvula_m, b.longitud_portalateral_m / 2)
        self.assertAlmostEqual(b.valvula[1], 40.0)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_PORCENTAJE, porcentaje_valvula=25))
        self.assertAlmostEqual(b.valvula_m, 0.25 * b.longitud_portalateral_m)
        # Automática: el extremo más cercano a la fuente
        b = trazar_bloque(self.lote, ParametrosBloque(**base), fuente=(0.0, 200.0))
        self.assertAlmostEqual(b.valvula_m, b.longitud_portalateral_m)

    def test_valvula_marcada_en_el_mapa(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0)
        # El portalateral va por x = 0, de y = 1 a y = 79: la válvula se proyecta sobre él.
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_PUNTO, punto_valvula=(3.0, 30.0)))
        self.assertAlmostEqual(b.valvula[0], 0.0)
        self.assertAlmostEqual(b.valvula[1], 30.0)
        self.assertEqual(b.avisos, [])
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_PUNTO, punto_valvula=(-50.0, -20.0)))
        self.assertAlmostEqual(b.valvula_m, 0.0)
        self.assertTrue(any("del portalateral" in a for a in b.avisos))
        # Sin punto: automática, con aviso
        b = trazar_bloque(self.lote, ParametrosBloque(**base, valvula=VALV_PUNTO), fuente=(0.0, 200.0))
        self.assertAlmostEqual(b.valvula_m, b.longitud_portalateral_m)
        self.assertTrue(any("No se ha marcado" in a for a in b.avisos))

    def test_tramos_de_conexion_con_la_valvula_en_un_extremo(self):
        # Portalateral por x = 0 de y = 1 a y = 79, hacia +y; válvula en su inicio (y = 1)
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, valvula=VALV_INICIO)
        b = trazar_bloque(self.lote, ParametrosBloque(**base))
        self.assertEqual(b.conexiones, [])
        self.assertIsNone(b.valvula_final)
        self.assertEqual(b.punto_de_la_valvula, b.valvula)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, prolongacion_extremo_m=1.0, prolongacion_valvula_m=0.5,
                                                      ramal_valvula_m=2.0))
        tipos = {tipo: linea for tipo, linea in b.conexiones}
        self.assertEqual(set(tipos), {CONEXION_EXTREMO, CONEXION_LADO_VALVULA, CONEXION_RAMAL_VALVULA})
        self.assertAlmostEqual(tipos[CONEXION_LADO_VALVULA][1][1], 0.5)  # más allá del primer lateral
        self.assertAlmostEqual(tipos[CONEXION_EXTREMO][0][1], 79.0)
        self.assertAlmostEqual(tipos[CONEXION_EXTREMO][1][1], 80.0)  # más allá del último
        # El ramal sale del extremo de la prolongación, perpendicular y a la izquierda del sentido (+y → -x)
        self.assertAlmostEqual(tipos[CONEXION_RAMAL_VALVULA][0][1], 0.5)
        self.assertAlmostEqual(b.valvula_final[0], -2.0)
        self.assertAlmostEqual(b.valvula_final[1], 0.5)
        self.assertEqual(b.punto_de_la_valvula, b.valvula_final)
        self.assertAlmostEqual(b.longitud_conexiones_m, 0.5 + 1.0 + 2.0)
        # El cálculo no cambia: el portalateral y la posición de la válvula son los mismos
        sin = trazar_bloque(self.lote, ParametrosBloque(**base))
        self.assertEqual(b.portalateral, sin.portalateral)
        self.assertAlmostEqual(b.valvula_m, sin.valvula_m)

    def test_tramos_de_conexion_con_la_valvula_en_el_final(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, valvula=VALV_FINAL)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, prolongacion_extremo_m=1.0, prolongacion_valvula_m=0.5,
                                                      ramal_valvula_m=2.0))
        tipos = {tipo: linea for tipo, linea in b.conexiones}
        self.assertAlmostEqual(tipos[CONEXION_LADO_VALVULA][1][1], 79.5)
        self.assertAlmostEqual(tipos[CONEXION_EXTREMO][1][1], 0.0)
        self.assertAlmostEqual(b.valvula_final[0], -2.0)
        self.assertAlmostEqual(b.valvula_final[1], 79.5)

    def test_tramos_de_conexion_con_la_valvula_al_centro(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, valvula=VALV_CENTRO)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, prolongacion_extremo_m=1.0, prolongacion_valvula_m=0.5,
                                                      ramal_valvula_m=3.0))
        # La prolongación del extremo va en los dos extremos; la del lado de la válvula no aplica
        self.assertEqual([t for t, _ in b.conexiones].count(CONEXION_EXTREMO), 2)
        self.assertNotIn(CONEXION_LADO_VALVULA, [t for t, _ in b.conexiones])
        self.assertTrue(any("no está en un extremo" in a for a in b.avisos))
        self.assertAlmostEqual(b.valvula_final[0], -3.0)
        self.assertAlmostEqual(b.valvula_final[1], 40.0)
        with self.assertRaises(ValueError):
            ParametrosBloque(**base, ramal_valvula_m=-1.0)

    def test_tramos_de_conexion_con_portalateral_quebrado(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, portalateral=PORTA_MANUAL, valvula=VALV_INICIO,
                    puntos_portalateral=((20.0, 0.0), (20.0, 40.0), (50.0, 40.0), (50.0, 80.0)))
        b = trazar_bloque(self.lote, ParametrosBloque(**base, prolongacion_extremo_m=2.0))
        (_, linea), = b.conexiones
        self.assertAlmostEqual(linea[0][0], b.portalateral[-1][0])
        self.assertAlmostEqual(math.dist(*linea), 2.0)

    def test_portalateral_dibujado_a_mano(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, portalateral=PORTA_MANUAL)
        # Recta vertical por x = 30: laterales a ambos lados, de 30 y 60 m
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((30.0, 0.0), (30.0, 80.0))))
        self.assertEqual(b.hileras, 40)
        self.assertEqual(len(b.laterales), 80)
        self.assertEqual(sorted({round(lat.longitud_m, 6) for lat in b.laterales}), [30.0, 60.0])
        self.assertEqual({lat.lado for lat in b.laterales}, {"A", "B"})
        self.assertAlmostEqual(b.portalateral[0][0], 30.0)
        self.assertAlmostEqual(b.longitud_portalateral_m, 80.0)
        self.assertEqual(b.avisos, [])
        # El sentido del dibujo no importa: se orienta hacia +y
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((30.0, 80.0), (30.0, 0.0))))
        self.assertAlmostEqual(b.portalateral[0][1], 0.0)
        # Con un quiebre: la conexión de cada lateral sigue la línea
        quebrada = ((20.0, 0.0), (20.0, 40.0), (50.0, 40.0), (50.0, 80.0))
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=quebrada))
        for lat in b.laterales:
            self.assertAlmostEqual(lat.inicio[0], 20.0 if lat.inicio[1] < 40.0 else 50.0, delta=0.6)

    def test_portalateral_dibujado_inclinado_deja_la_direccion_automatica(self):
        # Línea a 90° (hacia +y) → laterales perpendiculares (hacia ±x)
        base = dict(separacion_m=2.0, cabecera_m=0.0, portalateral=PORTA_MANUAL)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((30.0, 0.0), (30.0, 80.0))))
        self.assertAlmostEqual(math.sin(math.radians(b.angulo_deg)), 0.0, places=6)
        # El lote girado 30° y el portalateral dibujado a lo largo de su lado corto
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        girado = [girar(rectangulo(90, 80), 30.0)]
        linea = tuple((c * x - s * y, s * x + c * y) for x, y in ((30.0, 0.0), (30.0, 80.0)))
        b = trazar_bloque(girado, ParametrosBloque(**base, puntos_portalateral=linea))
        self.assertAlmostEqual(b.angulo_deg, 30.0, places=6)
        self.assertEqual(len(b.laterales), 80)

    def test_portalateral_dibujado_no_valido(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, portalateral=PORTA_MANUAL)
        with self.assertRaises(ValueError):  # sin línea
            ParametrosBloque(**base)
        with self.assertRaises(ValueError):  # un solo punto distinto
            ParametrosBloque(**base, puntos_portalateral=((5.0, 5.0), (5.0, 5.0)))
        with self.assertRaises(ValueError):  # retrocede en y
            trazar_bloque(self.lote, ParametrosBloque(
                **base, puntos_portalateral=((30.0, 0.0), (30.0, 60.0), (40.0, 20.0), (40.0, 80.0))))
        with self.assertRaises(ValueError):  # paralela a los laterales
            trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((10.0, 40.0), (60.0, 40.0))))
        # Fuera del lote: avisa
        with self.assertRaises(ValueError):
            trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((500.0, 0.0), (500.0, 80.0))))

    def test_portalateral_dibujado_parcial_avisa_de_hileras_sin_laterales(self):
        base = dict(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0, portalateral=PORTA_MANUAL)
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((30.0, 0.0), (30.0, 40.0))))
        self.assertLessEqual(b.hileras, 21)  # solo la mitad inferior del lote
        self.assertTrue(all(lat.inicio[1] <= 41.0 for lat in b.laterales))
        # Válvula en el extremo alto: sigue funcionando con la línea dibujada
        b = trazar_bloque(self.lote, ParametrosBloque(**base, puntos_portalateral=((30.0, 0.0), (30.0, 80.0)),
                                                      valvula=VALV_CENTRO))
        self.assertAlmostEqual(b.valvula[1], 40.0, delta=1.0)

    def test_direccion_con_dos_puntos(self):
        self.assertAlmostEqual(azimut_entre((0, 0), (0, 10)), 0.0)
        self.assertAlmostEqual(azimut_entre((0, 0), (10, 0)), 90.0)
        self.assertAlmostEqual(azimut_entre((5, 5), (0, 0)), 225.0)
        with self.assertRaises(ValueError):
            azimut_entre((1, 1), (1, 1))
        # Dos puntos sobre el lado inferior de un lote girado 30°: laterales paralelos a ese lado.
        lote = [girar(rectangulo(90, 60), 30.0)]
        p1, p2 = lote[0][0], lote[0][1]
        azimut = azimut_entre(p1, p2)
        b = trazar_bloque(lote, ParametrosBloque(separacion_m=2.0, cabecera_m=0.0,
                                                 angulo_deg=(90.0 - azimut) % 360.0))
        self.assertAlmostEqual(b.angulo_deg, 30.0)
        self.assertAlmostEqual(b.lateral_mas_largo_m, 90.0, places=3)

    def test_distancia_sobre_polilinea(self):
        self.assertEqual(distancia_sobre_polilinea([(0, 0), (10, 0), (10, 10)], (12, 4)), (14.0, 2.0))
        self.assertEqual(distancia_sobre_polilinea([(0, 0), (10, 0)], (-3, 4)), (0.0, 5.0))

    def test_caudal_y_lote_concavo(self):
        lote = [[(0, 0), (90, 0), (90, 30), (40, 30), (40, 60), (90, 60), (90, 80), (0, 80)]]  # una «C»
        params = ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                  caudal_lateral=lambda largo: 10.0 * largo)
        b = trazar_bloque(lote, params)
        for lat in b.laterales:
            for p in puntos_del_lateral(lat):
                self.assertTrue(dentro(p, lote, 1e-6))
        self.assertAlmostEqual(b.caudal, 10.0 * b.longitud_laterales_m)

    def test_punto_en_polilinea(self):
        self.assertEqual(punto_en([(0, 0), (10, 0), (10, 10)], 15), (10, 5))
        self.assertEqual(punto_en([(0, 0), (10, 0)], 50), (10, 0))


class PruebasSubdivision(unittest.TestCase):
    def setUp(self):
        self.lote = [rectangulo(200, 80)]
        self.bloque = ParametrosBloque(separacion_m=2.0, cabecera_m=0.0, angulo_deg=0.0,
                                       caudal_lateral=lambda largo: largo)  # 1 unidad por metro

    def cajas(self, partes):
        return sorted(recortar(p.anillo, (0, 0, 200, 80)) for p in partes)

    def test_sin_subdividir(self):
        partes = subdividir(self.lote, self.bloque, 0.0, ParametrosSubdivision())
        self.assertEqual(len(partes), 1)
        self.assertEqual(partes[0].hileras, 40)
        self.assertAlmostEqual(partes[0].caudal, 40 * 200)
        self.assertEqual(self.cajas(partes)[0], (0, 0, 200, 80))

    def test_cortes_por_distancia_con_hueco(self):
        partes = subdividir(self.lote, self.bloque, 0.0,
                            ParametrosSubdivision(cortes=DISTANCIA, cortes_valor=100, cortes_hueco_m=5))
        cajas = self.cajas(partes)
        self.assertEqual(len(cajas), 2)
        self.assertAlmostEqual(cajas[0][2], 100)
        self.assertAlmostEqual(cajas[1][0], 105)

    def test_cortes_por_numero(self):
        partes = subdividir(self.lote, self.bloque, 0.0,
                            ParametrosSubdivision(cortes=NUMERO, cortes_valor=4, cortes_hueco_m=0))
        self.assertEqual([round(c[2]) for c in self.cajas(partes)], [50, 100, 150, 200])

    def test_franjas_por_hileras_con_hueco(self):
        partes = subdividir(self.lote, self.bloque, 0.0,
                            ParametrosSubdivision(franjas=HILERAS, franjas_valor=15, franjas_hueco=2))
        self.assertEqual([p.hileras for p in partes], [15, 15, 6])  # 40 hileras: 15 + 2 + 15 + 2 + 6
        cajas = sorted(self.cajas(partes), key=lambda c: c[1])
        self.assertAlmostEqual(cajas[0][3], 30)  # hasta media separación después de la hilera 15 (y = 29)
        self.assertAlmostEqual(cajas[1][1], 34)  # el hueco son las hileras de y = 31 y 33

    def test_franjas_por_distancia_y_numero(self):
        partes = subdividir(self.lote, self.bloque, 0.0, ParametrosSubdivision(franjas=DISTANCIA, franjas_valor=20))
        self.assertEqual([p.hileras for p in partes], [10, 10, 10, 10])
        partes = subdividir(self.lote, self.bloque, 0.0, ParametrosSubdivision(franjas=NUMERO, franjas_valor=3))
        self.assertEqual(sorted(p.hileras for p in partes), [13, 13, 14])

    def test_automatica_por_caudal(self):
        params = ParametrosSubdivision(automatica=True, longitud_max_lateral_m=120, criterio=AUTO_CAUDAL,
                                       caudal_max=2500)
        partes = subdividir(self.lote, self.bloque, 0.0, params)
        # dos cortes de 100 m (laterales ≤ 120 m); cada mitad lleva 4000, así que dos franjas de 2000
        self.assertEqual(len(partes), 4)
        for p in partes:
            self.assertLessEqual(p.caudal, 2500)
            self.assertAlmostEqual(p.caudal, 2000)

    def test_automatica_por_area_y_numero(self):
        partes = subdividir(self.lote, self.bloque, 0.0, ParametrosSubdivision(
            automatica=True, longitud_max_lateral_m=500, criterio=AUTO_AREA, area_max_m2=6000))
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(p.area_m2 <= 6000 for p in partes))
        partes = subdividir(self.lote, self.bloque, 0.0, ParametrosSubdivision(
            automatica=True, longitud_max_lateral_m=500, criterio=AUTO_NUMERO, numero=4))
        self.assertEqual(len(partes), 4)

    def test_lote_girado(self):
        lote = [girar(rectangulo(200, 80), 30)]
        partes = subdividir(lote, ParametrosBloque(separacion_m=2.0, angulo_deg=30.0), 30.0,
                            ParametrosSubdivision(cortes=NUMERO, cortes_valor=2))
        self.assertEqual(len(partes), 2)
        centro = [sum(p[k] for p in partes[0].anillo) / 4 for k in (0, 1)]
        a = math.radians(30)
        self.assertLess(centro[0] * math.cos(a) + centro[1] * math.sin(a), 100)


if __name__ == "__main__":
    unittest.main()
