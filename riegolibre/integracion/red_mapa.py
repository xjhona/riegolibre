"""Red principal dibujada en el mapa: topología, válvulas, cotas y capas de resultado.

Las tuberías se dibujan como líneas sin necesidad de cortarlas en las uniones:
los extremos de cada línea, la fuente y las válvulas se convierten en nodos, y
cada línea se divide en tramos allí donde la toca un nodo (uniones en T).
"""

import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from qgis.core import (Qgis, QgsFeature, QgsGeometry,
                       QgsMarkerSymbol, QgsPointXY, QgsProject, QgsRectangle,
                       QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor

from ..nucleo import Red, TramoRed, Valvula
from ..nucleo.terreno import Terreno, celda_automatica
from ..nucleo.trazado_red import ORTOGONAL, ParametrosRed, ValvulaDestino, trazar_red
from ..nucleo.tuberias import rotulo_corto
from .perfil_terreno import MuestreadorDem, linea_simple, perfil_de_geometria
from .subunidad_mapa import PROPIEDAD, estilo_por_tuberia, geometria_en, rotular_tuberia

CAMPOS_VALVULA = ("presion", "caudal_lh")
PREFIJO_VALVULA = "Válvula · "


@dataclass
class ValvulaMapa:
    id: str
    punto: object  # QgsPointXY en el SRC de la red
    caudal_lh: float
    presion_m: float
    turno: int = 1
    elemento: Optional[object] = None  # ElementoHidraulico opcional


def capas_de_valvulas(proyecto=None):
    """Capas de puntos del proyecto con los campos de una válvula (presion, caudal_lh)."""
    proyecto = proyecto or QgsProject.instance()
    capas = []
    for capa in proyecto.mapLayers().values():
        if (isinstance(capa, QgsVectorLayer) and capa.geometryType() == Qgis.GeometryType.Point
                and all(capa.fields().indexOf(c) >= 0 for c in CAMPOS_VALVULA)):
            capas.append(capa)
    return sorted(capas, key=lambda c: c.name())


def leer_valvulas(capas, crs):
    """Lee todas las válvulas de las capas dadas (transformadas al SRC de la red)."""
    valvulas = []
    for capa in capas:
        base = capa.name()
        if base.startswith(PREFIJO_VALVULA):
            base = base[len(PREFIJO_VALVULA):]
        entidades = list(capa.getFeatures())
        for entidad in entidades:
            if entidad["presion"] is None or entidad["caudal_lh"] is None:
                continue
            nombre = base if len(entidades) == 1 else f"{base} #{entidad.id()}"
            punto = geometria_en(capa, entidad, crs).asPoint()
            valvulas.append(ValvulaMapa(nombre, punto, float(entidad["caudal_lh"]), float(entidad["presion"])))
    return valvulas


@dataclass
class RedMapa:
    red: Red
    geometrias: Dict[str, QgsGeometry]  # tramo -> geometría
    puntos: Dict[str, object]  # nodo -> QgsPointXY
    sin_dem: bool


def construir_red(capa_tuberias, punto_fuente, valvulas: List[ValvulaMapa], crs, muestreador=None,
                  tolerancia_m=0.5, paso_perfil_m=5.0, perdida_valvula_m=0.0, elemento_valvula=None):
    """Construye la red (nodos, tramos con perfil y válvulas) a partir del mapa."""
    lineas = []
    for entidad in capa_tuberias.getFeatures():
        geometria = geometria_en(capa_tuberias, entidad, crs)
        if geometria.isEmpty():
            continue
        try:
            lineas.append((entidad.id(), linea_simple(geometria)))
        except ValueError:
            raise ValueError(f"La tubería {entidad.id()} tiene varias partes; sepárelas.") from None
    if not lineas:
        raise ValueError(f"La capa «{capa_tuberias.name()}» no tiene tuberías.")

    puntos: List[object] = []

    def nodo_de(punto):
        for i, existente in enumerate(puntos):
            if existente.distance(punto) <= tolerancia_m:
                return f"N{i}"
        puntos.append(punto)
        return f"N{len(puntos) - 1}"

    fuente = nodo_de(punto_fuente)
    nodos_valvula = [nodo_de(v.punto) for v in valvulas]
    for _, geometria in lineas:
        vertices = geometria.asPolyline()
        nodo_de(vertices[0])
        nodo_de(vertices[-1])

    tramos, geometrias = [], {}
    for id_linea, geometria in lineas:
        posiciones = set()
        for i, punto in enumerate(puntos):
            punto_geom = QgsGeometry.fromPointXY(punto)
            if geometria.distance(punto_geom) <= tolerancia_m:
                posiciones.add((round(geometria.lineLocatePoint(punto_geom), 6), f"N{i}"))
        ordenadas = sorted(posiciones)
        for k, ((a, nodo_a), (b, nodo_b)) in enumerate(zip(ordenadas, ordenadas[1:])):
            if b - a <= 1e-6 or nodo_a == nodo_b:
                continue
            tramo_geom = QgsGeometry(geometria.constGet().curveSubstring(a, b))
            id_tramo = f"{id_linea}.{k + 1}"
            perfil = None
            if muestreador is not None:
                _, perfil = perfil_de_geometria(tramo_geom, crs, muestreador, paso_perfil_m)
            tramos.append(TramoRed(id_tramo, nodo_a, nodo_b, b - a, perfil))
            geometrias[id_tramo] = tramo_geom

    cotas = {}
    for i, punto in enumerate(puntos):
        cota = muestreador.cota(punto) if muestreador is not None else 0.0
        if cota is None:
            raise ValueError("El DEM no cubre toda la red (falta la cota de un nodo).")
        cotas[f"N{i}"] = cota

    lista = [Valvula(v.id, nodo, v.caudal_lh, v.presion_m, v.turno, perdida_valvula_m,
                     v.elemento or elemento_valvula)
             for v, nodo in zip(valvulas, nodos_valvula)]
    try:
        red = Red(cotas, tramos, lista, fuente)
    except ValueError as error:
        if "no están conectadas" in str(error):
            raise ValueError(f"{error}. Compruebe que la tubería pasa a menos de {tolerancia_m:g} m "
                             "de cada válvula y de la fuente.") from None
        raise
    return RedMapa(red, geometrias, {f"N{i}": p for i, p in enumerate(puntos)}, muestreador is None)


# --------------------------------------------------- trazado automático

PROPIEDAD_AUTOMATICA = "red_automatica"
NOMBRE_CAPA_AUTOMATICA = "Red principal · trazado automático"


@dataclass
class RestriccionesTrazado:
    """Capas del proyecto que condicionan el trazado automático de la red."""
    capa_zonas: Optional[QgsVectorLayer] = None  # polígonos que conviene evitar
    factor_zonas: Optional[float] = 5.0  # cuántas veces cuesta más tender en ellas; None = no se cruzan
    capa_caminos: Optional[QgsVectorLayer] = None  # líneas a seguir: caminos, zanjas existentes
    factor_caminos: float = 0.5  # fracción del costo normal sobre ellas
    capa_barreras: Optional[QgsVectorLayer] = None  # líneas que cuesta cruzar: canales, cercos
    costo_cruce_m: Optional[float] = 50.0  # metros de tubería que equivale a cruzarlas; None = no se cruzan
    capa_dem: Optional[object] = None  # DEM para evitar subidas y pendientes fuertes
    costo_subida: float = 5.0
    pendiente_duplica: Optional[float] = 0.25
    celda_m: Optional[float] = None  # tamaño de la celda de trabajo; None = automático

    @property
    def activa(self):
        return any(c is not None for c in (self.capa_zonas, self.capa_caminos, self.capa_barreras,
                                           self.capa_dem))


def _poligonos(geometria):
    """Polígonos de una geometría como listas de anillos de tuplas (x, y)."""
    if geometria.isEmpty():
        return []
    partes = geometria.asMultiPolygon() if geometria.isMultipart() else [geometria.asPolygon()]
    return [[[(p.x(), p.y()) for p in anillo] for anillo in poligono] for poligono in partes if poligono]


def _lineas(geometria):
    """Líneas de una geometría como listas de tuplas (x, y)."""
    if geometria.isEmpty():
        return []
    partes = geometria.asMultiPolyline() if geometria.isMultipart() else [geometria.asPolyline()]
    return [[(p.x(), p.y()) for p in linea] for linea in partes if len(linea) > 1]


def _cargar_cotas(terreno: Terreno, capa_dem, crs):
    """Pone en el terreno la cota del DEM en el centro de cada celda."""
    cotas = None
    if capa_dem.crs() == crs:  # un solo pedido al DEM, remuestreado a la cuadrícula del terreno
        nx, ny, paso = terreno.nx, terreno.ny, terreno.paso
        extension = QgsRectangle(terreno.x0, terreno.y0, terreno.x0 + nx * paso, terreno.y0 + ny * paso)
        bloque = capa_dem.dataProvider().block(1, extension, nx, ny)
        if bloque is not None and bloque.isValid():
            cotas = [math.nan] * (nx * ny)
            for fila in range(ny):
                base = (ny - 1 - fila) * nx  # la fila 0 del bloque es la del norte
                for columna in range(nx):
                    if not bloque.isNoData(fila, columna):
                        cotas[base + columna] = bloque.value(fila, columna)
    if cotas is None:
        muestreador = MuestreadorDem(capa_dem, crs)
        terreno.cargar_cotas(lambda x, y: muestreador.cota(QgsPointXY(x, y)))
    else:
        terreno.poner_cotas(cotas)
    if all(c != c for c in terreno.cotas):
        raise ValueError(f"El DEM «{capa_dem.name()}» no cubre el predio.")


def construir_terreno(puntos, crs, restricciones: Optional[RestriccionesTrazado]) -> Optional[Terreno]:
    """Mapa de costos del terreno alrededor de los puntos dados (fuente y válvulas); None sin restricciones."""
    if restricciones is None or not restricciones.activa:
        return None
    r = restricciones
    terreno = Terreno.cubriendo(puntos, r.celda_m or celda_automatica(puntos))
    if r.capa_zonas is not None:
        for entidad in r.capa_zonas.getFeatures():
            for poligono in _poligonos(geometria_en(r.capa_zonas, entidad, crs)):
                terreno.penalizar_poligono(poligono, r.factor_zonas)
    if r.capa_barreras is not None:
        for entidad in r.capa_barreras.getFeatures():
            for linea in _lineas(geometria_en(r.capa_barreras, entidad, crs)):
                terreno.barrera_linea(linea, r.costo_cruce_m)
    if r.capa_caminos is not None:  # al final: abarata sin quitar lo que prohíben las capas anteriores
        for entidad in r.capa_caminos.getFeatures():
            for linea in _lineas(geometria_en(r.capa_caminos, entidad, crs)):
                terreno.descontar_linea(linea, r.factor_caminos)
    if r.capa_dem is not None:
        _cargar_cotas(terreno, r.capa_dem, crs)
    return terreno


def trazar_red_en_mapa(punto_fuente, valvulas: List[ValvulaMapa], crs, modo=ORTOGONAL, angulo_grados=None,
                       proyecto=None, restricciones: Optional[RestriccionesTrazado] = None):
    """Traza la red principal de la fuente a las válvulas y la deja en una capa de líneas editable.

    La capa de un trazado anterior (la que lleva la propiedad `red_automatica`) se reutiliza y
    se vacía; si no existe se crea y se agrega al proyecto. Con `restricciones`, el trazado evita
    las zonas, sigue los caminos, cruza las barreras donde cuesta menos y esquiva el relieve.
    Devuelve (capa, RedTrazada).
    """
    proyecto = proyecto or QgsProject.instance()
    destinos = [ValvulaDestino(v.id, v.punto.x(), v.punto.y(), v.caudal_lh, v.turno) for v in valvulas]
    fuente = (punto_fuente.x(), punto_fuente.y())
    terreno = construir_terreno([fuente] + [(d.x, d.y) for d in destinos], crs, restricciones)
    parametros = ParametrosRed(modo=modo, angulo_grados=angulo_grados)
    if restricciones is not None:
        parametros.costo_subida = restricciones.costo_subida
        parametros.pendiente_duplica = restricciones.pendiente_duplica
    red = trazar_red(fuente, destinos, parametros, terreno)

    capa = next((c for c in proyecto.mapLayers().values()
                 if isinstance(c, QgsVectorLayer) and c.customProperty(PROPIEDAD_AUTOMATICA) and c.crs() == crs),
                None)
    if capa is None:
        capa = QgsVectorLayer("LineString?field=nombre:string(100)&field=desde:string(80)&field=hasta:string(80)"
                              "&field=caudal_lh:double&field=longitud:double",
                              NOMBRE_CAPA_AUTOMATICA, "memory")
        capa.setCrs(crs)
        capa.setCustomProperty(PROPIEDAD_AUTOMATICA, True)
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        simbolo.setColor(QColor("#1565c0"))
        simbolo.setWidth(0.8)
        capa.setRenderer(QgsSingleSymbolRenderer(simbolo))
        proyecto.addMapLayer(capa)
    else:
        capa.dataProvider().truncate()

    entidades = []
    for t in red.tramos:
        if t.longitud_m < 1e-6:
            continue  # válvula justo sobre otro punto de la red: no necesita tubería
        entidad = QgsFeature(capa.fields())
        entidad.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in t.vertices]))
        # Por nombre: si la capa ya se guardó en el GeoPackage, el primer campo es «fid».
        for campo, valor in (("nombre", f"{t.desde} → {t.hasta}"), ("desde", t.desde), ("hasta", t.hasta),
                             ("caudal_lh", round(t.caudal_lh, 1)), ("longitud", round(t.longitud_m, 2))):
            entidad[campo] = valor
        entidades.append(entidad)
    capa.dataProvider().addFeatures(entidades)
    capa.updateExtents()
    capa.triggerRepaint()
    return capa, red


