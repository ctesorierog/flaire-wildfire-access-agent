# Fichas de candidatas · Tolosaldea (v0.2, 1 oct 2026)

Generado por `code/link_build.py` (re-ejecutable). Datos: `processed/candidates/candidates_10.{gpkg,csv,geojson}`, versión de datos **v0.2-provisional-veg**.

> **Ser candidata no significa estar autorizada ni validada.** Son lugares para estudiar cobertura. Cada ficha tiene 6 comprobaciones pendientes de campo. Los tiempos son **estimaciones de desplazamiento** (no tiempos de respuesta). La vegetación usada para definir el conjunto de análisis es **PROVISIONAL (OSM)**: al llegar el Mapa Forestal se re-ejecuta la selección sin recalcular tiempos (ya están calculados desde los 458 sitios del pool).

## Regla de selección (transparente, no usa el objetivo del optimizador)

1. **Elegibilidad** sobre los 458 sitios utilizables del pool (`candidate_pool`, P4): dentro de los 28 municipios (punto en polígono con los límites P2: 206), tipo en orden de preferencia [1 instalación foral (`dfg_facility`), 2 aparcamiento ≥ 1 000 m², 3 polideportivo/frontón con aparcamiento ≤ 150 m, 4 zona industrial, 5 aparcamiento 400–1 000 m², 6 área de picnic/recreativa], enganche a la red ≤ 60 m, la vía más cercana no es autopista/autovía, y ≥ 2 km en línea recta de cualquier parque existente. **156 sitios elegibles** (por nivel: {'1': 4, '2': 25, '3': 17, '4': 52, '5': 36, '6': 22}). Motivos de exclusión dentro de Tolosaldea: {'<2km_from_park': 35, 'snap>60m': 4, 'site_type_not_in_list;<2km_from_park': 3, 'site_type_not_in_list': 3, 'snap>60m;<2km_from_park': 2, 'on_motorway_trunk;<2km_from_park': 1, 'on_motorway_trunk': 1, 'site_type_not_in_list;snap>60m': 1}. Aparcamientos sin área conocida (nodos OSM), centros culturales y refugios no están en la lista. Detalle: `candidate_eligibility.csv`.
2. **Demanda**: edificios del conjunto de análisis (residencial ∧ ≤ 100 m de bosque/matorral OSM) con tiempo base (9 parques, vehículo ligero) > 12 min: **389** (35 sin ruta por enganche > 150 m; se reportan pero no orientan la selección porque ninguna candidata arregla su enganche) → **354** edificios. Agrupados con DBSCAN (eps 2 km, mín. 5 edificios): 8 clusters + 4 edificios aislados. Cluster **principal** = ≥ 15 edificios en déficit: 4.
3. **Un sitio por cluster principal** (de mayor a menor): el sitio elegible mejor clasificado dentro de la envolvente convexa del cluster + 1 km (si no hay, + 2,5 km), ordenando por nivel de tipo, después por mediana del tiempo desde el sitio a los edificios en déficit del cluster, después por superficie. Separación ≥ 3 km entre candidatas.
4. **Relleno hasta 10 por dispersión territorial max-min** (farthest-first): se toma el edificio en déficit más alejado en línea recta de todos los parques y candidatas ya elegidas, y se le asigna el sitio elegible más cercano (≤ 1 km, si no ≤ 2,5 km; bandas de 500 m y después nivel de tipo), respetando ≥ 3 km entre candidatas.
   **Comprobación por carretera** (pasos 3 y 4): el sitio solo cuenta si llega antes que el parque actual (paso 3: mediana del tiempo al cluster < mediana del tiempo base del cluster; paso 4: tiempo al edificio objetivo < su tiempo base). Evita sitios cercanos en línea recta pero en otro valle. Si ningún sitio cumple, el edificio objetivo se marca como no atendible y se pasa al siguiente más alejado.
5. Las columnas `info_*` (alcance y ganancia a 12 min) se calculan **después** de elegir, solo como información; la elección de combinaciones 0–6 es trabajo del optimizador.

