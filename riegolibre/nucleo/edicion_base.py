"""Edición de la base de datos de materiales: campos de cada formulario, validación, copias.

La ventana (`gui/dialogo_base_datos.py`) arma el formulario de cada registro con `CAMPOS` y
usa estas funciones para comprobar y guardar los cambios, de modo que la lógica se prueba
sin QGIS.
"""

import copy
from dataclasses import dataclass
from typing import List, Optional

from .base_datos import BaseDatos, Cinta, ElementoHidraulico, RegistroTuberia

TEXTO, NUMERO, NUMERO_OPCIONAL, SI_NO, USOS = "texto", "numero", "numero_opcional", "si_no", "usos"
USOS_TUBERIA = ("lateral", "portalateral", "principal", "lavado")
CATEGORIAS = ("tuberias", "cintas", "valvulas", "hidraulicos")
TITULOS = {"tuberias": "Tuberías", "cintas": "Laterales con gotero", "valvulas": "Válvulas",
           "hidraulicos": "Otros hidráulicos"}
CLASES = {"tuberias": RegistroTuberia, "cintas": Cinta, "valvulas": ElementoHidraulico,
          "hidraulicos": ElementoHidraulico}
NOMBRES_NUEVOS = {"tuberias": "Tubería nueva", "cintas": "Lateral nuevo", "valvulas": "Válvula nueva",
                  "hidraulicos": "Elemento nuevo"}


@dataclass(frozen=True)
class Campo:
    nombre: str  # atributo del registro
    etiqueta: str
    tipo: str
    ayuda: str = ""
    decimales: int = 3


_COMERCIAL_TUBERIA = [
    Campo("etiqueta", "Etiqueta", TEXTO, "Texto corto para los rótulos del plano, p. ej. 63/5."),
    Campo("proveedor", "Proveedor", TEXTO), Campo("codigo", "Código de almacén", TEXTO),
    Campo("costo_m", "Costo por metro", NUMERO, decimales=4),
    Campo("precio_m", "Precio por metro", NUMERO, "Precio de venta; es el que usa la lista de materiales.",
          decimales=4),
]
_COMERCIAL_ELEMENTO = [
    Campo("etiqueta", "Etiqueta", TEXTO), Campo("proveedor", "Proveedor", TEXTO),
    Campo("codigo", "Código de almacén", TEXTO), Campo("costo", "Costo", NUMERO, decimales=2),
    Campo("precio", "Precio", NUMERO, "Precio de venta; es el que usa la lista de materiales.", decimales=2),
]
_ELEMENTO = [
    Campo("nombre", "Descripción", TEXTO),
    Campo("seleccionable", "Seleccionable en las ventanas", SI_NO),
    Campo("k", "K", NUMERO, "Pérdida de carga H = K·Qⁿ + C, con H en m y Q en m³/h.", decimales=8),
    Campo("n", "n (exponente)", NUMERO, decimales=5),
    Campo("c", "C (m)", NUMERO, "Pérdida constante que se suma.", decimales=3),
    Campo("caudal_min_m3h", "Caudal mínimo (m³/h)", NUMERO_OPCIONAL, "Vacío: sin límite."),
    Campo("caudal_max_m3h", "Caudal máximo (m³/h)", NUMERO_OPCIONAL, "Vacío: sin límite."),
    Campo("diametro_entrada_mm", "Diámetro de entrada (mm)", NUMERO_OPCIONAL),
    Campo("diametro_salida_mm", "Diámetro de salida (mm)", NUMERO_OPCIONAL),
    Campo("conexion_entrada", "Conexión de entrada", TEXTO),
    Campo("conexion_salida", "Conexión de salida", TEXTO),
] + _COMERCIAL_ELEMENTO

CAMPOS = {
    "tuberias": [
        Campo("nombre", "Descripción", TEXTO),
        Campo("usos", "Uso", USOS, "Dónde puede elegirse esta tubería. Sin ninguno, no aparece en las ventanas."),
        Campo("material", "Material", TEXTO, "PVC, PE, PEAD, Hierro…"),
        Campo("diametro_nominal_mm", "Diámetro nominal (mm)", NUMERO_OPCIONAL),
        Campo("diametro_interior_mm", "Diámetro interior (mm)", NUMERO, decimales=2),
        Campo("c_hazen", "C de Hazen-Williams", NUMERO, decimales=0),
        Campo("rugosidad_mm", "Rugosidad (mm)", NUMERO, "Para Darcy-Weisbach.", decimales=4),
        Campo("presion_nominal_m", "Presión admisible (m)", NUMERO_OPCIONAL),
    ] + _COMERCIAL_TUBERIA,
    "cintas": [
        Campo("nombre", "Descripción", TEXTO),
        Campo("seleccionable", "Seleccionable en las ventanas", SI_NO),
        Campo("k_emisor", "k del emisor", NUMERO, "q = k·hˣ, con q en L/h y h en m. Con x = 0, k es el caudal.",
              decimales=4),
        Campo("exponente_emisor", "x del emisor", NUMERO, "0 = autocompensado.", decimales=4),
        Campo("espaciamiento_m", "Espaciamiento de emisores (m)", NUMERO),
        Campo("presion_entrada_m", "Presión de entrada (m)", NUMERO, "Presión a la que se da el caudal nominal."),
        Campo("diametro_nominal_mm", "Diámetro nominal (mm)", NUMERO_OPCIONAL),
        Campo("diametro_interior_mm", "Diámetro interior (mm)", NUMERO, decimales=2),
        Campo("c_hazen", "C de Hazen-Williams", NUMERO, decimales=0),
        Campo("rugosidad_mm", "Rugosidad (mm)", NUMERO, decimales=4),
        Campo("presion_nominal_m", "Presión admisible de la manguera (m)", NUMERO_OPCIONAL),
        Campo("longitud_equivalente_m", "Factor de inserción (m)", NUMERO,
              "Longitud equivalente de pérdida por cada emisor («barb factor»)."),
        Campo("cv", "Coeficiente de variación", NUMERO, "De fabricación."),
        Campo("presion_min_m", "Presión mínima (m)", NUMERO_OPCIONAL),
        Campo("presion_max_m", "Presión máxima (m)", NUMERO_OPCIONAL),
        Campo("presion_min_compensacion_m", "Presión mínima de compensación (m)", NUMERO_OPCIONAL,
              "Desde donde compensa (emisores autocompensados)."),
        Campo("tolerancia_sobre_pct", "Tolerancia de presión por encima (%)", NUMERO),
        Campo("tolerancia_bajo_pct", "Tolerancia de presión por debajo (%)", NUMERO),
        Campo("tipo_tuberia", "Tipo de tubería", TEXTO, "Código de IRRICAD (LDP, DLN…)."),
    ] + _COMERCIAL_TUBERIA,
    "valvulas": _ELEMENTO,
    "hidraulicos": _ELEMENTO,
}


