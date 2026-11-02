# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Identidad visual de las ventanas de RiegoLibre: tipografía geométrica y paleta monocromática de alto contraste.

Hay dos temas (claro y oscuro) y la opción de dejar el aspecto estándar de QGIS. La paleta solo tiene grises, negro
y blanco: los colores de estado (verde «cumple», rojo «no cumple») y los de los turnos NO pasan por aquí; siguen
fijos donde se usan y la hoja de estilo no los toca.

Cada ventana llama a `aplicar_tema(self)` al final de su constructor; al cambiar de tema se repinta las abiertas.
"""

import os
import tempfile
import weakref

NOMBRES = {"claro": "Fondo claro, texto negro", "oscuro": "Fondo oscuro, texto blanco",
           "qgis": "Estándar de QGIS (sin tema)"}
TEMA_POR_DEFECTO = "claro"
CLAVE = "RiegoLibre/tema"

# Tipografías en orden de preferencia: la primera instalada. Bahnschrift (DIN geométrica) viene con Windows 10/11.
FUENTES = ("Bahnschrift", "D-DIN", "Barlow", "Segoe UI", "Arial")

PALETAS = {
    "claro": {
        "fondo": "#ffffff", "superficie": "#f4f4f4", "borde": "#c9c9c9", "texto": "#0a0a0a",
        "suave": "#585858", "acento": "#000000", "sobre_acento": "#ffffff", "apagado": "#a1a1a1",
    },
    "oscuro": {
        "fondo": "#0a0a0a", "superficie": "#161616", "borde": "#3b3b3b", "texto": "#f5f5f5",
        "suave": "#a3a3a3", "acento": "#ffffff", "sobre_acento": "#000000", "apagado": "#5d5d5d",
    },
}

_plantilla = """
QDialog, QWidget {{ background-color: {fondo}; color: {texto}; font-family: "{familia}"; }}
QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}
QToolTip {{ background-color: {superficie}; color: {texto}; border: 1px solid {borde}; }}

QGroupBox {{ border: 1px solid {borde}; margin-top: 14px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {suave}; }}

QPushButton, QToolButton {{ background-color: transparent; color: {texto}; border: 1px solid {texto};
    padding: 5px 16px; min-height: 18px; }}
