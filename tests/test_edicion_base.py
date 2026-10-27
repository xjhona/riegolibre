"""Pruebas de la edición de la base de datos de materiales (sin QGIS)."""

import dataclasses
import unittest

from riegolibre.nucleo.base_datos import BaseDatos, Cinta, ElementoHidraulico, RegistroTuberia
from riegolibre.nucleo.edicion_base import (CAMPOS, CLASES, base_nueva, duplicar, eliminar_registros,
                                            guardar_registro, nombre_libre, registro_nuevo, validar)


def _base():
    base = base_nueva()
    base.tuberias.append(RegistroTuberia("PVC 63 C-5", 59.0, "PVC", ["principal"], 63.0))
    base.cintas.append(Cinta("Gotero 2 L/h", 14.0, 2.0, 0.0, 0.5))
    base.valvulas.append(ElementoHidraulico("Válvula 2\"", k=0.0012, n=2.0))
    return base


class PruebasEdicionBase(unittest.TestCase):
    def test_los_campos_existen_en_los_registros(self):
        for categoria, campos in CAMPOS.items():
            nombres = {f.name for f in dataclasses.fields(CLASES[categoria])}
            self.assertLessEqual({c.nombre for c in campos}, nombres, categoria)
            self.assertEqual(len({c.nombre for c in campos}), len(campos), categoria)

    def test_registros_nuevos_piden_los_datos_obligatorios(self):
        base = base_nueva()
        for categoria in ("tuberias", "cintas"):
            nuevo = registro_nuevo(categoria, base)
            self.assertTrue(validar(base, categoria, nuevo), categoria)  # incompleto a propósito

    def test_registros_buenos(self):
        base = _base()
        for categoria in ("tuberias", "cintas", "valvulas"):
            self.assertEqual(validar(base, categoria, getattr(base, categoria)[0],
                                     getattr(base, categoria)[0]), [], categoria)

    def test_nombre_repetido_solo_al_agregar(self):
        base = _base()
        copia = dataclasses.replace(base.tuberias[0])
        self.assertIn("Ya existe «PVC 63 C-5» en esta pestaña.", validar(base, "tuberias", copia))
        self.assertEqual(validar(base, "tuberias", copia, original=base.tuberias[0]), [])
        copia.nombre = "pvc 63 c-5"  # sin distinguir mayúsculas
        self.assertTrue(validar(base, "tuberias", copia))

    def test_errores_de_datos(self):
        base = _base()
        cinta = dataclasses.replace(base.cintas[0], nombre="X", espaciamiento_m=0.0, k_emisor=-1.0)
        errores = validar(base, "cintas", cinta)
        self.assertIn("El espaciamiento de emisores debe ser mayor que cero.", errores)
        self.assertIn("La k del emisor debe ser mayor que cero.", errores)
        valvula = dataclasses.replace(base.valvulas[0], nombre="Y", caudal_min_m3h=10.0, caudal_max_m3h=5.0)
        self.assertEqual(validar(base, "valvulas", valvula), ["El caudal mínimo es mayor que el máximo."])
        valvula = dataclasses.replace(valvula, caudal_min_m3h=None, caudal_max_m3h=None, n=-1.0)
        self.assertEqual(validar(base, "valvulas", valvula), ["«n (exponente)» no puede ser negativo."])

    def test_duplicar_da_nombre_nuevo(self):
        base = _base()
        copia = duplicar(base, "tuberias", base.tuberias[0])
        self.assertEqual(copia.nombre, "PVC 63 C-5 (copia)")
        self.assertIsNot(copia.usos, base.tuberias[0].usos)  # copia profunda
        guardar_registro(base, "tuberias", copia)
        self.assertEqual(duplicar(base, "tuberias", base.tuberias[0]).nombre, "PVC 63 C-5 (copia) (2)")
        self.assertEqual(nombre_libre(base, "valvulas", "Otra"), "Otra")

    def test_guardar_reemplaza_en_su_lugar(self):
        base = _base()
        original = base.tuberias[0]
        editada = dataclasses.replace(original, precio_m=1.5)
        guardar_registro(base, "tuberias", editada, original=original)
        self.assertEqual(len(base.tuberias), 1)
        self.assertEqual(base.tuberias[0].precio_m, 1.5)

    def test_eliminar(self):
        base = _base()
        base.valvulas.append(ElementoHidraulico("V2", k=1.0))
        self.assertEqual(eliminar_registros(base, "valvulas", [base.valvulas[0]]), 1)
        self.assertEqual([v.nombre for v in base.valvulas], ["V2"])


if __name__ == "__main__":
    unittest.main()
