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
│   ├── aspersion.py        Aspersión: aspersor y elevador, marco, pluviometría, lateral de aspersores
│   ├── portalateral.py     Portalateral (laterales a uno o ambos lados)
│   ├── subunidad.py        Subunidad (entrada en extremo o centro) y selección de diámetro
│   ├── red.py              Red principal ramificada: turnos, diámetros, clases y bomba
│   ├── economia.py         Diámetros de la red por costo total: tubería + energía de bombeo
│   ├── precios.py          Lectura de listas de precios e identificación de tuberías
│   ├── base_datos.py       Base de datos de materiales: tuberías, laterales con gotero, válvulas, otros
│   ├── importar_irricad.py Importación de una base de datos de IRRICAD (.mdb)
│   ├── mdb.py              Lector de bases de Access (.mdb, Jet 3 y Jet 4) en Python puro
│   ├── ficha.py            Fichas de información de un objeto (formato «Object Info»)
│   ├── trazado.py          Trazado automático: orientación, portalaterales y subunidades de un terreno
│   ├── materiales.py       Partidas, tubos, desperdicio, costos y exportación a Excel
│   ├── memoria.py          Resúmenes de resultados y documento de la memoria de cálculo
│   ├── graficos.py         Gráficos de presiones (matplotlib)
│   ├── uniformidad.py      EU (Keller-Karmeli), variación de caudal, CU
│   └── datos/              Catálogos editables (JSON)
├── integracion/            Conexión con QGIS
│   ├── perfil_terreno.py   Perfil del terreno desde un DEM
│   ├── subunidad_mapa.py   Generación de laterales en el bloque y capas de resultado
│   ├── calculo_subunidad.py Cálculo de una subunidad dibujada (lo usan el diseño manual y el automático)
│   ├── info_objeto.py      Busca el objeto calculado bajo el cursor y arma su ficha
│   ├── trazado_mapa.py     Trazado automático: geometrías, pendiente del DEM, alcance de laterales y capas
│   ├── red_mapa.py         Topología de la red principal dibujada y capas de resultado
│   ├── turnos_mapa.py      Turnos de riego pintados en el mapa (capa «Turnos de riego»)
│   ├── importar_mcp.py     Rehace en el mapa un diseño del servidor MCP (capas propias del complemento)
│   ├── materiales_mapa.py  Metrado a partir de las capas de resultado del proyecto
│   └── memoria_mapa.py     Resúmenes guardados en las capas y plano general
└── gui/                    Ventanas: lateral, subunidad, diseño en el mapa, trazado automático, red, base de datos,
│                           materiales, memoria
│                           y las herramientas «Información del objeto» y «Turnos de riego»
riegolibre_app/             RiegoLibre como programa independiente (prototipo; ver más abajo)
riegolibre_escritorio/      Programa de escritorio sin QGIS (PySide6; ver más abajo)
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

## Menú y barra de RiegoLibre

Todas las herramientas están en el menú **RiegoLibre** (en la barra de menús de QGIS, antes de *Ayuda*) y en la barra de herramientas **RiegoLibre**, con el mismo orden. La barra se puede mover o apagar en *Ver → Barras de herramientas*.

| En la barra | Contiene |
| --- | --- |
| **Terreno y lotes** (despliega) | Topografía, Importar lotes de CAD, Importar diseño del MCP, Zonas |
| **Diseño de goteo** (despliega) | Calculadora de lateral, Subunidad de riego, Diseño de subunidad en el mapa, Trazado automático, Diámetros de portalaterales |
| **Diseño de aspersión** (despliega) | Calculadora de lateral de aspersión |
| **Bloque de goteo** | Herramienta de mapa, a un clic |
| **Fuente de agua** | Herramienta de mapa, a un clic |
| **Red principal y bomba** | Ventana de la red, a un clic |
| **Turnos de riego** | Herramienta de mapa, a un clic |
| **Información del objeto** | Herramienta de mapa, a un clic |
| **Presión mínima y máxima** (despliega) | Todas las válvulas, Válvulas seleccionadas, Borrar marcadores |
| **Materiales y documentos** (despliega) | Base de datos de materiales, Lista de materiales y costos, Memoria de cálculo |
| **Ayuda** (despliega) | Acerca de RiegoLibre |

## Diseño en el mapa

Menú **RiegoLibre → Diseño de goteo → Diseño de subunidad en el mapa**:

1. Dibuje el **bloque** (polígono) y el **portalateral** (línea). El botón *Crear capas para dibujar* prepara capas temporales en el SRC del proyecto. Todo debe estar en un SRC proyectado en metros (UTM).
2. **Generar laterales**: se trazan cada cierta separación, perpendiculares al portalateral o con un azimut fijo, a uno o ambos lados, y se recortan en el borde del bloque con un margen. La capa generada se puede editar: borrar, mover o alargar laterales.
3. **Calcular**: cada lateral se calcula con su longitud real y su perfil del DEM. La válvula puede ir al inicio, en el centro o al final del portalateral. Los resultados se añaden al mapa en el grupo *RiegoLibre · nombre*:
   - laterales coloreados por presión mínima de emisor,
   - tramos del portalateral con caudal, velocidad y presiones,
   - punto de la válvula con presión y caudal requeridos.

