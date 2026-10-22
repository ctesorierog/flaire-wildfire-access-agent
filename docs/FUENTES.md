# FUENTES · de la fuente a la base

Registro completo (URL, organismo, licencia, fecha de descarga, edición, fichero, sha256) en `datos/fuentes.csv`. Recuentos tomados de
los informes de calidad del equipo (`reports/quality_*.md`, `reports/linker_validation.md`) y del propio paquete. Código reproducible
en el repositorio del equipo (`code/`); este paquete no incluye los datos brutos.

## 1. Territorio · límites municipales
- **Fuente:** geoEuskadi, *Límites municipales de la CAPV 1:5.000* (`MUNICIPIOS_5000_ETRS89`, actualizado 07/05/2025; la página
  advierte que no es cartografía oficial a efectos legales). `SRC-GV-MUNICIPIOS5000-20250507`.
- 259 unidades CAPV → 88 municipios de Gipuzkoa → **28 de Tolosaldea** (campo oficial de área funcional = TOLOSALDEA, los mismos 28
  de la lista del equipo). Suma = unión = 323,5 km², sin solapes. Enirio-Aralar queda fuera (contexto).
- Comparado con OSM admin8: IoU 0,993, diferencias de borde de decenas a ~250 m.

## 2. Edificios · B5M INSPIRE
- **Fuente:** Diputación Foral de Gipuzkoa – B5M, *INSPIRE Buildings Gipuzkoa* (`GFA_INSPIRE_BU`, metadatos 2026-08-08). `SRC-B5M-BU`.
  Contabilidad completa de filas en `datos/auditoria.json`.
- **124.140** filas brutas en Gipuzkoa. 114 `INSPIREID` repetidos en 458 filas (copias idénticas por nombre/referencia catastral) →
  una fila por id (344 filas eliminadas en Gipuzkoa).
- Municipio por **punto interior** del contorno dentro de los límites oficiales → 14.016; 1 duplicado de geometría eliminado →
  **14.015 edificios en Tolosaldea** (4 edificios que cruzan el borde quedan en Errezil 2 y Legorreta 2 por su punto interior;
  respecto a los límites OSM: 12 entran, 1 sale y 99 cambian de municipio, todos a < 160 m del borde).
- Regla residencial (CURRENTUSE con `collectiveResidence` o `individualResidence`) → **5.292 residenciales** (967 no residenciales,
  7.756 de uso desconocido: construcciones B5M sin unidad catastral; 252 de ellas con nombre de caserío a ≤ 100 m de vegetación quedan
  fuera por la regla — límite conocido).
- Proximidad a vegetación ≤ 100 m (ver §3) → **3.331 edificios del conjunto de análisis, 10.651 viviendas** (viviendas nulas: 0).
- Por zona meteorológica: C029 Zizurkil 1.880, C026 Berastegi 864, C058 Bidania 587.

## 3. Vegetación · Mapa Forestal del País Vasco 2024
- **Fuente:** Gobierno Vasco, *Mapa Forestal / Inventario Forestal 2024 1:10.000* (`INV_FORESTAL_2024_10000_ETRS89`, datos a 31/12/2024,
  actualizado 06/03/2025). `SRC-GV-INVFORESTAL-2024`.
- Recorte = Tolosaldea + 2 km. Vegetación para proximidad = bosque (natural, de galería, plantación) + matorral (TIPES10 11, 12, 14, 21, 23):
  23.110 ha = 71,4 % de Tolosaldea. Prados y pastos excluidos (con ellos el 87 % de los residenciales quedaría a ≤ 100 m y la regla dejaría
  de discriminar).
- Distancia = del contorno del edificio al polígono más cercano (comprobación por fuerza bruta en 300 edificios: diferencia máx. 0,005 m).
- Clase más cercana en el conjunto: frondosas 2.381, plantación 729, matorral 207, mixto 14.
- Sensibilidad (residenciales a ≤ 100 m): sin bosques de galería 3.078; solo bosque 3.304; con prados 4.596.

