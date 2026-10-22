#!/usr/bin/env python3
"""
flAIre · Persona 4 · v0.3 — road network, fire stations and candidate pool (Tolosaldea pilot).

Re-runnable:  python3 code/network.py        (≈ 4–5 min, ~4 GB RAM peak)

v0.3: roads are read from TWO Geofabrik extracts (País Vasco + Navarra, same OSM snapshot 2026-09-30T20:22:42Z).
Ways present in both files (border buffer) are de-duplicated by OSM way id (the País Vasco copy is kept; node ids are
OSM ids, so the two extracts join at shared nodes). Same inclusion / speed / topology rules as v0.2. POIs, places and
CAPV admin polygons are read from the País Vasco file only (the candidate pool is unchanged; pool ids are kept stable
across versions by OSM identity). Navarra admin_level=8 polygons (INE 31xxx) give an exact NAV region flag.
No Navarra fire station is loaded (no official source in the package): Navarra roads are used for routing only.

Inputs  (raw/, never modified)
  pais-vasco-260930.osm.pbf       Geofabrik País Vasco, OSM snapshot 2026-09-30T20:22:42Z (ODbL)
  navarra-latest.osm.pbf          Geofabrik Navarra, OSM snapshot 2026-09-30T20:22:42Z (ODbL), md5 daaa7be9869a50e2e600cd20f6ed236f
  GFA_DSET_FIREST.gpkg (+ _es.csv) B5M / Diputación Foral de Gipuzkoa fire stations (10 points)
  persona4_accesos_bomberos/processed/*  v0.1 outputs (only for comparison)
  basque_country_readable.csv     OSM amenities (pyrosm) — only used to confirm v0.1 POI types

Outputs (processed/network/)
  roads.gpkg               layers road_edges, road_nodes, dropped_components (EPSG:25830)
  graph_arcs.parquet       directed arcs for routing (u_idx, v_idx, length_m, t_light_s, t_truck_s, flags)
  graph_nodes.parquet      node index (idx, node_id = OSM node id, x, y, lon, lat, SCC flags)
  fire_stations.gpkg/.geojson/.csv
  candidate_pool.gpkg/.csv/.geojson
  v01_candidates_reevaluated.csv
  validation_routes.csv, station_relevance.csv, dropped_components.csv
  network_stats.json       every number used in reports/quality_network.md
Also writes reports/quality_network.md and upserts this package's rows in reports/sources.csv.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import osmium
from importlib.metadata import version as _pkg_version
PYOSMIUM_VERSION = _pkg_version("osmium")
import pandas as pd
import geopandas as gpd
import shapely
import shapely.ops
from pyproj import Transformer
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

T0 = time.time()
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
OUT = ROOT / "processed" / "network"
REP = ROOT / "reports"
OUT.mkdir(parents=True, exist_ok=True)
REP.mkdir(parents=True, exist_ok=True)

PBF = RAW / "pais-vasco-260930.osm.pbf"
PBF_NAV = RAW / "navarra-latest.osm.pbf"
FIREST = RAW / "GFA_DSET_FIREST.gpkg"
V01 = RAW / "persona4_accesos_bomberos" / "processed"
SRC_OSM = "SRC-OSM-GEOFABRIK-PV-20260930"
SRC_NAV = "SRC-OSM-GEOFABRIK-NAV-20260930"
SRC_B5M = "SRC-B5M-FIREST"
DATA_VERSION = "v0.3"
V02_DIR = OUT / "v0.2"          # frozen copy of the v0.2 csv/json outputs (comparison + stable pool ids)

TO_UTM = Transformer.from_crs(4326, 25830, always_xy=True)
TO_WGS = Transformer.from_crs(25830, 4326, always_xy=True)

# Tolosaldea study bbox for the candidate pool (WGS84)
BB_W, BB_E, BB_S, BB_N = -2.25, -1.90, 42.98, 43.24
BB_MARGIN = 0.01  # collect features slightly beyond the bbox (nearest-parking etc.)

TOLOSALDEA = ["Abaltzisketa", "Aduna", "Albiztur", "Alegia", "Alkiza", "Altzo", "Amezketa", "Anoeta",
              "Asteasu", "Baliarrain", "Belauntza", "Berastegi", "Berrobi", "Bidania-Goiatz", "Elduain",
              "Gaztelu", "Hernialde", "Ibarra", "Ikaztegieta", "Irura", "Larraul", "Leaburu", "Lizartza",
              "Orendain", "Orexa", "Tolosa", "Amasa-Villabona", "Zizurkil"]

OSM_NAME_TO_OFFICIAL = {"Villabona": "Amasa-Villabona"}   # OSM admin8 name -> official (PTP) name


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)

# ----------------------------------------------------------------------------- road rules
ROAD_CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
                "residential", "living_street", "service"]
TRACK = "track"
BASE_SPEED = {"motorway": 100, "trunk": 80, "primary": 70, "secondary": 60, "tertiary": 50,
              "unclassified": 40, "residential": 30, "living_street": 15, "service": 15, "track": 10}
LINK_FACTOR = 0.6
for _p in ["motorway", "trunk", "primary", "secondary", "tertiary"]:
    BASE_SPEED[_p + "_link"] = BASE_SPEED[_p] * LINK_FACTOR
HIGH_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}
TRUCK_FACTOR_HIGH, TRUCK_FACTOR_LOW = 0.9, 0.8          # truck profile
NO_SNAP_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link"}  # never snap a site onto these
SERVICE_EXCLUDED = {"parking_aisle", "drive-through", "slipway"}
NO_ACCESS = {"private", "no"}
ACCESS_OVERRIDE_OK = {"yes", "designated", "permissive", "destination"}
EXCL_ACCESS_ROAD_ONLY = {"bus"}  # access=bus -> bus-only street
WAY_TAGS = ["highway", "name", "ref", "oneway", "maxspeed", "access", "motor_vehicle", "motorcar",
            "vehicle", "junction", "surface", "tracktype", "service", "hgv", "emergency", "fire_engine",
            "area"]


def parse_maxspeed(v):
    """km/h or None. Handles '50', '30 mph', 'ES:urban', 'walk', 'a;b' (min)."""
    if v is None:
        return None
    vals = []
    for part in str(v).split(";"):
        p = part.strip().lower()
        if not p:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh)?$", p)
        if m:
            x = float(m.group(1)) * (1.609 if m.group(2) == "mph" else 1.0)
            if x > 0:
                vals.append(x)
            continue
        z = {"es:urban": 50, "es:rural": 90, "es:motorway": 120, "es:trunk": 100, "es:living_street": 20,
             "es:zone30": 30, "es:zone20": 20, "walk": 6}
        if p in z:
            vals.append(z[p])
    return min(vals) if vals else None


GI_REF_RX = re.compile(r"^GI-")      # Gipuzkoa foral road numbers (GI-xxxx)


def way_decision(t):
    """Return (fclass or None, exclusion_reason or None, access_flag)."""
    h = t.get("highway")
    if h not in ROAD_CLASSES and h != TRACK:
        return None, None, None
    if h == "service" and GI_REF_RX.match(t.get("ref") or ""):
        h = "unclassified"            # v0.3.1: foral road number on a service way = mis-tagged road (judge review)
    if t.get("area") == "yes":
        return h, "area_highway", None
    if h == "service" and t.get("service") in SERVICE_EXCLUDED:
        return h, "service_" + t.get("service"), None
    acc = t.get("access")
    mv = t.get("motor_vehicle") or t.get("motorcar") or t.get("vehicle")
    emerg = t.get("emergency") in ("yes", "designated") or t.get("fire_engine") in ("yes", "designated")
    if acc in NO_ACCESS and not (emerg or mv in ACCESS_OVERRIDE_OK):
        return h, "access_" + acc, None
    if acc is None and mv in NO_ACCESS and not emerg:
        return h, "motor_vehicle_" + mv, None
    if acc in EXCL_ACCESS_ROAD_ONLY and not (emerg or mv in ACCESS_OVERRIDE_OK):
        return h, "access_bus", None
    flag = None
    if acc in NO_ACCESS:
        flag = "override_" + ("emergency" if emerg else "motor_vehicle")
    elif acc not in (None, "yes"):
        flag = "conditional_" + acc  # destination, customers, forestry, agricultural, permit, ...
    elif mv not in (None, "yes"):
        flag = "conditional_mv_" + str(mv)
    return h, None, flag


def oneway_code(t, h):
    """F (digitised direction), T (reverse), B (both)."""
    ow = t.get("oneway")
    if ow in ("yes", "true", "1"):
        return "F"
    if ow in ("-1", "reverse"):
        return "T"
    if ow in ("no", "false", "0", "reversible", "alternating"):
        return "B"
    if t.get("junction") in ("roundabout", "circular"):
        return "F"
    if h in ("motorway", "motorway_link"):  # OSM: oneway implied on motorways (and their ramps)
        return "F"
    return "B"


# ----------------------------------------------------------------------------- 0. read PBF once
POI_AREA_KEYS = ("amenity", "landuse", "leisure", "tourism", "office", "sport", "boundary", "building",
                 "operator", "name")
DFG_RX = re.compile(r"foru aldundi|diputaci[oó]n foral|bidezain|camineros", re.I)
REC_RX = re.compile(r"[áa]rea recreativa|atseden|aisialdi", re.I)


def interesting_poi(tg):
    a, l, le, tu, of = (tg.get(k) for k in ("amenity", "landuse", "leisure", "tourism", "office"))
    if a in ("parking", "community_centre", "shelter", "fire_station"):
        return True
    if le in ("sports_centre", "picnic_table", "picnic_site", "recreation_ground") or tu in ("picnic_site", "picnic_table"):
        return True
    if l in ("industrial", "depot", "recreation_ground"):
        return True
    if of == "government" or tg.get("sport") == "basque_pelota" or tg.get("highway") == "trailhead":
        return True
    s = " ".join(str(tg.get(k, "")) for k in ("name", "name:es", "name:eu", "operator"))
    if (DFG_RX.search(s) and a != "charging_station") or REC_RX.search(s):
        return True
    return False


def in_bb(lon, lat, m=BB_MARGIN):
    return (BB_W - m) <= lon <= (BB_E + m) and (BB_S - m) <= lat <= (BB_N + m)


def read_pbf():
    ways, places, pois, admin = [], [], [], []
    wkb = osmium.geom.WKBFactory()
    fp = (osmium.FileProcessor(str(PBF)).with_locations()
          .with_areas(osmium.filter.KeyFilter(*POI_AREA_KEYS)))
    for o in fp:
        if o.is_way():
            t = o.tags
            h = t.get("highway")
            if h in ROAD_CLASSES or h == TRACK:
                refs, lon, lat = [], [], []
                ok = True
                for n in o.nodes:
                    if not n.location.valid():
                        ok = False
                        continue
                    refs.append(n.ref); lon.append(n.location.lon); lat.append(n.location.lat)
                if len(refs) >= 2:
                    ways.append((o.id, {k: t.get(k) for k in WAY_TAGS if k in t},
                                 np.array(refs, np.int64), np.array(lon), np.array(lat), ok))
        elif o.is_node():
            t = o.tags
            if not t:
                continue
            loc = o.location
            if not loc.valid():
                continue
            if t.get("place") in ("city", "town", "village", "hamlet", "suburb", "neighbourhood", "locality") and "name" in t:
                places.append((o.id, t.get("place"), t.get("name"), loc.lon, loc.lat))
            if in_bb(loc.lon, loc.lat) and interesting_poi(t):
                pois.append(("node", o.id, dict(t), shapely.Point(loc.lon, loc.lat)))
        elif o.is_area():
            t = o.tags
            if t.get("boundary") == "administrative" and t.get("admin_level") in ("6", "8"):
                try:
                    g = shapely.from_wkb(wkb.create_multipolygon(o))
                except Exception:
                    continue
                admin.append(dict(admin_level=t.get("admin_level"), name=t.get("name"),
                                  ine=t.get("ine:municipio"), insee=t.get("ref:INSEE"),
                                  osm_rel=o.orig_id() if not o.from_way() else None, geometry=g))
                continue
            if not interesting_poi(t):
                continue
            try:
                ring = next(iter(o.outer_rings()))
                n0 = ring[0]
                if not in_bb(n0.lon, n0.lat, 0.03):
                    continue
                g = shapely.from_wkb(wkb.create_multipolygon(o))
            except Exception:
                continue
            pois.append(("way" if o.from_way() else "relation", o.orig_id(), dict(t), g))
    return ways, places, pois, admin


def read_pbf_nav():
    """Navarra extract: highway ways (with node locations) + admin_level=8 polygons only."""
    nways, nadmin = [], []
    wkb = osmium.geom.WKBFactory()
    fp = osmium.FileProcessor(str(PBF_NAV)).with_locations().with_areas(osmium.filter.KeyFilter("boundary"))
    for o in fp:
        if o.is_way():
            t = o.tags
            h = t.get("highway")
            if h in ROAD_CLASSES or h == TRACK:
                refs, lon, lat = [], [], []
                ok = True
                for n in o.nodes:
                    if not n.location.valid():
                        ok = False
                        continue
                    refs.append(n.ref); lon.append(n.location.lon); lat.append(n.location.lat)
                if len(refs) >= 2:
                    nways.append((o.id, {k: t.get(k) for k in WAY_TAGS if k in t},
                                  np.array(refs, np.int64), np.array(lon), np.array(lat), ok))
        elif o.is_area():
            t = o.tags
            if t.get("boundary") == "administrative" and t.get("admin_level") == "8":
                try:
                    g = shapely.from_wkb(wkb.create_multipolygon(o))
                except Exception:
                    continue
                nadmin.append(dict(admin_level="8", name=t.get("name"), ine=t.get("ine:municipio"),
                                   insee=t.get("ref:INSEE"), osm_rel=None, geometry=g))
    return nways, nadmin


log("reading PBF", PBF.name)
ways, places_raw, pois_raw, admin_raw = read_pbf()
log(f"road/track ways {len(ways):,}  places {len(places_raw):,}  POI objects {len(pois_raw):,}  admin areas {len(admin_raw)}")
log("reading PBF", PBF_NAV.name)
ways_nav, admin_nav = read_pbf_nav()
log(f"Navarra extract: road/track ways {len(ways_nav):,}, admin8 areas {len(admin_nav)}")
# de-duplicate ways present in both extracts (Geofabrik border buffers overlap): keep the País Vasco copy
_pv_pos = {w[0]: i for i, w in enumerate(ways)}
nav_stats = dict(ways_read_nav=len(ways_nav), ways_read_pv=len(ways), dup_identical=0, dup_different_nodes=0,
                 dup_different_tags=0, added_from_nav=0)
way_src = [SRC_OSM] * len(ways)
for w in ways_nav:
    i = _pv_pos.get(w[0])
    if i is None:
        ways.append(w); way_src.append(SRC_NAV); nav_stats["added_from_nav"] += 1
        continue
    same_nodes = np.array_equal(ways[i][2], w[2])
    if same_nodes and ways[i][1] == w[1]:
        nav_stats["dup_identical"] += 1
    else:
        nav_stats["dup_different_nodes"] += int(not same_nodes)
        nav_stats["dup_different_tags"] += int(ways[i][1] != w[1])
nav_stats["dup_total"] = nav_stats["ways_read_nav"] - nav_stats["added_from_nav"]
del ways_nav, _pv_pos
way_src = np.array(way_src)
log(f"merged ways {len(ways):,}: {nav_stats}")

admin = gpd.GeoDataFrame(admin_raw, crs=4326)
admin_utm = admin.to_crs(25830)
gip = admin_utm[(admin_utm.admin_level == "6") & (admin_utm.name == "Gipuzkoa")].geometry.union_all()
ara = admin_utm[(admin_utm.admin_level == "6") & (admin_utm.name.str.startswith("Araba"))].geometry.union_all()
m8 = admin_utm[admin_utm.admin_level == "8"].copy()
m8["ine2"] = m8.ine.str[:2]
m8_capv = m8[m8.ine2.isin(["01", "20", "48"])].reset_index(drop=True)
m8_capv["name"] = m8_capv.name.replace(OSM_NAME_TO_OFFICIAL)
_missing = sorted(set(TOLOSALDEA) - set(m8_capv.name))
log("Tolosaldea municipalities not found among OSM admin8 names:", _missing)
m8_other = m8[m8.ine2.isin(["09", "26", "39"]) | m8.insee.notna()].reset_index(drop=True)
# Navarra extract: INE 31xxx = Navarra municipalities (exact NAV region); Aragón/La Rioja/France fragments -> OTHER
an = gpd.GeoDataFrame(admin_nav, crs=4326).to_crs(25830)
an["ine2"] = an.ine.str[:2]
m8_nav = an[an.ine2 == "31"].reset_index(drop=True)
m8_other = pd.concat([m8_other, an[an.ine2.isin(["22", "26", "50", "09"]) | an.insee.notna()]], ignore_index=True)
nav_stats["navarra_admin8_polygons"] = int(len(m8_nav))
log(f"admin8 polygons: CAPV {len(m8_capv)}, Navarra {len(m8_nav)} (from the Navarra extract), other regions {len(m8_other)}")

# ----------------------------------------------------------------------------- 1. road graph
stats = {"input": {}, "rules": {}, "graph": {}}
all_lon = np.concatenate([w[3] for w in ways]); all_lat = np.concatenate([w[4] for w in ways])
X, Y = TO_UTM.transform(all_lon, all_lat)
offs = np.cumsum([0] + [len(w[2]) for w in ways])

excl = Counter(); excl_km = Counter(); kept_idx = []; decisions = []
way_len = np.zeros(len(ways))
for i, (wid, t, refs, lo, la, ok) in enumerate(ways):
    a, b = offs[i], offs[i + 1]
    way_len[i] = np.hypot(np.diff(X[a:b]), np.diff(Y[a:b])).sum()
    h, reason, flag = way_decision(t)
    decisions.append((h, reason, flag))
    if reason:
        excl[reason] += 1; excl_km[reason] += way_len[i] / 1000
    else:
        kept_idx.append(i)
hw_counts = Counter(w[1].get("highway") for w in ways)
stats["input"]["ways_by_highway"] = dict(hw_counts)
stats["input"]["ways_incomplete_locations"] = int(sum(1 for w in ways if not w[5]))
stats["rules"]["excluded_ways"] = {k: [excl[k], round(excl_km[k], 1)] for k in excl}
log(f"kept ways {len(kept_idx):,} / {len(ways):,}; excluded {dict(excl)}")

# node usage count over kept ways (consecutive duplicates removed)
clean = {}
for i in kept_idx:
    a, b = offs[i], offs[i + 1]
    refs = ways[i][2]
    keep = np.ones(len(refs), bool); keep[1:] = refs[1:] != refs[:-1]
    clean[i] = (refs[keep], X[a:b][keep], Y[a:b][keep])
all_refs = np.concatenate([clean[i][0] for i in kept_idx])
uniq, cnt = np.unique(all_refs, return_counts=True)
shared = set(uniq[cnt >= 2].tolist())
node_xy = {}
edges = []  # dict rows
extra_nodes = 0
for i in kept_idx:
    wid, t, *_ = ways[i]
    refs, xs, ys = clean[i]
    if len(refs) < 2:
        continue
    h, _, flag = decisions[i]
    isnode = np.array([r in shared for r in refs.tolist()]); isnode[0] = isnode[-1] = True
    cut = list(np.flatnonzero(isnode))
    # split loops (u == v) at an interior vertex so that u <> v always holds
    k = 0
    while k < len(cut) - 1:
        s, e = cut[k], cut[k + 1]
        if refs[s] == refs[e]:
            if e - s >= 2:
                cut.insert(k + 1, (s + e) // 2); extra_nodes += 1
                continue
            else:  # 1-step self loop: impossible after duplicate removal
                k += 1; continue
        k += 1
    ow = oneway_code(t, h)
    ms = parse_maxspeed(t.get("maxspeed"))
    for s, e in zip(cut[:-1], cut[1:]):
        u, v = int(refs[s]), int(refs[e])
        if u == v:
            continue
        cx, cy = xs[s:e + 1], ys[s:e + 1]
        L = float(np.hypot(np.diff(cx), np.diff(cy)).sum())
        node_xy[u] = (cx[0], cy[0]); node_xy[v] = (cx[-1], cy[-1])
        edges.append(dict(osm_id=str(wid), source_id=way_src[i], u=u, v=v, fclass=h, fclass_osm=t.get("highway"), oneway=ow, length_m=max(L, 0.1),
                          maxspeed_osm=ms, name=t.get("name"), ref=t.get("ref"), access=t.get("access"),
                          motor_vehicle=t.get("motor_vehicle"), junction=t.get("junction"),
                          surface=t.get("surface"), tracktype=t.get("tracktype"), service=t.get("service"),
                          hgv=t.get("hgv"), emergency=t.get("emergency"), access_flag=flag,
                          coords=np.column_stack([cx, cy])))
E = pd.DataFrame(edges)
del edges
log(f"edges {len(E):,} from {len(kept_idx):,} ways; loop-split extra nodes {extra_nodes}")

# speeds
cls = E.fclass.map(BASE_SPEED).astype(float)
ms = E.maxspeed_osm.astype(float)
E["speed_class_kmh"] = cls
E["speed_used_kmh"] = np.where(ms.notna(), np.minimum(ms, cls), cls)
E["speed_source"] = np.where(ms.notna(), "osm_maxspeed_capped", "class_assumed")
reclass = (E.fclass_osm == "service") & (E.fclass == "unclassified")
E.loc[reclass, "speed_source"] = "reclass_service_with_GI_ref"
reclass_stats = dict(edges=int(reclass.sum()), km=round(float(E.length_m[reclass].sum() / 1000), 3),
                     ways=int(E.osm_id[reclass].nunique()), with_maxspeed=int((reclass & ms.notna()).sum()),
                     list=E[reclass].groupby(["osm_id", "ref"]).agg(name=("name", "first"), surface=("surface", "first"),
                                                                    n_edges=("length_m", "size"), km=("length_m", lambda x: round(x.sum() / 1000, 3)))
                     .reset_index().to_dict("records"))
log(f"service ways with GI- ref reclassified to unclassified: {reclass_stats['edges']} edges, {reclass_stats['km']} km, {reclass_stats['ways']} ways")
n_clamped = int((E.speed_used_kmh < 5).sum())
E["speed_used_kmh"] = E.speed_used_kmh.clip(lower=5)
E["speed_truck_kmh"] = E.speed_used_kmh * np.where(E.fclass.isin(HIGH_CLASSES), TRUCK_FACTOR_HIGH, TRUCK_FACTOR_LOW)
E["t_light_s"] = E.length_m / (E.speed_used_kmh / 3.6)
E["t_truck_s"] = E.length_m / (E.speed_truck_kmh / 3.6)
E["is_track"] = (E.fclass == TRACK).astype(int)

# geometry + region
_cc = np.concatenate(E.coords.values)
_ii = np.repeat(np.arange(len(E)), [len(c) for c in E.coords.values])
E["geometry"] = shapely.linestrings(_cc, indices=_ii)
E = E.drop(columns=["coords"])
mid = shapely.line_interpolate_point(E.geometry.values, 0.5, normalized=True)
E["in_gipuzkoa"] = shapely.within(mid, gip).astype(int)
tree = shapely.STRtree(m8_capv.geometry.values)
in_capv = np.zeros(len(E), bool); in_capv[np.unique(tree.query(mid, predicate="within")[0])] = True
in_capv |= E.in_gipuzkoa.values.astype(bool) | shapely.within(mid, ara)
tree_o = shapely.STRtree(m8_other.geometry.values)
in_other = np.zeros(len(E), bool); in_other[np.unique(tree_o.query(mid, predicate="within")[0])] = True
tree_n = shapely.STRtree(m8_nav.geometry.values)
in_nav = np.zeros(len(E), bool); in_nav[np.unique(tree_n.query(mid, predicate="within")[0])] = True
mlon, mlat = TO_WGS.transform(shapely.get_x(mid), shapely.get_y(mid))
# exact polygons first (CAPV, Navarra INE 31, other regions); heuristic only for midpoints in no polygon
region = np.where(in_capv, "PV", np.where(in_nav, "NAV", np.where(in_other, "OTHER",
                  np.where((mlon > -2.42) & (mlon < -1.0) & ~((mlat > 43.30) & (mlon > -1.80)), "NAV", "OTHER"))))
E["region"] = region
E["region_rule"] = np.where(in_capv | in_nav | in_other, "polygon", "heuristic")
nav_stats["region_by_rule_km"] = E.groupby(["region", "region_rule"]).length_m.sum().div(1000).round(1).reset_index().to_dict("records")
nav_stats["edges_by_source"] = E.groupby("source_id").agg(n=("length_m", "size"), km=("length_m", lambda s_: round(s_.sum() / 1000, 1))).reset_index().to_dict("records")
reg_stats = E.groupby("region").agg(n=("length_m", "size"), km=("length_m", lambda s: s.sum() / 1000)).round(1)
stats["graph"]["region_edges_km"] = reg_stats.reset_index().to_dict("records")
log("region split:", reg_stats.to_dict())
# OTHER (La Rioja, Burgos, Cantabria, France fragments of the extract) is KEPT for connectivity
# (e.g. Rioja Alavesa and Karrantza are only connected through them); irrelevant for Tolosaldea.
E["edge_id"] = np.arange(1, len(E) + 1)

# nodes
nid = np.unique(np.concatenate([E.u.values, E.v.values]))
idx_of = pd.Series(np.arange(len(nid)), index=nid)
E["u_idx"] = idx_of.loc[E.u.values].values
E["v_idx"] = idx_of.loc[E.v.values].values
nx_ = np.array([node_xy[n][0] for n in nid]); ny_ = np.array([node_xy[n][1] for n in nid])
N = pd.DataFrame(dict(idx=np.arange(len(nid)), node_id=nid, x=nx_, y=ny_))
N["lon"], N["lat"] = TO_WGS.transform(N.x.values, N.y.values)

# directed arcs
fw = E.oneway.isin(["F", "B"]).values; bw = E.oneway.isin(["T", "B"]).values
A = pd.concat([
    pd.DataFrame(dict(edge_id=E.edge_id[fw], u_idx=E.u_idx[fw], v_idx=E.v_idx[fw], u=E.u[fw], v=E.v[fw])),
    pd.DataFrame(dict(edge_id=E.edge_id[bw], u_idx=E.v_idx[bw], v_idx=E.u_idx[bw], u=E.v[bw], v=E.u[bw]))],
    ignore_index=True)
A = A.merge(E[["edge_id", "length_m", "t_light_s", "t_truck_s", "fclass", "is_track"]], on="edge_id")
A = A.sort_values(["edge_id", "u_idx"]).reset_index(drop=True)
A.insert(0, "arc_id", np.arange(1, len(A) + 1))


def scc_main(arcs, n):
    m = sparse.csr_matrix((np.ones(len(arcs)), (arcs.u_idx.values, arcs.v_idx.values)), shape=(n, n))
    nc, lab = connected_components(m, directed=True, connection="strong")
    big = np.bincount(lab).argmax()
    return lab == big, nc


used_roads = np.zeros(len(N), bool)
ar = A[A.is_track == 0]
used_roads[ar.u_idx] = True; used_roads[ar.v_idx] = True
main_roads, nc_roads = scc_main(ar, len(N))
main_roads &= used_roads
main_all, nc_all = scc_main(A, len(N))
N["in_main_component"] = main_roads.astype(int)          # = trucks/light, roads without tracks (DEFAULT)
N["in_scc_with_tracks"] = main_all.astype(int)
for col, mask in (("in_main_component", main_roads), ("in_scc_with_tracks", main_all)):
    E[col] = (mask[E.u_idx.values] & mask[E.v_idx.values]).astype(int)
E.loc[E.is_track == 1, "in_main_component"] = 0
A = A.merge(E[["edge_id", "in_main_component", "in_scc_with_tracks"]], on="edge_id")
log(f"nodes {len(N):,}; arcs {len(A):,}; SCC roads: {main_roads.sum():,} nodes ({nc_roads} comps); "
    f"SCC with tracks: {main_all.sum():,} nodes")

# dropped components (roads graph, non-track edges not in main SCC)
D = E[(E.is_track == 0) & (E.in_main_component == 0)].copy()
dm = sparse.csr_matrix((np.ones(len(D)), (D.u_idx.values, D.v_idx.values)), shape=(len(N), len(N)))
_, wl = connected_components(dm, directed=False)
D["comp"] = wl[D.u_idx.values]
grp = []
for c, g in D.groupby("comp"):
    geom = shapely.union_all(g.geometry.values)
    rp = geom.centroid
    lo, la = TO_WGS.transform(rp.x, rp.y)
    touches_main = bool(main_roads[np.concatenate([g.u_idx.values, g.v_idx.values])].any())
    grp.append(dict(comp=int(c), n_edges=len(g), km=g.length_m.sum() / 1000,
                    main_class=g.groupby("fclass").length_m.sum().idxmax(),
                    names=";".join(sorted({str(x) for x in g.name.dropna()})[:4]),
                    oneway_edges=int((g.oneway != "B").sum()), touches_main=touches_main,
                    in_gipuzkoa=int(g.in_gipuzkoa.max()), region=g.region.iloc[0], lon=lo, lat=la, geometry=geom))
DC = gpd.GeoDataFrame(grp, crs=25830) if grp else gpd.GeoDataFrame(columns=["geometry"], crs=25830)
if len(DC):
    pt = gpd.GeoDataFrame(geometry=gpd.points_from_xy(DC.lon, DC.lat), crs=4326).to_crs(25830)
    j = gpd.sjoin(pt, m8_capv[["name", "geometry"]], how="left", predicate="within")
    DC["muni_osm"] = j.groupby(level=0).name.first().values
    DC["in_tolosaldea_bbox"] = ((DC.lon.between(BB_W, BB_E)) & (DC.lat.between(BB_S, BB_N))).astype(int)
    DC["kind"] = np.where(DC.touches_main, "attached_oneway_or_trap", "island")
    DC = DC.sort_values("km", ascending=False).reset_index(drop=True)
stats["graph"].update(dict(
    ways_kept=len(kept_idx), edges=int(len(E)), nodes=int(len(N)), arcs=int(len(A)),
    km_total=round(E.length_m.sum() / 1000, 1), km_roads=round(E[E.is_track == 0].length_m.sum() / 1000, 1),
    km_tracks=round(E[E.is_track == 1].length_m.sum() / 1000, 1),
    link_edges=int(E.fclass.str.endswith("_link").sum()),
    link_km=round(E[E.fclass.str.endswith("_link")].length_m.sum() / 1000, 1),
    synthetic_connectors=0, speed_clamped_to_5=n_clamped, loop_split_nodes=extra_nodes,
    scc_roads_nodes=int(main_roads.sum()), scc_roads_share_of_road_nodes=round(main_roads.sum() / used_roads.sum(), 5),
    scc_all_nodes=int(main_all.sum()), n_scc_roads=int(nc_roads),
    dropped_roads_edges=int(len(D)), dropped_roads_km=round(D.length_m.sum() / 1000, 1),
    dropped_components=int(len(DC)),
    dropped_in_gipuzkoa_km=round(D[D.in_gipuzkoa == 1].length_m.sum() / 1000, 1),
    dropped_in_bbox_components=int(DC.in_tolosaldea_bbox.sum()) if len(DC) else 0,
    dropped_in_bbox_km=round(float(DC[DC.in_tolosaldea_bbox == 1].km.sum()), 1) if len(DC) else 0,
    dropped_by_kind=DC.groupby("kind").agg(n=("km", "size"), km=("km", "sum")).round(1).reset_index().to_dict("records") if len(DC) else [],
    tracks_in_scc_km=round(E[(E.is_track == 1) & (E.in_scc_with_tracks == 1)].length_m.sum() / 1000, 1),
    nodes_only_via_tracks=int((main_all & ~main_roads).sum()),
))
sp = E[E.is_track == 0]
stats["graph"]["speed_source_share_roads"] = (sp.speed_source.value_counts(normalize=True).round(4)).to_dict()
stats["graph"]["maxspeed_present_share_km_roads"] = round(sp[sp.speed_source == "osm_maxspeed_capped"].length_m.sum() / sp.length_m.sum(), 4)
stats["graph"]["by_class"] = (E.groupby("fclass").agg(edges=("edge_id", "size"), km=("length_m", lambda s: s.sum() / 1000),
                              speed_kmh_mean=("speed_used_kmh", "mean"), maxspeed_share=("maxspeed_osm", lambda s: s.notna().mean()),
                              in_main=("in_main_component", "mean")).round(3).reset_index().to_dict("records"))
stats["graph"]["oneway"] = E.oneway.value_counts().to_dict()
stats["graph"]["access_flags"] = E.access_flag.value_counts().to_dict()
stats["graph"]["region"] = E.groupby("region").length_m.sum().div(1000).round(1).to_dict()
log("graph stats", {k: v for k, v in stats["graph"].items() if not isinstance(v, (list, dict))})

# ----------------------------------------------------------------------------- write graph
log("writing roads.gpkg + parquet")
gpkg = OUT / "roads.gpkg"
if gpkg.exists():
    gpkg.unlink()
ecols = ["edge_id", "osm_id", "u", "v", "fclass", "oneway", "length_m", "maxspeed_osm", "speed_used_kmh",
         "speed_source", "fclass_osm", "region", "region_rule", "source_id", "speed_truck_kmh", "t_light_s", "t_truck_s", "is_track",
         "in_main_component", "in_scc_with_tracks", "in_gipuzkoa", "name", "ref", "access", "motor_vehicle",
         "access_flag", "junction", "surface", "tracktype", "service", "hgv", "emergency"]
GE = gpd.GeoDataFrame(E[ecols + ["geometry"]], geometry="geometry", crs=25830)
GE.to_file(gpkg, layer="road_edges", driver="GPKG", engine="pyogrio")
deg = np.bincount(np.concatenate([E.u_idx.values, E.v_idx.values]), minlength=len(N))
N["degree"] = deg
GN = gpd.GeoDataFrame(N[["node_id", "x", "y", "in_main_component", "in_scc_with_tracks", "degree", "lon", "lat"]],
                      geometry=gpd.points_from_xy(N.x, N.y), crs=25830)
GN.to_file(gpkg, layer="road_nodes", driver="GPKG", engine="pyogrio")
if len(DC):
    DC.drop(columns=["touches_main"]).to_file(gpkg, layer="dropped_components", driver="GPKG", engine="pyogrio")
    DC.drop(columns=["geometry"]).round(4).to_csv(OUT / "dropped_components.csv", index=False)
A.to_parquet(OUT / "graph_arcs.parquet", index=False)
N[["idx", "node_id", "x", "y", "lon", "lat", "in_main_component", "in_scc_with_tracks"]].to_parquet(OUT / "graph_nodes.parquet", index=False)


# ----------------------------------------------------------------------------- routing helpers
class Snapper:
    def __init__(self, mask, name):
        self.ids = np.flatnonzero(mask)
        self.geoms = E.geometry.values[self.ids]
        self.tree = shapely.STRtree(self.geoms)
        self.name = name

    def snap(self, xs, ys):
        pts = shapely.points(xs, ys)
        qi, dist = self.tree.query_nearest(pts, return_distance=True, all_matches=False)
        order = np.argsort(qi[0]); ii = qi[1][order]; dist = dist[order]
        eidx = self.ids[ii]
        g = E.geometry.values[eidx]
        frac = shapely.line_locate_point(g, pts, normalized=True)
        L = E.length_m.values[eidx]
        node = np.where(frac <= 0.5, E.u.values[eidx], E.v.values[eidx])
        off = np.where(frac <= 0.5, frac, 1 - frac) * L
        return pd.DataFrame(dict(edge_row=eidx, snap_edge_id=E.edge_id.values[eidx], snap_dist_m=dist,
                                 frac=frac, snap_node_id=node, snap_offset_m=off,
                                 snap_edge_class=E.fclass.values[eidx], snap_road_name=E.name.values[eidx]))


ROAD_MAIN = (E.in_main_component == 1).values
ALL_MAIN = (E.in_scc_with_tracks == 1).values
SNAP_OK = ROAD_MAIN & ~E.fclass.isin(NO_SNAP_CLASSES).values
snap_roads = Snapper(SNAP_OK, "roads_no_mw_trunk")
snap_any = Snapper(ROAD_MAIN, "roads_any")
snap_tracks = Snapper(ALL_MAIN & ~E.fclass.isin(NO_SNAP_CLASSES).values, "with_tracks")


class Router:
    """Dijkstra on the main SCC with virtual nodes for snapped points (partial-edge costs)."""

    def __init__(self, with_tracks=False):
        col = "in_scc_with_tracks" if with_tracks else "in_main_component"
        self.arcs = A[A[col] == 1][["u_idx", "v_idx", "length_m", "t_light_s", "t_truck_s", "edge_id"]].copy()
        self.n = len(N)
        self.points = []  # (edge_row, frac)
        self.with_tracks = with_tracks

    def add_point(self, edge_row, frac):
        self.points.append((int(edge_row), float(frac)))
        return self.n + len(self.points) - 1

    def build(self):
        rows = []
        for k, (er, f) in enumerate(self.points):
            p = self.n + k
            u, v, L, tl, tt, ow = (E.u_idx.values[er], E.v_idx.values[er], E.length_m.values[er],
                                   E.t_light_s.values[er], E.t_truck_s.values[er], E.oneway.values[er])
            f = min(max(f, 1e-6), 1 - 1e-6)
            if ow in ("F", "B"):
                rows += [(u, p, f * L, f * tl, f * tt), (p, v, (1 - f) * L, (1 - f) * tl, (1 - f) * tt)]
            if ow in ("T", "B"):
                rows += [(v, p, (1 - f) * L, (1 - f) * tl, (1 - f) * tt), (p, u, f * L, f * tl, f * tt)]
        vr = pd.DataFrame(rows, columns=["u_idx", "v_idx", "length_m", "t_light_s", "t_truck_s"])
        vr["edge_id"] = -1  # partial edge of a snapped point
        ar = pd.concat([self.arcs, vr], ignore_index=True)
        self.size = self.n + len(self.points)
        self.mat, self.len_of = {}, {}
        for prof, col in (("light", "t_light_s"), ("truck", "t_truck_s")):
            g = ar.sort_values(col).drop_duplicates(["u_idx", "v_idx"])
            self.mat[prof] = sparse.csr_matrix((g[col].values, (g.u_idx.values, g.v_idx.values)), shape=(self.size, self.size))
            self.len_of[prof] = dict(zip(zip(g.u_idx.values, g.v_idx.values), g.length_m.values))
            self.edge_of = getattr(self, "edge_of", {})
            self.edge_of[prof] = dict(zip(zip(g.u_idx.values, g.v_idx.values), g.edge_id.values))

    def run(self, src, prof):
        d, pred = dijkstra(self.mat[prof], directed=True, indices=src, return_predecessors=True)
        return d, pred

    def path_classes(self, pred, src, dst, prof):
        """km by fclass along the optimal path + main refs."""
        if pred[dst] < 0:
            return {}, ""
        eo, lo = self.edge_of[prof], self.len_of[prof]
        km, refs, cur = Counter(), [], dst
        Ei = E.set_index("edge_id") if not hasattr(self, "_Ei") else self._Ei
        self._Ei = Ei
        while cur != src:
            p = pred[cur]
            e = eo[(p, cur)]
            if e > 0:
                km[Ei.at[e, "fclass"]] += lo[(p, cur)] / 1000
                r = Ei.at[e, "ref"] if pd.notna(Ei.at[e, "ref"]) else Ei.at[e, "name"]
                if pd.notna(r) and (not refs or refs[-1] != r) and Ei.at[e, "fclass"] not in ("service", "residential", "living_street"):
                    refs.append(r)
            cur = p
        return {k: round(v, 2) for k, v in km.most_common()}, " < ".join(refs)

    def path_km(self, pred, src, dst, prof):
        if pred[dst] < 0 and dst != src:
            return np.nan
        L, cur = 0.0, dst
        lo = self.len_of[prof]
        while cur != src:
            p = pred[cur]
            L += lo[(p, cur)]
            cur = p
        return L / 1000


# ----------------------------------------------------------------------------- 3. fire stations
log("fire stations")
fs = gpd.read_file(FIREST)
raw_geom_types = fs.geom_type.value_counts().to_dict()
fs = fs.to_crs(25830)
fs["geom_note"] = np.where(fs.geom_type == "Point", "point as published (layer declares generic GEOMETRY)",
                           "non-point: representative_point()")
fs["geometry"] = [g if g.geom_type == "Point" else g.representative_point() for g in fs.geometry]
ID_BY_MUNI = {"Tolosa": ("GIP-ORIA", "Parque de Oria", "DFG"), "Ordizia": ("GIP-GOIERRI", "Parque de Goierri", "DFG"),
              "Azpeitia": ("GIP-UROLA", "Parque de Urola", "DFG"), "Zarautz": ("GIP-KOSTA", "Parque de Kosta", "DFG"),
              "Donostia": ("DON-GARBERA", "Parque de Garbera (Donostia)", "municipal"),
              "Legazpi": ("GIP-KOROSTI", "Parque de Korosti", "DFG"), "Irun": ("GIP-BIDASOA", "Parque de Bidasoa", "DFG"),
              "Eibar": ("GIP-ARRATE", "Parque de Arrate", "DFG"), "Oñati": ("GIP-ZUBILLAGA", "Parque de Zubillaga", "DFG"),
              "Hondarribia": ("OTH-HONDARRIBIA", "Bomberos (Gabarrari kalea, Hondarribia)", "other")}
rows = []
for _, r in fs.iterrows():
    sid, nm, op = ID_BY_MUNI[r.MUNI_EU]
    bis = r.BIS if isinstance(r.BIS, str) else ""
    addr = f"{r.STREET_EU} {r.HOUSE_NUMBER}{bis}, {r.MUNI_EU} ({r.POSTCODE})"
    rows.append(dict(station_id=sid, b5mcode=r.B5MCODE, name=nm, name_b5m=r.NAME, name_eu=r.NAME_EU, name_es=r.NAME_ES,
                     operator=op, codmuni=r.CODMUNI, municipality=r.MUNI_EU, municipality_es=r.MUNI_ES, address=addr,
                     street_es=r.STREET_ES, house_number=r.HOUSE_NUMBER, postcode=r.POSTCODE,
                     b5midaddress=r.B5MIDADDRESS, b5midnamebuilding=r.B5MIDNAMEBUILDING, b5midut=r.B5MIDUT,
                     x=r.geometry.x, y=r.geometry.y, geom_note=r.geom_note))
S = pd.DataFrame(rows)
S["lon"], S["lat"] = TO_WGS.transform(S.x.values, S.y.values)
S["include_in_baseline"] = (S.operator != "other").astype(int)
S["loc_confidence"] = "address_street"   # schema value closest to "official B5M address point, not ortho-checked"
S["loc_method"] = "B5M official point (GFA_DSET_FIREST, geometry 'punto central'); not checked on orthophoto"
S["source_id"] = SRC_B5M
S["routable"] = 1
S.loc[S.station_id == "OTH-HONDARRIBIA", "note"] = ("Not a DFG park: name 'Suhiltzaileak / Bomberos' and point at "
    "Gabarrari kalea 24 = San Sebastián airport area (likely AENA airport fire service, to verify). Kept, excluded from baseline.")
S.loc[S.station_id == "DON-GARBERA", "note"] = "Donostia municipal fire service (operator from v0.1; B5M has no operator field)."

# v0.1 positions
v01s = pd.read_csv(V01 / "fire_stations.csv")
v01x, v01y = TO_UTM.transform(v01s.lon.values, v01s.lat.values)
v01s["x"], v01s["y"] = v01x, v01y
S = S.merge(v01s[["station_id", "x", "y", "relevance", "snap_dist_m", "min_to_tolosa_center"]].rename(
    columns={"x": "v01_x", "y": "v01_y", "relevance": "v01_relevance", "snap_dist_m": "v01_snap_m",
             "min_to_tolosa_center": "v01_min_to_tolosa"}), on="station_id", how="left")
S["dist_to_v01_m"] = np.hypot(S.x - S.v01_x, S.y - S.v01_y).round(1)
# OSM amenity=fire_station cross-check (all of PV extract would need another pass; bbox objects only)
osm_fs = [(t.get("name"), g) for (ot, oid, t, g) in pois_raw if t.get("amenity") == "fire_station"]
osm_fs_g = gpd.GeoDataFrame(dict(name=[a for a, _ in osm_fs]), geometry=[g.representative_point() for _, g in osm_fs], crs=4326).to_crs(25830) if osm_fs else None
if osm_fs_g is not None and len(osm_fs_g):
    d = np.array([[math.hypot(px - q.x, py - q.y) for q in osm_fs_g.geometry] for px, py in zip(S.x, S.y)])
    S["dist_to_osm_fire_station_m"] = np.where(d.min(1) < 2000, d.min(1).round(1), np.nan)
    S["osm_fire_station_name"] = np.where(d.min(1) < 2000, osm_fs_g.name.values[d.argmin(1)], None)

sn = snap_roads.snap(S.x.values, S.y.values)
sa = snap_any.snap(S.x.values, S.y.values)
S = pd.concat([S, sn[["snap_edge_id", "snap_dist_m", "snap_node_id", "snap_offset_m", "snap_edge_class", "snap_road_name"]]], axis=1)
S["nearest_any_edge_class"] = sa.snap_edge_class.values
S["nearest_any_edge_dist_m"] = sa.snap_dist_m.values
S = S.rename(columns={"snap_node_id": "node_id", "snap_dist_m": "snap_distance_m"})

# ----------------------------------------------------------------------------- places & routers
PL = pd.DataFrame(places_raw, columns=["osm_id", "place", "name", "lon", "lat"])
PL["x"], PL["y"] = TO_UTM.transform(PL.lon.values, PL.lat.values)


def centre(name):
    """OSM place node (town/village preferred) inside Gipuzkoa with that name."""
    c = PL[(PL.name == name) & PL.place.isin(["city", "town", "village"])]
    if len(c) == 0:
        c = PL[PL.name == name]
    c = c[[gip.contains(shapely.Point(a, b)) for a, b in zip(c.x, c.y)]]
    return c.iloc[0] if len(c) else None


MUNI_CENTRE_NAME = {m: m for m in TOLOSALDEA}
MUNI_CENTRE_NAME.update({"Amasa-Villabona": "Villabona", "Bidania-Goiatz": "Bidania"})
centres = []
for m in TOLOSALDEA:
    c = centre(MUNI_CENTRE_NAME[m])
    src = "osm_place_node"
    poly = m8_capv[m8_capv.name == m]
    if c is None or (len(poly) and not poly.geometry.iloc[0].contains(shapely.Point(c.x, c.y))):
        rp = poly.geometry.iloc[0].representative_point()
        c = pd.Series(dict(name=m, x=rp.x, y=rp.y, osm_id=None, place="polygon_rep_point"))
        src = "admin8_representative_point"
    centres.append(dict(municipality=m, centre_name=c["name"], centre_osm_node=c.osm_id, centre_source=src,
                        place=c.place, x=c.x, y=c.y))
C = pd.DataFrame(centres)
for nm in ["Tolosa", "Ordizia"]:
    if nm not in set(C.municipality):
        c = centre(nm)
        C = pd.concat([C, pd.DataFrame([dict(municipality=nm, centre_name=nm, centre_osm_node=c.osm_id,
                                              centre_source="osm_place_node", place=c.place, x=c.x, y=c.y)])], ignore_index=True)
cs = snap_roads.snap(C.x.values, C.y.values)
C = pd.concat([C, cs[["edge_row", "frac", "snap_dist_m", "snap_edge_class", "snap_road_name"]]], axis=1)

routers = {"roads": Router(False), "tracks": Router(True), "nomw": Router(False)}
routers["nomw"].arcs = routers["nomw"].arcs[~A.loc[routers["nomw"].arcs.index, "fclass"].isin(NO_SNAP_CLASSES).values]
for rname, R in routers.items():
    snp = snap_tracks if rname == "tracks" else snap_roads
    s_st = snp.snap(S.x.values, S.y.values)
    S[f"_vn_{rname}"] = [R.add_point(a, b) for a, b in zip(s_st.edge_row, s_st.frac)]
    c_st = snp.snap(C.x.values, C.y.values)
    C[f"_vn_{rname}"] = [R.add_point(a, b) for a, b in zip(c_st.edge_row, c_st.frac)]
    v01sn = snp.snap(v01s.x.values, v01s.y.values)
    v01s[f"_vn_{rname}"] = [R.add_point(a, b) for a, b in zip(v01sn.edge_row, v01sn.frac)]
    R.build()
log("routers built")

# per-station trees (light & truck, roads graph)
DIST = {}
for _, s in S.iterrows():
    for prof in ("light", "truck"):
        DIST[(s.station_id, prof)] = routers["roads"].run(s["_vn_roads"], prof)

# ----------------------------------------------------------------------------- 2. validation
log("validation routes")
V01_CHECK = [("GIP-ORIA", "Amezketa", 13.4, 16.1), ("GIP-ORIA", "Berastegi", 11.4, 11.5),
             ("GIP-ORIA", "Amasa-Villabona", 7.6, 5.5), ("GIP-ORIA", "Lizartza", 6.6, 7.4),
             ("GIP-GOIERRI", "Tolosa", None, 9.6)]
Cidx = C.set_index("municipality")
vrows = []
for sid, muni, v_km, v_min in V01_CHECK:
    s = S.set_index("station_id").loc[sid]
    c = Cidx.loc[muni]
    row = dict(origin=sid, destination=f"{muni} centre ({c.centre_name}, {c.centre_source})",
               origin_snap_m=round(s.snap_distance_m, 1), dest_snap_m=round(c.snap_dist_m, 1))
    for prof in ("light", "truck"):
        d, pred = DIST[(sid, prof)]
        tgt = int(c["_vn_roads"])
        row[f"km_{prof}"] = round(routers["roads"].path_km(pred, int(s["_vn_roads"]), tgt, prof), 2)
        row[f"min_{prof}"] = round(d[tgt] / 60, 1)
        if prof == "light":
            kc, refs = routers["roads"].path_classes(pred, int(s["_vn_roads"]), tgt, prof)
            row["light_path_km_by_class"] = json.dumps(kc)
            row["light_path_roads_dest_to_origin"] = refs
    # tracks graph (light)
    Rt = routers["tracks"]
    d, pred = Rt.run(int(s["_vn_tracks"]), "light")
    row["min_light_with_tracks"] = round(d[int(c["_vn_tracks"])] / 60, 1)
    Rn = routers["nomw"]
    d, pred = Rn.run(int(s["_vn_nomw"]), "light")
    row["min_light_no_motorway_trunk"] = round(d[int(c["_vn_nomw"])] / 60, 1)
    row["km_light_no_motorway_trunk"] = round(Rn.path_km(pred, int(s["_vn_nomw"]), int(c["_vn_nomw"]), "light"), 2)
    # same network, v0.1 approximate station position
    vs = v01s.set_index("station_id").loc[sid]
    d, pred = routers["roads"].run(int(vs["_vn_roads"]), "light")
    row["min_light_from_v01_position"] = round(d[int(c["_vn_roads"])] / 60, 1)
    row["v01_km"], row["v01_min"] = v_km, v_min
    row["diff_min_light_vs_v01"] = round(row["min_light"] - v_min, 1)
    row["diff_pct_light_vs_v01"] = round(100 * (row["min_light"] - v_min) / v_min, 1)
    vrows.append(row)
# like-for-like with v0.1: v0.1 'min_to_tolosa_center' was 0.0 for GIP-ORIA, i.e. its "Tolosa centre" was the Oria node
so, sg = S.set_index("station_id").loc["GIP-ORIA"], S.set_index("station_id").loc["GIP-GOIERRI"]
row = dict(origin="GIP-GOIERRI", destination="GIP-ORIA station (v0.1 'Tolosa centre' = Oria node)",
           origin_snap_m=round(sg.snap_distance_m, 1), dest_snap_m=round(so.snap_distance_m, 1))
for prof in ("light", "truck"):
    d, pred = DIST[("GIP-GOIERRI", prof)]
    tgt = int(so["_vn_roads"])
    row[f"km_{prof}"] = round(routers["roads"].path_km(pred, int(sg["_vn_roads"]), tgt, prof), 2)
    row[f"min_{prof}"] = round(d[tgt] / 60, 1)
    if prof == "light":
        kc, refs = routers["roads"].path_classes(pred, int(sg["_vn_roads"]), tgt, prof)
        row["light_path_km_by_class"] = json.dumps(kc); row["light_path_roads_dest_to_origin"] = refs
Rt = routers["tracks"]
d, _ = Rt.run(int(sg["_vn_tracks"]), "light"); row["min_light_with_tracks"] = round(d[int(so["_vn_tracks"])] / 60, 1)
Rn = routers["nomw"]
d, pred = Rn.run(int(sg["_vn_nomw"]), "light")
row["min_light_no_motorway_trunk"] = round(d[int(so["_vn_nomw"])] / 60, 1)
row["km_light_no_motorway_trunk"] = round(Rn.path_km(pred, int(sg["_vn_nomw"]), int(so["_vn_nomw"]), "light"), 2)
vs = v01s.set_index("station_id")
d, _ = routers["roads"].run(int(vs.loc["GIP-GOIERRI", "_vn_roads"]), "light")
row["min_light_from_v01_position"] = round(d[int(vs.loc["GIP-ORIA", "_vn_roads"])] / 60, 1)
row["v01_km"], row["v01_min"] = None, 9.6
row["diff_min_light_vs_v01"] = round(row["min_light"] - 9.6, 1)
row["diff_pct_light_vs_v01"] = round(100 * (row["min_light"] - 9.6) / 9.6, 1)
vrows.append(row)
VAL = pd.DataFrame(vrows)
VAL.to_csv(OUT / "validation_routes.csv", index=False)
print(VAL.to_string())

# ----------------------------------------------------------------------------- station relevance
log("station relevance")
rel = []
for _, c in C[C.municipality.isin(TOLOSALDEA)].iterrows():
    for _, s in S.iterrows():
        d, _ = DIST[(s.station_id, "light")]
        dt, _ = DIST[(s.station_id, "truck")]
        rel.append(dict(municipality=c.municipality, station_id=s.station_id, min_light=d[int(c["_vn_roads"])] / 60,
                        min_truck=dt[int(c["_vn_roads"])] / 60))
REL = pd.DataFrame(rel)
REL["rank_light"] = REL.groupby("municipality").min_light.rank(method="first").astype(int)
REL.round(2).sort_values(["municipality", "rank_light"]).to_csv(OUT / "station_relevance.csv", index=False)
first = REL[REL.rank_light == 1].station_id.value_counts().to_dict()
second = REL[REL.rank_light == 2].station_id.value_counts().to_dict()
tol = int(Cidx.loc["Tolosa", "_vn_roads"])
S["min_light_to_tolosa_centre"] = [round(DIST[(s, "light")][0][tol] / 60, 1) for s in S.station_id]
S["min_truck_to_tolosa_centre"] = [round(DIST[(s, "truck")][0][tol] / 60, 1) for s in S.station_id]
S["n_tolosaldea_munis_nearest"] = S.station_id.map(first).fillna(0).astype(int)
S["n_tolosaldea_munis_second"] = S.station_id.map(second).fillna(0).astype(int)
S["min_light_to_nearest_tolosaldea_centre"] = S.station_id.map(REL.groupby("station_id").min_light.min()).round(1)


def relevance(r):
    if r.operator == "other":
        return "not_applicable"
    if r.municipality in TOLOSALDEA:
        return "interior"
    if r.n_tolosaldea_munis_nearest > 0:
        return "exterior_first_for_some"
    if r.n_tolosaldea_munis_second > 0:
        return "exterior_backup"
    if r.min_light_to_nearest_tolosaldea_centre <= 20:
        return "exterior_context"
    return "exterior_far"


S["relevance"] = S.apply(relevance, axis=1)
scols = ["station_id", "b5mcode", "name", "name_b5m", "name_eu", "name_es", "operator", "codmuni", "municipality",
         "municipality_es", "address", "street_es", "house_number", "postcode", "b5midaddress", "b5midnamebuilding",
         "b5midut", "lon", "lat", "x", "y", "loc_confidence", "loc_method", "geom_note", "node_id", "snap_distance_m",
         "snap_edge_id", "snap_offset_m", "snap_edge_class", "snap_road_name", "nearest_any_edge_class",
         "nearest_any_edge_dist_m", "routable", "include_in_baseline", "relevance", "min_light_to_tolosa_centre",
         "min_truck_to_tolosa_centre", "n_tolosaldea_munis_nearest", "n_tolosaldea_munis_second",
         "min_light_to_nearest_tolosaldea_centre", "dist_to_v01_m", "v01_relevance", "v01_min_to_tolosa",
         "dist_to_osm_fire_station_m", "osm_fire_station_name", "note", "source_id"]
for c_ in scols:
    if c_ not in S:
        S[c_] = None
SG = gpd.GeoDataFrame(S[scols].round(4), geometry=gpd.points_from_xy(S.x, S.y), crs=25830)
for p in [OUT / "fire_stations.gpkg", OUT / "fire_stations.geojson"]:
    if p.exists():
        p.unlink()
SG.to_file(OUT / "fire_stations.gpkg", layer="fire_stations", driver="GPKG", engine="pyogrio")
SG.to_crs(4326).to_file(OUT / "fire_stations.geojson", driver="GeoJSON", engine="pyogrio")
S[scols].round(4).to_csv(OUT / "fire_stations.csv", index=False)
print(S[["station_id", "municipality", "dist_to_v01_m", "dist_to_osm_fire_station_m", "snap_distance_m", "snap_edge_class",
         "min_light_to_tolosa_centre", "n_tolosaldea_munis_nearest", "n_tolosaldea_munis_second", "relevance"]].to_string())

# ----------------------------------------------------------------------------- 4. candidate pool
log("candidate pool")
P = []
for ot, oid, t, g in pois_raw:
    P.append(dict(osm_type=ot, osm_id=int(oid), tags=t, geom_wgs=g))
P = pd.DataFrame(P)
P["geometry"] = gpd.GeoSeries(P.geom_wgs, crs=4326).to_crs(25830).values
P["is_poly"] = shapely.get_type_id(P.geometry.values) >= 3
P["area_m2"] = np.where(P.is_poly, shapely.area(P.geometry.values), np.nan)
tg = lambda k: P.tags.map(lambda d: d.get(k))
for k in ["amenity", "landuse", "leisure", "tourism", "office", "sport", "name", "access", "surface", "parking",
          "capacity", "fee", "operator", "shelter_type", "highway", "building"]:
    P[k] = tg(k)

# all parking features (incl. small / private) for "nearest parking" lookups
park_all = P[P.amenity == "parking"]
park_pub = park_all[~park_all.access.isin(["private", "no"])]
pk_pts = shapely.point_on_surface(park_pub.geometry.values)
pk_tree = shapely.STRtree(park_pub.geometry.values)
# track entries = nodes where a track edge (main SCC with tracks) meets a non-track road edge in the roads SCC
trk = E[(E.is_track == 1) & (E.in_scc_with_tracks == 1)]
road_nodes_main = set(np.concatenate([E[E.in_main_component == 1].u.values, E[E.in_main_component == 1].v.values]).tolist())
te = [n for n in set(np.concatenate([trk.u.values, trk.v.values]).tolist()) if n in road_nodes_main]
te_xy = N.set_index("node_id").loc[te, ["x", "y"]].values
te_tree = cKDTree(te_xy)
trailheads = P[P.highway == "trailhead"]


def classify(r):
    """(site_type, subtype, reject_reason or None). Priority order matters."""
    t = r.tags  # use the raw dict: DataFrame columns hold NaN (truthy) for missing tags
    a, l, le, tu = t.get("amenity"), t.get("landuse"), t.get("leisure"), t.get("tourism")
    nm = " ".join(str(t.get(k, "")) for k in ("name", "name:es", "name:eu", "operator"))
    building, sport, office, parking = t.get("building"), t.get("sport"), t.get("office"), t.get("parking")
    shelter_type, highway = t.get("shelter_type"), t.get("highway")
    if a == "fire_station":
        return "fire_station", None, None
    if (office == "government" or DFG_RX.search(nm)) and a not in ("charging_station", "parking"):
        sub = "dfg_named" if DFG_RX.search(nm) else "public_office_osm"
        return "dfg_facility", sub, None
    if a == "parking":
        if parking in ("underground", "multi-storey", "rooftop"):
            return "parking", parking, "parking_" + parking
        if r.is_poly and r.area_m2 < 400:
            return "parking", None, "parking_area_lt_400m2"
        return "parking", None, None
    if r.tags.get("disused") == "yes" or r.tags.get("abandoned") == "yes" or building == "ruins":
        return "disused", None, "disused_or_ruins"
    if sport and "pelota" in str(sport):
        return "fronton", le or l or (("building=" + building) if building else None) or "pitch", None
    if le == "sports_centre":
        return "sports_centre", sport, None
    if a == "community_centre":
        return "community_centre", None, None
    if l == "industrial":
        if r.is_poly and r.area_m2 < 2000:
            return "industrial", None, "industrial_area_lt_2000m2"
        return "industrial", None, None
    if tu == "picnic_site" or le == "picnic_site":
        return "picnic_site", None, None
    if a == "shelter":
        if shelter_type == "public_transport" or r.tags.get("bus") == "yes" or r.tags.get("public_transport"):
            return "shelter", "public_transport", "bus_shelter"
        return "shelter", shelter_type, None
    if le in ("picnic_table",) or tu == "picnic_table":
        return "picnic_table", None, None
    if le == "recreation_ground" or l == "recreation_ground" or (REC_RX.search(nm) and not building):
        if r.is_poly and r.area_m2 < 400:
            return "recreation_area", le or l, "recreation_area_lt_400m2"
        return "recreation_area", le or l or tu or r.tags.get("place"), None
    if l == "depot":
        return "dfg_facility", "depot", None
    if highway == "trailhead":
        return "trailhead", None, None
    return None, None, None


cl = P.apply(classify, axis=1, result_type="expand")
P["site_type"], P["subtype"], P["reject_reason"] = cl[0], cl[1], cl[2]
P = P[P.site_type.notna()].copy()
P.loc[P.access.isin(["private", "no"]) & P.reject_reason.isna(), "reject_reason"] = "access_" + P.access.astype(str)

# representative point
rep = shapely.point_on_surface(P.geometry.values)
ind = P.site_type.eq("industrial").values & P.is_poly.values
if ind.any():
    # access point: point inside the estate on its nearest road (internal street if any), else boundary point nearest the road
    ig = P.geometry.values[ind]
    qi, _ = snap_roads.tree.query_nearest(ig, return_distance=True, all_matches=False)
    o = np.argsort(qi[0])
    near = snap_roads.geoms[qi[1][o]]
    inner = []
    for poly, ln, rp in zip(ig, near, rep[ind]):
        inter = poly.intersection(ln)
        if not inter.is_empty and inter.length > 0:
            inner.append(shapely.ops.nearest_points(inter, rp)[0])
        else:
            inner.append(shapely.ops.nearest_points(poly, ln)[0])
    rep[ind] = inner
P["pt"] = rep
P["x"], P["y"] = shapely.get_x(rep), shapely.get_y(rep)
P["lon"], P["lat"] = TO_WGS.transform(P.x.values, P.y.values)
P = P[P.lon.between(BB_W, BB_E) & P.lat.between(BB_S, BB_N)].copy()

# picnic tables -> clusters (single-link 50 m); merge into picnic sites within 100 m
tb = P[P.site_type == "picnic_table"]
P = P[P.site_type != "picnic_table"].copy()
P["n_picnic_tables"] = 0
if len(tb):
    tr = cKDTree(np.column_stack([tb.x, tb.y]))
    pairs = tr.query_pairs(50, output_type="ndarray")
    gm = sparse.csr_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(tb), len(tb))) if len(pairs) else sparse.csr_matrix((len(tb), len(tb)))
    _, lab = connected_components(gm, directed=False)
    tb = tb.assign(cl=lab)
    sites = P[P.site_type.isin(["picnic_site", "recreation_area", "shelter"])]
    st_tree = cKDTree(np.column_stack([sites.x, sites.y])) if len(sites) else None
    newrows = []
    for c_, g in tb.groupby("cl"):
        cx_, cy_ = g.x.mean(), g.y.mean()
        if st_tree is not None:
            dd, ii = st_tree.query([cx_, cy_])
            if dd <= 100:
                P.loc[sites.index[ii], "n_picnic_tables"] += len(g)
                continue
        if len(g) >= 2:
            r0 = g.iloc[0].copy()
            r0["site_type"], r0["subtype"], r0["n_picnic_tables"] = "picnic_table_cluster", f"{len(g)} tables", len(g)
            r0["x"], r0["y"] = cx_, cy_
            r0["osm_id_list"] = ";".join(map(str, g.osm_id))
            newrows.append(r0)
    if newrows:
        nr = pd.DataFrame(newrows)
        nr["lon"], nr["lat"] = TO_WGS.transform(nr.x.values, nr.y.values)
        nr["pt"] = shapely.points(nr.x.values, nr.y.values)
        P = pd.concat([P, nr], ignore_index=False)
P = P.reset_index(drop=True)

# recreation_area / shelter within 50 m of a picnic_site -> duplicate (keep the picnic site)
ps_ = P[P.site_type == "picnic_site"]
if len(ps_):
    t_ = cKDTree(np.column_stack([ps_.x, ps_.y]))
    rr = P[P.site_type.isin(["recreation_area", "shelter"]) & P.reject_reason.isna()]
    d_, _ = t_.query(np.column_stack([rr.x, rr.y]))
    P.loc[rr.index[d_ <= 50], "reject_reason"] = "duplicate_of_picnic_site"

# dedupe parking nodes inside / within 25 m of a parking polygon
pp = P[(P.site_type == "parking") & P.is_poly]
pn = P[(P.site_type == "parking") & ~P.is_poly.astype(bool)]
if len(pp) and len(pn):
    tpp = shapely.STRtree(pp.geometry.values)
    hit = tpp.query(shapely.points(pn.x.values, pn.y.values), predicate="dwithin", distance=25)
    P.loc[pn.index[np.unique(hit[0])], "reject_reason"] = P.loc[pn.index[np.unique(hit[0])], "reject_reason"].fillna("duplicate_of_parking_polygon")

# nearest public parking (excluding itself), track entry, trailhead
pts = shapely.points(P.x.values, P.y.values)
nearest_pk = []
for i, (pt_, ot, oid) in enumerate(zip(pts, P.osm_type, P.osm_id)):
    cand = pk_tree.query(pt_, predicate="dwithin", distance=1000)
    best = np.nan
    for j in cand:
        r_ = park_pub.iloc[j]
        if r_.osm_type == ot and r_.osm_id == oid:
            continue
        d_ = shapely.distance(pt_, park_pub.geometry.values[j])
        best = d_ if np.isnan(best) else min(best, d_)
    nearest_pk.append(best)
P["nearest_parking_m"] = np.round(nearest_pk, 1)
P["dist_track_entry_m"] = np.round(te_tree.query(np.column_stack([P.x, P.y]))[0], 1)
if len(trailheads):
    th_tree = cKDTree(np.column_stack(TO_UTM.transform(trailheads.geom_wgs.map(lambda g: g.x).values, trailheads.geom_wgs.map(lambda g: g.y).values)))
    P["dist_trailhead_m"] = np.round(th_tree.query(np.column_stack([P.x, P.y]))[0], 1)
else:
    P["dist_trailhead_m"] = np.nan
mt = (P.site_type == "parking") & ((P.dist_track_entry_m <= 100) | (P.dist_trailhead_m <= 150))
P["subtype"] = P.subtype.where(~mt, "mountain_access")
need_pk = P.site_type.isin(["sports_centre", "community_centre", "fronton"]) & ~(P.nearest_parking_m <= 150) & P.reject_reason.isna()
P.loc[need_pk, "reject_reason"] = "no_parking_within_150m"

# snapping
sr = snap_roads.snap(P.x.values, P.y.values)
sa = snap_any.snap(P.x.values, P.y.values)
st = snap_tracks.snap(P.x.values, P.y.values)
for c_ in ["snap_edge_id", "snap_dist_m", "snap_node_id", "snap_offset_m", "snap_edge_class", "snap_road_name"]:
    P[c_] = sr[c_].values
P["nearest_any_edge_class"] = sa.snap_edge_class.values
P["nearest_any_edge_dist_m"] = sa.snap_dist_m.values.round(1)
P["track_snap_dist_m"] = st.snap_dist_m.values.round(1)
P["track_snap_edge_class"] = st.snap_edge_class.values
far = P.snap_dist_m > 150
P.loc[far & (P.track_snap_dist_m <= 150) & P.reject_reason.isna(), "reject_reason"] = "track_access_only"
P.loc[far & P.reject_reason.isna(), "reject_reason"] = "snap_gt_150m"
P["near_motorway_trunk"] = (P.nearest_any_edge_class.isin(NO_SNAP_CLASSES) & (P.nearest_any_edge_dist_m < P.snap_dist_m)).astype(int)
P["status"] = np.where(P.reject_reason.isna(), "ok", "rejected")

# municipality hint (OSM admin8, NOT the official linker assignment)
pg = gpd.GeoDataFrame(geometry=shapely.points(P.x.values, P.y.values), crs=25830)
jj = gpd.sjoin(pg, m8_capv[["name", "ine", "geometry"]], how="left", predicate="within")
jj = jj[~jj.index.duplicated()]
P["muni_osm_hint"] = jj.name.values
P["ine_osm_hint"] = jj.ine.values
P["in_tolosaldea_hint"] = P.muni_osm_hint.isin(TOLOSALDEA).astype(int)
P.loc[P.muni_osm_hint.isna(), "muni_osm_hint"] = "outside_CAPV_or_unassembled(Navarra?)"
P["municipality_code"] = None      # linker: official point-in-polygon with P2 municipalities
P["baseline_min_light"] = None     # linker
P["baseline_station"] = None       # linker

PRIO = {"disused": 99, "fire_station": 0, "dfg_facility": 1, "parking": 2, "fronton": 3, "sports_centre": 4, "community_centre": 5,
        "industrial": 6, "picnic_site": 7, "recreation_area": 8, "picnic_table_cluster": 9, "shelter": 10, "trailhead": 11}
P["_p"] = P.site_type.map(PRIO)
P = P.sort_values(["status", "_p", "in_tolosaldea_hint", "area_m2"], ascending=[True, True, False, False], kind="stable").reset_index(drop=True)
if "osm_id_list" not in P:
    P["osm_id_list"] = None
# v0.3: pool ids are STABLE across versions: a site keeps the id it had in v0.2 (same OSM type/id, site type and
# picnic-table list); only sites that did not exist get new ids after the last v0.2 id.
_key = lambda ot, oid, stt, lst: f"{ot}|{int(oid)}|{stt}|{'' if (lst is None or (isinstance(lst, float) and np.isnan(lst))) else lst}"
_old = pd.read_csv(V02_DIR / "candidate_pool.csv", dtype={"osm_id_list": str}) if (V02_DIR / "candidate_pool.csv").exists() else None
pool_id_stats = {}
if _old is not None:
    old_map = {_key(r.osm_type, r.osm_id, r.site_type, r.osm_id_list): r.pool_id for r in _old.itertuples()}
    keys = [_key(a_, b_, c_, d_) for a_, b_, c_, d_ in zip(P.osm_type, P.osm_id, P.site_type, P.osm_id_list)]
    assert len(set(keys)) == len(keys), "pool key not unique"
    nxt = int(_old.pool_id.str[5:].astype(int).max()) + 1
    ids = []
    for k_ in keys:
        if k_ in old_map:
            ids.append(old_map[k_])
        else:
            ids.append(f"POOL-{nxt:04d}"); nxt += 1
    P["pool_id"] = ids
    _st_old = dict(zip(_old.pool_id, _old.status))
    pool_id_stats = dict(kept_id=int(sum(k_ in old_map for k_ in keys)), new_id=int(sum(k_ not in old_map for k_ in keys)),
                         v02_sites_missing=int(len(set(old_map.values()) - set(P.pool_id))),
                         status_changed=[dict(pool_id=pid, v02=_st_old[pid], v03=st_)
                                         for pid, st_ in zip(P.pool_id, P.status) if pid in _st_old and _st_old[pid] != st_])
    log(f"pool ids: {pool_id_stats}")
else:
    P["pool_id"] = [f"POOL-{i + 1:04d}" for i in range(len(P))]
pcols = ["pool_id", "status", "reject_reason", "site_type", "subtype", "name", "osm_type", "osm_id", "osm_id_list", "lon", "lat",
         "x", "y", "area_m2", "surface", "access", "parking", "capacity", "fee", "operator", "n_picnic_tables",
         "nearest_parking_m", "dist_track_entry_m", "dist_trailhead_m", "snap_node_id", "snap_edge_id", "snap_dist_m",
         "snap_offset_m", "snap_edge_class", "snap_road_name", "nearest_any_edge_class", "nearest_any_edge_dist_m",
         "near_motorway_trunk", "track_snap_dist_m", "track_snap_edge_class", "muni_osm_hint", "ine_osm_hint",
         "in_tolosaldea_hint", "municipality_code", "baseline_min_light", "baseline_station"]
PO = P[pcols].copy().sort_values("pool_id").reset_index(drop=True)
for c_ in ["area_m2", "snap_dist_m", "snap_offset_m"]:
    PO[c_] = PO[c_].astype(float).round(1)
PO["lon"], PO["lat"] = PO.lon.round(6), PO.lat.round(6)
PO["x"], PO["y"] = PO.x.round(1), PO.y.round(1)
PO["source_id"] = SRC_OSM
PG = gpd.GeoDataFrame(PO, geometry=gpd.points_from_xy(PO.x, PO.y), crs=25830)
for p in [OUT / "candidate_pool.gpkg", OUT / "candidate_pool.geojson"]:
    if p.exists():
        p.unlink()
PG.to_file(OUT / "candidate_pool.gpkg", layer="candidate_pool", driver="GPKG", engine="pyogrio")
# polygons for review
PP = gpd.GeoDataFrame(P[["pool_id", "site_type", "status"]], geometry=P.geometry.values, crs=25830)
PP = PP[shapely.get_type_id(PP.geometry.values) >= 3]
if len(PP):
    PP.to_file(OUT / "candidate_pool.gpkg", layer="candidate_pool_footprints", driver="GPKG", engine="pyogrio")
PG.to_crs(4326).to_file(OUT / "candidate_pool.geojson", driver="GeoJSON", engine="pyogrio")
PO.to_csv(OUT / "candidate_pool.csv", index=False)
pool_stats = PO.groupby(["site_type", "status"]).size().unstack(fill_value=0)
pool_stats["ok_in_tolosaldea"] = PO[(PO.status == "ok") & (PO.in_tolosaldea_hint == 1)].groupby("site_type").size()
pool_stats = pool_stats.fillna(0).astype(int)
print(pool_stats)
print(PO[PO.status == "rejected"].reject_reason.value_counts())

# ----------------------------------------------------------------------------- v0.1 candidates re-evaluated
log("v0.1 candidates")
VC = pd.read_csv(V01 / "candidates_tolosaldea_10.csv")
VC["x"], VC["y"] = TO_UTM.transform(VC.lon.values, VC.lat.values)
s1 = snap_roads.snap(VC.x.values, VC.y.values)
for c_ in ["snap_node_id", "snap_dist_m", "snap_edge_class", "snap_road_name"]:
    VC["new_" + c_] = s1[c_].values
vpt = shapely.points(VC.x.values, VC.y.values)
pk_big = park_pub[(~park_pub.is_poly.astype(bool)) | (park_pub.area_m2 >= 400)]
pkb_tree = shapely.STRtree(pk_big.geometry.values)
qi, dd = pkb_tree.query_nearest(vpt, return_distance=True, all_matches=False)
o = np.argsort(qi[0])
VC["nearest_parking_ge400_m"] = dd[o].round(1)
VC["nearest_parking_ge400_area_m2"] = pk_big.area_m2.values[qi[1][o]].round(0)
ok = PO[PO.status == "ok"].reset_index(drop=True)
okt = cKDTree(np.column_stack([ok.x, ok.y]))
dd, ii = okt.query(np.column_stack([VC.x, VC.y]))
VC["nearest_pool_id"] = ok.pool_id.values[ii]
VC["nearest_pool_type"] = ok.site_type.values[ii]
VC["nearest_pool_name"] = ok.name.values[ii]
VC["nearest_pool_dist_m"] = dd.round(1)
jj = gpd.sjoin(gpd.GeoDataFrame(geometry=vpt, crs=25830), m8_capv[["name", "geometry"]], how="left", predicate="within")
VC["muni_osm_hint"] = jj[~jj.index.duplicated()].name.values
VC["muni_label_matches"] = [str(a) in str(b) for a, b in zip(VC.municipio, VC.muni_osm_hint)]
VC["in_tolosaldea_hint"] = VC.muni_osm_hint.isin(TOLOSALDEA)
# baseline time from nearest baseline station (light/truck, roads graph)
R = routers["roads"]
vc_vn = [R.add_point(a, b) for a, b in zip(s1.edge_row, s1.frac)]
R.build()
best = []
base_ids = S[S.include_in_baseline == 1].station_id.tolist()
for prof in ("light", "truck"):
    tt = []
    for sid in base_ids:
        d, _ = R.run(int(S.set_index("station_id").loc[sid, "_vn_roads"]), prof)
        tt.append(d[vc_vn])
    tt = np.array(tt)
    VC[f"new_baseline_min_{prof}"] = (tt.min(0) / 60).round(1)
    VC[f"new_baseline_station_{prof}"] = np.array(base_ids)[tt.argmin(0)]
VC["diff_baseline_min_light_vs_v01"] = (VC.new_baseline_min_light - VC.baseline_min_from_station).round(1)
VC["site_type_v01"] = VC.amenity.map(lambda a: f"{a} (POI; no reten site evidence)")
VC["site_type_assessment"] = np.where(VC.nearest_parking_ge400_m <= 150, "restaurant/cafe with parking>=400m2 within 150 m",
                                      "restaurant/cafe; no mapped parking>=400m2 within 150 m")
vcols = ["candidate_id", "poi_name", "amenity", "municipio", "muni_osm_hint", "muni_label_matches", "in_tolosaldea_hint", "lon", "lat",
         "site_type_v01", "site_type_assessment", "snap_m", "new_snap_dist_m", "new_snap_edge_class", "new_snap_road_name",
         "new_snap_node_id", "dist_to_parking_m", "nearest_parking_ge400_m", "nearest_parking_ge400_area_m2", "nearest_pool_id",
         "nearest_pool_type", "nearest_pool_name", "nearest_pool_dist_m", "baseline_min_from_station", "nearest_station",
         "new_baseline_min_light", "new_baseline_station_light", "new_baseline_min_truck", "new_baseline_station_truck",
         "diff_baseline_min_light_vs_v01"]
VC[vcols].round({"new_snap_dist_m": 1}).to_csv(OUT / "v01_candidates_reevaluated.csv", index=False)
print(VC[["candidate_id", "poi_name", "municipio", "muni_osm_hint", "new_snap_dist_m", "new_snap_edge_class", "nearest_parking_ge400_m",
          "nearest_pool_type", "nearest_pool_dist_m", "baseline_min_from_station", "new_baseline_min_light", "new_baseline_min_truck"]].to_string())

# ----------------------------------------------------------------------------- stats json
stats["stations"] = S[["station_id", "municipality", "dist_to_v01_m", "dist_to_osm_fire_station_m", "snap_distance_m",
                       "snap_edge_class", "relevance", "min_light_to_tolosa_centre", "n_tolosaldea_munis_nearest"]].round(1).to_dict("records")
stats["stations_raw_geom_types"] = {str(k): int(v) for k, v in raw_geom_types.items()}
stats["validation"] = VAL.to_dict("records")
stats["pool"] = {"by_type_status": pool_stats.reset_index().to_dict("records"),
                 "rejects": PO[PO.status == "rejected"].reject_reason.value_counts().to_dict(),
                 "ok_total": int((PO.status == "ok").sum()), "total": int(len(PO)),
                 "ok_in_tolosaldea": int(((PO.status == "ok") & (PO.in_tolosaldea_hint == 1)).sum())}
stats["v01_candidates"] = VC[vcols].round(2).to_dict("records")
stats["centres"] = C[["municipality", "centre_name", "centre_source", "snap_dist_m"]].round(1).to_dict("records")
stats["relevance_first"] = first
stats["relevance_second"] = second
stats["dropped_top"] = DC.drop(columns=["geometry"]).head(15).round(3).to_dict("records") if len(DC) else []
stats["navarra"] = nav_stats
stats["reclass_service_gi"] = reclass_stats
stats["pool_ids"] = pool_id_stats
stats["runtime_s"] = round(time.time() - T0, 1)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


(OUT / "network_stats.json").write_text(json.dumps(stats, indent=1, default=_default, ensure_ascii=False))

# ----------------------------------------------------------------------------- sources.csv (upsert own rows)
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


SRC_ROWS = [
    dict(source_id=SRC_OSM, dataset="OpenStreetMap extract País Vasco (.osm.pbf, full: includes *_link, track, service)",
         organisation="OpenStreetMap contributors, via Geofabrik GmbH",
         url="https://download.geofabrik.de/europe/spain/pais-vasco-260930.osm.pbf", licence="ODbL 1.0",
         download_date="2026-10-01", edition_or_period="OSM replication timestamp 2026-09-30T20:22:42Z",
         raw_file="raw/pais-vasco-260930.osm.pbf",
         processed_files="processed/network/roads.gpkg; graph_arcs.parquet; graph_nodes.parquet; candidate_pool.*; v01_candidates_reevaluated.csv",
         notes=f"sha256={sha256(PBF)}; download date = date file was received in the team workspace (verify); extract bbox lon -3.454..-1.662 lat 42.469..43.747; "
               "v0.3: road network = this file + SRC-OSM-GEOFABRIK-NAV-20260930 (ways in both files de-duplicated by OSM id, this copy kept); "
               "its use for municipal limits and vegetation is SUPERSEDED in v0.3 (2026-10-01) for municipal limits by SRC-GV-MUNICIPIOS5000-20250507 and for vegetation by "
               "SRC-GV-INVFORESTAL-2024 (OSM-based files kept as processed/territory/*_osm.*, processed/buildings/*_osm.*, processed/vegetation/vegetation_osm_provisional.gpkg; "
               "not deleted); still the source of the road network, POIs (candidate pool) and place nodes"),
    dict(source_id=SRC_NAV, dataset="OpenStreetMap extract Navarra (.osm.pbf, full: includes *_link, track, service)",
         organisation="OpenStreetMap contributors, via Geofabrik GmbH",
         url="https://download.geofabrik.de/europe/spain/navarra-latest.osm.pbf", licence="ODbL 1.0",
         download_date="2026-10-01", edition_or_period="OSM replication timestamp 2026-09-30T20:22:42Z (same snapshot as the País Vasco extract)",
         raw_file="raw/navarra-latest.osm.pbf",
         processed_files="processed/network/roads.gpkg (road_edges.source_id); graph_arcs.parquet; graph_nodes.parquet",
         notes=f"sha256={sha256(PBF_NAV)}; md5=daaa7be9869a50e2e600cd20f6ed236f (as published by Geofabrik, checked); 37,418,361 bytes; downloaded via the browser on Carlos's PC "
               "(reports/collector_downloads.md); extract bbox lon -2.502..-0.626 lat 41.906..43.372; used ONLY for roads (highway ways + admin_level=8 polygons for the NAV region flag); "
               "no Navarra fire station is loaded (no official source) -> Navarra parks are NOT origins"),
    dict(source_id=SRC_B5M, dataset="GFA_DSET_FIREST · Suhiltzaile etxeak / Parques de bomberos / Fire Stations",
         organisation="Diputación Foral de Gipuzkoa · B5M", url="https://b5m.gipuzkoa.eus/web5000/es/api-rest/conjuntos-datos",
         licence="B5M open data terms (verify: CC BY 4.0 expected)", download_date="2026-10-01",
         edition_or_period="gpkg_contents.last_change 2026-09-28T04:38:52Z", raw_file="raw/GFA_DSET_FIREST.gpkg; raw/GFA_DSET_FIREST_es.csv",
         processed_files="processed/network/fire_stations.gpkg; fire_stations.geojson; fire_stations.csv",
         notes=f"sha256={sha256(FIREST)}; 10 points EPSG:25830; geometry column declared GEOMETRY (generic) but all 10 are valid Points; exact dataset URL to record (verify)"),
    dict(source_id="SRC-FLAIRE-P4-V01", dataset="flAIre Persona 4 package v0.1 (approx. stations, 10 candidates, roads with synthetic connectors)",
         organisation="Team flAIre (derived)", url="https://claude.ai (team workspace, no public URL)", licence="derived (ODbL for OSM-derived parts)",
         download_date="2026-10-01", edition_or_period="v0.1 2026-10-01", raw_file="raw/persona4_accesos_bomberos/",
         processed_files="processed/network/v01_candidates_reevaluated.csv; validation_routes.csv; fire_stations.csv (dist_to_v01_m)",
         notes="used only for comparison; superseded by v0.2 network"),
    dict(source_id="SRC-OSM-AMENITIES-CSV", dataset="basque_country_readable.csv (OSM amenities name/amenity/lon/lat, pyrosm export)",
         organisation="OpenStreetMap contributors (team export)", url="https://www.openstreetmap.org (export date unknown)", licence="ODbL 1.0",
         download_date="2026-10-01", edition_or_period="unknown OSM snapshot", raw_file="raw/basque_country_readable.csv",
         processed_files="(none; v0.1 POI source)", notes=f"sha256={sha256(RAW / 'basque_country_readable.csv')}; not used in v0.2 pool (PBF used instead, dated snapshot)"),
]
src_path = REP / "sources.csv"
FIELDS = ["source_id", "dataset", "organisation", "url", "licence", "download_date", "edition_or_period", "raw_file",
          "processed_files", "notes"]
existing, header = [], list(FIELDS)
if src_path.exists():
    with open(src_path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        existing = [r for r in rd]
        header = list(rd.fieldnames or []) + [c for c in FIELDS if c not in (rd.fieldnames or [])]
mine = {r["source_id"] for r in SRC_ROWS}
existing = [r for r in existing if r.get("source_id") not in mine]
with open(src_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    for r in existing + SRC_ROWS:
        w.writerow(r)
log("done; outputs in", OUT)


# ----------------------------------------------------------------------------- 5. quality report
log("writing reports/quality_network.md")


def md(df, floatfmt=1):
    df = df.copy()
    for c_ in df.columns:
        if pd.api.types.is_float_dtype(df[c_]):
            df[c_] = df[c_].map(lambda v: "" if pd.isna(v) else f"{v:,.{floatfmt}f}")
    cols = [str(c_) for c_ in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join("" if (x is None or (isinstance(x, float) and np.isnan(x)) or str(x) in ("nan", "None", "<NA>"))
                                     else str(x).replace("|", "/") for x in r) + " |")
    return "\n".join(out)


g = stats["graph"]
bbN = N[(N.lon.between(BB_W, BB_E)) & (N.lat.between(BB_S, BB_N))]
road_in_bb = used_roads[bbN.idx.values]
aoi_share = float(main_roads[bbN.idx.values][road_in_bb].mean())
aoi_share_t = float(main_all[bbN.idx.values][road_in_bb].mean())
stats["graph"]["aoi_bbox_scc_share_with_tracks"] = round(aoi_share_t, 5)
truck_ratio = (VAL.min_truck / VAL.min_light - 1) * 100
stats["graph"]["aoi_bbox_road_nodes"] = int(road_in_bb.sum())
stats["graph"]["aoi_bbox_scc_share"] = round(aoi_share, 5)
nav_bb = E[(E.region == "NAV")]
nav_mid = shapely.line_interpolate_point(nav_bb.geometry.values, 0.5, normalized=True)
nlo, nla = TO_WGS.transform(shapely.get_x(nav_mid), shapely.get_y(nav_mid))
nav_near = nav_bb[(nlo > -2.25) & (nlo < -1.85) & (nla > 42.95) & (nla < 43.25)]
(OUT / "network_stats.json").write_text(json.dumps(stats, indent=1, default=_default, ensure_ascii=False))

excl_df = pd.DataFrame([(k, v[0], v[1]) for k, v in stats["rules"]["excluded_ways"].items()],
                       columns=["reason", "ways", "km"]).sort_values("km", ascending=False)
cls_df = pd.DataFrame(g["by_class"])[["fclass", "edges", "km", "speed_kmh_mean", "maxspeed_share", "in_main"]]
cls_df["class_speed_kmh"] = cls_df.fclass.map(BASE_SPEED)
cls_df["truck_factor"] = np.where(cls_df.fclass.isin(HIGH_CLASSES), TRUCK_FACTOR_HIGH, TRUCK_FACTOR_LOW)
cls_df = cls_df[["fclass", "class_speed_kmh", "truck_factor", "edges", "km", "speed_kmh_mean", "maxspeed_share", "in_main"]]
cls_df = cls_df.rename(columns={"speed_kmh_mean": "mean speed_used", "maxspeed_share": "share w/ maxspeed", "in_main": "share in main SCC"})
val_md = VAL[["origin", "destination", "km_light", "min_light", "min_truck", "min_light_with_tracks",
              "min_light_no_motorway_trunk", "min_light_from_v01_position", "v01_km", "v01_min", "diff_pct_light_vs_v01", "light_path_roads_dest_to_origin"]].copy()
val_md.columns = ["from", "to", "km", "min light", "min truck", "min light +tracks", "min light no motorway/trunk", "min light from v0.1 position",
                  "v0.1 km", "v0.1 min", "Δ% light vs v0.1", "roads used (dest ← origin)"]
st_md = S[["station_id", "b5mcode", "municipality", "address", "operator", "dist_to_v01_m", "dist_to_osm_fire_station_m",
           "snap_distance_m", "snap_edge_class", "min_light_to_tolosa_centre", "v01_min_to_tolosa",
           "n_tolosaldea_munis_nearest", "n_tolosaldea_munis_second", "relevance"]].copy()
st_md.columns = ["station_id", "b5m", "municipality", "address (B5M)", "operator", "Δ v0.1 pos (m)", "Δ OSM fire_station (m)",
                 "snap (m)", "snap class", "min → Tolosa centre", "v0.1 min → Tolosa", "1st for n munis", "2nd for n munis", "relevance"]
pool_md = pool_stats.reset_index()
rej_md = PO[PO.status == "rejected"].reject_reason.value_counts().rename_axis("reject_reason").reset_index(name="n")
vc_md = VC[["candidate_id", "poi_name", "municipio", "muni_osm_hint", "new_snap_dist_m", "new_snap_edge_class",
            "nearest_parking_ge400_m", "nearest_pool_id", "nearest_pool_type", "nearest_pool_dist_m",
            "baseline_min_from_station", "new_baseline_min_light", "new_baseline_min_truck", "new_baseline_station_light"]].copy()
vc_md.columns = ["cand", "POI", "label v0.1", "muni (OSM admin8)", "snap m", "snap class", "parking≥400 m² (m)", "nearest pool site",
                 "type", "dist m", "v0.1 min", "v0.2 min light", "v0.2 min truck", "nearest station"]
dc_top = DC.drop(columns=["geometry"]).head(12)[["n_edges", "km", "main_class", "names", "muni_osm", "region", "kind", "lon", "lat"]] if len(DC) else pd.DataFrame()
dc_gip = DC[DC.in_gipuzkoa == 1].drop(columns=["geometry"]).head(8)[["n_edges", "km", "main_class", "names", "muni_osm", "kind", "lon", "lat"]] if len(DC) else pd.DataFrame()
rel_tab = REL[REL.rank_light <= 2].pivot_table(index="municipality", columns="rank_light", values=["station_id", "min_light"], aggfunc="first")
rel_tab.columns = [f"{a}_{b}" for a, b in rel_tab.columns]
rel_tab = rel_tab.reset_index()[["municipality", "station_id_1", "min_light_1", "station_id_2", "min_light_2"]]
rel_tab.columns = ["municipality (centre)", "nearest station", "min light", "2nd station", "min light 2nd"]

ok_tol = int(((PO.status == "ok") & (PO.in_tolosaldea_hint == 1)).sum())
v = VAL.set_index("destination")
# ---- v0.3 vs v0.2 comparison (Navarra roads)
v02s = json.loads((V02_DIR / "network_stats.json").read_text()) if (V02_DIR / "network_stats.json").exists() else None
V02VAL = pd.read_csv(V02_DIR / "validation_routes.csv") if (V02_DIR / "validation_routes.csv").exists() else None
cmp_rows = []
if v02s is not None:
    g2 = v02s["graph"]
    for lab, key, fmt in [("highway ways read", None, "{:,}"), ("ways kept", "ways_kept", "{:,}"), ("edges", "edges", "{:,}"),
                          ("nodes", "nodes", "{:,}"), ("directed arcs", "arcs", "{:,}"), ("km roads", "km_roads", "{:,.0f}"),
                          ("km tracks", "km_tracks", "{:,.0f}"), ("NAV km (all)", "nav_km", "{:,.0f}"),
                          ("nodes in roads main SCC", "scc_roads_nodes", "{:,}"),
                          ("road nodes in Tolosaldea bbox in main SCC (%)", "aoi_bbox_scc_share", "{:.2%}"),
                          ("dropped road components (all)", "dropped_components", "{:,}"),
                          ("dropped components in Tolosaldea bbox", "dropped_in_bbox_components", "{:,}"),
                          ("dropped km in Gipuzkoa", "dropped_in_gipuzkoa_km", "{:,.0f}")]:
        if key is None:
            a2, a3 = sum(v02s["input"]["ways_by_highway"].values()), len(ways)
        elif key == "nav_km":
            a2, a3 = g2["region"].get("NAV", 0), g["region"].get("NAV", 0)
        else:
            a2, a3 = g2.get(key), g.get(key)
        cmp_rows.append({"measure": lab, "v0.2 (PV only)": fmt.format(a2) if a2 is not None else "",
                         "v0.3 (PV + Navarra)": fmt.format(a3) if a3 is not None else ""})
CMP = pd.DataFrame(cmp_rows)
a15 = DC[(DC.in_gipuzkoa == 1) & DC.names.str.contains("Leitzarango|Nafarroa-Gipuzkoa", na=False)] if len(DC) else DC
if V02VAL is not None:
    VV = VAL[["origin", "destination", "km_light", "min_light", "min_truck"]].merge(
        V02VAL[["origin", "destination", "km_light", "min_light", "min_truck"]], on=["origin", "destination"], suffixes=("_v03", "_v02"))
    VV["Δ min light"] = (VV.min_light_v03 - VV.min_light_v02).round(1)
    VV = VV[["origin", "destination", "km_light_v02", "km_light_v03", "min_light_v02", "min_light_v03", "Δ min light", "min_truck_v02", "min_truck_v03"]]
else:
    VV = pd.DataFrame()
ns = nav_stats
report = f"""# flAIre · Persona 4 · Network quality report (v0.3.1)

