# Fichas de candidatas · Tolosaldea (v0.3.1, 2 oct 2026)

> **v0.3.1 (revisión del jurado):** red corregida (vías `service` con matrícula foral GI-* tratadas como `unclassified`, 40 km/h); la regla de selección da **las mismas 10 candidatas y numeración que v0.3**. Se añaden advertencias específicas en CAND-01, CAND-04, CAND-08 y CAND-09.

Generado por `code/link_build.py` (re-ejecutable). Datos: `processed/candidates/candidates_10.{gpkg,csv,geojson}`, versión de datos **v0.3.1-official**.

> **Ser candidata no significa estar autorizada ni validada.** Son lugares para estudiar cobertura. Cada ficha tiene 6 comprobaciones pendientes de campo. Los tiempos son **estimaciones de desplazamiento** (no tiempos de respuesta). v0.3 usa las capas oficiales: límites municipales geoEuskadi 1:5.000 (SRC-GV-MUNICIPIOS5000-20250507), **Mapa Forestal del País Vasco 2024** (SRC-GV-INVFORESTAL-2024) para el conjunto de análisis (3.331 edificios, antes 1.747 con OSM) y red viaria País Vasco + **Navarra** (OSM). La regla de selección es **la misma que en v0.2**; los números CAND-xx se conservan para los sitios que siguen elegidos (tabla de equivalencias al final).

## Cambios respecto a v0.2

Sitios que se mantienen: **7**, salen: **3**, entran: **3**. Equivalencias en `processed/candidates/candidate_id_mapping_v02_v03.csv`.

| v02_cand_id | v03_cand_id | status | pool_id | name | municipality | site_type | note |
|---|---|---|---|---|---|---|---|
| CAND-01 | CAND-01 | kept | POOL-0005 | Casa Camineros | Asteasu | dfg_facility |  |
| CAND-02 | CAND-02 | kept | POOL-0044 | Aparcamiento sin nombre (Amezketa) | Amezketa | parking |  |
| CAND-03 | CAND-03 | kept | POOL-0050 | Aparcamiento sin nombre (Berastegi) | Berastegi | parking |  |
| CAND-04 | CAND-04 | kept | POOL-0342 | Insalus agua | Lizartza | industrial |  |
| CAND-05 |  | dropped | POOL-0060 | Aparcamiento sin nombre (Bidania-Goiatz) | Bidania-Goiatz | parking | sigue elegible; no elegido por la regla v0.3 (demanda y clusters cambian con el Mapa Forestal); candidata v0.3 más próxima CAND-05 a 1.2 km; edificios en déficit v0.3 a ≤ 2,5 km: 21 |
| CAND-06 | CAND-06 | kept | POOL-0304 | Zona industrial sin nombre (Villabona) | Villabona | industrial |  |
| CAND-07 |  | dropped | POOL-0249 | Frontón sin nombre (Ikaztegieta) | Ikaztegieta | fronton | sigue elegible; no elegido por la regla v0.3 (demanda y clusters cambian con el Mapa Forestal); candidata v0.3 más próxima CAND-07 a 1.2 km; edificios en déficit v0.3 a ≤ 2,5 km: 9 |
| CAND-08 |  | dropped | POOL-0024 | Aparcamiento sin nombre (Anoeta) | Anoeta | parking | sigue elegible; no elegido por la regla v0.3 (demanda y clusters cambian con el Mapa Forestal); candidata v0.3 más próxima CAND-08 a 0.3 km; edificios en déficit v0.3 a ≤ 2,5 km: 5 |
| CAND-09 | CAND-09 | kept | POOL-0411 | Área de picnic sin nombre (Tolosa) | Tolosa | picnic_site |  |
| CAND-10 | CAND-10 | kept | POOL-0040 | Aparcamiento sin nombre (Zizurkil) | Zizurkil | parking |  |
|  | CAND-05 | new | POOL-0255 | Frontoia | Bidania-Goiatz | fronton | nuevo sitio (cluster); hereda el número de la candidata v0.2 más próxima que sale (CAND-05 v0.2 a 1.2 km) |
|  | CAND-08 | new | POOL-0272 | Polideportivo sin nombre (Anoeta) | Anoeta | sports_centre | nuevo sitio (spread); hereda el número de la candidata v0.2 más próxima que sale (CAND-08 v0.2 a 0.3 km) |
|  | CAND-07 | new | POOL-0077 | Aparcamiento sin nombre (Orendain) | Orendain | parking | nuevo sitio (spread); hereda el número de la candidata v0.2 más próxima que sale (CAND-07 v0.2 a 1.2 km) |