# --------------------------------------------------------------- resultados


def _capa(tipo, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "resultado")
    return capa


def capas_resultado(red_mapa, resultado, bomba, crs):
    """Capas de tramos (por tubería), válvulas (presión disponible) y bomba."""
    red = red_mapa.red
    tramos = _capa(
        "LineString",
        "field=tramo:string(20)&field=tuberia:string(80)&field=dn_mm:double&field=pn_m:double"
        "&field=longitud:double&field=caudal_lh:double&field=velocidad:double&field=j_m100:double"
        "&field=p_min:double&field=p_max:double&field=observ:string(200)"
        "&field=desnivel_m:double&field=turnos:string(4000)&field=rotulo:string(80)",
        "Red principal · tuberías", crs)
    entidades = []
    for t in red.tramos:
        tuberia = resultado.asignacion[t.id]
        q, p_min, p_max = resultado.peor_tramo(t.id)
        peores = [r.tramos[t.id] for r in resultado.turnos]
        entidad = QgsFeature(tramos.fields())
        entidad.setGeometry(_en_sentido_del_flujo(red_mapa.geometrias[t.id], red_mapa.puntos[t.desde]))
        por_turno = [[r.turno, round(r.tramos[t.id].presion_inicio_m, 2), round(r.tramos[t.id].presion_fin_m, 2),
                      round(r.tramos[t.id].perdida_m, 3), round(r.tramos[t.id].caudal_lh, 1),
                      round(r.tramos[t.id].velocidad_ms, 3)] for r in resultado.turnos]
        entidad.setAttributes([
            t.id, tuberia.nombre, tuberia.diametro_nominal_mm, tuberia.presion_nominal_m,
            round(t.longitud_m, 2), round(q, 1), round(max(r.velocidad_ms for r in peores), 3),
            round(max(r.perdida_unitaria_m100 for r in peores), 3), round(p_min, 2), round(p_max, 2),
            resultado.observaciones(t.id), round(red.cotas[t.hasta] - red.cotas[t.desde], 3),
            json.dumps(por_turno, separators=(",", ":")),
            f"{t.longitud_m:.0f} m\n{rotulo_corto(tuberia)}"])
        entidades.append(entidad)
    tramos.dataProvider().addFeatures(entidades)
    estilo_por_tuberia(tramos, resultado.asignacion.values())
    # Un rótulo por tramo (de nodo a nodo), sin unir tramos vecinos aunque tengan el mismo texto.
    rotular_tuberia(tramos, color="#c62828", tamano=9, unir=False)

    valvulas = _capa(
        "Point",
        "field=valvula:string(80)&field=turno:integer&field=caudal_lh:double&field=p_requerida:double"
        "&field=p_disponible:double&field=exceso:double&field=cota_m:double&field=perdida_valvula_m:double"
        "&field=turnos:string(4000)",
        "Red principal · válvulas", crs)
    entidades = []
    for v in red.valvulas:
        r = resultado.turno(v.turno)
        entidad = QgsFeature(valvulas.fields())
        entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[v.nodo]))
        # Por cada turno: presión aguas arriba de la válvula, la requerida, su pérdida y su caudal.
        por_turno = [[t.turno, round(t.presiones[v.nodo], 2),
                      round(v.presion_requerida_m, 2) if t.turno == v.turno else 0.0,
                      round(v.perdida_m, 2) if t.turno == v.turno else 0.0,
                      round(v.caudal_lh, 1) if t.turno == v.turno else 0.0] for t in resultado.turnos]
        entidad.setAttributes([v.id, v.turno, round(v.caudal_lh, 1), round(v.presion_requerida_m, 2),
                               round(r.presion_disponible[v.id], 2), round(r.exceso(v), 2),
                               round(red.cotas[v.nodo], 2), round(v.perdida_m, 2),
                               json.dumps(por_turno, separators=(",", ":"))])
        entidades.append(entidad)
    valvulas.dataProvider().addFeatures(entidades)
    valvulas.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "3", "outline_color": "#ffffff"})))

    capa_bomba = _capa(
        "Point",
        "field=turno:integer&field=caudal_ls:double&field=cdt_m:double&field=potencia_kw:double"
        "&field=potencia_hp:double&field=cota_m:double",
        "Red principal · bomba", crs)
    entidad = QgsFeature(capa_bomba.fields())
    entidad.setGeometry(QgsGeometry.fromPointXY(red_mapa.puntos[red.fuente]))
    entidad.setAttributes([bomba.turno, round(bomba.caudal_ls, 3), round(bomba.carga_dinamica_total_m, 2),
                           round(bomba.potencia_kw, 2), round(bomba.potencia_hp, 2),
                           round(red.cotas[red.fuente], 2)])
    capa_bomba.dataProvider().addFeatures([entidad])
    capa_bomba.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": "#1565c0", "size": "5", "outline_color": "#ffffff"})))

    for capa in (tramos, valvulas, capa_bomba):
        capa.updateExtents()
    return [capa_bomba, valvulas, tramos]


def _en_sentido_del_flujo(geometria, punto_inicial):
    """La línea orientada de modo que empiece en el nodo de aguas arriba (P1) del tramo."""
    vertices = geometria.asPolyline()
    if vertices[0].distance(punto_inicial) <= vertices[-1].distance(punto_inicial):
        return geometria
    return QgsGeometry.fromPolylineXY(list(reversed(vertices)))
