# Data licences

The code is MIT (`LICENSE`). The data in this repository is not: it is derived from open datasets whose licences carry over.

| Data | Licence | Why |
|---|---|---|
| Travel times, candidate sites, scenarios and anything built on the road network: `agent/data/tiempos_ligero.csv`, `tiempos_camion.csv`, `candidatos.csv`, `escenarios.csv`, `parques.csv`, and the app tables built from them (`app/data/*.json`, `app/static/map.json`) | **ODbL 1.0** | Derived databases of OpenStreetMap. Keep the notice "© OpenStreetMap contributors" and share derived databases under ODbL. |
| Other team-produced tables, reports and docs: priority scores, weather summaries, `reports/`, `docs/`, `deck/` | **CC BY 4.0** | Keep the upstream attributions in `NOTICE.md`. |
| `app/static/hero.jpg` (photo by Joxemai, Wikimedia Commons) | **CC BY-SA 4.0** | The resized photo stays under the original licence; its credit is shown on the page. |
| Orthophotos (`reports/orthophotos/*.jpg`) and the forest background (`app/static/forest.jpg`) | Free use with attribution "Eusko Jaurlaritza / Gobierno Vasco" | geoEuskadi terms. |

Every source dataset, with URL, licence, download date and sha256, is in `reports/sources.csv`.

Not included on purpose: the past-fire perimeters from FireScope's "Previous Wildfires" viewer layer (scraped tiles, no explicit licence). The agent runs without them.
