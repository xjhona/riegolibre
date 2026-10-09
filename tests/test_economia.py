import itertools
import unittest

from riegolibre.nucleo import CriteriosRed, DatosBomba, cargar_catalogo_tuberias, dimensionar_red
from riegolibre.nucleo.economia import DatosEconomicos, costos_red, optimizar_red
from riegolibre.nucleo.red import punto_bomba
from tests.test_red import red_en_y


def precios_de(tuberias):
    """Precio por metro creciente con el diámetro y la clase."""
    return {t.nombre: 0.0012 * t.diametro_nominal_mm ** 2 * (1 + 0.3 * (t.presion_nominal_m / 50 - 1))
            for t in tuberias}


class PruebasEconomia(unittest.TestCase):
    def setUp(self):
        self.catalogo = cargar_catalogo_tuberias(uso="principal")
        self.precios = precios_de(self.catalogo)
        self.criterios = CriteriosRed()

    def test_factor_valor_presente(self):
        self.assertAlmostEqual(DatosEconomicos(vida_util_anios=20, tasa_interes=0.10).factor_valor_presente,
                               8.513564, places=5)
        self.assertEqual(DatosEconomicos(vida_util_anios=15, tasa_interes=0.0).factor_valor_presente, 15.0)

    def test_costos(self):
        red = red_en_y()
        resultado = dimensionar_red(red, self.catalogo, self.criterios)
        datos, economicos = DatosBomba(), DatosEconomicos(precio_energia_kwh=0.2, horas_bombeo_anio=1000)
        costos = costos_red(resultado, self.precios, datos, economicos)
        tuberia = sum(self.precios[resultado.asignacion[t.id].nombre] * t.longitud_m for t in red.tramos)
        self.assertAlmostEqual(costos.tuberia, tuberia)
        # Dos turnos: 500 h cada uno, cada uno con su potencia.
        kwh = sum(punto_bomba(r, datos).potencia_kw / 0.9 * 500 for r in resultado.turnos)
        self.assertAlmostEqual(costos.energia_kwh_anual, kwh)
        self.assertAlmostEqual(costos.energia_anual, 0.2 * kwh)
        self.assertAlmostEqual(costos.total, tuberia + 0.2 * kwh * economicos.factor_valor_presente)
        self.assertEqual(costos.sin_precio, [])
        sin_uno = dict(self.precios)
        del sin_uno[resultado.asignacion["FA"].nombre]
        self.assertEqual(costos_red(resultado, sin_uno, datos, economicos).sin_precio,
                         [resultado.asignacion["FA"].nombre])

    def test_energia_gratis_mantiene_el_diseno_por_velocidad(self):
        r = optimizar_red(red_en_y(), self.catalogo, self.precios, self.criterios,
                          economicos=DatosEconomicos(precio_energia_kwh=0.0))
        self.assertEqual(r.tramos_cambiados, [])
        self.assertAlmostEqual(r.ahorro, 0.0)

    def test_energia_cara_agranda_los_diametros(self):
        r = optimizar_red(red_en_y(), self.catalogo, self.precios, self.criterios,
                          economicos=DatosEconomicos(precio_energia_kwh=0.5, horas_bombeo_anio=4000))
        self.assertTrue(r.tramos_cambiados)
        self.assertGreater(r.ahorro, 0)
        self.assertGreater(r.costos.tuberia, r.costos_referencia.tuberia)
        self.assertLess(r.costos.energia_anual, r.costos_referencia.energia_anual)
        self.assertEqual(r.resultado.motivos, {})
        for i in r.tramos_cambiados:
            self.assertGreater(r.resultado.asignacion[i].diametro_nominal_mm,
                               r.referencia.asignacion[i].diametro_nominal_mm)

    def test_coincide_con_la_busqueda_exhaustiva(self):
        por_dn = {}
        for t in self.catalogo:
            por_dn.setdefault(t.diametro_nominal_mm, []).append(t)
        datos = DatosBomba()
        for turno_v2, precio, cambiados in ((1, 0.5, 1), (2, 1.0, 2)):
            red = red_en_y(turno_v2=turno_v2)
            economicos = DatosEconomicos(precio_energia_kwh=precio, horas_bombeo_anio=5000)
            r = optimizar_red(red, self.catalogo, self.precios, self.criterios, datos, economicos)
            self.assertGreaterEqual(len(r.tramos_cambiados), cambiados)
            mejor = None
            for combinacion in itertools.product(sorted(por_dn), repeat=len(red.tramos)):
                restriccion = {t.id: por_dn[d] for t, d in zip(red.tramos, combinacion)}
                resultado = dimensionar_red(red, self.catalogo, self.criterios,
                                            candidatas_por_tramo=restriccion)
                if resultado.motivos:
                    continue
                costo = costos_red(resultado, self.precios, datos, economicos).total
                mejor = costo if mejor is None else min(mejor, costo)
            self.assertAlmostEqual(r.costos.total, mejor, places=6)

    def test_solo_tuberias_con_precio(self):
        precios = {n: p for n, p in self.precios.items() if "C-5" in n}
        r = optimizar_red(red_en_y(), self.catalogo, precios, self.criterios)
        self.assertTrue(all("C-5" in t.nombre for t in r.resultado.asignacion.values()))
        with self.assertRaisesRegex(ValueError, "precio"):
            optimizar_red(red_en_y(), self.catalogo, {}, self.criterios)


if __name__ == "__main__":
    unittest.main()
