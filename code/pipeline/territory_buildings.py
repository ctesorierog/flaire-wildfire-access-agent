#!/usr/bin/env python3
"""
flAIre · Persona 2 (territory & buildings) + PROVISIONAL Persona 3 vegetation layer.

*** v0.3 (2026-10-01): the OSM limits and the OSM vegetation are SUPERSEDED by the official layers (code/official_layers.py:
geoEuskadi MUNICIPIOS_5000 + Mapa Forestal 2024). This script is kept as the LEGACY v0.2 path and now writes its OSM-based
outputs to *_osm file names, so it can never overwrite the official primary files:
  territory  -> processed/territory/*_osm.*              vegetation -> processed/vegetation/vegetation_osm_provisional.gpkg
  buildings  -> uses TERR_GPKG (default territory_osm.gpkg) and writes *_osm cleaning CSVs
  proximity  -> processed/buildings/*_osm.* (OSM vegetation)
code/official_layers.py imports this module and sets TERR_GPKG = territory.gpkg (official), SUFFIX = "" and its own STATS
to run the SAME building cleaning with the official limits (same rules, same INSPIRE ids). ***

Re-runnable end to end:   python3 code/territory_buildings.py            (legacy v0.2 steps, *_osm outputs)
                          python3 code/territory_buildings.py territory  (one step: territory|buildings|vegetation|proximity|report)

Inputs (raw/, never modified):
  raw/pais-vasco-260930.osm.pbf                     Geofabrik País Vasco extract, ODbL
  raw/GFA_INSPIRE_BU.gpkg (+ _es.csv dictionary)    B5M / DFG INSPIRE Buildings
  raw/persona4_accesos_bomberos/processed/tolosaldea_*_provisional.geojson   IGN via es-atlas (comparison only)
Outputs:
  processed/territory/   tolosaldea_municipalities.geojson, tolosaldea_boundary.geojson (WGS84),
                         municipalities.csv, territory.gpkg (EPSG:25830), territory_comparison_ign.csv, municipality_parts.csv
  processed/buildings/   buildings_tolosaldea.gpkg (layer buildings, EPSG:25830), buildings_analysis_set.csv,
                         quality_by_municipality.csv, duplicates_removed.csv, residential_rule.csv, sensitivity_veg_distance.csv
  processed/vegetation/  vegetation_osm_provisional.gpkg (EPSG:25830)   <- PROVISIONAL, replace by Mapa Forestal (P3)
  reports/quality_territory_buildings.md, reports/sources.csv (rows appended / replaced by source_id)
"""
import sys, json, time, hashlib, re
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely import wkb as swkb
import pyogrio

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
PBF = RAW / "pais-vasco-260930.osm.pbf"
BU_GPKG = RAW / "GFA_INSPIRE_BU.gpkg"
IGN_MUNIS = RAW / "persona4_accesos_bomberos/processed/tolosaldea_munis_provisional.geojson"
IGN_BOUND = RAW / "persona4_accesos_bomberos/processed/tolosaldea_boundary_provisional.geojson"
OUT_T = ROOT / "processed/territory"
OUT_B = ROOT / "processed/buildings"
OUT_V = ROOT / "processed/vegetation"
REPORTS = ROOT / "reports"
STATS = ROOT / "processed/territory_buildings_stats.json"
CRS = 25830
OSM_SFX = "_osm"                           # legacy OSM territory outputs (v0.3: official limits are the primary files)
TERR_GPKG = OUT_T / "territory_osm.gpkg"   # territory used by buildings()/proximity(); official_layers.py sets territory.gpkg
SUFFIX = "_osm"                            # suffix of buildings()/proximity() outputs; official_layers.py sets ""

# 28 Tolosaldea municipalities (AF Tolosa, PTP). INE codes = the authoritative key; names only for cross-check.
PILOT = {
    "20001": "Abaltzisketa", "20002": "Aduna", "20004": "Albiztur", "20005": "Alegia", "20006": "Alkiza",
    "20007": "Altzo", "20008": "Amezketa", "20010": "Anoeta", "20014": "Asteasu", "20904": "Baliarrain",
    "20021": "Belauntza", "20022": "Berastegi", "20023": "Berrobi", "20024": "Bidania-Goiatz", "20031": "Elduain",
    "20907": "Gaztelu", "20041": "Hernialde", "20042": "Ibarra", "20044": "Ikaztegieta", "20046": "Irura",
    "20048": "Larraul", "20050": "Leaburu", "20054": "Lizartza", "20905": "Orendain", "20060": "Orexa",
    "20071": "Tolosa", "20075": "Villabona", "20028": "Zizurkil",
}
SRC_OSM = "SRC-OSM-PV-260930"
SRC_BU = "SRC-B5M-BU"
SRC_IGN = "SRC-IGN-ESATLAS-PROV"

# Residential rule (explicit). CURRENTUSE is a composite string "code pct%; code pct%; ..." (B5M share by use).
# Codes observed in the layer: collectiveResidence, individualResidence, commerceAndServices, agriculture, industrial.
RESIDENTIAL_CODES = ("collectiveResidence", "individualResidence")
VEG_BUFFER_M = 2000        # vegetation clip = boundary + 2 km
VEG_RULE_M = 100           # placeholder threshold (parameters.veg_proximity_m, TEAM TO CONFIRM)
SENS_M = (0, 25, 50, 100, 200)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_stats():
    return json.loads(STATS.read_text()) if STATS.exists() else {}


def save_stats(key, val):
    s = load_stats(); s[key] = val
    STATS.write_text(json.dumps(s, indent=1, default=str, ensure_ascii=False))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_geojson(gdf, path):
    path.unlink(missing_ok=True)
    gdf.to_crs(4326).to_file(path, driver="GeoJSON", engine="pyogrio", layer_options={"COORDINATE_PRECISION": 6})


def write_gpkg(gdf, path, layer):
    gdf.to_file(path, layer=layer, driver="GPKG", engine="pyogrio")   # overwrites the layer


# --------------------------------------------------------------------------------------------- OSM reading
def osm_areas(tag_filters, keep_fn, bbox_lonlat=None):
    """Assemble OSM (multi)polygons with pyosmium's area handler. Returns GeoDataFrame in EPSG:4326."""
    import osmium
    wkbf = osmium.geom.WKBFactory()
    fp = (osmium.FileProcessor(str(PBF))
          .with_areas(osmium.filter.TagFilter(*tag_filters))
          .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA)))
    rows, geoms, fails = [], [], 0
    bb = shapely.box(*bbox_lonlat) if bbox_lonlat is not None else None
    for o in fp:
        rec = keep_fn(o)
        if rec is None:
            continue
        try:
            g = swkb.loads(wkbf.create_multipolygon(o), hex=True)
        except Exception:
            fails += 1
            continue
        if bb is not None and not g.intersects(bb):
            continue
        rec["osm_type"] = "way" if o.from_way() else "relation"
        rec["osm_id"] = o.orig_id()
        rows.append(rec); geoms.append(g)
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=4326), fails


