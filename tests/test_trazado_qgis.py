"""Pruebas del trazado automático en el mapa (requieren el Python de QGIS)."""

import math
import os
import tempfile
import unittest

from tests.test_integracion_qgis import (HAY_QGIS, PENDIENTE_ESTE, X0, Y0, _crear_dem,
                                         _iniciar_qgis)

if HAY_QGIS:
    from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
                           QgsVectorLayer)

# Terreno en «L» de 100 × 46 m dentro del DEM (que sube 2 % hacia el este).
TERRENO_L = [(10, -48), (110, -48), (110, -25), (60, -25), (60, -2), (10, -2)]
RECTANGULO = [(10, -48), (110, -48), (110, -2), (10, -2)]


def _punto(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _capa_poligono(puntos, nombre, huecos=()):
    capa = QgsVectorLayer("Polygon?crs=EPSG:32718", nombre, "memory")
    entidad = QgsFeature()
    entidad.setGeometry(QgsGeometry.fromPolygonXY(
        [[_punto(*p) for p in puntos]] + [[_punto(*p) for p in h] for h in huecos]))
    capa.dataProvider().addFeatures([entidad])
    capa.updateExtents()
    return capa


def _capa_punto(x, y, nombre):
    capa = QgsVectorLayer("Point?crs=EPSG:32718", nombre, "memory")
    entidad = QgsFeature()
    entidad.setGeometry(QgsGeometry.fromPointXY(_punto(x, y)))
    capa.dataProvider().addFeatures([entidad])
    capa.updateExtents()
    return capa


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasUtilidades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta_dem = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta_dem)
        cls.dem = QgsRasterLayer(ruta_dem, "dem")

    @classmethod
    def tearDownClass(cls):
        cls.dem = None
        cls.carpeta.cleanup()

    def test_anillos_con_hueco_y_multipoligono(self):
        from riegolibre.integracion.trazado_mapa import anillos_de_geometria
        hueco = [(30, -30), (50, -30), (50, -10), (30, -10)]
        capa = _capa_poligono(RECTANGULO, "t", [hueco])
        anillos = anillos_de_geometria(next(capa.getFeatures()).geometry())
        self.assertEqual([len(a) for a in anillos], [4, 4])  # sin repetir el primer vértice
        multi = QgsGeometry.fromMultiPolygonXY([
            [[_punto(*p) for p in RECTANGULO]], [[_punto(*p) for p in [(120, -40), (130, -40), (130, -30)]]]])
        self.assertEqual(len(anillos_de_geometria(multi)), 2)
        with self.assertRaises(ValueError):
            anillos_de_geometria(QgsGeometry.fromPointXY(_punto(0, 0)))

    def test_gradiente_del_terreno(self):
        from riegolibre.integracion.trazado_mapa import gradiente_del_terreno, pendiente_a_lo_largo
        capa = _capa_poligono(TERRENO_L, "t")
        geometria = next(capa.getFeatures()).geometry()
        gx, gy = gradiente_del_terreno(geometria, self.dem, capa.crs())
        self.assertAlmostEqual(gx, PENDIENTE_ESTE, delta=0.001)
        self.assertAlmostEqual(gy, 0.0, delta=0.001)
        self.assertAlmostEqual(pendiente_a_lo_largo((gx, gy), 0), PENDIENTE_ESTE, delta=0.001)
        self.assertAlmostEqual(pendiente_a_lo_largo((gx, gy), 90), 0.0, delta=0.001)
        self.assertEqual(pendiente_a_lo_largo(None, 30), 0.0)

    def test_gradiente_fuera_del_dem(self):
        from riegolibre.integracion.trazado_mapa import gradiente_del_terreno
        lejos = QgsGeometry.fromPolygonXY([[_punto(1000, 0), _punto(1100, 0), _punto(1100, 50)]])
        self.assertIsNone(gradiente_del_terreno(lejos, self.dem, self.dem.crs()))

    def test_orientaciones_siguen_las_curvas_de_nivel_y_descartan_las_imposibles(self):
        from riegolibre.integracion.trazado_mapa import construir_orientaciones
        anillos = [[(0, 0), (100, 0), (100, 50), (0, 50)]]
        orientaciones = construir_orientaciones(anillos, (0.02, 0.0), lambda pendiente: 60 - 1000 * pendiente)
        por_angulo = {round(o.angulo_deg): o for o in orientaciones}
        self.assertAlmostEqual(por_angulo[90].pendiente, 0.0, places=6)  # curvas de nivel: lateral a nivel
        self.assertAlmostEqual(por_angulo[90].longitud_max_m, 60.0)
        self.assertAlmostEqual(por_angulo[0].pendiente, 0.02, places=6)
        self.assertAlmostEqual(por_angulo[0].longitud_max_m, 40.0)
        # Donde el alcance es cero no se puede tender el lateral.
        solo_a_nivel = construir_orientaciones(anillos, (0.02, 0.0), lambda p: 60.0 if p < 0.01 else 0.0)
        self.assertTrue(all(o.pendiente < 0.01 for o in solo_a_nivel))
        with self.assertRaises(ValueError):
            construir_orientaciones(anillos, None, lambda p: 0.0)

    def test_funcion_caudal_cuenta_emisores(self):
        from riegolibre.integracion.trazado_mapa import funcion_caudal
        from riegolibre.nucleo import cargar_catalogo_emisores
        emisor = cargar_catalogo_emisores()[0]
        caudal = funcion_caudal(emisor, 0.3, 0.3)
        self.assertEqual(caudal(0.1), 0.0)
        self.assertAlmostEqual(caudal(0.3), emisor.caudal_nominal_lh)
        self.assertAlmostEqual(caudal(3.0), 10 * emisor.caudal_nominal_lh)


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasDialogoTrazado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta_dem = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta_dem)
        cls.dem = QgsRasterLayer(ruta_dem, "dem")
        cls.terreno = _capa_poligono(TERRENO_L, "terreno")
        cls.rectangulo = _capa_poligono(RECTANGULO, "rectangulo")
        cls.fuente = _capa_punto(5, -25, "fuente")
        QgsProject.instance().addMapLayers([cls.dem, cls.terreno, cls.rectangulo, cls.fuente])

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def _dialogo(self, capa=None, nombre="Parcela", con_dem=True):
        from riegolibre.gui.dialogo_trazado import DialogoTrazado
        dialogo = DialogoTrazado(iface=None)
        dialogo.edit_nombre.setText(nombre)
        dialogo.combo_terreno.setLayer(capa or self.terreno)
        if con_dem:
            dialogo.combo_dem.setLayer(self.dem)
        dialogo.spin_separacion.setValue(1.5)
        return dialogo

    def _capas_del_grupo(self, nombre):
        grupo = QgsProject.instance().layerTreeRoot().findGroup(nombre)
        self.assertIsNotNone(grupo, nombre)
        return {nodo.layer().name().split(" · ")[0]: nodo.layer() for nodo in grupo.findLayers()}

    def test_busca_y_prefiere_laterales_a_nivel(self):
        dialogo = self._dialogo(nombre="Busqueda")
        dialogo.buscar()
        self.assertGreaterEqual(len(dialogo.trazados), 2)
        mejor = dialogo.trazados[0]
        # El DEM sube hacia el este: los laterales norte-sur (azimut 0) van a nivel.
        self.assertAlmostEqual(mejor.azimut_laterales_grados % 180, 0.0, delta=1.0)
        self.assertAlmostEqual(mejor.orientacion.pendiente, 0.0, delta=0.002)
        self.assertLess(mejor.fraccion_sin_cubrir, 0.1)
        self.assertEqual(dialogo.tabla.rowCount(), len(dialogo.trazados))
        self.assertTrue(dialogo.boton_aplicar.isEnabled())
        # La vista previa del trazado elegido está en el mapa.
        grupo = QgsProject.instance().layerTreeRoot().findGroup("RiegoLibre · Vista previa del trazado · Busqueda")
        self.assertIsNotNone(grupo)
        capas = {n.layer().name(): n.layer() for n in grupo.findLayers()}
        laterales = next(c for nombre, c in capas.items() if nombre.startswith("Laterales"))
        self.assertEqual(laterales.featureCount(), sum(len(s.laterales) for s in mejor.subunidades))

    def test_aplicar_crea_capas_y_calcula_cada_subunidad(self):
        dialogo = self._dialogo(nombre="Aplicada")
        dialogo.buscar()
        trazado = dialogo.trazados[0]
        dialogo.aplicar()

        capas = self._capas_del_grupo("Trazado · Aplicada")
        total_laterales = sum(len(s.laterales) for s in trazado.subunidades)
        self.assertEqual(capas["Laterales"].featureCount(), total_laterales)
        self.assertEqual(capas["Portalaterales"].featureCount(), trazado.numero_subunidades)
        self.assertEqual(capas["Bloques"].featureCount(), trazado.numero_subunidades)
        # El bloque de cada subunidad es la franja de sus laterales.
        for entidad, s in zip(sorted(capas["Bloques"].getFeatures(), key=lambda f: f["subunidad"]),
                              trazado.subunidades):
            self.assertAlmostEqual(entidad["area_m2"], s.longitud_laterales_m * trazado.separacion_m, delta=2.0)

        valvulas = 0
        for s in trazado.subunidades:
            resultado = self._capas_del_grupo(f"RiegoLibre · Aplicada {s.numero}")
            self.assertEqual(resultado["Laterales"].featureCount(), len(s.laterales))
            valvula = next(resultado["Válvula"].getFeatures())
            self.assertGreater(valvula["presion"], 0)
            self.assertGreater(valvula["caudal_lh"], 0)
            # El caudal calculado coincide con el que se usó para partir el terreno.
            self.assertAlmostEqual(valvula["caudal_lh"], s.caudal, delta=0.02 * s.caudal)
            valvulas += 1
        self.assertEqual(valvulas, trazado.numero_subunidades)
        self.assertIn("Trazado aplicado", dialogo.texto.toPlainText())

    def test_el_resultado_coincide_con_el_calculo_manual_de_la_misma_subunidad(self):
        from riegolibre.gui.dialogo_mapa import DialogoMapa
        dialogo = self._dialogo(self.rectangulo, nombre="Igual")
        dialogo.buscar()
        dialogo.aplicar()
        capas = self._capas_del_grupo("Trazado · Igual")
        resultado = self._capas_del_grupo("RiegoLibre · Igual 1")
        valvula_auto = next(resultado["Válvula"].getFeatures())

        # La misma subunidad dibujada a mano (capas del trazado como si fueran las dibujadas).
        manual = DialogoMapa(iface=None)
        manual.edit_nombre.setText("Manual")
        manual.combo_bloque.setLayer(capas["Bloques"])
        manual.combo_portalateral.setLayer(capas["Portalaterales"])
        manual.combo_laterales.setLayer(capas["Laterales"])
        manual.combo_dem.setLayer(self.dem)
        manual.combo_entrada.setCurrentIndex(manual.combo_entrada.findData(dialogo.combo_entrada.currentData()))
        for capa in (capas["Bloques"], capas["Portalaterales"], capas["Laterales"]):
            capa.selectByExpression('"subunidad" = 1')
        manual.calcular()
        valvula_manual = next(self._capas_del_grupo("RiegoLibre · Manual")["Válvula"].getFeatures())
        self.assertAlmostEqual(valvula_auto["presion"], valvula_manual["presion"], places=3)
        self.assertAlmostEqual(valvula_auto["caudal_lh"], valvula_manual["caudal_lh"], places=1)

    def test_caudal_maximo_parte_en_mas_subunidades_y_el_nombre_se_reemplaza(self):
        dialogo = self._dialogo(self.rectangulo, nombre="Partida", con_dem=False)
        dialogo.combo_alcance.setCurrentIndex(1)  # longitud fija
        dialogo.spin_alcance.setValue(80)
        dialogo.buscar()
        sin_limite = dialogo.trazados[0].numero_subunidades
        caudal_total = sum(s.caudal for s in dialogo.trazados[0].subunidades)
        dialogo.spin_caudal_max.setValue(caudal_total / 1000 / 3)  # m³/h: al menos tres válvulas
        dialogo.buscar()
        mejor = dialogo.trazados[0]
        self.assertGreaterEqual(mejor.numero_subunidades, 3)
        self.assertGreater(mejor.numero_subunidades, sin_limite)
        self.assertTrue(all(s.caudal <= caudal_total / 3 * 1.0001 for s in mejor.subunidades))
        dialogo.aplicar()
        # Aplicar de nuevo con otro caudal reemplaza los grupos anteriores (no quedan subunidades viejas).
        dialogo.spin_caudal_max.setValue(0)
        dialogo.buscar()
        dialogo.aplicar()
        raiz = QgsProject.instance().layerTreeRoot()
        nombres = [g.name() for g in raiz.children() if g.name().startswith("RiegoLibre · Partida ")]
        self.assertEqual(len(nombres), dialogo.trazados[0].numero_subunidades)
        self.assertEqual(len([g for g in raiz.children() if g.name() == "Trazado · Partida"]), 1)

    def test_la_fuente_orienta_la_entrada_de_cada_portalateral(self):
        dialogo = self._dialogo(self.rectangulo, nombre="Fuente", con_dem=False)
        dialogo.combo_alcance.setCurrentIndex(1)
        dialogo.spin_alcance.setValue(80)
        dialogo.combo_fuente.setLayer(self.fuente)
        self.assertEqual(dialogo.combo_entrada.currentData(), "inicio")
        dialogo.buscar()
        fuente = (X0 + 5, Y0 - 25)
        for s in dialogo.trazados[0].subunidades:
            inicio, fin = s.portalateral
            self.assertLessEqual(math.dist(fuente, inicio), math.dist(fuente, fin) + 1e-6)

    def test_emisores_opcionales(self):
        dialogo = self._dialogo(self.rectangulo, nombre="ConEmisores", con_dem=False)
        dialogo.combo_alcance.setCurrentIndex(1)
        dialogo.spin_alcance.setValue(80)
        dialogo.check_emisores.setChecked(True)
        dialogo.buscar()
        dialogo.aplicar()
        capas = self._capas_del_grupo("Trazado · ConEmisores")
        from riegolibre.integracion.trazado_mapa import cantidad_de_emisores
        esperado = cantidad_de_emisores(dialogo.trazados[0], dialogo.grupo_laterales.spin_espaciamiento.value(),
                                        dialogo.grupo_laterales.spin_primer.value())
        self.assertEqual(capas["Emisores"].featureCount(), esperado)

    def test_errores_se_muestran_sin_romper(self):
        from qgis.PyQt.QtWidgets import QMessageBox
        dialogo = self._dialogo(nombre="Errores")
        mensajes = []
        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: mensajes.append(args[2]))
        try:
            dialogo.combo_terreno.setLayer(None)
            dialogo.buscar()
            self.assertIn("Elija la capa del terreno", mensajes[-1])
            self.assertFalse(dialogo.boton_aplicar.isEnabled())
        finally:
            QMessageBox.warning = original


if __name__ == "__main__":
    unittest.main()
