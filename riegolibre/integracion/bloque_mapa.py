"""Bloque de goteo de un lote en el mapa: del polígono del lote al portalateral, los laterales, la
válvula y el cálculo de la subunidad; y la subdivisión de un lote en sub-bloques.

El motor (`nucleo.bloque`, `nucleo.subdivision`) trabaja con listas de puntos; aquí se convierten las
geometrías de QGIS, se leen las cotas del DEM y se crean las capas.
"""

from typing import List, Optional

from qgis.core import (Qgis, QgsFeature, QgsGeometry, QgsMarkerSymbol, QgsPointXY, QgsSingleSymbolRenderer,
                       QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor

from ..nucleo.bloque import Bloque, ParametrosBloque, trazar_bloque
from ..nucleo.subdivision import ParametrosSubdivision, subdividir
from .lotes import CAMPO_AREA, CAMPO_NOMBRE
from .subunidad_mapa import PROPIEDAD, LateralMapa, reemplazar_grupo
from .trazado_mapa import (anillos_de_geometria, funcion_cota, gradiente_del_terreno,
                           pendiente_a_lo_largo)

GRUPO_VISTA_PREVIA = "RiegoLibre · Vista previa del bloque"


def _punto(p):
    return QgsPointXY(p[0], p[1])


def trazar_en_lote(geometria, params: ParametrosBloque, crs, capa_dem=None, fuente=None,
                   alcance_m: Optional[float] = None) -> Bloque:
    """Traza el bloque en el polígono del lote (en el SRC dado, en metros)."""
    anillos = anillos_de_geometria(geometria)
    cota = pendiente = None
    if capa_dem is not None:
        cota = funcion_cota(capa_dem, crs)
        gradiente = gradiente_del_terreno(geometria, capa_dem, crs)
        if gradiente is not None:
            def pendiente(angulo):
                return pendiente_a_lo_largo(gradiente, angulo)
    bloque = trazar_bloque(anillos, params, cota=cota, fuente=fuente, pendiente=pendiente, alcance_m=alcance_m)
    if capa_dem is not None and bloque.desnivel_portalateral_m is None:
        bloque.avisos.append("El DEM no cubre los extremos del portalateral.")
    return bloque


def geometria_portalateral(bloque: Bloque) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([_punto(p) for p in bloque.portalateral])


def laterales_mapa(bloque: Bloque) -> List[LateralMapa]:
    return [LateralMapa(i, QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)]),
                        lat.distancia_m, lat.longitud_m)
            for i, lat in enumerate(bloque.laterales)]


def _capa(tipo, campos, nombre, crs):
    capa = QgsVectorLayer(f"{tipo}?{campos}", nombre, "memory")
    capa.setCrs(crs)
    capa.setCustomProperty(PROPIEDAD, "vista_previa")
    return capa


def vista_previa(bloques, crs):
    """Dibuja los bloques (sin calcular) en un grupo temporal que reemplaza al anterior.

    `bloques` es una lista de (nombre del lote, Bloque).
    """
    laterales = _capa("LineString", "field=lote:string(80)&field=longitud:double", "Laterales (vista previa)", crs)
    portas = _capa("LineString", "field=lote:string(80)&field=longitud:double", "Portalaterales (vista previa)", crs)
    valvulas = _capa("Point", "field=lote:string(80)", "Válvulas (vista previa)", crs)
    ent_lat, ent_porta, ent_valv = [], [], []
    for nombre, b in bloques:
        for lat in b.laterales:
            e = QgsFeature(laterales.fields())
            e.setGeometry(QgsGeometry.fromPolylineXY([_punto(lat.inicio), _punto(lat.fin)]))
            e.setAttributes([nombre, round(lat.longitud_m, 2)])
            ent_lat.append(e)
        e = QgsFeature(portas.fields())
        e.setGeometry(geometria_portalateral(b))
        e.setAttributes([nombre, round(b.longitud_portalateral_m, 2)])
        ent_porta.append(e)
        e = QgsFeature(valvulas.fields())
        e.setGeometry(QgsGeometry.fromPointXY(_punto(b.valvula)))
        e.setAttributes([nombre])
        ent_valv.append(e)
    for capa, entidades in ((laterales, ent_lat), (portas, ent_porta), (valvulas, ent_valv)):
        capa.dataProvider().addFeatures(entidades)
        capa.updateExtents()
    simbolo = QgsSymbol.defaultSymbol(laterales.geometryType())
    simbolo.setColor(QColor("#3d7a3a"))
    simbolo.setWidth(0.3)
    laterales.setRenderer(QgsSingleSymbolRenderer(simbolo))
    simbolo = QgsSymbol.defaultSymbol(portas.geometryType())
    simbolo.setColor(QColor("#1565c0"))
    simbolo.setWidth(1.4)
    portas.setRenderer(QgsSingleSymbolRenderer(simbolo))
    valvulas.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#c62828", "size": "3", "outline_color": "#ffffff"})))
    return reemplazar_grupo(GRUPO_VISTA_PREVIA, [valvulas, portas, laterales])


