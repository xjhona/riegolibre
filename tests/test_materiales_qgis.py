"""Pruebas de la lista de materiales con resultados reales en el proyecto (requieren QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis
from tests.test_mapa_qgis import BLOQUE, PORTALATERAL, _capa
from tests.test_precios import LISTA

if HAY_QGIS:
    from qgis.core import QgsProject, QgsSettings


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasMaterialesQgis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        from riegolibre.integracion.materiales_mapa import (AJUSTE_DESPERDICIO, AJUSTE_LISTA,
                                                            AJUSTE_MONEDA)
        # No tocar los ajustes reales del usuario.
        cls.ajustes_originales = {k: QgsSettings().value(k)
                                  for k in (AJUSTE_LISTA, AJUSTE_MONEDA, AJUSTE_DESPERDICIO)}
        QgsSettings().remove(AJUSTE_LISTA)
        QgsProject.instance().clear()
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.ruta_lista = os.path.join(cls.carpeta.name, "precios.csv")
        with open(cls.ruta_lista, "w", encoding="utf-8") as archivo:
            archivo.write(LISTA + "\n".join(
                f"9{dn},PVC PIPE UF {dn}mm C-5 x 6 METERS,,{dn / 10:.2f}" for dn in (75, 90, 110, 160, 200, 250)))

        from riegolibre.gui.dialogo_mapa import DialogoMapa
        bloque, porta = _capa("Polygon", BLOQUE, "bloque"), _capa("LineString", PORTALATERAL, "porta")
        QgsProject.instance().addMapLayers([bloque, porta])
        mapa = DialogoMapa(iface=None)
        mapa.combo_bloque.setLayer(bloque)
        mapa.combo_portalateral.setLayer(porta)
        mapa.spin_separacion.setValue(1.5)
        mapa.spin_margen.setValue(0.5)
        mapa.generar_laterales()
        mapa.calcular()
        cls.diseno = mapa.panel.diseno

    @classmethod
    def tearDownClass(cls):
        for clave, valor in cls.ajustes_originales.items():
            if valor is None:
                QgsSettings().remove(clave)
            else:
                QgsSettings().setValue(clave, valor)
        QgsProject.instance().clear()
        cls.carpeta.cleanup()

    def test_metrado_desde_el_proyecto(self):
        from riegolibre.integracion.materiales_mapa import partidas_del_proyecto
        partidas, resumen = partidas_del_proyecto()
        por_material = {(p.categoria, p.material): p for p in partidas}
        lateral = self.diseno.subunidad.laterales[0]
        self.assertEqual(resumen, {"subunidades": 1, "laterales": 134, "red": False, "valvulas": 1})
        self.assertAlmostEqual(por_material[("Laterales", lateral.tuberia.nombre)].cantidad, 134 * 22.5, places=3)
        self.assertEqual(por_material[("Emisores", lateral.emisor.nombre)].cantidad,
                         sum(lat.numero_emisores for lat in self.diseno.subunidad.laterales))
        self.assertEqual(por_material[("Accesorios", f"Conector inicial para {lateral.tuberia.nombre}")].cantidad, 134)
        # El portalateral llega hasta la última conexión: 99.75 m desde la válvula.
        self.assertAlmostEqual(por_material[("Portalaterales", self.diseno.tuberia.nombre)].cantidad, 99.75, places=3)
        self.assertEqual(por_material[("Válvulas y equipos", "Válvula de subunidad")].cantidad, 1)

    def test_dialogo_precios_eleccion_y_exportacion(self):
        import openpyxl
        from riegolibre.gui.dialogo_materiales import DialogoMateriales
        dialogo = DialogoMateriales(iface=None)
        dialogo.cargar_lista(self.ruta_lista, avisar=False)
        partidas = {p.material: p for p in dialogo.partidas}
        porta = partidas[self.diseno.tuberia.nombre]
        self.assertTrue(porta.automatico)
        self.assertIn(f"{self.diseno.tuberia.diametro_nominal_mm:g}mm C-5", porta.articulo.descripcion)
        manguera = partidas[self.diseno.subunidad.laterales[0].tuberia.nombre]
        self.assertEqual(manguera.articulo.codigo, "101039392")

        # Elegir a mano el gotero y comprobar que la elección se recuerda en el proyecto.
        fila = dialogo.partidas.index(partidas[self.diseno.subunidad.laterales[0].emisor.nombre])
        gotero = next(a for a in dialogo.articulos if a.codigo == "101003185")
        dialogo.asignar(fila, gotero)
        otro = DialogoMateriales(iface=None)
        otro.cargar_lista(self.ruta_lista, avisar=False)
        self.assertEqual(next(p for p in otro.partidas if p.clave == dialogo.partidas[fila].clave).articulo.codigo,
                      "101003185")

        esperado = sum(p.costo(dialogo.desperdicio()) or 0 for p in dialogo.partidas)
        self.assertIn(f"{esperado:,.2f}", dialogo.etiqueta_total.text())
        ruta = dialogo.exportar(os.path.join(self.carpeta.name, "materiales.xlsx"))
        with open(ruta, "rb") as archivo:  # openpyxl deja abierto el archivo si recibe la ruta
            filas = list(openpyxl.load_workbook(archivo).active.iter_rows(values_only=True))
        inicio = next(i for i, f in enumerate(filas) if f[0] == "Categoría") + 1
        subtotales = [f[9] for f in filas[inicio:-1] if f[9] is not None]
        self.assertAlmostEqual(sum(subtotales), esperado, places=1)


if __name__ == "__main__":
    unittest.main()
