# flAIre · Data pipeline and 72 h plan (Tolosaldea pilot)

Written Thu 1 Oct 2026, 22:00 CEST. Hard deadline **Sun 4 Oct 23:59**; internal deadline **Sun 4 Oct 20:00**.
Everything goes into one database, `flaire.gpkg` (`schema.sql`). The agent reads it only through the tools in `tools_spec.md`.

## 1. Roles and hand-offs

| Stage | Who | Input | Output | Done when |
|---|---|---|---|---|
| **Collector** | Each Persona, on their own laptop (the cloud sandbox cannot reach euskadi.eus / gipuzkoa.eus / geofabrik) | Official portal | `raw/<dataset>/<file>`, never edited + one row in `sources` (exact URL incl. query, org, licence, download date, edition/period, sha256) | `sha256sum` recorded, file opens |
| **Cleaner** (agent or person) | Same Persona | raw file | `processed/<table>.gpkg` layer that matches the schema columns, EPSG:25830, original codes kept | Loads into `flaire.gpkg` with **no constraint errors** + `quality_reports` rows written, no `fail` |
| **Linker** (agent, run by the manager/P4) | processed tables | joins inside `flaire.gpkg`: building→municipality, building→vegetation distance, building→zone, building→network node, travel_times, scenarios | all `qa_*` views return 0 rows |

Rules for every hand-off: do not overwrite raw files. Keep original IDs and codes. Missing stays NULL. One file per dataset per edition. Use WGS84 only for GeoJSON exports and EPSG:25830 for anything metric. A Persona who changes a processed table posts "table X reloaded, N rows, version vX" in the team chat.

Loading pattern (Cleaner):
```python
gdf.to_crs(25830).to_file("flaire.gpkg", layer="buildings", driver="GPKG", mode="a", engine="pyogrio")
# attribute tables: pandas.to_sql(..., if_exists="append") with PRAGMA foreign_keys=ON
```
CHECK constraints reject bad rows, and that is intended. Fix the data; do not touch the constraint without the manager.

## 2. Datasets: source → raw → table → checks

**URLs marked (verify) could not be confirmed from the sandbox.** Record the URL you actually used in `sources`.

