"""Pruebas de la información de objetos del mapa (requieren el Python de QGIS)."""

import json
import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _crear_dem, _iniciar_qgis
from tests.test_red_qgis import (FUENTE, PRINCIPAL, RAMA, VALVULAS, _capa_lineas, _capa_punto,
                                 _p)

if HAY_QGIS:
    from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsRasterLayer, QgsVectorLayer

BLOQUE = [(10, -48), (110, -48), (110, -2), (10, -2)]
PORTALATERAL = [(10, -25), (110, -25)]


def _capa_poligono_o_linea(tipo, puntos, nombre):
    capa = QgsVectorLayer(f"{tipo}?crs=EPSG:32718", nombre, "memory")
    entidad = QgsFeature()
    if tipo == "Polygon":
        entidad.setGeometry(QgsGeometry.fromPolygonXY([[_p(*q) for q in puntos]]))
    else:
        entidad.setGeometry(QgsGeometry.fromPolylineXY([_p(*q) for q in puntos]))
    capa.dataProvider().addFeatures([entidad])
    capa.updateExtents()
    return capa


def _hijas(nombre_grupo):
    grupo = QgsProject.instance().layerTreeRoot().findGroup(nombre_grupo)
    return {n.layer().name().split(" · ")[0]: n.layer() for n in grupo.findLayers()}


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasInfoSubunidad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        QgsProject.instance().removeAllMapLayers()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta)
        cls.dem = QgsRasterLayer(ruta, "dem")
        cls.bloque = _capa_poligono_o_linea("Polygon", BLOQUE, "bloque")
        cls.porta = _capa_poligono_o_linea("LineString", PORTALATERAL, "portalateral")
        QgsProject.instance().addMapLayers([cls.dem, cls.bloque, cls.porta])

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def _calcular(self, nombre, entrada=0):
        from riegolibre.gui.dialogo_mapa import DialogoMapa
        from riegolibre.gui.dialogo_trazado import eliminar_grupos
        eliminar_grupos(r"RiegoLibre · .*")  # resultados de las pruebas anteriores
        dialogo = DialogoMapa(iface=None)
        dialogo.edit_nombre.setText(nombre)
        dialogo.combo_bloque.setLayer(self.bloque)
        dialogo.combo_portalateral.setLayer(self.porta)
        dialogo.spin_separacion.setValue(1.5)
        dialogo.spin_margen.setValue(0.5)
        dialogo.generar_laterales()
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.combo_entrada.setCurrentIndex(entrada)
        dialogo.calcular()
        return dialogo, _hijas(f"RiegoLibre · {nombre}")

    def test_laterales_guardan_presion_final_perdida_y_desnivel(self):
        dialogo, capas = self._calcular("InfoLat")
        resultado = dialogo.panel.resultado
        esperados = {round(r.presion_entrada_m, 3): r for c in resultado.laterales for r in c}
        n = 0
        for f in capas["Laterales"].getFeatures():
            self.assertAlmostEqual(f["p_entrada"] - f["p_final"], f["perdida_m"] + f["desnivel_m"], delta=0.0035)
            self.assertGreater(f["perdida_m"], 0)
            self.assertGreater(f["velocidad"], 0)
            r = esperados[round(f["p_entrada"], 3)]
            self.assertAlmostEqual(f["p_final"], r.presiones_m[-1], places=3)
            self.assertAlmostEqual(f["perdida_m"], r.perdida_friccion_m, places=3)
            self.assertAlmostEqual(f["desnivel_m"], r.cotas_m[-1], places=3)
            self.assertAlmostEqual(f["velocidad"], r.velocidad_entrada_ms, places=3)
            n += 1
        self.assertEqual(n, 134)

    def test_tramos_del_portalateral_van_de_p1_a_p2_en_el_sentido_del_flujo(self):
        # Entrada en el centro: la rama «hacia el inicio» va contra el sentido en que se dibujó el portalateral.
        _, capas = self._calcular("InfoTramos", entrada=1)
        valvula = next(capas["Válvula"].getFeatures()).geometry().asPoint()
        for f in capas["Portalateral"].getFeatures():
            p1, p2 = f.geometry().asPolyline()[0], f.geometry().asPolyline()[-1]
            self.assertLessEqual(p1.distance(valvula), p2.distance(valvula) + 1e-6, f["rama"])
            self.assertAlmostEqual(f["p_inicio"] - f["p_fin"], f["perdida_m"] + f["desnivel_m"], delta=0.0035)
            self.assertGreaterEqual(f["perdida_m"], 0.0)
            self.assertLessEqual(f["caudal_sale_lh"], f["caudal_lh"] + 1e-6)
        # El DEM sube 2 % hacia el este: «hacia el final» sube (desnivel > 0) y «hacia el inicio» baja.
        sube = {f["rama"]: f["desnivel_m"] for f in capas["Portalateral"].getFeatures()}
        self.assertGreater(sube["hacia el final"], 0)
        self.assertLess(sube["hacia el inicio"], 0)
        # El caudal que sale del último tramo de una rama es cero; el del primero es el total de la rama.
        for rama in ("hacia el final", "hacia el inicio"):
            tramos = sorted((f for f in capas["Portalateral"].getFeatures() if f["rama"] == rama),
                            key=lambda f: abs(f["desde_m"] - 50))
            self.assertAlmostEqual(tramos[-1]["caudal_sale_lh"], 0.0, places=1)

    def test_buscar_encuentra_el_lateral_o_la_valvula_bajo_el_cursor(self):
        from riegolibre.integracion.info_objeto import (LATERALES, VALVULA, buscar, consultar,
                                                        tipo_de_capa)
        _, capas = self._calcular("InfoBuscar")
        self.assertEqual({tipo_de_capa(c) for c in capas.values()}, {LATERALES, "portalateral", VALVULA})
        crs = self.porta.crs()
        # Clic a 10 m del portalateral, encima de un lateral (a 22.5 m de largo).
        lateral = next(capas["Laterales"].getFeatures())
        medio = lateral.geometry().interpolate(10.0).asPoint()
        candidatos = buscar(medio, crs, 0.3)
        self.assertEqual(candidatos[0].tipo, LATERALES)
        self.assertEqual(candidatos[0].entidad.id(), lateral.id())
        ficha, _ = consultar(medio, crs, 0.3)
        p1 = lateral.geometry().asPolyline()[0]
        self.assertIn(f"P1: x = {p1.x():.2f} m, y = {p1.y():.2f} m", ficha.texto)
        self.assertIn("Subunidad = InfoBuscar", ficha.texto)
        self.assertIn("Presión P1", ficha.texto)
        # Fuera de toda línea no hay nada.
        self.assertIsNone(consultar(_p(500, 500), crs, 0.3))
        # Sobre la válvula (en el inicio del portalateral) gana la válvula, aunque haya líneas encima.
        valvula = next(capas["Válvula"].getFeatures()).geometry().asPoint()
        ficha, candidato = consultar(valvula, crs, 0.5)
        self.assertEqual(candidato.tipo, VALVULA)
        self.assertIn("Presión necesaria a la entrada", ficha.texto)
        self.assertIn("Las presiones por turno aparecen cuando se asignan los turnos", ficha.texto)

    def test_perfil_del_lateral_se_reconstruye_con_el_mismo_resultado(self):
        from riegolibre.integracion.info_objeto import LATERALES, buscar, perfil_lateral
        from riegolibre.nucleo.graficos import dibujar_perfil_lateral, png, referencia_emisor
        _, capas = self._calcular("InfoPerfil")
        crs = self.porta.crs()
        for lateral in list(capas["Laterales"].getFeatures())[::40]:
            punto = lateral.geometry().interpolate(5.0).asPoint()
            candidato = next(c for c in buscar(punto, crs, 0.3) if c.tipo == LATERALES)
            perfil = perfil_lateral(candidato)
            r = perfil.resultado
            self.assertAlmostEqual(r.presion_entrada_m, lateral["p_entrada"], places=6)
            self.assertAlmostEqual(r.presiones_m[-1], lateral["p_final"], delta=0.02)
            self.assertAlmostEqual(r.perdida_friccion_m, lateral["perdida_m"], delta=0.01)
            self.assertAlmostEqual(r.cotas_m[-1], lateral["desnivel_m"], delta=0.01)
            self.assertEqual(r.numero_emisores, lateral["emisores"])
            self.assertAlmostEqual(r.caudal_total_lh, lateral["caudal_lh"], delta=0.5)
            imagen = png(dibujar_perfil_lateral, r, *referencia_emisor(perfil.emisor), "Lateral")
            if imagen is not None:
                self.assertEqual(imagen[1:4], b"PNG")
        # Una capa sin la configuración (calculada con una versión anterior) no tiene perfil.
        from riegolibre.integracion.calculo_subunidad import PROPIEDAD_LATERAL
        capas["Laterales"].removeCustomProperty(PROPIEDAD_LATERAL)
        self.assertIsNone(perfil_lateral(candidato))

    def test_capas_ocultas_no_se_consultan(self):
        from riegolibre.integracion.info_objeto import buscar
        _, capas = self._calcular("InfoOculta")
        lateral = next(capas["Laterales"].getFeatures())
        punto = lateral.geometry().interpolate(5.0).asPoint()
        grupo = QgsProject.instance().layerTreeRoot().findGroup("RiegoLibre · InfoOculta")
        grupo.setItemVisibilityChecked(False)
        self.assertEqual(buscar(punto, self.porta.crs(), 0.3), [])
        grupo.setItemVisibilityChecked(True)
        self.assertTrue(buscar(punto, self.porta.crs(), 0.3))

    def test_herramienta_de_mapa(self):
        from qgis.gui import QgsMapCanvas
        from riegolibre.gui.herramienta_info import DialogoInfo, HerramientaInfo
        _, capas = self._calcular("InfoHerramienta")
        canvas = QgsMapCanvas()
        canvas.resize(800, 600)
        canvas.setDestinationCrs(self.porta.crs())
        canvas.setExtent(self.porta.extent().buffered(30))
        dialogo = DialogoInfo()
        herramienta = HerramientaInfo(canvas, dialogo)
        canvas.setMapTool(herramienta)
        lateral = next(capas["Laterales"].getFeatures())
        ficha = herramienta.consultar(lateral.geometry().interpolate(8.0).asPoint())
        self.assertIsNotNone(ficha)
        self.assertIn("LATERAL", dialogo.texto.toPlainText())
        self.assertIsNotNone(herramienta.resaltado)
        if dialogo.lienzo is not None:  # el lateral se dibuja con su perfil de presión y caudal
            self.assertFalse(dialogo.lienzo.isHidden())
            self.assertEqual(len(dialogo.figura.axes), 3)  # presión, terreno y caudal
        dialogo.copiar()
        from qgis.PyQt.QtWidgets import QApplication
        self.assertIn("LATERAL", QApplication.clipboard().text())
        self.assertIsNone(herramienta.consultar(_p(800, 800)))
        self.assertIn("No hay ningún objeto", dialogo.texto.toPlainText())
        if dialogo.lienzo is not None:
            self.assertTrue(dialogo.lienzo.isHidden())
        self.assertIsNone(herramienta.resaltado)
        canvas.unsetMapTool(herramienta)


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasInfoRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        QgsProject.instance().removeAllMapLayers()
        cls.carpeta = tempfile.TemporaryDirectory()
        ruta = os.path.join(cls.carpeta.name, "dem.tif")
        _crear_dem(ruta)
        cls.dem = QgsRasterLayer(ruta, "dem")
        cls.tuberias = _capa_lineas([PRINCIPAL, RAMA])
        cls.fuente = _capa_punto(FUENTE, "Fuente")
        cls.capas_valvula = [
            _capa_punto(p, f"Válvula · {nombre}", "&field=presion:double&field=caudal_lh:double&field=caudal_ls:double"
                        "&field=tuberia:string(80)", (pr, q, q / 3600, "PVC 63 mm"))
            for nombre, (p, q, pr) in VALVULAS.items()]
        from riegolibre.integracion.subunidad_mapa import PROPIEDAD
        for capa in cls.capas_valvula:  # como las que crea el diseño de la subunidad
            capa.setCustomProperty(PROPIEDAD, "resultado")
        QgsProject.instance().addMapLayers([cls.dem, cls.tuberias, cls.fuente] + cls.capas_valvula)
        from riegolibre.gui.dialogo_red import DialogoRed
        cls.dialogo = DialogoRed(iface=None)
        cls.dialogo.combo_tuberias.setLayer(cls.tuberias)
        cls.dialogo.combo_fuente.setLayer(cls.fuente)
        cls.dialogo.combo_dem.setLayer(cls.dem)
        cls.dialogo.buscar_valvulas()
        fila_b = [v.id for v in cls.dialogo.valvulas].index("B")
        cls.dialogo.tabla_valvulas.cellWidget(fila_b, 3).setValue(2)
        cls.dialogo.calcular()
        cls.resultado = cls.dialogo.resultado
        from riegolibre.gui.dialogo_red import NOMBRE_GRUPO
        cls.capas = {n.layer().name(): n.layer()
                     for n in QgsProject.instance().layerTreeRoot().findGroup(NOMBRE_GRUPO).findLayers()}

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def test_tuberias_orientadas_en_el_sentido_del_flujo_y_con_resultados_por_turno(self):
        red = self.resultado.red
        fuente = _p(*FUENTE)
        n = 0
        for f in self.capas["Red principal · tuberías"].getFeatures():
            vertices = f.geometry().asPolyline()
            turnos = json.loads(f["turnos"])
            self.assertEqual([t[0] for t in turnos], [1, 2])
            # P1 está aguas arriba: más cerca de la fuente a lo largo de la red que P2.
            tramo = next(t for t in red.tramos if t.id == f["tramo"])
            self.assertLessEqual(len(red.camino(tramo.desde)), len(red.camino(tramo.hasta)))
            for _turno, p_ini, p_fin, perdida, _q, _v in turnos:
                self.assertAlmostEqual(p_ini - p_fin, perdida + f["desnivel_m"], delta=0.012)
            n += 1
        self.assertEqual(n, 3)
        # La rama se dibujó desde la válvula hacia la unión: su P1 queda en la unión (80, -45).
        rama = next(f for f in self.capas["Red principal · tuberías"].getFeatures()
                    if abs(f.geometry().length() - 35.0) < 1e-6)
        vertices = rama.geometry().asPolyline()
        self.assertAlmostEqual(vertices[0].y(), Y0 - 45, places=4)
        self.assertAlmostEqual(vertices[-1].y(), Y0 - 10, places=4)

    def test_ficha_de_la_valvula_con_los_turnos_calculados(self):
        from riegolibre.integracion.info_objeto import VALVULA_RED, consultar
        crs = self.tuberias.crs()
        ficha, candidato = consultar(_p(*VALVULAS["A"][0]), crs, 0.5)
        self.assertEqual(candidato.tipo, VALVULA_RED)
        t = ficha.texto
        self.assertIn("Red principal · válvulas", t)
        self.assertIn("Válvula · A", t)  # se une con la válvula de la subunidad del mismo punto
        self.assertIn("Presión necesaria a la entrada = 12.00 m", t)
        filas = [x.split() for x in t.splitlines() if x.startswith("Turno ") and x.split()[1].isdigit()]
        self.assertEqual(len(filas), 2)
        nodo = next(v.nodo for v in self.resultado.red.valvulas if v.id == "A")
        self.assertAlmostEqual(float(filas[0][2]), self.resultado.turno(1).presiones[nodo], places=2)
        self.assertAlmostEqual(float(filas[0][3]), 12.0, places=2)  # requerida: la válvula A trabaja en el turno 1
        self.assertAlmostEqual(float(filas[0][4]), 2.0, places=2)  # pérdida de la válvula (valor del diálogo)
        self.assertAlmostEqual(float(filas[0][5]), 20.0, places=2)  # 20 000 L/h
        self.assertAlmostEqual(float(filas[1][2]), self.resultado.turno(2).presiones[nodo], places=2)
        self.assertEqual(filas[1][3:], ["0.00", "0.00", "0.00"])  # fuera de su turno no tiene caudal
        cota = self.resultado.red.cotas[nodo]
        self.assertIn(f"Cota = {cota:.2f} m", t)
        self.assertIn("Turno de riego asignado = 1", t)

    def test_ficha_de_una_tuberia_de_la_red(self):
        from riegolibre.integracion.info_objeto import TUBERIA_RED, consultar
        crs = self.tuberias.crs()
        ficha, candidato = consultar(_p(*(110, -45)), crs, 0.5)  # sobre el primer tramo de la principal
        self.assertEqual(candidato.tipo, TUBERIA_RED)
        self.assertIn("TUBERÍA DE LA RED PRINCIPAL", ficha.texto)
        filas = [x.split() for x in ficha.texto.splitlines() if x.startswith("Turno ") and x.split()[1].isdigit()]
        self.assertEqual([f[1] for f in filas], ["1", "2"])
        for fila in filas:
            p1, p2, perdida, desnivel = (float(x) for x in fila[2:6])
            self.assertAlmostEqual(p1 - p2, perdida + desnivel, delta=0.012)

    def test_ficha_de_la_bomba(self):
        from riegolibre.integracion.info_objeto import BOMBA, consultar
        ficha, candidato = consultar(_p(*FUENTE), self.tuberias.crs(), 0.5)
        self.assertEqual(candidato.tipo, BOMBA)
        bomba = next(self.capas["Red principal · bomba"].getFeatures())
        self.assertIn(f"Carga dinámica total = {bomba['cdt_m']:.2f} m", ficha.texto)
        self.assertIn(f"Cota = {self.resultado.red.cotas[self.resultado.red.fuente]:.2f} m", ficha.texto)


if __name__ == "__main__":
    unittest.main()
