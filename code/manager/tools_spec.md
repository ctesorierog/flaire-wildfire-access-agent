# flAIre · Agent tool contracts (v1.0, 1 Oct 2026)

The agent answers planners' questions only through these 10 tools over `flaire.gpkg` (schema: `schema.sql`).
Tools are thin Python functions (sqlite3 + numpy, no GIS libs needed: point tables carry lon/lat/x/y).
`optimize_deployment` and `min_k_for_target` call `optimizer.py`.

## Common conventions (all tools)

- Every response includes `data_version`, `source_ids` (ids in `sources`) and `caveats` (list of strings). The agent must quote the caveats that apply.
- Errors: `{"error": {"code": "...", "message": "..."}}`. Codes: `NOT_FOUND`, `INVALID_PARAM`, `OUT_OF_SCOPE`, `DATA_MISSING`, `KMAX_EXCEEDS_CANDIDATES`.
- Missing values come back as `null` with a reason, never as 0.
- Default `season` = `JUL-AUG`, `threshold_min` = 12 (demo parameter, not official), `data_version` = latest frozen.
- Wording the agent must keep: "travel-time estimate" (not response time); "historical frequency of adverse days" (not fire probability); "weighted coverage" (not protected population); "candidate for study" (not authorised site).

---

### 1. `get_context(season, plan_year)`
Purpose: frame any answer: what period, data, scope and parameters are in use.

Input
```json
{"type":"object","properties":{
  "season":{"type":"string","enum":["JUL-AUG","JUN-SEP"],"default":"JUL-AUG"},
  "plan_year":{"type":"integer","minimum":2026,"default":2027}},
 "additionalProperties":false}
```
Output
```json
{"season":"JUL-AUG","months":[7,8],"plan_year":2027,
 "plan_year_effect":"label only - results depend on historical period, not on plan year",
 "historical_period":{"from":2018,"to":2023,"method_version":"ADV-v1","definition":"..."},
 "scope":{"area":"Tolosaldea (28 municipios)","n_municipalities":28,
          "n_buildings_scope":0,"rule":"residential AND near_vegetation (<=100 m)"},
 "origins":{"stations":[{"id":"GIP-ORIA","routable":true,"loc_confidence":"address_street"}],
            "n_valid_candidates":10},
 "parameters":{"threshold_default_min":12,"veg_proximity_m":100,"k_max_allowed":6},
 "sources":[{"source_id":"SRC-B5M-BU","title":"...","edition":"...","download_date":"2026-10-02"}],
 "data_version":"v1.0","caveats":["..."]}
```
Tables: `seasons, profile_methods, parameters, v_scope_buildings, fire_stations, candidates, data_versions, data_version_sources, sources`.
Example: `get_context({"season":"JUL-AUG","plan_year":2027})`

### 2. `get_zone_profile(zone_id | municipality_code | building_id, season)`
Purpose: explain why an area weighs more: adverse-day frequency, years and days behind it, data completeness.

Input
```json
{"type":"object","properties":{
  "zone_id":{"type":"string","pattern":"^Z-"},
  "municipality_code":{"type":"string","pattern":"^20[0-9]{3}$"},
  "municipality_name":{"type":"string"},
  "season":{"type":"string","default":"JUL-AUG"},
  "top_days":{"type":"integer","default":10,"maximum":50}},
 "oneOf":[{"required":["zone_id"]},{"required":["municipality_code"]},{"required":["municipality_name"]}]}
```
Output
```json
{"zone_id":"Z-C026","station":{"id":"C026","name":"Berastegi","elevation_m":0,"distance_km_median":0},
 "season":"JUL-AUG","years":[2018,2023],"valid_days":0,"adverse_days":0,
 "adverse_day_frequency":0.0,"interannual_sd":0.0,
 "by_year":[{"year":2018,"valid_days":0,"adverse_days":0}],
 "top_adverse_days":[{"date":"2022-07-18","tmax_c":0,"rhmin_pct":0,"wind_max_ms":0}],
 "completeness":[{"variable":"rh","pct_valid":0.0}],
 "rank_among_zones":1,"n_zones":3,
 "municipality_breakdown":[{"zone_id":"Z-C026","n_buildings":0,"share":0.0}],
 "data_version":"v1.0","caveats":["historical frequency is not fire probability"]}
```
Municipality input returns the distribution of its scope buildings across zones (`zone_assignment`) and each zone's profile.
Tables: `weather_zones, weather_stations, weather_profile, weather_profile_year, weather_adverse_days, weather_quality, zone_assignment, profile_methods`.
Example: `get_zone_profile({"municipality_name":"Berastegi","season":"JUL-AUG"})`