## 4. Red viaria y parques
- **Red:** OpenStreetMap vía Geofabrik, extractos **País Vasco** y **Navarra** (2026-09-30), ODbL. `SRC-OSM-GEOFABRIK-PV-20260930`,
  `SRC-OSM-GEOFABRIK-NAV-20260930`. Lectura completa del `.osm.pbf` (incluye todas las rampas `*_link`; 0 conectores sintéticos).
  En el extracto País Vasco: 167.468 vías leídas, 157.559 conservadas, 245.594 tramos. Excluidas: pasillos de aparcamiento, acceso privado/no
  (salvo emergencias), etc. Grafo por defecto = componente fuertemente conexa mayor sin pistas.
- **Velocidades:** por clase de vía (autopista 100, autovía 80, primaria 70, secundaria 60, terciaria 50, sin clasificar 40, residencial 30,
  servicio 15 km/h; rampas × 0,6); `maxspeed` de OSM solo en ≈ 15 % de los tramos → **≈ 85 % de velocidades supuestas**. Camión = × 0,9 / × 0,8.
- **Parques:** B5M `GFA_DSET_FIREST` (10 registros, punto oficial de dirección, no comprobado en ortofoto). `SRC-B5M-FIREST`. 9 en base;
  Hondarribia excluido (punto del aeropuerto). Oria (Tolosa) es el parque más cercano para 27 de los 28 centros municipales.
- **Comprobaciones manuales de rutas** (`datos/auditoria.json`, recalculadas con otra implementación, networkx): Oria → `ES.GFA.BU.37890`
  (Amezketa) 18,91 min / 13,69 km; Oria → `ES.GFA.BU.53078` (Berastegi) 12,27 min / 11,86 km; Oria → Leitza (Navarra) 18,56 min con
  4,42 km en Navarra: coinciden. Cobertura k=0 a 12 min recalculada con pandas: 2.712 (ligero) y 2.177 (camión), igual que la BD y
  `escenarios.csv`.
- **Navarra:** añadir las carreteras de Navarra no cambia ninguna cifra (ninguna ruta más rápida a un edificio del conjunto pasa por
  Navarra); lo que faltaría para los pueblos de borde son **parques** navarros (Leitza, Lekunberri…), sin fuente oficial en el paquete.

## 5. Tiempos de desplazamiento
`tiempo = acceso origen + red + tramo parcial + acceso edificio`; acceso = distancia en línea recta al tramo elegible más cercano a 15 km/h;
Dijkstra dirigido desde cada origen (sentido de salida). Edificio a > 150 m de una vía elegible → **sin ruta**: 726 de los 14.015
edificios y **47 del conjunto de análisis** (Berastegi 9, Elduain 9, Tolosa 5, Albiztur 4, …); se informan y nunca se eliminan.
Variante informativa con pistas a 10 km/h (no usada en escenarios): 42 de los 47 tendrían ruta y 9 quedarían a ≤ 12 min.
Enganche a la red: mediana 16,7 m, p90 69,6 m (los 14.015 edificios); conjunto de análisis: mediana 13,8 m, p90 27,1 m. Tiempos redondeados a 0,01 min; el optimizador trabaja con esos valores.

## 6. Candidatas (10 lugares de estudio)
- Versión v0.3: re-selección con el conjunto oficial (7 candidatas se mantienen, 3 cambian). Pool desde OSM: instalaciones forales, aparcamientos ≥ 400 m², frontones/polideportivos con aparcamiento, zonas industriales ≥ 2.000 m²,
  áreas de picnic (458 sitios utilizables en el entorno). `SRC-FLAIRE-CAND-V03`.
- Regla transparente (no usa el objetivo del optimizador): elegibilidad (dentro de los 28 municipios, enganche ≤ 60 m, no en autopista,
  ≥ 2 km de un parque), clusters de edificios en déficit (> 12 min) → un sitio por cluster principal, después dispersión max-min, ≥ 3 km entre
  candidatas, con comprobación por carretera. Motivo de cada una en `datos/candidatos.csv`.
- Cada candidata tiene **6 comprobaciones de campo pendientes** (espacio para pesado, titularidad, acceso de camión, agua, tráfico, ortofoto).

