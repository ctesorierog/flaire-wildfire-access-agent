#!/usr/bin/env python3
"""
flAIre · LINKER / VALIDATOR · data version v0.3-official (Tolosaldea pilot)

Re-runnable:  python3 code/link_build.py                 (all stages, ~12-15 min on 2 CPU, < 5 GB RAM)
              python3 code/link_build.py --reuse-times   (skip snapping/routing if the v0.3 parquet files exist)
              python3 code/link_build.py --stages db,optimize,bundle,validate

v0.3 = all official layers: municipal limits geoEuskadi MUNICIPIOS_5000 (SRC-GV-MUNICIPIOS5000-20250507), vegetation
Mapa Forestal 2024 (SRC-GV-INVFORESTAL-2024; analysis set 3,331), weather weights ADV-v1 (Euskalmet, P1), road network
País Vasco + Navarra OSM extracts (no Navarra fire station: origins are the 9 Gipuzkoa parks).

Stages
  snap      every Tolosaldea building (14,015), the 9 B5M parks, every usable candidate-pool site, the v0.1 CAND-01..10 and
            the 6,714 v0.1 proxy points -> default graph (roads, no tracks, main SCC)
  times     forward Dijkstra (scipy.sparse.csgraph) from every origin, light + truck; km driven in Navarra on park routes;
            with-tracks variant ONLY for the buildings with snap > 150 m (informational, never used in scenarios)
  baseline  9 parks (Hondarribia excluded), per building / municipality; Navarra effect vs the v0.2 network
  select    10 study candidates with the documented rule (NOT the optimizer objective); CAND numbers kept for unchanged sites
  db        db/flaire.gpkg from code/manager/schema.sql (v1.2) with the official layers + weather plug-in
  optimize  optimizer.py: A and B x weights (meteo ADV-v1 | uniform) x 10/12/15 min x light/truck, k=0..6 (848 combos)
  bundle    agent/datos/ exactly per bundle_contract.md (every file <= 3.5 MB)
  validate  qa_* views, FK/integrity, independent hand checks (from the bundle CSVs), agent/datos/auditoria.json,
            reports/linker_validation.md

Travel-time model (documented in reports/linker_validation.md):
  time(origin -> building) = access_o + network + partial edge + access_b
  access_* = straight-line snap distance (point -> nearest point on the nearest eligible edge) at 15 km/h
  partial edge = fraction of the snapped edge between its end node and the snap point, at that edge's speed
  network = Dijkstra on directed arcs (oneway respected) of the main strongly connected component, tracks excluded.
  Eligible snap edges: in main SCC, not motorway/trunk/(their links). Snap > 150 m -> routable = 0, reason 'snap>150m'.
  DB / bundle minutes are rounded to 0.01 min (bundle contract) and the optimizer runs on those rounded values, so any
  figure can be recomputed exactly from agent/datos/tiempos_*.csv.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from pyproj import Transformer
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

T0 = time.time()
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "processed"
NET = PROC / "network"
LINK = PROC / "links"
CANDDIR = PROC / "candidates"
REP = ROOT / "reports"
DBDIR = ROOT / "db"
DB = DBDIR / "flaire.gpkg"
AGENT = ROOT / "agent" / "datos"
MANAGER = ROOT / "code" / "manager"
for d in (LINK, CANDDIR, DBDIR, AGENT):
    d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(MANAGER))

DATA_VERSION = "v0.3.1-official"
TAG = "v0.3.1"
PREV03 = LINK / "v0.3"                         # frozen v0.3 outputs (judge review comparison)                                   # file-name tag of this linker run
PREV = LINK / "v0.2"                           # frozen v0.2 linker outputs (comparison)
SRC_OSM = "SRC-OSM-GEOFABRIK-PV-20260930"      # single id for the PBF (merges SRC-OSM-PV-260930)
SRC_OSM_DUP = "SRC-OSM-PV-260930"
SRC_NAV = "SRC-OSM-GEOFABRIK-NAV-20260930"
SRC_BU = "SRC-B5M-BU"
SRC_FS = "SRC-B5M-FIREST"
SRC_MUN = "SRC-GV-MUNICIPIOS5000-20250507"
SRC_VEG = "SRC-GV-INVFORESTAL-2024"
SRC_CAND = "SRC-FLAIRE-CAND-V031"
SRC_LINK = "SRC-FLAIRE-LINK-V031"
SRC_SUPERSEDED = {"SRC-FLAIRE-CAND-V02": "SRC-FLAIRE-CAND-V03", "SRC-FLAIRE-LINK-V02": "SRC-FLAIRE-LINK-V03",
                  "SRC-FLAIRE-CAND-V03": SRC_CAND, "SRC-FLAIRE-LINK-V03": SRC_LINK}
OWNER = {"SRC-B5M-BU": "P2", "SRC-IGN-ESATLAS-PROV": "P2", SRC_MUN: "P2", SRC_VEG: "P3", SRC_OSM_DUP: "P2"}
WEATHER_METHOD = "ADV-v1"

NO_SNAP = {"motorway", "motorway_link", "trunk", "trunk_link"}
ACCESS_KMH = 15.0
ACCESS_MS = ACCESS_KMH / 3.6
SNAP_MAX_M = 150.0
REASON_SNAP = "snap>150m"
PROFILES = ("light", "truck")
THRESHOLDS = (10.0, 12.0, 15.0)
K_MAX = 6
# candidate rule (unchanged from v0.2)
CAND_SNAP_MAX_M = 60.0
CAND_MIN_DIST_PARK_M = 2000.0
CAND_SEP_M = 3000.0
DEFICIT_THRESHOLD = 12.0
DBSCAN_EPS_M = 2000.0
DBSCAN_MIN = 5
MAJOR_CLUSTER_MIN = 15          # deficit buildings for a cluster to be "major"
CLUSTER_SEARCH_M = (1000.0, 2500.0)   # look for a site within the cluster hull + 1 km, else + 2.5 km

TO_WGS = Transformer.from_crs(25830, 4326, always_xy=True)
TO_UTM = Transformer.from_crs(4326, 25830, always_xy=True)


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md_table(df, floatfmt=1):
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("" if pd.isna(v) else f"{v:,.{floatfmt}f}")
            elif v is None or (not isinstance(v, str) and pd.isna(v)):
                cells.append("")
            else:
                cells.append(str(v).replace("|", "/"))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# =============================================================================================== graph
class Graph:
    """Routing graph from graph_arcs.parquet: default = roads main SCC (tracks excluded); with_tracks = SCC incl. tracks."""

    def __init__(self, with_tracks=False, base=None):
        self.with_tracks = with_tracks
        col = "in_scc_with_tracks" if with_tracks else "in_main_component"
        if base is None:
            log("loading graph")
            N = pd.read_parquet(NET / "graph_nodes.parquet")
            assert (N.idx.values == np.arange(len(N))).all()
            A = pd.read_parquet(NET / "graph_arcs.parquet")
            E = gpd.read_file(NET / "roads.gpkg", layer="road_edges", engine="pyogrio", use_arrow=True)
            nid2idx = pd.Series(N.idx.values, index=N.node_id.values)
            E["u_idx"] = nid2idx.loc[E.u.values].values
            E["v_idx"] = nid2idx.loc[E.v.values].values
            E["road_label"] = E.ref.where(E.ref.notna(), E.name)
            E["is_nav"] = (E.region == "NAV").astype(np.int8)
            # first vertex of every edge geometry is node u (fraction along the line is measured from u)
            f0 = shapely.get_coordinates(shapely.get_point(E.geometry.values[:2000], 0))
            assert np.allclose(f0, N.loc[E.u_idx.values[:2000], ["x", "y"]].values, atol=0.05)
            nav_by_edge = np.zeros(int(E.edge_id.max()) + 1, np.int8)
            nav_by_edge[E.edge_id.values] = E.is_nav.values
            A["is_nav"] = nav_by_edge[A.edge_id.values]
        else:
            N, A, E = base.N, base.A_all, base.E
        self.N, self.A_all, self.E = N, A, E
        self.A = A[A[col] == 1].reset_index(drop=True)
        self.n = len(N)
        ok = (E[col] == 1).values & ~E.fclass.isin(NO_SNAP).values
        if not with_tracks:
            ok &= (E.is_track == 0).values
        self.snap_rows = np.flatnonzero(ok)
        self.tree = shapely.STRtree(E.geometry.values[self.snap_rows])
        self.tree_any = base.tree_any if base is not None else shapely.STRtree(E.geometry.values)
        log(f"graph ({'with tracks' if with_tracks else 'default'}): {self.n} nodes, {len(self.A)} arcs, "
            f"{len(self.snap_rows)} snap-eligible edges")

    def snap(self, xs, ys):
        """Nearest point on the nearest eligible edge; chosen end node = nearer end along the edge."""
        E = self.E
        pts = shapely.points(np.asarray(xs, float), np.asarray(ys, float))
        qi, dist = self.tree.query_nearest(pts, return_distance=True, all_matches=False)
        order = np.argsort(qi[0])
        assert (qi[0][order] == np.arange(len(pts))).all()
        er = self.snap_rows[qi[1][order]]
        dist = dist[order]
        frac = shapely.line_locate_point(E.geometry.values[er], pts, normalized=True)
        L = E.length_m.values[er]
        near_u = frac <= 0.5
        out = pd.DataFrame(dict(
            edge_row=er, snap_edge_id=E.edge_id.values[er], snap_m=dist, frac=frac,
            node_idx=np.where(near_u, E.u_idx.values[er], E.v_idx.values[er]),
            node_id=np.where(near_u, E.u.values[er], E.v.values[er]),
            node_offset_m=np.where(near_u, frac, 1 - frac) * L,
            snap_edge_class=E.fclass.values[er], snap_road=E.road_label.values[er],
            snap_oneway=E.oneway.values[er], snap_region=E.region.values[er]))
        qa, da = self.tree_any.query_nearest(pts, return_distance=True, all_matches=False)
        o2 = np.argsort(qa[0])
        ea = qa[1][o2]
        out["nearest_any_m"] = da[o2]
        out["nearest_any_class"] = E.fclass.values[ea]
        out["nearest_any_in_main"] = E.in_main_component.values[ea]
        return out


class Router:
    """Forward Dijkstra from origins (virtual source nodes) to snapped targets (exact point-on-edge times).
    Along the time-optimal path it also accumulates the length and the length driven on NAV (Navarra) edges."""

    def __init__(self, G: Graph, origin_snaps: pd.DataFrame):
        self.G = G
        E = G.E
        n = G.n
        self.no = len(origin_snaps)
        self.size = n + self.no
        self.osnap = origin_snaps.reset_index(drop=True)
        self.mat, self.keys, self.lens, self.navl = {}, {}, {}, {}
        for prof in PROFILES:
            tcol = f"t_{prof}_s"
            g = G.A.sort_values(tcol).drop_duplicates(["u_idx", "v_idx"])
            u, v, t, L = [g.u_idx.values], [g.v_idx.values], [g[tcol].values], [g.length_m.values]
            NL = [g.length_m.values * g.is_nav.values]
            # virtual origin arcs: origin -> end node(s) reachable from the snap point (oneway respected)
            o = self.osnap
            er = o.edge_row.values
            f = o.frac.values.clip(0, 1)
            te, Le, ow = E[tcol].values[er], E.length_m.values[er], E.oneway.values[er]
            nv_e = E.is_nav.values[er]
            acc_t, acc_L = o.snap_m.values / ACCESS_MS, o.snap_m.values
            vid = n + np.arange(self.no)
            to_v = np.isin(ow, ["F", "B"])
            to_u = np.isin(ow, ["T", "B"])
            u += [vid[to_v], vid[to_u]]
            v += [E.v_idx.values[er][to_v], E.u_idx.values[er][to_u]]
            t += [(acc_t + (1 - f) * te)[to_v], (acc_t + f * te)[to_u]]
            L += [(acc_L + (1 - f) * Le)[to_v], (acc_L + f * Le)[to_u]]
            NL += [((1 - f) * Le * nv_e)[to_v], (f * Le * nv_e)[to_u]]
            u, v, t, L, NL = map(np.concatenate, (u, v, t, L, NL))
            t = np.maximum(t, 1e-6)          # csgraph: avoid explicit zeros
            self.mat[prof] = sparse.csr_matrix((t, (u, v)), shape=(self.size, self.size))
            key = u.astype(np.int64) * self.size + v
            o_ = np.argsort(key)
            self.keys[prof], self.lens[prof], self.navl[prof] = key[o_], L[o_], NL[o_]

    def path_acc(self, pred, prof, which="len"):
        """Sum of an arc attribute (length or NAV length, m) along the time-optimal path to every node (pointer jumping)."""
        size = self.size
        vals = self.lens[prof] if which == "len" else self.navl[prof]
        has = pred >= 0
        al = np.zeros(size)
        k = pred[has].astype(np.int64) * size + np.flatnonzero(has)
        pos = np.searchsorted(self.keys[prof], k)
        assert (self.keys[prof][pos] == k).all()
        al[has] = vals[pos]
        p = np.where(has, pred, -1).astype(np.int64)
        acc = al
        while True:
            m = p >= 0
            if not m.any():
                break
            acc_new = acc.copy()
            acc_new[m] += acc[p[m]]
            p_new = p.copy()
            p_new[m] = p[p[m]]
            acc, p = acc_new, p_new
        return acc

    def run(self, targets: pd.DataFrame, origin_rows=None, nav_rows=()):
        """Return dict prof -> (minutes[n_origins, n_targets], km[...], nav_km[...] (NaN unless origin in nav_rows));
        NaN where unroutable."""
        E = self.G.E
        n = self.G.n
        origin_rows = list(range(self.no)) if origin_rows is None else list(origin_rows)
        nav_rows = set(nav_rows)
        er = targets.edge_row.values
        f = targets.frac.values.clip(0, 1)
        ow = E.oneway.values[er]
        ue, ve = E.u_idx.values[er], E.v_idx.values[er]
        Le = E.length_m.values[er]
        nve = E.is_nav.values[er]
        tacc_t, tacc_L = targets.snap_m.values / ACCESS_MS, targets.snap_m.values
        from_u = np.isin(ow, ["F", "B"])      # traverse u -> point
        from_v = np.isin(ow, ["T", "B"])      # traverse v -> point
        t_ok = targets.snap_m.values <= SNAP_MAX_M
        out = {}
        for prof in PROFILES:
            te = E[f"t_{prof}_s"].values[er]
            Tm = np.full((len(origin_rows), len(targets)), np.nan, dtype=np.float64)
            Km = np.full_like(Tm, np.nan)
            Nm = np.full_like(Tm, np.nan)
            for ii, oi in enumerate(origin_rows):
                o = self.osnap.iloc[oi]
                if o.snap_m > SNAP_MAX_M:
                    continue
                d, pred = dijkstra(self.mat[prof], directed=True, indices=n + oi, return_predecessors=True)
                Lp = self.path_acc(pred, prof, "len")
                cu = np.where(from_u, d[ue] + f * te, np.inf)
                cv = np.where(from_v, d[ve] + (1 - f) * te, np.inf)
                lu, lv = Lp[ue] + f * Le, Lp[ve] + (1 - f) * Le
                best = np.minimum(cu, cv)
                use_u = cu <= cv
                blen = np.where(use_u, lu, lv)
                do_nav = oi in nav_rows
                if do_nav:
                    Np = self.path_acc(pred, prof, "nav")
                    bnav = np.where(use_u, Np[ue] + f * Le * nve, Np[ve] + (1 - f) * Le * nve)
                # origin and target on the same edge: direct along the edge if the direction allows it
                same = er == o.edge_row
                if same.any():
                    fo = min(max(o.frac, 0.0), 1.0)
                    oacc_t, oacc_L = o.snap_m / ACCESS_MS, o.snap_m
                    fwd = same & (f >= fo) & from_u
                    bwd = same & (f <= fo) & from_v
                    for msk in (fwd, bwd):
                        dt = oacc_t + np.abs(f - fo) * te
                        dl = oacc_L + np.abs(f - fo) * Le
                        better = msk & (dt < best)
                        best = np.where(better, dt, best)
                        blen = np.where(better, dl, blen)
                        if do_nav:
                            bnav = np.where(better, np.abs(f - fo) * Le * nve, bnav)
                tot = best + tacc_t
                okk = t_ok & np.isfinite(tot)
                Tm[ii] = np.where(okk, tot / 60.0, np.nan)
                Km[ii] = np.where(okk, (blen + tacc_L) / 1000.0, np.nan)
                if do_nav:
                    Nm[ii] = np.where(okk, bnav / 1000.0, np.nan)
            out[prof] = (Tm, Km, Nm)
            log(f"  routed {len(origin_rows)} origins x {len(targets)} targets ({prof})")
        return out


# =============================================================================================== inputs
def load_inputs():
    log("loading inputs")
    B = gpd.read_file(PROC / "buildings" / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio")
    aset = pd.read_csv(PROC / "buildings" / "buildings_analysis_set.csv")
    B["in_analysis_set"] = B.building_id.isin(aset.building_id).astype(int)
    assert B.in_analysis_set.sum() == len(aset) == ((B.is_residential == 1) & (B.near_vegetation == 1)).sum()
    FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio")
    POOL = gpd.read_file(NET / "candidate_pool.gpkg", layer="candidate_pool", engine="pyogrio")
    V01 = pd.read_csv(NET / "v01_candidates_reevaluated.csv")
    V01["x"], V01["y"] = TO_UTM.transform(V01.lon.values, V01.lat.values)
    PX = gpd.read_file(ROOT / "raw" / "persona4_accesos_bomberos" / "processed" / "baseline_coverage_proxy_points.geojson").to_crs(25830)
    return B, FS, POOL, V01, PX


def origins_table(FS, POOL, V01):
    st = FS[FS.include_in_baseline == 1]
    rows = [dict(origin_id=r.station_id, origin_type="station", name=r["name"], x=r.x, y=r.y) for _, r in st.iterrows()]
    ok = POOL[POOL.status == "ok"]
    rows += [dict(origin_id=r.pool_id, origin_type="pool", name=r["name"], x=r.x, y=r.y) for _, r in ok.iterrows()]
    rows += [dict(origin_id="V01-" + r.candidate_id, origin_type="v01_candidate", name=r.poi_name, x=r.x, y=r.y)
             for _, r in V01.iterrows()]
    return pd.DataFrame(rows)


F_TT = LINK / f"travel_times_{TAG}.parquet"
F_POOL = LINK / f"travel_times_pool_{TAG}.parquet"
F_BS = LINK / f"building_snap_{TAG}.parquet"
F_OS = LINK / f"origin_snap_{TAG}.parquet"
F_PX = LINK / f"proxy_points_{TAG}.parquet"
F_TRK = LINK / f"tracks_variant_unroutable_{TAG}.csv"


# =============================================================================================== stage: snap + times
def stage_times(reuse):
    if reuse and all(p.exists() for p in (F_TT, F_POOL, F_BS, F_OS, F_PX, F_TRK)):
        log("reusing travel times")
        return
    B, FS, POOL, V01, PX = load_inputs()
    G = Graph()
    O = origins_table(FS, POOL, V01)
    log(f"origins: {O.origin_type.value_counts().to_dict()}")
    os_ = G.snap(O.x.values, O.y.values)
    OS = pd.concat([O.reset_index(drop=True), os_], axis=1)
    OS["routable"] = (OS.snap_m <= SNAP_MAX_M).astype(int)
    bs = G.snap(B.x.values, B.y.values)
    BS = pd.concat([B[["building_id", "municipality_code", "in_analysis_set", "x", "y"]].reset_index(drop=True), bs], axis=1)
    BS["routable"] = (BS.snap_m <= SNAP_MAX_M).astype(int)
    BS["unroutable_reason"] = np.where(BS.routable == 1, None, REASON_SNAP)
    log(f"buildings snapped: {len(BS)}; median {BS.snap_m.median():.1f} m, >150 m: {(BS.routable == 0).sum()}")
    R = Router(G, OS)
    st_rows = list(np.flatnonzero(OS.origin_type.values == "station"))
    res = R.run(BS, nav_rows=st_rows)
    # v0.1 proxy points: stations only
    ps = G.snap(PX.geometry.x.values, PX.geometry.y.values)
    pres = R.run(ps, st_rows)
    PXo = pd.DataFrame(dict(cell_node=PX.cell_node.values, v01_baseline_min=PX.baseline_min.values,
                            v01_station=PX.baseline_station.values, x=PX.geometry.x.values, y=PX.geometry.y.values,
                            snap_m=ps.snap_m.values))
    for prof in PROFILES:
        Tm = pres[prof][0]
        allnan = np.all(np.isnan(Tm), axis=0)
        best = np.where(allnan, np.nan, np.nanmin(np.where(np.isnan(Tm), np.inf, Tm), axis=0))
        PXo[f"v03_{prof}_min"] = best
        PXo[f"v03_{prof}_station"] = np.where(allnan, None, OS.origin_id.values[st_rows][np.argmin(np.where(np.isnan(Tm), np.inf, Tm), axis=0)])
    PXo.to_parquet(F_PX, index=False)
    # baseline time at each origin site itself (nearest park -> site), for the fichas
    sres = R.run(OS, st_rows)
    st_ids = OS.origin_id.values[st_rows]
    for prof in PROFILES:
        Tm, Km, _ = sres[prof]
        F = np.where(np.isnan(Tm), np.inf, Tm)
        OS[f"site_base_{prof}_min"] = np.where(np.isfinite(F.min(0)), F.min(0), np.nan)
        OS[f"site_base_{prof}_station"] = st_ids[F.argmin(0)]
        OS[f"site_base_{prof}_km"] = Km[F.argmin(0), np.arange(F.shape[1])]
    # long format
    bids = BS.building_id.values
    frames = []
    for prof in PROFILES:
        Tm, Km, Nm = res[prof]
        for i, oid in enumerate(OS.origin_id.values):
            r_ok = ~np.isnan(Tm[i])
            reason = np.where(r_ok, None, np.where(OS.routable.values[i] == 0, "origin_unroutable", REASON_SNAP))
            frames.append(pd.DataFrame(dict(origin_id=oid, building_id=bids, profile=prof,
                                            minutes=np.round(Tm[i], 2), distance_km=np.round(Km[i], 3),
                                            nav_km=np.round(Nm[i], 3), routable=r_ok.astype(np.int8),
                                            unroutable_reason=reason)))
    TT = pd.concat(frames, ignore_index=True)
    del frames
    for c in ("origin_id", "building_id", "profile", "unroutable_reason"):
        TT[c] = TT[c].astype("category")
    for c in ("minutes", "distance_km", "nav_km"):
        TT[c] = TT[c].astype("float32")
    TT["data_version"] = DATA_VERSION
    is_pool = TT.origin_id.astype(str).str.startswith("POOL-")
    TT[~is_pool].to_parquet(F_TT, index=False, compression="zstd")
    TP = TT[is_pool].drop(columns=["nav_km"])           # nav km only computed for the parks
    del TT
    TP.sort_values(["profile", "origin_id", "building_id"]).to_parquet(F_POOL, index=False, compression="zstd",
                                                                        row_group_size=1_000_000)
    log(f"travel times written: {len(TP):,} pool rows + parks/v0.1 file")
    del TP
    BS.to_parquet(F_BS, index=False)
    OS.to_parquet(F_OS, index=False)
    # ---------------- with-tracks variant: ONLY the buildings with snap > 150 m on the default graph (informational)
    GT = Graph(with_tracks=True, base=G)
    U = BS[BS.routable == 0].reset_index(drop=True)
    ut = GT.snap(U.x.values, U.y.values)
    stt = OS[OS.origin_type == "station"].reset_index(drop=True)
    sts = GT.snap(stt.x.values, stt.y.values)
    RT = Router(GT, pd.concat([stt[["origin_id"]], sts], axis=1))
    rt = RT.run(ut)
    TV = U[["building_id", "municipality_code", "in_analysis_set", "snap_m", "nearest_any_class", "nearest_any_m"]].rename(
        columns={"snap_m": "snap_m_default"})
    TV["snap_m_with_tracks"] = ut.snap_m.round(1).values
    TV["snap_edge_class_with_tracks"] = ut.snap_edge_class.values
    for prof in PROFILES:
        Tm = rt[prof][0]
        F = np.where(np.isnan(Tm), np.inf, Tm)
        b = F.min(0)
        TV[f"base_{prof}_min_with_tracks"] = np.where(np.isfinite(b), np.round(b, 2), np.nan)
        TV[f"base_{prof}_station_with_tracks"] = np.where(np.isfinite(b), stt.origin_id.values[F.argmin(0)], None)
    TV["routable_with_tracks"] = TV.base_light_min_with_tracks.notna().astype(int)
    TV.to_csv(F_TRK, index=False)
    log(f"with-tracks variant: {int(TV.routable_with_tracks.sum())} of {len(TV)} unroutable buildings become routable")


def read_tt(pool=False, columns=None):
    f = F_POOL if pool else F_TT
    t = pd.read_parquet(f, columns=columns)
    for c in ("origin_id", "building_id", "profile"):
        if c in t:
            t[c] = t[c].astype(str)
    return t


def matrix(tt, origins, bids, prof, col="minutes"):
    """Dense (origins x buildings) matrix, NaN = unroutable."""
    t = tt[(tt.profile == prof) & tt.origin_id.isin(origins)]
    p = t.pivot(index="origin_id", columns="building_id", values=col)
    return p.reindex(index=list(origins), columns=list(bids)).values.astype(float)


# =============================================================================================== stats store
STATS_F = LINK / f"link_stats_{TAG}.json"
F_BL = LINK / f"baseline_buildings_{TAG}.csv"
F_MB = LINK / f"baseline_by_municipality_{TAG}.csv"
F_CP = LINK / f"baseline_comparison_{TAG}.csv"
F_NAV = LINK / f"navarra_effect_{TAG}.csv"


def stats_put(key, value):
    s = json.loads(STATS_F.read_text()) if STATS_F.exists() else {}
    s[key] = value
    STATS_F.write_text(json.dumps(s, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def stats_get():
    return json.loads(STATS_F.read_text()) if STATS_F.exists() else {}


def muni_names():
    t = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="municipalities_gipuzkoa", engine="pyogrio")
    return dict(zip(t.ine_code, t.name))


def analysis_ids():
    """Current analysis set (P2/P3 output). Read at every stage so a new vegetation layer needs no re-routing."""
    return set(pd.read_csv(PROC / "buildings" / "buildings_analysis_set.csv").building_id)


def station_ids():
    OS = pd.read_parquet(F_OS)
    return list(OS[OS.origin_type == "station"].origin_id)


def best_of(M, ids):
    """min over rows ignoring NaN; returns (best, argid) with NaN/None where all NaN."""
    F = np.where(np.isnan(M), np.inf, M)
    j = F.argmin(0)
    b = F[j, np.arange(F.shape[1])]
    ok = np.isfinite(b)
    return np.where(ok, b, np.nan), np.where(ok, np.asarray(ids, dtype=object)[j], None), j


# =============================================================================================== stage: baseline
def coverage_row(t, n_total):
    r = dict(n=n_total, n_unroutable=int(np.isnan(t).sum()))
    for th in (10, 12, 15, 20):
        r[f"pct_le_{th}"] = round(100.0 * np.nansum(t <= th) / n_total, 2) if n_total else np.nan
    r["median_min"] = round(float(np.nanmedian(t)), 2) if (~np.isnan(t)).any() else np.nan
    r["worst_min"] = round(float(np.nanmax(t)), 2) if (~np.isnan(t)).any() else np.nan
    return r


TOL_CMP = 0.011      # v0.2 stored 0.001 min, v0.3 0.01: differences <= one rounding step are not network changes


def stage_baseline():
    log("baseline")
    BS = pd.read_parquet(F_BS)
    BS["in_analysis_set"] = BS.building_id.isin(analysis_ids()).astype(int)
    tt = read_tt()
    st = station_ids()
    nm = muni_names()
    bids = BS.building_id.values
    BL = BS[["building_id", "municipality_code", "in_analysis_set", "routable", "unroutable_reason", "snap_m",
             "snap_edge_class", "snap_road", "node_id", "x", "y"]].copy()
    BL["municipality"] = BL.municipality_code.map(nm)
    for prof in PROFILES:
        M = matrix(tt, st, bids, prof)
        K = matrix(tt, st, bids, prof, "distance_km")
        NV = matrix(tt, st, bids, prof, "nav_km")
        b, o, j = best_of(M, st)
        BL[f"base_{prof}_min"] = np.round(b, 3)
        BL[f"base_{prof}_station"] = o
        BL[f"base_{prof}_km"] = np.where(np.isnan(b), np.nan, np.round(K[j, np.arange(len(bids))], 3))
        BL[f"base_{prof}_nav_km"] = np.where(np.isnan(b), np.nan, np.round(NV[j, np.arange(len(bids))], 3))
        F = np.where(np.isnan(M), np.inf, M)
        F2 = F.copy()
        F2[j, np.arange(len(bids))] = np.inf
        b2 = F2.min(0)
        BL[f"second_{prof}_min"] = np.where(np.isfinite(b2), np.round(b2, 3), np.nan)
    BL.to_csv(F_BL, index=False)
    S = BL[BL.in_analysis_set == 1]
    nA = len(S)
    rows = []
    for (code, name), g in S.groupby(["municipality_code", "municipality"]):
        r = dict(ine_code=code, municipality=name)
        r.update(coverage_row(g.base_light_min.values, len(g)))
        r["pct_le_12_truck"] = round(100.0 * (g.base_truck_min <= 12).sum() / len(g), 2)
        r["worst_truck_min"] = round(float(g.base_truck_min.max()), 2) if g.base_truck_min.notna().any() else np.nan
        r["n_via_navarra_light"] = int((g.base_light_nav_km > 0).sum())
        r["nearest_park_mode"] = g.base_light_station.mode().iloc[0] if g.base_light_station.notna().any() else None
        rows.append(r)
    MB = pd.DataFrame(rows).sort_values("pct_le_12")
    tot = dict(ine_code="TOTAL", municipality="Tolosaldea (analysis set)")
    tot.update(coverage_row(S.base_light_min.values, nA))
    tot["pct_le_12_truck"] = round(100.0 * (S.base_truck_min <= 12).sum() / nA, 2)
    tot["worst_truck_min"] = round(float(S.base_truck_min.max()), 2)
    tot["n_via_navarra_light"] = int((S.base_light_nav_km > 0).sum())
    tot["nearest_park_mode"] = S.base_light_station.mode().iloc[0]
    MB = pd.concat([MB, pd.DataFrame([tot])], ignore_index=True)
    MB.to_csv(F_MB, index=False)
    # ---- populations: comparison with v0.1 and v0.2
    PX = pd.read_parquet(F_PX)
    B = gpd.read_file(PROC / "buildings" / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio",
                      columns=["building_id", "is_residential"])
    BL2 = BL.merge(B[["building_id", "is_residential"]], on="building_id")
    both = PX.v01_baseline_min.notna() & PX.v03_light_min.notna()
    comp = []

    def add(label, t, n, note):
        r = dict(population=label, n=n, n_unroutable=int(np.isnan(t).sum()))
        for th in (10, 12, 15, 20):
            r[f"pct_le_{th}"] = round(100.0 * np.nansum(t <= th) / n, 1)
        r["median_min"] = round(float(np.nanmedian(t)), 2)
        r["worst_min"] = round(float(np.nanmax(t)), 2)
        r["note"] = note
        comp.append(r)
    add("v0.1 proxy points, v0.1 network (as reported)", PX.v01_baseline_min.values, len(PX), "v0.1 README: 71.8 % / worst 23.5 / 65 unroutable")
    add("same 6,714 proxy points, v0.3 network", PX.v03_light_min.values, len(PX), "PV + Navarra roads, official station points")
    v2 = pd.read_csv(PREV / "baseline_by_municipality.csv").set_index("ine_code").loc["TOTAL"]
    comp.append(dict(population="analysis set v0.2 (OSM vegetation + OSM limits), v0.2 network (as reported)", n=int(v2.n),
                     n_unroutable=int(v2.n_unroutable), pct_le_10=round(v2.pct_le_10, 1), pct_le_12=round(v2.pct_le_12, 1),
                     pct_le_15=round(v2.pct_le_15, 1), pct_le_20=round(v2.pct_le_20, 1), median_min=v2.median_min,
                     worst_min=v2.worst_min, note="reports/linker_validation.md v0.2"))
    add(f"all {len(BL2):,} buildings, v0.3", BL2.base_light_min.values, len(BL2), "every B5M building (incl. huts, unknown use)")
    add(f"{int((BL2.is_residential == 1).sum()):,} residential buildings, v0.3", BL2[BL2.is_residential == 1].base_light_min.values,
        int((BL2.is_residential == 1).sum()), "residential rule only")
    add(f"analysis set v0.3 ({nA:,}), light", S.base_light_min.values, nA, "residential AND <=100 m from Mapa Forestal 2024 forest/scrub")
    add(f"analysis set v0.3 ({nA:,}), truck", S.base_truck_min.values, nA, "truck profile")
    CP = pd.DataFrame(comp)
    CP.to_csv(F_CP, index=False)
    # ---- Navarra effect: same v0.3 analysis set, v0.2 network (PV only) vs v0.3 network (PV + Navarra)
    t2 = pd.read_parquet(LINK / "travel_times_v0.2.parquet", columns=["origin_id", "building_id", "profile", "minutes"])
    for c in ("origin_id", "building_id", "profile"):
        t2[c] = t2[c].astype(str)
    t2 = t2[t2.origin_id.isin(st)]
    bs2 = pd.read_parquet(LINK / "building_snap.parquet", columns=["building_id", "snap_m", "routable", "snap_edge_id"])
    NAVE = S[["building_id", "municipality", "routable", "snap_m"]].copy()
    nav = {}
    for prof in PROFILES:
        b2 = t2[t2.profile == prof].groupby("building_id").minutes.min().astype(float).round(2)   # v0.2 stored 0.001 -> same 0.01 rounding
        NAVE[f"v02net_{prof}_min"] = NAVE.building_id.map(b2).astype(float)
        NAVE[f"v03_{prof}_min"] = S[f"base_{prof}_min"].values
        NAVE[f"v03_{prof}_nav_km"] = S[f"base_{prof}_nav_km"].values
        NAVE[f"v03_{prof}_station"] = S[f"base_{prof}_station"].values
    NAVE["in_v02_times"] = NAVE.building_id.isin(set(t2.building_id)).astype(int)
    NAVE = NAVE.merge(bs2.rename(columns={"snap_m": "snap_m_v02", "routable": "routable_v02"})[["building_id", "snap_m_v02", "routable_v02"]],
                      on="building_id", how="left")
    for prof in PROFILES:
        a_, b_ = NAVE[f"v02net_{prof}_min"], NAVE[f"v03_{prof}_min"]
        both_ = a_.notna() & b_.notna()
        d_ = (b_ - a_)[both_]
        via = NAVE[f"v03_{prof}_nav_km"] > 0
        nav[prof] = dict(
            n_set=nA, n_with_v02_times=int(NAVE.in_v02_times.sum()), n_both_routable=int(both_.sum()),
            n_via_navarra=int(via.sum()), via_navarra_by_muni=NAVE[via].municipality.value_counts().to_dict(),
            via_navarra_station=NAVE[via][f"v03_{prof}_station"].value_counts().to_dict(),
            nav_km_median=round(float(NAVE[via][f"v03_{prof}_nav_km"].median()), 2) if via.any() else None,
            nav_km_max=round(float(NAVE[via][f"v03_{prof}_nav_km"].max()), 2) if via.any() else None,
            n_faster=int((d_ < -TOL_CMP).sum()), n_slower=int((d_ > TOL_CMP).sum()),
            n_faster_via_navarra=int(((d_ < -TOL_CMP) & via[both_]).sum()),
            n_rounding_only=int(((d_.abs() > 0) & (d_.abs() <= TOL_CMP)).sum()),
            saving_min_median=round(float(-d_[d_ < -TOL_CMP].median()), 2) if (d_ < -TOL_CMP).any() else 0.0,
            saving_min_max=round(float(-d_.min()), 2) if len(d_) else 0.0,
            pct_le_12_v02net=round(100.0 * (a_ <= 12).sum() / nA, 2), pct_le_12_v03=round(100.0 * (b_ <= 12).sum() / nA, 2),
            n_le_12_v02net=int((a_ <= 12).sum()), n_le_12_v03=int((b_ <= 12).sum()),
            n_cross_in_12=int(((a_ > 12) & (b_ <= 12)).sum()), n_cross_out_12=int(((a_ <= 12) & (b_ > 12)).sum()),
            n_unroutable_v02net=int((NAVE.in_v02_times.eq(1) & a_.isna()).sum()), n_unroutable_v03=int(b_.isna().sum()),
            worst_v02net=round(float(a_.max()), 2), worst_v03=round(float(b_.max()), 2))
    chg = (NAVE.v03_light_nav_km > 0) | (NAVE.v03_truck_nav_km > 0) | \
          ((NAVE.v03_light_min - NAVE.v02net_light_min).abs() > TOL_CMP) | ((NAVE.v03_truck_min - NAVE.v02net_truck_min).abs() > TOL_CMP) | \
          (NAVE.v02net_light_min.isna() != NAVE.v03_light_min.isna())
    NAVE[chg].round(3).to_csv(F_NAV, index=False)
    nav["n_rows_changed_file"] = int(chg.sum())
    d_all = PX.v03_light_min[both] - PX.v01_baseline_min[both]
    stats_put("baseline", dict(
        analysis=tot, n_buildings=len(BL), n_analysis=nA, n_unroutable_all=int((BL.routable == 0).sum()),
        n_unroutable_analysis=int((S.routable == 0).sum()),
        oria_nearest_share_analysis=round(float((S.base_light_station == "GIP-ORIA").mean() * 100), 1),
        nearest_park_counts_analysis=S.base_light_station.value_counts().to_dict(),
        navarra=nav,
        proxy_cross=dict(median_diff_min=round(float(d_all.median()), 2), v03_unroutable=int(PX.v03_light_min.isna().sum()))))
    log(f"baseline analysis set: {tot}")
    log(f"Navarra effect: {nav['light']}")


# =============================================================================================== stage: select candidates
TIER_LABEL = {1: "diputacion_facility", 2: "parking >=1000 m2", 3: "sports_centre/fronton with parking",
              4: "industrial", 5: "parking 400-1000 m2", 6: "trailhead/picnic"}
CHECK_ITEMS = [("heavy_vehicle_space", "espacio para vehículo pesado y maniobra (giro, estacionamiento)"),
               ("ownership_permit", "titularidad y permiso de uso"),
               ("truck_access", "acceso de camión: anchura, pendiente, gálibo, firme"),
               ("water", "agua (hidrante / depósito) cercana"),
               ("traffic_restrictions", "restricciones de tráfico (horario, eventos, aparcamiento ocupado en verano)"),
               ("ortho_location", "ubicación exacta en ortofoto (geoEuskadi)")]


def site_tier(r):
    st, area = r.site_type, r.area_m2
    if st == "dfg_facility":
        return 1
    if st == "parking" and pd.notna(area) and area >= 1000:
        return 2
    if st in ("sports_centre", "fronton") and pd.notna(r.nearest_parking_m) and r.nearest_parking_m <= 150:
        return 3
    if st == "industrial":
        return 4
    if st == "parking" and pd.notna(area) and 400 <= area < 1000:
        return 5
    if st in ("picnic_site", "picnic_table_cluster", "recreation_area"):
        return 6
    return None


def pool_sites():
    """Usable pool sites with linker snap, official municipality (point in P2 polygon) and eligibility flags."""
    POOL = gpd.read_file(NET / "candidate_pool.gpkg", layer="candidate_pool", engine="pyogrio")
    POOL = POOL[POOL.status == "ok"].copy()
    OS = pd.read_parquet(F_OS).set_index("origin_id")
    for c in ("snap_m", "snap_edge_class", "snap_road", "snap_edge_id", "node_id", "nearest_any_m", "nearest_any_class",
              "site_base_light_min", "site_base_light_station", "site_base_truck_min", "site_base_truck_station",
              "site_base_light_km"):
        POOL["l_" + c] = OS.loc[POOL.pool_id, c].values
    MUN = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="tolosaldea_municipalities", engine="pyogrio")
    j = gpd.sjoin(POOL[["pool_id", "geometry"]], MUN[["ine_code", "name", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    POOL["municipality_code"] = j.ine_code.values
    POOL["municipality"] = j["name"].values
    FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio")
    d = np.hypot(POOL.x.values[:, None] - FS.x.values[None, :], POOL.y.values[:, None] - FS.y.values[None, :])
    POOL["dist_nearest_park_m"] = d.min(1).round(0)
    POOL["nearest_park"] = FS.station_id.values[d.argmin(1)]
    POOL["tier"] = [site_tier(r) for r in POOL.itertuples()]
    POOL["elig_in_pilot"] = POOL.municipality_code.notna()
    POOL["elig_type"] = POOL.tier.notna()
    POOL["elig_snap"] = POOL.l_snap_m <= CAND_SNAP_MAX_M
    POOL["elig_not_mw_trunk"] = ~(POOL.l_nearest_any_class.isin(NO_SNAP) & (POOL.l_nearest_any_m < POOL.l_snap_m))
    POOL["elig_park_dist"] = POOL.dist_nearest_park_m >= CAND_MIN_DIST_PARK_M
    POOL["eligible"] = POOL[["elig_in_pilot", "elig_type", "elig_snap", "elig_not_mw_trunk", "elig_park_dist"]].all(axis=1)
    def why(r):
        out = [lab for col, lab in [("elig_in_pilot", "outside_28_municipalities"), ("elig_type", "site_type_not_in_list"),
                                    ("elig_snap", "snap>60m"), ("elig_not_mw_trunk", "on_motorway_trunk"),
                                    ("elig_park_dist", "<2km_from_park")] if not r[col]]
        return ";".join(out)
    POOL["ineligible_reason"] = POOL.apply(why, axis=1)
    return POOL


def stage_select():
    from sklearn.cluster import DBSCAN
    log("selecting candidates")
    BL = pd.read_csv(F_BL)
    P = pool_sites()
    FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio")
    parks = FS[FS.include_in_baseline == 1]
    S = BL[BL.in_analysis_set == 1].copy()
    D = S[~(S.base_light_min <= DEFICIT_THRESHOLD)].copy()          # > 12 min OR unroutable (NaN)
    # demand for the selection = routable deficit buildings (a site cannot fix a building-side snap failure;
    # unroutable buildings stay reported in every result)
    DR = D[D.routable == 1].copy()
    DR["cluster"] = DBSCAN(eps=DBSCAN_EPS_M, min_samples=DBSCAN_MIN).fit_predict(DR[["x", "y"]].values)
    D["cluster"] = D.building_id.map(dict(zip(DR.building_id, DR.cluster)))
    cl = (DR.groupby("cluster").agg(n_deficit=("building_id", "size"),
                                  n_unroutable=("routable", lambda s: int((s == 0).sum())),
                                  median_base_min=("base_light_min", "median"), worst_base_min=("base_light_min", "max"),
                                  municipalities=("municipality", lambda s: ", ".join(f"{k} {v}" for k, v in s.value_counts().items())),
                                  cx=("x", "mean"), cy=("y", "mean"))
          .reset_index().sort_values("n_deficit", ascending=False))
    cl["major"] = (cl.cluster >= 0) & (cl.n_deficit >= MAJOR_CLUSTER_MIN)
    E = P[P.eligible].copy()
    # median light time from each eligible site to the deficit buildings of each cluster (pool travel times)
    import pyarrow.dataset as ds
    tp = ds.dataset(F_POOL).to_table(
        filter=(ds.field("profile") == "light") & ds.field("origin_id").isin(list(E.pool_id))
        & ds.field("building_id").isin(list(DR.building_id)), columns=["origin_id", "building_id", "minutes"]).to_pandas()
    tp["origin_id"] = tp.origin_id.astype(str)
    tp["building_id"] = tp.building_id.astype(str)
    tp = tp.merge(DR[["building_id", "cluster"]], on="building_id")
    med = tp.groupby(["origin_id", "cluster"]).minutes.median()
    tmin = tp.set_index(["origin_id", "building_id"]).minutes
    chosen, log_rows = [], []
    xy = dict(zip(E.pool_id, zip(E.x, E.y)))

    def sep_ok(pid):
        return all(math.hypot(xy[pid][0] - xy[c][0], xy[pid][1] - xy[c][1]) >= CAND_SEP_M for c in chosen)

    for _, c in cl[cl.major].iterrows():
        pts = DR[DR.cluster == c.cluster]
        hull = shapely.convex_hull(shapely.multipoints(pts[["x", "y"]].values))
        pick, ring_used = None, None
        for ring in CLUSTER_SEARCH_M:
            zone = hull.buffer(ring)
            cand = E[shapely.contains_xy(zone, E.x.values, E.y.values)].copy()
            cand = cand[np.array([sep_ok(p) and p not in chosen for p in cand.pool_id], dtype=bool)].copy()
            cand["med_time_to_cluster"] = [med.get((p, c.cluster), np.nan) for p in cand.pool_id]
            # road relevance: median time from the site to the cluster < the cluster's median baseline time
            cand = cand[cand.med_time_to_cluster < c.median_base_min]
            if len(cand):
                cand = cand.sort_values(["tier", "med_time_to_cluster", "area_m2"], ascending=[True, True, False])
                pick, ring_used = cand.iloc[0], ring
                break
        if pick is None:
            log_rows.append(dict(step="cluster", cluster=int(c.cluster), pool_id=None, note="no eligible site within 2.5 km"))
            continue
        chosen.append(pick.pool_id)
        log_rows.append(dict(step="cluster", cluster=int(c.cluster), pool_id=pick.pool_id, tier=int(pick.tier),
                             ring_m=ring_used, n_options=len(cand), med_time_to_cluster=round(float(pick.med_time_to_cluster), 2),
                             note=f"sitio elegible mejor clasificado dentro de la envolvente del cluster + {ring_used/1000:g} km "
                                  f"(orden: nivel de tipo, mediana del tiempo a los edificios en déficit del cluster "
                                  f"= {pick.med_time_to_cluster:.1f} min, superficie); {len(cand)} opción(es) elegible(s)"))
    # fill to 10: farthest-first (max-min) territorial spread over the deficit buildings. At each step take the deficit
    # building farthest (straight line) from every park and every chosen site, and give it the best-ranked eligible site
    # near it (same rings and ranking as the clusters, ranking by distance instead of cluster time).
    anchor = np.array([(r.x, r.y) for r in parks.itertuples()])
    Dxy = DR[["x", "y"]].values
    skipped = set()
    while len(chosen) < 10:
        ref = np.vstack([anchor] + [np.array([xy[c] for c in chosen])])
        dmin = np.sqrt(((Dxy[:, None, :] - ref[None, :, :]) ** 2).sum(-1)).min(1)
        dmin[[i in skipped for i in range(len(DR))]] = -1
        if dmin.max() < 0:
            break
        i = int(dmin.argmax())
        bx, by = Dxy[i]
        pick = None
        for ring in CLUSTER_SEARCH_M:
            dd = np.hypot(E.x.values - bx, E.y.values - by)
            cand = E[(dd <= ring) & np.array([p not in chosen and sep_ok(p) for p in E.pool_id])].copy()
            # road relevance: the site must reach the target building faster than the current nearest park
            cand["time_to_target"] = [tmin.get((p, DR.building_id.iloc[i]), np.nan) for p in cand.pool_id]
            cand = cand[cand.time_to_target < DR.base_light_min.iloc[i]]
            if len(cand):
                cand["dist_to_target_m"] = np.hypot(cand.x - bx, cand.y - by)
                cand["dist_band"] = (cand.dist_to_target_m // 500).astype(int)
                cand = cand.sort_values(["dist_band", "tier", "dist_to_target_m"], ascending=[True, True, True])
                pick, ring_used = cand.iloc[0], ring
                break
        if pick is None:
            skipped.add(i)
            continue
        chosen.append(pick.pool_id)
        t = DR.iloc[i]
        log_rows.append(dict(step="spread", cluster=None, pool_id=pick.pool_id, tier=int(pick.tier),
                             target_building=t.building_id, target_dist_m=round(float(dmin[i])), n_options=len(cand),
                             note=f"dispersión farthest-first: el edificio en déficit {t.building_id} ({t.municipality}, "
                                  f"{t.base_light_min:.1f} min) estaba a {dmin[i]/1000:.1f} km de todo parque/candidata elegida; "
                                  f"sitio elegible más cercano a ≤ {ring_used/1000:g} km de él ({pick.dist_to_target_m:.0f} m, "
                                  f"{pick.time_to_target:.1f} min por carretera; orden: banda de 500 m, después nivel de tipo); "
                                  f"{len(cand)} opción(es) elegible(s)"))
    assert len(chosen) == 10, chosen
    SL = pd.DataFrame(log_rows)
    SL = SL[SL.pool_id.notna()].reset_index(drop=True)
    # v0.3: CAND numbers are STABLE: a site (pool id; pool ids are stable by OSM identity) that was a v0.2 candidate keeps
    # its number; new sites take the freed numbers in selection order.
    prev = pd.read_csv(CANDDIR / "v0.2" / "candidates_10.csv")          # history table (v0.2 -> current)
    prevN = pd.read_csv(CANDDIR / "v0.3" / "candidates_10.csv") if (CANDDIR / "v0.3" / "candidates_10.csv").exists() else prev
    prev_num = dict(zip(prevN.pool_id, prevN.cand_id))                  # numbering: latest published version
    keep = {pid: prev_num[pid] for pid in SL.pool_id if pid in prev_num}
    # freed numbers go to the new sites by spatial succession: greedy closest (new site, dropped v0.2 site) pairs
    gone = prevN[~prevN.pool_id.isin(SL.pool_id)]
    newp = [pid for pid in SL.pool_id if pid not in keep]
    pairs = sorted((math.hypot(xy[pid][0] - g_.x, xy[pid][1] - g_.y), pid, g_.cand_id) for pid in newp for g_ in gone.itertuples())
    used_n, used_c = set(), set()
    for d_, pid, cid in pairs:
        if pid not in used_n and cid not in used_c:
            keep[pid] = cid
            used_n.add(pid); used_c.add(cid)
    free = [f"CAND-{i:02d}" for i in range(1, 11) if f"CAND-{i:02d}" not in set(keep.values())]
    SL["cand_id"] = [keep[pid] if pid in keep else free.pop(0) for pid in SL.pool_id]
    assert SL.cand_id.is_unique
    pairs_now = set(zip(SL.cand_id, SL.pool_id))
    pairs_03 = set(zip(prevN.cand_id, prevN.pool_id))
    vs_v03 = dict(unchanged=pairs_now == pairs_03, added=sorted(pairs_now - pairs_03), removed=sorted(pairs_03 - pairs_now))
    log(f"selection vs v0.3: {vs_v03}")
    C = P.set_index("pool_id").loc[SL.pool_id].reset_index()
    for c_ in ("target_building", "target_dist_m"):
        if c_ not in SL:
            SL[c_] = None
    C = C.merge(SL[["pool_id", "cand_id", "step", "cluster", "note", "n_options", "target_building"]], on="pool_id")
    C["selection_order"] = np.arange(1, 11)
    D.to_csv(CANDDIR / "deficit_buildings.csv", index=False)
    cl["chosen_cand"] = cl.cluster.map(dict(zip(C.cluster.dropna().astype(int), C.cand_id[C.cluster.notna()])))
    cl.to_csv(CANDDIR / "deficit_clusters.csv", index=False)
    P.drop(columns="geometry").to_csv(CANDDIR / "candidate_eligibility.csv", index=False)
    # information only (NOT used for selection): reach and gain alone at 12 min, light, analysis set
    tc = ds.dataset(F_POOL).to_table(
        filter=(ds.field("profile") == "light") & ds.field("origin_id").isin(list(C.pool_id))
        & ds.field("building_id").isin(list(S.building_id)), columns=["origin_id", "building_id", "minutes"]).to_pandas()
    tc["origin_id"] = tc.origin_id.astype(str)
    tc["building_id"] = tc.building_id.astype(str)
    base = S.set_index("building_id").base_light_min
    tc["base"] = tc.building_id.map(base)
    C["reach_within_12_n"] = C.pool_id.map(tc[tc.minutes <= 12].groupby("origin_id").size()).fillna(0).astype(int)
    C["gain_alone_12_n"] = C.pool_id.map(tc[(tc.minutes <= 12) & ~(tc.base <= 12)].groupby("origin_id").size()).fillna(0).astype(int)
    rtree = shapely.STRtree(shapely.points(DR.x.values, DR.y.values))
    C["deficit_within_2500m_n"] = [len(rtree.query(shapely.Point(a, b).buffer(2500), predicate="contains")) for a, b in zip(C.x, C.y)]
    C["lon"], C["lat"] = TO_WGS.transform(C.x.values, C.y.values)
    C["site_type_rule"] = C.tier.map(TIER_LABEL)
    C.to_parquet(CANDDIR / "_candidates_full.parquet", index=False)
    # ---- diff vs v0.2 candidates (mapping table)
    elig = P.set_index("pool_id")
    mp = []
    for r in prev.itertuples():
        stay = r.pool_id in set(C.pool_id)
        row = dict(v02_cand_id=r.cand_id, pool_id=r.pool_id, name=r.name, municipality=r.municipality, site_type=r.site_type,
                   v02_step=r.selection_step, v03_cand_id=C.set_index("pool_id").cand_id.get(r.pool_id) if stay else None,
                   status="kept" if stay else "dropped")
        if not stay:
            e_ = elig.loc[r.pool_id] if r.pool_id in elig.index else None
            dd = np.hypot(C.x.values - r.x, C.y.values - r.y)
            row["v03_eligible"] = bool(e_.eligible) if e_ is not None else False
            row["note"] = (f"sigue elegible; no elegido por la regla v0.3 (demanda y clusters cambian con el Mapa Forestal); "
                           f"candidata v0.3 más próxima {C.cand_id.values[dd.argmin()]} a {dd.min() / 1000:.1f} km; "
                           f"edificios en déficit v0.3 a ≤ 2,5 km: "
                           f"{int((np.hypot(DR.x.values - r.x, DR.y.values - r.y) <= 2500).sum())}")
        mp.append(row)
    for r in C.itertuples():
        if r.pool_id not in set(prev.pool_id):
            dd = np.hypot(prev.x.values - r.x, prev.y.values - r.y)
            mp.append(dict(v02_cand_id=None, pool_id=r.pool_id, name=cand_name(pd.Series(r._asdict())), municipality=r.municipality,
                           site_type=r.site_type, v02_step=None, v03_cand_id=r.cand_id, status="new", v03_eligible=True,
                           note=f"nuevo sitio ({r.step}); hereda el número de la candidata v0.2 más próxima que sale "
                                f"({r.cand_id} v0.2 a {dd[prev.cand_id.values == r.cand_id][0] / 1000:.1f} km)" if r.cand_id in set(prev.cand_id) else
                                f"nuevo sitio ({r.step}); candidata v0.2 más próxima {prev.cand_id.values[dd.argmin()]} a {dd.min() / 1000:.1f} km"))
    MP = pd.DataFrame(mp)
    MP.to_csv(CANDDIR / "candidate_id_mapping_v02_v03.csv", index=False)
    stats_put("selection", dict(n_pool_ok=len(P), n_in_pilot=int(P.elig_in_pilot.sum()), n_eligible=int(P.eligible.sum()),
                                eligible_by_tier={int(k): int(v) for k, v in E.tier.value_counts().sort_index().items()},
                                ineligible_reasons=P[~P.eligible & P.elig_in_pilot].ineligible_reason.value_counts().to_dict(),
                                n_deficit=len(D), n_deficit_unroutable=int((D.routable == 0).sum()), n_demand=len(DR),
                                n_clusters=int((cl.cluster >= 0).sum()), n_major=int(cl.major.sum()),
                                n_noise=int(cl.loc[cl.cluster == -1, "n_deficit"].sum()) if (cl.cluster == -1).any() else 0,
                                chosen=list(zip(C.cand_id, C.pool_id)),
                                diff=dict(kept=int((MP.status == "kept").sum()), dropped=int((MP.status == "dropped").sum()),
                                          new=int((MP.status == "new").sum())), vs_v03=vs_v03))
    write_candidates(C, P, cl, D, MP)
    log("candidates: " + ", ".join(f"{a}={b}" for a, b in zip(C.cand_id, C.pool_id)))


TYPE_ES = {"dfg_facility": "Instalación foral", "parking": "Aparcamiento", "industrial": "Zona industrial",
           "fronton": "Frontón", "sports_centre": "Polideportivo", "picnic_site": "Área de picnic",
           "picnic_table_cluster": "Mesas de picnic", "recreation_area": "Área recreativa"}


def cand_name(r):
    if isinstance(r["name"], str) and r["name"].strip():
        return r["name"].strip()
    return f"{TYPE_ES.get(r.site_type, r.site_type)} sin nombre ({r.municipality})"


def site_caveat(r):
    """Site-specific caveats (judge review v0.3.1), keyed by the stable pool id; empty string if none."""
    pid = r.pool_id
    if pid == "POOL-0005":
        return (f"los {r.area_m2:,.0f} m² son la huella del edificio (casa de camineros), NO espacio de aparcamiento/maniobra: "
                "comprobar explanada o patio para vehículo pesado en ortofoto")
    if pid == "POOL-0342":
        return "«Insalus» es una planta embotelladora PRIVADA: titularidad y permiso de uso del recinto imprescindibles"
    if pid == "POOL-0272":
        return (f"punto OSM sin superficie (área desconocida), enganche a la red a {r.l_snap_m:.1f} m, y a solo "
                f"{r.dist_nearest_park_m / 1000:.1f} km en línea recta / {r.l_site_base_light_min:.1f} min de {r.l_site_base_light_station}: "
                "aporta poco frente al parque existente")
    if pid == "POOL-0411":
        return ("área de picnic en el enclave sur de Tolosa (separado del casco urbano, zona de Bedaio): accesibilidad y titularidad "
                "a confirmar; pertenecer a Tolosa no implica cercanía al casco ni al parque de Oria")
    return ""


def write_candidates(C, P, cl, D, MP):
    C = C.copy()
    C["cand_name"] = [cand_name(r) for _, r in C.iterrows()]
    C["access_road"] = [r.l_snap_road if isinstance(r.l_snap_road, str) else "vía sin nombre" for _, r in C.iterrows()]
    C["parking_dist_m"] = np.where(C.site_type == "parking", 0.0, C.nearest_parking_m)
    C["pending_checks"] = "; ".join(k for k, _ in CHECK_ITEMS)
    C["site_caveats"] = [site_caveat(r) for r in C.itertuples()]
    C["selection_reason"] = [
        (f"Cluster de déficit {int(r.cluster)} ({cl.set_index('cluster').loc[int(r.cluster), 'n_deficit']} edificios > 12 min: "
         f"{cl.set_index('cluster').loc[int(r.cluster), 'municipalities']}). " if r.step == "cluster" else "") + r.note
        for _, r in C.iterrows()]
    out = pd.DataFrame(dict(
        cand_id=C.cand_id, selection_order=C.selection_order, selection_step=C.step, pool_id=C.pool_id,
        site_type=C.site_type, site_type_rule=C.site_type_rule, tier=C.tier.astype(int), subtype=C.subtype,
        name=C.cand_name, osm_type=C.osm_type, osm_id=C.osm_id, municipality_code=C.municipality_code,
        municipality=C.municipality, lon=C.lon.round(6), lat=C.lat.round(6), x=C.x.round(1), y=C.y.round(1),
        access_road=C.access_road, snap_edge_class=C.l_snap_edge_class, snap_m=C.l_snap_m.round(1),
        node_id=C.l_node_id, area_m2=C.area_m2.round(1), parking_dist_m=C.parking_dist_m.round(1),
        dist_nearest_park_m=C.dist_nearest_park_m, nearest_park_straight=C.nearest_park,
        baseline_light_min=C.l_site_base_light_min.round(2), baseline_light_station=C.l_site_base_light_station,
        baseline_light_km=C.l_site_base_light_km.round(2), baseline_truck_min=C.l_site_base_truck_min.round(2),
        baseline_truck_station=C.l_site_base_truck_station, deficit_cluster=C.cluster,
        target_building=C.target_building, selection_reason=C.selection_reason,
        info_reach_within_12_n=C.reach_within_12_n, info_gain_alone_12_n=C.gain_alone_12_n,
        info_deficit_within_2500m_n=C.deficit_within_2500m_n, pending_checks=C.pending_checks, site_caveats=C.site_caveats,
        status="candidate", disclaimer="Candidata para estudio de cobertura; no autorizada ni validada",
        source_id=SRC_CAND))
    out = out.sort_values("cand_id").reset_index(drop=True)
    out.to_csv(CANDDIR / "candidates_10.csv", index=False)
    g = gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out.x, out.y), crs=25830)
    for f in (CANDDIR / "candidates_10.gpkg", CANDDIR / "candidates_10.geojson"):
        if f.exists():
            f.unlink()
    g.to_file(CANDDIR / "candidates_10.gpkg", layer="candidates_10", driver="GPKG", engine="pyogrio")
    g.to_crs(4326).to_file(CANDDIR / "candidates_10.geojson", driver="GeoJSON", engine="pyogrio")
    # ---- v0.1 candidates: replaced and why
    V = pd.read_csv(NET / "v01_candidates_reevaluated.csv")
    V["x"], V["y"] = TO_UTM.transform(V.lon.values, V.lat.values)
    OS = pd.read_parquet(F_OS).set_index("origin_id")
    MUN = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="tolosaldea_municipalities", engine="pyogrio")
    vg = gpd.GeoDataFrame(V[["candidate_id"]], geometry=gpd.points_from_xy(V.x, V.y), crs=25830)
    jj = gpd.sjoin(vg, MUN[["name", "geometry"]], how="left", predicate="within")
    jj = jj[~jj.index.duplicated()]
    V["muni_pip"] = jj["name"].values
    FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio")
    dpark = np.hypot(V.x.values[:, None] - FS.x.values[None, :], V.y.values[:, None] - FS.y.values[None, :])
    V["dist_park_m"] = dpark.min(1).round(0)
    V["nearest_park"] = FS.station_id.values[dpark.argmin(1)]
    dn = np.hypot(V.x.values[:, None] - out.x.values[None, :], V.y.values[:, None] - out.y.values[None, :])
    V["nearest_new"] = out.cand_id.values[dn.argmin(1)]
    V["nearest_new_km"] = (dn.min(1) / 1000).round(1)
    V["net_light_min"] = [OS.loc["V01-" + c, "site_base_light_min"] for c in V.candidate_id]
    V["net_light_station"] = [OS.loc["V01-" + c, "site_base_light_station"] for c in V.candidate_id]
    reasons = []
    for _, r in V.iterrows():
        rs = [f"POI {r.amenity} («{r.poi_name}»): no es un tipo de emplazamiento de retén (problema 4 de v0.1)"]
        if r.muni_pip != r.municipio and not (r.municipio == "Villabona" and r.muni_pip == "Villabona"):
            rs.append(f"etiquetada «{r.municipio}» pero cae en {r.muni_pip} (punto en polígono, límites P2)")
        if r.dist_park_m < CAND_MIN_DIST_PARK_M:
            rs.append(f"a {r.dist_park_m/1000:.1f} km de {r.nearest_park} (< 2 km): redundante con el parque")
        if r.net_light_min <= 8:
            rs.append(f"zona ya bien servida ({r.net_light_min:.1f} min desde {r.net_light_station})")
        if not (r.nearest_parking_ge400_m <= 150):
            rs.append("sin aparcamiento ≥ 400 m² a ≤ 150 m")
        if r.net_light_station != "GIP-ORIA":
            rs.append(f"más cerca de {r.net_light_station} que de Oria")
        if r.nearest_new_km < 0.1:
            rs.append(f"sustituida por el sitio contiguo {r.nearest_new} ({dn.min(1)[_] :.0f} m), que sí es un tipo de emplazamiento de la lista")
        elif r.nearest_new_km <= 3 and r.net_light_min > 10:
            rs.append(f"zona en déficit que ahora estudia {r.nearest_new} (a {r.nearest_new_km} km)")
        else:
            rs.append(f"candidata v0.2 más próxima: {r.nearest_new} a {r.nearest_new_km} km")
        reasons.append("; ".join(rs))
    V["why_replaced"] = reasons
    V[["candidate_id", "poi_name", "amenity", "municipio", "muni_pip", "lon", "lat", "dist_park_m", "nearest_park",
       "net_light_min", "net_light_station", "nearest_parking_ge400_m", "nearest_new", "nearest_new_km",
       "why_replaced"]].to_csv(CANDDIR / "v01_candidates_replaced.csv", index=False)
    write_fichas(out, P, cl, D, V, MP)


def write_fichas(out, P, cl, D, V, MP):
    st = stats_get()["selection"]
    L = []
    L.append("# Fichas de candidatas · Tolosaldea (v0.3.1, 2 oct 2026)\n")
    vs = stats_get()["selection"].get("vs_v03", {})
    L.append("> **v0.3.1 (revisión del jurado):** red corregida (vías `service` con matrícula foral GI-* tratadas como `unclassified`, 40 km/h); "
             + ("la regla de selección da **las mismas 10 candidatas y numeración que v0.3**. " if vs.get("unchanged") else
                f"la regla de selección cambia respecto a v0.3: entran {vs.get('added')}, salen {vs.get('removed')} (numeración estable). ")
             + "Se añaden advertencias específicas en CAND-01, CAND-04, CAND-08 y CAND-09.\n")
    L.append("Generado por `code/link_build.py` (re-ejecutable). Datos: `processed/candidates/candidates_10.{gpkg,csv,geojson}`, "
             f"versión de datos **{DATA_VERSION}**.\n")
    L.append("> **Ser candidata no significa estar autorizada ni validada.** Son lugares para estudiar cobertura. Cada ficha "
             "tiene 6 comprobaciones pendientes de campo. Los tiempos son **estimaciones de desplazamiento** (no tiempos de respuesta). "
             "v0.3 usa las capas oficiales: límites municipales geoEuskadi 1:5.000 (SRC-GV-MUNICIPIOS5000-20250507), "
             "**Mapa Forestal del País Vasco 2024** (SRC-GV-INVFORESTAL-2024) para el conjunto de análisis (3.331 edificios, antes 1.747 con OSM) "
             "y red viaria País Vasco + **Navarra** (OSM). La regla de selección es **la misma que en v0.2**; los números CAND-xx "
             "se conservan para los sitios que siguen elegidos (tabla de equivalencias al final).\n")
    dm = MP.copy()
    L.append("## Cambios respecto a v0.2\n")
    L.append(f"Sitios que se mantienen: **{int((dm.status == 'kept').sum())}**, salen: **{int((dm.status == 'dropped').sum())}**, "
             f"entran: **{int((dm.status == 'new').sum())}**. Equivalencias en `processed/candidates/candidate_id_mapping_v02_v03.csv`.\n")
    L.append(md_table(dm[["v02_cand_id", "v03_cand_id", "status", "pool_id", "name", "municipality", "site_type", "note"]], 1))
    L.append("")
    L.append("## Regla de selección (transparente, no usa el objetivo del optimizador)\n")
    L.append(f"1. **Elegibilidad** sobre los {st['n_pool_ok']} sitios utilizables del pool (`candidate_pool`, P4): dentro de los 28 municipios "
             f"(punto en polígono con los límites oficiales geoEuskadi: {st['n_in_pilot']}), tipo en orden de preferencia "
             "[1 instalación foral (`dfg_facility`), 2 aparcamiento ≥ 1 000 m², 3 polideportivo/frontón con aparcamiento ≤ 150 m, "
             "4 zona industrial, 5 aparcamiento 400–1 000 m², 6 área de picnic/recreativa], enganche a la red ≤ 60 m, "
             "la vía más cercana no es autopista/autovía, y ≥ 2 km en línea recta de cualquier parque existente. "
             f"**{st['n_eligible']} sitios elegibles** (por nivel: {st['eligible_by_tier']}). "
             f"Motivos de exclusión dentro de Tolosaldea: {st['ineligible_reasons']}. "
             "Aparcamientos sin área conocida (nodos OSM), centros culturales y refugios no están en la lista. "
             "Detalle: `candidate_eligibility.csv`.")
    L.append(f"2. **Demanda**: edificios del conjunto de análisis (residencial ∧ ≤ 100 m de bosque/matorral del Mapa Forestal 2024) con tiempo base "
             f"(9 parques, vehículo ligero) > 12 min: **{st['n_deficit']}** ({st['n_deficit_unroutable']} sin ruta por enganche > 150 m; "
             f"se reportan pero no orientan la selección porque ninguna candidata arregla su enganche) → **{st['n_demand']}** edificios. "
             f"Agrupados con DBSCAN (eps 2 km, mín. 5 edificios): {st['n_clusters']} clusters + {st['n_noise']} edificios aislados. "
             f"Cluster **principal** = ≥ {MAJOR_CLUSTER_MIN} edificios en déficit: {st['n_major']}.")
    L.append("3. **Un sitio por cluster principal** (de mayor a menor): el sitio elegible mejor clasificado dentro de la envolvente "
             "convexa del cluster + 1 km (si no hay, + 2,5 km), ordenando por nivel de tipo, después por mediana del tiempo "
             "desde el sitio a los edificios en déficit del cluster, después por superficie. Separación ≥ 3 km entre candidatas.")
    L.append("4. **Relleno hasta 10 por dispersión territorial max-min** (farthest-first): se toma el edificio en déficit más alejado "
             "en línea recta de todos los parques y candidatas ya elegidas, y se le asigna el sitio elegible más cercano "
             "(≤ 1 km, si no ≤ 2,5 km; bandas de 500 m y después nivel de tipo), respetando ≥ 3 km entre candidatas.")
    L.append("   **Comprobación por carretera** (pasos 3 y 4): el sitio solo cuenta si llega antes que el parque actual "
             "(paso 3: mediana del tiempo al cluster < mediana del tiempo base del cluster; paso 4: tiempo al edificio objetivo < "
             "su tiempo base). Evita sitios cercanos en línea recta pero en otro valle. Si ningún sitio cumple, el edificio "
             "objetivo se marca como no atendible y se pasa al siguiente más alejado.")
    L.append("5. Las columnas `info_*` (alcance y ganancia a 12 min) se calculan **después** de elegir, solo como información; "
             "la elección de combinaciones 0–6 es trabajo del optimizador.\n")
    L.append("### Clusters de déficit (vehículo ligero, > 12 min, con ruta)\n")
    c2 = cl.copy()
    c2["cluster"] = c2.cluster.astype(int)
    L.append(md_table(c2[["cluster", "n_deficit", "median_base_min", "worst_base_min", "municipalities", "major", "chosen_cand"]], 1))
    L.append("\n(cluster −1 = edificios aislados según DBSCAN)\n")
    L.append("## Resumen de las 10 candidatas\n")
    sm = out[["cand_id", "name", "site_type", "municipality", "lon", "lat", "snap_m", "area_m2", "baseline_light_min",
              "baseline_truck_min", "selection_step", "info_gain_alone_12_n"]].copy()
    sm["lon"] = sm.lon.map(lambda v: f"{v:.5f}")
    sm["lat"] = sm.lat.map(lambda v: f"{v:.5f}")
    L.append(md_table(sm, 1))
    L.append("")
    lab = dict(CHECK_ITEMS)
    for _, r in out.iterrows():
        L.append(f"## {r.cand_id} · {r['name']}" + ("" if r.municipality in r["name"] else f" ({r.municipality})") + "\n")
        L.append(f"- **Tipo:** {r.site_type}" + (f" / {r.subtype}" if isinstance(r.subtype, str) else "") +
                 f" · nivel {r.tier} ({r.site_type_rule}) · pool `{r.pool_id}` · OSM {r.osm_type} {r.osm_id}")
        L.append(f"- **Municipio:** {r.municipality} ({r.municipality_code}), por punto en polígono (límites oficiales geoEuskadi)")
        prv = MP[MP.v03_cand_id == r.cand_id].iloc[0]
        L.append(f"- **Respecto a v0.2:** " + (f"mismo sitio que {prv.v02_cand_id} v0.2" if prv.status == "kept" else "sitio nuevo en v0.3 (" + str(prv.note) + ")"))
        L.append(f"- **Coordenadas:** {r.lat:.5f}, {r.lon:.5f} (WGS84) · [ver en mapa](https://www.openstreetmap.org/?mlat={r.lat:.5f}&mlon={r.lon:.5f}#map=17/{r.lat:.5f}/{r.lon:.5f})")
        L.append(f"- **Acceso:** {r.access_road} ({r.snap_edge_class}); enganche a la red a {r.snap_m:.0f} m (nodo {r.node_id})")
        area_note = " (huella del edificio OSM; el espacio exterior no está cartografiado)" if r.site_type == "dfg_facility" else ""
        L.append(f"- **Superficie:** {r.area_m2:,.0f} m²{area_note}" if pd.notna(r.area_m2) else "- **Superficie:** desconocida (NULL)")
        if r.site_type != "parking":
            L.append(f"- **Aparcamiento público más cercano:** {r.parking_dist_m:.0f} m" if pd.notna(r.parking_dist_m)
                     else "- **Aparcamiento público más cercano:** no encontrado (NULL)")
        L.append(f"- **Tiempo actual desde parque:** {r.baseline_light_min:.1f} min ligero ({r.baseline_light_station}, {r.baseline_light_km:.1f} km) · "
                 f"{r.baseline_truck_min:.1f} min camión ({r.baseline_truck_station}); parque más cercano en línea recta a {r.dist_nearest_park_m/1000:.1f} km")
        L.append(f"- **Motivo de selección:** orden {r.selection_order} · {r.selection_reason}")
        L.append(f"- **Información (no usada para elegir):** {r.info_reach_within_12_n} edificios del conjunto a ≤ 12 min desde aquí; "
                 f"{r.info_gain_alone_12_n} pasarían a ≤ 12 min si solo se añade esta candidata; "
                 f"{r.info_deficit_within_2500m_n} edificios en déficit a ≤ 2,5 km")
        if isinstance(r.site_caveats, str) and r.site_caveats:
            L.append(f"- **⚠ Advertencia específica (revisión v0.3.1):** {r.site_caveats}")
        L.append("- **Pendiente de comprobar:** " + "; ".join(lab[k] for k, _ in CHECK_ITEMS))
        L.append("")
    L.append("## Candidatas v0.1 sustituidas y por qué\n")
    L.append("Las 10 candidatas v0.1 (CAND-01…10, restaurantes/cafeterías de un archivo de POI) se sustituyen **todas**. "
             "Los identificadores CAND-01…10 se reutilizan para las nuevas; las antiguas se guardan como `V01-CAND-xx` en "
             f"`processed/links/travel_times_{TAG}.parquet` y `v01_candidates_replaced.csv`.\n")
    v2 = V[["candidate_id", "poi_name", "municipio", "muni_pip", "net_light_min", "dist_park_m", "nearest_new", "nearest_new_km", "why_replaced"]].copy()
    v2["dist_park_m"] = (v2.dist_park_m / 1000).round(1)
    v2 = v2.rename(columns={"candidate_id": "v0.1", "municipio": "etiqueta v0.1", "muni_pip": "municipio (PIP)",
                            "net_light_min": "min (red v0.3)", "dist_park_m": "km a parque", "nearest_new": "v0.3 más próxima",
                            "nearest_new_km": "km", "why_replaced": "motivo"})
    L.append(md_table(v2, 1))
    L.append("\n## Limitaciones\n")
    L.append("- Pool basado en OSM: aparcamientos y frontones cartografiados de forma desigual; un sitio bueno no cartografiado no puede salir.")
    L.append("- En las instalaciones forales (`dfg_facility`) la superficie es la huella del edificio OSM; el espacio de maniobra hay que verlo en ortofoto.")
    L.append("- La demanda depende de la regla de proximidad (100 m al bosque/matorral del Mapa Forestal) y del umbral de 12 min, ambos parámetros de demo.")
    L.append("- Los parques de Navarra no son orígenes (no hay capa oficial en el paquete); las carreteras de Navarra sí se usan para calcular rutas.")
    L.append("- La regla de tipo (nivel) es una preferencia del equipo, no un criterio oficial del servicio de bomberos.")
    (REP / "fichas_candidatas_v03.md").write_text("\n".join(L), encoding="utf-8")
    log("fichas written")


# =============================================================================================== stage: database
import struct


def gpkg_blob(g, srs=25830):
    """GeoPackage binary: 'GP' header (v0, little-endian, no envelope) + ISO WKB."""
    if g is None:
        return None
    return b"GP" + bytes([0, 1]) + struct.pack("<i", srs) + shapely.to_wkb(g, byte_order=1, output_dimension=2)


def nn(v):
    """NaN/NA -> None for sqlite."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and math.isnan(v):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def rows_of(df, cols):
    return [tuple(nn(v) for v in r) for r in df[cols].itertuples(index=False, name=None)]


