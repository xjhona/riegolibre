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

## Cambios de una IA externa
- 2026-10-27: cambios de Gemini (válvula y cabezal con curva, horas por turno, cuartil inferior, presión estática)
  revisados y probados en QGIS; ver commits d8968e0 y 3a5abd8.
