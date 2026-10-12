"""Pruebas del dimensionado del portalateral por velocidad (motor de Python puro)."""

import math
import unittest

from riegolibre.nucleo import (ConexionLateral, CriteriosDiseno, Emisor, Lateral, Tuberia,
                               subunidad_desde_conexiones)
from riegolibre.nucleo.diametros_velocidad import (CriterioVelocidad, dimensionar_rama, disenar_por_velocidad,
                                                   ramas_de, serie_por_defecto, series_de_tuberias)
from riegolibre.nucleo.memoria import descripcion_telescopico

SERIE = [Tuberia(f"PVC {d} C-5", di, material="PVC", usos=["portalateral"], diametro_nominal_mm=d,
                 c_hazen=150, presion_nominal_m=50)
         for d, di in ((40, 37.2), (50, 46.4), (63, 59.0), (75, 70.6), (90, 84.6), (110, 103.6))]
PE16 = Tuberia("PE 16", 13.6)
NO_COMP = Emisor("2 L/h", 2.0, 10.0, exponente=0.5, cv=0.05)


def velocidad(tuberia, caudal_lh):
    return tuberia.velocidad(caudal_lh / 3.6e6)


def tuberia_en(rama, distancia):
    tubo = rama.tuberia
    for d, t in rama.reducciones:
        if distancia >= d - 1e-9:
            tubo = t
    return tubo


class PruebasRama(unittest.TestCase):
    def setUp(self):
        self.distancias = [10.0 * (k + 1) for k in range(10)]
        self.caudales = [3600.0] * 10  # 1 L/s por conexión: de 10 L/s en la válvula a 1 L/s al final

    def comprobar_velocidades(self, rama, vmax):
        for k, d in enumerate(self.distancias):
            tubo = tuberia_en(rama, d - 10.0 + 1e-6)  # tramo de d-10 a d
            self.assertLessEqual(velocidad(tubo, sum(self.caudales[k:])), vmax + 1e-9, (k, tubo.nombre))

    def test_sin_limites_cada_tramo_su_tuberia(self):
        rama = dimensionar_rama(self.distancias, self.caudales, SERIE,
                                CriterioVelocidad(1.5, diametros_max=10, tramo_min_m=0))
        self.comprobar_velocidades(rama, 1.5)
        # La entrada lleva la menor tubería que cumple con 10 L/s
        necesaria = next(t for t in SERIE if velocidad(t, 36000) <= 1.5)
        self.assertIs(rama.tuberia, necesaria)
        self.assertGreater(len(rama.reducciones), 1)
        diametros = [rama.tuberia.diametro_interior_mm] + [t.diametro_interior_mm for _, t in rama.reducciones]
        self.assertEqual(diametros, sorted(diametros, reverse=True))
        self.assertLessEqual(rama.velocidad_max_ms, 1.5)
        self.assertFalse(rama.insuficiente)

    def test_limite_de_diametros_y_tramo_minimo(self):
        dos = dimensionar_rama(self.distancias, self.caudales, SERIE, CriterioVelocidad(1.5, 2, 0))
        self.assertLessEqual(len(dos.reducciones), 1)
        self.comprobar_velocidades(dos, 1.5)
        largo = dimensionar_rama(self.distancias, self.caudales, SERIE, CriterioVelocidad(1.5, 4, 30))
        cortes = [0.0] + [d for d, _ in largo.reducciones] + [100.0]
        self.assertTrue(all(b - a >= 30 - 1e-9 for a, b in zip(cortes, cortes[1:])))
        self.comprobar_velocidades(largo, 1.5)
        uno = dimensionar_rama(self.distancias, self.caudales, SERIE, CriterioVelocidad(1.5, 1, 0))
        self.assertEqual(uno.reducciones, [])

    def test_tramo_minimo_mayor_que_la_rama(self):
        rama = dimensionar_rama([2.0, 4.0], [3600.0, 3600.0], SERIE, CriterioVelocidad(1.5, 3, 6.0))
        self.assertEqual(rama.reducciones, [])

    def test_serie_insuficiente(self):
        rama = dimensionar_rama([10.0], [200000.0], SERIE[:2], CriterioVelocidad(1.5))
        self.assertTrue(rama.insuficiente)
        self.assertIs(rama.tuberia, SERIE[1])

    def test_series(self):
        otra = Tuberia("PE 63 PN4", 57.0, material="PE", diametro_nominal_mm=63, presion_nominal_m=40)
        series = series_de_tuberias(SERIE + [otra])
        self.assertEqual([s.clave for s in series], ["PE|40", "PVC|50"])
        self.assertEqual(len(series[1].tuberias), 6)
        self.assertIn("PVC PN 50 m", series[1].nombre)

    def test_serie_con_todas_las_clases(self):
        # Como la base del usuario: PVC C-5 de 63 a 110 mm y el 1½" solo en C-7.5 (y un 63 C-7.5 que sobra)
        c5 = [t for t in SERIE if t.diametro_nominal_mm >= 63]
        c75 = [Tuberia(f"PVC {d} C-7.5", di, material="PVC", usos=["portalateral"], diametro_nominal_mm=d,
                       c_hazen=150, presion_nominal_m=73) for d, di in ((48, 43.4), (63, 57.0))]
        series = series_de_tuberias(c5 + c75)
        self.assertEqual([s.clave for s in series], ["PVC|*", "PVC|50", "PVC|73"])
        todas = series[0]
        self.assertEqual([t.nombre for t in todas.tuberias],
                         ["PVC 48 C-7.5", "PVC 63 C-5", "PVC 75 C-5", "PVC 90 C-5", "PVC 110 C-5"])
        self.assertIn("la clase más baja", todas.nombre)
        self.assertIs(serie_por_defecto(series), todas)

    def test_diametros_consecutivos_desde_la_entrada(self):
        # La entrada (10 L/s a 1.5 m/s) pide 110 mm y el final (1 L/s) 40 mm
        sin_limite = dimensionar_rama(self.distancias, self.caudales, SERIE,
                                      CriterioVelocidad(1.5, diametros_max=0, tramo_min_m=0))
        usadas = [sin_limite.tuberia] + [t for _, t in sin_limite.reducciones]
        self.assertEqual(usadas[0].diametro_nominal_mm, 110)
        self.assertEqual(usadas[-1].diametro_nominal_mm, 40)  # baja hasta el menor de la serie
        tres = dimensionar_rama(self.distancias, self.caudales, SERIE, CriterioVelocidad(1.5, 3, 0))
        usadas = [tres.tuberia] + [t for _, t in tres.reducciones]
        self.assertEqual([t.diametro_nominal_mm for t in usadas], [110, 90, 75])  # no salta a 63, 50 o 40 mm
        self.comprobar_velocidades(tres, 1.5)