def _quitar_grupo(nombre_grupo) -> bool:
    """Quita del proyecto el grupo y sus capas. Devuelve False si no existía."""
    from qgis.core import QgsProject
    proyecto = QgsProject.instance()
    grupo = proyecto.layerTreeRoot().findGroup(nombre_grupo)
    if grupo is None:
        return False
    for nodo in grupo.findLayers():
        proyecto.removeMapLayer(nodo.layerId())
    grupo.parent().removeChildNode(grupo)
    return True


def quitar_vista_previa():
    _quitar_grupo(GRUPO_VISTA_PREVIA)


def nombre_del_lote(entidad) -> str:
    return str(entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}")


def grupo_del_lote(entidad) -> str:
    """Grupo de las capas de resultado del bloque (laterales, portalateral y válvula)."""
    return f"RiegoLibre · {nombre_del_lote(entidad)}"


def eliminar_bloque(capa, entidad, borrar_lote=False):
    """Elimina el bloque de goteo de un lote, como «borrar el bloque» en IRRICAD.

    Quita sus capas de resultado (el grupo «RiegoLibre · nombre») y deja el lote sin diseñar.
    Con `borrar_lote` también se borra el polígono del lote de su capa.
    """
    from .lotes import borrar_parametros
    quitar_vista_previa()
    _quitar_grupo(grupo_del_lote(entidad))
    if not borrar_lote:
        borrar_parametros(capa, entidad.id())
    elif capa.isEditable():
        if not capa.deleteFeature(entidad.id()):
            raise ValueError("No se pudo borrar el lote.")
    else:
        if not capa.dataProvider().deleteFeatures([entidad.id()]):
            raise ValueError(f"No se pudo modificar la capa «{capa.name()}». ¿Es de solo lectura?")
        capa.updateExtents()
        capa.triggerRepaint()


def calcular_bloque(nombre, crs, bloque: Bloque, geometria_lote, config, avisos=None):
    """Calcula la subunidad del bloque y deja sus capas en el grupo «RiegoLibre · nombre»."""
    from dataclasses import replace

    from .calculo_subunidad import calcular_subunidad
    config = replace(config, entrada_m=bloque.valvula_m)
    return calcular_subunidad(nombre, crs, geometria_portalateral(bloque), geometria_lote, laterales_mapa(bloque),
                              config, list(avisos or []) + list(bloque.avisos))


# ------------------------------------------------------------------ subdivisión


def subdividir_en_lote(geometria, bloque: ParametrosBloque, angulo_deg: float,
                       params: ParametrosSubdivision):
    """Sub-bloques del lote: lista de (geometría, SubBloque), ya cortados con el polígono del lote."""
    partes = subdividir(anillos_de_geometria(geometria), bloque, angulo_deg, params)
    resultado = []
    for parte in partes:
        rectangulo = QgsGeometry.fromPolygonXY([[_punto(p) for p in parte.anillo + parte.anillo[:1]]])
        corte = geometria.intersection(rectangulo)
        poligonos = [g for g in corte.asGeometryCollection()
                     if g.type() == Qgis.GeometryType.Polygon and g.area() >= 1.0]
        if not poligonos:
            continue
        corte = QgsGeometry.unaryUnion(poligonos) if len(poligonos) > 1 else poligonos[0]
        resultado.append((corte, parte))
    return resultado


def vista_previa_subdivision(partes, crs):
    capa = _capa("Polygon", "field=parte:integer&field=hileras:integer&field=caudal:double&field=area_m2:double",
                 "Sub-bloques (vista previa)", crs)
    entidades = []
    for i, (geometria, parte) in enumerate(partes, 1):
        e = QgsFeature(capa.fields())
        e.setGeometry(geometria)
        e.setAttributes([i, parte.hileras, round(parte.caudal, 1), round(parte.area_m2, 1)])
        entidades.append(e)
    capa.dataProvider().addFeatures(entidades)
    capa.updateExtents()
    from qgis.core import QgsFillSymbol
    capa.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "255,160,0,70", "outline_color": "230,81,0", "outline_width": "0.6"})))
    return reemplazar_grupo(GRUPO_VISTA_PREVIA, [capa])