## Trazado automático

Menú **RiegoLibre → Diseño de goteo → Trazado automático de subunidades**. Sirve para terrenos de cualquier forma (con escotaduras, huecos o varias partes) y evita dibujar a mano el portalateral:

1. Elija la capa con el **polígono del terreno** (si tiene varias entidades, seleccione una). Opcionalmente, un **DEM** y un punto con la **fuente de agua**.
2. Indique la separación entre laterales, el emisor y los criterios, y pulse **Buscar trazado**. Se prueban unas veinte direcciones de laterales (rejilla de 15°, los lados más largos del contorno, el rectángulo mínimo que envuelve al terreno y, con DEM, las curvas de nivel) y se muestran las mejores en una tabla. Al elegir una fila se dibuja en el mapa.
3. **Aplicar y calcular** crea las capas del trazado (grupo *Trazado · nombre*: bloques, portalaterales y laterales, y opcionalmente los emisores) y calcula cada subunidad con el mismo cálculo del diseño en el mapa (grupos *RiegoLibre · nombre n*). Esas subunidades alimentan después la **Red principal y bomba**.

Cómo decide el trazado:
- **Alcance de los laterales.** Calculado con la hidráulica: la mayor longitud que cumple la variación de caudal (se reserva el 55 % de la variación admisible de la subunidad para los laterales y el resto para el portalateral), con la pendiente del DEM en cada dirección. También puede fijarse a mano.
- **Portalaterales.** Rectas perpendiculares a los laterales. Se reparte el ancho del terreno en bandas iguales según el alcance, se centra cada portalateral donde más riega y lo que no alcanza una banda (zonas cóncavas, partes tras un hueco) se cubre con portalaterales adicionales. Los laterales se recortan en el borde (menos el margen) y nunca cruzan un hueco ni se traslapan.
- **Caudal por subunidad.** Si se indica un caudal máximo por válvula, cada portalateral se parte en trozos de caudal parecido, cada uno con su válvula.
- **Válvula.** En el centro del portalateral o en un extremo. En un extremo, se elige el que sale más barato llevar el agua hasta él: la distancia a la fuente más 5 m de tubería por cada metro que el agua sube por el portalateral (con un DEM, usando la cota real de los extremos). Así, con pendiente, la válvula queda arriba y el agua baja por el portalateral.
- **Puntuación** de cada dirección, en metros equivalentes de tubería: laterales + 2 × portalaterales + 60 por válvula + 4 por metro de lateral no regado + 5 × pendiente × laterales + variación de caudales entre subunidades. Los pesos están en `PesosTrazado` (`nucleo/trazado.py`).

Los laterales generados se pueden editar y recalcular con la ventana de diseño en el mapa (seleccione la subunidad con el campo `subunidad`).

## Información del objeto

El botón **Información del objeto** (menú y barra de RiegoLibre) activa una herramienta de mapa parecida al *Object Info* de IRRICAD: al hacer clic sobre un objeto calculado se abre su ficha (se puede copiar) y el objeto se resalta. Solo se consultan las capas de resultado visibles.

| Objeto | Datos de la ficha |
|---|---|
| Lateral | P1 y P2 (coordenadas), longitud, ángulo, subunidad y posición en el portalateral, tubería, emisor, caudal por cada 100 m, presión en P1 y P2 (último emisor), pérdida, desnivel, caudal de entrada, velocidad, y presiones y caudales de sus emisores |
| Tramo de portalateral | Coordenadas, longitud, ángulo, rama, tubería, presiones en P1 y P2, pérdida, desnivel, caudal de entrada y de salida, velocidad |
| Tubería de la red | Lo mismo, con una fila por turno de riego |
| Válvula | Cota, datos de su subunidad (presión necesaria, caudal, área, uniformidad) y, si ya se calculó la red principal, una fila por turno con la presión aguas arriba, la requerida, la pérdida de la válvula y el caudal |
| Bomba | Cota y punto de diseño |

Al consultar un **lateral**, la ventana dibuja también su perfil: presión en cada emisor y terreno (arriba) y caudal de cada emisor (abajo). El perfil se reconstruye con la configuración guardada en la capa y el DEM con que se calculó, con la misma presión de entrada.

Las líneas se orientan en el sentido del flujo (P1 aguas arriba, P2 aguas abajo) y siempre se cumple *presión P1 − presión P2 = pérdida + desnivel*. Los resultados calculados con una versión anterior no tienen todos los campos: se muestran con «—» hasta que se vuelva a calcular. Las presiones por turno de una válvula aparecen cuando se asignan los turnos y se calcula la **Red principal y bomba**.

