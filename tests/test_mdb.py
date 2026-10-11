"""Pruebas del lector de bases de Access (.mdb) en Python puro.

Las bases de prueba se generan con tests/datos/generar_mdb.ps1 (datos ficticios).
"""

import datetime
import os
import tempfile
import unittest

from riegolibre.nucleo.mdb import BaseAccess, ErrorMdb

DATOS = os.path.join(os.path.dirname(__file__), "datos")
JET3 = os.path.join(DATOS, "irricad_jet3.mdb")
JET4 = os.path.join(DATOS, "irricad_jet4.mdb")


class _PruebasLector:
    ruta = None
    jet3 = None

    @classmethod
    def setUpClass(cls):
        cls.base = BaseAccess(cls.ruta)

    def test_formato(self):
        self.assertEqual(self.base.formato.jet3, self.jet3)

    def test_tablas_de_usuario(self):
        self.assertEqual(sorted(self.base.tablas()), ["Components", "Tapes", "Tipos"])

    def test_filas_borradas_no_aparecen(self):
        claves = sorted(f["Component Key"] for f in self.base.filas("Components"))
        self.assertEqual(claves, [1, 10, 11, 12, 13, 20, 21, 30, 31, 40, 41, 42, 50])

    def test_textos_con_tildes_y_simbolos(self):
        nombres = {f["Component Key"]: f["Description"] for f in self.base.filas("Components")}
        self.assertEqual(nombres[11], '1½" C-10 PVC Caño')
        self.assertEqual(nombres[30], 'Válvula 2" Prueba')
        self.assertEqual(nombres[50], "Codo 90° 63 mm")

    def test_numeros_de_precision_simple(self):
        fila = next(f for f in self.base.filas("Components") if f["Component Key"] == 10)
        self.assertEqual(fila["Reals7"], 0.719)  # como lo muestra Access, sin 0.71899998
        self.assertEqual(fila["Reals2"], 58.4)
        valvula = next(f for f in self.base.filas("Components") if f["Component Key"] == 30)
        self.assertEqual(valvula["Reals3"], 0.00387828)
        self.assertEqual(valvula["Database Number"], 2)

    def test_columnas_nulas(self):
        fila = next(f for f in self.base.filas("Components") if f["Component Key"] == 10)
        self.assertIsNone(fila["Item Type"])
        self.assertIsNone(fila["Flags"])

    def test_tipos_de_columna(self):
        filas = sorted(self.base.filas("Tipos"), key=lambda f: f["Id"])
        self.assertEqual(len(filas), 4)
        primera = filas[0]
        self.assertTrue(primera["Texto"].startswith("Riego por goteo con eñe y tilde á."))
        self.assertEqual(len(primera["Texto"]), 240)
        self.assertEqual(primera["Nota"], "Memo corto")
        self.assertEqual(primera["Fecha"], datetime.datetime(2026, 10, 11, 8, 30))
        self.assertIs(primera["Si"], True)
        self.assertAlmostEqual(primera["Dinero"], 1234.5678)
        self.assertAlmostEqual(primera["Doble"], 3.14159265358979)
        self.assertEqual(primera["Corto"], -12)
        self.assertEqual(primera["Octeto"], 200)
        self.assertIsNone(primera["Agregada"])  # columna creada después de esta fila

    def test_fila_vacia(self):
        fila = sorted(self.base.filas("Tipos"), key=lambda f: f["Id"])[1]
        self.assertIsNone(fila["Texto"])
        self.assertIsNone(fila["Nota"])
        self.assertIs(fila["Si"], False)

    def test_memos_en_otras_paginas(self):
        filas = sorted(self.base.filas("Tipos"), key=lambda f: f["Id"])
        self.assertEqual(filas[2]["Nota"], "0123456789" * 1000)  # repartido en varias páginas
        self.assertEqual(filas[3]["Nota"], "abcdefghij" * 150)
        self.assertEqual(filas[3]["Agregada"], 42)

    def test_tabla_inexistente(self):
        with self.assertRaises(KeyError):
            self.base.filas("NoExiste")


class PruebasJet3(_PruebasLector, unittest.TestCase):
    ruta, jet3 = JET3, True


class PruebasJet4(_PruebasLector, unittest.TestCase):
    ruta, jet3 = JET4, False


class PruebasArchivoInvalido(unittest.TestCase):
    def test_no_es_access(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "falso.mdb")
            with open(ruta, "wb") as archivo:
                archivo.write(b"esto no es una base de datos" * 200)
            with self.assertRaises(ErrorMdb):
                BaseAccess(ruta)


if __name__ == "__main__":
    unittest.main()
