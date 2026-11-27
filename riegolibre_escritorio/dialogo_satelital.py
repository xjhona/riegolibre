# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Ventana «Imagen satelital»: fuente de teselas, resolución y zona de la imagen de fondo; y la lectura y escritura
de JPEG y PNG con Qt (lo que `satelital.py`, sin Qt, no puede hacer)."""

import math

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLabel, QVBoxLayout)

from . import satelital

MARGEN_M = 50.0
RESOLUCION_M = 0.5
CALIDAD_JPEG = 85


# ------------------------------------------------------------------ imágenes con Qt

def decodificar(contenido: bytes):
    """Matriz filas × columnas × 3 (uint8) de un JPEG o PNG. ValueError si no es una imagen."""
    import numpy

    imagen = QImage()
    if not imagen.loadFromData(contenido):
        raise ValueError("no es una imagen")
    imagen = imagen.convertToFormat(QImage.Format.Format_RGB888)
    ancho, alto = imagen.width(), imagen.height()
    datos = numpy.frombuffer(imagen.constBits(), numpy.uint8, count=imagen.sizeInBytes())
    return datos.reshape(alto, imagen.bytesPerLine())[:, :ancho * 3].reshape(alto, ancho, 3).copy()


def codificar_jpeg(pixeles, calidad: int = CALIDAD_JPEG) -> bytes:
    """JPEG de una matriz filas × columnas × 3 (uint8)."""
    import numpy

    pixeles = numpy.ascontiguousarray(pixeles, numpy.uint8)
    alto, ancho = pixeles.shape[:2]
    imagen = QImage(pixeles.data, ancho, alto, 3 * ancho, QImage.Format.Format_RGB888)
    datos = QByteArray()
    buffer = QBuffer(datos)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not imagen.save(buffer, "JPG", calidad):
        raise ValueError("No se pudo comprimir la imagen en JPEG.")
    buffer.close()
    return bytes(datos.data())


def tamano_imagen(ruta: str):
    """(columnas, filas) de una imagen sin leerla entera. ValueError si no se puede leer."""
    lector = QImageReader(ruta)
    tamano = lector.size()
    if not tamano.isValid() or tamano.isEmpty():
        raise ValueError(f"No se pudo leer la imagen: {lector.errorString()}")
    return tamano.width(), tamano.height()


# ------------------------------------------------------------------ ventana

def _caja(minimo, maximo, decimales, sufijo, valor, paso=1.0):
    caja = QDoubleSpinBox()
    caja.setRange(minimo, maximo)
    caja.setDecimals(decimales)
    caja.setSuffix(sufijo)
    caja.setSingleStep(paso)
    caja.setValue(valor)
    return caja


class DialogoSatelital(QDialog):
    """Pide la fuente, la resolución y la zona (por omisión, la del proyecto con un margen)."""

    def __init__(self, extension, zona: int, sur: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imagen satelital")
        self.extension, self.zona, self.sur = extension, zona, sur
        self.resize(460, 0)

        self.combo_fuente = QComboBox()
        for fuente in satelital.FUENTES:
            self.combo_fuente.addItem(fuente.nombre)
        self.caja_resolucion = _caja(0.1, 20, 2, " m", RESOLUCION_M, 0.1)
        self.caja_resolucion.setToolTip("Tamaño de cada píxel de la imagen en el terreno")
        imagen = QGroupBox("Imagen")
        f = QFormLayout(imagen)
        f.addRow("Fuente:", self.combo_fuente)
        f.addRow("Resolución (tamaño del píxel):", self.caja_resolucion)

        self.caja_margen = _caja(0, 5000, 0, " m", MARGEN_M, 10)
        self.caja_margen.setToolTip("Alrededor de los lotes, la fuente, la matriz y las curvas de nivel")
        self.cajas_zona = [_caja(-1e8, 1e8, 1, " m", 0.0, 10) for _ in range(4)]
        zona_g = QGroupBox(f"Zona (UTM zona {zona} {'sur' if sur else 'norte'})")
        f = QFormLayout(zona_g)
        f.addRow("Margen alrededor del proyecto:", self.caja_margen)
        for texto, caja in zip(("Este mínimo:", "Norte mínimo:", "Este máximo:", "Norte máximo:"), self.cajas_zona):
            f.addRow(texto, caja)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Descargar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)

        principal = QVBoxLayout(self)
        principal.addWidget(imagen)
        principal.addWidget(zona_g)
        principal.addWidget(self.aviso)
        principal.addWidget(QLabel("La imagen se guarda dentro del proyecto: después se ve sin internet."))
        principal.addWidget(self.botones)

        self._poner_margen()
        self.caja_margen.valueChanged.connect(lambda _: self._poner_margen())
        for caja in self.cajas_zona + [self.caja_resolucion]:
            caja.valueChanged.connect(lambda _: self._revisar())
        self.combo_fuente.currentIndexChanged.connect(lambda _: self._revisar())

    def _poner_margen(self):
        margen = self.caja_margen.value()
        xmin, ymin, xmax, ymax = self.extension
        for caja, valor in zip(self.cajas_zona, (xmin - margen, ymin - margen, xmax + margen, ymax + margen)):
            caja.blockSignals(True)
            caja.setValue(valor)
            caja.blockSignals(False)
        self._revisar()

    def fuente(self) -> satelital.FuenteTeselas:
        return satelital.FUENTES[self.combo_fuente.currentIndex()]

    def zona_utm(self):
        return tuple(caja.value() for caja in self.cajas_zona)

    def valores(self) -> dict:
        return {"fuente": self.fuente(), "zona_utm": self.zona_utm(), "resolucion_m": self.caja_resolucion.value()}

    def _revisar(self):
        """Estima el tamaño de la imagen y las teselas; apaga «Descargar» si es demasiado grande."""
        boton = self.botones.button(QDialogButtonBox.StandardButton.Ok)
        resolucion = self.caja_resolucion.value()
        xmin, ymin, xmax, ymax = self.zona_utm()
        if xmax <= xmin or ymax <= ymin:
            self.aviso.setText("La zona está vacía: el máximo debe ser mayor que el mínimo.")
            boton.setEnabled(False)
            return
        fuente = self.fuente()
        _, lat = satelital.utm_a_geograficas((xmin + xmax) / 2, (ymin + ymax) / 2, self.zona, self.sur)
        zoom = satelital.zoom_para_resolucion(lat, resolucion, fuente.zoom_max)
        try:
            pixeles, teselas = satelital.estimar((xmin, ymin, xmax, ymax), resolucion, self.zona, self.sur, zoom)
        except ValueError as error:
            self.aviso.setText(str(error))
            boton.setEnabled(False)
            return
        problema = None
        if pixeles > satelital.MAX_PIXELES:
            sugerida = math.ceil(math.sqrt(pixeles / satelital.MAX_PIXELES) * resolucion * 10) / 10
            problema = (f"La imagen tendría {pixeles / 1e6:.0f} millones de píxeles: use una resolución de "
                        f"{sugerida:g} m o más.")
        elif teselas > satelital.MAX_TESELAS:
            problema = f"Habría que descargar {teselas} teselas: use una resolución más gruesa o una zona más chica."
        if problema:
            self.aviso.setText(problema)
        else:
            self.aviso.setText(
                f"{(xmax - xmin) / 1000:.2f} × {(ymax - ymin) / 1000:.2f} km · {pixeles / 1e6:.1f} millones de "
                f"píxeles · unas {teselas} teselas del zoom {zoom} ({satelital.metros_por_pixel(lat, zoom):.2f} m "
                "por píxel), o del mayor zoom con imagen en la zona si es menor.")
        boton.setEnabled(problema is None)
