"""Bloque de goteo de un lote (como el «Tape Irrigation Block» de IRRICAD).

Se abre con la herramienta de mapa «Bloque de goteo» (clic en un lote). Las pestañas son:

- Laterales: cinta o lateral con gotero de la base de datos, hileras y dirección de los laterales.
- Bloque: cabecera y costados, portalateral, válvula, terreno y criterios de diseño.
- Área: nombre del lote, intensidad máxima y lámina requerida.

Los parámetros se guardan en el lote (campo `bloque`) para volver a abrirlo igual.
"""

import json
import math
import re

from qgis.core import Qgis, QgsProject, QgsSettings
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (QAction, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                                 QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
                                 QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import PresionInsuficiente, cargar_catalogo_emisores, cargar_catalogo_tuberias
from ..nucleo.bloque import (PORTA_ALTO, PORTA_BAJO, PORTA_CENTRO, PORTA_DISTANCIA, PORTA_FINAL, PORTA_INICIO,
                             VALV_ALTO, VALV_AUTO, VALV_BAJO, VALV_CENTRO, VALV_PORCENTAJE, VALV_PUNTO,
                             ParametrosBloque, azimut_entre)
from ..nucleo.subunidad import incumplimientos
from ..nucleo.tuberias import clave_economica
from ..integracion.bloque_mapa import DIMENSIONADO_COSTO, DIMENSIONADO_VELOCIDAD
from ..nucleo.diametros_velocidad import serie_por_defecto, series_de_tuberias
from ..nucleo.memoria import descripcion_telescopico
from .comunes import (ComboDiametros, ComboTuberiaPortalateral, GrupoCriterios, GrupoLaterales, html_avisos,
                      html_estado, html_tabla, spin, spin_diametros_por_rama)

AJUSTE_ULTIMOS = "RiegoLibre/bloque_ultimos"  # últimos parámetros usados, para un lote nuevo
DIRECCION_AUTO, DIRECCION_USUARIO = "auto", "usuario"
PUNTOS_CARDINALES = ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"]
ELIMINAR_BLOQUE, ELIMINAR_CON_LOTE = "bloque", "lote"  # respuestas al eliminar un bloque


def cardinal(azimut):
    return PUNTOS_CARDINALES[int(((azimut % 360) + 22.5) // 45) % 8]


def _combo_capas(filtro, vacia=None):
    control = QgsMapLayerComboBox()
    control.setFilters(filtro)
    if vacia is not None:
        try:
            control.setAllowEmptyLayer(True, vacia)
        except TypeError:
            control.setAllowEmptyLayer(True)
    return control


def _elegir_por_dato(combo, dato):
    indice = combo.findData(dato)
    if indice >= 0:
        combo.setCurrentIndex(indice)


class DialogoBloque(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.capa = self.entidad = None  # lote abierto
        self.bloque = None  # último trazado del lote abierto
        self.punto_valvula = None  # (x, y) marcado en el mapa, en el SRC de la capa de lotes
        self._herramienta_puntos = None
        self.setWindowTitle("RiegoLibre · Bloque de goteo")
        self.resize(1150, 780)

        self.tuberias_lateral = cargar_catalogo_tuberias(uso="lateral")
        self.emisores = cargar_catalogo_emisores()
        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"), key=clave_economica)

        self.etiqueta_lote = QLabel("Haga clic en un lote con la herramienta «Bloque de goteo».")
        self.etiqueta_lote.setWordWrap(True)
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._desplazable(self._pestana_laterales()), "Laterales")
        self.pestanas.addTab(self._desplazable(self._pestana_bloque()), "Bloque")
        self.pestanas.addTab(self._desplazable(self._pestana_area()), "Área")
        izquierda = QWidget()
        capa_izquierda = QVBoxLayout(izquierda)
        capa_izquierda.setContentsMargins(0, 0, 0, 0)
        capa_izquierda.addWidget(self.etiqueta_lote)
        capa_izquierda.addWidget(self.pestanas)
        izquierda.setMinimumWidth(460)
        izquierda.setMaximumWidth(600)

        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<h3>Bloque de goteo</h3><ol>"
            "<li>Importe los lotes con <i>Importar lotes de CAD</i>.</li>"
            "<li>Active la herramienta <b>Bloque de goteo</b> y haga clic en un lote.</li>"
            "<li>Elija la cinta, la separación y la dirección de los laterales (pestaña Laterales), la "
            "posición del portalateral y de la válvula (pestaña Bloque) y el nombre (pestaña Área).</li>"
            "<li>Como en IRRICAD, la dirección se puede marcar con <b>dos puntos en el mapa</b> (por ejemplo, dos "
            "vértices de un lado del lote: los laterales quedan paralelos a ese lado) y la válvula con <b>un "
            "clic</b> sobre el portalateral. El cursor se pega a los vértices y lados del lote.</li>"
            "<li><b>Vista previa</b> dibuja el bloque sin calcular; <b>Aplicar y calcular</b> crea las capas "
            "de la subunidad y guarda los parámetros en el lote.</li></ol>"
            "<p>Con <b>Aplicar a los lotes seleccionados</b> se usan los mismos parámetros en varios lotes a "
            "la vez (cada uno con su propia dirección si es automática). Un lote demasiado grande se puede "
            "partir con <b>Subdividir…</b></p>"
            "<p>Para borrar un bloque use <b>Eliminar bloque…</b>, o como en IRRICAD, <b>Ctrl + clic</b> en el "
            "lote con la herramienta <b>Bloque de goteo</b>. <b>Ctrl + Z</b> lo recupera.</p>")

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(izquierda)
        divisor.addWidget(self.texto)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_previa = QPushButton("Vista previa")
        self.boton_aplicar = QPushButton("Aplicar y calcular")
        self.boton_aplicar.setDefault(True)
        self.boton_varios = QPushButton("Aplicar a los lotes seleccionados")
        self.boton_subdividir = QPushButton("Subdividir…")
        self.boton_eliminar = QPushButton("Eliminar bloque…")
        self.boton_eliminar.setToolTip("Quita los laterales, el portalateral y la válvula del lote (en el mapa: "
                                       "Ctrl + clic en el lote con la herramienta «Bloque de goteo»).")
        for boton in (self.boton_previa, self.boton_aplicar, self.boton_varios, self.boton_subdividir,
                      self.boton_eliminar):
            botones.addButton(boton, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_previa.clicked.connect(self.vista_previa)
        self.boton_aplicar.clicked.connect(self.aplicar)
        self.boton_varios.clicked.connect(self.aplicar_seleccionados)
        self.boton_subdividir.clicked.connect(self.subdividir)
        self.boton_eliminar.clicked.connect(self.eliminar)
        deshacer = QAction("Deshacer la eliminación del bloque", self)
        deshacer.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo))  # Ctrl + Z
        deshacer.triggered.connect(self.deshacer)
        self.addAction(deshacer)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)
        self._ultimos = self._leer_ultimos()
        if self._ultimos:
            self.poner_valores(self._ultimos)
        self._actualizar()

    @staticmethod
    def _desplazable(widget):
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    # ---------------------------------------------------------------- pestañas

    def _pestana_laterales(self):
        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        self.grupo_laterales = GrupoLaterales(self.tuberias_lateral, self.emisores, "Cinta o lateral")

        hileras = QGroupBox("Hileras")
        formulario = QFormLayout(hileras)
        self.spin_separacion = spin(0.2, 20, 1.5, 0.01, sufijo="m")
        self.spin_separacion.setToolTip("Distancia entre hileras (camas) vecinas, de eje a eje («Spacing»).")
        formulario.addRow("Separación entre hileras:", self.spin_separacion)
        self.spin_por_hilera = QSpinBox()
        self.spin_por_hilera.setRange(1, 6)
        self.spin_por_hilera.setToolTip("Laterales por hilera o cama («No. Laterals/Group»): 2 para cinta doble.")
        self.spin_por_hilera.valueChanged.connect(self._actualizar)
        formulario.addRow("Laterales por hilera:", self.spin_por_hilera)
        self.spin_en_hilera = spin(0.05, 5, 1.0, 0.05, sufijo="m")
        self.spin_en_hilera.setToolTip("Distancia entre los laterales de una misma hilera («Group Spacing»).")
        formulario.addRow("Separación dentro de la hilera:", self.spin_en_hilera)

        direccion = QGroupBox("Dirección de los laterales")
        formulario_dir = QFormLayout(direccion)
        self.radio_auto = QRadioButton("Determinar automáticamente")
        self.radio_auto.setToolTip("Se prueban varias direcciones (los lados del lote, su rectángulo envolvente y "
                                   "una rejilla) y se elige la de menos tubería, menos terreno sin regar y, con "
                                   "DEM, menos pendiente a lo largo de los laterales.")
        self.radio_usuario = QRadioButton("Definida por el usuario: azimut")
        self.grupo_direccion = QButtonGroup(self)
        self.grupo_direccion.addButton(self.radio_auto)
        self.grupo_direccion.addButton(self.radio_usuario)
        self.radio_auto.setChecked(True)
        self.spin_azimut = spin(0, 359.99, 0, 1, decimales=2, sufijo="°")
        self.spin_azimut.setToolTip("Sentido de los laterales, del inicio al final, en grados desde el norte "
                                    "(horario). Con el portalateral «al inicio», los laterales salen de él hacia "
                                    "ese rumbo.")
        self.radio_auto.toggled.connect(self._actualizar)
        formulario_dir.addRow(self.radio_auto)
        fila = QHBoxLayout()
        fila.addWidget(self.radio_usuario)
        fila.addWidget(self.spin_azimut)
        formulario_dir.addRow(fila)
        self.boton_dos_puntos = QPushButton("Marcar con dos puntos en el mapa")
        self.boton_dos_puntos.setToolTip(
            "Como «Block Lateral» de IRRICAD: haga clic en el primer punto y luego en el segundo. Los laterales "
            "van paralelos a esa línea, del lado del primer punto hacia el del segundo (con el portalateral «al "
            "inicio», queda del lado del primer punto). El cursor se pega a los vértices y lados del lote.")
        self.boton_dos_puntos.clicked.connect(self.marcar_direccion)
        formulario_dir.addRow(self.boton_dos_puntos)
        self.boton_usar_azimut = QPushButton("Fijar la dirección de la vista previa")
        self.boton_usar_azimut.setToolTip("Pasa a «definida por el usuario» con la dirección que eligió el modo "
                                          "automático, para afinarla a mano.")
        self.boton_usar_azimut.clicked.connect(self._fijar_azimut)
        formulario_dir.addRow(self.boton_usar_azimut)

        capa.addWidget(self.grupo_laterales)
        capa.addWidget(hileras)
        capa.addWidget(direccion)
        capa.addStretch()
        return pagina

    def _pestana_bloque(self):
        pagina = QWidget()
        capa = QVBoxLayout(pagina)

        bordes = QGroupBox("Bordes")
        formulario = QFormLayout(bordes)
        self.spin_cabecera = spin(0, 50, 0.2, 0.1, sufijo="m")
        self.spin_cabecera.setToolTip("Distancia libre entre el extremo de cada lateral y el borde del lote "
                                      "(«Headlands»).")
        formulario.addRow("Cabecera:", self.spin_cabecera)
        self.spin_costados = spin(0, 50, 0.75, 0.01, sufijo="m")
        self.spin_costados.setToolTip("Distancia del borde del lote al eje de la primera hilera («Sidelands»). "
                                      "Lo usual es media separación entre hileras.")
        formulario.addRow("Costados:", self.spin_costados)
        boton_mitad = QPushButton("Media separación")
        boton_mitad.clicked.connect(lambda: self.spin_costados.setValue(self.spin_separacion.value() / 2))
        formulario.addRow("", boton_mitad)

        porta = QGroupBox("Portalateral")
        formulario_porta = QFormLayout(porta)
        self.combo_porta = QComboBox()
        self.combo_porta.addItem("Al inicio de los laterales", PORTA_INICIO)
        self.combo_porta.addItem("Al final de los laterales", PORTA_FINAL)
        self.combo_porta.addItem("Al centro (laterales a ambos lados)", PORTA_CENTRO)
        self.combo_porta.addItem("A una distancia del inicio", PORTA_DISTANCIA)
        self.combo_porta.addItem("En el borde más alto (laterales en bajada)", PORTA_ALTO)
        self.combo_porta.addItem("En el borde más bajo (laterales en subida)", PORTA_BAJO)
        self.combo_porta.currentIndexChanged.connect(self._actualizar)
        formulario_porta.addRow("Posición:", self.combo_porta)
        self.spin_distancia = spin(0, 2000, 50, 1, sufijo="m")
        formulario_porta.addRow("Distancia:", self.spin_distancia)
        self.combo_dimensionado = QComboBox()
        self.combo_dimensionado.addItem("Menor tubería que cumple los criterios", DIMENSIONADO_COSTO)
        self.combo_dimensionado.addItem("Por velocidad (diámetros por tramos)", DIMENSIONADO_VELOCIDAD)
        self.combo_dimensionado.setToolTip(
            "«Por velocidad»: cada tramo entre laterales lleva la tubería más pequeña de la serie que no pasa la "
            "velocidad máxima (pestaña Bloque, criterios de diseño); los tramos se agrupan en pocos diámetros.")
        self.combo_dimensionado.currentIndexChanged.connect(self._actualizar)
        formulario_porta.addRow("Diámetros:", self.combo_dimensionado)
        self.combo_tuberia_porta = ComboTuberiaPortalateral(self.tuberias_portalateral)
        formulario_porta.addRow("Tubería:", self.combo_tuberia_porta)
        self.combo_diametros = ComboDiametros()
        formulario_porta.addRow("Telescópico:", self.combo_diametros)
        self.combo_serie = QComboBox()
        series = series_de_tuberias(self.tuberias_portalateral)
        for serie in series:
            self.combo_serie.addItem(serie.nombre, serie.clave)
        if series:
            self.combo_serie.setCurrentIndex(self.combo_serie.findData(serie_por_defecto(series).clave))
        self.combo_serie.setToolTip("Material y clase de las tuberías entre las que se elige cada diámetro.")
        formulario_porta.addRow("Serie:", self.combo_serie)
        self.spin_diametros_vel = spin_diametros_por_rama()
        formulario_porta.addRow("Diámetros por rama, máximo:", self.spin_diametros_vel)
        self.spin_tramo_min = spin(0, 100, 6, 1, decimales=1, sufijo="m")
        self.spin_tramo_min.setToolTip("Largo mínimo de cada diámetro (por ejemplo, el de un tubo).")
        formulario_porta.addRow("Largo mínimo de cada diámetro:", self.spin_tramo_min)
        self.check_ajustar = QCheckBox("Bajar la velocidad si no se cumple la variación de caudal")
        self.check_ajustar.setChecked(True)
        formulario_porta.addRow(self.check_ajustar)

        valvula = QGroupBox("Válvula")
        formulario_valv = QFormLayout(valvula)
        self.combo_valvula = QComboBox()
        self.combo_valvula.addItem("Automática (según la fuente y el relieve)", VALV_AUTO)
        self.combo_valvula.addItem("En el extremo más alto del portalateral", VALV_ALTO)
        self.combo_valvula.addItem("En el extremo más bajo del portalateral", VALV_BAJO)
        self.combo_valvula.addItem("Al centro del portalateral", VALV_CENTRO)
        self.combo_valvula.addItem("A un porcentaje del portalateral", VALV_PORCENTAJE)
        self.combo_valvula.addItem("Marcada en el mapa", VALV_PUNTO)
        self.combo_valvula.currentIndexChanged.connect(self._actualizar)
        formulario_valv.addRow("Posición:", self.combo_valvula)
        self.boton_valvula = QPushButton("Colocar la válvula en el mapa")
        self.boton_valvula.setToolTip("Como «Place a Point» de IRRICAD: haga clic donde va la válvula; queda en el "
                                      "punto más cercano del portalateral de la vista previa.")
        self.boton_valvula.clicked.connect(self.marcar_valvula)
        self.spin_porcentaje = spin(0, 100, 50, 5, decimales=0, sufijo="%")
        self.spin_porcentaje.setToolTip("Medido desde el extremo más alto del portalateral (sin DEM, desde su "
                                        "extremo 1).")
        formulario_valv.addRow("Porcentaje:", self.spin_porcentaje)
        formulario_valv.addRow(self.boton_valvula)

        terreno = QGroupBox("Terreno")
        formulario_terreno = QFormLayout(terreno)
        self.combo_dem = _combo_capas(Qgis.LayerFilter.RasterLayer, "Sin DEM (terreno plano)")
        formulario_terreno.addRow("DEM:", self.combo_dem)
        self.combo_fuente = _combo_capas(Qgis.LayerFilter.PointLayer, "Sin fuente")
        self.combo_fuente.setToolTip("Punto de la fuente o del cabezal, para la válvula automática.")
        formulario_terreno.addRow("Fuente de agua:", self.combo_fuente)

        self.grupo_criterios = GrupoCriterios()
        capa.addWidget(bordes)
        capa.addWidget(porta)
        capa.addWidget(valvula)
        capa.addWidget(terreno)
        capa.addWidget(self.grupo_criterios)
        capa.addStretch()
        return pagina

    def _pestana_area(self):
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        self.edit_nombre = QLineEdit()
        self.edit_nombre.setToolTip("Nombre del lote: también es el de su subunidad y su grupo de resultados.")
        formulario.addRow("Nombre:", self.edit_nombre)
        self.spin_intensidad = spin(0, 200, 0, 0.5, decimales=1, sufijo="mm/h")
        self.spin_intensidad.setSpecialValueText("sin límite")
        self.spin_intensidad.setToolTip("Se avisa si la intensidad de aplicación del bloque la supera.")
        formulario.addRow("Intensidad máxima:", self.spin_intensidad)
        self.spin_lamina = spin(0, 500, 0, 0.5, decimales=1, sufijo="mm")
        self.spin_lamina.setSpecialValueText("—")
        self.spin_lamina.setToolTip("Lámina por riego: con ella se calcula el tiempo de riego del bloque.")
        formulario.addRow("Lámina requerida:", self.spin_lamina)
        return pagina

    def _actualizar(self):
        self.spin_en_hilera.setEnabled(self.spin_por_hilera.value() > 1)
        self.spin_azimut.setEnabled(self.radio_usuario.isChecked())
        self.spin_distancia.setEnabled(self.combo_porta.currentData() == PORTA_DISTANCIA)
        self.spin_porcentaje.setEnabled(self.combo_valvula.currentData() == VALV_PORCENTAJE)
        por_velocidad = self.combo_dimensionado.currentData() == DIMENSIONADO_VELOCIDAD
        for control in (self.combo_serie, self.spin_diametros_vel, self.spin_tramo_min, self.check_ajustar):
            control.setEnabled(por_velocidad)
        for control in (self.combo_tuberia_porta, self.combo_diametros):
            control.setEnabled(not por_velocidad)
        self.boton_usar_azimut.setEnabled(self.radio_auto.isChecked() and self.bloque is not None)
        self.boton_dos_puntos.setEnabled(self.capa is not None and self.iface is not None)
        self.boton_valvula.setEnabled(self.bloque is not None and self.iface is not None)

    def _fijar_azimut(self):
        if self.bloque is not None:
            self.spin_azimut.setValue(round(self.bloque.azimut_laterales_grados, 1))
            self.radio_usuario.setChecked(True)

    # ---------------------------------------------------------------- valores

    def valores(self):
        """Parámetros de la ventana como diccionario (se guardan en el lote en JSON)."""
        g, c = self.grupo_laterales, self.grupo_criterios
        tuberia_porta = self.combo_tuberia_porta.tuberia()
        return {
            "tuberia": g.tuberia().nombre, "emisor": g.emisor().nombre,
            "espaciamiento_m": g.spin_espaciamiento.value(), "primer_emisor_m": g.spin_primer.value(),
            "separacion_m": self.spin_separacion.value(), "laterales_por_hilera": self.spin_por_hilera.value(),
            "separacion_en_hilera_m": self.spin_en_hilera.value(),
            "direccion": DIRECCION_AUTO if self.radio_auto.isChecked() else DIRECCION_USUARIO,
            "azimut_deg": self.spin_azimut.value(),
            "cabecera_m": self.spin_cabecera.value(), "costados_m": self.spin_costados.value(),
            "portalateral": self.combo_porta.currentData(), "distancia_portalateral_m": self.spin_distancia.value(),
            "tuberia_portalateral": tuberia_porta.nombre if tuberia_porta else None,
            "diametros_max": self.combo_diametros.maximo(),
            "dimensionado": self.combo_dimensionado.currentData(), "serie": self.combo_serie.currentData(),
            "diametros_velocidad": self.spin_diametros_vel.value(), "tramo_min_m": self.spin_tramo_min.value(),
            "ajustar_variacion": self.check_ajustar.isChecked(),
            "dem": self.combo_dem.currentLayer().id() if self.combo_dem.currentLayer() else None,
            "fuente": self.combo_fuente.currentLayer().id() if self.combo_fuente.currentLayer() else None,
            "valvula": self.combo_valvula.currentData(), "porcentaje_valvula": self.spin_porcentaje.value(),
            "punto_valvula": list(self.punto_valvula) if self.punto_valvula else None,
            "presion_conocida_m": c.presion_conocida(), "metodo": c.metodo(),
            "variacion_caudal_pct": c.spin_variacion.value(), "velocidad_max_ms": c.spin_velocidad.value(),
            "presion_entrada_max_m": c.spin_presion_max.value(),
            "intensidad_max_mmh": self.spin_intensidad.value(), "lamina_mm": self.spin_lamina.value(),
        }

    def poner_valores(self, v):
        """Pone en la ventana los valores de un diccionario (los que falten quedan como están)."""
        g, c = self.grupo_laterales, self.grupo_criterios

        def nombre_en(combo, lista, nombre):
            for i, objeto in enumerate(lista):
                if objeto.nombre == nombre:
                    combo.setCurrentIndex(i)
                    return

        if "tuberia" in v:
            nombre_en(g.combo_tuberia, g.tuberias, v["tuberia"])
        if "emisor" in v and g.combo_emisor.isEnabled():
            nombre_en(g.combo_emisor, g.emisores, v["emisor"])
        for clave, control in (("espaciamiento_m", g.spin_espaciamiento), ("primer_emisor_m", g.spin_primer),
                               ("separacion_m", self.spin_separacion),
                               ("separacion_en_hilera_m", self.spin_en_hilera), ("azimut_deg", self.spin_azimut),
                               ("cabecera_m", self.spin_cabecera), ("costados_m", self.spin_costados),
                               ("distancia_portalateral_m", self.spin_distancia),
                               ("porcentaje_valvula", self.spin_porcentaje),
                               ("variacion_caudal_pct", c.spin_variacion), ("velocidad_max_ms", c.spin_velocidad),
                               ("presion_entrada_max_m", c.spin_presion_max),
                               ("intensidad_max_mmh", self.spin_intensidad), ("lamina_mm", self.spin_lamina)):
            if v.get(clave) is not None:
                control.setValue(float(v[clave]))
        if v.get("laterales_por_hilera"):
            self.spin_por_hilera.setValue(int(v["laterales_por_hilera"]))
        if "direccion" in v:
            (self.radio_auto if v["direccion"] == DIRECCION_AUTO else self.radio_usuario).setChecked(True)
        if "portalateral" in v:
            _elegir_por_dato(self.combo_porta, v["portalateral"])
        if "valvula" in v:
            _elegir_por_dato(self.combo_valvula, v["valvula"])
        if "punto_valvula" in v:
            self.punto_valvula = tuple(v["punto_valvula"]) if v["punto_valvula"] else None
        if "tuberia_portalateral" in v:
            if v["tuberia_portalateral"] is None:
                self.combo_tuberia_porta.setCurrentIndex(0)
            else:
                for t in self.tuberias_portalateral:
                    if t.nombre == v["tuberia_portalateral"]:
                        self.combo_tuberia_porta.elegir(t)
        if "diametros_max" in v:
            _elegir_por_dato(self.combo_diametros, v["diametros_max"])
        if "dimensionado" in v:
            _elegir_por_dato(self.combo_dimensionado, v["dimensionado"])
        if v.get("serie"):
            _elegir_por_dato(self.combo_serie, v["serie"])
        if v.get("diametros_velocidad") is not None:
            self.spin_diametros_vel.setValue(int(v["diametros_velocidad"]))
        if v.get("tramo_min_m") is not None:
            self.spin_tramo_min.setValue(float(v["tramo_min_m"]))
        if "ajustar_variacion" in v:
            self.check_ajustar.setChecked(bool(v["ajustar_variacion"]))
        proyecto = QgsProject.instance()
        for clave, combo in (("dem", self.combo_dem), ("fuente", self.combo_fuente)):
            capa = proyecto.mapLayer(v[clave]) if v.get(clave) else None
            if capa is not None:
                combo.setLayer(capa)
        if "metodo" in v:
            _elegir_por_dato(c.combo_metodo, v["metodo"])
        if "presion_conocida_m" in v:
            if v["presion_conocida_m"] is None:
                c.radio_requerida.setChecked(True)
            else:
                c.radio_conocida.setChecked(True)
                c.spin_presion.setValue(float(v["presion_conocida_m"]))
        self._actualizar()

    @staticmethod
    def _leer_ultimos():
        try:
            datos = json.loads(QgsSettings().value(AJUSTE_ULTIMOS, "") or "{}")
        except ValueError:
            return {}
        return datos if isinstance(datos, dict) else {}

    def _guardar_ultimos(self):
        QgsSettings().setValue(AJUSTE_ULTIMOS, json.dumps(self.valores(), ensure_ascii=False))

    def parametros(self) -> ParametrosBloque:
        from ..integracion.bloque_mapa import parametros_de
        return parametros_de(self.valores(), self.grupo_laterales.emisor())

    def config_calculo(self):
        from ..integracion.bloque_mapa import config_de
        return config_de(self.valores(), self.tuberias_lateral, self.emisores, self.tuberias_portalateral,
                         self.combo_dem.currentLayer())

    def _alcance(self):
        """Longitud de lateral que cumple la variación de caudal en terreno plano (para la dirección automática)."""
        from ..integracion.trazado_mapa import alcance_hidraulico
        if not self.radio_auto.isChecked():
            return None
        g, c = self.grupo_laterales, self.grupo_criterios
        criterios = c.criterios()
        try:
            largo = alcance_hidraulico(g.tuberia(), g.emisor(), g.spin_espaciamiento.value(), g.spin_primer.value(),
                                       criterios.variacion_caudal_max, c.metodo(),
                                       criterios.presion_entrada_max_m)(0.0)
        except (ValueError, PresionInsuficiente):
            return None
        return largo or None

    # ---------------------------------------------------------------- lote

    def abrir_lote(self, capa, entidad):
        """Carga un lote: sus parámetros guardados, o los últimos usados si es nuevo."""
        from ..integracion.lotes import CAMPO_NOMBRE, parametros_guardados
        from ..integracion.bloque_mapa import quitar_vista_previa
        quitar_vista_previa()
        self.capa, self.entidad, self.bloque = capa, entidad, None
        self.punto_valvula = None  # el de otro lote no sirve
        guardados = parametros_guardados(entidad)
        if guardados:
            self.poner_valores(guardados)
        nombre = entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}"
        self.edit_nombre.setText(str(nombre))
        if self.combo_dem.currentLayer() is None:
            self._elegir_dem_del_proyecto()
        self.etiqueta_lote.setText(f"<b>Lote:</b> {nombre} &nbsp;·&nbsp; {entidad.geometry().area() / 10000:.3f} ha"
                                   f" &nbsp;·&nbsp; capa «{capa.name()}»"
                                   + ("" if guardados else " &nbsp;·&nbsp; <i>sin diseñar</i>"))
        self.setWindowTitle(f"RiegoLibre · Bloque de goteo · {nombre}")
        self._actualizar()
        self.show()
        self.raise_()
        self.activateWindow()
        self.vista_previa()

    def _elegir_dem_del_proyecto(self):
        for capa in QgsProject.instance().mapLayers().values():
            if capa.type() == Qgis.LayerType.Raster and "dem" in capa.name().lower() and "3d" not in capa.name().lower():
                self.combo_dem.setLayer(capa)
                return

    def _lote(self):
        if self.capa is None or self.entidad is None:
            raise ValueError("Primero haga clic en un lote con la herramienta «Bloque de goteo».")
        entidad = self.capa.getFeature(self.entidad.id())
        if not entidad.isValid():
            raise ValueError("El lote ya no existe en la capa (¿se subdividió o se borró?). Haga clic en otro.")
        self.entidad = entidad
        return entidad

    def _geometria(self, capa, entidad):
        from ..integracion.subunidad_mapa import geometria_en, verificar_crs_metrico
        crs = capa.crs()
        verificar_crs_metrico(crs, capa.name())
        return geometria_en(capa, entidad, crs), crs

    def _fuente(self, crs):
        from ..integracion.trazado_mapa import punto_de_entidad
        capa = self.combo_fuente.currentLayer()
        return punto_de_entidad(capa, crs) if capa is not None else None

    def _trazar(self, capa, entidad, params=None, alcance=None):
        from ..integracion.bloque_mapa import trazar_en_lote
        geometria, crs = self._geometria(capa, entidad)
        params = params or self.parametros()
        bloque = trazar_en_lote(geometria, params, crs, self.combo_dem.currentLayer(), self._fuente(crs),
                                alcance)
        return bloque, geometria, crs

    # ---------------------------------------------------------------- acciones

    def _ejecutar(self, funcion):
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return funcion()
        except (ValueError, PresionInsuficiente) as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
            if error:
                QMessageBox.warning(self, "RiegoLibre", error)
        return None

    def vista_previa(self):
        def hacer():
            from ..integracion.bloque_mapa import vista_previa
            entidad = self._lote()
            bloque, _, crs = self._trazar(self.capa, entidad, alcance=self._alcance())
            vista_previa([(self.edit_nombre.text().strip(), bloque)], crs)
            return bloque
        bloque = self._ejecutar(hacer)
        if bloque is not None:
            self.bloque = bloque
            self.texto.setHtml(self._html_bloque(bloque) + "<p>Pulse <b>Aplicar y calcular</b> para calcular la "
                               "subunidad y guardar los parámetros en el lote.</p>")
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        self._actualizar()

    def _html_bloque(self, b, titulo="Vista previa"):
        g = self.grupo_laterales
        caudal_m3h = b.caudal / 1000
        intensidad = b.caudal / b.area_regada_m2 if b.area_regada_m2 else 0.0  # L/h/m² = mm/h
        avisos = list(b.avisos)
        maximo = self.spin_intensidad.value()
        if maximo and intensidad > maximo:
            avisos.append(f"La intensidad de aplicación ({intensidad:.2f} mm/h) supera la máxima ({maximo:g} mm/h).")
        alcance = self._alcance()
        if alcance and b.lateral_mas_largo_m > alcance * 1.001:
            avisos.append(f"El lateral más largo ({b.lateral_mas_largo_m:.1f} m) pasa de lo que admite la variación "
                          f"de caudal en terreno plano (unos {alcance:.0f} m): considere el portalateral al centro o "
                          "subdividir el lote.")
        azimut = b.azimut_laterales_grados
        extremo_1, extremo_2 = b.portalateral[0], b.portalateral[-1]
        filas = [
            ("Dirección de los laterales", f"azimut {azimut:.1f}° (hacia el {cardinal(azimut)})"
                                           + (" · automática" if self.radio_auto.isChecked() else "")),
            ("Área del lote / regada", f"{b.area_lote_m2 / 10000:.3f} ha / {b.area_regada_m2 / 10000:.3f} ha"),
            ("Hileras · laterales", f"{b.hileras} · {len(b.laterales)}"),
            ("Lateral más largo", f"{b.lateral_mas_largo_m:.1f} m"),
            ("Metros de lateral", f"{b.longitud_laterales_m:,.0f} m"),
            ("Emisores (aprox.)", f"{int(round(b.longitud_laterales_m / g.spin_espaciamiento.value())):,}"),
            ("Caudal del bloque", f"{caudal_m3h:.2f} m³/h ({b.caudal / 3600:.2f} L/s)"),
            ("Intensidad de aplicación", f"{intensidad:.2f} mm/h"),
            ("Portalateral", f"{b.longitud_portalateral_m:.1f} m"
                             + ("" if b.desnivel_portalateral_m is None else
                                f" · desnivel entre extremos {abs(b.desnivel_portalateral_m):.2f} m")),
            ("Válvula", _texto_valvula(b, extremo_1, extremo_2)),
        ]
        if b.pendiente_laterales is not None:
            filas.append(("Pendiente de los laterales", f"{b.pendiente_laterales:+.2%} desde el portalateral"))
        lamina = self.spin_lamina.value()
        if lamina and intensidad:
            filas.append(("Tiempo de riego", f"{lamina / intensidad:.2f} h para {lamina:g} mm"))
        return f"<h3>{titulo}</h3>" + html_tabla(filas) + html_avisos(avisos)

    def aplicar(self):
        informe = self._ejecutar(self._aplicar)
        if informe is not None:
            self.texto.setHtml(informe)

    def _aplicar(self):
        from ..integracion.bloque_mapa import RESULTADO, calcular_bloque, quitar_vista_previa, resumen_resultado
        from ..integracion.lotes import CAMPO_NOMBRE, guardar_parametros, parametros_guardados
        entidad = self._lote()
        nombre = self.edit_nombre.text().strip()
        if not nombre:
            raise ValueError("Escriba el nombre del lote (pestaña Área).")
        anterior = entidad[CAMPO_NOMBRE]
        bloque, geometria, crs = self._trazar(self.capa, entidad, alcance=self._alcance())
        self.bloque = bloque
        quitar_vista_previa()
        config = self.config_calculo()
        r = calcular_bloque(nombre, crs, bloque, geometria, config)
        # Se conservan las claves que esta ventana no maneja (las de la tabla de zonas)
        valores = dict(parametros_guardados(entidad) or {}, **self.valores())
        valores["azimut_usado_deg"] = round(bloque.azimut_laterales_grados, 3)
        valores[RESULTADO] = resumen_resultado(r, config, valores)
        guardar_parametros(self.capa, entidad.id(), valores, nombre)
        self._guardar_ultimos()
        if anterior and anterior != nombre:
            from .dialogo_trazado import eliminar_grupos
            eliminar_grupos(re.escape(f"RiegoLibre · {anterior}"))
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
        res = r.diseno.resultado
        motivos = incumplimientos(res, self.grupo_criterios.criterios(), r.diseno.tuberia)
        filas = [
            ("Resultado", html_estado(not motivos) + ("" if not motivos else " " + "; ".join(motivos))),
            ("Presión en la válvula", f"{res.presion_entrada_m:.2f} m"),
            ("Caudal", f"{res.caudal_total_lh / 1000:.2f} m³/h ({res.caudal_total_lh / 3600:.2f} L/s)"),
            ("Portalateral", _texto_portalateral(r.diseno)),
            ("Velocidad máxima en el portalateral", f"{res.velocidad_max_ms:.2f} m/s"),
            ("Variación de caudal", f"{res.variacion_caudal:.1%}"),
        ]
        return (self._html_bloque(bloque, f"Bloque «{nombre}» calculado") + "<h3>Subunidad</h3>" + html_tabla(filas)
                + html_avisos(r.avisos + r.diseno.avisos) + f"<p>Las capas están en el grupo <i>RiegoLibre · {nombre}</i>. Los "
                "parámetros quedaron guardados en el lote.</p>")

    def aplicar_seleccionados(self):
        if self.capa is None:
            from ..integracion.lotes import capas_de_lotes
            capas = capas_de_lotes()
            if len(capas) != 1:
                QMessageBox.information(self, "RiegoLibre", "Primero haga clic en un lote de la capa de lotes.")
                return
            self.capa = capas[0]
        seleccion = self.capa.selectedFeatures()
        if not seleccion:
            QMessageBox.information(self, "RiegoLibre", f"Seleccione lotes en la capa «{self.capa.name()}».")
            return
        respuesta = QMessageBox.question(
            self, "RiegoLibre", f"Se diseñarán y calcularán {len(seleccion)} lotes con los parámetros de esta "
            "ventana (el nombre de cada lote se conserva). Los bloques que ya tenían se reemplazan. ¿Continuar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        informe = self._ejecutar(lambda: self._aplicar_varios(seleccion))
        if informe is not None:
            self.texto.setHtml(informe)

    def _aplicar_varios(self, entidades):
        from ..integracion.bloque_mapa import (RESULTADO, calcular_bloque, parametros_de, quitar_vista_previa,
                                               resumen_resultado)
        from ..integracion.lotes import CAMPO_NOMBRE, guardar_parametros, parametros_guardados
        quitar_vista_previa()
        valores = _sin_punto_de_valvula(self.valores())
        params, config, alcance = (parametros_de(valores, self.grupo_laterales.emisor()), self.config_calculo(),
                                   self._alcance())
        criterios = self.grupo_criterios.criterios()
        filas, fallos = [], []
        for i, entidad in enumerate(sorted(entidades, key=lambda e: str(e[CAMPO_NOMBRE])), 1):
            nombre = str(entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}")
            self.texto.setHtml(f"<p>Calculando el lote {nombre} ({i} de {len(entidades)})…</p>")
            QApplication.processEvents()
            try:
                bloque, geometria, crs = self._trazar(self.capa, entidad, params, alcance)
                r = calcular_bloque(nombre, crs, bloque, geometria, config)
            except (ValueError, PresionInsuficiente) as e:
                fallos.append(f"{nombre}: {e}")
                continue
            datos = dict(parametros_guardados(entidad) or {}, **valores)
            datos["azimut_usado_deg"] = round(bloque.azimut_laterales_grados, 3)
            datos[RESULTADO] = resumen_resultado(r, config, datos)
            guardar_parametros(self.capa, entidad.id(), datos)
            res = r.diseno.resultado
            motivos = incumplimientos(res, criterios, r.diseno.tuberia)
            filas.append((nombre, bloque, res, _texto_portalateral(r.diseno), motivos))
        self._guardar_ultimos()
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
        tabla = ["<table cellpadding='4' border='0'><tr><th align='left'>Lote</th><th>Azimut</th><th>Hileras</th>"
                 "<th>Área regada (ha)</th><th>Caudal (m³/h)</th><th>Presión válvula (m)</th>"
                 "<th align='left'>Portalateral</th><th>Variación</th><th align='left'>Resultado</th></tr>"]
        for nombre, b, res, tuberia, motivos in filas:
            tabla.append(
                f"<tr><td>{nombre}</td><td align='right'>{b.azimut_laterales_grados:.0f}°</td>"
                f"<td align='right'>{b.hileras}</td><td align='right'>{b.area_regada_m2 / 10000:.3f}</td>"
                f"<td align='right'>{res.caudal_total_lh / 1000:.2f}</td>"
                f"<td align='right'>{res.presion_entrada_m:.1f}</td><td>{tuberia}</td>"
                f"<td align='right'>{res.variacion_caudal:.1%}</td><td>{html_estado(not motivos)}"
                f"{'' if not motivos else ' ' + '; '.join(motivos)}</td></tr>")
        tabla.append("</table>")
        cumplen = sum(1 for *_, m in filas if not m)
        resumen = html_tabla([
            ("Lotes calculados", f"{len(filas)} de {len(entidades)} · cumplen {cumplen}"),
            ("Caudal total", f"{sum(f[2].caudal_total_lh for f in filas) / 1000:.2f} m³/h"),
            ("Área regada", f"{sum(f[1].area_regada_m2 for f in filas) / 10000:.2f} ha"),
        ])
        return "<h3>Lotes calculados</h3>" + resumen + "".join(tabla) + html_avisos(fallos)

    def eliminar(self):
        entidad = self._ejecutar(self._lote)
        if entidad is not None:
            self.confirmar_eliminar(self.capa, entidad)

    def _preguntar_eliminar(self, nombre, grupo, padre):
        """None (cancelar), ELIMINAR_BLOQUE o ELIMINAR_CON_LOTE."""
        caja = QMessageBox(padre or self)
        caja.setIcon(QMessageBox.Icon.Question)
        caja.setWindowTitle("RiegoLibre · Eliminar bloque de goteo")
        caja.setText(f"¿Eliminar el bloque de goteo del lote «{nombre}»?")
        caja.setInformativeText(
            f"Se quitan sus laterales, su portalateral y su válvula (grupo «{grupo}») y el diseño guardado en "
            "el lote. Si la red principal usaba esta válvula, vuelva a calcularla.")
        solo_bloque = caja.addButton("Eliminar el bloque", QMessageBox.ButtonRole.DestructiveRole)
        con_lote = caja.addButton("Eliminar el bloque y el lote", QMessageBox.ButtonRole.DestructiveRole)
        caja.addButton(QMessageBox.StandardButton.Cancel)
        caja.exec()
        return {solo_bloque: ELIMINAR_BLOQUE, con_lote: ELIMINAR_CON_LOTE}.get(caja.clickedButton())

    def confirmar_eliminar(self, capa, entidad, padre=None):
        """Pregunta y elimina el bloque del lote (botón «Eliminar bloque…» o Ctrl + clic en el mapa).

        Devuelve el texto de lo que se hizo, o None si se canceló.
        """
        from ..integracion.bloque_mapa import eliminar_bloque, grupo_del_lote, nombre_del_lote
        nombre = nombre_del_lote(entidad)
        seleccion = capa.selectedFeatureIds()
        capa.selectByIds([entidad.id()])  # el lote queda resaltado mientras se confirma, como en IRRICAD
        try:
            eleccion = self._preguntar_eliminar(nombre, grupo_del_lote(entidad), padre)
        finally:
            capa.selectByIds([i for i in seleccion if i != entidad.id()])
        if eleccion is None:
            return None
        con_lote = eleccion == ELIMINAR_CON_LOTE

        def hacer():
            eliminar_bloque(capa, entidad, borrar_lote=con_lote)
            return True
        if not self._ejecutar(hacer):
            return None
        if self.capa is capa and self.entidad is not None and self.entidad.id() == entidad.id():
            self.bloque = self.punto_valvula = None
            if con_lote:
                self.capa = self.entidad = None
                self.etiqueta_lote.setText("Haga clic en un lote con la herramienta «Bloque de goteo».")
                self.setWindowTitle("RiegoLibre · Bloque de goteo")
            else:
                self.etiqueta_lote.setText(f"<b>Lote:</b> {nombre} &nbsp;·&nbsp; <i>sin diseñar</i>")
        texto = (f"Se eliminaron el bloque de goteo y el lote «{nombre}»." if con_lote
                 else f"Se eliminó el bloque de goteo del lote «{nombre}». El lote quedó sin diseñar.")
        self.texto.setHtml(f"<p>{texto}</p><p>Para recuperarlo pulse <b>Ctrl + Z</b> (o «Deshacer» en el "
                           "aviso de arriba del mapa) mientras QGIS siga abierto.</p>")
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
            self._aviso_con_deshacer(texto)
        return texto

    def _aviso_con_deshacer(self, texto):
        """Aviso en la barra de mensajes de QGIS con un botón «Deshacer»."""
        barra = self.iface.messageBar()
        aviso = barra.createMessage("RiegoLibre", texto)
        boton = QPushButton("Deshacer")

        def pulsar():
            barra.popWidget(aviso)
            self.deshacer()
        boton.clicked.connect(pulsar)
        aviso.layout().addWidget(boton)
        barra.pushWidget(aviso, Qgis.MessageLevel.Info, 15)

    def deshacer(self):
        """Recupera el último bloque eliminado (Ctrl + Z). Devuelve el texto de lo hecho, o None."""
        from ..integracion.bloque_mapa import deshacer_eliminacion, hay_eliminacion_para_deshacer
        if not hay_eliminacion_para_deshacer():
            texto, nivel = "No hay ninguna eliminación de bloque para deshacer.", Qgis.MessageLevel.Info
            e = None
        else:
            e = self._ejecutar(deshacer_eliminacion)
            if e is None:
                return None
            texto = (f"Se recuperaron el lote «{e.nombre}» y su bloque de goteo." if e.lote_borrado
                     else f"Se recuperó el bloque de goteo del lote «{e.nombre}».")
            nivel = Qgis.MessageLevel.Success
            if (not e.lote_borrado and self.capa is e.capa_lotes and self.entidad is not None
                    and self.entidad.id() == e.entidad.id()):
                self.etiqueta_lote.setText(f"<b>Lote:</b> {e.nombre} &nbsp;·&nbsp; "
                                           f"{e.entidad.geometry().area() / 10000:.3f} ha")
        self.texto.setHtml(f"<p>{texto}</p>")
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
            self.iface.messageBar().pushMessage("RiegoLibre", texto, nivel, 5)
        return texto if e is not None else None

    def subdividir(self):
        from .dialogo_subdivision import DialogoSubdivision
        entidad = self._ejecutar(self._lote)
        if entidad is None:
            return
        try:
            params = self.parametros()
        except ValueError as e:
            QMessageBox.warning(self, "RiegoLibre", str(e))
            return
        angulo = None
        if self.bloque is not None:
            angulo = self.bloque.angulo_deg
        elif params.angulo_deg is not None:
            angulo = params.angulo_deg
        if angulo is None:
            bloque = self._ejecutar(lambda: self._trazar(self.capa, entidad, params, self._alcance())[0])
            if bloque is None:
                return
            angulo = bloque.angulo_deg
        dialogo = DialogoSubdivision(self, self.capa, entidad, params, angulo, self.edit_nombre.text().strip(),
                                     _sin_punto_de_valvula(self.valores()))
        if dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.nuevas:
            self.capa.selectByIds(dialogo.nuevas)
            self.entidad = self.bloque = None
            self.etiqueta_lote.setText(f"El lote se partió en {len(dialogo.nuevas)} sub-bloques (quedaron "
                                       "seleccionados). Haga clic en uno, o use <b>Aplicar a los lotes "
                                       "seleccionados</b>.")
            self.texto.setHtml(dialogo.informe)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()

    # ---------------------------------------------------------------- puntos en el mapa

    def marcar_direccion(self):
        """Dirección de los laterales con dos puntos en el mapa («Block Lateral» de IRRICAD)."""
        def listo(p1, p2):
            try:
                azimut = azimut_entre(p1, p2)
            except ValueError as e:
                QMessageBox.warning(self, "RiegoLibre", str(e))
                return
            self.spin_azimut.setValue(round(azimut, 2))
            self.radio_usuario.setChecked(True)
            self.vista_previa()

        self._marcar(2, ["Dirección de los laterales: haga clic en el primer punto",
                         "Dirección de los laterales: haga clic en el segundo punto"], listo)

    def marcar_valvula(self):
        """Válvula con un clic en el mapa («Place a Point» de IRRICAD)."""
        def listo(punto):
            self.punto_valvula = (punto[0], punto[1])
            _elegir_por_dato(self.combo_valvula, VALV_PUNTO)
            self.vista_previa()

        self._marcar(1, ["Válvula: haga clic donde va (queda sobre el portalateral)"], listo, con_portalateral=True)

    def _marcar(self, cuantos, mensajes, listo, con_portalateral=False):
        """Esconde la ventana y pide los puntos en el mapa; `listo` los recibe en el SRC de la capa de lotes."""
        from qgis.core import QgsCoordinateTransform
        from .herramienta_puntos import HerramientaPuntos
        entidad = self._ejecutar(self._lote)
        if entidad is None or self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        crs_mapa = canvas.mapSettings().destinationCrs()
        al_mapa = QgsCoordinateTransform(self.capa.crs(), crs_mapa, QgsProject.instance())
        al_lote = QgsCoordinateTransform(crs_mapa, self.capa.crs(), QgsProject.instance())
        geometrias = [entidad.geometry()]
        if con_portalateral and self.bloque is not None:
            from ..integracion.bloque_mapa import geometria_portalateral
            geometrias.append(geometria_portalateral(self.bloque))
        for geometria in geometrias:
            geometria.transform(al_mapa)
        anterior = canvas.mapTool()

        def volver():
            self._herramienta_puntos = None
            if canvas.mapTool() is None and anterior is not None:
                canvas.setMapTool(anterior)
            self.show()
            self.raise_()
            self.activateWindow()

        def terminar(puntos):
            volver()
            listo(*[al_lote.transform(p) for p in puntos])

        barra = self.iface.statusBarIface()
        self._herramienta_puntos = HerramientaPuntos(canvas, cuantos, geometrias, mensajes, terminar, volver,
                                                     barra.showMessage)
        self.iface.messageBar().pushMessage("RiegoLibre", mensajes[0] + " (Esc para cancelar).",
                                            Qgis.MessageLevel.Info, 5)
        self.hide()
        canvas.setMapTool(self._herramienta_puntos)
        canvas.setFocus()

    def reject(self):
        from ..integracion.bloque_mapa import quitar_vista_previa
        quitar_vista_previa()
        super().reject()


def _sin_punto_de_valvula(valores):
    """Valores para otros lotes: el punto de la válvula es de un solo lote; en ellos va automática."""
    if valores.get("valvula") != VALV_PUNTO:
        return valores
    return dict(valores, valvula=VALV_AUTO, punto_valvula=None)


def _texto_portalateral(diseno):
    return descripcion_telescopico(diseno) if diseno.telescopico else diseno.tuberia.nombre


def _azimut(desde, hacia):
    return math.degrees(math.atan2(hacia[0] - desde[0], hacia[1] - desde[1])) % 360


def _texto_valvula(b, extremo_1, extremo_2):
    lado_1 = cardinal(_azimut(extremo_2, extremo_1))
    lado_2 = cardinal(_azimut(extremo_1, extremo_2))
    largo = b.longitud_portalateral_m
    if b.valvula_m <= 0.01:
        return f"en el extremo {lado_1} del portalateral"
    if b.valvula_m >= largo - 0.01:
        return f"en el extremo {lado_2} del portalateral"
    return f"a {b.valvula_m:.1f} m del extremo {lado_1} del portalateral ({b.valvula_m / largo:.0%})"
