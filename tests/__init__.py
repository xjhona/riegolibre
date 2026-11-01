# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Pruebas de RiegoLibre."""

import os
import tempfile

# Las pruebas no deben leer ni modificar la base de datos de materiales del usuario.
os.environ["RIEGOLIBRE_BASE"] = os.path.join(tempfile.gettempdir(), "riegolibre_pruebas_sin_base",
                                             "base_datos.json")
