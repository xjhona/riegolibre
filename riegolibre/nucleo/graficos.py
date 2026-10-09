"""Gráficos de resultados con matplotlib (opcional: sin matplotlib no se dibuja nada).

Las funciones dibujar_* reciben una Figure de matplotlib, de modo que sirven
tanto para las ventanas (lienzo de Qt) como para las imágenes de la memoria.
"""

import io


def puntos_perfil_subunidad(resultado):
    """[(posición desde la entrada, presión en el portalateral, h mín., h máx., cota)] ordenados.

    La posición es negativa en la rama que va hacia el inicio del portalateral.
    """
    puntos = []
    for rama in resultado.ramas:
        for i, d in enumerate(rama.distancias_m):
            puntos.append((rama.sentido * d, rama.presiones_m[i], rama.h_min_m[i],
                           rama.h_max_m[i], rama.cotas_m[i]))
    return sorted(puntos, key=lambda p: p[0])


def referencia_emisor(emisor):
    """(presión, etiqueta) de la línea de referencia del emisor en el gráfico."""
    if emisor.autocompensado:
        return emisor.presion_compensacion_m, "Inicio de compensación"
    return emisor.presion_nominal_m, "Presión nominal"


def dibujar_perfil_subunidad(figura, puntos, presion_entrada_m, referencia_m, etiqueta_referencia):
    """Presión a lo largo del portalateral y rango de presión en los emisores."""
    todos = sorted(list(puntos) + [(0.0, presion_entrada_m, None, None, 0.0)], key=lambda p: p[0])
    x = [p[0] for p in todos]
    con_emisores = [p for p in todos if p[2] is not None]
    figura.clear()
    ejes = figura.add_subplot(111)
    ejes.plot(x, [p[1] for p in todos], color="#1e88e5", label="Presión en el portalateral")
    ejes.fill_between([p[0] for p in con_emisores], [p[2] for p in con_emisores],
                      [p[3] for p in con_emisores], color="#43a047", alpha=0.25,
                      label="Presión en emisores (mín.–máx.)")
    ejes.plot([0], [presion_entrada_m], "o", color="#c62828", label="Entrada (válvula)")
    ejes.axhline(referencia_m, color="#43a047", linestyle=":", label=etiqueta_referencia)
    ejes.set_xlabel("Posición a lo largo del portalateral, desde la entrada (m)")
    ejes.set_ylabel("Presión (m.c.a.)")
    ejes.grid(True, alpha=0.3)

    terreno = ejes.twinx()
    terreno.plot(x, [p[4] for p in todos], color="#6d4c41", linewidth=1, label="Terreno (relativo)")
    terreno.set_ylabel("Cota relativa (m)")
    lineas = ejes.get_legend_handles_labels()
    lineas_t = terreno.get_legend_handles_labels()
    ejes.legend(lineas[0] + lineas_t[0], lineas[1] + lineas_t[1], loc="best", fontsize=8)


def dibujar_perfil_red(figura, perfil):
    """Terreno y línea piezométrica de la ruta crítica (perfil: PerfilRuta o su dict)."""
    p = perfil if isinstance(perfil, dict) else vars(perfil)
    x, terreno = p["distancias_m"], p["terreno_m"]
    figura.clear()
    ejes = figura.add_subplot(111)
    ejes.fill_between(x, min(terreno) - 1, terreno, color="#8d6e63", alpha=0.35, label="Terreno")
    ejes.plot(x, p["piezometrica_m"], color="#1e88e5", label="Línea piezométrica")
    ejes.plot([x[-1]], [p["carga_requerida_m"]], "o", color="#c62828",
              label=f"Carga requerida en {p['valvula']}")
    ejes.plot([0], [p["carga_fuente_m"]], "s", color="#1565c0", label="Salida del cabezal")
    ejes.set_xlabel("Distancia desde la fuente (m)")
    ejes.set_ylabel("Cota (m)")
    ejes.set_title(f"Ruta crítica del turno {p['turno']}", fontsize=10)
    ejes.grid(True, alpha=0.3)
    ejes.legend(loc="best", fontsize=8)


def png(dibujar, *argumentos, ancho_pulg=7.0, alto_pulg=3.2, dpi=150):
    """Dibuja en una figura nueva y la devuelve como PNG (bytes), o None sin matplotlib."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None
    figura = Figure(figsize=(ancho_pulg, alto_pulg), dpi=dpi, layout="constrained")
    FigureCanvasAgg(figura)
    dibujar(figura, *argumentos)
    salida = io.BytesIO()
    figura.savefig(salida, format="png")
    return salida.getvalue()
