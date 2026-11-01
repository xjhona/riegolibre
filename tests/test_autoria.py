# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas de los avisos de autoría y licencia: lo que se instala debe llevarlos."""

import configparser
import pathlib
import unittest

from riegolibre.nucleo.autoria import ATRIBUCION, AUTOR, COPYRIGHT

RAIZ = pathlib.Path(__file__).resolve().parent.parent
COMPLEMENTO = RAIZ / "riegolibre"
ENCABEZADO = [f"# {COPYRIGHT}",
              "# SPDX-License-Identifier: GPL-3.0-only",
              "# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales)."]


class TestAutoria(unittest.TestCase):
    def test_todo_archivo_de_codigo_lleva_el_encabezado(self):
        archivos = [a for carpeta in (COMPLEMENTO, RAIZ / "tests") for a in carpeta.rglob("*.py")
                    if "__pycache__" not in a.parts]
        self.assertGreater(len(archivos), 90)
        sin_encabezado = [str(a.relative_to(RAIZ)) for a in archivos
                          if a.read_text(encoding="utf-8").splitlines()[:3] != ENCABEZADO]
        self.assertEqual(sin_encabezado, [])

    def test_el_complemento_instalado_lleva_licencia_y_aviso(self):
        self.assertEqual((COMPLEMENTO / "LICENSE").read_text(encoding="utf-8"),
                         (RAIZ / "LICENSE").read_text(encoding="utf-8"))
        aviso = (COMPLEMENTO / "NOTICE").read_text(encoding="utf-8")
        self.assertIn(COPYRIGHT, aviso)
        self.assertIn(f"«{ATRIBUCION}»", " ".join(aviso.split()))

    def test_metadatos_con_el_nombre_del_autor(self):
        metadatos = configparser.ConfigParser()
        metadatos.read(COMPLEMENTO / "metadata.txt", encoding="utf-8")
        self.assertEqual(metadatos.get("general", "author"), AUTOR)


if __name__ == "__main__":
    unittest.main()
