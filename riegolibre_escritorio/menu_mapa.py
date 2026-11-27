# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Menú del clic derecho en el mapa, como el de IRRICAD (Select Object, Clear Selection, Layers, Object Info,
Close, Restart, Modify, Zooms).

Obra sobre el objeto bajo el cursor (o, si no hay ninguno, sobre lo seleccionado). «Terminar» y «Reiniciar» el
trazo solo se activan mientras se dibuja un lote o la tubería matriz. No se replican «Invert Selection»,
«Selection Filter» ni el submenú «Select»: el programa selecciona un solo objeto a la vez.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMenu

from . import edicion, herramientas
from .capas import CAPAS


def armar_menu(ventana, x: float, y: float) -> QMenu:
    """El menú para el punto (x, y) del proyecto; la ventana es la principal (`VentanaPrincipal`)."""
    datos = ventana.datos()
    tolerancia = herramientas.TOLERANCIA_PX * ventana.lienzo.metros_por_pixel()
    bajo_cursor = edicion.objeto_en(datos, (x, y), tolerancia)
    objeto = bajo_cursor or ventana.seleccion
    actual = ventana.lienzo.herramienta
    trazando = isinstance(actual, herramientas.HerramientaTrazo) and actual.trazando
    menu = QMenu(ventana)

    accion = menu.addAction("Seleccionar objeto", lambda: ventana.seleccionar_objeto(bajo_cursor))
    accion.setShortcut(QKeySequence(Qt.Key.Key_Escape))
    accion.setEnabled(bajo_cursor is not None)
    accion = menu.addAction("Quitar la selección", lambda: ventana.seleccionar_objeto(None))
    accion.setEnabled(ventana.seleccion is not None)
    menu.addSeparator()

    capas = menu.addMenu("Capas")
    estilos = ventana.proyecto.estilos_capas
    for nombre in CAPAS:
        accion = capas.addAction(nombre)
        accion.setCheckable(True)
        accion.setChecked(bool(estilos[nombre]["visible"]))
        accion.setToolTip(CAPAS[nombre][3])
        accion.toggled.connect(lambda marcado, n=nombre: ventana.barra_capas.fijar_visible(n, marcado))
    menu.addSeparator()

    menu.addAction("Información del objeto", lambda: ventana.mostrar_ficha(x, y, tolerancia))
    accion = menu.addAction("Terminar el trazo", lambda: actual.terminar())
    accion.setShortcut(QKeySequence(Qt.Key.Key_Return))
    accion.setEnabled(trazando)
    accion = menu.addAction("Reiniciar el trazo", lambda: actual.reiniciar())
    accion.setEnabled(trazando)
    menu.addSeparator()

    modificar = menu.addMenu("Modificar")
    _llenar_modificar(modificar, ventana, datos, objeto, (x, y), tolerancia)
    modificar.setEnabled(not modificar.isEmpty())

    zooms = menu.addMenu("Zooms")
    a = ventana.acciones
    for clave in ("ver_todo", "acercar", "alejar"):
        zooms.addAction(a[clave])
    accion = zooms.addAction("Al objeto", lambda: ventana.acercar_a_objeto(objeto))
    accion.setEnabled(objeto is not None)
    return menu


def _llenar_modificar(menu: QMenu, ventana, datos, objeto, p, tolerancia):
    if objeto is None:
        return
    tipo = objeto[0]
    nombre = edicion.nombre_objeto(datos, objeto)
    if tipo in ("lote", "matriz"):
        vertice = edicion.vertice_en(datos, objeto, p, tolerancia)
        borde = edicion.borde_en(datos, objeto, p, tolerancia)
        if vertice is not None:
            texto = "Quitar este vértice" if tipo == "lote" else "Quitar este nodo (une sus tramos)"
            menu.addAction(texto, lambda: ventana.aplicar_cambio(
                edicion.borrar_vertice, objeto, vertice,
                texto="Quitar vértice" if tipo == "lote" else "Quitar nodo"))
        elif borde is not None:
            anillo, k, q = borde
            texto = "Agregar un vértice aquí" if tipo == "lote" else "Partir el tramo aquí (nodo nuevo)"
            menu.addAction(texto, lambda: ventana.aplicar_cambio(
                edicion.insertar_vertice, objeto, anillo, k, q,
                texto="Agregar vértice" if tipo == "lote" else "Partir tramo"))
    if tipo == "nodo":
        menu.addAction("Quitar el nodo (une sus tramos)",
                       lambda: ventana.aplicar_cambio(edicion.borrar, objeto, texto="Quitar nodo"))
    if tipo == "lote":
        menu.addAction("Bloque de goteo del lote…", lambda: ventana.editar_lote(objeto[1]))
    if tipo != "nodo":
        accion = menu.addAction(f"Borrar el {nombre}" if tipo != "fuente" else "Borrar la fuente de agua",
                                lambda: ventana.aplicar_cambio(edicion.borrar, objeto, texto="Borrar " + nombre))
        accion.setShortcut(QKeySequence(QKeySequence.StandardKey.Delete))
