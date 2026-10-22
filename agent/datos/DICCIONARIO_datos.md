# Diccionario de datos del agente flAIre (3 de octubre de 2026)

Incluye la parte de Persona 1 (prioridad, meteorología, municipios, referencias) y la de Persona 2 (tiempos, parques, candidatas, escenarios).

**Convenciones:** UTF-8 · coma como separador · punto decimal · metros y minutos · **vacío = desconocido (nunca 0)** · coordenadas WGS84 · IDs como texto.

## edificios_prioridad.csv · una fila por vivienda del conjunto de análisis (3.331)
| Columna | Significado |
|---|---|
| `building_id` | ID INSPIRE de B5M (`ES.GFA.BU.n`). Clave para unir con `tiempos_*.csv`. |
| `muni_ine`, `municipio` | Código INE y nombre del municipio. |
| `lon`, `lat` | Punto representativo del edificio (WGS84). |
| `viviendas` | Viviendas según B5M (vacío si no se sabe). |
| `uso_original` | Uso CURRENTUSE de B5M. |
| `dist_veg_m` | Distancia (m) del contorno del edificio a la vegetación más cercana: bosque o matorral, sin prados. 0 = dentro. |
| `banda_distancia` | dentro · 0–25 · 25–50 · 50–100. |
| `vegetacion_cercana` | Tipo de vegetación del polígono más cercano. |
| `tipo_veg_nivel` | 1, 2 o 3 (ver `REGLAS_prioridad.md`). |
| `t_base_ligero_min`, `parque_base_ligero` | Tiempo estimado (min) en vehículo ligero desde el parque más cercano, y qué parque es. Vacío = sin ruta. |
| `t_segundo_parque_ligero_min` | Tiempo desde el segundo parque más cercano: lo que pasa si el primero está ocupado. |
| `t_base_camion_min`, `parque_base_camion` | Lo mismo en camión. |
| `banda_acceso` | ≤8 · 8–12 · 12–15 · >15 · sin ruta. |
| `sin_ruta` | «sí» si el edificio está a más de 150 m de una vía de la red. Ningún retén lo mejora. |
| `zona_meteo` | Estación de referencia: C026 Berastegi, C029 Zizurkil o C058 Bidania. Solo informativa. |
| `puntos_distancia`, `puntos_vegetacion`, `puntos_acceso`, `puntos_meteo`, `puntos_total` | Puntos de cada componente y total (1–8). |
| `prioridad`, `peso_prioridad` | Clase (Alta, Media o Baja) con los 4 componentes y su peso (media 1). **Para el ranking y los mapas.** |
| `prioridad_sin_acceso`, `peso_optimizador` | Clase y peso sin el acceso. **Para el optimizador** (así no se cuenta dos veces). |
| `motivo_prioridad` | Frase que explica la nota, por ejemplo «a 15 m de matorral (nivel 3) · 19,0 min desde GIP-ORIA · puntos 3+2+3+0 = 8». |
| `fs_puntuacion_0_100`, `fs_clase` | FireScope (INSAIT): puntuación de 0 a 100 y clase (Seguro, Bajo, Moderado o Alto). **Solo referencia.** |
| `dist_incendio_previo_aprox_m`, `anio_incendio_previo_cercano` | Distancia aproximada al incendio cartografiado más cercano de 2018–2026 (capa de FireScope) y su año. **Solo referencia.** |
| `peso_meteo_sensibilidad`, `peso_firescope_sensibilidad` | Pesos alternativos antiguos (meteorología de julio–agosto y FireScope, normalizados a media 1). **Solo para el análisis de sensibilidad del optimizador**: no entran en la prioridad. |

## municipios.csv · uno por municipio (28)
`muni_ine`, `municipio`, `area_km2`, `zona_meteo`, `edificios_total`, `residenciales`, `edificios_analisis`, `viviendas_analisis`,
`alta`, `media`, `baja`, `viviendas_alta`, `sin_ruta`, `t_base_mediana_min`, `t_base_max_min`, `fs_mediana` y `ha_incendios_previos_2018_2026_aprox`.
`municipios.geojson` contiene los límites simplificados, con `muni_ine` y `municipio`.