Generated by `code/network.py` on {time.strftime('%Y-%m-%d %H:%M')} (runtime {time.time() - T0:.0f} s). All numbers below are written by the script
(also in `processed/network/network_stats.json`); re-running the script regenerates this file.

**What changed in v0.3:** Navarra roads added from `raw/navarra-latest.osm.pbf` (Geofabrik, same OSM snapshot), de-duplicated against the
País Vasco extract by OSM way id; same rules otherwise. Effect and comparison with v0.2: §10.

**What changed vs v0.1:** the network is rebuilt from the full Geofabrik `.osm.pbf` (not the `drivable_roads.geojson` export),
so **all `*_link` ramps are present ({g['link_edges']:,} link edges, {g['link_km']:.0f} km) and there are 0 synthetic connectors**.
Fire stations come from the official B5M layer. Candidates come from an explainable site-type pool, not from restaurants.

## 1. Source

| item | value |
|---|---|
| file | `raw/pais-vasco-260930.osm.pbf` (Geofabrik País Vasco), OSM replication timestamp **2026-09-30T20:22:42Z**, ODbL 1.0 (`{SRC_OSM}`) |
| file (v0.3) | `raw/navarra-latest.osm.pbf` (Geofabrik Navarra), OSM replication timestamp **2026-09-30T20:22:42Z**, ODbL 1.0, md5 daaa7be9869a50e2e600cd20f6ed236f (`{SRC_NAV}`) — roads + admin8 polygons only |
| de-duplication | {ns['ways_read_nav']:,} highway ways read from Navarra; {ns['dup_total']:,} also in the País Vasco file ({ns['dup_identical']:,} identical, {ns['dup_different_nodes']} with different node lists, {ns['dup_different_tags']} with different tags → País Vasco copy kept); **{ns['added_from_nav']:,} added** |
| reader | pyosmium {PYOSMIUM_VERSION} (ways with node locations, multipolygon assembly for areas) |
| CRS | lengths/snaps in EPSG:25830 (pyproj), GeoJSON exports in EPSG:4326 |
| ways read | {len(ways):,} highway ways of the 15 classes considered ({', '.join(f"{k} {v:,}" for k, v in sorted(hw_counts.items(), key=lambda x: -x[1]))}) |
| ways kept | {g['ways_kept']:,} |

