"""Pruebas de la ventana de la base de datos y de la elección de laterales con gotero (requieren QGIS)."""

import os
import tempfile
import unittest
from unittest import mock

from riegolibre.nucleo.base_datos import VARIABLE_RUTA, base_activa
from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis
from tests.test_mdb import JET3


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasBaseDatosQgis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()

    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        parche = mock.patch.dict(os.environ, {VARIABLE_RUTA: os.path.join(carpeta.name, "base_datos.json")})
        parche.start()
        self.addCleanup(parche.stop)

    def _importar(self):
        from riegolibre.gui.dialogo_base_datos import DialogoBaseDatos
        dialogo = DialogoBaseDatos(iface=None)
        avisos = []
        dialogo.base_cambiada.connect(lambda: avisos.append(True))
        resultado = dialogo.importar(JET3)
        return dialogo, resultado, avisos

    def test_ventana_sin_base(self):
        from riegolibre.gui.dialogo_base_datos import DialogoBaseDatos
        dialogo = DialogoBaseDatos(iface=None)
        self.assertEqual(dialogo.pestanas.tabText(0), "Tuberías (0)")
        self.assertFalse(dialogo.boton_generico.isEnabled())

    def test_importar_desde_la_ventana(self):
        dialogo, resultado, avisos = self._importar()
        self.assertEqual(avisos, [True])
        self.assertIsNotNone(base_activa())
        self.assertEqual([dialogo.pestanas.tabText(i) for i in range(4)],
                         ["Tuberías (4)", "Laterales con gotero (2)", "Válvulas (2)", "Otros hidráulicos (3)"])
        self.assertEqual(dialogo.tabla_tuberias.item(0, 2).text(), "PE")
        self.assertTrue(dialogo.boton_generico.isEnabled())
        self.assertIn("Pumps (bombas): 1 registros", dialogo._informe(resultado))

    def test_editar_duplicar_y_eliminar(self):
        from qgis.PyQt.QtWidgets import QMessageBox
        from riegolibre.gui.dialogo_base_datos import DialogoRegistro
        dialogo, _, avisos = self._importar()
        dialogo.pestanas.setCurrentIndex(2)  # válvulas
        tabla = dialogo.tabla_valvulas

        tabla.selectRow(0)
        antes = len(avisos)
        dialogo.duplicar_seleccion()
        self.assertEqual(len(base_activa().valvulas), 3)
        self.assertEqual(sum("(copia)" in v.nombre for v in base_activa().valvulas), 1)
        self.assertEqual(len(avisos), antes + 1)

        # editar el primer registro con el formulario
        formulario = DialogoRegistro("valvulas", base_activa().valvulas[0], base_activa())
        formulario.controles["precio"].setText("12,5")
        formulario.controles["seleccionable"].setChecked(False)
        formulario.controles["caudal_max_m3h"].setText("")
        formulario.accept()
        self.assertIsNotNone(formulario.registro)
        self.assertEqual((formulario.registro.precio, formulario.registro.seleccionable,
                          formulario.registro.caudal_max_m3h), (12.5, False, None))

        # número mal escrito y nombre repetido: no se acepta
        formulario = DialogoRegistro("valvulas", base_activa().valvulas[0], base_activa())
        formulario.controles["k"].setText("abc")
        formulario.accept()
        self.assertIsNone(formulario.registro)
        self.assertIn("no es un número", formulario.etiqueta_error.text())
        formulario = DialogoRegistro("valvulas", base_activa().valvulas[0], base_activa())
        formulario.controles["nombre"].setText(base_activa().valvulas[1].nombre)
        formulario.accept()
        self.assertIsNone(formulario.registro)

        # guardar la edición y borrar
        def aceptar(self):
            self.controles["precio"].setText("99")
            DialogoRegistro.accept(self)
            return True
        tabla.selectRow(0)
        nombre = base_activa().valvulas[0].nombre
        with mock.patch.object(DialogoRegistro, "exec", aceptar):
            dialogo.editar()
        self.assertEqual(base_activa().valvulas[0].precio, 99.0)
        self.assertEqual(base_activa().valvulas[0].nombre, nombre)
        self.assertEqual(len(base_activa().valvulas), 3)
        tabla.selectRow(0)
        with mock.patch("riegolibre.gui.dialogo_base_datos.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes):
            dialogo.eliminar()
        self.assertEqual(len(base_activa().valvulas), 2)

    def test_agregar_sin_base_la_crea(self):
        from riegolibre.gui.dialogo_base_datos import DialogoBaseDatos, DialogoRegistro
        self.assertIsNone(base_activa())
        dialogo = DialogoBaseDatos(iface=None)
        dialogo.pestanas.setCurrentIndex(3)

        def aceptar(self):
            self.controles["nombre"].setText("Filtro de malla 120")
            self.controles["k"].setText("0.0005")
            self.controles["precio"].setText("80")
            DialogoRegistro.accept(self)
            return True
        with mock.patch.object(DialogoRegistro, "exec", aceptar):
            dialogo.agregar()
        base = base_activa()
        self.assertEqual([h.nombre for h in base.hidraulicos], ["Filtro de malla 120"])
        self.assertEqual(base.origen, "Creada en RiegoLibre")
        self.assertEqual(dialogo.pestanas.tabText(3), "Otros hidráulicos (1)")

    def test_buscar(self):
        dialogo, _, _ = self._importar()
        dialogo.pestanas.setCurrentIndex(3)
        dialogo.edit_buscar.setText("hidro")
        tabla = dialogo.tabla_hidraulicos
        visibles = [tabla.item(f, 0).text() for f in range(tabla.rowCount()) if not tabla.isRowHidden(f)]
        self.assertEqual(visibles, ["Hidrociclón", "Hidrociclón (2)"])

    def test_elegir_un_lateral_con_gotero_fija_emisor_y_espaciamiento(self):
        self._importar()
        from riegolibre.gui.comunes import GrupoLaterales
        from riegolibre.nucleo import cargar_catalogo_emisores, cargar_catalogo_tuberias
        grupo = GrupoLaterales(cargar_catalogo_tuberias(uso="lateral"), cargar_catalogo_emisores())
        nombres = [t.nombre for t in grupo.tuberias]
        grupo.combo_tuberia.setCurrentIndex(nombres.index("Gotero PC 2.0 l/h @0.5m 16mm"))
        self.assertEqual(grupo.emisor().nombre, "Gotero PC 2.0 l/h @0.5m 16mm")
        self.assertEqual(grupo.spin_espaciamiento.value(), 0.5)
        self.assertFalse(grupo.combo_emisor.isEnabled())

        grupo.combo_tuberia.setCurrentIndex(nombres.index("16 mm LDPE Manguera"))
        self.assertTrue(grupo.combo_emisor.isEnabled())
        self.assertNotIn(grupo.emisor().nombre, nombres)  # vuelve a un emisor suelto

    def test_calculadora_de_lateral_con_la_base(self):
        self._importar()
        from riegolibre.gui.dialogo_lateral import DialogoLateral
        dialogo = DialogoLateral(iface=None)
        self.assertEqual(dialogo.tuberia().nombre, "Cinta 1.0 l/h @0.2m 16mm")
        self.assertEqual(dialogo.emisor().nombre, "Cinta 1.0 l/h @0.2m 16mm")
        self.assertEqual(dialogo.spin_espaciamiento.value(), 0.2)


if __name__ == "__main__":
    unittest.main()
