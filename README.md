# flAIre: a data agent for wildfire-access planning in Gipuzkoa

**Top 3 of the Gipuzkoa AI Hackathon (Urban Challenge, October 2026). Invited to present at the MIT City Science Summit Tools Workshop (Donostia, November 2026).**

flAIre helps the fire-prevention planner of Gipuzkoa answer one question: *where should up to N extra preventive crews (retenes) be placed in Tolosaldea, and what does each one add?* An LLM agent answers in plain Spanish, but every number comes from deterministic, tested data tools. The agent cites the source and the limits of each figure and refuses to invent what the data can't support.

## Result

For the 3,331 homes within 100 m of forest or scrub in Tolosaldea, light-vehicle access within 12 minutes:

| Extra crews | Sites | Homes reached in 12 min |
|---|---|---|
| 0 (today: 9 fire stations) | – | 2,712 (81.4 %) |
| 3 | CAND-01, CAND-02, CAND-03 | 3,187 (95.7 %) |

CAND-02 (Amezketa) and CAND-03 are chosen under every travel-time threshold and vehicle we tested; the third site is a judgement call (a 6-building margin). In this version the weather weighting has no effect on the result yet, so we don't claim the choice is robust across weightings.

## How it works

1. **Data pipeline** (`code/pipeline/`): official open data is cleaned and linked.
   - 28 municipalities; 124,140 → 14,015 buildings → 3,331 residential homes near vegetation (Mapa Forestal 2024).
   - A routable OpenStreetMap road graph (415k edges, motorway ramps included, light-vehicle and truck speed profiles).
   - 16.7 M ten-minute weather readings.
   - 532k travel times from 9 fire stations and 10 candidate sites to every home.
2. **Database** (`database/`): a 36-table schema with integrity rules (`schema.sql`) and a 15 MB GeoPackage (`flaire_lite.gpkg`). The full 214 MB database is reproducible with `code/pipeline/link_build.py`.
3. **Optimizer** (`code/manager/optimizer.py`): an exhaustive search over all 848 candidate combinations × 36 scenarios. It compares strategy A (maximise homes within the threshold) with strategy B (improve the worst access). Unit-tested in `test_optimizer.py`.
4. **Priority module** (`code/prioridad/`): ranks homes by vegetation, building data and historical adverse-weather days.
5. **Agent** (`agent/`): runs on the hackathon's agent platform with 10 tools, including coverage, comparison, scenario lookup, maps, figure checking (`comprobar_cifra`) and an HTML report generator. `flaire_data.py` holds the validated query layer. The data the agent reads is in `agent/datos/`.
6. **Evaluation**: 26 agent tests with a fake platform module (`code/tests_agente/`), 11 QA views and 11 hand checks of travel times (`docs/linker_validation.md`).

## Try the data layer

```bash
pip install pandas
cd agent
python -c "import flaire_data as f; print(f.cobertura(k=3)['resultado'])"
```

`example_report/` contains a generated report: two synced maps, a benefit chart and a manifest listing the source of every figure.

## Honest limits

- Travel times are estimates from assumed speeds (only about 14 % of roads have a tagged speed limit), not real response times.
- The 12-minute threshold is for the demo, not an official standard.
- Candidate sites are study locations, not authorised bases.
- Historical adverse-weather frequency is not fire probability.
- FireScope is used only as an experimental, third weighting.

## Data and licences

OpenStreetMap (ODbL), Euskalmet / Open Data Euskadi (CC BY 4.0), geoEuskadi, Mapa Forestal del País Vasco 2024, Diputación Foral de Gipuzkoa B5M (CC BY 4.0), and INSAIT FireScope (CC BY 4.0). Derived travel times and candidates are shared under ODbL. Details: `docs/LICENCIAS.md` and `docs/sources.csv` (URL, licence, date and sha256 for every dataset).

## Stack

Python, pandas, GeoPandas/GDAL, SQL + GeoPackage, OpenStreetMap routing, pytest, LLM tool calling.

## Team urbAIn

Felipe Salazar, Carlos Tesoriero, Luca Castagnet and Santiago Mariño.

Carlos's work: the data and access track (fire-station access, candidate sites and travel times), then the territorial priority module (buildings, vegetation and historical weather).

A web-app version for the MIT City Science Summit is in progress.
