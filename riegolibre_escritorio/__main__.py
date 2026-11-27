# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Arranque del programa de escritorio: `python -m riegolibre_escritorio [proyecto.riegolibre | diseño_datos.json]`.

No usa QGIS: basta Python con PySide6 (ver `requisitos_escritorio.txt`). `RiegoLibre_escritorio.bat`, en la raíz
del repositorio, lo abre con doble clic.
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argumentos=None):
    argumentos = list(sys.argv if argumentos is None else argumentos)
    if RAIZ not in sys.path:  # para importar `riegolibre.nucleo` y `mcp_riegolibre`
        sys.path.insert(0, RAIZ)
    from PySide6.QtWidgets import QApplication

    from riegolibre_escritorio.estilo import aplicar_tema, traducir_qt
    from riegolibre_escritorio.ventana import VentanaPrincipal

    app = QApplication(argumentos)
    app.setOrganizationName("RiegoLibre")
    app.setApplicationName("RiegoLibre")
    traducir_qt(app)
    aplicar_tema(app)
    ventana = VentanaPrincipal()
    ventana.showMaximized()
    ruta = next((a for a in argumentos[1:] if not a.startswith("-")), None)
    if ruta:
        if ruta.lower().endswith(".json"):
            ventana.importar_mcp(ruta)
        else:
            ventana.abrir(ruta)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
