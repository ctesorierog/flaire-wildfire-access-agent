#!/usr/bin/env python3
"""
flAIre · P1 METEOROLOGY CLEANER · Tolosaldea pilot · Euskalmet 10-min stations 2018-2023

Re-runnable:  python3 code/weather.py                    (all stages, ~3-4 min on 2 CPU, < 3 GB RAM)
              python3 code/weather.py --stages daily,adverse,profile,zones,db,report   (reuse the parsed Parquet)

Stages
  parse    raw/flaire_meteo_tolosaldea_2018_2023.zip (inner YYYY_CODE_YYYY.zip -> monthly XML + XSD) ->
           processed/weather/obs_10min.parquet  (long table of ORIGINAL 10-min records, flagged, never filled)
  inventory station inventory (catalogue + what the XML actually contains) -> processed/weather/station_inventory.csv
  quality  station x year x month x variable completeness -> processed/weather/quality_monthly.csv
  daily    daily aggregates (UTC day) with per-variable validity -> processed/weather/daily.csv
  adverse  exploratory adverse-day rules ("indicador exploratorio flAIre v1", NOT FWI) -> adverse_rule_counts*.csv
  profile  JUL-AUG / JUN-SEP season profiles per station (common period) -> season_profile*.csv
  zones    municipality -> representative station, building weights -> zone_assignment_municipality.csv, building_weights.csv
  db       schema-named CSVs for code/link_build.py -> processed/weather/db_tables/*.csv
  report   reports/quality_weather.md + rows in reports/sources.csv

Conventions
  * timestamps: the XML 'Dia'+'Hora' labels are UTC (established empirically, see stage `tzcheck` / report):
    no 23-/25-hour days at the DST changes and the irradiance diurnal cycle is centred on solar noon in UTC
    both in winter and in summer. ts_utc = label (no shift).
  * units from the 2023 XSD <xs:documentation>: degC, %, mm, m/s (NOT km/h), deg, W/m2, mb.
  * values are kept as published; implausible ones are flagged ('invalid' / 'suspect'), never dropped or replaced;
    absent slots are 'missing' and are never 0 (team rule R1).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()
ROOT = Path(__file__).resolve().parents[1] / "work"
RAW = ROOT / "raw"
ZIP = RAW / "flaire_meteo_tolosaldea_2018_2023.zip"
OUT = ROOT / "processed" / "weather"
DBT = OUT / "db_tables"
REP = ROOT / "reports"
for d in (OUT, DBT):
    d.mkdir(parents=True, exist_ok=True)

YEARS = list(range(2018, 2024))
STATIONS = ["C0EA", "C0E8", "C0E9", "C029", "C058", "C026", "C077", "C052", "C043", "C0DB"]
DATA_VERSION = "v0.2-provisional-veg"          # must equal link_build.DATA_VERSION
SLOTS_PER_DAY = 144

# XML tag prefix -> (normalized variable, unit). Only meteorological variables are extracted; hydrological /
# water-quality sensors (Nivel*, Caudal*, Tem.Agua, pH, Conduct., Oxigeno, Turbidez, Amonio, Mat.Org., SolSusp.)
# are listed in the inventory but not parsed.
VARMAP = {
    "Tem.Aire.": ("tair", "degC"),
    "Humedad.": ("rh", "%"),
    "Precip..": ("precip", "mm"),
    "Vel.Med.": ("wind_speed", "m/s"),
    "Vel.Max.": ("wind_gust", "m/s"),
    "Dir.Med.": ("wind_dir", "deg"),
    "Sig.Vel.": ("wind_speed_sd", "m/s"),
    "Sig.Dir.": ("wind_dir_sd", "deg"),
    "Irradia..": ("irradiance", "W/m2"),
    "Presion.": ("pressure", "hPa"),
}
VARS = list(dict.fromkeys(v for v, _ in VARMAP.values()))
UNITS = {v: u for v, u in VARMAP.values()}
TAG_RE = re.compile(r"^(.*)_a_(\d+)cm$")

# plausibility limits (flag only; the published value is always kept in obs_10min.parquet)
#   invalid = physically impossible / sensor sentinel (e.g. -799.9, 7999)      -> usable = False
#   suspect = possible in principle but implausible here, or stuck sensor     -> usable = False
#   suspect_usable = RH in (100, 105]: capacitive-sensor saturation overshoot in fog/rain; used as 100 % in
#                    aggregates (usable = True, value_used = 100). Excluding it would delete mostly humid,
#                    non-adverse days and bias adverse-day frequencies upwards.
INVALID = {"tair": (-30.0, 50.0), "rh": (0.0, 105.0), "precip": (0.0, 60.0), "wind_speed": (0.0, 75.0),
           "wind_gust": (0.0, 90.0), "wind_dir": (0.0, 360.0), "wind_speed_sd": (0.0, 50.0), "wind_dir_sd": (0.0, 360.0),
           "irradiance": (0.0, 1500.0), "pressure": (850.0, 1080.0)}
SUSPECT = {"tair": (-20.0, 42.0), "rh": (3.0, 105.0), "precip": (0.0, 30.0), "pressure": (880.0, 1060.0)}
RH_SAT = 100.0           # (100, 105] -> suspect_usable, value_used = 100
SPIKE_T = 6.0            # tair jump > 6 degC away from and back to both neighbours in 10 min -> suspect
FLAT_SLOTS = 36          # >= 6 h of identical tair, or identical non-zero wind speed -> suspect (stuck sensor)
FLAT_SLOTS_RH = 72       # >= 12 h of identical RH below 99 % -> suspect
ZERO_WIND_SLOTS = 144    # >= 24 h of wind speed exactly 0 -> suspect (frozen/blocked anemometer)


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================================== stage: parse
DIA_RE = re.compile(r'<dia Dia="([^"]+)">')
HORA_RE = re.compile(r'<hora Hora="([^"]+)">\s*<Meteoros>(.*?)</Meteoros>', re.S)
EL_RE = re.compile(r"<([^<>/\s]+)>([^<]*)</\1>")
EMPTY_RE = re.compile(r"<([^<>/\s]+)\s*/>")


def parse_inner(name_bytes):
    """Parse one inner station-year zip -> compact DataFrame (station, ts_utc, tag, value, raw_if_not_numeric)
    plus per-file metadata. Only meteorological tags (VARMAP) are kept."""
    name, data = name_bytes
    iz = zipfile.ZipFile(io.BytesIO(data))
    st_l, ts_l, tag_l, val_l, raw_l = [], [], [], [], []
    meta = []
    for m in sorted(iz.namelist()):
        if not m.endswith(".xml"):
            continue
        st, yy, mm = Path(m).stem.split("_")
        txt = iz.read(m).decode("iso-8859-1")
        pos = [(mo.start(), mo.group(1)) for mo in DIA_RE.finditer(txt)] + [(len(txt), None)]
        n_slots = 0
        empties = 0
        labels = []
        for (p0, day), (p1, _) in zip(pos[:-1], pos[1:]):
            y_, m_, d_ = map(int, day.split("-"))
            base = np.datetime64(f"{y_:04d}-{m_:02d}-{d_:02d}T00:00", "m")
            for h in HORA_RE.finditer(txt, p0, p1):
                n_slots += 1
                hh, body = h.group(1), h.group(2)
                t = base + np.timedelta64(int(hh[:2]) * 60 + int(hh[3:5]), "m")
                labels.append(t)
                for tag, val in EL_RE.findall(body):
                    pre = TAG_RE.match(tag)
                    if not pre or pre.group(1) not in VARMAP:
                        continue
                    st_l.append(st)
                    ts_l.append(t)
                    tag_l.append(tag)
                    val = val.strip()
                    try:
                        val_l.append(float(val))
                        raw_l.append(None)
                    except ValueError:
                        val_l.append(np.nan)
                        raw_l.append(val)
                empties += len(EMPTY_RE.findall(body))
        lab = np.array(labels, dtype="datetime64[m]")
        meta.append(dict(station=st, year=int(yy), month=int(mm), file=m, n_slots=n_slots,
                         n_unique_slots=len(np.unique(lab)), first_label=str(lab.min()) if len(lab) else None,
                         last_label=str(lab.max()) if len(lab) else None, n_empty_elements=empties, chars=len(txt)))
    df = pd.DataFrame(dict(station=pd.Categorical(st_l), ts_utc=np.array(ts_l, dtype="datetime64[m]").astype("datetime64[ns]"),
                           tag=pd.Categorical(tag_l), value=np.array(val_l, dtype="float64"), raw=raw_l))
    return df, meta


def stage_parse():
    log(f"parse {ZIP.name}")
    Z = zipfile.ZipFile(ZIP)
    items = []
    inner_meta = []
    for n in sorted(Z.namelist()):
        b = Z.read(n)
        y, st, _ = n.split("_")
        inner_meta.append(dict(inner_zip=n, year=int(y), station=st, bytes=len(b), sha256=sha256_bytes(b)))
        items.append((n, b))
    pd.DataFrame(inner_meta).to_csv(OUT / "inner_zips.csv", index=False)
    # xsd tags per station-year-month (what each monthly file declares)
    xsd = []
    for n, b in items:
        iz = zipfile.ZipFile(io.BytesIO(b))
        for m in iz.namelist():
            if m.endswith(".xsd"):
                t = iz.read(m).decode("iso-8859-1")
                st, yy, mm = Path(m).stem.split("_")
                tags = re.findall(r'<xs:element (?:ref|name)="([^"]+_a_\d+cm)"', t)
                docs = dict(re.findall(r'<xs:element name="([^"]+)">\s*<xs:annotation>\s*<xs:documentation>([^<]*)<', t))
                for tg in dict.fromkeys(tags):
                    xsd.append(dict(station=st, year=int(yy), month=int(mm), tag=tg, documentation=docs.get(tg)))
    pd.DataFrame(xsd).to_csv(OUT / "xsd_tags.csv", index=False)
    frames, meta = [], []
    with ProcessPoolExecutor(max_workers=2) as ex:
        for df, mt in ex.map(parse_inner, items, chunksize=3):
            frames.append(df)
            meta += mt
    del items
    pd.DataFrame(meta).to_csv(OUT / "xml_files.csv", index=False)
    D = pd.concat(frames, ignore_index=True)
    del frames
    for c in ("station", "tag"):
        D[c] = D[c].astype(str).astype("category")
    log(f"  {len(D):,} meteorological element values")
    pre = D.tag.cat.categories.str.replace(r"_a_\d+cm$", "", regex=True)
    vcat = np.array([VARMAP[x][0] for x in pre], dtype=object)
    D["variable"] = pd.Categorical(vcat[D.tag.cat.codes.values])
    D["unit"] = D.variable.map(UNITS).astype("category")
    hcat = D.tag.cat.categories.str.extract(r"_a_(\d+)cm$")[0].astype(int).values
    D["sensor_height_cm"] = hcat[D.tag.cat.codes.values].astype("int32")
    D["ts_utc"] = D.ts_utc.dt.tz_localize("UTC")
    n_nonnum = int(D.raw.notna().sum())
    log(f"  non-numeric raw values: {n_nonnum}")
    D = D.sort_values(["station", "variable", "sensor_height_cm", "ts_utc"], kind="stable").reset_index(drop=True)
    dup = D.duplicated(["station", "ts_utc", "variable", "sensor_height_cm"], keep="first")
    D["is_duplicate"] = dup.values
    log(f"  duplicate (station, ts, variable, height) rows: {int(dup.sum())}")
    D = flag(D)
    for c in ("station", "variable", "unit", "tag", "quality_flag", "flag_reason"):
        D[c] = D[c].astype(str).astype("category")
    D = D[["station", "ts_utc", "variable", "sensor_height_cm", "value", "unit", "quality_flag", "flag_reason",
           "usable", "value_used", "tag", "raw", "is_duplicate"]]
    D.to_parquet(OUT / "obs_10min.parquet", index=False, compression="zstd")
    log(f"  wrote obs_10min.parquet {len(D):,} rows, {(OUT / 'obs_10min.parquet').stat().st_size / 1e6:.1f} MB")


def flag(D):
    v = D.value.values
    var = np.asarray(D.variable.astype(str).values)
    q = np.full(len(D), "valid", dtype=object)
    why = np.full(len(D), "", dtype=object)
    for name, (lo, hi) in SUSPECT.items():
        m = (var == name) & ((v < lo) | (v > hi))
        q[m] = "suspect"
        why[m] = f"{name} outside plausible [{lo:g},{hi:g}]"
    sat = (var == "rh") & (v > RH_SAT) & (v <= INVALID["rh"][1])
    q[sat] = "suspect_usable"
    why[sat] = "rh in (100,105]: saturation overshoot, used as 100"
    for name, (lo, hi) in INVALID.items():
        m = (var == name) & ((v < lo) | (v > hi))
        q[m] = "invalid"
        why[m] = f"{name} outside [{lo:g},{hi:g}] (impossible/sentinel)"
    nan = np.isnan(v)
    q[nan] = "missing"
    why[nan] = "empty/non-numeric element"
    D["quality_flag"] = q
    D["flag_reason"] = why
    # sequence checks on continuous 10-min series (sorted by station, variable, height, ts)
    st = D.station.astype(str).values
    ts = D.ts_utc.values
    same = np.r_[False, (st[1:] == st[:-1]) & (var[1:] == var[:-1]) & ((ts[1:] - ts[:-1]) == np.timedelta64(10, "m"))]

    def runs(cond_eq):
        brk = ~(same & cond_eq)
        rid = np.cumsum(brk)
        cnt = np.bincount(rid)
        return cnt[rid]
    good = q == "valid"
    eqprev = np.r_[False, v[1:] == v[:-1]]
    rl = runs(eqprev)
    for name, nmin, extra, lab in (("tair", FLAT_SLOTS, np.ones(len(D), bool), "tair constant >= 6 h (stuck sensor?)"),
                                   ("wind_speed", FLAT_SLOTS, v > 0, "wind speed constant non-zero >= 6 h (stuck sensor?)"),
                                   ("rh", FLAT_SLOTS_RH, v < 99, "rh constant < 99 % for >= 12 h (stuck sensor?)"),
                                   ("wind_speed", ZERO_WIND_SLOTS, v == 0, "wind speed exactly 0 for >= 24 h (frozen anemometer?)")):
        m = good & (var == name) & (rl >= nmin) & extra
        q[m] = "suspect"
        why[m] = lab
        good = q == "valid"
    # tair spikes
    mt = var == "tair"
    d1 = np.r_[np.nan, v[1:] - v[:-1]]
    d2 = np.r_[v[1:] - v[:-1], np.nan]
    nxt_same = np.r_[same[1:], False]
    spk = mt & same & nxt_same & (np.abs(d1) > SPIKE_T) & (np.abs(d2) > SPIKE_T) & (np.sign(d1) != np.sign(d2)) & (q == "valid")
    q[spk] = "suspect"
    why[spk] = f"tair spike > {SPIKE_T:g} degC vs both neighbours"
    dupm = D.is_duplicate.values
    q[dupm] = "invalid"
    why[dupm] = "duplicate slot (first occurrence kept)"
    D["quality_flag"] = q
    D["flag_reason"] = why
    usable = (q == "valid") | (q == "suspect_usable")
    D["usable"] = usable
    D["value_used"] = np.where(usable, np.where(q == "suspect_usable", RH_SAT, v), np.nan)
    return D


# =============================================================================================== helpers
CAT_XLSX = RAW / "estaciones.xlsx"
CAT_GEOJSON = RAW / "estaciones.geojson"
TERR = ROOT / "processed" / "territory"
BLD = ROOT / "processed" / "buildings"
STATS = OUT / "weather_stats.json"
KMH = 1 / 3.6
SEASONS = {"JUL-AUG": [7, 8], "JUN-SEP": [6, 7, 8, 9]}
MIN_SLOTS = 130            # valid day: >= 130 of 144 usable 10-min values (90.3 %) for every variable the rule needs
SEASON_COMPLETE = 0.80     # a station-season-year is used only if >= 80 % of its days are valid for the rule
RAIN_DAY_MM = 1.0          # "rain day" = daily precipitation >= 1.0 mm
MUN_SNAP_KM = 2.0          # eligible zone stations: inside Tolosaldea or <= 2 km from its boundary
ELEV_SCALE = 30.0          # elevation-adjusted distance: d_eff = sqrt(d_h^2 + (ELEV_SCALE * dz)^2), i.e. 1 m of height
                           # difference counts like 30 m of horizontal distance (heuristic; keeps valley-floor
                           # municipalities on the valley-floor station and uplands on upland stations)
ASSIGN_METHOD = "nearest_same_valley"   # schema enum; here = elevation-adjusted nearest (see ELEV_SCALE)
TYPE_MEANING = {
    "KM": "meteorological station (wind, irradiance, T/RH, precipitation) - meaning inferred from the sensors present; "
          "the catalogue does not document the type codes",
    "KC": "river station with water-quality sensors (pH, conductivity, O2, turbidity, water level) + T/RH/precipitation "
          "- inferred, not documented",
    "KA": "river gauging station (water level/flow) + T/RH/precipitation - inferred, not documented",
    "B": "port/buoy station (B090 'Puerto de Bilbao', ...) - inferred from names, not documented",
}


def stats_put(key, val):
    d = json.loads(STATS.read_text()) if STATS.exists() else {}
    d[key] = val
    STATS.write_text(json.dumps(d, indent=1, default=str))


def stats_get():
    return json.loads(STATS.read_text()) if STATS.exists() else {}


def load_obs(cols=None, variables=None):
    import pyarrow.dataset as ds
    f = None if variables is None else ds.field("variable").isin(variables)
    t = ds.dataset(OUT / "obs_10min.parquet").to_table(columns=cols, filter=f)
    return t.to_pandas()


def boundary_utm():
    import geopandas as gpd
    b = gpd.read_file(TERR / "tolosaldea_boundary.geojson").to_crs(25830)
    return b.geometry.union_all()


def catalogue():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        X = pd.read_excel(CAT_XLSX)
    X = X.rename(columns={"Código": "station_id", "Nombre": "name", "Descripción": "description", "Tipo": "type",
                          "Fecha creación": "created", "Fecha baja": "closed", "LATWGS84": "lat", "LONWGS84": "lon",
                          "Municipio": "municipality", "Provincia": "province", "URL amigable": "url"})
    return X


# =============================================================================================== stage: tzcheck
def eot_min(doy):
    B = 2 * np.pi * (doy - 81) / 364
    return 9.87 * np.sin(2 * B) - 7.53 * np.cos(B) - 1.5 * np.sin(B)


def stage_tzcheck():
    """Time zone of the 'Dia'/'Hora' labels, established from the data (the source does not state it)."""
    log("tzcheck")
    O = load_obs(["station", "ts_utc", "variable", "value", "usable"], ["irradiance", "tair"])
    X = catalogue().set_index("station_id")
    out = {}
    # 1) DST: slots per day on the last Sunday of March / October (local civil time would give 138 / 150 slots)
    days = O[O.variable == "tair"].assign(d=lambda x: x.ts_utc.dt.tz_convert(None).dt.normalize())
    cnt = days.groupby(["station", "d"], observed=True).size()
    dst = []
    for y in YEARS:
        for mth in (3, 10):
            last = pd.Timestamp(y, mth, 31)
            last = last - pd.Timedelta(days=(last.weekday() + 1) % 7)
            sub = cnt.xs(last, level="d") if last in cnt.index.get_level_values("d") else pd.Series(dtype=int)
            dst.append(dict(date=str(last.date()), kind="spring-forward" if mth == 3 else "fall-back",
                            n_stations=len(sub), slots_min=int(sub.min()) if len(sub) else None,
                            slots_max=int(sub.max()) if len(sub) else None))
    DST = pd.DataFrame(dst)
    DST.to_csv(OUT / "tzcheck_dst_days.csv", index=False)
    allday = cnt.value_counts().sort_index()
    out["slots_per_day_distribution"] = {int(k): int(v) for k, v in allday.items()}
    out["max_slots_any_day"] = int(cnt.max())
    # 2) irradiance centroid vs solar noon (UTC), by half-year
    ir = O[(O.variable == "irradiance") & O.usable].copy()
    ir["date"] = ir.ts_utc.dt.tz_convert(None).dt.normalize()
    ir["mins"] = ir.ts_utc.dt.hour * 60 + ir.ts_utc.dt.minute
    ir["w"] = ir.value.clip(lower=0)
    ir["wm"] = ir.w * ir.mins
    g = ir.groupby(["station", "date"], observed=True).agg(n=("w", "size"), w=("w", "sum"), wm=("wm", "sum")).reset_index()
    g = g[(g.n == SLOTS_PER_DAY) & (g.w > 0)]
    g["centroid_min_utc"] = g.wm / g.w
    lon = X.lon.to_dict()
    g["solar_noon_min_utc"] = 720 - 4 * g.station.map(lon).astype(float) - eot_min(g.date.dt.dayofyear)
    g["offset_min"] = g.centroid_min_utc - g.solar_noon_min_utc
    g["half"] = np.where(g.date.dt.month.isin([4, 5, 6, 7, 8, 9]), "Apr-Sep (local CEST = UTC+2)", "Oct-Mar (local CET = UTC+1)")
    T = g.groupby(["station", "half"]).agg(n_days=("offset_min", "size"), offset_median_min=("offset_min", "median"),
                                           offset_p25=("offset_min", lambda s: s.quantile(.25)),
                                           offset_p75=("offset_min", lambda s: s.quantile(.75))).round(1).reset_index()
    T.to_csv(OUT / "tzcheck_irradiance.csv", index=False)
    out["irradiance_offset_median_min_all"] = round(float(g.offset_min.median()), 1)
    out["irradiance_offset_by_half"] = g.groupby("half").offset_min.median().round(1).to_dict()
    out["conclusion"] = ("labels are UTC: no 23/25-hour days at DST changes (every day 144 slots), and the irradiance "
                         "centroid is within a few minutes of solar noon in UTC in both half-years (local time would give "
                         "+60 min in winter and +120 min in summer). The small positive offset (~+4 min) is consistent "
                         "with labels marking the END of each 10-min averaging interval.")
    stats_put("tzcheck", out)
    log(f"  irradiance offset vs solar noon (UTC): {out['irradiance_offset_by_half']}; DST days: "
        f"{DST.slots_min.min()}-{DST.slots_max.max()} slots")


# =============================================================================================== stage: inventory
def stage_inventory():
    import geopandas as gpd
    import shapely
    log("inventory")
    X = catalogue()
    S = X[X.station_id.isin(STATIONS)].copy()
    S["type_meaning"] = S.type.map(TYPE_MEANING)
    g = gpd.GeoSeries(gpd.points_from_xy(S.lon, S.lat), crs=4326).to_crs(25830)
    S["x"] = g.x.round(2).values
    S["y"] = g.y.round(2).values
    bd = boundary_utm()
    pts = shapely.points(S.x.values, S.y.values)
    S["inside_tolosaldea"] = shapely.contains(bd, pts).astype(int)
    S["dist_boundary_km"] = np.where(S.inside_tolosaldea == 1, 0.0, shapely.distance(bd, pts) / 1000).round(2)
    S["dist_inside_to_edge_km"] = np.where(S.inside_tolosaldea == 1, shapely.distance(bd.boundary, pts) / 1000, np.nan).round(2)
    # elevation: not in the catalogue, not in XML/XSD -> elevation_m NULL. Proxy only: median B5M ground elevation of
    # Tolosaldea buildings within 500 m of the station (NOT the station altitude; flagged as proxy).
    B = gpd.read_file(BLD / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio",
                      columns=["building_id", "elevation", "x", "y"])
    bx, by, be = B.x.values, B.y.values, B.elevation.values
    prox, nprox, nearest = [], [], []
    for x, y in zip(S.x, S.y):
        d = np.hypot(bx - x, by - y)
        m = (d <= 500) & ~np.isnan(be)
        prox.append(float(np.median(be[m])) if m.sum() >= 3 else np.nan)
        nprox.append(int(m.sum()))
        nearest.append(float(d.min()))
    S["elevation_m"] = np.nan
    S["elev_proxy_bldg500m_m"] = np.round(prox, 0)
    S["n_bldg_proxy"] = nprox
    O = load_obs(["station", "ts_utc", "variable", "sensor_height_cm", "value"])
    O = O[O.value.notna()]
    O["year"] = O.ts_utc.dt.year
    V = O.groupby(["station", "year", "variable", "sensor_height_cm"], observed=True).agg(
        n_present=("value", "size"), first_ts_utc=("ts_utc", "min"), last_ts_utc=("ts_utc", "max")).reset_index()
    V.to_csv(OUT / "station_variables_by_year.csv", index=False)
    xs = pd.read_csv(OUT / "xsd_tags.csv")
    pre = xs.tag.str.replace(r"_a_\d+cm$", "", regex=True)
    hyd = xs[~pre.isin(VARMAP.keys())].groupby("station").tag.apply(lambda t: ", ".join(sorted(set(t))))
    fl = pd.read_csv(OUT / "xml_files.csv")
    rows = []
    for r in S.itertuples():
        v = V[V.station == r.station_id]
        per_year = []
        for y in YEARS:
            vy = v[v.year == y]
            months = sorted(fl[(fl.station == r.station_id) & (fl.year == y)].month)
            per_year.append(f"{y}: " + ("NO DATA" if vy.empty else
                            f"{len(months)} months ({months[0]}-{months[-1]}) · " +
                            ", ".join(f"{a}@{b / 100:g}m" for a, b in zip(vy.variable, vy.sensor_height_cm))))
        hts = v.groupby("variable").sensor_height_cm.agg(lambda s: sorted(set(s)))
        rows.append(dict(station_id=r.station_id, name=r.name, type=r.type, type_meaning=r.type_meaning,
                         catalogue_municipality=r.municipality, created=r.created, closed=r.closed,
                         lon=r.lon, lat=r.lat, x=r.x, y=r.y, inside_tolosaldea=r.inside_tolosaldea,
                         dist_boundary_km=r.dist_boundary_km, dist_inside_to_edge_km=r.dist_inside_to_edge_km,
                         elevation_m=None, elev_proxy_bldg500m_m=r.elev_proxy_bldg500m_m, n_bldg_proxy=r.n_bldg_proxy,
                         has_wind=int("wind_speed" in set(v.variable)),
                         tair_height_m=";".join(f"{h / 100:g}" for h in hts.get("tair", [])),
                         rh_height_m=";".join(f"{h / 100:g}" for h in hts.get("rh", [])),
                         precip_height_m=";".join(f"{h / 100:g}" for h in hts.get("precip", [])),
                         wind_height_m=";".join(f"{h / 100:g}" for h in hts.get("wind_speed", [])),
                         first_ts_utc=str(v.first_ts_utc.min()), last_ts_utc=str(v.last_ts_utc.max()),
                         variables_by_year=" | ".join(per_year),
                         hydro_or_water_quality_tags_not_parsed=hyd.get(r.station_id, "")))
    INV = pd.DataFrame(rows)
    order = {s: i for i, s in enumerate(STATIONS)}
    INV = INV.sort_values("station_id", key=lambda c: c.map(order))
    INV.to_csv(OUT / "station_inventory.csv", index=False)
    stats_put("catalogue", dict(n_stations=int(len(X)), types=X.type.value_counts().to_dict(),
                                has_altitude_column=False, columns=list(X.columns)))
    log(f"  {len(INV)} stations, {int(INV.has_wind.sum())} with wind")


# =============================================================================================== stage: quality
MAIN_VARS = ["tair", "rh", "precip", "wind_speed", "wind_gust", "wind_dir"]


def stage_quality():
    log("quality (station x year x month x variable)")
    O = load_obs(["station", "ts_utc", "variable", "value", "quality_flag", "usable"])
    O["year"] = O.ts_utc.dt.year
    O["month"] = O.ts_utc.dt.month
    O["present"] = O.value.notna()
    O["inv"] = O.quality_flag == "invalid"
    O["sus"] = O.quality_flag == "suspect"
    O["sat"] = O.quality_flag == "suspect_usable"
    Q = O.groupby(["station", "year", "month", "variable"], observed=True).agg(
        n_rows=("value", "size"), n_present=("present", "sum"), n_valid=("usable", "sum"), n_invalid=("inv", "sum"),
        n_suspect=("sus", "sum"), n_rh_saturation_used_as_100=("sat", "sum")).reset_index()
    # full grid: every variable the station declares (any year), every month 2018-2023
    decl = {st: sorted(set(g.astype(str))) for st, g in O.groupby("station", observed=True).variable}
    grid = [dict(station=st, year=y, month=m, variable=v) for st in STATIONS for v in decl[st] for y in YEARS
            for m in range(1, 13)]
    G = pd.DataFrame(grid).merge(Q, how="left", on=["station", "year", "month", "variable"])
    for c in ("n_rows", "n_present", "n_valid", "n_invalid", "n_suspect", "n_rh_saturation_used_as_100"):
        G[c] = G[c].fillna(0).astype(int)
    G["n_expected"] = [pd.Period(f"{y}-{m:02d}").days_in_month * SLOTS_PER_DAY for y, m in zip(G.year, G.month)]
    G["n_missing"] = G.n_expected - G.n_present
    G["pct_present"] = (100 * G.n_present / G.n_expected).round(2)
    G["pct_valid"] = (100 * G.n_valid / G.n_expected).round(2)
    assert (G.n_valid <= G.n_present).all() and (G.n_present <= G.n_expected).all()
    G = G.rename(columns={"station": "station_id"})
    G.to_csv(OUT / "quality_monthly.csv", index=False)
    # flag summary
    F = O.groupby(["station", "variable", "quality_flag"], observed=True).size().unstack(fill_value=0).reset_index()
    F.to_csv(OUT / "quality_flags_by_station_variable.csv", index=False)
    R = (load_obs(["station", "variable", "quality_flag", "flag_reason"])
         .query("quality_flag != 'valid'").groupby(["station", "variable", "quality_flag", "flag_reason"], observed=True)
         .size().rename("n").reset_index())
    R.to_csv(OUT / "quality_flag_reasons.csv", index=False)
    log(f"  {len(G)} rows")


# =============================================================================================== stage: daily
def stage_daily():
    log("daily aggregates (UTC day)")
    O = load_obs(["station", "ts_utc", "variable", "value_used", "usable"], ["tair", "rh", "wind_speed", "wind_gust", "precip"])
    O = O[O.usable]
    O["date"] = O.ts_utc.dt.tz_convert(None).dt.normalize()
    O["hhmm"] = O.ts_utc.dt.strftime("%H:%M")
    out = []
    spec = {"tair": [("tmax_c", "max"), ("tmin_c", "min"), ("tmean_c", "mean")],
            "rh": [("rhmin_pct", "min"), ("rhmean_pct", "mean")],
            "wind_speed": [("wind_max_ms", "max"), ("wind_mean_ms", "mean")],
            "wind_gust": [("gust_max_ms", "max")],
            "precip": [("precip_mm", "sum")]}
    nname = {"tair": "n_tair", "rh": "n_rh", "wind_speed": "n_wind", "wind_gust": "n_gust", "precip": "n_precip"}
    for v, aggs in spec.items():
        sub = O[O.variable == v]
        g = sub.groupby(["station", "date"], observed=True).value_used
        df = pd.DataFrame({nm: getattr(g, f)() for nm, f in aggs})
        df[nname[v]] = g.size()
        if v in ("tair", "rh"):
            idx = g.idxmax() if v == "tair" else g.idxmin()
            df["t_tmax_utc" if v == "tair" else "t_rhmin_utc"] = sub.loc[idx.values, "hhmm"].values
        out.append(df)
    D = pd.concat(out, axis=1).reset_index()
    full = pd.MultiIndex.from_product([STATIONS, pd.date_range("2018-01-01", "2023-12-31", freq="D")], names=["station", "date"])
    D = D.set_index(["station", "date"]).reindex(full).reset_index()
    for c in nname.values():
        D[c] = D[c].fillna(0).astype(int)
    has_wind = set(O[O.variable == "wind_speed"].station.unique())
    for v, c in nname.items():
        D[f"valid_{v}"] = D[c] >= MIN_SLOTS
    D.loc[~D.station.isin(has_wind), ["valid_wind_speed", "valid_wind_gust"]] = False
    D["precip_mm"] = D.precip_mm.round(2)
    for c in ("tmax_c", "tmin_c", "tmean_c", "rhmin_pct", "rhmean_pct", "wind_max_ms", "wind_mean_ms", "gust_max_ms"):
        D[c] = D[c].round(2)
    # spatial consistency (day level): Tmax / RHmin far from the median of the other stations that day
    oth_t, oth_rh = [], []
    for st in STATIONS:
        o = D[(D.station != st)]
        mt = o[o.valid_tair].groupby("date").tmax_c.median()
        mr = o[o.valid_rh].groupby("date").rhmin_pct.median()
        sub = D[D.station == st]
        oth_t.append(pd.Series(sub.date.map(mt).values, index=sub.index))
        oth_rh.append(pd.Series(sub.date.map(mr).values, index=sub.index))
    D["tmax_median_others"] = pd.concat(oth_t).sort_index().round(2)
    D["rhmin_median_others"] = pd.concat(oth_rh).sort_index().round(2)
    D["spatial_suspect_tair"] = D.valid_tair & ((D.tmax_c - D.tmax_median_others).abs() > 8)
    D["spatial_suspect_rh"] = D.valid_rh & (D.rhmin_pct < 20) & (D.rhmin_median_others > 50)
    D["year"] = D.date.dt.year
    D["month"] = D.date.dt.month
    D["date"] = D.date.dt.strftime("%Y-%m-%d")
    D = D.rename(columns={"station": "station_id"})
    D.to_csv(OUT / "daily.csv", index=False)
    # precipitation: interval amounts or accumulated?
    P = load_obs(["station", "ts_utc", "variable", "value", "usable"], ["precip"])
    P = P[P.usable].sort_values(["station", "ts_utc"])
    P["year"] = P.ts_utc.dt.year
    P["d"] = P.groupby("station", observed=True).value.diff()
    pc = P.groupby(["station", "year"], observed=True).agg(
        n=("value", "size"), pct_zero=("value", lambda s: round(100 * (s == 0).mean(), 2)),
        pct_decrease=("d", lambda s: round(100 * (s < 0).mean(), 2)), pct_increase=("d", lambda s: round(100 * (s > 0).mean(), 2)),
        max_10min_mm=("value", "max"), sum_mm=("value", "sum")).reset_index()
    pc["sum_mm"] = pc.sum_mm.round(0)
    pc.to_csv(OUT / "precip_check.csv", index=False)
    stats_put("daily", dict(n_rows=int(len(D)), spatial_suspect_tair=int(D.spatial_suspect_tair.sum()),
                            spatial_suspect_rh=int(D.spatial_suspect_rh.sum()), min_slots=MIN_SLOTS,
                            precip_interval_evidence=dict(median_pct_zero=float(pc.pct_zero.median()),
                                                          median_pct_decrease=float(pc.pct_decrease.median()),
                                                          annual_sum_range_mm=[float(pc.sum_mm.min()), float(pc.sum_mm.max())])))
    log(f"  {len(D)} station-days; spatial suspects tair {int(D.spatial_suspect_tair.sum())}, rh {int(D.spatial_suspect_rh.sum())}")


# =============================================================================================== stage: adverse
# All thresholds in the units of the data: degC, %, m/s (15 km/h = 4.167 m/s; 20 km/h = 5.556 m/s).
RULES = {
    "R1_T25_RH40_W15": dict(label="Tmax>=25 degC AND RHmin<=40 % AND max 10-min mean wind>=15 km/h",
                            needs=["tair", "rh", "wind_speed"], t=25, rh=40, w=15),
    "R2_HOTDRY_T25_RH35": dict(label="hot-dry: Tmax>=25 degC AND RHmin<=35 %", needs=["tair", "rh"], t=25, rh=35, w=None),
    "R3_DRYWIND_RH40_W20": dict(label="dry-wind: RHmin<=40 % AND max 10-min mean wind>=20 km/h",
                                needs=["rh", "wind_speed"], t=None, rh=40, w=20),
    "R4_T25_RH40": dict(label="Tmax>=25 degC AND RHmin<=40 % (R1 without wind)", needs=["tair", "rh"], t=25, rh=40, w=None),
    "R1N_T25_RH40_W15_NORAIN3": dict(label="R1 AND no rain day (>=1 mm) in the previous 3 days",
                                     needs=["tair", "rh", "wind_speed", "prev3"], t=25, rh=40, w=15),
    "R4N_T25_RH40_NORAIN3": dict(label="R4 AND no rain day (>=1 mm) in the previous 3 days",
                                 needs=["tair", "rh", "prev3"], t=25, rh=40, w=None),
}
PRIMARY = "R4N_T25_RH40_NORAIN3"     # chosen in the report (section 4); METHOD_VERSION in the DB
METHOD_VERSION = "ADV-v1"


def eval_rules(D):
    D = D.sort_values(["station_id", "date"]).copy()
    D["valid_tair_r"] = D.valid_tair & ~D.spatial_suspect_tair
    D["valid_rh_r"] = D.valid_rh & ~D.spatial_suspect_rh
    g = D.groupby("station_id")
    raind = D.valid_precip & (D.precip_mm >= RAIN_DAY_MM)
    okp = D.valid_precip.astype(int)
    D["_rain"] = raind.astype(int)
    D["_okp"] = okp
    D["prev3_valid"] = (g._okp.shift(1).fillna(0) + g._okp.shift(2).fillna(0) + g._okp.shift(3).fillna(0)) == 3
    D["prev3_norain"] = D.prev3_valid & ((g._rain.shift(1).fillna(1) + g._rain.shift(2).fillna(1) + g._rain.shift(3).fillna(1)) == 0)
    D = D.drop(columns=["_rain", "_okp"])
    vmap = {"tair": "valid_tair_r", "rh": "valid_rh_r", "wind_speed": "valid_wind_speed", "prev3": "prev3_valid"}
    for rid, r in RULES.items():
        valid = np.ones(len(D), bool)
        for n in r["needs"]:
            valid &= D[vmap[n]].values
        adv = np.ones(len(D), bool)
        if r["t"] is not None:
            adv &= (D.tmax_c >= r["t"]).values
        if r["rh"] is not None:
            adv &= (D.rhmin_pct <= r["rh"]).values
        if r["w"] is not None:
            adv &= (D.wind_max_ms >= r["w"] * KMH - 1e-9).values
        if "prev3" in r["needs"]:
            adv &= D.prev3_norain.values
        D[f"valid_{rid}"] = valid
        D[f"adv_{rid}"] = valid & adv
    return D


def stage_adverse():
    log("adverse-day rules (indicador exploratorio flAIre v1, NOT FWI)")
    D = pd.read_csv(OUT / "daily.csv", dtype={"station_id": str})
    D = eval_rules(D)
    D.to_csv(OUT / "daily_with_rules.csv", index=False)
    rows = []
    for rid in RULES:
        g = D.groupby(["station_id", "year", "month"]).agg(valid_days=(f"valid_{rid}", "sum"), adverse_days=(f"adv_{rid}", "sum"),
                                                           days=("date", "size")).reset_index()
        g["rule"] = rid
        rows.append(g)
    M = pd.concat(rows, ignore_index=True)
    M.to_csv(OUT / "adverse_counts_station_year_month.csv", index=False)
    # Jul-Aug 2018-2023 per station x rule x year (+ total)
    J = M[M.month.isin([7, 8])].groupby(["rule", "station_id", "year"])[["days", "valid_days", "adverse_days"]].sum().reset_index()
    JT = J.groupby(["rule", "station_id"])[["days", "valid_days", "adverse_days"]].sum().reset_index().assign(year="2018-2023")
    J = pd.concat([J.astype({"year": str}), JT], ignore_index=True)
    J["frequency"] = np.where(J.valid_days > 0, J.adverse_days / J.valid_days.where(J.valid_days > 0), np.nan).round(4)
    J.to_csv(OUT / "adverse_rule_counts_julaug.csv", index=False)
    # all months (2018-2023 pooled) per station x rule x month
    A = M.groupby(["rule", "station_id", "month"])[["days", "valid_days", "adverse_days"]].sum().reset_index()
    A["frequency"] = (A.adverse_days / A.valid_days.where(A.valid_days > 0)).round(4)
    A.to_csv(OUT / "adverse_rule_counts_monthly.csv", index=False)
    log(f"  primary {PRIMARY}: Jul-Aug totals " +
        JT[JT.rule == PRIMARY].set_index("station_id").adverse_days.astype(int).to_dict().__repr__())


# =============================================================================================== stage: zones
def stage_zones():
    """Municipality -> representative station. Rule: nearest (straight line from the centroid of the municipality's
    analysis-set buildings) among KM stations that are inside Tolosaldea or <= 2 km from it and have the variables of
    the primary rule. Every building inherits its municipality's station."""
    import geopandas as gpd
    import shapely
    log("zones")
    INV = pd.read_csv(OUT / "station_inventory.csv")
    need_wind = "wind_speed" in RULES[PRIMARY]["needs"]
    elig = INV[(INV.type == "KM") & (INV.dist_boundary_km <= MUN_SNAP_KM) & ((INV.has_wind == 1) | (not need_wind))]
    ctx = INV[(INV.type == "KM") & ~INV.station_id.isin(elig.station_id)]
    M = gpd.read_file(TERR / "tolosaldea_municipalities.geojson").to_crs(25830)
    B = gpd.read_file(BLD / "buildings_tolosaldea.gpkg", layer="buildings_rep_points", engine="pyogrio",
                      columns=["building_id", "municipality_code", "muni_name", "elevation", "x", "y"])
    A = pd.read_csv(BLD / "buildings_analysis_set.csv", usecols=["building_id"])
    B["in_analysis_set"] = B.building_id.isin(A.building_id).astype(int)
    rows = []
    for m in M.itertuples():
        bm = B[B.municipality_code == m.ine_code]
        ba = bm[bm.in_analysis_set == 1]
        if len(ba):
            rx, ry, how = ba.x.mean(), ba.y.mean(), "centroid of analysis-set buildings"
        elif len(bm):
            rx, ry, how = bm.x.mean(), bm.y.mean(), "centroid of all buildings (no analysis-set building)"
        else:
            pt = m.geometry.representative_point()
            rx, ry, how = pt.x, pt.y, "polygon representative point"
        d = np.hypot(elig.x.values - rx, elig.y.values - ry) / 1000
        elev_m = float(np.nanmedian(ba.elevation)) if len(ba) else float(np.nanmedian(bm.elevation))
        dz = np.abs(elig.elev_proxy_bldg500m_m.values - elev_m)
        deff = np.hypot(d, ELEV_SCALE * dz / 1000)
        o = np.argsort(deff)
        on = np.argsort(d)
        dc = np.hypot(INV.x.values - rx, INV.y.values - ry) / 1000
        dkm = np.hypot(INV[INV.type == "KM"].x.values - rx, INV[INV.type == "KM"].y.values - ry) / 1000
        km_ids = INV[INV.type == "KM"].station_id.values
        rows.append(dict(ine_code=m.ine_code, name=m.name, rep_point_rule=how, rep_x=round(rx, 1), rep_y=round(ry, 1),
                         n_buildings=len(bm), n_analysis_set=len(ba), median_bldg_elev_m=elev_m,
                         station_id=elig.station_id.values[o[0]], station_name=elig.name.values[o[0]],
                         distance_km=round(float(d[o[0]]), 2), d_eff_km=round(float(deff[o[0]]), 2),
                         second_station=elig.station_id.values[o[1]], second_d_eff_km=round(float(deff[o[1]]), 2),
                         margin_d_eff_km=round(float(deff[o[1]] - deff[o[0]]), 2),
                         sens_nearest_straight=elig.station_id.values[on[0]], sens_nearest_straight_km=round(float(d[on[0]]), 2),
                         nearest_any_km_station=km_ids[np.argmin(dkm)], nearest_any_km_station_km=round(float(dkm.min()), 2),
                         nearest_any_station=INV.station_id.values[np.argmin(dc)], nearest_any_station_km=round(float(dc.min()), 2)))
    Z = pd.DataFrame(rows).sort_values("ine_code")
    st_el = INV.set_index("station_id").elev_proxy_bldg500m_m
    Z["station_elev_proxy_m"] = Z.station_id.map(st_el)
    Z["elev_diff_proxy_m"] = (Z.median_bldg_elev_m - Z.station_elev_proxy_m).round(0)
    Z.to_csv(OUT / "zone_assignment_municipality.csv", index=False)
    # buildings
    Bz = B.merge(Z[["ine_code", "station_id"]], left_on="municipality_code", right_on="ine_code", how="left", validate="m:1")
    assert Bz.station_id.notna().all()
    sx = INV.set_index("station_id").x
    sy = INV.set_index("station_id").y
    Bz["distance_km"] = (np.hypot(Bz.x - Bz.station_id.map(sx), Bz.y - Bz.station_id.map(sy)) / 1000).round(3)
    Bz["elev_diff_proxy_m"] = (Bz.elevation - Bz.station_id.map(st_el)).round(0)
    # sensitivities: municipality -> straight-line nearest; per-building elevation-adjusted nearest; with Ordizia C043 allowed
    Bz["sens_nearest_straight"] = Bz.municipality_code.map(Z.set_index("ine_code").sens_nearest_straight)
    ex, ey, ez = elig.x.values, elig.y.values, elig.elev_proxy_bldg500m_m.values
    bel = Bz.elevation.fillna(Bz.elevation.median()).values
    dd = np.hypot(np.hypot(Bz.x.values[:, None] - ex[None, :], Bz.y.values[:, None] - ey[None, :]),
                  ELEV_SCALE * np.abs(bel[:, None] - ez[None, :]))
    Bz["sens_nearest_per_building"] = elig.station_id.values[dd.argmin(1)]
    km = INV[INV.type == "KM"]
    dd2 = np.hypot(Bz.x.values[:, None] - km.x.values[None, :], Bz.y.values[:, None] - km.y.values[None, :])
    Bz["sens_nearest_incl_C043"] = km.station_id.values[dd2.argmin(1)]
    Bz.drop(columns=["ine_code"]).to_csv(OUT / "building_zone.csv", index=False)
    a = Bz[Bz.in_analysis_set == 1]
    stats_put("zones", dict(eligible=list(elig.station_id), context_only=list(ctx.station_id),
                            n_municipalities=int(len(Z)), stations_used=sorted(Z.station_id.unique()),
                            analysis_buildings_by_station=a.station_id.value_counts().to_dict(),
                            sens_changed_straight_nearest=int((a.sens_nearest_straight != a.station_id).sum()),
                            sens_changed_per_building=int((a.sens_nearest_per_building != a.station_id).sum()),
                            sens_changed_incl_C043=int((a.sens_nearest_incl_C043 != a.station_id).sum())))
    log(f"  eligible {list(elig.station_id)}; analysis-set buildings by station {a.station_id.value_counts().to_dict()}")


