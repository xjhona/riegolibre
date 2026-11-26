# Servidor MCP de RiegoLibre (prototipo)

Permite que un asistente (Claude Code, Claude Desktop u otro cliente MCP) diseñe un sistema de riego por
goteo a partir de instrucciones. El asistente toma las decisiones (dirección, subdivisión, turnos,
tuberías) y **todos los cálculos los hace `riegolibre/nucleo`**, el mismo motor del complemento. No
necesita QGIS.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `ver_catalogo` | Emisores, tuberías y laterales con gotero disponibles (la base de datos del usuario, si existe) y los valores por omisión. |
| `disenar_proyecto` | Diseña todo: bloques de goteo (con subdivisión opcional), subunidades, turnos, red principal y bomba. Devuelve un id y el resumen con lo que no cumple. |
| `detalle_subunidad` | El cálculo completo de una subunidad: diámetros evaluados y por qué no cumplen, tramos y presiones. |
| `exportar_proyecto` | GeoJSON (se abre en QGIS), memoria de cálculo en HTML, resumen y datos de entrada. |

El formato de entrada está en la descripción de `disenar_proyecto` ([servidor.py](servidor.py)) y hay un
ejemplo en [ejemplos/fundo_demo.json](ejemplos/fundo_demo.json). Las coordenadas van en metros (UTM).

## Uso

Requiere [uv](https://docs.astral.sh/uv/), que instala el SDK de MCP en un entorno aparte:

```
uv run --no-project --with "mcp>=2.3,<3" python mcp_riegolibre/servidor.py
```

En Claude Code queda registrado por el archivo `.mcp.json` de la raíz del repositorio (hay que aprobarlo
la primera vez). Luego basta con pedir, por ejemplo: *«Diseña el riego de los lotes de lotes.geojson,
palto a 6 × 4 m con doble lateral, gotero autocompensado de 2 L/h cada 0.5 m, fuente en (x, y), 3 turnos,
variación de caudal máxima 10 %, la matriz por el camino del borde oeste»*.

## La tubería matriz

Como en el complemento (y en IRRICAD, «Mainline Pipe»), la matriz no se traza sola: se entrega dibujada en
`red.matriz`, como polilíneas que empiezan en la fuente. Quien la dibuja aquí es el asistente, siguiendo
las indicaciones del usuario (caminos, bordes). Cada válvula se une a la matriz con un tramo recto, como
«Conectar válvulas a la matriz…» (`nucleo/conector_valvulas.py`), y la red se corta en los nodos y se
dimensiona con `nucleo/red.py`. Lo práctico es diseñar primero sin matriz para ver dónde quedan las
válvulas (`valvula_xy`) y luego dibujarla.

## Diferencias con el complemento

- El terreno es llano, un plano inclinado, puntos acotados (IDW) o un DEM en ASCII Grid (`.asc`); no lee
  otros formatos de ráster.
- La subdivisión recorta los sub-bloques con un algoritmo simple (Sutherland-Hodgman); en lotes muy
  cóncavos o con huecos puede dejar bordes de más.
- Los diseños viven en memoria mientras el servidor está abierto; para retomarlos, vuelva a diseñar con
  el archivo `_datos.json` exportado.

## Pruebas

```
uv run --no-project python -m unittest tests.test_mcp_motor
```
