"""Topografía del proyecto: curvas de nivel de un plano CAD (DXF) → DEM y lindero, imagen satelital
recortada al DEM y vista 3D del terreno."""

import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMapLayerProxyModel,
                       QgsPointXY, QgsProject, QgsRasterLayer, QgsSettings)
from qgis.gui import QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                                 QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                                 QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                                 QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..integracion.imagen_satelital import FUENTES, abrir_vista_3d, imagen_para_dem
from ..integracion.topografia_cad import (agregar_al_mapa, capas_que_usan, celdas_estimadas,
                                          generar_topografia, leer_dxf, parecen_coordenadas_planas)
from .comunes import html_avisos, html_tabla, spin

AJUSTE_CARPETA = "RiegoLibre/topografia_carpeta"
AJUSTE_CRS = "RiegoLibre/topografia_crs"  # último sistema de coordenadas usado para un plano
USO_NINGUNO, USO_CURVAS, USO_LINDERO = "No usar", "Curvas de nivel", "Lindero"
FUENTE_CAPA = "Una capa ráster del proyecto"


def _formato_cotas(capa):
    if capa.cota_min is None:
        return "sin elevación"
    if capa.cota_min == capa.cota_max:
        return f"{capa.cota_min:g} m"
    return f"{capa.cota_min:g} – {capa.cota_max:g} m"


def _grados(valor, positivo, negativo):
    return f"{abs(valor):.4f}° {positivo if valor >= 0 else negativo}"


def _combo_dem():
    control = QgsMapLayerComboBox()
    control.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
    return control


def _nota(texto):
    etiqueta = QLabel(texto)
    etiqueta.setWordWrap(True)
    return etiqueta


