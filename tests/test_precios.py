import os
import tempfile
import unittest

from riegolibre.nucleo import Tuberia
from riegolibre.nucleo.materiales import (Partida, asignar_articulos, clave_articulo,
                                          exportar_csv, exportar_excel, resumen_por_categoria,
                                          total)
from riegolibre.nucleo.precios import (buscar, candidatos_conector, candidatos_tuberia,
                                       cargar_lista_precios,
                                       clase_de, interpretar_tuberia, longitud_pieza,
                                       precio_representativo)

LISTA = """codigo,descripcion,unidad,precio
101076401,PVC PIPE UF 63mm C-5 x 6 METERS,,4.87
101076856,"PVC PIPE 63MM C - 5 X 6 METERS + RING",,4.6
101076456,PVC PIPE SP 63mm CLASS 5 X 6 METERS,,6.59
101076402,PVC PIPE UF 63mm C-7.5 x 6 METERS,,9.2
101076969,LUBRICANT FOR PVC UF x GALON PIPES,,6.9
101076455,"PVC PIPE SP 3/4"" CLASS 10 x 5 METERS",,3.48
101103089,PVC PIPE 450-7.5 GASCKET JOINT -6m GRAY,,447.15
101039392,MANGUERA CIEGA 16/40 500m,,0.1162
101094302,MANGUERA DE POLIETILENO HDPE 50 mm PN-8,,0.9556
S.C,HDPE PE100 50MM PN8,,1.11
S.C,TAPA HDPE 110MM TERMOFUSION,,17
101089516,AMNON PC ND 16/25/1.6/0.40 B-450M,,0.2326
101003185,GOTERO SUPERTIF 1.6H l/h SOL ND MOP,,0.0519
101001885,CONECTOR INICIAL DENTADO VERDE 16 MM,,0.0319
101003840,CONEC. INICIAL 16MM NEG. S,,0.1131
101076183,CONECTOR INICIAL 16mm NEGRO+GOMA B AZUD,,0.1029
101076184,CONECTOR INICIAL 20mm NEGRO +GOMA AZUD,,0.0764
101091612,CONECTOR INICIAL 16-17mm LAY FLAT TAVLIT,,0.3338
"""

PVC63 = Tuberia("Tubería PVC 63 mm C-5", 59.8, material="PVC", diametro_nominal_mm=63, presion_nominal_m=50)
MANGUERA16 = Tuberia("Manguera PE 16 mm (pared 1.0 mm)", 14.0, diametro_nominal_mm=16)
PE50 = Tuberia("Tubería PE 50 mm PN4", 44.6, diametro_nominal_mm=50, presion_nominal_m=40)


def _lista(contenido=LISTA):
    carpeta = tempfile.mkdtemp()
    ruta = os.path.join(carpeta, "precios.csv")
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)
    return ruta


