"""Lista de materiales y costos del proyecto."""

import os
from datetime import date

from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                                 QFileDialog, QFormLayout, QHBoxLayout,
                                 QHeaderView, QLabel, QLineEdit, QListWidget,
                                 QListWidgetItem, QMessageBox, QPushButton,
                                 QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..integracion.materiales_mapa import (AJUSTE_DESPERDICIO, AJUSTE_LISTA,
                                           AJUSTE_MONEDA, elecciones_del_proyecto,
                                           guardar_eleccion)
from ..nucleo import cargar_catalogo_tuberias
from ..nucleo.materiales import (asignar_articulos, exportar_csv, exportar_excel,
                                 resumen_por_categoria, total)
from ..nucleo.precios import buscar, cargar_lista_precios
from .comunes import spin

COLUMNAS = ["Categoría", "Material del diseño", "Cantidad", "Unidad", "A comprar", "Tubos",
            "Artículo de la lista de precios", "Precio unit.", "Subtotal"]


class DialogoArticulo(QDialog):
    """Buscador de artículos de la lista de precios."""

    def __init__(self, articulos, texto_inicial="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegir artículo de la lista de precios")
        self.resize(720, 480)
        self.articulos = articulos
        self.elegido = None
        self.busqueda = QLineEdit(texto_inicial)
        self.busqueda.setPlaceholderText("Escriba palabras de la descripción o el código, p. ej.: PVC 63 C-5")
        self.busqueda.textChanged.connect(self._filtrar)
        self.lista = QListWidget()
        self.lista.itemDoubleClicked.connect(lambda _item: self.accept())
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Elegir")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addWidget(self.busqueda)
        capa.addWidget(self.lista)
        capa.addWidget(botones)
        self._filtrar(texto_inicial)

    def _filtrar(self, texto):
        self.lista.clear()
        for articulo in buscar(self.articulos, texto):
            pieza = f" · tubo de {articulo.longitud_pieza_m:g} m" if articulo.por_pieza else ""
            item = QListWidgetItem(f"{articulo.descripcion}   [{articulo.codigo}]  —  {articulo.precio:g}{pieza}")
            item.setData(Qt.ItemDataRole.UserRole, articulo)
            self.lista.addItem(item)
        if self.lista.count():
            self.lista.setCurrentRow(0)

    def accept(self):
        item = self.lista.currentItem()
        self.elegido = item.data(Qt.ItemDataRole.UserRole) if item else None
        super().accept()


