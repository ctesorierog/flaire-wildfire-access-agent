#!/usr/bin/env python3
"""
flAIre · export today's coverage (9 DFG parks, no new crews) for a study area to the web app.

    python 05_codigo/pipeline/export_area_baseline.py --area gipuzkoa

Reads what the pipeline wrote for that area (official_layers.py + link_build.py --stages times):
  processed/<area>/buildings/buildings_analysis_set.csv, processed/<area>/links/travel_times_v0.3.1.parquet,
  processed/<area>/territory/territory.gpkg
Writes processed/<area>/baseline_buildings.csv (nearest + second-nearest park per building, light and truck) and
app/data/<area>_baseline.json (by municipality, comarca and park; totals; limits).
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent))
import area  # noqa: E402

AREA = area.current()
ROOT = Path(__file__).resolve().parents[1] / "work"
REPO = ROOT.parent
PROC = AREA.proc(ROOT)
APP_JSON = REPO / "app" / "data" / f"{AREA.tag}_baseline.json"
THRESHOLD_MIN = 12.0
TAG = "v0.3.1"


def nearest_two(A, T, prof, park_ids):
    """Nearest and second-nearest park per building from the wide minutes table T (parks x buildings)."""
    F = np.where(np.isnan(T), np.inf, T)
    order = np.argsort(F, axis=0)
    cols = np.arange(F.shape[1])
    t1, t2 = F[order[0], cols], F[order[1], cols]
    A[f"nearest_park_{prof}"] = np.where(np.isfinite(t1), park_ids[order[0]], None)
    A[f"t_nearest_{prof}"] = np.where(np.isfinite(t1), t1, np.nan)
    A[f"second_park_{prof}"] = np.where(np.isfinite(t2), park_ids[order[1]], None)
    A[f"t_second_{prof}"] = np.where(np.isfinite(t2), t2, np.nan)


def buildings_table():
    A = pd.read_csv(PROC / "buildings" / "buildings_analysis_set.csv", dtype={"muni_ine": str})
    TT = pd.read_parquet(PROC / "links" / f"travel_times_{TAG}.parquet", columns=["origin_id", "building_id", "profile", "minutes"])
    TT = TT.astype({"origin_id": str, "building_id": str, "profile": str})
    TT = TT[TT.origin_id.str.match(r"^(GIP|DON|OTH)-") & TT.building_id.isin(A.building_id)]
    for prof in ("light", "truck"):
        W = TT[TT.profile == prof].pivot(index="origin_id", columns="building_id", values="minutes").reindex(columns=A.building_id)
        nearest_two(A, W.values.astype(float), prof, W.index.values)
    return A.rename(columns={"nearest_park_light": "nearest_park", "second_park_light": "second_park"})


def summary(A):
    munis = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="municipalities_gipuzkoa")
    names = gpd.read_file(ROOT / "processed" / "network" / "fire_stations.gpkg").set_index("station_id")["name"]
    A = A.assign(in12=A.t_nearest_light <= THRESHOLD_MIN, two12=A.t_second_light <= THRESHOLD_MIN, unreach=A.t_nearest_light.isna())
    agg = A.groupby("muni_ine").agg(exposed_buildings=("building_id", "size"), within_12_min=("in12", "sum"),
                                    second_park_within_12_min=("two12", "sum"), no_route=("unreach", "sum"),
                                    dwellings=("dwellings", "sum"))
    m = munis[munis.ine_code.isin(AREA.codes)][["ine_code", "name", "comarca"]].merge(
        agg, left_on="ine_code", right_index=True, how="left").fillna(0).sort_values("ine_code")
    pct = lambda a, n: round(100 * a / n, 1) if n else None
    rows = [dict(ine_code=r["ine_code"], name=r["name"], comarca=r["comarca"], in_tolosaldea=r["ine_code"] in area.TOLOSALDEA,
                 exposed_buildings=int(r["exposed_buildings"]), within_12_min=int(r["within_12_min"]),
                 pct_within_12_min=pct(r["within_12_min"], r["exposed_buildings"]),
                 second_park_within_12_min=int(r["second_park_within_12_min"]), no_route=int(r["no_route"]),
                 dwellings=int(r["dwellings"])) for _, r in m.iterrows()]
    R = pd.DataFrame(rows)
    by_comarca = [dict(comarca=c, municipalities=len(d), exposed_buildings=int(d.exposed_buildings.sum()),
                       within_12_min=int(d.within_12_min.sum()), pct_within_12_min=pct(d.within_12_min.sum(), d.exposed_buildings.sum()))
                  for c, d in R.groupby("comarca")]
    by_comarca.sort(key=lambda d: (d["pct_within_12_min"] is None, d["pct_within_12_min"]))
    by_park = [dict(park_id=p, name=names[p], nearest_for_buildings=len(d), within_12_min=int(d.in12.sum()))
               for p, d in A.groupby("nearest_park")]
    n = len(A)
    return dict(
        meta=dict(area=AREA.tag, generated=str(date.today()), threshold_min=THRESHOLD_MIN, vehicle="light", data_version=TAG,
                  origins="9 Diputación fire parks (B5M); no Bizkaia, Navarra or Donostia-airport origins",
                  analysis_set="residential B5M buildings within 100 m of forest or scrub (Mapa Forestal 2024)",
                  limits=["Estimated road travel time, not response time (no turnout).",
                          "No stations outside Gipuzkoa: border municipalities can look worse than they are.",
                          "Buildings, not people: dwellings are given for context."],
                  script="pipeline/export_area_baseline.py"),
        totals=dict(exposed_buildings=n, within_12_min=int(A.in12.sum()), pct_within_12_min=pct(A.in12.sum(), n),
                    second_park_within_12_min=int(A.two12.sum()), no_route=int(A.unreach.sum())),
        by_comarca=by_comarca, by_park=by_park, municipalities=rows)


if __name__ == "__main__":
    A = buildings_table()
    A.to_csv(PROC / "baseline_buildings.csv", index=False)
    out = summary(A)
    APP_JSON.parent.mkdir(parents=True, exist_ok=True)
    APP_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {APP_JSON.relative_to(REPO)}:", out["totals"])
