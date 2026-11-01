"""Registro del complemento en la interfaz de QGIS."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton

MENU = "&RiegoLibre"
CARPETA = os.path.dirname(__file__)


class RiegoLibrePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.menu = None  # menú propio en la barra de menús de QGIS
        self.barra = None  # barra de herramientas propia, con el mismo orden que el menú
        self.acciones = []
        self.dialogos = {}
        self.desactualizados = set()  # ventanas abiertas cuando cambió la base de datos
        self.accion_info = None
        self.menu_limites = None
        self.herramienta_info = None
        self.dialogo_info = None
        self.accion_bloque = None
        self.herramienta_bloque = None
        self.accion_turnos = None
        self.herramienta_turnos = None
        self.panel_turnos = None
        self.guardado_pendiente = False
        self.reescribiendo = False

    def initGui(self):  # noqa: N802 (nombre exigido por QGIS)
        ventana = self.iface.mainWindow()
        self.menu = QMenu(MENU, ventana)
        self.menu.setObjectName("menuRiegoLibre")
        ventana.menuBar().insertMenu(self.iface.firstRightStandardMenu().menuAction(), self.menu)
        self.barra = self.iface.addToolBar("RiegoLibre")
        self.barra.setObjectName("barraRiegoLibre")  # QGIS recuerda por este nombre dónde se dejó la barra
        self._agregar_grupo("Terreno y lotes", "icon_topografia.svg", (
            self._crear_accion("icon_topografia.svg", "Topografía: curvas de CAD, imagen satelital y 3D…",
                               "topografia"),
            self._crear_accion("icon_lotes.svg", "Importar lotes de CAD…", "lotes"),
            self._crear_accion("icon_zonas.svg", "Zonas: tabla de diseño de los lotes…", "zonas")))
        self._agregar_grupo("Diseño de goteo", "icon_subunidad.svg", (
            self._crear_accion("icon.svg", "Calculadora de lateral (goteo)…", "lateral"),
            self._crear_accion("icon_subunidad.svg", "Subunidad de riego (goteo)…", "subunidad"),
            self._crear_accion("icon_mapa.svg", "Diseño de subunidad en el mapa (goteo)…", "mapa"),
            self._crear_accion("icon_trazado.svg", "Trazado automático de subunidades (goteo)…", "trazado"),
            self._crear_accion("icon_diametros.svg", "Diámetros de portalaterales por velocidad…", "diametros")))
        # Las herramientas de mapa y lo que se abre seguido quedan a un clic, sin desplegar nada.
        self.accion_bloque = self._crear_herramienta(
            "icon_bloque.svg", "Bloque de goteo (clic en un lote; Ctrl + clic para eliminar su bloque)",
            self._activar_bloque)
        self._agregar_directa(self.accion_bloque)
        self._separar()
        self._agregar_directa(self._crear_accion("icon_red.svg", "Red principal y bomba…", "red"))
        self.accion_turnos = self._crear_herramienta(
            "icon_turnos.svg", "Turnos de riego (marcar bloques en el mapa y asignarles un turno)",
            self._activar_turnos)
        self._agregar_directa(self.accion_turnos)
        self._separar()
        self.accion_info = self._crear_herramienta(
            "icon_info.svg", "Información del objeto (clic en un lateral, tubería o válvula)", self._activar_info)
        self._agregar_directa(self.accion_info)
        self.menu_limites = self._agregar_grupo("Presión mínima y máxima", "icon_presion.svg", (
            self._crear_limite("Todas las válvulas", "Marca el emisor de menor y de mayor presión de cada "
                               "subunidad calculada", "todas"),
            self._crear_limite("Válvulas seleccionadas", "Lo mismo, solo de las válvulas o lotes que tenga "
                               "seleccionados en el mapa", "seleccionadas"),
            self._crear_limite("Borrar marcadores", "Quita los marcadores de presión del mapa", "borrar")))
        self._separar()
        self._agregar_grupo("Materiales y documentos", "icon_materiales.svg", (
            self._crear_accion("icon_base_datos.svg", "Base de datos de materiales…", "base_datos"),
            self._crear_accion("icon_materiales.svg", "Lista de materiales y costos…", "materiales"),
            self._crear_accion("icon_memoria.svg", "Memoria de cálculo…", "memoria")))
        from qgis.core import QgsProject
        proyecto = QgsProject.instance()
        proyecto.layersAdded.connect(self._programar_guardado)
        proyecto.projectSaved.connect(self._proyecto_guardado)
        self._programar_guardado()  # capas temporales que ya estaban (por ejemplo, al recargar el complemento)

    # Las capas que crea RiegoLibre nacen en memoria; se pasan al GeoPackage del proyecto en
    # cuanto termina la operación que las agregó (ya con sus entidades) y al guardar el proyecto.

    def _programar_guardado(self, *_):
        if not self.guardado_pendiente:
            from qgis.PyQt.QtCore import QTimer
            self.guardado_pendiente = True
            QTimer.singleShot(0, self._guardar_capas)

    def _guardar_capas(self):
        from .integracion.persistencia import guardar_capas_temporales
        self.guardado_pendiente = False
        try:
            return guardar_capas_temporales()
        except OSError as error:
            from qgis.core import Qgis
            self.iface.messageBar().pushMessage("RiegoLibre", str(error), Qgis.MessageLevel.Warning, 8)
            return []

    def _proyecto_guardado(self):
        """Al guardar un proyecto por primera vez, sus capas temporales pasan al GeoPackage y el
        proyecto se vuelve a escribir para que apunte a ellas."""
        if self.reescribiendo or not self._guardar_capas():
            return
        from qgis.core import QgsProject
        self.reescribiendo = True
        try:
            QgsProject.instance().write()
        finally:
            self.reescribiendo = False

    def _crear_accion(self, icono, texto, dialogo):
        accion = QAction(QIcon(os.path.join(CARPETA, icono)), texto, self.menu)
        accion.triggered.connect(lambda: self.abrir(dialogo))
        self.acciones.append(accion)
        return accion

    def _crear_herramienta(self, icono, texto, activar):
        """Herramienta de mapa: el botón queda hundido mientras está activa."""
        accion = QAction(QIcon(os.path.join(CARPETA, icono)), texto, self.menu)
        accion.setCheckable(True)
        accion.toggled.connect(activar)
        self.acciones.append(accion)
        return accion

    def _crear_limite(self, texto, ayuda, modo):
        """Opción del botón de presión, como el de IRRICAD: marcadores de presión mínima y máxima de todas las
        subunidades, de las seleccionadas, o borrarlos."""
        accion = QAction(QIcon(os.path.join(CARPETA, "icon_presion.svg")), texto, self.menu)
        accion.setToolTip(ayuda)
        accion.setStatusTip(ayuda)
        accion.triggered.connect(lambda _=False, m=modo: self._limites_presion(m))
        self.acciones.append(accion)
        return accion

    def _agregar_directa(self, accion):
        self.menu.addAction(accion)
        self.barra.addAction(accion)

    def _agregar_grupo(self, titulo, icono, acciones):
        """Submenú en el menú y, en la barra, un solo botón que despliega las mismas opciones."""
        grupo = self.menu.addMenu(QIcon(os.path.join(CARPETA, icono)), titulo)
        grupo.addActions(list(acciones))
        self.barra.addAction(grupo.menuAction())
        self.barra.widgetForAction(grupo.menuAction()).setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return grupo

    def _separar(self):
        self.menu.addSeparator()
        self.barra.addSeparator()

    def _limites_presion(self, modo):
        from qgis.core import Qgis
        from .integracion import limites_presion
        barra = self.iface.messageBar()
        try:
            if modo == "borrar":
                cantidad = limites_presion.borrar()
                texto = f"Se quitaron {cantidad} marcadores de presión." if cantidad else "No hay marcadores."
                barra.pushMessage("RiegoLibre", texto, Qgis.MessageLevel.Info, 5)
                return
            resumen = limites_presion.mostrar(solo_seleccionadas=(modo == "seleccionadas"))
        except ValueError as error:
            barra.pushMessage("RiegoLibre", str(error), Qgis.MessageLevel.Warning, 8)
            return
        finally:
            self.iface.mapCanvas().refresh()  # al quitar la capa el lienzo conserva los rótulos hasta repintar
        # La capa de marcadores queda activa al crearse y «Seleccionar objetos» solo actúa sobre la activa: se
        # devuelve la activa a los lotes para poder seguir eligiéndolos en el mapa.
        from .integracion.lotes import capas_de_lotes
        lotes = capas_de_lotes()
        if lotes:
            self.iface.setActiveLayer(lotes[0])
        plural = "subunidad" if resumen.subunidades == 1 else "subunidades"
        texto = f"Presión mínima y máxima marcada en {resumen.subunidades} {plural} ({resumen.marcadores} marcadores)."
        if resumen.sin_resultados:
            texto += " Sin laterales calculados: " + ", ".join(resumen.sin_resultados) + "."
        barra.pushMessage("RiegoLibre", texto, Qgis.MessageLevel.Info, 6)

    def _activar_turnos(self, activa):
        canvas = self.iface.mapCanvas()
        if activa:
            from .gui.herramienta_turnos import HerramientaTurnos, PanelTurnos
            if self.herramienta_turnos is None:
                self.panel_turnos = PanelTurnos(self.iface.mainWindow())
                self.panel_turnos.cambio.connect(self._turnos_cambiaron)
                self.herramienta_turnos = HerramientaTurnos(canvas, self.panel_turnos)
                self.herramienta_turnos.deactivated.connect(lambda: self.accion_turnos.setChecked(False))
            canvas.setMapTool(self.herramienta_turnos)
        elif self.herramienta_turnos is not None and canvas.mapTool() is self.herramienta_turnos:
            canvas.unsetMapTool(self.herramienta_turnos)

    def _turnos_cambiaron(self):
        """Se pintaron turnos en el mapa: la ventana de la red, si está abierta, los toma."""
        dialogo = self.dialogos.get("red")
        if dialogo is not None:
            dialogo.cargar_turnos_del_mapa()

    def _activar_bloque(self, activa):
        canvas = self.iface.mapCanvas()
        if activa:
            from .gui.herramienta_bloque import HerramientaBloque
            if self.herramienta_bloque is None:
                self.herramienta_bloque = HerramientaBloque(canvas, self._abrir_lote, self._avisar,
                                                            self._eliminar_bloque, self._deshacer_bloque)
                self.herramienta_bloque.deactivated.connect(lambda: self.accion_bloque.setChecked(False))
            canvas.setMapTool(self.herramienta_bloque)
        elif self.herramienta_bloque is not None and canvas.mapTool() is self.herramienta_bloque:
            canvas.unsetMapTool(self.herramienta_bloque)

    def _abrir_lote(self, capa, entidad):
        self.abrir("bloque", mostrar=False)
        self.dialogos["bloque"].abrir_lote(capa, entidad)

    def _eliminar_bloque(self, capa, entidad):
        self.abrir("bloque", mostrar=False)
        self.dialogos["bloque"].confirmar_eliminar(capa, entidad, self.iface.mainWindow())

    def _deshacer_bloque(self):
        self.abrir("bloque", mostrar=False)
        self.dialogos["bloque"].deshacer()

    def _avisar(self, texto):
        from qgis.core import Qgis
        self.iface.messageBar().pushMessage("RiegoLibre", texto, Qgis.MessageLevel.Info, 5)

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
        from qgis.core import QgsProject
        proyecto = QgsProject.instance()
        for senal, ranura in ((proyecto.layersAdded, self._programar_guardado),
                              (proyecto.projectSaved, self._proyecto_guardado)):
            try:
                senal.disconnect(ranura)
            except TypeError:
                pass
        if self.herramienta_bloque is not None:
            self.iface.mapCanvas().unsetMapTool(self.herramienta_bloque)
            self.herramienta_bloque = None
        from .integracion.bloque_mapa import olvidar_eliminaciones
        olvidar_eliminaciones()  # suelta las capas guardadas para deshacer
        if self.herramienta_turnos is not None:
            self.iface.mapCanvas().unsetMapTool(self.herramienta_turnos)
            self.herramienta_turnos = None
        if self.panel_turnos is not None:
            self.panel_turnos.close()
            self.panel_turnos.deleteLater()
            self.panel_turnos = None
        if self.herramienta_info is not None:
            self.iface.mapCanvas().unsetMapTool(self.herramienta_info)
            self.herramienta_info = None
        if self.dialogo_info is not None:
            self.dialogo_info.close()
            self.dialogo_info.deleteLater()
            self.dialogo_info = None
        ventana = self.iface.mainWindow()
        ventana.removeToolBar(self.barra)
        self.barra.deleteLater()
        self.barra = None
        ventana.menuBar().removeAction(self.menu.menuAction())
        self.menu.deleteLater()  # con él se van sus submenús y acciones
        self.menu = None
        self.menu_limites = None
        self.acciones = []
        for dialogo in self.dialogos.values():
            dialogo.close()
            dialogo.deleteLater()
        self.dialogos = {}

    def _base_cambiada(self):
        """Las ventanas leen los catálogos al crearse: las cerradas se descartan y las abiertas
        se rehacen la próxima vez que se abran."""
        for nombre, dialogo in list(self.dialogos.items()):
            if nombre == "base_datos":
                continue
            if dialogo.isVisible():
                self.desactualizados.add(nombre)
            else:
                dialogo.deleteLater()
                del self.dialogos[nombre]

    def abrir(self, nombre, mostrar=True):
        dialogo = self.dialogos.get(nombre)
        if dialogo is not None and nombre in self.desactualizados and not dialogo.isVisible():
            self.dialogos.pop(nombre).deleteLater()
            dialogo = None
        if dialogo is None:
            self.desactualizados.discard(nombre)
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
            elif nombre == "topografia":
                from .gui.dialogo_topografia import DialogoTopografia as Clase
            elif nombre == "materiales":
                from .gui.dialogo_materiales import DialogoMateriales as Clase
            elif nombre == "base_datos":
                from .gui.dialogo_base_datos import DialogoBaseDatos as Clase
            elif nombre == "lotes":
                from .gui.dialogo_lotes import DialogoLotes as Clase
            elif nombre == "bloque":
                from .gui.dialogo_bloque import DialogoBloque as Clase
            elif nombre == "diametros":
                from .gui.dialogo_diametros import DialogoDiametros as Clase
            elif nombre == "zonas":
                from .gui.dialogo_zonas import DialogoZonas as Clase
            else:
                from .gui.dialogo_memoria import DialogoMemoria as Clase
            dialogo = self.dialogos[nombre] = Clase(self.iface, self.iface.mainWindow())
            if nombre == "base_datos":
                dialogo.base_cambiada.connect(self._base_cambiada)
            elif nombre == "zonas":
                dialogo.abrir_lote = self._abrir_lote
            elif nombre == "red":
                dialogo.abrir_turnos = lambda: self.accion_turnos.setChecked(True)
        if not mostrar:
            return
        dialogo.show()
        dialogo.raise_()
        dialogo.activateWindow()
