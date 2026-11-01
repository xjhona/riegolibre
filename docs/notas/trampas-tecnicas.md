# Trampas técnicas (RiegoLibre)

## Entorno de este computador
- QGIS 3.44.15: `C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat` (Python 3.12, matplotlib y GDAL disponibles).
  La carpeta `QGIS 3.40.6` está vacía. El plugin está enlazado por junction en el perfil default de QGIS.
- Pruebas con QGIS: `QT_QPA_PLATFORM=offscreen` y `timeout`, porque un `QMessageBox` en una prueba la deja colgada.
  Para ver texto en capturas sin pantalla: `QT_QPA_FONTDIR=C:\Windows\Fonts`.
- Pruebas sin QGIS (solo motor): cualquier Python 3, `python -m unittest discover -s tests -t .`.
  El `python` de bash es el alias de la Tienda y no sirve; usar `C:\Users\Jhonatan\AppData\Local\Python\bin\python.exe`.
- Falta `%APPDATA%\RiegoLibre\base_datos.json` en este computador: las pruebas usan el catálogo genérico (menor PVC: 63 mm).
- La lista de precios `BaseDatos_Costos_COT-2026-001.csv` no está en el repo (dato comercial): copiarla a mano.
- `muestras/` está ignorada en git (datos del cliente: DXF de Fruveg, videos).

## Código
- El núcleo no importa QGIS. Compatibilidad Qt6: enums con nombre completo, `exec()` en vez de `exec_()`.
- GeoPackage: el primer campo es `fid`. Nunca usar `setAttributes` posicional sobre una capa que ya pudo guardarse.
  Las capas de RiegoLibre pasan a `<proyecto>_riegolibre.gpkg` (`integracion/persistencia.py`); las vistas previas siguen en memoria.
  Las tablas del gpkg de un bloque eliminado quedan huérfanas (se reutilizan al recalcular con el mismo nombre).
- Rótulos: QGIS une líneas con el mismo texto; `chr(0x200B)` distingue ramas. En este entorno Bash y Edit convierten
  `\u200b` y `\n` dentro de cadenas escritas por heredoc en caracteres reales: usar `chr()`.
- Con otra sesión trabajando en el mismo árbol: commitear solo los cambios propios.

## Ver videos del usuario
Ahora hay `ffmpeg` en el PATH: `ffmpeg -i video -vf fps=… salida_%03d.png` y leer los fotogramas con Read.
(Antes se servían con `http.server` desde `.claude/launch.json` y se cargaban como blob en el navegador del panel.)

## Hechos sin probar a mano en QGIS con pantalla
Casi todo lo de octubre: ventana de trazado automático, red con restricciones, turnos, base de datos editable,
bloque de goteo (portalateral manual, conexiones), rótulos, guardado en gpkg, imagen satelital y vista 3D.
La lista detallada de qué confirmar está en `PENDIENTES.md` («Por confirmar»).