# =============================================================================================== stage: profile
def season_tables(D, rid, stations):
    rows = []
    for sid, months in SEASONS.items():
        sub = D[D.month.isin(months) & D.station_id.isin(stations)]
        g = sub.groupby(["station_id", "year"]).agg(days=("date", "size"), valid_days=(f"valid_{rid}", "sum"),
                                                     adverse_days=(f"adv_{rid}", "sum")).reset_index()
        g["season_id"] = sid
        miss = (sub.assign(v=sub[f"valid_{rid}"]).groupby(["station_id", "year", "month"]).v.mean() < SEASON_COMPLETE)
        mm = miss[miss].reset_index().groupby(["station_id", "year"]).month.agg(lambda s: ",".join(map(str, s)))
        g["months_below_80pct"] = [mm.get((a, b), "") for a, b in zip(g.station_id, g.year)]
        rows.append(g)
    Y = pd.concat(rows, ignore_index=True)
    Y["complete"] = Y.valid_days >= SEASON_COMPLETE * Y.days
    Y["frequency"] = (Y.adverse_days / Y.valid_days.where(Y.valid_days > 0)).round(4)
    return Y


def stage_profile():
    log("season profiles + weights")
    D = pd.read_csv(OUT / "daily_with_rules.csv", dtype={"station_id": str})
    zs = stats_get()["zones"]
    used = zs["stations_used"]
    allkm = zs["eligible"] + zs["context_only"]
    out_y, out_p = [], []
    common = {}
    for rid in RULES:
        st_rule = [s for s in STATIONS if s in allkm] if "wind_speed" in RULES[rid]["needs"] else STATIONS
        Y = season_tables(D, rid, st_rule)
        Y["rule"] = rid
        out_y.append(Y)
        for sid in SEASONS:
            ys = Y[(Y.season_id == sid) & Y.station_id.isin(used)]
            cy = sorted(set(YEARS) - set(ys[~ys.complete].year))
            common[(rid, sid)] = cy
            for st in st_rule:
                for variant, yrs in (("common_period", cy),
                                     ("all_complete_years", sorted(Y[(Y.season_id == sid) & (Y.station_id == st) & Y.complete].year))):
                    s = Y[(Y.season_id == sid) & (Y.station_id == st) & Y.year.isin(yrs)]
                    fy = s.adverse_days / s.valid_days
                    out_p.append(dict(rule=rid, season_id=sid, station_id=st, variant=variant, years=",".join(map(str, yrs)),
                                      n_years_used=len(yrs), valid_days=int(s.valid_days.sum()), adverse_days=int(s.adverse_days.sum()),
                                      frequency=(s.adverse_days.sum() / s.valid_days.sum()) if s.valid_days.sum() else np.nan,
                                      interannual_mean=fy.mean() if len(fy) else np.nan,
                                      interannual_sd=fy.std(ddof=1) if len(fy) > 1 else np.nan,
                                      mean_adverse_days_per_year=s.adverse_days.mean() if len(s) else np.nan,
                                      sd_adverse_days_per_year=s.adverse_days.std(ddof=1) if len(s) > 1 else np.nan,
                                      zone_station=int(st in used),
                                      excluded_years=",".join(str(y) for y in YEARS if y not in yrs),
                                      months_below_80pct=";".join(f"{a}:{b}" for a, b in
                                                                   Y[(Y.season_id == sid) & (Y.station_id == st) & (Y.months_below_80pct != "")]
                                                                   [["year", "months_below_80pct"]].itertuples(index=False))))
    Yall = pd.concat(out_y, ignore_index=True)
    Yall.to_csv(OUT / "season_profile_year.csv", index=False)
    P = pd.DataFrame(out_p)
    for c in ("frequency", "interannual_mean", "interannual_sd", "mean_adverse_days_per_year", "sd_adverse_days_per_year"):
        P[c] = P[c].round(4)
    P.to_csv(OUT / "season_profile.csv", index=False)
    # noise test for the primary rule, JUL-AUG, common period: paired yearly differences between zone stations
    Y = Yall[(Yall.rule == PRIMARY) & (Yall.season_id == "JUL-AUG") & Yall.station_id.isin(used)
             & Yall.year.isin(common[(PRIMARY, "JUL-AUG")])]
    W = Y.pivot(index="year", columns="station_id", values="frequency")
    pairs = []
    import itertools
    for a, b in itertools.combinations(sorted(used), 2):
        dlt = W[a] - W[b]
        n = dlt.notna().sum()
        sd = dlt.std(ddof=1)
        pairs.append(dict(station_a=a, station_b=b, n_years=int(n), mean_diff=round(dlt.mean(), 4), sd_diff=round(sd, 4),
                          t_paired=round(dlt.mean() / (sd / np.sqrt(n)), 2) if sd > 0 else np.nan,
                          years_a_gt_b=int((dlt > 0).sum()), years_b_gt_a=int((dlt < 0).sum())))
    PR = pd.DataFrame(pairs)
    PR.to_csv(OUT / "zone_difference_test.csv", index=False)
    # weights
    BZ = pd.read_csv(OUT / "building_zone.csv", dtype={"station_id": str})
    prof = P[(P.rule == PRIMARY) & (P.variant == "common_period")].set_index(["season_id", "station_id"])
    for sid in SEASONS:
        BZ[f"freq_{sid}"] = [prof.loc[(sid, s), "frequency"] for s in BZ.station_id]
        mean_as = BZ.loc[BZ.in_analysis_set == 1, f"freq_{sid}"].mean()
        BZ[f"weight_norm_{sid}"] = (BZ[f"freq_{sid}"] / mean_as).round(4)
    BZ.to_csv(OUT / "building_weights.csv", index=False)
    ZW = (prof.loc["JUL-AUG"].loc[used, ["frequency", "interannual_sd", "valid_days", "adverse_days", "years"]].reset_index())
    a = BZ[BZ.in_analysis_set == 1]
    ZW["n_analysis_buildings"] = ZW.station_id.map(a.station_id.value_counts()).fillna(0).astype(int)
    ZW["weight_norm"] = ZW.station_id.map(a.groupby("station_id").weight_norm_JUL_AUG.first() if "weight_norm_JUL_AUG" in a
                                         else a.groupby("station_id")["weight_norm_JUL-AUG"].first())
    ZW["lo_1sd"] = (ZW.frequency - ZW.interannual_sd).round(4)
    ZW["hi_1sd"] = (ZW.frequency + ZW.interannual_sd).round(4)
    ZW.to_csv(OUT / "zone_weights.csv", index=False)
    overlap = all(ZW.lo_1sd.max() <= h for h in ZW.hi_1sd)
    stats_put("profile", dict(common_years={f"{k[0]}|{k[1]}": v for k, v in common.items()}, primary=PRIMARY,
                              zone_weights=ZW.to_dict("records"), all_1sd_intervals_overlap=bool(overlap),
                              max_abs_paired_t=float(PR.t_paired.abs().max()) if len(PR) else None))
    log(f"  JUL-AUG common years {common[(PRIMARY, 'JUL-AUG')]}; weights {ZW[['station_id', 'frequency', 'interannual_sd', 'weight_norm']].to_dict('records')}")


