# Enlaza la carpeta riegolibre/ del repositorio con la carpeta de complementos de QGIS.
# Así QGIS usa directamente el código del proyecto (no hace falta copiar nada tras cada cambio).
$origen = (Resolve-Path (Join-Path $PSScriptRoot "..\riegolibre")).Path
$plugins = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\default\python\plugins"
$destino = Join-Path $plugins "riegolibre"

New-Item -ItemType Directory -Force $plugins | Out-Null
if (Test-Path $destino) {
    Write-Host "Ya existe $destino (no se modifica)."
} else {
    New-Item -ItemType Junction -Path $destino -Target $origen | Out-Null
    Write-Host "Enlace creado: $destino -> $origen"
}
Write-Host "Abra QGIS > Complementos > Administrar e instalar complementos > Instalados y active RiegoLibre."
