@echo off
rem RiegoLibre como programa de escritorio independiente de QGIS (necesita Python con PySide6).
rem Uso: RiegoLibre_escritorio.bat [proyecto.riegolibre ^| diseno_datos.json]
rem Busca pythonw en: el gestor de Python (%LOCALAPPDATA%\Python\bin), el instalador de python.org
rem (%LOCALAPPDATA%\Programs\Python\Python3xx, el mas nuevo) y por ultimo el PATH.
setlocal
set "PYW=%LOCALAPPDATA%\Python\bin\pythonw.exe"
if exist "%PYW%" goto abrir
set "PYW="
for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\%%D\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\%%D\pythonw.exe"
)
if defined PYW goto abrir
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%P"
if defined PYW goto abrir
echo No se encontro Python. Instale Python 3.10 o posterior y luego: python -m pip install -r requisitos_escritorio.txt
pause
exit /b 1
:abrir
cd /d "%~dp0"
start "" "%PYW%" -m riegolibre_escritorio %*