## Presión mínima y máxima en el mapa

El botón **Presión mínima y máxima** (menú y barra de RiegoLibre) replica el de IRRICAD. Tiene un menú:

- **Todas las válvulas**: en cada subunidad calculada pone un marcador rojo en el emisor de mayor presión («Máx: 21.0 m») y uno azul en el de menor presión («Mín: 18.5 m»).
- **Válvulas seleccionadas**: lo mismo, solo en las subunidades cuya válvula está seleccionada, o cuyo lote (o bloque) está seleccionado con *Seleccionar entidades*.
- **Borrar marcadores**: quita la capa de marcadores.

Los marcadores van en la capa *Presión mínima y máxima* (campos `tipo`, `presion`, `subunidad`, `rotulo`) y se reemplazan al repetir la acción. La presión sale de los campos `p_min` y `p_max` de los laterales; la posición se obtiene reconstruyendo el lateral extremo como lo hace *Información del objeto* (con el DEM con que se calculó). Código: `integracion/limites_presion.py`.

## Red principal y bomba

Menú **RiegoLibre → Red principal y bomba**:

1. Cada subunidad diseñada en el mapa deja una capa *Válvula · nombre* con su caudal y presión requerida. También sirve cualquier capa de puntos con los campos `presion` (m) y `caudal_lh` (L/h).
2. Marque la **fuente de agua** (punto de la bomba y el cabezal) con el botón **Fuente de agua** (siguiente sección) y dibuje las **tuberías** hasta cada válvula. No hace falta cortar las líneas en las uniones: los extremos, las uniones en T, la fuente y las válvulas se detectan dentro de una tolerancia.
3. Pulse **Buscar válvulas**, asigne el **turno** de riego de cada una y pulse **Calcular**. Los turnos se asignan en la tabla o, más cómodo, en el mapa (siguiente sección).

### Fuente de agua en el mapa

El botón **Fuente de agua** de la barra de RiegoLibre (o **Colocar la fuente de agua…** en la ventana de la red, que se esconde mientras se marca) es el *Water Supply* de IRRICAD: de ese punto arranca la tubería matriz.

- Un **clic** en el mapa deja la fuente en ese punto; con el imán del proyecto activado se pega a un extremo de tubería o a una válvula (y la herramienta atrae por sí sola a los vértices de la capa *Red principal* y de las válvulas). Esc o clic derecho cancelan.
- La fuente es la capa de puntos **Fuente** (cuadro azul como la bomba de los resultados, rotulada «Fuente»), con un solo punto. Si el proyecto no la tiene, se crea en el SRC del proyecto (debe ser métrico) y se guarda en el GeoPackage junto al proyecto, como las demás capas de dibujo.
- Si ya hay una fuente, pregunta antes de cambiarla de lugar: la nueva **reemplaza** a la anterior (siempre un solo punto). Si la capa estaba en edición, el cambio se confirma sin cerrar la edición.
- La ventana de la red, si está abierta, queda con esa capa en «Capa de la fuente», y la ventana del bloque de goteo también si no tenía fuente elegida; al calcular no hay que tocar nada más. Sin fuente colocada, el cálculo avisa que falta.

Código: `integracion/fuente_mapa.py` (capa, estilo, reemplazo) y `gui/herramienta_fuente.py` (el clic, con `HerramientaPuntos`).

### Turnos de riego en el mapa

El botón **Turnos de riego** de la barra de RiegoLibre (o **Asignar turnos en el mapa…** en la ventana de la red) abre un panel flotante y activa una herramienta de mapa, como el reparto de turnos de IRRICAD:

1. **Clic** en un bloque (un lote, un bloque del trazado automático o una válvula suelta) lo marca en rojo; otro clic lo desmarca. **Arrastrar** un rectángulo marca todos los bloques que toca.
2. Elija el **turno** en el panel y pulse **Asignar** (o Intro): los bloques se pintan con el color del turno y llevan su etiqueta «T1», «T2»… El panel deja elegido el turno siguiente para el próximo grupo; Esc limpia la selección.
3. Repita con otro grupo y otro turno. Un clic en un turno de la tabla del panel lo elige para añadirle más bloques; volver a marcar un bloque ya pintado y asignarlo le cambia el turno.

El panel muestra por turno las válvulas y el caudal, y el **desbalance** entre turnos (el turno de mayor caudal es el que manda los diámetros de la red y la bomba). Los turnos quedan en la capa *Turnos de riego* (se guarda con el proyecto) y la ventana de la red los toma al pulsar **Buscar válvulas**; si la ventana ya está abierta, la tabla se actualiza sola. Cambiar un turno en la tabla también pinta el bloque en el mapa. Las válvulas sin turno se calculan en el turno 1.