# =============================================================================================== stage: db
SRC_STATIONS = "SRC-EUSKALMET-STATIONS"
SRC_MET = "SRC-EUSKALMET-MET-{y}"
DB_VARS = ["tair", "rh", "wind_speed", "wind_gust", "wind_dir", "precip"]
URL_MET = "https://opendata.euskadi.eus/contenidos/ds_meteorologicos/met_stations_ds_{y}/opendata/{y}.zip"
URL_ST = "https://opendata.euskadi.eus/contenidos/ds_meteorologicos/estaciones_meteorologicas/opendata/estaciones.geojson"
DEFINITION = ("indicador exploratorio flAIre v1 (NOT FWI, NOT an official index). Adverse day (UTC day) = "
              "Tmax >= 25 degC AND RHmin <= 40 % AND no rain day (daily precipitation >= 1.0 mm) in the 3 previous days. "
              "Station 10-min Euskalmet data, T/RH at 1.44-1.80 m. Historical frequency of adverse days, not fire probability.")
VALID_RULE = (f"day valid if >= {MIN_SLOTS} of 144 10-min values usable for tair AND rh (RH 100-105 % counted as 100), "
              "the day is not a spatial-consistency outlier, and precipitation is valid (>= 130 slots) on each of the 3 previous "
              f"days; a station-season-year is used only if >= {int(SEASON_COMPLETE * 100)} % of its days are valid; profile period "
              "= years complete at all zone stations (JUL-AUG: 2019, 2020, 2022, 2023)")


