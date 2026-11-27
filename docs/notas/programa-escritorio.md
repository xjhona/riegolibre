# Programa de escritorio sin QGIS (`riegolibre_escritorio/`)

Pedido del usuario el 2026-11-26: un programa tipo IRRICAD que se instale y corra **sin QGIS**. El prototipo
`riegolibre_app/` (ventana propia sobre las librerías de QGIS) queda solo como referencia de menús y flujos.

## Arquitectura aprobada (2026-11-26)
- PySide6 (Qt) con lienzo propio sobre `QGraphicsView`; nada de `import qgis` (`tests/test_escritorio.py` lo revisa).
- Cálculo: `riegolibre/nucleo` tal cual; geometría (bloque, subdivisión, conector de válvulas): `mcp_riegolibre/motor.py`.
  El núcleo y el motor solo usan la biblioteca estándar: el único requisito es `PySide6-Essentials`
  (`requisitos_escritorio.txt`).
- Proyecto: archivo `.riegolibre` = SQLite con los datos del diseño (formato del `…_datos.json` del MCP), parámetros
  de la red, estilos de la barra de capas, archivos (el DEM) y, de copia, el resumen y las geometrías en GeoJSON. Al
  abrir se vuelve a calcular desde los datos.
- Tema: el de `riegolibre/gui/tema.py` (solo `PALETAS` y `hoja_de_estilo`, que no importan QGIS); textos propios de Qt
  en español con `qtbase_es.qm` (`estilo.traducir_qt`).
- Pendiente por etapas: 2) edición (dibujar lotes, fuente, matriz con imán, deshacer, bloque por lote, info, tabla);
  3) terreno (DEM .tif, DXF con ezdxf, pyproj, satelital); 4) ventanas del complemento (subunidad, turnos,
  materiales, memoria, base de datos); 5) planos PDF y exportar DXF/GeoJSON; 6) PyInstaller + instalador e iconos.

## Decisiones del usuario
- **Barra de capas como la «Layer Bar» de IRRICAD**, no como el panel de QGIS (2026-11-26, con capturas de IRRICAD):
  capas fijas en mayúsculas, una fila compacta cada una, columnas ver (👁) e imprimir (🖨), y debajo «Propiedades de
  la capa» (color, tipo de línea, grosor). Sin leyendas desplegables; los diámetros de la red van en la descripción
  emergente de RED_PRINCIPAL. Código: `capas.py` (sin Qt) y `barra_capas.py`.

## Números de referencia (Fundo demo, `muestras/demo_mcp/Fundo_demo_datos.json`)
- Complemento en QGIS (importar + «Red principal y bomba» con valores por omisión): 31.257 L/s, **CDT 30.056 m,
  13.166 kW**; 140 mm 681.7 m, 200 mm 14.1 m, 63 mm 432.5 m, 90 mm 375.1 m.
- Programa de escritorio: 31.26 L/s, **CDT 30.042 m, 13.16 kW**, mismos metros. Válvulas a menos de 0.015 m: el
  complemento lee el plano como DEM `.asc` por celda; el programa usa el plano exacto.
- Diferencia de 2 m que se vio al principio: la ventana de la red del complemento empieza con **pérdida en cada válvula
  = 2 m** y el servidor MCP con 0 m. El programa usa 2 m salvo que el diseño traiga `red.perdida_valvula_m`.

## Trampas
- Diseñar el Fundo demo tarda unos 9 s (todo en Python puro): importar y abrir corren en un hilo (`en_segundo_plano`).
- `pythonw.exe` no muestra errores: para depurar, `python -m riegolibre_escritorio`.
- El emisor del diseño debe estar en la base de datos de materiales del equipo; el `.riegolibre` todavía no lleva el
  catálogo adentro (abrirlo en otro equipo sin esa base falla).
- `Tuberia` no es hashable (tiene una lista): agrupar por nombre.
- Computer use: la ventana es de `pythonw.exe` (pedir acceso con ese nombre); el cuadro Guardar no acepta rutas en
  la carpeta temporal de Claude.