# --------------------------------------------------------------------------------------------- 1 TERRITORY
def territory():
    OUT_T.mkdir(parents=True, exist_ok=True)
    log("territory: reading admin_level=8 boundaries from PBF")

    def keep(o):
        if o.tags.get("admin_level") != "8":
            return None
        t = o.tags
        return dict(name=t.get("name"), name_eu_tag=t.get("name:eu"), name_es_tag=t.get("name:es"),
                    ine_municipio=t.get("ine:municipio"), ref_ine=t.get("ref:ine"))
    adm, fails = osm_areas([("boundary", "administrative")], keep)
    adm = adm.to_crs(CRS)
    n_inv = int((~adm.is_valid).sum())
    adm["geometry"] = adm.geometry.make_valid()
    adm["ine_code"] = adm.ine_municipio.fillna(adm.ref_ine.str[:5])
    gip = adm[adm.ine_code.fillna("").str.match(r"^20\d{3}$")].copy()
    log(f"  admin_level=8 areas: {len(adm)} (assembly failures {fails}); Gipuzkoa 20xxx: {len(gip)}")

    # non-municipal admin_level=8 units inside Gipuzkoa (mancomunidades / parzonerías) - context only
    ctx = adm[adm.ine_code.isna() & adm.name.fillna("").str.contains("Enirio|Partzuergo|partzuergo|Alegiako", regex=True)].copy()

    gip["in_pilot"] = gip.ine_code.isin(PILOT).astype(int)
    gip["name_eu"] = gip.name_eu_tag.fillna(gip.name)
    gip["name_es"] = gip.name_es_tag.fillna(gip.name)
    gip["name_fill_note"] = np.where(gip.name_eu_tag.isna() | gip.name_es_tag.isna(), "name:eu/name:es missing in OSM, filled from name", "")
    gip["ine_tag_consistent"] = (gip.ine_municipio.isna() | gip.ref_ine.isna() | (gip.ref_ine.str[:5] == gip.ine_municipio))
    gip["area_km2"] = gip.area / 1e6
    gip["n_parts"] = gip.geometry.apply(lambda g: len(getattr(g, "geoms", [g])))
    gip["source"] = "OSM Geofabrik pais-vasco-260930 relation/" + gip.osm_id.astype(str)
    gip["source_id"] = SRC_OSM
    gip = gip.sort_values("ine_code")

    found = set(gip.ine_code[gip.in_pilot == 1])
    missing = sorted(set(PILOT) - found)
    dup = gip.ine_code[gip.ine_code.duplicated()].tolist()
    name_check = []
    for _, r in gip[gip.in_pilot == 1].iterrows():
        exp = PILOT[r.ine_code].lower()
        names = " ".join(str(x) for x in (r["name"], r.name_eu_tag, r.name_es_tag)).lower()
        name_check.append(dict(ine_code=r.ine_code, expected=PILOT[r.ine_code], osm_name=r["name"], osm_name_eu=r.name_eu_tag,
                               osm_name_es=r.name_es_tag, name_match=exp.split("-")[0] in names))
    name_check = pd.DataFrame(name_check)
    log(f"  pilot found {len(found)}/28; missing {missing}; duplicated INE {dup}")

    pilot = gip[gip.in_pilot == 1].copy()
    union = shapely.union_all(pilot.geometry.values)
    sum_area = pilot.area.sum(); union_area = union.area
    holes = []
    for poly in getattr(union, "geoms", [union]):
        for ring in poly.interiors:
            h = shapely.Polygon(ring)
            who = ctx[ctx.intersects(h.buffer(-1))].name.tolist() + gip[(gip.in_pilot == 0) & gip.intersects(h.buffer(-1))].name.tolist()
            holes.append(dict(area_km2=round(h.area / 1e6, 4), filled_by=";".join(who) or "?"))
    bnd = gpd.GeoDataFrame(dict(name=["Tolosaldea (28 municipios, AF Tolosa PTP)"], n_municipalities=[len(pilot)],
                                area_km2=[union_area / 1e6], source_id=[SRC_OSM]), geometry=[union], crs=CRS)
    bnd["geometry"] = bnd.geometry.apply(lambda g: g if g.geom_type == "MultiPolygon" else shapely.MultiPolygon([g]))

    # parts per municipality
    parts = []
    for _, r in pilot.iterrows():
        polys = sorted(getattr(r.geometry, "geoms", [r.geometry]), key=lambda p: -p.area)
        for i, p in enumerate(polys):
            parts.append(dict(ine_code=r.ine_code, name=r["name"], part=i + 1, area_km2=round(p.area / 1e6, 5),
                              touches_main=bool(i == 0 or p.distance(polys[0]) < 0.5),
                              rep_lon=None, rep_lat=None, _pt=p.representative_point()))
    parts = pd.DataFrame(parts)
    pts = gpd.GeoSeries(parts.pop("_pt"), crs=CRS).to_crs(4326)
    parts["rep_lon"] = pts.x.round(5); parts["rep_lat"] = pts.y.round(5)
    parts.to_csv(OUT_T / f"municipality_parts{OSM_SFX}.csv", index=False)

    # comparison with IGN provisional (generalised ~200 m)
    ign = gpd.read_file(IGN_MUNIS).to_crs(CRS)
    ign["geometry"] = ign.geometry.make_valid()
    comp = []
    for _, r in pilot.iterrows():
        m = ign[ign.ine == r.ine_code]
        if m.empty:
            comp.append(dict(ine_code=r.ine_code, name=r["name"], ign_found=False)); continue
        gi = m.geometry.iloc[0]; go = r.geometry
        inter = go.intersection(gi).area; uni = go.union(gi).area
        comp.append(dict(ine_code=r.ine_code, name=r["name"], ign_found=True, area_osm_km2=round(go.area / 1e6, 3),
                         area_ign_km2=round(gi.area / 1e6, 3), area_diff_pct=round(100 * (go.area - gi.area) / gi.area, 2),
                         iou=round(inter / uni, 4), hausdorff_m=round(go.hausdorff_distance(gi), 0),
                         parts_osm=r.n_parts, parts_ign=len(getattr(gi, "geoms", [gi]))))
    comp = pd.DataFrame(comp)
    ib = gpd.read_file(IGN_BOUND).to_crs(CRS).geometry.make_valid().iloc[0]
    comp_union = dict(area_osm_km2=round(union_area / 1e6, 3), area_ign_km2=round(ib.area / 1e6, 3),
                      area_diff_pct=round(100 * (union_area - ib.area) / ib.area, 2),
                      iou=round(union.intersection(ib).area / union.union(ib).area, 4),
                      hausdorff_m=round(union.hausdorff_distance(ib), 0))
    comp.to_csv(OUT_T / "territory_comparison_ign.csv", index=False)

    # outputs
    cols = ["ine_code", "name", "name_eu", "name_es", "in_pilot", "area_km2", "n_parts", "osm_type", "osm_id", "source", "source_id", "geometry"]
    gip["geometry"] = gip.geometry.apply(lambda g: g if g.geom_type == "MultiPolygon" else shapely.MultiPolygon([g]))
    pilot = gip[gip.in_pilot == 1][cols].reset_index(drop=True)
    tp = OUT_T / f"territory{OSM_SFX}.gpkg"; tp.unlink(missing_ok=True)
    write_gpkg(pilot, tp, "tolosaldea_municipalities")
    write_gpkg(bnd, tp, "tolosaldea_boundary")
    write_gpkg(gip[cols].reset_index(drop=True), tp, "municipalities_gipuzkoa")  # schema `municipalities` (all Gipuzkoa, in_pilot)
    ctx_out = ctx.copy(); ctx_out["area_km2"] = ctx_out.area / 1e6; ctx_out["note"] = "non-municipal admin_level=8 unit (context, NOT in pilot)"
    write_gpkg(ctx_out[["name", "osm_type", "osm_id", "area_km2", "note", "geometry"]].reset_index(drop=True), tp, "context_non_municipal")
    write_geojson(pilot, OUT_T / f"tolosaldea_municipalities{OSM_SFX}.geojson")
    write_geojson(bnd, OUT_T / f"tolosaldea_boundary{OSM_SFX}.geojson")
    csv = pilot[["ine_code", "name_eu", "name_es", "area_km2", "n_parts", "osm_id", "source"]].copy()
    csv["area_km2"] = csv.area_km2.round(3)
    csv.to_csv(OUT_T / f"municipalities{OSM_SFX}.csv", index=False)

    save_stats("territory", dict(
        n_admin8=len(adm), assembly_failures=fails, invalid_before_fix=n_inv, n_gipuzkoa=len(gip), pilot_found=len(found),
        missing=missing, duplicated_ine=dup, ine_tag_inconsistent=gip.loc[~gip.ine_tag_consistent, "ine_code"].tolist(),
        names_filled=gip.loc[gip.name_fill_note != "", ["ine_code", "name"]].values.tolist(),
        name_mismatch=name_check.loc[~name_check.name_match].to_dict("records"),
        sum_area_km2=round(sum_area / 1e6, 4), union_area_km2=round(union_area / 1e6, 4),
        overlap_km2=round((sum_area - union_area) / 1e6, 5), union_parts=len(getattr(union, "geoms", [union])),
        union_holes=holes, ign_union=comp_union,
        ign_area_diff_abs_max=float(comp.area_diff_pct.abs().max()), ign_hausdorff_max=float(comp.hausdorff_m.max()),
        ign_hausdorff_median=float(comp.hausdorff_m.median()), ign_iou_min=float(comp.iou.min()),
        multipart=parts.groupby(["ine_code", "name"]).size().loc[lambda s: s > 1].reset_index().values.tolist(),
        context_units=ctx_out[["name", "osm_id", "area_km2"]].round(3).values.tolist(),
        bbox_lonlat=list(bnd.to_crs(4326).total_bounds)))
    log("territory done", comp_union)


