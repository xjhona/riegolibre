"""Memoria de cálculo del proyecto: vista previa y exportación a PDF, ODT (Word/LibreOffice) y HTML."""

import base64
import configparser
import json
import os
import re
from datetime import date

from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtCore import QMarginsF, Qt, QUrl
from qgis.PyQt.QtGui import (QImage, QPageLayout, QPageSize, QPdfWriter,
                             QTextDocument, QTextDocumentWriter)
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QLineEdit, QMessageBox, QPlainTextEdit,
                                 QPushButton, QSplitter, QTextBrowser,
                                 QVBoxLayout, QWidget)

from ..nucleo import cargar_catalogo_tuberias
from ..nucleo.memoria import DatosMemoria, graficos_memoria, memoria_html

ENTRADA_MEMORIA = ("RiegoLibre", "memoria")  # datos del documento, guardados en el proyecto
AJUSTE_PROYECTISTA = "RiegoLibre/proyectista"
FILTROS = {"PDF (*.pdf)": ".pdf", "Word / LibreOffice (*.odt)": ".odt", "Página web (*.html)": ".html"}


def version_complemento():
    metadatos = configparser.ConfigParser()
    metadatos.read(os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt"), encoding="utf-8")
    return metadatos.get("general", "version", fallback="")


class DialogoMemoria(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Memoria de cálculo")
        self.resize(1200, 820)
        self.tuberias = {t.nombre: t for t in cargar_catalogo_tuberias()}
        self.datos_memoria = None
        self.imagenes = {}  # clave -> PNG (bytes)

        grupo_datos = QGroupBox("Datos del documento")
        formulario = QFormLayout(grupo_datos)
        self.edit_titulo = QLineEdit()
        self.edit_proyecto = QLineEdit()
        self.edit_cliente = QLineEdit()
        self.edit_ubicacion = QLineEdit()
        self.edit_proyectista = QLineEdit()
        self.edit_fecha = QLineEdit(f"{date.today():%d/%m/%Y}")
        for etiqueta, control in (("Título:", self.edit_titulo), ("Proyecto:", self.edit_proyecto),
                                  ("Cliente:", self.edit_cliente), ("Ubicación:", self.edit_ubicacion),
                                  ("Proyectista:", self.edit_proyectista), ("Fecha:", self.edit_fecha)):
            formulario.addRow(etiqueta, control)
        self.edit_notas = QPlainTextEdit()
        self.edit_notas.setPlaceholderText("Observaciones y recomendaciones que se añaden al final.")
        self.edit_notas.setMaximumHeight(120)
        formulario.addRow("Observaciones:", self.edit_notas)

        grupo_contenido = QGroupBox("Contenido")
        capa_contenido = QVBoxLayout(grupo_contenido)
        self.check_mapa = QCheckBox("Plano general (capas visibles del proyecto)")
        self.check_graficos = QCheckBox("Gráficos de presiones")
        self.check_presupuesto = QCheckBox("Presupuesto (lista de precios de la ventana de materiales)")
        self.check_detalle = QCheckBox("Detalle de todas las partidas del presupuesto")
        for control in (self.check_mapa, self.check_graficos, self.check_presupuesto, self.check_detalle):
            control.setChecked(True)
            capa_contenido.addWidget(control)
        self.check_presupuesto.toggled.connect(self.check_detalle.setEnabled)

        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setTextFormat(Qt.TextFormat.RichText)
        boton_actualizar = QPushButton("Actualizar vista previa")
        boton_actualizar.clicked.connect(self.actualizar)

        izquierda = QWidget()
        capa_izquierda = QVBoxLayout(izquierda)
        capa_izquierda.addWidget(grupo_datos)
        capa_izquierda.addWidget(grupo_contenido)
        capa_izquierda.addWidget(boton_actualizar)
        capa_izquierda.addWidget(self.etiqueta_estado)
        capa_izquierda.addStretch()
        izquierda.setMinimumWidth(360)
        izquierda.setMaximumWidth(460)

        self.vista = QTextBrowser()
        self.vista.setOpenLinks(False)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(izquierda)
        divisor.addWidget(self.vista)
        divisor.setStretchFactor(1, 1)

        botones = QHBoxLayout()
        botones.addWidget(QLabel("La memoria se arma con los resultados calculados en el proyecto."))
        botones.addStretch()
        boton_exportar = QPushButton("Exportar…")
        boton_exportar.clicked.connect(self._elegir_exportacion)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)
        botones.addWidget(boton_exportar)
        botones.addWidget(boton_cerrar)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addLayout(botones)
        self._cargar_campos()

    def showEvent(self, evento):  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self._cargar_campos()
        self.actualizar()

    # ------------------------------------------------------------- campos

    def _campos(self):
        return {"titulo": self.edit_titulo, "proyecto": self.edit_proyecto, "cliente": self.edit_cliente,
                "ubicacion": self.edit_ubicacion, "proyectista": self.edit_proyectista}

    def _cargar_campos(self):
        """Datos del documento guardados en el proyecto (o valores por defecto)."""
        texto, _ok = QgsProject.instance().readEntry(*ENTRADA_MEMORIA, "{}")
        try:
            valores = json.loads(texto)
        except ValueError:
            valores = {}
        por_defecto = {"titulo": DatosMemoria.titulo, "proyecto": QgsProject.instance().baseName(),
                       "proyectista": QgsSettings().value(AJUSTE_PROYECTISTA, "")}
        for clave, control in self._campos().items():
            control.setText(valores.get(clave) or por_defecto.get(clave, ""))
        self.edit_notas.setPlainText(valores.get("notas", ""))

    def _guardar_campos(self):
        valores = {clave: control.text().strip() for clave, control in self._campos().items()}
        valores["notas"] = self.edit_notas.toPlainText()
        texto = json.dumps(valores, ensure_ascii=False)
        if texto != QgsProject.instance().readEntry(*ENTRADA_MEMORIA, "")[0]:  # no marcar cambios sin motivo
            QgsProject.instance().writeEntry(*ENTRADA_MEMORIA, texto)
        if valores["proyectista"]:
            QgsSettings().setValue(AJUSTE_PROYECTISTA, valores["proyectista"])

    # ------------------------------------------------------------ contenido

    def _datos(self):
        from ..integracion.materiales_mapa import presupuesto_del_proyecto
        from ..integracion.memoria_mapa import resumenes_del_proyecto
        subunidades, red, avisos = resumenes_del_proyecto()
        presupuesto = None
        if self.check_presupuesto.isChecked():
            try:
                presupuesto = presupuesto_del_proyecto(self.tuberias)
            except (OSError, ValueError, UnicodeDecodeError) as error:
                avisos.append(f"No se pudo leer la lista de precios: {error}")
            if presupuesto is not None:
                presupuesto.detalle = self.check_detalle.isChecked()
        return DatosMemoria(
            titulo=self.edit_titulo.text().strip() or DatosMemoria.titulo,
            proyecto=self.edit_proyecto.text().strip(), cliente=self.edit_cliente.text().strip(),
            ubicacion=self.edit_ubicacion.text().strip(), proyectista=self.edit_proyectista.text().strip(),
            fecha=self.edit_fecha.text().strip(), notas=self.edit_notas.toPlainText(),
            subunidades=subunidades, red=red, presupuesto=presupuesto, avisos=avisos,
            version=version_complemento())

    def actualizar(self):
        """Vuelve a leer los resultados del proyecto y regenera la vista previa."""
        from ..integracion.memoria_mapa import imagen_mapa
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._guardar_campos()
            self.datos_memoria = datos = self._datos()
            self.imagenes = {}
            if self.check_mapa.isChecked():
                mapa = imagen_mapa()
                if mapa:
                    self.imagenes["mapa"] = mapa
            if self.check_graficos.isChecked():
                self.imagenes.update(graficos_memoria(datos))
            self.vista.setDocument(self._documento())
        finally:
            QApplication.restoreOverrideCursor()
        self._mostrar_estado(datos)

    def _mostrar_estado(self, datos):
        if not datos.subunidades and datos.red is None:
            self.etiqueta_estado.setText(
                "<span style='color:#c62828'>No hay resultados de diseño en el proyecto. Calcule las "
                "subunidades en el mapa y la red principal; luego pulse <i>Actualizar vista previa</i>.</span>")
            return
        partes = [f"{len(datos.subunidades)} subunidades", "red principal y bomba" if datos.red else "sin red principal"]
        if datos.presupuesto is not None:
            partes.append(f"presupuesto con {len(datos.presupuesto.partidas)} partidas")
        elif self.check_presupuesto.isChecked():
            partes.append("sin presupuesto (abra una lista de precios en la ventana de materiales)")
        texto = "Incluye: " + ", ".join(partes) + "."
        if datos.avisos:
            texto += "<br><span style='color:#c62828'>" + "<br>".join("⚠ " + a for a in datos.avisos) + "</span>"
        self.etiqueta_estado.setText(texto)

    def _documento(self):
        """QTextDocument de la memoria, con las imágenes como recursos (para la vista, PDF y ODT)."""
        documento = QTextDocument(self)
        for clave, datos in self.imagenes.items():
            documento.addResource(QTextDocument.ResourceType.ImageResource, QUrl(f"{clave}.png"),
                                  QImage.fromData(datos, "PNG"))
        documento.setHtml(memoria_html(self.datos_memoria, {c: f"{c}.png" for c in self.imagenes}))
        return documento

    def html_autonomo(self):
        """HTML con las imágenes incrustadas: un solo archivo que se abre en cualquier navegador."""
        fuentes = {c: "data:image/png;base64," + base64.b64encode(d).decode("ascii")
                   for c, d in self.imagenes.items()}
        return memoria_html(self.datos_memoria, fuentes)

    # ------------------------------------------------------------ exportación

    def _elegir_exportacion(self):
        nombre = re.sub(r"[^\w\- ]+", "", self.edit_proyecto.text()).strip() or "proyecto"
        ruta, filtro = QFileDialog.getSaveFileName(self, "Exportar memoria de cálculo",
                                                   f"Memoria de cálculo - {nombre}.pdf", ";;".join(FILTROS))
        if not ruta:
            return
        if os.path.splitext(ruta)[1].lower() not in FILTROS.values():
            ruta += FILTROS.get(filtro, ".pdf")
        self.exportar(ruta)

    def exportar(self, ruta):
        """Exporta según la extensión (.pdf, .odt o .html). Devuelve la ruta, o None si falla."""
        self.actualizar()
        extension = os.path.splitext(ruta)[1].lower()
        try:
            if extension == ".pdf":
                self._exportar_pdf(ruta)
            elif extension == ".odt":
                escritor = QTextDocumentWriter(ruta, b"odf")
                if not escritor.write(self._documento()):
                    raise OSError(f"no se pudo escribir {ruta}")
            else:
                with open(ruta, "w", encoding="utf-8") as archivo:
                    archivo.write(self.html_autonomo())
        except OSError as error:
            QMessageBox.warning(self, "RiegoLibre", f"No se pudo guardar la memoria:\n{error}")
            return None
        if self.iface is not None:
            self.iface.messageBar().pushSuccess("RiegoLibre", f"Memoria de cálculo guardada en {ruta}")
        return ruta

    def _exportar_pdf(self, ruta):
        escritor = QPdfWriter(ruta)
        escritor.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        # Sin márgenes propios, QTextDocument.print usa 2 mm de la hoja más 2 cm del documento
        # y numera las páginas.
        escritor.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        escritor.setTitle(self.datos_memoria.titulo)
        escritor.setCreator("RiegoLibre")
        documento = self._documento()
        imprimir = getattr(documento, "print_", None) or getattr(documento, "print")
        imprimir(escritor)
        del escritor  # cierra el archivo
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            raise OSError(f"no se pudo escribir {ruta}")
