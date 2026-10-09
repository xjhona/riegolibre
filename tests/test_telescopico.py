import unittest

from riegolibre.nucleo import (ENTRADA_CENTRO, CriteriosDiseno, Tuberia, cargar_catalogo_tuberias,
                               disenar_subunidad, incumplimientos, subunidad_rectangular)
from riegolibre.nucleo.hidraulica import LH_A_M3S
from riegolibre.nucleo.portalateral import ConexionLateral, Portalateral
from riegolibre.nucleo.subunidad import costo_relativo, telescopizar
from riegolibre.nucleo.tuberias import clave_economica
from tests.test_subunidad import COMP, NO_COMP, laterales

PVC90 = Tuberia("PVC 90", 85.6, material="PVC", diametro_nominal_mm=90, presion_nominal_m=50)
PVC63 = Tuberia("PVC 63", 59.8, material="PVC", diametro_nominal_mm=63, presion_nominal_m=50)
PVC50 = Tuberia("PVC 50", 46.0, material="PVC", diametro_nominal_mm=50, presion_nominal_m=50)


class PruebasPortalateralTelescopico(unittest.TestCase):
    def test_perdidas_por_tramo(self):
        a, _ = laterales(n=100)
        conexiones = [ConexionLateral(1.5 * (i + 1), [a]) for i in range(40)]  # 1.5 … 60 m
        telescopico = Portalateral(PVC90, conexiones, reducciones=[(30.0, PVC63)])
        self.assertIs(telescopico.tuberia_en(10.0), PVC90)
        self.assertIs(telescopico.tuberia_en(30.0), PVC63)
        self.assertEqual([t.nombre for t in telescopico.tuberias], ["PVC 90", "PVC 63"])
        r = telescopico.simular_desde_final(10.0, con_secciones=True)
        # Pérdida a mano: cada tramo con la tubería que le corresponde.
        perdida, acumulado = 0.0, 0.0
        distancias = r.distancias_m
        for i in range(len(distancias) - 1, -1, -1):
            if i < len(distancias) - 1:
                tuberia = PVC90 if distancias[i + 1] <= 30.0 + 1e-9 else PVC63
                perdida += tuberia.perdida(acumulado * LH_A_M3S, distancias[i + 1] - distancias[i])
            acumulado += r.caudales_lh[i]
        perdida += PVC90.perdida(acumulado * LH_A_M3S, distancias[0])
        self.assertAlmostEqual(r.perdida_friccion_m, perdida, places=9)
        # Más pérdida que el uniforme de 90 mm y menos que el de 63 mm.
        uniforme90 = Portalateral(PVC90, conexiones).simular_desde_final(10.0)
        uniforme63 = Portalateral(PVC63, conexiones).simular_desde_final(10.0)
        self.assertGreater(r.perdida_friccion_m, uniforme90.perdida_friccion_m)
        self.assertLess(r.perdida_friccion_m, uniforme63.perdida_friccion_m)
        # Dos secciones; la velocidad máxima de la de 63 mm es la de su caudal de entrada.
        s90, s63 = r.secciones
        self.assertEqual((s90.desde_m, s90.hasta_m, s63.desde_m, s63.hasta_m), (0.0, 30.0, 30.0, 60.0))
        q63 = sum(q for d, q in zip(distancias, r.caudales_lh) if d > 30.0)
        self.assertAlmostEqual(s63.velocidad_max_ms, PVC63.velocidad(q63 * LH_A_M3S))
        self.assertAlmostEqual(s90.presion_max_m, r.presion_entrada_m)
        self.assertAlmostEqual(r.velocidad_max_ms, max(s90.velocidad_max_ms, s63.velocidad_max_ms))

    def test_reduccion_entre_conexiones(self):
        a, _ = laterales(n=100)
        conexiones = [ConexionLateral(10.0 * (i + 1), [a]) for i in range(4)]  # 10 … 40 m
        r = Portalateral(PVC90, conexiones, reducciones=[(25.0, PVC50)]).simular_desde_final(
            10.0, con_secciones=True)
        self.assertEqual([(s.desde_m, s.hasta_m) for s in r.secciones], [(0.0, 25.0), (25.0, 40.0)])
        q = [sum(r.caudales_lh[i:]) * LH_A_M3S for i in range(4)]  # caudal que llega a cada conexión
        esperado = (PVC90.perdida(q[0], 10.0) + PVC90.perdida(q[1], 10.0)
                    + PVC90.perdida(q[2], 5.0) + PVC50.perdida(q[2], 5.0)  # el tramo de 20 a 30 m
                    + PVC50.perdida(q[3], 10.0))
        self.assertAlmostEqual(r.perdida_friccion_m, esperado, places=9)

    def test_presion_nominal_por_tramo(self):
        debil = Tuberia("PE 50 débil", 46.0, diametro_nominal_mm=50, presion_nominal_m=8)
        a, b = laterales(n=100)
        sub = subunidad_rectangular(PVC90, a, b, 1.5, 40, reducciones=[(30.0, debil)])
        r = sub.simular(12.0, detallado=False)
        motivos = incumplimientos(r, CriteriosDiseno(0.5, 3.0), PVC90)
        self.assertEqual(motivos, ["supera la presión nominal de PE 50 débil (8 m)"])


