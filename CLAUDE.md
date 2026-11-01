# RiegoLibre

Plugin libre (GPL-3.0) de QGIS para diseñar riego tecnificado, réplica de lo esencial de IRRICAD. Primero goteo, luego aspersión.
El usuario (Jhonatan, habla español) da las instrucciones y valida la hidráulica y la interfaz en QGIS; Claude escribe el código.
Repositorio: https://github.com/xjhona/riegolibre (rama `main`, cuenta gh `xjhona`).

## Estructura
- `riegolibre/nucleo/`: motor de cálculo en Python puro, SIN imports de QGIS.
- `riegolibre/integracion/`: capas, geometrías y cálculo sobre el mapa de QGIS.
- `riegolibre/gui/`: ventanas y herramientas de mapa. `riegolibre/plugin.py`: menú y barra.
- `tests/`, `scripts/` (instalación para desarrollo), `muestras/` (datos del cliente, no se sube a git).
- Detalle de cada módulo y de los métodos de cálculo: `README.md`.

## Ejecutar y probar
- QGIS 3.44.15: `C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat` (el plugin ya está enlazado en el perfil default).
- Pruebas completas (con QGIS), desde la raíz del repo:
  `QT_QPA_PLATFORM=offscreen timeout 600 "C:/Program Files/QGIS 3.44.15/bin/python-qgis-ltr.bat" -m unittest discover -s tests -t .`
- Solo el motor: `C:\Users\Jhonatan\AppData\Local\Python\bin\python.exe -m unittest discover -s tests -t .`
  (el `python` de bash es el alias de la Tienda y no sirve).
- Estado: ~385 pruebas pasan (el 2026-10-31 se retiró el motor de trazado automático de la red y sus pruebas). Lo nuevo de octubre no se ha probado a mano con pantalla en QGIS.

## Reglas
- Mantener el núcleo sin imports de QGIS. Compatibilidad Qt6: enums con nombre completo, `exec()`.
- Textos de la interfaz solo en español. Moneda USD.
- Validar los cálculos con pruebas contra valores teóricos.
- La zona UTM varía por proyecto (32717, 32718…): nunca fijarla.
- Commits en español, estilo de los existentes. No subir a GitHub sin que el usuario lo pida. Commitear solo cambios propios.
- Cuando el usuario explique algo de IRRICAD (videos, capturas), replicar su comportamiento; lo que descarta, no se hace
  («Number of Laterals», «Even Flow», «Flushing»).
- Toda herramienta o módulo nuevo va dentro de una de las pestañas existentes (los grupos del menú y la barra de RiegoLibre, en
  `plugin.py`). Si no guarda relación con ninguna, se crea una pestaña nueva. Nunca un botón suelto fuera de ellas.
- Todo `.py` nuevo empieza con las tres líneas de autoría (copiarlas de otro archivo; `tests/test_autoria.py` lo exige).
  `LICENSE` de la raíz y `riegolibre/LICENSE` deben ser iguales; el texto legal no se traduce ni se edita.

## Trampas que no hay que olvidar
- GeoPackage: el primer campo es `fid`; nunca `setAttributes` posicional en capas que ya pudieron guardarse.
- Un `QMessageBox` dentro de una prueba la deja colgada: usar `QT_QPA_PLATFORM=offscreen` y `timeout`.
- Bash y Edit convierten `\u200b` y `\n` escritos en heredoc: usar `chr()`.
- La lista de precios `BaseDatos_Costos_COT-2026-001.csv` no está en el repo; en este computador no existe
  `%APPDATA%\RiegoLibre\base_datos.json` (se usa el catálogo genérico).

## Estado al 2026-10-31
Hecho: lateral, subunidad, diseño en el mapa, trazado automático de subunidades, red principal y bomba (la tubería matriz se
dibuja a mano con cuadro previo de diámetro, como «Mainline Pipe» de IRRICAD; ya no hay trazado automático de la red; turnos desde
el mapa, varios equipos de cabezal), materiales y costos, memoria de cálculo, base de datos de materiales (importar IRRICAD + editar),
topografía de CAD + satelital + 3D, lotes y bloque de goteo completo, diámetros por velocidad, información del objeto.

Pendientes principales (lista viva y «Por confirmar» en `PENDIENTES.md`):
1. Probar a mano en QGIS, con un terreno real, las ventanas nuevas.
2. Riego por aspersión (el usuario dará las pestañas Outlets/Nozzles del .mdb).
3. Importar bombas (pestaña Pumps) y precios de válvulas/equipos en la lista de materiales.
4. Turnos automáticos que equilibren el caudal.
5. Presión estática: ignora la presión de entrada (subestima un poco con bomba).

## Índice de docs/notas/
- `docs/notas/decisiones-usuario.md`: decisiones y criterios del usuario, réplica de IRRICAD.
- `docs/notas/trampas-tecnicas.md`: entorno de este computador, trampas de código, cómo ver videos, qué falta probar.
Leer la que corresponda antes de tocar ese tema. Historial detallado de lo construido: `PENDIENTES.md`.
