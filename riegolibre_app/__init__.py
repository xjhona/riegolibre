# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""RiegoLibre como programa independiente (prototipo).

Abre una ventana propia con el mapa, el panel de capas y los menús de RiegoLibre, sin la interfaz de QGIS.
Por dentro usa las librerías de QGIS (lienzo, capas, GDAL, GeoPackage), y las herramientas son las mismas
del complemento: la ventana le ofrece la misma interfaz (`iface`) que QGIS le da al complemento.
"""