### Clusters de déficit (vehículo ligero, > 12 min, con ruta)

| cluster | n_deficit | median_base_min | worst_base_min | municipalities | major | chosen_cand |
|---|---|---|---|---|---|---|
| 1 | 147 | 14.5 | 20.5 | Asteasu 104, Zizurkil 20, Alkiza 16, Larraul 5, Aduna 2 | True | CAND-01 |
| 4 | 139 | 14.6 | 18.5 | Abaltzisketa 63, Amezketa 57, Tolosa 12, Orendain 7 | True | CAND-02 |
| 7 | 21 | 14.6 | 17.0 | Berastegi 21 | True | CAND-03 |
| 6 | 16 | 13.1 | 15.6 | Orexa 16 | True | CAND-04 |
| 0 | 12 | 13.1 | 13.9 | Albiztur 7, Bidania-Goiatz 5 | False |  |
| 3 | 5 | 18.6 | 19.0 | Tolosa 5 | False |  |
| 2 | 5 | 13.4 | 13.7 | Bidania-Goiatz 5 | False |  |
| 5 | 5 | 13.2 | 16.6 | Lizartza 5 | False |  |
| -1 | 4 | 12.2 | 12.7 | Bidania-Goiatz 2, Albiztur 1, Villabona 1 | False |  |

(cluster −1 = edificios aislados según DBSCAN)

## Resumen de las 10 candidatas

| cand_id | name | site_type | municipality | lon | lat | snap_m | area_m2 | baseline_light_min | baseline_truck_min | selection_step | info_gain_alone_12_n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAND-01 | Casa Camineros | dfg_facility | Asteasu | -2.13381 | 43.20265 | 9.7 | 133.5 | 16.7 | 20.2 | cluster | 128 |
| CAND-02 | Aparcamiento sin nombre (Amezketa) | parking | Amezketa | -2.08911 | 43.04989 | 10.7 | 1,173.9 | 12.1 | 14.7 | cluster | 139 |
| CAND-03 | Aparcamiento sin nombre (Berastegi) | parking | Berastegi | -1.97815 | 43.12362 | 29.8 | 1,087.4 | 12.2 | 15.2 | cluster | 21 |
| CAND-04 | Insalus agua | industrial | Lizartza | -2.03529 | 43.09573 | 4.2 | 4,549.0 | 8.5 | 10.6 | cluster | 21 |
| CAND-05 | Aparcamiento sin nombre (Bidania-Goiatz) | parking | Bidania-Goiatz | -2.17388 | 43.14477 | 31.2 | 795.5 | 12.2 | 15.0 | spread | 19 |
| CAND-06 | Zona industrial sin nombre (Villabona) | industrial | Villabona | -2.03959 | 43.20124 | 0.0 | 38,680.5 | 9.5 | 10.9 | spread | 103 |
| CAND-07 | Frontón sin nombre (Ikaztegieta) | fronton | Ikaztegieta | -2.12625 | 43.09306 | 41.0 | 1,178.6 | 6.2 | 7.1 | spread | 71 |
| CAND-08 | Aparcamiento sin nombre (Anoeta) | parking | Anoeta | -2.07096 | 43.15911 | 1.2 | 2,054.1 | 6.0 | 7.1 | spread | 79 |
| CAND-09 | Área de picnic sin nombre (Tolosa) | picnic_site | Tolosa | -2.04090 | 43.05008 | 16.9 | 518.1 | 17.8 | 21.9 | spread | 22 |
| CAND-10 | Aparcamiento sin nombre (Zizurkil) | parking | Zizurkil | -2.07728 | 43.20788 | 22.3 | 1,338.9 | 11.9 | 14.1 | spread | 110 |

## CAND-01 · Casa Camineros (Asteasu)