# --------------------------------------------------------------------------------------------- 2 BUILDINGS
def parse_use(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return {}
    out = {}
    for tok in str(s).split(";"):
        m = re.match(r"\s*([A-Za-z]+)\s+(\d+(?:\.\d+)?)%", tok)
        if m:
            out[m.group(1)] = out.get(m.group(1), 0) + float(m.group(2))
    return out


def buildings():
    OUT_B.mkdir(parents=True, exist_ok=True)
    tp = TERR_GPKG
    munis = gpd.read_file(tp, layer="municipalities_gipuzkoa")
    bnd = gpd.read_file(tp, layer="tolosaldea_boundary").geometry.iloc[0]
    log("buildings: reading INSPIRE layer")
    info = pyogrio.read_info(BU_GPKG)
    bu = gpd.read_file(BU_GPKG, engine="pyogrio")
    st = dict(n_raw=len(bu), layers=[list(x) for x in pyogrio.list_layers(BU_GPKG)], geom_types=bu.geom_type.value_counts().to_dict(),
              layer_last_update=info["layer_metadata"].get("DBF_DATE_LAST_UPDATE"), crs=str(bu.crs))

    # ---- whole-province attribute profile (raw rows)
    use_tok = bu.CURRENTUSE.dropna().str.split(";").explode().str.strip().str.replace(r"\s*\d+(\.\d+)?%", "", regex=True)
    st["currentuse_null_raw"] = int(bu.CURRENTUSE.isna().sum())
    st["currentuse_distinct_strings_raw"] = int(bu.CURRENTUSE.nunique())
    st["currentuse_codes_raw"] = use_tok.value_counts().to_dict()
    st["currentuse_top_strings_raw"] = bu.CURRENTUSE.value_counts(dropna=False).head(15).to_dict()
    st["dwellings_raw"] = dict(null=int(bu.DWELLINGS.isna().sum()), zero=int((bu.DWELLINGS == 0).sum()),
                               pos=int((bu.DWELLINGS > 0).sum()), max=float(bu.DWELLINGS.max()))
    st["null_use_cadastral_link"] = dict(
        null_use_rows=int(bu.CURRENTUSE.isna().sum()),
        null_use_with_b5m_only_url=int(bu.loc[bu.CURRENTUSE.isna(), "URL_CADAST"].str.contains("b5m.gipuzkoa.eus/map", na=False).sum()),
        null_use_with_dwellings_0=int((bu.CURRENTUSE.isna() & (bu.DWELLINGS == 0)).sum()),
        null_use_with_dwellings_pos=int((bu.CURRENTUSE.isna() & (bu.DWELLINGS > 0)).sum()))
    st["id"] = dict(inspireid_null=int(bu.INSPIREID.isna().sum()), inspireid_unique_values=int(bu.INSPIREID.nunique()),
                    rows_with_repeated_inspireid=int(bu.INSPIREID.duplicated(keep=False).sum()),
                    ids_repeated=int(bu.INSPIREID[bu.INSPIREID.duplicated()].nunique()),
                    inspireid_eq_prefix_localid=bool((bu.INSPIREID == "ES.GFA.BU." + bu.LOCALID.astype(str)).all()),
                    localid_unique_values=int(bu.LOCALID.nunique()))
    st["buildingpart_check"] = dict(
        layers_in_file=[l[0] for l in pyogrio.list_layers(BU_GPKG)],
        inspireid_prefixes=bu.INSPIREID.str.extract(r"^(ES\.GFA\.[A-Z]+)\.")[0].value_counts().to_dict())

    # ---- step A: collapse repeated INSPIREID rows (export fan-out: one row per BUILDING_N / cadastral ref)
    bu = bu.sort_values(["LOCALID"]).reset_index(drop=True)
    multi_cols = ["BUILDING_N", "URL_CADAST", "URL_PARCEL", "ENDCONSTRU"]
    rep = bu[bu.INSPIREID.duplicated(keep=False)].copy()
    rep["_wkb"] = shapely.to_wkb(shapely.normalize(rep.geometry.values))
    other = [c for c in bu.columns if c not in multi_cols + ["geometry"]]
    chk = rep.groupby("INSPIREID").agg(n_rows=("LOCALID", "size"), n_geom=("_wkb", "nunique"),
                                       **{f"n_{c}": (c, "nunique") for c in other if c not in ("INSPIREID",)})
    differing_core = [c for c in other if c != "INSPIREID" and (chk[f"n_{c}"] > 1).any()]
    agg = rep.groupby("INSPIREID").agg(
        building_name=("BUILDING_N", lambda s: " | ".join(sorted(set(s.dropna())))),
        url_cadast_all=("URL_CADAST", lambda s: " | ".join(sorted(set(s.dropna())))),
        endconstru_min=("ENDCONSTRU", "min"), endconstru_max=("ENDCONSTRU", "max"),
        n_source_rows=("LOCALID", "size"))
    st["repeated_id"] = dict(ids=len(chk), rows=int(chk.n_rows.sum()), rows_dropped=int(chk.n_rows.sum() - len(chk)),
                             all_same_geometry=bool((chk.n_geom == 1).all()), core_columns_differing=differing_core,
                             endconstru_differs=int((agg.endconstru_min != agg.endconstru_max).sum()))
    dropped_rep = rep[rep.INSPIREID.duplicated(keep="first")][["INSPIREID", "LOCALID", "BUILDING_N", "URL_CADAST"]].copy()
    dropped_rep["rule"] = "R-DUP-ID: repeated INSPIREID row (identical geometry & core attributes); kept first row, BUILDING_N/URL_CADAST aggregated"
    bu = bu.drop_duplicates("INSPIREID", keep="first").reset_index(drop=True)
    bu["building_name"] = bu.BUILDING_N
    bu["n_source_rows"] = 1
    m = bu.INSPIREID.isin(agg.index)
    bu.loc[m, "building_name"] = bu.loc[m, "INSPIREID"].map(agg.building_name).replace("", None)
    bu.loc[m, "n_source_rows"] = bu.loc[m, "INSPIREID"].map(agg.n_source_rows)
    # ENDCONSTRU: when copies differ, keep the latest (completion of the last construction phase) and flag
    bu["endconstru_multi"] = False
    bu.loc[m, "ENDCONSTRU"] = bu.loc[m, "INSPIREID"].map(agg.endconstru_max)
    bu.loc[m, "endconstru_multi"] = bu.loc[m, "INSPIREID"].map(agg.endconstru_min != agg.endconstru_max).fillna(False)

    # ---- buildings in non-municipal context units (Enirio-Aralar etc.): counted over the whole unit, then excluded
    ctx = gpd.read_file(tp, layer="context_non_municipal")
    ctx_near = ctx[ctx.intersects(bnd.buffer(5))]
    cb = bu[bu.intersects(shapely.box(*ctx_near.total_bounds))] if len(ctx_near) else bu.iloc[:0]
    cj = gpd.sjoin(gpd.GeoDataFrame(cb[["CURRENTUSE", "DWELLINGS"]], geometry=cb.representative_point(), crs=CRS),
                   ctx_near[["name", "geometry"]], predicate="within")
    st["context_units_adjacent"] = {n: dict(n_buildings=int(len(g)), n_with_use=int(g.CURRENTUSE.notna().sum()),
                                            dwellings_sum=float(g.DWELLINGS.sum())) for n, g in cj.groupby("name")}

    # ---- restrict to study area early (memory): bbox of boundary + 1 km
    bu = bu[bu.intersects(shapely.box(*bnd.buffer(1000).bounds))].reset_index(drop=True)

    # ---- geometry validity
    inv = ~bu.is_valid
    st["invalid_in_bbox"] = int(inv.sum())
    bu["geom_fixed"] = inv.values
    if inv.any():
        fixed = shapely.make_valid(bu.geometry[inv].values)
        fixed = [shapely.union_all([g for g in getattr(x, "geoms", [x]) if g.geom_type in ("Polygon", "MultiPolygon")]) for x in fixed]
        bu.loc[inv, "geometry"] = fixed
    bu["geometry"] = bu.geometry.apply(lambda g: g if g.geom_type == "MultiPolygon" else shapely.MultiPolygon([g]))
    st["still_invalid"] = int((~bu.is_valid).sum())
    st["empty_after_fix"] = int(bu.is_empty.sum())

    # ---- representative point and municipality assignment (one only)
    rp = bu.geometry.representative_point()
    pts = gpd.GeoDataFrame({"i": np.arange(len(bu))}, geometry=rp.values, crs=CRS)
    j = gpd.sjoin(pts, munis[["ine_code", "name", "in_pilot", "geometry"]], how="left", predicate="within")
    multi = j.i.duplicated(keep=False)
    st["rep_point_in_several_munis"] = int(j.i[multi].nunique())
    j = j.sort_values(["i", "ine_code"]).drop_duplicates("i")   # if ever >1 (shared edge), lowest INE wins
    bu["muni_ine"] = j.ine_code.values; bu["muni_name"] = j["name"].values; bu["in_pilot"] = j.in_pilot.fillna(0).astype(int).values
    bu["rep_x"] = rp.x.values; bu["rep_y"] = rp.y.values
    tol = bu[bu.in_pilot == 1].copy()
    # buildings whose footprint touches the boundary but rep point is outside (excluded by rule) - report
    edge = bu[(bu.in_pilot != 1) & bu.intersects(bnd)]
    st["excluded_border_buildings"] = dict(n=len(edge), muni_of_rep_point=edge.muni_name.fillna("outside Gipuzkoa municipalities / context unit").value_counts().to_dict())
    in_ctx = gpd.sjoin(pts[bu.muni_ine.isna().values], ctx[["name", "geometry"]], predicate="within")
    st["bbox_buildings_in_context_units"] = in_ctx["name"].value_counts().to_dict()
    st["bbox_buildings_no_municipality"] = int(bu.muni_ine.isna().sum())
    del bu, pts, j, rp

    # ---- duplicates by identical geometry, different IDs (within Tolosaldea)
    tol = tol.sort_values("LOCALID").reset_index(drop=True)
    tol["_wkb"] = shapely.to_wkb(shapely.normalize(tol.geometry.values))
    dg = tol[tol._wkb.duplicated(keep=False)]
    dropped_geom = tol[tol._wkb.duplicated(keep="first")].copy()
    keeper = tol.drop_duplicates("_wkb").set_index("_wkb").INSPIREID
    dropped_geom["kept_building_id"] = dropped_geom._wkb.map(keeper)
    dropped_geom["rule"] = "R-DUP-GEOM: identical normalised footprint to another INSPIREID; kept lowest LOCALID"
    st["dup_geom_tolosaldea"] = dict(groups=int(dg._wkb.nunique()), rows=len(dg), dropped=len(dropped_geom),
                                     dropped_with_use=int(dropped_geom.CURRENTUSE.notna().sum()),
                                     dropped_with_dwellings=int(dropped_geom.DWELLINGS.notna().sum()))
    tol = tol.drop_duplicates("_wkb").drop(columns="_wkb").reset_index(drop=True)
    dr = pd.concat([
        dropped_rep[dropped_rep.INSPIREID.isin(tol.INSPIREID)].rename(columns={"INSPIREID": "building_id", "LOCALID": "localid"}).assign(kept_building_id=lambda d: d.building_id),
        dropped_geom.rename(columns={"INSPIREID": "building_id", "LOCALID": "localid"})[["building_id", "localid", "kept_building_id", "rule", "muni_ine"]],
    ], ignore_index=True)
    dr["muni_ine"] = dr.muni_ine.fillna(dr.kept_building_id.map(tol.set_index("INSPIREID").muni_ine))
    dr[["building_id", "localid", "kept_building_id", "muni_ine", "rule"]].to_csv(OUT_B / f"duplicates_removed{SUFFIX}.csv", index=False)

    # ---- possible BuildingPart / overlapping footprints inside Tolosaldea
    tree = shapely.STRtree(tol.geometry.values)
    a_idx, b_idx = tree.query(tol.geometry.values, predicate="intersects")
    keep = a_idx < b_idx
    a_idx, b_idx = a_idx[keep], b_idx[keep]
    ga, gb = tol.geometry.values[a_idx], tol.geometry.values[b_idx]
    ia = shapely.area(shapely.intersection(ga, gb))
    small = np.minimum(shapely.area(ga), shapely.area(gb))
    frac = ia / small
    st["overlap_pairs"] = dict(touching_or_intersecting_pairs=int(len(a_idx)), overlap_gt_1m2=int((ia > 1).sum()),
                               overlap_gt_50pct_of_smaller=int((frac > 0.5).sum()), contained_gt_99pct=int((frac > 0.99).sum()))
    ov = pd.DataFrame(dict(a=tol.INSPIREID.values[a_idx], b=tol.INSPIREID.values[b_idx], inter_m2=ia.round(2), frac_smaller=frac.round(3)))
    ov[ov.frac_smaller > 0.5].to_csv(OUT_B / f"overlapping_footprints_gt50pct{SUFFIX}.csv", index=False)
    del tree, ga, gb

    # ---- fields
    uses = tol.CURRENTUSE.map(parse_use)
    tol["use_codes"] = uses.map(lambda d: ";".join(sorted(d)) if d else None)
    tol["residential_share_pct"] = uses.map(lambda d: sum(v for k, v in d.items() if k in RESIDENTIAL_CODES) if d else np.nan)
    tol["dominant_use"] = uses.map(lambda d: max(d, key=d.get) if d else None)
    has_use = tol.CURRENTUSE.notna()
    is_res = uses.map(lambda d: any(k in RESIDENTIAL_CODES for k in d))
    tol["residential_flag"] = np.where(~has_use, "unknown", np.where(is_res, "residential", "non_residential"))
    tol["is_residential"] = (tol.residential_flag == "residential").astype(int)
    tol["residential_rule"] = np.where(tol.is_residential == 1, "use", "none")
    # informational only (does NOT change residential_flag): unknown-use building whose B5M name says house/farmhouse
    tol["unknown_named_house"] = (tol.residential_flag == "unknown") & tol.building_name.fillna("").str.contains(
        r"baserri|caser[ií]o|\betxea\b|\bcasa\b", case=False, regex=True)
    out = gpd.GeoDataFrame(dict(
        building_id=tol.INSPIREID, localid=tol.LOCALID.astype("int64"), current_use=tol.CURRENTUSE, use_codes=tol.use_codes,
        dominant_use=tol.dominant_use, residential_share_pct=tol.residential_share_pct,
        dwellings=tol.DWELLINGS.astype("Int64"),              # NULL = unknown (never 0); genuine 0 kept
        residential_flag=tol.residential_flag, is_residential=tol.is_residential, residential_rule=tol.residential_rule,
        muni_ine=tol.muni_ine, muni_name=tol.muni_name,
        end_construction=pd.to_datetime(tol.ENDCONSTRU).dt.strftime("%Y-%m-%d"),
        year_built=pd.to_datetime(tol.ENDCONSTRU).dt.year.astype("Int64"), endconstru_multi=tol.endconstru_multi,
        elevation=tol.ELEVATION, floors_above=tol.FLOORABOGR.astype("Int64"), height_above=tol.HEIGHTABOG,
        building_name=tol.building_name, address_eu=tol.DIRPOS_E, address_es=tol.DIRPOS_C, url_b5m=tol.URL_B5M,
        has_cadastral_link=~tol.URL_CADAST.fillna("").str.contains("b5m.gipuzkoa.eus/map"),
        unknown_named_house=tol.unknown_named_house,
        n_source_rows=tol.n_source_rows.astype(int), geom_fixed=tol.geom_fixed,
        footprint_m2=tol.area.round(2), rep_x=tol.rep_x.round(2), rep_y=tol.rep_y.round(2), source_id=SRC_BU,
    ), geometry=tol.geometry.values, crs=CRS)
    ll = gpd.GeoSeries(gpd.points_from_xy(out.rep_x, out.rep_y), crs=CRS).to_crs(4326)
    out["lon"] = ll.x.round(6).values; out["lat"] = ll.y.round(6).values
    st["tolosaldea_buildings"] = len(out)
    st["lonlat_range"] = [float(out.lon.min()), float(out.lon.max()), float(out.lat.min()), float(out.lat.max())]
    st["use_tol"] = out.residential_flag.value_counts().to_dict()
    st["dominant_use_tol"] = out.dominant_use.value_counts(dropna=False).to_dict()
    st["res_share_ge50"] = int(((out.residential_share_pct >= 50) & (out.is_residential == 1)).sum())
    st["anomalies"] = dict(
        nonres_with_dwellings_pos=int(((out.residential_flag == "non_residential") & (out.dwellings > 0)).sum()),
        res_with_dwellings_0=int(((out.residential_flag == "residential") & (out.dwellings == 0)).sum()),
        res_with_dwellings_null=int(((out.residential_flag == "residential") & out.dwellings.isna()).sum()),
        unknown_with_dwellings_pos=int(((out.residential_flag == "unknown") & (out.dwellings > 0)).sum()),
        unknown_with_dwellings_0=int(((out.residential_flag == "unknown") & (out.dwellings == 0)).sum()),
        unknown_with_cadastral_link=int(((out.residential_flag == "unknown") & out.has_cadastral_link).sum()),
        unknown_named_house=int(out.unknown_named_house.sum()),
        unknown_footprint_median_m2=float(out.loc[out.residential_flag == "unknown", "footprint_m2"].median()),
        unknown_height0=int(((out.residential_flag == "unknown") & (out.height_above == 0)).sum()),
        elevation_null=int(out.elevation.isna().sum()), elevation_le0=int((out.elevation <= 0).sum()),
        year_built_null=int(out.year_built.isna().sum()), year_built_min=int(out.year_built.min()),
        footprint_lt_5m2=int((out.footprint_m2 < 5).sum()), footprint_gt_10000m2=int((out.footprint_m2 > 10000).sum()))
    # residential rule table
    rr = (out.assign(use_codes=out.use_codes.fillna("(null)")).groupby(["residential_flag"]).agg(
        n=("building_id", "size"), dwellings_sum=("dwellings", "sum"), n_dw_null=("dwellings", lambda s: int(s.isna().sum()))).reset_index())
    rr["rule"] = rr.residential_flag.map({
        "residential": f"CURRENTUSE contains code {' or '.join(RESIDENTIAL_CODES)} at any share (>0%)",
        "non_residential": "CURRENTUSE present and contains only commerceAndServices / agriculture / industrial",
        "unknown": "CURRENTUSE NULL (B5M cartographic building without cadastral use)"})
    rr.to_csv(OUT_B / f"residential_rule{SUFFIX}.csv", index=False)
    out.to_parquet(OUT_B / f"_buildings_stage{SUFFIX}.parquet")   # intermediate for the proximity step
    save_stats("buildings", st)
    log("buildings done:", len(out), st["use_tol"])


# --------------------------------------------------------------------------------------------- 3 VEGETATION (PROVISIONAL)
VEG_CLASSES = {  # (key, value) -> veg_class
    ("landuse", "forest"): "forest", ("natural", "wood"): "forest",
    ("natural", "scrub"): "scrub_heath", ("natural", "heath"): "scrub_heath",
    ("landuse", "meadow"): "grassland", ("natural", "grassland"): "grassland",
}
FUEL = {"forest", "scrub_heath"}


def vegetation():
    OUT_V.mkdir(parents=True, exist_ok=True)
    tp = OUT_T / f"territory{OSM_SFX}.gpkg"     # provisional layer stays tied to the OSM limits it was built with
    bnd = gpd.read_file(tp, layer="tolosaldea_boundary").geometry.iloc[0]
    clip = bnd.buffer(VEG_BUFFER_M)
    bb = gpd.GeoSeries([clip.envelope], crs=CRS).to_crs(4326).total_bounds
    bb = (bb[0] - 0.01, bb[1] - 0.01, bb[2] + 0.01, bb[3] + 0.01)
    log("vegetation: reading OSM areas (PROVISIONAL)")

    def keep(o):
        t = o.tags
        lu, na = t.get("landuse"), t.get("natural")
        cls = VEG_CLASSES.get(("landuse", lu)) or VEG_CLASSES.get(("natural", na))
        # if both present and conflicting, fuel wins (e.g. landuse=meadow + natural=scrub)
        c2 = VEG_CLASSES.get(("natural", na))
        if c2 in FUEL: cls = c2
        c1 = VEG_CLASSES.get(("landuse", lu))
        if c1 in FUEL and cls not in FUEL: cls = c1
        if cls is None:
            return None
        return dict(veg_class=cls, landuse=lu, natural=na, leaf_type=t.get("leaf_type"), leaf_cycle=t.get("leaf_cycle"),
                    wood=t.get("wood"), name=t.get("name"))
    veg, fails = osm_areas([("landuse", "forest"), ("natural", "wood"), ("natural", "scrub"), ("natural", "heath"),
                            ("landuse", "meadow"), ("natural", "grassland")], keep, bbox_lonlat=bb)
    veg = veg.to_crs(CRS)
    n_in = len(veg)
    inv = ~veg.is_valid
    veg.loc[inv, "geometry"] = shapely.make_valid(veg.geometry[inv].values)
    veg = veg[veg.intersects(clip)].copy()
    within = veg.within(clip)
    veg["clipped"] = ~within
    veg.loc[~within, "geometry"] = shapely.intersection(veg.geometry[~within].values, clip)
    veg["geometry"] = veg.geometry.apply(lambda g: shapely.union_all([p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")]))
    veg = veg[~veg.is_empty].copy()
    veg["geometry"] = veg.geometry.apply(lambda g: g if g.geom_type == "MultiPolygon" else shapely.MultiPolygon([g]))
    veg["is_fuel"] = veg.veg_class.isin(FUEL).astype(int)
    veg["area_ha"] = (veg.area / 1e4).round(3)
    veg["in_tolosaldea"] = veg.intersects(bnd)
    veg["status"] = "PROVISIONAL - OSM, replace by Mapa Forestal del País Vasco (P3)"
    veg["source_id"] = SRC_OSM
    cols = ["osm_type", "osm_id", "veg_class", "is_fuel", "landuse", "natural", "leaf_type", "leaf_cycle", "wood", "name",
            "clipped", "in_tolosaldea", "area_ha", "status", "source_id", "geometry"]
    veg = veg[cols].reset_index(drop=True)
    vp = OUT_V / "vegetation_osm_provisional.gpkg"; vp.unlink(missing_ok=True)
    write_gpkg(veg, vp, "vegetation_osm_provisional")
    clip_g = gpd.GeoDataFrame(dict(name=["Tolosaldea boundary + 2 km (vegetation clip extent)"], buffer_m=[VEG_BUFFER_M]), geometry=[clip], crs=CRS)
    write_gpkg(clip_g, vp, "clip_extent")

    # coverage of the PBF extract: which part of the clip extent lies outside the CAV (Navarra) and how much veg OSM has there
    adm = gpd.read_file(tp, layer="municipalities_gipuzkoa")
    gip_union = shapely.union_all(adm.geometry.values)
    outside_gip = clip.difference(gip_union)
    fuel_u = shapely.union_all(veg.geometry[veg.is_fuel == 1].values)
    # tag-level summary
    by = veg.groupby(["veg_class", "landuse", "natural"], dropna=False).agg(n=("osm_id", "size"), area_ha=("area_ha", "sum")).reset_index()
    by.to_csv(OUT_V / "vegetation_tag_summary.csv", index=False)
    inside = gpd.GeoSeries([bnd], crs=CRS)
    st = dict(n_areas_bbox=n_in, assembly_failures=fails, invalid_fixed=int(inv.sum()), n_kept=len(veg),
              by_class=veg.groupby("veg_class").agg(n=("osm_id", "size"), area_ha=("area_ha", "sum")).round(1).reset_index().values.tolist(),
              fuel_union_area_ha=round(fuel_u.area / 1e4, 1),
              fuel_union_share_of_tolosaldea_pct=round(100 * fuel_u.intersection(bnd).area / bnd.area, 1),
              fuel_share_in_clip_outside_gipuzkoa_pct=round(100 * fuel_u.intersection(outside_gip).area / max(outside_gip.area, 1), 1),
              fuel_share_in_clip_inside_gipuzkoa_pct=round(100 * fuel_u.intersection(clip.intersection(gip_union)).area / clip.intersection(gip_union).area, 1),
              clip_area_outside_gipuzkoa_km2=round(outside_gip.area / 1e6, 1),
              leaf_type=veg[veg.veg_class == "forest"].leaf_type.value_counts(dropna=False).to_dict(),
              tag_summary=by.round(1).values.tolist())
    save_stats("vegetation", st)
    log("vegetation done", st["by_class"])


# --------------------------------------------------------------------------------------------- 4 PROXIMITY
def proximity():
    """LEGACY (OSM vegetation). Superseded by official_layers.proximity (Mapa Forestal 2024); writes *{SUFFIX} files."""
    tp = TERR_GPKG
    b = gpd.read_parquet(OUT_B / f"_buildings_stage{SUFFIX}.parquet")
    veg = gpd.read_file(OUT_V / "vegetation_osm_provisional.gpkg", layer="vegetation_osm_provisional", where="is_fuel = 1")
    log(f"proximity: {len(b)} buildings vs {len(veg)} fuel polygons")
    # split fuel polygons on a 1 km grid -> small bboxes, fast exact nearest; distance unchanged (same union)
    parts = veg.geometry.explode(index_parts=False).values
    minx, miny, maxx, maxy = shapely.total_bounds(parts)
    xs = np.arange(np.floor(minx / 1000) * 1000, maxx + 1000, 1000); ys = np.arange(np.floor(miny / 1000) * 1000, maxy + 1000, 1000)
    cells = shapely.box(*np.meshgrid(xs[:-1], ys[:-1]), *np.meshgrid(xs[1:], ys[1:]))
    cells = cells.ravel()
    ct = shapely.STRtree(cells)
    pi, ci = ct.query(parts, predicate="intersects")
    pieces = shapely.intersection(parts[pi], cells[ci])
    pieces = pieces[~shapely.is_empty(pieces)]
    log(f"  fuel parts {len(parts)} -> grid pieces {len(pieces)}")
    tree = shapely.STRtree(pieces)
    (bi, _), dist = tree.query_nearest(b.geometry.values, return_distance=True, all_matches=False)
    d = np.full(len(b), np.nan); d[bi] = dist
    b["dist_veg_m"] = np.round(d, 2)
    b["near_veg_100"] = b.dist_veg_m <= VEG_RULE_M
    b["veg_rule_m"] = float(VEG_RULE_M)
    b["veg_source"] = "PROVISIONAL OSM forest+scrub_heath (" + SRC_OSM + ")"
    # distance from building rep point to the Navarra border (outside CAV) - extract has no/partial Navarra vegetation
    adm = gpd.read_file(tp, layer="municipalities_gipuzkoa")
    gip_line = shapely.union_all(adm.geometry.values).boundary
    bnd = gpd.read_file(tp, layer="tolosaldea_boundary").geometry.iloc[0]
    b["dist_gipuzkoa_edge_m"] = np.round(shapely.distance(b.geometry.values, gip_line), 1)

    res = b[b.residential_flag == "residential"]
    sens = []
    for t in SENS_M:
        s = res[res.dist_veg_m <= t]
        sens.append(dict(threshold_m=t, residential_buildings=len(s), share_of_residential_pct=round(100 * len(s) / len(res), 1),
                         dwellings_sum=int(s.dwellings.sum()), n_dwellings_null=int(s.dwellings.isna().sum()),
                         all_buildings=int((b.dist_veg_m <= t).sum())))
    sens = pd.DataFrame(sens)
    sens.to_csv(OUT_B / f"sensitivity_veg_distance{SUFFIX}.csv", index=False)

    # final building layer
    cols = ["building_id", "localid", "current_use", "use_codes", "dominant_use", "residential_share_pct", "dwellings",
            "residential_flag", "is_residential", "residential_rule", "muni_ine", "muni_name", "end_construction", "year_built",
            "endconstru_multi", "elevation", "floors_above", "height_above", "building_name", "address_eu", "address_es", "url_b5m",
            "has_cadastral_link", "unknown_named_house", "n_source_rows", "geom_fixed", "footprint_m2", "rep_x", "rep_y", "lon", "lat",
            "dist_veg_m", "near_veg_100", "veg_rule_m", "veg_source", "dist_gipuzkoa_edge_m", "source_id", "geometry"]
    b = b[cols]
    bp = OUT_B / f"buildings_tolosaldea{SUFFIX}.gpkg"; bp.unlink(missing_ok=True)
    write_gpkg(b, bp, "buildings")
    # rep-point layer matching schema `buildings` (POINT geometry)
    pts = b.drop(columns="geometry").rename(columns={"rep_x": "x", "rep_y": "y", "muni_ine": "municipality_code",
                                                     "current_use": "source_use", "dist_veg_m": "veg_distance_m"})
    pts["near_vegetation"] = pts.near_veg_100.astype(int)
    pts = gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts.x, pts.y), crs=CRS)
    write_gpkg(pts, bp, "buildings_rep_points")

    a = b[(b.residential_flag == "residential") & (b.dist_veg_m <= VEG_RULE_M)]
    a[["building_id", "muni_ine", "residential_flag", "dwellings", "dist_veg_m", "lon", "lat"]].assign(
        x=a.rep_x, y=a.rep_y).to_csv(OUT_B / f"buildings_analysis_set{SUFFIX}.csv", index=False)

    # quality per municipality
    dup = pd.read_csv(OUT_B / f"duplicates_removed{SUFFIX}.csv", dtype={"muni_ine": str})
    munis = pd.read_csv(OUT_T / f"municipalities{SUFFIX}.csv", dtype={"ine_code": str})
    g = b.groupby("muni_ine")
    q = pd.DataFrame(dict(
        n_buildings=g.size(), n_residential=g.is_residential.sum(),
        n_non_residential=g.residential_flag.apply(lambda s: (s == "non_residential").sum()),
        n_unknown_use=g.residential_flag.apply(lambda s: (s == "unknown").sum()),
        n_with_dwellings=g.dwellings.apply(lambda s: s.notna().sum()),
        n_dwellings_pos=g.dwellings.apply(lambda s: (s > 0).sum()),
        sum_dwellings=g.dwellings.sum(), invalid_geoms_fixed=g.geom_fixed.sum(),
        n_res_dist_le100=g.apply(lambda x: ((x.residential_flag == "residential") & (x.dist_veg_m <= 100)).sum()),
        dwellings_analysis_set=g.apply(lambda x: x.loc[(x.residential_flag == "residential") & (x.dist_veg_m <= 100), "dwellings"].sum()),
        n_unknown_named_house_le100=g.apply(lambda x: (x.unknown_named_house & (x.dist_veg_m <= 100)).sum()),
        n_res_within_500m_of_gipuzkoa_edge=g.apply(lambda x: ((x.residential_flag == "residential") & (x.dist_gipuzkoa_edge_m <= 500)).sum()),
    )).reset_index()
    q["dup_rows_removed_same_id"] = q.muni_ine.map(dup[dup.rule.str.startswith("R-DUP-ID")].groupby("muni_ine").size()).fillna(0).astype(int)
    q["dup_removed_same_geom"] = q.muni_ine.map(dup[dup.rule.str.startswith("R-DUP-GEOM")].groupby("muni_ine").size()).fillna(0).astype(int)
    q = munis[["ine_code", "name_eu"]].merge(q, left_on="ine_code", right_on="muni_ine", how="left").drop(columns="muni_ine")
    tot = q.drop(columns=["ine_code", "name_eu"]).sum(); tot["ine_code"] = "TOTAL"; tot["name_eu"] = "Tolosaldea"
    q = pd.concat([q, tot.to_frame().T], ignore_index=True)
    q.to_csv(OUT_B / f"quality_by_municipality{SUFFIX}.csv", index=False)
    st = dict(n=len(b), dist_null=int(b.dist_veg_m.isna().sum()), inside_fuel=int((b.dist_veg_m == 0).sum()),
              analysis_set=len(a), analysis_dwellings=int(a.dwellings.sum()), analysis_dw_null=int(a.dwellings.isna().sum()),
              sensitivity=sens.to_dict("records"),
              unknown_named_house_le100=int((b.unknown_named_house & (b.dist_veg_m <= 100)).sum()),
              unknown_le100=int(((b.residential_flag == "unknown") & (b.dist_veg_m <= 100)).sum()),
              res_within_500m_gip_edge=int(((b.residential_flag == "residential") & (b.dist_gipuzkoa_edge_m <= 500)).sum()),
              res_within_500m_gip_edge_far_from_veg=int(((b.residential_flag == "residential") & (b.dist_gipuzkoa_edge_m <= 500) & (b.dist_veg_m > 100)).sum()))
    save_stats("proximity", st)
    (OUT_B / f"_buildings_stage{SUFFIX}.parquet").unlink(missing_ok=True)
    log("proximity done", st)


# --------------------------------------------------------------------------------------------- 5 SOURCES + REPORT
def sources():
    REPORTS.mkdir(parents=True, exist_ok=True)
    p = REPORTS / "sources.csv"
    cols = ["source_id", "dataset", "organisation", "url", "licence", "download_date", "edition_or_period", "raw_file", "processed_files", "notes"]
    rows = [
        dict(source_id=SRC_OSM, dataset="OpenStreetMap extract País Vasco (.osm.pbf) - used for admin_level=8 municipal limits and PROVISIONAL vegetation polygons",
             organisation="OpenStreetMap contributors via Geofabrik GmbH", url="https://download.geofabrik.de/europe/spain/pais-vasco.html (exact file URL to confirm)",
             licence="ODbL 1.0", download_date="to confirm (file dated 2026-09-30)", edition_or_period="snapshot 2026-09-30 (pais-vasco-260930)",
             raw_file="raw/pais-vasco-260930.osm.pbf",
             processed_files="processed/territory/*_osm.*; processed/vegetation/vegetation_osm_provisional.gpkg; processed/buildings/*_osm.*",
             notes=f"sha256={sha256(PBF)}; SUPERSEDED in v0.3 (2026-10-01) for municipal limits by SRC-GV-MUNICIPIOS5000-20250507 and for vegetation by SRC-GV-INVFORESTAL-2024 (files kept as *_osm / vegetation_osm_provisional for traceability; code/official_layers.py); v0.2 use: OSM admin_level=8 limits as stand-in for geoEuskadi, PROVISIONAL vegetation; extract covers CAV only, Navarra mostly absent"),
        dict(source_id=SRC_BU, dataset="INSPIRE Buildings Gipuzkoa (Building, flat layer GFA_INSPIRE_BU)",
             organisation="Diputación Foral de Gipuzkoa - B5M", url="to confirm (b5m.gipuzkoa.eus, downloaded by team; https://b5m.gipuzkoa.eus/web5000/es/api-rest/conjuntos-datos)",
             licence="to confirm (B5M open data terms)", download_date="2026-10-01", edition_or_period=f"layer metadata DBF_DATE_LAST_UPDATE={pyogrio.read_info(BU_GPKG)['layer_metadata'].get('DBF_DATE_LAST_UPDATE')}",
             raw_file="raw/GFA_INSPIRE_BU.gpkg; raw/GFA_INSPIRE_BU_es.csv", processed_files="processed/buildings/*",
             notes=f"sha256={sha256(BU_GPKG)}; EPSG:25830; 124,140 rows (incl. repeated INSPIREID rows); exact download URL not recorded"),
        dict(source_id=SRC_IGN, dataset="Provisional Tolosaldea municipalities/boundary (IGN, stated ~200 m generalisation but much coarser: 4-30 vertices per municipality) - comparison only",
             organisation="IGN (via npm package es-atlas 0.6.0)", url="https://www.npmjs.com/package/es-atlas", licence="CC BY 4.0 (IGN)",
             download_date="2026-10-01", edition_or_period="es-atlas 0.6.0 (IGN edition to confirm)",
             raw_file="raw/persona4_accesos_bomberos/processed/tolosaldea_munis_provisional.geojson; ...tolosaldea_boundary_provisional.geojson",
             processed_files="processed/territory/territory_comparison_ign.csv", notes="fallback only, not used for any output geometry"),
    ]
    new = pd.DataFrame(rows, columns=cols)
    if p.exists():
        old = pd.read_csv(p, dtype=str)
        old = old[~old.source_id.isin(new.source_id)]
        new = pd.concat([old, new], ignore_index=True)[cols]
    new.to_csv(p, index=False)
    log("sources.csv updated")


def main(steps):
    for s in steps:
        {"territory": territory, "buildings": buildings, "vegetation": vegetation, "proximity": proximity,
         "sources": sources, "report": report}[s]()


def report():
    import report_territory_buildings as r   # report template kept separate (code/report_territory_buildings.py)
    r.write(load_stats(), ROOT)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    steps = sys.argv[1:] or ["territory", "buildings", "vegetation", "proximity", "sources", "report"]   # legacy v0.2 (*_osm)
    main(steps)
