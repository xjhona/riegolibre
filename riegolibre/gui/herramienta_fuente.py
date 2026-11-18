# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Herramienta «Fuente de agua»: un clic en el mapa deja ahí la fuente (el «Water Supply» de IRRICAD)."""

from qgis.core import Qgis, QgsCoordinateTransform, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox

from ..integracion.fuente_mapa import (capa_de_fuente, colocar_fuente, crear_capa_fuente,
                                       geometrias_de_iman, tiene_fuente)
from ..integracion.subunidad_mapa import verificar_crs_metrico
from .herramienta_puntos import HerramientaPuntos

MENSAJE = "Fuente de agua: haga clic donde están la bomba y el cabezal"


class ColocarFuente:
    """Pide un clic en el mapa (con imán) y deja ese punto como única fuente de agua del proyecto.

    `al_colocar(capa)` se llama cuando la fuente quedó puesta; `al_terminar()` cuando la herramienta ya
    no está activa, se haya colocado o no.
    """

    def __init__(self, iface, ventana, al_colocar=None, al_terminar=None):
        self.iface, self.ventana = iface, ventana
        self.al_colocar, self.al_terminar = al_colocar, al_terminar
        self.herramienta = None

    def iniciar(self):
        """Activa la herramienta. Devuelve False (y avisa por qué) si no se pudo."""
        capa = capa_de_fuente()
        try:
            verificar_crs_metrico(capa.crs() if capa is not None else QgsProject.instance().crs(),
                                  capa.name() if capa is not None else "del proyecto")
        except ValueError as error:
            QMessageBox.warning(self.ventana, "RiegoLibre", f"{error} Cámbielo en Proyecto → Propiedades → SRC.")
            return False
        if tiene_fuente(capa):
            respuesta = QMessageBox.question(
                self.ventana, "RiegoLibre",
                "El proyecto ya tiene una fuente de agua. ¿Quiere cambiarla de lugar?\n"
                "Solo puede haber una: la nueva reemplaza a la anterior.")
            if respuesta != QMessageBox.StandardButton.Yes:
                return False
        canvas = self.iface.mapCanvas()
        crs_mapa = canvas.mapSettings().destinationCrs()
        anterior = canvas.mapTool()
        mensajes = [MENSAJE]

        def volver():
            self.herramienta = None
            if canvas.mapTool() is None and anterior is not None:
                canvas.setMapTool(anterior)
            if self.al_terminar is not None:
                self.al_terminar()

        def terminar(puntos):
            volver()
            self._colocar(puntos[0], crs_mapa)

        self.herramienta = HerramientaPuntos(canvas, 1, geometrias_de_iman(crs_mapa), mensajes, terminar, volver,
                                             self.iface.statusBarIface().showMessage)
        self.iface.messageBar().pushMessage("RiegoLibre", mensajes[0] + " (Esc para cancelar).",
                                            Qgis.MessageLevel.Info, 5)
        canvas.setMapTool(self.herramienta)
        canvas.setFocus()
        return True

    def cancelar(self):
        """Suelta la herramienta si sigue activa (el botón se desmarcó)."""
        canvas = self.iface.mapCanvas()
        if self.herramienta is not None and canvas.mapTool() is self.herramienta:
            canvas.unsetMapTool(self.herramienta)

    def _colocar(self, punto, crs_mapa):
        barra = self.iface.messageBar()
        try:
            capa = capa_de_fuente()
            if capa is None:
                capa, _ = crear_capa_fuente()
            colocar_fuente(capa, QgsCoordinateTransform(crs_mapa, capa.crs(), QgsProject.instance()).transform(punto))
        except (ValueError, OSError) as error:
            barra.pushMessage("RiegoLibre", str(error), Qgis.MessageLevel.Warning, 8)
            return
        self.iface.mapCanvas().refresh()
        barra.pushMessage("RiegoLibre", "Fuente de agua colocada: la red principal arranca de este punto.",
                          Qgis.MessageLevel.Info, 5)
        if self.al_colocar is not None:
            self.al_colocar(capa)
