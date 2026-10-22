"""Tests for optimizer.py and schema.sql.  Run:  python -m pytest -q test_optimizer.py"""
import itertools
import math
import os
import sqlite3

import numpy as np
import pytest

import optimizer as opt

HERE = os.path.dirname(os.path.abspath(__file__))
CANDS = [f"CAND-{i:02d}" for i in range(1, 11)]
STATIONS = ["GIP-ORIA", "GIP-GOIERRI", "NAV-LEITZA"]


def synthetic(seed, n_b=300, p_unroutable=0.03, p_wmiss=0.05, dead_station=True):
    rng = np.random.default_rng(seed)
    origins = STATIONS + CANDS
    T = rng.gamma(4.0, 3.5, size=(len(origins), n_b))          # ~14 min mean
    T[rng.random(T.shape) < 0.05] = np.nan                     # pairwise unroutable
    dead = rng.random(n_b) < p_unroutable                      # buildings nobody reaches
    T[:, dead] = np.nan
    if dead_station:
        T[2, :] = np.nan                                       # Navarra station not routable
    w = rng.random(n_b)
    w[rng.random(n_b) < p_wmiss] = np.nan
    bids = [f"B{j:05d}" for j in range(n_b)]
    return opt.Problem(T, origins, CANDS, bids, w)


# ---------------------------------------------------------------- independent brute force
def brute(p, threshold, k_max, strategy):
    nb = len(p.building_ids)
    stations = [i for i, o in enumerate(p.origin_ids) if o not in CANDS]
    out = {}
    for k in range(k_max + 1):
        best = None
        for combo in itertools.combinations(sorted(CANDS), k):
            rows = stations + [p.origin_ids.index(c) for c in combo]
            cov = unr = 0
            worst = -1.0
            wc = 0.0
            for j in range(nb):
                ts = [p.times[r, j] for r in rows if not math.isnan(p.times[r, j])]
                if not ts:
                    unr += 1
                    continue
                t = min(ts)
                worst = max(worst, t)
                if t <= threshold + 1e-9:
                    cov += 1
                    if p.weights is not None and not math.isnan(p.weights[j]):
                        wc += p.weights[j]
            worst = worst if worst >= 0 else math.inf
            wcr = round(wc if p.weights is not None else cov, 9)
            key = (-wcr, -cov, round(worst, 9)) if strategy == "A" else (unr, round(worst, 9), -wcr, -cov)
            cand = (key, "|".join(combo), cov, unr)
            if best is None or cand[:2] < best[:2]:
                best = cand
        out[k] = best
    return out


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("strategy", ["A", "B"])
def test_matches_brute_force(seed, strategy):
    p = synthetic(seed, n_b=120)
    res = opt.optimize(p, 12.0, 4, strategy)
    bf = brute(p, 12.0, 4, strategy)
    for m in res["per_k"]:
        key, sel, cov, unr = bf[m["k"]]
        assert m["selection"] == sel
        assert m["n_covered"] == cov
        assert m["n_unroutable"] == unr
        assert opt.objective_key(m, strategy) == key


def test_848_combinations_and_full_run():
    p = synthetic(42, n_b=2000)
    res = opt.optimize(p, 12.0, 6, "A")
    assert res["n_combinations"] == 848
    assert len(res["all_combos"]) == 848
    assert sum(math.comb(10, k) for k in range(7)) == 848


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("strategy", ["A", "B"])
def test_monotone_in_k(seed, strategy):
    p = synthetic(100 + seed, n_b=200)
    res = opt.optimize(p, 10.0 + seed % 5, 6, strategy, keep_all=False)
    keys = [opt.objective_key(m, strategy) for m in res["per_k"]]
    assert all(keys[k] <= keys[k - 1] for k in range(1, len(keys)))
    for m in res["per_k"]:
        assert m["gain_covered_vs_k0"] >= 0 or strategy == "B"
        if strategy == "A":
            assert m["weighted_covered"] + 1e-9 >= res["per_k"][0]["weighted_covered"]