### 3. `compute_coverage(origins, threshold_min, weighted)`
Purpose: coverage of any explicit set of origins, computed live from `travel_times`. Also the **figure check**: with `origins:["EXISTING"]` it recomputes k=0 independently and compares with the stored result.

Input
```json
{"type":"object","required":["origins"],"properties":{
  "origins":{"type":"array","items":{"type":"string"},
             "description":"'EXISTING' (all routable stations) and/or station/candidate ids"},
  "threshold_min":{"type":"number","exclusiveMinimum":0,"maximum":60,"default":12},
  "weighted":{"type":"boolean","default":true},
  "season":{"type":"string","default":"JUL-AUG"},
  "speed_factor":{"type":"number","exclusiveMinimum":0,"maximum":1,"default":1.0},
  "by_municipality":{"type":"boolean","default":true}}}
```
Output
```json
{"origins_used":["GIP-ORIA","GIP-GOIERRI","CAND-03"],"threshold_min":12,
 "n_buildings":0,"n_covered":0,"pct_covered":0.0,
 "weighted_covered":0.0,"weighted_total":0.0,"weighted_share":0.0,"n_weight_missing":0,
 "worst_time_min_est":0.0,"n_unroutable":0,
 "by_municipality":[{"code":"20071","name":"Tolosa","n":0,"covered":0,"unroutable":0,"worst":0.0}],
 "check":{"stored_scenario":"S-JUL-AUG-12-A-...","stored_n_covered":0,"match":true},
 "data_version":"v1.0","caveats":["travel-time estimate, no turnout time"]}
```
Tables: `travel_times, v_scope_buildings, v_building_weight, municipalities, origins, results`.
Example: `compute_coverage({"origins":["EXISTING","CAND-02"],"threshold_min":15})`

### 4. `optimize_deployment(k_max, strategy, threshold_min)`
Purpose: best combination of extra retenes for each k = 0..k_max (exhaustive, 848 combos for 10 candidates / k<=6). Returns stored scenario if the same calculation exists (same key minus plan_year), else runs `optimizer.py` (~1-2 s) and stores it.

Input
```json
{"type":"object","required":["k_max","strategy"],"properties":{
  "k_max":{"type":"integer","minimum":0,"maximum":6},
  "strategy":{"type":"string","enum":["A","B"],
              "description":"A: max weighted coverage. B: fewest unroutable, then lowest worst time, then weighted coverage"},
  "threshold_min":{"type":"number","default":12},
  "season":{"type":"string","default":"JUL-AUG"},
  "weighting":{"type":"string","enum":["historical_frequency","none"],"default":"historical_frequency"},
  "speed_factor":{"type":"number","default":1.0}}}
```
Output
```json
{"scenario_id":"S-JUL-AUG-12-A-historical_frequency-v1.0","strategy":"A","n_combinations":848,
 "per_k":[{"k":0,"selection":[],"n_covered":0,"pct_covered":0.0,"weighted_share":0.0,
           "worst_time_min_est":0.0,"n_unroutable":0,"gain_covered_vs_k0":0,
           "gain_covered_vs_prev":null,"nested_with_prev":null,"ties":1}],
 "data_version":"v1.0","caveats":["best k-set need not contain best (k-1)-set"]}
```
Tables: `scenarios, results, result_selection, combo_metrics` (read) / `result_building` (write); runs `optimizer.optimize`.
Example: `optimize_deployment({"k_max":6,"strategy":"B","threshold_min":12})`

### 5. `compare_results(scenario_a, scenario_b, k)`
Purpose: explain why two scenarios (e.g. A vs B, 12 vs 15 min) pick different sites.

Input
```json
{"type":"object","required":["scenario_a","scenario_b"],"properties":{
  "scenario_a":{"type":"string"},"scenario_b":{"type":"string"},
  "k":{"type":"integer","minimum":0,"maximum":6,"description":"omit = all k"}}}
```
Output
```json
{"k":3,"selection_a":["CAND-01","CAND-06","CAND-02"],"selection_b":["CAND-05","CAND-02","CAND-03"],
 "only_in_a":["CAND-01"],"only_in_b":["CAND-05"],
 "metrics_a":{"n_covered":0,"weighted_share":0.0,"worst_time_min_est":0.0,"n_unroutable":0},
 "metrics_b":{"n_covered":0,"weighted_share":0.0,"worst_time_min_est":0.0,"n_unroutable":0},
 "buildings_covered_only_a":0,"buildings_covered_only_b":0,
 "worst_buildings_a":[{"building_id":"...","municipality":"Amezketa","minutes":0.0}],
 "rank_of_b_selection_in_a":17,
 "explanation_facts":["A objective = weighted coverage; B first minimises unroutable then worst time"],
 "data_version":"v1.0","caveats":[]}
```
Tables: `scenarios, results, result_selection, result_building, combo_metrics, buildings, municipalities`.
Example: `compare_results({"scenario_a":"S-JUL-AUG-12-A-...","scenario_b":"S-JUL-AUG-12-B-...","k":3})`