| # | Dataset / owner | Expected official source | Raw file | Table(s) | Validation checks |
|---|---|---|---|---|---|
| D1 | Municipal limits · **P2** | geoEuskadi (Gobierno Vasco), download section, "Límites administrativos – municipios CAPV" (SHP, EPSG:25830) (verify) | `raw/limits/municipios_capv_<edition>.zip` | `municipalities` (all Gipuzkoa, `in_pilot` = 1 for the 28), `boundary` (union) | 28 INE codes of the list matched exactly. Every geometry valid (`ST_IsValid`/`make_valid` count = 0 changes). Sum of the 28 areas = union area (±0.1 %, no gaps or overlaps). Area per municipality vs Udalmap/Eustat (±2 %). CRS 25830 |
| D2 | Buildings · **P2** | B5M (Diputación Foral de Gipuzkoa) INSPIRE Buildings WFS. Find the endpoint on b5m.gipuzkoa.eus/web5000/es/api-rest/conjuntos-datos. GetFeature `typeName=bu-core2d:Building` (feature type **Building only, not BuildingPart**), `srsName=EPSG:25830`, BBOX = boundary + 500 m, paged with `count`/`startIndex` (verify) | `raw/buildings/b5m_bu_tolosaldea_<yyyymmdd>.gml` | `buildings` (`building_id` = INSPIRE `localId`, `source_use` = `currentUse`, `dwellings` = `numberOfDwellings` or NULL, rep point = `representative_point()`, municipality by point-in-polygon) | Row count per municipality reported. Duplicates: `localId` unique and `qa_duplicate_building_geom` = 0. Invalid geometries counted and fixed. Nulls in use/dwellings per municipality (warn, not fail). Every point falls in exactly 1 municipality. Paging complete (last page < count). Residential rule written to `residential_rule` |
| D3 | Vegetation · **P3** | Mapa Forestal de la CAPV, latest edition (Gobierno Vasco, geoEuskadi / opendata.euskadi.eus) (verify) | `raw/vegetation/mapa_forestal_<year>.zip` | `vegetation_classes` (original code + name → `class_group`, `is_fuel`), `vegetation` (clip = boundary + 1 km) | Edition year in `sources.edition`. The dictionary covers 100 % of the codes in the layer. Clip margin ≥ `veg_proximity_m`. Validity. Area by group reported. Then `buildings.veg_distance_m`/`near_vegetation` filled (Linker), with NULL count = 0 for the pilot |
| D4 | DEM 5 m · **P3** | geoEuskadi MDT 5 m from LiDAR (Gobierno Vasco). Record the flight year (verify) | `raw/dem/mdt05_<sheet>.tif` | GeoTIFF `processed/dem_tolosaldea_5m.tif` (outside the gpkg). Used for `zone_assignment.elev_diff_m`, station elevation and candidate slope | CRS 25830, 5 m pixel, nodata < 0.1 % inside boundary, extent ⊇ boundary + 1 km |
| D5 | Weather · **P1** | Euskalmet: station catalogue + historical readings 2018–2023 (Open Data Euskadi yearly "lecturas" files, or the Euskalmet Open Data API with a key) (verify). Stations start with C026 Berastegi, C029 Zizurkil, C058 Bidania | `raw/weather/catalogue_<date>.csv`, `raw/weather/<year>/<station>_<year>.csv` | `weather_stations`, `weather_obs` (UTC, units fixed by CHECK), `weather_quality`, `profile_methods`, `weather_zones`, `zone_assignment`, `weather_profile`, `weather_profile_year`, `weather_adverse_days` | Time zone of the source confirmed and converted to UTC (`…Z`). Native frequency. Sensor heights. No duplicate (station, ts, variable). Ranges (RH 0–100, wind ≥ 0). Completeness table for each station × year × month × variable. Valid-day rule applied. Jul–Aug valid days ≥ 80 % per station-year, or the year is flagged. Profile period identical for all zones |
| D6 | Roads · **P4** | Geofabrik `https://download.geofabrik.de/europe/spain/pais-vasco-latest-free.shp.zip` **and** `…/spain/navarra-latest-free.shp.zip` (ODbL). Record the OSM snapshot date shown on the Geofabrik page. Filter `gis_osm_roads_free_1` with `fclass IN (motorway, motorway_link, trunk, trunk_link, primary, primary_link, secondary, secondary_link, tertiary, tertiary_link, unclassified, residential, living_street, service)` | `raw/roads/pais-vasco-<date>-free.shp.zip`, `raw/roads/navarra-<date>-free.shp.zip` | `road_nodes`, `road_edges` (`speed_used_kmh`, `speed_source`, `region`) | `*_link` count > 0 and **0 synthetic connectors**. Largest connected component ≥ 99 % of nodes in the AOI. Share of `speed_source` reported. Edges in NAV > 0. Manual check vs v0.1: Oria→Berastegi ≈ 11.5 min, →Amezketa ≈ 16.1, →Villabona ≈ 5.5, →Lizartza ≈ 7.4 (±15 %, explain any difference) |
| D7 | Fire stations · **P4** | B5M / Diputación Foral de Gipuzkoa fire-service station list with official addresses (verify the dataset name on B5M). Position checked on the geoEuskadi orthophoto | `raw/fire_stations/parques_<date>.csv` | `fire_stations`, `origins` | 9 rows (8 foral + Garbera), unique ids. Oria, Goierri and Garbera set to `verified_ortho`. Snap ≤ 200 m. Navarra stations get `routable` = 1 only once D6 Navarra is loaded |
| D8 | Candidates · **P4** | Derived (team): 10 sites from v0.1, `source_id` = `SRC-FLAIRE-CAND` pointing to the OSM POI file and selection method | `raw/candidates/candidates_tolosaldea_10_v0.1.csv` | `candidates`, `candidate_checks` (6 × 10 = 60 rows, `pending`), `origins` | 10 rows. Snap ≤ 200 m. Separation ≥ 3 km. Recompute `current_time_min_est` with the new network. **CAND-05 is labelled "Tolosa" but its coordinates (43.050, −2.041) are ~9 km south of Tolosa town: check the municipality by point-in-polygon (it may fall outside the pilot)** |
| L1 | Travel times · **P4 (Linker)** | Derived: Dijkstra on D6 from each origin (9 stations + 10 candidates) to every scope building node | `processed/travel_times_<version>.parquet` | `travel_times` | `qa_missing_travel_pairs` = 0. Unroutable rows present with a reason. No 0/999 placeholders. Times from GIP-ORIA match the D6 manual check |
| L2 | Scenarios · **Manager + P4** | `optimizer.py run --write` | — | `scenarios`, `results`, `result_selection`, `result_building`, `combo_metrics` | 848 combos per scenario. `qa_result_building_count` = 0, `qa_monotone_results` = 0. Recomputed k = 0 (`compute_coverage`) = stored |