Qué hace el cálculo:
- **Turnos**: en cada turno funcionan solo sus válvulas.
- **Carga en la fuente**: la necesaria para que la válvula más desfavorecida reciba su presión, con la pérdida de la válvula. Además, ningún punto de la red puede bajar de la presión mínima, incluidos los puntos altos del terreno según el DEM.
- **Diámetro de cada tramo**: el menor que cumple la velocidad máxima y, opcionalmente, la pérdida unitaria máxima.
- **Clase de presión**: la más baja que soporta la presión máxima real del tramo, incluidos los puntos bajos del terreno.
- **Bomba**: CDT = presión a la entrada de la red + pérdidas del cabezal + altura de succión. Potencia = ρ·g·Q·CDT / η.
- **Diámetros por costo total** (opcional): compara el costo de las tuberías con el valor presente de la energía de bombeo.
  - Los precios por metro salen de la última lista de precios abierta en la ventana de materiales, con sus artículos elegidos y su desperdicio. Las tuberías sin precio no se consideran.
  - Energía de cada turno = potencia al eje / eficiencia del motor × horas de bombeo. Las horas del año se reparten por igual entre los turnos.
  - Valor presente = energía anual × (1 − (1 + i)^−n) / i.
  - La búsqueda parte del menor diámetro que cumple y prueba, tramo a tramo, el diámetro inmediato superior e inferior. Aplica el cambio que más baja el costo y repite hasta que ninguno lo baja. Los criterios de velocidad y presión se siguen cumpliendo.

Resultados en el mapa (grupo *RiegoLibre · Red principal*):
- tuberías por tipo, con un grosor según el diámetro,
- válvulas con la presión disponible y el exceso a regular,
- bomba con su punto de diseño.

La ventana también muestra el perfil hidráulico de la ruta crítica: la línea piezométrica sobre el terreno.

Por ahora solo se calculan redes ramificadas, sin circuitos cerrados.

### Tubería matriz dibujada en el mapa

La red principal se dibuja a mano, como la herramienta *Mainline Pipe* de IRRICAD. El botón **Dibujar tubería matriz…** abre primero un cuadro modal con la **Tubería**: un diámetro del catálogo (red principal) o **Elegida por el programa**, que deja el diámetro por dimensionar (*Computer Selected* de IRRICAD).

La capa no se pregunta: el programa crea solo las capas **Matriz** (líneas, como *MAINLINE_PIPES* de IRRICAD) y **Nodos de la matriz** (puntos, como *MAINLINE_JUNCTIONS*) la primera vez que se dibuja, o con **Crear capas para dibujar**, y las guarda en el GeoPackage del proyecto. Cada vértice de una tubería queda como un nodo en *Nodos de la matriz* (no se repiten los que están a menos de la tolerancia de conexión).

Al aceptar, la ventana se esconde y se traza con clics en el mapa: un clic por vértice, clic derecho, doble clic o Intro terminan la tubería y se sigue con la siguiente con el mismo diámetro; Esc termina y la ventana vuelve. Con el imán del proyecto activado, los extremos se pegan a las otras tuberías, la fuente y las válvulas; no hace falta cortar las líneas en las uniones.

- El diámetro se guarda en el campo `tuberia` de cada línea y se rotula en el mapa («Por dimensionar» si lo elige el programa).
- Al calcular, las líneas con diámetro lo respetan en todos sus tramos; en las demás el dimensionamiento elige el menor que cumple la velocidad máxima y la presión (o el de menor costo total, si esa opción está activa).
- **Cambiar el diámetro de las tuberías seleccionadas…** cambia el diámetro de las que tenga seleccionadas en el mapa (*Edit Mainline Pipe* de IRRICAD), a uno del catálogo o de nuevo a «Elegida por el programa».
- **Insertar nodo en la matriz…** (como *Mainline Pipe Junction* de IRRICAD) esconde la ventana y deja poner nodos a mano con un clic sobre una tubería de *Matriz* (quiebres, derivaciones, tees); Esc termina. Un clic fuera de las tuberías se rechaza y donde ya hay un nodo no se repite. Los nodos, puestos solos o a mano, son solo referencias visuales y topológicas: **no cambian el cálculo hidráulico** (la red se arma con las líneas y no parte tramos en los nodos).
- **Conectar válvulas a la matriz…** (como *Valve Connector* de IRRICAD) une cada válvula con la tubería de *Matriz* más cercana mediante un tramo recto, en una sola pasada y sin clics en el mapa. El cuadro previo pide la **longitud máxima del tramo** (100 m por defecto) y el diámetro: con **Igualar a la tubería más cercana** (*Match nearest pipe*) el tramo copia el de la tubería a la que se une; sin marcar, se elige del catálogo o «Elegida por el programa». Una válvula que ya toca la matriz (a menos de la tolerancia de conexión) no recibe tramo; las que quedan más lejos que el máximo se listan sin conectar. Los dos extremos del tramo quedan como nodos y repetir la herramienta no duplica tramos. Es un paso previo a **Calcular**: el dimensionamiento exige todas las válvulas conectadas, una fuente y los turnos asignados. La geometría está en `nucleo/conector_valvulas.py` y el dibujo en `conectar_valvulas_a_la_matriz` (`integracion/red_mapa.py`).
- **Borrar las tuberías seleccionadas** borra de *Matriz* las que estén seleccionadas en el mapa (herramienta de selección de QGIS) y los nodos que se quedan sin tubería; **Borrar toda la tubería matriz** pide confirmación y vacía las dos capas. Un nodo en una T se queda mientras otra tubería pase por él. Borrar a mano con la edición de QGIS también sirve, pero deja los nodos.
- Si una línea usa una tubería que ya no está en el catálogo, el cálculo avisa cuál es.