### 6. `explain_building(building_id, scenario_id, k)`
Purpose: full traceable record of one building (also used to check a figure against raw data).

Input
```json
{"type":"object","required":["building_id"],"properties":{
  "building_id":{"type":"string"},"scenario_id":{"type":"string"},"k":{"type":"integer"}}}
```
Output
```json
{"building_id":"ES.B5M.BU.000","source_id":"SRC-B5M-BU","source_use":"1_residential","dwellings":null,
 "dwellings_note":"not published in source","municipality":{"code":"20022","name":"Berastegi"},
 "lon":0.0,"lat":0.0,"veg_distance_m":0.0,"near_vegetation":true,
 "zone":{"zone_id":"Z-C026","weight":0.0,"assign_method":"nearest_station"},
 "network":{"node_id":0,"snap_distance_m":0.0},
 "times":[{"origin_id":"GIP-ORIA","minutes_est":0.0,"routable":true}],
 "baseline":{"best_origin":"GIP-ORIA","minutes_est":0.0,"covered":false},
 "in_scenario":{"k":3,"best_origin":"CAND-03","minutes_est":0.0,"covered":true},
 "data_version":"v1.0","caveats":[]}
```
Tables: `buildings, municipalities, zone_assignment, v_building_weight, travel_times, result_building`.
Example: `explain_building({"building_id":"ES.B5M.BU.12345","scenario_id":"S-...-A-...","k":3})`

### 7. `buildings_gained(scenario, kth_reten)`
Purpose: which buildings the k-th retén brings within threshold, which are lost (if optimal sets are not nested) and which stay out.

Input
```json
{"type":"object","required":["scenario_id","kth_reten"],"properties":{
  "scenario_id":{"type":"string"},"kth_reten":{"type":"integer","minimum":1,"maximum":6},
  "list_limit":{"type":"integer","default":50},"as_geojson":{"type":"boolean","default":false}}}
```
Output
```json
{"k":3,"selection_prev":["CAND-01","CAND-06"],"selection":["CAND-01","CAND-06","CAND-02"],
 "nested":true,"n_gained":0,"n_lost":0,"n_still_out_routable":0,"n_unroutable":0,
 "gained_weighted":0.0,
 "by_municipality":[{"name":"Amezketa","gained":0,"still_out":0}],
 "gained_sample":[{"building_id":"...","before_min":0.0,"after_min":0.0,"by":"CAND-02"}],
 "still_out_sample":[{"building_id":"...","best_min":0.0}],
 "geojson":null,"data_version":"v1.0","caveats":[]}
```
Tables: `result_building, result_selection, buildings, municipalities, v_building_weight`. Logic = `optimizer.buildings_gained`.
Example: `buildings_gained({"scenario_id":"S-JUL-AUG-12-A-...","kth_reten":3})`

### 8. `min_k_for_target(target, strategy)`
Purpose: smallest number of extra retenes that reaches the user's coverage target.

Input
```json
{"type":"object","required":["target"],"properties":{
  "target":{"type":"number","description":"pct_covered in % (0-100) or weighted_share in 0-1"},
  "metric":{"type":"string","enum":["pct_covered","weighted_share"],"default":"pct_covered"},
  "strategy":{"type":"string","enum":["A","B"],"default":"A"},
  "threshold_min":{"type":"number","default":12},"season":{"type":"string","default":"JUL-AUG"}}}
```
Output
```json
{"reached":true,"k":3,"selection":["..."],"value":90.4,"target":90,
 "curve":[{"k":0,"value":71.8}],
 "if_not_reached":{"max_value":null,"k_max_tested":6},
 "data_version":"v1.0","caveats":["k limited to 6 and to 10 study candidates"]}
```
Tables: `results` (via `optimize_deployment`). Logic = `optimizer.min_k_for_target`.
Example: `min_k_for_target({"target":90,"metric":"pct_covered","strategy":"A"})`

### 9. `list_limitations()`
Purpose: honest limits, with live counts from the data.

