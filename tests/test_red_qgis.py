# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas de la red principal dibujada en el mapa (requieren el Python de QGIS)."""

import os
import tempfile
import unittest

from tests.test_integracion_qgis import HAY_QGIS, X0, Y0, _crear_dem, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                           QgsRasterLayer, QgsVectorLayer)

FUENTE = (5, -45)
# Tubería principal con un quiebre y una rama en T (dibujada al revés, desde la válvula).
PRINCIPAL = [(5, -45), (150, -45), (150, -10)]
RAMA = [(80, -10), (80, -45)]
VALVULAS = {"A": ((150, -10), 20000.0, 12.0), "B": ((80, -10), 15000.0, 10.0)}


def _p(x, y):
    return QgsPointXY(X0 + x, Y0 + y)


def _capa_lineas(lineas, nombre="Red principal"):
    capa = QgsVectorLayer("LineString?crs=EPSG:32718", nombre, "memory")
    entidades = []
    for puntos in lineas:
        entidad = QgsFeature()
        entidad.setGeometry(QgsGeometry.fromPolylineXY([_p(*p) for p in puntos]))
        entidades.append(entidad)
    capa.dataProvider().addFeatures(entidades)
    return capa


def _capa_punto(punto, nombre, campos="", valores=()):
    capa = QgsVectorLayer(f"Point?crs=EPSG:32718{campos}", nombre, "memory")
    entidad = QgsFeature(capa.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(_p(*punto)))
    if valores:
        entidad.setAttributes(list(valores))
    capa.dataProvider().addFeatures([entidad])
    return capa


