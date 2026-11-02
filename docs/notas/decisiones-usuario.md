# Decisiones del usuario (RiegoLibre)

Fuente: sesiones de octubre de 2026. El usuario valida la hidráulica y prueba en QGIS; Claude escribe el código.

## Base del proyecto (2026-10-08)
- Plugin de QGIS (no ejecutable propio), motor en Python puro (`riegolibre/nucleo`), licencia GPL-3.0.
- Primero goteo, después aspersión. Interfaz solo en español. Moneda: USD.
- Orden acordado: ventana de subunidad → dibujo de bloques y laterales en el mapa → red principal y bomba → materiales.
- QGIS ya resuelve CAD/GIS (DEM, CRS, dibujo, impresión); el trabajo se centra en la hidráulica.

## Réplica de IRRICAD
- El «Tape Irrigation Block» es «el corazón de IRRICAD». Un lote = una válvula; laterales por hilera (grupo).
- Se descartaron «Number of Laterals», «Even Flow» y la pestaña «Flushing».
- Base de datos: solo importar el .mdb (no exportar), una sola base global, lector .mdb propio en Python.
  Las pestañas de aspersión (Outlets, Nozzles) y Pumps las dará el usuario después.
- Orientación de laterales: el programa sugiere, el usuario fija el azimut.
- Tramos de conexión del bloque («Stub Length», «Submain Stub», «Valve Stub»): se dibujan y suman al metrado,
  NO entran en la pérdida de carga.
- Tuberías menores de 63 mm se rotulan en pulgadas (`diametro_en_plano` en `nucleo/tuberias.py`).
- La zona UTM varía por proyecto (32717 o 32718): nunca fijarla en el código.
- Red principal (video del usuario, 2026-10-31): se descartó el trazado automático; la red se dibuja a mano. Al activar la
  herramienta «Mainline Pipe» IRRICAD abre un cuadro con la capa y «Pipe Properties»: lista de tuberías cuya primera opción es
  «Computer Selected» (diámetro por dimensionar). Después se pide «Enter First Point / Enter Second Point». Con la tubería ya
  dibujada, «Edit Mainline Pipe» muestra el mismo cuadro para cambiarle el diámetro. Aquí: `gui/dialogo_tuberia_matriz.py`.
- Capas de la matriz (2026-11-01, video «DH-M1»): IRRICAD tiene capas fijas MAINLINE_PIPES y MAINLINE_JUNCTIONS y no pregunta la
  capa; los vértices son nodos («Junction» en el menú del clic derecho) en su capa aparte. Aquí: capas «Matriz» y «Nodos de la
  matriz» creadas solas (`crear_capas_de_matriz` en `integracion/red_mapa.py`); un nodo por vértice dibujado; borrar = botones
  de la ventana de la red. El cálculo no usa los nodos (sigue sacándolos de los extremos de las líneas).
- Nodos (2026-11-01, video 23-38-30): el usuario aclaró que los nodos NO alteran el cálculo hidráulico: son referencias visuales y
  topológicas (quiebres, bifurcaciones tipo tee). IRRICAD también los inserta a mano con «Mainline Pipe Junction» (cuadro con
  capa, color, símbolo, tamaño y «Permanent»; luego clics sobre la tubería). Aquí: «Insertar nodo en la matriz…»
  (`DialogoRed.insertar_nodo`); no se replicó el cuadro de símbolo/tamaño/«Permanent».
- Valve Connector (2026-11-02, video 00-07-37): el usuario explicó que la matriz solo se dimensiona si todas las válvulas están
  conectadas a ella, hay una fuente asignada y los turnos están configurados; esta herramienta resuelve el primer punto. En
  IRRICAD es de un solo paso: cuadro (Match nearest pipe, longitud máxima 100 m, capa/ancho/tubería en gris cuando «Match» está
  marcado) → OK → dibuja a la vez todos los tramos válvula–matriz (barra de estado: «Automatically connect valves to the nearest
  mainline»). Aquí: «Conectar válvulas a la matriz…» en la ventana de la red (`DialogoRed.conectar_valvulas`,
  `gui/dialogo_conector_valvulas.py`); no se replicaron capa ni ancho de línea (la capa siempre es «Matriz»). Por confirmar: que
  IRRICAD conecte también a las tuberías de conexión ya dibujadas, y si «Permanent Junctions»/«Depth» hacen falta.
- Presión mínima y máxima en el mapa (video del usuario, 2026-10-31): un botón con menú «All Valves / Selected Valves /
  Clear Markers»; los marcadores salen en el emisor de menor y de mayor presión y, al pasar el cursor, muestran
  «Max: 21.0 m». Aquí van como rótulos fijos «Máx: 21.0 m» / «Mín: …» (`integracion/limites_presion.py`). Por confirmar
  con el usuario: que el rótulo fijo le sirva (IRRICAD lo muestra solo al pasar el cursor).
- Menú y barra propios (2026-10-31, el usuario pidió agrupar las herramientas dispersas): ya no se usan el menú ni la barra
  de Complementos de QGIS. Ventanas agrupadas en botones desplegables; a un clic quedan las herramientas de mapa (bloque,
  turnos, información) y la red. Por confirmar con el usuario: el agrupamiento y qué debe quedar a un clic.

## Cambios de una IA externa
- 2026-10-27: cambios de Gemini (válvula y cabezal con curva, horas por turno, cuartil inferior, presión estática)
  revisados y probados en QGIS; ver commits d8968e0 y 3a5abd8.
