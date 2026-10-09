import json
import unittest

from riegolibre.nucleo import (CriteriosDiseno, CriteriosRed, DatosBomba, cargar_catalogo_tuberias,
                               dimensionar_red, disenar_subunidad, punto_bomba,
                               subunidad_rectangular)
from riegolibre.nucleo.materiales import Partida, total
from riegolibre.nucleo.memoria import (DatosMemoria, Presupuesto, graficos_memoria, memoria_html,
                                       potencia_comercial_hp, resumen_red, resumen_subunidad)
from riegolibre.nucleo.precios import Articulo
from riegolibre.nucleo.tuberias import clave_economica
from tests.test_red import red_en_y
from tests.test_subunidad import COMP, laterales

try:
    import matplotlib  # noqa: F401
    HAY_MATPLOTLIB = True
except ImportError:
    HAY_MATPLOTLIB = False


def _subunidad():
    a, b = laterales(COMP, n=100)
    tuberias = sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica)
    criterios = CriteriosDiseno(0.10, 1.5)
    diseno = disenar_subunidad(lambda t: subunidad_rectangular(t, a, b, 1.5, 30), tuberias, criterios)
    return diseno, criterios


def _red():
    red = red_en_y()
    resultado = dimensionar_red(red, cargar_catalogo_tuberias(uso="principal"), CriteriosRed())
    bombas = [punto_bomba(r, DatosBomba()) for r in resultado.turnos]
    return red, resultado, bombas


class PruebasResumenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.diseno, cls.criterios = _subunidad()
        cls.sub = resumen_subunidad("Bloque 1", cls.diseno, cls.criterios, "darcy", area_m2=2700.0,
                                    avisos=["Sin DEM: se calculó con el terreno plano."])
        cls.red, cls.resultado, cls.bombas = _red()
        cls.resumen_red = resumen_red(cls.red, cls.resultado, cls.bombas, DatosBomba())

    def test_resumen_subunidad(self):
        s, r = self.sub, self.diseno.resultado
        self.assertEqual(json.loads(json.dumps(s)), s)  # se puede guardar como JSON
        self.assertEqual(s["lateral"]["numero"], 60)
        self.assertEqual(s["resultados"]["numero_emisores"], r.numero_emisores)
        self.assertAlmostEqual(s["resultados"]["caudal_lh"], r.caudal_total_lh, places=1)
        self.assertAlmostEqual(s["resultados"]["presion_entrada_m"], r.presion_entrada_m, places=3)
        self.assertAlmostEqual(s["portalateral"]["longitud_m"], 0.75 + 29 * 1.5)
        elegidas = [e for e in s["evaluaciones"] if e["elegida"]]
        self.assertEqual([e["tuberia"] for e in elegidas], [self.diseno.tuberia.nombre])
        self.assertTrue(s["cumple"])
        self.assertEqual(s["referencia"], [5.0, "Inicio de compensación"])
        self.assertIn("Sin DEM: se calculó con el terreno plano.", s["avisos"])
        self.assertEqual(len(s["perfil"]), 30)

    def test_resumen_red_y_bomba(self):
        s = self.resumen_red
        self.assertEqual(json.loads(json.dumps(s)), s)
        critica = max(self.bombas, key=lambda b: b.carga_dinamica_total_m)
        self.assertAlmostEqual(s["bomba"]["cdt_m"], critica.carga_dinamica_total_m, places=3)
        self.assertEqual(s["bomba"]["critico"], "válvula v1")
        self.assertEqual([t["turno"] for t in s["turnos"]], [1, 2])
        self.assertEqual(s["turnos"][0]["valvulas"], ["v1"])
        self.assertEqual(len(s["tramos"]), 3)
        # La ruta crítica llega a la válvula v1 justo con la carga que necesita.
        perfil = s["perfil"]
        self.assertEqual(perfil["valvula"], "v1")
        self.assertAlmostEqual(perfil["distancias_m"][-1], 300.0)
        self.assertAlmostEqual(perfil["piezometrica_m"][-1], perfil["carga_requerida_m"], places=2)
        self.assertGreaterEqual(s["bomba"]["potencia_comercial_hp"], s["bomba"]["potencia_hp"] * 1.1)

    def test_potencia_comercial(self):
        self.assertEqual(potencia_comercial_hp(2.0), 3)  # 2.2 HP con el margen
        self.assertEqual(potencia_comercial_hp(0.1), 0.5)
        self.assertEqual(potencia_comercial_hp(4.5, margen=0.0), 5)
        self.assertIsNone(potencia_comercial_hp(1000))

    def _datos(self, **cambios):
        tubo = Articulo("1", "PVC PIPE UF 63mm C-5 x 6 METERS", "", 4.87, 6.0)
        partidas = [Partida("Red principal", "Tubería PVC 63 mm C-5", 100.0, "m", "tuberia:x", tubo),
                    Partida("Válvulas y equipos", "Válvula de subunidad", 1, "und", "valvula_subunidad")]
        valores = dict(proyecto="Fundo Prueba", cliente="Agrícola A & B <SAC>", fecha="09/10/2026",
                       subunidades=[self.sub], red=self.resumen_red,
                       presupuesto=Presupuesto(partidas, 0.05, "USD", "precios.csv"),
                       notas="Primera línea\nSegunda línea", version="0.2.0")
        valores.update(cambios)
        return DatosMemoria(**valores)

    def test_documento_html(self):
        datos = self._datos()
        texto = memoria_html(datos)
        for esperado in ("1. Resumen del proyecto", "Bases de cálculo", "Subunidades de riego", "Bloque 1",
                         "Selección del diámetro del portalateral", "Red principal de conducción",
                         "Equipo de bombeo", "Presupuesto de materiales", "Observaciones",
                         "Primera línea<br>Segunda línea", "RiegoLibre 0.2.0", "Darcy-Weisbach",
                         f"{total(datos.presupuesto.partidas, 0.05):,.2f}", "sin precio"):
            self.assertIn(esperado, texto)
        self.assertIn("Agrícola A &amp; B &lt;SAC&gt;", texto)  # los textos del usuario se escapan
        self.assertNotIn("<SAC>", texto)
        self.assertNotIn("Hazen-Williams:", texto)  # solo las fórmulas usadas
        self.assertNotIn("Plano general", texto)  # sin imagen del mapa
        self.assertIn("1 partidas sin precio", texto)

    def test_documento_parcial_e_imagenes(self):
        datos = self._datos(red=None, presupuesto=None, notas="")
        texto = memoria_html(datos, {"mapa": "mapa.png", "subunidad_0": "s0.png"})
        self.assertIn("2. Plano general", texto)
        self.assertIn("src='mapa.png'", texto)
        self.assertIn("src='s0.png'", texto)
        for ausente in ("Equipo de bombeo", "Presupuesto de materiales", "Observaciones"):
            self.assertNotIn(ausente, texto)

    @unittest.skipUnless(HAY_MATPLOTLIB, "requiere matplotlib")
    def test_graficos(self):
        imagenes = graficos_memoria(self._datos())
        self.assertEqual(set(imagenes), {"subunidad_0", "red_perfil"})
        for imagen in imagenes.values():
            self.assertTrue(imagen.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