## Base de datos de materiales

Menú **RiegoLibre → Materiales y documentos → Base de datos de materiales**. Es una sola base para todos los proyectos, como la de IRRICAD:

- **Importar base de IRRICAD (.mdb)** lee el archivo directamente, sin instalar Microsoft Access ni drivers (lector propio en Python, para Access 97 y 2000-2003). Se importan las pestañas *Pipes*, *Tapes*, *Valves* y *Other Hydraulics*. Las bombas, los aspersores y las boquillas se dejan para más adelante.
- La base se guarda en `%APPDATA%\RiegoLibre\base_datos.json`. Al importar otra vez o al volver al catálogo genérico, la anterior queda como copia de respaldo (`.bak`). La variable de entorno `RIEGOLIBRE_BASE` permite usar otro archivo.
- Las ventanas de diseño ofrecen las tuberías según su uso en IRRICAD: *L* para laterales, *Z* para portalaterales y *M* para la red principal. Las tuberías sin uso quedan en la base, pero no se ofrecen. Si la base no tiene tuberías para un uso, se usan las del catálogo genérico.
- Los laterales con gotero (*Tapes*) aparecen como tuberías de lateral. Al elegir uno, su emisor y su espaciamiento quedan fijados. El emisor sigue q = k·hˣ (L/h y m). Con x = 0 es autocompensado desde la *Minimum PC Pressure* (o, si no hay, desde la presión mínima) hasta la presión máxima. El *barb factor* se usa como longitud equivalente de cada emisor.
- Las válvulas y los otros elementos hidráulicos guardan su pérdida H = K·Qⁿ + C (H en m, Q en m³/h) y su rango de caudal. Todavía no entran en el cálculo.
- La ventana muestra la base en pestañas, con un buscador. La edición de registros es la fase 2.

## Lista de materiales y costos

Menú **RiegoLibre → Materiales y documentos → Lista de materiales y costos**:

- **Metrado**: se arma con las capas de resultado del proyecto (subunidades en el mapa y red principal):
  - metros de tubería por tipo en laterales, portalaterales y red principal,
  - número de emisores,
  - conectores iniciales y cierres (uno por lateral),
  - válvulas de subunidad y bomba.
- **Lista de precios**: un CSV con las columnas `codigo, descripcion, unidad, precio`. Las tuberías se reconocen por su descripción (material, diámetro y clase), por ejemplo «PVC PIPE UF 63mm C-5 x 6 METERS». Si la descripción indica un largo de tubo («x 6 METERS»), el precio es por tubo; los largos de bobina («500m», «B-450M») indican precio por metro.
- **Asignación automática**: las tuberías y los conectores iniciales reciben su artículo equivalente. Si hay varios, se usa el de precio central (mediana).
- **Asignación manual**: el resto se elige con doble clic y un buscador. La elección queda guardada en el proyecto de QGIS.
- **Desperdicio**: porcentaje configurable sobre los metros de tubería. El número de tubos se redondea hacia arriba.
- **Exportación**: a Excel (.xlsx) con fórmula de total, o a CSV.

Los precios son referenciales: actualice la lista de precios cuando cambie.

## Memoria de cálculo

Menú **RiegoLibre → Materiales y documentos → Memoria de cálculo**. Cada vez que se calcula una subunidad en el mapa o la red principal, el resumen del cálculo queda guardado en sus capas de resultado. La memoria se arma con esos resúmenes:

1. Datos del proyecto: cliente, ubicación, proyectista y fecha. Quedan guardados en el proyecto de QGIS.
2. Resumen: área, caudal, punto de diseño de la bomba, costo y si se cumplen los criterios.
3. Plano general con las capas visibles, barra de escala y norte.
4. Bases de cálculo: solo las fórmulas que se usaron.
5. Cada subunidad:
   - datos de diseño y resultados hidráulicos,
   - tabla de selección del diámetro del portalateral,
   - gráfico de presiones.