## 2. Inclusion rules and decisions

* Classes: motorway, trunk, primary, secondary, tertiary (+ their `_link`), unclassified, residential, living_street, service, **and track**
  (separate class, flag `is_track = 1`). `highway=road` (1 way), `busway`, `construction`, `proposed`, paths/footways are not drivable and are excluded.
* `service`: **kept** `driveway`, `alley`, `emergency_access` and untagged service roads (driveways are the only access to many
  caseríos, which the building linker needs). **Excluded** `parking_aisle` (internal circulation of car parks; the car park is reached via its
  street, and keeping the aisles would let routes cut through car parks), `drive-through`, `slipway`.
* Access: excluded if `access=private|no` unless `emergency|fire_engine=yes|designated` or `motor_vehicle|motorcar|vehicle` in
  (yes, designated, permissive, destination); excluded if `access` is absent and `motor_vehicle|motorcar|vehicle=private|no`; `access=bus` excluded.
  Conditional access (destination, customers, forestry, agricultural, permit, …) is **kept** and recorded in `access_flag`.
  Emergency vehicles may legally use some excluded roads; this is conservative and it is the main reason for small isolated islands (§4).
* `area=yes` highways excluded (squares drawn as polygons).

{md(excl_df)}

* Direction: `oneway=yes/true/1` → F (digitised direction), `-1/reverse` → T, `no`, `reversible`, `alternating` → B;
  `junction=roundabout|circular` implies F; `highway=motorway|motorway_link` implies F unless `oneway=no`.
  Result: {g['oneway'].get('B', 0):,} two-way edges, {g['oneway'].get('F', 0):,} F, {g['oneway'].get('T', 0)} T.