class PruebasSubunidad(unittest.TestCase):
    def conexiones(self, n=30, separacion=3.0, emisores=150):
        lateral = Lateral(PE16, NO_COMP, 0.3, emisores)
        return [ConexionLateral(separacion * k, [lateral, lateral]) for k in range(n)]

    def construir(self, conexiones, entrada):
        def construir(por_rama):
            return subunidad_desde_conexiones(SERIE[0], conexiones, entrada, por_rama=por_rama)
        return construir

    def test_valvula_al_centro_cada_rama_con_sus_diametros(self):
        conexiones = self.conexiones()
        entrada = 30.0  # 11 conexiones hacia el inicio y 19 hacia el final
        ramas = ramas_de(conexiones, entrada)
        self.assertEqual(len(ramas[1]), 20)
        self.assertEqual(len(ramas[-1]), 10)
        diseno = disenar_por_velocidad(self.construir(conexiones, entrada), conexiones, entrada, SERIE,
                                       CriterioVelocidad(1.2, 3, 0, ajustar_variacion=False),
                                       CriteriosDiseno(variacion_caudal_max=0.5, velocidad_max_ms=1.5))
        hacia_final, hacia_inicio = sorted(diseno.subunidad.ramas, key=lambda r: -r.sentido)
        self.assertGreaterEqual(hacia_final.tuberia.diametro_interior_mm, hacia_inicio.tuberia.diametro_interior_mm)
        self.assertIs(diseno.tuberia, hacia_final.tuberia)
        self.assertLessEqual(diseno.resultado.velocidad_max_ms, 1.2 * 1.1)
        self.assertTrue(diseno.telescopico)
        texto = descripcion_telescopico(diseno)
        self.assertIn("hacia el final", texto)
        self.assertIn("hacia el inicio", texto)

    def test_ajuste_por_variacion(self):
        conexiones = self.conexiones(n=40)
        criterios = CriteriosDiseno(variacion_caudal_max=0.10, velocidad_max_ms=3.0)
        sin_ajuste = disenar_por_velocidad(self.construir(conexiones, 0.0), conexiones, 0.0, SERIE,
                                           CriterioVelocidad(2.5, 3, 0, ajustar_variacion=False), criterios)
        con_ajuste = disenar_por_velocidad(self.construir(conexiones, 0.0), conexiones, 0.0, SERIE,
                                           CriterioVelocidad(2.5, 3, 0, ajustar_variacion=True), criterios)
        self.assertGreater(sin_ajuste.resultado.variacion_caudal, 0.10)
        self.assertLessEqual(con_ajuste.resultado.variacion_caudal, 0.10 + 1e-9)
        self.assertGreaterEqual(con_ajuste.tuberia.diametro_interior_mm, sin_ajuste.tuberia.diametro_interior_mm)
        self.assertTrue(any("se dimensionó con" in a for a in con_ajuste.avisos))
        self.assertTrue(math.isfinite(con_ajuste.resultado.presion_entrada_m))


if __name__ == "__main__":
    unittest.main()