class _HerramientaFalsa:
    """Sustituye a `HerramientaPuntos`: guarda lo que recibe para que la prueba termine o cancele el trazo."""
    creadas = []

    def __init__(self, canvas, cuantos, geometrias, mensajes, terminar, cancelar, mostrar_estado=None):
        self.cuantos, self.geometrias, self.mensajes = cuantos, geometrias, mensajes
        self.terminar, self.cancelar = terminar, cancelar
        self.creadas.append(self)


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasRedMapa(unittest.TestCase):
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
            _capa_punto(p, f"Válvula · {nombre}", "&field=presion:double&field=caudal_lh:double", (pr, q))
            for nombre, (p, q, pr) in VALVULAS.items()]
        QgsProject.instance().addMapLayers([cls.dem, cls.tuberias, cls.fuente] + cls.capas_valvula)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.dem = None
        cls.carpeta.cleanup()

    def tearDown(self):
        # Los turnos cambiados en la tabla quedan pintados en el mapa: que no pasen a la prueba siguiente.
        from riegolibre.integracion.turnos_mapa import capa_de_turnos
        capa = capa_de_turnos()
        if capa is not None:
            QgsProject.instance().removeMapLayer(capa.id())

    def _red(self, muestreador=True, tolerancia=0.5, turnos=None):
        from riegolibre.integracion.perfil_terreno import MuestreadorDem
        from riegolibre.integracion.red_mapa import capas_de_valvulas, construir_red, leer_valvulas
        crs = self.tuberias.crs()
        valvulas = leer_valvulas(capas_de_valvulas(), crs)
        for v in valvulas:
            v.turno = (turnos or {}).get(v.id, 1)
        return construir_red(self.tuberias, _p(*FUENTE), valvulas, crs,
                             MuestreadorDem(self.dem, crs) if muestreador else None,
                             tolerancia_m=tolerancia, perdida_valvula_m=2.0)

    def test_topologia_con_union_en_t(self):
        red_mapa = self._red()
        red = red_mapa.red
        self.assertEqual(sorted(v.id for v in red.valvulas), ["A", "B"])
        longitudes = sorted(round(t.longitud_m, 6) for t in red.tramos)
        self.assertEqual(longitudes, [35.0, 75.0, 105.0])
        # La rama se dibujó desde la válvula: debe quedar orientada desde la unión.
        rama = red.padre[next(v.nodo for v in red.valvulas if v.id == "B")]
        self.assertAlmostEqual(rama.longitud_m, 35.0)
        self.assertEqual(red.padre[rama.desde].desde, red.fuente)
        self.assertAlmostEqual(red.cotas[red.fuente], 100 + 0.02 * 5.5, places=4)

    def test_carga_igual_al_calculo_manual(self):
        from riegolibre.nucleo import CriteriosRed, cargar_catalogo_tuberias, dimensionar_red
        from riegolibre.nucleo.hidraulica import LH_A_M3S
        red = self._red(turnos={"A": 1, "B": 2}).red
        criterios = CriteriosRed(presion_min_m=0.0, factor_perdidas_menores=0.1)
        resultado = dimensionar_red(red, cargar_catalogo_tuberias(uso="principal"), criterios)
        valvula_a = next(v for v in red.valvulas if v.id == "A")
        turno = resultado.turno(1)
        perdidas = sum(resultado.asignacion[t.id].perdida(20000 * LH_A_M3S, t.longitud_m) * 1.1
                       for t in red.camino(valvula_a.nodo))
        esperado = red.cotas[valvula_a.nodo] + 12.0 + 2.0 + perdidas
        self.assertAlmostEqual(turno.carga_fuente_m, esperado, places=6)
        self.assertEqual(turno.critico, "válvula A")
        self.assertEqual(resultado.motivos, {})

    def test_valvula_lejos_de_la_tuberia(self):
        from riegolibre.integracion.red_mapa import ValvulaMapa, construir_red
        lejana = ValvulaMapa("Lejana", _p(120, -30), 1000.0, 10.0)
        with self.assertRaisesRegex(ValueError, "Lejana.*0.5 m"):
            construir_red(self.tuberias, _p(*FUENTE), [lejana], self.tuberias.crs())

    @staticmethod
    def _capa_zona(x0, y0, x1, y1):
        capa = QgsVectorLayer("Polygon?crs=EPSG:32718", "zona", "memory")
        entidad = QgsFeature()
        entidad.setGeometry(QgsGeometry.fromPolygonXY(
            [[_p(x0, y0), _p(x1, y0), _p(x1, y1), _p(x0, y1), _p(x0, y0)]]))
        capa.dataProvider().addFeatures([entidad])
        return capa

    @staticmethod
    def _capa_bloques(nombre, propiedad, x0, y0, x1, y1):
        from riegolibre.integracion.subunidad_mapa import PROPIEDAD
        capa = PruebasRedMapa._capa_zona(x0, y0, x1, y1)
        capa.setName(nombre)
        if propiedad:
            capa.setCustomProperty(PROPIEDAD, propiedad)
        return capa

    def test_capas_de_bloques_se_encuentran_solas(self):
        from riegolibre.integracion.red_mapa import capas_de_bloques
        capas = [self._capa_bloques("Bloques", "dibujo", 0, 0, 1, 1),
                 self._capa_bloques("Bloques · Norte", "trazado", 0, 0, 1, 1),
                 self._capa_bloques("Bloques", None, 0, 0, 1, 1),  # sin la marca de RiegoLibre
                 self._capa_bloques("Lotes", "dibujo", 0, 0, 1, 1),
                 self._capa_bloques("Laterales · Norte", "trazado", 0, 0, 1, 1)]
        QgsProject.instance().addMapLayers(capas)
        self.addCleanup(lambda: [QgsProject.instance().removeMapLayer(c.id()) for c in capas])
        self.assertEqual([c.name() for c in capas_de_bloques()], ["Bloques", "Bloques · Norte"])
        self.assertEqual({c.customProperty("riegolibre/tipo") for c in capas_de_bloques()}, {"dibujo", "trazado"})

    # ------------------------------------- tubería matriz dibujada a mano

    @staticmethod
    def _catalogo():
        from riegolibre.nucleo import cargar_catalogo_tuberias
        return cargar_catalogo_tuberias(uso="principal")

    def test_agregar_tuberia_crea_el_campo_y_guarda_el_diametro(self):
        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, agregar_tuberia, cambiar_tuberia
        capa = _capa_lineas([])  # una capa dibujada antes, sin el campo de la tubería
        self.assertLess(capa.fields().indexOf(CAMPO_TUBERIA), 0)
        tubo = self._catalogo()[-1]
        fija = agregar_tuberia(capa, [_p(0, 0), _p(10, 0), _p(10, 10)], tubo)
        libre = agregar_tuberia(capa, [_p(10, 10), _p(30, 10)])
        self.assertEqual(capa.featureCount(), 2)
        valores = {e.id(): e[CAMPO_TUBERIA] for e in capa.getFeatures()}
        self.assertEqual(valores[fija.id()], tubo.nombre)
        self.assertNotIsInstance(valores[libre.id()], str)  # NULL: la elige el cálculo
        self.assertAlmostEqual(next(capa.getFeatures()).geometry().length(), 20.0)
        # Cambiar el diámetro después, y volver a «Elegida por el programa».
        cambiar_tuberia(capa, [libre.id()], tubo)
        self.assertEqual({e[CAMPO_TUBERIA] for e in capa.getFeatures()}, {tubo.nombre})
        cambiar_tuberia(capa, [fija.id(), libre.id()], None)
        self.assertFalse(any(isinstance(e[CAMPO_TUBERIA], str) for e in capa.getFeatures()))

    def test_agregar_tuberia_con_la_capa_en_edicion_va_al_bufer(self):
        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, agregar_tuberia
        capa = _capa_lineas([])
        agregar_tuberia(capa, [_p(0, 0), _p(5, 0)])  # crea el campo
        capa.startEditing()
        self.addCleanup(capa.rollBack)
        agregar_tuberia(capa, [_p(5, 0), _p(9, 0)], self._catalogo()[0])
        self.assertTrue(capa.isModified())
        self.assertEqual(capa.featureCount(), 2)
        capa.rollBack()
        self.assertEqual(capa.featureCount(), 1)

    def test_el_diametro_fijado_se_respeta_al_calcular(self):
        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, agregar_tuberia, construir_red
        from riegolibre.nucleo import CriteriosRed, dimensionar_red
        catalogo = self._catalogo()
        tubo = catalogo[-1]
        capa = _capa_lineas([])
        agregar_tuberia(capa, [_p(*p) for p in PRINCIPAL], tubo)
        agregar_tuberia(capa, [_p(*p) for p in RAMA])  # sin diámetro: lo elige el cálculo
        id_principal = min(e.id() for e in capa.getFeatures())
        crs = capa.crs()
        from riegolibre.integracion.red_mapa import capas_de_valvulas, leer_valvulas
        red = construir_red(capa, _p(*FUENTE), leer_valvulas(capas_de_valvulas(), crs), crs,
                            catalogo=catalogo).red
        fijos = {t.id for t in red.tramos if t.tuberia is not None}
        self.assertEqual(fijos, {t.id for t in red.tramos if t.id.startswith(f"{id_principal}.")})
        self.assertEqual(len(fijos), 2)  # la línea principal quedó partida en la unión de la rama
        resultado = dimensionar_red(red, catalogo, CriteriosRed(presion_min_m=0.0))
        for t in red.tramos:
            if t.id in fijos:
                self.assertIs(resultado.asignacion[t.id], tubo)
            else:
                self.assertIsNot(resultado.asignacion[t.id], tubo)  # la rama delgada no necesita la mayor

    def test_tuberia_fuera_del_catalogo_avisa(self):
        from riegolibre.integracion.red_mapa import agregar_tuberia, capas_de_valvulas, construir_red, leer_valvulas
        from riegolibre.nucleo.tuberias import Tuberia
        capa = _capa_lineas([])
        agregar_tuberia(capa, [_p(*p) for p in PRINCIPAL], Tuberia("Tubo inexistente", 90.0))
        agregar_tuberia(capa, [_p(*p) for p in RAMA])
        crs = capa.crs()
        valvulas = leer_valvulas(capas_de_valvulas(), crs)
        with self.assertRaisesRegex(ValueError, "Tubo inexistente.*catálogo"):
            construir_red(capa, _p(*FUENTE), valvulas, crs, catalogo=self._catalogo())

    def test_dialogo_de_tuberia_matriz(self):
        from riegolibre.gui.dialogo_tuberia_matriz import TEXTO_POR_PROGRAMA, DialogoTuberiaMatriz
        catalogo = self._catalogo()
        dialogo = DialogoTuberiaMatriz(catalogo, self.tuberias)
        self.assertEqual(dialogo.combo_tuberia.itemText(0), TEXTO_POR_PROGRAMA)
        self.assertEqual(dialogo.combo_tuberia.count(), len(catalogo) + 1)
        self.assertIsNone(dialogo.tuberia())  # por defecto la elige el programa
        self.assertIs(dialogo.capa(), self.tuberias)
        dialogo.combo_tuberia.setCurrentIndex(3)
        self.assertEqual(dialogo.tuberia(), dialogo.combo_tuberia.itemData(3))
        # Con una tubería recordada, el cuadro la deja marcada; al editar no pide la capa.
        recordada = DialogoTuberiaMatriz(catalogo, elegida=dialogo.tuberia(), edicion=True)
        self.assertEqual(recordada.tuberia().nombre, dialogo.tuberia().nombre)
        self.assertIsNone(recordada.capa())
        self.assertIsNone(recordada.combo_capa)

    def _dialogo_con_mapa(self, capa):
        """Ventana de la red con una interfaz y un lienzo simulados (un lienzo real deja inestable
        la suite: la prueba de la imagen satelital cae más adelante al dibujar en hilos)."""
        from unittest import mock

        from qgis.core import QgsCoordinateReferenceSystem

        from riegolibre.gui.dialogo_red import DialogoRed
        canvas = mock.Mock()
        canvas.mapTool.return_value = None
        canvas.mapSettings.return_value.destinationCrs.return_value = QgsCoordinateReferenceSystem("EPSG:32718")
        iface = mock.Mock()
        iface.mapCanvas.return_value = canvas
        dialogo = DialogoRed(iface=iface)
        dialogo.combo_tuberias.setLayer(capa)
        dialogo.combo_fuente.setLayer(self.fuente)
        dialogo.combo_dem.setLayer(None)
        self.addCleanup(dialogo.hide)
        return dialogo, canvas

    def test_se_dibuja_la_red_con_clics_y_se_calcula(self):
        from unittest import mock

        from qgis.PyQt.QtWidgets import QDialog

        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA
        capa = _capa_lineas([], "Red dibujada")
        QgsProject.instance().addMapLayer(capa)
        self.addCleanup(QgsProject.instance().removeMapLayer, capa.id())
        dialogo, canvas = self._dialogo_con_mapa(capa)
        dialogo.buscar_valvulas()
        tubo = dialogo.tuberias[-1]
        fake = mock.patch("riegolibre.gui.dialogo_tuberia_matriz.DialogoTuberiaMatriz.exec",
                          return_value=QDialog.DialogCode.Accepted)
        with fake, mock.patch("riegolibre.gui.dialogo_tuberia_matriz.DialogoTuberiaMatriz.tuberia",
                              return_value=tubo), \
                mock.patch("riegolibre.gui.herramienta_puntos.HerramientaPuntos", _HerramientaFalsa):
            _HerramientaFalsa.creadas = []
            dialogo.dibujar_tuberia_matriz()
        herramienta = dialogo._herramienta_puntos
        self.assertIsNotNone(herramienta)
        self.assertIs(canvas.setMapTool.call_args[0][0], herramienta)
        self.assertIsNone(herramienta.cuantos)  # una línea de dos o más puntos
        self.assertGreaterEqual(len(herramienta.geometrias), 3)  # fuente y las dos válvulas atraen al cursor
        self.assertIn(tubo.nombre, herramienta.mensajes[0])
        self.assertFalse(dialogo.isVisible())  # la ventana se esconde mientras se traza
        self.assertIs(dialogo.diametro_matriz, tubo)
        # Primera tubería (la principal, con el diámetro elegido) y a continuación la rama, con el mismo.
        herramienta.terminar([_p(*p) for p in PRINCIPAL])
        self.assertIsNot(dialogo._herramienta_puntos, herramienta)  # sigue con la tubería siguiente
        self.assertIs(canvas.setMapTool.call_args[0][0], dialogo._herramienta_puntos)
        self.assertEqual(len(dialogo._herramienta_puntos.geometrias), len(herramienta.geometrias) + 1)  # atrae la nueva
        dialogo._herramienta_puntos.terminar([_p(*p) for p in RAMA])
        self.assertEqual(capa.featureCount(), 2)
        self.assertEqual({e[CAMPO_TUBERIA] for e in capa.getFeatures()}, {tubo.nombre})
        # Esc termina: la ventana vuelve con el resumen.
        dialogo._herramienta_puntos.cancelar()
        self.assertIsNone(dialogo._herramienta_puntos)
        self.assertIn("2 con diámetro fijo · 0 por dimensionar", dialogo.etiqueta_matriz.text())
        self.assertIn("Se dibujaron 2 tuberías", dialogo.texto.toPlainText())
        dialogo.calcular()
        self.assertIsNotNone(dialogo.resultado)
        self.assertEqual({dialogo.resultado.asignacion[t.id].nombre for t in dialogo.resultado.red.tramos},
                         {tubo.nombre})
        self.assertIn("Diámetros fijados al dibujar", dialogo.texto.toPlainText())

    def test_cambiar_el_diametro_de_las_seleccionadas(self):
        from unittest import mock

        from qgis.PyQt.QtWidgets import QDialog

        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, agregar_tuberia
        capa = _capa_lineas([], "Red a editar")
        QgsProject.instance().addMapLayer(capa)
        self.addCleanup(QgsProject.instance().removeMapLayer, capa.id())
        primera = agregar_tuberia(capa, [_p(0, 0), _p(10, 0)])
        segunda = agregar_tuberia(capa, [_p(10, 0), _p(20, 0)])
        dialogo, _ = self._dialogo_con_mapa(capa)
        tubo = dialogo.tuberias[1]
        capa.selectByIds([primera.id()])
        with mock.patch("riegolibre.gui.dialogo_tuberia_matriz.DialogoTuberiaMatriz.exec",
                        return_value=QDialog.DialogCode.Accepted), \
                mock.patch("riegolibre.gui.dialogo_tuberia_matriz.DialogoTuberiaMatriz.tuberia", return_value=tubo):
            dialogo.cambiar_diametro_seleccionadas()
        valores = {e.id(): e[CAMPO_TUBERIA] for e in capa.getFeatures()}
        self.assertEqual(valores[primera.id()], tubo.nombre)
        self.assertNotIsInstance(valores[segunda.id()], str)
        self.assertIn("1 con diámetro fijo · 1 por dimensionar", dialogo.etiqueta_matriz.text())
        # Sin selección avisa en vez de cambiar nada.
        capa.removeSelection()
        with mock.patch("riegolibre.gui.dialogo_red.QMessageBox.warning") as aviso:
            dialogo.cambiar_diametro_seleccionadas()
        self.assertIn("Seleccione", aviso.call_args[0][2])

    def test_crear_capas_de_dibujo_trae_el_campo_de_la_tuberia(self):
        from riegolibre.gui.dialogo_red import DialogoRed
        from riegolibre.integracion.red_mapa import CAMPO_TUBERIA, NOMBRE_CAPA_RED
        from qgis.core import QgsCoordinateReferenceSystem
        proyecto = QgsProject.instance()
        crs_anterior = proyecto.crs()
        proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))  # en grados no deja crear las capas
        self.addCleanup(proyecto.setCrs, crs_anterior)
        antes = set(proyecto.mapLayers())
        dialogo = DialogoRed(iface=None)
        dialogo.crear_capas_de_dibujo()
        creadas = [c for i, c in proyecto.mapLayers().items() if i not in antes]
        self.addCleanup(lambda: [proyecto.removeMapLayer(c.id()) for c in creadas])
        red = next(c for c in creadas if c.name() == NOMBRE_CAPA_RED)
        self.assertGreaterEqual(red.fields().indexOf(CAMPO_TUBERIA), 0)
        self.assertTrue(red.labelsEnabled())

    def test_dialogo_calcula_y_crea_capas(self):
        from riegolibre.gui.dialogo_red import NOMBRE_GRUPO, DialogoRed
        dialogo = DialogoRed(iface=None)
        dialogo.combo_tuberias.setLayer(self.tuberias)
        dialogo.combo_fuente.setLayer(self.fuente)
        dialogo.combo_dem.setLayer(self.dem)
        dialogo.buscar_valvulas()
        self.assertEqual(dialogo.tabla_valvulas.rowCount(), 2)
        fila_b = [v.id for v in dialogo.valvulas].index("B")
        dialogo.tabla_valvulas.cellWidget(fila_b, 3).setValue(2)
        dialogo.calcular()

        resultado = dialogo.resultado
        self.assertEqual([r.turno for r in resultado.turnos], [1, 2])
        self.assertEqual(dialogo.tabla_turnos.rowCount(), 2)
        self.assertEqual(dialogo.tabla_tramos.rowCount(), 3)
        grupo = QgsProject.instance().layerTreeRoot().findGroup(NOMBRE_GRUPO)
        capas = {n.layer().name(): n.layer() for n in grupo.findLayers()}
        self.assertEqual(set(capas), {"Red principal · tuberías", "Red principal · válvulas",
                                      "Red principal · bomba"})
        bomba = next(capas["Red principal · bomba"].getFeatures())
        critico = resultado.turno_critico
        self.assertAlmostEqual(bomba["cdt_m"], critico.presion_entrada_red_m + 7.0 + 2.0, places=2)
        from riegolibre.integracion.memoria_mapa import resumenes_del_proyecto
        _subunidades, red, _avisos = resumenes_del_proyecto()
        self.assertAlmostEqual(red["bomba"]["cdt_m"], bomba["cdt_m"], places=2)
        self.assertEqual(len(red["tramos"]), 3)
        excesos = {f["valvula"]: f["exceso"] for f in capas["Red principal · válvulas"].getFeatures()}
        self.assertAlmostEqual(min(excesos.values()), 0.0, places=2)
        self.assertIn("Punto de diseño de la bomba", dialogo.texto.toPlainText())

    def test_dialogo_con_equipos_de_la_base_sin_caudal_minimo(self):
        # La base importada de IRRICAD puede traer el caudal mínimo vacío: la ventana no debe caerse.
        from unittest import mock

        from qgis.PyQt.QtCore import Qt

        from riegolibre.gui.dialogo_red import DialogoRed, _texto_rango
        from riegolibre.nucleo.base_datos import (VARIABLE_RUTA, BaseDatos, ElementoHidraulico,
                                                  guardar_base)
        valvula = ElementoHidraulico('Válvula 2"', k=0.004, n=2.0, c=1.5, caudal_max_m3h=25.0)
        filtro = ElementoHidraulico("Filtro anillas", k=0.002, n=2.0, c=1.0,
                                    caudal_min_m3h=5.0, caudal_max_m3h=25.0)
        sin_rango = ElementoHidraulico("Hidrociclón", k=0.001, n=2.0)
        self.assertEqual(_texto_rango(valvula), " (0–25 m³/h)")
        self.assertEqual(_texto_rango(filtro), " (5–25 m³/h)")
        self.assertEqual(_texto_rango(sin_rango), "")
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "base_datos.json")
            guardar_base(BaseDatos(valvulas=[valvula], hidraulicos=[filtro, sin_rango]), ruta)
            with mock.patch.dict(os.environ, {VARIABLE_RUTA: ruta}):
                dialogo = DialogoRed(iface=None)
                self.assertEqual(dialogo.combo_valvula_base.itemText(1), 'Válvula 2" (0–25 m³/h)')
                lista = dialogo.lista_hidraulicos_cabezal
                self.assertEqual(lista.item(0).text(), "Filtro anillas (5–25 m³/h)")
                self.assertEqual(lista.item(1).text(), "Hidrociclón")
                self.assertEqual(dialogo.datos_bomba().elementos_cabezal, ())
                dialogo.combo_valvula_base.setCurrentIndex(1)
                lista.item(0).setCheckState(Qt.CheckState.Checked)
                lista.item(1).setCheckState(Qt.CheckState.Checked)  # dos equipos en serie
                self.assertEqual([e.nombre for e in dialogo.datos_bomba().elementos_cabezal],
                                 ["Filtro anillas", "Hidrociclón"])
                dialogo.combo_tuberias.setLayer(self.tuberias)
                dialogo.combo_fuente.setLayer(self.fuente)
                dialogo.combo_dem.setLayer(self.dem)
                dialogo.buscar_valvulas()
                dialogo.calcular()
                critico = dialogo.resultado.turno_critico
                cabezal = 7.0 + (0.002 + 0.001) * (critico.caudal_total_lh / 1000) ** 2 + 1.0
                self.assertIn(f"cabezal {cabezal:.1f}", dialogo.texto.toPlainText())


if __name__ == "__main__":
    unittest.main()