class PruebasPrecios(unittest.TestCase):
    def test_interpretar(self):
        casos = {
            "PVC PIPE UF 63mm C-5 x 6 METERS": ("PVC", 63, 5),
            "PVC PIPE 110MM C - 5 X 6 METERS + RING": ("PVC", 110, 5),
            "PVC PIPE SP 63mm CLASS 5 X 6 METERS": ("PVC", 63, 5),
            "PVC PIPE UF 200mm C-7.5 x 6 METERS": ("PVC", 200, 7.5),
            "PVC PIPE 630 C5 GASKET JOINT 6m GRAY+RIN": ("PVC", 630, 5),
            "PVC PIPE 450-7.5 GASCKET JOINT -6m GRAY": ("PVC", 450, 7.5),
            "MANGUERA CIEGA 16/40 500m": ("MANGUERA", 16, None),
            "MANGUERA DE POLIETILENO HDPE 90 mm PN-8": ("PE", 90, 8),
            "TUBERIA HDPE PE80 PN6 NEGRO 110mm": ("PE", 110, 6),
        }
        for descripcion, (material, dn, clase) in casos.items():
            d = interpretar_tuberia(descripcion)
            self.assertEqual((d.material, d.dn_mm, d.clase), (material, dn, clase), descripcion)
        for no_tuberia in ("LUBRICANT FOR PVC UF x GALON PIPES", 'PVC PIPE SP 3/4" CLASS 10 x 5 METERS',
                           "TAPA HDPE 110MM TERMOFUSION", "CODO 45° HDPE SDR11 PN16 40MM",
                           "GOTERO SUPERTIF 1.6H l/h SOL ND MOP"):
            self.assertIsNone(interpretar_tuberia(no_tuberia), no_tuberia)

    def test_longitud_de_pieza(self):
        self.assertEqual(longitud_pieza("PVC PIPE UF 63mm C-5 x 6 METERS"), 6)
        self.assertEqual(longitud_pieza("PVC PIPE 630 C5 GASKET JOINT 6m GRAY"), 6)
        self.assertEqual(longitud_pieza('PVC PIPE SP 1" CLASS 7.5 x 5 METERS'), 5)
        for por_metro in ("MANGUERA CIEGA 16/40 500m", "AMNON PC ND 16/25/1.6/0.40 B-450M",
                          "MANGUERA LAY FLAT DE 2\"-x 100m", "TUBO HDPE 20 mm"):
            self.assertIsNone(longitud_pieza(por_metro), por_metro)

    def test_cargar_y_precio_por_metro(self):
        articulos = cargar_lista_precios(_lista())
        self.assertEqual(len(articulos), 18)
        tubo = articulos[0]
        self.assertTrue(tubo.por_pieza)
        self.assertAlmostEqual(tubo.precio_m, 4.87 / 6)
        bobina = next(a for a in articulos if a.codigo == "101039392")
        self.assertFalse(bobina.por_pieza)
        self.assertAlmostEqual(bobina.precio_m, 0.1162)

    def test_cargar_con_punto_y_coma_y_coma_decimal(self):
        ruta = _lista("codigo;descripcion;unidad;precio\n1;PVC PIPE UF 63mm C-5 x 6 METERS;;1.234,50\n"
                      "2;MANGUERA CIEGA 16/40 500m;;0,1162\n3;SIN PRECIO;;\n")
        articulos = cargar_lista_precios(ruta)
        self.assertEqual([a.precio for a in articulos], [1234.5, 0.1162])

    def test_columnas_obligatorias(self):
        with self.assertRaisesRegex(ValueError, "precio"):
            cargar_lista_precios(_lista("codigo,descripcion,valor\n1,a,2\n"))

    def test_candidatos_por_material_diametro_y_clase(self):
        articulos = cargar_lista_precios(_lista())
        self.assertEqual(clase_de(PVC63), 5)
        candidatos = candidatos_tuberia(PVC63, articulos)
        self.assertEqual([a.codigo for a in candidatos], ["101076856", "101076401", "101076456"])
        self.assertEqual(precio_representativo(candidatos).codigo, "101076401")  # mediana
        self.assertEqual([a.codigo for a in candidatos_tuberia(MANGUERA16, articulos)], ["101039392"])
        self.assertEqual(len(candidatos_tuberia(PE50, articulos)), 2)  # sin la tapa
        self.assertIsNone(precio_representativo([]))

    def test_conectores_por_diametro(self):
        articulos = cargar_lista_precios(_lista())
        conectores = candidatos_conector(16, articulos)
        self.assertEqual([a.codigo for a in conectores], ["101001885", "101076183", "101003840"])
        self.assertEqual(precio_representativo(conectores).codigo, "101076183")
        self.assertEqual([a.codigo for a in candidatos_conector(20, articulos)], ["101076184"])

    def test_buscar(self):
        articulos = cargar_lista_precios(_lista())
        self.assertEqual([a.codigo for a in buscar(articulos, "pvc 63 c-7.5")], ["101076402"])
        self.assertEqual(len(buscar(articulos, "S.C")), 2)


