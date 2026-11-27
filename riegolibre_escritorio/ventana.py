# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana principal del programa: mapa, barra de herramientas de dibujo, panel de capas, tablas, menús.

La ventana es el «editor» de las herramientas del mapa (`herramientas.py`): recibe los datos nuevos del diseño
y los guarda con deshacer (`QUndoStack`); cada cambio vuelve a calcular solo los lotes que cambiaron y, si la
red principal estaba calculada, también la red.
"""

import copy
import os
from typing import Optional

from PySide6.QtCore import QEventLoop, QRectF, QThread, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QFileDialog, QHeaderView, QLabel, QMainWindow,
                               QMessageBox, QProgressDialog, QTableWidget, QTableWidgetItem, QToolBar)

from . import VERSION, archivo, edicion, fichas, herramientas
from .barra_capas import BarraCapas
from .dialogo_bloque import DialogoBloque
from .dialogos import DialogoFicha, DialogoNuevo, DialogoTurnos, TablaAtributos
from .dialogo_red import DialogoRed
from .estilo import ROJO, TEMAS, VERDE, aplicar_tema, tema_actual
from .lienzo import Lienzo, dibujar_proyecto
from .modelo import ProyectoRiego

FILTRO_PROYECTO = f"Proyecto de RiegoLibre (*{archivo.EXTENSION})"
FILTRO_MCP = "Diseño del servidor MCP (*_datos.json)"


class _Trabajo(QThread):
    terminado = Signal()

    def __init__(self, funcion):
        super().__init__()
        self.funcion, self.resultado, self.error = funcion, None, None

    def run(self):
        try:
            self.resultado = self.funcion()
        except Exception as error:  # se vuelve a lanzar en el hilo de la ventana
            self.error = error


def en_segundo_plano(ventana, texto: str, funcion):
    """Corre `funcion` en otro hilo con un aviso de espera, sin congelar la ventana; devuelve su resultado."""
    trabajo = _Trabajo(funcion)
    aviso = QProgressDialog(texto, None, 0, 0, ventana)
    aviso.setWindowTitle("RiegoLibre")
    aviso.setWindowModality(Qt.WindowModality.WindowModal)
    aviso.setMinimumDuration(300)
    bucle = QEventLoop()
    trabajo.finished.connect(bucle.quit)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        trabajo.start()
        bucle.exec()
        trabajo.wait()
    finally:
        QApplication.restoreOverrideCursor()
        aviso.close()
    if trabajo.error is not None:
        raise trabajo.error
    return trabajo.resultado


class CambioDatos(QUndoCommand):
    """Un cambio del diseño: guarda los datos de antes y de después."""

    def __init__(self, ventana, antes: dict, despues: dict, texto: str):
        super().__init__(texto)
        self.ventana, self.antes, self.despues = ventana, antes, despues

    def redo(self):
        self.ventana._poner_datos(self.despues)

    def undo(self):
        self.ventana._poner_datos(self.antes)


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.proyecto = ProyectoRiego()
        self.dialogo_red: Optional[DialogoRed] = None
        self.dialogo_ficha: Optional[DialogoFicha] = None
        self.pila = QUndoStack(self)
        self._ocupado = False
        self.resize(1280, 820)

        self.lienzo = Lienzo(self)
        self.setCentralWidget(self.lienzo)
        self.lienzo.coordenadas.connect(self._mostrar_coordenadas)

        self.barra_capas = BarraCapas()
        self.barra_capas.visibilidad.connect(self._visibilidad_capa)
        self.barra_capas.estilo_cambiado.connect(self._estilo_capa)
        dock = QDockWidget("Barra de capas", self)
        dock.setObjectName("capas")
        dock.setWidget(self.barra_capas)
        dock.setMinimumWidth(230)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.dock_capas = dock

        self.tabla_subunidades = QTableWidget(0, 9)
        self.tabla_subunidades.setHorizontalHeaderLabels(
            ["Subunidad", "Lote", "Turno", "Área (ha)", "Caudal (m³/h)", "P válvula (m)", "Variación (%)",
             "Portalateral", "Estado"])
        self.tabla_subunidades.verticalHeader().setVisible(False)
        self.tabla_subunidades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabla_subunidades.horizontalHeader().setStretchLastSection(True)
        self.tabla_subunidades.itemDoubleClicked.connect(self._ir_a_subunidad)
        dock = QDockWidget("Subunidades", self)
        dock.setObjectName("subunidades")
        dock.setWidget(self.tabla_subunidades)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.dock_subunidades = dock

        self.tabla_atributos = TablaAtributos()
        self.tabla_atributos.elegido.connect(self._elegir_en_tabla)
        self.tabla_atributos.abrir_lote.connect(self.editar_lote)
        dock = QDockWidget("Tabla de atributos", self)
        dock.setObjectName("atributos")
        dock.setWidget(self.tabla_atributos)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.tabifyDockWidget(self.dock_subunidades, dock)
        self.dock_subunidades.raise_()
        self.dock_atributos = dock

        self.etiqueta_coordenadas = QLabel()
        self.etiqueta_escala = QLabel()
        self.etiqueta_src = QLabel()
        for etiqueta in (self.etiqueta_coordenadas, self.etiqueta_escala, self.etiqueta_src):
            self.statusBar().addPermanentWidget(etiqueta)

        self._crear_acciones()
        self._crear_herramientas()
        self._actualizar()

    # ------------------------------------------------------------ menús

    def _accion(self, texto, funcion, atajo=None, ayuda=None):
        accion = QAction(texto, self)
        accion.triggered.connect(funcion)
        if atajo:
            accion.setShortcut(QKeySequence(atajo))
        if ayuda:
            accion.setStatusTip(ayuda)
        return accion

    def _crear_acciones(self):
        a = self.acciones = {
            "nuevo": self._accion("&Nuevo", self.nuevo, QKeySequence.StandardKey.New),
            "abrir": self._accion("&Abrir…", self.abrir, QKeySequence.StandardKey.Open),
            "guardar": self._accion("&Guardar", self.guardar, QKeySequence.StandardKey.Save),
            "guardar_como": self._accion("Guardar &como…", self.guardar_como, "Ctrl+Shift+S"),
            "importar_mcp": self._accion("&Importar diseño del MCP…", self.importar_mcp, "Ctrl+I",
                                         "Abre el …_datos.json que escribe exportar_proyecto del servidor MCP"),
            "memoria": self._accion("Exportar &memoria de cálculo (HTML)…", self.exportar_memoria),
            "salir": self._accion("&Salir", self.close, QKeySequence.StandardKey.Quit),
            "ver_todo": self._accion("&Toda la extensión", self.lienzo.ver_todo, "Ctrl+Shift+F"),
            "acercar": self._accion("A&cercar", self.lienzo.acercar, QKeySequence.StandardKey.ZoomIn),
            "alejar": self._accion("A&lejar", self.lienzo.alejar, QKeySequence.StandardKey.ZoomOut),
            "red": self._accion("&Red principal y bomba…", self.abrir_red, "Ctrl+R",
                                "Une las válvulas a la matriz, dimensiona la red y calcula la bomba"),
            "acerca": self._accion("&Acerca de RiegoLibre", self.acerca_de),
            "deshacer": self._accion("&Deshacer", self.deshacer, QKeySequence.StandardKey.Undo),
            "rehacer": self._accion("&Rehacer", self.rehacer, "Ctrl+Y"),
            "goteo": self._accion("&Bloque de goteo del proyecto…", self.editar_goteo, None,
                                  "Emisor, lateral, hileras, portalateral y válvula para todos los lotes"),
            "bloque": self._accion("Bloque de goteo del &lote seleccionado…", self.editar_lote_seleccionado,
                                   "Ctrl+B"),
            "turnos": self._accion("&Turnos de riego…", self.editar_turnos, "Ctrl+T"),
            "borrar": self._accion("&Borrar lo seleccionado", self.borrar_seleccion),
        }
        a["rehacer"].setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        a["borrar"].setShortcut(QKeySequence(QKeySequence.StandardKey.Delete))
        a["borrar"].setShortcutContext(Qt.ShortcutContext.WidgetShortcut)  # Supr lo atiende el mapa
        self.pila.indexChanged.connect(lambda _=None: self._estado_deshacer())
        menu = self.menuBar().addMenu("&Proyecto")
        for clave in ("nuevo", "abrir", "guardar", "guardar_como", None, "importar_mcp", "memoria", None, "salir"):
            menu.addSeparator() if clave is None else menu.addAction(a[clave])
        menu = self.menuBar().addMenu("&Editar")
        for clave in ("deshacer", "rehacer", None, "borrar", None, "bloque", "goteo", "turnos"):
            menu.addSeparator() if clave is None else menu.addAction(a[clave])
        self.menu_dibujo = self.menuBar().addMenu("&Dibujo")
        menu = self.menuBar().addMenu("&Ver")
        for clave in ("ver_todo", "acercar", "alejar"):
            menu.addAction(a[clave])
        menu.addSeparator()
        menu.addAction(self.dock_capas.toggleViewAction())
        menu.addAction(self.dock_subunidades.toggleViewAction())
        menu.addAction(self.dock_atributos.toggleViewAction())
        temas = menu.addMenu("T&ema")
        grupo = QActionGroup(self)
        for nombre, texto in TEMAS.items():
            accion = temas.addAction(texto)
            accion.setCheckable(True)
            accion.setChecked(nombre == tema_actual())
            accion.triggered.connect(lambda _=False, n=nombre: aplicar_tema(QApplication.instance(), n))
            grupo.addAction(accion)
        menu = self.menuBar().addMenu("&Red y bomba")
        menu.addAction(a["red"])
        menu = self.menuBar().addMenu("A&yuda")
        menu.addAction(a["acerca"])

        barra = QToolBar("Herramientas", self)
        barra.setObjectName("herramientas")
        barra.setMovable(False)
        barra.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        for clave in ("nuevo", "abrir", "guardar", "importar_mcp", None, "deshacer", "rehacer", None, "ver_todo",
                      "acercar", "alejar", None, "turnos", "red"):
            barra.addSeparator() if clave is None else barra.addAction(a[clave])
        self.addToolBar(barra)
        self._estado_deshacer()

    def _crear_herramientas(self):
        """Barra vertical de dibujo a la izquierda, como en IRRICAD; una herramienta activa a la vez."""
        textos = {"seleccion": ("↖  Seleccionar", "Seleccionar y editar lotes, tramos de matriz y la fuente"),
                  "lote": ("▱  Lote", "Dibujar un lote (área de riego): clics en sus vértices"),
                  "fuente": ("◉  Fuente de agua", "Ubicar la fuente de agua (bomba y cabezal); reemplaza la anterior"),
                  "matriz": ("╱  Tubería matriz", "Dibujar la tubería matriz desde la fuente"),
                  "info": ("ⓘ  Información", "Información del objeto: clic en un lote, válvula, tramo o fuente")}
        barra = QToolBar("Dibujo", self)
        barra.setObjectName("dibujo")
        barra.setMovable(False)
        barra.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        grupo = QActionGroup(self)
        self.herramientas = {}
        self.acciones_herramientas = {}
        for clase in herramientas.HERRAMIENTAS:
            herramienta = clase(self.lienzo, self)
            texto, ayuda = textos[clase.nombre]
            accion = QAction(texto, self)
            accion.setCheckable(True)
            accion.setToolTip(ayuda)
            accion.setStatusTip(ayuda)
            accion.triggered.connect(lambda _=False, n=clase.nombre: self.usar_herramienta(n))
            grupo.addAction(accion)
            barra.addAction(accion)
            self.menu_dibujo.addAction(accion)
            self.herramientas[clase.nombre] = herramienta
            self.acciones_herramientas[clase.nombre] = accion
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, barra)
        botones = [barra.widgetForAction(a) for a in self.acciones_herramientas.values()]
        ancho = max(b.sizeHint().width() for b in botones)
        for boton in botones:  # todos del mismo ancho, alineados a la izquierda
            boton.setFixedWidth(ancho)
            boton.setStyleSheet("text-align: left; padding-left: 8px;")
        self.barra_dibujo = barra
        self.usar_herramienta("seleccion")

    def usar_herramienta(self, nombre: str):
        self.acciones_herramientas[nombre].setChecked(True)
        self.lienzo.fijar_herramienta(self.herramientas[nombre])
        self.lienzo.setFocus()

    @property
    def seleccion(self):
        return self.herramientas["seleccion"].seleccion if hasattr(self, "herramientas") else None

    def _estado_deshacer(self):
        try:
            self.pila.index()
        except RuntimeError:  # la ventana se está cerrando
            return
        a = self.acciones
        a["deshacer"].setEnabled(self.pila.canUndo())
        a["rehacer"].setEnabled(self.pila.canRedo())
        a["deshacer"].setText("&Deshacer: " + self.pila.undoText() if self.pila.canUndo() else "&Deshacer")
        a["rehacer"].setText("&Rehacer: " + self.pila.redoText() if self.pila.canRedo() else "&Rehacer")

    # ------------------------------------------------------------ editor (lo usan las herramientas)

    def datos(self) -> dict:
        return self.proyecto.datos

    def mensaje(self, texto: str):
        self.statusBar().showMessage(texto)

    def aplicar(self, datos: dict, texto: str):
        """Guarda los datos nuevos del diseño con deshacer y vuelve a calcular lo que cambió."""
        if self._ocupado or datos == self.proyecto.datos:
            return
        self.pila.push(CambioDatos(self, copy.deepcopy(self.proyecto.datos), copy.deepcopy(datos), texto))

    def _poner_datos(self, datos: dict):
        p = self.proyecto
        habia_red = p.red is not None or bool(p.error_red)
        p.datos = copy.deepcopy(datos)
        self._ocupado = True
        self.lienzo.setEnabled(False)
        try:
            try:
                en_segundo_plano(self, "Calculando los lotes…", p.disenar)
            except ValueError as error:  # nombres repetidos u otro dato que impide todo el cálculo
                p.errores.append(str(error))
            if habia_red and p.subunidades:
                try:
                    p.calcular_red()
                except ValueError:
                    pass  # queda en p.error_red y se ve en la ventana de la red
        finally:
            self._ocupado = False
            self.lienzo.setEnabled(True)
            self.lienzo.setFocus()
        self._actualizar(conservar_vista=True)
        if self.dialogo_red is not None:
            self.dialogo_red.mostrar()
        self._marcar(True)
        if p.errores:
            self.statusBar().showMessage("Lotes con errores: " + " | ".join(p.errores), 15000)
        elif habia_red and p.error_red:
            self.statusBar().showMessage(f"Red principal: {p.error_red}", 15000)

    def deshacer(self):
        if not self._ocupado:
            self.pila.undo()

    def rehacer(self):
        if not self._ocupado:
            self.pila.redo()

    def seleccion_cambiada(self, objeto):
        self.tabla_atributos.marcar(objeto)
        self.acciones["bloque"].setEnabled(bool(objeto and objeto[0] == "lote"))

    def _elegir_en_tabla(self, objeto):
        self.usar_herramienta("seleccion")
        self.herramientas["seleccion"].seleccionar(objeto)
        puntos = [p for anillo in edicion.vertices(self.proyecto.datos, objeto) for p in anillo]
        if puntos:
            xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
            a, b = self.lienzo.a_escena(min(xs), max(ys)), self.lienzo.a_escena(max(xs), min(ys))
            self.lienzo.fitInView(QRectF(a, b).adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
            self._mostrar_escala()

    def mostrar_ficha(self, x, y, tolerancia):
        ficha = fichas.ficha_en(self.proyecto, (x, y), tolerancia)
        if ficha is None:
            self.mensaje("No hay ningún objeto en ese punto.")
            return
        if self.dialogo_ficha is None:
            self.dialogo_ficha = DialogoFicha(self)
        self.dialogo_ficha.mostrar(ficha)
        self.dialogo_ficha.show()
        self.dialogo_ficha.raise_()

    def _dialogo_bloque(self, indice):
        try:
            return DialogoBloque(self.proyecto.datos, indice, parent=self)
        except Exception as error:  # la base de datos de materiales puede faltar o estar dañada
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo abrir el bloque de goteo:\n{error}")
            return None

    def editar_lote(self, indice: int):
        """Cuadro del bloque de goteo del lote (también al terminar de dibujarlo)."""
        datos = self.proyecto.datos
        if not 0 <= indice < len(datos.get("lotes", [])):
            return
        dialogo = self._dialogo_bloque(indice)
        if dialogo is None or dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self.aplicar_bloque(indice, *dialogo.cambios())

    def aplicar_bloque(self, indice, goteo: dict, lote: dict):
        try:
            nuevos = edicion.cambiar_lote(edicion.cambiar_goteo(self.proyecto.datos, goteo), indice, lote)
        except ValueError as error:
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        self.aplicar(nuevos, f"Bloque de goteo de «{nuevos['lotes'][indice]['nombre']}»")

    def editar_lote_seleccionado(self):
        if self.seleccion and self.seleccion[0] == "lote":
            self.editar_lote(self.seleccion[1])

    def editar_goteo(self):
        dialogo = self._dialogo_bloque(None)
        if dialogo is not None and dialogo.exec() == QDialog.DialogCode.Accepted:
            goteo, _ = dialogo.cambios()
            self.aplicar(edicion.cambiar_goteo(self.proyecto.datos, goteo), "Bloque de goteo del proyecto")

    def editar_turnos(self):
        dialogo = DialogoTurnos(self.proyecto.datos, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            nuevos = edicion.fijar_turnos(self.proyecto.datos, dialogo.caja_turnos.value(), dialogo.turnos_fijos())
        except ValueError as error:
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        self.aplicar(nuevos, "Turnos de riego")

    def borrar_seleccion(self):
        seleccion = self.herramientas["seleccion"]
        if seleccion.seleccion is None:
            return
        objeto = seleccion.seleccion
        texto = "Borrar " + edicion.nombre_objeto(self.proyecto.datos, objeto)
        seleccion.seleccionar(None)
        self.aplicar(edicion.borrar(self.proyecto.datos, objeto), texto)

    # ------------------------------------------------------------ estado

    def _actualizar(self, conservar_vista=False):
        """Redibuja mapa, capas y tabla de subunidades con el proyecto actual."""
        p = self.proyecto
        ruta = os.path.basename(p.ruta) if p.ruta else "sin guardar"
        self.setWindowTitle(f"RiegoLibre — {p.nombre} ({ruta})[*]")
        dibujar_proyecto(self.lienzo, p, conservar_vista)
        self.barra_capas.cargar(p.estilos_capas, self.lienzo.diametros)
        self._llenar_subunidades()
        self.tabla_atributos.cargar(p.datos)
        self.tabla_atributos.marcar(self.seleccion)
        self.acciones["bloque"].setEnabled(bool(self.seleccion and self.seleccion[0] == "lote"))
        self.etiqueta_src.setText(f"EPSG:{p.epsg}" if p.epsg else "SRC sin definir")
        self.acciones["red"].setEnabled(bool(p.subunidades))
        self.acciones["memoria"].setEnabled(bool(p.subunidades))
        self._mostrar_escala()
        if p.errores:
            self.statusBar().showMessage("Lotes con errores: " + " | ".join(p.errores), 15000)

    def _llenar_subunidades(self):
        subunidades = self.proyecto.subunidades
        self.tabla_subunidades.setRowCount(len(subunidades))
        for i, s in enumerate(subunidades):
            r = s.resumen()
            valores = [r["nombre"], r["lote"], r["turno"], r["area_ha"], r["caudal_m3h"], r["presion_valvula_m"],
                       r["variacion_caudal_pct"], r["portalateral"],
                       "Cumple" if r["cumple"] else "No cumple: " + "; ".join(r["motivos"])]
            for j, valor in enumerate(valores):
                item = QTableWidgetItem(f"{valor:.2f}" if isinstance(valor, float) else str(valor))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if isinstance(valor, (int, float)):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if j == len(valores) - 1:
                    item.setForeground(QColor(VERDE if r["cumple"] else ROJO))
                self.tabla_subunidades.setItem(i, j, item)

    def _visibilidad_capa(self, nombre, visible):
        self.lienzo.mostrar_capa(nombre, visible)
        self._marcar(True)

    def _estilo_capa(self, _nombre):
        self._actualizar(conservar_vista=True)
        self._marcar(True)

    def _ir_a_subunidad(self, item):
        s = self.proyecto.subunidades[item.row()]
        xs = [p[0] for a in s.anillos for p in a]
        ys = [p[1] for a in s.anillos for p in a]
        a, b = self.lienzo.a_escena(min(xs), max(ys)), self.lienzo.a_escena(max(xs), min(ys))
        self.lienzo.fitInView(QRectF(a, b).adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
        self._mostrar_escala()

    def _mostrar_coordenadas(self, x, y):
        self.etiqueta_coordenadas.setText(f"E {x:,.2f}   N {y:,.2f}".replace(",", " "))
        self._mostrar_escala()

    def _mostrar_escala(self):
        metros = self.lienzo.metros_por_pixel()
        if metros:
            escala = metros * self.lienzo.logicalDpiX() / 0.0254
            self.etiqueta_escala.setText(f"Escala 1:{escala:,.0f}".replace(",", " "))

    def _marcar(self, modificado=True):
        self.setWindowModified(modificado)

    # ------------------------------------------------------------ proyecto

    def _seguir_sin_guardar(self) -> bool:
        if not self.isWindowModified():
            return True
        respuesta = QMessageBox.question(
            self, "RiegoLibre", f"El proyecto «{self.proyecto.nombre}» tiene cambios sin guardar. ¿Guardarlos?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if respuesta == QMessageBox.StandardButton.Save:
            return self.guardar()
        return respuesta == QMessageBox.StandardButton.Discard

    def _cambiar_proyecto(self, proyecto: ProyectoRiego, modificado: bool):
        if self.dialogo_red is not None:
            self.dialogo_red.close()
            self.dialogo_red = None
        if self.dialogo_ficha is not None:
            self.dialogo_ficha.close()
        self.proyecto.cerrar()
        self.proyecto = proyecto
        self.pila.clear()
        self.usar_herramienta("seleccion")
        self.herramientas["seleccion"].seleccionar(None)
        self._actualizar()
        self._marcar(modificado)

    def nuevo(self, valores: Optional[dict] = None):
        """Proyecto desde cero: pide nombre, zona UTM, terreno y el punto donde empezar a dibujar."""
        from .estilo import ajustes
        if not self._seguir_sin_guardar():
            return
        if valores is None:
            dialogo = DialogoNuevo(self)
            guardado = ajustes()
            dialogo.caja_epsg.setValue(int(guardado.value("epsg", dialogo.caja_epsg.value())))
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                return
            valores = dialogo.valores()
            guardado.setValue("epsg", valores["epsg"])
        self._cambiar_proyecto(ProyectoRiego.nuevo(**valores), False)
        self.usar_herramienta("lote")

    def abrir(self, ruta=None):
        if not self._seguir_sin_guardar():
            return
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", self._carpeta(), FILTRO_PROYECTO)
            if not ruta:
                return
        try:
            proyecto = en_segundo_plano(self, "Abriendo el proyecto y calculando los lotes…", lambda: archivo.abrir(ruta))
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo abrir el proyecto:\n{error}")
            return
        self._cambiar_proyecto(proyecto, False)
        self._recordar_carpeta(ruta)
        if proyecto.error_red:
            self.statusBar().showMessage(f"Red principal: {proyecto.error_red}", 15000)

    def importar_mcp(self, ruta=None):
        if not self._seguir_sin_guardar():
            return
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(self, "Importar diseño del servidor MCP", self._carpeta(), FILTRO_MCP)
            if not ruta:
                return
        try:
            proyecto = en_segundo_plano(self, "Trazando y calculando los lotes…",
                                        lambda: ProyectoRiego.importar_mcp(ruta))
        except Exception as error:  # el diseño puede venir con cualquier dato malo
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo importar el diseño:\n{error}")
            return
        self._cambiar_proyecto(proyecto, True)
        self._recordar_carpeta(ruta)
        cumplen = sum(1 for s in proyecto.subunidades if not s.motivos)
        self.statusBar().showMessage(
            f"Diseño importado: {len(proyecto.subunidades)} subunidades ({cumplen} cumplen), "
            f"{proyecto.turnos} turno(s). Siga con «Red principal y bomba».", 15000)

    def guardar(self) -> bool:
        if not self.proyecto.ruta:
            return self.guardar_como()
        return self._guardar_en(self.proyecto.ruta)

    def guardar_como(self) -> bool:
        sugerido = self.proyecto.ruta or os.path.join(self._carpeta(), self.proyecto.nombre + archivo.EXTENSION)
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", sugerido, FILTRO_PROYECTO)
        if not ruta:
            return False
        if not ruta.lower().endswith(archivo.EXTENSION):
            ruta += archivo.EXTENSION
        return self._guardar_en(ruta)

    def _guardar_en(self, ruta) -> bool:
        try:
            archivo.guardar(self.proyecto, ruta)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo guardar:\n{error}")
            return False
        self._recordar_carpeta(ruta)
        self._marcar(False)
        self.setWindowTitle(f"RiegoLibre — {self.proyecto.nombre} ({os.path.basename(ruta)})[*]")
        self.statusBar().showMessage(f"Guardado en {ruta}", 8000)
        return True

    def exportar_memoria(self):
        sugerido = os.path.join(self._carpeta(), self.proyecto.nombre + "_memoria.html")
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar memoria de cálculo", sugerido, "Página web (*.html)")
        if not ruta:
            return
        with open(ruta, "w", encoding="utf-8") as salida:
            salida.write(self.proyecto.memoria_html())
        self.statusBar().showMessage(f"Memoria de cálculo en {ruta}", 8000)

    def _carpeta(self):
        from .estilo import ajustes
        if self.proyecto.ruta:
            return os.path.dirname(self.proyecto.ruta)
        return ajustes().value("carpeta", os.path.expanduser("~"))

    def _recordar_carpeta(self, ruta):
        from .estilo import ajustes
        ajustes().setValue("carpeta", os.path.dirname(os.path.abspath(ruta)))

    # ------------------------------------------------------------ red

    def abrir_red(self):
        if self.dialogo_red is None:
            self.dialogo_red = DialogoRed(self.proyecto, self)
            self.dialogo_red.calculada.connect(self._red_calculada)
        self.dialogo_red.show()
        self.dialogo_red.raise_()
        self.dialogo_red.activateWindow()

    def _red_calculada(self):
        self._actualizar(conservar_vista=True)
        self._marcar(True)

    def acerca_de(self):
        QMessageBox.about(self, "Acerca de RiegoLibre",
                          f"<h3>RiegoLibre {VERSION}</h3><p>Diseño de riego tecnificado por goteo.</p>"
                          "<p>Programa de escritorio independiente de QGIS. Software libre bajo la licencia "
                          "GPL-3.0.</p><p>© 2026 Jhonatan Chilet</p>")

    def closeEvent(self, evento):  # noqa: N802 (Qt)
        if self._seguir_sin_guardar():
            self.proyecto.cerrar()
            evento.accept()
        else:
            evento.ignore()
