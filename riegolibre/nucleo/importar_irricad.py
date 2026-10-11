"""Importación de una base de datos de IRRICAD (.mdb) a la base de RiegoLibre.

IRRICAD guarda casi todo en la tabla «Components»: la columna «Database Number» dice a
qué pestaña pertenece cada registro y los valores van en columnas genéricas (Reals1-8,
Rextra1-4) cuyo significado depende de la pestaña. Los laterales con gotero («Tapes»)
tienen además una fila en la tabla «Tapes» con los datos del emisor.

Se importan las pestañas Pipes, Tapes, Valves y Other Hydraulics.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List

from .base_datos import BaseDatos, Cinta, ElementoHidraulico, RegistroTuberia
from .mdb import BaseAccess, ErrorMdb

PESTANA_TUBERIAS = 1  # tuberías y laterales con gotero
PESTANA_VALVULAS = 2
PESTANA_HIDRAULICOS = 3
PESTANA_SIN_TUBERIA = 5  # registro «*** NO PIPE SELECTED ***»

USOS = {"L": "lateral", "Z": "portalateral", "M": "principal", "F": "lavado"}
MATERIALES = {"PVC": "PVC", "HDP": "PEAD", "HDPE": "PEAD", "MDP": "PE", "LDP": "PE", "LDPE": "PE",
              "LPE": "PE", "DLN": "PE", "PE": "PE", "LFT": "Layflat", "IRN": "Hierro",
              "GAL": "Hierro galvanizado", "STL": "Acero", "ALU": "Aluminio", "AC": "Asbesto cemento"}
RUGOSIDAD_MM = {"Hierro": 0.15, "Hierro galvanizado": 0.15, "Acero": 0.045, "Asbesto cemento": 0.025}
RUGOSIDAD_PLASTICO_MM = 0.0015


@dataclass
class ResultadoImportacion:
    base: BaseDatos
    avisos: List[str] = field(default_factory=list)
    omitidos_por_pestana: Dict[int, int] = field(default_factory=dict)  # pestañas no importadas


def _texto(fila, columna):
    return (fila.get(columna) or "").strip()


def _numero(fila, columna):
    valor = fila.get(columna)
    return float(valor) if valor is not None else 0.0


def _positivo(fila, columna):
    """El valor, o None si es cero o negativo (IRRICAD usa 0 para «sin dato»)."""
    valor = _numero(fila, columna)
    return valor if valor > 0 else None


def _nombre_unico(nombre, usados):
    """Hace único un nombre repetido añadiendo « (2)», « (3)»…"""
    nombre = nombre or "Sin nombre"
    candidato, n = nombre, 1
    while candidato.casefold() in usados:
        n += 1
        candidato = f"{nombre} ({n})"
    usados.add(candidato.casefold())
    return candidato


def _material(codigo):
    return MATERIALES.get(codigo.upper(), codigo or "PE")


def _tuberia(fila, nombre):
    material = _material(_texto(fila, "Major1"))
    return RegistroTuberia(
        nombre=nombre,
        diametro_interior_mm=_numero(fila, "Reals2"),
        material=material,
        usos=[USOS[letra] for letra in _texto(fila, "Usage").upper() if letra in USOS],
        diametro_nominal_mm=_positivo(fila, "Reals1"),
        rugosidad_mm=RUGOSIDAD_MM.get(material, RUGOSIDAD_PLASTICO_MM),
        c_hazen=_positivo(fila, "Reals3") or 140.0,
        presion_nominal_m=_positivo(fila, "Reals4"),
        etiqueta=_texto(fila, "Major2"),
        codigo=_texto(fila, "Warehouse Code"),
        proveedor=_texto(fila, "Supplier Code"),
        costo_m=_numero(fila, "Reals7"),
        precio_m=_numero(fila, "Reals8"))


def _cinta(fila, emisor, nombre):
    return Cinta(
        nombre=nombre,
        diametro_interior_mm=_numero(fila, "Reals2"),
        k_emisor=_numero(emisor, "Reals1"),
        exponente_emisor=_numero(emisor, "Reals2"),
        espaciamiento_m=_numero(emisor, "Reals4"),
        diametro_nominal_mm=_positivo(fila, "Reals1"),
        c_hazen=_positivo(fila, "Reals3") or 140.0,
        presion_nominal_m=_positivo(fila, "Reals4"),
        longitud_equivalente_m=_numero(emisor, "Reals3"),
        cv=_numero(fila, "Rextra3"),
        presion_entrada_m=_positivo(emisor, "Reals5") or 10.0,
        presion_min_m=_positivo(emisor, "Rextra1"),
        presion_max_m=_positivo(emisor, "Rextra2"),
        presion_min_compensacion_m=_positivo(fila, "Rextra4"),
        tolerancia_sobre_pct=_numero(emisor, "Rextra3"),
        tolerancia_bajo_pct=_numero(emisor, "Rextra4"),
        tipo_tuberia=_texto(fila, "Major1"),
        seleccionable="L" in _texto(fila, "Usage").upper(),
        etiqueta=_texto(fila, "Major2"),
        codigo=_texto(fila, "Warehouse Code"),
        proveedor=_texto(fila, "Supplier Code"),
        costo_m=_numero(fila, "Reals7"),
        precio_m=_numero(fila, "Reals8"))


def _elemento(fila, nombre):
    return ElementoHidraulico(
        nombre=nombre,
        k=_numero(fila, "Reals3"),
        n=_numero(fila, "Reals4"),
        c=_numero(fila, "Reals5"),
        diametro_entrada_mm=_positivo(fila, "Reals1"),
        diametro_salida_mm=_positivo(fila, "Reals2"),
        conexion_entrada=" ".join(_texto(fila, "Major1").split()),
        conexion_salida=" ".join(_texto(fila, "Minor1").split()),
        caudal_min_m3h=_numero(fila, "Rextra1"),
        caudal_max_m3h=_positivo(fila, "Rextra2"),
        seleccionable="Y" in _texto(fila, "Usage").upper(),
        etiqueta=_texto(fila, "Major2"),
        codigo=_texto(fila, "Warehouse Code"),
        proveedor=_texto(fila, "Supplier Code"),
        costo=_numero(fila, "Reals7"),
        precio=_numero(fila, "Reals8"))


def importar_irricad(ruta) -> ResultadoImportacion:
    """Lee un .mdb de IRRICAD y devuelve la base de RiegoLibre equivalente (sin guardarla)."""
    access = BaseAccess(ruta)
    if "Components" not in access.tablas():
        raise ErrorMdb("El archivo no parece una base de datos de IRRICAD (no tiene la tabla «Components»).")
    componentes = access.filas("Components")
    faltan = {"Component Key", "Database Number", "Description", "Reals1"} - set(access.columnas("Components"))
    if faltan:
        raise ErrorMdb("La tabla «Components» no tiene las columnas de IRRICAD: " + ", ".join(sorted(faltan)))
    emisores = {}
    if "Tapes" in access.tablas():
        emisores = {f["Pipe Key"]: f for f in access.filas("Tapes")}

    componentes.sort(key=lambda f: f.get("Component Key") or 0)
    base = BaseDatos(origen=f"IRRICAD: {os.path.basename(ruta)}")
    resultado = ResultadoImportacion(base)
    nombres_tuberias, nombres_valvulas, nombres_hidraulicos = set(), set(), set()
    for fila in componentes:
        pestana = fila.get("Database Number")
        descripcion = _texto(fila, "Description")
        if pestana == PESTANA_TUBERIAS:
            emisor = emisores.get(fila.get("Component Key"))
            if _numero(fila, "Reals2") <= 0:
                resultado.avisos.append(f"«{descripcion}»: sin diámetro interior, no se importó.")
                continue
            if emisor is None:
                base.tuberias.append(_tuberia(fila, _nombre_unico(descripcion, nombres_tuberias)))
            elif _numero(emisor, "Reals1") <= 0 or _numero(emisor, "Reals4") <= 0:
                resultado.avisos.append(f"«{descripcion}»: lateral sin caudal o sin espaciamiento "
                                        "de emisores, no se importó.")
            else:
                base.cintas.append(_cinta(fila, emisor, _nombre_unico(descripcion, nombres_tuberias)))
        elif pestana == PESTANA_VALVULAS:
            base.valvulas.append(_elemento(fila, _nombre_unico(descripcion, nombres_valvulas)))
        elif pestana == PESTANA_HIDRAULICOS:
            base.hidraulicos.append(_elemento(fila, _nombre_unico(descripcion, nombres_hidraulicos)))
        elif pestana != PESTANA_SIN_TUBERIA:
            resultado.omitidos_por_pestana[pestana] = resultado.omitidos_por_pestana.get(pestana, 0) + 1

    base.tuberias.sort(key=lambda t: (t.material, t.diametro_nominal_mm or t.diametro_interior_mm,
                                      t.presion_nominal_m or 0.0, t.nombre.casefold()))
    for lista in (base.cintas, base.valvulas, base.hidraulicos):
        lista.sort(key=lambda r: r.nombre.casefold())
    return resultado
