"""Diseño de una subunidad de goteo: laterales + portalateral con selección de diámetro."""

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                                 QComboBox, QDialog, QDialogButtonBox,
                                 QFormLayout, QGroupBox, QHBoxLayout,
                                 QHeaderView, QLabel, QMessageBox, QPushButton,
                                 QRadioButton, QScrollArea, QSpinBox,
                                 QSplitter, QTableWidget, QTableWidgetItem,
                                 QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import (ENTRADA_CENTRO, ENTRADA_EXTREMO, CriteriosDiseno, Lateral,
                      PresionInsuficiente, cargar_catalogo_emisores,
                      cargar_catalogo_tuberias, evaluar_diametros,
                      incumplimientos, subunidad_rectangular)
from .comunes import (M_POR_BAR, Figure, FigureCanvasQTAgg, combo, descripcion_emisor,
                      html_avisos, html_estado, html_tabla, spin)

AUTOMATICA = -1


class DialogoSubunidad(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Subunidad de riego (goteo)")
        self.resize(1200, 760)

        self.tuberias_lateral = cargar_catalogo_tuberias(uso="lateral")
        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"),
                                            key=lambda t: t.diametro_interior_mm)
        self.emisores = cargar_catalogo_emisores()

        contenido = QWidget()
        izquierda = QVBoxLayout(contenido)
        izquierda.addWidget(self._grupo_laterales())
        izquierda.addWidget(self._grupo_portalateral())
        izquierda.addWidget(self._grupo_criterios())
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(contenido)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(400)
        desplazable.setMaximumWidth(520)

        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._pestana_resumen(), "Resumen")
        self.tabla_diametros = self._tabla([
            "Tubería", "DI (mm)", "Presión entrada (m)", "Velocidad (m/s)",
            "Var. caudal", "EU (%)", "Resultado"])
        self.tabla_diametros.cellDoubleClicked.connect(self._usar_diametro)
        pestana = QWidget()
        capa = QVBoxLayout(pestana)
        capa.addWidget(QLabel("Doble clic en una fila para calcular la subunidad con esa tubería."))
        capa.addWidget(self.tabla_diametros)
        self.pestanas.addTab(pestana, "Diámetros del portalateral")
        self.tabla_laterales = self._tabla([
            "Rama", "Posición (m)", "Presión portalateral (m)", "Caudal (L/h)",
            "Presión mín. emisor (m)", "Presión máx. emisor (m)", "Caudal mín. emisor (L/h)",
            "Fuera de rango"])
        self.pestanas.addTab(self.tabla_laterales, "Laterales")

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(desplazable)
        divisor.addWidget(self.pestanas)
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

        self._actualizar_emisor()
        self._actualizar_modo()
        self._actualizar_terreno()
        self._actualizar_longitud_portalateral()
        self.texto.setHtml(
            "<p>Configure los laterales y el portalateral y pulse <b>Calcular</b>.</p>"
            "<p>Con la tubería <b>automática</b> se elige el menor diámetro del catálogo que cumple "
            "la variación de caudal, la velocidad máxima y la presión máxima indicadas. "
            "La pestaña <i>Diámetros del portalateral</i> muestra la comparación completa.</p>")

    # ---------------------------------------------------------------- interfaz

    def _grupo_laterales(self):
        grupo = QGroupBox("Laterales")
        formulario = QFormLayout(grupo)
        self.combo_tuberia_lateral = combo()
        for t in self.tuberias_lateral:
            self.combo_tuberia_lateral.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)")
        formulario.addRow("Tubería:", self.combo_tuberia_lateral)

        self.combo_emisor = combo()
        for e in self.emisores:
            self.combo_emisor.addItem(e.nombre)
        self.combo_emisor.currentIndexChanged.connect(self._actualizar_emisor)
        formulario.addRow("Emisor:", self.combo_emisor)
        self.etiqueta_emisor = QLabel()
        self.etiqueta_emisor.setWordWrap(True)
        formulario.addRow("", self.etiqueta_emisor)

        self.spin_espaciamiento = spin(0.05, 10, 0.30, 0.05, sufijo="m")
        formulario.addRow("Espaciamiento entre emisores:", self.spin_espaciamiento)
        self.spin_primer = spin(0.0, 10, 0.30, 0.05, sufijo="m")
        formulario.addRow("Distancia al primer emisor:", self.spin_primer)
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
        return grupo

    def _grupo_portalateral(self):
        grupo = QGroupBox("Portalateral")
        formulario = QFormLayout(grupo)
        self.combo_tuberia_porta = combo()
        self.combo_tuberia_porta.addItem("Automática (menor diámetro que cumple)", AUTOMATICA)
        for i, t in enumerate(self.tuberias_portalateral):
            self.combo_tuberia_porta.addItem(f"{t.nombre}  (DI {t.diametro_interior_mm:.1f} mm)", i)
        formulario.addRow("Tubería:", self.combo_tuberia_porta)

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

    def _grupo_criterios(self):
        grupo = QGroupBox("Criterios de diseño")
        formulario = QFormLayout(grupo)
        self.radio_requerida = QRadioButton("Calcular la presión de entrada necesaria")
        self.radio_conocida = QRadioButton("Presión de entrada conocida:")
        self.radio_requerida.setChecked(True)
        self.radio_requerida.toggled.connect(self._actualizar_modo)
        formulario.addRow(self.radio_requerida)
        fila = QHBoxLayout()
        self.spin_presion = spin(0.5, 150, 15, 0.5, sufijo="m")
        fila.addWidget(self.radio_conocida)
        fila.addWidget(self.spin_presion)
        formulario.addRow(fila)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Darcy-Weisbach", "darcy")
        self.combo_metodo.addItem("Hazen-Williams", "hazen")
        formulario.addRow("Fórmula de pérdidas:", self.combo_metodo)
        self.spin_variacion = spin(1, 50, 10, 1, decimales=1, sufijo="%")
        self.spin_variacion.setToolTip("Variación de caudal entre todos los emisores de la subunidad.")
        formulario.addRow("Variación de caudal admisible:", self.spin_variacion)
        self.spin_velocidad = spin(0.3, 5, 1.5, 0.1, sufijo="m/s")
        formulario.addRow("Velocidad máxima en portalateral:", self.spin_velocidad)
        self.spin_presion_max = spin(0, 150, 0, 1, decimales=1, sufijo="m")
        self.spin_presion_max.setSpecialValueText("sin límite")
        formulario.addRow("Presión de entrada máxima:", self.spin_presion_max)
        return grupo

    def _pestana_resumen(self):
        self.texto = QTextBrowser()
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.texto)
        self.figura = None
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(6, 3.2), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            divisor.addWidget(self.lienzo)
        divisor.setSizes([330, 330])
        return divisor

    @staticmethod
    def _tabla(columnas):
        tabla = QTableWidget(0, len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.verticalHeader().setVisible(False)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tabla.horizontalHeader().setStretchLastSection(True)
        return tabla

    def _actualizar_emisor(self):
        self.etiqueta_emisor.setText(descripcion_emisor(self.emisor()))

    def _actualizar_modo(self):
        self.spin_presion.setEnabled(self.radio_conocida.isChecked())

    def _actualizar_terreno(self):
        usar = self.check_terreno.isChecked()
        self.combo_linea.setEnabled(usar)
        self.combo_dem.setEnabled(usar)
        self.spin_numero.setEnabled(not usar)
        self.spin_pendiente_porta.setEnabled(not usar)

    def _actualizar_longitud_portalateral(self):
        longitud = self.spin_numero.value() * self.spin_separacion.value()
        self.etiqueta_longitud.setText(f"{longitud:.1f} m")

    # ------------------------------------------------------------------ datos

    def emisor(self):
        return self.emisores[self.combo_emisor.currentIndex()]

    def tuberia_lateral(self):
        return self.tuberias_lateral[self.combo_tuberia_lateral.currentIndex()]

    def criterios(self):
        return CriteriosDiseno(
            variacion_caudal_max=self.spin_variacion.value() / 100,
            velocidad_max_ms=self.spin_velocidad.value(),
            presion_entrada_max_m=self.spin_presion_max.value() or None,
        )

    def _crear_laterales(self):
        metodo = self.combo_metodo.currentData()
        pendiente = self.spin_pendiente_lateral.value() / 100
        laterales = []
        for longitud, signo in ((self.spin_longitud_a.value(), 1), (self.spin_longitud_b.value(), -1)):
            if longitud <= 0:
                laterales.append(None)
                continue
            if longitud < self.spin_primer.value():
                raise ValueError("La longitud de los laterales es menor que la distancia al primer emisor.")
            laterales.append(Lateral.desde_longitud(
                self.tuberia_lateral(), self.emisor(), self.spin_espaciamiento.value(), longitud,
                distancia_primer_emisor_m=self.spin_primer.value(),
                pendiente=signo * pendiente, metodo=metodo))
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

    # ---------------------------------------------------------------- cálculo

    def calcular(self):
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            datos = self._calcular()
        except (ValueError, PresionInsuficiente) as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "RiegoLibre", error)
            return
        self._mostrar(*datos)

    def _calcular(self):
        lateral_a, lateral_b = self._crear_laterales()
        numero, pendiente, perfil = self._geometria_portalateral()
        separacion = self.spin_separacion.value()
        entrada = self.combo_entrada.currentData()
        metodo = self.combo_metodo.currentData()

        def construir(tuberia):
            return subunidad_rectangular(tuberia, lateral_a, lateral_b, separacion, numero,
                                         posicion_entrada=entrada, pendiente=pendiente,
                                         perfil=perfil, metodo=metodo)

        criterios = self.criterios()
        presion = self.spin_presion.value() if self.radio_conocida.isChecked() else None
        evaluaciones, elegida = evaluar_diametros(construir, self.tuberias_portalateral, criterios,
                                                  presion_entrada_m=presion)

        avisos = []
        indice = self.combo_tuberia_porta.currentData()
        if indice != AUTOMATICA:
            tuberia = self.tuberias_portalateral[indice]
        elif elegida is not None:
            tuberia = evaluaciones[elegida].tuberia
        else:
            calculables = [e for e in evaluaciones if e.resultado is not None]
            if not calculables:
                raise ValueError("No se pudo calcular la subunidad con ninguna tubería: "
                                 + evaluaciones[-1].motivos[0])
            tuberia = calculables[-1].tuberia
            avisos.append("Ningún diámetro del catálogo cumple todos los criterios; "
                          "se muestra el de mayor diámetro.")

        subunidad = construir(tuberia)
        if presion is None:
            resultado = subunidad.presion_entrada_requerida(detallado=True)
        else:
            resultado = subunidad.simular(presion, detallado=True)
        return subunidad, resultado, tuberia, evaluaciones, elegida, avisos, (lateral_a, lateral_b)

    # --------------------------------------------------------------- resultados

    def _mostrar(self, subunidad, r, tuberia, evaluaciones, elegida, avisos, laterales):
        self.resultado = r
        criterios = self.criterios()
        motivos = incumplimientos(r, criterios, tuberia)
        tuberia_lateral = self.tuberia_lateral()
        presion_max_laterales = max(p for rama in r.ramas for p in rama.presiones_m)
        if tuberia_lateral.presion_nominal_m and presion_max_laterales > tuberia_lateral.presion_nominal_m:
            avisos.append(f"La presión en la entrada de algunos laterales ({presion_max_laterales:.1f} m) "
                          f"supera la nominal de la tubería lateral ({tuberia_lateral.presion_nominal_m:g} m).")

        longitud_porta = self.spin_numero.value() * self.spin_separacion.value()
        ancho = self.spin_longitud_a.value() + self.spin_longitud_b.value()
        area_m2 = longitud_porta * ancho
        q = r.caudal_total_lh
        numero_laterales = sum(len(c.laterales) for rama in subunidad.ramas for c in rama.conexiones)
        presiones_laterales = [p for rama in r.ramas for p in rama.presiones_m]
        modo = "automática" if self.combo_tuberia_porta.currentData() == AUTOMATICA else "elegida"

        filas = [
            ("Tubería del portalateral", f"<b>{tuberia.nombre}</b> ({modo})"),
            ("Presión en la entrada (válvula)",
             f"<b>{r.presion_entrada_m:.2f} m</b> ({r.presion_entrada_m / M_POR_BAR:.2f} bar)"),
            ("Caudal de la subunidad",
             f"<b>{q:,.0f} L/h</b> ({q / 3600:.2f} L/s · {q / 1000:.2f} m³/h)"),
            ("Laterales / emisores", f"{numero_laterales} / {r.numero_emisores:,}"),
            ("Área", f"{area_m2 / 10000:.3f} ha ({longitud_porta:.1f} × {ancho:.1f} m)"),
            ("Precipitación horaria", f"{q / area_m2:.2f} mm/h" if area_m2 else "—"),
            ("Velocidad máxima en portalateral", f"{r.velocidad_max_ms:.2f} m/s"),
            ("Pérdida por fricción en portalateral", f"{r.perdida_friccion_max_m:.2f} m"),
            ("Presión en entrada de laterales",
             f"{min(presiones_laterales):.2f} – {max(presiones_laterales):.2f} m"),
            ("Presión en emisores (mín. / máx.)",
             f"{r.presion_min_emisor_m:.2f} / {r.presion_max_emisor_m:.2f} m"),
            ("Caudal de emisores (mín. / medio / máx.)",
             f"{r.caudal_min_lh:.3f} / {r.caudal_medio_lh:.3f} / {r.caudal_max_lh:.3f} L/h"),
            ("Variación de caudal", f"{r.variacion_caudal:.1%}"),
            ("Uniformidad de emisión (EU)", f"{r.uniformidad_emision:.1f} %"),
            ("Emisores fuera de rango", f"{r.emisores_fuera_de_rango}"),
        ]
        avisos = [m[0].upper() + m[1:] + "." for m in motivos] + avisos
        self.texto.setHtml(f"<h3>Subunidad — {html_estado(not motivos)}</h3>"
                           + html_tabla(filas) + html_avisos(avisos))
        self._llenar_diametros(evaluaciones, elegida, tuberia)
        self._llenar_laterales(r)
        self._graficar(r, laterales[0] or laterales[1])
        self.pestanas.setCurrentIndex(0)

    def _llenar_diametros(self, evaluaciones, elegida, tuberia_usada):
        self._evaluaciones = evaluaciones
        tabla = self.tabla_diametros
        tabla.setRowCount(len(evaluaciones))
        for fila, e in enumerate(evaluaciones):
            r = e.resultado
            valores = [e.tuberia.nombre, f"{e.tuberia.diametro_interior_mm:.1f}"]
            if r is None:
                valores += ["—"] * 4
            else:
                valores += [f"{r.presion_entrada_m:.2f}", f"{r.velocidad_max_ms:.2f}",
                            f"{r.variacion_caudal:.1%}", f"{r.uniformidad_emision:.1f}"]
            valores.append("✔ cumple" if e.cumple else "✘ " + "; ".join(e.motivos))
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if e.cumple:
                    item.setForeground(QBrush(QColor("#2e7d32")))
                if e.tuberia is tuberia_usada:
                    fuente = QFont()
                    fuente.setBold(True)
                    item.setFont(fuente)
                if fila == elegida:
                    item.setBackground(QBrush(QColor(46, 125, 50, 40)))
                tabla.setItem(fila, columna, item)

    def _usar_diametro(self, fila, _columna):
        tuberia = self._evaluaciones[fila].tuberia
        indice = self.combo_tuberia_porta.findData(self.tuberias_portalateral.index(tuberia))
        self.combo_tuberia_porta.setCurrentIndex(indice)
        self.calcular()

    @staticmethod
    def _ramas_con_signo(r):
        """Por rama: (nombre, signo) — con entrada central la segunda rama va hacia el inicio."""
        if len(r.ramas) == 1:
            return [("Única", 1)]
        return [("Hacia el final", 1), ("Hacia el inicio", -1)]

    def _llenar_laterales(self, r):
        filas = []
        for (nombre, signo), rama in zip(self._ramas_con_signo(r), r.ramas):
            for i, d in enumerate(rama.distancias_m):
                filas.append((signo * d, [
                    nombre, f"{signo * d:.1f}", f"{rama.presiones_m[i]:.2f}",
                    f"{rama.caudales_lh[i]:.1f}", f"{rama.h_min_m[i]:.2f}", f"{rama.h_max_m[i]:.2f}",
                    f"{rama.q_min_lh[i]:.3f}", "Sí" if rama.fuera_de_rango[i] else "No"]))
        filas.sort(key=lambda f: f[0])
        tabla = self.tabla_laterales
        tabla.setRowCount(len(filas))
        for fila, (_, valores) in enumerate(filas):
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if columna and valor.replace(".", "").replace("-", "").isdigit():
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tabla.setItem(fila, columna, item)

    def _graficar(self, r, lateral):
        if self.figura is None:
            return
        puntos = []
        for (_, signo), rama in zip(self._ramas_con_signo(r), r.ramas):
            for i, d in enumerate(rama.distancias_m):
                puntos.append((signo * d, rama.presiones_m[i], rama.h_min_m[i], rama.h_max_m[i],
                               rama.cotas_m[i]))
        puntos.append((0.0, r.presion_entrada_m, None, None, 0.0))
        puntos.sort(key=lambda p: p[0])
        x = [p[0] for p in puntos]
        con_emisores = [p for p in puntos if p[2] is not None]

        self.figura.clear()
        ejes = self.figura.add_subplot(111)
        ejes.plot(x, [p[1] for p in puntos], color="#1e88e5", label="Presión en el portalateral")
        ejes.fill_between([p[0] for p in con_emisores], [p[2] for p in con_emisores],
                          [p[3] for p in con_emisores], color="#43a047", alpha=0.25,
                          label="Presión en emisores (mín.–máx.)")
        ejes.plot([0], [r.presion_entrada_m], "o", color="#c62828", label="Entrada (válvula)")
        e = lateral.emisor
        if e.autocompensado:
            ejes.axhline(e.presion_compensacion_m, color="#43a047", linestyle=":",
                         label="Inicio de compensación")
        else:
            ejes.axhline(e.presion_nominal_m, color="#43a047", linestyle=":", label="Presión nominal")
        ejes.set_xlabel("Posición a lo largo del portalateral, desde la entrada (m)")
        ejes.set_ylabel("Presión (m.c.a.)")
        ejes.grid(True, alpha=0.3)

        terreno = ejes.twinx()
        terreno.plot(x, [p[4] for p in puntos], color="#6d4c41", linewidth=1, label="Terreno (relativo)")
        terreno.set_ylabel("Cota relativa (m)")
        lineas = ejes.get_legend_handles_labels()
        lineas_t = terreno.get_legend_handles_labels()
        ejes.legend(lineas[0] + lineas_t[0], lineas[1] + lineas_t[1], loc="best", fontsize=8)
        self.lienzo.draw()
