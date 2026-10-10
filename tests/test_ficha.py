"""Pruebas del formato de las fichas de información de objetos (Python puro)."""

import unittest

from riegolibre.nucleo import ficha


class PruebasFormato(unittest.TestCase):
    def test_numero_y_angulo(self):
        self.assertEqual(ficha.numero(None), "—")
        self.assertEqual(ficha.numero(float("nan")), "—")
        self.assertEqual(ficha.numero(1.23456, 3), "1.235")
        # Igual que en la ficha de IRRICAD: de (504068.88, 8346532.27) a (504068.43, 8346530.90) → 251.88 °.
        self.assertAlmostEqual(ficha.angulo_grados((504068.88, 8346532.27), (504068.43, 8346530.90)), 251.88, delta=0.1)  # coordenadas redondeadas a 1 cm
        self.assertAlmostEqual(ficha.angulo_grados((0, 0), (0, 5)), 90.0)
        self.assertAlmostEqual(ficha.angulo_grados((0, 0), (-1, 0)), 180.0)

    def test_tabla_alinea_columnas(self):
        lineas = ficha.tabla([("Presión P1", "m"), ("Caudal", "m³/h")],
                             [("Turno 1", ["18.48", "19.54"]), ("Turno 12", ["9.00", "0.00"])])
        self.assertEqual(len({len(linea) for linea in lineas if not linea.startswith(("-", "="))}), 1)
        self.assertEqual(len(lineas[0]), len(lineas[-1]))
        self.assertIn("Presión P1", lineas[1])
        self.assertIn("(m³/h)", lineas[2])
        self.assertTrue(lineas[4].startswith("Turno 1 "))
        self.assertTrue(lineas[5].rstrip().endswith("0.00"))


