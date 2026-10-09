"""Datos del proyecto para la memoria de cálculo: resúmenes guardados en las capas y plano general."""

import json
import math

from qgis.core import (Qgis, QgsCoordinateTransform, QgsMapRendererParallelJob,
                       QgsMapSettings, QgsProject, QgsRectangle)
from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from .materiales_mapa import _tipo, capas_de_resultado

# Propiedad de la capa con el resumen del cálculo (JSON): en la capa de la válvula
# de cada subunidad y en la capa de la bomba de la red principal.
PROPIEDAD_RESUMEN = "riegolibre/resumen"


def guardar_resumen(capa, resumen):
    capa.setCustomProperty(PROPIEDAD_RESUMEN, json.dumps(resumen, ensure_ascii=False))


def resumenes_del_proyecto(proyecto=None):
    """Devuelve (resúmenes de subunidades ordenados por nombre, resumen de la red o None, avisos)."""
    subunidades, red, avisos = [], None, []
    for capa in capas_de_resultado(proyecto):
        tipo = _tipo(capa)
        if tipo not in ("valvula", "bomba"):
            continue
        try:
            resumen = json.loads(capa.customProperty(PROPIEDAD_RESUMEN) or "")
        except (TypeError, ValueError):
            resumen = None
        if not isinstance(resumen, dict):
            avisos.append(f"«{capa.name()}» no tiene los datos para la memoria (se calculó con una versión "
                          "anterior de RiegoLibre): vuelva a calcularla para incluirla.")
        elif tipo == "valvula":
            subunidades.append(resumen)
        elif red is None:
            red = resumen
        else:
            avisos.append("Hay más de una red principal calculada en el proyecto; la memoria incluye una sola.")
    subunidades.sort(key=lambda s: s["nombre"].lower())
    return subunidades, red, avisos


# ------------------------------------------------------------------ plano


def _extension(capas, crs, proyecto):
    extension = None
    for capa in capas:
        if capa.featureCount() == 0:
            continue
        caja = QgsCoordinateTransform(capa.crs(), crs, proyecto).transformBoundingBox(capa.extent())
        if extension is None:
            extension = QgsRectangle(caja)
        else:
            extension.combineExtentWith(caja)
    if extension is None:
        return None
    margen = max(extension.width(), extension.height()) * 0.05 or 25.0
    extension = extension.buffered(margen)
    # Espacio libre abajo para la barra de escala y arriba para la flecha del norte.
    alto = extension.height()
    extension.setYMinimum(extension.yMinimum() - 0.12 * alto)
    extension.setYMaximum(extension.yMaximum() + 0.08 * alto)
    return extension


def _longitud_redonda(maximo):
    """La mayor longitud 1, 2 o 5 × 10^n que no supera el máximo."""
    potencia = 10 ** math.floor(math.log10(maximo))
    return max(p * potencia for p in (1, 2, 5) if p * potencia <= maximo)


def _dibujar_escala_y_norte(imagen, metros_por_pixel):
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    ancho, alto = imagen.width(), imagen.height()
    unidad = max(ancho / 900, 1.0)  # tamaño de referencia de textos y líneas
    fuente = QFont("Arial")
    fuente.setPixelSize(int(14 * unidad))
    pintor.setFont(fuente)

    # Barra de escala abajo a la izquierda (dos tramos).
    longitud_m = _longitud_redonda(ancho * 0.25 * metros_por_pixel)
    largo = longitud_m / metros_por_pixel
    x0, y0, grueso = 16 * unidad, alto - 26 * unidad, 7 * unidad
    pintor.fillRect(QRectF(x0 - 8 * unidad, y0 - 24 * unidad, largo + 70 * unidad, 42 * unidad),
                    QColor(255, 255, 255, 215))
    pintor.setPen(QPen(QColor("black"), max(unidad, 1.0)))
    for i in range(2):
        rectangulo = QRectF(x0 + i * largo / 2, y0, largo / 2, grueso)
        pintor.fillRect(rectangulo, QColor("black") if i == 0 else QColor("white"))
        pintor.drawRect(rectangulo)
    texto = f"{longitud_m:g} m" if longitud_m < 1000 else f"{longitud_m / 1000:g} km"
    pintor.drawText(QPointF(x0, y0 - 6 * unidad), "0")
    pintor.drawText(QPointF(x0 + largo - 6 * unidad, y0 - 6 * unidad), texto)

    # Flecha del norte arriba a la derecha (el SRC proyectado tiene el norte hacia arriba).
    cx, cy, h = ancho - 34 * unidad, 22 * unidad, 34 * unidad
    pintor.setBrush(QColor("black"))
    pintor.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(cx - 10 * unidad, cy + h),
                                  QPointF(cx, cy + h * 0.75), QPointF(cx + 10 * unidad, cy + h)]))
    fuente.setBold(True)
    pintor.setFont(fuente)
    pintor.drawText(QRectF(cx - 15 * unidad, cy + h, 30 * unidad, 20 * unidad),
                    int(Qt.AlignmentFlag.AlignCenter), "N")
    pintor.end()


def imagen_mapa(proyecto=None, ancho_px=1800):
    """Plano de los resultados (PNG en bytes) con las capas visibles del proyecto, o None.

    El encuadre abarca todas las capas de resultado de RiegoLibre, que se dibujan
    aunque estén ocultas en el panel de capas.
    """
    proyecto = proyecto or QgsProject.instance()
    resultado = capas_de_resultado(proyecto)
    if not resultado:
        return None
    crs = proyecto.crs() if proyecto.crs().isValid() else resultado[0].crs()
    extension = _extension(resultado, crs, proyecto)
    if extension is None:
        return None
    visibles = [c for c in proyecto.layerTreeRoot().checkedLayers() if c is not None and c.isValid()]
    capas = [c for c in resultado if c not in visibles] + visibles  # la primera se dibuja encima

    proporcion = min(max(extension.height() / extension.width(), 0.45), 1.1)
    ajustes = QgsMapSettings()
    ajustes.setLayers(capas)
    ajustes.setDestinationCrs(crs)
    ajustes.setTransformContext(proyecto.transformContext())
    ajustes.setOutputSize(QSize(ancho_px, int(ancho_px * proporcion)))
    ajustes.setExtent(extension)
    ajustes.setBackgroundColor(QColor("white"))
    ajustes.setFlag(Qgis.MapSettingsFlag.Antialiasing, True)
    trabajo = QgsMapRendererParallelJob(ajustes)
    trabajo.start()
    trabajo.waitForFinished()
    imagen = trabajo.renderedImage()
    if crs.mapUnits() == Qgis.DistanceUnit.Meters:
        _dibujar_escala_y_norte(imagen, ajustes.mapUnitsPerPixel())

    datos = QByteArray()
    salida = QBuffer(datos)
    salida.open(QIODevice.OpenModeFlag.WriteOnly)
    imagen.save(salida, "PNG")
    salida.close()
    return bytes(datos)
