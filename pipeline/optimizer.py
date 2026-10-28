"""flAIre optimizer - exhaustive search of extra preventive "retenes".

Given a travel-time matrix (existing stations + candidates x buildings), building
weights, a threshold, k_max and a strategy, enumerate every combination of
candidates of size 0..k_max (10 candidates, k<=6 -> 848 incl. empty) and return
the best combination per k with its metrics.

Rules implemented
- A building is a column of the matrix: counted once (duplicate ids rejected).
- Unroutable = NaN/inf time. Never dropped: counted in n_unroutable, never covered.
- Missing weight = NaN. Never treated as 0: excluded from weighted sums and
  reported in n_weight_missing.
- Times are travel estimates; threshold is a demo parameter.
- Strategy A: maximise weighted coverage (tie: covered count, worst time).
  Strategy B: lexicographic (fewest unroutable, lowest worst time, highest
  weighted coverage), then covered count.
- Best objective per k is non-decreasing in k (asserted; follows from the fact
  that adding an origin never worsens any building's best time).
- k_max must be <= number of valid candidates.

Weighting: 'historical_frequency' (weather weights from v_building_weight), 'none' (unweighted: weighted_* NULL) or
'uniform_pending_weather' (weight 1 for every building while weather weights are not available: weighted == count).

Changes 1.2.0 (linker, 2 Oct 2026): weighting 'uniform' (weight 1 for every building as a deliberate COMPARISON with the
weather-weighted run, now that weather weights exist; identical maths to 'uniform_pending_weather', which is kept for
backward compatibility). Schema v1.2 accepts it.

Changes 1.1.0 (linker, 1 Oct 2026): travel_times has a `profile` column (light|truck) -> load_from_gpkg filters it
(1.0.0 would have mixed both profiles); 'uniform_pending_weather' weighting; scenarios written with named columns
incl. profile; scenario id includes the profile.

Usage
  python optimizer.py run --db flaire.gpkg --data-version v1.0 --season JUL-AUG \
      --threshold 12 --k-max 6 --strategy A [--method ADV-v1] [--weighting none] [--profile light] [--write]
  python optimizer.py run-csv --times travel_times.csv --weights weights.csv ...
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

VERSION = "1.2.0"
EPS = 1e-9


# ----------------------------------------------------------------------------- core
@dataclass
class Problem:
    times: np.ndarray          # (n_origins, n_buildings) minutes; NaN/inf = unroutable
    origin_ids: list[str]
    candidate_ids: list[str]   # subset of origin_ids that may be selected
    building_ids: list[str]
    weights: np.ndarray | None = None   # (n_buildings,) NaN = missing; None = unweighted

    def __post_init__(self):
        t = np.asarray(self.times, dtype=float).copy()
        t[~np.isfinite(t)] = np.nan
        if t.ndim != 2 or t.shape != (len(self.origin_ids), len(self.building_ids)):
            raise ValueError("times shape must be (n_origins, n_buildings)")
        if (t[~np.isnan(t)] < 0).any():
            raise ValueError("negative travel time")
        if len(set(self.building_ids)) != len(self.building_ids):
            raise ValueError("duplicate building_id: each building must be counted once")
        if len(set(self.origin_ids)) != len(self.origin_ids):
            raise ValueError("duplicate origin_id")
        missing = set(self.candidate_ids) - set(self.origin_ids)
        if missing:
            raise ValueError(f"candidates not in origins: {sorted(missing)}")
        self.times = t
        idx = {o: i for i, o in enumerate(self.origin_ids)}
        self.cand_idx = [idx[c] for c in self.candidate_ids]
        self.station_idx = [i for i, o in enumerate(self.origin_ids) if o not in set(self.candidate_ids)]
        if self.weights is not None:
            w = np.asarray(self.weights, dtype=float)
            if w.shape != (len(self.building_ids),):
                raise ValueError("weights length must equal n_buildings")
            if (w[~np.isnan(w)] < 0).any():
                raise ValueError("negative weight")
            self.weights = w


@dataclass
class Evaluation:
    selection: tuple[str, ...]
    best_time: np.ndarray      # NaN = unroutable
    best_origin: np.ndarray    # index into origin_ids, -1 = unroutable
    covered: np.ndarray        # bool
    metrics: dict = field(default_factory=dict)


def _best_times(p: Problem, sel_idx: list[int]):
    rows = p.station_idx + list(sel_idx)
    n = p.times.shape[1]
    if not rows:
        return np.full(n, np.nan), np.full(n, -1)
    sub = p.times[rows]
    allnan = np.all(np.isnan(sub), axis=0)
    filled = np.where(np.isnan(sub), np.inf, sub)
    arg = np.argmin(filled, axis=0)
    best = filled[arg, np.arange(n)]
    best[allnan] = np.nan
    origin = np.asarray(rows)[arg]
    origin[allnan] = -1
    return best, origin


def evaluate(p: Problem, selection: tuple[str, ...], threshold: float) -> Evaluation:
    idx = {o: i for i, o in enumerate(p.origin_ids)}
    sel_idx = [idx[c] for c in selection]
    best, origin = _best_times(p, sel_idx)
    routable = ~np.isnan(best)
    covered = routable & (np.nan_to_num(best, nan=np.inf) <= threshold + EPS)
    n = len(best)
    m = {
        "k": len(selection),
        "selection": "|".join(sorted(selection)),
        "n_buildings": n,
        "n_covered": int(covered.sum()),
        "pct_covered": 100.0 * covered.sum() / n if n else 0.0,
        "n_unroutable": int((~routable).sum()),
        "worst_time_min_est": float(np.nanmax(best)) if routable.any() else None,
    }
    if p.weights is None:
        m.update(weighted_covered=None, weighted_total=None, weighted_share=None, n_weight_missing=0)
    else:
        known = ~np.isnan(p.weights)
        wt = float(p.weights[known].sum())
        wc = float(p.weights[known & covered].sum())
        m.update(weighted_covered=wc, weighted_total=wt,
                 weighted_share=(wc / wt) if wt > 0 else None,
                 n_weight_missing=int((~known).sum()))
    return Evaluation(tuple(sorted(selection)), best, origin, covered, m)


def objective_key(m: dict, strategy: str) -> tuple:
    """Smaller is better. Selection string is the final deterministic tie-break."""
    wc = m["weighted_covered"] if m["weighted_covered"] is not None else float(m["n_covered"])
    wc = round(wc, 9)
    worst = m["worst_time_min_est"] if m["worst_time_min_est"] is not None else math.inf
    worst = round(worst, 9)
    if strategy == "A":
        return (-wc, -m["n_covered"], worst)
    if strategy == "B":
        return (m["n_unroutable"], worst, -wc, -m["n_covered"])
    raise ValueError("strategy must be 'A' or 'B'")


def optimize(p: Problem, threshold: float, k_max: int, strategy: str, keep_all: bool = True) -> dict:
    if strategy not in ("A", "B"):
        raise ValueError("strategy must be 'A' or 'B'")
    if threshold <= 0:
        raise ValueError("threshold must be > 0")
    if not 0 <= k_max <= len(p.candidate_ids):
        raise ValueError(f"k_max={k_max} must be between 0 and n_valid_candidates={len(p.candidate_ids)}")
    cands = sorted(p.candidate_ids)
    best: dict[int, Evaluation] = {}
    ties: dict[int, int] = {}
    all_rows: list[dict] = []
    for k in range(k_max + 1):
        bucket = []
        for combo in itertools.combinations(cands, k):
            ev = evaluate(p, combo, threshold)
            key = objective_key(ev.metrics, strategy)
            bucket.append((key, ev.metrics["selection"], ev))
        bucket.sort(key=lambda r: (r[0], r[1]))
        top_key = bucket[0][0]
        ties[k] = sum(1 for r in bucket if r[0] == top_key)
        best[k] = bucket[0][2]
        if keep_all:
            for rank, (key, sel, ev) in enumerate(bucket, start=1):
                mm = {kk: ev.metrics[kk] for kk in ("selection", "k", "n_covered", "weighted_covered",
                                                    "worst_time_min_est", "n_unroutable")}
                mm["rank_in_k"] = rank
                all_rows.append(mm)
    # monotonicity guarantee
    for k in range(1, k_max + 1):
        if objective_key(best[k].metrics, strategy) > objective_key(best[k - 1].metrics, strategy):
            raise AssertionError(f"objective decreased from k={k-1} to k={k}")
    base = best[0].metrics
    per_k = []
    for k in range(k_max + 1):
        m = dict(best[k].metrics)
        m["gain_covered_vs_k0"] = m["n_covered"] - base["n_covered"]
        m["gain_weighted_vs_k0"] = (None if m["weighted_covered"] is None
                                    else m["weighted_covered"] - base["weighted_covered"])
        if k == 0:
            m["gain_covered_vs_prev"], m["nested_with_prev"] = None, None
        else:
            prev = best[k - 1]
            m["gain_covered_vs_prev"] = m["n_covered"] - prev.metrics["n_covered"]
            m["nested_with_prev"] = int(set(prev.selection) <= set(best[k].selection))
        m["ties"] = ties[k]
        per_k.append(m)
    return {"strategy": strategy, "threshold_min": threshold, "k_max": k_max,
            "n_candidates": len(cands), "n_combinations": sum(math.comb(len(cands), k) for k in range(k_max + 1)),
            "per_k": per_k, "best_eval": best, "all_combos": all_rows}


def buildings_gained(p: Problem, result: dict, k: int) -> dict:
    """Buildings newly covered by the best k-solution vs the best (k-1)-solution.
    Best solutions need not be nested, so 'lost' lists buildings covered at k-1 but not at k."""
    if k < 1:
        raise ValueError("k must be >= 1")
    a, b = result["best_eval"][k - 1], result["best_eval"][k]
    ids = np.asarray(p.building_ids)
    return {"k": k, "selection_prev": a.metrics["selection"], "selection": b.metrics["selection"],
            "gained": ids[b.covered & ~a.covered].tolist(),
            "lost": ids[a.covered & ~b.covered].tolist(),
            "still_out_routable": ids[~b.covered & ~np.isnan(b.best_time)].tolist(),
            "still_unroutable": ids[np.isnan(b.best_time)].tolist()}


def min_k_for_target(result: dict, target: float, metric: str = "pct_covered") -> dict:
    """Smallest k whose best solution reaches target (pct_covered in %, weighted_share in 0..1)."""
    if metric not in ("pct_covered", "weighted_share"):
        raise ValueError("metric must be pct_covered or weighted_share")
    for m in result["per_k"]:
        v = m[metric]
        if v is not None and v + EPS >= target:
            return {"reached": True, "k": m["k"], "selection": m["selection"], "value": v}
    vals = [m[metric] for m in result["per_k"] if m[metric] is not None]
    return {"reached": False, "k": None, "max_value": max(vals) if vals else None, "k_max_tested": result["k_max"]}


# ----------------------------------------------------------------------------- I/O
def load_from_gpkg(db: str, data_version: str, season: str, method_version: str | None,
                   weighting: str = "historical_frequency", speed_factor: float = 1.0,
                   profile: str = "light") -> Problem:
    if weighting not in ("historical_frequency", "none", "uniform", "uniform_pending_weather"):
        raise ValueError("weighting must be historical_frequency, none, uniform or uniform_pending_weather")
    if profile not in ("light", "truck"):
        raise ValueError("profile must be light or truck")
    con = sqlite3.connect(db)
    bids = [r[0] for r in con.execute("SELECT building_id FROM v_scope_buildings ORDER BY building_id")]
    stations = [r[0] for r in con.execute("SELECT origin_id FROM origins WHERE origin_type='station' ORDER BY origin_id")]
    cands = [r[0] for r in con.execute(
        "SELECT o.origin_id FROM origins o JOIN candidates c ON c.cand_id=o.origin_id "
        "WHERE c.is_valid=1 ORDER BY o.origin_id")]
    origins = stations + cands
    oi = {o: i for i, o in enumerate(origins)}
    bi = {b: j for j, b in enumerate(bids)}
    T = np.full((len(origins), len(bids)), np.nan)
    for o, b, mins in con.execute(
            "SELECT origin_id, building_id, minutes_est FROM travel_times WHERE data_version=? AND profile=? "
            "AND routable=1", (data_version, profile)):
        if o in oi and b in bi:
            T[oi[o], bi[b]] = mins / speed_factor
    w = None
    if weighting in ("uniform", "uniform_pending_weather"):
        w = np.ones(len(bids))
    elif weighting == "historical_frequency":
        w = np.full(len(bids), np.nan)
        for b, wt in con.execute(
                "SELECT building_id, weight FROM v_building_weight WHERE season_id=? AND method_version=? "
                "AND data_version=?", (season, method_version, data_version)):
            if b in bi and wt is not None:
                w[bi[b]] = wt
    con.close()
    return Problem(T, origins, cands, bids, w)


def write_to_gpkg(db: str, p: Problem, res: dict, scenario: dict) -> str:
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    profile = scenario.get("profile", "light")
    sf = scenario.get("speed_factor", 1.0)
    sid = scenario.get("scenario_id") or "S-{s}-{t:g}-{st}-{w}-{p}{f}-{dv}".format(
        s=scenario["season_id"], t=res["threshold_min"], st=res["strategy"], w=scenario["weighting"], p=profile,
        f="" if sf == 1.0 else f"-sf{sf:g}", dv=scenario["data_version"])
    with con:
        con.execute("INSERT INTO scenarios (scenario_id, season_id, threshold_min, k_max, strategy, weighting, "
                    "method_version, speed_factor, data_version, n_candidates, n_combinations, created_utc, "
                    "code_version, profile) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, scenario["season_id"], res["threshold_min"], res["k_max"], res["strategy"],
                     scenario["weighting"], scenario.get("method_version"), sf,
                     scenario["data_version"], res["n_candidates"], res["n_combinations"],
                     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), f"optimizer.py {VERSION}", profile))
        for m in res["per_k"]:
            con.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, m["k"], m["selection"], m["n_buildings"], m["n_covered"], m["pct_covered"],
                         m["weighted_covered"], m["weighted_total"], m["weighted_share"], m["n_weight_missing"],
                         m["worst_time_min_est"], m["n_unroutable"], m["gain_covered_vs_k0"],
                         m["gain_weighted_vs_k0"], m["gain_covered_vs_prev"], m["nested_with_prev"], m["ties"]))
            if m["selection"]:
                con.executemany("INSERT INTO result_selection VALUES (?,?,?)",
                                [(sid, m["k"], c) for c in m["selection"].split("|")])
            ev = res["best_eval"][m["k"]]
            rows = []
            for j, b in enumerate(p.building_ids):
                r = not np.isnan(ev.best_time[j])
                rows.append((sid, m["k"], b, p.origin_ids[ev.best_origin[j]] if r else None,
                             float(ev.best_time[j]) if r else None, int(r), int(ev.covered[j])))
            con.executemany("INSERT INTO result_building VALUES (?,?,?,?,?,?,?)", rows)
        con.executemany("INSERT INTO combo_metrics VALUES (?,?,?,?,?,?,?,?)",
                        [(sid, r["selection"], r["k"], r["n_covered"], r["weighted_covered"],
                          r["worst_time_min_est"], r["n_unroutable"], r["rank_in_k"]) for r in res["all_combos"]])
    con.close()
    return sid


def load_from_csv(times_csv: str, weights_csv: str | None, candidates: list[str]) -> Problem:
    """Long CSV: origin_id,building_id,minutes_est,routable (unroutable rows: empty minutes, routable=0).
    weights CSV: building_id,weight (empty = missing)."""
    import csv
    rows = list(csv.DictReader(open(times_csv, newline="", encoding="utf-8")))
    origins = sorted({r["origin_id"] for r in rows})
    bids = sorted({r["building_id"] for r in rows})
    oi = {o: i for i, o in enumerate(origins)}
    bi = {b: j for j, b in enumerate(bids)}
    T = np.full((len(origins), len(bids)), np.nan)
    for r in rows:
        if r["routable"] == "1" and r["minutes_est"] != "":
            T[oi[r["origin_id"]], bi[r["building_id"]]] = float(r["minutes_est"])
    w = None
    if weights_csv:
        w = np.full(len(bids), np.nan)
        for r in csv.DictReader(open(weights_csv, newline="", encoding="utf-8")):
            if r["building_id"] in bi and r["weight"] != "":
                w[bi[r["building_id"]]] = float(r["weight"])
    return Problem(T, origins, candidates, bids, w)


def summary_json(res: dict) -> str:
    return json.dumps({k: v for k, v in res.items() if k not in ("best_eval", "all_combos")},
                      indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "run-csv"):
        s = sub.add_parser(name)
        s.add_argument("--threshold", type=float, default=12.0)
        s.add_argument("--k-max", type=int, default=6)
        s.add_argument("--strategy", choices=["A", "B"], default="A")
        if name == "run":
            s.add_argument("--db", required=True)
            s.add_argument("--data-version", required=True)
            s.add_argument("--season", default="JUL-AUG")
            s.add_argument("--method", default=None)
            s.add_argument("--weighting", choices=["historical_frequency", "none", "uniform", "uniform_pending_weather"],
                           default="historical_frequency")
            s.add_argument("--speed-factor", type=float, default=1.0)
            s.add_argument("--profile", choices=["light", "truck"], default="light")
            s.add_argument("--write", action="store_true")
        else:
            s.add_argument("--times", required=True)
            s.add_argument("--weights")
            s.add_argument("--candidates", required=True, help="comma-separated CAND ids")
    a = ap.parse_args()
    if a.cmd == "run":
        p = load_from_gpkg(a.db, a.data_version, a.season, a.method, a.weighting, a.speed_factor, a.profile)
        res = optimize(p, a.threshold, a.k_max, a.strategy)
        if a.write:
            sid = write_to_gpkg(a.db, p, res, dict(season_id=a.season, weighting=a.weighting,
                                method_version=a.method, data_version=a.data_version,
                                speed_factor=a.speed_factor, threshold_min=a.threshold, strategy=a.strategy,
                                profile=a.profile))
            print("written scenario", sid)
    else:
        p = load_from_csv(a.times, a.weights, a.candidates.split(","))
        res = optimize(p, a.threshold, a.k_max, a.strategy)
    print(summary_json(res))


if __name__ == "__main__":
    main()
