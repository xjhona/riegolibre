# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana de la calculadora de lateral de aspersión (requiere QGIS)."""

import unittest

from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis


@unittest.skipUnless(HAY_QGIS, "QGIS no disponible")
class PruebasDialogoAspersion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def _dialogo(self):
        from riegolibre.gui.dialogo_aspersion import DialogoAspersion
        dialogo = DialogoAspersion(iface=None)
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_solo_tuberias_de_aspersion(self):
        dialogo = self._dialogo()
        self.assertTrue(dialogo.tuberias)
        diametros = [t.diametro_interior_mm for t in dialogo.tuberias]
        self.assertTrue(all(d >= 25 for d in diametros))
        self.assertEqual(diametros, sorted(diametros))
        self.assertGreaterEqual(dialogo.tuberia().diametro_interior_mm, 35)
        self.assertGreater(len(dialogo.aspersores), 0)
        self.assertIn("m³/h", dialogo.etiqueta_aspersor.text())

    def test_calcular(self):
        dialogo = self._dialogo()
        dialogo.spin_se.setValue(12)
        self.assertEqual(dialogo.spin_primer.value(), 6)  # medio espaciamiento
        dialogo.spin_numero.setValue(5)
        dialogo.spin_lamina.setValue(30)
        r = dialogo.calcular()
        self.assertIsNotNone(r)
        self.assertEqual(r.numero_aspersores, 5)
        self.assertAlmostEqual(r.caudal_medio_m3h, dialogo.aspersor().caudal_nominal_m3h, places=3)
        # La entrada lleva la presión nominal más el elevador (0.6 m) y algo de fricción
        self.assertGreater(r.presion_entrada_m, dialogo.aspersor().presion_nominal_m + 0.6)
        texto = dialogo.texto.toPlainText()
        self.assertIn("Pluviometría media", texto)
        self.assertIn("tiempo de riego", texto)

    def test_numero_maximo(self):
        dialogo = self._dialogo()
        r = dialogo.calcular_maximo()
        self.assertIsNotNone(r)
        self.assertEqual(dialogo.spin_numero.value(), r.numero_aspersores)
        self.assertLessEqual(r.variacion_presion, 0.20 + 1e-9)
        self.assertIn("Número máximo", dialogo.texto.toPlainText())


if __name__ == "__main__":
    unittest.main()