QPushButton:hover, QToolButton:hover {{ background-color: {acento}; color: {sobre_acento}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {suave}; color: {fondo}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {apagado}; border-color: {apagado};
    background-color: transparent; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser, QListView, QTreeView,
QTableView, QTableWidget {{ background-color: {superficie}; border: 1px solid {borde}; padding: 3px;
    selection-background-color: {acento}; selection-color: {sobre_acento}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {texto}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {apagado}; }}
QComboBox QAbstractItemView {{ background-color: {superficie}; border: 1px solid {texto};
    selection-background-color: {acento}; selection-color: {sobre_acento}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{flecha_abajo}"); width: 10px; height: 10px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; background-color: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
    subcontrol-position: bottom right; width: 18px; border: none; background-color: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{ background-color: {borde}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{flecha_arriba}"); width: 8px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{flecha_abajo}"); width: 8px; height: 8px; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {texto};
    background-color: {superficie}; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked {{ background-color: {acento}; image: url("{marca}"); }}
QRadioButton::indicator:checked {{ background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 {acento}, stop:0.5 {acento}, stop:0.6 {superficie}, stop:1 {superficie}); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {apagado}; }}

QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{ color: {apagado}; }}

QTableView, QTableWidget {{ gridline-color: {borde}; padding: 0; }}
QListView, QTableView, QTreeView {{ alternate-background-color: {fondo}; }}
QListView::indicator, QTableView::indicator, QTreeView::indicator {{ width: 14px; height: 14px;
    border: 1px solid {texto}; background-color: {superficie}; }}
QListView::indicator:checked, QTableView::indicator:checked, QTreeView::indicator:checked {{
    background-color: {acento}; image: url("{marca}"); }}

QProgressBar {{ border: 1px solid {borde}; background-color: {superficie}; text-align: center; min-height: 14px; }}
QProgressBar::chunk {{ background-color: {borde}; }}

QMenu {{ background-color: {superficie}; border: 1px solid {texto}; padding: 2px; }}
QMenu::item {{ padding: 5px 22px; background-color: transparent; }}
QMenu::item:selected {{ background-color: {acento}; color: {sobre_acento}; }}
QMenu::item:disabled {{ color: {apagado}; }}
QMenu::separator {{ height: 1px; background-color: {borde}; margin: 3px 0; }}
QHeaderView::section {{ background-color: {fondo}; color: {suave}; border: none;
    border-bottom: 1px solid {texto}; padding: 5px 6px; }}

QTabWidget::pane {{ border: 1px solid {borde}; top: -1px; }}
QTabBar::tab {{ background-color: transparent; color: {suave}; padding: 7px 16px;
    border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {texto}; border-bottom: 2px solid {texto}; }}
QTabBar::tab:hover {{ color: {texto}; }}

QSplitter::handle {{ background-color: {borde}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QScrollBar:vertical {{ background-color: {fondo}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background-color: {fondo}; height: 10px; margin: 0; }}
QScrollBar::handle {{ background-color: {borde}; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background-color: {suave}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""

_ventanas = weakref.WeakSet()
_familia = None


def familia_tipografica():
    """Primera de FUENTES que esté instalada en este computador."""
    global _familia
    if _familia is None:
        from qgis.PyQt.QtGui import QFontDatabase
        try:
            instaladas = set(QFontDatabase.families())
        except TypeError:  # Qt5: método de instancia
            instaladas = set(QFontDatabase().families())
        _familia = next((f for f in FUENTES if f in instaladas), FUENTES[-1])
    return _familia


def _iconos(nombre):
    """Flechas y marca de verificación del tema, como SVG en la carpeta temporal (QSS solo acepta archivos).

    Se regeneran en cada llamada porque cuestan casi nada y así siguen a la paleta.
    """
    paleta = PALETAS[nombre]
    carpeta = os.path.join(tempfile.gettempdir(), "riegolibre_tema")
    os.makedirs(carpeta, exist_ok=True)
    formas = {
        "flecha_abajo": ("M1 3 L5 7 L9 3", paleta["texto"]),
        "flecha_arriba": ("M1 7 L5 3 L9 7", paleta["texto"]),
        "marca": ("M2 5.5 L4.3 8 L8.2 2.2", paleta["sobre_acento"]),
    }
    rutas = {}
    for clave, (trazo, color) in formas.items():
        ruta = os.path.join(carpeta, f"{clave}_{nombre}.svg")
        with open(ruta, "w", encoding="utf-8") as archivo:
            archivo.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                          f'<path d="{trazo}" fill="none" stroke="{color}" stroke-width="1.6"/></svg>')
        rutas[clave] = ruta.replace("\\", "/")
    return rutas


def hoja_de_estilo(nombre, familia=None):
    """Hoja de estilo (QSS) del tema `nombre`; cadena vacía para el aspecto estándar de QGIS."""
    if nombre == "qgis":
        return ""
    if nombre not in PALETAS:
        raise ValueError(f"Tema desconocido: {nombre!r}")
    return _plantilla.format(familia=familia or familia_tipografica(), **PALETAS[nombre], **_iconos(nombre))


def tema_actual():
    from qgis.PyQt.QtCore import QSettings
    nombre = QSettings().value(CLAVE, TEMA_POR_DEFECTO)
    return nombre if nombre in NOMBRES else TEMA_POR_DEFECTO


def _repintar_figuras(ventana):
    """Pinta con el tema los lienzos de matplotlib de la ventana, también los que aún no tienen gráfica."""
    if ventana is None:
        return
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    except ImportError:  # QGIS sin matplotlib
        return
    try:
        for lienzo in ventana.findChildren(FigureCanvasQTAgg):
            pintar_figura(lienzo.figure)
            lienzo.draw_idle()
    except RuntimeError:  # la ventana ya fue destruida en Qt
        pass


def aplicar_tema(ventana):
    """Da a la ventana el tema elegido y la recuerda para repintarla si se cambia.

    Se llama al empezar el constructor; los lienzos de gráficas, que se crean después, se pintan al volver al
    bucle de eventos.
    """
    from qgis.PyQt.QtCore import QTimer
    _ventanas.add(ventana)
    ventana.setStyleSheet(hoja_de_estilo(tema_actual()))
    referencia = weakref.ref(ventana)
    QTimer.singleShot(0, lambda: _repintar_figuras(referencia()))


def sombra_solo_lectura():
    """Sombreado de las celdas que no se pueden editar: oscurece en el tema claro y aclara en el oscuro."""
    from qgis.PyQt.QtGui import QColor
    return QColor(255, 255, 255, 16) if tema_actual() == "oscuro" else QColor(0, 0, 0, 12)


# Vista previa de un documento (la memoria de cálculo): se muestra como una hoja blanca en cualquier tema, porque su
# propio CSS fija el color del texto para el papel y el PDF.
ESTILO_PAPEL = "QTextBrowser { background-color: #ffffff; color: #212121; }"


def pintar_figura(figura):
    """Fondo, ejes y texto de una figura de matplotlib con la paleta del tema.

    Solo toca el marco: las series (azul, verde, rojo…) conservan su color. Con el tema «qgis» deja el marco claro.
    Se llama después de dibujar y antes de `lienzo.draw()`; los lienzos vacíos y los ya dibujados los repinta
    `aplicar_tema`/`cambiar_tema`.
    """
    paleta = PALETAS.get(tema_actual(), PALETAS["claro"])
    figura.set_facecolor(paleta["fondo"])
    for ejes in figura.axes:
        ejes.set_facecolor(paleta["fondo"])
        ejes.tick_params(which="both", colors=paleta["texto"])
        for rotulo in (ejes.xaxis.label, ejes.yaxis.label, ejes.title):
            rotulo.set_color(paleta["texto"])
        for espina in ejes.spines.values():
            espina.set_color(paleta["suave"])
        for linea in ejes.get_xgridlines() + ejes.get_ygridlines():
            linea.set_color(paleta["borde"])
        leyenda = ejes.get_legend()
        if leyenda is not None:
            leyenda.get_frame().set_facecolor(paleta["superficie"])
            leyenda.get_frame().set_edgecolor(paleta["borde"])
            for texto in leyenda.get_texts():
                texto.set_color(paleta["texto"])


def cambiar_tema(nombre):
    """Guarda el tema y lo aplica a las ventanas de RiegoLibre que estén abiertas."""
    if nombre not in NOMBRES:
        raise ValueError(f"Tema desconocido: {nombre!r}")
    from qgis.PyQt.QtCore import QSettings
    QSettings().setValue(CLAVE, nombre)
    hoja = hoja_de_estilo(nombre)
    for ventana in list(_ventanas):
        try:
            ventana.setStyleSheet(hoja)
        except RuntimeError:  # la ventana ya fue destruida en Qt
            _ventanas.discard(ventana)
        else:
            _repintar_figuras(ventana)