- **Tipo:** dfg_facility / dfg_named · nivel 1 (diputacion_facility) · pool `POOL-0005` · OSM way 505635740
- **Municipio:** Asteasu (20014), por punto en polígono (límites P2)
- **Coordenadas:** 43.20265, -2.13381 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20265&mlon=-2.13381#map=17/43.20265/-2.13381)
- **Acceso:** GI-2631 (secondary); enganche a la red a 10 m (nodo 2315750405)
- **Superficie:** 134 m² (huella del edificio OSM; el espacio exterior no está cartografiado)
- **Aparcamiento público más cercano:** 104 m
- **Tiempo actual desde parque:** 16.7 min ligero (GIP-ORIA, 18.1 km) · 20.2 min camión (GIP-ORIA); parque más cercano en línea recta a 9.1 km
- **Motivo de selección:** orden 1 · Cluster de déficit 1 (147 edificios > 12 min: Asteasu 104, Zizurkil 20, Alkiza 16, Larraul 5, Aduna 2). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 7.7 min, superficie); 31 opción(es) elegible(s)
- **Información (no usada para elegir):** 636 edificios del conjunto a ≤ 12 min desde aquí; 128 pasarían a ≤ 12 min si solo se añade esta candidata; 77 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-02 · Aparcamiento sin nombre (Amezketa)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0044` · OSM way 201662629
- **Municipio:** Amezketa (20008), por punto en polígono (límites P2)
- **Coordenadas:** 43.04989, -2.08911 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.04989&mlon=-2.08911#map=17/43.04989/-2.08911)
- **Acceso:** GI-2133 (tertiary); enganche a la red a 11 m (nodo 303290547)
- **Superficie:** 1,174 m²
- **Tiempo actual desde parque:** 12.1 min ligero (GIP-ORIA, 11.3 km) · 14.7 min camión (GIP-ORIA); parque más cercano en línea recta a 7.6 km
- **Motivo de selección:** orden 2 · Cluster de déficit 4 (139 edificios > 12 min: Abaltzisketa 63, Amezketa 57, Tolosa 12, Orendain 7). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 4.8 min, superficie); 14 opción(es) elegible(s)
- **Información (no usada para elegir):** 376 edificios del conjunto a ≤ 12 min desde aquí; 139 pasarían a ≤ 12 min si solo se añade esta candidata; 111 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-03 · Aparcamiento sin nombre (Berastegi)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0050` · OSM way 362824533
- **Municipio:** Berastegi (20022), por punto en polígono (límites P2)
- **Coordenadas:** 43.12362, -1.97815 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.12362&mlon=-1.97815#map=17/43.12362/-1.97815)
- **Acceso:** Arandia kalea (residential); enganche a la red a 30 m (nodo 663200364)
- **Superficie:** 1,087 m²
- **Tiempo actual desde parque:** 12.2 min ligero (GIP-ORIA, 11.8 km) · 15.2 min camión (GIP-ORIA); parque más cercano en línea recta a 8.3 km
- **Motivo de selección:** orden 3 · Cluster de déficit 7 (21 edificios > 12 min: Berastegi 21). sitio elegible mejor clasificado dentro de la envolvente del cluster + 1 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 2.8 min, superficie); 3 opción(es) elegible(s)
- **Información (no usada para elegir):** 139 edificios del conjunto a ≤ 12 min desde aquí; 21 pasarían a ≤ 12 min si solo se añade esta candidata; 20 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-04 · Insalus agua (Lizartza)

- **Tipo:** industrial · nivel 4 (industrial) · pool `POOL-0342` · OSM way 1006779679
- **Municipio:** Lizartza (20054), por punto en polígono (límites P2)
- **Coordenadas:** 43.09573, -2.03529 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.09573&mlon=-2.03529#map=17/43.09573/-2.03529)
- **Acceso:** Errepide Orokorrean (service); enganche a la red a 4 m (nodo 11769273663)
- **Superficie:** 4,549 m²
- **Aparcamiento público más cercano:** 559 m
- **Tiempo actual desde parque:** 8.5 min ligero (GIP-ORIA, 7.7 km) · 10.6 min camión (GIP-ORIA); parque más cercano en línea recta a 5.2 km
- **Motivo de selección:** orden 4 · Cluster de déficit 6 (16 edificios > 12 min: Orexa 16). sitio elegible mejor clasificado dentro de la envolvente del cluster + 2.5 km (orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster = 5.6 min, superficie); 5 opción(es) elegible(s)
- **Información (no usada para elegir):** 389 edificios del conjunto a ≤ 12 min desde aquí; 21 pasarían a ≤ 12 min si solo se añade esta candidata; 21 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-05 · Aparcamiento sin nombre (Bidania-Goiatz)