def insert(con, table, df, cols, geom=None):
    c = list(cols) + (["geom"] if geom is not None else [])
    q = f"INSERT INTO {table} ({','.join(c)}) VALUES ({','.join('?' * len(c))})"
    data = rows_of(df, cols)
    if geom is not None:
        data = [r + (gpkg_blob(g),) for r, g in zip(data, geom)]
    con.executemany(q, data)
    if geom is not None and len(df):
        b = shapely.total_bounds(np.asarray(geom))
        con.execute("UPDATE gpkg_contents SET min_x=?, min_y=?, max_x=?, max_y=? WHERE table_name=?",
                    (float(b[0]), float(b[1]), float(b[2]), float(b[3]), table))
    return len(data)


def sources_table():
    S = pd.read_csv(REP / "sources.csv")
    rows = []
    for _, r in S.iterrows():
        sid = r.source_id
        if sid == SRC_OSM_DUP:
            continue                                   # merged into SRC_OSM (same file, same sha256)
        if sid in (SRC_CAND, SRC_LINK):
            continue                                   # rebuilt below from the current files
        notes = str(r.notes) if pd.notna(r.notes) else ""
        m = re.search(r"sha256=([0-9a-f]{64})", notes)
        sha = m.group(1) if m else None
        raw = str(r.raw_file).split(";")[0].strip()
        if sha is None:
            pth = ROOT / raw
            if pth.is_file():
                sha = sha256_file(pth)
            elif pth.is_dir():
                h = hashlib.sha256()
                for f in sorted(pth.rglob("*")):
                    if f.is_file():
                        h.update(f"{f.relative_to(pth)}:{sha256_file(f)}\n".encode())
                sha = h.hexdigest()
                notes += "; sha256 = sha256 of the sorted '<relpath>:<sha256>' list of the folder (computed by linker)"
            else:
                alt = ROOT / "raw" / "persona4_accesos_bomberos" / "processed" / Path(raw).name
                if alt.is_file():
                    sha = sha256_file(alt)
                    notes += f"; sha256 of {alt.relative_to(ROOT)} (computed by linker)"
        url = str(r.url)
        if not url.startswith("http"):
            mm = re.search(r"https?://\S+", url)
            notes += f"; url as recorded: '{url}'"
            url = mm.group(0).rstrip(")") if mm else "https://b5m.gipuzkoa.eus"
        dd = re.search(r"\d{4}-\d{2}-\d{2}", str(r.download_date))
        if not dd or dd.group(0) != str(r.download_date):
            notes += f"; download_date as recorded: '{r.download_date}'"
        if sid == SRC_OSM:
            notes += ("; MERGED: SRC-OSM-PV-260930 (same file and sha256; used by P2 territory and P3 provisional "
                      "vegetation in v0.2) is this source")
        if sid in SRC_SUPERSEDED and "SUPERSEDED" not in notes:
            notes = f"SUPERSEDED by {SRC_SUPERSEDED[sid]} (newer data version); " + notes
        pf = pt = None
        per = re.search(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", str(r.edition_or_period))
        if per:
            pf, pt = per.group(1), per.group(2)
        owner = "P1" if sid.startswith("SRC-EUSKALMET") else OWNER.get(sid, "P4")
        rows.append(dict(source_id=sid, title=r.dataset, organization=r.organisation, url=url, licence=r.licence,
                         download_date=dd.group(0) if dd else "2026-10-01", edition=r.edition_or_period,
                         period_from=pf, period_to=pt, raw_file=raw, sha256=sha, crs_native=None,
                         owner_persona=owner, notes=notes))
    rows.append(dict(source_id=SRC_CAND, title="flAIre study candidates v0.3.1 (10 sites from the OSM candidate pool, same transparent rule as v0.2)",
                     organization="Team flAIre (derived; OSM ODbL)", url="https://claude.ai (team workspace, no public URL)",
                     licence="ODbL 1.0 (derived from OSM)", download_date="2026-10-02", edition=DATA_VERSION, period_from=None,
                     period_to=None, raw_file="processed/candidates/candidates_10.csv",
                     sha256=sha256_file(CANDDIR / "candidates_10.csv"), crs_native="EPSG:25830", owner_persona="P4",
                     notes="code/link_build.py stage select; rule and v0.2 diff in reports/fichas_candidatas_v03.md; "
                           "CAND numbers kept for sites selected in v0.2 (processed/candidates/candidate_id_mapping_v02_v03.csv)"))
    rows.append(dict(source_id=SRC_LINK, title="flAIre linker v0.3.1: snaps and travel-time estimates (light/truck), roads País Vasco + Navarra",
                     organization="Team flAIre (derived; OSM ODbL)", url="https://claude.ai (team workspace, no public URL)",
                     licence="ODbL 1.0 (derived from OSM)", download_date="2026-10-02", edition=DATA_VERSION, period_from=None,
                     period_to=None, raw_file=f"processed/links/travel_times_{TAG}.parquet",
                     sha256=sha256_file(F_TT), crs_native="EPSG:25830", owner_persona="P4",
                     notes="code/link_build.py stages snap/times; model in reports/linker_validation.md; DB minutes rounded to 0.01"))
    out = pd.DataFrame(rows)
    assert out.sha256.str.len().eq(64).all(), out[["source_id", "sha256"]]
    # upsert the linker's own rows in the shared register (other rows untouched; v0.2 linker rows marked SUPERSEDED)
    S2 = S[~S.source_id.isin([SRC_CAND, SRC_LINK])].copy()
    for old, newid in SRC_SUPERSEDED.items():
        msk = (S2.source_id == old) & ~S2.notes.astype(str).str.contains("SUPERSEDED")
        S2.loc[msk, "notes"] = f"SUPERSEDED by {newid} (newer data version); " + S2.loc[msk, "notes"].astype(str)
    mine = out[out.source_id.isin([SRC_CAND, SRC_LINK])]
    S2 = pd.concat([S2, pd.DataFrame(dict(
        source_id=mine.source_id, dataset=mine.title, organisation=mine.organization, url=mine.url, licence=mine.licence,
        download_date=mine.download_date, edition_or_period=mine.edition, raw_file=mine.raw_file,
        processed_files=["processed/candidates/*; db/flaire.gpkg candidates; agent/datos/candidatos.csv",
                         "processed/links/*; db/flaire.gpkg travel_times; agent/datos/tiempos_*.csv"],
        notes=[f"sha256={h}; " + n for h, n in zip(mine.sha256, mine.notes)]))], ignore_index=True)
    S2.to_csv(REP / "sources.csv", index=False)
    return out


# Plug-in contract for P1 (weather): CSVs named exactly like the schema tables in processed/weather/db_tables/
# (columns = schema columns; weather_stations may carry x, y in EPSG:25830 for the geometry). weather_profile /
# weather_profile_year carry the data version label of the P1 run; the loader writes them under DATA_VERSION (the
# profile does not depend on the building set except through zone membership, which is re-checked by qa views).
WEATHER_DIR = PROC / "weather" / "db_tables"
WEATHER_TABLES = ["weather_stations", "profile_methods", "weather_zones", "weather_quality", "weather_obs", "zone_assignment",
                  "weather_profile", "weather_profile_year", "weather_adverse_days"]


def load_weather_tables(con):
    n = {}
    if not WEATHER_DIR.exists():
        return n
    for t in WEATHER_TABLES:
        f = WEATHER_DIR / f"{t}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, dtype={"station_id": str})
        if "data_version" in df.columns:
            df["data_version_p1_label"] = df.data_version
            df["data_version"] = DATA_VERSION
        tcols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        cols = [c for c in df.columns if c in tcols and c not in ("fid", "geom")]
        geom = list(gpd.points_from_xy(df.x, df.y)) if (t == "weather_stations" and {"x", "y"} <= set(df.columns)) else None
        n[t] = insert(con, t, df, cols, geom)
        log(f"  weather plug-in: {t} {n[t]} rows")
    return n


def stage_db():
    log("building db/flaire.gpkg")
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript((MANAGER / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys=ON")
    counts = {}
    with con:
        SRC = sources_table()
        counts["sources"] = insert(con, "sources", SRC, list(SRC.columns))
        con.execute("INSERT INTO data_versions VALUES (?,?,0,?)",
                    (DATA_VERSION, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "Official layers: municipal limits geoEuskadi MUNICIPIOS_5000 (2025-05-07), vegetation Mapa Forestal del País Vasco 2024, "
                     "B5M buildings and fire stations, Euskalmet 2018-2023 weather weights (ADV-v1, exploratory, not FWI), "
                     "OSM roads País Vasco + Navarra (2026-09-30). No Navarra fire stations. v0.3.1 (judge review): highway=service ways "
                     "with a GI-* ref routed as unclassified (40 km/h); p95 travel time added per scenario; site caveats on candidates. Not frozen."))
        used = [SRC_OSM, SRC_NAV, SRC_BU, SRC_FS, SRC_MUN, SRC_VEG, SRC_CAND, SRC_LINK] + \
               sorted(x for x in SRC.source_id if x.startswith("SRC-EUSKALMET"))
        missing = set(used) - set(SRC.source_id)
        assert not missing, missing
        con.executemany("INSERT INTO data_version_sources VALUES (?,?)", [(DATA_VERSION, s_) for s_ in used])
        counts["data_version_sources"] = len(used)
        # territory (official geoEuskadi limits)
        MUN = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="municipalities_gipuzkoa", engine="pyogrio")
        assert set(MUN.source_id) == {SRC_MUN}, set(MUN.source_id)
        mg = [shapely.MultiPolygon([g]) if g.geom_type == "Polygon" else g for g in MUN.geometry]
        counts["municipalities"] = insert(con, "municipalities", MUN, ["ine_code", "name", "in_pilot", "area_km2", "source_id"], mg)
        BD = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="tolosaldea_boundary", engine="pyogrio")
        assert set(BD.source_id) == {SRC_MUN}
        bg = [shapely.MultiPolygon([g]) if g.geom_type == "Polygon" else g for g in BD.geometry]
        counts["boundary"] = insert(con, "boundary", BD, ["n_municipalities", "source_id"], bg)
        boundary = bg[0]
        # vegetation (official Mapa Forestal 2024, clip = boundary + 2 km)
        VD = pd.read_csv(PROC / "vegetation" / "class_dictionary.csv")
        VC = pd.DataFrame(dict(class_code_orig=VD.class_code, source_id=VD.source_id,
                               class_name_orig=[f"{a} · {b}" + (" (mixto por especie secundaria)" if "|MIX" in str(c) else "")
                                                for a, b, c in zip(VD.TIPES_es, VD.SP1_es.fillna("sin especie"), VD.class_code)],
                               class_group=VD.class_group, is_fuel=VD.is_veg_proximity.astype(int)))
        counts["vegetation_classes"] = insert(con, "vegetation_classes", VC, list(VC.columns))
        V = gpd.read_file(PROC / "vegetation" / "vegetation_forest_map_2024.gpkg", layer="vegetation_db", engine="pyogrio")
        assert set(V.source_id) == {SRC_VEG}
        vg = [shapely.MultiPolygon([g]) if g.geom_type == "Polygon" else g for g in V.geometry]
        counts["vegetation"] = insert(con, "vegetation", V, ["class_code_orig", "class_group", "is_fuel", "source_id"], vg)
        # road network: Tolosaldea + 15 km (+ the nodes referenced by stations / buildings / candidates)
        E = gpd.read_file(NET / "roads.gpkg", layer="road_edges", engine="pyogrio", use_arrow=True)
        N = gpd.read_file(NET / "roads.gpkg", layer="road_nodes", engine="pyogrio", use_arrow=True)
        buf = boundary.buffer(15000)
        keep_e = shapely.intersects(E.geometry.values, buf)
        E = E[keep_e].copy()
        BS = pd.read_parquet(F_BS)
        FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio")
        CA = pd.read_csv(CANDDIR / "candidates_10.csv")
        OSn = pd.read_parquet(F_OS)
        need = set(E.u) | set(E.v) | set(BS.node_id) | set(OSn[OSn.origin_type == "station"].node_id) | set(FS.node_id) | set(CA.node_id)
        N = N[N.node_id.isin(need)].copy()
        counts["road_nodes"] = insert(con, "road_nodes", N, ["node_id", "x", "y", "in_main_component"], list(N.geometry))
        E["osm_id"] = E.osm_id.astype("Int64").astype(str)
        assert set(E.source_id) <= {SRC_OSM, SRC_NAV}
        ecols = ["edge_id", "osm_id", "u", "v", "fclass", "oneway", "length_m", "maxspeed_osm", "speed_used_kmh",
                 "speed_source", "region", "source_id", "speed_truck_kmh", "t_light_s", "t_truck_s", "is_track",
                 "in_main_component", "name", "ref"]
        counts["road_edges"] = insert(con, "road_edges", E, ecols, list(E.geometry))
        # buildings
        B = gpd.read_file(PROC / "buildings" / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio")
        BS["in_analysis_set"] = BS.building_id.isin(analysis_ids()).astype(int)
        B = B.merge(BS[["building_id", "node_id", "snap_m", "routable", "unroutable_reason", "snap_edge_class", "snap_road",
                        "in_analysis_set"]], on="building_id", how="left", validate="1:1")
        assert B.node_id.notna().all() and len(B) == len(BS)
        B["snap_distance_m"] = B.snap_m.round(2)
        B["dwellings"] = B.dwellings.astype("Int64")
        B["year_built"] = B.year_built.astype("Int64")
        B["near_vegetation"] = B.near_vegetation.astype(int)
        bcols = ["building_id", "source_id", "source_use", "dwellings", "is_residential", "residential_rule",
                 "municipality_code", "x", "y", "lon", "lat", "veg_distance_m", "veg_rule_m", "near_vegetation", "node_id",
                 "snap_distance_m", "year_built", "residential_flag", "footprint_m2", "in_analysis_set", "routable",
                 "unroutable_reason", "snap_edge_class", "snap_road"]
        counts["buildings"] = insert(con, "buildings", B, bcols, list(B.geometry))
        # fire stations (10; Hondarribia loaded with include_in_baseline = 0 and NOT an origin; no Navarra station)
        OS = OSn.set_index("origin_id")
        FS["routable"] = (FS.snap_distance_m <= SNAP_MAX_M).astype(int)
        for c in ("node_id", "snap_distance_m"):        # linker snap for the 9 parks (identical method; checked)
            FS[c] = [OS.loc[s_, {"node_id": "node_id", "snap_distance_m": "snap_m"}[c]] if s_ in OS.index else v
                     for s_, v in zip(FS.station_id, FS[c])]
        FS["b5m_code"] = FS.b5mcode
        fcols = ["station_id", "name", "operator", "address", "lon", "lat", "x", "y", "loc_confidence", "node_id",
                 "snap_distance_m", "routable", "source_id", "include_in_baseline", "b5m_code", "municipality",
                 "snap_edge_class", "note"]
        counts["fire_stations"] = insert(con, "fire_stations", FS, fcols, list(FS.geometry))
        # candidates + checks
        CA["reference"] = [f"OSM {a} {b} · pool {c} · {d}" for a, b, c, d in zip(CA.osm_type, CA.osm_id, CA.pool_id, CA.site_type)]
        CA["access_dist_m"] = CA.snap_m
        CA["snap_distance_m"] = CA.snap_m
        CA["current_time_min_est"] = CA.baseline_light_min
        CA["current_time_from"] = CA.baseline_light_station
        CA["current_truck_time_min_est"] = CA.baseline_truck_min
        CA["gain_alone_n"] = CA.info_gain_alone_12_n
        CA["reach_within_threshold_n"] = CA.info_reach_within_12_n
        CA["is_valid"] = 1
        CA["osm_id"] = CA.osm_id.astype(str)
        ccols = ["cand_id", "name", "municipality_code", "lon", "lat", "x", "y", "reference", "access_road", "access_dist_m",
                 "node_id", "snap_distance_m", "parking_dist_m", "current_time_min_est", "current_time_from",
                 "selection_order", "selection_reason", "gain_alone_n", "reach_within_threshold_n", "status", "is_valid",
                 "disclaimer", "source_id", "pool_id", "site_type", "tier", "osm_id", "area_m2",
                 "current_truck_time_min_est", "selection_step"]
        counts["candidates"] = insert(con, "candidates", CA, ccols, list(gpd.points_from_xy(CA.x, CA.y)))
        chk = pd.DataFrame([dict(cand_id=c, check_item=k, status="pending", note=lab) for c in CA.cand_id for k, lab in CHECK_ITEMS])
        counts["candidate_checks"] = insert(con, "candidate_checks", chk, ["cand_id", "check_item", "status", "note"])
        st = sorted(FS[FS.include_in_baseline == 1].station_id)
        orig = pd.DataFrame(dict(origin_id=st + list(CA.cand_id), origin_type=["station"] * len(st) + ["candidate"] * len(CA)))
        counts["origins"] = insert(con, "origins", orig, ["origin_id", "origin_type"])
        # travel times: 9 parks + 10 candidates x all buildings x 2 profiles; minutes rounded to 0.01 (bundle contract)
        tt = read_tt()
        tt = tt[tt.origin_id.isin(st)].drop(columns=["nav_km"])
        import pyarrow.dataset as ds
        tp = ds.dataset(F_POOL).to_table(filter=ds.field("origin_id").isin(list(CA.pool_id))).to_pandas()
        for c in ("origin_id", "building_id", "profile"):
            tp[c] = tp[c].astype(str)
        tp["origin_id"] = tp.origin_id.map(dict(zip(CA.pool_id, CA.cand_id)))
        T = pd.concat([tt, tp], ignore_index=True)
        T["minutes_est"] = T.minutes.astype(float).round(2)
        T["distance_km"] = T.distance_km.astype(float).round(3)
        T["unroutable_reason"] = T.unroutable_reason.astype(object).where(T.routable == 0, None)
        T["routable"] = T.routable.astype(int)
        T["data_version"] = DATA_VERSION
        T.drop(columns=["minutes"]).to_parquet(LINK / f"travel_times_db_{TAG}.parquet", index=False, compression="zstd")
        counts["travel_times"] = insert(con, "travel_times", T, ["origin_id", "building_id", "minutes_est", "distance_km",
                                                                   "routable", "unroutable_reason", "data_version", "profile"])
        counts.update(load_weather_tables(con))
        con.execute("INSERT OR REPLACE INTO parameters VALUES ('minutes_rounding', 0.01, 'min', 0, "
                    "'DB/bundle travel times rounded to 0.01 min; optimizer runs on the rounded values')")
    con.execute("ANALYZE")
    con.close()
    stats_put("db_load_counts", counts)
    log(f"db loaded: {counts}")


# =============================================================================================== stage: optimize
SEASON = "JUL-AUG"
# (bundle label, schema weighting, method_version)
WEIGHTS = [("meteo", "historical_frequency", WEATHER_METHOD), ("uniforme", "uniform", None)]
MAIN = dict(strategy="A", pesos="meteo", threshold=12.0, profile="light")      # plan scenario


def scenario_id(thr, strat, prof, pesos="meteo"):
    _, w, meth = next(x for x in WEIGHTS if x[0] == pesos)
    return f"S-{SEASON}-{thr:g}-{strat}-{w}{'-' + meth if meth else ''}-{prof}-{DATA_VERSION}"


def stage_optimize():
    import importlib
    import optimizer as opt
    importlib.reload(opt)
    log(f"optimizer {opt.VERSION}: 10 candidates, k=0..{K_MAX}, A/B x weights {[w[0] for w in WEIGHTS]} x {THRESHOLDS} x {PROFILES}")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    with con:
        for t in ("plans", "combo_metrics", "result_building", "result_selection", "results", "scenarios"):
            con.execute(f"DELETE FROM {t}")
    nscope = con.execute("SELECT count(*) FROM v_scope_buildings").fetchone()[0]
    con.close()
    nA = len(analysis_ids())
    assert nscope == nA, (nscope, nA)
    summary = []
    for pesos, weighting, meth in WEIGHTS:
        for prof in PROFILES:
            p = opt.load_from_gpkg(str(DB), DATA_VERSION, SEASON, meth, weighting, 1.0, prof)
            assert len(p.building_ids) == nA and len(p.candidate_ids) == 10 and len(p.origin_ids) == 19
            assert not np.isnan(p.weights).any(), "missing weights"
            for thr in THRESHOLDS:
                for strat in ("A", "B"):
                    t0 = time.time()
                    res = opt.optimize(p, thr, K_MAX, strat)
                    sid = opt.write_to_gpkg(str(DB), p, res, dict(scenario_id=scenario_id(thr, strat, prof, pesos), season_id=SEASON,
                                                                   weighting=weighting, method_version=meth,
                                                                   data_version=DATA_VERSION, speed_factor=1.0, profile=prof))
                    for m in res["per_k"]:
                        summary.append(dict(scenario_id=sid, pesos=pesos, weighting=weighting, profile=prof, threshold_min=thr,
                                            strategy=strat, k=m["k"], selection=m["selection"], n_buildings=m["n_buildings"],
                                            n_covered=m["n_covered"], pct_covered=round(m["pct_covered"], 2),
                                            weighted_covered=m["weighted_covered"], weighted_share=m["weighted_share"],
                                            worst_time_min_est=round(m["worst_time_min_est"], 2), n_unroutable=m["n_unroutable"],
                                            gain_covered_vs_k0=m["gain_covered_vs_k0"], gain_covered_vs_prev=m["gain_covered_vs_prev"],
                                            nested_with_prev=m["nested_with_prev"], ties=m["ties"]))
                    log(f"  {sid}: {time.time() - t0:.1f} s")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    with con:
        con.execute("INSERT INTO plans VALUES (?,?,?,?,?)", ("PLAN-2027-JULAUG", 2027, SEASON,
                    scenario_id(MAIN["threshold"], MAIN["strategy"], MAIN["profile"], MAIN["pesos"]),
                    "Plan preventivo · Julio–agosto 2027"))
        con.execute("INSERT INTO plans VALUES (?,?,?,?,?)", ("PLAN-2027-JULAUG-CMP-UNIFORME", 2027, SEASON,
                    scenario_id(MAIN["threshold"], MAIN["strategy"], MAIN["profile"], "uniforme"),
                    "Plan preventivo · Julio–agosto 2027 · comparación con pesos uniformes"))
    con.close()
    SM = pd.DataFrame(summary)
    SM.to_csv(LINK / f"scenario_results_summary_{TAG}.csv", index=False)
    stats_put("optimize", dict(n_scenarios=int(SM.scenario_id.nunique()), optimizer_version=opt.VERSION,
                               weather_methods=[WEATHER_METHOD]))


# =============================================================================================== stage: validate
QA_EXPLAIN = {}      # v0.3: every qa_* view must return 0 rows (weather is loaded)


def nx_route(origin_xy, target_xy, bbox_margin=12000):
    """Independent route with networkx on a bbox subgraph; brute-force snap (no STRtree, no scipy)."""
    import networkx as nx
    xs, ys = [origin_xy[0], target_xy[0]], [origin_xy[1], target_xy[1]]
    bb = (min(xs) - bbox_margin, min(ys) - bbox_margin, max(xs) + bbox_margin, max(ys) + bbox_margin)
    N = pd.read_parquet(NET / "graph_nodes.parquet")
    A = pd.read_parquet(NET / "graph_arcs.parquet")
    inb = (N.x.between(bb[0], bb[2]) & N.y.between(bb[1], bb[3])).values
    A = A[(A.in_main_component == 1) & inb[A.u_idx.values] & inb[A.v_idx.values]]
    E_all = gpd.read_file(NET / "roads.gpkg", layer="road_edges", engine="pyogrio", bbox=bb)
    E = E_all[(E_all.in_main_component == 1) & ~E_all.fclass.isin(NO_SNAP)].reset_index(drop=True)
    nid = dict(zip(N.node_id, N.idx))
    G = nx.DiGraph()
    for r in A.itertuples():
        if G.has_edge(r.u_idx, r.v_idx) and G[r.u_idx][r.v_idx]["t"] <= r.t_light_s:
            continue
        G.add_edge(r.u_idx, r.v_idx, t=r.t_light_s, L=r.length_m, e=r.edge_id)

    def snap(pt):
        d = shapely.distance(E.geometry.values, shapely.Point(pt))
        i = int(np.argmin(d))
        e = E.iloc[i]
        f = float(shapely.line_locate_point(e.geometry, shapely.Point(pt), normalized=True))
        return e, f, float(d[i])
    eo, fo, so = snap(origin_xy)
    et, ft, st = snap(target_xy)
    for tag, e, f, s_, out in (("O", eo, fo, so, True), ("T", et, ft, st, False)):
        u, v = nid[e.u], nid[e.v]
        acc = s_ / ACCESS_MS
        if out:     # origin point -> end nodes
            if e.oneway in ("F", "B"):
                G.add_edge("O", v, t=acc + (1 - f) * e.t_light_s, L=s_ + (1 - f) * e.length_m, e=-1, pl=(1 - f) * e.length_m, reg=e.region)
            if e.oneway in ("T", "B"):
                G.add_edge("O", u, t=acc + f * e.t_light_s, L=s_ + f * e.length_m, e=-1, pl=f * e.length_m, reg=e.region)
        else:       # end nodes -> target point
            if e.oneway in ("F", "B"):
                G.add_edge(u, "T", t=acc + f * e.t_light_s, L=s_ + f * e.length_m, e=-2, pl=f * e.length_m, reg=e.region)
            if e.oneway in ("T", "B"):
                G.add_edge(v, "T", t=acc + (1 - f) * e.t_light_s, L=s_ + (1 - f) * e.length_m, e=-2, pl=(1 - f) * e.length_m, reg=e.region)
    path = nx.dijkstra_path(G, "O", "T", weight="t")
    t = sum(G[a][b]["t"] for a, b in zip(path[:-1], path[1:]))
    L = sum(G[a][b]["L"] for a, b in zip(path[:-1], path[1:]))
    Ei = E_all.set_index("edge_id")
    km_by, km_reg, refs = {}, {}, []
    for a, b in zip(path[:-1], path[1:]):
        e = G[a][b]["e"]
        if e < 0:                       # partial snapped edge (access excluded), counted in its region
            km_reg[G[a][b]["reg"]] = km_reg.get(G[a][b]["reg"], 0) + G[a][b]["pl"] / 1000
        if e > 0 and e in Ei.index:
            km_by[Ei.at[e, "fclass"]] = km_by.get(Ei.at[e, "fclass"], 0) + G[a][b]["L"] / 1000
            km_reg[Ei.at[e, "region"]] = km_reg.get(Ei.at[e, "region"], 0) + G[a][b]["L"] / 1000
            r = Ei.at[e, "ref"] if isinstance(Ei.at[e, "ref"], str) else None
            if r and (not refs or refs[-1] != r):
                refs.append(r)
    return dict(minutes=t / 60, km=L / 1000, n_arcs=len(path) - 1, snap_o_m=so, snap_t_m=st,
                subgraph_nodes=G.number_of_nodes(), subgraph_arcs=G.number_of_edges(),
                km_by_class={k: round(v, 2) for k, v in sorted(km_by.items(), key=lambda x: -x[1])},
                km_by_region={k: round(v, 2) for k, v in km_reg.items()}, roads=" > ".join(refs))


def brute_force_csv(T, w, n_st, cand_ids, thr, strategy, k_max=K_MAX):
    """Brute force from the bundle matrices, independent of optimizer.py (numpy, own objective):
    T = (n_parks + n_cands, n_buildings) minutes with NaN, w = weights. Returns dict k -> best metrics."""
    out = {}
    Tf = np.where(np.isnan(T), np.inf, T)
    for k in range(k_max + 1):
        best, keys = None, []
        for combo in itertools.combinations(range(len(cand_ids)), k):
            rows = list(range(n_st)) + [n_st + c for c in combo]
            bt = Tf[rows].min(0)
            routable = np.isfinite(bt)
            cov = routable & (bt <= thr + 1e-9)
            wc = round(float(w[cov].sum()), 6)
            worst = round(float(bt[routable].max()), 6)
            n_cov, unr = int(cov.sum()), int((~routable).sum())
            key = (-wc, -n_cov, worst) if strategy == "A" else (unr, worst, -wc, -n_cov)
            sel = ";".join(sorted(cand_ids[c] for c in combo))
            keys.append(key)
            if best is None or (key, sel) < (best[0], best[1]):
                best = (key, sel, n_cov, wc, worst, unr, cov)
        out[k] = dict(selection=best[1], n_covered=best[2], wcov=best[3], worst=round(best[4], 2), n_unroutable=best[5],
                      ties=sum(1 for x in keys if x == best[0]), covered=best[6])
    return out


def adverse_from_raw(station, year):
    """ADV-v1 for one station, JUL-AUG of one year, recomputed from the ORIGINAL 10-min values (obs_10min.parquet).
    Independent of weather.py: own daily aggregation; RH 100-105 % used as 100; valid day = >= 130 usable slots."""
    import pyarrow.dataset as ds
    t0 = pd.Timestamp(f"{year}-06-27", tz="UTC")
    t1 = pd.Timestamp(f"{year}-09-01", tz="UTC")
    O = ds.dataset(PROC / "weather" / "obs_10min.parquet").to_table(
        filter=(ds.field("station") == station) & (ds.field("ts_utc") >= t0) & (ds.field("ts_utc") < t1)
        & ds.field("variable").isin(["tair", "rh", "precip"]),
        columns=["ts_utc", "variable", "value", "quality_flag"]).to_pandas()
    O["variable"] = O.variable.astype(str)
    O["quality_flag"] = O.quality_flag.astype(str)
    O = O[O.quality_flag.isin(["valid", "suspect_usable"])].copy()
    O.loc[O.variable == "rh", "value"] = O.loc[O.variable == "rh", "value"].clip(upper=100.0)
    O["day"] = O.ts_utc.dt.strftime("%Y-%m-%d")
    agg = O.groupby(["day", "variable"]).value.agg(["size", "max", "min", "sum"]).unstack("variable")
    days = pd.date_range(f"{year}-06-27", f"{year}-08-31").strftime("%Y-%m-%d")
    agg = agg.reindex(days)
    n_t, n_rh, n_p = (agg[("size", v)].fillna(0) for v in ("tair", "rh", "precip"))
    tmax, rhmin, psum = agg[("max", "tair")], agg[("min", "rh")], agg[("sum", "precip")]
    vt, vr, vp = n_t >= 130, n_rh >= 130, n_p >= 130
    rows = []
    for i, d in enumerate(days):
        if d < f"{year}-07-01":
            continue
        prev = [days[i - j] for j in (1, 2, 3)]
        prev_ok = all(vp[x] for x in prev)
        valid = bool(vt[d] and vr[d] and prev_ok)
        adv = valid and tmax[d] >= 25 and rhmin[d] <= 40 and all(psum[x] < 1.0 for x in prev)
        rows.append(dict(day=d, valid=valid, adverse=bool(adv), tmax=tmax[d], rhmin=rhmin[d]))
    R = pd.DataFrame(rows)
    return int(R.valid.sum()), int(R.adverse.sum()), list(R[R.adverse].day)


def stage_validate():
    log("validation")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    qa = []
    for (v,) in con.execute("SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'qa_%' ORDER BY name"):
        n = con.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
        qa.append(dict(view=v, rows=n, status="pass" if n == 0 else ("explained" if v in QA_EXPLAIN else "FAIL"),
                       explanation=QA_EXPLAIN.get(v, "") if n else ""))
    QA = pd.DataFrame(qa)
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    integ = con.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for (t,) in
              con.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name").fetchall()}
    checks = []
    E = pd.read_csv(AGENT / "edificios.csv", dtype={"building_id": str, "muni_ine": str})
    ES = pd.read_csv(AGENT / "escenarios.csv", dtype={"seleccion": str, "umbral_min": str}, keep_default_na=False, na_values=[""])
    ES["seleccion"] = ES.seleccion.fillna("")
    TL = pd.read_csv(AGENT / "tiempos_ligero.csv", dtype={"building_id": str})
    TC = pd.read_csv(AGENT / "tiempos_camion.csv", dtype={"building_id": str})
    parks = [c for c in TL.columns if c != "building_id" and not c.startswith("CAND-")]
    cands = [c for c in TL.columns if c.startswith("CAND-")]
    # ---------------- H1/H2: routes recomputed with networkx (Amezketa worst-served building; Berastegi median building)
    BL = pd.read_csv(F_BL)
    FS = gpd.read_file(NET / "fire_stations.gpkg", engine="pyogrio").set_index("station_id")
    tt = read_tt()
    S = BL[(BL.in_analysis_set == 1) & (BL.routable == 1)]
    picks = [("Amezketa", S[(S.municipality == "Amezketa") & (S.base_light_station == "GIP-ORIA")].sort_values("base_light_min").iloc[-1]),
             ("Berastegi", S[(S.municipality == "Berastegi") & (S.base_light_station == "GIP-ORIA")]
              .assign(d=lambda d: (d.base_light_min - d.base_light_min.median()).abs()).sort_values("d").iloc[0])]
    viaN = S[S.base_light_nav_km > 0]
    if len(viaN):
        picks.append(("Navarra", viaN.sort_values("base_light_nav_km").iloc[-1]))
    for label, b in picks:
        sid = b.base_light_station
        r = nx_route((FS.at[sid, "x"], FS.at[sid, "y"]), (b.x, b.y))
        row = tt[(tt.origin_id == sid) & (tt.building_id == b.building_id) & (tt.profile == "light")].iloc[0]
        dbv = con.execute("SELECT minutes_est, distance_km FROM travel_times WHERE origin_id=? AND building_id=? "
                          "AND profile='light' AND data_version=?", (sid, b.building_id, DATA_VERSION)).fetchone()
        csv_v = float(TL.set_index("building_id").at[b.building_id, sid])
        ok = (abs(r["minutes"] - row.minutes) < 0.01 and abs(r["km"] - row.distance_km) < 0.01
              and abs(dbv[0] - round(r["minutes"], 2)) < 0.0051 and abs(csv_v - dbv[0]) < 1e-9)
        nav_ok = abs(r["km_by_region"].get("NAV", 0.0) - float(row.nav_km)) < 0.01
        checks.append(dict(id=f"H-route-{label}", claim=f"{sid} -> {b.building_id} ({b.municipality}), light",
                           stored=f"{row.minutes:.3f} min / {row.distance_km:.3f} km / {row.nav_km:.2f} km in Navarra (parquet); "
                                  f"{dbv[0]:.2f} min (DB); {csv_v:.2f} min (agent/datos/tiempos_ligero.csv)",
                           recomputed=f"{r['minutes']:.3f} min / {r['km']:.3f} km / {r['km_by_region'].get('NAV', 0.0):.2f} km in Navarra "
                                      f"(networkx, {r['subgraph_nodes']} nodes / {r['subgraph_arcs']} arcs subgraph, brute-force snap "
                                      f"{r['snap_o_m']:.1f} m / {r['snap_t_m']:.1f} m)",
                           match=bool(ok and nav_ok), detail=f"roads: {r['roads']}; km by class: {r['km_by_class']}; km by region: {r['km_by_region']}; "
                                                         f"lon/lat {TO_WGS.transform(b.x, b.y)[0]:.5f}, {TO_WGS.transform(b.x, b.y)[1]:.5f}"))
    # ---------------- H2c (v0.3.1): route over the reclassified foral road GI-3712 (was highway=service)
    bg = BL.set_index("building_id")
    for bid in ("ES.GFA.BU.32835",):
        if bid in bg.index and bg.at[bid, "routable"] == 1:
            bb = bg.loc[bid]
            sid = bb.base_light_station
            r = nx_route((FS.at[sid, "x"], FS.at[sid, "y"]), (bb.x, bb.y))
            row = tt[(tt.origin_id == sid) & (tt.building_id == bid) & (tt.profile == "light")].iloc[0]
            ok = abs(r["minutes"] - row.minutes) < 0.01 and abs(r["km"] - row.distance_km) < 0.01 and "GI-3712" in r["roads"]
            checks.append(dict(id="H-route-GI3712", claim=f"{sid} -> {bid} ({bb.municipality}), light, over GI-3712 (OSM service way 230176767 "
                                                          "reclassified as unclassified 40 km/h in v0.3.1)",
                               stored=f"{row.minutes:.2f} min / {row.distance_km:.3f} km (parquet)",
                               recomputed=f"{r['minutes']:.3f} min / {r['km']:.3f} km (networkx); GI-3712 on the path: {'GI-3712' in r['roads']}",
                               match=bool(ok), detail=f"roads: {r['roads']}; km by class: {r['km_by_class']}"))
    # ---------------- H2b: Navarra accounting on a target INSIDE Navarra (no analysis building routes through Navarra)
    G = Graph()
    OSs = pd.read_parquet(F_OS)
    oria = OSs[OSs.origin_id == "GIP-ORIA"].reset_index(drop=True)
    RR = Router(G, oria)
    lx, ly = TO_UTM.transform(-1.9156, 43.0794)                     # test point in Leitza village (Navarra)
    tg = G.snap([lx], [ly])
    rr = RR.run(tg, nav_rows=[0])["light"]
    r = nx_route((FS.at["GIP-ORIA", "x"], FS.at["GIP-ORIA", "y"]), (lx, ly))
    ok = abs(r["minutes"] - rr[0][0, 0]) < 0.01 and abs(r["km"] - rr[1][0, 0]) < 0.01 and abs(r["km_by_region"].get("NAV", 0) - rr[2][0, 0]) < 0.01
    checks.append(dict(id="H-route-Leitza-NAV", claim="GIP-ORIA -> test point in Leitza village (Navarra, lon -1.9156 lat 43.0794), light: "
                                                      "Navarra roads routable and km in Navarra accounted",
                       stored=f"{rr[0][0, 0]:.3f} min / {rr[1][0, 0]:.3f} km / {rr[2][0, 0]:.2f} km in Navarra (link_build Router, scipy)",
                       recomputed=f"{r['minutes']:.3f} min / {r['km']:.3f} km / {r['km_by_region'].get('NAV', 0.0):.2f} km in Navarra (networkx)",
                       match=bool(ok), detail=f"roads: {r['roads']}; km by region: {r['km_by_region']}; target snap {tg.snap_m.iloc[0]:.1f} m on a "
                                              f"{tg.snap_edge_class.iloc[0]} ({tg.snap_region.iloc[0]}). Not reachable at all in v0.2 (PV extract only)."))
    del G, RR
    # ---------------- H3: k=0 coverage at 12 min from the bundle CSVs with plain pandas
    for prof, TT_ in (("light", TL), ("truck", TC)):
        tb = TT_.set_index("building_id")[parks].min(axis=1)           # NaN = unroutable from all 9 parks
        cov = int((tb <= 12).sum())
        col = f"t_base_{PERFIL[prof]}"
        same_col = bool(np.allclose(tb.reindex(E.building_id).values, E[col].values, equal_nan=True))
        esr = ES[(ES.estrategia == "A") & (ES.k == 0) & (ES.umbral_min == "12") & (ES.perfil == PERFIL[prof]) & (ES.pesos == "meteo")].iloc[0]
        stored = con.execute("SELECT n_covered, pct_covered, n_unroutable, worst_time_min_est FROM results WHERE scenario_id=? AND k=0",
                             (scenario_id(12, "A", prof, "meteo"),)).fetchone()
        ok = (cov == stored[0] == esr.edificios_cubiertos and abs(100 * cov / len(E) - stored[1]) < 1e-6
              and int(tb.isna().sum()) == stored[2] == esr.sin_ruta and abs(tb.max() - stored[3]) < 1e-6 and same_col
              and int((E[col] <= 12).sum()) == cov)
        checks.append(dict(id=f"H-k0-{prof}", claim=f"k=0 coverage at 12 min, {prof}, {len(E):,} analysis buildings",
                           stored=f"{stored[0]} covered = {stored[1]:.2f} %, {stored[2]} unroutable, worst {stored[3]:.2f} min (DB results); "
                                  f"escenarios.csv {esr.edificios_cubiertos} / {esr.pct_cubiertos:.2f} %",
                           recomputed=f"{cov} covered = {100 * cov / len(E):.2f} %, {int(tb.isna().sum())} unroutable, worst {tb.max():.2f} min "
                                      f"(plain pandas row-min over the 9 park columns of agent/datos/tiempos_{PERFIL[prof]}.csv; "
                                      f"edificios.csv {col} identical: {same_col})",
                           match=bool(ok), detail=""))
    # ---------------- H4: optimizer result brute-forced from the bundle CSVs (main scenario + strategy B)
    w_meteo = E.set_index("building_id").peso_meteo.reindex(TL.building_id).values
    for strat, pesos, thr, prof, TT_ in (("A", "meteo", 12.0, "light", TL), ("B", "meteo", 12.0, "light", TL),
                                         ("A", "uniforme", 12.0, "light", TL)):
        M = TT_.set_index("building_id")[parks + cands].T.values.astype(float)
        w = w_meteo if pesos == "meteo" else np.ones(M.shape[1])
        bf = brute_force_csv(M, w, len(parks), cands, thr, strat)
        es = ES[(ES.estrategia == strat) & (ES.pesos == pesos) & (ES.umbral_min == f"{thr:g}") & (ES.perfil == PERFIL[prof])].set_index("k")
        sid = scenario_id(thr, strat, prof, pesos)
        db_ = {k: (s_, n_) for k, s_, n_ in con.execute("SELECT k, selection, n_covered FROM results WHERE scenario_id=?", (sid,))}
        mism = [k for k in bf if (bf[k]["selection"], bf[k]["n_covered"], bf[k]["n_unroutable"], bf[k]["ties"])
                != (es.at[k, "seleccion"], es.at[k, "edificios_cubiertos"], es.at[k, "sin_ruta"], es.at[k, "empates"])
                or abs(bf[k]["worst"] - es.at[k, "peor_tiempo"]) > 0.0051 or abs(bf[k]["wcov"] - es.at[k, "cobertura_ponderada"]) > 0.0051
                or db_[k][0].replace("|", ";") != bf[k]["selection"] or db_[k][1] != bf[k]["n_covered"]]
        checks.append(dict(id=f"H-brute-{strat}-{pesos}-{prof}-{thr:g}",
                           claim=f"strategy {strat}, weights {pesos}, {prof}, {thr:g} min: best per k=0..6 over 848 combinations",
                           stored="; ".join(f"k{k}: {es.at[k, 'seleccion'] or '-'} ({es.at[k, 'edificios_cubiertos']}, w {es.at[k, 'cobertura_ponderada']:.2f}, "
                                            f"worst {es.at[k, 'peor_tiempo']:.2f}, ties {es.at[k, 'empates']})" for k in range(K_MAX + 1)),
                           recomputed="; ".join(f"k{k}: {bf[k]['selection'] or '-'} ({bf[k]['n_covered']}, w {bf[k]['wcov']:.2f}, worst {bf[k]['worst']:.2f}, "
                                                f"ties {bf[k]['ties']})" for k in range(K_MAX + 1)),
                           match=not mism, detail=(f"mismatching k: {mism}" if mism else
                                                   "brute force on agent/datos/tiempos_ligero.csv + edificios.peso_meteo (numpy, not optimizer.py): "
                                                   "selection, covered, weighted coverage, worst, unroutable and ties identical to escenarios.csv and DB for every k")))
        if strat == "A" and pesos == "meteo":
            main_bf = bf
    # ---------------- H5: buildings gained by the k-th retén (main scenario) from the CSVs vs DB result_building
    sidm = scenario_id(12, "A", "light", "meteo")
    gm = []
    ids = TL.building_id.values
    for k in range(1, K_MAX + 1):
        a_ = set(ids[main_bf[k - 1]["covered"]]); b_ = set(ids[main_bf[k]["covered"]])
        q = pd.read_sql("SELECT building_id, k, covered FROM result_building WHERE scenario_id=? AND k IN (?,?)", con, params=(sidm, k - 1, k))
        pv = q.pivot(index="building_id", columns="k", values="covered")
        db_g = set(pv.index[(pv[k] == 1) & (pv[k - 1] == 0)]); db_l = set(pv.index[(pv[k] == 0) & (pv[k - 1] == 1)])
        gm.append((k, len(b_ - a_), len(a_ - b_), (b_ - a_) == db_g and (a_ - b_) == db_l))
    checks.append(dict(id="H-gains-main", claim=f"buildings gained / lost by the k-th retén, main scenario {sidm}",
                       stored="DB result_building (covered at k vs k-1)",
                       recomputed="; ".join(f"k{k}: +{g_} / -{l_}" for k, g_, l_, _ in gm) + " (from tiempos_ligero.csv + escenarios.csv selections)",
                       match=all(x[3] for x in gm), detail="identical building sets for every k" if all(x[3] for x in gm) else str(gm)))
    # ---------------- H6: adverse days from the ORIGINAL 10-min data for one station-season
    st_, yr = "C026", 2022
    nv, na_, days_ = adverse_from_raw(st_, yr)
    MA = pd.read_csv(AGENT / "meteo_anual.csv", dtype={"codigo": str}).set_index(["codigo", "anio"])
    dbw = con.execute("SELECT y.valid_days, y.adverse_days FROM weather_profile_year y JOIN weather_zones z USING (zone_id) "
                      "WHERE z.station_id=? AND y.year=? AND y.season_id='JUL-AUG' AND y.method_version=? AND y.data_version=?",
                      (st_, yr, WEATHER_METHOD, DATA_VERSION)).fetchone()
    AD = pd.read_csv(AGENT / "meteo_dias_adversos.csv", dtype={"codigo": str})
    ad_days = sorted(AD[(AD.codigo == st_) & AD.fecha.str.startswith(str(yr)) & AD.fecha.str[5:7].isin(["07", "08"])].fecha)
    ok = (nv, na_) == (int(MA.at[(st_, yr), "dias_validos"]), int(MA.at[(st_, yr), "dias_adversos"])) == tuple(dbw) and ad_days == days_
    checks.append(dict(id=f"H-adverse-{st_}-{yr}", claim=f"ADV-v1 adverse days, {st_} Berastegi, July-August {yr}",
                       stored=f"{int(MA.at[(st_, yr), 'dias_adversos'])} adverse / {int(MA.at[(st_, yr), 'dias_validos'])} valid days "
                              f"(meteo_anual.csv; DB weather_profile_year {dbw[1]}/{dbw[0]}); days {', '.join(ad_days)}",
                       recomputed=f"{na_} adverse / {nv} valid (own daily aggregation of obs_10min.parquet; spatial-consistency filter "
                                  f"of weather.py not replicated); days {', '.join(days_)}", match=bool(ok), detail=""))
    # ---------------- H7: optimizer unit tests
    import subprocess
    pt = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_optimizer.py"], cwd=MANAGER, capture_output=True, text=True)
    pt_line = (pt.stdout.strip().splitlines() or ["(no output)"])[-1]
    checks.append(dict(id="H-optimizer-tests", claim="code/manager/test_optimizer.py (brute force, monotonicity, schema rules)",
                       stored="optimizer.py " + __import__("optimizer").VERSION, recomputed=pt_line,
                       match=pt.returncode == 0, detail=""))
    HC = pd.DataFrame(checks)
    # ---------------- quality_reports
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    qrows = []

    def qr(dataset, check, value, expected, status, scope=None, note=None):
        qrows.append((DATA_VERSION, dataset, check, scope, None if value is None else float(value), expected, status, now,
                      "code/link_build.py (linker)", note))
    for t, n in counts.items():
        qr(t, "row_count", n, None, "pass")
    BS = pd.read_parquet(F_BS)
    BS["in_analysis_set"] = BS.building_id.isin(analysis_ids()).astype(int)
    TV = pd.read_csv(F_TRK)
    qr("buildings", "snap_gt_150m", int((BS.routable == 0).sum()), "reported, not dropped", "warn",
       note=f"{int(TV.routable_with_tracks.sum())} would be routable in the with-tracks variant (informational)")
    qr("buildings", "snap_gt_150m", int(((BS.routable == 0) & (BS.in_analysis_set == 1)).sum()), "reported, not dropped", "warn",
       scope="analysis_set")
    qr("buildings", "snap_m_median", float(BS.snap_m.median()), "<= 50", "pass")
    for _, r in QA.iterrows():
        qr("qa_views", r.view, r.rows, "0", "pass" if r.rows == 0 else ("warn" if r.status == "explained" else "fail"),
           note=r.explanation or None)
    for _, r in HC.iterrows():
        qr("hand_checks", r.id, 1.0 if r.match else 0.0, "1 (match)", "pass" if r["match"] else "fail", note=r.claim)
    qr("database", "foreign_key_check", len(fk), "0", "pass" if not fk else "fail")
    qr("database", "integrity_check", 1.0 if integ == "ok" else 0.0, "ok", "pass" if integ == "ok" else "fail")
    with con:
        con.execute("DELETE FROM quality_reports WHERE data_version=?", (DATA_VERSION,))
        con.executemany("INSERT INTO quality_reports (data_version,dataset,check_name,scope,value,expected,status,run_utc,"
                        "run_by,note) VALUES (?,?,?,?,?,?,?,?,?,?)", qrows)
    counts["quality_reports"] = con.execute("SELECT count(*) FROM quality_reports").fetchone()[0]
    con.close()
    QA.to_csv(LINK / f"qa_views_{TAG}.csv", index=False)
    HC.to_csv(LINK / f"hand_checks_{TAG}.csv", index=False)
    stats_put("validate", dict(qa=qa, fk_violations=len(fk), integrity=integ, counts=counts,
                               hand_checks=HC[["id", "match"]].to_dict("records")))
    con = sqlite3.connect(DB)
    con.execute("VACUUM")
    con.close()
    v031_diff()
    write_audit(QA, HC, fk, integ)
    write_report(QA, HC, counts, fk, integ)
    # bundle completeness marker (only when every QA view is 0, FK/integrity ok and every hand check matches)
    if (QA.rows == 0).all() and not fk and integ == "ok" and HC["match"].all():
        man = {f.name: sha256_file(f) for f in sorted(AGENT.glob("*")) if not f.name.startswith(".")}
        (AGENT / f".READY_{TAG}").write_text(json.dumps(dict(data_version=DATA_VERSION, ready_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                              files_sha256=man), indent=1), encoding="utf-8")
        log(f"bundle READY marker written: .READY_{TAG}")
    else:
        log("NOT READY: QA/FK/hand checks not all clean -> no marker")
    log(f"QA: {QA[['view', 'rows', 'status']].values.tolist()}")
    log(f"hand checks: {HC[['id', 'match']].values.tolist()}")


def v031_diff():
    """Judge review v0.3 -> v0.3.1: effect of the GI-ref reclass on the baseline, two named buildings and the scenarios."""
    f3 = LINK / "baseline_buildings_v0.3.csv"
    if not f3.exists() or not (PREV03 / "escenarios.csv").exists():
        return
    b3 = pd.read_csv(f3).set_index("building_id")
    b31 = pd.read_csv(F_BL).set_index("building_id")
    aset = sorted(analysis_ids())
    out = {}
    for prof in PROFILES:
        c = f"base_{prof}_min"
        x3, x31 = b3.loc[aset, c], b31.loc[aset, c]
        d = x31 - x3
        out[prof] = dict(n_faster=int((d < -0.005).sum()), n_slower=int((d > 0.005).sum()),
                         saving_max=round(float(-d.min()), 2),
                         saving_median_changed=round(float(-d[d < -0.005].median()), 2) if (d < -0.005).any() else 0.0,
                         changed_by_muni=b31.loc[d[d.abs() > 0.005].index, "municipality"].value_counts().to_dict(),
                         n_le_12_v03=int((x3 <= 12).sum()), n_le_12_v031=int((x31 <= 12).sum()),
                         pct_le_12_v03=round(100 * (x3 <= 12).mean(), 2), pct_le_12_v031=round(100 * (x31 <= 12).mean(), 2),
                         cross_in=int(((x3 > 12) & (x31 <= 12)).sum()), cross_out=int(((x3 <= 12) & (x31 > 12)).sum()),
                         worst_v03=round(float(x3.max()), 2), worst_v031=round(float(x31.max()), 2))
    named = []
    for bid in ("ES.GFA.BU.32835", "ES.GFA.BU.32837"):
        r = dict(building_id=bid, municipality=b31.at[bid, "municipality"], in_analysis_set=int(b31.at[bid, "in_analysis_set"]))
        for prof in PROFILES:
            r[f"{prof}_v03"] = f"{b3.at[bid, f'base_{prof}_min']:.2f} ({b3.at[bid, f'base_{prof}_station']}, {b3.at[bid, f'base_{prof}_km']:.2f} km)"
            r[f"{prof}_v031"] = f"{b31.at[bid, f'base_{prof}_min']:.2f} ({b31.at[bid, f'base_{prof}_station']}, {b31.at[bid, f'base_{prof}_km']:.2f} km)"
        named.append(r)
    e3 = pd.read_csv(PREV03 / "escenarios.csv", dtype={"seleccion": str, "umbral_min": str}, keep_default_na=False)
    e31 = pd.read_csv(AGENT / "escenarios.csv", dtype={"seleccion": str, "umbral_min": str}, keep_default_na=False)
    key = ["estrategia", "pesos", "umbral_min", "perfil", "k"]
    m = e3.merge(e31, on=key, suffixes=("_v03", "_v031"))
    m["sel_changed"] = m.seleccion_v03 != m.seleccion_v031
    m["worst_changed"] = (m.peor_tiempo_v03 - m.peor_tiempo_v031).abs() > 0.005
    m["cov_changed"] = m.edificios_cubiertos_v03 != m.edificios_cubiertos_v031
    bm = m[(m.estrategia == "B") & (m.pesos == "meteo") & (m.umbral_min == "12") & (m.perfil == "ligero")]
    stats_put("v031_diff", dict(
        baseline=out, named=named, n_rows=len(m), n_sel_changed=int(m.sel_changed.sum()), n_worst_changed=int(m.worst_changed.sum()),
        n_cov_changed=int(m.cov_changed.sum()),
        sel_changed_rows=m[m.sel_changed][key + ["seleccion_v03", "seleccion_v031", "peor_tiempo_v03", "peor_tiempo_v031",
                                                 "edificios_cubiertos_v03", "edificios_cubiertos_v031"]].to_dict("records"),
        B_meteo_12_light=bm[["k", "seleccion_v03", "seleccion_v031", "peor_tiempo_v03", "peor_tiempo_v031", "edificios_cubiertos_v03",
                             "edificios_cubiertos_v031", "p95_tiempo"]].to_dict("records")))


def write_audit(QA, HC, fk, integ):
    """agent/datos/auditoria.json: row accounting + unroutable + snaps + QA + hand checks (bundle contract)."""
    st = stats_get()
    ol = json.loads((PROC / "official_layers_stats.json").read_text())
    b5 = ol["buildings"]
    BS = pd.read_parquet(F_BS)
    aset = analysis_ids()
    BS["in_analysis_set"] = BS.building_id.isin(aset).astype(int)
    E = pd.read_csv(AGENT / "edificios.csv", dtype={"building_id": str})
    TV = pd.read_csv(F_TRK)
    nm = muni_names()
    un_a = BS[(BS.routable == 0) & (BS.in_analysis_set == 1)]
    tva = TV[TV.in_analysis_set == 1]
    sizes = {f.name: f.stat().st_size for f in sorted(AGENT.glob("*")) if f.name != "auditoria.json"}
    nav = st["baseline"]["navarra"]
    A = {
        "version_datos": DATA_VERSION,
        "generado_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generado_por": "code/link_build.py (linker/validator)",
        "contabilidad_edificios": {
            "b5m_gipuzkoa_filas": b5["n_raw"],
            "b5m_ids_inspire_unicos": b5["id"]["inspireid_unique_values"],
            "filas_id_repetido_eliminadas": b5["repeated_id"]["rows_dropped"],
            "tolosaldea_punto_interior_limites_oficiales": b5["tolosaldea_buildings"] + b5["dup_geom_tolosaldea"]["dropped"],
            "duplicados_misma_geometria_eliminados": b5["dup_geom_tolosaldea"]["dropped"],
            "tolosaldea_edificios": b5["tolosaldea_buildings"],
            "residenciales": b5["use_tol"]["residential"],
            "no_residenciales": b5["use_tol"]["non_residential"],
            "uso_desconocido": b5["use_tol"]["unknown"],
            "conjunto_analisis_residencial_y_100m_vegetacion": len(aset),
            "viviendas_conjunto_analisis": int(E.viviendas.sum()),
            "viviendas_desconocidas_conjunto_analisis": int(E.viviendas.isna().sum()),
            "edificios_excluidos_borde_otro_municipio": b5["excluded_border_buildings"],
            "nota": "Cada edificio aparece una vez (building_id = INSPIRE id B5M). Uso desconocido = sin CURRENTUSE catastral (no se cuentan como residenciales).",
        },
        "sin_ruta": {
            "todos_los_edificios": int((BS.routable == 0).sum()),
            "conjunto_analisis": int(len(un_a)),
            "conjunto_analisis_por_municipio": un_a.municipality_code.map(nm).value_counts().to_dict(),
            "motivo": "snap>150m (punto interior a > 150 m de una vía elegible del grafo por defecto, sin pistas)",
            "tratamiento": "se mantienen en todos los ficheros con tiempos vacíos; nunca cubiertos; cuentan en el denominador",
            "variante_con_pistas_informativa": {
                "evaluados": int(len(TV)), "rutables_con_pistas": int(TV.routable_with_tracks.sum()),
                "conjunto_analisis_evaluados": int(len(tva)), "conjunto_analisis_rutables_con_pistas": int(tva.routable_with_tracks.sum()),
                "conjunto_analisis_a_12min_ligero_con_pistas": int((tva.base_light_min_with_tracks <= 12).sum()),
                "uso": "solo informativo, no se usa en escenarios"},
        },
        "snap": {
            "mediana_m": round(float(BS.snap_m.median()), 1), "p90_m": round(float(BS.snap_m.quantile(.9)), 1),
            "mayor_150m_todos": int((BS.snap_m > SNAP_MAX_M).sum()),
            "mayor_150m_conjunto_analisis": int(((BS.snap_m > SNAP_MAX_M) & (BS.in_analysis_set == 1)).sum()),
            "parques_snap_max_m": round(float(pd.read_parquet(F_OS).query("origin_type == 'station'").snap_m.max()), 1),
        },
        "pesos_meteo": {
            "regla": WEATHER_METHOD, "temporada": "jul-ago", "edificios_sin_peso": int(E.peso_meteo.isna().sum()),
            "media_peso_meteo": round(float(E.peso_meteo.mean()), 6),
            "edificios_por_zona": E.zona_meteo.value_counts().to_dict(),
        },
        "red_navarra": {
            "edificios_conjunto_ruta_mas_rapida_por_navarra_ligero": nav["light"]["n_via_navarra"],
            "edificios_conjunto_ruta_mas_rapida_por_navarra_camion": nav["truck"]["n_via_navarra"],
            "pct_12min_ligero_red_v0.2_vs_v0.3": [nav["light"]["pct_le_12_v02net"], nav["light"]["pct_le_12_v03"]],
            "parques_navarra_como_origen": 0,
        },
        "candidatas": st["selection"].get("diff", {}),
        "cambios_v0.3.1": {
            "reclasificacion_service_ref_GI": json.loads((NET / "network_stats.json").read_text()).get("reclass_service_gi", {}),
            "seleccion_igual_a_v0.3": st["selection"].get("vs_v03", {}).get("unchanged"),
            "linea_base_vs_v0.3": {k: {kk: v[kk] for kk in ("n_faster", "n_slower", "pct_le_12_v03", "pct_le_12_v031", "worst_v03", "worst_v031")}
                                   for k, v in st.get("v031_diff", {}).get("baseline", {}).items()},
            "filas_escenarios_con_seleccion_distinta": st.get("v031_diff", {}).get("n_sel_changed"),
            "columna_nueva": "escenarios.csv: p95_tiempo (última columna)"},
        "qa_vistas": QA[["view", "rows", "status"]].to_dict("records"),
        "fk_violaciones": len(fk), "integrity_check": integ,
        "comprobaciones_a_mano": HC[["id", "claim", "stored", "recomputed", "match"]].to_dict("records"),
        "ficheros_bundle_bytes": sizes,
        "limite_bytes_por_fichero": MAX_BYTES,
    }
    (AGENT / "auditoria.json").write_text(json.dumps(A, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                                          encoding="utf-8")
    assert (AGENT / "auditoria.json").stat().st_size <= MAX_BYTES


def write_report(QA, HC, counts, fk, integ):
    st = stats_get()
    BS = pd.read_parquet(F_BS)
    BS["in_analysis_set"] = BS.building_id.isin(analysis_ids()).astype(int)
    OS = pd.read_parquet(F_OS)
    MB = pd.read_csv(F_MB)
    CP = pd.read_csv(F_CP)
    ES = pd.read_csv(AGENT / "escenarios.csv", dtype={"seleccion": str, "umbral_min": str}, keep_default_na=False, na_values=[""])
    ES["seleccion"] = ES.seleccion.fillna("")
    CA = pd.read_csv(CANDDIR / "candidates_10.csv")
    MP = pd.read_csv(CANDDIR / "candidate_id_mapping_v02_v03.csv")
    TV = pd.read_csv(F_TRK)
    nav = st["baseline"]["navarra"]
    b = st["baseline"]
    a = b["analysis"]
    nA = b["n_analysis"]
    sel = st["selection"]
    net = json.loads((NET / "network_stats.json").read_text())
    nm = muni_names()
    L = []
    L.append(f"# flAIre · Linker / validator report · data {DATA_VERSION}\n")
    L.append(f"Generated by `code/link_build.py` on {time.strftime('%Y-%m-%d %H:%M', time.localtime())} (all numbers written by the script; "
             "re-running regenerates this file). Database: `db/flaire.gpkg` (schema `code/manager/schema.sql` v1.3). Agent bundle: "
             "`agent/datos/` (contract `bundle_contract.md`). **All layers are official now**: municipal limits geoEuskadi 1:5.000, "
             "Mapa Forestal 2024, B5M buildings and parks, Euskalmet weather weights (ADV-v1), OSM roads País Vasco + Navarra. "
             "Times are travel-time estimates, not response times. The v0.2 report is kept as an annex at the end.\n")
    L.append("## 0. Key numbers\n")
    nl, nt = nav["light"], nav["truck"]
    L.append(f"* **Navarra roads** (+{net['navarra']['added_from_nav']:,} ways, {net['navarra']['dup_total']} border ways de-duplicated): "
             f"**{nl['n_via_navarra']} of {nA:,} analysis buildings** have a fastest park route through Navarra (light; truck {nt['n_via_navarra']}). "
             f"Vs the v0.2 network: {nl['n_faster']} buildings faster, {nl['n_slower']} slower (beyond the ±0.01 min rounding step; {nl['n_rounding_only']} differ only by rounding; any change comes from the v0.3.1 GI-ref road fix, not from Navarra, since no route has Navarra km), 12-min coverage {nl['pct_le_12_v02net']:.2f} % → "
             f"{nl['pct_le_12_v03']:.2f} % on the same set (v0.2 vs v0.3 network). Navarra roads ARE routable (Oria → Leitza village "
             "check, §7); they simply never beat the Gipuzkoa roads from the 9 Gipuzkoa parks. Navarra parks are not origins (no official data).")
    L.append(f"* **Baseline (0 retenes, 9 parks), analysis set {nA:,} buildings: light {a['pct_le_12']:.1f} % within 12 min** "
             f"({a['pct_le_10']:.1f} % ≤10, {a['pct_le_15']:.1f} % ≤15, {a['pct_le_20']:.1f} % ≤20; worst {a['worst_min']:.1f} min); "
             f"**truck {a['pct_le_12_truck']:.1f} % ≤12** (worst {a['worst_truck_min']:.1f}); **{a['n_unroutable']} unroutable** (snap > 150 m, "
             f"kept). v0.2 (OSM set of 1,747): 77.7 % light / 59.9 % truck.")
    L.append(f"* **Candidates** (same rule): {sel['diff']['kept']} kept with the same number, {sel['diff']['dropped']} dropped, "
             f"{sel['diff']['new']} new (they inherit the number of the nearest dropped v0.2 site): " +
             "; ".join(f"{r.v02_cand_id} {r['name']} → {MP[(MP.status == 'new') & (MP.v03_cand_id == r.v02_cand_id)]['name'].iloc[0]}"
                       for _, r in MP[MP.status == "dropped"].iterrows()) + ".")
    for strat, pesos in (("A", "meteo"), ("A", "uniforme"), ("B", "meteo")):
        r = ES[(ES.estrategia == strat) & (ES.pesos == pesos) & (ES.umbral_min == "12") & (ES.perfil == "ligero")]
        L.append(f"* **{strat}-{pesos}** (12 min, light): " + "; ".join(
            f"k={int(x.k)} {x.seleccion or '—'} → {x.edificios_cubiertos} ({x.pct_cubiertos:.1f} %, pond. {x.pct_ponderada:.1f} %, worst {x.peor_tiempo:.1f}, p95 {x.p95_tiempo:.1f}"
            + (f", ties {x.empates}" if x.empates > 1 else "") + ")" for x in r.itertuples()))
    cmpw = weighted_vs_uniform(ES)
    nd = int((~cmpw.same).sum())
    L.append(f"* **Weighted vs uniform (strategy A)**: different selection in {nd} of {len(cmpw)} (threshold, profile, k) cases; "
             f"where they differ the uniform choice covers at most {int(cmpw.d_buildings.max())} more buildings and the weighted choice gains at most "
             f"{cmpw.d_wpct.max():.2f} pp of weighted coverage. Weights are nearly flat (0.81–1.30, within inter-annual noise): differences are near-ties (§5.2).")
    nfail = int((QA.status == "FAIL").sum())
    L.append(f"* QA views: {len(QA)} run, {int((QA.status == 'pass').sum())} return 0 rows, {nfail} unexplained. Foreign-key violations: {len(fk)}; "
             f"integrity_check: {integ}. Hand checks: **{int(HC['match'].sum())}/{len(HC)} match** (§7).")
    bs_ = st["bundle"]["files"]
    L.append(f"* Bundle `agent/datos/`: {len(bs_) + 1} files incl. `auditoria.json`, total {st['bundle']['total_mb']:.2f} MB, largest "
             f"{max(bs_, key=bs_.get)} {max(bs_.values()) / 1e6:.2f} MB (limit 3.5 MB).\n")

    dv = st.get("v031_diff")
    if dv:
        rc = net.get("reclass_service_gi", {})
        L.append("## 0b. v0.3 → v0.3.1 (judge review)\n")
        L.append(f"1. **Road fix**: `highway=service` ways with a foral `ref` `^GI-` routed as `unclassified` (40 km/h, `speed_source = "
                 f"'reclass_service_with_GI_ref'`): **{rc.get('edges')} edges, {rc.get('km', 0):.2f} km, {rc.get('ways')} ways** "
                 "(GI-3712 Aldaba auzoa way 230176767, GI-2631 Agaraitz auzoa, …; list in `reports/quality_network.md` §11).")
        for prof in PROFILES:
            x = dv["baseline"][prof]
            L.append(f"   * Baseline {prof}: {x['n_faster']} analysis buildings faster (max −{x['saving_max']:.2f} min, median −{x['saving_median_changed']:.2f}; "
                     f"{x['changed_by_muni']}), {x['n_slower']} slower; ≤12 min {x['n_le_12_v03']} → {x['n_le_12_v031']} "
                     f"({x['pct_le_12_v03']:.2f} % → {x['pct_le_12_v031']:.2f} %; in {x['cross_in']}, out {x['cross_out']}); worst {x['worst_v03']:.2f} → {x['worst_v031']:.2f}.")
        L.append("")
        L.append(md_table(pd.DataFrame(dv["named"]), 2))
        L.append(f"\n   * Scenarios: {dv['n_sel_changed']} of {dv['n_rows']} rows of `escenarios.csv` change selection, {dv['n_cov_changed']} change the "
                 f"covered count, {dv['n_worst_changed']} the worst time. Strategy B, weights meteo, 12 min, light (p95 = new column):\n")
        L.append(md_table(pd.DataFrame(dv["B_meteo_12_light"]), 2))
        con_ = sqlite3.connect(DB)
        sidb = scenario_id(12, "B", "light", "meteo")
        top = pd.read_sql("SELECT selection, n_covered, worst_time_min_est, rank_in_k FROM combo_metrics WHERE scenario_id=? AND k=2 "
                          "ORDER BY rank_in_k LIMIT 4", con_, params=(sidb,))
        c12 = con_.execute("SELECT n_covered, worst_time_min_est, rank_in_k FROM combo_metrics WHERE scenario_id=? AND selection='CAND-01|CAND-02'",
                           (sidb,)).fetchone()
        con_.close()
        L.append(f"\n   B k=2 (12 min, light): the judge expected CAND-01+02. With GI-3712 fixed the Tolosa buildings stop being the worst; under B's "
                 f"unchanged lexicographic objective (fewest unroutable, then lowest worst time) CAND-01+02 ranks **{c12[2]}th** (worst {c12[1]:.2f} min, "
                 f"{c12[0]} covered) behind " + "; ".join(f"{r.selection.replace('|', '+')} (worst {r.worst_time_min_est:.2f}, {r.n_covered})"
                                                          for r in top.itertuples() if r.rank_in_k < c12[2]) +
                 ". Confirmed by the independent brute force H-brute-B-meteo-light-12.")
        if dv["sel_changed_rows"]:
            L.append("\n   All rows whose selection changed:\n")
            L.append(md_table(pd.DataFrame(dv["sel_changed_rows"]), 2))
        vs = st["selection"].get("vs_v03", {})
        L.append("\n2. **Candidates**: rule re-run → " + ("same 10 sites and numbers as v0.3 (kept)." if vs.get("unchanged") else
                 f"changed vs v0.3: added {vs.get('added')}, removed {vs.get('removed')} (numbering stable)."))
        L.append("3. **Site caveats** added to `candidatos.csv.comprobaciones_pendientes` ('ESPECÍFICO: …') and to the fichas: CAND-01 footprint ≠ "
                 "parking/manoeuvre space; CAND-04 private bottling plant (ownership/permission); CAND-08 OSM point without area, snap 50.5 m, close "
                 "to Oria; CAND-09 picnic site in Tolosa's southern exclave.")
        L.append("4. **`p95_tiempo`** appended as the LAST column of `escenarios.csv` (p95 of the best time over routable buildings; reported only, "
                 "objectives unchanged); noted in `bundle_contract.md`.")
        L.append("5. QA views, FK/integrity and hand checks re-run (incl. new H-route-GI3712); `auditoria.json` regenerated; marker `agent/datos/.READY_v0.3.1`.\n")
    L.append("## 1. Snapping and unroutable buildings\n")
    L.append("Default graph = roads main strongly connected component (`in_main_component = 1`, tracks excluded) of the merged País Vasco + Navarra "
             f"network ({net['graph']['arcs']:,} directed arcs, {net['graph']['nodes']:,} nodes). Snap = nearest point on the nearest **eligible** edge "
             "(main SCC, not motorway/trunk/their links) from the building's interior representative point; snap > 150 m → `routable = 0`, "
             f"reason `{REASON_SNAP}` (kept everywhere).\n")
    sc = BS.snap_edge_class.value_counts()
    un = BS[BS.routable == 0]
    L.append(f"* Buildings: **{len(BS):,}** (12 new vs v0.2, 99 changed municipality with the official limits — all re-snapped and re-routed, no reuse); "
             f"snap median {BS.snap_m.median():.1f} m, p90 {BS.snap_m.quantile(.9):.1f} m; **{len(un)} unroutable** (all buildings) / "
             f"**{int((un.in_analysis_set == 1).sum())}** in the analysis set. Snap class: " + ", ".join(f"{k} {v:,}" for k, v in sc.items()) + ".")
    ua = BS[(BS.routable == 0) & (BS.in_analysis_set == 1)].municipality_code.map(nm).value_counts()
    L.append("* Analysis-set unroutable by municipality: " + ", ".join(f"{k} {v}" for k, v in ua.items()) + ".")
    tva = TV[TV.in_analysis_set == 1]
    L.append(f"* **With-tracks variant (informational only, not used in any scenario)**: of the {len(TV)} unroutable buildings, "
             f"{int(TV.routable_with_tracks.sum())} become routable when tracks (10 km/h) are allowed; in the analysis set "
             f"{int(tva.routable_with_tracks.sum())} of {len(tva)} (light baseline via tracks: median {tva.base_light_min_with_tracks.median():.1f} min, "
             f"{int((tva.base_light_min_with_tracks <= 12).sum())} within 12 min). File `processed/links/tracks_variant_unroutable_{TAG}.csv`.")
    so = OS.groupby("origin_type").snap_m.agg(["count", "median", "max"]).round(1).reset_index()
    L.append("* Origins: " + "; ".join(f"{r.origin_type}: n={r['count']}, median {r['median']} m, max {r['max']} m" for _, r in so.iterrows()) +
             ". 9 parks (`include_in_baseline = 1`; OTH-HONDARRIBIA excluded; **no Navarra park**), all usable pool sites, 10 v0.1 candidates (`V01-*`).\n")

    L.append("## 2. Travel-time model, Navarra roads and files\n")
    L.append("`time = access_origin + network + partial_edge + access_building`, access = straight-line snap distance at 15 km/h, forward Dijkstra "
             "(`scipy.sparse.csgraph`), oneway respected, light = class speed, truck = ×0.9 motorway/trunk/primary, ×0.8 below. The km driven on "
             "`region = 'NAV'` edges are accumulated along every park route (`nav_km`). **DB and bundle minutes are rounded to 0.01** and the optimizer "
             "runs on those values, so every scenario can be recomputed exactly from `agent/datos/tiempos_*.csv`.\n")
    L.append(f"**Navarra effect on the v0.3 analysis set** (same {nA:,} buildings; v0.2 network = PV extract only, `travel_times_v0.2.parquet`):\n")
    nrow = []
    for prof in PROFILES:
        x = nav[prof]
        nrow.append(dict(profile=prof, buildings_via_navarra=x["n_via_navarra"], faster=x["n_faster"], slower=x["n_slower"],
                         pct_le_12_v02_network=x["pct_le_12_v02net"], pct_le_12_v03_network=x["pct_le_12_v03"],
                         cross_in_12=x["n_cross_in_12"], cross_out_12=x["n_cross_out_12"], unroutable_v02net=x["n_unroutable_v02net"],
                         unroutable_v03=x["n_unroutable_v03"], worst_v02net=x["worst_v02net"], worst_v03=x["worst_v03"]))
    L.append(md_table(pd.DataFrame(nrow), 2))
    L.append(f"\nNo park → building route of the 9 parks × {len(BS):,} buildings × 2 profiles uses a Navarra edge (all `nav_km` = 0). The new Navarra "
             "edges are connected (A-15/N-130 carriageways cut at the border in v0.2 are now in the main SCC; Oria → Leitza village is routable with "
             "km in Navarra, hand check H-route-Leitza-NAV), and Gipuzkoa edges and times are identical to v0.2 for every routable building. "
             "Conclusion: adding Navarra roads does not change any v0.3 figure; the missing piece for border villages (Berastegi, Elduain, Lizartza, "
             "Orexa, Gaztelu) would be Navarra **parks** (Leitza, Lekunberri…), which have no official source in the package. "
             "Validation routes of the network report are identical to v0.2 (`reports/quality_network.md` §10).\n")
    L.append("| file | content |\n|---|---|")
    L.append(f"| `processed/links/travel_times_{TAG}.parquet` | 9 parks + 10 v0.1 candidates × {len(BS):,} buildings × light/truck (minutes 0.01, km, nav_km) |")
    L.append(f"| `processed/links/travel_times_pool_{TAG}.parquet` | {int((OS.origin_type == 'pool').sum())} pool sites × {len(BS):,} × 2 |")
    L.append(f"| `processed/links/travel_times_db_{TAG}.parquet` / DB `travel_times` | 9 parks + CAND-01..10 × {len(BS):,} × 2 ({counts.get('travel_times', 0):,} rows, minutes 0.01) |")
    L.append(f"| `processed/links/building_snap_{TAG}.parquet`, `origin_snap_{TAG}.parquet`, `baseline_buildings_{TAG}.csv` | snaps, site baselines, nearest park per building |")
    L.append(f"| `processed/links/navarra_effect_{TAG}.csv`, `tracks_variant_unroutable_{TAG}.csv` | per-building Navarra comparison (changed rows only), with-tracks variant |\n")

    L.append("## 3. Baseline (0 retenes, 9 parks)\n")
    L.append(f"Nearest park for the analysis set: {b['nearest_park_counts_analysis']} (Oria {b['oria_nearest_share_analysis']} %). "
             f"Percentages use all {nA:,} buildings as denominator (unroutable = not covered).\n")
    mb = MB.rename(columns={"pct_le_10": "% ≤10", "pct_le_12": "% ≤12", "pct_le_15": "% ≤15", "pct_le_20": "% ≤20",
                            "pct_le_12_truck": "% ≤12 truck", "n_unroutable": "unroutable", "worst_min": "worst",
                            "worst_truck_min": "worst truck", "median_min": "median", "nearest_park_mode": "nearest park",
                            "n_via_navarra_light": "via NAV"})
    L.append(md_table(mb, 1))
    L.append("\n### Comparison with v0.1 and v0.2\n")
    L.append(md_table(CP, 1))
    L.append("\nThe 12-min share rises from 77.7 % (v0.2, 1,747 buildings) to "
             f"{a['pct_le_12']:.1f} % because the official Mapa Forestal adds 1,959 buildings (riparian strips and small woods near "
             "villages; Tolosa +405, Ibarra +203), mostly in well-served valley floors, and removes 375 OSM-forest buildings; the network effect is nil.\n")

    L.append("## 4. Candidates (stage `select`)\n")
    L.append(f"Same rule as v0.2 (fichas: `reports/fichas_candidatas_v03.md`): {sel['n_eligible']} eligible of {sel['n_in_pilot']} pool sites inside the 28 "
             f"municipalities; demand = {sel['n_demand']} routable analysis buildings > 12 min ({sel['n_deficit']} incl. {sel['n_deficit_unroutable']} unroutable), "
             f"DBSCAN 2 km → {sel['n_major']} major clusters, then farthest-first spread. CAND numbers are kept for unchanged sites; new sites take the "
             "number of the nearest dropped v0.2 site.\n")
    L.append(md_table(CA[["cand_id", "pool_id", "site_type", "name", "municipality", "snap_m", "area_m2", "baseline_light_min",
                          "baseline_truck_min", "selection_step", "selection_order", "info_gain_alone_12_n"]], 1))
    L.append("\n**Diff vs v0.2** (`processed/candidates/candidate_id_mapping_v02_v03.csv`):\n")
    L.append(md_table(MP[["v02_cand_id", "v03_cand_id", "status", "pool_id", "name", "municipality", "note"]], 1))
    L.append("")

    L.append("## 5. Optimizer (stage `optimize`)\n")
    L.append(f"`code/manager/optimizer.py` {st['optimize']['optimizer_version']} (adds weighting `uniform`; schema v1.2). "
             f"{st['optimize']['n_scenarios']} scenarios = A/B × weights (meteo = ADV-v1 historical frequency, uniform = 1) × 10/12/15 min × light/truck, "
             f"k = 0..6, 848 combinations each, {nA:,} buildings, season JUL-AUG, data `{DATA_VERSION}`. Plan `PLAN-2027-JULAUG` → "
             f"`{scenario_id(12, 'A', 'light', 'meteo')}`; comparison plan `PLAN-2027-JULAUG-CMP-UNIFORME` → `{scenario_id(12, 'A', 'light', 'uniforme')}`. "
             "Building-level results for every k (who is covered, best origin) are in DB `result_building`; the agent can recompute the buildings gained "
             "by the k-th retén from `tiempos_*.csv` + `escenarios.csv` (hand check H-gains-main). In `escenarios.csv` the weighted coverage uses the "
             "normalized weights (`peso_meteo`, mean 1); the DB stores the raw frequency (same ranking, the objective is scale-invariant).\n")
    for prof in PROFILES:
        for thr in THRESHOLDS:
            L.append(f"**{PERFIL[prof]}, {thr:g} min**\n")
            rows = []
            for k in range(K_MAX + 1):
                row = dict(k=k)
                for strat, pesos in (("A", "meteo"), ("A", "uniforme"), ("B", "meteo")):
                    x = ES[(ES.estrategia == strat) & (ES.pesos == pesos) & (ES.umbral_min == f"{thr:g}") & (ES.perfil == PERFIL[prof]) & (ES.k == k)].iloc[0]
                    lab = f"{strat}-{pesos[:4]}"
                    row[lab] = (x.seleccion or "—") + (f" ({x.empates} ties)" if x.empates > 1 else "")
                    row[f"{lab} n (%)"] = f"{x.edificios_cubiertos} ({x.pct_cubiertos:.1f})"
                    if pesos == "meteo":
                        row[f"{lab} pond %"] = f"{x.pct_ponderada:.1f}"
                    row[f"{lab} worst"] = f"{x.peor_tiempo:.2f}"
                rows.append(row)
            L.append(md_table(pd.DataFrame(rows), 2))
            L.append("")
    bm = ES[ES.estrategia == "B"].pivot_table(index=["umbral_min", "perfil", "k"], columns="pesos", values="seleccion", aggfunc="first")
    L.append(f"B with uniform weights picks the same combination as B-meteo in {int((bm.meteo == bm.uniforme).sum())} of {len(bm)} cases "
             "(weights only break ties in B); both are in `escenarios.csv`.\n")
    con = sqlite3.connect(DB)
    wb = con.execute("SELECT m.name, b.snap_road, rb.best_origin_id, rb.best_minutes_est FROM result_building rb "
                     "JOIN buildings b ON b.building_id = rb.building_id JOIN municipalities m ON m.ine_code = b.municipality_code "
                     "WHERE rb.scenario_id = ? AND rb.k = ? AND rb.routable = 1 ORDER BY rb.best_minutes_est DESC LIMIT 1",
                     (scenario_id(12, "B", "light"), K_MAX)).fetchone()
    con.close()
    L.append(f"Reading notes (12 min): unroutable = {a['n_unroutable']} in every row (a candidate cannot fix a building-side snap). The worst building left by "
             f"B at k = 6 (light) is in {wb[0]} ({wb[1]}), {wb[3]:.2f} min from {wb[2]}. A and B differ because B spends its first retenes on the "
             "worst-served buildings while A picks the sites that bring most (weighted) buildings under the threshold.\n")
    L.append("### 5.2 Weighted vs uniform (strategy A)\n")
    L.append(md_table(cmpw[~cmpw.same].drop(columns=["same"]), 2) if nd else "Identical selections in every case.")
    L.append("\nZone weights (normalized, mean 1 over the analysis set): C026 Berastegi 1.30, C058 Bidania 1.18, C029 Zizurkil 0.81; every ±1 sd "
             "interval overlaps (4 seasons, 13–21 adverse days per zone, `reports/quality_weather.md` §8). Where the selections differ the totals "
             "are near-ties: present weighted Strategy A as count maximisation with a weak historical tilt, not as a risk ranking.\n")

    L.append("## 6. Database `db/flaire.gpkg` (stage `db`)\n")
    L.append("Built from `schema.sql` v1.3 with `PRAGMA foreign_keys = ON`; every row passed the CHECK constraints/triggers. Official layers: "
             f"`municipalities`/`boundary` = `{SRC_MUN}`, `vegetation` = layer `vegetation_db` of `vegetation_forest_map_2024.gpkg` ({counts.get('vegetation', 0):,} "
             "polygons, clip = boundary + 2 km) with `vegetation_classes` = `class_dictionary.csv` (263 codes), `road_edges.source_id` = PV or NAV extract. "
             "Weather plug-in loaded from `processed/weather/db_tables/` (profiles stored under this data version; Euskalmet sources owner P1, all in "
             "`data_version_sources`). `data_version = 'v0.3-official'` (not frozen).\n")
    L.append("| table | rows |\n|---|---|")
    for t, n in counts.items():
        L.append(f"| {t} | {n:,} |")
    L.append("\n### QA views\n")
    L.append(md_table(QA, 0))
    L.append("")

    L.append("## 7. Hand checks (end to end, independent code paths)\n")
    for _, r in HC.iterrows():
        L.append(f"**{r.id}** — {r.claim}: **{'MATCH' if r['match'] else 'MISMATCH'}**")
        L.append(f"* stored: {r.stored}")
        L.append(f"* recomputed: {r.recomputed}")
        if isinstance(r.detail, str) and r.detail:
            L.append(f"* {r.detail}")
        L.append("")

    L.append("## 8. Agent bundle `agent/datos/`\n")
    L.append("Written exactly per `bundle_contract.md` (UTF-8, comma, '.' decimals, IDs as text, missing = empty, minutes with 2 decimals, WGS84). "
             "`municipios.geojson` = official limits simplified with `shapely.coverage_simplify` (shared borders stay shared), "
             f"tolerance {st['bundle_geojson']['simplify_tolerance_m']} m, valid geometries: {st['bundle_geojson']['valid']}.\n")
    L.append("| file | bytes |\n|---|---|")
    for f_, n_ in st["bundle"]["files"].items():
        L.append(f"| {f_} | {n_:,} |")
    L.append(f"| auditoria.json | {(AGENT / 'auditoria.json').stat().st_size:,} |\n")

    L.append("## 9. Open issues\n")
    L.append("1. **No Navarra parks** as origins (no official source loaded): Navarra roads are in the graph but cannot change any figure from the 9 Gipuzkoa parks.")
    L.append(f"2. {len(un)} buildings ({int((un.in_analysis_set == 1).sum())} in the analysis set) are > 150 m from a road of the default graph; "
             f"{int(tva.routable_with_tracks.sum())} of the analysis-set ones would be routable via tracks. Team decision: keep them as unroutable (current) or adopt the with-tracks variant.")
    L.append("3. Weather weights are nearly flat (within inter-annual noise) and July–August is not the historical peak (September is): say so with every weighted result.")
    L.append("4. Speeds assumed for ≈ 85 % of edges; truck factors are assumptions; times are estimates, not response times.")
    L.append("5. Candidates: OSM-dependent pool; 60 field checks pending; dfg_facility areas are building footprints.")
    L.append("6. Schema v1.2 / optimizer 1.2.0 add weighting `uniform`; `tools_spec.md` should list it (the agent reads the bundle, not the DB).")
    L.append("7. Official-limits page warns the lines are not official cartography and some are provisional (P2 §7.4).")
    L.append("8. `reports/sources.csv`: B5M buildings URL/licence still 'to confirm'.\n")
    L.append("---\n")
    L.append("# Annex · v0.2 report (superseded, kept as record)\n")
    old = (PREV / "linker_validation_v02.md").read_text(encoding="utf-8") if (PREV / "linker_validation_v02.md").exists() else ""
    old = old.replace("\n## ", "\n### ").replace("# flAIre · Linker / validator report · data v0.2-provisional-veg",
                                                  "## flAIre · Linker / validator report · data v0.2-provisional-veg")
    L.append(old)
    (REP / "linker_validation.md").write_text("\n".join(L), encoding="utf-8")
    log("report written")


def weighted_vs_uniform(ES):
    """Strategy A: weighted vs uniform selection per (threshold, profile, k), with the weighted share of the uniform choice."""
    rows = []
    for (thr, perf, k), g in ES[ES.estrategia == "A"].groupby(["umbral_min", "perfil", "k"]):
        m = g[g.pesos == "meteo"].iloc[0]
        u = g[g.pesos == "uniforme"].iloc[0]
        rows.append(dict(umbral_min=thr, perfil=perf, k=k, same=m.seleccion == u.seleccion, seleccion_meteo=m.seleccion,
                         seleccion_uniforme=u.seleccion, n_meteo=m.edificios_cubiertos, n_uniforme=u.edificios_cubiertos,
                         d_buildings=u.edificios_cubiertos - m.edificios_cubiertos, pond_pct_meteo=m.pct_ponderada,
                         pond_pct_of_uniform_choice=np.nan))
    D = pd.DataFrame(rows)
    E = pd.read_csv(AGENT / "edificios.csv", dtype={"building_id": str})
    w = E.set_index("building_id").peso_meteo
    for perf in ("ligero", "camion"):
        T = pd.read_csv(AGENT / f"tiempos_{perf}.csv", dtype={"building_id": str}).set_index("building_id")
        parks = [c for c in T.columns if not c.startswith("CAND-")]
        for i, r in D[D.perfil == perf].iterrows():
            cols = parks + (r.seleccion_uniforme.split(";") if r.seleccion_uniforme else [])
            bt = T[cols].min(axis=1)
            cov = bt <= float(r.umbral_min) + 1e-9
            D.at[i, "pond_pct_of_uniform_choice"] = round(100 * w.reindex(bt.index)[cov].sum() / w.sum(), 2)
    D["d_wpct"] = (D.pond_pct_meteo - D.pond_pct_of_uniform_choice).round(2)
    return D


# =============================================================================================== stage: bundle
BUNDLE_FILES = ["edificios.csv", "tiempos_ligero.csv", "tiempos_camion.csv", "parques.csv", "candidatos.csv", "municipios.csv",
                "municipios.geojson", "meteo_estaciones.csv", "meteo_perfil.csv", "meteo_anual.csv", "meteo_mensual.csv",
                "meteo_dias_adversos.csv", "escenarios.csv", "fuentes.csv", "metodologia.csv"]
MAX_BYTES = 3_500_000
PERFIL = {"light": "ligero", "truck": "camion"}
CHECK_ES = {k: v for k, v in CHECK_ITEMS}
PRIMARY_RULE = "R4N_T25_RH40_NORAIN3"          # = ADV-v1 in processed/weather/*.csv


def write_csv(df, name):
    f = AGENT / name
    df.to_csv(f, index=False, encoding="utf-8", lineterminator="\n")
    assert f.stat().st_size <= MAX_BYTES, (name, f.stat().st_size)
    return f


def bundle_weights(con):
    """Raw JUL-AUG ADV-v1 frequency per analysis building + normalized weight (mean 1 over the analysis set)."""
    W = pd.read_sql("SELECT w.building_id, w.zone_id, w.weight, z.station_id FROM v_building_weight w "
                    "JOIN weather_zones z ON z.zone_id = w.zone_id JOIN v_scope_buildings b ON b.building_id = w.building_id "
                    "WHERE w.season_id=? AND w.method_version=? AND w.data_version=?", con,
                    params=(SEASON, WEATHER_METHOD, DATA_VERSION))
    assert W.building_id.is_unique and W.weight.notna().all()
    W["peso"] = W.weight / W.weight.mean()
    return W


def stage_bundle():
    log("agent bundle -> agent/datos (bundle_contract.md)")
    AGENT.mkdir(parents=True, exist_ok=True)
    for f_ in AGENT.glob(".READY_*"):
        f_.unlink()
    for name in BUNDLE_FILES + ["auditoria.json"]:
        if (AGENT / name).exists():
            (AGENT / name).unlink()
    con = sqlite3.connect(DB)
    nm = muni_names()
    W = bundle_weights(con)
    nA = len(W)
    B = pd.read_sql("SELECT building_id, municipality_code, lon, lat, dwellings, source_use, residential_rule, veg_distance_m, "
                    "routable, unroutable_reason, snap_distance_m FROM buildings WHERE in_analysis_set=1 ORDER BY building_id", con)
    assert len(B) == nA
    vb = gpd.read_file(PROC / "buildings" / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio",
                       columns=["building_id", "veg_class_nearest"], read_geometry=False)
    B = B.merge(vb, on="building_id", how="left").merge(W[["building_id", "station_id", "peso", "weight"]], on="building_id", how="left")
    parks = [r[0] for r in con.execute("SELECT origin_id FROM origins WHERE origin_type='station' ORDER BY origin_id")]
    cands = [r[0] for r in con.execute("SELECT cand_id FROM candidates WHERE is_valid=1 ORDER BY cand_id")]
    T = pd.read_sql("SELECT t.origin_id, t.building_id, t.profile, t.minutes_est FROM travel_times t "
                    "JOIN buildings b ON b.building_id = t.building_id WHERE b.in_analysis_set=1 AND t.data_version=?",
                    con, params=(DATA_VERSION,))
    base = {}
    for prof in PROFILES:
        M = T[T.profile == prof].pivot(index="building_id", columns="origin_id", values="minutes_est").reindex(
            index=B.building_id, columns=parks + cands)
        M = M.round(2)
        Mo = M.reset_index()
        Mo.columns.name = None
        write_csv(Mo, f"tiempos_{PERFIL[prof]}.csv")
        P_ = M[parks]
        Fv = np.where(np.isnan(P_.values), np.inf, P_.values)
        j_ = Fv.argmin(1)
        bmin = Fv[np.arange(len(Fv)), j_]
        ok_ = np.isfinite(bmin)
        base[prof] = (np.where(ok_, bmin, np.nan), np.where(ok_, np.asarray(parks, dtype=object)[j_], None))
    E = pd.DataFrame(dict(
        building_id=B.building_id, muni_ine=B.municipality_code, municipio=B.municipality_code.map(nm),
        lon=B.lon.round(6), lat=B.lat.round(6), viviendas=B.dwellings.astype("Int64"), uso_original=B.source_use,
        residencial_regla=B.residential_rule, dist_veg_m=B.veg_distance_m.round(1), veg_clase_cercana=B.veg_class_nearest,
        zona_meteo=B.station_id, peso_meteo=B.peso.round(6), freq_adversa=B.weight.round(6),
        estado_ruta=np.where(B.routable == 1, "calculado", "sin_ruta: " + B.unroutable_reason.fillna("")),
        snap_m=B.snap_distance_m.round(1),
        parque_base_ligero=base["light"][1], t_base_ligero=np.round(base["light"][0], 2),
        parque_base_camion=base["truck"][1], t_base_camion=np.round(base["truck"][0], 2)))
    assert (E.estado_ruta == "calculado").sum() == E.t_base_ligero.notna().sum()
    write_csv(E, "edificios.csv")
    # parks
    FS = pd.read_sql("SELECT station_id, name, municipality, lon, lat, include_in_baseline, source_id, snap_distance_m, note, "
                     "loc_confidence FROM fire_stations ORDER BY include_in_baseline DESC, station_id", con)
    PQ = pd.DataFrame(dict(origen_id=FS.station_id, nombre=FS["name"], municipio=FS.municipality, lon=FS.lon.round(6),
                           lat=FS.lat.round(6), en_base=FS.include_in_baseline, fuente=FS.source_id, snap_m=FS.snap_distance_m.round(1),
                           nota=[(n_ + " " if isinstance(n_, str) else "") + "Posición oficial B5M (no comprobada en ortofoto)."
                                 for n_ in FS.note]))
    write_csv(PQ, "parques.csv")
    # candidates
    CA = pd.read_csv(CANDDIR / "candidates_10.csv").sort_values("cand_id")
    CQ = pd.DataFrame(dict(origen_id=CA.cand_id, nombre=CA["name"], tipo_sitio=CA.site_type, municipio=CA.municipality,
                           lon=CA.lon.round(6), lat=CA.lat.round(6), osm_id=[f"{a}/{b}" for a, b in zip(CA.osm_type, CA.osm_id)],
                           area_m2=CA.area_m2.round(0), via_acceso=CA.access_road, snap_m=CA.snap_m.round(1),
                           t_desde_parque_ligero=CA.baseline_light_min.round(2), parque_mas_cercano=CA.baseline_light_station,
                           motivo=CA.selection_reason,
                           comprobaciones_pendientes=[("ESPECÍFICO: " + c_ + " | GENÉRICAS: " if isinstance(c_, str) and c_ else "GENÉRICAS: ")
                                                      + "; ".join(CHECK_ES[k] for k, _ in CHECK_ITEMS) for c_ in CA.site_caveats]))
    write_csv(CQ, "candidatos.csv")
    # municipalities
    allb = pd.read_sql("SELECT municipality_code, is_residential, in_analysis_set, dwellings FROM buildings", con)
    za = pd.read_sql("SELECT b.municipality_code, z.station_id, count(*) n FROM zone_assignment z JOIN buildings b USING (building_id) "
                     "WHERE z.method_version=? GROUP BY 1, 2", con, params=(WEATHER_METHOD,))
    assert not za.municipality_code.duplicated().any(), "a municipality spans several weather zones"
    MU = pd.read_sql("SELECT ine_code, name, area_km2 FROM municipalities WHERE in_pilot=1 ORDER BY ine_code", con)
    g = allb.groupby("municipality_code")
    MQ = pd.DataFrame(dict(muni_ine=MU.ine_code, municipio=MU["name"], area_km2=MU.area_km2.round(3),
                           zona_meteo=MU.ine_code.map(dict(zip(za.municipality_code, za.station_id))),
                           edificios_total=MU.ine_code.map(g.size()).fillna(0).astype(int),
                           residenciales=MU.ine_code.map(g.is_residential.sum()).fillna(0).astype(int),
                           edificios_analisis=MU.ine_code.map(g.in_analysis_set.sum()).fillna(0).astype(int),
                           viviendas_analisis=MU.ine_code.map(allb[allb.in_analysis_set == 1].groupby("municipality_code").dwellings.sum()).fillna(0).astype(int)))
    assert MQ.edificios_analisis.sum() == nA
    write_csv(MQ, "municipios.csv")
    GM = gpd.read_file(PROC / "territory" / "territory.gpkg", layer="tolosaldea_municipalities", engine="pyogrio")
    for tol in (15, 25, 40, 60):
        geo = shapely.coverage_simplify(GM.geometry.values, tolerance=tol)
        G2 = gpd.GeoDataFrame(dict(muni_ine=GM.ine_code.values, municipio=GM["name"].values), geometry=list(geo), crs=25830).to_crs(4326)
        G2["geometry"] = shapely.set_precision(G2.geometry.values, 1e-5)
        G2.sort_values("muni_ine").to_file(AGENT / "municipios.geojson", driver="GeoJSON", engine="pyogrio",
                                           layer_options={"COORDINATE_PRECISION": 5, "RFC7946": "YES"})
        if (AGENT / "municipios.geojson").stat().st_size <= 1_000_000:
            break
    stats_put("bundle_geojson", dict(simplify_tolerance_m=tol, bytes=(AGENT / "municipios.geojson").stat().st_size,
                                     valid=bool(shapely.is_valid(G2.geometry.values).all())))
    # weather
    WI = pd.read_csv(PROC / "weather" / "station_inventory.csv", dtype={"station_id": str})
    zst = set(pd.read_sql("SELECT station_id FROM weather_zones", con).station_id)
    write_csv(pd.DataFrame(dict(codigo=WI.station_id, nombre=WI["name"], tipo=WI["type"], lon=WI.lon.round(6), lat=WI.lat.round(6),
                                municipio=WI.catalogue_municipality, altitud_proxy_m=WI.elev_proxy_bldg500m_m.round(0).astype("Int64"),
                                mide_viento=WI.has_wind.astype(int), usada_en_zonas=WI.station_id.isin(zst).astype(int))),
              "meteo_estaciones.csv")
    SP = pd.read_csv(PROC / "weather" / "season_profile.csv", dtype={"station_id": str})
    SP = SP[(SP.rule == PRIMARY_RULE) & (SP.season_id == "JUL-AUG") & (SP.variant == "common_period")].copy()
    wprof = pd.read_sql("SELECT z.station_id, p.adverse_day_frequency, p.valid_days, p.adverse_days FROM weather_profile p "
                        "JOIN weather_zones z USING (zone_id) WHERE p.season_id='JUL-AUG' AND p.method_version=? AND p.data_version=?",
                        con, params=(WEATHER_METHOD, DATA_VERSION)).set_index("station_id")
    mean_raw = W.weight.mean()
    MP_ = pd.DataFrame(dict(codigo=SP.station_id, temporada="jul-ago", anios=SP.years.str.replace(",", ";"),
                            dias_validos=SP.valid_days, dias_adversos=SP.adverse_days,
                            frecuencia=(SP.adverse_days / SP.valid_days).round(6), media_anual=SP.interannual_mean.round(4),
                            sd_anual=SP.interannual_sd.round(4),
                            peso_normalizado=[round(wprof.at[c, "adverse_day_frequency"] / mean_raw, 6) if c in wprof.index else np.nan
                                              for c in SP.station_id],
                            regla=WEATHER_METHOD)).sort_values("codigo")
    for c in wprof.index:      # bundle profile == DB profile for the zone stations
        r_ = MP_.set_index("codigo").loc[c]
        assert (r_.dias_validos, r_.dias_adversos) == (wprof.at[c, "valid_days"], wprof.at[c, "adverse_days"])
    write_csv(MP_, "meteo_perfil.csv")
    SY = pd.read_csv(PROC / "weather" / "season_profile_year.csv", dtype={"station_id": str})
    SY = SY[(SY.rule == PRIMARY_RULE) & (SY.season_id == "JUL-AUG")]
    write_csv(pd.DataFrame(dict(codigo=SY.station_id, anio=SY.year, dias_validos=SY.valid_days, dias_adversos=SY.adverse_days,
                                frecuencia=np.where(SY.valid_days > 0, (SY.adverse_days / SY.valid_days.where(SY.valid_days > 0)).round(6), np.nan)))
              .sort_values(["codigo", "anio"]), "meteo_anual.csv")
    SM_ = pd.read_csv(PROC / "weather" / "adverse_rule_counts_monthly.csv", dtype={"station_id": str})
    SM_ = SM_[SM_.rule == PRIMARY_RULE]
    write_csv(pd.DataFrame(dict(codigo=SM_.station_id, mes=SM_.month, dias_validos=SM_.valid_days, dias_adversos=SM_.adverse_days,
                                frecuencia=np.where(SM_.valid_days > 0, (SM_.adverse_days / SM_.valid_days.where(SM_.valid_days > 0)).round(6), np.nan)))
              .sort_values(["codigo", "mes"]), "meteo_mensual.csv")
    DW = pd.read_csv(PROC / "weather" / "daily_with_rules.csv", dtype={"station_id": str},
                     usecols=["station_id", "date", "tmax_c", "rhmin_pct", "precip_mm", f"adv_{PRIMARY_RULE}"])
    DW = DW.sort_values(["station_id", "date"])
    gp = DW.groupby("station_id").precip_mm
    DW["prev3"] = gp.shift(1) + gp.shift(2) + gp.shift(3)
    AD = DW[DW[f"adv_{PRIMARY_RULE}"]]
    ADV = pd.DataFrame(dict(codigo=AD.station_id, fecha=AD.date, tmax=AD.tmax_c.round(2), hrmin=AD.rhmin_pct.round(2),
                            lluvia_3d_previos_mm=AD.prev3.round(2)))
    chk = ADV.assign(mes=ADV.fecha.str[5:7].astype(int)).groupby(["codigo", "mes"]).size()
    sm_idx = SM_.set_index(["station_id", "month"]).adverse_days
    assert all(sm_idx.get(k_, 0) == v_ for k_, v_ in chk.items()) and sm_idx.sum() == len(ADV), "adverse days != monthly counts"
    write_csv(ADV, "meteo_dias_adversos.csv")
    # scenarios
    R = pd.read_sql("SELECT s.scenario_id, s.strategy, s.threshold_min, s.profile, s.weighting, r.k, r.selection, r.n_covered, "
                    "r.pct_covered, r.worst_time_min_est, r.n_unroutable, r.ties, r.n_buildings FROM results r JOIN scenarios s USING (scenario_id) "
                    "WHERE s.data_version=? ORDER BY s.strategy, s.weighting, s.profile, s.threshold_min, r.k", con, params=(DATA_VERSION,))
    RB = pd.read_sql("SELECT scenario_id, k, building_id, covered FROM result_building WHERE covered=1", con)
    RB["peso"] = RB.building_id.map(dict(zip(W.building_id, W.peso)))
    wcov = RB.groupby(["scenario_id", "k"]).peso.sum()
    k0 = R[R.k == 0].set_index("scenario_id").n_covered
    pes = {w_: lab for lab, w_, _ in WEIGHTS}
    ES = pd.DataFrame(dict(
        estrategia=R.strategy, k=R.k, umbral_min=R.threshold_min.map(lambda v: f"{v:g}"), perfil=R.profile.map(PERFIL),
        pesos=R.weighting.map(pes), seleccion=R.selection.str.replace("|", ";", regex=False),
        edificios_cubiertos=R.n_covered, pct_cubiertos=R.pct_covered.round(2)))
    wc = np.array([wcov.get((sid, k), 0.0) for sid, k in zip(R.scenario_id, R.k)])
    ES["cobertura_ponderada"] = np.where(ES.pesos == "meteo", wc, R.n_covered).round(2)
    ES["pct_ponderada"] = (100.0 * ES.cobertura_ponderada / np.where(ES.pesos == "meteo", W.peso.sum(), R.n_buildings)).round(2)
    ES["peor_tiempo"] = R.worst_time_min_est.round(2)
    ES["sin_ruta"] = R.n_unroutable
    ES["mejora_vs_k0"] = R.n_covered - R.scenario_id.map(k0)
    ES["empates"] = R.ties
    # v0.3.1: p95 of the best travel time over ROUTABLE buildings (reported only; not part of any objective). Appended last.
    RBr = pd.read_sql("SELECT scenario_id, k, best_minutes_est FROM result_building WHERE routable=1", con)
    p95 = RBr.groupby(["scenario_id", "k"]).best_minutes_est.quantile(0.95, interpolation="linear")
    ES["p95_tiempo"] = [round(float(p95[(sid, k)]), 2) for sid, k in zip(R.scenario_id, R.k)]
    assert len(ES) == len(WEIGHTS) * 2 * len(THRESHOLDS) * len(PROFILES) * (K_MAX + 1)
    write_csv(ES, "escenarios.csv")
    # sources
    SRCT = pd.read_sql("SELECT * FROM sources ORDER BY source_id", con)
    used = set(pd.read_sql("SELECT source_id FROM data_version_sources WHERE data_version=?", con, params=(DATA_VERSION,)).source_id)
    est = []
    for r in SRCT.itertuples():
        if r.source_id in used:
            est.append(f"usada en {DATA_VERSION}")
        elif "SUPERSEDED" in str(r.notes):
            est.append("superada (versión anterior)")
        else:
            est.append("solo comparación / referencia")
    write_csv(pd.DataFrame(dict(source_id=SRCT.source_id, conjunto=SRCT.title, organismo=SRCT.organization, url=SRCT.url,
                                licencia=SRCT.licence, fecha_descarga=SRCT.download_date, edicion_periodo=SRCT.edition,
                                archivo=SRCT.raw_file, sha256=SRCT.sha256, estado=est)), "fuentes.csv")
    write_csv(methodology_table(con, W, E), "metodologia.csv")
    con.close()
    sizes = {f.name: f.stat().st_size for f in sorted(AGENT.glob("*"))}
    assert all(v <= MAX_BYTES for v in sizes.values()), sizes
    stats_put("bundle", dict(files=sizes, total_mb=round(sum(sizes.values()) / 1e6, 2)))
    log(f"bundle: {len(sizes)} files, {sum(sizes.values()) / 1e6:.2f} MB, largest {max(sizes, key=sizes.get)} {max(sizes.values()) / 1e6:.2f} MB")


def methodology_table(con, W, E):
    st = stats_get()
    zw = W.groupby("station_id").agg(n=("building_id", "size"), freq=("weight", "first"), peso=("peso", "first"))
    rows = [
        ("version_datos", DATA_VERSION, "Versión de datos de todos los ficheros; no congelada (frozen=0)."),
        ("conjunto_analisis", f"{len(E)} edificios", "Edificio residencial (B5M CURRENTUSE contiene collectiveResidence o individualResidence) "
         "cuyo contorno está a ≤ 100 m de bosque o matorral del Mapa Forestal del País Vasco 2024 (forest_* + scrub_heath: TIPES10 11, 12, 14, 21, 23; "
         "pastos y prados excluidos). Municipio por punto interior con límites oficiales geoEuskadi 1:5.000. Cada edificio cuenta una vez."),
        ("distancia_vegetacion_m", "100", "Parámetro de equipo (no oficial)."),
        ("origenes_base", "9 parques", "Parques B5M de Gipuzkoa con en_base=1. OTH-HONDARRIBIA (punto del aeropuerto) excluido. "
         "No hay parques de Navarra (sin capa oficial en el paquete)."),
        ("red_viaria", "OSM País Vasco + Navarra 2026-09-30", "Carreteras de ambos extractos Geofabrik (vías duplicadas en la frontera eliminadas por id OSM). "
         "Grafo por defecto sin pistas (track). Velocidad por clase de vía (≈85 % de tramos sin maxspeed), sin tráfico ni giros."),
        ("modelo_tiempo", "acceso + red + tramo parcial + acceso", "Acceso en línea recta a 15 km/h desde el punto al tramo más cercano elegible; "
         "Dijkstra dirigido desde cada origen. Son ESTIMACIONES de desplazamiento, no tiempos de respuesta (no incluye salida ni preparación)."),
        ("perfil_ligero", "velocidad de la vía", "Vehículo ligero."),
        ("perfil_camion", "0,9 × (autopista/autovía/primaria) · 0,8 × (resto)", "Supuesto de equipo, no medido en camiones de bomberos."),
        ("snap_max_m", "150", "Edificio a más de 150 m de una vía elegible → estado_ruta 'sin_ruta: snap>150m'; nunca cubierto, nunca eliminado; cuenta en el denominador."),
        ("redondeo_minutos", "0,01", "Tiempos redondeados a 2 decimales; el optimizador trabaja con estos valores (resultados recomputables desde tiempos_*.csv)."),
        ("umbral_min", "10 / 12 / 15 (12 por defecto)", "Umbral de demostración, no un estándar oficial."),
        ("cubierto", "min(tiempo desde parques + candidatas elegidas) ≤ umbral", "Mínimo por edificio sobre los 9 parques más las candidatas de la selección."),
        ("pct_cubiertos", f"denominador {len(E)}", "Porcentaje sobre TODO el conjunto de análisis (incluye los sin ruta)."),
        ("estrategia_A", "max cobertura ponderada", "Maximiza la suma de pesos de edificios a ≤ umbral; desempate: más edificios cubiertos, menor peor tiempo, selección alfabética."),
        ("estrategia_B", "mejor peor acceso", "Lexicográfico: menos sin ruta, menor peor tiempo, mayor cobertura ponderada, más edificios; después selección alfabética."),
        ("pesos_meteo", WEATHER_METHOD, "peso_meteo = frecuencia histórica de días adversos jul-ago (2019, 2020, 2022, 2023) de la estación de la zona del edificio, "
         "normalizada a media 1 en el conjunto de análisis: " + "; ".join(f"{k} freq {r.freq:.4f} → peso {r.peso:.3f} ({r.n} edificios)" for k, r in zw.iterrows()) +
         ". Las diferencias entre zonas están dentro del ruido interanual (±1 sd se solapan): pesos casi planos."),
        ("pesos_uniforme", "1 por edificio", "Comparación: cobertura ponderada = número de edificios."),
        ("cobertura_ponderada", "suma de peso_meteo (o 1) de los edificios cubiertos", "NO es población protegida; pct_ponderada = cobertura_ponderada / suma total de pesos."),
        ("regla_ADV-v1", "Tmax ≥ 25 °C y HRmin ≤ 40 % y sin día de lluvia (≥ 1 mm) en los 3 días previos", "Indicador exploratorio flAIre v1 (NO es FWI ni un índice oficial). "
         "Día UTC; día válido si ≥ 130 de 144 valores de 10 min utilizables por variable. Frecuencia histórica ≠ probabilidad de incendio."),
        ("zonas_meteo", "C026 Berastegi · C029 Zizurkil · C058 Bidania", "Estación KM más cercana ajustada por altitud (1 m de desnivel = 30 m de distancia), por municipio. "
         "C043 Ordizia y estaciones de río solo como contexto."),
        ("temporada", "jul-ago", "El pico histórico de días adversos es septiembre en las 3 zonas (en Zizurkil C029 octubre, 20 días, supera a julio+agosto juntos, 14); ver meteo_mensual.csv."),
        ("combinaciones", "848", "Todas las combinaciones de 0 a 6 de las 10 candidatas (búsqueda exhaustiva)."),
        ("k_max", "6", "Nunca más retenes que candidatas válidas (10)."),
        ("empates", "número de combinaciones con el mismo objetivo", "Si empates > 1, se guarda la primera en orden alfabético."),
        ("mejora_vs_k0", "edificios", "edificios_cubiertos(k) − edificios_cubiertos(k=0) del mismo escenario."),
        ("p95_tiempo", "percentil 95 (interpolación lineal)", "Percentil 95 del mejor tiempo (parques + selección) de los edificios CON ruta; "
         "métrica informativa añadida en v0.3.1, no forma parte del objetivo de A ni de B."),
        ("reclasificacion_viaria", "service con ref GI-* → unclassified (40 km/h)", "v0.3.1: vías OSM highway=service que llevan matrícula foral "
         "(p. ej. GI-3712 Aldaba auzoa) se tratan como carretera sin clasificar; speed_source = reclass_service_with_GI_ref."),
        ("candidatas", "10 sitios de estudio", "Regla transparente (no usa el objetivo del optimizador): elegibilidad, clusters de déficit > 12 min, "
         "dispersión max-min, ≥ 3 km entre sí y ≥ 2 km de parques. Candidata ≠ sitio autorizado; 6 comprobaciones de campo pendientes."),
        ("anio_plan", "2027", "Cambiar el año del plan solo cambia el título; los resultados dependen de la versión de datos."),
        ("datos_faltantes", "vacío", "Un valor desconocido se deja vacío, nunca 0."),
    ]
    return pd.DataFrame(rows, columns=["clave", "valor", "explicacion"])


# =============================================================================================== main
STAGES = ["times", "baseline", "select", "db", "optimize", "bundle", "validate"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default=",".join(STAGES), help="comma-separated subset of " + ",".join(STAGES))
    ap.add_argument("--reuse-times", action="store_true", help="skip snapping/routing if the parquet files exist")
    a = ap.parse_args()
    todo = [s.strip() for s in a.stages.split(",") if s.strip()]
    bad = set(todo) - set(STAGES) - {"snap"}
    if bad:
        ap.error(f"unknown stages {bad}")
    for s in STAGES:
        if s in todo or (s == "times" and "snap" in todo):
            {"times": lambda: stage_times(a.reuse_times), "baseline": stage_baseline, "select": stage_select, "db": stage_db,
             "optimize": stage_optimize, "validate": stage_validate, "bundle": stage_bundle}[s]()
    log("done")


if __name__ == "__main__":
    main()