class DialogoTopografia(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.contenido = None
        self.setWindowTitle("RiegoLibre · Topografía: curvas de CAD, imagen satelital y vista 3D")
        self.resize(780, 780)

        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._pestana_cad(), "Curvas del CAD → DEM")
        self.pestanas.addTab(self._pestana_imagen(), "Imagen satelital")
        self.pestanas.addTab(self._pestana_3d(), "Vista 3D")

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setVisible(False)
        self.etiqueta_resultado = QLabel()
        self.etiqueta_resultado.setWordWrap(True)
        self.etiqueta_resultado.setTextFormat(Qt.TextFormat.RichText)

        botones = QHBoxLayout()
        botones.addStretch()
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)
        botones.addWidget(boton_cerrar)

        principal = QVBoxLayout(self)
        principal.addWidget(self.pestanas, 1)
        principal.addWidget(self.barra)
        principal.addWidget(self.etiqueta_resultado)
        principal.addLayout(botones)

    # ------------------------------------------------------------- pestañas

    def _pestana_cad(self):
        grupo_archivo = QGroupBox("Plano CAD")
        capa_archivo = QVBoxLayout(grupo_archivo)
        fila = QHBoxLayout()
        self.edit_dxf = QLineEdit()
        self.edit_dxf.setPlaceholderText("Archivo .dxf con las curvas de nivel (polilíneas con elevación)")
        self.edit_dxf.editingFinished.connect(self._leer)
        boton_dxf = QPushButton("Examinar…")
        boton_dxf.clicked.connect(self._elegir_dxf)
        fila.addWidget(self.edit_dxf)
        fila.addWidget(boton_dxf)
        capa_archivo.addLayout(fila)
        capa_archivo.addWidget(_nota("Si el plano está en DWG, guárdelo desde el CAD como «AutoCAD DXF» "
                                     "(2013 o 2018)."))

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Capa del CAD", "Líneas", "Cotas", "Uso"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setMinimumHeight(150)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for columna in (1, 2, 3):
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        capa_archivo.addWidget(self.tabla)
        self.etiqueta_contenido = QLabel()
        self.etiqueta_contenido.setWordWrap(True)
        capa_archivo.addWidget(self.etiqueta_contenido)

        grupo_opciones = QGroupBox("Modelo de elevación")
        formulario = QFormLayout(grupo_opciones)
        self.selector_crs = QgsProjectionSelectionWidget()
        self.selector_crs.setCrs(self._crs_inicial())
        self.selector_crs.crsChanged.connect(self._actualizar_resumen)
        self.selector_crs.setToolTip("Zona UTM en la que se dibujó el plano (17 S, 18 S, 19 S…). El DXF no la "
                                     "indica; la lista guarda las últimas usadas.")
        formulario.addRow("Sistema de coordenadas del plano:", self.selector_crs)
        self.spin_paso = spin(0.1, 50, 1.0, 0.5, sufijo="m")
        self.spin_paso.setToolTip("Lado de la celda del DEM. 1 m basta para curvas cada 0.5–1 m; "
                                  "celdas menores no agregan precisión a unas curvas.")
        self.spin_paso.valueChanged.connect(self._actualizar_resumen)
        formulario.addRow("Tamaño de celda:", self.spin_paso)
        self.spin_distancia = spin(1, 1000, 30, 5, decimales=0, sufijo="m")
        self.spin_distancia.setToolTip(
            "Las celdas más lejos que esto de cualquier curva quedan sin dato. Evita que la triangulación "
            "invente terreno en huecos y bordes sin levantamiento. Auméntela si el terreno es muy plano "
            "y las curvas quedan muy separadas.")
        formulario.addRow("Distancia máxima a una curva:", self.spin_distancia)
        fila_carpeta = QHBoxLayout()
        self.edit_carpeta = QLineEdit()
        self.edit_carpeta.setPlaceholderText("La carpeta del DXF")
        boton_carpeta = QPushButton("…")
        boton_carpeta.setMaximumWidth(32)
        boton_carpeta.clicked.connect(self._elegir_carpeta)
        fila_carpeta.addWidget(self.edit_carpeta)
        fila_carpeta.addWidget(boton_carpeta)
        formulario.addRow("Carpeta de salida:", fila_carpeta)

        self.boton_importar = QPushButton("Importar")
        self.boton_importar.setEnabled(False)
        self.boton_importar.clicked.connect(self.importar)
        fila_boton = QHBoxLayout()
        fila_boton.addStretch()
        fila_boton.addWidget(self.boton_importar)

        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        capa.addWidget(grupo_archivo, 1)
        capa.addWidget(grupo_opciones)
        capa.addLayout(fila_boton)
        return pagina

    def _pestana_imagen(self):
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        self.combo_dem_imagen = _combo_dem()
        formulario.addRow("DEM del proyecto:", self.combo_dem_imagen)
        self.combo_fuente = QComboBox()
        for fuente in FUENTES:
            self.combo_fuente.addItem(fuente.nombre, fuente)
        self.combo_fuente.addItem(FUENTE_CAPA, None)
        self.combo_fuente.currentIndexChanged.connect(self._cambio_fuente)
        formulario.addRow("Fuente:", self.combo_fuente)
        self.combo_capa_fuente = QgsMapLayerComboBox()
        self.combo_capa_fuente.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
        self.combo_capa_fuente.setToolTip("Por ejemplo, un ortomosaico de dron o un servicio de teselas "
                                          "que ya esté cargado en el proyecto.")
        formulario.addRow("Capa:", self.combo_capa_fuente)
        self.spin_resolucion = spin(0.1, 20, 0.5, 0.1, sufijo="m")
        self.spin_resolucion.setToolTip("Tamaño del píxel de la imagen guardada. La nitidez real depende de "
                                        "la fuente: se usa el mayor zoom que tenga imagen en la zona.")
        formulario.addRow("Resolución:", self.spin_resolucion)
        self.check_recortar = QCheckBox("Recortar al contorno del DEM (fuera queda transparente)")
        self.check_recortar.setChecked(True)
        formulario.addRow(self.check_recortar)
        boton = QPushButton("Descargar imagen")
        boton.clicked.connect(self.descargar_imagen)
        formulario.addRow(boton)
        formulario.addRow(_nota(
            "La imagen se guarda como GeoTIFF junto al DEM y se agrega al mapa debajo de las curvas. "
            "Las imágenes de Google y Esri tienen condiciones de uso propias: úselas como referencia del "
            "diseño y cite la fuente en los planos."))
        self._cambio_fuente()
        return pagina

    def _pestana_3d(self):
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        self.combo_dem_3d = _combo_dem()
        formulario.addRow("DEM del proyecto:", self.combo_dem_3d)
        self.spin_exageracion = spin(0.1, 10, 1.0, 0.5, decimales=1, sufijo="×")
        self.spin_exageracion.setToolTip("Multiplica las cotas en la vista 3D para que el relieve se note "
                                         "mejor en terrenos suaves.")
        formulario.addRow("Exageración vertical:", self.spin_exageracion)
        boton = QPushButton("Abrir vista 3D")
        boton.clicked.connect(self.abrir_3d)
        formulario.addRow(boton)
        formulario.addRow(_nota(
            "El DEM se usa como terreno del proyecto y las capas visibles del mapa (imagen satelital, curvas, "
            "lindero, bloques, tuberías) se ven sobre él. En la vista 3D: arrastre con el botón izquierdo "
            "para desplazar, con el derecho o la rueda para acercar y con Mayús + arrastre para girar. La "
            "llave de herramientas de la vista permite cambiar la exageración y la iluminación."))
        return pagina

    # ------------------------------------------------------------- lectura del DXF

    def _crs_inicial(self):
        proyecto = QgsProject.instance().crs()
        if proyecto.isValid() and not proyecto.isGeographic():
            return proyecto
        guardado = QgsCoordinateReferenceSystem(QgsSettings().value(AJUSTE_CRS, ""))
        return guardado if guardado.isValid() else QgsCoordinateReferenceSystem()

    def _elegir_dxf(self):
        inicio = self.edit_dxf.text() or QgsSettings().value(AJUSTE_CARPETA, "")
        ruta, _ = QFileDialog.getOpenFileName(self, "Plano CAD", inicio, "Dibujo DXF (*.dxf *.DXF)")
        if ruta:
            self.edit_dxf.setText(ruta)
            QgsSettings().setValue(AJUSTE_CARPETA, os.path.dirname(ruta))
            self._leer()

    def _elegir_carpeta(self):
        inicio = self.edit_carpeta.text() or os.path.dirname(self.edit_dxf.text())
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida", inicio)
        if carpeta:
            self.edit_carpeta.setText(carpeta)

    def _leer(self):
        ruta = self.edit_dxf.text().strip()
        self.contenido = None
        self.tabla.setRowCount(0)
        self.etiqueta_resultado.clear()
        if not ruta:
            self._actualizar_resumen()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.contenido = leer_dxf(ruta)
        except ValueError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            self._actualizar_resumen()
            return
        QApplication.restoreOverrideCursor()

        candidatas_lindero = [c for c in self.contenido.capas if not c.parece_curvas and c.cerradas]
        self.tabla.setRowCount(len(self.contenido.capas))
        for i, capa in enumerate(self.contenido.capas):
            self.tabla.setItem(i, 0, QTableWidgetItem(capa.nombre))
            lineas = QTableWidgetItem(f"{capa.lineas}" + (f" ({capa.cerradas} cerradas)" if capa.cerradas else ""))
            lineas.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(i, 1, lineas)
            self.tabla.setItem(i, 2, QTableWidgetItem(_formato_cotas(capa)))
            uso = QComboBox()
            uso.addItems([USO_NINGUNO, USO_CURVAS, USO_LINDERO])
            if capa.parece_curvas:
                uso.setCurrentText(USO_CURVAS)
            elif len(candidatas_lindero) == 1 and capa is candidatas_lindero[0]:
                uso.setCurrentText(USO_LINDERO)
            uso.currentTextChanged.connect(lambda texto, combo=uso: self._cambio_uso(combo, texto))
            self.tabla.setCellWidget(i, 3, uso)

        crs = self.selector_crs.crs()
        if parecen_coordenadas_planas(self.contenido.extension) and crs.isValid() and crs.isGeographic():
            self.selector_crs.setCrs(QgsCoordinateReferenceSystem())
        self._actualizar_resumen()

    def _cambio_uso(self, combo, texto):
        if texto == USO_LINDERO:  # un solo lindero
            for i in range(self.tabla.rowCount()):
                otro = self.tabla.cellWidget(i, 3)
                if otro is not combo and otro.currentText() == USO_LINDERO:
                    otro.setCurrentText(USO_NINGUNO)
        self._actualizar_resumen()

    def _capas_con_uso(self, uso):
        return [self.tabla.item(i, 0).text() for i in range(self.tabla.rowCount())
                if self.tabla.cellWidget(i, 3).currentText() == uso]

    def _centro_geografico(self, crs):
        """Centro del plano en grados según el sistema elegido, para comprobar la zona UTM."""
        xmin, xmax, ymin, ymax = self.contenido.extension
        transformacion = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:4326"),
                                                QgsProject.instance())
        centro = transformacion.transform(QgsPointXY((xmin + xmax) / 2, (ymin + ymax) / 2))
        return f"{_grados(centro.y(), 'N', 'S')}, {_grados(centro.x(), 'E', 'O')}"

    def _actualizar_resumen(self, *_):
        if self.contenido is None:
            self.etiqueta_contenido.setText("")
            self.boton_importar.setEnabled(False)
            return
        c = self.contenido
        celdas = celdas_estimadas(c.extension, self.spin_paso.value())
        filas = [("Tamaño del dibujo:", f"{c.ancho:,.0f} × {c.alto:,.0f} m".replace(",", " ")),
                 ("Celdas del DEM (aprox.):", f"{celdas / 1e6:.1f} millones")]
        faltantes = []  # impiden importar
        crs = self.selector_crs.crs()
        if not crs.isValid():
            faltantes.append("Elija el sistema de coordenadas del plano (WGS 84 / UTM de la zona del "
                             "proyecto: 17 S, 18 S…). El DXF no lo indica.")
        elif crs.isGeographic():
            faltantes.append("El sistema elegido está en grados; las coordenadas del plano están en metros.")
        else:
            filas.append(("Centro del plano:", f"{self._centro_geografico(crs)} "
                                               "<i>(compruebe que es la ubicación del proyecto)</i>"))
        if not self._capas_con_uso(USO_CURVAS):
            faltantes.append("Marque al menos una capa como «Curvas de nivel».")
        avisos = list(faltantes)
        if c.ancho < 1 or c.ancho > 100_000:
            avisos.append("El tamaño del dibujo no parece estar en metros: revise las unidades del CAD.")
        self.etiqueta_contenido.setText(html_tabla(filas) + html_avisos(avisos))
        self.boton_importar.setEnabled(not faltantes)

    # ------------------------------------------------------------- tareas largas

    def _empezar(self):
        self.barra.setValue(0)
        self.barra.setVisible(True)
        self.pestanas.setEnabled(False)
        self.etiqueta_resultado.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def _terminar(self):
        QApplication.restoreOverrideCursor()
        self.barra.setVisible(False)
        self.pestanas.setEnabled(True)

    def _progreso(self, fraccion, texto):
        self.barra.setValue(int(fraccion * 100))
        self.barra.setFormat(f"{texto} %p %")
        QApplication.processEvents()

    def _quitar_capas_de(self, rutas):
        """Pide confirmación para reemplazar archivos y quita del mapa las capas que los usan."""
        existentes = [r for r in rutas if os.path.exists(r)]
        if not existentes:
            return True
        respuesta = QMessageBox.question(
            self, "RiegoLibre", "Ya existen estos archivos y se reemplazarán:\n\n"
            + "\n".join(os.path.basename(r) for r in existentes) + "\n\n¿Continuar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return False
        proyecto = QgsProject.instance()
        for capa in capas_que_usan(existentes):
            proyecto.removeMapLayer(capa.id())
        return True

    # ------------------------------------------------------------- importación del DXF

    def importar(self):
        ruta = self.edit_dxf.text().strip()
        carpeta = self.edit_carpeta.text().strip() or os.path.dirname(ruta)
        base = os.path.splitext(os.path.basename(ruta))[0]
        if not self._quitar_capas_de([os.path.join(carpeta, f"{base}_curvas.gpkg"),
                                      os.path.join(carpeta, f"{base}_dem.tif")]):
            return
        linderos = self._capas_con_uso(USO_LINDERO)
        crs = self.selector_crs.crs()
        self._empezar()
        try:
            resultado = generar_topografia(
                ruta, self._capas_con_uso(USO_CURVAS), crs.toWkt(), carpeta,
                paso_m=self.spin_paso.value(), distancia_max_m=self.spin_distancia.value(),
                capa_lindero=linderos[0] if linderos else None, nombre_base=base, progreso=self._progreso)
        except (ValueError, RuntimeError) as error:
            self._terminar()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        QgsSettings().setValue(AJUSTE_CRS, crs.authid() or crs.toWkt())
        if not QgsProject.instance().crs().isValid():
            QgsProject.instance().setCrs(crs)
        curvas, dem, _ = agregar_al_mapa(resultado, f"Topografía · {base}")
        self.combo_dem_imagen.setLayer(dem)
        self.combo_dem_3d.setLayer(dem)
        if self.iface is not None:
            lienzo = self.iface.mapCanvas()
            lienzo.setExtent(lienzo.mapSettings().layerExtentToOutputExtent(curvas, curvas.extent()))
            lienzo.refresh()
        self._terminar()

        filas = [("Curvas importadas:", f"{resultado.curvas}"),
                 ("Cotas:", f"{resultado.cota_min:.2f} – {resultado.cota_max:.2f} m"),
                 ("DEM:", f"{resultado.columnas} × {resultado.filas} celdas de {resultado.paso_m:g} m "
                          f"({resultado.cobertura * 100:.0f} % con dato)")]
        if resultado.linderos:
            filas.append(("Lindero:", f"{resultado.linderos} polígono(s), {resultado.area_lindero_ha:.2f} ha"))
        filas.append(("Archivos:", f"{os.path.basename(resultado.ruta_dem)}<br>"
                                   f"{os.path.basename(resultado.ruta_curvas)}"))
        self.etiqueta_resultado.setText(
            "<b>Topografía importada.</b> Elija la capa «DEM (curvas del CAD)» como modelo de elevación "
            "en las demás ventanas de RiegoLibre. En las otras pestañas puede descargar la imagen "
            "satelital y ver el terreno en 3D." + html_tabla(filas) + html_avisos(resultado.avisos))

    # ------------------------------------------------------------- imagen satelital

    def _cambio_fuente(self, *_):
        self.combo_capa_fuente.setEnabled(self.combo_fuente.currentData() is None)

    def _dem_elegido(self, combo):
        capa = combo.currentLayer()
        if not isinstance(capa, QgsRasterLayer) or capa.providerType() != "gdal":
            QMessageBox.warning(self, "RiegoLibre", "Elija un DEM guardado en un archivo (GeoTIFF u otro "
                                                    "ráster de GDAL).")
            return None
        return capa

    def descargar_imagen(self):
        dem = self._dem_elegido(self.combo_dem_imagen)
        if dem is None:
            return
        fuente = self.combo_fuente.currentData()
        if fuente is None:
            fuente = self.combo_capa_fuente.currentLayer()
            if fuente is None:
                QMessageBox.warning(self, "RiegoLibre", "Elija la capa ráster de la que se tomará la imagen.")
                return
            if fuente is dem:
                QMessageBox.warning(self, "RiegoLibre", "La capa de la imagen no puede ser el mismo DEM.")
                return
        ruta_dem = dem.source()
        base = os.path.splitext(ruta_dem)[0]
        base = base[:-4] if base.endswith("_dem") else base
        ruta = f"{base}_satelite.tif"
        if not self._quitar_capas_de([ruta]):
            return
        self._empezar()
        try:
            resultado = imagen_para_dem(fuente, dem, ruta, self.spin_resolucion.value(),
                                        self.check_recortar.isChecked(), progreso=self._progreso)
        except (ValueError, RuntimeError) as error:
            self._terminar()
            QMessageBox.warning(self, "RiegoLibre", str(error))
            return
        nombre_fuente = fuente.nombre if hasattr(fuente, "nombre") else fuente.name()
        imagen = QgsRasterLayer(resultado.ruta, f"Imagen satelital ({nombre_fuente})")
        self._agregar_debajo_de_curvas(imagen, dem)
        self._terminar()
        filas = [("Imagen:", f"{resultado.columnas} × {resultado.filas} píxeles de {resultado.resolucion_m:g} m"),
                 ("Archivo:", os.path.basename(resultado.ruta))]
        if resultado.zoom is not None:
            filas.insert(1, ("Fuente:", f"{nombre_fuente}, zoom {resultado.zoom} "
                                        f"(≈ {resultado.metros_por_pixel_fuente:.2f} m por píxel)"))
        avisos = []
        if resultado.metros_por_pixel_fuente and resultado.metros_por_pixel_fuente > 1.5 * resultado.resolucion_m:
            avisos.append(f"La fuente solo tiene ≈ {resultado.metros_por_pixel_fuente:.1f} m por píxel en esta "
                          "zona: la imagen se ve más borrosa que la resolución elegida. Pruebe otra fuente.")
        self.etiqueta_resultado.setText("<b>Imagen satelital descargada.</b>" + html_tabla(filas)
                                        + html_avisos(avisos))

    def _agregar_debajo_de_curvas(self, imagen, dem):
        """Agrega la imagen en el grupo del DEM, justo encima de él (debajo de curvas y lindero)."""
        proyecto = QgsProject.instance()
        proyecto.addMapLayer(imagen, False)
        nodo_dem = proyecto.layerTreeRoot().findLayer(dem.id())
        if nodo_dem is None:
            proyecto.layerTreeRoot().insertLayer(0, imagen)
            return
        grupo = nodo_dem.parent()
        grupo.insertLayer(grupo.children().index(nodo_dem), imagen)

    # ------------------------------------------------------------- vista 3D

    def abrir_3d(self):
        dem = self._dem_elegido(self.combo_dem_3d)
        if dem is None:
            return
        try:
            abrir_vista_3d(self.iface, dem, self.spin_exageracion.value())
        except ValueError as error:
            QMessageBox.warning(self, "RiegoLibre", str(error))