## Regla de selección (transparente, no usa el objetivo del optimizador)

1. **Elegibilidad** sobre los 458 sitios utilizables del pool (`candidate_pool`, P4): dentro de los 28 municipios (punto en polígono con los límites oficiales geoEuskadi: 208), tipo en orden de preferencia [1 instalación foral (`dfg_facility`), 2 aparcamiento ≥ 1 000 m², 3 polideportivo/frontón con aparcamiento ≤ 150 m, 4 zona industrial, 5 aparcamiento 400–1 000 m², 6 área de picnic/recreativa], enganche a la red ≤ 60 m, la vía más cercana no es autopista/autovía, y ≥ 2 km en línea recta de cualquier parque existente. **158 sitios elegibles** (por nivel: {'1': 4, '2': 26, '3': 17, '4': 53, '5': 36, '6': 22}). Motivos de exclusión dentro de Tolosaldea: {'<2km_from_park': 35, 'snap>60m': 4, 'site_type_not_in_list;<2km_from_park': 3, 'site_type_not_in_list': 3, 'snap>60m;<2km_from_park': 2, 'on_motorway_trunk;<2km_from_park': 1, 'on_motorway_trunk': 1, 'site_type_not_in_list;snap>60m': 1}. Aparcamientos sin área conocida (nodos OSM), centros culturales y refugios no están en la lista. Detalle: `candidate_eligibility.csv`.
2. **Demanda**: edificios del conjunto de análisis (residencial ∧ ≤ 100 m de bosque/matorral del Mapa Forestal 2024) con tiempo base (9 parques, vehículo ligero) > 12 min: **619** (47 sin ruta por enganche > 150 m; se reportan pero no orientan la selección porque ninguna candidata arregla su enganche) → **572** edificios. Agrupados con DBSCAN (eps 2 km, mín. 5 edificios): 6 clusters + 4 edificios aislados. Cluster **principal** = ≥ 15 edificios en déficit: 5.
3. **Un sitio por cluster principal** (de mayor a menor): el sitio elegible mejor clasificado dentro de la envolvente convexa del cluster + 1 km (si no hay, + 2,5 km), ordenando por nivel de tipo, después por mediana del tiempo desde el sitio a los edificios en déficit del cluster, después por superficie. Separación ≥ 3 km entre candidatas.
4. **Relleno hasta 10 por dispersión territorial max-min** (farthest-first): se toma el edificio en déficit más alejado en línea recta de todos los parques y candidatas ya elegidas, y se le asigna el sitio elegible más cercano (≤ 1 km, si no ≤ 2,5 km; bandas de 500 m y después nivel de tipo), respetando ≥ 3 km entre candidatas.
   **Comprobación por carretera** (pasos 3 y 4): el sitio solo cuenta si llega antes que el parque actual (paso 3: mediana del tiempo al cluster < mediana del tiempo base del cluster; paso 4: tiempo al edificio objetivo < su tiempo base). Evita sitios cercanos en línea recta pero en otro valle. Si ningún sitio cumple, el edificio objetivo se marca como no atendible y se pasa al siguiente más alejado.
5. Las columnas `info_*` (alcance y ganancia a 12 min) se calculan **después** de elegir, solo como información; la elección de combinaciones 0–6 es trabajo del optimizador.

### Clusters de déficit (vehículo ligero, > 12 min, con ruta)

