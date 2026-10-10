"""Cálculo hidráulico de una subunidad dibujada en el mapa, sin depender de ninguna ventana.

Lo usan la ventana de diseño en el mapa (una subunidad dibujada a mano) y la de trazado
automático (todas las subunidades de un terreno).
"""

import json
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

from ..nucleo import (CriteriosDiseno, Lateral, disenar_subunidad,
                      subunidad_desde_conexiones)
from ..nucleo.memoria import resumen_subunidad
from . import subunidad_mapa as mapa
from .memoria_mapa import guardar_resumen

ENTRADA_INICIO, ENTRADA_CENTRO, ENTRADA_FINAL = "inicio", "centro", "final"
PROPIEDAD_LATERAL = "riegolibre/laterales"  # configuración con la que se calcularon los laterales de la capa


@dataclass
class ConfigCalculo:
    tuberia_lateral: object
    emisor: object
    espaciamiento_m: float
    primer_emisor_m: float
    metodo: str
    tuberias_portalateral: Sequence
    criterios: CriteriosDiseno
    entrada: str = ENTRADA_INICIO
    capa_dem: Optional[object] = None
    tuberia_portalateral: Optional[object] = None  # None: la menor que cumple
    presion_conocida: Optional[float] = None
    diametros_max: int = 1


@dataclass
class ResultadoCalculo:
    diseno: object
    capas: list  # [válvula, tramos del portalateral, laterales]
    area_m2: float
    avisos: list


def guardar_configuracion_laterales(capa, config):
    """Guarda en la capa de laterales con qué se calcularon, para poder reconstruir uno al consultarlo."""
    capa.setCustomProperty(PROPIEDAD_LATERAL, json.dumps({
        "tuberia": asdict(config.tuberia_lateral), "emisor": asdict(config.emisor),
        "espaciamiento_m": config.espaciamiento_m, "primer_emisor_m": config.primer_emisor_m,
        "metodo": config.metodo, "dem": config.capa_dem.id() if config.capa_dem is not None else None,
        "paso_perfil_m": max(config.espaciamiento_m, 1.0)}, ensure_ascii=False))


def distancia_entrada(entrada, portalateral):
    return {ENTRADA_INICIO: 0.0, ENTRADA_CENTRO: portalateral.length() / 2,
            ENTRADA_FINAL: portalateral.length()}[entrada]


def calcular_subunidad(nombre, crs, portalateral, bloque, laterales_mapa, config, avisos=None,
                       agregar_al_mapa=True) -> ResultadoCalculo:
    """Calcula la subunidad, crea sus capas de resultado y guarda su resumen para la memoria.

    Lanza ValueError o PresionInsuficiente si no se puede calcular. Con `agregar_al_mapa`
    las capas se colocan en el grupo «RiegoLibre · nombre» del proyecto.
    """
    avisos = list(avisos or [])
    metodo = config.metodo

    def crear_lateral(longitud, perfil):
        if longitud < config.primer_emisor_m:
            return None
        return Lateral.desde_longitud(config.tuberia_lateral, config.emisor, config.espaciamiento_m,
                                      longitud, distancia_primer_emisor_m=config.primer_emisor_m,
                                      perfil=perfil, metodo=metodo)

    modelo = mapa.construir_modelo(laterales_mapa, crear_lateral, portalateral, crs,
                                   capa_dem=config.capa_dem,
                                   paso_perfil_m=max(config.espaciamiento_m, 1.0))
    if modelo.descartados:
        avisos.append(f"{len(modelo.descartados)} laterales son más cortos que la distancia "
                      "al primer emisor y no se calcularon.")
    if config.capa_dem is None:
        avisos.append("Sin DEM: se calculó con el terreno plano.")

    entrada = distancia_entrada(config.entrada, portalateral)

    def construir(tuberia, reducciones=()):
        return subunidad_desde_conexiones(tuberia, modelo.conexiones, entrada,
                                          perfil=modelo.perfil_portalateral, metodo=metodo,
                                          reducciones=reducciones)

    diseno = disenar_subunidad(construir, config.tuberias_portalateral, config.criterios,
                               tuberia_fija=config.tuberia_portalateral,
                               presion_entrada_m=config.presion_conocida,
                               diametros_max=config.diametros_max)
    area = bloque.area() if bloque is not None else 0.0
    descartados = {id(lat) for lat in modelo.descartados}
    longitudes = [lat.longitud_m for lat in laterales_mapa if id(lat) not in descartados]
    capas = mapa.capas_resultado(diseno, modelo, portalateral, entrada, crs, nombre)
    guardar_configuracion_laterales(capas[2], config)
    guardar_resumen(capas[0], resumen_subunidad(
        nombre, diseno, config.criterios, metodo, area, longitudes, config.presion_conocida, avisos))
    if agregar_al_mapa:
        mapa.reemplazar_grupo(f"RiegoLibre · {nombre}", capas)
    return ResultadoCalculo(diseno, capas, area, avisos)