* **Topology:** every way is split at every OSM node shared by two or more kept ways (or repeated inside the same way) and at its ends. No
  snapping, no geometric noding, no synthetic connectors. Closed ways with a single junction node (e.g. cul-de-sac loops) are additionally split at
  an interior vertex so that `u ≠ v` always holds ({g['loop_split_nodes']} extra nodes). Bridges/tunnels therefore never connect to what they cross.
* Node id = OSM node id (`node_id`), edge `osm_id` = OSM way id. Edge length = sum of segment lengths in EPSG:25830.

### Speeds

`speed_used_kmh = min(maxspeed_OSM, class speed)` when `maxspeed` is tagged (`speed_source = osm_maxspeed_capped`), else the class speed
(`class_assumed`). `*_link` = parent class × {LINK_FACTOR}. Track = 10 km/h. Truck profile = speed_used × {TRUCK_FACTOR_HIGH} on motorway/trunk/primary
(+links) and × {TRUCK_FACTOR_LOW} on secondary and below (incl. tracks). {g['speed_clamped_to_5']} edges with `maxspeed` < 5 (values 1–3 km/h) are clamped to 5 km/h
(schema CHECK ≥ 5). `maxspeed` is present on {100 * g['speed_source_share_roads'].get('osm_maxspeed_capped', 0):.1f} % of road edges
({100 * g['maxspeed_present_share_km_roads']:.1f} % of road km), so **≈ 85 % of speeds are assumed**. No turn penalties, junction delays, slopes or traffic.
`t_light_s = length / speed_used`, `t_truck_s = length / speed_truck`.

