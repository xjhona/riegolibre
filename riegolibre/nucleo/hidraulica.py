"""Fórmulas hidráulicas básicas para tuberías a presión.

Unidades (SI) salvo que se indique lo contrario:
    caudal      m³/s
    diámetro    m
    longitud    m
    pérdidas    m.c.a. (metros de columna de agua)
"""

import math

G = 9.81  # m/s²
VISCOSIDAD_CINEMATICA_20C = 1.004e-6  # m²/s, agua a 20 °C

LH_A_M3S = 1.0 / 3.6e6  # 1 L/h expresado en m³/s


def area(diametro):
    return math.pi * diametro * diametro / 4.0


def velocidad(caudal, diametro):
    return caudal / area(diametro)


def reynolds(caudal, diametro, viscosidad=VISCOSIDAD_CINEMATICA_20C):
    return abs(velocidad(caudal, diametro)) * diametro / viscosidad


def _friccion_turbulenta(re, rugosidad_relativa):
    """Swamee-Jain: aproximación explícita de Colebrook-White (error < 1 %)."""
    return 0.25 / math.log10(rugosidad_relativa / 3.7 + 5.74 / re ** 0.9) ** 2


def factor_friccion(re, rugosidad_relativa=0.0):
    """Factor de fricción de Darcy.

    - Laminar (Re < 2000): f = 64/Re
    - Turbulento (Re > 4000): Swamee-Jain
    - Transición: interpolación lineal entre ambos extremos.
    """
    if re <= 0:
        return 0.0
    if re < 2000:
        return 64.0 / re
    if re < 4000:
        f_lam = 64.0 / 2000
        f_tur = _friccion_turbulenta(4000, rugosidad_relativa)
        return f_lam + (f_tur - f_lam) * (re - 2000) / 2000
    return _friccion_turbulenta(re, rugosidad_relativa)


def perdida_darcy(caudal, diametro, longitud, rugosidad=0.0,
                  viscosidad=VISCOSIDAD_CINEMATICA_20C):
    """Pérdida por fricción con Darcy-Weisbach (rugosidad absoluta en m)."""
    if caudal == 0 or longitud == 0:
        return 0.0
    re = reynolds(caudal, diametro, viscosidad)
    f = factor_friccion(re, rugosidad / diametro)
    v = velocidad(abs(caudal), diametro)
    return math.copysign(f * longitud / diametro * v * v / (2 * G), caudal)


def perdida_hazen_williams(caudal, diametro, longitud, c):
    """Pérdida por fricción con Hazen-Williams."""
    if caudal == 0 or longitud == 0:
        return 0.0
    hf = 10.674 * longitud * abs(caudal) ** 1.852 / (c ** 1.852 * diametro ** 4.871)
    return math.copysign(hf, caudal)


def perdida_localizada(caudal, diametro, k):
    """Pérdida localizada k·v²/2g."""
    v = velocidad(caudal, diametro)
    return k * v * v / (2 * G)


def factor_christiansen(n_salidas, m=1.852, primera_salida_a_medio_espaciamiento=False):
    """Factor F de Christiansen para tuberías con salidas múltiples equidistantes.

    m: exponente del caudal en la fórmula de pérdidas (1.852 Hazen-Williams,
    1.75 Blasius, 2 Darcy turbulento rugoso).
    """
    n = n_salidas
    f = 1.0 / (m + 1) + 1.0 / (2 * n) + math.sqrt(m - 1) / (6 * n * n)
    if primera_salida_a_medio_espaciamiento:
        f = (2 * n * f - 1) / (2 * n - 1)
    return f


def interpolar_perfil(perfil, distancia):
    """Interpola la cota de un perfil [(distancia, cota), ...] ordenado por distancia.

    Fuera del rango se mantiene la cota del extremo más cercano.
    """
    if distancia <= perfil[0][0]:
        return perfil[0][1]
    if distancia >= perfil[-1][0]:
        return perfil[-1][1]
    bajo, alto = 0, len(perfil) - 1
    while alto - bajo > 1:
        medio = (bajo + alto) // 2
        if perfil[medio][0] <= distancia:
            bajo = medio
        else:
            alto = medio
    (x0, z0), (x1, z1) = perfil[bajo], perfil[alto]
    if x1 == x0:
        return z0
    return z0 + (z1 - z0) * (distancia - x0) / (x1 - x0)


class PresionInsuficiente(ValueError):
    """La presión disponible no alcanza para presurizar toda la tubería."""


def resolver_creciente(funcion, objetivo, x_bajo, x_alto, tolerancia=1e-4,
                       max_iteraciones=200, x_limite=1e4):
    """Encuentra x tal que funcion(x) = objetivo, con funcion no decreciente.

    Usa regula falsi (variante Illinois). Si funcion(x_bajo) ya supera el objetivo
    lanza PresionInsuficiente; x_alto se amplía automáticamente si hace falta.
    """
    f_bajo = funcion(x_bajo) - objetivo
    if f_bajo > tolerancia:
        raise PresionInsuficiente(
            "No hay solución: incluso con la presión mínima posible se supera el objetivo.")
    if abs(f_bajo) <= tolerancia:
        return x_bajo
    f_alto = funcion(x_alto) - objetivo
    while f_alto < 0:
        x_bajo, f_bajo = x_alto, f_alto
        x_alto *= 2
        if x_alto > x_limite:
            raise ValueError("No se encontró solución dentro de un rango razonable de presiones.")
        f_alto = funcion(x_alto) - objetivo

    lado = 0
    x = x_alto
    for _ in range(max_iteraciones):
        if f_alto == f_bajo:
            break
        x = x_alto - f_alto * (x_alto - x_bajo) / (f_alto - f_bajo)
        fx = funcion(x) - objetivo
        if abs(fx) <= tolerancia or (x_alto - x_bajo) < 1e-9:
            return x
        if fx > 0:
            x_alto, f_alto = x, fx
            if lado == 1:
                f_bajo /= 2
            lado = 1
        else:
            x_bajo, f_bajo = x, fx
            if lado == -1:
                f_alto /= 2
            lado = -1
    return x
