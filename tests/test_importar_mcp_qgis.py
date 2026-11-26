# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Importar en el mapa un diseño del servidor MCP (requieren el Python de QGIS).

El diseño importado debe dar lo mismo que el servidor MCP (`mcp_riegolibre.motor`) y quedar en las capas de
siempre, para que las herramientas del complemento trabajen sobre él.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from tests.test_integracion_qgis import HAY_QGIS, _iniciar_qgis

if HAY_QGIS:
    from qgis.core import QgsProject

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Caso real del cliente (no está en git): en la carpeta de muestras del repositorio o del checkout principal
CARPETAS_FRUVEG = [os.path.join(RAIZ, "muestras", "fruveg_mcp"),
                   os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(RAIZ))), "muestras", "fruveg_mcp")]
CARPETA_FRUVEG = next((c for c in CARPETAS_FRUVEG if os.path.exists(os.path.join(c, "Fruveg_portalaterales_datos.json"))),
                      None)

X0, Y0 = 600000.0, 9000000.0
GOTEO = {
    "emisor": "Gotero autocompensado 1.6 L/h (genérico)",
    "tuberia_lateral": "Manguera PE 16 mm (pared 1.0 mm)",
    "espaciamiento_emisores_m": 0.5,
    "separacion_hileras_m": 3.0,
    "azimut_laterales_deg": 90.0,
    "portalateral": "centro",
    "valvula": "centro",
}
CINTA = {"nombre": "Cinta de prueba 16 mm 1.0 L/h @0.30 m", "diametro_interior_mm": 15.6, "k_emisor": 1.0,
         "exponente_emisor": 0.5, "espaciamiento_m": 0.3, "presion_entrada_m": 10.0, "cv": 0.03}


def rectangulo(x, y, ancho, alto):
    return [[X0 + x, Y0 + y], [X0 + x + ancho, Y0 + y], [X0 + x + ancho, Y0 + y + alto], [X0 + x, Y0 + y + alto]]


def datos_reducidos():
    return {
        "nombre": "Prueba MCP", "epsg": 32717, "fuente": [X0 - 20, Y0 - 20], "goteo": dict(GOTEO),
        "terreno": {"tipo": "plano", "cota_m": 100, "origen": [X0, Y0], "pendiente_y": 0.01},
        "red": {"turnos": 2, "matriz": [[[X0 - 20, Y0 - 20], [X0 - 20, Y0 + 40], [X0 + 200, Y0 + 40]]]},
        "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)},
                  {"nombre": "B", "contorno": rectangulo(70, 0, 50, 30)},
                  {"nombre": "C", "contorno": rectangulo(130, 0, 60, 30), "portalateral": "inicio",
                   "valvula": "inicio"}],
    }


def _sin_mensajes(*args, **kwargs):
    raise AssertionError(f"Se mostró un mensaje: {args[2] if len(args) > 2 else args}")