6. Red principal:
   - tuberías por tramo,
   - válvulas,
   - perfil de la ruta crítica.
7. Equipo de bombeo: CDT desglosada, potencia, motor comercial sugerido y turnos.
8. Presupuesto, con la lista de precios, la moneda, el desperdicio y los artículos elegidos en la ventana de materiales.
9. Observaciones.

Se exporta a **PDF**, a **ODT**, que se abre y edita en Word o LibreOffice, o a **HTML** con las imágenes incluidas. Si cambia el diseño, vuelva a calcular y pulse *Actualizar vista previa*.

## Método de cálculo

**Lateral.** Se calcula paso a paso desde el último emisor hacia la entrada. En cada tramo se suman el caudal real de los emisores aguas abajo, la pérdida por fricción y el desnivel del terreno, ya sea con pendiente uniforme o con el perfil del DEM. La inserción de cada emisor se modela como una longitud equivalente.

**Criterios de diseño.**
- Emisor no compensado: la presión de entrada se fija para que el caudal medio sea el nominal. La variación de caudal admisible es del 10 % por defecto.
- Emisor autocompensado: la presión de entrada se fija para que el emisor más desfavorecido reciba la presión mínima de compensación. Se exige además que ningún emisor quede fuera del rango.

**Portalateral.** Para cada lateral distinto se construye una sola vez su curva: caudal y presiones extremas de los emisores en función de la presión de entrada. Con ella se resuelve el portalateral rápidamente, y con la solución final se calcula cada lateral en detalle.

**Subunidad.** La válvula puede estar en un extremo del portalateral o en el centro. En el centro hay dos ramas que reciben la misma presión, y con pendiente una sube y la otra baja. Los laterales de cada lado pueden tener su propia pendiente transversal.

**Selección del diámetro del portalateral.** Se evalúan todas las tuberías del catálogo y se elige la de menor diámetro nominal que cumple estas condiciones. Entre tubos del mismo diámetro se prefiere la clase de presión más baja: pared más delgada, más diámetro interior y menor precio.
- variación de caudal en toda la subunidad,
- velocidad máxima en el portalateral,
- presión de entrada máxima, si se indica,
- presión nominal de la tubería,
- todos los emisores dentro de su rango de compensación.

**Portalateral telescópico.** Con *Diámetros: hasta dos* o *hasta tres*, el portalateral puede reducir su diámetro hacia el final, donde lleva menos caudal.
- La tubería de la entrada es la que cumpliría sola en todo el portalateral.
- Para el tramo final se prueba cada diámetro menor, con la clase de presión más baja que resiste. Una búsqueda binaria entre las conexiones encuentra el punto de cambio más cercano a la válvula que sigue cumpliendo los criterios: variación de caudal, velocidad en cada tramo y presión nominal de cada tubería.
- Se elige la alternativa con menos material (longitud × diámetro²) y se repite con el tramo siguiente.
- Con la válvula en el centro, el cambio de diámetro está a la misma distancia de la válvula en las dos ramas.
- En el mapa, cada tramo del portalateral lleva su tubería, de modo que el metrado sale por tubería.

**Fricción.**
- Darcy-Weisbach con factor de Swamee-Jain en régimen turbulento y 64/Re en laminar. Es la opción recomendada para laterales, que trabajan con números de Reynolds bajos al final.
- Hazen-Williams como alternativa.

**Convención de pendiente.** Positiva cuando el terreno sube desde la entrada hacia el final.

**Aspersión** (`nucleo/aspersion.py`, primera etapa).
- El aspersor sigue q = k·hᵇ con la presión en la boquilla. Entre el lateral y la boquilla se descuentan la altura del elevador y su pérdida (Darcy a lo largo del tubo más K = 1 de la te). Así el aspersor se comporta como un emisor más y el lateral se calcula con el mismo motor paso a paso del goteo.
- El primer aspersor va a medio espaciamiento de la entrada. La presión de entrada se fija para que el caudal medio sea el nominal (presión media = nominal).
- El lateral cumple si la diferencia de presión entre boquillas no pasa el 20 % de la nominal (regla de Christiansen, un 10 % de caudal) y ningún aspersor sale de su rango de trabajo. *Número máximo de aspersores* busca el lateral más largo que lo cumple.
- Marco rectangular o triangular: pluviometría = q / (Se·Sl). La separación máxima es una fracción del diámetro mojado según el viento: menos de 2 m/s, 60 %; de 2 a 4 m/s, 50 %; más de 4 m/s, 40 % (triangular, +5 %). Si la pluviometría supera la infiltración básica del suelo hay escorrentía. El tiempo de riego es la lámina bruta entre la pluviometría.
- El catálogo `datos/aspersores.json` trae aspersores genéricos (caudal de orificio con Cd 0.95). Los de IRRICAD llegarán con las pestañas *Outlets* y *Nozzles*.