def reemplazar_lote_por_partes(capa, entidad, partes, nombres: List[str]) -> List[int]:
    """Reemplaza el lote por sus sub-bloques en la capa de lotes (con los mismos parámetros del bloque)."""
    nuevas = []
    campos = capa.fields()
    for (geometria, _), nombre in zip(partes, nombres):
        nueva = QgsFeature(campos)
        if capa.wkbType() != geometria.wkbType():
            geometria = QgsGeometry(geometria)
            geometria.convertToMultiType()
        nueva.setGeometry(geometria)
        for i in range(campos.count()):
            nombre_campo = campos.at(i).name()
            if nombre_campo == CAMPO_NOMBRE:
                nueva.setAttribute(i, nombre)
            elif nombre_campo == CAMPO_AREA:
                nueva.setAttribute(i, round(geometria.area() / 10000, 4))
            elif nombre_campo.lower() != "fid":  # el GeoPackage numera las entidades nuevas
                nueva.setAttribute(i, entidad[nombre_campo])
        nuevas.append(nueva)
    if capa.isEditable():
        if not capa.addFeatures(nuevas) or not capa.deleteFeature(entidad.id()):
            raise ValueError("No se pudo reemplazar el lote por sus sub-bloques.")
        return [f.id() for f in nuevas]
    proveedor = capa.dataProvider()
    ok, agregadas = proveedor.addFeatures(nuevas)
    if not ok or not proveedor.deleteFeatures([entidad.id()]):
        raise ValueError(f"No se pudo modificar la capa «{capa.name()}». ¿Es de solo lectura?")
    capa.updateExtents()
    capa.triggerRepaint()
    return [f.id() for f in agregadas]


# ------------------------------------------------------------------ parámetros guardados

DIMENSIONADO_COSTO, DIMENSIONADO_VELOCIDAD = "costo", "velocidad"


def _por_nombre(lista, nombre, que):
    for objeto in lista:
        if objeto.nombre == nombre:
            return objeto
    raise ValueError(f"{que} «{nombre}» no está en la base de datos de materiales.")


def parametros_de(v: dict, emisor) -> ParametrosBloque:
    """Parámetros del motor a partir de los valores guardados en un lote (ver `DialogoBloque.valores`)."""
    from .trazado_mapa import funcion_caudal
    automatica = v.get("direccion", "auto") == "auto"
    return ParametrosBloque(
        separacion_m=float(v["separacion_m"]), laterales_por_hilera=int(v.get("laterales_por_hilera", 1)),
        separacion_en_hilera_m=float(v.get("separacion_en_hilera_m", 1.0)),
        cabecera_m=float(v.get("cabecera_m", 0.0)), costados_m=v.get("costados_m"),
        angulo_deg=None if automatica else (90.0 - float(v.get("azimut_deg", 0.0))) % 360.0,
        portalateral=v.get("portalateral", "inicio"),
        distancia_portalateral_m=float(v.get("distancia_portalateral_m", 0.0)),
        valvula=v.get("valvula", "auto"), porcentaje_valvula=float(v.get("porcentaje_valvula", 50.0)),
        punto_valvula=tuple(v["punto_valvula"]) if v.get("punto_valvula") else None,
        caudal_lateral=funcion_caudal(emisor, float(v["espaciamiento_m"]), float(v["primer_emisor_m"])))


def serie_elegida(v: dict, tuberias_portalateral):
    """Serie de tuberías del dimensionado por velocidad (la guardada, o la de menor presión nominal)."""
    from ..nucleo.diametros_velocidad import serie_por_defecto, series_de_tuberias
    series = series_de_tuberias(tuberias_portalateral)
    if not series:
        raise ValueError("No hay tuberías de portalateral en la base de datos.")
    return next((s for s in series if s.clave == v.get("serie")), serie_por_defecto(series))


