"""Pruebas de la base de datos de materiales y de la importación desde IRRICAD."""

import os
import tempfile
import unittest
from unittest import mock

from riegolibre.nucleo import Lateral, cargar_catalogo_emisores, cargar_catalogo_tuberias
from riegolibre.nucleo.base_datos import (VARIABLE_RUTA, BaseDatos, base_activa, cargar_base,
                                          cintas_activas, desactivar_base, guardar_base)
from riegolibre.nucleo.emisores import RUTA_CATALOGO as EMISORES_GENERICOS
from riegolibre.nucleo.importar_irricad import importar_irricad
from riegolibre.nucleo.mdb import ErrorMdb
from riegolibre.nucleo.precios import Articulo, candidatos_tuberia
from riegolibre.nucleo.tuberias import RUTA_CATALOGO as TUBERIAS_GENERICAS
from tests.test_mdb import JET3, JET4


class PruebasImportacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resultado = importar_irricad(JET3)
        cls.base = cls.resultado.base

    def _tuberia(self, inicio):
        return next(t for t in self.base.tuberias if t.nombre.startswith(inicio))

    def test_resumen(self):
        self.assertEqual(self.base.resumen(), {"Tuberías": 4, "Laterales con gotero": 2,
                                               "Válvulas": 2, "Otros hidráulicos": 3})
        self.assertEqual(self.resultado.omitidos_por_pestana, {11: 1})  # bombas: aún no se importan
        self.assertEqual(self.resultado.avisos, [])
        self.assertEqual(self.base.origen, "IRRICAD: irricad_jet3.mdb")

    def test_jet4_igual_que_jet3(self):
        self.assertEqual(importar_irricad(JET4).base.resumen(), self.base.resumen())

    def test_tuberia(self):
        t = self._tuberia("63 mm C-7.5")
        self.assertEqual((t.material, t.usos), ("PVC", ["principal"]))
        self.assertEqual((t.diametro_nominal_mm, t.diametro_interior_mm), (63, 58.4))
        self.assertEqual((t.c_hazen, t.presion_nominal_m), (150, 73))
        self.assertEqual((t.etiqueta, t.proveedor, t.costo_m, t.precio_m), ("63/7.5", "SUP1", 0.719, 0.8))

    def test_usos_y_materiales(self):
        self.assertEqual(self._tuberia("1½").usos, ["portalateral", "principal"])
        self.assertEqual(self._tuberia("1½").codigo, "COD-11")
        pead = self._tuberia("110 mm")
        self.assertEqual((pead.material, pead.usos), ("PEAD", []))  # sin uso: no seleccionable
        self.assertEqual(self._tuberia("16 mm LDPE").material, "PE")

    def test_lateral_autocompensado(self):
        cinta = next(c for c in self.base.cintas if c.nombre.startswith("Gotero PC"))
        self.assertTrue(cinta.autocompensado)
        self.assertEqual((cinta.espaciamiento_m, cinta.caudal_nominal_lh, cinta.caudal_por_metro_lhm), (0.5, 2, 4))
        emisor = cinta.emisor()
        self.assertTrue(emisor.autocompensado)
        self.assertEqual(emisor.caudal(15), 2.0)
        self.assertEqual((emisor.presion_min_m, emisor.presion_max_m), (5, 30))  # desde la presión mín. PC
        self.assertEqual((emisor.cv, emisor.longitud_equivalente_m), (0.03, 0.8))
        tuberia = cinta.tuberia()
        self.assertEqual((tuberia.diametro_interior_mm, tuberia.usos, tuberia.material), (13.8, ["lateral"], "Cinta"))

    def test_lateral_no_compensado(self):
        cinta = next(c for c in self.base.cintas if c.nombre.startswith("Cinta 1.0"))
        self.assertFalse(cinta.autocompensado)
        emisor = cinta.emisor()
        self.assertAlmostEqual(emisor.caudal(10), 0.352 * 10 ** 0.45)
        self.assertAlmostEqual(emisor.caudal(6), 0.352 * 6 ** 0.45)
        self.assertEqual(emisor.exponente, 0.45)

    def test_calculo_de_un_lateral_con_cinta(self):
        cinta = next(c for c in self.base.cintas if c.nombre.startswith("Gotero PC"))
        r = Lateral.desde_longitud(cinta.tuberia(), cinta.emisor(), cinta.espaciamiento_m, 100).simular(12)
        self.assertEqual(len(r.caudales_lh), 200)
        self.assertAlmostEqual(r.caudal_total_lh, 400, delta=1e-6)

    def test_valvula(self):
        valvula = self.base.valvulas[0]
        self.assertEqual(valvula.nombre, 'Válvula 2" Prueba')
        self.assertAlmostEqual(valvula.perdida(20), 0.00387828 * 20 ** 2.01454 + 2)
        self.assertEqual(valvula.perdida(0), 0)
        self.assertEqual((valvula.caudal_min_m3h, valvula.caudal_max_m3h), (10, 25))
        self.assertEqual((valvula.conexion_entrada, valvula.etiqueta), ("NPT FY", '2"'))
        self.assertTrue(valvula.fuera_de_rango(30))
        self.assertFalse(self.base.valvulas[1].seleccionable)

    def test_otros_hidraulicos_con_nombres_repetidos(self):
        nombres = [h.nombre for h in self.base.hidraulicos]
        self.assertEqual(nombres, ["Filtro 10 mca", "Hidrociclón", "Hidrociclón (2)"])
        filtro = self.base.hidraulicos[0]
        self.assertEqual(filtro.perdida(500), 10)  # n = 0: pérdida fija
        self.assertEqual(filtro.caudal_max_m3h, 1000)

    def test_archivo_que_no_es_de_irricad(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "otra.mdb")
            with open(ruta, "wb") as archivo:
                archivo.write(b"\0" * 4096)
            with self.assertRaises(ErrorMdb):
                importar_irricad(ruta)


