# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Arranque del programa: `python -m riegolibre_app [proyecto.qgz]` con el Python de QGIS
(lo hace `RiegoLibre.bat`, en la raíz del repositorio)."""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argumentos=None):
    argumentos = list(sys.argv if argumentos is None else argumentos)
    if RAIZ not in sys.path:  # para importar el paquete del complemento, `riegolibre`
        sys.path.insert(0, RAIZ)
    from qgis.core import QgsApplication
    from qgis.PyQt.QtCore import QCoreApplication

    app = QgsApplication([a.encode() for a in argumentos], True)  # la API de QGIS pide bytes
    prefijo = os.environ.get("QGIS_PREFIX_PATH")
    if prefijo:
        QgsApplication.setPrefixPath(prefijo, True)
    app.initQgis()
    # Preferencias propias (tema, ventanas), aparte de las de QGIS.
    QCoreApplication.setOrganizationName("RiegoLibre")
    QCoreApplication.setApplicationName("RiegoLibre")

    from riegolibre_app.ventana import VentanaPrincipal
    ventana = VentanaPrincipal()
    ventana.showMaximized()
    proyecto = next((a for a in argumentos[1:] if a.lower().endswith((".qgz", ".qgs"))), None)
    if proyecto:
        ventana.abrir_proyecto(proyecto)
    codigo = app.exec()
    app.exitQgis()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
