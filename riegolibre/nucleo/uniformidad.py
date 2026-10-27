"""Indicadores de uniformidad de riego."""

import math


def uniformidad_emision_keller(caudal_min, caudal_medio, cv, emisores_por_planta=1):
    """Uniformidad de emisión de diseño, EU (%) según Keller y Karmeli.

    EU = 100 · (1 - 1.27·cv/√e) · q_min / q_medio
    """
    if caudal_medio <= 0:
        return 0.0
    return 100.0 * (1 - 1.27 * cv / math.sqrt(emisores_por_planta)) * caudal_min / caudal_medio


def caudal_cuartil_inferior(caudales):
    """Promedio del 25 % de los emisores de menor caudal (q_25%)."""
    if not caudales:
        return 0.0
    ordenados = sorted(caudales)
    n_cuartil = max(1, len(ordenados) // 4)
    return sum(ordenados[:n_cuartil]) / n_cuartil


def uniformidad_emision_cuartil(caudales, cv, emisores_por_planta=1):
    """Uniformidad de emisión EU (%) usando el promedio del cuartil inferior (q_25%)."""
    if not caudales:
        return 0.0
    media = sum(caudales) / len(caudales)
    return uniformidad_emision_keller(caudal_cuartil_inferior(caudales), media, cv, emisores_por_planta)


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
