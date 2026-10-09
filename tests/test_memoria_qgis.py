"""Pruebas de la memoria de cálculo con resultados reales en el proyecto (requieren QGIS)."""

import json
import os
import tempfile
import unittest
import zipfile

from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis
from tests.test_mapa_qgis import BLOQUE, PORTALATERAL, _capa
from tests.test_precios import LISTA

if HAY_QGIS:
    from qgis.core import QgsProject, QgsSettings
    from qgis.PyQt.QtGui import QImage


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasMemoriaQgis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        from riegolibre.gui.dialogo_memoria import AJUSTE_PROYECTISTA
        from riegolibre.integracion.materiales_mapa import (AJUSTE_DESPERDICIO, AJUSTE_LISTA,
                                                            AJUSTE_MONEDA)
        # No tocar los ajustes reales del usuario.
        claves = (AJUSTE_LISTA, AJUSTE_MONEDA, AJUSTE_DESPERDICIO, AJUSTE_PROYECTISTA)
        cls.ajustes_originales = {k: QgsSettings().value(k) for k in claves}
        QgsProject.instance().clear()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta_lista = os.path.join(cls.carpeta.name, "precios.csv")
        with open(ruta_lista, "w", encoding="utf-8") as archivo:
            archivo.write(LISTA + "\n".join(
                f"9{dn},PVC PIPE UF {dn}mm C-5 x 6 METERS,,{dn / 10:.2f}" for dn in (75, 90, 110, 160)))
        QgsSettings().setValue(AJUSTE_LISTA, ruta_lista)
        QgsSettings().setValue(AJUSTE_MONEDA, "USD")
        QgsSettings().setValue(AJUSTE_DESPERDICIO, 5)

        from riegolibre.gui.dialogo_mapa import DialogoMapa
        cls.bloque = _capa("Polygon", BLOQUE, "bloque")
        porta = _capa("LineString", PORTALATERAL, "porta")
        QgsProject.instance().addMapLayers([cls.bloque, porta])
        mapa = DialogoMapa(iface=None)
        mapa.combo_bloque.setLayer(cls.bloque)
        mapa.combo_portalateral.setLayer(porta)
        mapa.spin_separacion.setValue(1.5)
        mapa.spin_margen.setValue(0.5)
        mapa.edit_nombre.setText("Lote Norte")
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

    def test_resumen_guardado_en_la_capa(self):
        from riegolibre.integracion.memoria_mapa import resumenes_del_proyecto
        subunidades, red, avisos = resumenes_del_proyecto()
        self.assertEqual((len(subunidades), red, avisos), (1, None, []))
        s = subunidades[0]
        self.assertEqual(s["nombre"], "Lote Norte")
        self.assertAlmostEqual(s["resultados"]["presion_entrada_m"], self.diseno.resultado.presion_entrada_m, places=3)
        self.assertEqual(s["lateral"]["numero"], 134)
        self.assertAlmostEqual(s["lateral"]["longitud_total_m"], 134 * 22.5, places=2)
        self.assertAlmostEqual(s["area_m2"], 100 * 46, places=2)
        self.assertIn("Sin DEM: se calculó con el terreno plano.", s["avisos"])

    def test_resultado_sin_resumen(self):
        from riegolibre.integracion.memoria_mapa import PROPIEDAD_RESUMEN, resumenes_del_proyecto
        valvula = QgsProject.instance().mapLayersByName("Válvula · Lote Norte")[0]
        guardado = valvula.customProperty(PROPIEDAD_RESUMEN)
        valvula.removeCustomProperty(PROPIEDAD_RESUMEN)
        try:
            subunidades, _red, avisos = resumenes_del_proyecto()
        finally:
            valvula.setCustomProperty(PROPIEDAD_RESUMEN, guardado)
        self.assertEqual(subunidades, [])
        self.assertIn("vuelva a calcularla", avisos[0])

    def test_plano(self):
        from riegolibre.integracion.memoria_mapa import imagen_mapa
        datos = imagen_mapa(ancho_px=900)
        self.assertTrue(datos.startswith(b"\x89PNG"))
        imagen = QImage.fromData(datos, "PNG")
        self.assertEqual(imagen.width(), 900)
        # Algo se dibujó: no toda la imagen es blanca.
        colores = {imagen.pixel(x, y) for x in range(0, 900, 15) for y in range(0, imagen.height(), 15)}
        self.assertGreater(len(colores), 2)

    def test_exportar(self):
        from riegolibre.gui.dialogo_memoria import ENTRADA_MEMORIA, DialogoMemoria
        dialogo = DialogoMemoria(iface=None)
        dialogo.edit_cliente.setText("Agrícola Prueba")
        rutas = {ext: dialogo.exportar(os.path.join(self.carpeta.name, f"memoria.{ext}"))
                 for ext in ("pdf", "odt", "html")}
        self.assertIn("1 subunidades", dialogo.etiqueta_estado.text())
        self.assertIn("presupuesto con", dialogo.etiqueta_estado.text())
        self.assertEqual(set(dialogo.imagenes), {"mapa", "subunidad_0"})

        with open(rutas["pdf"], "rb") as archivo:
            pdf = archivo.read()
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 20000)

        with zipfile.ZipFile(rutas["odt"]) as odt:
            contenido = odt.read("content.xml").decode("utf-8")
            imagenes = [n for n in odt.namelist() if n.startswith("Pictures/")]
        self.assertIn("Agrícola Prueba", contenido)
        self.assertIn("Lote Norte", contenido)
        self.assertEqual(len(imagenes), 2)

        with open(rutas["html"], encoding="utf-8") as archivo:
            pagina = archivo.read()
        self.assertEqual(pagina.count("data:image/png;base64,"), 2)
        self.assertIn("Presupuesto de materiales", pagina)

        # Los datos del documento quedan guardados en el proyecto.
        texto, _ok = QgsProject.instance().readEntry(*ENTRADA_MEMORIA, "{}")
        self.assertEqual(json.loads(texto)["cliente"], "Agrícola Prueba")
        otro = DialogoMemoria(iface=None)
        self.assertEqual(otro.edit_cliente.text(), "Agrícola Prueba")


if __name__ == "__main__":
    unittest.main()