## Meteorología
| Archivo | Una fila = | Columnas |
|---|---|---|
| `meteo_mensual.csv` | estación × mes (2018–2023) | `codigo`, `zona`, `mes`, `dias_validos`, `dias_calor_seco`, `dias_viento_sur`, `dias_riesgo`, y las medias por mes: `media_calor_seco_por_mes`, `media_viento_sur_por_mes` y `media_dias_riesgo_por_mes` |
| `meteo_anual.csv` | zona × año | `codigo`, `zona`, `anio`, `dias_validos`, `dias_riesgo`, `dias_calor_seco`, `dias_viento_sur`, `anio_completo` (≥ 80 % de días válidos) y `dias_riesgo_por_anio` |
| `meteo_dias_riesgo.csv` | estación × día de riesgo | `codigo`, `zona`, `fecha` (UTC), `tmax_c`, `hr_min_pct`, `registros_viento_sur_seco_10min`, `racha_max_sur_ms`, `lluvia_dia_mm` y `tipo` |
| `meteo_test_zonas.csv` | par de zonas | la diferencia en días al año, su IC del 95 %, el p de la prueba de permutación, los años a favor de cada zona y si es `distinguible` (sí/no) |
| `meteo_estaciones.csv` | estación | `codigo`, `nombre`, `tipo`, `lon`, `lat`, `municipio`, `altitud_proxy_m`, `mide_viento` y `usada_en_zonas` |

## incendios_previos.csv · un trozo de polígono por fila (98), Tolosaldea + unos 3 km
`anio`, `lon` y `lat` (centroide), `superficie_m2`, `municipio_tolosaldea`, `municipio_gipuzkoa`, `zona` (Tolosaldea / resto de Gipuzkoa / Navarra),
`superficie_ha_aprox`, `dist_vivienda_conjunto_aprox_m`, `dist_vivienda_alta_aprox_m`, `alta_mas_cercana`, `muni_alta_mas_cercana` y `fuente`.

## Otros
- `fuentes.csv`: las fuentes de todos los datos, con URL, licencia, fecha y `responsable` (Persona 1 o Persona 2).
- `metodologia.csv`: los parámetros y reglas en formato clave / valor / explicación.
- `cifras_clave_persona1.json`: las cifras ya calculadas que el agente puede citar.
- `REGLAS_prioridad.md`: las reglas, las decisiones del equipo y cómo debe hablar el agente.

## Datos de Persona 2 (tiempos y optimizador, v0.3.1, sin cambios)
| Archivo | Una fila = | Columnas |
|---|---|---|
| `tiempos_ligero.csv`, `tiempos_camion.csv` | vivienda del conjunto (3.331) | `building_id` más una columna por origen (9 parques GIP-… y DON-GARBERA, y CAND-01 a CAND-10), en minutos estimados. Vacío = sin ruta. |
| `parques.csv` | parque de bomberos (10) | `origen_id`, `nombre`, `municipio`, `lon`, `lat`, `en_base` (1 = se usa; OTH-HONDARRIBIA = 0), `fuente`, `snap_m` y `nota` |
| `candidatos.csv` | sitio de estudio (10) | `origen_id` (CAND-xx), `nombre`, `tipo_sitio`, `municipio`, `lon`, `lat`, `osm_id`, `area_m2`, `via_acceso`, `snap_m`, `t_desde_parque_ligero`, `parque_mas_cercano`, `motivo` y `comprobaciones_pendientes`. Son sitios de estudio, **no autorizados**. |
| `escenarios.csv` | mejor selección para cada combinación de estrategia (A/B), k (0–6), umbral (10/12/15), perfil (ligero/camión) y pesos (uniforme/meteo/firescope) | `seleccion`, `edificios_cubiertos`, `pct_cubiertos`, `cobertura_ponderada`, `pct_ponderada`, `peor_tiempo`, `sin_ruta`, `mejora_vs_k0`, `empates` y `p95_tiempo`. **Todavía no incluye la ponderación «prioridad»** (`peso_optimizador`): Persona 2 la puede añadir. |

**Cómo se unen:** por `building_id`, entre `edificios_prioridad.csv` y `tiempos_*.csv`. Las columnas de `tiempos_*.csv` son los `origen_id` de `parques.csv` (los que tienen `en_base = 1`) y de `candidatos.csv`.