{md(cls_df, 3)}

## 3. Graph

| measure | value |
|---|---|
| edges (`road_edges`) | {g['edges']:,} ({g['km_total']:,.0f} km: roads {g['km_roads']:,.0f} km, tracks {g['km_tracks']:,.0f} km) |
| nodes (`road_nodes`) | {g['nodes']:,} |
| directed arcs (`graph_arcs.parquet`) | {g['arcs']:,} |
| `*_link` edges | {g['link_edges']:,} ({g['link_km']:.0f} km) — v0.1 had 0 |
| synthetic connectors | **0** — v0.1 had 1,561 |
| region (edge midpoint) | PV {g['region'].get('PV', 0):,.0f} km · NAV {g['region'].get('NAV', 0):,.0f} km · OTHER {g['region'].get('OTHER', 0):,.0f} km |
| NAV km near Tolosaldea (lon −2.25…−1.85, lat 42.95…43.25) | {nav_near.length_m.sum() / 1000:.0f} km ({(nav_near.is_track == 1).mean() * 100:.0f} % tracks) — v0.2: 98 km (boundary buffer only) |
| edges by source | {'; '.join(f"{r['source_id']}: {r['n']:,} edges / {r['km']:,.0f} km" for r in ns['edges_by_source'])} |

Region rule (v0.3, column `region_rule`): midpoint inside an OSM admin_level=8 municipality with INE code 01/20/48, or inside the Gipuzkoa/Araba admin_level=6 polygons → `PV`;
inside a Navarra admin_level=8 municipality (INE 31xxx, {ns['navarra_admin8_polygons']} polygons assembled from the Navarra extract) → `NAV`;
inside La Rioja/Burgos/Cantabria/Aragón municipalities or a French commune → `OTHER`; midpoints in no polygon (e.g. Bardenas, facerías, unassembled units) → heuristic
`NAV` if −2.42 < lon < −1.0 and not in the French corner, else `OTHER`. km by region and rule: {'; '.join(f"{r['region']}/{r['region_rule']} {r['length_m']:,.0f}" for r in ns['region_by_rule_km'])}. `OTHER` edges (Rioja Alavesa and Karrantza are only connected through them) are kept for
connectivity; they are **rejected by the current schema CHECK `region IN ('PV','NAV')`** (tested: all {int((E.region != 'OTHER').sum()):,} PV/NAV edges load
into `schema.sql` with no constraint error; the {int((E.region == 'OTHER').sum()):,} OTHER edges fail). Manager: add `'OTHER'` to the CHECK, or load `WHERE region <> 'OTHER'`
(no effect on Tolosaldea).