def test_building_counted_once():
    # every origin reaches every building within threshold -> covered must equal n, not n*origins
    n = 50
    origins = STATIONS + CANDS
    T = np.ones((len(origins), n))
    p = opt.Problem(T, origins, CANDS, [f"B{j}" for j in range(n)], np.ones(n))
    res = opt.optimize(p, 12, 6, "A", keep_all=False)
    for m in res["per_k"]:
        assert m["n_covered"] == n and m["weighted_covered"] == n and m["pct_covered"] == 100.0
    with pytest.raises(ValueError, match="counted once"):
        opt.Problem(T, origins, CANDS, ["B0"] * n, np.ones(n))


def test_unroutable_kept_and_missing_weight_not_zero():
    p = synthetic(7, n_b=100, p_unroutable=0.1, p_wmiss=0.2)
    dead = int(np.all(np.isnan(p.times), axis=0).sum())
    nmiss = int(np.isnan(p.weights).sum())
    res = opt.optimize(p, 12, 6, "A", keep_all=False)
    for m in res["per_k"]:
        assert m["n_buildings"] == 100                       # nobody dropped
        assert m["n_unroutable"] >= dead
        assert m["n_covered"] + m["n_unroutable"] <= 100
        assert m["n_weight_missing"] == nmiss
        assert abs(m["weighted_total"] - np.nansum(p.weights)) < 1e-9
    ev = res["best_eval"][6]
    assert np.all(np.isnan(ev.best_time[np.all(np.isnan(p.times), axis=0)]))
    assert not ev.covered[np.all(np.isnan(p.times), axis=0)].any()
    # all weights missing -> share is None (unknown), not 0
    p2 = opt.Problem(p.times, p.origin_ids, CANDS, p.building_ids, np.full(100, np.nan))
    assert opt.optimize(p2, 12, 1, "A", keep_all=False)["per_k"][0]["weighted_share"] is None


def test_strategy_b_prioritises_unroutable_then_worst():
    # 3 buildings. CAND-01 covers many cheaply (A), CAND-02 reaches the only otherwise-unroutable building (B)
    origins = ["GIP-ORIA", "CAND-01", "CAND-02"]
    nan = np.nan
    T = np.array([[20.0, 20.0, nan],
                  [5.0, 5.0, nan],
                  [25.0, 25.0, 30.0]])
    p = opt.Problem(T, origins, ["CAND-01", "CAND-02"], ["b1", "b2", "b3"], np.array([1.0, 1.0, 1.0]))
    a = opt.optimize(p, 12, 1, "A")["per_k"][1]
    b = opt.optimize(p, 12, 1, "B")["per_k"][1]
    assert a["selection"] == "CAND-01" and a["n_covered"] == 2 and a["n_unroutable"] == 1
    assert b["selection"] == "CAND-02" and b["n_unroutable"] == 0 and b["worst_time_min_est"] == 30.0


def test_kmax_limit_and_gained():
    p = synthetic(3, n_b=150)
    with pytest.raises(ValueError):
        opt.optimize(p, 12, 11, "A")
    res = opt.optimize(p, 12, 3, "A")
    g = opt.buildings_gained(p, res, 3)
    m2, m3 = res["per_k"][2], res["per_k"][3]
    assert len(g["gained"]) - len(g["lost"]) == m3["n_covered"] - m2["n_covered"]
    assert len(g["still_unroutable"]) == m3["n_unroutable"]
    assert len(g["gained"]) + len(g["still_out_routable"]) + len(g["still_unroutable"]) \
        + (m2["n_covered"] - len(g["lost"])) == 150
    t = opt.min_k_for_target(res, res["per_k"][2]["pct_covered"])
    assert t["reached"] and t["k"] <= 2
    assert not opt.min_k_for_target(res, 101.0)["reached"]