class DialogoMateriales(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Lista de materiales y costos")
        self.resize(1250, 720)
        self.articulos = []
        self.partidas = []
        self.resumen = {}
        self.ruta_lista = None
        self.tuberias = {t.nombre: t for t in cargar_catalogo_tuberias()}
        ajustes = QgsSettings()

        cabecera = QFormLayout()
        fila_lista = QHBoxLayout()
        self.etiqueta_lista = QLabel("Sin lista de precios")
        self.etiqueta_lista.setWordWrap(True)
        boton_lista = QPushButton("Abrir lista de precios (CSV)…")
        boton_lista.clicked.connect(self._elegir_lista)
        fila_lista.addWidget(self.etiqueta_lista, 1)
        fila_lista.addWidget(boton_lista)
        cabecera.addRow("Lista de precios:", fila_lista)
        fila_opciones = QHBoxLayout()
        self.edit_moneda = QLineEdit(ajustes.value(AJUSTE_MONEDA, "USD"))
        self.edit_moneda.setMaximumWidth(80)
        self.edit_moneda.textChanged.connect(self._actualizar_tabla)
        self.spin_desperdicio = spin(0, 50, float(ajustes.value(AJUSTE_DESPERDICIO, 5.0, type=float)), 1,
                                     decimales=0, sufijo="%")
        self.spin_desperdicio.setToolTip("Se suma a los metros de tubería (cortes, uniones, imprevistos).")
        self.spin_desperdicio.valueChanged.connect(self._actualizar_tabla)
        fila_opciones.addWidget(QLabel("Moneda:"))
        fila_opciones.addWidget(self.edit_moneda)
        fila_opciones.addSpacing(20)
        fila_opciones.addWidget(QLabel("Desperdicio en tuberías:"))
        fila_opciones.addWidget(self.spin_desperdicio)
        fila_opciones.addStretch()
        boton_metrado = QPushButton("Actualizar metrado desde el proyecto")
        boton_metrado.clicked.connect(self.actualizar_metrado)
        fila_opciones.addWidget(boton_metrado)
        cabecera.addRow(fila_opciones)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda fila, _c: self.elegir_articulo(fila))

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setTextFormat(Qt.TextFormat.RichText)
        ayuda = QLabel("Doble clic en una fila para elegir o cambiar su artículo. En verde, los artículos "
                       "asignados automáticamente por diámetro y clase (precio central entre los "
                       "equivalentes de la lista).")
        ayuda.setWordWrap(True)

        botones = QHBoxLayout()
        boton_elegir = QPushButton("Elegir artículo…")
        boton_elegir.clicked.connect(lambda: self.elegir_articulo(self.tabla.currentRow()))
        boton_quitar = QPushButton("Quitar artículo")
        boton_quitar.clicked.connect(self.quitar_articulo)
        boton_exportar = QPushButton("Exportar a Excel…")
        boton_exportar.clicked.connect(self._elegir_exportacion)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)
        for boton in (boton_elegir, boton_quitar):
            botones.addWidget(boton)
        botones.addStretch()
        botones.addWidget(boton_exportar)
        botones.addWidget(boton_cerrar)

        principal = QVBoxLayout(self)
        principal.addLayout(cabecera)
        principal.addWidget(ayuda)
        principal.addWidget(self.tabla)
        principal.addWidget(self.etiqueta_total)
        principal.addLayout(botones)

        ruta = ajustes.value(AJUSTE_LISTA, "")
        if ruta and os.path.exists(ruta):
            self.cargar_lista(ruta, avisar=False)
        self.actualizar_metrado()

    # --------------------------------------------------------------- acciones

    def _elegir_lista(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Lista de precios", self.ruta_lista or "",
                                              "Listas de precios (*.csv)")
        if ruta:
            self.cargar_lista(ruta)

    def cargar_lista(self, ruta, avisar=True):
        try:
            self.articulos = cargar_lista_precios(ruta)
        except (OSError, ValueError, UnicodeDecodeError) as error:
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo leer la lista de precios:\n{error}")
            return
        self.ruta_lista = ruta
        QgsSettings().setValue(AJUSTE_LISTA, ruta)
        self.etiqueta_lista.setText(f"{os.path.basename(ruta)} · {len(self.articulos):,} artículos")
        self._asignar()
        if avisar and not self.partidas:
            QMessageBox.information(self, "RiegoLibre", "Lista cargada. Aún no hay resultados de diseño "
                                    "en el proyecto para hacer el metrado.")

    def actualizar_metrado(self):
        from ..integracion.materiales_mapa import partidas_del_proyecto
        self.partidas, self.resumen = partidas_del_proyecto()
        self._asignar()

    def _asignar(self):
        asignar_articulos(self.partidas, self.articulos, self.tuberias, elecciones_del_proyecto())
        self._actualizar_tabla()

    def elegir_articulo(self, fila):
        if not 0 <= fila < len(self.partidas):
            return
        if not self.articulos:
            QMessageBox.information(self, "RiegoLibre", "Abra primero una lista de precios.")
            return
        partida = self.partidas[fila]
        sugerencia = partida.articulo.descripcion if partida.articulo else ""
        dialogo = DialogoArticulo(self.articulos, sugerencia, self)
        if dialogo.exec() and dialogo.elegido is not None:
            self.asignar(fila, dialogo.elegido)

    def asignar(self, fila, articulo):
        partida = self.partidas[fila]
        guardar_eleccion(partida.clave, articulo)
        partida.articulo, partida.automatico = articulo, False
        self._actualizar_tabla()

    def quitar_articulo(self):
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self.partidas):
            partida = self.partidas[fila]
            guardar_eleccion(partida.clave, None)
            partida.articulo, partida.automatico = None, False
            self._actualizar_tabla()

    def desperdicio(self):
        return self.spin_desperdicio.value() / 100

    # -------------------------------------------------------------- resultados

    def _actualizar_tabla(self):
        QgsSettings().setValue(AJUSTE_MONEDA, self.edit_moneda.text())
        QgsSettings().setValue(AJUSTE_DESPERDICIO, self.spin_desperdicio.value())
        d = self.desperdicio()
        self.tabla.setRowCount(len(self.partidas))
        for fila, p in enumerate(self.partidas):
            a = p.articulo
            piezas = p.piezas(d)
            unitario = p.precio_unitario()
            valores = [
                p.categoria, p.material, f"{p.cantidad:,.1f}" if p.unidad == "m" else f"{p.cantidad:,.0f}",
                p.unidad, f"{p.cantidad_compra(d):,.1f}" if p.unidad == "m" else f"{p.cantidad_compra(d):,.0f}",
                f"{piezas:,}" if piezas is not None else "",
                f"{a.descripcion}  [{a.codigo}]" if a else "— sin precio —",
                f"{unitario:,.4f}" + ("/m" if p.unidad == "m" else "") if a else "",
                f"{p.costo(d):,.2f}" if a else "",
            ]
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if columna in (2, 4, 5, 7, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if columna == 6:
                    if a is None:
                        item.setForeground(QBrush(QColor("#c62828")))
                    elif p.automatico:
                        item.setForeground(QBrush(QColor("#2e7d32")))
                    if p.nota:
                        item.setToolTip(p.nota)
                self.tabla.setItem(fila, columna, item)

        moneda = self.edit_moneda.text()
        sin_precio = sum(1 for p in self.partidas if p.articulo is None)
        partes = [f"{c}: {s:,.2f}" + (f" ({n} sin precio)" if n else "")
                  for c, s, n in resumen_por_categoria(self.partidas, d)]
        texto = f"<b>Total: {total(self.partidas, d):,.2f} {moneda}</b>"
        if partes:
            texto += " &nbsp;·&nbsp; " + " · ".join(partes)
        if sin_precio:
            texto += (f"<br><span style='color:#c62828'>{sin_precio} partidas sin precio no están "
                      "incluidas en el total.</span>")
        if not self.partidas:
            texto = ("No hay resultados de diseño en el proyecto. Calcule subunidades en el mapa o la "
                     "red principal y pulse <i>Actualizar metrado</i>.")
        self.etiqueta_total.setText(texto)

    def _elegir_exportacion(self):
        ruta, filtro = QFileDialog.getSaveFileName(self, "Exportar lista de materiales",
                                                   "lista_de_materiales.xlsx",
                                                   "Excel (*.xlsx);;CSV (*.csv)")
        if ruta:
            self.exportar(ruta)

    def exportar(self, ruta):
        proyecto = QgsProject.instance()
        nombre = proyecto.baseName() or "proyecto sin guardar"
        detalles = [f"Proyecto: {nombre}", f"Fecha: {date.today():%d/%m/%Y}"]
        if self.ruta_lista:
            detalles.append(f"Lista de precios: {os.path.basename(self.ruta_lista)}")
        detalles.append(f"Subunidades: {self.resumen.get('subunidades', 0)} · laterales: "
                        f"{self.resumen.get('laterales', 0)} · válvulas: {self.resumen.get('valvulas', 0)}")
        try:
            if ruta.lower().endswith(".csv"):
                exportar_csv(self.partidas, ruta, self.desperdicio(), self.edit_moneda.text())
            else:
                exportar_excel(self.partidas, ruta, self.desperdicio(), self.edit_moneda.text(),
                               "RiegoLibre · Lista de materiales y costos", detalles)
        except ImportError:
            ruta = os.path.splitext(ruta)[0] + ".csv"
            exportar_csv(self.partidas, ruta, self.desperdicio(), self.edit_moneda.text())
        except OSError as error:
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo guardar el archivo:\n{error}")
            return None
        if self.iface is not None:
            self.iface.messageBar().pushSuccess("RiegoLibre", f"Lista de materiales guardada en {ruta}")
        return ruta