- **Tipo:** parking · nivel 5 (parking 400-1000 m2) · pool `POOL-0060` · OSM way 1094755925
- **Municipio:** Bidania-Goiatz (20024), por punto en polígono (límites P2)
- **Coordenadas:** 43.14477, -2.17388 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.14477&mlon=-2.17388#map=17/43.14477/-2.17388)
- **Acceso:** Goiatz barreiatua (unclassified); enganche a la red a 31 m (nodo 2312751242)
- **Superficie:** 796 m²
- **Tiempo actual desde parque:** 12.2 min ligero (GIP-ORIA, 11.8 km) · 15.0 min camión (GIP-ORIA); parque más cercano en línea recta a 7.8 km
- **Motivo de selección:** orden 5 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.33614 (Bidania-Goiatz, 12.7 min) estaba a 8.0 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (845 m, 3.3 min por carretera; orden: banda de 500 m, después nivel de tipo); 1 opción(es) elegible(s)
- **Información (no usada para elegir):** 114 edificios del conjunto a ≤ 12 min desde aquí; 19 pasarían a ≤ 12 min si solo se añade esta candidata; 11 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-06 · Zona industrial sin nombre (Villabona)

- **Tipo:** industrial · nivel 4 (industrial) · pool `POOL-0304` · OSM way 32871872
- **Municipio:** Villabona (20075), por punto en polígono (límites P2)
- **Coordenadas:** 43.20124, -2.03959 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20124&mlon=-2.03959#map=17/43.20124/-2.03959)
- **Acceso:** Ubegun industrialdea (service); enganche a la red a 0 m (nodo 11185664640)
- **Superficie:** 38,680 m²
- **Aparcamiento público más cercano:** 69 m
- **Tiempo actual desde parque:** 9.5 min ligero (GIP-ORIA, 12.4 km) · 10.9 min camión (GIP-ORIA); parque más cercano en línea recta a 8.7 km
- **Motivo de selección:** orden 6 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.44601 (Villabona, 12.7 min) estaba a 8.0 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (437 m, 9.6 min por carretera; orden: banda de 500 m, después nivel de tipo); 9 opción(es) elegible(s)
- **Información (no usada para elegir):** 1049 edificios del conjunto a ≤ 12 min desde aquí; 103 pasarían a ≤ 12 min si solo se añade esta candidata; 1 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-07 · Frontón sin nombre (Ikaztegieta)

