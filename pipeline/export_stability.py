#!/usr/bin/env python3
"""
flAIre · stability table for the web app and slide 4 (PLAN.md task 10.2, audit item M3).

    python 05_codigo/pipeline/export_stability.py

For each threshold (10, 12, 15 min) and vehicle (light, truck), runs the exhaustive optimizer
(05_codigo/manager/optimizer.py) for k = 3 on the rebuilt Tolosaldea times and records the winning 3 sites, the
runner-up combination and the margin between them, in buildings. Every building is weighted 1, so this says nothing
about weightings. The 10-min light row also answers "what if travel times are 20 % longer?" (12 / 1.2 = 10; times scale
linearly with speed).

Reads processed/links/travel_times_v0.3.1.parquet (parks) and travel_times_pool_v0.3.1.parquet (candidate sites).
Pool ids differ between the delivered pool and the rebuild, so CAND-01..10 are matched to rebuilt sites by
position (agent_final_data/candidatos.csv vs processed/links/origin_snap_v0.3.1.parquet).
Writes app/data/stability.json. Guarded by 05_codigo/tests_pipeline/test_stability.py.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1] / "work"
REPO = ROOT.parent
sys.path.insert(0, str(Path(__file__).parent))
import optimizer as opt  # noqa: E402

TAG = "v0.3.1"
LINKS = ROOT / "processed" / "links"
TIMES = LINKS / f"travel_times_{TAG}.parquet"
POOL_TIMES = LINKS / f"travel_times_pool_{TAG}.parquet"
ORIGIN_SNAP = LINKS / f"origin_snap_{TAG}.parquet"
ANALYSIS_SET = ROOT / "processed" / "buildings" / "buildings_analysis_set.csv"
CANDIDATES = REPO / "agent" / "data" / "candidatos.csv"
APP_JSON = REPO / "app" / "data" / "stability.json"

# Fire parks in the baseline (OTH-HONDARRIBIA, the airport service, is excluded).
PARKS = ["DON-GARBERA", "GIP-ARRATE", "GIP-BIDASOA", "GIP-GOIERRI", "GIP-KOROSTI",
         "GIP-KOSTA", "GIP-ORIA", "GIP-UROLA", "GIP-ZUBILLAGA"]
THRESHOLDS = [10, 12, 15]
PROFILES = ["light", "truck"]
K = 3
MATCH_TOL_M = 5.0


def candidate_pool_ids():
    """CAND id -> rebuilt pool id, by nearest site position (EPSG:25830). Fails if any match is further than 5 m."""
    c = pd.read_csv(CANDIDATES)
    x, y = Transformer.from_crs(4326, 25830, always_xy=True).transform(c.lon.values, c.lat.values)
    pool = pd.read_parquet(ORIGIN_SNAP, columns=["origin_id", "origin_type", "x", "y"])
    pool = pool[pool.origin_type == "pool"]
    out = {}
    for cid, cx, cy in zip(c.origen_id, x, y):
        d = np.hypot(pool.x.values - cx, pool.y.values - cy)
        j = int(np.argmin(d))
        if d[j] > MATCH_TOL_M:
            raise ValueError(f"{cid}: nearest rebuilt site is {d[j]:.1f} m away")
        out[cid] = pool.origin_id.iloc[j]
    return out


def minutes_table(profile):
    """Wide table: analysis-set buildings x (parks + CAND-01..10), minutes; NaN = no route."""
    ids = pd.read_csv(ANALYSIS_SET).building_id
    pool_ids = candidate_pool_ids()
    cols = ["origin_id", "building_id", "profile", "minutes"]
    parks = pd.read_parquet(TIMES, columns=cols, filters=[("profile", "==", profile), ("origin_id", "in", PARKS)])
    cands = pd.read_parquet(POOL_TIMES, columns=cols,
                            filters=[("profile", "==", profile), ("origin_id", "in", list(pool_ids.values()))])
    cands["origin_id"] = cands.origin_id.map({p: c for c, p in pool_ids.items()})
    t = pd.concat([parks, cands])
    return t.pivot(index="building_id", columns="origin_id", values="minutes").reindex(
        index=ids, columns=PARKS + list(pool_ids))


def scenario(profile, threshold):
    W = minutes_table(profile)
    cands = [c for c in W.columns if c not in PARKS]
    p = opt.Problem(W.values.T, list(W.columns), cands, list(W.index))
    res = opt.optimize(p, threshold, K, "A", keep_all=True)
    ranked = [c for c in res["all_combos"] if c["k"] == K]       # best first
    best, second = ranked[0], ranked[1]
    n = res["per_k"][0]["n_buildings"]
    today = res["per_k"][0]["n_covered"]
    return {"profile": profile, "threshold_min": threshold,
            "today_covered": today, "today_pct": round(100 * today / n, 1),
            "pick": best["selection"].split("|"), "covered": best["n_covered"],
            "pct_covered": round(100 * best["n_covered"] / n, 1),
            "runner_up": second["selection"].split("|"), "runner_up_covered": second["n_covered"],
            "runner_up_ties": sum(1 for c in ranked if c["n_covered"] == second["n_covered"]),
            "margin": best["n_covered"] - second["n_covered"]}, n


def main():
    rows, n = [], None
    for profile in PROFILES:
        for th in THRESHOLDS:
            row, n = scenario(profile, th)
            rows.append(row)
            print(profile, th, row["pick"], row["covered"], "margin", row["margin"])
    out = {"meta": {"area": "tolosaldea", "generated": date.today().isoformat(), "data_version": TAG,
                    "n_buildings": n, "k": K,
                    "method": "Exhaustive search over all 120 combinations of 3 of the 10 study sites "
                              "(05_codigo/manager/optimizer.py, every building weighted 1).",
                    "limits": ["Estimated road travel times, not response times.",
                               "Study sites, not authorised sites.",
                               "Every building weighted 1: robustness across weightings is not shown.",
                               "Runner-up = second-best combination of 3 (runner_up_ties > 1: others share its "
                               "count); margin = buildings between them."]},
           "rows": rows}
    APP_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", APP_JSON)


if __name__ == "__main__":
    main()
