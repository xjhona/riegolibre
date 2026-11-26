# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas del motor del servidor MCP (diseño completo sin QGIS)."""

import json
import os
import tempfile
import unittest

from mcp_riegolibre import motor

GOTEO = {
    "emisor": "Gotero autocompensado 1.6 L/h (genérico)",
    "tuberia_lateral": "Manguera PE 16 mm (pared 1.0 mm)",
    "espaciamiento_emisores_m": 0.5,
    "separacion_hileras_m": 3.0,
}


def rectangulo(x0, y0, ancho, alto):
    return [[x0, y0], [x0 + ancho, y0], [x0 + ancho, y0 + alto], [x0, y0 + alto]]


class PruebasMotor(unittest.TestCase):
    def test_lote_llano_sin_fuente(self):
        p = motor.disenar_proyecto({"goteo": GOTEO, "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})
        self.assertEqual(len(p.subunidades), 1)
        s = p.resumen()["subunidades"][0]
        self.assertTrue(s["cumple"], s["motivos"])
        self.assertGreater(s["caudal_m3h"], 0)
        self.assertIsNone(p.red)
        self.assertTrue(any("fuente" in e for e in p.errores))

    def test_proyecto_con_red_y_bomba(self):
        datos = {
            "fuente": [-20, -20], "goteo": GOTEO,
            "red": {"turnos": 2, "matriz": [[[-20, -20], [-20, 40], [150, 40]], [[70, 40], [70, -10]]]},
            "terreno": {"tipo": "plano", "cota_m": 100, "pendiente_y": 0.01},
            "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)},
                      {"nombre": "B", "contorno": rectangulo(80, 0, 60, 30)}],
        }
        p = motor.disenar_proyecto(datos)
        r = p.resumen()
        self.assertEqual(r["errores"], [])
        self.assertEqual({s["turno"] for s in r["subunidades"]}, {1, 2})
        self.assertGreater(r["bomba"]["cdt_m"], 0)
        self.assertGreater(r["red"]["longitud_m"], 0)
        self.assertTrue(any("(red principal)" in k for k in r["metrados_m"]))
        # Las válvulas lejos de la matriz llevan su conector, y la red los dimensiona
        self.assertTrue(all(t["desde"] != t["hasta"] for t in r["red"]["tramos"]))

    def test_sin_matriz_no_hay_red(self):
        p = motor.disenar_proyecto({"fuente": [-20, -20], "goteo": GOTEO,
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})
        self.assertIsNone(p.red)
        self.assertTrue(any("matriz" in e for e in p.errores))
        self.assertIn("valvula_xy", p.resumen()["subunidades"][0])

    def test_valvula_fuera_de_alcance(self):
        p = motor.disenar_proyecto({"fuente": [-20, -20], "goteo": GOTEO,
                                    "red": {"matriz": [[[-20, -20], [-20, 40]]], "largo_max_conector_m": 1},
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})
        self.assertIsNone(p.red)
        self.assertTrue(any("demasiado lejos" in e for e in p.errores))

    def test_matriz_cortada_en_las_valvulas(self):
        r = motor._subpolilinea([(0, 0), (10, 0), (10, 10)], 5, 15)
        self.assertEqual(r, [(5.0, 0.0), (10, 0), (10.0, 5.0)])

    def test_subdivision_por_largo_de_lateral(self):
        goteo = dict(GOTEO, subdivision={"longitud_max_lateral_m": 40})
        p = motor.disenar_proyecto({"goteo": goteo, "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 100, 30)}]})
        self.assertGreater(len(p.subunidades), 1)
        self.assertTrue(all(s.bloque.lateral_mas_largo_m <= 40 + 1e-6 for s in p.subunidades))
        self.assertEqual({s.lote for s in p.subunidades}, {"A"})

    def test_lote_con_error_no_detiene_el_resto(self):
        p = motor.disenar_proyecto({"goteo": GOTEO, "lotes": [
            {"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)},
            {"nombre": "B", "contorno": rectangulo(0, 0, 60, 30), "emisor": "no existe"}]})
        self.assertEqual([s.nombre for s in p.subunidades], ["A"])
        self.assertTrue(any(e.startswith("B:") for e in p.errores))

    def test_cinta_definida_en_el_proyecto(self):
        cinta = {"nombre": "Cinta PC 1.6 L/h", "diametro_interior_mm": 13.7, "k_emisor": 1.6, "exponente_emisor": 0.0,
                 "espaciamiento_m": 0.3, "presion_min_compensacion_m": 10, "presion_max_m": 30, "cv": 0.02}
        p = motor.disenar_proyecto({"goteo": {"cinta": cinta, "separacion_hileras_m": 3.0},
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})
        s = p.resumen()["subunidades"][0]
        self.assertTrue(s["cumple"], s["motivos"])
        self.assertGreaterEqual(s["presion_emisor_min_m"], 10)
        with self.assertRaisesRegex(ValueError, "desconocidos"):
            motor.disenar_proyecto({"goteo": {"cinta": dict(cinta, caudal=2), "separacion_hileras_m": 3.0},
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})

    def test_nombre_ambiguo(self):
        with self.assertRaisesRegex(ValueError, "ambiguo"):
            motor.disenar_proyecto({"goteo": dict(GOTEO, emisor="autocompensado"),
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})

    def test_recortar_con_rectangulo(self):
        recorte = motor._recortar([(0, 0), (10, 0), (10, 10), (0, 10)], [(5, -1), (20, -1), (20, 20), (5, 20)])
        self.assertAlmostEqual(motor._area(recorte), 50.0)

    def test_terreno_por_puntos(self):
        t = motor.Terreno({"tipo": "puntos", "puntos": [[0, 0, 10], [100, 0, 20], [0, 100, 10]]})
        self.assertAlmostEqual(t.cota(0, 0), 10.0)
        self.assertTrue(10 < t.cota(50, 0) < 20)

    def test_dem_ascii(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "dem.asc")
            with open(ruta, "w", encoding="utf-8") as archivo:
                archivo.write("ncols 3\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n"
                              "20 21 22\n10 11 12\n")
            t = motor.Terreno({"tipo": "dem", "archivo": ruta})
            self.assertAlmostEqual(t.cota(5, 5), 10.0)  # centro de la celda de abajo a la izquierda
            self.assertAlmostEqual(t.cota(5, 15), 20.0)
            self.assertAlmostEqual(t.cota(10, 10), 15.5)

    def test_exportar(self):
        p = motor.disenar_proyecto({"fuente": [-10, -10], "epsg": 32718, "goteo": GOTEO,
                                    "red": {"matriz": [[[-10, -10], [-10, 40], [70, 40]]]},
                                    "lotes": [{"nombre": "A", "contorno": rectangulo(0, 0, 60, 30)}]})
        with tempfile.TemporaryDirectory() as carpeta:
            rutas = p.exportar(carpeta)
            with open(rutas["geojson"], encoding="utf-8") as archivo:
                geo = json.load(archivo)
            capas = {e["properties"]["capa"] for e in geo["features"]}
            self.assertEqual(capas - {"conector"}, {"bloque", "portalateral", "lateral", "valvula", "fuente", "matriz"})
            self.assertIn("32718", geo["crs"]["properties"]["name"])
            with open(rutas["memoria"], encoding="utf-8") as archivo:
                self.assertIn("<html", archivo.read())

    def test_lotes_desde_geojson(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "lotes.geojson")
            with open(ruta, "w", encoding="utf-8") as archivo:
                json.dump({"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {"nombre": "Norte"},
                     "geometry": {"type": "Polygon", "coordinates": [rectangulo(0, 0, 60, 30) + [[0, 0]]]}}]}, archivo)
            p = motor.disenar_proyecto({"goteo": GOTEO, "lotes_geojson": ruta,
                                        "lotes": [{"nombre": "Norte", "portalateral": "centro"}]})
            self.assertEqual(p.subunidades[0].nombre, "Norte")
            self.assertEqual(p.subunidades[0].config["portalateral"], "centro")


if __name__ == "__main__":
    unittest.main()