| cluster | n_deficit | median_base_min | worst_base_min | municipalities | major | chosen_cand |
|---|---|---|---|---|---|---|
| 3 | 246 | 13.9 | 18.9 | Amezketa 135, Abaltzisketa 86, Tolosa 18, Orendain 7 | True | CAND-02 |
| 1 | 152 | 14.4 | 20.5 | Asteasu 78, Alkiza 29, Larraul 25, Zizurkil 18, Aduna 2 | True | CAND-01 |
| 5 | 104 | 13.1 | 17.0 | Berastegi 104 | True | CAND-03 |
| 4 | 30 | 13.2 | 16.6 | Orexa 24, Lizartza 6 | True | CAND-04 |
| 0 | 28 | 12.9 | 13.9 | Bidania-Goiatz 20, Albiztur 8 | True | CAND-05 |
| 2 | 8 | 14.5 | 14.7 | Tolosa 8 | False |  |
| -1 | 4 | 12.2 | 12.7 | Bidania-Goiatz 2, Albiztur 1, Villabona 1 | False |  |

(cluster −1 = edificios aislados según DBSCAN)

## Resumen de las 10 candidatas

| cand_id | name | site_type | municipality | lon | lat | snap_m | area_m2 | baseline_light_min | baseline_truck_min | selection_step | info_gain_alone_12_n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAND-01 | Casa Camineros | dfg_facility | Asteasu | -2.13381 | 43.20265 | 9.7 | 133.5 | 16.7 | 20.2 | cluster | 125 |
| CAND-02 | Aparcamiento sin nombre (Amezketa) | parking | Amezketa | -2.08911 | 43.04989 | 10.7 | 1,173.9 | 12.1 | 14.7 | cluster | 246 |
| CAND-03 | Aparcamiento sin nombre (Berastegi) | parking | Berastegi | -1.97815 | 43.12362 | 29.8 | 1,087.4 | 12.2 | 15.2 | cluster | 104 |
| CAND-04 | Insalus agua | industrial | Lizartza | -2.03529 | 43.09573 | 4.2 | 4,549.0 | 8.5 | 10.6 | cluster | 30 |
| CAND-05 | Frontoia | fronton | Bidania-Goiatz | -2.16045 | 43.14039 | 24.3 | 583.6 | 10.1 | 12.4 | cluster | 29 |
| CAND-06 | Zona industrial sin nombre (Villabona) | industrial | Villabona | -2.03956 | 43.20078 | 0.0 | 38,680.5 | 9.2 | 10.6 | spread | 105 |
| CAND-07 | Aparcamiento sin nombre (Orendain) | parking | Orendain | -2.12424 | 43.08247 | 1.5 | 585.9 | 8.1 | 9.6 | spread | 29 |
| CAND-08 | Polideportivo sin nombre (Anoeta) | sports_centre | Anoeta | -2.07088 | 43.16145 | 50.5 |  | 5.5 | 6.4 | spread | 100 |
| CAND-09 | Área de picnic sin nombre (Tolosa) | picnic_site | Tolosa | -2.04090 | 43.05008 | 16.9 | 518.1 | 17.8 | 21.9 | spread | 74 |
| CAND-10 | Aparcamiento sin nombre (Zizurkil) | parking | Zizurkil | -2.07728 | 43.20788 | 22.3 | 1,338.9 | 11.9 | 14.1 | spread | 119 |

## CAND-01 · Casa Camineros (Asteasu)

