# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana principal del programa: mapa, panel de capas, tabla de subunidades, menús y barra de estado."""

import os
from typing import Optional

from PySide6.QtCore import QEventLoop, QRectF, QThread, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHeaderView, QLabel, QMainWindow,
                               QMessageBox, QProgressDialog, QTableWidget, QTableWidgetItem, QToolBar)

from . import VERSION, archivo
from .barra_capas import BarraCapas
from .dialogo_red import DialogoRed
from .estilo import ROJO, TEMAS, VERDE, aplicar_tema, tema_actual
from .lienzo import Lienzo, dibujar_proyecto
from .modelo import ProyectoRiego

FILTRO_PROYECTO = f"Proyecto de RiegoLibre (*{archivo.EXTENSION})"
FILTRO_MCP = "Diseño del servidor MCP (*_datos.json *.json)"


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


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.proyecto = ProyectoRiego()
        self.dialogo_red: Optional[DialogoRed] = None
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

        self.etiqueta_coordenadas = QLabel()
        self.etiqueta_escala = QLabel()
        self.etiqueta_src = QLabel()
        for etiqueta in (self.etiqueta_coordenadas, self.etiqueta_escala, self.etiqueta_src):
            self.statusBar().addPermanentWidget(etiqueta)

        self._crear_acciones()
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
        }
        menu = self.menuBar().addMenu("&Proyecto")
        for clave in ("nuevo", "abrir", "guardar", "guardar_como", None, "importar_mcp", "memoria", None, "salir"):
            menu.addSeparator() if clave is None else menu.addAction(a[clave])
        menu = self.menuBar().addMenu("&Ver")
        for clave in ("ver_todo", "acercar", "alejar"):
            menu.addAction(a[clave])
        menu.addSeparator()
        menu.addAction(self.dock_capas.toggleViewAction())
        menu.addAction(self.dock_subunidades.toggleViewAction())
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
        for clave in ("abrir", "guardar", "importar_mcp", None, "ver_todo", "acercar", "alejar", None, "red"):
            barra.addSeparator() if clave is None else barra.addAction(a[clave])
        self.addToolBar(barra)

    # ------------------------------------------------------------ estado

    def _actualizar(self, conservar_vista=False):
        """Redibuja mapa, capas y tabla de subunidades con el proyecto actual."""
        p = self.proyecto
        ruta = os.path.basename(p.ruta) if p.ruta else "sin guardar"
        self.setWindowTitle(f"RiegoLibre — {p.nombre} ({ruta})[*]")
        dibujar_proyecto(self.lienzo, p, conservar_vista)
        self.barra_capas.cargar(p.estilos_capas, self.lienzo.diametros)
        self._llenar_subunidades()
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
        self.proyecto.cerrar()
        self.proyecto = proyecto
        self._actualizar()
        self._marcar(modificado)

    def nuevo(self):
        if self._seguir_sin_guardar():
            self._cambiar_proyecto(ProyectoRiego(), False)

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
