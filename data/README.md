# Data folder

Small inputs the tests need, plus how to get the large layers that are not in this repository.

- `schema.sql`: the GeoPackage database schema (36 tables with rules built in).
- `priority/paso3_dias_riesgo.csv`, `priority/paso3_meteo_mensual.csv`: risk-weather days per station (2018–2023), read by `pipeline/export_weekly_calendar.py`.

## Large layers (not in the repo)

They are only needed to rebuild everything from raw data or to redraw the map background; the agent, the web app and the tests run without them.

| Layer | Download | Put it in |
|---|---|---|
| Mapa Forestal 2024 (vegetation) | https://www.geo.euskadi.eus/cartografia/DatosDescarga/Agricultura/INV_FORESTAL_2024_10000_ETRS89.zip | `work/raw/` |
| Municipal limits 1:5,000 | https://www.geo.euskadi.eus/cartografia/DatosDescarga/Limites/MUNICIPIOS_5000_ETRS89.zip | `work/raw/` |
| OpenStreetMap, País Vasco | https://download.geofabrik.de/europe/spain/pais-vasco-latest.osm.pbf | `work/raw/` |
| OpenStreetMap, Navarra | https://download.geofabrik.de/europe/spain/navarra-latest.osm.pbf | `work/raw/` |
| B5M buildings and fire stations | https://b5m.gipuzkoa.eus/datasets/GFA_INSPIRE_BU.gpkg and https://b5m.gipuzkoa.eus/web5000/es/api-rest/conjuntos-datos | `work/raw/` |
| Euskalmet readings 2018–2023 | Open Data Euskadi (URLs in `reports/sources.csv`) | `work/raw/` |

The exact files we used (dates and sha256) are in `reports/sources.csv`; newer downloads will move the numbers slightly.

## Rebuild order

The pipeline writes everything under `work/` (gitignored):

```bash
python pipeline/territory_buildings.py                    # ~40 s
python pipeline/network.py                                # ~2 min, ~4 GB RAM
python pipeline/official_layers.py forest proximity       # ~3 min
python pipeline/link_build.py --stages times              # ~17 min
```

Run `official_layers.py` with only the `forest proximity` steps: its full run needs `processed/candidates/candidates_10.csv`, which `link_build.py select` writes later (a known circular dependency).

`tests/test_rebuild_from_raw.py` then checks that the rebuild gives the same 3,331 buildings, 2,712 today and 3,187 with three crews. The map background (`app/static/forest.jpg`, `map.json`) is redrawn by `app/build_map.py`, which expects the vegetation layer and `flaire_lite.gpkg` in `data/external/`.
