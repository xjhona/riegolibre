"""Motor de cálculo de RiegoLibre.

Este paquete es Python puro: no depende de QGIS, de modo que puede usarse y
probarse por separado (scripts, cuadernos, otras interfaces).
"""

from .emisores import Emisor, cargar_catalogo_emisores
from .hidraulica import PresionInsuficiente, factor_christiansen
from .lateral import (CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA, Lateral,
                      ResultadoLateral, longitud_maxima)
from .portalateral import (ConexionLateral, Portalateral, ResultadoSubunidad,
                           portalateral_uniforme)
from .tuberias import Tuberia, cargar_catalogo_tuberias
from .uniformidad import (coeficiente_uniformidad_christiansen,
                          uniformidad_emision_keller, variacion_caudal)

__all__ = [
    "Emisor", "cargar_catalogo_emisores",
    "PresionInsuficiente", "factor_christiansen",
    "CRITERIO_CAUDAL_MEDIO", "CRITERIO_PRESION_MINIMA",
    "Lateral", "ResultadoLateral", "longitud_maxima",
    "ConexionLateral", "Portalateral", "ResultadoSubunidad", "portalateral_uniforme",
    "Tuberia", "cargar_catalogo_tuberias",
    "coeficiente_uniformidad_christiansen", "uniformidad_emision_keller", "variacion_caudal",
]
