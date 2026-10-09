"""Red principal y bomba: diámetros por tramo, turnos de riego y carga dinámica total."""

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                                 QDialog, QDialogButtonBox, QFormLayout,
                                 QGroupBox, QHeaderView, QMessageBox,
                                 QPushButton, QScrollArea, QSpinBox, QSplitter,
                                 QTableWidget, QTableWidgetItem, QTabWidget,
                                 QTextBrowser, QVBoxLayout, QWidget)

from ..nucleo import (CriteriosRed, DatosBomba, cargar_catalogo_tuberias,
                      dimensionar_red, punto_bomba)
from .comunes import (M_POR_BAR, Figure, FigureCanvasQTAgg, html_avisos, html_estado,
                      html_tabla, spin)

NOMBRE_GRUPO = "RiegoLibre · Red principal"


def _combo_capas(filtro, vacia=None):
    control = QgsMapLayerComboBox()
    control.setFilters(filtro)
    if vacia is not None:
        try:
            control.setAllowEmptyLayer(True, vacia)
        except TypeError:
            control.setAllowEmptyLayer(True)
    return control


def _tabla(columnas):
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tabla.horizontalHeader().setStretchLastSection(True)
    return tabla


def _llenar(tabla, filas):
    tabla.setRowCount(len(filas))
    for f, valores in enumerate(filas):
        for c, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if c and (valor[:1].isdigit() or valor[:1] == "-"):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tabla.setItem(f, c, item)


