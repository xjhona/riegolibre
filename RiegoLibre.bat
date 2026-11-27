@echo off
rem RiegoLibre como programa independiente (prototipo). Usa las librerias de QGIS instaladas en el equipo.
rem Uso: RiegoLibre.bat [proyecto.qgz]
setlocal
set "QGIS_PY="
for /d %%D in ("%ProgramFiles%\QGIS *") do (
    if exist "%%D\bin\python-qgis-ltr.bat" set "QGIS_PY=%%D\bin\python-qgis-ltr.bat"
    if exist "%%D\bin\python-qgis.bat" if not defined QGIS_PY set "QGIS_PY=%%D\bin\python-qgis.bat"
)
if not defined QGIS_PY (
    echo No se encontro QGIS en "%ProgramFiles%". Instale QGIS 3.40 o posterior.
    pause
    exit /b 1
)
cd /d "%~dp0"
call "%QGIS_PY%" -m riegolibre_app %*
