@echo off
rem RiegoLibre como programa de escritorio independiente de QGIS (necesita Python con PySide6).
rem Uso: RiegoLibre_escritorio.bat [proyecto.riegolibre ^| diseno_datos.json]
setlocal
set "PYW=%LOCALAPPDATA%\Python\bin\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
cd /d "%~dp0"
start "" "%PYW%" -m riegolibre_escritorio %*