- **Tipo:** dfg_facility / dfg_named · nivel 1 (diputacion_facility) · pool `POOL-0005` · OSM way 505635740
- **Municipio:** Asteasu (20014), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-01 v0.2
- **Coordenadas:** 43.20265, -2.13381 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20265&mlon=-2.13381#map=17/43.20265/-2.13381)
- **Acceso:** GI-2631 (secondary); enganche a la red a 10 m (nodo 2315750405)
- **Superficie:** 134 m² (huella del edificio OSM; el espacio exterior no está cartografiado)
- **Aparcamiento público más cercano:** 104 m
- **Tiempo actual desde parque:** 16.7 min ligero (GIP-ORIA, 18.1 km) · 20.2 min camión (GIP-ORIA); parque más cercano en línea recta a 9.1 km
- **Motivo de selección:** orden 2 · Cluster de déficit 1 (152 edificios > 12 min: Asteasu 78, Alkiza 29, Larraul 25, Zizurkil 18, Aduna 2). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 9.4 min, superficie); 31 opción(es) elegible(s)
- **Información (no usada para elegir):** 566 edificios del conjunto a ≤ 12 min desde aquí; 125 pasarían a ≤ 12 min si solo se añade esta candidata; 64 edificios en déficit a ≤ 2,5 km
- **⚠ Advertencia específica (revisión v0.3.1):** los 134 m² son la huella del edificio (casa de camineros), NO espacio de aparcamiento/maniobra: comprobar explanada o patio para vehículo pesado en ortofoto
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-02 · Aparcamiento sin nombre (Amezketa)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0044` · OSM way 201662629
- **Municipio:** Amezketa (20008), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-02 v0.2
- **Coordenadas:** 43.04989, -2.08911 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.04989&mlon=-2.08911#map=17/43.04989/-2.08911)
- **Acceso:** GI-2133 (tertiary); enganche a la red a 11 m (nodo 303290547)
- **Superficie:** 1,174 m²
- **Tiempo actual desde parque:** 12.1 min ligero (GIP-ORIA, 11.3 km) · 14.7 min camión (GIP-ORIA); parque más cercano en línea recta a 7.6 km
- **Motivo de selección:** orden 1 · Cluster de déficit 3 (246 edificios > 12 min: Amezketa 135, Abaltzisketa 86, Tolosa 18, Orendain 7). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 3.8 min, superficie); 15 opción(es) elegible(s)
- **Información (no usada para elegir):** 732 edificios del conjunto a ≤ 12 min desde aquí; 246 pasarían a ≤ 12 min si solo se añade esta candidata; 211 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-03 · Aparcamiento sin nombre (Berastegi)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0050` · OSM way 362824533
- **Municipio:** Berastegi (20022), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-03 v0.2
- **Coordenadas:** 43.12362, -1.97815 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.12362&mlon=-1.97815#map=17/43.12362/-1.97815)
- **Acceso:** Arandia kalea (residential); enganche a la red a 30 m (nodo 663200364)
- **Superficie:** 1,087 m²
- **Tiempo actual desde parque:** 12.2 min ligero (GIP-ORIA, 11.8 km) · 15.2 min camión (GIP-ORIA); parque más cercano en línea recta a 8.3 km
- **Motivo de selección:** orden 3 · Cluster de déficit 5 (104 edificios > 12 min: Berastegi 104). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 1.6 min, superficie); 3 opción(es) elegible(s)
- **Información (no usada para elegir):** 605 edificios del conjunto a ≤ 12 min desde aquí; 104 pasarían a ≤ 12 min si solo se añade esta candidata; 103 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-04 · Insalus agua (Lizartza)

- **Tipo:** industrial · nivel 4 (industrial) · pool `POOL-0342` · OSM way 1006779679
- **Municipio:** Lizartza (20054), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-04 v0.2
- **Coordenadas:** 43.09573, -2.03529 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.09573&mlon=-2.03529#map=17/43.09573/-2.03529)
- **Acceso:** Errepide Orokorrean (service); enganche a la red a 4 m (nodo 11769273663)
- **Superficie:** 4,549 m²
- **Aparcamiento público más cercano:** 559 m
- **Tiempo actual desde parque:** 8.5 min ligero (GIP-ORIA, 7.7 km) · 10.6 min camión (GIP-ORIA); parque más cercano en línea recta a 5.2 km
- **Motivo de selección:** orden 4 · Cluster de déficit 4 (30 edificios > 12 min: Orexa 24, Lizartza 6). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 5.9 min, superficie); 4 opción(es) elegible(s)
- **Información (no usada para elegir):** 1236 edificios del conjunto a ≤ 12 min desde aquí; 30 pasarían a ≤ 12 min si solo se añade esta candidata; 30 edificios en déficit a ≤ 2,5 km
- **⚠ Advertencia específica (revisión v0.3.1):** «Insalus» es una planta embotelladora PRIVADA: titularidad y permiso de uso del recinto imprescindibles
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-05 · Frontoia (Bidania-Goiatz)

