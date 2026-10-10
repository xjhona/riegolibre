"""Trazado automático: laterales, portalaterales y subunidades sobre el polígono de un terreno."""

import re

from qgis.core import Qgis, QgsLayerTreeGroup, QgsProject
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QFormLayout, QGroupBox, QHeaderView,
                                 QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                                 QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
                                 QVBoxLayout, QWidget)

from ..integracion.calculo_subunidad import ENTRADA_CENTRO, ENTRADA_INICIO
from ..nucleo import PresionInsuficiente, cargar_catalogo_emisores, cargar_catalogo_tuberias
from ..nucleo.subunidad import incumplimientos
from ..nucleo.trazado import (LADOS_AMBOS, LADOS_UNO, ParametrosTrazado, buscar_trazados)
from ..nucleo.tuberias import clave_economica
from .comunes import (ComboDiametros, ComboTuberiaPortalateral, GrupoCriterios,
                      GrupoLaterales, html_avisos, html_estado, html_tabla, spin)

ALCANCE_HIDRAULICO, ALCANCE_FIJO = "hidraulico", "fijo"
COLUMNAS = ["#", "Dirección de laterales", "Subunidades", "Laterales (m)", "Portalaterales (m)",
            "Sin regar", "Pendiente de laterales", "Puntuación"]


def _combo_capas(filtro, vacia=None):
    control = QgsMapLayerComboBox()
    control.setFilters(filtro)
    if vacia is not None:
        try:
            control.setAllowEmptyLayer(True, vacia)
        except TypeError:  # versiones de QGIS sin texto para la opción vacía
            control.setAllowEmptyLayer(True)
    return control


def eliminar_grupos(patron):
    """Quita del proyecto los grupos (y sus capas) cuyo nombre coincide con el patrón."""
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    for grupo in [g for g in raiz.children() if isinstance(g, QgsLayerTreeGroup) and re.fullmatch(patron, g.name())]:
        for nodo in grupo.findLayers():
            proyecto.removeMapLayer(nodo.layerId())
        raiz.removeChildNode(grupo)


