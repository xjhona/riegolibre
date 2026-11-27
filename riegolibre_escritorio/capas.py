# Copyright (C) 2026 Jhonatan Chilet
# SPDX-License-Identifier: GPL-3.0-only
# RiegoLibre: software libre; ver los archivos LICENSE y NOTICE (autoría y condiciones adicionales).
"""Capas del dibujo y su estilo, como la barra de capas («Layer Bar») de IRRICAD. Sin Qt.

Las capas son fijas y siempre están, aunque vacías. Cada una tiene color, tipo de línea, grosor (en píxeles de
pantalla), si se ve y si se imprime; el proyecto guarda esos estilos.
"""

from typing import Dict, Optional

# nombre: (color, tipo de línea, grosor, descripción), de arriba abajo
CAPAS = {
    "TEXTO": ("#212121", "solida", 1.0, "Rótulos de los lotes y de la fuente"),
    "DIBUJO": ("#000000", "solida", 1.5, "Dibujo libre: polilíneas, líneas, polígonos, rectángulos, circunferencias y arcos (DRAWING)"),
    "FUENTE": ("#0277bd", "solida", 1.0, "Fuente de agua: bomba y cabezal"),
    "VÁLVULAS": ("#6a1b9a", "solida", 1.0, "Válvula de cada subunidad"),
    "RED_PRINCIPAL": ("#c62828", "solida", 4.0, "Red principal calculada y conectores de válvula (color por diámetro)"),
    "MATRIZ_DIBUJADA": ("#5d4037", "solida", 2.0, "Tubería matriz dibujada, un tramo entre cada par de nodos"),
    "NODOS_MATRIZ": ("#5d4037", "solida", 1.0, "Nodos (uniones) de la tubería matriz, como MAINLINE_JUNCTIONS"),
    "PORTALATERALES": ("#1565c0", "solida", 2.6, "Tubería portalateral de cada subunidad"),
    "LATERALES": ("#43a047", "solida", 0.8, "Laterales de goteo"),
    "LOTES": ("#424242", "solida", 1.2, "Áreas de riego (relleno con el color del turno)"),
    "DIBUJO_CAD": ("#78909c", "solida", 0.8, "Líneas de referencia importadas de un DXF (caminos, canales, linderos…)"),
    "CURVAS_NIVEL": ("#a1887f", "solida", 0.6, "Curvas de nivel del terreno (las maestras, más gruesas)"),
    "IMAGEN_SATELITAL": ("#9e9e9e", "solida", 1.0, "Imagen satelital de fondo (menú Terreno → Imagen satelital)"),
}
CAPAS_IMAGEN = {"IMAGEN_SATELITAL"}  # sin color ni línea: solo transparencia
TIPOS_LINEA = {"solida": "Sólida", "discontinua": "Discontinua", "punteada": "Punteada", "punto_raya": "Punto y raya"}


def estilos_por_omision() -> Dict[str, dict]:
    estilos = {nombre: {"color": c, "linea": l, "ancho": a, "visible": True, "imprimir": True}
               for nombre, (c, l, a, _) in CAPAS.items()}
    for nombre in CAPAS_IMAGEN:
        estilos[nombre]["transparencia"] = 0  # en %
    return estilos


def completar_estilos(estilos: Optional[dict]) -> Dict[str, dict]:
    """Estilos de todas las capas: los guardados encima de los por omisión (ignora capas y claves desconocidas)."""
    completos = estilos_por_omision()
    for nombre, estilo in (estilos or {}).items():
        if nombre in completos and isinstance(estilo, dict):
            completos[nombre].update({k: v for k, v in estilo.items() if k in completos[nombre]})
    return completos