## 4. Largest strongly connected component (what is dropped)

Two directed graphs are built from the same edges: **roads** (tracks excluded; DEFAULT, flag `in_main_component`) and **roads + tracks**
(`in_scc_with_tracks`). Only the largest strongly connected component (SCC) of each is routable.

| measure | roads (default) | roads + tracks |
|---|---|---|
| nodes in main SCC | {g['scc_roads_nodes']:,} ({100 * g['scc_roads_share_of_road_nodes']:.2f} % of road nodes) | {g['scc_all_nodes']:,} |
| road nodes in the Tolosaldea bbox in main SCC | {100 * aoi_share:.2f} % of {g['aoi_bbox_road_nodes']:,} (pipeline target ≥ 99 %: **not met**, see below) | {100 * aoi_share_t:.2f} % |
| dropped road edges / km | {g['dropped_roads_edges']:,} / {g['dropped_roads_km']:.0f} km in {g['dropped_components']:,} components | tracks in SCC: {g['tracks_in_scc_km']:,.0f} of {g['km_tracks']:,.0f} km |
| dropped in Gipuzkoa | {g['dropped_in_gipuzkoa_km']:.0f} km | |
| dropped inside the Tolosaldea bbox | {g['dropped_in_bbox_components']} components, {g['dropped_in_bbox_km']:.1f} km | |
| nodes reachable only through tracks | — | {g['nodes_only_via_tracks']:,} (mostly track-internal nodes) |