class DialogoTrazado(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Trazado automático de subunidades (goteo)")
        self.resize(1300, 820)
        self.trazados = []
        self.contexto = None  # datos de la última búsqueda

        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"),
                                            key=clave_economica)
        self.grupo_laterales = GrupoLaterales(cargar_catalogo_tuberias(uso="lateral"),
                                              cargar_catalogo_emisores(), "Laterales y emisores")
        self.grupo_criterios = GrupoCriterios()

        contenido = QWidget()
        izquierda = QVBoxLayout(contenido)
        izquierda.addWidget(self._grupo_terreno())
        izquierda.addWidget(self._grupo_trazado())
        izquierda.addWidget(self.grupo_laterales)
        izquierda.addWidget(self._grupo_portalateral())
        izquierda.addWidget(self.grupo_criterios)
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(contenido)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(430)
        desplazable.setMaximumWidth(560)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.itemSelectionChanged.connect(self._seleccion_cambiada)
        self.texto = QTextBrowser()
        self.texto.setHtml(
            "<h3>Pasos</h3><ol>"
            "<li>Elija la capa con el <b>polígono del terreno</b> (puede tener huecos o varias partes "
            "y cualquier forma; seleccione una entidad si la capa tiene varias).</li>"
            "<li>Indique la separación entre laterales, el emisor y los criterios, y pulse "
            "<b>Buscar trazado</b>. Se prueban varias direcciones de laterales y se ordenan de "
            "mejor a peor.</li>"
            "<li>Elija una alternativa en la tabla (se dibuja en el mapa) y pulse "
            "<b>Aplicar y calcular</b>: se crean las capas del trazado y se calcula cada subunidad.</li></ol>"
            "<p>La capa debe estar en un sistema de coordenadas proyectado en metros (UTM).</p>")
        derecha = QSplitter(Qt.Orientation.Vertical)
        derecha.addWidget(self.tabla)
        derecha.addWidget(self.texto)
        derecha.setSizes([230, 520])

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(desplazable)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)

        botones = QDialogButtonBox()
        self.boton_buscar = QPushButton("Buscar trazado")
        self.boton_buscar.setDefault(True)
        self.boton_aplicar = QPushButton("Aplicar y calcular")
        self.boton_aplicar.setEnabled(False)
        botones.addButton(self.boton_buscar, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(self.boton_aplicar, QDialogButtonBox.ButtonRole.ActionRole)
        botones.addButton(QPushButton("Cerrar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.rejected.connect(self.reject)
        self.boton_buscar.clicked.connect(self.buscar)
        self.boton_aplicar.clicked.connect(self.aplicar)

        principal = QVBoxLayout(self)
        principal.addWidget(divisor)
        principal.addWidget(botones)
        self._actualizar_alcance()

    # ---------------------------------------------------------------- interfaz

    def _grupo_terreno(self):
        grupo = QGroupBox("1. Terreno")
        formulario = QFormLayout(grupo)
        self.edit_nombre = QLineEdit("Parcela")
        self.edit_nombre.setToolTip("Las subunidades se llaman «nombre 1», «nombre 2»…")
        formulario.addRow("Nombre:", self.edit_nombre)
        self.combo_terreno = _combo_capas(Qgis.LayerFilter.PolygonLayer)
        formulario.addRow("Capa del terreno:", self.combo_terreno)
        self.combo_dem = _combo_capas(Qgis.LayerFilter.RasterLayer, "Sin DEM (terreno plano)")
        formulario.addRow("DEM:", self.combo_dem)
        self.combo_fuente = _combo_capas(Qgis.LayerFilter.PointLayer, "Sin fuente")
        self.combo_fuente.setToolTip("Punto de la fuente de agua o del cabezal: la válvula de cada "
                                     "subunidad se coloca en el extremo del portalateral más cercano a él.")
        self.combo_fuente.layerChanged.connect(self._fuente_cambiada)
        formulario.addRow("Fuente de agua (opcional):", self.combo_fuente)
        return grupo

    def _grupo_trazado(self):
        grupo = QGroupBox("2. Trazado")
        formulario = QFormLayout(grupo)
        self.spin_separacion = spin(0.2, 20, 1.5, 0.1, sufijo="m")
        formulario.addRow("Separación entre laterales:", self.spin_separacion)
        self.spin_margen = spin(0, 20, 0.5, 0.1, sufijo="m")
        self.spin_margen.setToolTip("Distancia libre entre el extremo de cada lateral y el borde del terreno.")
        formulario.addRow("Margen al borde:", self.spin_margen)
        self.spin_longitud_min = spin(0.5, 100, 3.0, 0.5, sufijo="m")
        self.spin_longitud_min.setToolTip("Un lateral más corto no se traza.")
        formulario.addRow("Longitud mínima de lateral:", self.spin_longitud_min)
        self.combo_lados = QComboBox()
        self.combo_lados.addItem("A ambos lados del portalateral", LADOS_AMBOS)
        self.combo_lados.addItem("A un solo lado (portalateral en el borde)", LADOS_UNO)
        formulario.addRow("Laterales:", self.combo_lados)

        self.combo_alcance = QComboBox()
        self.combo_alcance.addItem("Calcular con la hidráulica", ALCANCE_HIDRAULICO)
        self.combo_alcance.addItem("Fija", ALCANCE_FIJO)
        self.combo_alcance.setToolTip(
            "Longitud máxima de un lateral desde su portalateral. «Calcular» busca la mayor longitud "
            "que cumple la variación de caudal (el 55 % de la admisible de la subunidad, según la "
            "pendiente del DEM en cada dirección).")
        self.combo_alcance.currentIndexChanged.connect(self._actualizar_alcance)
        formulario.addRow("Longitud máxima de lateral:", self.combo_alcance)
        self.spin_alcance = spin(5, 1000, 80, 5, decimales=1, sufijo="m")
        formulario.addRow("Longitud fija:", self.spin_alcance)

        self.spin_caudal_max = spin(0, 10000, 0, 1, decimales=1, sufijo="m³/h")
        self.spin_caudal_max.setSpecialValueText("sin límite")
        self.spin_caudal_max.setToolTip("Caudal máximo que puede tener una subunidad (una válvula): los "
                                        "portalaterales se parten en trozos de caudal parecido.")
        formulario.addRow("Caudal máximo por subunidad:", self.spin_caudal_max)
        self.spin_laterales_min = QSpinBox()
        self.spin_laterales_min.setRange(1, 200)
        self.spin_laterales_min.setValue(3)
        self.spin_laterales_min.setToolTip("Una zona con menos laterales no vale una válvula y queda sin regar.")
        formulario.addRow("Laterales mínimos por subunidad:", self.spin_laterales_min)
        self.combo_entrada = QComboBox()
        self.combo_entrada.addItem("En el centro del portalateral", ENTRADA_CENTRO)
        self.combo_entrada.addItem("Al inicio (extremo más cercano a la fuente)", ENTRADA_INICIO)
        formulario.addRow("Entrada (válvula):", self.combo_entrada)
        self.check_curvas = QCheckBox("Probar también laterales siguiendo las curvas de nivel")
        self.check_curvas.setChecked(True)
        formulario.addRow(self.check_curvas)
        self.check_emisores = QCheckBox("Crear la capa de emisores (puede ser pesada)")
        formulario.addRow(self.check_emisores)
        return grupo

    def _grupo_portalateral(self):
        grupo = QGroupBox("Portalaterales")
        formulario = QFormLayout(grupo)
        self.combo_tuberia_porta = ComboTuberiaPortalateral(self.tuberias_portalateral)
        formulario.addRow("Tubería:", self.combo_tuberia_porta)
        self.combo_diametros = ComboDiametros()
        formulario.addRow("Diámetros:", self.combo_diametros)
        return grupo

    def _actualizar_alcance(self):
        self.spin_alcance.setEnabled(self.combo_alcance.currentData() == ALCANCE_FIJO)

    def _fuente_cambiada(self, capa):
        self.combo_entrada.setCurrentIndex(self.combo_entrada.findData(
            ENTRADA_INICIO if capa is not None else ENTRADA_CENTRO))

    def nombre(self):
        return self.edit_nombre.text().strip() or "Parcela"

    # ------------------------------------------------------------- acciones

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

    def buscar(self):
        resultado = self._ejecutar(self._buscar)
        if resultado is None:
            return
        self.trazados, self.contexto = resultado
        self.tabla.setRowCount(len(self.trazados))
        for fila, t in enumerate(self.trazados):
            valores = [
                str(fila + 1), f"{t.azimut_laterales_grados:.0f}°", str(t.numero_subunidades),
                f"{t.longitud_laterales_m:,.0f}", f"{t.longitud_portalaterales_m:,.0f}",
                f"{t.fraccion_sin_cubrir:.1%}", f"{t.orientacion.pendiente:.1%}", f"{t.puntuacion:,.0f}"]
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if columna:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if fila == 0:
                    item.setBackground(QBrush(QColor(46, 125, 50, 40)))
                self.tabla.setItem(fila, columna, item)
        self.boton_aplicar.setEnabled(bool(self.trazados))
        if self.trazados:
            self.tabla.selectRow(0)
        else:
            self.texto.setHtml("<p>No se pudo trazar ninguna subunidad. Reduzca los laterales mínimos o "
                               "la longitud mínima, o revise que el terreno sea suficientemente grande.</p>")

    def _buscar(self):
        from ..integracion import trazado_mapa as tm
        from ..integracion.perfil_terreno import entidad_unica
        from ..integracion.subunidad_mapa import geometria_en, verificar_crs_metrico

        capa = self.combo_terreno.currentLayer()
        if capa is None:
            raise ValueError("Elija la capa del terreno.")
        crs = capa.crs()
        verificar_crs_metrico(crs, capa.name())
        geometria = geometria_en(capa, entidad_unica(capa), crs)
        anillos = tm.anillos_de_geometria(geometria)

        grupo, criterios = self.grupo_laterales, self.grupo_criterios.criterios()
        e, d1 = grupo.spin_espaciamiento.value(), grupo.spin_primer.value()
        avisos = []

        dem = self.combo_dem.currentLayer()
        gradiente = None
        if dem is not None:
            gradiente = tm.gradiente_del_terreno(geometria, dem, crs)
            if gradiente is None:
                avisos.append("El DEM no cubre el terreno: se trazó como si fuera plano.")

        if self.combo_alcance.currentData() == ALCANCE_FIJO:
            def alcance(_pendiente):
                return self.spin_alcance.value()
        else:
            alcance = tm.alcance_hidraulico(
                grupo.tuberia(), grupo.emisor(), e, d1, criterios.variacion_caudal_max,
                self.grupo_criterios.metodo(), criterios.presion_entrada_max_m)
        orientaciones = tm.construir_orientaciones(
            anillos, gradiente, alcance, usar_curvas_de_nivel=self.check_curvas.isChecked())

        caudal_max = self.spin_caudal_max.value() * 1000 or None  # m³/h → L/h
        params = ParametrosTrazado(
            separacion_m=self.spin_separacion.value(), margen_m=self.spin_margen.value(),
            longitud_min_m=self.spin_longitud_min.value(), lados=self.combo_lados.currentData(),
            caudal_max_lh=caudal_max, laterales_min=self.spin_laterales_min.value(),
            caudal_lateral=tm.funcion_caudal(grupo.emisor(), e, d1))
        capa_fuente = self.combo_fuente.currentLayer()
        fuente = tm.punto_de_entidad(capa_fuente, crs) if capa_fuente is not None else None
        if fuente is None and self.combo_entrada.currentData() == ENTRADA_INICIO:
            avisos.append("Sin fuente elegida, el inicio de cada portalateral queda en el extremo sur "
                          "de su recta, según la dirección de los laterales.")

        trazados = buscar_trazados(anillos, params, orientaciones, fuente=fuente)
        return trazados, {"crs": crs, "geometria": geometria, "params": params, "avisos": avisos,
                          "gradiente": gradiente, "fuente": fuente}

    def _seleccion_cambiada(self):
        fila = self._fila()
        if fila is None:
            return
        from ..integracion import trazado_mapa as tm
        trazado = self.trazados[fila]
        self._ejecutar(lambda: tm.vista_previa(trazado, self.contexto["crs"],
                                               f"RiegoLibre · Vista previa del trazado · {self.nombre()}"))
        self._resumen_trazado(trazado)

    def _fila(self):
        filas = self.tabla.selectionModel().selectedRows()
        return filas[0].row() if filas and filas[0].row() < len(self.trazados) else None

    def _resumen_trazado(self, t):
        from ..integracion import trazado_mapa as tm
        grupo = self.grupo_laterales
        caudales = [s.caudal / 3600 for s in t.subunidades]  # L/s
        emisores = tm.cantidad_de_emisores(t, grupo.spin_espaciamiento.value(), grupo.spin_primer.value())
        avisos = list(self.contexto["avisos"])
        if t.fraccion_sin_cubrir > 0.05:
            avisos.append(f"Queda sin regar el {t.fraccion_sin_cubrir:.1%} del terreno (zonas muy angostas, "
                          "huecos o subunidades con menos laterales que el mínimo).")
        if not t.subunidades:
            avisos.append("Este trazado no tiene subunidades.")
        filas = [
            ("Dirección de los laterales", f"azimut {t.azimut_laterales_grados:.0f}° "
                                           f"(pendiente a lo largo de ellos: {t.orientacion.pendiente:.1%})"),
            ("Alcance máximo de un lateral", f"{t.orientacion.longitud_max_m:.0f} m desde el portalateral"),
            ("Terreno", f"{t.area_terreno_m2 / 10000:.3f} ha"),
            ("Subunidades", f"<b>{t.numero_subunidades}</b>"),
            ("Laterales", f"{sum(len(s.laterales) for s in t.subunidades):,} · {t.longitud_laterales_m:,.0f} m"),
            ("Emisores (aprox.)", f"{emisores:,}"),
            ("Portalaterales", f"{t.longitud_portalaterales_m:,.0f} m"),
            ("Caudal por subunidad", f"{min(caudales):.2f} – {max(caudales):.2f} L/s" if caudales else "—"),
            ("Terreno sin regar", f"{t.fraccion_sin_cubrir:.1%}"),
        ]
        self.texto.setHtml("<h3>Trazado propuesto</h3>" + html_tabla(filas) + html_avisos(avisos)
                           + "<p>Pulse <b>Aplicar y calcular</b> para crear las capas y calcular cada subunidad.</p>")

    def aplicar(self):
        fila = self._fila()
        if fila is None:
            QMessageBox.information(self, "RiegoLibre", "Elija un trazado de la tabla.")
            return
        informe = self._ejecutar(lambda: self._aplicar(self.trazados[fila]))
        if informe is not None:
            self.texto.setHtml(informe)

    def _aplicar(self, trazado):
        from ..integracion import trazado_mapa as tm
        from ..integracion.calculo_subunidad import ConfigCalculo, calcular_subunidad
        from ..integracion.subunidad_mapa import reemplazar_grupo

        crs, nombre = self.contexto["crs"], self.nombre()
        grupo, criterios = self.grupo_laterales, self.grupo_criterios.criterios()
        proyecto = QgsProject.instance()

        eliminar_grupos(re.escape(f"RiegoLibre · Vista previa del trazado · {nombre}"))
        eliminar_grupos(rf"RiegoLibre · {re.escape(nombre)} \d+")
        laterales, portalaterales, bloques, laterales_de, portas, geometrias_bloque = tm.capas_trazado(
            trazado, crs, nombre)
        capas = [portalaterales, bloques, laterales]
        if self.check_emisores.isChecked():
            capas.insert(0, tm.capa_emisores(trazado, crs, nombre, grupo.spin_espaciamiento.value(),
                                             grupo.spin_primer.value()))
        reemplazar_grupo(f"Trazado · {nombre}", capas)

        config = ConfigCalculo(
            tuberia_lateral=grupo.tuberia(), emisor=grupo.emisor(),
            espaciamiento_m=grupo.spin_espaciamiento.value(), primer_emisor_m=grupo.spin_primer.value(),
            metodo=self.grupo_criterios.metodo(), tuberias_portalateral=self.tuberias_portalateral,
            criterios=criterios, entrada=self.combo_entrada.currentData(),
            capa_dem=self.combo_dem.currentLayer(), tuberia_portalateral=self.combo_tuberia_porta.tuberia(),
            presion_conocida=self.grupo_criterios.presion_conocida(), diametros_max=self.combo_diametros.maximo())

        filas, fallos, total = [], [], len(trazado.subunidades)
        for i, s in enumerate(trazado.subunidades, 1):
            self.texto.setHtml(f"<p>Calculando la subunidad {i} de {total}…</p>")
            QApplication.processEvents()
            nombre_s = f"{nombre} {s.numero}"
            try:
                r = calcular_subunidad(nombre_s, crs, portas[s.numero], geometrias_bloque[s.numero],
                                       laterales_de[s.numero], config, list(self.contexto["avisos"]))
            except (ValueError, PresionInsuficiente) as e:
                fallos.append(f"{nombre_s}: {e}")
                continue
            res = r.diseno.resultado
            motivos = incumplimientos(res, criterios, r.diseno.tuberia)
            filas.append((nombre_s, len(s.laterales), res.caudal_total_lh / 3600, res.presion_entrada_m,
                          r.diseno.tuberia.nombre, res.variacion_caudal, motivos, r.area_m2))
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
        return self._informe(trazado, filas, fallos)

    def _informe(self, trazado, filas, fallos):
        tabla = ["<table cellpadding='4' border='0'><tr><th align='left'>Subunidad</th><th>Laterales</th>"
                 "<th>Área (ha)</th><th>Caudal (L/s)</th><th>Presión en la válvula (m)</th>"
                 "<th align='left'>Portalateral</th><th>Variación de caudal</th><th align='left'>Resultado</th></tr>"]
        cumplen = 0
        for nombre, laterales, caudal, presion, tuberia, variacion, motivos, area in filas:
            cumplen += not motivos
            tabla.append(
                f"<tr><td>{nombre}</td><td align='right'>{laterales}</td><td align='right'>{area / 10000:.3f}</td>"
                f"<td align='right'>{caudal:.2f}</td><td align='right'>{presion:.1f}</td><td>{tuberia}</td>"
                f"<td align='right'>{variacion:.1%}</td><td>{html_estado(not motivos)}"
                f"{'' if not motivos else ' ' + '; '.join(motivos)}</td></tr>")
        tabla.append("</table>")
        avisos = list(self.contexto["avisos"]) + fallos
        mayor = max((f[3] for f in filas), default=0.0)
        resumen = html_tabla([
            ("Subunidades calculadas", f"{len(filas)} de {trazado.numero_subunidades} · cumplen {cumplen}"),
            ("Presión máxima en una válvula", f"{mayor:.1f} m"),
            ("Caudal total", f"{sum(f[2] for f in filas):.2f} L/s"),
        ])
        return ("<h3>Trazado aplicado</h3>" + resumen + "".join(tabla) + html_avisos(avisos)
                + "<p>Las capas del trazado están en el grupo <i>Trazado · " + self.nombre() + "</i> y los "
                "resultados de cada subunidad en <i>RiegoLibre · " + self.nombre() + " n</i>. Los "
                "laterales se pueden editar y recalcular con <i>Diseño de subunidad en el mapa</i>. "
                "Siguiente paso: <i>Red principal y bomba</i>.</p>")