- **Tipo:** fronton / sports_centre · nivel 3 (sports_centre/fronton with parking) · pool `POOL-0255` · OSM way 50437825
- **Municipio:** Bidania-Goiatz (20024), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** sitio nuevo en v0.3 (nuevo sitio (cluster); hereda el número de la candidata v0.2 más próxima que sale (CAND-05 v0.2 a 1.2 km))
- **Coordenadas:** 43.14039, -2.16045 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.14039&mlon=-2.16045#map=17/43.14039/-2.16045)
- **Acceso:** Agerre-Azpi kalea (residential); enganche a la red a 24 m (nodo 605248345)
- **Superficie:** 584 m²
- **Aparcamiento público más cercano:** 15 m
- **Tiempo actual desde parque:** 10.1 min ligero (GIP-ORIA, 10.2 km) · 12.4 min camión (GIP-ORIA); parque más cercano en línea recta a 6.6 km
- **Motivo de selección:** orden 5 · Cluster de déficit 0 (28 edificios > 12 min: Bidania-Goiatz 20, Albiztur 8). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 3.4 min, superficie); 4 opción(es) elegible(s)
- **Información (no usada para elegir):** 674 edificios del conjunto a ≤ 12 min desde aquí; 29 pasarían a ≤ 12 min si solo se añade esta candidata; 26 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-06 · Zona industrial sin nombre (Villabona)

- **Tipo:** industrial · nivel 4 (industrial) · pool `POOL-0304` · OSM way 32871872
- **Municipio:** Villabona (20075), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-06 v0.2
- **Coordenadas:** 43.20078, -2.03956 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20078&mlon=-2.03956#map=17/43.20078/-2.03956)
- **Acceso:** Ubegun industrialdea (service); enganche a la red a 0 m (nodo 11185664662)
- **Superficie:** 38,680 m²
- **Aparcamiento público más cercano:** 40 m
- **Tiempo actual desde parque:** 9.2 min ligero (GIP-ORIA, 12.4 km) · 10.6 min camión (GIP-ORIA); parque más cercano en línea recta a 8.7 km
- **Motivo de selección:** orden 6 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.44601 (Villabona, 12.7 min) estaba a 8.0 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (403 m, 9.9 min por carretera; orden: banda de 500 m, después nivel de tipo); 12 opción(es) elegible(s)
- **Información (no usada para elegir):** 1896 edificios del conjunto a ≤ 12 min desde aquí; 105 pasarían a ≤ 12 min si solo se añade esta candidata; 1 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-07 · Aparcamiento sin nombre (Orendain)

- **Tipo:** parking · nivel 5 (parking 400-1000 m2) · pool `POOL-0077` · OSM way 1370800724
- **Municipio:** Orendain (20905), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** sitio nuevo en v0.3 (nuevo sitio (spread); hereda el número de la candidata v0.2 más próxima que sale (CAND-07 v0.2 a 1.2 km))
- **Coordenadas:** 43.08247, -2.12424 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.08247&mlon=-2.12424#map=17/43.08247/-2.12424)
- **Acceso:** vía sin nombre (service); enganche a la red a 2 m (nodo 2379890348)
- **Superficie:** 586 m²
- **Tiempo actual desde parque:** 8.1 min ligero (GIP-GOIERRI, 8.5 km) · 9.6 min camión (GIP-GOIERRI); parque más cercano en línea recta a 6.0 km
- **Motivo de selección:** orden 9 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.736921 (Orendain, 13.0 min) estaba a 4.2 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (417 m, 10.8 min por carretera; orden: banda de 500 m, después nivel de tipo); 2 opción(es) elegible(s)
- **Información (no usada para elegir):** 1146 edificios del conjunto a ≤ 12 min desde aquí; 29 pasarían a ≤ 12 min si solo se añade esta candidata; 9 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-08 · Polideportivo sin nombre (Anoeta)

