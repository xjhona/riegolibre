# Pendientes de RiegoLibre

Estado al 9 de octubre de 2026. Ya están hechos:
- la calculadora de lateral,
- la subunidad,
- el diseño en el mapa,
- la red principal y la bomba,
- los materiales y costos,
- la memoria de cálculo (PDF, ODT y HTML),
- los diámetros de la red principal por costo total (tubería + energía de bombeo),
- el estilo semitransparente de la capa «Bloques».

## Por desarrollar

1. **Portalateral telescópico**, con dos o más diámetros.
2. **Riego por aspersión.**

## Por confirmar

- Moneda de la lista de precios. Se supone USD y se puede cambiar en la ventana de materiales.
- Criterio para sugerir el motor comercial: 10 % de margen sobre la potencia al eje (`MARGEN_MOTOR` en `riegolibre/nucleo/memoria.py`).
- Revisar en un navegador la memoria exportada en HTML.
- Diámetros por costo: las horas de bombeo del año se reparten por igual entre los turnos y cada turno se bombea con su propia CDT (bomba con variador o regulación). Confirmar si conviene otro criterio, por ejemplo horas distintas por turno.
- Probar en QGIS la opción «Elegir diámetros por costo total» de la ventana de la red. Las pruebas del motor pasan, pero la ventana no se pudo abrir sin QGIS.
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
