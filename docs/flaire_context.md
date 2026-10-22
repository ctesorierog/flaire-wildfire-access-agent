# flAIre — shared context for all agents (compiled 1 Oct 2026, 21:30 CEST)

## Hackathon (Gipuzkoa AI Hackathon · Urban Challenge · MIT Media Lab City Science)
Brief: build a DATA AGENT that lets a person ask several questions about an urban problem in Gipuzkoa and get answers grounded in real data.
Steps: 1) define user + main question + related queries; 2) prepare the base (organized files, precomputed calcs allowed, keep sources, explain each field); 3) build agent + tools (tool = function/flow that queries data or runs a calculation; agent decides when/with which params); 4) show it can be explored: one query + one variation, check a figure, review limits, save a working version in the workspace.
Platform workspace sections: Resumen, Datos (file upload), Agentes (Langflow or Python), Pruebas, Entrega, Asistente IA. Team workspace is named "flAIre". Delivery date: 4 Oct 2026. Team must be 3–4 confirmed people; choose preferred track (industrial / services).
Worked example (Donostia climate refuges): buildings with dwellings, census by zone, pedestrian network, 96 refuges; Coordinator agent calls analysis, visualization and review agents. Their audit file lists: population distributed/not distributed, duplicate rows, buildings without dwellings, accesses excluded (no building within 10 m, ambiguous association), buildings with several accesses -> this is the level of traceability judges expect.

MANDATORY for jury: question located in Gipuzkoa + recipient + usefulness; identified sources and prepared data; working agent version; test of main question + a variation + a limit; at least one figure checked directly against the data.
SCORING: Utility 25% · Analysis quality, sources & traceability 25% · Agent functioning & tool use 25% · Clarity of answers/artifacts 15% · Reliability, limits, human oversight 10%. Tie-break: agent functioning, analysis quality, utility. Technology choice doesn't score; multiple agents only if they help.
Official portals listed by organizers: Udalmap, Gipuzkoa Irekia, Donostia Open Data, B5M (b5m.gipuzkoa.eus/web5000/es/api-rest/conjuntos-datos), Open Data Euskadi APIs, Eustat, geoEuskadi geonetwork, NAP Transporte, INE, Lanbide.

## Project flAIre (team docs)
Product: help fire-service planners decide where to study placing additional preventive "retenes" (temporary crews) during a season (July–Aug 2027 plan), using historical weather patterns, residential buildings near vegetation, and road access times. Compare 0..N extra retenes (N = 1..6) from 10 candidate sites; two strategies: A) maximize sum of historical weights of buildings within travel threshold (also show raw count), B) improve worst access (first reduce unroutable, then worst time; weighted coverage tie-break). 10 candidates -> 847 combinations for k=1..6; reuse time matrices. Two synced maps (no reinforcement vs proposal), benefit-per-reten chart, AI agent, report "Plan preventivo · Julio–agosto 2027".
Agent conceptual tools: consultar contexto; calcular cobertura; optimizar despliegue; comparar resultados; preparar propuesta. Must answer: why does this zone have more historical weight / which years & days back it; why do strategies pick different sites; show buildings the 3rd retén benefits and which stay out; minimum quantity reaching my coverage target.
Rules: a building counted once; unroutable points reported not dropped; historical frequency ≠ fire probability; weighted coverage ≠ protected population; never mix dates/sources; max retenes ≤ valid candidates; times are travel estimates, not response times; threshold default 12 min (demo, not official); changing only the plan year must not change results; missing data ≠ zero; FWI not to be computed ad hoc.

PILOT ZONE: product docs (29 Sep) say Oarsoaldea–Bidasoa, but research-roles doc (1 Oct, newest) and existing Persona 4 work use TOLOSALDEA = union of 28 municipalities: Abaltzisketa, Aduna, Albiztur, Alegia, Alkiza, Altzo, Amezketa, Anoeta, Asteasu, Baliarrain, Belauntza, Berastegi, Berrobi, Bidania-Goiatz, Elduain, Gaztelu, Hernialde, Ibarra, Ikaztegieta, Irura, Larraul, Leaburu, Lizartza, Orendain, Orexa, Tolosa, Amasa-Villabona, Zizurkil (reference: Área Funcional de Tolosa del PTP; Enirio-Aralar kept separate as context).

