"""Diseño de una subunidad dibujada en el mapa: bloque, portalateral y laterales reales."""

from qgis.core import (Qgis, QgsFillSymbol, QgsProject, QgsSingleSymbolRenderer,
                       QgsVectorLayer)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QDialog,
                                 QDialogButtonBox, QFormLayout, QGroupBox,
                                 QLabel, QLineEdit, QMessageBox, QPushButton,
                                 QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ..nucleo import (Lateral, PresionInsuficiente, cargar_catalogo_emisores,
                      cargar_catalogo_tuberias, disenar_subunidad,
                      subunidad_desde_conexiones)
from ..nucleo.memoria import resumen_subunidad
from ..nucleo.tuberias import clave_economica
from .comunes import (ComboDiametros, ComboTuberiaPortalateral, GrupoCriterios,
                      GrupoLaterales, html_tabla, spin)
from .panel_resultados import PanelResultadosSubunidad

ENTRADA_INICIO, ENTRADA_CENTRO, ENTRADA_FINAL = "inicio", "centro", "final"
DIRECCION_PERPENDICULAR, DIRECCION_AZIMUT = "perpendicular", "azimut"


def _combo_capas(filtro, vacia=None):
    control = QgsMapLayerComboBox()
    control.setFilters(filtro)
    if vacia is not None:
        try:
            control.setAllowEmptyLayer(True, vacia)
        except TypeError:  # versiones de QGIS sin texto para la opción vacía
            control.setAllowEmptyLayer(True)
    return control