class PruebasDisenoTelescopico(unittest.TestCase):
    def setUp(self):
        self.tuberias = sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica)
        self.criterios = CriteriosDiseno(0.10, 1.5)

    def _disenar(self, emisor, entrada="extremo", diametros_max=3, n=100):
        a, b = laterales(emisor, n=n)

        def construir(tuberia, reducciones=()):
            return subunidad_rectangular(tuberia, a, b, 1.5, 80, posicion_entrada=entrada, pendiente=0.005,
                                         reducciones=reducciones)
        uniforme = disenar_subunidad(lambda t: construir(t), self.tuberias, self.criterios)
        return uniforme, disenar_subunidad(construir, self.tuberias, self.criterios,
                                           diametros_max=diametros_max), construir

    def _verificar(self, uniforme, telescopico, diametros_max):
        self.assertIs(telescopico.tuberia, uniforme.tuberia)  # la entrada no cambia
        self.assertTrue(telescopico.telescopico)
        self.assertLessEqual(len(telescopico.reducciones) + 1, diametros_max)
        diametros = [uniforme.tuberia.diametro_nominal_mm] + [t.diametro_nominal_mm
                                                              for _, t in telescopico.reducciones]
        self.assertEqual(diametros, sorted(diametros, reverse=True))
        self.assertEqual(len(set(diametros)), len(diametros))
        r = telescopico.resultado
        self.assertEqual(incumplimientos(r, self.criterios, telescopico.tuberia), [])
        self.assertLessEqual(r.velocidad_max_ms, 1.5 + 1e-9)
        # Menos material que el portalateral uniforme.
        material = sum(costo_relativo(s.tuberia) * s.longitud_m for s in r.secciones)
        uniforme_material = sum(costo_relativo(s.tuberia) * s.longitud_m for s in uniforme.resultado.secciones)
        self.assertLess(material, uniforme_material)

    def test_no_compensado_en_extremo(self):
        uniforme, telescopico, _ = self._disenar(NO_COMP)
        self._verificar(uniforme, telescopico, 3)
        # Aprovecha la variación de caudal admisible que el uniforme dejaba libre.
        self.assertGreater(telescopico.resultado.variacion_caudal, uniforme.resultado.variacion_caudal)

    def test_autocompensado_en_el_centro(self):
        uniforme, telescopico, _ = self._disenar(COMP, ENTRADA_CENTRO, n=150)
        self._verificar(uniforme, telescopico, 3)
        self.assertEqual(len(telescopico.resultado.ramas), 2)
        self.assertEqual(len(telescopico.resultado.secciones), 2 * (len(telescopico.reducciones) + 1))

    def test_dos_diametros(self):
        uniforme, telescopico, _ = self._disenar(NO_COMP, diametros_max=2)
        self._verificar(uniforme, telescopico, 2)
        self.assertEqual(len(telescopico.reducciones), 1)

    def test_punto_de_cambio_es_el_mas_cercano_que_cumple(self):
        uniforme, telescopico, construir = self._disenar(NO_COMP, diametros_max=2)
        (distancia, menor), = telescopico.reducciones
        conexiones = sorted({c.distancia_m for rama in construir(uniforme.tuberia).ramas for c in rama.conexiones})
        anterior = max(d for d in conexiones if d < distancia - 1e-9)
        r = construir(uniforme.tuberia, [(anterior, menor)]).presion_entrada_requerida(detallado=False)
        self.assertTrue(incumplimientos(r, self.criterios, uniforme.tuberia))

    def test_sin_reduccion_posible(self):
        # Con un solo diámetro en el catálogo no hay nada que reducir.
        a, b = laterales(n=100)
        solo = [t for t in self.tuberias if t.diametro_nominal_mm == 110]
        diseno = disenar_subunidad(lambda t, r=(): subunidad_rectangular(t, a, b, 1.5, 80, reducciones=r),
                                   solo, self.criterios, diametros_max=3)
        self.assertEqual(diseno.reducciones, [])
        self.assertFalse(diseno.telescopico)

    def test_uniforme_sin_cambios(self):
        uniforme, _, _ = self._disenar(NO_COMP)
        self.assertEqual(uniforme.reducciones, [])
        self.assertEqual(len(uniforme.resultado.secciones), 1)
        self.assertEqual(telescopizar(lambda t, r: subunidad_rectangular(t, *laterales(n=100), 1.5, 80,
                                                                         reducciones=r),
                                      uniforme.tuberia, self.tuberias, self.criterios, diametros_max=1), [])


if __name__ == "__main__":
    unittest.main()