Scope rule (to confirm): **scope building = residential AND near_vegetation AND in a pilot municipality**. Every metric uses `v_scope_buildings`. The v0.1 proxy points (6,714) are retired once D2 and D3 are linked.

## 3. Order of work and checkpoints (CEST)

| When | Owner | Task | Checkpoint |
|---|---|---|---|
| Thu 1 Oct 22:00–23:30 | All | Confirm the decisions in §5. Manager publishes an empty `flaire.gpkg` from `schema.sql` | **CP0 23:30** schema frozen |
| Fri 2 Oct 09:00–11:00 | P2 | D1 limits → `municipalities` and `boundary` (**blocks everyone**) | **CP1 11:00** boundary shared (gpkg + WGS84 GeoJSON) |
| Fri 09:00–13:00 | P4 | D6 download PV + Navarra, re-export with links. D7 ortho check | |
| Fri 09:00–13:00 | P1 | D5 catalogue + 2018–2023 readings for C026/C029/C058 (+ neighbours) | |
| Fri 09:00–13:00 | P3 | D3 Mapa Forestal + D4 DEM download. Class dictionary draft | |
| Fri 11:00–17:00 | P2 | D2 buildings WFS → clean → `buildings` (without links yet) | |
| Fri 13:00–19:00 | P4 / P1 / P3 | Graph into gpkg, D8 recomputed / obs to UTC + `weather_quality` / `vegetation` + groups | |
| Fri 20:00 | All | All `sources` rows + raw sha256. Base tables loaded, `quality_reports` written | **CP2 20:00** data v0.5 |
| Sat 3 Oct 09:00–12:00 | P3+P2 / P1 / P4 | Vegetation distance on buildings / adverse-day method, profiles, `zone_assignment` / snapping buildings to nodes | |
| Sat 12:00–15:00 | P4 | L1 travel times (19 origins × scope buildings) | **CP3 15:00** data v0.9, all `qa_*` = 0 |
| Sat 15:00–17:00 | Manager + P4 | L2 scenarios: A/B × 12/15 min × weighted/none (8 runs, ~2 s each) | **CP4 17:00** freeze **data v1.0** |
| Sat 15:00–22:00 | P4 + P2 (code), P1 (`get_zone_profile`), P3 (`list_limitations`, report template) | Tools 1–10 in the platform. Upload data to "Datos" | **CP5 22:00** main question answered end-to-end in "Pruebas" |
| Sun 4 Oct 09:00–13:00 | All | Jury tests: main question, one variation, one limit, one figure checked against the data. Maps (baseline vs proposal) and benefit-per-retén chart | **CP6 13:00** tests logged |
| Sun 13:00–18:00 | P2 + P3 | Report "Plan preventivo · Julio–agosto 2027", field dictionary, audit file (counts in/out, duplicates, unroutable, missing weights) | |
| Sun 18:00–20:00 | All | Save the working version in the workspace, submit in "Entrega" | **CP7 20:00** internal deadline |
| Sun 20:00–23:59 | — | Buffer only, no new features | |