class DialogoRed(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Red principal y bomba")
        self.resize(1250, 800)
        self.tuberias = cargar_catalogo_tuberias(uso="principal")
        self.valvulas = []  # ValvulaMapa encontradas en el proyecto
        self.resultado = None

        contenido = QWidget()
        izquierda = QVBoxLayout(contenido)
        izquierda.addWidget(self._grupo_red())
        izquierda.addWidget(self._grupo_valvulas())
        izquierda.addWidget(self._grupo_criterios())
        izquierda.addWidget(self._grupo_bomba())
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(contenido)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(430)
        desplazable.setMaximumWidth(540)

        self.pestanas = QTabWidget()
        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<h3>Pasos</h3><ol>"
            "<li>Diseñe las subunidades en el mapa: cada una deja una capa <i>Válvula · nombre</i> "
            "con su caudal y presión requerida.</li>"
            "<li>Dibuje la <b>fuente</b> (un punto donde está la bomba y el cabezal) y las "
            "<b>tuberías</b> de la red principal hasta cada válvula. No hace falta cortar las líneas "
            "en las uniones.</li>"
            "<li>Pulse <b>Buscar válvulas</b>, asigne los <b>turnos</b> de riego y pulse "
            "<b>Calcular</b>.</li></ol>")
        resumen = QSplitter(Qt.Orientation.Vertical)
        resumen.addWidget(self.texto)
        self.figura = None
        if FigureCanvasQTAgg is not None:
            self.figura = Figure(figsize=(6, 3.2), layout="constrained")
            self.lienzo = FigureCanvasQTAgg(self.figura)
            resumen.addWidget(self.lienzo)
        resumen.setSizes([360, 330])
        self.pestanas.addTab(resumen, "Resumen")
        self.tabla_turnos = _tabla(["Turno", "Válvulas", "Caudal (L/s)", "Presión entrada red (m)",
                                    "CDT (m)", "Potencia (kW)", "Potencia (HP)", "Determina la carga"])
        self.pestanas.addTab(self.tabla_turnos, "Turnos")
        self.tabla_tramos = _tabla(["Tramo", "Tubería", "Longitud (m)", "Caudal máx. (L/h)",
                                    "Velocidad (m/s)", "Pérdida (m/100 m)", "Presión mín. (m)",
                                    "Presión máx. (m)", "Observaciones"])
        self.pestanas.addTab(self.tabla_tramos, "Tramos")
        self.tabla_resultado_valvulas = _tabla(["Válvula", "Turno", "Caudal (L/h)", "Presión requerida (m)",
                                                "Presión disponible (m)", "Exceso a regular (m)"])
        self.pestanas.addTab(self.tabla_resultado_valvulas, "Válvulas")

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

    # ---------------------------------------------------------------- interfaz

    def _grupo_red(self):
        grupo = QGroupBox("Red")
        formulario = QFormLayout(grupo)
        self.combo_tuberias = _combo_capas(Qgis.LayerFilter.LineLayer)
        formulario.addRow("Capa de tuberías:", self.combo_tuberias)
        self.combo_fuente = _combo_capas(Qgis.LayerFilter.PointLayer)
        formulario.addRow("Capa de la fuente:", self.combo_fuente)
        self.combo_dem = _combo_capas(Qgis.LayerFilter.RasterLayer, "Sin DEM (terreno plano)")
        formulario.addRow("DEM:", self.combo_dem)
        self.spin_tolerancia = spin(0.01, 20, 0.5, 0.1, sufijo="m")
        self.spin_tolerancia.setToolTip("Distancia máxima para considerar unidos dos extremos de "
                                        "tubería, o una válvula y la tubería que la alimenta.")
        formulario.addRow("Tolerancia de conexión:", self.spin_tolerancia)
        boton = QPushButton("Crear capas para dibujar")
        boton.setToolTip("Crea capas temporales «Fuente» (punto) y «Red principal» (líneas) en el SRC "
                         "del proyecto y activa la edición de la fuente.")
        boton.clicked.connect(self.crear_capas_de_dibujo)
        formulario.addRow(boton)
        return grupo

    def crear_capas_de_dibujo(self):
        from ..integracion.subunidad_mapa import verificar_crs_metrico
        proyecto = QgsProject.instance()
        try:
            verificar_crs_metrico(proyecto.crs(), "del proyecto")
        except ValueError as error:
            QMessageBox.warning(self, "RiegoLibre", f"{error} Cámbielo en Proyecto → Propiedades → SRC.")
            return
        fuente = QgsVectorLayer("Point?field=nombre:string(50)", "Fuente", "memory")
        tuberias = QgsVectorLayer("LineString?field=nombre:string(50)", "Red principal", "memory")
        for capa in (fuente, tuberias):
            capa.setCrs(proyecto.crs())
        proyecto.addMapLayers([fuente, tuberias])
        self.combo_fuente.setLayer(fuente)
        self.combo_tuberias.setLayer(tuberias)
        if self.iface is not None:
            self.iface.setActiveLayer(fuente)
            fuente.startEditing()
            self.iface.actionAddFeature().trigger()
        self.texto.setHtml(
            "<p>Se crearon las capas temporales <b>Fuente</b> y <b>Red principal</b>.</p>"
            "<p>Marque la fuente con un clic. Luego active la edición de <i>Red principal</i> y dibuje "
            "las tuberías desde la fuente hasta cada válvula (active el autoajuste para unir bien "
            "los extremos). Guarde las ediciones.</p>")

    def _grupo_valvulas(self):
        grupo = QGroupBox("Válvulas y turnos de riego")
        capa = QVBoxLayout(grupo)
        boton = QPushButton("Buscar válvulas en el proyecto")
        boton.setToolTip("Busca capas de puntos con los campos «presion» y «caudal_lh», como las "
                         "capas «Válvula · …» que crea el diseño de subunidades.")
        boton.clicked.connect(self.buscar_valvulas)
        capa.addWidget(boton)
        self.tabla_valvulas = QTableWidget(0, 4)
        self.tabla_valvulas.setHorizontalHeaderLabels(["Válvula", "Caudal (L/h)", "Presión (m)", "Turno"])
        self.tabla_valvulas.verticalHeader().setVisible(False)
        self.tabla_valvulas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_valvulas.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabla_valvulas.horizontalHeader().setStretchLastSection(True)
        self.tabla_valvulas.setMinimumHeight(140)
        capa.addWidget(self.tabla_valvulas)
        formulario = QFormLayout()
        self.spin_perdida_valvula = spin(0, 30, 2.0, 0.5, sufijo="m")
        self.spin_perdida_valvula.setToolTip("Pérdida en la válvula de cada subunidad y sus accesorios.")
        formulario.addRow("Pérdida en cada válvula:", self.spin_perdida_valvula)
        capa.addLayout(formulario)
        return grupo

    def _grupo_criterios(self):
        grupo = QGroupBox("Criterios de diseño de la red")
        formulario = QFormLayout(grupo)
        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Darcy-Weisbach", "darcy")
        self.combo_metodo.addItem("Hazen-Williams", "hazen")
        formulario.addRow("Fórmula de pérdidas:", self.combo_metodo)
        self.spin_velocidad = spin(0.3, 5, 1.5, 0.1, sufijo="m/s")
        formulario.addRow("Velocidad máxima:", self.spin_velocidad)
        self.spin_j_max = spin(0, 20, 0, 0.1, sufijo="m/100 m")
        self.spin_j_max.setSpecialValueText("sin límite")
        formulario.addRow("Pérdida unitaria máxima:", self.spin_j_max)
        self.spin_presion_min = spin(0, 30, 2.0, 0.5, sufijo="m")
        self.spin_presion_min.setToolTip("Presión mínima en cualquier punto de la red, incluidos "
                                         "los puntos altos del terreno.")
        formulario.addRow("Presión mínima en la red:", self.spin_presion_min)
        self.spin_menores = spin(0, 100, 10, 1, decimales=0, sufijo="%")
        self.spin_menores.setToolTip("Pérdidas en codos, tes y válvulas como porcentaje de la fricción.")
        formulario.addRow("Pérdidas menores:", self.spin_menores)
        return grupo

    def _grupo_bomba(self):
        grupo = QGroupBox("Cabezal y bomba")
        formulario = QFormLayout(grupo)
        self.spin_cabezal = spin(0, 50, 7.0, 0.5, sufijo="m")
        self.spin_cabezal.setToolTip("Filtros, fertirriego, medidor y válvulas del cabezal.")
        formulario.addRow("Pérdidas en el cabezal:", self.spin_cabezal)
        self.spin_succion = spin(-20, 100, 2.0, 0.5, sufijo="m")
        self.spin_succion.setToolTip("Desnivel desde el nivel del agua hasta la bomba más las pérdidas "
                                     "en la succión (negativo si el agua está por encima de la bomba).")
        formulario.addRow("Altura de succión:", self.spin_succion)
        self.spin_eficiencia = spin(10, 100, 70, 1, decimales=0, sufijo="%")
        formulario.addRow("Eficiencia de la bomba:", self.spin_eficiencia)
        return grupo

    # ---------------------------------------------------------------- válvulas

    def buscar_valvulas(self):
        from ..integracion.red_mapa import capas_de_valvulas, leer_valvulas
        capa_tuberias = self.combo_tuberias.currentLayer()
        if capa_tuberias is None:
            QMessageBox.warning(self, "RiegoLibre", "Elija primero la capa de tuberías.")
            return
        turnos = {v.id: v.turno for v in self.valvulas}
        self.valvulas = leer_valvulas(capas_de_valvulas(), capa_tuberias.crs())
        for v in self.valvulas:
            v.turno = turnos.get(v.id, 1)
        tabla = self.tabla_valvulas
        tabla.setRowCount(len(self.valvulas))
        for fila, v in enumerate(self.valvulas):
            for columna, texto in enumerate([v.id, f"{v.caudal_lh:,.0f}", f"{v.presion_m:.2f}"]):
                tabla.setItem(fila, columna, QTableWidgetItem(texto))
            turno = QSpinBox()
            turno.setRange(1, 50)
            turno.setValue(v.turno)
            tabla.setCellWidget(fila, 3, turno)
        if not self.valvulas:
            QMessageBox.information(self, "RiegoLibre",
                                    "No se encontraron válvulas. Diseñe las subunidades en el mapa o "
                                    "cree una capa de puntos con los campos «presion» (m) y "
                                    "«caudal_lh» (L/h).")

    def _turnos_de_tabla(self):
        for fila, v in enumerate(self.valvulas):
            v.turno = self.tabla_valvulas.cellWidget(fila, 3).value()

    # ---------------------------------------------------------------- cálculo

    def criterios(self):
        return CriteriosRed(
            velocidad_max_ms=self.spin_velocidad.value(),
            perdida_unitaria_max_m100=self.spin_j_max.value() or None,
            presion_min_m=self.spin_presion_min.value(),
            factor_perdidas_menores=self.spin_menores.value() / 100,
            metodo=self.combo_metodo.currentData(),
        )

    def datos_bomba(self):
        return DatosBomba(perdidas_cabezal_m=self.spin_cabezal.value(),
                          altura_succion_m=self.spin_succion.value(),
                          eficiencia=self.spin_eficiencia.value() / 100)

    def calcular(self):
        from ..integracion.perfil_terreno import MuestreadorDem, entidad_unica
        from ..integracion.red_mapa import capas_resultado, construir_red
        from ..integracion.subunidad_mapa import (geometria_en, reemplazar_grupo,
                                                  verificar_crs_metrico)
        error = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            capa_tuberias, capa_fuente = self.combo_tuberias.currentLayer(), self.combo_fuente.currentLayer()
            if capa_tuberias is None or capa_fuente is None:
                raise ValueError("Elija la capa de tuberías y la capa de la fuente.")
            if not self.valvulas:
                raise ValueError("Pulse «Buscar válvulas en el proyecto» antes de calcular.")
            crs = capa_tuberias.crs()
            verificar_crs_metrico(crs, capa_tuberias.name())
            self._turnos_de_tabla()
            fuente = geometria_en(capa_fuente, entidad_unica(capa_fuente), crs).asPoint()
            dem = self.combo_dem.currentLayer()
            red_mapa = construir_red(capa_tuberias, fuente, self.valvulas, crs,
                                     MuestreadorDem(dem, crs) if dem is not None else None,
                                     tolerancia_m=self.spin_tolerancia.value(),
                                     perdida_valvula_m=self.spin_perdida_valvula.value())
            resultado = dimensionar_red(red_mapa.red, self.tuberias, self.criterios())
            bombas = [punto_bomba(r, self.datos_bomba()) for r in resultado.turnos]
            critica = max(bombas, key=lambda b: (b.carga_dinamica_total_m, b.caudal_lh))
            capas = capas_resultado(red_mapa, resultado, critica, crs)
            reemplazar_grupo(NOMBRE_GRUPO, capas)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        except ValueError as e:
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "RiegoLibre", error)
            return
        self.red_mapa, self.resultado, self.bombas = red_mapa, resultado, bombas
        self._mostrar(red_mapa, resultado, bombas, critica)

    # --------------------------------------------------------------- resultados

    def _mostrar(self, red_mapa, resultado, bombas, critica):
        red = red_mapa.red
        turno = resultado.turno(critica.turno)
        longitud = sum(t.longitud_m for t in red.tramos)
        caudal_max = max(b.caudal_lh for b in bombas)
        cumple = not resultado.motivos
        avisos = list(resultado.avisos)
        for id_tramo, motivos in resultado.motivos.items():
            avisos.append(f"Tramo {id_tramo}: " + "; ".join(motivos) + ".")
        if red_mapa.sin_dem:
            avisos.append("Sin DEM: la red se calculó con el terreno plano.")
        if len(bombas) > 1 and abs(caudal_max - critica.caudal_lh) > 1:
            avisos.append(f"El caudal máximo ({caudal_max / 3600:.2f} L/s) no coincide con el del turno "
                          "crítico: verifique la curva de la bomba en ambos puntos (ver pestaña Turnos).")

        metros = {}
        for t in red.tramos:
            nombre = resultado.asignacion[t.id].nombre
            metros[nombre] = metros.get(nombre, 0.0) + t.longitud_m
        filas = [
            ("Punto de diseño de la bomba", f"<b>{critica.caudal_ls:.2f} L/s</b> ({critica.caudal_m3h:.1f} m³/h) "
                                            f"a <b>{critica.carga_dinamica_total_m:.1f} m</b> de CDT"),
            ("Potencia hidráulica / al eje",
             f"{critica.potencia_kw * self.spin_eficiencia.value() / 100:.2f} kW / "
             f"<b>{critica.potencia_kw:.2f} kW</b> ({critica.potencia_hp:.1f} HP)"),
            ("Turno crítico", f"{critica.turno} (de {len(bombas)}) · lo determina la {turno.critico}"),
            ("Presión a la entrada de la red",
             f"{turno.presion_entrada_red_m:.2f} m ({turno.presion_entrada_red_m / M_POR_BAR:.2f} bar)"),
            ("Componentes de la CDT",
             f"red {turno.presion_entrada_red_m:.1f} + cabezal {self.spin_cabezal.value():.1f} + "
             f"succión {self.spin_succion.value():.1f} m"),
            ("Red principal", f"{len(red.tramos)} tramos · {longitud:,.0f} m · {len(red.valvulas)} válvulas"),
        ]
        filas += [(f"&nbsp;&nbsp;{nombre}", f"{m:,.1f} m") for nombre, m in sorted(metros.items())]
        self.texto.setHtml(f"<h3>Red principal — {html_estado(cumple)}</h3>"
                           + html_tabla(filas) + html_avisos(avisos))

        _llenar(self.tabla_turnos, [
            [str(b.turno), str(sum(1 for v in red.valvulas if v.turno == b.turno)), f"{b.caudal_ls:.2f}",
             f"{resultado.turno(b.turno).presion_entrada_red_m:.2f}", f"{b.carga_dinamica_total_m:.2f}",
             f"{b.potencia_kw:.2f}", f"{b.potencia_hp:.1f}", resultado.turno(b.turno).critico]
            for b in bombas])
        filas_tramos = []
        for t in red.tramos:
            q, p_min, p_max = resultado.peor_tramo(t.id)
            peores = [r.tramos[t.id] for r in resultado.turnos]
            filas_tramos.append([
                t.id, resultado.asignacion[t.id].nombre, f"{t.longitud_m:.1f}", f"{q:,.0f}",
                f"{max(r.velocidad_ms for r in peores):.2f}",
                f"{max(r.perdida_unitaria_m100 for r in peores):.2f}", f"{p_min:.2f}", f"{p_max:.2f}",
                resultado.observaciones(t.id)])
        _llenar(self.tabla_tramos, filas_tramos)
        _llenar(self.tabla_resultado_valvulas, [
            [v.id, str(v.turno), f"{v.caudal_lh:,.0f}", f"{v.presion_requerida_m:.2f}",
             f"{resultado.turno(v.turno).presion_disponible[v.id]:.2f}",
             f"{resultado.turno(v.turno).exceso(v):.2f}"]
            for v in red.valvulas])
        self._graficar(red, turno)
        self.pestanas.setCurrentIndex(0)

    def _graficar(self, red, turno):
        """Perfil de la ruta hasta la válvula más desfavorecida del turno crítico."""
        if self.figura is None:
            return
        activas = [v for v in red.valvulas if v.turno == turno.turno]
        valvula = min(activas, key=turno.exceso)
        x, terreno, piezometrica = [], [], []
        inicio = 0.0
        for t in red.camino(valvula.nodo):
            r = turno.tramos[t.id]
            j = r.perdida_m / t.longitud_m if t.longitud_m else 0.0
            puntos = [(0.0, red.cotas[t.desde])] + list(t.perfil or ()) + [(t.longitud_m, red.cotas[t.hasta])]
            for d, z in puntos:
                x.append(inicio + d)
                terreno.append(z)
                piezometrica.append(turno.cargas[t.desde] - j * d)
            inicio += t.longitud_m

        self.figura.clear()
        ejes = self.figura.add_subplot(111)
        ejes.fill_between(x, min(terreno) - 1, terreno, color="#8d6e63", alpha=0.35, label="Terreno")
        ejes.plot(x, piezometrica, color="#1e88e5", label="Línea piezométrica")
        requerida = red.cotas[valvula.nodo] + valvula.presion_requerida_m + valvula.perdida_m
        ejes.plot([x[-1]], [requerida], "o", color="#c62828", label=f"Carga requerida en {valvula.id}")
        ejes.plot([0], [turno.carga_fuente_m], "s", color="#1565c0", label="Salida del cabezal")
        ejes.set_xlabel("Distancia desde la fuente (m)")
        ejes.set_ylabel("Cota (m)")
        ejes.set_title(f"Ruta crítica del turno {turno.turno}", fontsize=10)
        ejes.grid(True, alpha=0.3)
        ejes.legend(loc="best", fontsize=8)
        self.lienzo.draw()