class PruebasBaseActiva(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.carpeta.name, "sub", "base_datos.json")
        parche = mock.patch.dict(os.environ, {VARIABLE_RUTA: self.ruta})
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(self.carpeta.cleanup)
        self.base = importar_irricad(JET3).base

    def test_sin_base_se_usa_el_catalogo_generico(self):
        self.assertIsNone(base_activa())
        self.assertEqual(cargar_catalogo_tuberias(uso="lateral"),
                         cargar_catalogo_tuberias(TUBERIAS_GENERICAS, uso="lateral"))
        self.assertEqual(cargar_catalogo_emisores(), cargar_catalogo_emisores(EMISORES_GENERICOS))
        self.assertEqual(cintas_activas(), {})

    def test_guardar_y_cargar(self):
        guardar_base(self.base, self.ruta)
        self.assertEqual(cargar_base(self.ruta), self.base)

    def test_catalogos_desde_la_base(self):
        guardar_base(self.base, self.ruta)
        laterales = [t.nombre for t in cargar_catalogo_tuberias(uso="lateral")]
        self.assertEqual(laterales, ["Cinta 1.0 l/h @0.2m 16mm", "Gotero PC 2.0 l/h @0.5m 16mm",
                                     "16 mm LDPE Manguera"])
        self.assertEqual([t.nombre for t in cargar_catalogo_tuberias(uso="portalateral")], ['1½" C-10 PVC Caño'])
        self.assertEqual(len(cargar_catalogo_tuberias(uso="principal")), 2)
        emisores = cargar_catalogo_emisores()
        genericos = cargar_catalogo_emisores(EMISORES_GENERICOS)
        self.assertEqual(emisores[:len(genericos)], genericos)
        self.assertEqual([e.nombre for e in emisores[len(genericos):]], laterales[:2])
        self.assertEqual(set(cintas_activas()), set(laterales[:2]))

    def test_todas_incluye_las_genericas_para_proyectos_anteriores(self):
        guardar_base(self.base, self.ruta)
        nombres = {t.nombre for t in cargar_catalogo_tuberias()}
        self.assertIn("110 mm PN6 HDPE Prueba", nombres)
        self.assertTrue({t.nombre for t in cargar_catalogo_tuberias(TUBERIAS_GENERICAS)} <= nombres)

    def test_uso_sin_tuberias_en_la_base(self):
        guardar_base(BaseDatos(cintas=self.base.cintas), self.ruta)
        self.assertEqual(cargar_catalogo_tuberias(uso="principal"),
                         cargar_catalogo_tuberias(TUBERIAS_GENERICAS, uso="principal"))
        self.assertEqual(len(cargar_catalogo_tuberias(uso="lateral")), 2)

    def test_respaldo_y_volver_al_generico(self):
        guardar_base(self.base, self.ruta)
        guardar_base(BaseDatos(), self.ruta)
        self.assertTrue(os.path.exists(self.ruta + ".bak"))
        self.assertEqual(cargar_base(self.ruta + ".bak"), self.base)
        desactivar_base()
        self.assertIsNone(base_activa())
        self.assertFalse(os.path.exists(self.ruta))

    def test_la_cinta_no_se_busca_en_la_lista_de_precios(self):
        cinta = self.base.cintas[0].tuberia()
        articulo = Articulo("1", "MANGUERA CIEGA 16/40 500m", "m", 50.0, None)
        self.assertEqual(candidatos_tuberia(cinta, [articulo]), [])


if __name__ == "__main__":
    unittest.main()
