import unittest

from riegolibre.nucleo import (ENTRADA_CENTRO, ENTRADA_EXTREMO, CriteriosDiseno, Emisor,
                               Lateral, Tuberia, cargar_catalogo_tuberias,
                               evaluar_diametros, subunidad_rectangular)
from riegolibre.nucleo.tuberias import clave_economica

PE16 = Tuberia("PE 16", 13.6)
PVC63 = Tuberia("PVC 63", 59.8, material="PVC", c_hazen=150)
NO_COMP = Emisor("2 L/h", 2.0, 10.0, exponente=0.5, cv=0.05)
COMP = Emisor("2 L/h PC", 2.0, 10.0, exponente=0.0, cv=0.03, autocompensado=True,
              presion_min_m=5.0, presion_max_m=40.0)


def laterales(emisor=NO_COMP, n=150, pendiente=0.0):
    a = Lateral(PE16, emisor, 0.3, n, pendiente=pendiente)
    b = Lateral(PE16, emisor, 0.3, n, pendiente=-pendiente)
    return a, b


class PruebasSubunidad(unittest.TestCase):
    def test_curva_aproxima_al_detalle(self):
        a, b = laterales()
        sub = subunidad_rectangular(PVC63, a, b, 1.5, 40, pendiente=0.01)
        rapido = sub.simular(15.0, detallado=False)
        exacto = sub.simular(15.0, detallado=True)
        self.assertAlmostEqual(rapido.caudal_total_lh / exacto.caudal_total_lh, 1.0, delta=0.002)
        self.assertAlmostEqual(rapido.caudal_min_lh, exacto.caudal_min_lh, delta=0.005)
        self.assertAlmostEqual(rapido.presion_min_emisor_m, exacto.presion_min_emisor_m, delta=0.05)
        self.assertAlmostEqual(rapido.uniformidad_emision, exacto.uniformidad_emision, delta=0.2)
        self.assertAlmostEqual(min(exacto.presiones_emisores_m), exacto.presion_min_emisor_m, places=9)

    def test_entrada_central_simetrica(self):
        a, b = laterales()
        sub = subunidad_rectangular(PVC63, a, b, 1.5, 40, posicion_entrada=ENTRADA_CENTRO)
        self.assertEqual(len(sub.ramas), 2)
        self.assertEqual(sub.numero_emisores, 2 * 150 * 40)
        r = sub.presion_entrada_requerida()
        izquierda, derecha = r.ramas
        self.assertAlmostEqual(izquierda.caudal_total_lh, derecha.caudal_total_lh, delta=0.5)
        self.assertAlmostEqual(r.caudal_medio_lh, 2.0, delta=0.005)

    def test_entrada_central_numero_impar(self):
        a, b = laterales(n=50)
        sub = subunidad_rectangular(PVC63, a, b, 1.5, 7, posicion_entrada=ENTRADA_CENTRO)
        conexiones = sum(len(rama.conexiones) for rama in sub.ramas)
        self.assertEqual(conexiones, 7)

    def test_entrada_central_reduce_perdidas(self):
        a, b = laterales()
        pvc50 = Tuberia("PVC 50", 46.0, material="PVC", c_hazen=150)
        extremo = subunidad_rectangular(pvc50, a, b, 1.5, 60).presion_entrada_requerida(detallado=False)
        centro = subunidad_rectangular(pvc50, a, b, 1.5, 60, posicion_entrada=ENTRADA_CENTRO
                                       ).presion_entrada_requerida(detallado=False)
        self.assertLess(centro.perdida_friccion_max_m, extremo.perdida_friccion_max_m / 4)
        self.assertLess(centro.variacion_caudal, extremo.variacion_caudal)

    def test_entrada_central_en_pendiente(self):
        # Rama en subida y rama en bajada: con autocompensados la presión la fija la de subida.
        a, b = laterales(COMP)
        sub = subunidad_rectangular(PVC63, a, b, 1.5, 40, posicion_entrada=ENTRADA_CENTRO,
                                    pendiente=0.02)
        r = sub.presion_entrada_requerida()
        subida, bajada = r.ramas
        self.assertAlmostEqual(min(r.presiones_emisores_m), 5.0, delta=0.05)
        self.assertLess(subida.presion_min_emisor_m, bajada.presion_min_emisor_m)
        self.assertEqual(r.emisores_fuera_de_rango, 0)

    def test_perfil_central_equivale_a_pendiente(self):
        a, b = laterales()
        perfil = [(0.0, 300.0), (60.0, 301.2)]  # 2 % de subida en 60 m
        con_perfil = subunidad_rectangular(PVC63, a, b, 1.5, 40, posicion_entrada=ENTRADA_CENTRO,
                                           perfil=perfil).simular(15.0, detallado=False)
        con_pendiente = subunidad_rectangular(PVC63, a, b, 1.5, 40, posicion_entrada=ENTRADA_CENTRO,
                                              pendiente=0.02).simular(15.0, detallado=False)
        self.assertAlmostEqual(con_perfil.caudal_total_lh, con_pendiente.caudal_total_lh, delta=0.5)

    def test_seleccion_de_diametro(self):
        a, b = laterales()
        candidatas = cargar_catalogo_tuberias(uso="portalateral")
        criterios = CriteriosDiseno(variacion_caudal_max=0.15, velocidad_max_ms=2.0)

        def construir(tuberia):
            return subunidad_rectangular(tuberia, a, b, 1.5, 60)

        evaluaciones, elegida = evaluar_diametros(construir, candidatas, criterios)
        self.assertIsNotNone(elegida)
        self.assertTrue(evaluaciones[elegida].cumple)
        self.assertEqual([e.tuberia for e in evaluaciones], sorted(candidatas, key=clave_economica))
        # Entre tubos del mismo diámetro nominal se prefiere la clase más baja (C-5).
        self.assertIn("C-5", evaluaciones[elegida].tuberia.nombre)
        for e in evaluaciones[:elegida]:
            self.assertFalse(e.cumple)
            self.assertTrue(e.motivos)

    def test_sin_diametro_que_cumpla(self):
        a, b = laterales(n=300)  # laterales demasiado largos: no hay portalateral que lo arregle
        evaluaciones, elegida = evaluar_diametros(
            lambda t: subunidad_rectangular(t, a, b, 1.5, 10), [PVC63], CriteriosDiseno(0.10))
        self.assertIsNone(elegida)
        self.assertIn("variación de caudal", evaluaciones[0].motivos[0])

    def test_disenar_sugiere_cuando_fallan_los_laterales(self):
        from riegolibre.nucleo import disenar_subunidad
        a, b = laterales(n=300)
        diseno = disenar_subunidad(lambda t: subunidad_rectangular(t, a, b, 1.5, 10), [PVC63],
                                   CriteriosDiseno(0.10))
        self.assertIs(diseno.tuberia, PVC63)
        self.assertTrue(diseno.automatica)
        self.assertIn("autocompensados", diseno.avisos[-1])
        self.assertIsNotNone(diseno.resultado.laterales)  # cálculo detallado

    def test_un_solo_lado(self):
        a, _ = laterales()
        sub = subunidad_rectangular(PVC63, a, None, 1.5, 20, posicion_entrada=ENTRADA_EXTREMO)
        self.assertEqual(sub.numero_emisores, 150 * 20)


if __name__ == "__main__":
    unittest.main()
