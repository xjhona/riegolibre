"""Base de datos de materiales: importación desde IRRICAD y consulta por pestañas."""

import os

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                                 QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                                 QTabWidget, QVBoxLayout)

from ..nucleo.base_datos import base_activa, desactivar_base, guardar_base, ruta_base_usuario
from ..nucleo.importar_irricad import importar_irricad
from ..nucleo.mdb import ErrorMdb

AJUSTE_CARPETA = "riegolibre/base_datos/carpeta_mdb"
NOMBRES_PESTANAS_IRRICAD = {11: "Pumps (bombas)", 12: "Outlets (aspersores, microaspersores, hidrantes)",
                            15: "Boquillas de los emisores"}


def _n(valor, decimales=2):
    """Número para la tabla (vacío si no hay dato)."""
    if valor is None:
        return ""
    return f"{valor:.{decimales}f}".rstrip("0").rstrip(".") if isinstance(valor, float) else str(valor)


def _si_no(valor):
    return "Sí" if valor else "No"


COLUMNAS_TUBERIAS = [
    ("Descripción", lambda t: t.nombre), ("Uso", lambda t: ", ".join(t.usos)),
    ("Material", lambda t: t.material), ("DN (mm)", lambda t: _n(t.diametro_nominal_mm)),
    ("DI (mm)", lambda t: _n(t.diametro_interior_mm)), ("C", lambda t: _n(t.c_hazen)),
    ("Presión admisible (m)", lambda t: _n(t.presion_nominal_m)), ("Etiqueta", lambda t: t.etiqueta),
    ("Proveedor", lambda t: t.proveedor), ("Código", lambda t: t.codigo),
    ("Costo / m", lambda t: _n(t.costo_m, 4)), ("Precio / m", lambda t: _n(t.precio_m, 4)),
]
COLUMNAS_CINTAS = [
    ("Descripción", lambda c: c.nombre), ("Seleccionable", lambda c: _si_no(c.seleccionable)),
    ("Caudal (L/h)", lambda c: _n(c.caudal_nominal_lh, 3)),
    ("Autocompensado", lambda c: _si_no(c.autocompensado)),
    ("k", lambda c: _n(c.k_emisor, 4)), ("x", lambda c: _n(c.exponente_emisor, 4)),
    ("Espaciamiento (m)", lambda c: _n(c.espaciamiento_m, 3)),
    ("L/h por m", lambda c: _n(c.caudal_por_metro_lhm, 3)),
    ("DN (mm)", lambda c: _n(c.diametro_nominal_mm)), ("DI (mm)", lambda c: _n(c.diametro_interior_mm)),
    ("C", lambda c: _n(c.c_hazen)), ("Factor de inserción (m)", lambda c: _n(c.longitud_equivalente_m, 3)),
    ("CV", lambda c: _n(c.cv, 3)), ("Presión de entrada (m)", lambda c: _n(c.presion_entrada_m)),
    ("Presión mín. (m)", lambda c: _n(c.presion_min_m)), ("Presión máx. (m)", lambda c: _n(c.presion_max_m)),
    ("Mín. compensación (m)", lambda c: _n(c.presion_min_compensacion_m)),
    ("Proveedor", lambda c: c.proveedor), ("Código", lambda c: c.codigo),
]
COLUMNAS_HIDRAULICOS = [
    ("Descripción", lambda h: h.nombre), ("Seleccionable", lambda h: _si_no(h.seleccionable)),
    ("K", lambda h: _n(h.k, 8)), ("n", lambda h: _n(h.n, 5)), ("C (m)", lambda h: _n(h.c, 3)),
    ("Q mín. (m³/h)", lambda h: _n(h.caudal_min_m3h)), ("Q máx. (m³/h)", lambda h: _n(h.caudal_max_m3h)),
    ("D entrada (mm)", lambda h: _n(h.diametro_entrada_mm)), ("D salida (mm)", lambda h: _n(h.diametro_salida_mm)),
    ("Conexión entrada", lambda h: h.conexion_entrada), ("Conexión salida", lambda h: h.conexion_salida),
    ("Etiqueta", lambda h: h.etiqueta), ("Proveedor", lambda h: h.proveedor), ("Código", lambda h: h.codigo),
    ("Costo", lambda h: _n(h.costo)), ("Precio", lambda h: _n(h.precio)),
]


def _tabla(columnas):
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels([titulo for titulo, _ in columnas])
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.setAlternatingRowColors(True)
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    tabla.columnas = columnas
    return tabla


def _llenar(tabla, registros):
    tabla.setSortingEnabled(False)
    tabla.setRowCount(len(registros))
    for fila, registro in enumerate(registros):
        for columna, (_, valor) in enumerate(tabla.columnas):
            tabla.setItem(fila, columna, QTableWidgetItem(valor(registro)))
    tabla.resizeColumnsToContents()
    tabla.setColumnWidth(0, min(tabla.columnWidth(0), 320))