@unittest.skipUnless(HAY_QGIS, "requiere el Python de QGIS")
class PruebasImportarMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _iniciar_qgis()
        cls.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.carpeta.cleanup()

    def setUp(self):
        QgsProject.instance().clear()

    def _importar(self, datos, cinta=None, matriz=None):
        from riegolibre.integracion.importar_mcp import Catalogos, importar_diseno
        return importar_diseno(datos, Catalogos.activos(cinta), cinta, matriz, self.carpeta.name)

    # ------------------------------------------------------------ piezas

    def test_valores_por_omision_iguales_al_servidor(self):
        from mcp_riegolibre import motor
        from riegolibre.integracion import importar_mcp
        self.assertEqual(importar_mcp.GOTEO_POR_OMISION, motor.GOTEO_POR_OMISION)
        self.assertEqual(importar_mcp.RED_POR_OMISION, motor.RED_POR_OMISION)

    def test_valores_del_bloque(self):
        from riegolibre.integracion.bloque_mapa import parametros_de
        from riegolibre.integracion.importar_mcp import Catalogos, configuracion_goteo, valores_del_bloque
        from riegolibre.nucleo.base_datos import Cinta
        cinta = Cinta(**CINTA)
        catalogos = Catalogos.activos(cinta)
        c = configuracion_goteo({"cinta": CINTA, "separacion_hileras_m": 1.5, "azimut_laterales_deg": 30.0,
                                 "laterales_por_hilera": 2}, {"nombre": "X", "portalateral": "final"})
        v = valores_del_bloque(c, catalogos, cinta)
        self.assertEqual((v["tuberia"], v["emisor"]), (cinta.nombre, cinta.nombre))
        self.assertEqual(v["espaciamiento_m"], 0.3)
        self.assertEqual(v["primer_emisor_m"], 0.15)
        self.assertEqual(v["costados_m"], 0.75)  # «None» del servidor: media separación
        self.assertEqual((v["direccion"], v["azimut_deg"]), ("usuario", 30.0))
        self.assertEqual(v["portalateral"], "final")  # lo del lote manda
        self.assertEqual(v["diametros_max"], 2)
        params = parametros_de(v, catalogos.emisores[-1])
        self.assertAlmostEqual(params.angulo_deg, 60.0)
        self.assertEqual(params.laterales_por_hilera, 2)
        sin = valores_del_bloque(configuracion_goteo(dict(GOTEO, azimut_laterales_deg=None), {}), catalogos)
        self.assertEqual(sin["direccion"], "auto")
        self.assertIn("genérico", sin["emisor"])
        with self.assertRaises(ValueError):
            configuracion_goteo({"emisores": "x"}, {})
        with self.assertRaises(ValueError):
            valores_del_bloque(configuracion_goteo({"emisor": "no existe", "tuberia_lateral": "Manguera",
                                                    "espaciamiento_emisores_m": 0.5, "separacion_hileras_m": 1},
                                                   {}), catalogos)

    def test_repartir_turnos_como_el_servidor(self):
        from mcp_riegolibre import motor
        from riegolibre.integracion.importar_mcp import repartir_turnos
        caudales = [("A", "A", 5.0), ("B-1", "B", 9.0), ("B-2", "B", 4.0), ("C", "C", 6.0), ("D", "D", 1.0)]

        class S:
            def __init__(self, nombre, lote, caudal):
                self.nombre, self.lote, self.caudal_lh = nombre, lote, caudal
        subs = [S(*x) for x in caudales]
        motor.repartir_turnos(subs, 3, {"B": 2})
        self.assertEqual(repartir_turnos(caudales, 3, {"B": 2}), {s.nombre: s.turno for s in subs})

    def test_leer_datos_con_lotes_geojson(self):
        from riegolibre.integracion.importar_mcp import leer_datos
        carpeta = self.carpeta.name
        lotes = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"nombre": "L1"},
             "geometry": {"type": "Polygon", "coordinates": [rectangulo(0, 0, 40, 20)]}}]}
        with open(os.path.join(carpeta, "mis_lotes.geojson"), "w", encoding="utf-8") as archivo:
            json.dump(lotes, archivo)
        datos = {"goteo": GOTEO, "lotes_geojson": r"D:\otra\carpeta\mis_lotes.geojson",  # se copió de otra PC
                 "lotes": [{"nombre": "L1", "portalateral": "final"}]}
        ruta = os.path.join(carpeta, "x_datos.json")
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo)
        leidos = leer_datos(ruta)
        self.assertEqual(len(leidos["lotes"]), 1)
        self.assertEqual(leidos["lotes"][0]["portalateral"], "final")
        self.assertIn("anillos", leidos["lotes"][0])
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump({"lotes": []}, archivo)
        with self.assertRaises(ValueError):
            leer_datos(ruta)

    def test_agregar_cinta_a_la_base(self):
        from riegolibre.integracion.importar_mcp import agregar_cinta_a_la_base, cinta_del_diseno
        from riegolibre.nucleo.base_datos import VARIABLE_RUTA, cintas_activas, recargar_base
        ruta = os.path.join(self.carpeta.name, "base_prueba.json")
        with mock.patch.dict(os.environ, {VARIABLE_RUTA: ruta}):
            recargar_base()
            try:
                datos = {"goteo": {"cinta": CINTA}}
                self.assertFalse(cinta_del_diseno(datos).en_base)
                agregar_cinta_a_la_base(cinta_del_diseno(datos).cinta)
                self.assertIn(CINTA["nombre"], cintas_activas())
                encontrada = cinta_del_diseno(datos)
                self.assertTrue(encontrada.en_base)
                self.assertFalse(encontrada.distinta)
                self.assertTrue(cinta_del_diseno({"goteo": {"cinta": "Cinta de prueba"}}).en_base)  # por nombre
                with self.assertRaises(ValueError):  # ya está
                    agregar_cinta_a_la_base(encontrada.cinta)
            finally:
                recargar_base()

    # ------------------------------------------------------------ diseño completo

    def test_diseno_reducido_igual_al_servidor(self):
        from mcp_riegolibre import motor
        from riegolibre.integracion.bloque_mapa import eliminar_bloque, recalcular_lote, resumen_resultado
        from riegolibre.integracion.fuente_mapa import capa_de_fuente
        from riegolibre.integracion.lotes import capas_de_lotes, parametros_guardados
        from riegolibre.integracion.red_mapa import capa_de_matriz, capas_de_valvulas, leer_valvulas
        from riegolibre.integracion.turnos_mapa import turnos_asignados
        from riegolibre.integracion.importar_mcp import Catalogos

        datos = datos_reducidos()
        esperado = {s["nombre"]: s for s in motor.disenar_proyecto(json.loads(json.dumps(datos))).resumen()["subunidades"]}
        r = self._importar(datos)
        self.assertEqual(r.errores, [])
        self.assertEqual(sorted(l.nombre for l in r.lotes), ["A", "B", "C"])
        for l in r.lotes:
            s = esperado[l.nombre]
            self.assertEqual(l.resultado["portalateral"], s["portalateral"], l.nombre)
            self.assertAlmostEqual(l.resultado["presion_valvula_m"], s["presion_valvula_m"], delta=0.1, msg=l.nombre)
            self.assertAlmostEqual(l.resultado["caudal_m3h"], s["caudal_m3h"], delta=0.01, msg=l.nombre)
            self.assertEqual(l.turno, s["turno"], l.nombre)

        # Las capas de siempre
        proyecto = QgsProject.instance()
        self.assertEqual(proyecto.crs().authid(), "EPSG:32717")
        self.assertEqual(capas_de_lotes(), [r.capa_lotes])
        entidades = {e["nombre"]: e for e in r.capa_lotes.getFeatures()}
        for nombre in "ABC":
            v = parametros_guardados(entidades[nombre])
            self.assertEqual(v["dem"], r.capa_dem.id())
            self.assertEqual(v["fuente"], r.capa_fuente.id())
            self.assertAlmostEqual(v["azimut_usado_deg"], 90.0, places=3)
            self.assertIsNotNone(proyecto.layerTreeRoot().findGroup(f"RiegoLibre · {nombre}"))
        self.assertTrue(os.path.exists(r.capa_dem.source()))
        self.assertEqual(capa_de_fuente().featureCount(), 1)
        self.assertEqual(r.tuberias_matriz, 1)
        self.assertEqual(r.conectores, 3)
        self.assertEqual(capa_de_matriz().featureCount(), 4)
        valvulas = {v.id for v in leer_valvulas(capas_de_valvulas(), proyecto.crs())}
        self.assertEqual(valvulas, {"A", "B", "C"})
        self.assertEqual(turnos_asignados(), {n: s["turno"] for n, s in esperado.items()})

        # Las herramientas del complemento trabajan sobre los lotes importados
        catalogos = Catalogos.activos()
        entidad = entidades["B"]
        calculo, config = recalcular_lote(r.capa_lotes, entidad, parametros_guardados(entidad),
                                          catalogos.tuberias_lateral, catalogos.emisores,
                                          catalogos.tuberias_portalateral)
        de_nuevo = resumen_resultado(calculo, config, parametros_guardados(entidad))
        self.assertEqual(de_nuevo, parametros_guardados(entidad)["resultado"])
        eliminar_bloque(r.capa_lotes, entidad)
        self.assertIsNone(proyecto.layerTreeRoot().findGroup("RiegoLibre · B"))

        # Volver a importar el mismo diseño pisaría los lotes: se avisa
        with self.assertRaises(ValueError):
            self._importar(datos_reducidos())

    def test_cinta_solo_para_esta_importacion_y_subdivision(self):
        from mcp_riegolibre import motor
        from riegolibre.nucleo.base_datos import Cinta
        datos = datos_reducidos()
        datos["goteo"] = {"cinta": CINTA, "separacion_hileras_m": 1.5, "azimut_laterales_deg": 90.0,
                          "portalateral": "centro", "valvula": "centro"}
        datos["lotes"] = [{"nombre": "G", "contorno": rectangulo(0, 0, 150, 30),
                           "subdivision": {"longitud_max_lateral_m": 60}}]
        del datos["red"]
        esperado = {s["nombre"]: s for s in motor.disenar_proyecto(json.loads(json.dumps(datos))).resumen()["subunidades"]}
        r = self._importar(datos, Cinta(**CINTA))
        self.assertEqual(r.errores, [])
        self.assertEqual(sorted(l.nombre for l in r.lotes), sorted(esperado))
        self.assertGreater(len(r.lotes), 1)
        for l in r.lotes:
            self.assertEqual(l.lote, "G")
            self.assertEqual(l.resultado["portalateral"], esperado[l.nombre]["portalateral"])
            self.assertAlmostEqual(l.resultado["presion_valvula_m"], esperado[l.nombre]["presion_valvula_m"],
                                   delta=0.1)
        self.assertTrue(any("matriz" in a for a in r.avisos))
        self.assertEqual(r.tuberias_matriz, 0)

    def test_ventana(self):
        from riegolibre.gui.dialogo_importar_mcp import DialogoImportarMcp
        ruta = os.path.join(self.carpeta.name, "ventana_datos.json")
        datos = datos_reducidos()
        datos["goteo"] = dict(datos["goteo"], cinta=CINTA)
        del datos["goteo"]["emisor"], datos["goteo"]["tuberia_lateral"]
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo)
        with mock.patch("qgis.PyQt.QtWidgets.QMessageBox.warning", _sin_mensajes), \
                mock.patch("qgis.PyQt.QtWidgets.QMessageBox.information", _sin_mensajes):
            dialogo = DialogoImportarMcp(None)
            dialogo.edit_datos.setText(ruta)
            dialogo._leer()
            self.assertFalse(dialogo.check_cinta.isHidden())  # la cinta no está en la base
            self.assertFalse(dialogo.edit_matriz.isEnabled())  # el diseño trae la matriz
            dialogo.check_cinta.setChecked(False)  # solo para esta importación
            dialogo.importar()
        self.assertEqual(len(dialogo.resultado.lotes), 3)
        html = dialogo.texto.toHtml()
        self.assertIn("Diseño importado", html)
        self.assertIn("no se agregó a la base de datos", html)

    @unittest.skipUnless(CARPETA_FRUVEG, "falta la carpeta de muestras fruveg_mcp")
    def test_fruveg_igual_al_resumen_del_servidor(self):
        """Caso real (EPSG 32717, DEM, cinta definida en el diseño, portalateral al centro): ocho de sus lotes."""
        from riegolibre.integracion.importar_mcp import cinta_del_diseno, leer_datos, matriz_de_geojson
        datos = leer_datos(os.path.join(CARPETA_FRUVEG, "Fruveg_portalaterales_datos.json"))
        with open(os.path.join(CARPETA_FRUVEG, "Fruveg_portalaterales_resumen.json"), encoding="utf-8") as archivo:
            resumen = {s["nombre"]: s for s in json.load(archivo)["subunidades"]}
        datos["lotes"] = datos["lotes"][:8]
        cinta = cinta_del_diseno(datos)
        matriz = matriz_de_geojson(os.path.join(CARPETA_FRUVEG, "matriz_trazada.geojson"))
        from riegolibre.integracion.importar_mcp import Catalogos, importar_diseno
        r = importar_diseno(datos, Catalogos.activos(None if cinta.en_base else cinta.cinta), cinta.cinta, matriz,
                            self.carpeta.name)
        self.assertEqual(r.errores, [])
        self.assertEqual(len(r.lotes), 8)
        for l in r.lotes:
            s = resumen[l.nombre]
            self.assertEqual(l.resultado["portalateral"], s["portalateral"], l.nombre)
            self.assertAlmostEqual(l.resultado["presion_valvula_m"], s["presion_valvula_m"], delta=0.15, msg=l.nombre)
            self.assertAlmostEqual(l.resultado["caudal_m3h"], s["caudal_m3h"], delta=0.01, msg=l.nombre)
        self.assertGreater(r.tuberias_matriz, 0)
        self.assertEqual(r.capa_dem.crs().authid(), "EPSG:32717")


if __name__ == "__main__":
    unittest.main()
