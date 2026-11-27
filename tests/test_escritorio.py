# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Programa de escritorio independiente de QGIS (`riegolibre_escritorio`).

El modelo y el archivo de proyecto se prueban con el Python normal; la ventana, solo si está PySide6 (con el
Python de QGIS esas pruebas se saltan). Nada de esto debe cargar QGIS.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from mcp_riegolibre import motor
from riegolibre.nucleo.red import bomba_critica
from riegolibre_escritorio import archivo, modelo
from riegolibre_escritorio.capas import CAPAS, completar_estilos
from riegolibre_escritorio.modelo import PARAMETROS_RED, ProyectoRiego

try:
    import PySide6  # noqa: F401
    HAY_PYSIDE = "qgis" not in sys.modules  # no mezclar PySide6 con el PyQt de QGIS en el mismo proceso
except ImportError:
    HAY_PYSIDE = False

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOTEO = {
    "emisor": "Gotero autocompensado 1.6 L/h (genérico)",
    "tuberia_lateral": "Manguera PE 16 mm (pared 1.0 mm)",
    "espaciamiento_emisores_m": 0.5,
    "separacion_hileras_m": 3.0,
    "azimut_laterales_deg": 90.0,
    "portalateral": "centro",
    "valvula": "centro",
}
X0, Y0 = 600000.0, 9000000.0


def rectangulo(x, y, ancho, alto):
    return [[X0 + x, Y0 + y], [X0 + x + ancho, Y0 + y], [X0 + x + ancho, Y0 + y + alto], [X0 + x, Y0 + y + alto]]


def datos_prueba():
    return {
        "nombre": "Prueba escritorio", "epsg": 32717, "fuente": [X0 - 20, Y0 - 20], "goteo": dict(GOTEO),
        "terreno": {"tipo": "plano", "cota_m": 100, "origen": [X0, Y0], "pendiente_y": 0.01},
        "red": {"turnos": 2, "matriz": [[[X0 - 20, Y0 - 20], [X0 - 20, Y0 + 40], [X0 + 200, Y0 + 40]]]},
        "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)},
                  {"nombre": "B", "contorno": rectangulo(70, 0, 50, 30)},
                  {"nombre": "C", "contorno": rectangulo(130, 0, 60, 30), "portalateral": "inicio",
                   "valvula": "inicio"}],
    }


def escribir(carpeta, nombre, contenido):
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "w", encoding="utf-8") as salida:
        salida.write(contenido if isinstance(contenido, str) else json.dumps(contenido))
    return ruta