## 7. Meteorología
- **Fuente:** Euskalmet (Gobierno Vasco, Open Data Euskadi), lecturas de 10 min 2018–2023 de 10 estaciones en/junto a Tolosaldea
  (`SRC-EUSKALMET-MET-2018…2023`) y catálogo de estaciones (`SRC-EUSKALMET-STATIONS`). CC BY 4.0.
- 16,7 millones de valores; marcas de tiempo en **UTC** (comprobado con cambios de hora e irradiancia); viento en m/s.
- Día válido si ≥ 130 de 144 valores por variable; control espacial de valores anómalos. Huecos: C026 Berastegi sin datos jul 2021–may 2022;
  C058 Bidania sin HR jul–sep 2018.
- Regla **ADV-v1** (elegida entre 6 variantes: calculable en todas las estaciones, recuentos no triviales). Periodo común completo para las
  3 zonas: **2019, 2020, 2022, 2023**. Jul–ago: C026 21/248 días (0,085), C029 13/248 (0,052), C058 18/235 (0,077). Intervalos ±1 sd
  solapan → pesos casi planos. Septiembre es el mes con más días adversos en la mayoría de estaciones.

## 8. Escenarios
`escenarios.csv` = 36 combinaciones de parámetros (A/B × 10/12/15 min × ligero/camión × meteo/uniforme/firescope) × k = 0..6; las 24
de meteo/uniforme calculadas con `code/manager/optimizer.py` (búsqueda exhaustiva), las 12 de firescope con el mismo motor del agente. El agente las **recalcula en vivo** con `flaire_data.optimizar` y las pruebas
comprueban que coinciden fila a fila (selección, edificios, peor tiempo, sin ruta, empates).

## 9. Cómo reproducir
```
python3 code/territory_buildings.py && python3 code/official_layers.py backup limits buildings forest proximity sources report
python3 code/network.py
python3 code/weather.py
python3 code/link_build.py            # tiempos, candidatas, BD, escenarios, validación y este paquete (agent/datos/)
cd agent && python3 -m pytest tests && python3 tests/generar_docs.py
```


## Índice de riesgo FireScope (peso alternativo, experimental)
- **Origen:** INSAIT, *FireScope Risk 2026*, `europe_risk.tif` (Hugging Face, CC BY 4.0; artículo arXiv 2511.17171, CVPR 2026). Ráster europeo de 12,3 GB, 30 m, EPSG:3857, uint8 (0–254, 255 = sin dato), sin README que documente la escala.
- **Cómo se obtuvo:** solo se leyeron las 20 teselas (512×512, LZW) que cubren Tolosaldea mediante peticiones HTTP Range (1,7 MB transferidos), decodificadas y guardadas como ventana 1.487×1.629 px (`raw/firescope/`, sha256 en `datos/fuentes.csv`). Comprobación de coherencia espacial: diferencia media entre píxeles vecinos 0,64 frente a 32,8 entre píxeles aleatorios.
- **Uso:** para cada edificio del conjunto de análisis, media de la ventana 9×9 px (±~90 m) → `fs_indice`; `peso_firescope` = `fs_indice` / media (media 1). Rango 65–188; más alto en Amezketa/Abaltzisketa (Aralar) y Berastegi, más bajo en el fondo del valle (Ibarra, Tolosa). Correlación con `peso_meteo`: 0,55.
- **Límites:** modelo de IA de terceros, no oficial; escala no documentada (se usa solo como peso relativo); variación espacial suave. Sirve como **prueba de robustez**: con pesos históricos, uniformes y FireScope la estrategia A elige los mismos sitios desde k = 3.

## Corrección de la red v0.3.1
Vías OSM `highway=service` con matrícula foral `GI-*` se tratan como `unclassified` (40 km/h): 17 tramos, 3,4 km (p. ej. GI-3712, Aldaba, Tolosa). Detectado por la revisión del jurado interno: el edificio ES.GFA.BU.32835 decidía el «peor tiempo» de la estrategia B por ese error de etiquetado.