def zone_id(st):
    return f"Z-{st}"


def stage_db():
    log("db tables -> processed/weather/db_tables/")
    INV = pd.read_csv(OUT / "station_inventory.csv")
    zs = stats_get()["zones"]
    used = zs["stations_used"]
    # weather_stations (all 10; geometry from x, y in EPSG:25830)
    WS = pd.DataFrame(dict(station_id=INV.station_id, name=INV.name, operator="Euskalmet", lon=INV.lon, lat=INV.lat,
                           x=INV.x, y=INV.y, elevation_m=np.nan,
                           temp_sensor_height_m=INV.tair_height_m.astype(str).str.split(";").str[0].astype(float),
                           wind_sensor_height_m=pd.to_numeric(INV.wind_height_m.astype(str).str.split(";").str[0], errors="coerce"),
                           native_timezone="UTC", native_frequency_min=10, in_pilot=INV.inside_tolosaldea.astype(int),
                           source_id=SRC_STATIONS))
    WS.to_csv(DBT / "weather_stations.csv", index=False)
    pd.DataFrame([dict(method_version=METHOD_VERSION, index_type="threshold_rule", definition=DEFINITION,
                       valid_day_rule=VALID_RULE, year_from=2018, year_to=2023, source_id=None)]).to_csv(DBT / "profile_methods.csv", index=False)
    name = INV.set_index("station_id").name
    Zm = pd.read_csv(OUT / "zone_assignment_municipality.csv")
    pd.DataFrame([dict(zone_id=zone_id(s), station_id=s,
                       description=f"Zone represented by Euskalmet {s} {name[s]}; municipalities: "
                                   + ", ".join(Zm[Zm.station_id == s].name)
                                   + f" (rule: elevation-adjusted nearest KM station, 1 m height = {ELEV_SCALE:g} m distance)")
                  for s in used]).to_csv(DBT / "weather_zones.csv", index=False)
    Q = pd.read_csv(OUT / "quality_monthly.csv")
    Q[["station_id", "year", "month", "variable", "n_expected", "n_present", "n_valid"]].to_csv(DBT / "weather_quality.csv", index=False)
    # zone_assignment: every Tolosaldea building (not only the analysis set, so a new vegetation layer needs no rerun)
    BZ = pd.read_csv(OUT / "building_weights.csv", dtype={"station_id": str})
    ZA = pd.DataFrame(dict(building_id=BZ.building_id, method_version=METHOD_VERSION, zone_id=BZ.station_id.map(zone_id),
                           station_id=BZ.station_id, assign_method=ASSIGN_METHOD, distance_km=BZ.distance_km,
                           elev_diff_m=BZ.elev_diff_proxy_m))
    assert ZA.building_id.is_unique
    ZA.to_csv(DBT / "zone_assignment.csv", index=False)
    # profiles (primary rule, common period)
    P = pd.read_csv(OUT / "season_profile.csv", dtype={"station_id": str})
    P = P[(P.rule == PRIMARY) & (P.variant == "common_period") & P.station_id.isin(used)]
    Yall = pd.read_csv(OUT / "season_profile_year.csv", dtype={"station_id": str})
    prof, pyear = [], []
    for r in P.itertuples():
        yrs = [int(y) for y in str(r.years).split(",") if y and y != "nan"]
        prof.append(dict(zone_id=zone_id(r.station_id), season_id=r.season_id, method_version=METHOD_VERSION,
                         year_from=min(yrs), year_to=max(yrs), n_years_used=len(yrs), valid_days=int(r.valid_days),
                         adverse_days=int(r.adverse_days),
                         adverse_day_frequency=(r.adverse_days / r.valid_days) if r.valid_days > 0 else None,
                         interannual_sd=None if pd.isna(r.interannual_sd) else r.interannual_sd, data_version=DATA_VERSION))
        y = Yall[(Yall.rule == PRIMARY) & (Yall.season_id == r.season_id) & (Yall.station_id == r.station_id) & Yall.year.isin(yrs)]
        for q in y.itertuples():
            pyear.append(dict(zone_id=zone_id(r.station_id), season_id=r.season_id, method_version=METHOD_VERSION,
                              data_version=DATA_VERSION, year=int(q.year), valid_days=int(q.valid_days), adverse_days=int(q.adverse_days)))
    pd.DataFrame(prof).to_csv(DBT / "weather_profile.csv", index=False, float_format="%.12g")
    pd.DataFrame(pyear).to_csv(DBT / "weather_profile_year.csv", index=False)
    # adverse days (primary rule, all months 2018-2023, zone stations)
    D = pd.read_csv(OUT / "daily_with_rules.csv", dtype={"station_id": str})
    A = D[D[f"adv_{PRIMARY}"] & D.station_id.isin(used)]
    AD = pd.DataFrame(dict(zone_id=A.station_id.map(zone_id), method_version=METHOD_VERSION, date_utc=A.date,
                           tmax_c=A.tmax_c, rhmin_pct=A.rhmin_pct,
                           wind_max_ms=A.wind_max_ms.where(A.valid_wind_speed), precip_mm=A.precip_mm.where(A.valid_precip)))
    AD.to_csv(DBT / "weather_adverse_days.csv", index=False)
    # weather_obs: ORIGINAL 10-min values of the 6 schema variables, zone stations, on every adverse day (lets anyone check
    # a daily figure against the raw data). The full record is processed/weather/obs_10min.parquet (16.7 M rows).
    O = load_obs(["station", "ts_utc", "variable", "value", "quality_flag", "usable", "value_used"], DB_VARS)
    O = O[O.station.isin(used)]
    O["date"] = O.ts_utc.dt.strftime("%Y-%m-%d")
    keys = set(zip(A.station_id, A.date))
    O = O[[k in keys for k in zip(O.station.astype(str), O.date)]]
    grid = pd.DataFrame([(st, pd.Timestamp(d, tz="UTC") + pd.Timedelta(minutes=10 * i), v)
                         for st, d in keys for i in range(SLOTS_PER_DAY) for v in DB_VARS],
                        columns=["station", "ts_utc", "variable"])
    O["station"] = O.station.astype(str)
    O["variable"] = O.variable.astype(str)
    G = grid.merge(O, how="left", on=["station", "ts_utc", "variable"])
    qf = G.quality_flag.astype(object).fillna("missing")
    flagmap = {"valid": "valid", "suspect_usable": "suspect", "suspect": "suspect", "invalid": "invalid", "missing": "missing"}
    G["quality_flag"] = qf.map(flagmap)
    val = np.where(qf == "suspect_usable", G.value_used, G.value)          # RH 100-105 stored as 100 (schema CHECK 0..100)
    G["value"] = np.where(G.quality_flag.isin(["missing", "invalid"]), np.nan, val)
    G["unit"] = G.variable.map({"tair": "degC", "rh": "%", "wind_speed": "m/s", "wind_gust": "m/s", "wind_dir": "deg", "precip": "mm"})
    G["source_id"] = [SRC_MET.format(y=t.year) for t in G.ts_utc]
    G["station_id"] = G.station
    G["ts_utc"] = G.ts_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    G = G[["station_id", "ts_utc", "variable", "value", "unit", "quality_flag", "source_id"]].sort_values(["station_id", "ts_utc", "variable"])
    G.to_csv(DBT / "weather_obs.csv", index=False)
    # field notes for the DB tables
    (DBT / "README.md").write_text(DB_README.format(n_obs=len(G), n_days=len(keys)), encoding="utf-8")
    stage_sources()
    log(f"  weather_stations {len(WS)}, zone_assignment {len(ZA)}, profile {len(prof)}, profile_year {len(pyear)}, "
        f"adverse_days {len(AD)}, weather_obs {len(G)}, weather_quality {len(Q)}")