class DialogoMapa(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RiegoLibre · Diseño de subunidad en el mapa (goteo)")
        self.resize(1250, 800)

        self.tuberias_portalateral = sorted(cargar_catalogo_tuberias(uso="portalateral"),
                                            key=clave_economica)
        self.grupo_laterales = GrupoLaterales(cargar_catalogo_tuberias(uso="lateral"),
                                              cargar_catalogo_emisores(), "Laterales y emisores")
        self.grupo_criterios = GrupoCriterios()

        contenido = QWidget()
        izquierda = QVBoxLayout(contenido)
        izquierda.addWidget(self._grupo_geometria())
        izquierda.addWidget(self._grupo_generar())
        izquierda.addWidget(self._grupo_calculo())
        izquierda.addWidget(self.grupo_laterales)
        izquierda.addWidget(self.grupo_criterios)
        izquierda.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(contenido)
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setMinimumWidth(420)
        desplazable.setMaximumWidth(540)

        self.panel = PanelResultadosSubunidad(
            "<h3>Pasos</h3><ol>"
            "<li>Dibuje el <b>bloque</b> (polígono) y el <b>portalateral</b> (línea). Si no tiene "
            "capas, use <i>Crear capas para dibujar</i>. El primer vértice de la línea es su inicio.</li>"
            "<li>Pulse <b>Generar laterales</b>. Puede editar la capa generada: borrar, mover o "
            "alargar laterales.</li>"
            "<li>Elija emisor, tubería y DEM, y pulse <b>Calcular</b>. Los resultados se añaden "
            "al mapa en el grupo <i>RiegoLibre · nombre de la subunidad</i>.</li></ol>"
            "<p>Las capas deben estar en un sistema de coordenadas proyectado en metros (UTM).</p>")
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
        self._actualizar_direccion()

    # ---------------------------------------------------------------- interfaz

    def _grupo_geometria(self):
        grupo = QGroupBox("1. Bloque y portalateral")
        formulario = QFormLayout(grupo)
        self.edit_nombre = QLineEdit("Subunidad 1")
        formulario.addRow("Nombre de la subunidad:", self.edit_nombre)
        self.combo_bloque = _combo_capas(Qgis.LayerFilter.PolygonLayer)
        formulario.addRow("Capa del bloque:", self.combo_bloque)
        self.combo_portalateral = _combo_capas(Qgis.LayerFilter.LineLayer)
        formulario.addRow("Capa del portalateral:", self.combo_portalateral)
        nota = QLabel("De cada capa se usa la entidad seleccionada (o la única que tenga).")
        nota.setWordWrap(True)
        formulario.addRow(nota)
        boton = QPushButton("Crear capas para dibujar")
        boton.setToolTip("Crea capas temporales «Bloques» y «Portalaterales» en el SRC del proyecto "
                         "y activa la edición para dibujar el bloque.")
        boton.clicked.connect(self.crear_capas_de_dibujo)
        formulario.addRow(boton)
        return grupo

    def _grupo_generar(self):
        grupo = QGroupBox("2. Generar laterales")
        formulario = QFormLayout(grupo)
        self.spin_separacion = spin(0.2, 20, 1.5, 0.1, sufijo="m")
        formulario.addRow("Separación entre laterales:", self.spin_separacion)
        self.spin_primero = spin(0, 50, 0, 0.1, sufijo="m")
        self.spin_primero.setSpecialValueText("mitad de la separación")
        formulario.addRow("Distancia al primer lateral:", self.spin_primero)
        self.spin_margen = spin(0, 20, 0.5, 0.1, sufijo="m")
        self.spin_margen.setToolTip("Distancia libre entre el final de cada lateral y el borde del bloque.")
        formulario.addRow("Margen al borde del bloque:", self.spin_margen)
        self.spin_longitud_max = spin(0, 2000, 0, 5, decimales=1, sufijo="m")
        self.spin_longitud_max.setSpecialValueText("sin límite")
        formulario.addRow("Longitud máxima de laterales:", self.spin_longitud_max)
        self.combo_lados = QComboBox()
        self.combo_lados.addItem("A ambos lados", ("A", "B"))
        self.combo_lados.addItem("Solo a la izquierda (lado A)", ("A",))
        self.combo_lados.addItem("Solo a la derecha (lado B)", ("B",))
        self.combo_lados.setToolTip("Izquierda y derecha según el sentido en que se dibujó el portalateral.")
        formulario.addRow("Laterales:", self.combo_lados)
        self.combo_direccion = QComboBox()
        self.combo_direccion.addItem("Perpendiculares al portalateral", DIRECCION_PERPENDICULAR)
        self.combo_direccion.addItem("Con azimut fijo (hileras)", DIRECCION_AZIMUT)
        self.combo_direccion.currentIndexChanged.connect(self._actualizar_direccion)
        formulario.addRow("Dirección:", self.combo_direccion)
        self.spin_azimut = spin(0, 360, 90, 1, decimales=1, sufijo="°")
        self.spin_azimut.setToolTip("Azimut del lado A, medido desde el norte en sentido horario.")
        formulario.addRow("Azimut:", self.spin_azimut)
        boton = QPushButton("Generar laterales")
        boton.clicked.connect(self.generar_laterales)
        formulario.addRow(boton)
        return grupo

    def _grupo_calculo(self):
        grupo = QGroupBox("3. Cálculo hidráulico")
        formulario = QFormLayout(grupo)
        self.combo_laterales = _combo_capas(Qgis.LayerFilter.LineLayer)
        formulario.addRow("Capa de laterales:", self.combo_laterales)
        self.combo_dem = _combo_capas(Qgis.LayerFilter.RasterLayer, "Sin DEM (terreno plano)")
        formulario.addRow("DEM:", self.combo_dem)
        self.combo_entrada = QComboBox()
        self.combo_entrada.addItem("Al inicio del portalateral", ENTRADA_INICIO)
        self.combo_entrada.addItem("En el centro del portalateral", ENTRADA_CENTRO)
        self.combo_entrada.addItem("Al final del portalateral", ENTRADA_FINAL)
        formulario.addRow("Entrada (válvula):", self.combo_entrada)
        self.combo_tuberia_porta = ComboTuberiaPortalateral(self.tuberias_portalateral)
        formulario.addRow("Tubería del portalateral:", self.combo_tuberia_porta)
        self.combo_diametros = ComboDiametros()
        formulario.addRow("Diámetros:", self.combo_diametros)
        return grupo

    def _actualizar_direccion(self):
        self.spin_azimut.setEnabled(self.combo_direccion.currentData() == DIRECCION_AZIMUT)

    def _usar_tuberia(self, tuberia):
        self.combo_tuberia_porta.elegir(tuberia)
        self.calcular()

    def nombre(self):
        return self.edit_nombre.text().strip() or "Subunidad"

    # ------------------------------------------------------------- acciones

    def _ejecutar(self, funcion):
        """Ejecuta una acción mostrando el cursor de espera y los errores en un mensaje."""
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

    def crear_capas_de_dibujo(self):
        from ..integracion.subunidad_mapa import verificar_crs_metrico

        def crear():
            proyecto = QgsProject.instance()
            crs = proyecto.crs()
            if not crs.isValid() or crs.isGeographic():
                raise ValueError("El proyecto debe usar un SRC proyectado en metros (por ejemplo UTM) "
                                 "para dibujar el bloque. Cámbielo en Proyecto → Propiedades → SRC.")
            verificar_crs_metrico(crs, "del proyecto")
            bloques = QgsVectorLayer("Polygon?field=nombre:string(50)", "Bloques", "memory")
            lineas = QgsVectorLayer("LineString?field=nombre:string(50)", "Portalaterales", "memory")
            for capa in (bloques, lineas):
                capa.setCrs(crs)
            # Relleno semitransparente para que el bloque no tape el DEM en el mapa ni en el plano.
            bloques.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
                {"color": "80,170,80,50", "outline_color": "40,120,40", "outline_width": "0.6"})))
            proyecto.addMapLayers([bloques, lineas])
            self.combo_bloque.setLayer(bloques)
            self.combo_portalateral.setLayer(lineas)
            if self.iface is not None:
                self.iface.setActiveLayer(bloques)
                bloques.startEditing()
                self.iface.actionAddFeature().trigger()
            return bloques, lineas

        if self._ejecutar(crear):
            self.panel.texto.setHtml(
                "<p>Se crearon las capas temporales <b>Bloques</b> y <b>Portalaterales</b>.</p>"
                "<p>Dibuje el bloque en el mapa (clic para cada vértice, clic derecho para terminar). "
                "Luego seleccione la capa <i>Portalaterales</i>, active la edición y dibuje el "
                "portalateral empezando por el extremo donde irá la válvula. Guarde las ediciones.</p>"
                "<p>Son capas temporales: si quiere conservarlas, use <i>Exportar → Guardar "
                "objetos como…</i></p>")

    def _geometrias(self):
        from ..integracion.perfil_terreno import entidad_unica, linea_simple
        from ..integracion.subunidad_mapa import geometria_en, verificar_crs_metrico
        capa_porta = self.combo_portalateral.currentLayer()
        if capa_porta is None:
            raise ValueError("Elija la capa del portalateral.")
        crs = capa_porta.crs()
        verificar_crs_metrico(crs, capa_porta.name())
        portalateral = linea_simple(geometria_en(capa_porta, entidad_unica(capa_porta), crs))
        capa_bloque = self.combo_bloque.currentLayer()
        bloque = None
        if capa_bloque is not None:
            bloque = geometria_en(capa_bloque, entidad_unica(capa_bloque), crs)
        return crs, portalateral, bloque

    def generar_laterales(self):
        from ..integracion import subunidad_mapa as mapa

        def generar():
            crs, portalateral, bloque = self._geometrias()
            if bloque is None:
                raise ValueError("Elija la capa del bloque.")
            separacion = self.spin_separacion.value()
            azimut = (self.spin_azimut.value()
                      if self.combo_direccion.currentData() == DIRECCION_AZIMUT else None)
            laterales = mapa.generar_laterales(
                bloque, portalateral, separacion,
                distancia_primero_m=self.spin_primero.value() or None,
                margen_m=self.spin_margen.value(),
                longitud_max_m=self.spin_longitud_max.value() or None,
                lados=self.combo_lados.currentData(), azimut_grados=azimut)
            if not laterales:
                raise ValueError("No se generó ningún lateral: compruebe que el portalateral está "
                                 "dentro del bloque o sobre su borde.")
            nombre = f"Laterales generados · {self.nombre()}"
            proyecto = QgsProject.instance()
            for capa in proyecto.mapLayersByName(nombre):
                if capa.customProperty(mapa.PROPIEDAD) == "laterales":
                    proyecto.removeMapLayer(capa.id())
            capa = mapa.capa_laterales(laterales, crs, nombre)
            proyecto.addMapLayer(capa)
            self.combo_laterales.setLayer(capa)
            return laterales

        laterales = self._ejecutar(generar)
        if laterales:
            longitudes = [lat.longitud_m for lat in laterales]
            conexiones = len({lat.conexion for lat in laterales})
            self.panel.texto.setHtml(
                "<h3>Laterales generados</h3>" + html_tabla([
                    ("Laterales", f"{len(laterales)} en {conexiones} posiciones del portalateral"),
                    ("Longitud total", f"{sum(longitudes):,.1f} m"),
                    ("Longitud mín. / media / máx.",
                     f"{min(longitudes):.1f} / {sum(longitudes) / len(longitudes):.1f} / "
                     f"{max(longitudes):.1f} m"),
                ]) + "<p>Revise los laterales en el mapa (puede editarlos) y pulse <b>Calcular</b>.</p>")

    def calcular(self):
        from ..integracion import subunidad_mapa as mapa
        from ..integracion.memoria_mapa import guardar_resumen

        def calculo():
            crs, portalateral, bloque = self._geometrias()
            capa_laterales = self.combo_laterales.currentLayer()
            if capa_laterales is None:
                raise ValueError("Elija la capa de laterales (o genérelos en el paso 2).")
            laterales_mapa, avisos = mapa.leer_laterales(capa_laterales, portalateral, crs)

            grupo = self.grupo_laterales
            metodo = self.grupo_criterios.metodo()
            espaciamiento, primero = grupo.spin_espaciamiento.value(), grupo.spin_primer.value()

            def crear_lateral(longitud, perfil):
                if longitud < primero:
                    return None
                return Lateral.desde_longitud(grupo.tuberia(), grupo.emisor(), espaciamiento, longitud,
                                              distancia_primer_emisor_m=primero, perfil=perfil,
                                              metodo=metodo)

            modelo = mapa.construir_modelo(laterales_mapa, crear_lateral, portalateral, crs,
                                           capa_dem=self.combo_dem.currentLayer(),
                                           paso_perfil_m=max(espaciamiento, 1.0))
            if modelo.descartados:
                avisos.append(f"{len(modelo.descartados)} laterales son más cortos que la distancia "
                              "al primer emisor y no se calcularon.")
            if self.combo_dem.currentLayer() is None:
                avisos.append("Sin DEM: se calculó con el terreno plano.")

            entrada = {ENTRADA_INICIO: 0.0, ENTRADA_CENTRO: portalateral.length() / 2,
                       ENTRADA_FINAL: portalateral.length()}[self.combo_entrada.currentData()]

            def construir(tuberia, reducciones=()):
                return subunidad_desde_conexiones(tuberia, modelo.conexiones, entrada,
                                                  perfil=modelo.perfil_portalateral, metodo=metodo,
                                                  reducciones=reducciones)

            diseno = disenar_subunidad(construir, self.tuberias_portalateral,
                                       self.grupo_criterios.criterios(),
                                       tuberia_fija=self.combo_tuberia_porta.tuberia(),
                                       presion_entrada_m=self.grupo_criterios.presion_conocida(),
                                       diametros_max=self.combo_diametros.maximo())
            area = bloque.area() if bloque is not None else 0.0
            descartados = {id(lat) for lat in modelo.descartados}
            longitudes = [lat.longitud_m for lat in laterales_mapa if id(lat) not in descartados]
            capas = mapa.capas_resultado(diseno, modelo, portalateral, entrada, crs, self.nombre())
            guardar_resumen(capas[0], resumen_subunidad(
                self.nombre(), diseno, self.grupo_criterios.criterios(), metodo, area, longitudes,
                self.grupo_criterios.presion_conocida(), avisos))
            mapa.reemplazar_grupo(f"RiegoLibre · {self.nombre()}", capas)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
            return diseno, bloque, area, avisos

        datos = self._ejecutar(calculo)
        if datos is None:
            return
        diseno, bloque, area, avisos = datos
        texto_area = "bloque" if bloque is not None else "sin bloque"
        self.panel.mostrar(diseno, self.grupo_criterios.criterios(), self.grupo_laterales.tuberia(),
                           area, texto_area, avisos)
