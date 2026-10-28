#!/usr/bin/env python3
"""
flAIre · screen data for Tolosaldea today and with 1..3 crews (PLAN.md task 10.3, screens (a) and (b)).

    python 05_codigo/pipeline/export_tolosaldea.py

Reads only the delivered CSVs in 01_agente_plataforma/agent_final_data (light vehicle, 12 min, every building
weighted 1). For k = 1..3 it finds the best sites by exhaustive search over the 10 study sites. The best picks are
nested (02 -> 01+02 -> 01+02+03), so each crew has one gain: the buildings it brings under 12 min that the previous
step did not reach. The villages each crew rescues are counted from those buildings, not copied from the fichas.
Writes app/data/tolosaldea.json. Guarded by 05_codigo/tests_pipeline/test_tolosaldea_screens.py.
"""
import itertools
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DELIVERED = REPO / "agent" / "data"
APP_JSON = REPO / "app" / "data" / "tolosaldea.json"

TAG = "v0.3.1"
THRESHOLD_MIN = 12
MAX_K = 3


def best_pick(reach, today, cands, k):
    """Sorted ids of the k sites that cover the most buildings with the parks; fails on a tie."""
    scored = sorted(((int((today | reach[list(c)].any(axis=1)).sum()), list(c))
                     for c in itertools.combinations(cands, k)), key=lambda r: (-r[0], r[1]))
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise ValueError(f"k={k}: tie between {scored[0][1]} and {scored[1][1]}")
    return scored[0][1]


def minutes(x):
    return None if math.isnan(x) else round(float(x), 2)


def main():
    parks = pd.read_csv(DELIVERED / "parques.csv")
    parks = parks[parks.en_base == 1]
    sites = pd.read_csv(DELIVERED / "candidatos.csv")
    bld = pd.read_csv(DELIVERED / "edificios_prioridad.csv").set_index("building_id")
    T = pd.read_csv(DELIVERED / "tiempos_ligero.csv").set_index("building_id").reindex(bld.index)
    park_ids, cands = list(parks.origen_id), list(sites.origen_id)

    reach = T.fillna(np.inf) <= THRESHOLD_MIN + 1e-9
    today = reach[park_ids].any(axis=1)
    t_today = T[park_ids].min(axis=1)

    picks = [[]] + [best_pick(reach, today, cands, k) for k in range(1, MAX_K + 1)]
    for prev, cur in zip(picks, picks[1:]):
        if not set(prev) < set(cur):
            raise ValueError(f"picks are not nested: {prev} -> {cur}; per-crew gains are undefined")

    # Step at which each building first falls within 12 min (0 = today; NaN = never, up to MAX_K crews).
    step_of = pd.Series(np.nan, index=bld.index)
    step_of[today] = 0
    steps = []
    for k, pick in enumerate(picks):
        covered = today | reach[pick].any(axis=1) if pick else today
        step_of[covered & step_of.isna()] = k
        alta = bld.prioridad == "Alta"
        step = {"k": k, "pick": pick, "covered": int(covered.sum()),
                "pct_covered": round(100 * covered.sum() / len(bld), 1),
                "alta_covered": int((covered & alta).sum())}
        if k:
            added = (set(pick) - set(picks[k - 1])).pop()
            new = step_of == k
            villages = bld[new].groupby("municipio").size().sort_values(ascending=False)
            step |= {"added_site": added, "gain": int(new.sum()),
                     "villages_rescued": [{"municipality": m, "buildings": int(n)} for m, n in villages.items()]}
        steps.append(step)
        print(k, pick, step["covered"], "Alta", step["alta_covered"])

    t_final = T[park_ids + picks[-1]].min(axis=1)
    buildings = [{"id": bid, "lon": round(r.lon, 6), "lat": round(r.lat, 6), "municipality": r.municipio,
                  "priority": r.prioridad, "t_today_min": minutes(t_today[bid]), "t_final_min": minutes(t_final[bid]),
                  "covered_by_step": None if math.isnan(step_of[bid]) else int(step_of[bid]),
                  "rescued_by": steps[int(step_of[bid])]["added_site"] if step_of[bid] > 0 else None}
                 for bid, r in bld.iterrows()]

    out = {"meta": {"area": "tolosaldea", "generated": date.today().isoformat(), "data_version": TAG,
                    "profile": "light", "threshold_min": THRESHOLD_MIN, "n_buildings": len(bld),
                    "n_alta": int((bld.prioridad == "Alta").sum()),
                    "method": "Exhaustive search over the 10 study sites for k = 1..3 (every building weighted 1) on "
                              "the delivered light-vehicle times. The picks are nested, so each crew's gain is the "
                              "buildings it adds to the previous step.",
                    "limits": ["Estimated road travel times, not response times.",
                               "Study sites, not authorised sites.",
                               "Alta/Media/Baja is the team's priority class (REGLAS_prioridad.md), not an official "
                               "risk map.",
                               "Buildings with no route (t_today_min null) count as not covered."]},
           "parks": [{"id": p.origen_id, "name": p.nombre, "lon": p.lon, "lat": p.lat} for p in parks.itertuples()],
           "sites": [{"id": s.origen_id, "name": s.nombre, "municipality": s.municipio, "lon": s.lon, "lat": s.lat}
                     for s in sites.itertuples()],
           "steps": steps,
           "buildings": buildings}
    APP_JSON.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("wrote", APP_JSON, f"{APP_JSON.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