class DialogoBaseDatos(QDialog):
    base_cambiada = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Base de datos de materiales")
        self.resize(1200, 680)

        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        boton_importar = QPushButton("Importar base de IRRICAD (.mdb)…")
        boton_importar.clicked.connect(self.elegir_e_importar)
        self.boton_carpeta = QPushButton("Abrir carpeta")
        self.boton_carpeta.setToolTip("Carpeta donde se guarda la base y su copia de respaldo.")
        self.boton_carpeta.clicked.connect(self._abrir_carpeta)
        self.boton_generico = QPushButton("Volver al catálogo genérico")
        self.boton_generico.clicked.connect(self.volver_al_generico)
        fila_botones = QHBoxLayout()
        fila_botones.addWidget(boton_importar)
        fila_botones.addWidget(self.boton_carpeta)
        fila_botones.addWidget(self.boton_generico)
        fila_botones.addStretch()

        self.edit_buscar = QLineEdit()
        self.edit_buscar.setPlaceholderText("Buscar en la pestaña (descripción, código, proveedor…)")
        self.edit_buscar.setClearButtonEnabled(True)
        self.edit_buscar.textChanged.connect(self._filtrar)

        self.pestanas = QTabWidget()
        self.tabla_tuberias = _tabla(COLUMNAS_TUBERIAS)
        self.tabla_cintas = _tabla(COLUMNAS_CINTAS)
        self.tabla_valvulas = _tabla(COLUMNAS_HIDRAULICOS)
        self.tabla_hidraulicos = _tabla(COLUMNAS_HIDRAULICOS)
        for tabla in (self.tabla_tuberias, self.tabla_cintas, self.tabla_valvulas, self.tabla_hidraulicos):
            self.pestanas.addTab(tabla, "")
        self.pestanas.currentChanged.connect(lambda _i: self._filtrar())

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(self.etiqueta_estado)
        principal.addLayout(fila_botones)
        principal.addWidget(self.edit_buscar)
        principal.addWidget(self.pestanas, 1)
        principal.addWidget(botones)
        self.actualizar()

    # ------------------------------------------------------------------ vista

    def actualizar(self):
        ruta = ruta_base_usuario()
        try:
            base = base_activa()
        except (OSError, ValueError, TypeError) as error:
            base = None
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo leer la base de datos:\n{ruta}\n\n{error}")
        if base is None:
            self.etiqueta_estado.setText(
                "<b>Sin base de datos propia.</b> Las ventanas usan el catálogo genérico de RiegoLibre. "
                "Importe la base de IRRICAD que usa en sus proyectos para trabajar con sus materiales.")
            registros = ([], [], [], [])
        else:
            self.etiqueta_estado.setText(
                f"<b>Base de datos activa</b> ({base.origen or 'sin origen'})<br>{ruta}<br>"
                "Las ventanas de diseño eligen las tuberías y los laterales con gotero de esta base.")
            registros = (base.tuberias, base.cintas, base.valvulas, base.hidraulicos)
        self.boton_generico.setEnabled(base is not None)
        titulos = ("Tuberías", "Laterales con gotero", "Válvulas", "Otros hidráulicos")
        tablas = (self.tabla_tuberias, self.tabla_cintas, self.tabla_valvulas, self.tabla_hidraulicos)
        for i, (tabla, titulo, lista) in enumerate(zip(tablas, titulos, registros)):
            _llenar(tabla, lista)
            self.pestanas.setTabText(i, f"{titulo} ({len(lista)})")
        self._filtrar()

    def _filtrar(self):
        palabras = self.edit_buscar.text().casefold().split()
        tabla = self.pestanas.currentWidget()
        for fila in range(tabla.rowCount()):
            texto = " ".join(tabla.item(fila, c).text() for c in range(tabla.columnCount())).casefold()
            tabla.setRowHidden(fila, not all(p in texto for p in palabras))

    def _abrir_carpeta(self):
        carpeta = os.path.dirname(ruta_base_usuario())
        os.makedirs(carpeta, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(carpeta))

    # --------------------------------------------------------------- acciones

    def elegir_e_importar(self):
        ajustes = QgsSettings()
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Base de datos de IRRICAD", ajustes.value(AJUSTE_CARPETA, ""),
            "Base de datos de IRRICAD (*.mdb);;Todos los archivos (*)")
        if not ruta:
            return
        ajustes.setValue(AJUSTE_CARPETA, os.path.dirname(ruta))
        if base_activa() is not None:
            respuesta = QMessageBox.question(
                self, "RiegoLibre",
                "Se reemplazará la base de datos actual por la importada.\n"
                "La actual queda guardada como copia de respaldo (.bak).\n\n¿Continuar?")
            if respuesta != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resultado = self.importar(ruta)
        except (ErrorMdb, OSError) as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo importar la base de datos:\n{error}")
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "RiegoLibre", self._informe(resultado))

    def importar(self, ruta):
        """Importa el .mdb y lo deja como base activa (lanza ErrorMdb u OSError si no puede)."""
        resultado = importar_irricad(ruta)
        guardar_base(resultado.base, ruta_base_usuario())
        self.actualizar()
        self.base_cambiada.emit()
        return resultado

    def volver_al_generico(self):
        respuesta = QMessageBox.question(
            self, "RiegoLibre",
            "Las ventanas volverán a usar el catálogo genérico de RiegoLibre.\n"
            "La base actual queda guardada como copia de respaldo (.bak).\n\n¿Continuar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        desactivar_base()
        self.actualizar()
        self.base_cambiada.emit()

    @staticmethod
    def _informe(resultado):
        lineas = ["Base de datos importada:"]
        lineas += [f"   {titulo}: {cantidad}" for titulo, cantidad in resultado.base.resumen().items()]
        if resultado.omitidos_por_pestana:
            lineas.append("\nNo se importaron (pestañas que aún no usa RiegoLibre):")
            lineas += [f"   {NOMBRES_PESTANAS_IRRICAD.get(p, f'pestaña {p}')}: {n} registros"
                       for p, n in sorted(resultado.omitidos_por_pestana.items())]
        if resultado.avisos:
            lineas.append("\nAvisos:")
            lineas += [f"   {aviso}" for aviso in resultado.avisos[:15]]
            if len(resultado.avisos) > 15:
                lineas.append(f"   … y {len(resultado.avisos) - 15} más.")
        lineas.append("\nLas ventanas que están abiertas usarán la nueva base cuando las cierre y las "
                      "vuelva a abrir.")
        return "\n".join(lineas)
