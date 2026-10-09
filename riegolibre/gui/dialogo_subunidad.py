"""Diseño de una subunidad de goteo rectangular: laterales + portalateral."""

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QFormLayout, QGroupBox,
                                 QLabel, QMessageBox, QPushButton, QScrollArea,
                                 QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ..nucleo import (ENTRADA_CENTRO, ENTRADA_EXTREMO, Lateral,
                      PresionInsuficiente, cargar_catalogo_emisores,
                      cargar_catalogo_tuberias, disenar_subunidad,
                      subunidad_rectangular)
from ..nucleo.tuberias import clave_economica
from .comunes import (ComboDiametros, ComboTuberiaPortalateral, GrupoCriterios,
                      GrupoLaterales, spin)
from .panel_resultados import PanelResultadosSubunidad


class DialogoSubunidad(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Subunidad de riego (goteo)")
        self.resize(1200, 760)

        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"),
                                            key=clave_economica)
        self.grupo_laterales = GrupoLaterales(cargar_catalogo_tuberias(uso="lateral"),
                                              cargar_catalogo_emisores())
        self._completar_grupo_laterales()
        self.grupo_criterios = GrupoCriterios()

        contenido = QWidget()
        izquierda = QVBoxLayout(contenido)
        izquierda.addWidget(self.grupo_laterales)
        izquierda.addWidget(self._grupo_portalateral())
        izquierda.addWidget(self.grupo_criterios)
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(contenido)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(400)
        desplazable.setMaximumWidth(520)

        self.panel = PanelResultadosSubunidad(
            "<p>Configure los laterales y el portalateral y pulse <b>Calcular</b>.</p>"
            "<p>Con la tubería <b>automática</b> se elige el menor diámetro del catálogo que cumple "
            "la variación de caudal, la velocidad máxima y la presión máxima indicadas. "
            "La pestaña <i>Diámetros del portalateral</i> muestra la comparación completa.</p>")
        self.panel.tuberia_elegida.connect(self._usar_tuberia)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(desplazable)
        divisor.addWidget(self.panel)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_calcular = QPushButton("Calcular")
        self.boton_calcular.setDefault(True)
        botones.addButton(self.boton_calcular, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_calcular.clicked.connect(self.calcular)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)
        self._actualizar_terreno()
        self._actualizar_longitud_portalateral()

    # ---------------------------------------------------------------- interfaz

    def _completar_grupo_laterales(self):
        formulario = self.grupo_laterales.formulario
        self.spin_longitud_a = spin(0, 1000, 50, 5, decimales=1, sufijo="m")
        formulario.addRow("Longitud de laterales, lado A:", self.spin_longitud_a)
        self.spin_longitud_b = spin(0, 1000, 50, 5, decimales=1, sufijo="m")
        self.spin_longitud_b.setSpecialValueText("sin laterales")
        formulario.addRow("Longitud de laterales, lado B:", self.spin_longitud_b)
        self.spin_pendiente_lateral = spin(-50, 50, 0, 0.5, sufijo="%")
        self.spin_pendiente_lateral.setToolTip(
            "Pendiente transversal, positiva si el terreno sube hacia el lado A. "
            "Los laterales del lado B tienen la pendiente contraria.")
        formulario.addRow("Pendiente hacia el lado A:", self.spin_pendiente_lateral)

    def _grupo_portalateral(self):
        grupo = QGroupBox("Portalateral")
        formulario = QFormLayout(grupo)
        self.combo_tuberia_porta = ComboTuberiaPortalateral(self.tuberias_portalateral)
        formulario.addRow("Tubería:", self.combo_tuberia_porta)
        self.combo_diametros = ComboDiametros()
        formulario.addRow("Diámetros:", self.combo_diametros)

        self.spin_separacion = spin(0.2, 20, 1.5, 0.1, sufijo="m")
        self.spin_separacion.setToolTip("Distancia entre hileras de laterales (marco entre líneas).")
        self.spin_separacion.valueChanged.connect(self._actualizar_longitud_portalateral)
        formulario.addRow("Separación entre laterales:", self.spin_separacion)
        self.spin_numero = QSpinBox()
        self.spin_numero.setRange(1, 5000)
        self.spin_numero.setValue(40)
        self.spin_numero.valueChanged.connect(self._actualizar_longitud_portalateral)
        formulario.addRow("Número de laterales por lado:", self.spin_numero)
        self.etiqueta_longitud = QLabel()
        formulario.addRow("Longitud del portalateral:", self.etiqueta_longitud)

        self.combo_entrada = QComboBox()
        self.combo_entrada.addItem("En un extremo", ENTRADA_EXTREMO)
        self.combo_entrada.addItem("En el centro", ENTRADA_CENTRO)
        formulario.addRow("Entrada (válvula):", self.combo_entrada)
        self.spin_pendiente_porta = spin(-50, 50, 0, 0.5, sufijo="%")
        self.spin_pendiente_porta.setToolTip(
            "Positiva si el terreno sube desde el inicio del portalateral hacia su final.")
        formulario.addRow("Pendiente del portalateral:", self.spin_pendiente_porta)

        self.check_terreno = QCheckBox("Tomar el portalateral de una línea y un DEM")
        self.check_terreno.toggled.connect(self._actualizar_terreno)
        formulario.addRow(self.check_terreno)
        self.combo_linea = QgsMapLayerComboBox()
        self.combo_linea.setFilters(Qgis.LayerFilter.LineLayer)
        formulario.addRow("Capa de líneas:", self.combo_linea)
        self.combo_dem = QgsMapLayerComboBox()
        self.combo_dem.setFilters(Qgis.LayerFilter.RasterLayer)
        formulario.addRow("DEM:", self.combo_dem)
        nota = QLabel("Se usa la línea seleccionada: su longitud fija el número de laterales y su "
                      "primer vértice es el inicio del portalateral.")
        nota.setWordWrap(True)
        formulario.addRow(nota)
        return grupo

    def _actualizar_terreno(self):
        usar = self.check_terreno.isChecked()
        self.combo_linea.setEnabled(usar)
        self.combo_dem.setEnabled(usar)
        self.spin_numero.setEnabled(not usar)
        self.spin_pendiente_porta.setEnabled(not usar)

    def _actualizar_longitud_portalateral(self):
        longitud = self.spin_numero.value() * self.spin_separacion.value()
        self.etiqueta_longitud.setText(f"{longitud:.1f} m")

    def _usar_tuberia(self, tuberia):
        self.combo_tuberia_porta.elegir(tuberia)
        self.calcular()

    # ---------------------------------------------------------------- cálculo

    def _crear_laterales(self):
        grupo = self.grupo_laterales
        pendiente = self.spin_pendiente_lateral.value() / 100
        laterales = []
        for longitud, signo in ((self.spin_longitud_a.value(), 1), (self.spin_longitud_b.value(), -1)):
            if longitud <= 0:
                laterales.append(None)
                continue
            if longitud < grupo.spin_primer.value():
                raise ValueError("La longitud de los laterales es menor que la distancia al primer emisor.")
            laterales.append(Lateral.desde_longitud(
                grupo.tuberia(), grupo.emisor(), grupo.spin_espaciamiento.value(), longitud,
                distancia_primer_emisor_m=grupo.spin_primer.value(),
                pendiente=signo * pendiente, metodo=self.grupo_criterios.metodo()))
        if laterales == [None, None]:
            raise ValueError("Indique la longitud de los laterales de al menos un lado.")
        return laterales

    def _geometria_portalateral(self):
        """Devuelve (número de laterales por lado, pendiente, perfil o None)."""
        if not self.check_terreno.isChecked():
            return self.spin_numero.value(), self.spin_pendiente_porta.value() / 100, None
        from ..integracion.perfil_terreno import entidad_unica, extraer_perfil
        capa_linea, capa_dem = self.combo_linea.currentLayer(), self.combo_dem.currentLayer()
        if capa_linea is None or capa_dem is None:
            raise ValueError("Elija una capa de líneas y un DEM.")
        separacion = self.spin_separacion.value()
        longitud, perfil = extraer_perfil(capa_linea, entidad_unica(capa_linea), capa_dem,
                                          paso_m=max(separacion, 0.5))
        numero = max(1, int(round(longitud / separacion)))
        self.spin_numero.setValue(numero)
        return numero, 0.0, perfil

    def calcular(self):
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lateral_a, lateral_b = self._crear_laterales()
            numero, pendiente, perfil = self._geometria_portalateral()
            separacion = self.spin_separacion.value()
            entrada = self.combo_entrada.currentData()
            metodo = self.grupo_criterios.metodo()

            def construir(tuberia, reducciones=()):
                return subunidad_rectangular(tuberia, lateral_a, lateral_b, separacion, numero,
                                             posicion_entrada=entrada, pendiente=pendiente,
                                             perfil=perfil, metodo=metodo, reducciones=reducciones)

            diseno = disenar_subunidad(construir, self.tuberias_portalateral,
                                       self.grupo_criterios.criterios(),
                                       tuberia_fija=self.combo_tuberia_porta.tuberia(),
                                       presion_entrada_m=self.grupo_criterios.presion_conocida(),
                                       diametros_max=self.combo_diametros.maximo())
        except (ValueError, PresionInsuficiente) as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "RiegoLibre", error)
            return
        longitud_porta = numero * separacion
        ancho = self.spin_longitud_a.value() + self.spin_longitud_b.value()
        self.panel.mostrar(diseno, self.grupo_criterios.criterios(), self.grupo_laterales.tuberia(),
                           longitud_porta * ancho, f"{longitud_porta:.1f} × {ancho:.1f} m")