## Importar un diseño del servidor MCP

El servidor MCP de [`mcp_riegolibre/`](mcp_riegolibre/README.md) diseña un proyecto a partir de instrucciones,
sin QGIS. **RiegoLibre → Terreno y lotes → Importar diseño del MCP…** lo convierte en un borrador para terminar en
QGIS: se elige el `…_datos.json` que escribe `exportar_proyecto` y, con esos datos, se rehacen los bloques con las
mismas funciones de la herramienta *Bloque de goteo* (no se copian las geometrías del GeoJSON del servidor):

- una capa de lotes «Lotes · proyecto» con los parámetros del bloque guardados en cada lote (campo `bloque`,
  como al pulsar *Aplicar y calcular*), y el grupo *RiegoLibre · lote* con laterales, portalateral y válvula;
  con `subdivision`, cada sub-bloque es un lote (`lote-1`, `lote-2`…);
- el DEM (`terreno.tipo = dem`) como capa ráster; un terreno `plano` o `puntos` se escribe antes como `.asc`
  junto al archivo de datos;
- la `fuente` en la capa «Fuente»; `red.matriz` en «Matriz» y «Nodos de la matriz», con las válvulas unidas
  como *Conector de válvulas*. Si el diseño no trae la matriz se puede dar un GeoJSON de líneas aparte (la
  ventana propone `matriz_trazada.geojson` si está junto a los datos);
- con más de un turno, los turnos repartidos como el servidor, pintados en «Turnos de riego»;
- una `cinta` definida en el diseño (no en la base de datos) se agrega a la base de datos si se marca la
  casilla; si no, sirve solo para esta importación y para recalcular un lote habrá que agregarla.

Las capas pasan al GeoPackage del proyecto como las demás. Después se sigue como con un diseño hecho a mano:
*Red principal y bomba*, materiales y memoria. Si el proyecto ya tiene lotes con los mismos nombres, la importación
se detiene para no pisarlos. Con el caso Fruveg (61 lotes, DEM de 1 m) da los mismos portalaterales que el
servidor y presiones en la válvula a menos de 0.1 m (el complemento lee el DEM por celda y el servidor interpola).
Código: `integracion/importar_mcp.py` y `gui/dialogo_importar_mcp.py`.

## Programa independiente (prototipo)

RiegoLibre también abre como programa propio, con su ventana, sin la interfaz de QGIS. Por dentro usa las
librerías de QGIS instaladas en el equipo (lienzo del mapa, capas, GDAL, GeoPackage), así que sigue haciendo
falta tener QGIS instalado. Para abrirlo, doble clic en `RiegoLibre.bat`, en la raíz del repositorio, o:

```powershell
.\RiegoLibre.bat "C:\ruta\al\proyecto.qgz"
```

- La ventana (`riegolibre_app/ventana.py`) tiene el mapa, el panel de capas y los menús **Proyecto** (nuevo,
  abrir, guardar, sistema de coordenadas), **Capas** (agregar vectorial o ráster, editar, agregar entidad,
  quitar), **Ver** (desplazar, acercar, alejar, toda la extensión) y **Ayuda**; la barra de estado muestra la
  coordenada, la escala y el SRC.
- Las herramientas son las mismas del complemento, sin cambiar una línea: la ventana le ofrece la misma
  interfaz que QGIS le da (`mapCanvas`, `messageBar`, `mainWindow`, `statusBarIface`, `setActiveLayer`,
  `actionAddFeature`…), así que el menú y la barra **RiegoLibre** salen completos.
- Las capas nuevas entran como en QGIS: encima de la capa elegida en el panel y quedan elegidas.
- Los proyectos son `.qgz` normales: se abren también en QGIS, y al guardar las capas de RiegoLibre pasan al
  GeoPackage junto al proyecto.
- Probado a mano con el diseño de prueba del servidor MCP: importar, «Bloque de goteo», «Red principal y
  bomba» y guardar y volver a abrir dan lo mismo que en QGIS.

Falta para que sea un programa completo: tabla de atributos, propiedades y estilo de las capas, mapa satelital
de fondo, deshacer, impresión de planos, un instalador propio (hoy abre una consola junto a la ventana) e
iconos de la ventana. Pruebas: `tests/test_aplicacion_qgis.py`.

## Programa de escritorio sin QGIS

`riegolibre_escritorio/` es RiegoLibre como programa propio que **no necesita QGIS**: basta Python con PySide6
(`python -m pip install -r requisitos_escritorio.txt`). Se abre con doble clic en `RiegoLibre_escritorio.bat` o:

```powershell
.\RiegoLibre_escritorio.bat "C:\ruta\al\proyecto.riegolibre"
```

Primera etapa (2026-11-26):