class PruebasModelo(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)

    def importar(self, datos=None):
        ruta = escribir(self.carpeta.name, "Prueba_datos.json", datos or datos_prueba())
        proyecto = ProyectoRiego.importar_mcp(ruta)
        self.addCleanup(proyecto.cerrar)
        return proyecto

    def test_importar_igual_al_servidor(self):
        p = self.importar()
        esperado = motor.disenar_proyecto(datos_prueba()).resumen()
        self.assertEqual(p.errores, [])
        self.assertEqual(p.resumen()["subunidades"], esperado["subunidades"])
        self.assertIsNone(p.red)

    def test_red_igual_al_servidor_con_los_mismos_criterios(self):
        p = self.importar()
        p.calcular_red({"perdida_valvula_m": 0.0})  # el servidor usa 0 m si el diseño no la da
        esperado = motor.disenar_proyecto(datos_prueba()).resumen()
        obtenido = p.resumen()
        for clave in ("red", "bomba", "turnos", "metrados_m"):
            self.assertEqual(obtenido[clave], esperado[clave], clave)

    def test_perdida_en_valvula_como_el_complemento(self):
        """Empieza en 2 m (como la ventana del complemento) y sube la carga de la válvula crítica en lo mismo."""
        p = self.importar()
        self.assertEqual(p.parametros_red["perdida_valvula_m"], 2.0)
        p.calcular_red()
        con = bomba_critica(p.red.bombas)
        p.calcular_red({"perdida_valvula_m": 0.0})
        sin = bomba_critica(p.red.bombas)
        critico = p.red.resultado.turno(sin.turno).critico
        if any(v.id == critico for v in p.red.red.valvulas):
            self.assertAlmostEqual(con.carga_dinamica_total_m - sin.carga_dinamica_total_m, 2.0, places=6)
        else:
            self.assertGreaterEqual(con.carga_dinamica_total_m, sin.carga_dinamica_total_m)

    def test_bomba_contra_la_formula_teorica(self):
        """P = ρ·g·Q·H / η, con Q del turno crítico y H la CDT."""
        p = self.importar()
        p.calcular_red({"eficiencia_bomba": 0.65})
        b = bomba_critica(p.red.bombas)
        q_m3s = sum(s.caudal_lh for s in p.subunidades if s.turno == b.turno) / 3_600_000
        self.assertAlmostEqual(b.caudal_lh / 3_600_000, q_m3s, places=9)
        self.assertAlmostEqual(b.potencia_kw, 1000 * 9.81 * q_m3s * b.carga_dinamica_total_m / 0.65 / 1000, delta=0.01)
        # CDT = carga a la entrada de la red + cabezal + succión
        turno = p.red.resultado.turno(b.turno)
        cdt = turno.presion_entrada_red_m + p.parametros_red["perdidas_cabezal_m"] + p.parametros_red["altura_succion_m"]
        self.assertAlmostEqual(b.carga_dinamica_total_m, cdt, delta=0.01)

    def test_errores_de_la_red(self):
        datos = datos_prueba()
        del datos["red"]["matriz"]
        p = self.importar(datos)
        with self.assertRaisesRegex(ValueError, "matriz"):
            p.calcular_red()
        with self.assertRaisesRegex(ValueError, "desconocidos"):
            p.calcular_red({"caudal": 3})
        datos = datos_prueba()
        datos["red"]["matriz"] = [[[X0 + 500, Y0 + 500], [X0 + 600, Y0 + 500]]]
        p = self.importar(datos)
        with self.assertRaisesRegex(ValueError, "fuente"):
            p.calcular_red()
        self.assertIn("fuente", p.error_red)
        self.assertIn("Red principal", " ".join(p.resumen()["errores"]))

    def test_no_es_un_diseno(self):
        with self.assertRaisesRegex(ValueError, "lotes"):
            ProyectoRiego.importar_mcp(escribir(self.carpeta.name, "otro.json", {"a": 1}))

    def test_lotes_de_geojson_y_dem_dentro_del_proyecto(self):
        datos = datos_prueba()
        entidades = [{"type": "Feature", "properties": {"nombre": l["nombre"]},
                      "geometry": {"type": "Polygon", "coordinates": [l["contorno"] + l["contorno"][:1]]}}
                     for l in datos.pop("lotes")]
        escribir(self.carpeta.name, "lotes.geojson", {"type": "FeatureCollection", "features": entidades})
        datos["lotes_geojson"] = "lotes.geojson"
        datos["lotes"] = [{"nombre": "C", "portalateral": "inicio", "valvula": "inicio"}]
        # DEM del mismo plano inclinado, en celdas de 1 m
        filas = ["ncols 260", "nrows 100", f"xllcorner {X0 - 40}", f"yllcorner {Y0 - 40}", "cellsize 1",
                 "NODATA_value -9999"]
        for j in range(100):
            y = Y0 - 40 + 99.5 - j
            filas.append(" ".join(f"{100 + 0.01 * (y - Y0):.4f}" for _ in range(260)))
        escribir(self.carpeta.name, "dem.asc", "\n".join(filas))
        datos["terreno"] = {"tipo": "dem", "archivo": "dem.asc"}
        p = self.importar(datos)
        self.assertEqual([s.nombre for s in p.subunidades], ["A", "B", "C"])
        self.assertNotIn("lotes_geojson", p.datos)
        self.assertEqual(p.datos["terreno"]["archivo"], "dem.asc")
        self.assertIn("dem.asc", p.archivos)
        plano = ProyectoRiego.importar_mcp(escribir(self.carpeta.name, "plano.json", datos_prueba()))
        self.addCleanup(plano.cerrar)
        for a, b in zip(p.subunidades, plano.subunidades):
            self.assertAlmostEqual(a.presion_valvula_m, b.presion_valvula_m, delta=0.02, msg=a.nombre)

        # El proyecto guardado no depende de los archivos de origen
        ruta = os.path.join(self.carpeta.name, "con_dem.riegolibre")
        archivo.guardar(p, ruta)
        os.remove(os.path.join(self.carpeta.name, "dem.asc"))
        os.remove(os.path.join(self.carpeta.name, "lotes.geojson"))
        q = archivo.abrir(ruta)
        self.addCleanup(q.cerrar)
        self.assertEqual(q.resumen()["subunidades"], p.resumen()["subunidades"])

    def test_guardar_y_abrir(self):
        p = self.importar()
        p.calcular_red({"perdidas_cabezal_m": 9.5})
        p.estilos_capas["LATERALES"].update(color="#123456", ancho=0.5, visible=False)
        ruta = os.path.join(self.carpeta.name, "Prueba.riegolibre")
        archivo.guardar(p, ruta)
        self.assertEqual(p.ruta, ruta)
        self.assertFalse(os.path.exists(ruta + ".tmp"))

        q = archivo.abrir(ruta)
        self.addCleanup(q.cerrar)
        self.assertEqual(q.datos, p.datos)
        self.assertEqual(q.parametros_red["perdidas_cabezal_m"], 9.5)
        self.assertIsNotNone(q.red)
        self.assertEqual(q.resumen(), p.resumen())
        self.assertEqual(q.estilos_capas["LATERALES"]["color"], "#123456")
        self.assertFalse(q.estilos_capas["LATERALES"]["visible"])

        # Lo guardado se puede leer sin RiegoLibre: SQLite con el resumen y las geometrías en GeoJSON
        conexion = sqlite3.connect(ruta)
        try:
            capas = {c for (c,) in conexion.execute("SELECT DISTINCT capa FROM entidades")}
            resumen = json.loads(conexion.execute("SELECT json FROM datos WHERE clave = 'resumen'").fetchone()[0])
        finally:
            conexion.close()
        self.assertTrue({"bloque", "lateral", "portalateral", "valvula", "fuente", "matriz", "conector"} <= capas)
        self.assertEqual(resumen["bomba"], p.resumen()["bomba"])

    def test_abrir_sin_red_calculada_y_archivos_ajenos(self):
        p = self.importar()
        ruta = os.path.join(self.carpeta.name, "sin_red.riegolibre")
        archivo.guardar(p, ruta)
        q = archivo.abrir(ruta)
        self.addCleanup(q.cerrar)
        self.assertIsNone(q.red)
        self.assertEqual(len(q.subunidades), 3)
        ajeno = escribir(self.carpeta.name, "ajeno.riegolibre", "no soy una base de datos")
        with self.assertRaisesRegex(ValueError, "no es un proyecto"):
            archivo.abrir(ajeno)
        with self.assertRaises(ValueError):
            archivo.abrir(os.path.join(self.carpeta.name, "no_existe.riegolibre"))

    def test_estilos_de_capas(self):
        estilos = completar_estilos({"LATERALES": {"color": "#000000", "otra": 1}, "DESCONOCIDA": {}})
        self.assertEqual(list(estilos), list(CAPAS))
        self.assertEqual(estilos["LATERALES"]["color"], "#000000")
        self.assertNotIn("otra", estilos["LATERALES"])
        self.assertEqual(estilos["LOTES"]["ancho"], CAPAS["LOTES"][2])

    def test_parametros_iniciales_desde_el_diseno(self):
        datos = datos_prueba()
        datos["red"]["velocidad_max_ms"] = 2.0
        p = ProyectoRiego(datos)
        self.assertEqual(p.parametros_red["velocidad_max_ms"], 2.0)
        self.assertEqual(set(p.parametros_red), set(PARAMETROS_RED))

    def test_lotes_en_paralelo_igual_que_uno_a_uno(self):
        """Con varios lotes el cálculo se reparte entre procesos; el resultado y los errores no cambian."""
        datos = datos_prueba()
        datos["lotes"] += [{"nombre": "D", "contorno": rectangulo(0, 40, 50, 30)},
                           {"nombre": "Malo", "contorno": rectangulo(70, 40, 50, 30), "emisor": "No existe"}]
        with mock.patch("riegolibre_escritorio.modelo.os.cpu_count", return_value=4), \
                mock.patch("riegolibre_escritorio.modelo.ProcessPoolExecutor", wraps=modelo.ProcessPoolExecutor) as grupo:
            paralelo = self.importar(datos)
        grupo.assert_called_once()
        with mock.patch("riegolibre_escritorio.modelo.LOTES_MIN_PARALELO", 10 ** 6), \
                mock.patch("riegolibre_escritorio.modelo.ProcessPoolExecutor") as grupo:
            uno_a_uno = self.importar(datos)
        grupo.assert_not_called()
        self.assertEqual(len(paralelo.errores), 1)
        self.assertTrue(paralelo.errores[0].startswith("Malo: "))
        self.assertEqual(paralelo.errores, uno_a_uno.errores)
        self.assertEqual([s.nombre for s in paralelo.subunidades], ["A", "B", "C", "D"])
        self.assertEqual(paralelo.resumen(), uno_a_uno.resumen())

    def test_sin_qgis(self):
        """El paquete no importa QGIS en ninguno de sus módulos."""
        carpeta = os.path.join(RAIZ, "riegolibre_escritorio")
        for nombre in os.listdir(carpeta):
            if nombre.endswith(".py"):
                with open(os.path.join(carpeta, nombre), encoding="utf-8") as fuente:
                    texto = fuente.read()
                self.assertNotRegex(texto, r"(?m)^\s*(from|import)\s+qgis", nombre)


