# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Bloque de goteo de un lote (como el «Tape Irrigation Block» de IRRICAD) o del proyecto entero.

Los campos son los de `GOTEO_POR_OMISION` del servidor MCP. Para un lote se muestran los valores que valen
para él (los del proyecto, con lo propio del lote encima) y al aceptar se guardan en el lote solo los que
difieren de los del proyecto. Con «Usar también como valores del proyecto» se guardan en `goteo` y valen para
todos los lotes que no tengan los suyos.
"""

from typing import Dict, Optional

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from mcp_riegolibre import motor

AUTOMATICA = "Selección automática"
PORTALATERAL = [("inicio", "Al inicio de los laterales"), ("final", "Al final"), ("centro", "Al centro"),
                ("distancia", "A una distancia del inicio"), ("alto", "En el lado alto"), ("bajo", "En el lado bajo")]
VALVULA = [("auto", "Automática (cerca de la fuente)"), ("alto", "En el extremo alto"), ("bajo", "En el extremo bajo"),
           ("inicio", "Al inicio del portalateral"), ("final", "Al final"), ("centro", "Al centro"),
           ("porcentaje", "A un porcentaje del portalateral")]
SUBDIVISION = [("", "Sin subdividir"), ("caudal_max_m3h", "Por caudal máximo (m³/h)"),
               ("area_max_ha", "Por área máxima (ha)"), ("numero", "En un número de partes")]


def _caja(minimo, maximo, decimales=2, sufijo="", paso=0.1):
    caja = QDoubleSpinBox()
    caja.setRange(minimo, maximo)
    caja.setDecimals(decimales)
    caja.setSingleStep(paso)
    if sufijo:
        caja.setSuffix(sufijo)
    return caja


def _combo_nombres(nombres, automatica=False):
    combo = QComboBox()
    combo.setEditable(True)
    combo.setMinimumContentsLength(34)
    if automatica:
        combo.addItem(AUTOMATICA)
    combo.addItems(nombres)
    return combo


def _poner_texto(combo: QComboBox, texto: Optional[str]):
    texto = texto or ""
    indice = combo.findText(texto)
    if indice >= 0:
        combo.setCurrentIndex(indice)
    else:
        combo.setEditText(texto)


def _combo_opciones(opciones):
    combo = QComboBox()
    for clave, texto in opciones:
        combo.addItem(texto, clave)
    return combo


def _elegir(combo: QComboBox, clave):
    indice = combo.findData(clave)
    combo.setCurrentIndex(max(0, indice))


def _opcional(caja, valor_inicial, texto="automático"):
    """(casilla, fila): la casilla marcada deja el valor en automático (None)."""
    casilla = QCheckBox(texto)
    casilla.toggled.connect(lambda marcada: caja.setEnabled(not marcada))
    fila = QHBoxLayout()
    fila.addWidget(caja, 1)
    fila.addWidget(casilla)
    casilla.setChecked(valor_inicial is None)
    caja.setEnabled(valor_inicial is not None)
    if valor_inicial is not None:
        caja.setValue(float(valor_inicial))
    return casilla, fila


class DialogoBloque(QDialog):
    """Con `indice` edita ese lote; sin él, los valores del bloque de goteo de todo el proyecto."""

    def __init__(self, datos: dict, indice: Optional[int] = None, catalogo: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.datos, self.indice = datos, indice
        self.lote = datos["lotes"][indice] if indice is not None else None
        self.goteo = dict(datos.get("goteo") or {})
        self.catalogo = catalogo if catalogo is not None else motor.catalogo()
        try:
            self.valores = motor._config_goteo(self.goteo, self.lote or {})
        except ValueError:
            self.valores = dict(motor.GOTEO_POR_OMISION)
        titulo = f"Bloque de goteo · {self.lote.get('nombre')}" if self.lote else "Bloque de goteo del proyecto"
        self.setWindowTitle(titulo)

        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._pestana_laterales(), "Laterales")
        self.pestanas.addTab(self._pestana_bloque(), "Bloque")
        self.pestanas.addTab(self._pestana_criterios(), "Criterios")
        if self.lote is not None:
            self.pestanas.addTab(self._pestana_area(), "Área")

        self.casilla_proyecto = QCheckBox("Usar también como valores del proyecto (para los lotes nuevos y los "
                                          "que no tienen los suyos)")
        sin_emisor = not (self.goteo.get("emisor") or self.goteo.get("cinta"))
        self.casilla_proyecto.setChecked(sin_emisor)
        self.casilla_proyecto.setVisible(self.lote is not None)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        principal = QVBoxLayout(self)
        principal.addWidget(self.pestanas)
        principal.addWidget(self.casilla_proyecto)
        principal.addWidget(botones)

    # ------------------------------------------------------------ pestañas

    def _pestana_laterales(self):
        v = self.valores
        c = self.catalogo
        self.radio_emisor = QRadioButton("Emisor y manguera")
        self.radio_cinta = QRadioButton("Cinta o lateral con gotero integrado (de la base de datos)")
        self.combo_emisor = _combo_nombres([e["nombre"] for e in c["emisores"]])
        self.combo_lateral = _combo_nombres([t["nombre"] for t in c["tuberias_lateral"]])
        self.combo_cinta = _combo_nombres([x["nombre"] for x in c["cintas"]])
        _poner_texto(self.combo_emisor, v["emisor"])
        _poner_texto(self.combo_lateral, v["tuberia_lateral"])
        cinta = v["cinta"] if isinstance(v["cinta"], str) else ""
        _poner_texto(self.combo_cinta, cinta)
        (self.radio_cinta if cinta else self.radio_emisor).setChecked(True)
        self.radio_emisor.toggled.connect(self._tipo_lateral)

        self.caja_espaciamiento = _caja(0.05, 10, 2, " m", 0.05)
        self.caja_espaciamiento.setValue(float(v["espaciamiento_emisores_m"] or 0.4))
        self.caja_primero = _caja(0, 10, 2, " m", 0.05)
        self.casilla_primero, fila_primero = _opcional(self.caja_primero, v["primer_emisor_m"],
                                                       "medio espaciamiento")
        tipo = QGroupBox("Lateral")
        f = QFormLayout(tipo)
        f.addRow(self.radio_emisor)
        f.addRow("Emisor:", self.combo_emisor)
        f.addRow("Manguera:", self.combo_lateral)
        f.addRow(self.radio_cinta)
        f.addRow("Cinta:", self.combo_cinta)
        f.addRow("Espaciamiento entre emisores:", self.caja_espaciamiento)
        f.addRow("Primer emisor:", fila_primero)

        self.caja_hileras = _caja(0.1, 50, 2, " m", 0.1)
        self.caja_hileras.setValue(float(v["separacion_hileras_m"] or 3.0))
        self.caja_por_hilera = QSpinBox()
        self.caja_por_hilera.setRange(1, 4)
        self.caja_por_hilera.setValue(int(v["laterales_por_hilera"]))
        self.caja_en_hilera = _caja(0, 5, 2, " m", 0.1)
        self.caja_en_hilera.setValue(float(v["separacion_en_hilera_m"]))
        hileras = QGroupBox("Hileras")
        f = QFormLayout(hileras)
        f.addRow("Separación entre hileras:", self.caja_hileras)
        f.addRow("Laterales por hilera:", self.caja_por_hilera)
        f.addRow("Separación dentro de la hilera:", self.caja_en_hilera)

        self.caja_azimut = _caja(0, 359.9, 1, " °", 1)
        self.casilla_azimut, fila_azimut = _opcional(self.caja_azimut, v["azimut_laterales_deg"],
                                                     "automática (el programa sugiere)")
        direccion = QGroupBox("Dirección de los laterales")
        f = QFormLayout(direccion)
        f.addRow("Azimut (desde el norte, horario):", fila_azimut)

        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        for grupo in (tipo, hileras, direccion):
            capa.addWidget(grupo)
        capa.addStretch(1)
        self._tipo_lateral()
        return pagina

    def _tipo_lateral(self):
        emisor = self.radio_emisor.isChecked()
        self.combo_emisor.setEnabled(emisor)
        self.combo_lateral.setEnabled(emisor)
        self.combo_cinta.setEnabled(not emisor)

    def _pestana_bloque(self):
        v = self.valores
        self.caja_cabecera = _caja(0, 50, 2, " m", 0.1)
        self.caja_cabecera.setValue(float(v["cabecera_m"]))
        self.caja_costados = _caja(0, 50, 2, " m", 0.1)
        self.casilla_costados, fila_costados = _opcional(self.caja_costados, v["costados_m"],
                                                         "media separación entre hileras")
        bordes = QGroupBox("Bordes")
        f = QFormLayout(bordes)
        f.addRow("Cabecera:", self.caja_cabecera)
        f.addRow("Costados:", fila_costados)

        self.combo_porta = _combo_opciones(PORTALATERAL)
        _elegir(self.combo_porta, v["portalateral"])
        self.caja_distancia = _caja(0, 5000, 1, " m", 1)
        self.caja_distancia.setValue(float(v["distancia_portalateral_m"]))
        self.combo_tuberia_porta = _combo_nombres([t["nombre"] for t in self.catalogo["tuberias_portalateral"]], True)
        _poner_texto(self.combo_tuberia_porta, v["tuberia_portalateral"] or AUTOMATICA)
        self.caja_diametros = QSpinBox()
        self.caja_diametros.setRange(1, 3)
        self.caja_diametros.setValue(int(v["diametros_max_portalateral"]))
        self.caja_diametros.setToolTip("1: un solo diámetro; 2 o 3: telescópico")
        porta = QGroupBox("Portalateral")
        f = QFormLayout(porta)
        f.addRow("Posición:", self.combo_porta)
        f.addRow("Distancia:", self.caja_distancia)
        f.addRow("Tubería:", self.combo_tuberia_porta)
        f.addRow("Diámetros, máximo:", self.caja_diametros)
        self.combo_porta.currentIndexChanged.connect(
            lambda: self.caja_distancia.setEnabled(self.combo_porta.currentData() == "distancia"))
        self.caja_distancia.setEnabled(self.combo_porta.currentData() == "distancia")

        self.combo_valvula = _combo_opciones(VALVULA)
        _elegir(self.combo_valvula, v["valvula"])
        self.caja_porcentaje = _caja(0, 100, 1, " %", 5)
        self.caja_porcentaje.setValue(float(v["porcentaje_valvula"]))
        valvula = QGroupBox("Válvula")
        f = QFormLayout(valvula)
        f.addRow("Posición:", self.combo_valvula)
        f.addRow("Porcentaje:", self.caja_porcentaje)
        self.combo_valvula.currentIndexChanged.connect(
            lambda: self.caja_porcentaje.setEnabled(self.combo_valvula.currentData() == "porcentaje"))
        self.caja_porcentaje.setEnabled(self.combo_valvula.currentData() == "porcentaje")

        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        for grupo in (bordes, porta, valvula):
            capa.addWidget(grupo)
        capa.addStretch(1)
        return pagina

    def _pestana_criterios(self):
        v = self.valores
        self.caja_variacion = _caja(1, 50, 1, " %", 1)
        self.caja_variacion.setValue(float(v["variacion_caudal_max_pct"]))
        self.caja_velocidad = _caja(0.1, 5, 2, " m/s", 0.1)
        self.caja_velocidad.setValue(float(v["velocidad_max_portalateral_ms"]))
        self.caja_presion_max = _caja(1, 100, 1, " m", 1)
        self.casilla_presion_max, fila_presion = _opcional(self.caja_presion_max, v["presion_entrada_max_m"],
                                                           "sin límite")
        self.combo_metodo = _combo_opciones([("darcy", "Darcy-Weisbach"), ("hazen", "Hazen-Williams")])
        _elegir(self.combo_metodo, v["metodo"])
        criterios = QGroupBox("Criterios de diseño")
        f = QFormLayout(criterios)
        f.addRow("Variación de caudal máxima:", self.caja_variacion)
        f.addRow("Velocidad máxima en el portalateral:", self.caja_velocidad)
        f.addRow("Presión máxima a la entrada:", fila_presion)
        f.addRow("Pérdida de carga:", self.combo_metodo)

        sub = v["subdivision"] or {}
        self.combo_subdivision = _combo_opciones(SUBDIVISION)
        criterio = next((c for c, _ in SUBDIVISION[1:] if c in sub), "")
        _elegir(self.combo_subdivision, criterio)
        self.caja_valor_sub = _caja(0.01, 100000, 2, "", 1)
        self.caja_valor_sub.setValue(float(sub.get(criterio, 1) if criterio else 1))
        self.caja_largo_sub = _caja(1, 5000, 1, " m", 10)
        self.casilla_largo_sub, fila_largo = _opcional(self.caja_largo_sub, sub.get("longitud_max_lateral_m"),
                                                       "sin límite")
        subdivision = QGroupBox("Subdivisión del lote en subunidades")
        f = QFormLayout(subdivision)
        f.addRow("Criterio:", self.combo_subdivision)
        f.addRow("Valor:", self.caja_valor_sub)
        f.addRow("Lateral más largo:", fila_largo)
        self.combo_subdivision.currentIndexChanged.connect(self._subdivision)
        self._subdivision()

        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        capa.addWidget(criterios)
        capa.addWidget(subdivision)
        capa.addStretch(1)
        return pagina

    def _subdivision(self):
        activa = bool(self.combo_subdivision.currentData())
        self.caja_valor_sub.setEnabled(activa)
        self.casilla_largo_sub.setEnabled(activa)
        self.caja_largo_sub.setEnabled(activa and not self.casilla_largo_sub.isChecked())
        if self.combo_subdivision.currentData() == "numero":
            self.caja_valor_sub.setDecimals(0)
            self.caja_valor_sub.setMinimum(2)

    def _pestana_area(self):
        self.edit_nombre = QLineEdit(str(self.lote.get("nombre", "")))
        turnos = max(1, int((self.datos.get("red") or {}).get("turnos", 1)))
        fijos = (self.datos.get("red") or {}).get("turnos_fijos") or {}
        self.combo_turno = QComboBox()
        self.combo_turno.addItem("Automático (reparte por caudal)", 0)
        for t in range(1, turnos + 1):
            self.combo_turno.addItem(f"Turno {t}", t)
        _elegir(self.combo_turno, int(fijos.get(str(self.lote.get("nombre")), 0)))
        pagina = QWidget()
        f = QFormLayout(pagina)
        f.addRow("Nombre:", self.edit_nombre)
        f.addRow("Turno de riego:", self.combo_turno)
        f.addRow(QLabel(f"El proyecto tiene {turnos} turno(s); se cambia en «Turnos de riego…»."))
        return pagina

    # ------------------------------------------------------------ resultado

    def valores_goteo(self) -> Dict[str, object]:
        """Todos los campos de `GOTEO_POR_OMISION` como quedaron en el cuadro."""
        cinta = self.radio_cinta.isChecked()
        porta = self.combo_tuberia_porta.currentText().strip()
        criterio = self.combo_subdivision.currentData()
        subdivision = None
        if criterio:
            valor = self.caja_valor_sub.value()
            subdivision = {criterio: int(valor) if criterio == "numero" else valor}
            if not self.casilla_largo_sub.isChecked():
                subdivision["longitud_max_lateral_m"] = self.caja_largo_sub.value()

        def opcional(casilla, caja):
            return None if casilla.isChecked() else caja.value()

        return {
            "emisor": None if cinta else (self.combo_emisor.currentText().strip() or None),
            "tuberia_lateral": None if cinta else (self.combo_lateral.currentText().strip() or None),
            "cinta": (self.combo_cinta.currentText().strip() or None) if cinta else "",
            "espaciamiento_emisores_m": self.caja_espaciamiento.value(),
            "primer_emisor_m": opcional(self.casilla_primero, self.caja_primero),
            "separacion_hileras_m": self.caja_hileras.value(),
            "laterales_por_hilera": self.caja_por_hilera.value(),
            "separacion_en_hilera_m": self.caja_en_hilera.value(),
            "cabecera_m": self.caja_cabecera.value(),
            "costados_m": opcional(self.casilla_costados, self.caja_costados),
            "azimut_laterales_deg": opcional(self.casilla_azimut, self.caja_azimut),
            "portalateral": self.combo_porta.currentData(),
            "distancia_portalateral_m": self.caja_distancia.value(),
            "valvula": self.combo_valvula.currentData(),
            "porcentaje_valvula": self.caja_porcentaje.value(),
            "variacion_caudal_max_pct": self.caja_variacion.value(),
            "velocidad_max_portalateral_ms": self.caja_velocidad.value(),
            "presion_entrada_max_m": opcional(self.casilla_presion_max, self.caja_presion_max),
            "diametros_max_portalateral": self.caja_diametros.value(),
            "tuberia_portalateral": None if porta in ("", AUTOMATICA) else porta,
            "metodo": self.combo_metodo.currentData(),
            "subdivision": subdivision,
        }

    def cambios(self):
        """(cambios del goteo del proyecto, cambios del lote) para `edicion.cambiar_goteo` y `cambiar_lote`.

        Un valor None quita la clave. En el proyecto se guardan solo los valores distintos de los por omisión;
        en el lote, solo los distintos de los del proyecto.
        """
        valores = self.valores_goteo()
        por_omision = dict(motor.GOTEO_POR_OMISION, cinta=None)
        goteo_cambios: Dict[str, object] = {}
        lote_cambios: Dict[str, object] = {}
        if self.lote is None or self.casilla_proyecto.isChecked():
            for clave, valor in valores.items():
                if clave == "cinta" and not valor:
                    valor = None
                goteo_cambios[clave] = None if valor == por_omision.get(clave) else valor
            if self.lote is not None:
                lote_cambios = {clave: None for clave in valores}
        else:
            proyecto = dict(por_omision)
            proyecto.update({k: v for k, v in self.goteo.items() if v is not None})
            for clave, valor in valores.items():
                if clave == "cinta" and not valor:
                    valor = "" if proyecto.get("cinta") else None
                lote_cambios[clave] = None if valor == proyecto.get(clave) else valor
        if self.lote is not None:
            lote_cambios["nombre"] = self.edit_nombre.text()
            lote_cambios["turno"] = self.combo_turno.currentData() or None
        return goteo_cambios, lote_cambios
