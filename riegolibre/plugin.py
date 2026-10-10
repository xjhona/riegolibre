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
        self.accion_info = None
        self.herramienta_info = None
        self.dialogo_info = None

    def initGui(self):  # noqa: N802 (nombre exigido por QGIS)
        self._agregar_accion("icon.svg", "Calculadora de lateral (goteo)…", "lateral")
        self._agregar_accion("icon_subunidad.svg", "Subunidad de riego (goteo)…", "subunidad")
        self._agregar_accion("icon_mapa.svg", "Diseño de subunidad en el mapa (goteo)…", "mapa")
        self._agregar_accion("icon_trazado.svg", "Trazado automático de subunidades (goteo)…", "trazado")
        self._agregar_accion("icon_red.svg", "Red principal y bomba…", "red")
        self._agregar_accion("icon_materiales.svg", "Lista de materiales y costos…", "materiales")
        self._agregar_accion("icon_memoria.svg", "Memoria de cálculo…", "memoria")
        self._agregar_herramienta_info()

    def _agregar_accion(self, icono, texto, dialogo):
        accion = QAction(QIcon(os.path.join(CARPETA, icono)), texto, self.iface.mainWindow())
        accion.triggered.connect(lambda: self.abrir(dialogo))
        self.iface.addPluginToMenu(MENU, accion)
        self.iface.addToolBarIcon(accion)
        self.acciones.append(accion)

    def _agregar_herramienta_info(self):
        accion = QAction(QIcon(os.path.join(CARPETA, "icon_info.svg")),
                         "Información del objeto (clic en un lateral, tubería o válvula)", self.iface.mainWindow())
        accion.setCheckable(True)
        accion.toggled.connect(self._activar_info)
        self.iface.addPluginToMenu(MENU, accion)
        self.iface.addToolBarIcon(accion)
        self.accion_info = accion
        self.acciones.append(accion)

    def _activar_info(self, activa):
        canvas = self.iface.mapCanvas()
        if activa:
            from .gui.herramienta_info import DialogoInfo, HerramientaInfo
            if self.dialogo_info is None:
                self.dialogo_info = DialogoInfo(self.iface.mainWindow())
                self.herramienta_info = HerramientaInfo(canvas, self.dialogo_info)
                self.herramienta_info.deactivated.connect(lambda: self.accion_info.setChecked(False))
            canvas.setMapTool(self.herramienta_info)
        elif self.herramienta_info is not None and canvas.mapTool() is self.herramienta_info:
            canvas.unsetMapTool(self.herramienta_info)

    def unload(self):
        if self.herramienta_info is not None:
            self.iface.mapCanvas().unsetMapTool(self.herramienta_info)
            self.herramienta_info = None
        if self.dialogo_info is not None:
            self.dialogo_info.close()
            self.dialogo_info.deleteLater()
            self.dialogo_info = None
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