@unittest.skipUnless(HAY_PYSIDE, "requiere PySide6 (Python normal, no el de QGIS)")
class PruebasVentana(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.carpeta.cleanup)
        from riegolibre_escritorio import ventana
        # Un cuadro de mensaje dejaría colgada la prueba
        parche = mock.patch.object(ventana, "QMessageBox")
        self.mensajes = parche.start()
        self.addCleanup(parche.stop)
        self.ventana = ventana.VentanaPrincipal()
        self.addCleanup(self.ventana.deleteLater)

    def test_importar_calcular_guardar_y_abrir(self):
        from PySide6.QtCore import Qt
        v = self.ventana
        v.importar_mcp(escribir(self.carpeta.name, "Prueba_datos.json", datos_prueba()))
        self.mensajes.warning.assert_not_called()
        self.assertEqual(v.tabla_subunidades.rowCount(), 3)
        self.assertEqual(list(v.lienzo.capas), list(CAPAS))
        self.assertTrue(v.lienzo.capas["LATERALES"].elementos)
        self.assertEqual(v.lienzo.capas["RED_PRINCIPAL"].elementos, [])
        self.assertTrue(v.isWindowModified())

        # Barra de capas: ver y propiedades
        barra = v.barra_capas
        self.assertEqual(barra.tabla.rowCount(), len(CAPAS))
        fila = list(CAPAS).index("LATERALES")
        barra.tabla.item(fila, 2).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(v.lienzo.capas["LATERALES"].elementos[0].isVisible())
        self.assertFalse(v.proyecto.estilos_capas["LATERALES"]["visible"])
        barra.tabla.setCurrentCell(fila, 1)
        barra._cambiar("color", "#ff00ff")
        self.assertEqual(v.lienzo.capas["LATERALES"].elementos[0].pen().color().name(), "#ff00ff")
        self.assertFalse(v.lienzo.capas["LATERALES"].elementos[0].isVisible())  # sigue oculta al redibujar

        # Red principal y bomba
        v.abrir_red()
        v.dialogo_red.calcular()
        self.mensajes.warning.assert_not_called()
        self.assertIsNotNone(v.proyecto.red)
        self.assertEqual(len(v.lienzo.capas["RED_PRINCIPAL"].elementos), len(v.proyecto.red.red.tramos))
        self.assertEqual(v.dialogo_red.tabla_tramos.rowCount(), len(v.proyecto.red.red.tramos))
        self.assertEqual(v.dialogo_red.tabla_turnos.rowCount(), 2)
        self.assertIn("CDT", v.dialogo_red.texto.toPlainText())
        cdt = bomba_critica(v.proyecto.red.bombas).carga_dinamica_total_m

        ruta = os.path.join(self.carpeta.name, "Prueba.riegolibre")
        self.assertTrue(v._guardar_en(ruta))
        self.assertFalse(v.isWindowModified())
        v.nuevo({"nombre": "Vacío", "epsg": 32717, "terreno": None, "referencia": None})
        self.assertEqual(v.tabla_subunidades.rowCount(), 0)
        v.abrir(ruta)
        self.mensajes.warning.assert_not_called()
        self.assertEqual(v.tabla_subunidades.rowCount(), 3)
        self.assertAlmostEqual(bomba_critica(v.proyecto.red.bombas).carga_dinamica_total_m, cdt, places=9)
        self.assertFalse(v.lienzo.capas["LATERALES"].elementos[0].isVisible())
        self.assertEqual(barra.tabla.item(fila, 2).checkState(), Qt.CheckState.Unchecked)

    def test_error_al_calcular_se_avisa(self):
        datos = datos_prueba()
        del datos["red"]["matriz"]
        v = self.ventana
        v.importar_mcp(escribir(self.carpeta.name, "Sin_matriz_datos.json", datos))
        v.abrir_red()
        from riegolibre_escritorio import dialogo_red
        with mock.patch.object(dialogo_red, "QMessageBox") as mensajes:
            v.dialogo_red.calcular()
        mensajes.warning.assert_called_once()
        self.assertIn("matriz", v.dialogo_red.texto.toPlainText())

    def test_importar_malo_se_avisa(self):
        self.ventana.importar_mcp(escribir(self.carpeta.name, "malo.json", {"x": 1}))
        self.mensajes.warning.assert_called_once()
        self.assertEqual(self.ventana.proyecto.subunidades, [])


if __name__ == "__main__":
    unittest.main()
