"""Registro del complemento en la interfaz de QGIS."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

MENU = "&RiegoLibre"


class RiegoLibrePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.acciones = []
        self.dialogo_lateral = None

    def initGui(self):  # noqa: N802 (nombre exigido por QGIS)
        icono = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        accion = QAction(icono, "Calculadora de lateral (goteo)…", self.iface.mainWindow())
        accion.triggered.connect(self.abrir_calculadora_lateral)
        self.iface.addPluginToMenu(MENU, accion)
        self.iface.addToolBarIcon(accion)
        self.acciones.append(accion)

    def unload(self):
        for accion in self.acciones:
            self.iface.removePluginMenu(MENU, accion)
            self.iface.removeToolBarIcon(accion)
        self.acciones = []
        if self.dialogo_lateral is not None:
            self.dialogo_lateral.close()
            self.dialogo_lateral.deleteLater()
            self.dialogo_lateral = None

    def abrir_calculadora_lateral(self):
        if self.dialogo_lateral is None:
            from .gui.dialogo_lateral import DialogoLateral
            self.dialogo_lateral = DialogoLateral(self.iface, self.iface.mainWindow())
        self.dialogo_lateral.show()
        self.dialogo_lateral.raise_()
        self.dialogo_lateral.activateWindow()
