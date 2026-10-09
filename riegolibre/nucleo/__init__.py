"""Motor de cálculo de RiegoLibre.

Este paquete es Python puro: no depende de QGIS, de modo que puede usarse y
probarse por separado (scripts, cuadernos, otras interfaces).
"""

from .emisores import Emisor, cargar_catalogo_emisores
from .hidraulica import PresionInsuficiente, factor_christiansen
from .memoria import DatosMemoria, memoria_html, resumen_red, resumen_subunidad
from .lateral import (CRITERIO_CAUDAL_MEDIO, CRITERIO_PRESION_MINIMA, CurvaLateral,
                      Lateral, ResultadoLateral, longitud_maxima)
from .portalateral import (ConexionLateral, Portalateral, ResultadoPortalateral,
                           portalateral_uniforme)
from .subunidad import (ENTRADA_CENTRO, ENTRADA_EXTREMO, CriteriosDiseno, Diseno,
                        EvaluacionDiametro, ResultadoSubunidad, Subunidad,
                        disenar_subunidad, evaluar_diametros, incumplimientos,
                        subunidad_desde_conexiones, subunidad_rectangular)
from .red import (CriteriosRed, DatosBomba, PuntoBomba, Red, ResultadoRed,
                  ResultadoTurno, TramoRed, Valvula, dimensionar_red, elegir_tuberia,
                  punto_bomba)
from .tuberias import Tuberia, cargar_catalogo_tuberias
from .uniformidad import (coeficiente_uniformidad_christiansen,
                          uniformidad_emision_keller, variacion_caudal)

__all__ = [
    "Emisor", "cargar_catalogo_emisores",
    "PresionInsuficiente", "factor_christiansen",
    "CRITERIO_CAUDAL_MEDIO", "CRITERIO_PRESION_MINIMA",
    "DatosMemoria", "memoria_html", "resumen_red", "resumen_subunidad",
    "CurvaLateral", "Lateral", "ResultadoLateral", "longitud_maxima",
    "ConexionLateral", "Portalateral", "ResultadoPortalateral", "portalateral_uniforme",
    "ENTRADA_CENTRO", "ENTRADA_EXTREMO", "CriteriosDiseno", "Diseno", "EvaluacionDiametro",
    "ResultadoSubunidad", "Subunidad", "disenar_subunidad", "evaluar_diametros",
    "incumplimientos", "subunidad_desde_conexiones", "subunidad_rectangular",
    "CriteriosRed", "DatosBomba", "PuntoBomba", "Red", "ResultadoRed", "ResultadoTurno",
    "TramoRed", "Valvula", "dimensionar_red", "elegir_tuberia", "punto_bomba",
    "Tuberia", "cargar_catalogo_tuberias",
    "coeficiente_uniformidad_christiansen", "uniformidad_emision_keller", "variacion_caudal",
]
