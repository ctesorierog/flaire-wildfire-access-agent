# flAIre FINAL agent · changes from v3, and since the hackathon

English rewrite (28 Oct 2026) of the Spanish changelog written on 3 Oct 2026 (`CAMBIOS_v3_a_final.md`, in git history up to commit 606141b). Facts were re-checked against the code on 28 Oct; where the 3 Oct text no longer holds, this file says so.

## In one paragraph

FINAL is the tested v3 agent adapted to the final data package and a new question: *where should up to N extra preventive crews go for the forest-edge homes of Tolosaldea, and on which risk days should they be active?* It was delivered to the hackathon platform on 3 Oct 2026 and is the canonical agent. v3 is the older version shown at the hackathon; it is in this repo's history (commit 7ff99a2), not in the current tree.

## Where things are

| | In this repo | On the hackathon platform |
|---|---|---|
| Agent code (5 files) | `agent/` | `agentes/agente_flair_final/` |
| Data (16 data files, 3 docs, 1 check script) | `agent/data/` | `agentes/flAIr datos FINAL/` |
| Platform runtime (`ejecucion.py`, `studio`) | not here: stand-ins in `app/` | provided by the platform template |

The code still carries the platform names (`CARPETA_DATOS = "flAIr datos FINAL"`, the paths in `main.py`'s `STUDIO_CONTEXT_FILES`). That is on purpose: the delivered code is kept as delivered. Off-platform, the runners pass the data folder explicitly.

## 1. What changed from v3, file by file

### `flaire_data.py` (94 KB) · the data layer
- **Finds the data folder** in this order: `./agentes/flAIr datos FINAL/` (the platform runs from the workspace root), the sibling folder of the code, `./datos/`. The marker file is `edificios_prioridad.csv`.
- **Reads `edificios_prioridad.csv`** with the new columns (`sin_ruta`, `prioridad`, `motivo_prioridad`, `puntos_*`, `fs_*`). It no longer reads v3's `edificios.csv`, `meteo_perfil.csv`, `meteo_dias_adversos.csv` or `auditoria.json`.
- **Weightings:** `prioridad` is the default (column `peso_optimizador`); `uniforme`; `meteo` and `firescope` use the `*_sensibilidad` columns and are labelled *sensitivity only*.
- **High-priority (Alta) buildings in every result:** each coverage, optimizer row, comparison and check reports `alta_dentro`, `pct_alta_dentro`, `alta_sin_ruta`, `alta_fuera_con_ruta`, `dentro_por_prioridad` and `viviendas_dentro`.
- **New functions:** `prioridad()`, `referencias()` (FireScope and past fires, reference only), `reglas_prioridad()`, `metodologia()`, `diccionario()`, `_meteo_resumen()`.
- **`perfil_meteo()` rewritten for the whole year:** risk days by month, zone and year; the zone test (`meteo_test_zonas.csv`); the Bera–Aiako Harria episode (Feb 2021); a filterable list of days.
- **`optimizar()` takes `objetivo_pct` and `metrica`** (`edificios`, `ponderada` or `alta`) and replaces v3's `minimo_retenes`; `minimo_k()` is kept for compatibility.
- **`fuera_umbral()` and `edificios_ganados()`** can filter by priority class.
- **`contexto()` lost the `temporada` parameter** and the July–August framing.
- **`comprobar()`** recomputes independently and compares with the engine, `escenarios.csv` (when it has the weighting), `cifras_clave_persona1.json` (Alta 49 today, 177 with CAND-01+02+03) and a report manifest.

### `tools.py` (18 KB)
- **10 tools** (section 2). Removed: `minimo_retenes` (now `objetivo_pct` in `optimizar_despliegue`) and `edificios_ganados` (now `modo='ganados'` in `consultar_edificios`). Added: `consultar_prioridad` and `ejecutar_codigo` (from the platform template, lazy `from ejecucion import execute_program`).
- **`ETAPA = 7`** switches tools on step by step for the platform deploy (section 3); 7 means all 10.
- `mapas` is imported inside `generar_informe`, so `mapas.py` is only needed from step 7.

### `mapas.py` (33 KB) · the HTML report
- Keeps the two synced maps, the chart, the tables and the JSON manifest.
- Homes coloured by priority (Alta, Media, Baja); a dark halo marks homes outside the threshold, a grey halo homes with no route.
- New chart "Alta inside (of 243)" for strategies A and B; table row Alta 49 → 177; crew table column "Alta it reaches first"; a new "When to activate" block with risk days per month.
- About 262 KB per report, well under the platform's 2 MB limit.

### `instrucciones.py` (6 KB) · the prompt
- Rewritten for the new question; the coordinator prompt is about 4,600 characters (v3: 6,700).
- Tool order: context (first turn only) → priority → **where** (optimize, then coverage or compare, then check) → **when** (weather) → report → `ejecutar_codigo` only if no tool answers.
- Speaking rules (from `REGLAS_prioridad.md`): it is a planning priority; never "fire probability" or "real risk"; never add FireScope into the score; never invent staff or real response times; decisions belong to the team; always state the limits.

### `main.py` (4 KB)
- `AGENT_NAME = "Agente flAIr FINAL"`, 8 iterations, memory on, no internet.
- `STUDIO_CONTEXT_FILES` lists the data files by their platform paths and no agent docs.
- Tolerates the step-by-step deploy (a provisional prompt before `instrucciones.py` exists; only `ejecutar_codigo` while `tools.py` is the template's).
- The reviewer sub-agent exists but is off (`USAR_SUBAGENTE_REVISION = False`).

## 2. The 10 tools

| # | Tool | What it does |
|---|---|---|
| 1 | `consultar_contexto` | The frame: question, area, priority, stations and candidates, "when". Sections: sources, methodology, limits, dictionary, references, rules |
| 2 | `consultar_prioridad` | Planning priority: counts per class (Alta 243 / Media 961 / Baja 2,127), municipalities, list with reasons, one building, rules |
| 3 | `perfil_meteorologico` | Year-round risk days by month, zone and year; zone test; Bera–Aiako Harria 2021; list of days |
| 4 | `calcular_cobertura` | Live coverage of a selection or of the best k crews: buildings, Alta, weighted, worst time, no route, municipalities |
| 5 | `optimizar_despliegue` | Exhaustive optimum for k = 0 to 6 (strategies A and B), Alta per k; with `objetivo_pct`, the smallest k over all 848 combinations for the chosen metric |
| 6 | `comparar_selecciones` | Two deployments side by side (default: best A vs best B, k = 3) |
| 7 | `consultar_edificios` | One building · the ones left outside (filter by priority) · `modo='ganados'`: what the k-th crew adds |
| 8 | `generar_informe` | HTML report with maps by priority, charts and a manifest |
| 9 | `comprobar_cifra` | Independent recount against the engine, `escenarios.csv`, the team's key figures and the manifest |
| 10 | `ejecutar_codigo` | The platform template's tool, to explore the CSVs freely. Off-platform it is replaced (section 5) |

## 3. Step-by-step deploy on the platform (3 Oct)

Upload to `agentes/agente_flair_final/` what each step says, then "Comprobar preparación", create a version and ask the test question. Steps 4 to 6 only change one line, `ETAPA` in `tools.py`; the delivered file has `ETAPA = 7`.

| Step | Upload (on top of earlier steps) | Tools | Test question → expected |
|---|---|---|---|
| 1 | `main.py` (template `tools.py`) | 1 | "Lee REGLAS_prioridad.md y dime cuántas viviendas Alta hay" |
| 2 | `instrucciones.py` | 1 | (the prompt already names later tools; expected) |
| 3 | `flaire_data.py` + `tools.py` with `ETAPA = 3` | 2 | "¿Cuántas viviendas Alta hay y dónde?" → 243; Asteasu 43, Amezketa 35, Abaltzisketa 28 |
| 4 | `ETAPA = 4` | 4 | "Cobertura con CAND-01;CAND-02;CAND-03" → 3,187 (95.7 %), 177 Alta, check passes |
| 5 | `ETAPA = 5` | 7 | "¿Dónde pongo 3 retenes?" → CAND-01, 02, 03 (weighted 94.7 %); at 15 min CAND-02, 03, 10 |
| 6 | `ETAPA = 6` | 9 | "¿Cuándo activarlos?" → ~26.3 risk days a year; Feb–Apr 32 %, Sep–Oct 31 %, Jul–Aug 14 %; zones not distinguishable |
| 7 | `mapas.py` + `ETAPA = 7` | 10 | "Genera el informe con 3 retenes" → ~262 KB HTML, then check against the manifest |

## 4. Tests

- **The FINAL suite `tests_final/` (68 tests on 3 Oct) is not in this repo.** It covered the expected optimizer values (A, light, 12 and 15 min, k = 0–6), Alta 49 / 177, the weather figures, the old weightings against `escenarios.csv`, package limits (≤ 10 tools, ≤ 4 MB per file, no forbidden imports, HTML ≤ 2 MB with no external resources) and a smoke call per tool. Ask the hackathon team whether the upload kept it.
- **What guards FINAL today:**
  - `tests/test_greedy.py` (4 tests) imports `flaire_data` and checks greedy against exhaustive.
  - The rest of `tests/` re-counts the headline numbers from `agent/data/` independently of this code (screens, stability table, map data, web app): `python -m pytest -q tests` gives 64 passed and 11 skipped on a fresh clone; the 11 need the pipeline rebuilt from raw data.

## 5. Since the hackathon (27–28 Oct 2026)

The delivered code changed in one place only; everything else wraps it.

- **`greedy_cobertura()`** added to `flaire_data.py` (bcbd0ed, 21 lines): greedy max coverage, equal to the exhaustive result for k = 1–6 here (2,958 with one crew, 3,187 with three). Not used by any tool; it is the evidence that the method could scale to a larger pool.
- **First real runs off the platform** (`app/run_agent_once.py`, b4a4281): same prompt, tools and data; `studio.py` stands in for the platform module; model `claude-opus-5-5` with the team's own API key. Two fixes the platform hid: no `temperature` (current models reject it) and `base_url` pinned to api.anthropic.com. Transcript and claim-by-claim check: `docs/transcripts/2026-10-27_1057_agent_final.md` (one false claim caught after the run: Asteasu "mostly Alta" is really half).
- **Web app** (`app/agent_local.py`): loads the same prompt, tools and data, but swaps `ejecutar_codigo` (needs the platform's `ejecucion` module) for `mostrar_ortofoto` (the orthophoto and verdict of a study site). Still 10 tools.
- **Public layout:** the agent lives in `agent/` and its data in `agent/data/`. File contents unchanged, except that `incendios_previos.csv` (past fire perimeters scraped from the FireScope viewer, no licence) is left out; the agent treats it as optional and skips that reference.

## 6. Risks and open points (re-checked 28 Oct)

- **Weightings.** The 3 Oct text said "with k = 3 the 4 weightings all pick CAND-01, 02, 03". That is true only at light vehicle, 12 min (`escenarios.csv`: uniform, meteo and firescope all pick them). It is not a general robustness claim: across thresholds, vehicles and k, the weighted and uniform picks differ in 9 of 42 cases (`reports/linker_validation.md`), and the weather points in the priority score are 0 for every building, so the "meteo" weighting is inert. What we defend: CAND-02 and CAND-03 are in every best trio across thresholds and vehicles with every building weighted 1 (`app/data/stability.json`).
- **Crew order depends on the weighting.** At k = 4 the `prioridad` weighting picks CAND-05 where the other three pick CAND-04 (3,216 buildings / 183 Alta vs 3,217 / 184, a near tie). The agent defaults to `pesos='prioridad'`; the web map uses weight 1. Know which one a screen shows.
- **`escenarios.csv` has no `prioridad` weighting.** Not blocking: the agent computes live and `comprobar_cifra` recomputes; if the column is added, the comparison switches on by itself.
- **Step 2 of the deploy:** the prompt names tools that don't exist until step 7; a call to one returns a tool error. Uploading `instrucciones.py` with step 3 avoids it.
- **Output size:** lists stop at 50 rows per call (`lista_truncada` says so and how to see the rest); default outputs stay under about 10,000 characters.

## 7. Review fixes applied before delivery (3 Oct)

1. **Minimum crews (`objetivo_pct`):** for each k it now searches all 848 combinations for the chosen metric, instead of reading strategy A's curve. With metric `alta` (12 min, light): 80 % needs k = 6 (k = 5 gives 194/243 = 79.8 %); 82 % needs k = 6 with CAND-01, 02, 03, 04, 05, 10 (200/243 = 82.3 %, before "not reached"); 85 % is not reachable (maximum 82.3 %). The Alta maximum at k = 4 is 187.
2. **Lists capped at 50 rows** (`limite` in `consultar_prioridad` and `consultar_edificios`, `top_dias` in `perfil_meteorologico`).
3. **Prompt:** "which Alta stay outside with N crews?" is answered with `consultar_edificios(prioridad='Alta', k=N)`; with k = 3, 32 stay outside with a route and 34 have no route.
4. **`comprobar_cifra`:** `k = -1` means "not given" and uses 3, like the other tools.
5. **Labels:** the municipality is no longer repeated in site names ("Aparcamiento sin nombre (Amezketa)"); the `meteo` weighting is labelled "legacy Jul–Aug, sensitivity only".