The {100 - 100 * aoi_share:.2f} % of road nodes in the Tolosaldea bbox outside the main SCC are the {g['dropped_in_bbox_components']} small components listed in
`dropped_components.csv` ({g['dropped_in_bbox_km']:.1f} km, mostly service driveways reachable only through a track or an excluded private road); with tracks the
share is {100 * aoi_share_t:.2f} %. The linker should snap buildings to `in_main_component = 1` nodes and report `snap_too_far` / `disconnected_component` rather than drop them.

Kinds: `island` = not touching the main SCC (roads whose only connection is a track, an excluded private/no road, a parking aisle or a footway);
`attached_oneway_or_trap` = touches the main SCC but can only be entered or left (one-way dead ends, and **motorway carriageways cut at the
extract boundary**: e.g. the A-15 between the last Berastegi junction and the Navarra border, and the A-1 towards Altsasu). Every dropped component is
in `roads.gpkg|dropped_components` and `dropped_components.csv` (km, names, OSM municipality, lon/lat).

Largest dropped components (all regions):

{md(dc_top, 2)}

Largest in Gipuzkoa:

{md(dc_gip, 2)}

## 5. Validation against the v0.1 manual checks

Official B5M station positions (§6), town centre = OSM `place` node of the municipality (Villabona for Amasa-Villabona), snapped to the nearest
road edge of the main SCC (excluding motorway/trunk); routes are node-to-node Dijkstra plus the partial edge at each end.