def config_de(v: dict, tuberias_lateral, emisores, tuberias_portalateral, capa_dem=None):
    """Configuración del cálculo de la subunidad a partir de los valores guardados en un lote."""
    from ..nucleo import CriteriosDiseno
    from ..nucleo.diametros_velocidad import CriterioVelocidad
    from .calculo_subunidad import ConfigCalculo
    tuberia = _por_nombre(tuberias_lateral, v["tuberia"], "La tubería lateral")
    emisor = _por_nombre(emisores, v["emisor"], "El emisor")
    criterios = CriteriosDiseno(
        variacion_caudal_max=float(v.get("variacion_caudal_pct", 10.0)) / 100,
        velocidad_max_ms=float(v.get("velocidad_max_ms", 1.5)),
        presion_entrada_max_m=float(v.get("presion_entrada_max_m") or 0) or None)
    velocidad, tubos, fija = None, tuberias_portalateral, None
    if v.get("dimensionado") == DIMENSIONADO_VELOCIDAD:
        velocidad = CriterioVelocidad(criterios.velocidad_max_ms, int(v.get("diametros_velocidad", 3)),
                                      float(v.get("tramo_min_m", 6.0)), bool(v.get("ajustar_variacion", True)))
        tubos = serie_elegida(v, tuberias_portalateral).tuberias
    elif v.get("tuberia_portalateral"):
        fija = _por_nombre(tuberias_portalateral, v["tuberia_portalateral"], "La tubería del portalateral")
    return ConfigCalculo(
        tuberia_lateral=tuberia, emisor=emisor, espaciamiento_m=float(v["espaciamiento_m"]),
        primer_emisor_m=float(v["primer_emisor_m"]), metodo=v.get("metodo", "darcy"),
        tuberias_portalateral=tubos, criterios=criterios, capa_dem=capa_dem, tuberia_portalateral=fija,
        presion_conocida=v.get("presion_conocida_m"), diametros_max=int(v.get("diametros_max", 1)),
        velocidad=velocidad)


def metros_por_tuberia(diseno) -> dict:
    """{nombre de la tubería: metros} del portalateral de una subunidad calculada."""
    metros = {}
    for rama in diseno.subunidad.ramas:
        for tuberia, a, b in rama.piezas(0.0, rama.longitud_m):
            metros[tuberia.nombre] = metros.get(tuberia.nombre, 0.0) + (b - a)
    return metros


# ------------------------------------------------------------------ recálculo y resumen de una zona

# Claves del lote (JSON) que solo usa la tabla de zonas
PERMITIDA_MIN, PERMITIDA_MAX, RESULTADO = "presion_permitida_min_m", "presion_permitida_max_m", "resultado"


def recalcular_lote(capa, entidad, valores: dict, tuberias_lateral, emisores, tuberias_portalateral,
                    dem_defecto=None):
    """Vuelve a trazar y calcular un lote con los valores dados (los guardados, quizá con cambios).

    Usa la dirección con que se aplicó el bloque (`azimut_usado_deg`), para que el trazado no cambie.
    Devuelve (ResultadoCalculo, ConfigCalculo); lanza ValueError o PresionInsuficiente.
    """
    from qgis.core import QgsProject
    from .trazado_mapa import punto_de_entidad
    proyecto = QgsProject.instance()
    dem = proyecto.mapLayer(valores["dem"]) if valores.get("dem") else None
    dem = dem or dem_defecto
    fuente_capa = proyecto.mapLayer(valores["fuente"]) if valores.get("fuente") else None
    config = config_de(valores, tuberias_lateral, emisores, tuberias_portalateral, dem)
    trazo = dict(valores)
    if valores.get("azimut_usado_deg") is not None:
        trazo.update(direccion="usuario", azimut_deg=valores["azimut_usado_deg"])
    params = parametros_de(trazo, config.emisor)
    fuente = punto_de_entidad(fuente_capa, capa.crs()) if fuente_capa is not None else None
    geometria = entidad.geometry()
    bloque = trazar_en_lote(geometria, params, capa.crs(), dem, fuente)
    nombre = str(entidad[CAMPO_NOMBRE] or f"Lote {entidad.id()}")
    return calcular_bloque(nombre, capa.crs(), bloque, geometria, config), config


def resumen_resultado(r, config, valores: dict) -> dict:
    """Lo que la tabla de zonas muestra de un lote calculado (se guarda en el lote, clave «resultado»)."""
    from ..nucleo.memoria import descripcion_telescopico
    from ..nucleo.subunidad import fuera_de_presiones_permitidas, incumplimientos
    res = r.diseno.resultado
    motivos = incumplimientos(res, config.criterios, r.diseno.tuberia)
    motivos += fuera_de_presiones_permitidas(res.presion_min_emisor_m, res.presion_max_emisor_m,
                                             valores.get(PERMITIDA_MIN), valores.get(PERMITIDA_MAX))
    return {
        "caudal_m3h": round(res.caudal_total_lh / 1000, 3),
        "presion_valvula_m": round(res.presion_entrada_m, 2),
        "h_emisor_min_m": round(res.presion_min_emisor_m, 2),
        "h_emisor_max_m": round(res.presion_max_emisor_m, 2),
        "variacion_caudal": round(res.variacion_caudal, 4), "velocidad_max_ms": round(res.velocidad_max_ms, 3),
        "portalateral": descripcion_telescopico(r.diseno) if r.diseno.telescopico else r.diseno.tuberia.nombre,
        "motivos": motivos,
    }
