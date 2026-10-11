# Pendientes de RiegoLibre

Estado al 11 de octubre de 2026. Ya están hechos:
- la calculadora de lateral,
- la subunidad,
- el diseño en el mapa,
- la red principal y la bomba,
- los materiales y costos,
- la memoria de cálculo (PDF, ODT y HTML),
- los diámetros de la red principal por costo total (tubería + energía de bombeo),
- el estilo semitransparente de la capa «Bloques»,
- el portalateral telescópico (hasta tres diámetros),
- el trazado automático de laterales, portalaterales y subunidades sobre un terreno de cualquier forma,
- la herramienta «Información del objeto» (ficha de laterales, portalaterales, tuberías, válvulas y bomba),
- la red principal automática (botón «Trazar la red automáticamente» en la ventana de la red; motor en `nucleo/trazado_red.py`),
- la válvula de cada subunidad en el extremo conveniente del portalateral según el DEM y la fuente (`PesosTrazado.subida`),
- la red automática con restricciones: evita zonas (polígonos), sigue caminos, cruza barreras (canales, vías) donde cuesta menos y esquiva el relieve del DEM (`nucleo/terreno.py`, `nucleo/trazado_rejilla.py`, `RestriccionesTrazado` en `integracion/red_mapa.py`).
- la topografía del proyecto: botón «Topografía: curvas de CAD, imagen satelital y 3D…». Las curvas de nivel de un DXF (polilíneas con elevación) se convierten en un DEM por TIN, recortado a 30 m de la curva más cercana, y la polilínea cerrada del lindero en polígono; se descarga la imagen satelital (Google o Esri, con el mayor zoom que tenga imagen en la zona, o una capa ráster del proyecto) recortada al DEM; y se abre una vista 3D con el DEM como terreno (`integracion/topografia_cad.py`, `integracion/imagen_satelital.py`, `gui/dialogo_topografia.py`). La importación se probó en QGIS con el plano de Fruveg (793 curvas, 2 × 1.4 km, DEM de 1 m en unos 10 s); la imagen de Google de esa zona, a 0.5 m, se descarga en unos segundos.

## Por desarrollar

1. **Riego por aspersión.**
2. Trazado automático de subunidades: usar la elevación real del DEM también para elegir la orientación de los laterales (hoy se usa un plano ajustado a todo el terreno) y para la penalización por pendiente de la puntuación.
3. Red principal automática con restricciones, mejoras posibles: evitar automáticamente la capa «Bloques» del diseño (hoy se elige a mano como zona a evitar); distinguir varias capas de zonas con factores distintos; ajustar el costo de la tubería a la lista de precios.

## Por confirmar

- Criterio para sugerir el motor comercial: 10 % de margen sobre la potencia al eje (`MARGEN_MOTOR` en `riegolibre/nucleo/memoria.py`).
- Revisar en un navegador la memoria exportada en HTML.
- Diámetros por costo: las horas de bombeo del año se reparten por igual entre los turnos y cada turno se bombea con su propia CDT (bomba con variador o regulación). Confirmar si conviene otro criterio, por ejemplo horas distintas por turno.
- Probar en QGIS la opción «Elegir diámetros por costo total» de la ventana de la red y el selector «Diámetros» del portalateral (ventanas de subunidad y de diseño en el mapa). Las pruebas del motor pasan, pero las ventanas no se pudieron abrir sin QGIS; correr también las pruebas de integración (`test_mapa_qgis` incluye una del telescópico).
- Portalateral telescópico: el costo se compara con longitud × diámetro². Confirmar si conviene usar los precios de la lista, como en la red principal, y si se deben permitir cambios de material (por ejemplo, de PVC a PE).
- Trazado automático: confirmar los pesos de la puntuación (60 m por válvula, 2 × portalateral, 4 por metro sin regar, 5 × pendiente), la regla de 55 % de la variación de caudal para los laterales y el peso de la subida del portalateral al elegir el extremo de la válvula (5 m de tubería por metro).
- Probar en QGIS la ventana «Trazado automático» con un terreno real (las pruebas pasan, pero no se pudo ver el texto de la ventana en modo sin pantalla).
- Información del objeto: probar el clic en QGIS (las pruebas cubren la búsqueda y la ficha, pero no el clic real con el ratón) y confirmar si falta algún dato de la ficha de IRRICAD (conexiones entre objetos y flujo de purga no existen en RiegoLibre).
- Red principal automática: el costo por metro usado para elegir el recorrido es `0.2 + (q/Q)^0.7` (constantes `COSTO_FIJO` y `EXPONENTE_COSTO` en `riegolibre/nucleo/trazado_red.py`); confirmar si representa bien los precios reales de las tuberías, o si conviene usar la lista de precios.
- Red principal automática: probar en QGIS el botón con las subunidades de un terreno real. Las pruebas pasan, pero no se vio el resultado en pantalla.
- Red automática con restricciones: las pruebas con QGIS pasan (226), pero falta probar la ventana a mano con un terreno real. Confirmar los valores por defecto: zonas ×5, camino al 50 %, cruce de barrera = 50 m de tubería, subida = 5 m de tubería por metro, pendiente que duplica el costo = 25 %.
- Topografía: la zona UTM se elige en cada plano (17 S, 18 S…); la ventana recuerda la última usada y muestra el centro del plano en grados para comprobarla. Probar en QGIS la descarga de la imagen satelital y el botón «Abrir vista 3D» (sin la interfaz de QGIS no se pueden probar). Confirmar con otros planos los valores por defecto (celda de 1 m y distancia máxima de 30 m a una curva). Mejora posible: leer la cota de los textos cuando las curvas vienen con elevación 0.
- Probar el complemento con un caso real.

## Retomar en otro computador

1. Instalar QGIS 3.40.6 LTR.
2. Clonar el repositorio:
   ```
   git clone https://github.com/xjhona/riegolibre.git
   ```
3. Enlazar el complemento con QGIS y activarlo en *Complementos → Administrar e instalar complementos*:
   ```
   powershell -ExecutionPolicy Bypass -File scripts\instalar_desarrollo.ps1
   ```
4. Copiar a mano la lista de precios `BaseDatos_Costos_COT-2026-001.csv`. No está en el repositorio porque es un dato comercial. Ábrala una vez desde la ventana de materiales.
5. Ejecutar las pruebas:
   ```
   & "C:\Program Files\QGIS 3.40.6\bin\python-qgis-ltr.bat" -m unittest discover -s tests -t .
   ```
