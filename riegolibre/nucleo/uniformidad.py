"""Indicadores de uniformidad de riego."""

import math


def uniformidad_emision_keller(caudal_min, caudal_medio, cv, emisores_por_planta=1):
    """Uniformidad de emisión de diseño, EU (%) según Keller y Karmeli.

    EU = 100 · (1 - 1.27·cv/√e) · q_min / q_medio
    """
    if caudal_medio <= 0:
        return 0.0
    return 100.0 * (1 - 1.27 * cv / math.sqrt(emisores_por_planta)) * caudal_min / caudal_medio


def variacion_caudal(caudal_max, caudal_min):
    """Variación de caudal qv = (q_max - q_min) / q_max (fracción)."""
    if caudal_max <= 0:
        return 0.0
    return (caudal_max - caudal_min) / caudal_max


def coeficiente_uniformidad_christiansen(caudales):
    """CU de Christiansen (%), útil sobre todo en aspersión."""
    n = len(caudales)
    media = sum(caudales) / n
    if media <= 0:
        return 0.0
    return 100.0 * (1 - sum(abs(q - media) for q in caudales) / (n * media))