- **Tipo:** fronton / sports_centre · nivel 3 (sports_centre/fronton with parking) · pool `POOL-0249` · OSM way 498651038
- **Municipio:** Ikaztegieta (20044), por punto en polígono (límites P2)
- **Coordenadas:** 43.09306, -2.12625 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.09306&mlon=-2.12625#map=17/43.09306/-2.12625)
- **Acceso:** GI-2131 (tertiary); enganche a la red a 41 m (nodo 304579688)
- **Superficie:** 1,179 m²
- **Aparcamiento público más cercano:** 38 m
- **Tiempo actual desde parque:** 6.2 min ligero (GIP-ORIA, 7.3 km) · 7.1 min camión (GIP-ORIA); parque más cercano en línea recta a 5.4 km
- **Motivo de selección:** orden 7 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.44682 (Tolosa, 18.5 min) estaba a 4.7 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 2.5 km de él (2341 m, 15.3 min por carretera; orden: banda de 500 m, después nivel de tipo); 2 opción(es) elegible(s)
- **Información (no usada para elegir):** 765 edificios del conjunto a ≤ 12 min desde aquí; 71 pasarían a ≤ 12 min si solo se añade esta candidata; 6 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-08 · Aparcamiento sin nombre (Anoeta)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0024` · OSM way 1417986470
- **Municipio:** Anoeta (20010), por punto en polígono (límites P2)
- **Coordenadas:** 43.15911, -2.07096 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.15911&mlon=-2.07096#map=17/43.15911/-2.07096)
- **Acceso:** vía sin nombre (residential); enganche a la red a 1 m (nodo 4895866973)
- **Superficie:** 2,054 m²
- **Tiempo actual desde parque:** 6.0 min ligero (GIP-ORIA, 6.9 km) · 7.1 min camión (GIP-ORIA); parque más cercano en línea recta a 3.5 km
- **Motivo de selección:** orden 8 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.50397 (Alkiza, 13.2 min) estaba a 4.6 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 2.5 km de él (1669 m, 8.8 min por carretera; orden: banda de 500 m, después nivel de tipo); 23 opción(es) elegible(s)
- **Información (no usada para elegir):** 1255 edificios del conjunto a ≤ 12 min desde aquí; 79 pasarían a ≤ 12 min si solo se añade esta candidata; 1 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-09 · Área de picnic sin nombre (Tolosa)

- **Tipo:** picnic_site · nivel 6 (trailhead/picnic) · pool `POOL-0411` · OSM way 45059143
- **Municipio:** Tolosa (20071), por punto en polígono (límites P2)
- **Coordenadas:** 43.05008, -2.04090 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.05008&mlon=-2.04090#map=17/43.05008/-2.04090)
- **Acceso:** vía sin nombre (service); enganche a la red a 17 m (nodo 9008385816)
- **Superficie:** 518 m²
- **Aparcamiento público más cercano:** 57 m
- **Tiempo actual desde parque:** 17.8 min ligero (GIP-ORIA, 16.0 km) · 21.9 min camión (GIP-ORIA); parque más cercano en línea recta a 9.3 km
- **Motivo de selección:** orden 9 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.38439 (Tolosa, 17.7 min) estaba a 4.4 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 1 km de él (500 m, 1.3 min por carretera; orden: banda de 500 m, después nivel de tipo); 1 opción(es) elegible(s)
- **Información (no usada para elegir):** 57 edificios del conjunto a ≤ 12 min desde aquí; 22 pasarían a ≤ 12 min si solo se añade esta candidata; 29 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## CAND-10 · Aparcamiento sin nombre (Zizurkil)

- **Tipo:** parking · nivel 2 (parking >=1000 m2) · pool `POOL-0040` · OSM way 509977692
- **Municipio:** Zizurkil (20028), por punto en polígono (límites P2)
- **Coordenadas:** 43.20788, -2.07728 (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat=43.20788&mlon=-2.07728#map=17/43.20788/-2.07728)
- **Acceso:** Buztinbailara (service); enganche a la red a 22 m (nodo 3402476274)
- **Superficie:** 1,339 m²
- **Tiempo actual desde parque:** 11.9 min ligero (GIP-ORIA, 13.0 km) · 14.1 min camión (GIP-ORIA); parque más cercano en línea recta a 8.8 km
- **Motivo de selección:** orden 10 · dispersión farthest-first: el edificio en déficit ES.GFA.BU.889478 (Zizurkil, 16.0 min) estaba a 4.1 km de todo parque/candidata elegida; sitio elegible más cercano a ≤ 2.5 km de él (2339 m, 6.0 min por carretera; orden: banda de 500 m, después nivel de tipo); 1 opción(es) elegible(s)
- **Información (no usada para elegir):** 786 edificios del conjunto a ≤ 12 min desde aquí; 110 pasarían a ≤ 12 min si solo se añade esta candidata; 57 edificios en déficit a ≤ 2,5 km
- **Pendiente de comprobar:** espacio para vehículo pesado y maniobra (giro, estacionamiento); titularidad y permiso de uso; acceso de camión: anchura, pendiente, gálibo, firme; agua (hidrante / depósito) cercana; restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano); ubicación exacta en ortofoto (geoEuskadi)

## Candidatas v0.1 sustituidas y por qué

Las 10 candidatas v0.1 (CAND-01…10, restaurantes/cafeterías de un archivo de POI) se sustituyen **todas**. Los identificadores CAND-01…10 se reutilizan para las nuevas; las antiguas se guardan como `V01-CAND-xx` en `processed/links/travel_times_v0.2.parquet` y `v01_candidates_replaced.csv`.

| v0.1 | poi_name | etiqueta v0.1 | municipio (PIP) | min v0.2 | km a parque | v0.2 más próxima | km | motivo |
|---|---|---|---|---|---|---|---|---|
| CAND-01 | Pasus Jatetxea | Villabona | Zizurkil | 7.4 | 7.1 | CAND-06 | 1.8 | POI restaurant («Pasus Jatetxea»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); etiquetada «Villabona» pero cae en Zizurkil (punto en polígono, límites P2); zona ya bien servida (7.4 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-06 a 1.8 km |
| CAND-02 | Txindoki | Amezketa | Amezketa | 13.3 | 8.0 | CAND-02 | 0.8 | POI restaurant («Txindoki»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona en déficit que ahora estudia CAND-02 (a 0.8 km) |
| CAND-03 | Kako | Berastegi | Berastegi | 11.8 | 8.3 | CAND-03 | 0.1 | POI restaurant («Kako»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona en déficit que ahora estudia CAND-03 (a 0.1 km) |
| CAND-04 | Elane | Albiztur | Albiztur | 5.8 | 4.1 | CAND-05 | 3.9 | POI restaurant («Elane»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (5.8 min desde GIP-ORIA); sin aparcamiento ≥ 400 m² a ≤ 150 m; candidata v0.2 más próxima: CAND-05 a 3.9 km |
| CAND-05 | Abaetxe Jatetxea | Tolosa | Tolosa | 17.8 | 9.3 | CAND-09 | 0.0 | POI restaurant («Abaetxe Jatetxea»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); sin aparcamiento ≥ 400 m² a ≤ 150 m; sustituida por el sitio contiguo CAND-09 (19 m), que sí es un tipo de emplazamiento de la lista |
| CAND-06 | cafe iTunes | Asteasu | Asteasu | 13.2 | 8.0 | CAND-01 | 2.4 | POI restaurant («cafe iTunes»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); sin aparcamiento ≥ 400 m² a ≤ 150 m; zona en déficit que ahora estudia CAND-01 (a 2.4 km) |
| CAND-07 | Sausta | Tolosa | Tolosa | 3.6 | 1.6 | CAND-08 | 1.9 | POI restaurant («Sausta»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); a 1.6 km de GIP-ORIA (< 2 km): redundante con el parque; zona ya bien servida (3.6 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-08 a 1.9 km |
| CAND-08 | Errotatxo | Alegia | Alegia | 5.0 | 3.6 | CAND-07 | 2.5 | POI cafe («Errotatxo»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (5.0 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-07 a 2.5 km |
| CAND-09 | Iriarte | Berrobi | Berrobi | 6.0 | 4.8 | CAND-08 | 4.0 | POI restaurant («Iriarte»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); zona ya bien servida (6.0 min desde GIP-ORIA); candidata v0.2 más próxima: CAND-08 a 4.0 km |
| CAND-10 | Zartagi | Baliarrain | Baliarrain | 9.2 | 4.9 | CAND-07 | 2.7 | POI restaurant («Zartagi»): no es un tipo de emplazamiento de retén (problema 4 de v0.1); más cerca de GIP-GOIERRI que de Oria; candidata v0.2 más próxima: CAND-07 a 2.7 km |

## Limitaciones

- Pool basado en OSM: aparcamientos y frontones cartografiados de forma desigual; un sitio bueno no cartografiado no puede salir.
- La superficie de CAND-01 (instalación foral) es la huella del edificio; el espacio de maniobra hay que verlo en ortofoto.
- Demanda calculada con vegetación OSM provisional; con el Mapa Forestal cambian el conjunto de análisis, los clusters y quizá algunas candidatas.
- La regla de tipo (nivel) es una preferencia del equipo, no un criterio oficial del servicio de bomberos.