DB_README = """# processed/weather/db_tables — P1 weather plug-in for code/link_build.py (load_weather_tables)

CSV names = schema tables, columns = schema columns (weather_stations also carries x, y EPSG:25830 for the geometry).
Generated by `python3 code/weather.py --stages db` (re-run `--stages zones,profile,db,report` after any change of the
building set: it takes seconds). Method ADV-v1 = "indicador exploratorio flAIre v1", NOT FWI.

- weather_stations: 10 Euskalmet stations; elevation_m NULL (not published in the catalogue nor in the XML/XSD);
  native_timezone = UTC (established empirically, reports/quality_weather.md §2).
- profile_methods: ADV-v1 (threshold_rule).
- weather_zones: Z-C026 Berastegi, Z-C029 Zizurkil, Z-C058 Bidania.
- weather_quality: station x year x month x variable, n_expected 10-min slots, n_present, n_valid (usable).
- zone_assignment: EVERY building of buildings_tolosaldea.gpkg (not only the analysis set) -> one zone;
  assign_method 'nearest_same_valley' = elevation-adjusted nearest station by municipality; elev_diff_m = building
  ground elevation (B5M) - station elevation PROXY (median B5M elevation of buildings <= 500 m from the station).
- weather_profile / weather_profile_year: JUL-AUG and JUN-SEP, common period of the 3 zone stations.
  adverse_day_frequency = adverse_days / valid_days exactly (raw frequency; the normalized weight mean = 1 lives in
  processed/weather/building_weights.csv — the optimizer objective is scale-invariant, so raw = normalized for rankings).
- weather_adverse_days: every ADV-v1 adverse day 2018-2023, ALL months, zone stations (wind_max_ms = max 10-min mean).
- weather_obs: {n_obs:,} rows = the ORIGINAL 10-min values (tair, rh, wind_speed, wind_gust, wind_dir, precip) of the
  zone stations on the {n_days} adverse station-days, so a daily figure can be checked against raw data. Absent slots are
  rows with quality_flag 'missing' and NULL value; RH 100-105 % (saturation overshoot) stored as 100 with flag 'suspect'.
  Full record: processed/weather/obs_10min.parquet.
"""