Research roles (1 Oct):
- P1 Meteorology: stations in/near Tolosaldea (start Berastegi C026, Zizurkil C029, Bidania C058), 2018–2023 working period, temp, RH, wind speed/dir, precip; units/timezone/frequency/sensor height; quality table station×year×month×variable (present vs valid). Sources: Euskadi station catalogue, 2023 historical readings, Euskalmet Open Data services.
- P2 Buildings & territory: tolosaldea_boundary.geojson, tolosaldea_municipalities.geojson, municipalities.csv FIRST; then building layer (stable IDs, declared use, dwellings, date), border rule (interior representative point), quality per municipality. Sources: geoEuskadi admin limits, PTP Tolosa memoria, INSPIRE buildings Gipuzkoa (B5M).
- P3 Vegetation & terrain: provincial forest/land-use layer (Mapa Forestal del País Vasco), edition year, class dictionary, DEM 5 m (geoEuskadi), slope; pilot extract with margin ≥ proximity distance. GeoPackage/GeoTIFF.
- P4 Access & fire stations (Carlos): routable road network incl. outside links, fire stations (official), ~10 candidates with fichas, connectivity checks, speed notes. Sources: Geofabrik OSM, Gipuzkoa roads, Gipuzkoa fire stations (B5M), geoEuskadi viewer.
Every package: raw/, processed/, source register (exact URL, org, licence, download date, edition/period, file), field explanation, quality report. WGS84 for GeoJSON exchange; EPSG:25830 for metric calcs.

## Existing Persona 4 package v0.1 (built in a previous session; FILES NOT AVAILABLE in this workspace, only the docs)
- roads_study_area_with_speeds.gpkg: OSM Geofabrik (País Vasco extract) 55,386 segments, speeds assumed by class (motorway 100, trunk 80, primary 70, secondary 60, tertiary 50, unclassified 40, residential 30, service/living 15); 86% segments lack maxspeed.
- PROBLEM 1: source drivable_roads.geojson lacked *_link classes -> 1,561 synthetic connectors (≤200 m, 40 km/h + 18 s). Real fix: re-export with links.
- PROBLEM 2: no Navarra roads (Leitza, Lekunberri, Betelu), Navarre stations not routable.
- PROBLEM 3: fire-station locations approximate (100–400 m), placed on street of official address, no geocoder.
- PROBLEM 4: candidates chosen from a POI file (restaurants/cafés) — weak as reten sites.
- 9 stations (8 foral + Garbera municipal). Oria (Tolosa) closest for 96% of points.
- Baseline uses 6,714 PROXY points (network points, 1 per 100 m cell) instead of buildings. 12 min: 71.8% covered; worst 23.5 min; 65 unroutable. All 10 candidates: 97.5%, worst 16.1.
- Manual check from Oria: Amezketa 13.4 km/16.1 min; Berastegi 11.4 km/11.5 min; Villabona 7.6/5.5; Lizartza 6.6/7.4.
- Candidates CAND-01..10 (lat, lon): 01 Pasus Jatetxea Villabona 43.19027,-2.05586 (7.1 min); 02 Txindoki Amezketa 43.04369,-2.08397 (13.0); 03 Kako Berastegi 43.12425,-1.97905 (11.4); 04 Elane Albiztur 43.12950,-2.13024 (5.9); 05 Abaetxe Jatetxea "Tolosa" 43.05011,-2.04067 (17.5); 06 cafe iTunes Asteasu 43.19812,-2.10435 (12.8); 07 Sausta Tolosa 43.14223,-2.07303 (3.2); 08 Errotatxo Alegia 43.09873,-2.09686 (4.7); 09 Iriarte Berrobi 43.14531,-2.02589 (5.6); 10 Zartagi Baliarrain 43.06921,-2.12804 (8.4). Greedy selection, min 3 km separation; 01–08 by new points ≤12 min, 09–10 by reduced minutes over threshold. All via GIP-ORIA.

## Environment constraint
The cloud sandbox CANNOT reach euskadi.eus, gipuzkoa.eus, geofabrik, copernicus, overpass, open-meteo (egress policy). Only PyPI, npm registry and GitHub are reachable. Do not attempt to fetch data; do not use unofficial mirrors as sources of record.
