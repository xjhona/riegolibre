"""Motor de cálculo de RiegoLibre.

Este paquete es Python puro: no depende de QGIS, de modo que puede usarse y
probarse por separado (scripts, cuadernos, otras interfaces).
"""

from .emisores import Emisor, cargar_catalogo_emisores
from .hidraulica import PresionInsuficiente, factor_christiansen
from .lateral import (CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA, CurvaLateral,
                      Lateral, ResultadoLateral, longitud_maxima)
from .portalateral import (ConexionLateral, Portalateral, ResultadoPortalateral,
                           portalateral_uniforme)
from .subunidad import (ENTRADA_CENTRO, ENTRADA_EXTREMO, CriteriosDiseno,
                        EvaluacionDiametro, ResultadoSubunidad, Subunidad,
                        evaluar_diametros, incumplimientos, subunidad_rectangular)
from .tuberias import Tuberia, cargar_catalogo_tuberias
from .uniformidad import (coeficiente_uniformidad_christiansen,
                          uniformidad_emision_keller, variacion_caudal)

__all__ = [
    "Emisor", "cargar_catalogo_emisores",
    "PresionInsuficiente", "factor_christiansen",
    "CRITERIO_CAUDAL_MEDIO", "CRITERIO_PRESION_MINIMA",
    "CurvaLateral", "Lateral", "ResultadoLateral", "longitud_maxima",
    "ConexionLateral", "Portalateral", "ResultadoPortalateral", "portalateral_uniforme",
    "ENTRADA_CENTRO", "ENTRADA_EXTREMO", "CriteriosDiseno", "EvaluacionDiametro",
    "ResultadoSubunidad", "Subunidad", "evaluar_diametros", "incumplimientos",
    "subunidad_rectangular",
    "Tuberia", "cargar_catalogo_tuberias",
    "coeficiente_uniformidad_christiansen", "uniformidad_emision_keller", "variacion_caudal",
]