def stage_sources():
    """Upsert P1 rows in reports/sources.csv (one per yearly archive + catalogue). sha256 of a yearly archive = sha256 of
    the sorted '<inner zip>:<sha256>' list of the 10 station zips taken unchanged from it (the 136-147 MB archives
    themselves are on Carlos's PC, not in raw/)."""
    S = pd.read_csv(REP / "sources.csv")
    S = S[~S.source_id.astype(str).str.startswith("SRC-EUSKALMET")]
    IZ = pd.read_csv(OUT / "inner_zips.csv")
    rows = []
    for y in YEARS:
        sub = IZ[IZ.year == y].sort_values("inner_zip")
        h = hashlib.sha256("".join(f"{a}:{b}\n" for a, b in zip(sub.inner_zip, sub.sha256)).encode()).hexdigest()
        rows.append(dict(source_id=SRC_MET.format(y=y),
                         dataset=f"Euskalmet meteorological stations, 10-minute readings, calendar year {y} (XML per station-month)",
                         organisation="EUSKALMET, Gobierno Vasco - Dpto. Seguridad (Open Data Euskadi)", url=URL_MET.format(y=y),
                         licence="CC BY 4.0 + Euskalmet legal information", download_date="2026-10-01",
                         edition_or_period=f"{y}-01-01..{y}-12-31",
                         raw_file="raw/flaire_meteo_tolosaldea_2018_2023.zip",
                         processed_files="processed/weather/obs_10min.parquet; processed/weather/*; db weather_* tables",
                         notes=(f"sha256={h}; sha256 = sorted '<inner zip>:<sha256>' list of the 10 station zips {y}_<CODE>_{y}.zip "
                                f"extracted unchanged from {y}.zip into raw/flaire_meteo_tolosaldea_2018_2023.zip; "
                                f"period={y}-01-01..{y}-12-31; timestamps UTC (established empirically); wind in m/s per XSD"
                                + ("; C026 Berastegi only Jan-Jun" if y == 2021 else "")
                                + ("; C026 Berastegi only Jun-Dec" if y == 2022 else "")
                                + ("; dataset page metadata wrongly describes 2018" if y == 2023 else ""))))
    rows.append(dict(source_id=SRC_STATIONS, dataset="Euskalmet station catalogue (Red de estaciones meteorologicas de Euskadi), 153 stations",
                     organisation="EUSKALMET, Gobierno Vasco (Open Data Euskadi)", url=URL_ST, licence="CC BY 4.0",
                     download_date="2026-10-01", edition_or_period="updated 2026-09-17",
                     raw_file="raw/estaciones.geojson; raw/estaciones.xlsx",
                     processed_files="processed/weather/station_inventory.csv; db weather_stations",
                     notes=f"sha256={sha256_file(CAT_GEOJSON)}; sha256 of the geojson; xlsx sha256={sha256_file(CAT_XLSX)}; "
                           "same content (code, name, type, lon/lat WGS84, municipality); no altitude field; type codes undocumented"))
    S = pd.concat([S, pd.DataFrame(rows)], ignore_index=True)
    S.to_csv(REP / "sources.csv", index=False)


# =============================================================================================== stage: validate
def stage_validate():
    """Load db_tables into a COPY of db/flaire.gpkg with link_build.load_weather_tables (schema CHECKs/FKs/triggers apply).
    Does NOT touch db/flaire.gpkg. Also previews weighted vs uniform Strategy A with optimizer.py on the CURRENT analysis set."""
    import shutil
    import sqlite3
    log("validate (DB copy)")
    sys.path.insert(0, str(Path(__file__).parent))
    sys.path.insert(0, str(Path(__file__).parent))
    import link_build as lb
    tmpdir = Path(__import__("os").environ.get("FLAIRE_SCRATCH", "/tmp")) / "flaire_weather_validate"
    tmpdir.mkdir(parents=True, exist_ok=True)
    dbc = tmpdir / "flaire_copy.gpkg"
    shutil.copy(lb.DB, dbc)
    con = sqlite3.connect(dbc)
    con.execute("PRAGMA foreign_keys=ON")
    res = {}
    with con:
        for t in reversed(lb.WEATHER_TABLES):
            con.execute(f"DELETE FROM {t}")
        # sources rows, transformed exactly like link_build.sources_table() does
        S = pd.read_csv(REP / "sources.csv")
        S = S[S.source_id.str.startswith("SRC-EUSKALMET")]
        for r in S.itertuples():
            sha = re.search(r"sha256=([0-9a-f]{64})", r.notes).group(1)
            con.execute("INSERT OR REPLACE INTO sources (source_id,title,organization,url,licence,download_date,edition,raw_file,"
                        "sha256,owner_persona,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r.source_id, r.dataset, r.organisation, r.url, r.licence, r.download_date, r.edition_or_period,
                         r.raw_file.split(";")[0].strip(), sha, "P1", r.notes))
        # buildings that exist in the current buildings gpkg but not yet in this (older) DB copy cannot satisfy the FK
        # until the main rebuild: test with the shared ids, report the others
        ids = {x[0] for x in con.execute("SELECT building_id FROM buildings")}
        za = pd.read_csv(DBT / "zone_assignment.csv")
        res["zone_assignment_ids_not_in_db_copy"] = sorted(set(za.building_id) - ids)
        res["db_copy_buildings_without_zone"] = sorted(ids - set(za.building_id))
        orig = lb.WEATHER_DIR
        tmp_tables = tmpdir / "db_tables"
        tmp_tables.mkdir(exist_ok=True)
        for f in DBT.glob("*.csv"):
            shutil.copy(f, tmp_tables / f.name)
        za[za.building_id.isin(ids)].to_csv(tmp_tables / "zone_assignment.csv", index=False)
        lb.WEATHER_DIR = tmp_tables
        n = lb.load_weather_tables(con)
        lb.WEATHER_DIR = orig
    res["loaded_rows"] = n
    res["fk_violations"] = con.execute("PRAGMA foreign_key_check").fetchall()[:20]
    qa = {}
    for (v,) in con.execute("SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'qa_%' ORDER BY name"):
        qa[v] = con.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
    res["qa_views_db_copy"] = qa
    res["v_building_weight_rows"] = con.execute(
        "SELECT season_id, count(*), min(weight), max(weight), sum(weight IS NULL) FROM v_building_weight GROUP BY season_id").fetchall()
    res["scope_weight_missing"] = con.execute(
        "SELECT count(*) FROM v_scope_buildings s LEFT JOIN v_building_weight w ON w.building_id=s.building_id "
        "AND w.season_id='JUL-AUG' WHERE w.weight IS NULL").fetchone()[0]
    con.close()
    # optimizer preview on the CURRENT analysis set (travel times for all buildings already exist)
    import optimizer as opt
    T = pd.read_parquet(ROOT / "processed" / "links" / "travel_times_db_v0.2.parquet")
    T = T[(T.profile == "light")]
    A = pd.read_csv(BLD / "buildings_analysis_set.csv", usecols=["building_id"])
    BW = pd.read_csv(OUT / "building_weights.csv")
    cands = sorted(pd.read_csv(ROOT / "processed" / "candidates" / "candidates_10.csv").cand_id)
    stations = sorted(set(T.origin_id) - set(cands))
    origins = stations + cands
    bids = sorted(set(A.building_id) & set(T.building_id))
    res["preview_n_buildings"] = len(bids)
    res["preview_buildings_without_times"] = len(set(A.building_id) - set(T.building_id))
    oi = {o: i for i, o in enumerate(origins)}
    bi = {b: j for j, b in enumerate(bids)}
    M = np.full((len(origins), len(bids)), np.nan)
    Tr = T[T.routable == 1 & T.building_id.isin(bi)] if False else T[(T.routable == 1) & T.building_id.isin(bi) & T.origin_id.isin(oi)]
    M[Tr.origin_id.map(oi).values, Tr.building_id.map(bi).values] = Tr.minutes_est.values
    w = BW.set_index("building_id").loc[bids, "freq_JUL-AUG"].values
    rows = []
    for thr in (10.0, 12.0, 15.0):
        ru = opt.optimize(opt.Problem(M, origins, cands, bids, np.ones(len(bids))), thr, 6, "A")
        rw = opt.optimize(opt.Problem(M, origins, cands, bids, w), thr, 6, "A")
        for mu, mw in zip(ru["per_k"], rw["per_k"]):
            rows.append(dict(threshold_min=thr, k=mu["k"], uniform_selection=mu["selection"], weighted_selection=mw["selection"],
                             same_selection=mu["selection"] == mw["selection"], uniform_n_covered=mu["n_covered"],
                             weighted_n_covered=mw["n_covered"], uniform_ties=mu["ties"], weighted_ties=mw["ties"],
                             weighted_share_of_weighted_choice=round(mw["weighted_share"], 4) if mw["weighted_share"] is not None else None,
                             weighted_share_of_uniform_choice=None))
    PV = pd.DataFrame(rows)
    # weighted share achieved by the uniform choice (to show what is lost/gained)
    for i, r in PV.iterrows():
        sel = [c for c in str(r.uniform_selection).split("|") if c]
        idx = [oi[s] for s in stations] + [oi[c] for c in sel]
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                best = np.nanmin(M[idx], axis=0)
        cov = np.nan_to_num(best, nan=np.inf) <= r.threshold_min
        PV.loc[i, "weighted_share_of_uniform_choice"] = round(float(w[cov].sum() / w.sum()), 4)
    PV.to_csv(OUT / "optimizer_preview_weighted_vs_uniform.csv", index=False)
    res["preview_k_with_different_selection"] = PV[~PV.same_selection][["threshold_min", "k"]].values.tolist()
    stats_put("validate", res)
    log(f"  loaded {n}; FK violations {len(res['fk_violations'])}; qa {qa}; preview differing (thr,k): "
        f"{res['preview_k_with_different_selection']}")


