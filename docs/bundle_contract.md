# flAIre agent bundle contract v0.3 (shared by Linker and Manager)

Folder: /home/claude/flaire/agent/ (this whole folder is uploaded to the platform as one agent folder). Data in agent/datos/. Every file ≤ 3.5 MB (platform limit 4 MB). UTF-8, comma CSV, '.' decimals, IDs as text, missing = empty (never 0 for unknown). Times in minutes (float, 2 decimals). CRS for lon/lat: WGS84.

| File (agent/datos/) | One row = | Columns |
|---|---|---|
| edificios.csv | one ANALYSIS-SET building (residential ∧ ≤100 m forest/scrub, official Mapa Forestal 2024) | building_id, muni_ine, municipio, lon, lat, viviendas, uso_original, residencial_regla, dist_veg_m, veg_clase_cercana, zona_meteo (station code), peso_meteo (normalized, mean 1), freq_adversa (raw), estado_ruta ('calculado' or 'sin_ruta: snap>150m'), snap_m, parque_base_ligero, t_base_ligero, parque_base_camion, t_base_camion |
| tiempos_ligero.csv / tiempos_camion.csv | one analysis building | building_id + one column per origin id (9 parks `GIP-…` with include_in_baseline=1, then CAND-01..CAND-10); value = minutes or empty if unroutable |
| parques.csv | fire station | origen_id, nombre, municipio, lon, lat, en_base (1/0), fuente, snap_m, nota |
| candidatos.csv | study candidate | origen_id (CAND-xx), nombre, tipo_sitio, municipio, lon, lat, osm_id, area_m2, via_acceso, snap_m, t_desde_parque_ligero, parque_mas_cercano, motivo, comprobaciones_pendientes |
| municipios.csv | municipality | muni_ine, municipio, area_km2, zona_meteo, edificios_total, residenciales, edificios_analisis, viviendas_analisis |
| municipios.geojson | municipality (simplified ≤ 1 MB) | muni_ine, municipio |
| meteo_estaciones.csv | station | codigo, nombre, tipo, lon, lat, municipio, altitud_proxy_m, mide_viento, usada_en_zonas |
| meteo_perfil.csv | station × season definition | codigo, temporada ('jul-ago'), anios, dias_validos, dias_adversos, frecuencia, media_anual, sd_anual, peso_normalizado, regla ('ADV-v1') |
| meteo_anual.csv | station × year (jul-ago) | codigo, anio, dias_validos, dias_adversos, frecuencia |
| meteo_mensual.csv | station × month (all years) | codigo, mes, dias_validos, dias_adversos, frecuencia |
| meteo_dias_adversos.csv | adverse station-day | codigo, fecha, tmax, hrmin, lluvia_3d_previos_mm |
| escenarios.csv | precomputed best per (strategy, k, threshold, profile, weights) | estrategia, k, umbral_min, perfil, pesos ('meteo' / 'uniforme'), seleccion ('CAND-02;CAND-05'), edificios_cubiertos, pct_cubiertos, cobertura_ponderada, pct_ponderada, peor_tiempo, sin_ruta, mejora_vs_k0, empates, **p95_tiempo** (added v0.3.1, last column) |
| fuentes.csv | source | source_id, conjunto, organismo, url, licencia, fecha_descarga, edicion_periodo, archivo, sha256, estado |
| metodologia.csv | parameter / rule | clave, valor, explicacion |
| auditoria.json | — | row accounting: buildings in B5M Gipuzkoa → Tolosaldea → dedup → residential → analysis set; unroutable; snaps > 150 m; QA view results; hand checks |

Parks used as origins = the 9 with include_in_baseline=1 (Hondarribia OTH excluded). Unroutable buildings stay in all files with empty times.

**Added in v0.3.1 (linker, 2 Oct 2026):** `escenarios.csv` gains a LAST column `p95_tiempo` = 95th percentile (linear interpolation) of the best travel time (parks + selection, minutes, 2 decimals) over ROUTABLE buildings of that scenario and k. Reported metric only: the A/B objectives are unchanged. Existing column order is unchanged. `candidatos.csv.comprobaciones_pendientes` now starts with site-specific caveats ('ESPECÍFICO: … | GENÉRICAS: …') where applicable. Bundle completeness marker: `agent/datos/.READY_v0.3.1`.

**Added in v0.3.1b (2 Oct, FireScope):** `edificios.csv` gains trailing columns `fs_indice`, `peso_firescope`; `escenarios.csv` has rows with `pesos='firescope'` (A and B, 10/12/15 min, ligero/camión). Source `SRC-INSAIT-FIRESCOPE-2026`.
