"""Registro del complemento en la interfaz de QGIS."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

MENU = "&RiegoLibre"
CARPETA = os.path.dirname(__file__)


class RiegoLibrePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.acciones = []
        self.dialogos = {}

    def initGui(self):  # noqa: N802 (nombre exigido por QGIS)
        self._agregar_accion("icon.svg", "Calculadora de lateral (goteo)…", "lateral")
        self._agregar_accion("icon_subunidad.svg", "Subunidad de riego (goteo)…", "subunidad")
        self._agregar_accion("icon_mapa.svg", "Diseño de subunidad en el mapa (goteo)…", "mapa")
        self._agregar_accion("icon_trazado.svg", "Trazado automático de subunidades (goteo)…", "trazado")
        self._agregar_accion("icon_red.svg", "Red principal y bomba…", "red")
        self._agregar_accion("icon_materiales.svg", "Lista de materiales y costos…", "materiales")
        self._agregar_accion("icon_memoria.svg", "Memoria de cálculo…", "memoria")

    def _agregar_accion(self, icono, texto, dialogo):
        accion = QAction(QIcon(os.path.join(CARPETA, icono)), texto, self.iface.mainWindow())
        accion.triggered.connect(lambda: self.abrir(dialogo))
        self.iface.addPluginToMenu(MENU, accion)
        self.iface.addToolBarIcon(accion)
        self.acciones.append(accion)

    def unload(self):
        for accion in self.acciones:
            self.iface.removePluginMenu(MENU, accion)
            self.iface.removeToolBarIcon(accion)
        self.acciones = []
        for dialogo in self.dialogos.values():
            dialogo.close()
            dialogo.deleteLater()
        self.dialogos = {}

    def abrir(self, nombre):
        dialogo = self.dialogos.get(nombre)
        if dialogo is None:
            if nombre == "lateral":
                from .gui.dialogo_lateral import DialogoLateral as Clase
            elif nombre == "subunidad":
                from .gui.dialogo_subunidad import DialogoSubunidad as Clase
            elif nombre == "mapa":
                from .gui.dialogo_mapa import DialogoMapa as Clase
            elif nombre == "trazado":
                from .gui.dialogo_trazado import DialogoTrazado as Clase
            elif nombre == "red":
                from .gui.dialogo_red import DialogoRed as Clase
            elif nombre == "materiales":
                from .gui.dialogo_materiales import DialogoMateriales as Clase
            else:
                from .gui.dialogo_memoria import DialogoMemoria as Clase
            dialogo = self.dialogos[nombre] = Clase(self.iface, self.iface.mainWindow())
        dialogo.show()
        dialogo.raise_()
        dialogo.activateWindow()
