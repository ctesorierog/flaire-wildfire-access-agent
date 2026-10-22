# Vegetación · revisión v0.3.2 (respuesta a la revisión del equipo, 2 oct 2026)

Fuente: Gobierno Vasco, **Mapa Forestal del País Vasco 2024 / Inventario Forestal 1:10.000** (`INV_FORESTAL_2024_10000_ETRS89.zip`,
datos a 31/12/2024, actualizado 06/03/2025, atribución «Eusko Jaurlaritza / Gobierno Vasco»). Script: `05_codigo/pipeline/official_layers.py`
(etapa `forest`). Recorte = Tolosaldea + 2 km (no se corta en el límite municipal).

## 1. El archivo con las geometrías

`03_datos_procesados/vegetacion/vegetation_forest_map_2024.gpkg` (81 MB, EPSG:25830). Tiene tres capas:

| Capa | Contenido |
|---|---|
| `vegetation_forest_map_2024` | **18.691 polígonos** con **todos los atributos originales**: TIPES10, SP1/SP2/SP3 con nombres es/eu, O1–O3, E1–E3, EMASA1–3, FCCARB, FORARB, DISTRIB, FCCMAT, FORMAT, FORMAT2, FCCHER, FORHER, ATRIBUTO, OSUPTIP, OCUOSUP, HMMAT y MODCOM_I. Además lleva las **categorías añadidas**: `class_code`, `veg_class`, `veg_subclass`, `leaf_type`, `mixed_rule`, `occ_other_leaf_tenths` (nuevo), `class_group`, `is_veg_proximity`, `clipped`, `in_tolosaldea`, `area_orig_ha`, `area_ha` y `area_in_tolosaldea_ha`. |
| `vegetation_db` | Versión ligera que se carga en la base de datos (clase, combustible y fuente). |
| `clip_extent` | La extensión del recorte. |

Los CSV que lo acompañan son `class_dictionary.csv` (263 códigos), `forest_area_by_class.csv` y `species_leaf_type.csv` (nuevo: cada especie del recorte con su tipo de hoja, para revisarlo a mano).

## 2. Comprobación del mapa (recalculada sobre el archivo)

| Comprobación | Resultado |
|---|---|
| Geometrías no válidas / vacías | **0 / 0** de 18.691 |
| Superficie de Tolosaldea (límites oficiales) | 32.354,68 ha |
| Unión de polígonos dentro de Tolosaldea | 32.354,65 ha |
| **Huecos** | **0,026 ha en total**, repartidos en 322 astillas de digitalización; la mayor mide 32,5 m² |
| **Solapes** (suma de áreas − unión) | **0,000 ha** |
| Fuera de la CAPV | El margen de 2 km entra 52 km² en Navarra, que **no** tiene cobertura (el mapa es de la CAPV). Afecta a 4 edificios residenciales a ≤ 300 m del límite; añadir la vegetación OSM allí no cambia ninguno. |

Conclusión: el mapa es una **partición completa del territorio**. Cubre el 100 % de Tolosaldea, sin solapes y con huecos despreciables. Los totales por clase de las tablas proceden de estas mismas geometrías.

## 3. Pinabete y Tsuga corregidos, y también Pinsapo

El nombre de la especie se clasificaba con una lista de palabras de coníferas en la que faltaban **Pinabete** (*Abies alba*), **Tsuga** y **Pinsapo** (*Abies pinsapo*). Esta última no estaba en la revisión del equipo, pero tenía el mismo error. Las tres caían por defecto en «frondosa». La lista se ha ampliado y ahora las tres son **conífera**.

- **Afecta a 4 filas del diccionario**, todas de plantación. En la CAPV suman 35,3 ha de Pinabete, 13,1 ha de Pinsapo y 13,5 ha de Tsuga; en Tolosaldea, 0 ha.
- **Revisión completa:** se han repasado las 69 especies del recorte y los 263 códigos de la CAPV (`species_leaf_type.csv`). No queda ninguna conífera clasificada como frondosa.

## 4. Reglas añadidas: definición y justificación

