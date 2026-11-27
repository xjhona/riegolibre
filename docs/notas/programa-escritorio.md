# Programa de escritorio sin QGIS (`riegolibre_escritorio/`)

Pedido del usuario el 2026-11-26: un programa tipo IRRICAD que se instale y corra **sin QGIS**. El prototipo
`riegolibre_app/` (ventana propia sobre las librerías de QGIS) queda solo como referencia de menús y flujos.

## Arquitectura aprobada (2026-11-26)
- PySide6 (Qt) con lienzo propio sobre `QGraphicsView`; nada de `import qgis` (`tests/test_escritorio.py` lo revisa).
- Cálculo: `riegolibre/nucleo` tal cual; geometría (bloque, subdivisión, conector de válvulas): `mcp_riegolibre/motor.py`.
  El núcleo y el motor solo usan la biblioteca estándar. Requisitos del programa (`requisitos_escritorio.txt`):
  `PySide6-Essentials` y, para las curvas de nivel, `ezdxf`, `numpy` y `scipy` (decisión del usuario, 2026-11-27:
  librerías estándar antes que un lector propio; solo las importa `topografia.py`, y tarde).
- Proyecto: archivo `.riegolibre` = SQLite con los datos del diseño (formato del `…_datos.json` del MCP), parámetros
  de la red, estilos de la barra de capas, archivos (el DEM) y, de copia, el resumen y las geometrías en GeoJSON. Al
  abrir se vuelve a calcular desde los datos.
- Tema: el de `riegolibre/gui/tema.py` (solo `PALETAS` y `hoja_de_estilo`, que no importan QGIS); textos propios de Qt
  en español con `qtbase_es.qm` (`estilo.traducir_qt`).
- Pendiente por etapas: 2) edición (dibujar lotes, fuente, matriz con imán, deshacer, bloque por lote, info, tabla);
  3) terreno (curvas de DXF: hecho; falta DEM .tif, pyproj, satelital); 4) ventanas del complemento (subunidad, turnos,
  materiales, memoria, base de datos); 5) planos PDF y exportar DXF/GeoJSON; 6) PyInstaller + instalador e iconos.

## Decisiones del usuario
- **Barra de capas como la «Layer Bar» de IRRICAD**, no como el panel de QGIS (2026-11-26, con capturas de IRRICAD):
  capas fijas en mayúsculas, una fila compacta cada una, columnas ver (👁) e imprimir (🖨), y debajo «Propiedades de
  la capa» (color, tipo de línea, grosor). Sin leyendas desplegables; los diámetros de la red van en la descripción
  emergente de RED_PRINCIPAL. Código: `capas.py` (sin Qt) y `barra_capas.py`.

## Etapa 2: edición en el mapa (2026-11-26)
- El usuario aprobó el plan sin cambios (barra vertical, imán, deshacer, bloque por lote, info, tabla, proyecto nuevo).
  No respondió si el bloque se dibuja antes o después del cuadro: se hizo como el complemento (se dibuja el lote y al
  cerrarlo se abre su «Bloque de goteo»). Por confirmar con un video de IRRICAD.
- Módulos: `edicion.py` (sin Qt: imán, objeto bajo el cursor, cambios que devuelven datos nuevos), `herramientas.py`
  (herramientas del lienzo; la ventana es su «editor»), `dialogo_bloque.py`, `dialogos.py` (nuevo, turnos, ficha,
  tabla de atributos), `fichas.py` (sin Qt: «Información del objeto» con `riegolibre/nucleo/ficha.py`).
- Deshacer: `QUndoStack` con la copia de los datos de antes y de después (`CambioDatos`). `ProyectoRiego.disenar`
  guarda los lotes calculados por sus datos (lote, goteo, terreno y, solo con válvula automática, la fuente): editar
  un lote del Fundo demo tarda ~3.5 s y deshacer es inmediato. La red tarda milisegundos: si estaba calculada, se
  recalcula sola tras cada cambio.
- Lote en el formato del MCP: al editarlo, `anillos` pasa a `contorno` + `huecos`. Turnos fijos en
  `red.turnos_fijos` por nombre de lote (renombrar o borrar el lote los arrastra). Un lote no puede anular un valor
  del proyecto con None (`_config_goteo` ignora los None); para la cinta se usa `""`.
- Proyecto nuevo: `referencia` (E, N) en los datos, solo para abrir el mapa ahí; el EPSG elegido se recuerda en
  los ajustes. La escena mide ±200 km alrededor del origen para poder recorrer un proyecto vacío; con
  `conservar_vista` el origen no cambia al redibujar.
- No se hizo: diámetro por tramo al dibujar la matriz («Pipe Properties»): el motor del MCP siempre dimensiona;
  escribir coordenadas a mano; modo orto. Verificación en pantalla: capturas con la plataforma `windows`; el usuario
  no dio acceso a la pantalla (computer use), falta su prueba a mano.

## Etapa 3: curvas de nivel de un DXF (2026-11-27)
- Pedido del usuario: importar un DXF con curvas de nivel y que el programa lo lea. Solo las curvas (no el lindero ni
  los lotes del DXF). Menú «Terreno → Importar curvas de nivel (DXF)…» y «Quitar el terreno (llano)».
- `topografia.py` (sin Qt) hace lo del complemento sin GDAL: ezdxf lee LWPOLYLINE, POLYLINE (2D y 3D), LINE y SPLINE
  del espacio modelo (`ezdxf.path.make_path` + aplanado a 0.1 m); TIN de Delaunay (scipy) con los vértices; cada
  triángulo marca sus celdas (rasterizado con numpy, como `gdal_grid -a linear`); se borran las celdas a más de la
  distancia máxima de una curva (`distance_transform_edt`, como ComputeProximity) y se recorta al recuadro con datos.
  `LinearNDInterpolator` no sirve: buscar el triángulo de cada celda se atasca con los triángulos finos de las curvas.
- DEM binario del motor `.rdem` (`motor.rejilla_a_bytes`, solo biblioteca estándar: float32 + zlib): el plano de Fruveg
  a 1 m tiene 14.5 millones de celdas; en `.asc` pesaba 142 MB y leerlo en Python puro tardaba minutos en cada
  proceso; en `.rdem`, 5 MB. El terreno queda `{"tipo": "dem", "archivo": "dem_<hash>.rdem", "curvas":
  "curvas_<hash>.json.gz", "origen", "capas", "celda_m", "distancia_max_m"}`; nombres por contenido para que deshacer
  vuelva al terreno anterior; al guardar solo van los archivos en uso (`archivos_en_uso`).
- Capa CURVAS_NIVEL (al fondo de la barra de capas): un elemento por cota, con la cota en la descripción emergente; las
  maestras (cada 5 equidistancias) al doble de grosor. La extensión del proyecto incluye las curvas.
- Fruveg (`Downloads/prueba fruveg.dxf`, 43 MB, capas `_CV` y `_CVD`, 1215 curvas, 520 000 vértices): DEM en ~30 s;
  contra el DEM de GDAL del complemento (`muestras/fruveg_mcp/fruveg_dem.asc`) 4 mm como máximo; con el diseño del MCP,
  presión en las válvulas a 1 cm como máximo y los mismos portalaterales. Falta la prueba a mano del usuario.

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
