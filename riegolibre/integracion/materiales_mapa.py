"""Metrado a partir de las capas de resultado de RiegoLibre en el proyecto."""

from qgis.core import QgsProject, QgsVectorLayer

from ..nucleo.materiales import Partida, ordenar
from .subunidad_mapa import PROPIEDAD

SIN_IDENTIFICAR = "sin identificar (recalcule la subunidad)"


def _tipo(capa):
    """Qué resultado contiene una capa, según sus campos."""
    campos = set(capa.fields().names())
    if {"emisores", "longitud", "p_entrada"} <= campos:
        return "laterales"
    if {"rama", "desde_m", "hasta_m", "tuberia"} <= campos:
        return "portalateral"
    if {"tramo", "tuberia", "dn_mm"} <= campos:
        return "red"
    if "cdt_m" in campos:
        return "bomba"
    if {"presion", "caudal_lh"} <= campos and "valvula" not in campos:
        return "valvula"
    return None


def capas_de_resultado(proyecto=None):
    proyecto = proyecto or QgsProject.instance()
    capas = [c for c in proyecto.mapLayers().values()
             if isinstance(c, QgsVectorLayer) and c.customProperty(PROPIEDAD) == "resultado"]
    return sorted(capas, key=lambda c: c.name())


def partidas_del_proyecto(proyecto=None):
    """Devuelve (partidas, resumen) con las cantidades de todas las capas de resultado.

    resumen: número de subunidades, laterales, válvulas y si hay red principal.
    """
    metros = {}  # (categoría, tubería) -> m
    emisores = {}  # emisor -> und
    laterales_por_tuberia = {}  # tubería lateral -> número de laterales
    valvulas = 0
    bombas = []
    resumen = {"subunidades": 0, "laterales": 0, "red": False}

    def sumar(categoria, nombre, cantidad):
        metros[(categoria, nombre)] = metros.get((categoria, nombre), 0.0) + cantidad

    for capa in capas_de_resultado(proyecto):
        tipo = _tipo(capa)
        campos = set(capa.fields().names())
        if tipo == "laterales":
            resumen["subunidades"] += 1
            for f in capa.getFeatures():
                tuberia = f["tuberia"] if "tuberia" in campos and f["tuberia"] else f"Lateral {SIN_IDENTIFICAR}"
                emisor = f["emisor"] if "emisor" in campos and f["emisor"] else f"Emisor {SIN_IDENTIFICAR}"
                sumar("Laterales", tuberia, float(f["longitud"] or 0.0))
                emisores[emisor] = emisores.get(emisor, 0) + int(f["emisores"] or 0)
                laterales_por_tuberia[tuberia] = laterales_por_tuberia.get(tuberia, 0) + 1
                resumen["laterales"] += 1
        elif tipo == "portalateral":
            for f in capa.getFeatures():
                sumar("Portalaterales", f["tuberia"], f.geometry().length())
        elif tipo == "red":
            resumen["red"] = True
            for f in capa.getFeatures():
                sumar("Red principal", f["tuberia"], float(f["longitud"] or f.geometry().length()))
        elif tipo == "valvula":
            valvulas += capa.featureCount()
        elif tipo == "bomba":
            for f in capa.getFeatures():
                bombas.append(f)

    partidas = [Partida(categoria, nombre, cantidad, "m", f"tuberia:{nombre}")
                for (categoria, nombre), cantidad in metros.items()]
    partidas += [Partida("Emisores", nombre, cantidad, "und", f"emisor:{nombre}",
                         nota="Si la manguera ya trae los goteros incorporados, deje esta partida sin precio.")
                 for nombre, cantidad in emisores.items()]
    for tuberia, cantidad in laterales_por_tuberia.items():
        partidas.append(Partida("Accesorios", f"Conector inicial para {tuberia}", cantidad, "und",
                                f"conector:{tuberia}"))
        partidas.append(Partida("Accesorios", f"Cierre final de lateral ({tuberia})", cantidad, "und",
                                f"cierre:{tuberia}"))
    resumen["valvulas"] = valvulas
    if valvulas:
        partidas.append(Partida("Válvulas y equipos", "Válvula de subunidad", valvulas, "und",
                                "valvula_subunidad"))
    for f in bombas:
        partidas.append(Partida(
            "Válvulas y equipos",
            f"Bomba {f['caudal_ls']:.2f} L/s a {f['cdt_m']:.1f} m de CDT ({f['potencia_hp']:.1f} HP)",
            1, "und", "bomba"))
    return ordenar(partidas), resumen
