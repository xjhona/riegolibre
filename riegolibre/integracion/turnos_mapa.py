"""Turnos de riego en el mapa: qué bloque pertenece a qué turno, guardado como una capa de polígonos.

Cada válvula es una entidad de la capa «Turnos de riego» (polígono del bloque que riega, id de la válvula
y turno), pintada con el color del turno. La capa se guarda con el proyecto y de ella leen los turnos la
ventana de la red y la herramienta de mapa.

Un «bloque» es lo que se ve y se toca en el mapa: un lote, un bloque del trazado automático o un bloque
dibujado a mano; sus válvulas se buscan por el nombre («Válvula · Lote 3») o por estar dentro del polígono.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from qgis.core import (Qgis, QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsFillSymbol, QgsGeometry,
                       QgsPalLayerSettings, QgsPointXY, QgsProject, QgsProperty, QgsRectangle,
                       QgsSingleSymbolRenderer, QgsSymbolLayer, QgsTextBufferSettings, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from ..nucleo.turnos import PALETA, TURNO_POR_DEFECTO, ResumenTurnos, resumen_turnos
from .bloque_mapa import nombre_del_lote
from .lotes import capas_de_lotes
from .red_mapa import ValvulaMapa, capas_de_bloques, capas_de_valvulas, leer_valvulas
from .subunidad_mapa import PROPIEDAD, geometria_en

NOMBRE_CAPA = "Turnos de riego"
PROPIEDAD_TURNOS = "turnos"  # valor de `subunidad_mapa.PROPIEDAD` en la capa de turnos
PREFIJO_BLOQUES = "Bloques"
CAMPOS = ("valvula:string(120)", "bloque:string(120)", "turno:integer", "caudal_lh:double")


@dataclass
class BloqueTurno:
    """Algo que se puede tocar en el mapa y tiene válvulas: se le asigna turno completo."""
    nombre: str
    geometria: QgsGeometry  # en el SRC con que se pidió
    valvulas: List[ValvulaMapa] = field(default_factory=list)

    @property
    def clave(self) -> str:
        return "|".join(sorted(v.id for v in self.valvulas)) or self.nombre

    @property
    def caudal_lh(self) -> float:
        return sum(v.caudal_lh for v in self.valvulas)


# ------------------------------------------------------------------ la capa de turnos


def capa_de_turnos(crear=False, crs=None) -> Optional[QgsVectorLayer]:
    """La capa «Turnos de riego» del proyecto; con `crear` la crea (en `crs`) si no existe."""
    for capa in QgsProject.instance().mapLayers().values():
        if (isinstance(capa, QgsVectorLayer) and capa.geometryType() == Qgis.GeometryType.Polygon
                and capa.customProperty(PROPIEDAD) == PROPIEDAD_TURNOS):
            return capa
    if not crear:
        return None
    capa = QgsVectorLayer("Polygon?" + "&".join(f"field={c}" for c in CAMPOS), NOMBRE_CAPA, "memory")
    capa.setCrs(crs or QgsProject.instance().crs())
    capa.setCustomProperty(PROPIEDAD, PROPIEDAD_TURNOS)
    dar_estilo(capa)
    QgsProject.instance().addMapLayer(capa)
    return capa


def expresion_de_color() -> str:
    colores = ", ".join(f"'{c}'" for c in PALETA)
    return f'array_get(array({colores}), (coalesce("turno", 1) - 1) % {len(PALETA)})'


def dar_estilo(capa):
    """Relleno semitransparente con el color del turno y la etiqueta «T1», «T2»…"""
    simbolo = QgsFillSymbol.createSimple({"color": "128,128,128", "outline_color": "64,64,64",
                                          "outline_width": "0.6"})
    simbolo.setOpacity(0.55)
    color = QgsProperty.fromExpression(expresion_de_color())
    capa_simbolo = simbolo.symbolLayer(0)
    capa_simbolo.setDataDefinedProperty(QgsSymbolLayer.Property.PropertyFillColor, color)
    capa_simbolo.setDataDefinedProperty(QgsSymbolLayer.Property.PropertyStrokeColor, color)
    capa.setRenderer(QgsSingleSymbolRenderer(simbolo))
    etiquetas = QgsPalLayerSettings()
    etiquetas.fieldName = "'T' || \"turno\""
    etiquetas.isExpression = True
    etiquetas.priority = 10  # gana a las etiquetas de los lotes: el turno es lo que se quiere ver
    formato = QgsTextFormat()
    formato.setColor(QColor(33, 33, 33))
    formato.setSize(11)
    formato.setForcedBold(True)
    fondo = QgsTextBufferSettings()
    fondo.setEnabled(True)
    fondo.setSize(1.0)
    formato.setBuffer(fondo)
    etiquetas.setFormat(formato)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(etiquetas))
    capa.setLabelsEnabled(True)


def turnos_asignados() -> Dict[str, int]:
    """{id de válvula: turno} guardado en el mapa (vacío si no hay capa de turnos)."""
    capa = capa_de_turnos()
    if capa is None:
        return {}
    asignados = {}
    for entidad in capa.getFeatures():
        if entidad["valvula"] and entidad["turno"] is not None:
            asignados[str(entidad["valvula"])] = int(entidad["turno"])
    return asignados


def _modificar(capa, borrar: List[int], agregar: List[QgsFeature]):
    if capa.isEditable():
        if borrar:
            capa.deleteFeatures(borrar)
        if agregar:
            capa.addFeatures(agregar)
    else:
        proveedor = capa.dataProvider()
        if borrar and not proveedor.deleteFeatures(borrar):
            raise ValueError(f"No se pudo modificar la capa «{capa.name()}». ¿Es de solo lectura?")
        if agregar and not proveedor.addFeatures(agregar)[0]:
            raise ValueError(f"No se pudo escribir en la capa «{capa.name()}».")
        capa.updateExtents()
    capa.triggerRepaint()


def _quitar_de(capa, ids: Iterable[str]) -> List[int]:
    ids = set(ids)
    return [e.id() for e in capa.getFeatures() if str(e["valvula"]) in ids]


def asignar(bloques: List[BloqueTurno], turno: int, crs) -> int:
    """Pone el turno a todas las válvulas de los bloques (pintándolos) y devuelve cuántas válvulas son."""
    capa = capa_de_turnos(crear=True, crs=crs)
    transformacion = (QgsCoordinateTransform(crs, capa.crs(), QgsProject.instance())
                      if crs != capa.crs() else None)
    nuevas, cuantas = [], 0
    for bloque in bloques:
        for v in bloque.valvulas:
            geometria = QgsGeometry(bloque.geometria)
            if transformacion is not None:
                geometria.transform(transformacion)
            entidad = QgsFeature(capa.fields())
            entidad.setGeometry(geometria)
            entidad["valvula"] = v.id
            entidad["bloque"] = bloque.nombre
            entidad["turno"] = int(turno)
            entidad["caudal_lh"] = round(v.caudal_lh, 1)
            nuevas.append(entidad)
            cuantas += 1
    _modificar(capa, _quitar_de(capa, (e["valvula"] for e in nuevas)), nuevas)
    return cuantas


def quitar(ids: Iterable[str]) -> int:
    """Deja sin turno las válvulas dadas (se despintan). Devuelve cuántas tenían."""
    capa = capa_de_turnos()
    if capa is None:
        return 0
    borrar = _quitar_de(capa, ids)
    if borrar:
        _modificar(capa, borrar, [])
    return len(borrar)


def quitar_todos() -> int:
    capa = capa_de_turnos()
    if capa is None:
        return 0
    borrar = [e.id() for e in capa.getFeatures()]
    if borrar:
        _modificar(capa, borrar, [])
    return len(borrar)


def cambiar_turnos(valvulas: Dict[str, int], crs) -> int:
    """Cambia el turno de válvulas ya pintadas, o las pinta con su bloque si aún no lo estaban."""
    if not valvulas:
        return 0
    capa = capa_de_turnos()
    indice = capa.fields().indexOf("turno") if capa is not None else -1
    cambios, faltan = {}, []
    existentes = {str(e["valvula"]): e.id() for e in capa.getFeatures()} if capa is not None else {}
    for id_valvula, turno in valvulas.items():
        if id_valvula in existentes:
            cambios[existentes[id_valvula]] = {indice: int(turno)}
        else:
            faltan.append(id_valvula)
    if cambios:
        if capa.isEditable():
            for fid, atributos in cambios.items():
                capa.changeAttributeValue(fid, indice, atributos[indice])
        elif not capa.dataProvider().changeAttributeValues(cambios):
            raise ValueError(f"No se pudo modificar la capa «{capa.name()}».")
        capa.triggerRepaint()
    if faltan:
        todas = leer_valvulas(capas_de_valvulas(), crs)
        por_turno = defaultdict(list)
        for v in todas:
            if v.id in faltan:
                por_turno[valvulas[v.id]].append(v)
        for turno, lista in por_turno.items():
            asignar(bloques_de_valvulas(lista, crs), turno, crs)
    return len(valvulas)


# ------------------------------------------------------------------ bloques y válvulas


def _por_nombre(valvulas: List[ValvulaMapa]) -> Dict[str, List[ValvulaMapa]]:
    """Válvulas por el nombre de su capa («Lote 3» para «Lote 3» y «Lote 3 #5»)."""
    nombres = defaultdict(list)
    for v in valvulas:
        nombres[v.id.split(" #")[0]].append(v)
    return nombres


def _poligonos(crs, rect: Optional[QgsRectangle]):
    """(nombre, geometría en `crs`, nombre de la capa de válvula que le corresponde o None) de lo tocable.

    Primero los bloques del diseño (más pequeños), luego los lotes. Con `rect` (en `crs`) solo los que
    lo tocan.
    """
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()

    def visible(capa):
        nodo = raiz.findLayer(capa.id())
        return nodo is None or nodo.isVisible()

    def entidades(capa):
        transformacion = (QgsCoordinateTransform(capa.crs(), crs, proyecto) if capa.crs() != crs else None)
        peticion = QgsFeatureRequest()
        if rect is not None:
            inverso = (QgsCoordinateTransform(crs, capa.crs(), proyecto).transformBoundingBox(rect)
                       if transformacion is not None else rect)
            peticion.setFilterRect(inverso)
        for entidad in capa.getFeatures(peticion):
            geometria = QgsGeometry(entidad.geometry())
            if geometria.isEmpty():
                continue
            if transformacion is not None:
                geometria.transform(transformacion)
            if rect is None or geometria.intersects(rect):
                yield entidad, geometria

    for capa in capas_de_bloques():
        if not visible(capa):
            continue
        sufijo = capa.name()[len(PREFIJO_BLOQUES):].lstrip(" ·")
        con_numero = bool(sufijo) and capa.fields().indexOf("subunidad") >= 0
        for entidad, geometria in entidades(capa):
            # Subunidad n del trazado «X»: su válvula está en la capa «Válvula · X n».
            nombre = f"{sufijo} {entidad['subunidad']}" if con_numero else f"{capa.name()} {entidad.id()}"
            yield nombre, geometria, (nombre if con_numero else None)
    for capa in capas_de_lotes():
        if not visible(capa):
            continue
        for entidad, geometria in entidades(capa):
            nombre = nombre_del_lote(entidad)
            yield nombre, geometria, nombre


def _valvulas_de(geometria, capa_valvula, nombres, valvulas, tolerancia) -> List[ValvulaMapa]:
    """Las válvulas de un bloque: las de la capa que lleva su nombre o, si no hay, las que caen dentro."""
    propias = list(nombres.get(capa_valvula, [])) if capa_valvula else []
    if propias:
        return propias
    zona = geometria.buffer(tolerancia, 4)
    return [v for v in valvulas if zona.contains(QgsGeometry.fromPointXY(v.punto))]


def _bloques(crs, valvulas: List[ValvulaMapa], rect: Optional[QgsRectangle], tolerancia: float):
    """Los bloques tocables con válvulas en `rect`, sin repetir válvulas entre ellos: (bloques, ids usados)."""
    nombres = _por_nombre(valvulas)
    usadas = set()
    resultado = []
    for nombre, geometria, capa_valvula in _poligonos(crs, rect):
        nuevas = [v for v in _valvulas_de(geometria, capa_valvula, nombres, valvulas, tolerancia)
                  if v.id not in usadas]
        if nuevas:
            usadas.update(v.id for v in nuevas)
            resultado.append(BloqueTurno(nombre, geometria, nuevas))
    return resultado, usadas


def _circulo(valvula: ValvulaMapa, radio: float) -> QgsGeometry:
    return QgsGeometry.fromPointXY(valvula.punto).buffer(radio, 16)


def bloque_en(punto: QgsPointXY, crs, tolerancia: float) -> Optional[BloqueTurno]:
    """El bloque bajo el punto (el más pequeño si hay varios); si no hay, la válvula más cercana.

    `tolerancia`: distancia en unidades del mapa (unos píxeles) para alcanzar una válvula suelta.
    """
    valvulas = leer_valvulas(capas_de_valvulas(), crs)
    if not valvulas:
        return None
    caja = QgsRectangle(punto.x(), punto.y(), punto.x(), punto.y())
    geometria_punto = QgsGeometry.fromPointXY(punto)
    candidatos = []
    nombres = _por_nombre(valvulas)
    for nombre, geometria, capa_valvula in _poligonos(crs, caja):
        if not geometria.contains(geometria_punto):
            continue
        propias = _valvulas_de(geometria, capa_valvula, nombres, valvulas, tolerancia)
        if propias:
            candidatos.append(BloqueTurno(nombre, geometria, propias))
    if candidatos:
        return min(candidatos, key=lambda b: b.geometria.area())
    cercana = min(valvulas, key=lambda v: v.punto.distance(punto))
    if cercana.punto.distance(punto) <= tolerancia:
        return BloqueTurno(cercana.id, _circulo(cercana, tolerancia), [cercana])
    return None


def bloques_en(rect: QgsRectangle, crs, tolerancia: float) -> List[BloqueTurno]:
    """Los bloques que toca el rectángulo (en `crs`), más las válvulas sueltas que caigan en él."""
    valvulas = leer_valvulas(capas_de_valvulas(), crs)
    if not valvulas:
        return []
    bloques, usadas = _bloques(crs, valvulas, rect, tolerancia)
    for v in valvulas:
        if v.id not in usadas and rect.contains(v.punto):
            bloques.append(BloqueTurno(v.id, _circulo(v, tolerancia), [v]))
    return bloques


def bloques_de_valvulas(valvulas: List[ValvulaMapa], crs, tolerancia: float = 10.0) -> List[BloqueTurno]:
    """El bloque (polígono) de cada válvula; las que no están en ninguno llevan un círculo propio."""
    todas = leer_valvulas(capas_de_valvulas(), crs)
    por_id = {v.id for v in valvulas}
    bloques, usadas = _bloques(crs, todas, None, tolerancia)
    resultado = []
    for b in bloques:
        elegidas = [v for v in b.valvulas if v.id in por_id]
        if elegidas:
            resultado.append(BloqueTurno(b.nombre, b.geometria, elegidas))
    cubiertas = {v.id for b in resultado for v in b.valvulas}
    for v in valvulas:
        if v.id not in cubiertas:
            resultado.append(BloqueTurno(v.id, _circulo(v, tolerancia), [v]))
    return resultado


# ------------------------------------------------------------------ uso desde la ventana de la red


def aplicar_turnos(valvulas: List[ValvulaMapa], asignados: Optional[Dict[str, int]] = None,
                   por_defecto: Optional[Dict[str, int]] = None) -> int:
    """Pone a cada válvula el turno pintado en el mapa. Devuelve cuántas no tienen turno asignado.

    Las que no están pintadas conservan el turno de `por_defecto` ({id: turno}, p. ej. el de la tabla
    de la ventana) o, si tampoco está, el turno 1.
    """
    asignados = turnos_asignados() if asignados is None else asignados
    por_defecto = por_defecto or {}
    sin = 0
    for v in valvulas:
        if v.id in asignados:
            v.turno = asignados[v.id]
        else:
            v.turno = por_defecto.get(v.id, TURNO_POR_DEFECTO)
            sin += 1
    return sin


def resumen_del_proyecto(crs) -> ResumenTurnos:
    """Válvulas del proyecto resumidas por turno (las no pintadas, aparte)."""
    asignados = turnos_asignados()
    return resumen_turnos((v.id, v.caudal_lh, asignados.get(v.id))
                          for v in leer_valvulas(capas_de_valvulas(), crs))