# ---------------------------------------------------------------- schema + integration
def make_db(tmp_path):
    db = str(tmp_path / "flaire.gpkg")
    con = sqlite3.connect(db)
    con.executescript(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    con.execute("PRAGMA foreign_keys=ON")
    return db, con


def seed_db(con, p, n_valid=10):
    sha = "0" * 64
    for sid in ("SRC-GIPA", "SRC-B5MBU", "SRC-OSM", "SRC-EUSK"):
        con.execute("INSERT INTO sources (source_id,title,organization,url,licence,download_date,raw_file,sha256) "
                    "VALUES (?,?,?,?,?,?,?,?)", (sid, sid, "org", "https://example.invalid", "CC BY 4.0",
                                                 "2026-10-02", "raw/x", sha))
    con.execute("INSERT INTO data_versions VALUES ('v0.9','2026-10-03T12:00:00Z',0,'test')")
    con.execute("INSERT INTO municipalities (ine_code,name,in_pilot,source_id) VALUES ('20071','Tolosa',1,'SRC-GIPA')")
    con.execute("INSERT INTO road_nodes (node_id,x,y,in_main_component) VALUES (1,0,0,1)")
    for j, b in enumerate(p.building_ids):
        con.execute("INSERT INTO buildings (building_id,source_id,source_use,dwellings,is_residential,residential_rule,"
                    "municipality_code,x,y,lon,lat,veg_distance_m,veg_rule_m,near_vegetation,node_id,snap_distance_m) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (b, "SRC-B5MBU", "1_residential", None if j % 7 == 0 else 2, 1, "use", "20071",
                     560000 + j, 4775000 + j, -2.07, 43.13, 10.0, 100.0, 1, 1, 5.0))
    con.execute("INSERT INTO profile_methods VALUES ('ADV-v1','threshold_rule','test','test',2018,2023,NULL)")
    con.execute("INSERT INTO weather_stations (station_id,name,lon,lat,native_timezone,in_pilot,source_id) "
                "VALUES ('C026','Berastegi',-1.98,43.12,'UTC',1,'SRC-EUSK')")
    con.execute("INSERT INTO weather_zones VALUES ('Z-C026','C026',NULL)")
    con.execute("INSERT INTO weather_profile VALUES ('Z-C026','JUL-AUG','ADV-v1',2018,2023,6,360,36,0.1,0.03,'v0.9')")
    con.executemany("INSERT INTO zone_assignment VALUES (?,?,?,?,?,?,?)",
                    [(b, "ADV-v1", "Z-C026", "C026", "nearest_station", 3.0, None) for b in p.building_ids])
    for o in p.origin_ids:
        if o.startswith("CAND"):
            i = int(o[-2:])
            con.execute("INSERT INTO candidates (cand_id,name,lon,lat,x,y,node_id,is_valid,status,source_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (o, o, -2.07, 43.13, 0, 0, 1,
                                                       int(i <= n_valid), "candidate" if i <= n_valid else "discarded",
                                                       "SRC-OSM"))
        else:
            con.execute("INSERT INTO fire_stations (station_id,name,operator,lon,lat,x,y,loc_confidence,node_id,routable,source_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (o, o, "Navarra" if o.startswith("NAV") else "DFG",
                                                         -2.07, 43.13, 0, 0, "address_street",
                                                         None if o.startswith("NAV") else 1,
                                                         0 if o.startswith("NAV") else 1, "SRC-OSM"))
        con.execute("INSERT INTO origins VALUES (?,?)", (o, "candidate" if o.startswith("CAND") else "station"))
    rows = []
    for i, o in enumerate(p.origin_ids):
        for j, b in enumerate(p.building_ids):
            t = p.times[i, j]
            if np.isnan(t):
                rows.append((o, b, None, None, 0, "disconnected_component", "v0.9"))
            else:
                rows.append((o, b, float(t), 1.0, 1, None, "v0.9"))
    con.executemany("INSERT INTO travel_times (origin_id,building_id,minutes_est,distance_km,routable,"
                    "unroutable_reason,data_version) VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()


def test_schema_end_to_end(tmp_path):
    p = synthetic(11, n_b=80)
    db, con = make_db(tmp_path)
    seed_db(con, p)
    for v in ("qa_scope_without_zone", "qa_missing_travel_pairs", "qa_duplicate_building_geom"):
        assert con.execute(f"SELECT count(*) FROM {v}").fetchone()[0] == 0, v
    q = opt.load_from_gpkg(db, "v0.9", "JUL-AUG", "ADV-v1")
    res = opt.optimize(q, 12, 6, "A")
    direct = opt.optimize(opt.Problem(p.times, p.origin_ids, CANDS, p.building_ids, np.full(80, 0.1)), 12, 6, "A")
    assert [m["selection"] for m in res["per_k"]] == [m["selection"] for m in direct["per_k"]]
    sid = opt.write_to_gpkg(db, q, res, dict(season_id="JUL-AUG", weighting="historical_frequency",
                                             method_version="ADV-v1", data_version="v0.9",
                                             threshold_min=12, strategy="A"))
    for v in ("qa_result_building_count", "qa_monotone_results"):
        assert con.execute(f"SELECT count(*) FROM {v}").fetchone()[0] == 0, v
    assert con.execute("SELECT count(*) FROM combo_metrics WHERE scenario_id=?", (sid,)).fetchone()[0] == 848
    # RULE R6: plan year is a label; same calculation cannot be stored twice
    con.execute("INSERT INTO plans VALUES ('PLAN-2027','2027','JUL-AUG',?,'Plan preventivo · Julio–agosto 2027')", (sid,))
    con.execute("INSERT INTO plans VALUES ('PLAN-2028','2028','JUL-AUG',?,'Plan preventivo · Julio–agosto 2028')", (sid,))
    con.commit()
    assert con.execute("SELECT count(DISTINCT scenario_id) FROM plans").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        opt.write_to_gpkg(db, q, res, dict(scenario_id="S-dup", season_id="JUL-AUG", weighting="historical_frequency",
                                           method_version="ADV-v1", data_version="v0.9"))
    con.close()


def test_schema_rejects_rule_violations(tmp_path):
    p = synthetic(12, n_b=10)
    db, con = make_db(tmp_path)
    seed_db(con, p, n_valid=4)
    bad = [
        # R1 missing != 0: value present but flagged missing / NULL value flagged valid
        "INSERT INTO weather_obs VALUES ('C026','2023-07-01T12:00:00Z','tair',0,'degC','missing','SRC-EUSK')",
        "INSERT INTO weather_obs VALUES ('C026','2023-07-01T12:00:00Z','tair',NULL,'degC','valid','SRC-EUSK')",
        # local time stamp rejected (must be UTC 'Z')
        "INSERT INTO weather_obs VALUES ('C026','2023-07-01 12:00','tair',20,'degC','valid','SRC-EUSK')",
        # wrong unit
        "INSERT INTO weather_obs VALUES ('C026','2023-07-01T12:00:00Z','wind_speed',3,'km/h','valid','SRC-EUSK')",
        # R2 duplicate building
        "INSERT INTO buildings (building_id,source_id,is_residential,residential_rule,municipality_code,x,y,lon,lat) "
        "VALUES ('B00000','SRC-B5MBU',1,'use','20071',1,1,-2.07,43.13)",
        # R3 unroutable with a time / routable without time
        "INSERT INTO travel_times (origin_id,building_id,minutes_est,distance_km,routable,unroutable_reason,data_version) "
        "VALUES ('CAND-01','B00000',999,NULL,0,'no_snap','v0.9')",
        # inconsistent near_vegetation flag
        "UPDATE buildings SET near_vegetation=1, veg_distance_m=500 WHERE building_id='B00001'",
        # frequency inconsistent with counts
        "UPDATE weather_profile SET adverse_day_frequency=0.5",
        # R8 FWI without a published source
        "INSERT INTO profile_methods VALUES ('FWI-x','official_fwi','x','x',2018,2023,NULL)",
        # R5 k_max > valid candidates (4 valid)
        "INSERT INTO scenarios (scenario_id,season_id,threshold_min,k_max,strategy,weighting,method_version,speed_factor,"
        "data_version,n_candidates,n_combinations,created_utc,code_version) "
        "VALUES ('S1','JUL-AUG',12,5,'A','none','ADV-v1',1.0,'v0.9',4,163,'t','c')",
        # candidate validated with pending checks
        "INSERT INTO candidate_checks VALUES ('CAND-01','water','pending',NULL,NULL,NULL)",
    ]
    for sql in bad[:-1]:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
    con.execute(bad[-1])
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE candidates SET status='validated' WHERE cand_id='CAND-01'")
    # dwellings NULL accepted (unknown), 0 accepted only as a real value
    assert con.execute("SELECT count(*) FROM buildings WHERE dwellings IS NULL").fetchone()[0] > 0
    con.close()


def test_gdal_reads_gpkg(tmp_path):
    pyogrio = pytest.importorskip("pyogrio")
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point
    db, con = make_db(tmp_path)
    p = synthetic(13, n_b=5)
    seed_db(con, p)
    con.close()
    layers = dict(pyogrio.list_layers(db))
    assert layers.get("buildings") == "Point" and "travel_times" in layers
    # append through GDAL into the constrained table
    g = gpd.GeoDataFrame({"building_id": ["NEW1"], "source_id": ["SRC-B5MBU"], "is_residential": [1],
                          "residential_rule": ["use"], "municipality_code": ["20071"], "x": [570000.0],
                          "y": [4780000.0], "lon": [-2.07], "lat": [43.13]},
                         geometry=[Point(570000, 4780000)], crs="EPSG:25830")
    g.to_file(db, layer="buildings", driver="GPKG", mode="a", engine="pyogrio")
    back = gpd.read_file(db, layer="buildings")
    assert "NEW1" in set(back.building_id) and back.crs.to_epsg() == 25830


# ---------------------------------------------------------------- v1.1 (linker) additions
def test_profile_filter_and_uniform_weights(tmp_path):
    p = synthetic(21, n_b=40)
    db, con = make_db(tmp_path)
    seed_db(con, p)
    # add a truck profile that is 2x slower: loading 'light' must not see it
    con.execute("INSERT INTO travel_times (origin_id,building_id,minutes_est,distance_km,routable,unroutable_reason,"
                "data_version,profile) SELECT origin_id,building_id,minutes_est*2,distance_km,routable,unroutable_reason,"
                "data_version,'truck' FROM travel_times")
    con.commit()
    q_l = opt.load_from_gpkg(db, "v0.9", "JUL-AUG", None, "uniform_pending_weather", profile="light")
    q_t = opt.load_from_gpkg(db, "v0.9", "JUL-AUG", None, "uniform_pending_weather", profile="truck")
    assert np.allclose(np.nan_to_num(q_t.times), np.nan_to_num(q_l.times * 2))
    res = opt.optimize(q_l, 12, 6, "A")
    for m in res["per_k"]:
        assert m["weighted_covered"] == m["n_covered"] and m["weighted_total"] == 40 and m["n_weight_missing"] == 0
    sid = opt.write_to_gpkg(db, q_l, res, dict(season_id="JUL-AUG", weighting="uniform_pending_weather",
                                               method_version=None, data_version="v0.9", profile="light"))
    assert "light" in sid
    assert con.execute("SELECT count(*) FROM qa_uniform_weight").fetchone()[0] == 0
    # same key again (other id) is rejected even with NULL method_version
    with pytest.raises(sqlite3.IntegrityError):
        opt.write_to_gpkg(db, q_l, res, dict(scenario_id="S-dup2", season_id="JUL-AUG", weighting="uniform_pending_weather",
                                             method_version=None, data_version="v0.9", profile="light"))
    # historical weighting without a method is rejected by the schema
    with pytest.raises(sqlite3.IntegrityError):
        opt.write_to_gpkg(db, q_l, res, dict(scenario_id="S-x", season_id="JUL-AUG", weighting="historical_frequency",
                                             method_version=None, data_version="v0.9", profile="truck"))
    con.close()