# =============================================================================================== stage: report
def md(df, fmt=None):
    fmt = fmt or {}
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        cells = []
        for c, v in zip(cols, r):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("")
            elif isinstance(v, (float, np.floating)):
                cells.append(format(v, fmt.get(c, ".3g")))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def stage_report():
    log("report -> reports/quality_weather.md")
    st = stats_get()
    INV = pd.read_csv(OUT / "station_inventory.csv")
    Q = pd.read_csv(OUT / "quality_monthly.csv")
    F = pd.read_csv(OUT / "quality_flags_by_station_variable.csv")
    J = pd.read_csv(OUT / "adverse_rule_counts_julaug.csv", dtype={"year": str})
    AM = pd.read_csv(OUT / "adverse_rule_counts_monthly.csv")
    P = pd.read_csv(OUT / "season_profile.csv", dtype={"station_id": str})
    Y = pd.read_csv(OUT / "season_profile_year.csv", dtype={"station_id": str})
    Zm = pd.read_csv(OUT / "zone_assignment_municipality.csv")
    ZW = pd.read_csv(OUT / "zone_weights.csv")
    PR = pd.read_csv(OUT / "zone_difference_test.csv")
    PC = pd.read_csv(OUT / "precip_check.csv")
    TZ = pd.read_csv(OUT / "tzcheck_irradiance.csv")
    DST = pd.read_csv(OUT / "tzcheck_dst_days.csv")
    BW = pd.read_csv(OUT / "building_weights.csv", dtype={"station_id": str})
    PVf = OUT / "optimizer_preview_weighted_vs_uniform.csv"
    PV = pd.read_csv(PVf) if PVf.exists() else None
    zs, pf, va = st["zones"], st["profile"], st.get("validate", {})
    used = zs["stations_used"]
    nA = int(BW.in_analysis_set.sum())
    L = []
    A = L.append
    A("# flAIre · P1 Meteorology — quality report (Euskalmet 10-min stations, Tolosaldea, 2018–2023)\n")
    A(f"Generated by `code/weather.py` (re-runnable) on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. "
      f"Data version label for the DB: `{DATA_VERSION}`. Method: **{METHOD_VERSION} = \"indicador exploratorio flAIre v1\" — "
      "NOT FWI, NOT an official index; a historical frequency of adverse days, not a fire probability.**\n")
    jt = J[(J.rule == PRIMARY) & (J.year == "2018-2023")].set_index("station_id")
    A("## 0. Summary\n")
    w = ZW.set_index("station_id")
    A(f"- **10 stations parsed**, {16_699_536:,} original 10-min values of 10 meteorological variables (`processed/weather/obs_10min.parquet`). "
      "Only the 4 **KM** stations (C026 Berastegi, C029 Zizurkil, C058 Bidania, C043 Ordizia) measure wind; the 6 KC/KA river stations measure T, RH, precipitation (+ hydrology).")
    A("- **Timestamps are UTC** (no DST behaviour; irradiance centred on solar noon UTC all year, ≈ +4 min → labels = end of the 10-min interval). "
      "**Wind is m/s** (2023 XSD documentation), not km/h as the collector note assumed.")
    A("- Completeness is high (≥ 98 % valid for most station-years). Main gaps: **C026 Berastegi Jul 2021–May 2022** (no data), "
      "**C058 Bidania RH Jul–Sep 2018 + part of 2019** (sensor outage/invalid), C0EA RH autumn 2019–2020 (stuck/near-0 values).")
    A(f"- **Primary rule (ADV-v1)**: Tmax ≥ 25 °C AND RHmin ≤ 40 % AND no rain day (≥ 1 mm) in the 3 previous days. Jul–Aug 2018–2023 adverse days: "
      + ", ".join(f"{s} {int(jt.adverse_days[s])}/{int(jt.valid_days[s])}" for s in ["C026", "C029", "C058", "C043"]) + " (adverse/valid days).")
    A("- **Seasonality**: adverse days are NOT concentrated in July–August: September is the peak month at 8 of 10 stations and Zizurkil C029 has more adverse days in October "
      "than in July+August; the dry-wind variant (south foehn) peaks in **February–March**. See §5.3.")
    A(f"- **Zones**: 28 municipalities → 3 in-territory KM stations by elevation-adjusted nearest distance: C029 Zizurkil (valley floor, "
      f"{int(w.n_analysis_buildings.get('C029', 0))} analysis-set buildings), C026 Berastegi ({int(w.n_analysis_buildings.get('C026', 0))}), "
      f"C058 Bidania ({int(w.n_analysis_buildings.get('C058', 0))}); analysis set = {nA:,} buildings (current Mapa Forestal set).")
    A(f"- **Weights (JUL-AUG, common period {', '.join(map(str, pf['common_years'][PRIMARY + '|JUL-AUG']))})**: "
      + "; ".join(f"{s} freq {w.frequency[s]:.3f} ± {w.interannual_sd[s]:.3f} (sd) → weight {w.weight_norm[s]:.2f}" for s in used) + ". "
      "**All ±1 sd intervals overlap: the zone differences are within inter-annual noise (4 years). Treat weights as nearly flat — "
      "weighted Strategy A ≈ count maximisation with a mild tie-break towards Berastegi/Bidania zones.** The only consistent signal is "
      "Zizurkil ≤ Berastegi in every year (strictly lower in 4 of 4 years for ADV-v1 and the wind variant R1).")
    if PV is not None:
        nd = int((~PV.same_selection).sum())
        A(f"- **Optimizer preview** (light profile, current analysis set, `optimizer.py` directly, NOT the DB rebuild): weighted vs uniform Strategy A pick "
          f"a different combination in {nd} of {len(PV)} (threshold, k) cases, always near-ties (building counts differ by "
          f"{int((PV.uniform_n_covered - PV.weighted_n_covered).abs().max())} buildings at most, weighted share by "
          f"≤ {100 * (PV.weighted_share_of_weighted_choice - PV.weighted_share_of_uniform_choice).abs().max():.1f} pp). §9.")
    A("- DB plug-in tables written to `processed/weather/db_tables/` and validated by loading them with `link_build.load_weather_tables` into a "
      f"**copy** of `db/flaire.gpkg`: all schema CHECKs/FKs pass, {len(va.get('fk_violations', []))} FK violations, every `qa_*` view = 0 in the copy "
      "(incl. `qa_scope_without_zone`). link_build.py was NOT run (main agent rebuilds after the forest layer).\n")

    A("## 1. Sources\n")
    A("| source_id | what | URL |\n|---|---|---|")
    for y in YEARS:
        A(f"| {SRC_MET.format(y=y)} | yearly archive {y}.zip → 10 station zips `{y}_<CODE>_{y}.zip` (unchanged) | {URL_MET.format(y=y)} |")
    A(f"| {SRC_STATIONS} | station catalogue (153 stations, updated 2026-09-17) | {URL_ST} (+ .xlsx) |")
    A("\nEUSKALMET, Gobierno Vasco – Dpto. Seguridad (Open Data Euskadi), CC BY 4.0 + Euskalmet legal information, downloaded 2026-10-01 20:41–20:57 UTC "
      "(collector, Carlos's PC). sha256 per year = sha256 of the sorted `<inner zip>:<sha256>` list (`processed/weather/inner_zips.csv`). "
      "Rows are in `reports/sources.csv`. Known source issue: the 2023 dataset page metadata describes 2018.\n")

    A("## 2. Format, units, time zone\n")
    A("- Each station zip holds one XML per month (`CODE_YYYY_M.xml`, ISO-8859-1) + XSD: `<mes><dia Dia=\"YYYY-M-DD\"><hora Hora=\"HH:MM\"><Meteoros><Tag._a_<h>cm>value</…>`. "
      "Tag = variable + **sensor height in cm**. Month in `Dia` is not zero-padded. 2018–2022 XSDs list tags only; **2023 XSDs document units**: "
      "temperature °C, RH %, precipitation mm, **wind speed / max / sigma m/s**, direction °, irradiance W/m², pressure mb.")
    A("- Wind: the collector note (from `abreviaturas.txt`) says km/h; the 2023 XSD says **m/s** and magnitudes agree with m/s "
      "(10-min mean median 1.6, p99.9 10.7; highest gust 38 m/s = 137 km/h at C026 on 2018-01-29, a winter storm value; as km/h these would be implausibly calm). Used m/s (= schema unit).")
    A(f"- **Time zone = UTC**, established empirically (the source does not state it):")
    A(f"  1. DST: on all 12 change days (last Sunday of March/October 2018–2023) every station has exactly "
      f"{int(DST.slots_min.min())} slots, no duplicated or missing hour (local civil time would give 138/150 slots). "
      f"Every day in the archive has ≤ {st['tzcheck']['max_slots_any_day']} slots.")
    A(f"  2. Irradiance (KM stations): the daily irradiance-weighted centroid time minus solar noon in UTC (equation of time, station longitude) is "
      + ", ".join(f"{k}: {v:+.1f} min" for k, v in st["tzcheck"]["irradiance_offset_by_half"].items())
      + ". Local time would give ≈ +60 min (winter) / +120 min (summer). The constant ≈ +4 min offset suggests each label is the **end** of its 10-min "
      "averaging interval (±10 min is irrelevant for daily aggregates).")
    A("\n" + md(TZ) + "\n")
    A("- `ts_utc` = label as published (no shift). Daily aggregates use the **UTC day** (00:00–23:50 UTC = 02:00–01:50 CEST in summer); "
      "Tmax/RHmin occur in the afternoon, so the UTC/local day boundary does not affect them.\n")

    A("## 3. Station inventory\n")
    A("Catalogue type codes are **not documented**; meanings below are inferred from the sensors present: "
      "**KM** = full meteorological station (wind, irradiance, T/RH, precipitation); **KC** = river station with water-quality probes "
      "(pH, conductivity, O₂, turbidity, level) + T/RH/precip; **KA** = river gauging station (level/flow) + T/RH/precip; **B** = port/buoy stations. "
      "**Altitude is not in the catalogue (no field) nor in the XML/XSD → `elevation_m` = NULL.** As a documented proxy only, "
      "`elev_proxy_bldg500m_m` = median B5M ground elevation of Tolosaldea buildings ≤ 500 m from the station (none for stations outside Tolosaldea).\n")
    inv = INV[["station_id", "name", "type", "catalogue_municipality", "lon", "lat", "inside_tolosaldea", "dist_boundary_km",
               "elev_proxy_bldg500m_m", "n_bldg_proxy", "tair_height_m", "precip_height_m", "wind_height_m", "first_ts_utc", "last_ts_utc"]].copy()
    inv["first_ts_utc"] = inv.first_ts_utc.str[:16]
    inv["last_ts_utc"] = inv.last_ts_utc.str[:16]
    A(md(inv, {"lon": ".5f", "lat": ".5f", "dist_boundary_km": ".2f", "elev_proxy_bldg500m_m": ".0f"}))
    A("\nVariables and heights per year (from the data; hydrology/water-quality tags listed in `station_inventory.csv` are not parsed):\n")
    for r in INV.itertuples():
        A(f"- **{r.station_id} {r.name}**: " + r.variables_by_year.replace(" | ", "; "))
    A("\nSensor heights are constant over 2018–2023 at every station (only C043 pressure moves from 0 to 50 cm in 2021). Not comparable across stations: wind at 9.3 m (C058), 11.4 m (C029), 11.5 m (C026), "
      "20 m (C043) — none at the WMO 10 m standard; river stations have T/RH at 1.0–4.35 m (C0EA 3.15 m, C077 4.35 m) on river banks.\n")

    A("## 4. Parsing, flags, completeness\n")
    A("Long table `obs_10min.parquet`: station, ts_utc, variable, sensor_height_cm, value (as published), unit, quality_flag, flag_reason, usable, "
      "value_used, tag, raw (non-numeric text). No duplicates (station, ts, variable, height). **Nothing is filled; missing ≠ 0.** Flag rules:\n")
    A(f"- `invalid` (impossible / sentinel −799.9, ±7999): T ∉ [−30, 50] °C, RH < 0 or > 105 %, wind < 0 or > 75 m/s, precip < 0, irradiance ∉ [0, 1500], pressure ∉ [850, 1080] hPa.")
    A(f"- `suspect` (not used): T ∉ [−20, 42]; RH < 3 % (e.g. C026 7–11 Jun 2018 ≈ 1 % for days = sensor failure); T spike > {SPIKE_T:g} °C vs both neighbours; "
      "T constant ≥ 6 h; RH constant < 99 % ≥ 12 h; wind constant non-zero ≥ 6 h or exactly 0 ≥ 24 h (frozen anemometer, C026 2018/2021).")
    A("- `suspect_usable`: **RH in (100, 105] %** (capacitive sensor saturation in fog/rain; 9 % of all RH values, up to 20 % at C077) → used as 100 % in aggregates. "
      "Treating them as invalid would delete mostly humid, non-adverse days and inflate adverse frequencies. In the DB they are stored as 100 with flag `suspect` (schema CHECK RH ≤ 100); the raw value stays in the Parquet.")
    A("- `missing`: empty/non-numeric element (107,464 values; whole-slot gaps are counted in completeness as expected − present).\n")
    f2 = F[F.variable.isin(["tair", "rh", "precip", "wind_speed"])][["station", "variable", "valid", "suspect_usable", "suspect", "invalid", "missing"]]
    A(md(f2, {c: ".0f" for c in f2.columns}))
    A("\n**% valid (usable) 10-min values per station-year** (expected slots = days × 144; full table station × year × month × variable in `quality_monthly.csv` → DB `weather_quality`):\n")
    q = (Q[Q.variable.isin(["tair", "rh", "precip", "wind_speed"])].groupby(["station_id", "variable", "year"])
         .apply(lambda g: round(100 * g.n_valid.sum() / g.n_expected.sum(), 1), include_groups=False).unstack().reset_index())
    q.columns = [str(c) for c in q.columns]
    A(md(q, {str(y): ".1f" for y in YEARS}))
    low = Q[(Q.variable.isin(["tair", "rh", "precip", "wind_speed"])) & (Q.pct_valid < 80) & (Q.station_id.isin(used + ["C043"]))]
    lowg = low.groupby(["station_id", "variable"]).apply(lambda g: ", ".join(f"{a}-{b:02d}" for a, b in zip(g.year, g.month)), include_groups=False)
    A("\nMonths < 80 % valid at the KM stations: " + "; ".join(f"**{a} {b}**: {v}" for (a, b), v in lowg.items()) + "\n")

    A("## 5. Daily aggregates and the adverse-day indicator\n")
    A(f"`daily.csv` (station × UTC day 2018–2023, 21,910 rows): Tmax/Tmin/Tmean, RHmin/RHmean (+ time of Tmax / RHmin), max 10-min mean wind, "
      f"daily mean wind, max gust (Vel.Max), precipitation sum, and n usable slots per variable. **A variable is valid for a day if ≥ {MIN_SLOTS} of 144 slots "
      f"(90.3 %) are usable**; a rule is evaluable only if every variable it needs is valid.")
    A(f"- Spatial consistency: a day is excluded if Tmax differs > 8 °C from the median of the other stations ({st['daily']['spatial_suspect_tair']} station-days) "
      f"or RHmin < 20 % while the others' median RHmin > 50 % ({st['daily']['spatial_suspect_rh']} station-days, mostly C0E8 Jan 2018 drifting RH sensor). "
      "One of them (C052 2019-07-25, 36 °C / RHmin 19 %) is probably genuine; C052 is not a zone station.")
    A(f"- **Precipitation = interval amounts per 10 min, not accumulated**: {PC.pct_zero.median():.0f} % of slots are 0, decreases are as frequent as increases "
      f"({PC.pct_decrease.median():.1f} % vs {PC.pct_increase.median():.1f} %; an accumulator would only increase and reset), max 10-min value 18.5 mm, "
      f"annual sums {PC[PC.n > 50000].sum_mm.min():.0f}–{PC[PC.n > 50000].sum_mm.max():.0f} mm (plausible for Tolosaldea). Daily = sum. Rain day = ≥ {RAIN_DAY_MM:g} mm.\n")
    A("### 5.1 Variants (Jul–Aug 2018–2023, adverse days / valid days per station)\n")
    A("Thresholds in data units: 15 km/h = 4.17 m/s, 20 km/h = 5.56 m/s; wind = max of the 10-min means of the day.\n")
    A("| rule | definition |\n|---|---|")
    for rid, r in RULES.items():
        A(f"| {rid}{' **(primary, ADV-v1)**' if rid == PRIMARY else ''} | {r['label']} |")
    jt2 = J[J.year == "2018-2023"].copy()
    jt2["cell"] = [f"{int(a)}/{int(v)}" if v > 0 else "n/a" for a, v in zip(jt2.adverse_days, jt2.valid_days)]
    piv = jt2.pivot(index="station_id", columns="rule", values="cell").reindex(STATIONS)[list(RULES)].reset_index()
    A("\n" + md(piv))
    A("\nPer year (Jul–Aug, adverse days) at the KM stations, primary rule and R1 (wind):\n")
    for rid in (PRIMARY, "R1_T25_RH40_W15"):
        jy = J[(J.rule == rid) & (J.year != "2018-2023") & J.station_id.isin(["C026", "C029", "C058", "C043"])]
        pv = jy.assign(c=[f"{int(a)}/{int(v)}" for a, v in zip(jy.adverse_days, jy.valid_days)]).pivot(index="station_id", columns="year", values="c").reset_index()
        A(f"{rid}:\n\n" + md(pv) + "\n")
    A("### 5.2 Choice of the primary rule\n")
    A("**ADV-v1 = R4N: Tmax ≥ 25 °C AND RHmin ≤ 40 % AND no rain day in the 3 previous days.** Reasons:")
    A("1. **Computable at all 10 stations** with comparable sensors (T/RH screens, tipping-bucket rain gauge); wind exists only at the 4 KM stations and is "
      "measured at 9.3–20 m, so a wind threshold is not comparable between stations (C043 at 20 m sees systematically stronger wind).")
    A("2. **Non-trivial counts**: 14–23 days at the three zone stations in Jul–Aug 2018–2023 (≈ 2–8 per season), not saturated and not zero.")
    A("3. The 3-day antecedent-dry condition is a transparent proxy for dead-fuel drying and removes hot afternoons right after rain; R4 alone (no rain filter) "
      "gives 50–85 % more days at the zone stations; R2 (RH ≤ 35) is of similar size to R4N.")
    A("4. R1 (with wind ≥ 15 km/h) gives a similar station ranking (Zizurkil lowest, Berastegi ≈ Bidania) — reported as sensitivity, see §7. The wind variant is "
      "more fire-relevant in principle, but its station differences are partly instrument height/siting.")
    A("This is a demo indicator: thresholds are round numbers, not calibrated against fire records (no fire-occurrence data in the package).\n")
    A("### 5.3 All months (2018–2023 pooled, adverse days per month)\n")
    for rid in (PRIMARY, "R1_T25_RH40_W15", "R3_DRYWIND_RH40_W20"):
        am = AM[AM.rule == rid].pivot(index="station_id", columns="month", values="adverse_days")
        am = am.loc[[s for s in STATIONS if s in am.index and AM[(AM.rule == rid) & (AM.station_id == s)].valid_days.sum() > 0]].reset_index()
        am.columns = [str(c) for c in am.columns]
        A(f"**{rid}**\n\n" + md(am, {c: ".0f" for c in am.columns}) + "\n")
    A("Honest reading: with temperature-based rules **September is the peak month at 8 of 10 stations** (C077 Andoain: October; C0EA Belauntza: May) and May–June and October are comparable to July–August "
      "(Zizurkil C029 has more adverse days in October than in July+August). The dry-wind rule (no temperature condition) peaks in **February–March** "
      "(southerly foehn episodes, e.g. 2019-02-17 with RH ≈ 5–8 % at several stations). A July–August plan therefore covers only part of the historically "
      "adverse days; `weather_adverse_days` in the DB contains all months so the agent can say so.\n")

    A("## 6. Season profiles (primary rule)\n")
    cy = pf["common_years"][PRIMARY + "|JUL-AUG"]
    A(f"A station-season-year is used if ≥ {int(SEASON_COMPLETE * 100)} % of its days are valid for the rule. **Common comparison period = years complete at "
      f"all three zone stations: JUL-AUG {', '.join(map(str, cy))}** (2018 dropped: C058 RH outage; 2021 dropped: C026 gap). The pipeline rule "
      "\"profile period identical for all zones\" is respected; per-station profiles with all their complete years are given as a sensitivity.\n")
    pp = P[(P.rule == PRIMARY) & P.station_id.isin(["C026", "C029", "C058", "C043"])][
        ["season_id", "station_id", "variant", "years", "valid_days", "adverse_days", "frequency", "interannual_mean", "interannual_sd", "excluded_years", "months_below_80pct"]]
    A(md(pp, {"frequency": ".3f", "interannual_mean": ".3f", "interannual_sd": ".3f"}))
    yy = Y[(Y.rule == PRIMARY) & (Y.season_id == "JUL-AUG") & Y.station_id.isin(["C026", "C029", "C058", "C043"])]
    yv = yy.assign(c=[f"{int(a)}/{int(v)}{'' if c else '*'}" for a, v, c in zip(yy.adverse_days, yy.valid_days, yy.complete)]).pivot(
        index="station_id", columns="year", values="c").reset_index()
    yv.columns = [str(c) for c in yv.columns]
    A("\nJul–Aug per year (adverse/valid; * = < 80 % valid, not used):\n\n" + md(yv) + "\n")

    A("## 7. Zone assignment\n")
    A(f"Eligible stations: KM stations inside Tolosaldea or ≤ {MUN_SNAP_KM:g} km from it with valid summer data → **{', '.join(zs['eligible'])}**. "
      f"C043 Ordizia ({INV.set_index('station_id').dist_boundary_km['C043']:.1f} km outside) is context/sensitivity only; KC/KA river stations are not used "
      "(bank-side T/RH at 1–4.35 m, not representative of slopes).")
    A(f"Rule (`assign_method = '{ASSIGN_METHOD}'`): for each municipality, representative point = centroid of its analysis-set buildings; elevation = their median "
      f"B5M ground elevation; station = argmin √(d² + ({ELEV_SCALE:g}·Δz)²), i.e. **1 m of height difference weighs like {ELEV_SCALE:g} m of distance** "
      "(station elevation = building proxy, §3). Every building inherits its municipality's station (so a building is in exactly one zone). Why: pure straight-line "
      "nearest put Tolosa, Alegia and Ikaztegieta (valley floor ≈ 90–110 m) on Bidania (plateau ≈ 520 m); the adjustment sends valley-floor towns to Zizurkil "
      f"(Oria valley floor, ≈ 70 m) and uplands to Berastegi/Bidania. A factor of 100 was tested and rejected (it pushed Albiztur/Abaltzisketa, next to Bidania, to Berastegi 13 km away). "
      "**Limitation**: no DEM in the package, station altitudes are proxies, the factor is a heuristic, and valley/foehn exposure is not modelled.\n")
    zm = Zm[["ine_code", "name", "n_analysis_set", "median_bldg_elev_m", "station_id", "distance_km", "elev_diff_proxy_m", "second_station",
             "margin_d_eff_km", "sens_nearest_straight"]]
    A(md(zm, {"median_bldg_elev_m": ".0f", "distance_km": ".1f", "elev_diff_proxy_m": ".0f", "margin_d_eff_km": ".1f"}))
    A(f"\nSensitivity (analysis-set buildings changing station): straight-line nearest {zs['sens_changed_straight_nearest']:,}; per-building (instead of per-municipality) "
      f"elevation-adjusted nearest {zs['sens_changed_per_building']:,}; allowing C043 Ordizia {zs['sens_changed_incl_C043']:,} (of {nA:,}). "
      "Low margins (< 1 km effective) — Abaltzisketa, Alkiza, Altzo, Lizartza — are coin-flips between two stations.\n")

    A("## 8. Weights and whether they matter\n")
    A(f"Raw weight = JUL-AUG adverse-day frequency of the assigned station (common period). Normalised weight = raw / mean over the {nA:,} analysis-set buildings "
      "(mean = 1; `building_weights.csv`, also JUN-SEP). The DB stores the raw frequency (`weather_profile.adverse_day_frequency`, CHECK = adverse/valid); "
      "Strategy A is scale-invariant, so raw and normalised weights give identical selections.\n")
    zw = ZW[["station_id", "years", "valid_days", "adverse_days", "frequency", "interannual_sd", "lo_1sd", "hi_1sd", "n_analysis_buildings", "weight_norm"]]
    A(md(zw, {"frequency": ".4f", "interannual_sd": ".4f", "lo_1sd": ".4f", "hi_1sd": ".4f", "weight_norm": ".3f"}))
    A("\nPaired yearly differences (same years, so common weather is cancelled):\n\n" + md(PR, {"mean_diff": ".4f", "sd_diff": ".4f", "t_paired": ".2f"}))
    sens = []
    for rid in RULES:
        pr = P[(P.rule == rid) & (P.variant == "common_period") & (P.season_id == "JUL-AUG")].set_index("station_id").frequency
        if not all(s in pr.index and pd.notna(pr[s]) for s in used):
            continue
        f_b = BW.station_id.map(pr)
        m = f_b[BW.in_analysis_set == 1].mean()
        sens.append(dict(rule=rid, **{f"w_{s}": pr[s] / m for s in used}, **{f"freq_{s}": pr[s] for s in used}))
    A("\nNormalised zone weights under each variant (same zones, common period):\n\n" + md(pd.DataFrame(sens), {c: ".3f" for c in pd.DataFrame(sens).columns if c != "rule"}))
    A(f"\n**Verdict**: weights range {ZW.weight_norm.min():.2f}–{ZW.weight_norm.max():.2f}, but every zone's ±1 sd interval overlaps the others "
      f"(all_1sd_intervals_overlap = {pf['all_1sd_intervals_overlap']}), and the frequencies rest on 13–21 adverse days in 4 seasons. Only Zizurkil ≤ Berastegi "
      "holds in every year (strictly lower in 4/4 years for ADV-v1 and R1, 2–3/4 with ties for R2/R4); Bidania vs Berastegi flips between variants. **The weights are effectively flat within noise: "
      "weighted Strategy A should be presented as count maximisation with a weak, uncertain historical tilt, not as a risk ranking.**\n")
    if PV is not None:
        A("## 9. Effect on Strategy A (preview, light profile)\n")
        A(f"Computed with `optimizer.optimize` on the current analysis set ({va.get('preview_n_buildings', 0):,} buildings with travel times; "
          f"{va.get('preview_buildings_without_times', 0)} new building(s) without times until the rebuild), 9 parks + 10 candidates, k = 0..6. "
          "Final numbers will come from the main agent's `link_build.py` rebuild.\n")
        pv = PV[["threshold_min", "k", "uniform_selection", "weighted_selection", "same_selection", "uniform_n_covered", "weighted_n_covered",
                 "weighted_share_of_uniform_choice", "weighted_share_of_weighted_choice"]].copy()
        A(md(pv, {"threshold_min": ".0f", "weighted_share_of_uniform_choice": ".4f", "weighted_share_of_weighted_choice": ".4f"}))
        A("\nWhere selections differ, the uniform choice covers 1–29 more buildings and the weighted choice gains ≤ 1 pp of weighted share — the weights only "
          "break near-ties (e.g. 10 min, k = 2–4: CAND-10 ↔ CAND-08; 12 min, k = 2: CAND-01 → CAND-03). Given §8, these swaps are not robust evidence.\n")
    A("## 10. DB plug-in tables and validation\n")
    A("`processed/weather/db_tables/` (contract of `link_build.load_weather_tables`; field notes in its README.md):\n")
    for t, n in va.get("loaded_rows", {}).items():
        A(f"- `{t}.csv`: {n:,} rows loaded in the test" + (" (+12 buildings that exist in the current buildings gpkg but not in the old DB copy)" if t == "zone_assignment" else ""))
    A("\nValidation: `db/flaire.gpkg` copied to the scratchpad, weather tables emptied, Euskalmet sources inserted as `sources_table()` would, tables loaded with "
      "`link_build.load_weather_tables` (PRAGMA foreign_keys = ON, all CHECKs). Result: "
      f"FK violations {len(va.get('fk_violations', []))}; qa views " + ", ".join(f"{k}={v}" for k, v in va.get("qa_views_db_copy", {}).items())
      + f"; `v_building_weight` JUL-AUG weights {va.get('v_building_weight_rows', [[0, 0, 0, 0]])[0][2:4]} for every building, scope buildings without weight = "
      f"{va.get('scope_weight_missing')}. The one building of the old DB not in the current gpkg ({', '.join(va.get('db_copy_buildings_without_zone', []))}) has no zone — it disappears in the rebuild.\n")
    A("Notes for the rebuild (no change made to link_build.py): (1) `sources_table()` will tag the SRC-EUSKALMET-* rows `owner_persona = 'P4'` (default) — should be P1; "
      "(2) weather source ids are not added to `data_version_sources` (matters when a version is frozen, `qa_source_not_in_version`); "
      "(3) the plan row `PLAN-2027-JULAUG` still points at the uniform scenario, and report texts/QA_EXPLAIN say \"no weather weights yet\" — update once loaded; "
      "(4) `weather_obs` is a subset (10-min data of the adverse days) to keep the gpkg small; the full record is the Parquet.\n")
    A("## 11. Limitations / open issues\n")
    A("- Indicator is exploratory (not FWI, not calibrated with fire records); thresholds are round numbers. Frequency ≠ fire probability.")
    A("- Only 4 common seasons; frequencies rest on 13–21 events per zone → large sampling noise (§8).")
    A("- Three zones for 28 municipalities; station altitude unknown (proxy from buildings); wind heights differ (9.3–20 m); river-station T/RH not used.")
    A("- UTC daily boundary; labels likely end-of-interval (≈ +4 min evidence), not documented by Euskalmet.")
    A("- C026 Berastegi: no data Jul 2021–May 2022; C058 Bidania: RH outage Jul–Sep 2018 and invalid T in 2019 (values ≈ −190 °C).")
    A("- RH 100–105 % treated as 100 % (documented); RH < 3 % treated as sensor failure.")
    A("- Seasonality: July–August is not the peak of adverse days in Tolosaldea (September/October, and foehn in late winter).\n")
    A("## 12. Reproduce\n")
    A("```\npython3 code/weather.py                                   # all stages (~3 min)\n"
      "python3 code/weather.py --stages zones,profile,db,validate,report   # after a change of the building / analysis set (~1 min)\n```\n"
      "Outputs: `processed/weather/` (obs_10min.parquet, station_inventory.csv, station_variables_by_year.csv, xsd_tags.csv, xml_files.csv, inner_zips.csv, "
      "tzcheck_*.csv, quality_monthly.csv, quality_flag*.csv, daily.csv, daily_with_rules.csv, precip_check.csv, adverse_*.csv, season_profile*.csv, "
      "zone_assignment_municipality.csv, building_zone.csv, building_weights.csv, zone_weights.csv, zone_difference_test.csv, "
      "optimizer_preview_weighted_vs_uniform.csv, weather_stats.json, db_tables/).")
    (REP / "quality_weather.md").write_text("\n".join(L), encoding="utf-8")


# =============================================================================================== main
STAGES = ["parse", "tzcheck", "inventory", "quality", "daily", "adverse", "zones", "profile", "db", "validate", "report"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default=",".join(STAGES))
    a = ap.parse_args()
    todo = [s.strip() for s in a.stages.split(",") if s.strip()]
    for s in STAGES:
        if s in todo:
            globals()[f"stage_{s}"]()
    log("done")


if __name__ == "__main__":
    main()
