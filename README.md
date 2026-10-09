# RiegoLibre

Complemento libre (GPL-3.0) para QGIS que sirve para diseñar riego tecnificado. La primera etapa es **riego por goteo**.

> ⚠️ Está en desarrollo. Verifique los resultados con cálculos manuales o con los catálogos del fabricante antes de usarlos en un proyecto real.

## Estructura

```
riegolibre/                 Complemento de QGIS (esta carpeta es la que se instala)
├── nucleo/                 Motor de cálculo en Python puro, sin dependencias de QGIS
│   ├── hidraulica.py       Darcy-Weisbach, Hazen-Williams, factor F de Christiansen
│   ├── emisores.py         Goteros y cintas: q = k·h^x, autocompensados
│   ├── tuberias.py         Tuberías y catálogo
│   ├── lateral.py          Lateral emisor por emisor, presión requerida, longitud máxima
│   ├── portalateral.py     Portalateral (laterales a uno o ambos lados)
│   ├── subunidad.py        Subunidad (entrada en extremo o centro) y selección de diámetro
│   ├── red.py              Red principal ramificada: turnos, diámetros, clases y bomba
│   ├── uniformidad.py      EU (Keller-Karmeli), variación de caudal, CU
│   └── datos/              Catálogos editables (JSON)
├── integracion/            Conexión con QGIS
│   ├── perfil_terreno.py   Perfil del terreno desde un DEM
│   ├── subunidad_mapa.py   Generación de laterales en el bloque y capas de resultado
│   └── red_mapa.py         Topología de la red principal dibujada y capas de resultado
└── gui/                    Ventanas: lateral, subunidad, diseño en el mapa y red principal
tests/                      Pruebas automáticas
scripts/                    Utilidades de desarrollo
```

## Instalación para desarrollo (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar_desarrollo.ps1
```

El script enlaza `riegolibre/` con la carpeta de complementos de QGIS. Después, en QGIS, vaya a **Complementos → Administrar e instalar complementos → Instalados** y active **RiegoLibre**.

Para recargar los cambios sin reiniciar QGIS, instale el complemento **Plugin Reloader**.

## Pruebas

Las pruebas del motor funcionan con cualquier Python 3.9 o superior. Las de integración solo corren con el Python de QGIS; con otro Python se omiten.

```powershell
& "C:\Program Files\QGIS 3.40.6\bin\python-qgis-ltr.bat" -m unittest discover -s tests -t .
```

## Diseño en el mapa

Menú **Complementos → RiegoLibre → Diseño de subunidad en el mapa**:

1. Dibuje el **bloque** (polígono) y el **portalateral** (línea). El botón *Crear capas para dibujar* prepara capas temporales en el SRC del proyecto. Todo debe estar en un SRC proyectado en metros (UTM).
2. **Generar laterales**: se trazan cada cierta separación, perpendiculares al portalateral o con un azimut fijo, a uno o ambos lados, y se recortan en el borde del bloque con un margen. La capa generada se puede editar: borrar, mover o alargar laterales.
3. **Calcular**: cada lateral se calcula con su longitud real y su perfil del DEM. La válvula puede ir al inicio, en el centro o al final del portalateral. Los resultados se añaden al mapa en el grupo *RiegoLibre · nombre*:
   - laterales coloreados por presión mínima de emisor,
   - tramos del portalateral con caudal, velocidad y presiones,
   - punto de la válvula con presión y caudal requeridos.

## Red principal y bomba

Menú **Complementos → RiegoLibre → Red principal y bomba**:

1. Cada subunidad diseñada en el mapa deja una capa *Válvula · nombre* con su caudal y presión requerida. También sirve cualquier capa de puntos con los campos `presion` (m) y `caudal_lh` (L/h).
2. Dibuje la **fuente** (punto de la bomba y el cabezal) y las **tuberías** hasta cada válvula. No hace falta cortar las líneas en las uniones: los extremos, las uniones en T, la fuente y las válvulas se detectan dentro de una tolerancia.
3. Pulse **Buscar válvulas**, asigne el **turno** de riego de cada una y pulse **Calcular**.

Qué hace el cálculo:
- **Turnos**: en cada turno funcionan solo sus válvulas.
- **Carga en la fuente**: la necesaria para que la válvula más desfavorecida reciba su presión, con la pérdida de la válvula. Además, ningún punto de la red puede bajar de la presión mínima, incluidos los puntos altos del terreno según el DEM.
- **Diámetro de cada tramo**: el menor que cumple la velocidad máxima y, opcionalmente, la pérdida unitaria máxima.
- **Clase de presión**: la más baja que soporta la presión máxima real del tramo, incluidos los puntos bajos del terreno.
- **Bomba**: CDT = presión a la entrada de la red + pérdidas del cabezal + altura de succión. Potencia = ρ·g·Q·CDT / η.

Resultados en el mapa (grupo *RiegoLibre · Red principal*):
- tuberías por tipo, con un grosor según el diámetro,
- válvulas con la presión disponible y el exceso a regular,
- bomba con su punto de diseño.

La ventana también muestra el perfil hidráulico de la ruta crítica: la línea piezométrica sobre el terreno.

Por ahora solo se calculan redes ramificadas, sin circuitos cerrados.

## Método de cálculo

**Lateral.** Se calcula paso a paso desde el último emisor hacia la entrada. En cada tramo se suman el caudal real de los emisores aguas abajo, la pérdida por fricción y el desnivel del terreno, ya sea con pendiente uniforme o con el perfil del DEM. La inserción de cada emisor se modela como una longitud equivalente.

**Criterios de diseño.**
- Emisor no compensado: la presión de entrada se fija para que el caudal medio sea el nominal. La variación de caudal admisible es del 10 % por defecto.
- Emisor autocompensado: la presión de entrada se fija para que el emisor más desfavorecido reciba la presión mínima de compensación. Se exige además que ningún emisor quede fuera del rango.

**Portalateral.** Para cada lateral distinto se construye una sola vez su curva: caudal y presiones extremas de los emisores en función de la presión de entrada. Con ella se resuelve el portalateral rápidamente, y con la solución final se calcula cada lateral en detalle.

**Subunidad.** La válvula puede estar en un extremo del portalateral o en el centro. En el centro hay dos ramas que reciben la misma presión, y con pendiente una sube y la otra baja. Los laterales de cada lado pueden tener su propia pendiente transversal.

**Selección del diámetro del portalateral.** Se evalúan todas las tuberías del catálogo y se elige la de menor diámetro que cumple estas condiciones:
- variación de caudal en toda la subunidad,
- velocidad máxima en el portalateral,
- presión de entrada máxima, si se indica,
- presión nominal de la tubería,
- todos los emisores dentro de su rango de compensación.

**Fricción.**
- Darcy-Weisbach con factor de Swamee-Jain en régimen turbulento y 64/Re en laminar. Es la opción recomendada para laterales, que trabajan con números de Reynolds bajos al final.
- Hazen-Williams como alternativa.

**Convención de pendiente.** Positiva cuando el terreno sube desde la entrada hacia el final.

## Hoja de ruta

- [x] Motor hidráulico de laterales y portalaterales
- [x] Calculadora de lateral con perfil del terreno desde un DEM
- [x] Ventana de subunidad: portalateral y laterales, selección de diámetro
- [ ] Portalateral telescópico (dos o más diámetros)
- [x] Herramientas de mapa: dibujar el bloque y generar los laterales automáticamente
- [x] Red principal, carga dinámica total y punto de diseño de la bomba
- [ ] Lista de materiales y memoria de cálculo
- [ ] Riego por aspersión