- **Tipo:** sports_centre · nivel 3 (sports_centre/fronton with parking) · pool `POOL-0272` · OSM node 3654166549
- **Municipio:** Anoeta (20010), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** sitio nuevo en v0.3 (nuevo sitio (spread); hereda el número de la candidata v0.2 más próxima que sale (CAND-08 v0.2 a 0.3 km))
- **Coordenadas:** 43.16145, -2.07088 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.16145&mlon=-2.07088#map=17/43.16145/-2.07088)
- **Acceso:** Herriko plaza (residential); enganche a la red a 50 m (nodo 4894233574)
- **Superficie:** desconocida (NULL)
- **Aparcamiento público más cercano:** 10 m
- **Tiempo actual desde parque:** 5.5 min ligero (GIP-ORIA, 6.6 km) · 6.4 min camión (GIP-ORIA); parque más cercano en línea recta a 3.7 km
- **Motivo de selección:** orden 7 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.50413 (Alkiza, 14.9 min) estaba a 5.0 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 2.5 km de él (1849 m, 10.0 min por carretera; orden: banda de 500 m, después nivel de tipo); 24 opción(es) elegible(s)
- **Información (no usada para elegir):** 2353 edificios del conjunto a ≤ 12 min desde aquí; 100 pasarían a ≤ 12 min si solo se añade esta candidata; 7 edificios en déficit a ≤ 2,5 km
- **⚠ Advertencia específica (revisión v0.3.1):** punto OSM sin superficie (área desconocida), enganche a la red a 50.5 m, y a solo 3.7 km en línea recta / 5.5 min de GIP-ORIA: aporta poco frente al parque existente
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-09 · Área de picnic sin nombre (Tolosa)

