# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana principal del programa independiente.

Hace dos papeles: es la ventana que ve el usuario (mapa, capas, menús «Proyecto», «Capas» y «Ver») y es la
interfaz que el complemento espera de QGIS (`mapCanvas`, `messageBar`, `mainWindow`, `statusBarIface`,
`firstRightStandardMenu`, `addToolBar`, `setActiveLayer`, `actionAddFeature`). Así el complemento entra
tal cual, con todos sus menús, barras y herramientas de mapa.
"""

import os

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsLayerTreeModel, QgsMapLayer, QgsProject,
                       QgsRasterLayer, QgsVectorLayer, QgsWkbTypes)
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsLayerTreeMapCanvasBridge, QgsLayerTreeView,
                      QgsMapCanvas, QgsMapToolCapture, QgsMapToolDigitizeFeature, QgsMapToolPan,
                      QgsMapToolZoom, QgsMessageBar, QgsProjectionSelectionDialog)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (QAction, QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox,
                                 QPushButton, QVBoxLayout, QWidget)

CARPETA_COMPLEMENTO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "riegolibre")
FILTRO_PROYECTO = "Proyecto de RiegoLibre (*.qgz);;Proyecto QGIS sin comprimir (*.qgs)"
FILTRO_VECTOR = ("Capas vectoriales (*.gpkg *.shp *.geojson *.json *.dxf *.kml *.kmz *.csv);;"
                 "Todos los archivos (*.*)")
FILTRO_RASTER = "Rásteres (*.tif *.tiff *.asc *.img *.vrt *.jpg *.png);;Todos los archivos (*.*)"
MODOS_DE_CAPTURA = {
    Qgis.GeometryType.Point: QgsMapToolCapture.CaptureMode.CapturePoint,
    Qgis.GeometryType.Line: QgsMapToolCapture.CaptureMode.CaptureLine,
    Qgis.GeometryType.Polygon: QgsMapToolCapture.CaptureMode.CapturePolygon,
}


def _icono(nombre):
    return QIcon(os.path.join(CARPETA_COMPLEMENTO, nombre))


class VentanaPrincipal(QMainWindow):
    def __init__(self, cargar_complemento=True):
        super().__init__()
        from riegolibre.gui.tema import aplicar_tema
        aplicar_tema(self)
        self.setWindowIcon(_icono("icon.svg"))
        self.resize(1280, 800)
        self.proyecto = QgsProject.instance()

        self.lienzo = QgsMapCanvas()
        self.lienzo.setObjectName("theMapCanvas")  # el nombre de QGIS: la vista guardada se comparte con él
        self.lienzo.setCanvasColor(QColor(255, 255, 255))
        self.lienzo.enableAntiAliasing(True)
        self.barra_mensajes = QgsMessageBar()
        central = QWidget()
        disposicion = QVBoxLayout(central)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(0)
        disposicion.addWidget(self.barra_mensajes)
        disposicion.addWidget(self.lienzo)
        self.setCentralWidget(central)

        raiz = self.proyecto.layerTreeRoot()
        self.modelo_capas = QgsLayerTreeModel(raiz, self)
        for bandera in (QgsLayerTreeModel.Flag.AllowNodeReorder, QgsLayerTreeModel.Flag.AllowNodeRename,
                        QgsLayerTreeModel.Flag.AllowNodeChangeVisibility,
                        QgsLayerTreeModel.Flag.AllowLegendChangeState):
            self.modelo_capas.setFlag(bandera, True)
        self.arbol = QgsLayerTreeView()
        self.arbol.setModel(self.modelo_capas)
        self.puente = QgsLayerTreeMapCanvasBridge(raiz, self.lienzo, self)
        # Conexiones con objetos que viven más que la ventana (el proyecto y su árbol): se sueltan al cerrar.
        self._conexiones = []
        self.arbol.currentLayerChanged.connect(self._actualizar_punto_de_insercion)
        self.arbol.selectionModel().currentChanged.connect(self._actualizar_punto_de_insercion)
        # Se recalcula también cuando cambia el árbol: si se insertan grupos arriba, la posición guardada ya no sirve.
        self._conectar(raiz.addedChildren, self._actualizar_punto_de_insercion)
        self._conectar(raiz.removedChildren, self._actualizar_punto_de_insercion)
        # Como QGIS («autoSelectAddedLayer»): la capa que entra queda elegida y la siguiente va encima de ella.
        self._conectar(self.proyecto.layerTreeRegistryBridge().addedLayersToLayerTree, self._elegir_agregada)
        panel = QDockWidget("Capas", self)
        panel.setObjectName("PanelCapas")
        panel.setWidget(self.arbol)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, panel)
        # Panel de digitalización avanzada: lo exige la herramienta de agregar entidades; queda escondido.
        self.cad = QgsAdvancedDigitizingDockWidget(self.lienzo, self)
        self.cad.setObjectName("PanelDigitalizacion")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.cad)
        self.cad.hide()

        self.herramienta_desplazar = QgsMapToolPan(self.lienzo)
        self.herramienta_acercar = QgsMapToolZoom(self.lienzo, False)
        self.herramienta_alejar = QgsMapToolZoom(self.lienzo, True)
        self.herramienta_dibujo = None
        self._crear_menus()
        self._crear_barra_de_estado()
        self.lienzo.setMapTool(self.herramienta_desplazar)

        self._conectar(self.proyecto.crsChanged, self._src_cambiado)
        self._conectar(self.proyecto.layersAdded, self._capas_agregadas)
        # Al leer un proyecto el puente no pasa solo las capas al lienzo (QGIS lo hace desde su aplicación).
        self._conectar(self.proyecto.readProject, self._proyecto_leido)
        self._conectar(self.proyecto.isDirtyChanged, self._actualizar_titulo)
        self._conectar(self.proyecto.fileNameChanged, self._actualizar_titulo)
        self._src_cambiado()
        self._actualizar_titulo()

        self.complemento = None
        if cargar_complemento:
            from riegolibre import classFactory
            self.complemento = classFactory(self)
            self.complemento.initGui()

    # ------------------------------------------------------------ interfaz que espera el complemento

    def mapCanvas(self):  # noqa: N802 (nombres de la interfaz de QGIS)
        return self.lienzo

    def mainWindow(self):  # noqa: N802
        return self

    def messageBar(self):  # noqa: N802
        return self.barra_mensajes

    def statusBarIface(self):  # noqa: N802
        return self.statusBar()

    def firstRightStandardMenu(self):  # noqa: N802
        return self.menu_ayuda

    def activeLayer(self):  # noqa: N802
        return self.arbol.currentLayer()

    def setActiveLayer(self, capa):  # noqa: N802
        self.arbol.setCurrentLayer(capa)
        return True

    def actionAddFeature(self):  # noqa: N802
        return self.accion_agregar_entidad

    # ------------------------------------------------------------ menús y barras

    def _accion(self, texto, funcion, atajo=None, icono=None, ayuda=None):
        accion = QAction(texto, self)
        if icono is not None:
            accion.setIcon(icono)
        if atajo is not None:
            accion.setShortcut(QKeySequence(atajo))
        if ayuda:
            accion.setToolTip(ayuda)
            accion.setStatusTip(ayuda)
        accion.triggered.connect(funcion)
        return accion

    def _crear_menus(self):
        barra = self.menuBar()
        proyecto = barra.addMenu("&Proyecto")
        proyecto.addAction(self._accion("Nuevo", self.nuevo_proyecto, QKeySequence.StandardKey.New))
        proyecto.addAction(self._accion("Abrir…", self._elegir_proyecto, QKeySequence.StandardKey.Open))
        proyecto.addAction(self._accion("Guardar", self.guardar, QKeySequence.StandardKey.Save))
        proyecto.addAction(self._accion("Guardar como…", self.guardar_como, "Ctrl+Shift+S"))
        proyecto.addSeparator()
        proyecto.addAction(self._accion("Sistema de coordenadas del proyecto…", self.elegir_src))
        proyecto.addSeparator()
        proyecto.addAction(self._accion("Salir", self.close, "Ctrl+Q"))

        capas = barra.addMenu("&Capas")
        capas.addAction(self._accion("Agregar capa vectorial…", self._elegir_vector, "Ctrl+Shift+V",
                                     ayuda="GeoPackage, Shapefile, GeoJSON, DXF, KML o CSV"))
        capas.addAction(self._accion("Agregar ráster…", self._elegir_raster, "Ctrl+Shift+R",
                                     ayuda="DEM o imagen georreferenciada"))
        capas.addSeparator()
        self.accion_editar = self._accion("Editar la capa activa", self._conmutar_edicion)
        self.accion_editar.setCheckable(True)
        capas.addAction(self.accion_editar)
        self.accion_agregar_entidad = self._accion(
            "Agregar entidad", self._agregar_entidad, "Ctrl+.",
            ayuda="Dibuja en la capa activa: clic para cada vértice, clic derecho para terminar")
        capas.addAction(self.accion_agregar_entidad)
        capas.addAction(self._accion("Guardar las ediciones", self._guardar_ediciones))
        capas.addSeparator()
        capas.addAction(self._accion("Acercar a la capa", self._acercar_a_la_capa))
        capas.addAction(self._accion("Quitar la capa", self._quitar_capa, QKeySequence.StandardKey.Delete))

        ver = barra.addMenu("&Ver")
        self.navegacion = self.addToolBar("Navegación")
        self.navegacion.setObjectName("BarraNavegacion")
        from qgis.core import QgsApplication
        for texto, funcion, atajo, icono in (
                ("Desplazar el mapa", lambda: self.lienzo.setMapTool(self.herramienta_desplazar), "Ctrl+1",
                 "/mActionPan.svg"),
                ("Acercar", lambda: self.lienzo.setMapTool(self.herramienta_acercar), "Ctrl+2", "/mActionZoomIn.svg"),
                ("Alejar", lambda: self.lienzo.setMapTool(self.herramienta_alejar), "Ctrl+3", "/mActionZoomOut.svg"),
                ("Toda la extensión", self.lienzo.zoomToFullExtent, "Ctrl+Shift+F", "/mActionZoomFullExtent.svg")):
            accion = self._accion(texto, funcion, atajo, QgsApplication.getThemeIcon(icono), texto)
            ver.addAction(accion)
            self.navegacion.addAction(accion)
        ver.addSeparator()
        ver.addAction(self._accion("Actualizar el mapa", self.lienzo.refreshAllLayers, "F5"))

        self.menu_ayuda = barra.addMenu("Ayuda")
        self.menu_ayuda.addAction(self._accion("Acerca de RiegoLibre…", self._acerca_de))

    def _crear_barra_de_estado(self):
        barra = self.statusBar()
        self.etiqueta_coordenadas = QLabel()
        self.etiqueta_escala = QLabel()
        self.boton_src = QPushButton()
        self.boton_src.setFlat(True)
        self.boton_src.setToolTip("Sistema de coordenadas del proyecto")
        self.boton_src.clicked.connect(self.elegir_src)
        barra.addPermanentWidget(self.etiqueta_coordenadas)
        barra.addPermanentWidget(self.etiqueta_escala)
        barra.addPermanentWidget(self.boton_src)
        self.lienzo.xyCoordinates.connect(
            lambda p: self.etiqueta_coordenadas.setText(f"Coordenada  {p.x():,.1f}  {p.y():,.1f}"))
        self.lienzo.scaleChanged.connect(lambda e: self.etiqueta_escala.setText(f"Escala 1:{e:,.0f}"))

    # ------------------------------------------------------------ proyecto

    def _actualizar_titulo(self, *_):
        nombre = self.proyecto.baseName() or "Proyecto sin título"
        marca = "*" if self.proyecto.isDirty() else ""
        self.setWindowTitle(f"{marca}{nombre} — RiegoLibre")

    def _src_cambiado(self):
        crs = self.proyecto.crs()
        self.lienzo.setDestinationCrs(crs)
        self.boton_src.setText(crs.authid() if crs.isValid() else "Sin SRC")

    def _capas_agregadas(self, capas):
        """El primer SRC del proyecto lo da la primera capa que llega (como en QGIS)."""
        if self.proyecto.crs().isValid():
            return
        crs = next((c.crs() for c in capas if c.crs().isValid()), None)
        if crs is not None:
            self.proyecto.setCrs(crs)
            self.lienzo.zoomToFullExtent()

    def _descartar_cambios(self):
        """True si se puede seguir: no hay cambios, se guardaron o el usuario los descarta."""
        if not self.proyecto.isDirty() or not self.proyecto.count():
            return True
        respuesta = QMessageBox.question(
            self, "RiegoLibre", "El proyecto tiene cambios sin guardar. ¿Guardarlos?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if respuesta == QMessageBox.StandardButton.Save:
            return self.guardar()
        return respuesta == QMessageBox.StandardButton.Discard

    def nuevo_proyecto(self, preguntar=True):
        if preguntar and not self._descartar_cambios():
            return False
        self.proyecto.clear()
        self.proyecto.setCrs(QgsCoordinateReferenceSystem())
        self.lienzo.refresh()
        self._actualizar_titulo()
        return True

    def _elegir_proyecto(self):
        if not self._descartar_cambios():
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", "Proyectos (*.qgz *.qgs)")
        if ruta:
            self.abrir_proyecto(ruta)

    def abrir_proyecto(self, ruta):
        if not self.proyecto.read(ruta):
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo abrir el proyecto:\n{self.proyecto.error()}")
            return False
        self.puente.setCanvasLayers()
        if self.lienzo.extent().isEmpty():
            self.lienzo.zoomToFullExtent()
        self._actualizar_titulo()
        return True

    def guardar(self):
        if not self.proyecto.fileName():
            return self.guardar_como()
        return self.guardar_en(self.proyecto.fileName())

    def guardar_como(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", "", FILTRO_PROYECTO)
        if not ruta:
            return False
        if not ruta.lower().endswith((".qgz", ".qgs")):
            ruta += ".qgz"
        return self.guardar_en(ruta)

    def guardar_en(self, ruta):
        # Al guardar, el complemento pasa sus capas temporales al GeoPackage junto al proyecto.
        if not self.proyecto.write(ruta):
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo guardar el proyecto:\n{self.proyecto.error()}")
            return False
        self.barra_mensajes.pushMessage("RiegoLibre", f"Proyecto guardado en {ruta}", Qgis.MessageLevel.Success, 4)
        self._actualizar_titulo()
        return True

    def elegir_src(self):
        dialogo = QgsProjectionSelectionDialog(self)
        dialogo.setCrs(self.proyecto.crs())
        if dialogo.exec():
            self.proyecto.setCrs(dialogo.crs())

    # ------------------------------------------------------------ capas

    def _elegir_vector(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Agregar capa vectorial", "", FILTRO_VECTOR)
        if ruta:
            self.agregar_vector(ruta)

    def agregar_vector(self, ruta, nombre=None):
        capa = QgsVectorLayer(ruta, nombre or os.path.splitext(os.path.basename(ruta))[0], "ogr")
        return self._agregar_capa(capa, ruta)

    def _elegir_raster(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Agregar ráster", "", FILTRO_RASTER)
        if ruta:
            self.agregar_raster(ruta)

    def agregar_raster(self, ruta, nombre=None):
        capa = QgsRasterLayer(ruta, nombre or os.path.splitext(os.path.basename(ruta))[0])
        return self._agregar_capa(capa, ruta)

    def _agregar_capa(self, capa, ruta):
        if not capa.isValid():
            self.barra_mensajes.pushMessage("RiegoLibre", f"No se pudo leer {ruta}", Qgis.MessageLevel.Warning, 6)
            return None
        self.proyecto.addMapLayer(capa)
        self.setActiveLayer(capa)
        return capa

    def punto_de_insercion(self):
        """Dónde entra una capa nueva, como en QGIS: dentro del grupo elegido (arriba) o encima de la capa
        elegida; sin nada elegido, arriba de todo."""
        from qgis.core import QgsLayerTree, QgsLayerTreeRegistryBridge
        raiz = self.proyecto.layerTreeRoot()
        nodo = self.arbol.index2node(self.arbol.currentIndex()) if self.arbol.currentIndex().isValid() else None
        if nodo is not None and QgsLayerTree.isGroup(nodo):
            return QgsLayerTreeRegistryBridge.InsertionPoint(nodo, 0)
        if nodo is not None and QgsLayerTree.isLayer(nodo) and nodo.parent() is not None:
            padre = nodo.parent()
            return QgsLayerTreeRegistryBridge.InsertionPoint(padre, padre.children().index(nodo))
        return QgsLayerTreeRegistryBridge.InsertionPoint(raiz, 0)

    def _actualizar_punto_de_insercion(self, *_):
        self.proyecto.layerTreeRegistryBridge().setLayerInsertionPoint(self.punto_de_insercion())

    def _elegir_agregada(self, capas):
        if capas:
            self.arbol.setCurrentLayer(capas[0])

    def _proyecto_leido(self, *_):
        self.puente.setCanvasLayers()

    def _conectar(self, senal, ranura):
        senal.connect(ranura)
        self._conexiones.append((senal, ranura))

    def liberar(self):
        """Descarga el complemento y suelta el proyecto: lo que la ventana conectó ya no actúa y las capas
        nuevas vuelven a entrar arriba de todo."""
        from qgis.core import QgsLayerTreeRegistryBridge
        if self.complemento is not None:
            self.complemento.unload()
            self.complemento = None
        for senal, ranura in self._conexiones:
            try:
                senal.disconnect(ranura)
            except (TypeError, RuntimeError):
                pass
        self._conexiones = []
        self.proyecto.layerTreeRegistryBridge().setLayerInsertionPoint(
            QgsLayerTreeRegistryBridge.InsertionPoint(self.proyecto.layerTreeRoot(), 0))

    def _capa_vectorial_activa(self):
        capa = self.activeLayer()
        if capa is None or capa.type() != QgsMapLayer.LayerType.VectorLayer:
            self.barra_mensajes.pushMessage("RiegoLibre", "Elija una capa vectorial en el panel de capas.",
                                            Qgis.MessageLevel.Info, 4)
            return None
        return capa

    def _conmutar_edicion(self, activa):
        capa = self._capa_vectorial_activa()
        if capa is None:
            self.accion_editar.setChecked(False)
            return
        if activa:
            capa.startEditing()
        elif capa.isEditable():
            self._guardar_ediciones()

    def _agregar_entidad(self):
        capa = self._capa_vectorial_activa()
        if capa is None:
            return None
        if not capa.isEditable():
            capa.startEditing()
        self.accion_editar.setChecked(True)
        modo = MODOS_DE_CAPTURA.get(QgsWkbTypes.geometryType(capa.wkbType()))
        if modo is None:
            return None
        herramienta = QgsMapToolDigitizeFeature(self.lienzo, self.cad, modo)
        herramienta.setLayer(capa)

        def terminada(entidad, capa=capa):
            from qgis.core import QgsFeature
            nueva = QgsFeature(capa.fields())
            nueva.setGeometry(entidad.geometry())
            capa.addFeature(nueva)
            capa.triggerRepaint()
        herramienta.digitizingCompleted.connect(terminada)
        self.herramienta_dibujo = herramienta
        self.lienzo.setMapTool(herramienta)
        return herramienta

    def _guardar_ediciones(self):
        capa = self._capa_vectorial_activa()
        if capa is not None and capa.isEditable() and not capa.commitChanges():
            QMessageBox.warning(self, "RiegoLibre", "No se guardaron las ediciones:\n" + "\n".join(capa.commitErrors()))
        self.accion_editar.setChecked(bool(capa is not None and capa.isEditable()))

    def _acercar_a_la_capa(self):
        capa = self.activeLayer()
        if capa is not None:
            extension = self.lienzo.mapSettings().layerExtentToOutputExtent(capa, capa.extent())
            self.lienzo.setExtent(extension)
            self.lienzo.refresh()

    def _quitar_capa(self):
        capa = self.activeLayer()
        if capa is not None:
            self.proyecto.removeMapLayer(capa.id())

    # ------------------------------------------------------------ ayuda y cierre

    def _acerca_de(self):
        if self.complemento is not None:
            self.complemento.abrir("acerca")

    def closeEvent(self, evento):  # noqa: N802
        if not self._descartar_cambios():
            evento.ignore()
            return
        self.liberar()
        evento.accept()