class PruebasFichas(unittest.TestCase):
    LATERAL = {
        "capa": "Laterales · Sub 1", "id": 12, "p1": (504066.19, 8346524.06), "p2": (504116.77, 8346524.06),
        "longitud": 50.58, "subunidad": "Sub 1", "conexion": 4, "dist_porta": 7.5,
        "tuberia": "Manguera PE 16 mm", "emisor": "Gotero 1.6 L/h", "emisores": 156, "p_entrada": 12.0,
        "p_final": 10.5, "perdida_m": 0.88, "desnivel_m": 0.62, "caudal_lh": 256.5, "velocidad": 0.0,
        "p_min": 10.5, "p_max": 11.9, "q_min": 1.59, "q_max": 1.64, "var_caudal": 3.1, "fuera_rango": 0}

    def test_lateral_como_object_info(self):
        f = ficha.ficha_lateral(self.LATERAL)
        t = f.texto
        self.assertIn("P1: x = 504066.19 m, y = 8346524.06 m", t)
        self.assertIn("P2: x = 504116.77 m, y = 8346524.06 m", t)
        self.assertIn("Longitud = 50.58 m,  Ángulo = 0.00 °", t)
        self.assertIn("conexión n.º 5 a 7.50 m", t)
        self.assertIn("Caudal por cada 100 m = 507.12 L/h", t)
        linea = next(x for x in t.splitlines() if x.startswith("Lateral "))
        self.assertEqual(linea.split(), ["Lateral", "12.00", "10.50", "0.88", "0.62", "256.5", "0.00"])
        self.assertIn("Variación de caudal = 3.1 %", t)
        self.assertIn("Lateral 12", f.titulo)

    def test_lateral_de_una_version_anterior_muestra_guiones(self):
        d = dict(self.LATERAL, p_final=None, perdida_m=None, desnivel_m=None, velocidad=None)
        linea = next(x for x in ficha.ficha_lateral(d).texto.splitlines() if x.startswith("Lateral "))
        self.assertEqual(linea.split(), ["Lateral", "12.00", "—", "—", "—", "256.5", "—"])

    def test_tramo_de_portalateral(self):
        d = {"capa": "Portalateral · Sub 1", "id": 3, "p1": (0.0, 0.0), "p2": (0.0, -1.5), "longitud": 1.5,
             "subunidad": "Sub 1", "rama": "hacia el final", "desde_m": 0.0, "hasta_m": 1.5,
             "tuberia": "PVC 75 mm", "p_inicio": 18.70, "p_fin": 18.66, "perdida_m": 0.04, "desnivel_m": 0.0,
             "caudal_lh": 19540.0, "caudal_sale_lh": 19320.0, "velocidad": 1.36}
        t = ficha.ficha_tramo_portalateral(d).texto
        self.assertIn("Ángulo = 270.00 °", t)
        linea = next(x for x in t.splitlines() if x.startswith("Tramo "))
        self.assertEqual(linea.split(), ["Tramo", "18.70", "18.66", "0.04", "0.00", "19.54", "19.32", "1.36"])

    def test_tuberia_de_la_red_por_turno(self):
        d = {"capa": "Red principal · tuberías", "id": "1.2", "p1": (0, 0), "p2": (10, 0), "longitud": 10.0,
             "tuberia": "PVC 90 mm", "dn_mm": 90, "pn_m": 100.0, "j_m100": 1.0, "desnivel_m": -0.5, "observ": "",
             "turnos": [[1, 20.0, 19.0, 0.5, 20000.0, 1.2], [2, 15.0, 15.0, 0.0, 0.0, 0.0]]}
        t = ficha.ficha_tramo_red(d).texto
        filas = [x.split() for x in t.splitlines() if x.startswith("Turno")]
        self.assertEqual(filas[0], ["Turno", "1", "20.00", "19.00", "0.50", "-0.50", "20.00", "1.20"])
        self.assertEqual(filas[1][2:], ["15.00", "15.00", "0.00", "-0.50", "0.00", "0.00"])
        self.assertIn("Sin resultados por turno", ficha.ficha_tramo_red(dict(d, turnos=[])).texto)

    def test_valvula_con_y_sin_red_calculada(self):
        d = {"nombre": "M6. 23", "p1": (504127.85, 8346559.85), "cota": 526.6, "capas": ["Red principal · válvulas"],
             "turno": 2, "subunidad": {"presion_m": 24.69, "caudal_lh": 24940.0, "tuberia": "PVC 63 mm",
                                       "area_m2": 12000.0, "laterales": 80, "emisores": 9000, "variacion": 0.052,
                                       "uniformidad": 93.4, "cumple": True},
             "turnos": [[1, 24.6, 0.0, 0.0, 0.0], [2, 26.61, 24.69, 3.69, 24940.0]]}
        t = ficha.ficha_valvula(d).texto
        self.assertIn("Cota = 526.60 m", t)
        self.assertIn("Presión necesaria a la entrada = 24.69 m,  caudal = 24.94 m³/h", t)
        self.assertIn("Área = 1.200 ha,  laterales = 80,  emisores = 9000", t)
        filas = [x.split() for x in t.splitlines() if x.startswith("Turno ") and x.split()[1].isdigit()]
        self.assertEqual(filas[1], ["Turno", "2", "26.61", "24.69", "3.69", "24.94"])
        self.assertEqual(filas[0][2:], ["24.60", "0.00", "0.00", "0.00"])
        sin_red = ficha.ficha_valvula(dict(d, turnos=[], cota=None, turno=None)).texto
        self.assertIn("asignan los turnos de riego y se calcula la red principal", sin_red)
        self.assertIn("Cota = — m", sin_red)

    def test_bomba(self):
        t = ficha.ficha_bomba({"capa": "Red principal · bomba", "p1": (1.0, 2.0), "cota": 100.0, "turno": 2,
                               "caudal_ls": 10.0, "cdt_m": 45.5, "potencia_kw": 6.4, "potencia_hp": 8.6}).texto
        self.assertIn("Caudal = 10.000 L/s (36.00 m³/h)", t)
        self.assertIn("Carga dinámica total = 45.50 m", t)


if __name__ == "__main__":
    unittest.main()