def registros(base: BaseDatos, categoria: str) -> list:
    return getattr(base, categoria)


def base_nueva() -> BaseDatos:
    """Base vacía para quien quiere armar sus materiales sin importar la de IRRICAD."""
    return BaseDatos(origen="Creada en RiegoLibre")


def registro_nuevo(categoria: str, base: BaseDatos):
    """Registro con valores razonables para empezar a llenarlo."""
    nombre = nombre_libre(base, categoria, NOMBRES_NUEVOS[categoria])
    if categoria == "tuberias":
        return RegistroTuberia(nombre=nombre, diametro_interior_mm=0.0, material="PVC", usos=["principal"])
    if categoria == "cintas":
        return Cinta(nombre=nombre, diametro_interior_mm=0.0, k_emisor=0.0, exponente_emisor=0.0,
                     espaciamiento_m=0.0)
    return ElementoHidraulico(nombre=nombre, n=2.0)


def nombre_libre(base: BaseDatos, categoria: str, nombre: str) -> str:
    """Hace único el nombre dentro de la pestaña: «X», «X (2)», «X (3)»…"""
    usados = {r.nombre.casefold() for r in registros(base, categoria)}
    candidato, n = nombre, 1
    while candidato.casefold() in usados:
        n += 1
        candidato = f"{nombre} ({n})"
    return candidato


def duplicar(base: BaseDatos, categoria: str, registro):
    """Copia del registro con otro nombre, sin agregarla a la base."""
    copia = copy.deepcopy(registro)
    copia.nombre = nombre_libre(base, categoria, f"{registro.nombre} (copia)")
    return copia


def validar(base: BaseDatos, categoria: str, registro, original=None) -> List[str]:
    """Errores que impiden guardar el registro (lista vacía si está bien).

    `original` es el registro que se está editando, para no tomar su propio nombre como repetido.
    """
    errores = []
    nombre = (registro.nombre or "").strip()
    if not nombre:
        errores.append("Escriba la descripción.")
    elif any(r is not original and r.nombre.casefold() == nombre.casefold()
             for r in registros(base, categoria)):
        errores.append(f"Ya existe «{nombre}» en esta pestaña.")
    if categoria in ("tuberias", "cintas"):
        if registro.diametro_interior_mm <= 0:
            errores.append("El diámetro interior debe ser mayor que cero.")
        if registro.c_hazen <= 0:
            errores.append("La C de Hazen-Williams debe ser mayor que cero.")
    if categoria == "cintas":
        if registro.k_emisor <= 0:
            errores.append("La k del emisor debe ser mayor que cero.")
        if registro.espaciamiento_m <= 0:
            errores.append("El espaciamiento de emisores debe ser mayor que cero.")
        if registro.presion_entrada_m <= 0:
            errores.append("La presión de entrada debe ser mayor que cero.")
        _rango(errores, "presión", registro.presion_min_m, registro.presion_max_m)
    if categoria in ("valvulas", "hidraulicos"):
        _rango(errores, "caudal", registro.caudal_min_m3h, registro.caudal_max_m3h)
    for campo in CAMPOS[categoria]:
        if campo.tipo in (NUMERO, NUMERO_OPCIONAL):
            valor = getattr(registro, campo.nombre)
            if valor is not None and valor < 0:
                errores.append(f"«{campo.etiqueta}» no puede ser negativo.")
    return errores


def _rango(errores, titulo, minimo: Optional[float], maximo: Optional[float]):
    if minimo and maximo and minimo > maximo:
        errores.append(f"El {titulo} mínimo es mayor que el máximo.")


def guardar_registro(base: BaseDatos, categoria: str, registro, original=None):
    """Agrega el registro a la base o, si se editaba `original`, lo reemplaza en su lugar."""
    lista = registros(base, categoria)
    if original is None:
        lista.append(registro)
        return
    for i, existente in enumerate(lista):
        if existente is original:
            lista[i] = registro
            return
    lista.append(registro)


def eliminar_registros(base: BaseDatos, categoria: str, a_borrar) -> int:
    """Quita de la base los registros indicados (por identidad) y devuelve cuántos quitó."""
    ids = {id(r) for r in a_borrar}
    lista = registros(base, categoria)
    quedan = [r for r in lista if id(r) not in ids]
    cuantos = len(lista) - len(quedan)
    lista[:] = quedan
    return cuantos