- **Proyecto → Importar diseño del MCP…** abre el `…_datos.json` de `exportar_proyecto` y rehace los bloques con el
  motor del servidor (`mcp_riegolibre/motor.py`) y el núcleo; los lotes de un GeoJSON aparte y el DEM (`.asc`) quedan
  dentro del proyecto.
- Lienzo propio: zoom con la rueda, desplazamiento arrastrando, **Ver → Toda la extensión**; coordenadas y escala en
  la barra de estado. Al pasar el ratón por un lote, una válvula o un tramo se ven sus datos.
- **Barra de capas** a la derecha, como la de IRRICAD: TEXTO, FUENTE, VÁLVULAS, RED_PRINCIPAL, MATRIZ_DIBUJADA,
  PORTALATERALES, LATERALES y LOTES, con casillas «ver» e «imprimir» y las propiedades de la capa elegida (color,
  tipo de línea y grosor). Los lotes se rellenan con el color de su turno y la red con un color por diámetro.
- Tabla de subunidades abajo (doble clic: acercar a esa subunidad).
- **Red y bomba → Red principal y bomba…**: los mismos criterios de la ventana del complemento (pérdida en cada
  válvula 2 m, cabezal 7 m, succión 2 m, eficiencia 70 %…), une las válvulas a la matriz, dimensiona la red y
  muestra resumen, tramos, turnos y válvulas. Con el diseño de prueba da lo mismo que el complemento (CDT 30.04 m
  contra 30.06 m: el complemento lee el plano como DEM por celda).
- Proyecto `.riegolibre`: una base SQLite con los datos del diseño, los parámetros, los estilos de capas, el DEM y una
  copia del resumen y de las geometrías en GeoJSON. Exporta la memoria de cálculo en HTML.

Siguientes etapas: edición en el mapa (lotes, fuente y matriz con imán, deshacer), terreno (DEM, DXF, satelital),
las demás ventanas del complemento, planos e instalador. Detalle en `docs/notas/programa-escritorio.md`; pruebas en
`tests/test_escritorio.py`.

## Hoja de ruta

- [x] Motor hidráulico de laterales y portalaterales
- [x] Calculadora de lateral con perfil del terreno desde un DEM
- [x] Ventana de subunidad: portalateral y laterales, selección de diámetro
- [x] Portalateral telescópico (dos o tres diámetros)
- [x] Herramientas de mapa: dibujar el bloque y generar los laterales automáticamente
- [x] Trazado automático de laterales, portalaterales y subunidades sobre un terreno de cualquier forma
- [x] Red principal, carga dinámica total y punto de diseño de la bomba
- [x] Lista de materiales y costos con lista de precios
- [x] Base de datos de materiales: importación desde IRRICAD (fase 1)
- [ ] Base de datos: edición de registros (fase 2) y válvulas y filtros en el cálculo (fase 3)
- [x] Memoria de cálculo (PDF, ODT y HTML)
- [x] Elección de diámetros de la red por costo (tubería + energía de bombeo)
- [x] Riego por aspersión, primera etapa: calculadora de lateral de aspersión
- [ ] Riego por aspersión: bloque en el mapa, red y aspersores de la base de IRRICAD
- [x] Programa independiente, prototipo: ventana propia con las librerías de QGIS
- [x] Programa de escritorio sin QGIS, primera etapa: importar del MCP, lienzo, barra de capas, red y bomba, proyecto propio
- [ ] Programa de escritorio: edición en el mapa, terreno, demás ventanas, planos e instalador

## Autoría y licencia

RiegoLibre fue creado por **Jhonatan Chilet**. Copyright (C) 2026 Jhonatan Chilet.

Es software libre bajo la licencia [GPL-3.0](LICENSE), con condiciones adicionales de la sección 7 de esa licencia: toda copia o versión modificada debe conservar la atribución al autor, y no se permite falsear el origen del programa. El texto completo está en [`riegolibre/NOTICE`](riegolibre/NOTICE) y en la ventana **Ayuda → Acerca de RiegoLibre**.

El código se escribió con asistencia de inteligencia artificial (Claude, de Anthropic). La dirección del proyecto, los criterios de diseño y la validación de la hidráulica y de la interfaz son de Jhonatan Chilet.

### Marcas y compatibilidad

RiegoLibre es un proyecto independiente: **no está afiliado, patrocinado ni respaldado por IRRICAD ni por Lindsay Corporation**. «IRRICAD» y los demás nombres de productos o empresas citados son marcas de sus respectivos dueños y se mencionan solo para indicar compatibilidad o para describir un flujo de trabajo parecido. El código es propio; no contiene código, iconos, textos de ayuda ni bases de datos de otros programas. Las bases de IRRICAD (`.mdb`) solo se leen cuando el usuario elige su propio archivo; este repositorio no las distribuye (los `.mdb` de `tests/datos/` son datos ficticios generados con `generar_mdb.ps1`).