class PruebasMateriales(unittest.TestCase):
    def setUp(self):
        self.articulos = cargar_lista_precios(_lista())
        self.tubo = next(a for a in self.articulos if a.codigo == "101076401")

    def test_tubos_desperdicio_y_costo(self):
        p = Partida("Red principal", "Tubería PVC 63 mm C-5", 100.0, "m", "tuberia:x", self.tubo)
        self.assertAlmostEqual(p.cantidad_compra(0.05), 105.0)
        self.assertEqual(p.piezas(0.05), 18)  # 105 m / 6 m = 17.5 tubos
        self.assertAlmostEqual(p.costo(0.05), 18 * 4.87)
        self.assertEqual(Partida("Red principal", "x", 12.0, "m", "x", self.tubo).piezas(), 2)
        goteros = Partida("Emisores", "Gotero", 1000, "und", "emisor:g",
                          next(a for a in self.articulos if a.codigo == "101003185"))
        self.assertEqual(goteros.cantidad_compra(0.05), 1000)  # el desperdicio no aplica a unidades
        self.assertAlmostEqual(goteros.costo(0.05), 51.9)
        self.assertIsNone(Partida("Accesorios", "x", 3, "und", "x").costo())

    def test_asignacion_automatica_y_elegida(self):
        partidas = [Partida("Red principal", PVC63.nombre, 60.0, "m", f"tuberia:{PVC63.nombre}"),
                    Partida("Laterales", MANGUERA16.nombre, 500.0, "m", f"tuberia:{MANGUERA16.nombre}"),
                    Partida("Emisores", "Gotero 1.6 L/h", 300, "und", "emisor:g"),
                    Partida("Accesorios", "Conector", 20, "und", f"conector:{MANGUERA16.nombre}")]
        tuberias = {t.nombre: t for t in (PVC63, MANGUERA16)}
        amnon = next(a for a in self.articulos if a.codigo == "101089516")
        elegidos = {f"tuberia:{MANGUERA16.nombre}": clave_articulo(amnon)}
        asignar_articulos(partidas, self.articulos, tuberias, elegidos)
        self.assertEqual(partidas[0].articulo.codigo, "101076401")
        self.assertTrue(partidas[0].automatico)
        self.assertIs(partidas[1].articulo, amnon)  # la elección manual manda
        self.assertFalse(partidas[1].automatico)
        self.assertIsNone(partidas[2].articulo)
        self.assertEqual(partidas[3].articulo.codigo, "101076183")
        self.assertTrue(partidas[3].automatico)
        self.assertAlmostEqual(total(partidas), 10 * 4.87 + 500 * 0.2326 + 20 * 0.1029)
        resumen = dict((c, (s, n)) for c, s, n in resumen_por_categoria(partidas))
        self.assertEqual(resumen["Emisores"], (0.0, 1))

    def test_exportar(self):
        partidas = [Partida("Red principal", PVC63.nombre, 100.0, "m", "x", self.tubo),
                    Partida("Accesorios", "Conector", 10, "und", "y")]
        carpeta = tempfile.mkdtemp()
        ruta_csv = os.path.join(carpeta, "lista.csv")
        exportar_csv(partidas, ruta_csv, 0.05, "USD")
        with open(ruta_csv, encoding="utf-8-sig") as archivo:
            lineas = archivo.read().splitlines()
        self.assertEqual(len(lineas), 4)
        self.assertTrue(lineas[-1].endswith(f"Total USD;{18 * 4.87:.2f}"))
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no disponible")
        ruta_xlsx = os.path.join(carpeta, "lista.xlsx")
        exportar_excel(partidas, ruta_xlsx, 0.05, "USD", detalles=["Proyecto: prueba"])
        with open(ruta_xlsx, "rb") as archivo:  # openpyxl deja abierto el archivo si recibe la ruta
            valores = list(openpyxl.load_workbook(archivo).active.iter_rows(values_only=True))
        encabezado = next(i for i, f in enumerate(valores) if f[0] == "Categoría")
        self.assertEqual(valores[encabezado + 1][5], 18)
        self.assertTrue(str(valores[-1][9]).startswith("=SUM(J"))


if __name__ == "__main__":
    unittest.main()