- **Tipo:** picnic_site · nivel 6 (trailhead/picnic) · pool `POOL-0411` · OSM way 45059143
- **Municipio:** Tolosa (20071), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-09 v0.2
- **Coordenadas:** 43.05008, -2.04090 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.05008&mlon=-2.04090#map=17/43.05008/-2.04090)
- **Acceso:** vía sin nombre (service); enganche a la red a 17 m (nodo 9008385816)
- **Superficie:** 518 m²
- **Aparcamiento público más cercano:** 57 m
- **Tiempo actual desde parque:** 17.8 min ligero (GIP-ORIA, 16.0 km) · 21.9 min camión (GIP-ORIA); parque más cercano en línea recta a 9.3 km
- **Motivo de selección:** orden 8 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.38439 (Tolosa, 17.7 min) estaba a 4.4 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (500 m, 1.3 min por carretera; orden: banda de 500 m, después nivel de tipo); 1 opción(es) elegible(s)
- **Información (no usada para elegir):** 141 edificios del conjunto a ≤ 12 min desde aquí; 74 pasarían a ≤ 12 min si solo se añade esta candidata; 35 edificios en déficit a ≤ 2,5 km
- **⚠ Advertencia específica (revisión v0.3.1):** área de picnic en el enclave sur de Tolosa (separado del casco urbano, zona de Bedaio): accesibilidad y titularidad a confirmar; pertenecer a Tolosa no implica cercanía al casco ni al parque de Oria
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-10 · Aparcamiento sin nombre (Zizurkil)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0040` · OSM way 509977692
- **Municipio:** Zizurkil (20028), por punto en polígono (límites oficiales geoEuskadi)
- **Respecto a v0.2:** mismo sitio que CAND-10 v0.2
- **Coordenadas:** 43.20788, -2.07728 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20788&mlon=-2.07728#map=17/43.20788/-2.07728)
- **Acceso:** Buztinbailara (service); enganche a la red a 22 m (nodo 3402476274)
- **Superficie:** 1,339 m²
- **Tiempo actual desde parque:** 11.9 min ligero (GIP-ORIA, 13.0 km) · 14.1 min camión (GIP-ORIA); parque más cercano en línea recta a 8.8 km
- **Motivo de selección:** orden 10 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.889478 (Zizurkil, 16.0 min) estaba a 4.1 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 2.5 km de él (2339 m, 6.0 min por carretera; orden: banda de 500 m, después nivel de tipo); 1 opción(es) elegible(s)
- **Información (no usada para elegir):** 1079 edificios del conjunto a ≤ 12 min desde aquí; 119 pasarían a ≤ 12 min si solo se añade esta candidata; 41 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## Candidatas v0.1 sustituidas y por qué

Las 10 candidatas v0.1 (CAND-01…10, restaurantes/cafeterías de un archivo de POI) se sustituyen **todas**. Los identificadores CAND-01…10 se reutilizan para las nuevas; las antiguas se guardan como `V01-CAND-xx` en `processed/links/travel_times_v0.3.1.parquet` y `v01_candidates_replaced.csv`.

| v0.1 | poi_name | etiqueta v0.1 | municipio (PIP) | min (red v0.3) | km a parque | v0.3 más próxima | km | motivo |
|---|---|---|---|---|---|---|---|---|
| CAND-01 | Pasus Jatetxea | Villabona | Zizurkil | 7.4 | 7.1 | CAND-06 | 1.8 | POI restaurant («Pasus Jatetxea»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); etiquetada «Villabona» pero cae en Zizurkil (punto en polígono, límites P2); zona ya bien servida (7.4 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-06 a 1.8 km |
| CAND-02 | Txindoki | Amezketa | Amezketa | 13.3 | 8.0 | CAND-02 | 0.8 | POI restaurant («Txindoki»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona en déficit que ahora estudia CAND-02 (a 0.8 km) |
| CAND-03 | Kako | Berastegi | Berastegi | 11.8 | 8.3 | CAND-03 | 0.1 | POI restaurant («Kako»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona en déficit que ahora estudia CAND-03 (a 0.1 km) |
| CAND-04 | Elane | Albiztur | Albiztur | 5.8 | 4.1 | CAND-05 | 2.7 | POI restaurant («Elane»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (5.8 min desde GIP-ORIA); sin aparcamiento ≥ 400 m² a ≤ 150 m; candidata v0.2 más próxima: CAND-05 a 2.7 km |
| CAND-05 | Abaetxe Jatetxea | Tolosa | Tolosa | 17.8 | 9.3 | CAND-09 | 0.0 | POI restaurant («Abaetxe Jatetxea»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); sin aparcamiento ≥ 400 m² a ≤ 150 m; sustituida por el sitio contiguo CAND-09 (19 m), que sí es un tipo de emplazamiento de la lista |
| CAND-06 | cafe iTunes | Asteasu | Asteasu | 13.2 | 8.0 | CAND-01 | 2.4 | POI restaurant («cafe iTunes»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); sin aparcamiento ≥ 400 m² a ≤ 150 m; zona en déficit que ahora estudia CAND-01 (a 2.4 km) |
| CAND-07 | Sausta | Tolosa | Tolosa | 3.6 | 1.6 | CAND-08 | 2.1 | POI restaurant («Sausta»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); a 1.6 km de GIP-ORIA (< 2 km): redundante con el parque; zona ya bien servida (3.6 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-08 a 2.1 km |
| CAND-08 | Errotatxo | Alegia | Alegia | 5.0 | 3.6 | CAND-07 | 2.9 | POI cafe («Errotatxo»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (5.0 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-07 a 2.9 km |
| CAND-09 | Iriarte | Berrobi | Berrobi | 6.0 | 4.8 | CAND-08 | 4.1 | POI restaurant («Iriarte»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (6.0 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-08 a 4.1 km |
| CAND-10 | Zartagi | Baliarrain | Baliarrain | 9.2 | 4.9 | CAND-07 | 1.5 | POI restaurant («Zartagi»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); más cerca de GIP-GOIERRI que de Oria; candidata v0.2 más próxima: CAND-07 a 1.5 km |

## Limitaciones

- Pool basado en OSM: aparcamientos y frontones cartografiados de forma desigual; un sitio bueno no cartografiado no puede salir.
- En las instalaciones forales (`dfg_facility`) la superficie es la huella del edificio OSM; el espacio de maniobra hay que verlo en ortofoto.
- La demanda depende de la regla de proximidad (100 m al bosque/matorral del Mapa Forestal) y del umbral de 12 min, ambos parámetros de demo.
- Los parques de Navarra no son orígenes (no hay capa oficial en el paquete); las carreteras de Navarra sí se usan para calcular rutas.
- La regla de tipo (nivel) es una preferencia del equipo, no un criterio oficial del servicio de bomberos.