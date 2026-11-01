# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""RiegoLibre: diseño de riego tecnificado para QGIS."""


def classFactory(iface):  # noqa: N802 (nombre exigido por QGIS)
    from .plugin import RiegoLibrePlugin
    return RiegoLibrePlugin(iface)