Fallbacks if a step slips:
- D2 fails by Fri 17:00: keep the v0.1 proxy points as the scope and state it as limitation L-proxy.
- Navarra not loaded: keep `routable` = 0 for NAV and state the limitation.
- Fewer than 6 valid years: shorten the period for **all** zones (never mix periods).
- Platform rejects `.gpkg`: use the bundle in §4.

## 4. Getting it into the hackathon platform

1. **Datos** (workspace "flAIre"): upload `flaire.gpkg` v1.0 plus `README_datos.md` (fields dictionary + source register). The agent does not need road geometry, vegetation polygons or raw `weather_obs` at runtime. If the size limit bites, upload a slim `flaire_agent.gpkg` without those tables.
2. **Also upload a compact bundle `agent_bundle/` (CSV + Parquet)** in case large or binary files can't be uploaded. Precomputed `travel_times` and scenario results are enough for every tool:
   - `buildings_scope.csv` (id, municipality, lon, lat, use, dwellings, veg_distance_m, zone_id, weight)
   - `origins.csv` (stations + candidate ficha fields), `candidate_checks.csv`
   - `travel_times.parquet` + `travel_times.csv.gz` (≈ 19 × 15k rows ≈ 2 MB parquet)
   - `weather_profile.csv`, `weather_profile_year.csv`, `weather_adverse_days.csv`, `weather_quality.csv`
   - `scenarios.csv`, `results.csv`, `result_selection.csv`, `combo_metrics.csv`, `result_building.parquet`
   - `municipalities.geojson`, `boundary.geojson` (WGS84, simplified), `sources.csv`, `quality_reports.csv`, `parameters.csv`
   ```python
   import sqlite3, pandas as pd
   con = sqlite3.connect("flaire.gpkg")
   pd.read_sql("SELECT * FROM travel_times WHERE data_version='v1.0'", con).to_parquet("agent_bundle/travel_times.parquet")
   pd.read_sql("SELECT * FROM result_building", con).to_parquet("agent_bundle/result_building.parquet")
   pd.read_sql("SELECT * FROM v_scope_buildings", con).drop(columns="geom").to_csv("agent_bundle/buildings_scope.csv", index=False)
   ```
3. **Agentes**: preferably a Python agent whose 10 tools are the functions in `tools_spec.md` (sqlite3/pandas + `optimizer.py`). If Langflow is used, wrap the same functions as custom components so there is a single implementation. `optimizer.py run-csv` works directly on `travel_times.csv` if only the bundle is available.
4. **Pruebas**: save the 4 jury test conversations (main question, variation, limit, figure check). **Entrega**: report, maps, test log, data version v1.0.

## 5. Decisions the team must confirm at CP0
1. Pilot = **Tolosaldea (28 municipalities)**, not Oarsoaldea–Bidasoa. Update the product docs.
2. Scope buildings = residential (by `currentUse`, or by dwellings > 0 when use is missing) AND within **100 m** of fuel vegetation.
3. Adverse-day rule (thresholds on Tmax / RHmin / wind, no FWI), period **2018–2023**, season JUL-AUG.
4. Weight = adverse-day frequency of the building's zone. A building without a valid profile gets weight NULL (reported) and is still counted in raw coverage.
5. Benefit-per-retén = difference between best-k and best-(k−1) solutions, which may not be nested. Show `nested_with_prev` and the buildings lost.
6. Strategy A tie-break: covered count, then worst time. Strategy B: unroutable → worst time → weighted coverage → covered count.
7. Default threshold 12 min. Variations at 15 min and with speed factor 0.8.