**a) Qué es O1/O2/O3.** Es la **ocupación de cada especie en décimas de la cubierta arbolada**, que es la convención del Mapa Forestal de España (MFE) y del IFN. Se comprueba en los datos: **O1 + O2 + O3 = 10 en los 14.095 polígonos arbolados** del recorte, y 0 en los 4.596 polígonos sin árboles. Por tanto, `O2 = 3` significa que la segunda especie ocupa el 30 % de la cubierta arbolada.
Pendiente: la ficha de metadatos de geoEuskadi no se pudo consultar automáticamente (robots.txt). Hay que **confirmar esta definición en la ficha oficial** antes de presentar.

**b) Regla de masa mixta, v0.3.2.** Un polígono de bosque (TIPES10 11, 12 o 14) es **mixto** en dos casos:
- si SP1 ya es un código mixto («Plantaciones de frondosas y coníferas variadas»);
- si las especies de **la otra familia de hoja** que aparecen en **SP2 y SP3 juntas** ocupan **≥ 3 décimas** (30 %).

Las familias son conífera y frondosa; el eucalipto cuenta como frondosa. La ocupación de la otra familia se guarda en el campo nuevo `occ_other_leaf_tenths`.
- **SP3:** antes solo se miraba SP2, ahora también SP3. En el recorte hay 266 polígonos con SP3, y en 7 de ellos el cambio decide que pasen a mixtos.
- **SP2 o SP3 con un código mixto:** si la especie secundaria es ella misma un código mixto, no se cuenta como «otra familia», porque su composición es ambigua. Por eso 2 polígonos (7,1 ha) dejan de ser mixtos.
- **Efecto total de la corrección:** cambian **20 polígonos** (38 ha en Tolosaldea). Los bosques naturales mixtos pasan de 89 a **105,8 ha**.
- **Sensibilidad del umbral** (superficie de masas mixtas en Tolosaldea, natural más plantación, sobre 20.847 ha de bosque): **2 décimas = 1.877 ha · 3 décimas = 1.059 ha · 4 décimas = 602 ha · 5 décimas = 386 ha.**
- **Justificación:** el 30 % es una **decisión del proyecto**, no un estándar oficial. Con ella, la especie secundaria debe ser una parte visible del dosel y no un acompañamiento.
- **Impacto en el análisis:** el umbral **no cambia** qué edificios están cerca de vegetación, porque todas las clases de bosque cuentan igual. Solo cambia la etiqueta de clase. En 3 de los 3.331 edificios del conjunto, la clase más cercana pasa de frondosa a mixta.

**c) Decisiones del proyecto (no son reglas oficiales).**
- **Qué cuenta como «vegetación» para la proximidad:** bosque natural, de galería y de plantación, más matorral (TIPES10 11, 12, 14, 21 y 23). **Los prados y pastos (31, 73 y 74) quedan fuera.** Si se incluyeran, el **87 %** de los edificios residenciales quedaría a ≤ 100 m (4.596 de 5.292) y el criterio dejaría de distinguir nada.
- **Umbral de 100 m.** Sensibilidad con la regla oficial (residenciales a ≤ X m): 25 m = 1.203 · 50 m = 1.991 · **100 m = 3.331** · 200 m = 4.916.
- Otras variantes a 100 m: solo bosque = 3.304 · sin bosque de galería = 3.078 · sin mosaico pastizal-matorral = 3.330.
- El tipo de árbol **no** mide directamente el combustible ni la probabilidad de incendio.

Estas tres decisiones deben quedar **acordadas por el equipo** y figurar como tales en la presentación.

## 5. Qué cambia en los datos del agente

**Ninguna cifra de cobertura cambia.** La distancia a la vegetación y el conjunto de 3.331 edificios son los mismos.

Solo cambia la etiqueta `veg_clase_cercana` de 3 edificios: ES.GFA.BU.28972, ES.GFA.BU.41875 y ES.GFA.BU.41957 pasan de forest_broadleaf a forest_mixed. Está actualizada en `edificios.csv` y entrará en la próxima versión del agente en la plataforma.