{md(val_md)}

Why they differ:

* **Amezketa {v.iloc[0]['diff_pct_light_vs_v01']:+.0f} % ({v.iloc[0]['min_light']} vs 16.1 min, {v.iloc[0]['km_light']:.1f} vs 13.4 km).** The fastest v0.2 route takes the N-I for
  {json.loads(v.iloc[0]['light_path_km_by_class']).get('motorway', 0):.1f} km (Tolosa → Alegia, entering/leaving by real `motorway_link` ramps) and then GI-2131/GI-2133.
  Forbidding motorway/trunk on the same network gives **{v.iloc[0]['min_light_no_motorway_trunk']} min / {v.iloc[0]['km_light_no_motorway_trunk']} km**, i.e. the v0.1 value
  corresponds to a route that did not use the N-I (no ramps in v0.1; its synthetic connectors only joined motorway segment ends). The station position is not the cause
  (from the v0.1 position: {v.iloc[0]['min_light_from_v01_position']} min). This is v0.1 problem 1 being fixed, not a regression.
* **Berastegi ({v.iloc[1]['diff_pct_light_vs_v01']:+.0f} %), Lizartza ({v.iloc[3]['diff_pct_light_vs_v01']:+.0f} %)** — same roads (GI-2135, GI-2130), no motorway: v0.1 and v0.2 agree; the
  residual ~0.2–0.3 min is the official station position (B5M point is {S.set_index('station_id').at['GIP-ORIA', 'dist_to_v01_m']:.0f} m from the v0.1 point).
* **Villabona ({v.iloc[2]['diff_pct_light_vs_v01']:+.0f} %, {v.iloc[2]['min_light']} vs 5.5 min, {v.iloc[2]['km_light']:.1f} vs 7.6 km)**: N-I for
  {json.loads(v.iloc[2]['light_path_km_by_class']).get('motorway', 0):.1f} km via real ramps; from the v0.1 position {v.iloc[2]['min_light_from_v01_position']} min, so about half of
  the difference is the station position and half the ramps vs synthetic connectors. Within ±15 %.
* **Goierri → Tolosa**: v0.1's "Tolosa centre" was the Oria node (v0.1 `min_to_tolosa_center` = 0.0 for GIP-ORIA). Like-for-like (Goierri → Oria station)
  v0.2 gives **{VAL.iloc[5]['min_light']} min / {VAL.iloc[5]['km_light']} km** vs 9.6 ({VAL.iloc[5]['diff_pct_light_vs_v01']:+.0f} %). To the OSM place node of Tolosa (old town,
  {VAL.iloc[4]['dest_snap_m']:.0f} m snap) it is {VAL.iloc[4]['min_light']} min (the extra ~2 min are 30 km/h streets inside Tolosa). The v0.1 24-min figure (no links) is gone;
  without motorway/trunk it would be {VAL.iloc[5]['min_light_no_motorway_trunk']} min.
* Including tracks (10 km/h) changes none of these routes. The truck profile adds {truck_ratio.min():.0f}–{truck_ratio.max():.0f} %.
* All checks are within the manager's ±15 % except Amezketa, which is explained by the link fix.

## 6. Fire stations (B5M `GFA_DSET_FIREST`)

* 10 records, EPSG:25830. `gpkg_geometry_columns` declares the generic type **GEOMETRY** (shown as 'Unknown' by some readers), but all 10 geometries
  are valid **Points** ({stats['stations_raw_geom_types']}); field dictionary says "punto central". Used as published (representative point would only be
  applied to non-points: none). Layer `last_change` 2026-09-28.
* `loc_confidence = address_street` (closest schema value: official B5M address point, **not** checked on orthophoto), `loc_method` explains it.
  Independent check: OSM `amenity=fire_station` polygons for Oria, Goierri and Urola lie within 6–18 m of the B5M points.
* **Hondarribia (E_A83498, "Suhiltzaileak / Bomberos", Gabarrari kalea 24)** is not one of the 9 parks of v0.1: the point falls in the San Sebastián
  airport area (likely the AENA airport fire service — to verify). Kept as `OTH-HONDARRIBIA`, operator `other`, `include_in_baseline = 0`.
  The schema expects 9 rows: load 10 with this flag, or skip it.
* Garbera: B5M has no operator field; `municipal` (Donostia city fire service) is taken from v0.1.
* There is **no station in Hernani/Andoain** in the official layer.

{md(st_md)}

Relevance for Tolosaldea (travel time from each station to the 28 municipal centres, light profile): **Oria is the nearest station for
{first.get('GIP-ORIA', 0)} of 28 centres**; Goierri is nearest for {first.get('GIP-GOIERRI', 0)} and second for {second.get('GIP-GOIERRI', 0)}; Garbera is second for
{second.get('DON-GARBERA', 0)}, Urola for {second.get('GIP-UROLA', 0)}. Kosta and Korosti only within 20 min of the closest centre (context); Arrate, Zubillaga, Bidasoa far.
Full matrix in `station_relevance.csv`.

{md(rel_tab)}

## 7. Candidate pool (not the final 10)

Bbox lon {BB_W}…{BB_E}, lat {BB_S}…{BB_N}, from the same PBF (nodes + assembled multipolygons). Rules (in priority order when an object has several tags):

| site_type | rule | representative point |
|---|---|---|
| fire_station | `amenity=fire_station` | point on surface |
| dfg_facility | name/operator matches Foru Aldundia / Diputación Foral / Bidezain / Camineros, or `office=government` (`subtype` says which), or `landuse=depot` | point on surface |
| parking | `amenity=parking`; polygons ≥ 400 m² or nodes (area NULL); rejected: underground / multi-storey / rooftop (headroom), `< 400 m²`, nodes within 25 m of a parking polygon (duplicate). `subtype = mountain_access` if ≤ 100 m from a track entry (track meeting the road SCC) or ≤ 150 m from `highway=trailhead` | point on surface |
| fronton / sports_centre / community_centre | `sport~pelota`, `leisure=sports_centre`, `amenity=community_centre`; **requires a public parking feature within 150 m** | point on surface |
| industrial | `landuse=industrial` ≥ 2,000 m² | point on the internal road nearest the polygon centre, or the polygon point closest to the nearest road |
| picnic_site / picnic_table_cluster / recreation_area / shelter | `tourism|leisure=picnic_site`; `leisure=picnic_table` single-link clusters (50 m, ≥ 2 tables; merged into a picnic site within 100 m); `recreation_ground` ≥ 400 m² or name ~ área recreativa / atseden / aisialdi (not buildings); `amenity=shelter` except `shelter_type=public_transport` | point on surface |

All types: `access=private|no` rejected; disused/ruins rejected. Snap = nearest edge of the roads main SCC **excluding motorway/trunk and their links**
(`snap_dist_m`, `snap_edge_class`, `snap_node_id` = nearer end of that edge, `snap_offset_m`); **rejected if > 150 m**; if the road snap is > 150 m but a track
is ≤ 150 m the reason is `track_access_only` (usable only in the with-tracks variant). `nearest_any_edge_class` + `near_motorway_trunk` show sites next to
a motorway/trunk. `muni_osm_hint` / `in_tolosaldea_hint` are from OSM admin_level=8 and are **hints only**: `municipality_code`, `baseline_min_light` and
`baseline_station` are left NULL for the linker (official P2 municipalities, travel_times).

**{int((PO.status == 'ok').sum())} usable sites of {len(PO):,} evaluated; {ok_tol} usable inside Tolosaldea (OSM hint).**

{md(pool_md)}

{md(rej_md)}

### v0.1 CAND-01…10 re-evaluated (`v01_candidates_reevaluated.csv`)

{md(vc_md)}

* All 10 still snap ≤ 23 m to the new graph (none onto motorway/trunk); baseline times move by +0.2…+0.6 min (official station positions, real ramps).
* All 10 are restaurants/cafés: none is itself a reten site type. 7 of 10 have a mapped public car park ≥ 400 m² within 150 m (v0.1 reported
  the nearest parking at 0.3–8.4 km because it used parking nodes from the POI file only). CAND-04 (Albiztur), CAND-05 and CAND-06 (Asteasu) have none.
* **CAND-01 "Villabona" falls in Zizurkil** according to OSM admin boundaries (border area); to confirm with the P2 municipalities.
* **CAND-05 "Tolosa" (43.050, −2.041)** is inside Tolosa's southern **exclave** (OSM Tolosa multipolygon has 3 parts; this is the Bedaio area), so the label
  is plausibly right even though it is ~9 km from Tolosa town; it remains the worst-served v0.1 site (17.7 min light / 21.8 truck) and has a picnic site 20 m away.
* CAND-10 (Baliarrain) is now closer to Goierri than to Oria.

## 8. Remaining limits

1. **Navarra roads are now included (v0.3)**, but **no Navarra fire station is an origin**: the package has no official Navarra station layer (Leitza,
   Lekunberri, Altsasu…), so travel times only use the 9 Gipuzkoa parks; a Navarra park could serve some border buildings faster. To add them an official
   source (Gobierno de Navarra / SEPEI) is needed. Speeds and access rules in Navarra are the same OSM class assumptions.
2. **Assumed speeds** (≈ 85 % of edges), no traffic, no turn/junction delays, no slope, no road width/weight limits. Truck factors 0.8/0.9 are an assumption, not a
   fire-truck measurement. `hgv=no` (141 ways) is recorded but not applied (emergency vehicles exempt). Times are travel estimates, not response times.
3. Access rule is conservative (private/no excluded even if emergency services may pass); conditional access kept.
4. Tracks are 10 km/h regardless of `tracktype`; grade1 (paved) tracks are probably faster. Results with tracks are a variant only.
5. B5M station points not checked on orthophoto (sandbox has no access); v0.1 offsets up to 1.1 km (Korosti) are now corrected.
6. Candidate pool depends on OSM completeness (car parks and frontones are unevenly mapped); site types are study proposals, not authorised sites. Ownership, gates,
   surface, water and turning space must be checked (v0.1 ficha checklist still applies).
7. Municipality fields are OSM hints; official assignment is the linker's job (P2 boundaries).
8. Download date of the PBF/B5M files = date received in the workspace (2026-10-01); exact B5M dataset URL to be recorded by the collector.

## 9. Files

`processed/network/`: `roads.gpkg` (road_edges, road_nodes, dropped_components; EPSG:25830), `graph_arcs.parquet` + `graph_nodes.parquet` (routing; filter
`in_main_component == 1` for the default graph or `in_scc_with_tracks == 1` for the tracks variant; `u_idx/v_idx` index `graph_nodes.idx`), `fire_stations.gpkg/.geojson/.csv`,
`candidate_pool.gpkg` (points + `candidate_pool_footprints`) / `.csv` / `.geojson`, `v01_candidates_reevaluated.csv`, `validation_routes.csv`, `station_relevance.csv`,
`dropped_components.csv`, `network_stats.json`. Sources: `reports/sources.csv` ({SRC_OSM}, {SRC_NAV}, {SRC_B5M}, SRC-FLAIRE-P4-V01, SRC-OSM-AMENITIES-CSV).
v0.2 csv/json outputs are frozen in `processed/network/v0.2/` for comparison.

## 10. v0.3 — Navarra roads: what changed

{md(CMP)}

* A-15 / N-130 (Leitzarango autobia, Nafarroa-Gipuzkoa autobidea) carriageways cut at the extract border in v0.2: {'still dropped: ' + str(len(a15)) + ' component(s)' if len(a15) else '**now part of the main SCC** (0 dropped components with these names)'}.
* Pool ids are stable: {pool_id_stats.get('kept_id', 0)} sites keep their v0.2 id, {pool_id_stats.get('new_id', 0)} new, {pool_id_stats.get('v02_sites_missing', 0)} v0.2 sites missing; status changes: {pool_id_stats.get('status_changed', [])}.
* Validation routes v0.2 → v0.3 (same rules; any difference = Navarra roads or SCC changes):

{md(VV)}

* The effect on building travel times (how many analysis buildings now have a fastest park route through Navarra, change of the baseline) is computed by
  the linker (`code/link_build.py`, report `reports/linker_validation.md` §1–§3), because it needs the building set and the full routing.

## 11. v0.3.1 — service ways carrying a foral road number

`highway=service` ways whose `ref` matches `^GI-` (Gipuzkoa foral road numbers, e.g. way 230176767 'Aldaba auzoa' = GI-3712, asphalt) are
mis-tagged roads: they are treated as **`unclassified` (40 km/h)** with `speed_source = 'reclass_service_with_GI_ref'` (original tag kept in `fclass_osm`).
Changed: **{reclass_stats['edges']} edges, {reclass_stats['km']:.2f} km, {reclass_stats['ways']} ways** ({reclass_stats['with_maxspeed']} with a maxspeed tag, capped as usual).

{md(pd.DataFrame(reclass_stats['list']), 3)}
"""
(REP / "quality_network.md").write_text(report, encoding="utf-8")
log("report written")