Input `{"type":"object","properties":{"scenario_id":{"type":"string"}}}`
Output
```json
{"limitations":[
  {"id":"L1","text":"Travel-time estimates with assumed speeds by road class (light vehicle, free flow); no turnout time","metric":{"share_edges_class_assumed":0.86}},
  {"id":"L2","text":"Unroutable buildings reported, not dropped","metric":{"n_unroutable_k0":0}},
  {"id":"L3","text":"Historical frequency of adverse days (2018-2023) is not fire probability; no FWI computed","metric":{}},
  {"id":"L4","text":"Weighted coverage is not protected population; dwellings missing for some buildings","metric":{"n_dwellings_null":0}},
  {"id":"L5","text":"Candidates are study sites (OSM POIs); 6 field checks pending each","metric":{"n_checks_pending":60}},
  {"id":"L6","text":"Fire-station locations approximate (address street)","metric":{"n_not_verified":0}},
  {"id":"L7","text":"Navarra roads/stations: included or not","metric":{"nav_edges":0}},
  {"id":"L8","text":"12 min is a demo threshold, not an official standard","metric":{}},
  {"id":"L9","text":"Weather zone = nearest representative station; missing weight not imputed","metric":{"n_weight_missing":0}}],
 "quality_fails":[{"dataset":"buildings","check":"nulls:dwellings","status":"warn","value":0}],
 "data_version":"v1.0"}
```
Tables: `parameters, quality_reports, road_edges, results, buildings, candidate_checks, fire_stations`.
Example: `list_limitations({})`

### 10. `prepare_report(scenario)`
Purpose: build "Plan preventivo · Julio–agosto 2027" (Markdown + figure data) for a chosen scenario and k.

Input
```json
{"type":"object","required":["scenario_id"],"properties":{
  "scenario_id":{"type":"string"},"k":{"type":"integer","description":"proposed number of retenes"},
  "plan_year":{"type":"integer","default":2027},"compare_with":{"type":"string"},
  "format":{"type":"string","enum":["markdown","json"],"default":"markdown"}}}
```
Output
```json
{"title":"Plan preventivo · Julio–agosto 2027","markdown":"...",
 "sections":["Pregunta y destinatario","Datos y fuentes","Situación sin refuerzo","Propuesta k","Beneficio por retén","Edificios que siguen fuera","Comparación A/B","Cifra comprobada","Limitaciones","Pendiente de comprobar en campo"],
 "figures":{"benefit_per_reten":[{"k":1,"gain":0}],"map_layers":["baseline","proposal"]},
 "checked_figure":{"claim":"...","recomputed":0,"stored":0,"match":true},
 "data_version":"v1.0","source_ids":["..."]}
```
Tables: everything read-only; calls `get_context`, `compute_coverage` (check), `buildings_gained`, `list_limitations`. Writes `plans` row.
Example: `prepare_report({"scenario_id":"S-JUL-AUG-12-A-...","k":3,"plan_year":2027,"compare_with":"S-JUL-AUG-12-B-..."})`

---

## Question -> tool map

| Question | Tools (in order) |
|---|---|
| **Main (jury)**: "For July-Aug 2027, where should we study placing up to N extra retenes in Tolosaldea to cover the most historically exposed residential buildings near vegetation within 12 min?" | `get_context` -> `optimize_deployment(k_max=N, A)` -> `buildings_gained` -> `prepare_report` |
| **Variation (jury)**: "And if we prioritise the worst-served buildings?" / "And at 15 min?" | `optimize_deployment(B)` or `(threshold=15)` -> `compare_results` |
| **Limit (jury)**: "What is the fire probability in Amezketa?" / "Plan for 2028?" / "8 retenes?" | refuse/reframe with `get_zone_profile` (frequency, not probability); `get_context(plan_year=2028)` shows identical results; `optimize_deployment(k_max=8)` -> `KMAX_EXCEEDS_CANDIDATES`/max 6; `list_limitations` |
| **Figure checked (jury)** | `compute_coverage(["EXISTING"],12)` recomputes k=0 from `travel_times` and compares with stored `results`; `explain_building` on a Berastegi building shows GIP-ORIA time vs manual check (11.4 km / 11.5 min) |
| Why does this zone have more historical weight? Which years/days back it? | `get_zone_profile` (by_year, top_adverse_days, completeness) |
| Why do strategies pick different sites? | `optimize_deployment(A)`, `optimize_deployment(B)`, `compare_results` |
| Which buildings does the 3rd retén benefit, which stay out? | `buildings_gained(scenario, 3)` (+ `explain_building` for one) |
| Minimum number to reach my target | `min_k_for_target` |
| Why is building X not covered? | `explain_building` |
| What does adding CAND-02 alone give? | `compute_coverage(["EXISTING","CAND-02"])` |

## Agent guardrails (system prompt essentials)
1. Call `get_context` first in every new conversation; state season, period, data version.
2. Never compute numbers itself; every figure comes from a tool output and is quoted with its unit and data_version.
3. Always report unroutable count next to coverage; never say "protected", "probability" or "response time".
4. k > valid candidates or > 6: refuse with reason. Plan year changes nothing but the title.
5. End proposals with the candidate disclaimer and the pending field checks (`candidate_checks`).
