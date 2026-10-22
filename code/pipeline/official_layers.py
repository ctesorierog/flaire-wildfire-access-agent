#!/usr/bin/env python3
"""
flAIre · v0.3 OFFICIAL LAYERS · Persona 2 (official municipal limits) + Persona 3 CLEANER (Mapa Forestal 2024)

Replaces the PROVISIONAL OSM stand-ins used by code/territory_buildings.py (v0.2):
  * municipal limits  : geoEuskadi MUNICIPIOS_5000_ETRS89 (Gobierno Vasco, 1:5,000, updated 07/05/2025)
  * vegetation        : Mapa Forestal del País Vasco 2024 (INV_FORESTAL_2024_10000_ETRS89, 1:10,000)

Re-runnable end to end (raw/ never modified; ~4-6 min, < 3 GB RAM):
    python3 code/official_layers.py                      all steps
    python3 code/official_layers.py forest proximity     selected steps
Steps (in order):
  backup     copy the v0.2 OSM-based outputs to *_osm names (only if the *_osm copy does not exist yet, so it is never
             overwritten by an official-layer file)
  limits     official limits -> processed/territory/ (primary files) + comparison with OSM (territory_comparison_osm.csv)
  buildings  B5M cleaning of code/territory_buildings.py (same rules, same IDs) with the OFFICIAL municipalities
             -> municipality changes / pilot entries & exits vs v0.2 (building_municipality_changes.csv); candidates check
  forest     Mapa Forestal read from the zip (/vsizip/, bbox = Tolosaldea + 2 km, never the whole CAPV), class dictionary,
             clip to boundary + 2 km -> processed/vegetation/vegetation_forest_map_2024.gpkg, class_dictionary.csv,
             forest_area_by_class.csv, forest_vs_osm_comparison.csv
  proximity  footprint -> nearest 'vegetation' polygon (FUEL_GROUPS) -> buildings_tolosaldea.gpkg, buildings_analysis_set.csv,
             sensitivity_veg_distance.csv, analysis_set_diff_vs_osm.csv, quality_by_municipality.csv
  sources    rows in reports/sources.csv for both official datasets; OSM limits/vegetation rows marked SUPERSEDED (kept)
  report     section "7. v0.3 official layers" in reports/quality_territory_buildings.md (replaced in place on re-run)
Stats: processed/official_layers_stats.json. Metric CRS EPSG:25830; GeoJSON exports WGS84 (6 decimals).
"""
import sys, json, time, shutil, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
import pyogrio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
import territory_buildings as tb   # noqa: E402  (cleaning rules, PILOT list, helpers)

RAW = ROOT / "raw"
MUNI_ZIP = RAW / "MUNICIPIOS_5000_ETRS89.zip"
FOREST_ZIP = RAW / "INV_FORESTAL_2024_10000_ETRS89.zip"
MUNI_SHP = f"/vsizip/{MUNI_ZIP}/MUNICIPIOS_5000_ETRS89.shp"
FOREST_SHP = f"/vsizip/{FOREST_ZIP}/INV_FORESTAL_2024_10000_ETRS89.shp"
OUT_T, OUT_B, OUT_V = tb.OUT_T, tb.OUT_B, tb.OUT_V
CAND = ROOT / "processed/candidates/candidates_10.csv"
REPORTS = ROOT / "reports"
STATS = ROOT / "processed/official_layers_stats.json"
CRS = 25830
PILOT = tb.PILOT
SRC_MUNI = "SRC-GV-MUNICIPIOS5000-20250507"
SRC_FOREST = "SRC-GV-INVFORESTAL-2024"
SRC_OSM = "SRC-OSM-PV-260930"
VEG_BUFFER_M = 2000
VEG_RULE_M = 100
SLIVER_M2 = 1000          # gaps between municipal polygons smaller than this are filled in the boundary union
SENS_M = (0, 25, 50, 100, 200)
VEG_SOURCE = f"Mapa Forestal País Vasco 2024 ({SRC_FOREST}); vegetation = forest_* + scrub_heath"

log = tb.log


def load_stats():
    return json.loads(STATS.read_text()) if STATS.exists() else {}


def save_stats(key, val):
    s = load_stats(); s[key] = val
    STATS.write_text(json.dumps(s, indent=1, default=str, ensure_ascii=False))


def to_multi(g):
    return g if g.geom_type == "MultiPolygon" else shapely.MultiPolygon([g]) if g.geom_type == "Polygon" else \
        shapely.MultiPolygon([p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"])


# =============================================================================================== 0 BACKUP (v0.2 OSM state)
BACKUP = {  # primary (v0.2, OSM-based) -> *_osm copy kept for traceability
    OUT_T / "tolosaldea_municipalities.geojson": OUT_T / "tolosaldea_municipalities_osm.geojson",
    OUT_T / "tolosaldea_boundary.geojson": OUT_T / "tolosaldea_boundary_osm.geojson",
    OUT_T / "municipalities.csv": OUT_T / "municipalities_osm.csv",
    OUT_T / "territory.gpkg": OUT_T / "territory_osm.gpkg",
    OUT_T / "municipality_parts.csv": OUT_T / "municipality_parts_osm.csv",
    OUT_B / "buildings_tolosaldea.gpkg": OUT_B / "buildings_tolosaldea_osm.gpkg",
    OUT_B / "buildings_analysis_set.csv": OUT_B / "buildings_analysis_set_osm.csv",
    OUT_B / "sensitivity_veg_distance.csv": OUT_B / "sensitivity_veg_distance_osm.csv",
    OUT_B / "quality_by_municipality.csv": OUT_B / "quality_by_municipality_osm.csv",
    OUT_B / "duplicates_removed.csv": OUT_B / "duplicates_removed_osm.csv",
    OUT_B / "residential_rule.csv": OUT_B / "residential_rule_osm.csv",
    OUT_B / "overlapping_footprints_gt50pct.csv": OUT_B / "overlapping_footprints_gt50pct_osm.csv",
    ROOT / "processed/territory_buildings_stats.json": ROOT / "processed/territory_buildings_stats_osm.json",
}


def backup():
    done = []
    for src, dst in BACKUP.items():
        if dst.exists() or not src.exists():
            continue
        if src.name == "territory.gpkg":   # never back up an already-official territory as "_osm"
            sid = gpd.read_file(src, layer="tolosaldea_boundary").source_id.iloc[0]
            if sid != SRC_OSM:
                log(f"  skip backup of {src.name}: source_id {sid} is not OSM"); continue
        shutil.copy2(src, dst); done.append(dst.name)
    log("backup:", done or "nothing to do (copies exist)")


# =============================================================================================== 1 OFFICIAL LIMITS
def read_official_limits():
    g = gpd.read_file(MUNI_SHP, engine="pyogrio")
    assert g.crs.to_epsg() == CRS
    g["n_invalid_raw"] = (~g.is_valid).astype(int)
    g["geometry"] = [to_multi(x) for x in shapely.make_valid(g.geometry.values)]
    g["code3"] = g.EUSTAT.str[2:].astype(int)
    # 5xx codes = parzonerías / mancomunidades (common land, NOT municipalities); "Limitadua / El Limitado" = shared land
    g["unit_type"] = np.where((g.code3 >= 500) & (g.code3 < 600), "non_municipal", np.where(g.NOMBRE_TOP.str.contains("Limitadua"), "shared_land", "municipality"))
    return g


def limits():
    OUT_T.mkdir(parents=True, exist_ok=True)
    log("limits: reading MUNICIPIOS_5000 from zip")
    info = pyogrio.read_info(MUNI_SHP)
    g = read_official_limits()
    st = dict(n_features=len(g), fields=list(info["fields"]), dbf_last_update=info["layer_metadata"].get("DBF_DATE_LAST_UPDATE"),
              geom_types=dict(pyogrio.read_dataframe(MUNI_SHP, read_geometry=True, columns=[]).geom_type.value_counts()),
              invalid_raw=int(g.n_invalid_raw.sum()), unit_types=g.unit_type.value_counts().to_dict(),
              eustat_repeated=g.loc[g.EUSTAT.duplicated(keep=False), ["EUSTAT", "NOMBRE_TOP"]].values.tolist())
    gip = g[(g.MUN_PROV == "20") & (g.unit_type == "municipality")].copy()
    ctx = g[g.unit_type != "municipality"].copy()
    st["gipuzkoa_municipalities"] = len(gip)
    st["gipuzkoa_non_municipal"] = g.loc[(g.MUN_PROV == "20") & (g.unit_type != "municipality"), ["EUSTAT", "NOMBRE_TOP"]].values.tolist()
    gip["ine_code"] = gip.EUSTAT
    gip["in_pilot"] = gip.ine_code.isin(PILOT).astype(int)
    # independent check of the 28: official functional-area field A_FUNC_CAS (PTP) and comarca
    af = set(gip.ine_code[gip.A_FUNC_CAS == "TOLOSALDEA"]); com = set(gip.ine_code[gip.COMARCA == "TOLOSALDEA"])
    st["pilot_found"] = int(gip.in_pilot.sum()); st["pilot_missing"] = sorted(set(PILOT) - set(gip.ine_code))
    st["afunc_tolosaldea_equals_pilot"] = af == set(PILOT)
    st["comarca_tolosaldea_extra"] = gip.loc[gip.ine_code.isin(com - set(PILOT)), ["ine_code", "NOMBRE_TOP", "A_FUNC_CAS"]].values.tolist()
    # names: official NOMBRE_TOP; name_eu / name_es carried from the v0.2 (OSM) layer by INE code for continuity
    osm_g = gpd.read_file(OUT_T / "territory_osm.gpkg", layer="municipalities_gipuzkoa")
    nm = osm_g.set_index("ine_code")[["name_eu", "name_es"]]
    gip["name"] = gip.NOMBRE_TOP
    gip["name_eu"] = gip.ine_code.map(nm.name_eu).fillna(gip.NOMBRE_TOP)
    gip["name_es"] = gip.ine_code.map(nm.name_es).fillna(gip.NOMBRE_TOP)
    gip["name_check"] = [PILOT.get(c, n).lower().split("-")[0] in n.lower() for c, n in zip(gip.ine_code, gip.name)]
    st["name_mismatch_pilot"] = gip.loc[(gip.in_pilot == 1) & ~gip.name_check, ["ine_code", "name"]].values.tolist()
    gip["area_km2"] = gip.area / 1e6
    gip["n_parts"] = [len(x.geoms) for x in gip.geometry]
    gip["idtoponimo"] = gip.IDTOPONIMO
    gip["comarca"] = gip.COMARCA; gip["area_funcional"] = gip.A_FUNC_CAS
    gip["source"] = "geoEuskadi MUNICIPIOS_5000_ETRS89 EUSTAT=" + gip.EUSTAT + " IDTOPONIMO=" + gip.IDTOPONIMO.astype(str)
    gip["source_id"] = SRC_MUNI
    gip = gip.sort_values("ine_code").reset_index(drop=True)
    cols = ["ine_code", "name", "name_eu", "name_es", "in_pilot", "area_km2", "n_parts", "idtoponimo", "comarca",
            "area_funcional", "source", "source_id", "geometry"]
    pilot = gip[gip.in_pilot == 1][cols].reset_index(drop=True)
    union_raw = shapely.union_all(pilot.geometry.values)
    holes = np.array([shapely.Polygon(r).area for p in getattr(union_raw, "geoms", [union_raw]) for r in p.interiors])
    # sliver gaps between neighbouring municipal polygons (digitising gaps, < SLIVER_M2) are filled in the BOUNDARY only;
    # municipality polygons are left exactly as published
    union = shapely.MultiPolygon([shapely.Polygon(p.exterior, [r for r in p.interiors if shapely.Polygon(r).area >= SLIVER_M2])
                                  for p in getattr(union_raw, "geoms", [union_raw])])
    st.update(sum_area_km2=round(pilot.area_km2.sum(), 4), union_area_km2=round(union.area / 1e6, 4),
              overlap_km2=round(pilot.area_km2.sum() - union_raw.area / 1e6, 5),
              union_parts=len(getattr(union, "geoms", [union])),
              union_sliver_holes=dict(n=int((holes < SLIVER_M2).sum()), total_m2=round(float(holes[holes < SLIVER_M2].sum()), 1),
                                      max_m2=round(float(holes.max()), 1) if len(holes) else 0.0, filled_in_boundary=True,
                                      larger_holes_kept_km2=[round(h / 1e6, 4) for h in holes[holes >= SLIVER_M2]]))
    bnd = gpd.GeoDataFrame(dict(name=["Tolosaldea (28 municipios, AF Tolosa PTP)"], n_municipalities=[len(pilot)],
                                area_km2=[union.area / 1e6], source_id=[SRC_MUNI]), geometry=[to_multi(union)], crs=CRS)

    # parts (exclaves)
    parts = []
    for r in pilot.itertuples():
        polys = sorted(r.geometry.geoms, key=lambda p: -p.area)
        for i, p in enumerate(polys):
            parts.append(dict(ine_code=r.ine_code, name=r.name, part=i + 1, area_km2=round(p.area / 1e6, 5),
                              touches_main=bool(i == 0 or p.distance(polys[0]) < 0.5),
                              touches_pilot_union_main=None, _pt=p.representative_point()))
    parts = pd.DataFrame(parts)
    upolys = sorted(getattr(union, "geoms", [union]), key=lambda p: -p.area)
    parts["touches_pilot_union_main"] = [bool(upolys[0].buffer(0.5).intersects(pt)) for pt in parts._pt]   # rep point in main body
    pts = gpd.GeoSeries(parts.pop("_pt"), crs=CRS).to_crs(4326)
    parts["rep_lon"] = pts.x.round(5).values; parts["rep_lat"] = pts.y.round(5).values
    parts.to_csv(OUT_T / "municipality_parts.csv", index=False)
    st["multipart"] = parts.groupby(["ine_code", "name"]).size().loc[lambda s: s > 1].reset_index().values.tolist()
    st["union_part_areas_km2"] = [round(p.area / 1e6, 4) for p in upolys]

    # ---- comparison with the v0.2 OSM limits
    osm = gpd.read_file(OUT_T / "territory_osm.gpkg", layer="tolosaldea_municipalities").set_index("ine_code")
    osm_parts = pd.read_csv(OUT_T / "municipality_parts_osm.csv", dtype={"ine_code": str})
    comp = []
    for r in pilot.itertuples():
        go = osm.geometry[r.ine_code]; gf = r.geometry
        sym = gf.symmetric_difference(go)
        comp.append(dict(ine_code=r.ine_code, name=r.name, area_official_km2=round(gf.area / 1e6, 4), area_osm_km2=round(go.area / 1e6, 4),
                         area_diff_pct=round(100 * (go.area - gf.area) / gf.area, 3),
                         iou=round(gf.intersection(go).area / gf.union(go).area, 5),
                         hausdorff_m=round(shapely.hausdorff_distance(gf, go, densify=0.25), 1),
                         sym_diff_km2=round(sym.area / 1e6, 4),
                         parts_official=r.n_parts, parts_osm=int(osm.n_parts[r.ine_code]),
                         exclaves_official_km2=";".join(str(a) for a in parts.loc[(parts.ine_code == r.ine_code) & (parts.part > 1), "area_km2"]),
                         exclaves_osm_km2=";".join(str(a) for a in osm_parts.loc[(osm_parts.ine_code == r.ine_code) & (osm_parts.part > 1), "area_km2"])))
    comp = pd.DataFrame(comp)
    comp.to_csv(OUT_T / "territory_comparison_osm.csv", index=False)
    ob = gpd.read_file(OUT_T / "territory_osm.gpkg", layer="tolosaldea_boundary").geometry.iloc[0]
    st["osm_union"] = dict(area_official_km2=round(union.area / 1e6, 4), area_osm_km2=round(ob.area / 1e6, 4),
                           area_diff_pct=round(100 * (ob.area - union.area) / union.area, 3),
                           iou=round(union.intersection(ob).area / union.union(ob).area, 5),
                           hausdorff_m=round(shapely.hausdorff_distance(union, ob, densify=0.25), 1),
                           sym_diff_km2=round(union.symmetric_difference(ob).area / 1e6, 4))
    st["osm_per_muni"] = dict(area_diff_abs_max_pct=float(comp.area_diff_pct.abs().max()), iou_min=float(comp.iou.min()),
                              iou_median=float(comp.iou.median()), hausdorff_median_m=float(comp.hausdorff_m.median()),
                              hausdorff_max_m=float(comp.hausdorff_m.max()),
                              hausdorff_max_muni=comp.loc[comp.hausdorff_m.idxmax(), "name"],
                              parts_differ=comp.loc[comp.parts_official != comp.parts_osm, ["name", "parts_official", "parts_osm"]].values.tolist())
    # all Gipuzkoa: same 88 codes?
    st["gipuzkoa_codes_equal_osm"] = set(gip.ine_code) == set(osm_g.ine_code)

    # ---- context units (parzonerías / mancomunidades + shared land) for the whole CAPV
    ctx["name"] = ctx.NOMBRE_TOP; ctx["eustat"] = ctx.EUSTAT; ctx["area_km2"] = ctx.area / 1e6
    ctx["note"] = ctx.unit_type.map({"non_municipal": "parzonería / mancomunidad (common land, NOT a municipality; NOT in pilot)",
                                     "shared_land": "shared land (Limitadua / El Limitado) listed under two municipalities; NOT in pilot"})
    ctx["source_id"] = SRC_MUNI
    ctx = ctx[["name", "eustat", "unit_type", "area_km2", "note", "source_id", "geometry"]].reset_index(drop=True)
    near = ctx[ctx.intersects(union.buffer(50))]
    st["context_adjacent_to_pilot"] = near[["eustat", "name"]].values.tolist()
    capv = gpd.GeoDataFrame(dict(name=["CAPV / Euskadi (union of MUNICIPIOS_5000)"], source_id=[SRC_MUNI]),
                            geometry=[to_multi(shapely.union_all(g.geometry.values))], crs=CRS)

    # ---- write (primary names)
    tp = OUT_T / "territory.gpkg"; tp.unlink(missing_ok=True)
    tb.write_gpkg(pilot, tp, "tolosaldea_municipalities")
    tb.write_gpkg(bnd, tp, "tolosaldea_boundary")
    tb.write_gpkg(gip[cols].reset_index(drop=True), tp, "municipalities_gipuzkoa")
    tb.write_gpkg(ctx, tp, "context_non_municipal")
    tb.write_gpkg(capv, tp, "capv_extent")
    tb.write_geojson(pilot, OUT_T / "tolosaldea_municipalities.geojson")
    tb.write_geojson(bnd, OUT_T / "tolosaldea_boundary.geojson")
    csv = pilot[["ine_code", "name", "name_eu", "name_es", "area_km2", "n_parts", "idtoponimo", "comarca", "area_funcional", "source", "source_id"]].copy()
    csv["area_km2"] = csv.area_km2.round(4)
    csv.to_csv(OUT_T / "municipalities.csv", index=False)
    st["bbox_lonlat"] = [round(v, 6) for v in bnd.to_crs(4326).total_bounds]
    st["bbox_25830_plus2km"] = [round(v, 1) for v in bnd.buffer(VEG_BUFFER_M).total_bounds]
    save_stats("limits", st)
    log("limits done", st["osm_union"], st["osm_per_muni"])


# =============================================================================================== 2 BUILDINGS (official limits)
def _use_official_in_tb():
    tb.TERR_GPKG = OUT_T / "territory.gpkg"
    tb.SUFFIX = ""
    tb.STATS = STATS          # tb.save_stats("buildings", ...) lands in official_layers_stats.json


def buildings():
    """Same B5M cleaning as v0.2 (tb.buildings), municipality by representative point within the OFFICIAL polygons."""
    _use_official_in_tb()
    sid = gpd.read_file(tb.TERR_GPKG, layer="tolosaldea_boundary").source_id.iloc[0]
    assert sid == SRC_MUNI, f"territory.gpkg is not the official layer ({sid}); run step limits first"
    tb.buildings()                                    # -> processed/buildings/_buildings_stage.parquet (+ cleaning CSVs)
    new = gpd.read_parquet(OUT_B / "_buildings_stage.parquet")
    old = gpd.read_file(OUT_B / "buildings_tolosaldea_osm.gpkg", layer="buildings", engine="pyogrio")
    aset_old = set(pd.read_csv(OUT_B / "buildings_analysis_set_osm.csv").building_id)
    o = old.set_index("building_id"); n = new.set_index("building_id")
    entered = sorted(set(n.index) - set(o.index)); left = sorted(set(o.index) - set(n.index))
    common = n.index.intersection(o.index)
    moved = [b for b in common if n.muni_ine[b] != o.muni_ine[b]]
    # municipality of the rep point for buildings that left (official, any Gipuzkoa municipality or context unit)
    munis = gpd.read_file(tb.TERR_GPKG, layer="municipalities_gipuzkoa"); ctx = gpd.read_file(tb.TERR_GPKG, layer="context_non_municipal")
    bnd = gpd.read_file(tb.TERR_GPKG, layer="tolosaldea_boundary").geometry.iloc[0]
    rows = []
    for kind, ids, src in (("entered_pilot", entered, n), ("left_pilot", left, o), ("municipality_changed", moved, n)):
        for b in ids:
            r = src.loc[b]
            rows.append(dict(building_id=b, change=kind, muni_osm=o.muni_ine.get(b), muni_osm_name=o.muni_name.get(b),
                             muni_official=n.muni_ine.get(b), muni_official_name=n.muni_name.get(b),
                             residential_flag=r.residential_flag, dwellings=r.dwellings,
                             in_analysis_set_osm=b in aset_old, rep_x=r.rep_x, rep_y=r.rep_y, lon=r.lon, lat=r.lat))
    ch = pd.DataFrame(rows, columns=["building_id", "change", "muni_osm", "muni_osm_name", "muni_official", "muni_official_name",
                                     "residential_flag", "dwellings", "in_analysis_set_osm", "rep_x", "rep_y", "lon", "lat"])
    if len(ch):
        p = gpd.GeoSeries(gpd.points_from_xy(ch.rep_x, ch.rep_y), crs=CRS)
        ch["dist_pilot_boundary_m"] = np.round(shapely.distance(p.values, bnd.boundary), 1)
        lp = ch.change == "left_pilot"
        if lp.any():
            j = gpd.sjoin(gpd.GeoDataFrame(geometry=p[lp].values, crs=CRS),
                          pd.concat([munis[["ine_code", "name", "geometry"]],
                                     ctx.rename(columns={"eustat": "ine_code"})[["ine_code", "name", "geometry"]]]), how="left", predicate="within")
            j = j[~j.index.duplicated()]
            ch.loc[lp, "muni_official"] = j.ine_code.values; ch.loc[lp, "muni_official_name"] = j["name"].values
        allu = pd.concat([munis[["ine_code", "geometry"]], ctx.rename(columns={"eustat": "ine_code"})[["ine_code", "geometry"]]]).set_index("ine_code").geometry
        ch["dist_official_muni_border_m"] = [round(float(shapely.distance(pt, allu[c].boundary)), 1) if c in allu.index else None
                                             for pt, c in zip(p.values, ch.muni_official)]
    ch.to_csv(OUT_B / "building_municipality_changes.csv", index=False)
    st = dict(n_official=len(new), n_osm=len(old), entered=len(entered), left=len(left), municipality_changed=len(moved),
              by_change_flag=ch.groupby(["change", "residential_flag"]).size().reset_index().values.tolist() if len(ch) else [],
              dwellings_by_change=ch.groupby("change").dwellings.sum().to_dict() if len(ch) else {},
              changes_in_osm_analysis_set=int(ch.in_analysis_set_osm.sum()) if len(ch) else 0,
              moved_pairs=ch[ch.change == "municipality_changed"].groupby(["muni_osm_name", "muni_official_name"]).size().reset_index().values.tolist() if len(ch) else [],
              left_to=ch[ch.change == "left_pilot"].muni_official_name.fillna("(none)").value_counts().to_dict() if len(ch) else {},
              entered_from=ch[ch.change == "entered_pilot"].muni_osm_name.fillna("(outside OSM pilot)").value_counts().to_dict() if len(ch) else {},
              ids_identical_for_common=True,
              dist_official_muni_border_m=ch.dist_official_muni_border_m.describe().round(1).to_dict() if len(ch) else {})

    # ---- candidates (report only, do not move) and candidate pool eligibility
    C = pd.read_csv(CAND, dtype={"municipality_code": str})
    cp = gpd.GeoDataFrame(C[["cand_id", "name", "municipality_code", "municipality"]], geometry=gpd.points_from_xy(C.x, C.y), crs=CRS)
    j = gpd.sjoin(cp, munis[["ine_code", "name", "in_pilot", "geometry"]].rename(columns={"name": "muni_name_official"}),
                  how="left", predicate="within")
    j = j[~j.index.duplicated()]
    j["dist_to_muni_border_m"] = [round(float(shapely.distance(pt, munis.boundary[munis.ine_code == c].iloc[0])), 1) if isinstance(c, str) else None
                                  for pt, c in zip(j.geometry, j.ine_code)]
    j["municipality_changed"] = j.ine_code != j.municipality_code
    cc = j[["cand_id", "name", "municipality_code", "municipality", "ine_code", "muni_name_official", "in_pilot",
            "municipality_changed", "dist_to_muni_border_m"]].rename(columns={"municipality_code": "muni_code_v02", "municipality": "muni_v02",
                                                                            "ine_code": "muni_code_official", "in_pilot": "in_pilot_official"})
    cc.to_csv(ROOT / "processed/candidates/candidates_municipality_check_v03.csv", index=False)
    st["candidates"] = cc.to_dict("records")
    P = gpd.read_file(ROOT / "processed/network/candidate_pool.gpkg", layer="candidate_pool", engine="pyogrio")
    P = P[P.status == "ok"]
    tolm = munis[munis.in_pilot == 1]
    jp = gpd.sjoin(P[["pool_id", "municipality_code", "geometry"]], tolm[["ine_code", "geometry"]], how="left", predicate="within")
    jp = jp[~jp.index.duplicated()]
    to = gpd.read_file(OUT_T / "territory_osm.gpkg", layer="tolosaldea_municipalities")
    jo = gpd.sjoin(P[["pool_id", "geometry"]], to[["ine_code", "geometry"]], how="left", predicate="within")
    jo = jo[~jo.index.duplicated()]
    pc = pd.DataFrame(dict(pool_id=P.pool_id.values, muni_osm=jo.ine_code.values, muni_official=jp.ine_code.values))
    pc = pc[pc.muni_osm.fillna("-") != pc.muni_official.fillna("-")]
    pc.to_csv(ROOT / "processed/candidates/pool_municipality_changes_v03.csv", index=False)
    st["pool_sites_ok"] = len(P); st["pool_changes"] = pc.to_dict("records")
    save_stats("buildings_official", st)
    log("buildings (official limits):", {k: st[k] for k in ("n_official", "n_osm", "entered", "left", "municipality_changed")},
        "candidates changed:", int(cc.municipality_changed.sum()), "pool changes:", len(pc))


# =============================================================================================== 3 FOREST MAP 2024
# Grouping rules (explicit; original TIPES10 / SP1..3 codes and names are kept on every polygon).
#   TIPES10 11 Bosque, 14 Bosque de galería  -> forest_conifer | forest_broadleaf | forest_mixed  (by leaf type of SP1;
#                                               forest_mixed when SP1 is a mixed conifer+broadleaf code, or the 2nd species is of the
#                                               other leaf type with O2 >= MIX_O2 tenths)
#   TIPES10 12 Bosque de plantación          -> forest_plantation (subclass by leaf type; eucalyptus separate)
#   TIPES10 21 Arbustedos                    -> scrub_heath (subclass scrub)
#   TIPES10 23 Pastizal-Matorral             -> scrub_heath (subclass pasture_scrub_mosaic: mean shrub cover 44 %, fuel models 5-7)
#   TIPES10 31 Herbazal-pastizal, 73 Prados, 74 Prados con setos -> grassland_pasture
#   everything else                          -> non_forest_other (subclass agricultural | artificial | bare_rock | water_wetland)
FOREST_TIPES = {11: "natural", 14: "riparian"}
VEG_FOR_PROXIMITY = ("forest_conifer", "forest_broadleaf", "forest_mixed", "forest_plantation", "scrub_heath")   # grassland EXCLUDED
MIX_O2 = 3
CONIFER_RX = r"pino|pinu|abeto|pinabete|pinsapo|tsuga|alerce|p[ií]cea|secuoy|criptomeria|chameciparis|cedro|cipr[eé]s|tuya|tejo|enebro|con[ií]feras"
# v0.3.2: Pinabete (Abies alba), Pinsapo (Abies pinsapo) and Tsuga are conifers (were wrongly falling to broadleaf).
MIXED_RX = r"frondosas y con[ií]feras"
EUCA_RX = r"eucalipt"
GROUP_SCHEMA = {  # -> schema.sql vegetation_classes.class_group (CHECK list)
    "forest_conifer": "conifer", "forest_broadleaf": "broadleaf", "forest_mixed": "mixed_forest", "scrub_heath": "shrub",
    "grassland_pasture": "grassland"}
FOREST_COLS = ["OBJECTID", "TIPES10", "TIPES_es", "TIPES_eu", "SP1", "SP1_es", "SP1_eu", "O1", "E1", "EMASA1", "SP2", "SP2_es",
               "SP2_eu", "O2", "E2", "EMASA2", "SP3", "SP3_es", "SP3_eu", "O3", "E3", "EMASA3", "FCCARB", "FORARB", "DISTRIB",
               "FCCMAT", "FORMAT", "FORMAT2", "FCCHER", "FORHER", "ATRIBUTO", "OSUPTIP", "OCUOSUP", "HMMAT", "MODCOM_I", "Shape_Area"]


def leaf_type(code, name):
    if not isinstance(name, str) or not code:
        return None
    n = name.lower()
    if pd.Series([n]).str.contains(MIXED_RX).iloc[0]:
        return "mixed"
    if pd.Series([n]).str.contains(CONIFER_RX).iloc[0]:
        return "conifer"
    return "eucalyptus" if pd.Series([n]).str.contains(EUCA_RX).iloc[0] else "broadleaf"


def classify(df):
    """Adds leaf_type, mixed_rule, veg_class, veg_subclass, class_code, class_group (schema), is_veg_proximity."""
    sp_lt = {}
    for c, nm in pd.concat([df[[f"SP{i}", f"SP{i}_es"]].set_axis(["c", "n"], axis=1) for i in (1, 2, 3)]).drop_duplicates().values:
        sp_lt[(c, nm)] = leaf_type(c, nm)
    lt1 = pd.Series([sp_lt.get((c, n)) for c, n in zip(df.SP1, df.SP1_es)], index=df.index)
    lt2 = pd.Series([sp_lt.get((c, n)) for c, n in zip(df.SP2, df.SP2_es)], index=df.index)
    lt3 = pd.Series([sp_lt.get((c, n)) for c, n in zip(df.SP3, df.SP3_es)], index=df.index)
    fam = lambda s: s.replace({"eucalyptus": "broadleaf"})
    t = df.TIPES10
    is_for = t.isin(list(FOREST_TIPES)); is_pl = t == 12
    # v0.3.2 mixed rule: O1..O3 are occupation in TENTHS of the tree cover (O1+O2+O3 = 10 in every tree polygon).
    # A stand is mixed if SP1 is itself a mixed code, or if species of the OTHER leaf family (conifer vs broadleaf;
    # eucalyptus counts as broadleaf) among SP2 and SP3 together occupy >= MIX_O2 tenths (30 %).
    o2 = pd.to_numeric(df.O2, errors="coerce").fillna(0); o3 = pd.to_numeric(df.O3, errors="coerce").fillna(0)
    other2 = lt2.notna() & (lt2 != "mixed") & (fam(lt2) != fam(lt1))
    other3 = lt3.notna() & (lt3 != "mixed") & (fam(lt3) != fam(lt1))
    df["occ_other_leaf_tenths"] = np.where(other2, o2, 0) + np.where(other3, o3, 0)
    mixed = (lt1 == "mixed") | ((lt1 != "mixed") & (df["occ_other_leaf_tenths"] >= MIX_O2))
    vc = pd.Series("non_forest_other", index=df.index)
    vc[is_for] = np.where(mixed[is_for], "forest_mixed", np.where(lt1[is_for] == "conifer", "forest_conifer", "forest_broadleaf"))
    vc[is_pl] = "forest_plantation"
    vc[t.isin([21, 23])] = "scrub_heath"
    vc[t.isin([31, 73, 74])] = "grassland_pasture"
    sub = pd.Series(None, index=df.index, dtype=object)
    sub[is_for] = np.where(t[is_for] == 14, "riparian_", "natural_") + vc[is_for].str.replace("forest_", "", regex=False)
    sub[is_pl] = "plantation_" + np.where(mixed[is_pl], "mixed", lt1[is_pl].fillna("unknown"))
    sub[t == 21] = "scrub"; sub[t == 23] = "pasture_scrub_mosaic"
    sub[t == 31] = "grassland"; sub[t.isin([73, 74])] = "meadow"
    oth = vc == "non_forest_other"
    sub[oth & t.isin([71, 75])] = "agricultural"
    sub[oth & (t >= 80) & (t < 900)] = "artificial"
    sub[oth & t.isin([41, 441, 442, 443, 4541])] = "bare_rock"
    sub[oth & (t.isin([511, 512, 513, 521, 611, 622, 623, 6121, 6122]))] = "water_wetland"
    sub[oth & sub.isna()] = "other"
    df["leaf_type"] = np.where(is_for | is_pl, np.where(mixed, "mixed", lt1), None)
    df["mixed_rule"] = (is_for | is_pl) & mixed
    df["veg_class"] = vc.values; df["veg_subclass"] = sub.values
    # class_code_orig (dictionary key) = original codes; '|MIX' marks the O2 mixed-stand rule
    sp = np.where(is_for | is_pl, "|SP1=" + df.SP1.fillna(0).astype(int).astype(str), "")
    df["class_code"] = "TIPES10=" + t.astype(str) + sp + np.where(df.mixed_rule & (lt1 != "mixed"), "|MIX", "")
    grp = vc.map(GROUP_SCHEMA)
    pl_grp = pd.Series(df.leaf_type, index=df.index).map({"conifer": "conifer", "broadleaf": "broadleaf", "eucalyptus": "broadleaf", "mixed": "mixed_forest"})
    grp[is_pl] = pl_grp[is_pl]
    grp[oth & sub.eq("agricultural")] = "crop"; grp[oth & sub.isin(["artificial", "bare_rock"])] = "non_vegetated"
    grp[oth & sub.eq("water_wetland")] = "water"; grp = grp.fillna("other")
    df["class_group"] = grp.values
    df["is_veg_proximity"] = vc.isin(VEG_FOR_PROXIMITY).astype(int).values
    return df


def forest():
    OUT_V.mkdir(parents=True, exist_ok=True)
    tp = OUT_T / "territory.gpkg"
    bnd = gpd.read_file(tp, layer="tolosaldea_boundary").geometry.iloc[0]
    capv = gpd.read_file(tp, layer="capv_extent").geometry.iloc[0]
    clip = bnd.buffer(VEG_BUFFER_M)
    info = pyogrio.read_info(FOREST_SHP)
    st = dict(n_features_capv=info["features"], geometry_type=info["geometry_type"], crs=info["crs"],
              dbf_last_update=info["layer_metadata"].get("DBF_DATE_LAST_UPDATE"), fields=list(info["fields"]))
    # edition / date: what the data itself says (no date attribute in the table)
    import zipfile, re
    with zipfile.ZipFile(FOREST_ZIP) as z:
        xml = z.read("INV_FORESTAL_2024_10000_ETRS89.shp.xml").decode("utf-8", "ignore")
        st["zip_member_dates"] = {i.filename: "%04d-%02d-%02d" % i.date_time[:3] for i in z.infolist()}
    st["xml_dates"] = {k: re.findall(rf"<{k}>(\d+)</{k}>", xml) for k in ("CreaDate", "ModDate", "SyncDate")}
    st["xml_source_gdb"] = sorted(set(re.findall(r"IF_2024_V\d+_FINAL_V\d+_A", xml)))
    st["date_fields_in_table"] = [f for f in info["fields"] if re.search(r"FECHA|DATE|ANO|YEAR|EDIC", f, re.I)]

    # ---- CAPV-wide attribute profile (attributes only, no geometry) -> complete dictionary
    log("forest: CAPV-wide attribute profile")
    A = pyogrio.read_dataframe(FOREST_SHP, columns=[c for c in FOREST_COLS if c != "OBJECTID"], read_geometry=False)
    A = classify(A)
    st["capv_area_ha_by_tipes"] = A.groupby(["TIPES10", "TIPES_es"]).Shape_Area.sum().div(1e4).round(1).reset_index().values.tolist()
    st["capv_area_km2"] = round(A.Shape_Area.sum() / 1e6, 1)

    # ---- spatial read: bbox of boundary + 2 km only
    bb = tuple(clip.bounds)
    log(f"forest: reading bbox {tuple(round(v) for v in bb)} from zip")
    t0 = time.time()
    F = pyogrio.read_dataframe(FOREST_SHP, bbox=bb)
    st["read_bbox_s"] = round(time.time() - t0, 1); st["n_bbox"] = len(F)
    F["geometry"] = shapely.force_2d(F.geometry.values)
    inv = ~F.is_valid
    st["invalid_fixed"] = int(inv.sum())
    if inv.any():
        F.loc[inv, "geometry"] = shapely.make_valid(F.geometry[inv].values)
    F = F[F.intersects(clip)].copy()
    st["n_intersecting_clip"] = len(F)
    within = F.within(clip)
    F["clipped"] = ~within
    F.loc[~within, "geometry"] = shapely.intersection(F.geometry[~within].values, clip)
    F["geometry"] = [to_multi(g) for g in F.geometry]
    F = F[~F.is_empty].copy()
    F = classify(F)
    F["area_orig_ha"] = (F.Shape_Area / 1e4).round(4)
    F["area_ha"] = (F.area / 1e4).round(4)
    F["in_tolosaldea"] = F.intersects(bnd)
    F["source_id"] = SRC_FOREST
    F = F.drop(columns=["Shape_Area", "Shape_Leng"], errors="ignore")
    keep = [c for c in FOREST_COLS if c != "Shape_Area"] + ["class_code", "veg_class", "veg_subclass", "leaf_type", "mixed_rule", "occ_other_leaf_tenths",
                                                             "class_group", "is_veg_proximity", "clipped", "in_tolosaldea",
                                                             "area_orig_ha", "area_ha", "source_id", "geometry"]
    F = F[keep].reset_index(drop=True)

    # ---- area inside Tolosaldea (exact intersection with the official boundary)
    inside = F[F.in_tolosaldea]
    gi = shapely.intersection(inside.geometry.values, bnd)
    F["area_in_tolosaldea_ha"] = 0.0
    F.loc[inside.index, "area_in_tolosaldea_ha"] = np.round(shapely.area(gi) / 1e4, 4)
    tot_in = F.area_in_tolosaldea_ha.sum()
    st["tolosaldea_area_covered_ha"] = round(tot_in, 1); st["tolosaldea_area_ha"] = round(bnd.area / 1e4, 1)
    st["clip_area_km2"] = round(clip.area / 1e6, 2)
    st["clip_outside_capv_km2"] = round(clip.difference(capv).area / 1e6, 2)
    st["clip_covered_km2"] = round(F.area_ha.sum() / 100, 2)

    # ---- write layer
    vp = OUT_V / "vegetation_forest_map_2024.gpkg"; vp.unlink(missing_ok=True)
    tb.write_gpkg(F, vp, "vegetation_forest_map_2024")
    tb.write_gpkg(gpd.GeoDataFrame(dict(name=["Tolosaldea official boundary + 2 km (clip extent)"], buffer_m=[VEG_BUFFER_M],
                                        area_outside_capv_km2=[st["clip_outside_capv_km2"]]), geometry=[clip], crs=CRS), vp, "clip_extent")
    # DB-ready layer for code/manager/schema.sql `vegetation` (class_code_orig, class_group, is_fuel, source_id)
    db = F[["class_code", "class_group", "is_veg_proximity", "source_id", "geometry"]].rename(
        columns={"class_code": "class_code_orig", "is_veg_proximity": "is_fuel"})
    tb.write_gpkg(db, vp, "vegetation_db")

    # ---- class dictionary (all codes present in the CAPV; areas CAPV / clip / Tolosaldea)
    key = ["class_code", "TIPES10", "TIPES_es", "TIPES_eu", "SP1", "SP1_es", "SP1_eu", "veg_class", "veg_subclass", "leaf_type",
           "mixed_rule", "class_group", "is_veg_proximity"]
    dcap = A.assign(SP1=np.where(A.TIPES10.isin([11, 12, 14]), A.SP1, np.nan),
                    SP1_es=np.where(A.TIPES10.isin([11, 12, 14]), A.SP1_es, None),
                    SP1_eu=np.where(A.TIPES10.isin([11, 12, 14]), A.SP1_eu, None))
    D = dcap.groupby(key, dropna=False).agg(n_polygons_capv=("Shape_Area", "size"), area_ha_capv=("Shape_Area", lambda s: round(s.sum() / 1e4, 2))).reset_index()
    Fk = F.assign(SP1=np.where(F.TIPES10.isin([11, 12, 14]), F.SP1, np.nan))
    clipagg = Fk.groupby("class_code").agg(n_polygons_clip=("OBJECTID", "size"), area_ha_clip=("area_ha", "sum"),
                                           area_ha_tolosaldea=("area_in_tolosaldea_ha", "sum")).round(2)
    D = D.merge(clipagg, left_on="class_code", right_index=True, how="left").fillna({"n_polygons_clip": 0, "area_ha_clip": 0, "area_ha_tolosaldea": 0})
    assert not D.class_code.duplicated().any(), D[D.class_code.duplicated(keep=False)]
    D["rule"] = D.apply(lambda r: _rule_text(r), axis=1)
    D["source_id"] = SRC_FOREST
    D = D.sort_values(["TIPES10", "area_ha_capv"], ascending=[True, False])
    D.to_csv(OUT_V / "class_dictionary.csv", index=False)

    # ---- area by class within Tolosaldea (and clip)
    ac = F.groupby(["veg_class", "veg_subclass"]).agg(n_polygons=("OBJECTID", "size"), area_ha_clip=("area_ha", "sum"),
                                                      area_ha_tolosaldea=("area_in_tolosaldea_ha", "sum")).reset_index()
    ac["share_tolosaldea_pct"] = (100 * ac.area_ha_tolosaldea / tot_in).round(2)
    ac["is_veg_proximity"] = ac.veg_class.isin(VEG_FOR_PROXIMITY).astype(int)
    ac = ac.round(1)
    ac.to_csv(OUT_V / "forest_area_by_class.csv", index=False)
    by = F.groupby("veg_class").area_in_tolosaldea_ha.sum()
    st["area_ha_tolosaldea_by_class"] = by.round(1).to_dict()
    st["share_pct_tolosaldea_by_class"] = (100 * by / tot_in).round(2).to_dict()
    st["veg_proximity_share_tolosaldea_pct"] = round(100 * by[list(VEG_FOR_PROXIMITY)].sum() / tot_in, 2)
    st["top_species_tolosaldea_ha"] = F[F.TIPES10.isin([11, 12, 14])].groupby("SP1_es").area_in_tolosaldea_ha.sum().sort_values(ascending=False).head(12).round(1).to_dict()
    st["dev_state_tolosaldea_ha"] = F[F.TIPES10.isin([11, 12, 14])].groupby("EMASA1").area_in_tolosaldea_ha.sum().round(1).to_dict()
    st["modcom_tolosaldea_ha"] = F.groupby("MODCOM_I").area_in_tolosaldea_ha.sum().round(1).to_dict()
    st["mixed_rule_polygons"] = int(F.mixed_rule.sum())
    st["value_counts_clip"] = {c: F[c].value_counts(dropna=False).head(30).to_dict() for c in
                               ["TIPES10", "E1", "EMASA1", "O1", "FORARB", "DISTRIB", "FORMAT", "FORHER", "ATRIBUTO", "MODCOM_I", "HMMAT"]}
    st["cover_pct_by_tipes_clip"] = F.groupby("TIPES10")[["FCCARB", "FCCMAT", "FCCHER"]].mean().round(1).reset_index().values.tolist()
    st["n_written"] = len(F)
    save_stats("forest", st)
    compare_osm(F, bnd)
    log("forest done", st["area_ha_tolosaldea_by_class"], "veg share", st["veg_proximity_share_tolosaldea_pct"])


def _rule_text(r):
    t = int(r.TIPES10)
    if t in FOREST_TIPES:
        return (f"TIPES10 {t} ({FOREST_TIPES[t]} forest): leaf type of SP1 '{r.SP1_es}'" +
                (f"; mixed: species of the other leaf type in SP2+SP3 occupy >= {MIX_O2}/10 of the tree cover" if "|MIX" in r.class_code else ""))
    if t == 12:
        return f"TIPES10 12 plantation; leaf type of SP1 '{r.SP1_es}'" + (f"; mixed: other-leaf species in SP2+SP3 >= {MIX_O2}/10" if "|MIX" in r.class_code else "")
    return f"TIPES10 {t} '{r.TIPES_es}' -> {r.veg_class}"


def _grid_pieces(geoms, size=1000):
    minx, miny, maxx, maxy = shapely.total_bounds(geoms)
    xs = np.arange(np.floor(minx / size) * size, maxx + size, size); ys = np.arange(np.floor(miny / size) * size, maxy + size, size)
    cells = shapely.box(*np.meshgrid(xs[:-1], ys[:-1]), *np.meshgrid(xs[1:], ys[1:])).ravel()
    pi, ci = shapely.STRtree(cells).query(geoms, predicate="intersects")
    pieces = shapely.intersection(geoms[pi], cells[ci])
    ok = ~shapely.is_empty(pieces)
    return pieces[ok], pi[ok]


def compare_osm(F, bnd):
    """Forest map vs OSM provisional inside Tolosaldea (official boundary): exact vector overlay on 1 km grid pieces."""
    O = gpd.read_file(OUT_V / "vegetation_osm_provisional.gpkg", layer="vegetation_osm_provisional")
    # one OSM category per location: forest > scrub_heath > grassland > none
    cat = {}
    done = shapely.Polygon()
    for c in ("forest", "scrub_heath", "grassland"):
        u = shapely.intersection(shapely.union_all(O.geometry[O.veg_class == c].values), bnd)
        cat[c] = shapely.difference(u, done); done = shapely.union(done, u)
    cat["none"] = shapely.difference(bnd, done)
    Fi = F[F.area_in_tolosaldea_ha > 0]
    fg = shapely.intersection(Fi.geometry.values, bnd)
    fp, fidx = _grid_pieces(fg)
    rows = []
    for c, g in cat.items():
        gp, _ = _grid_pieces(np.array([g]))
        a, b = shapely.STRtree(gp).query(fp, predicate="intersects")
        ar = shapely.area(shapely.intersection(fp[a], gp[b]))
        s = pd.Series(ar).groupby(Fi.veg_class.values[fidx[a]]).sum() / 1e4
        for k, v in s.items():
            rows.append(dict(official_class=k, osm_class=c, area_ha=round(v, 2)))
    M = pd.DataFrame(rows).pivot_table(index="official_class", columns="osm_class", values="area_ha", aggfunc="sum", fill_value=0)
    M = M.reindex(columns=["forest", "scrub_heath", "grassland", "none"], fill_value=0)
    M["total_ha"] = M.sum(1)
    M.round(1).reset_index().to_csv(OUT_V / "forest_vs_osm_comparison.csv", index=False)
    of = M.loc[M.index.isin(VEG_FOR_PROXIMITY)]
    off_fuel = of.total_ha.sum(); osm_fuel = M[["forest", "scrub_heath"]].values.sum()
    both = of[["forest", "scrub_heath"]].values.sum()
    tot = M.total_ha.sum()
    both_non = M.loc[~M.index.isin(VEG_FOR_PROXIMITY), ["grassland", "none"]].values.sum()
    st = dict(official_veg_ha=round(off_fuel, 1), osm_fuel_ha=round(osm_fuel, 1), both_ha=round(both, 1),
              official_veg_share_pct=round(100 * off_fuel / tot, 2), osm_fuel_share_pct=round(100 * osm_fuel / tot, 2),
              iou_pct=round(100 * both / (off_fuel + osm_fuel - both), 2),
              official_covered_by_osm_pct=round(100 * both / off_fuel, 2), osm_confirmed_by_official_pct=round(100 * both / osm_fuel, 2),
              overall_agreement_pct=round(100 * (both + both_non) / tot, 2), total_ha=round(tot, 1),
              matrix_ha=M.round(1).reset_index().to_dict("records"))
    # forest-only agreement
    ff = M.loc[M.index.str.startswith("forest_"), "forest"].sum()
    st["forest_only"] = dict(official_forest_ha=round(M.loc[M.index.str.startswith("forest_"), "total_ha"].sum(), 1),
                             osm_forest_ha=round(M["forest"].sum(), 1), both_ha=round(ff, 1))
    save_stats("forest_vs_osm", st)
    log("forest vs OSM:", {k: v for k, v in st.items() if k != "matrix_ha"})


# =============================================================================================== 4 PROXIMITY (official vegetation)
def _nearest(b_geoms, F, mask):
    """Exact planar distance footprint -> nearest polygon of F[mask] (1 km grid pieces, same union). Returns dist, class, objectid.
    Ties (e.g. footprint inside / touching several polygons): the polygon with the largest overlap with the footprint, then the
    largest piece."""
    sub = F[mask]
    pieces, pidx = _grid_pieces(sub.geometry.values)
    tree = shapely.STRtree(pieces)
    (bi, pj), dist = tree.query_nearest(b_geoms, return_distance=True, all_matches=True)
    df = pd.DataFrame(dict(bi=bi, pj=pj, d=dist))
    multi = df.bi.duplicated(keep=False)
    df["ov"] = 0.0
    if multi.any():
        m = df[multi]
        df.loc[multi, "ov"] = shapely.area(shapely.intersection(b_geoms[m.bi.values], pieces[m.pj.values]))
    df["pa"] = shapely.area(pieces[df.pj.values])
    df = df.sort_values(["bi", "ov", "pa"], ascending=[True, False, False]).drop_duplicates("bi")
    d = np.full(len(b_geoms), np.nan); d[df.bi.values] = df.d.values
    k = np.full(len(b_geoms), None, dtype=object); k[df.bi.values] = sub.veg_class.values[pidx[df.pj.values]]
    sc = np.full(len(b_geoms), None, dtype=object); sc[df.bi.values] = sub.veg_subclass.values[pidx[df.pj.values]]
    oid = np.full(len(b_geoms), -1, dtype="int64"); oid[df.bi.values] = sub.OBJECTID.values[pidx[df.pj.values]]
    return np.round(d, 2), k, sc, oid


def proximity():
    _use_official_in_tb()
    tp = OUT_T / "territory.gpkg"
    b = gpd.read_parquet(OUT_B / "_buildings_stage.parquet")
    F = gpd.read_file(OUT_V / "vegetation_forest_map_2024.gpkg", layer="vegetation_forest_map_2024", engine="pyogrio")
    log(f"proximity: {len(b)} buildings vs {int(F.is_veg_proximity.sum())} vegetation polygons (official)")
    g = b.geometry.values
    b["dist_veg_m"], b["veg_class_nearest"], b["veg_subclass_nearest"], b["veg_objectid_nearest"] = _nearest(g, F, F.is_veg_proximity == 1)
    # sensitivity definitions (not used by the rule)
    b["dist_grass_m"] = _nearest(g, F, F.veg_class == "grassland_pasture")[0]
    b["dist_veg_incl_grass_m"] = np.fmin(b.dist_veg_m, b.dist_grass_m)
    b["dist_forest_m"] = _nearest(g, F, F.veg_class.str.startswith("forest_"))[0]
    b["dist_veg_excl_mosaic_m"] = _nearest(g, F, (F.is_veg_proximity == 1) & (F.veg_subclass != "pasture_scrub_mosaic"))[0]
    b["dist_veg_excl_riparian_m"] = _nearest(g, F, (F.is_veg_proximity == 1) & (F.TIPES10 != 14))[0]
    b["near_veg_100"] = b.dist_veg_m <= VEG_RULE_M
    b["veg_rule_m"] = float(VEG_RULE_M)
    b["veg_source"] = VEG_SOURCE
    # edges: Gipuzkoa (as v0.2) and CAPV (the forest map stops at the CAPV border; Navarra not mapped)
    adm = gpd.read_file(tp, layer="municipalities_gipuzkoa")
    b["dist_gipuzkoa_edge_m"] = np.round(shapely.distance(g, shapely.union_all(adm.geometry.values).boundary), 1)
    capv = gpd.read_file(tp, layer="capv_extent").geometry.iloc[0]
    b["dist_capv_edge_m"] = np.round(shapely.distance(g, capv.boundary), 1)
    # brute-force validation on 300 random buildings (distance to the union of vegetation polygons)
    rng = np.random.default_rng(42); smp = rng.choice(len(b), 300, replace=False)
    vu = shapely.union_all(F.geometry[F.is_veg_proximity == 1].values)
    bf = shapely.distance(g[smp], vu)
    val_max = float(np.abs(bf - b.dist_veg_m.values[smp]).max())

    res = b[b.residential_flag == "residential"]
    def sens_rows(col, label):
        out = []
        for t in SENS_M:
            s = res[res[col] <= t]
            out.append(dict(definition=label, threshold_m=t, residential_buildings=len(s), share_of_residential_pct=round(100 * len(s) / len(res), 1),
                            dwellings_sum=int(s.dwellings.sum()), n_dwellings_null=int(s.dwellings.isna().sum()), all_buildings=int((b[col] <= t).sum())))
        return out
    sens = pd.DataFrame(sens_rows("dist_veg_m", "official: forest_* + scrub_heath"))
    sens.drop(columns="definition").to_csv(OUT_B / "sensitivity_veg_distance.csv", index=False)   # same columns as v0.2
    sdef = pd.DataFrame(sens_rows("dist_veg_m", "A official: forest_* + scrub_heath") +
                        sens_rows("dist_veg_incl_grass_m", "B A + grassland_pasture") +
                        sens_rows("dist_forest_m", "C forest_* only") +
                        sens_rows("dist_veg_excl_mosaic_m", "D A without pasture_scrub_mosaic (TIPES10 23)") +
                        sens_rows("dist_veg_excl_riparian_m", "E A without riparian gallery forest (TIPES10 14)"))
    osm_s = pd.read_csv(OUT_B / "sensitivity_veg_distance_osm.csv").assign(definition="v0.2 OSM forest + scrub_heath (OSM limits)")
    sdef = pd.concat([sdef, osm_s[sdef.columns]], ignore_index=True)
    sdef.to_csv(OUT_B / "sensitivity_veg_definition.csv", index=False)

    # ---- outputs (same columns as v0.2 + new ones)
    cols = ["building_id", "localid", "current_use", "use_codes", "dominant_use", "residential_share_pct", "dwellings",
            "residential_flag", "is_residential", "residential_rule", "muni_ine", "muni_name", "end_construction", "year_built",
            "endconstru_multi", "elevation", "floors_above", "height_above", "building_name", "address_eu", "address_es", "url_b5m",
            "has_cadastral_link", "unknown_named_house", "n_source_rows", "geom_fixed", "footprint_m2", "rep_x", "rep_y", "lon", "lat",
            "dist_veg_m", "near_veg_100", "veg_rule_m", "veg_source", "veg_class_nearest", "veg_subclass_nearest", "veg_objectid_nearest",
            "dist_veg_incl_grass_m", "dist_forest_m", "dist_veg_excl_mosaic_m", "dist_veg_excl_riparian_m", "dist_gipuzkoa_edge_m", "dist_capv_edge_m", "source_id", "geometry"]
    b = b[cols]
    bp = OUT_B / "buildings_tolosaldea.gpkg"; bp.unlink(missing_ok=True)
    tb.write_gpkg(b, bp, "buildings")
    pts = b.drop(columns="geometry").rename(columns={"rep_x": "x", "rep_y": "y", "muni_ine": "municipality_code",
                                                     "current_use": "source_use", "dist_veg_m": "veg_distance_m"})
    pts["near_vegetation"] = pts.near_veg_100.astype(int)
    tb.write_gpkg(gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts.x, pts.y), crs=CRS), bp, "buildings_rep_points")
    a = b[(b.residential_flag == "residential") & (b.dist_veg_m <= VEG_RULE_M)]
    A = a[["building_id", "muni_ine", "residential_flag", "dwellings", "dist_veg_m", "lon", "lat"]].assign(
        x=a.rep_x, y=a.rep_y, veg_class_nearest=a.veg_class_nearest)
    A.to_csv(OUT_B / "buildings_analysis_set.csv", index=False)

    # ---- diff vs the v0.2 OSM-based analysis set
    O = pd.read_csv(OUT_B / "buildings_analysis_set_osm.csv", dtype={"muni_ine": str})
    Bo = gpd.read_file(OUT_B / "buildings_tolosaldea_osm.gpkg", layer="buildings", engine="pyogrio", columns=["building_id", "dist_veg_m", "muni_ine"])
    Bo = pd.DataFrame(Bo.drop(columns="geometry")).set_index("building_id")
    bi = b.set_index("building_id")
    ids = sorted(set(A.building_id) | set(O.building_id))
    D = pd.DataFrame(dict(building_id=ids))
    D["in_osm_set"] = D.building_id.isin(O.building_id); D["in_official_set"] = D.building_id.isin(A.building_id)
    D["status"] = np.where(D.in_osm_set & D.in_official_set, "kept", np.where(D.in_official_set, "added", "removed"))
    D["muni_ine"] = D.building_id.map(bi.muni_ine).fillna(D.building_id.map(Bo.muni_ine))
    D["muni_ine_osm"] = D.building_id.map(Bo.muni_ine)
    D["dwellings"] = D.building_id.map(bi.dwellings).fillna(D.building_id.map(O.set_index("building_id").dwellings))
    D["dist_veg_osm_m"] = D.building_id.map(Bo.dist_veg_m)
    D["dist_veg_official_m"] = D.building_id.map(bi.dist_veg_m)
    D["veg_class_nearest"] = D.building_id.map(bi.veg_class_nearest)
    D["reason"] = np.select(
        [D.status == "kept", (D.status == "removed") & D.dist_veg_official_m.isna(), D.status == "removed",
         (D.status == "added") & D.dist_veg_osm_m.isna(), D.status == "added"],
        ["", "left pilot (official limits)", "official dist > 100 m", "entered pilot (official limits)", "official dist <= 100 m, OSM > 100 m"], "")
    D.to_csv(OUT_B / "analysis_set_diff_vs_osm.csv", index=False)
    nm = gpd.read_file(tp, layer="tolosaldea_municipalities").set_index("ine_code")["name"]
    M = D.groupby("muni_ine").apply(lambda x: pd.Series(dict(
        n_osm=int(x.in_osm_set.sum()), n_official=int(x.in_official_set.sum()), added=int((x.status == "added").sum()),
        removed=int((x.status == "removed").sum()), dwellings_osm=int(x.loc[x.in_osm_set, "dwellings"].sum()),
        dwellings_official=int(x.loc[x.in_official_set, "dwellings"].sum()))), include_groups=False).reset_index()
    M.insert(1, "name", M.muni_ine.map(nm))
    tot = M.drop(columns=["muni_ine", "name"]).sum(); tot["muni_ine"] = "TOTAL"; tot["name"] = "Tolosaldea"
    M = pd.concat([M, tot.to_frame().T], ignore_index=True)
    M.to_csv(OUT_B / "analysis_set_diff_by_municipality.csv", index=False)

    # ---- quality per municipality (same columns as v0.2)
    dup = pd.read_csv(OUT_B / "duplicates_removed.csv", dtype={"muni_ine": str})
    munis = pd.read_csv(OUT_T / "municipalities.csv", dtype={"ine_code": str})
    gg = b.groupby("muni_ine")
    q = pd.DataFrame(dict(
        n_buildings=gg.size(), n_residential=gg.is_residential.sum(),
        n_non_residential=gg.residential_flag.apply(lambda s: (s == "non_residential").sum()),
        n_unknown_use=gg.residential_flag.apply(lambda s: (s == "unknown").sum()),
        n_with_dwellings=gg.dwellings.apply(lambda s: s.notna().sum()), n_dwellings_pos=gg.dwellings.apply(lambda s: (s > 0).sum()),
        sum_dwellings=gg.dwellings.sum(), invalid_geoms_fixed=gg.geom_fixed.sum(),
        n_res_dist_le100=gg.apply(lambda x: ((x.residential_flag == "residential") & (x.dist_veg_m <= 100)).sum(), include_groups=False),
        dwellings_analysis_set=gg.apply(lambda x: x.loc[(x.residential_flag == "residential") & (x.dist_veg_m <= 100), "dwellings"].sum(), include_groups=False),
        n_unknown_named_house_le100=gg.apply(lambda x: (x.unknown_named_house & (x.dist_veg_m <= 100)).sum(), include_groups=False),
        n_res_within_500m_of_gipuzkoa_edge=gg.apply(lambda x: ((x.residential_flag == "residential") & (x.dist_gipuzkoa_edge_m <= 500)).sum(), include_groups=False),
    )).reset_index()
    q["dup_rows_removed_same_id"] = q.muni_ine.map(dup[dup.rule.str.startswith("R-DUP-ID")].groupby("muni_ine").size()).fillna(0).astype(int)
    q["dup_removed_same_geom"] = q.muni_ine.map(dup[dup.rule.str.startswith("R-DUP-GEOM")].groupby("muni_ine").size()).fillna(0).astype(int)
    q = munis[["ine_code", "name_eu"]].merge(q, left_on="ine_code", right_on="muni_ine", how="left").drop(columns="muni_ine")
    tot = q.drop(columns=["ine_code", "name_eu"]).sum(); tot["ine_code"] = "TOTAL"; tot["name_eu"] = "Tolosaldea"
    q = pd.concat([q, tot.to_frame().T], ignore_index=True)
    q.to_csv(OUT_B / "quality_by_municipality.csv", index=False)

    # ---- CAPV-edge check: buildings near the Navarra border may miss vegetation that the forest map does not cover
    edge = res[(res.dist_capv_edge_m <= 300)]
    O2 = gpd.read_file(OUT_V / "vegetation_osm_provisional.gpkg", layer="vegetation_osm_provisional", where="is_fuel = 1")
    O2 = O2.geometry.values
    out_capv = shapely.difference(shapely.union_all(O2), capv)
    d_out = shapely.distance(edge.geometry.values, out_capv) if len(edge) else np.array([])
    flip = int(((edge.dist_veg_m > VEG_RULE_M).values & (d_out <= VEG_RULE_M)).sum()) if len(edge) else 0
    st = dict(n=len(b), dist_null=int(b.dist_veg_m.isna().sum()), inside_veg=int((b.dist_veg_m == 0).sum()),
              res_inside_veg=int((res.dist_veg_m == 0).sum()), validation_max_abs_diff_m=round(val_max, 4),
              analysis_set=len(A), analysis_dwellings=int(A.dwellings.sum()), analysis_dw_null=int(A.dwellings.isna().sum()),
              analysis_by_veg_class=A.veg_class_nearest.value_counts().to_dict(),
              analysis_by_veg_subclass=a.veg_subclass_nearest.value_counts().to_dict(),
              sensitivity=sens.to_dict("records"), sensitivity_definitions=sdef.to_dict("records"),
              diff=dict(kept=int((D.status == "kept").sum()), added=int((D.status == "added").sum()), removed=int((D.status == "removed").sum()),
                        reasons=D[D.status != "kept"].reason.value_counts().to_dict(),
                        added_dwellings=int(D.loc[D.status == "added", "dwellings"].sum()), removed_dwellings=int(D.loc[D.status == "removed", "dwellings"].sum())),
              unknown_named_house_le100=int((b.unknown_named_house & (b.dist_veg_m <= 100)).sum()),
              unknown_le100=int(((b.residential_flag == "unknown") & (b.dist_veg_m <= 100)).sum()),
              res_within_300m_capv_edge=len(edge), res_within_100m_capv_edge=int((res.dist_capv_edge_m <= 100).sum()),
              res_near_capv_edge_would_flip_with_osm_navarra_veg=flip,
              res_within_500m_gip_edge=int(((b.residential_flag == "residential") & (b.dist_gipuzkoa_edge_m <= 500)).sum()),
              analysis_only_via_riparian=int((a.dist_veg_excl_riparian_m > VEG_RULE_M).sum()),
              analysis_only_via_riparian_by_muni=a[a.dist_veg_excl_riparian_m > VEG_RULE_M].muni_name.value_counts().head(8).to_dict(),
              median_dist_veg_res_m=float(res.dist_veg_m.median()))
    save_stats("proximity", st)
    (OUT_B / "_buildings_stage.parquet").unlink(missing_ok=True)
    log("proximity done", {k: st[k] for k in ("analysis_set", "analysis_dwellings", "diff", "validation_max_abs_diff_m")})


# =============================================================================================== 5 SOURCES
SUPERSEDED_NOTE = ("SUPERSEDED in v0.3 (2026-10-01) for municipal limits by SRC-GV-MUNICIPIOS5000-20250507 and for vegetation by "
                   "SRC-GV-INVFORESTAL-2024 (OSM-based files kept as processed/territory/*_osm.*, processed/buildings/*_osm.*, "
                   "processed/vegetation/vegetation_osm_provisional.gpkg; not deleted)")


def sources():
    """Upsert the two official rows; mark the OSM limits/vegetation uses as superseded. Other agents' rows are untouched."""
    p = REPORTS / "sources.csv"
    S = pd.read_csv(p, dtype=str)
    cols = list(S.columns)
    st = load_stats()
    rows = [
        dict(source_id=SRC_MUNI, dataset="Límites municipales de la CAPV 1:5.000 (MUNICIPIOS_5000_ETRS89, geoEuskadi) - PRIMARY municipal limits from v0.3",
             organisation="Gobierno Vasco - Dirección de Planificación Territorial y Agenda Urbana (geoEuskadi)",
             url="https://www.geo.euskadi.eus/cartografia/DatosDescarga/Limites/MUNICIPIOS_5000_ETRS89.zip",
             licence="Any use with attribution 'Eusko Jaurlaritza / Gobierno Vasco'", download_date="2026-10-01",
             edition_or_period="updated 07/05/2025 (download page); shapefile DBF date 2025-03-21; 1:5,000",
             raw_file="raw/MUNICIPIOS_5000_ETRS89.zip",
             processed_files="processed/territory/territory.gpkg; tolosaldea_municipalities.geojson; tolosaldea_boundary.geojson; municipalities.csv; municipality_parts.csv; territory_comparison_osm.csv",
             notes=(f"sha256={tb.sha256(MUNI_ZIP)}; EPSG:25830; {st['limits']['n_features']} units (CAPV); key EUSTAT (= INE 5-digit code); "
                    "28 Tolosaldea municipalities = field A_FUNC_CAS 'TOLOSALDEA' (checked); 5xx codes = parzonerías (context, not in pilot); "
                    "download page states: not official cartography under Ley 7/1986 / RD 1545/2007, some lines provisional; "
                    "via the browser on Carlos's PC (reports/collector_downloads.md)")),
        dict(source_id=SRC_FOREST, dataset="Mapa Forestal del País Vasco 2024 / Inventario Forestal 1:10.000 (INV_FORESTAL_2024_10000_ETRS89) - PRIMARY vegetation from v0.3",
             organisation="Gobierno Vasco - Dpto. Agricultura, Pesca y Política Alimentaria",
             url="https://www.geo.euskadi.eus/cartografia/DatosDescarga/Agricultura/INV_FORESTAL_2024_10000_ETRS89.zip",
             licence="Any use with attribution 'Eusko Jaurlaritza / Gobierno Vasco'", download_date="2026-10-01",
             edition_or_period="edition 2024 (data to 31/12/2024, updated 06/03/2025 per download page); DBF/XML dates 2025-03-05/06; 1:10,000; min patch 0.10 ha",
             raw_file="raw/INV_FORESTAL_2024_10000_ETRS89.zip",
             processed_files="processed/vegetation/vegetation_forest_map_2024.gpkg; class_dictionary.csv; forest_area_by_class.csv; forest_vs_osm_comparison.csv; processed/buildings/* (dist_veg_m, analysis set)",
             notes=(f"sha256={tb.sha256(FOREST_ZIP)}; EPSG:25830; {st['forest']['n_features_capv']} polygons CAPV, PolygonZ (forced 2D); "
                    "read from the zip with a bbox (Tolosaldea + 2 km); no date attribute in the table; covers CAPV only (Navarra not mapped); "
                    "ISO metadata https://www.geo.euskadi.eus/contenidos/ds_geograficos/md_ideeu_invent_forestal/es_def/data/md_ideeu_invent_forestal_es.xml")),
    ]
    S = S[~S.source_id.isin([SRC_MUNI, SRC_FOREST])]
    for sid in (SRC_OSM, "SRC-OSM-GEOFABRIK-PV-20260930"):
        m = S.source_id == sid
        if m.any() and "SUPERSEDED in v0.3" not in str(S.loc[m, "notes"].iloc[0]):
            extra = SUPERSEDED_NOTE if sid == SRC_OSM else "v0.3: its use for municipal limits and vegetation is " + SUPERSEDED_NOTE + "; still the source of the road network"
            S.loc[m, "notes"] = S.loc[m, "notes"].fillna("") + "; " + extra
    if (S.source_id == SRC_OSM).any():
        S.loc[S.source_id == SRC_OSM, "processed_files"] = ("processed/territory/*_osm.*; processed/vegetation/vegetation_osm_provisional.gpkg; "
                                                            "processed/buildings/*_osm.* (v0.2, superseded)")
    S = pd.concat([S, pd.DataFrame(rows)[cols]], ignore_index=True)
    S.to_csv(p, index=False)
    log("sources.csv: official rows upserted, OSM rows marked superseded")


# =============================================================================================== 6 REPORT
V03_MARKER = "<!-- v0.3-official-layers -->"
V03_BANNER = "<!-- v0.3-banner -->"


def _md(df):
    df = df.copy()
    out = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "|".join("---" for _ in df.columns) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) or v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def report():
    S = load_stats()
    L, B, BO, F, FO, P = S["limits"], S["buildings"], S["buildings_official"], S["forest"], S["forest_vs_osm"], S["proximity"]
    comp = pd.read_csv(OUT_T / "territory_comparison_osm.csv", dtype={"ine_code": str})
    ch = pd.read_csv(OUT_B / "building_municipality_changes.csv", dtype={"muni_osm": str, "muni_official": str})
    cc = pd.read_csv(ROOT / "processed/candidates/candidates_municipality_check_v03.csv")
    ac = pd.read_csv(OUT_V / "forest_area_by_class.csv")
    D = pd.read_csv(OUT_V / "class_dictionary.csv")
    M = pd.read_csv(OUT_V / "forest_vs_osm_comparison.csv")
    sens = pd.read_csv(OUT_B / "sensitivity_veg_definition.csv")
    dm = pd.read_csv(OUT_B / "analysis_set_diff_by_municipality.csv")
    U = L["osm_union"]; PM = L["osm_per_muni"]
    by = ac.groupby("veg_class")[["area_ha_tolosaldea", "share_tolosaldea_pct"]].sum().round(1).reset_index()
    vs = sens.pivot_table(index="definition", columns="threshold_m", values="residential_buildings").astype(int).reset_index()
    vs.columns = [str(c) if c == "definition" else f"res ≤{c} m" for c in vs.columns]
    dsum = D.groupby(["veg_class", "class_group", "is_veg_proximity"]).agg(n_codes=("class_code", "size"), area_ha_capv=("area_ha_capv", "sum"),
                                                                           area_ha_tolosaldea=("area_ha_tolosaldea", "sum")).round(0).astype({"area_ha_capv": int, "area_ha_tolosaldea": int}).reset_index()
    tip = D.groupby(["TIPES10", "TIPES_es", "veg_class"]).agg(area_ha_tolosaldea=("area_ha_tolosaldea", "sum")).round(1).reset_index()
    tip = tip[tip.area_ha_tolosaldea > 0]
    moved_res = ch[ch.residential_flag == "residential"][["building_id", "change", "muni_osm_name", "muni_official_name", "dwellings",
                                                          "in_analysis_set_osm", "dist_official_muni_border_m"]]
    d = P["diff"]
    txt = f"""{V03_MARKER}
## 7. v0.3 official layers (2026-10-01/02, `code/official_layers.py`)

**This section supersedes §1 (OSM limits), §3 (OSM vegetation) and §4 (proximity) above, which are kept as the v0.2 record.**
Primary files now come from the official geoEuskadi layers; the v0.2 OSM-based files are kept with an `_osm` suffix
(`processed/territory/*_osm.*`, `processed/buildings/*_osm.*`, `processed/vegetation/vegetation_osm_provisional.gpkg`).
Re-run: `python3 code/official_layers.py backup limits buildings forest proximity sources report` (~5 min; raw zips read in place via `/vsizip/`).
Sources: `{SRC_MUNI}`, `{SRC_FOREST}` in `reports/sources.csv`; OSM rows marked SUPERSEDED (not deleted).

### 7.1 Official municipal limits (MUNICIPIOS_5000_ETRS89)
- {L['n_features']} units for the CAPV (fields `EUSTAT`, `NOMBRE_TOP`, `MUN_PROV`, `COMARCA`, `A_FUNC_CAS`, `IDTOPONIMO`, …), 0 invalid geometries, DBF date {L['dbf_last_update']}
  (download page: updated 07/05/2025; page warns it is *not official cartography* under Ley 7/1986 / RD 1545/2007 and some lines are provisional).
- Key: `EUSTAT` (5-digit code = INE municipal code). Gipuzkoa: **{L['gipuzkoa_municipalities']} municipalities** (same 88 codes as OSM: {L['gipuzkoa_codes_equal_osm']}) +
  3 non-municipal units (5xx codes: {', '.join(n for _, n in L['gipuzkoa_non_municipal'])}) kept in layer `context_non_municipal` with the other CAPV parzonerías and the shared
  "Limitadua / El Limitado" (EUSTAT 01003 / 48072 appear twice for that reason).
- **28/28 pilot municipalities found** (missing: {L['pilot_missing'] or 'none'}). Independent check: the official functional-area field `A_FUNC_CAS = 'TOLOSALDEA'` gives exactly the
  same 28 ({L['afunc_tolosaldea_equals_pilot']}); the *comarca* TOLOSALDEA adds Legorreta (20052, functional area Goierri), which stays out.
- Names: `name` = official `NOMBRE_TOP` (e.g. 20075 "Villabona"); `name_eu`/`name_es` carried from v0.2 by INE code.
- Sum of the 28 areas = union = **{L['union_area_km2']} km²** (overlap {L['overlap_km2']} km²). The union contains {L['union_sliver_holes']['n']} zero-area rings
  (digitising gaps between neighbours, total {L['union_sliver_holes']['total_m2']} m²), removed in the boundary only. Union = {L['union_parts']} parts
  (main {L['union_part_areas_km2'][0]} km² + detached exclaves {', '.join(map(str, L['union_part_areas_km2'][1:]))} km²: Bidania-Goiatz and Zizurkil, as in OSM).
- Multipart municipalities: {', '.join(f"{n} ({k})" for _, n, k in L['multipart'])} — same part counts as OSM for all 28 (Tolosa's detached southern part = 12.04 km²).
- Enirio-Aralar (20506) is the only non-municipal unit adjacent to the pilot (outside, as in v0.2).

**Official vs OSM (v0.2).** Union: official {U['area_official_km2']} km² vs OSM {U['area_osm_km2']} km² (**{U['area_diff_pct']} %**), IoU **{U['iou']}**,
Hausdorff {U['hausdorff_m']} m, symmetric difference {U['sym_diff_km2']} km². Per municipality: |area diff| ≤ {PM['area_diff_abs_max_pct']} % (Larraul),
IoU {PM['iou_min']}–{comp.iou.max()} (median {PM['iou_median']}), Hausdorff median {PM['hausdorff_median_m']} m / max {PM['hausdorff_max_m']} m ({PM['hausdorff_max_muni']}).
Exclaves: identical number of parts per municipality; exclave areas within 0.1 km². OSM was a good stand-in; the differences are border digitising (tens to ~250 m).
Full table: `processed/territory/territory_comparison_osm.csv`.

{_md(comp[["ine_code", "name", "area_official_km2", "area_osm_km2", "area_diff_pct", "iou", "hausdorff_m", "parts_official", "parts_osm"]])}

**Buildings re-assigned by representative point** (same B5M cleaning rules and INSPIRE ids as v0.2, run against the official polygons):
{BO['n_osm']:,} → **{BO['n_official']:,} buildings**: **{BO['entered']} entered** the pilot (1 residential, 1 dwelling: `ES.GFA.BU.40995`, Abaltzisketa; 11 unknown-use),
**{BO['left']} left** (unknown use, now in Legorreta) and **{BO['municipality_changed']} changed municipality** inside the pilot
({sum(n for f, r, n in BO['by_change_flag'] if f == 'municipality_changed' and r == 'residential')} residential, {BO['dwellings_by_change'].get('municipality_changed', 0)} dwellings;
largest moves Altzo→Tolosa 22, Tolosa→Leaburu 16, Zizurkil→Aduna 10). All changes lie within 160 m of the official municipal border (median
{BO['dist_official_muni_border_m'].get('50%')} m). {BO['changes_in_osm_analysis_set']} changed buildings were in the v0.2 analysis set. List: `processed/buildings/building_municipality_changes.csv`.
Residential buildings affected:

{_md(moved_res)}

Residential totals: 5,291 → {B['use_tol']['residential']:,}; unknown 7,746 → {B['use_tol']['unknown']:,}; non-residential unchanged ({B['use_tol']['non_residential']}).

**Candidates (report only, not moved):** all 10 `candidates_10.csv` sites fall in the same municipality with the official limits
({int(cc.municipality_changed.sum())} changes; closest to a border: {cc.sort_values('dist_to_muni_border_m').iloc[0]['cand_id']} at {cc.dist_to_muni_border_m.min()} m).
Candidate pool: 1 of {BO['pool_sites_ok']} usable sites changes pilot status (`POOL-0128` enters the pilot, Aduna) → `processed/candidates/pool_municipality_changes_v03.csv`.
`processed/candidates/candidates_municipality_check_v03.csv`.

### 7.2 Mapa Forestal del País Vasco 2024 (INV_FORESTAL_2024_10000_ETRS89)
- Shapefile in the zip ({F['n_features_capv']:,} PolygonZ, CAPV {F['capv_area_km2']} km², tessellation of the whole territory). Read with pyogrio from `/vsizip/` with bbox =
  Tolosaldea boundary + 2 km ({F['n_bbox']:,} polygons in {F['read_bbox_s']} s, < 0.4 GB RAM); {F['n_intersecting_clip']:,} intersect the clip; {F['invalid_fixed']} invalid geometries made valid; Z dropped.
- **Clip**: official boundary + 2 km (not cut at the Tolosaldea border; polygons crossing the 2 km line are cut there, `clipped` = true, `area_orig_ha` keeps the full area).
  Clip = {F['clip_area_km2']} km², of which **{F['clip_outside_capv_km2']} km² is Navarra, where the forest map has no data**. Coverage inside Tolosaldea = {F['tolosaldea_area_covered_ha']} ha
  = 100 % of the boundary ({F['tolosaldea_area_ha']} ha).
- **Edition / dates — what the data says:** no date or edition attribute in the table (fields: {', '.join(F['fields'][:12])}, …).
  DBF last update {F['dbf_last_update']}; zip members dated 2025-03-06; ArcGIS XML CreaDate {F['xml_dates']['CreaDate'][0]}, ModDate {F['xml_dates']['ModDate'][0]};
  source GDB feature class `{F['xml_source_gdb'][0]}`. The download page says edition 2024, data to 31/12/2024, updated 06/03/2025 — consistent.
  The XML has no field descriptions; code meanings below come from the `_es`/`_eu` label fields.
- Main fields (clip): `TIPES10` land-cover type (25 values in the clip, 36 in the CAPV) with `TIPES_es/_eu`; `SP1..SP3` species code + names, `O1..O3` occupation (tenths),
  `E1..E3`/`EMASA1..3` development state (Repoblado, Monte bravo, Latizal, Fustal, Tala); `FCCARB`/`FCCMAT`/`FCCHER` tree/shrub/herb cover %; `FORARB`, `FORMAT`, `DISTRIB`, `HMMAT`, `ATRIBUTO`, `OSUPTIP`, `OCUOSUP`.
  `MODCOM_I` (0–10) follows the pattern of the Rothermel/ICONA fuel models (0 on urban/water, 1–3 on meadows/grass, 4–7 on scrub, 8–10 on forest) — **inferred, not documented in the file; to confirm in the ISO metadata**. Kept, not used.
  Development state of forest in Tolosaldea (ha): {F['dev_state_tolosaldea_ha']}.

**Class dictionary** (`processed/vegetation/class_dictionary.csv`, {len(D)} codes = every TIPES10 × SP1 combination in the CAPV; original codes and names kept on every polygon):
- `TIPES10` 11 Bosque / 14 Bosque de galería → **forest_conifer / forest_broadleaf / forest_mixed** by leaf type of `SP1` (name-based list of conifers; eucalyptus = broadleaf);
  **forest_mixed** when `SP1` is a mixed code ("Plantaciones de frondosas y coníferas variadas") or the 2nd species is of the other leaf type with `O2` ≥ {MIX_O2}/10 (`|MIX` in `class_code`, {F['mixed_rule_polygons']} polygons in the clip).
- 12 Bosque de plantación → **forest_plantation** (subclass plantation_conifer / _broadleaf / _eucalyptus / _mixed).
- 21 Arbustedos → **scrub_heath** (scrub); 23 Pastizal-Matorral → **scrub_heath** (pasture_scrub_mosaic: mean shrub cover 44 %, herb 52 %, fuel-model codes 5–7).
- 31 Herbazal-pastizal, 73 Prados, 74 Prados con setos → **grassland_pasture**.
- all other types → **non_forest_other** (agricultural 71/75, artificial 8xx, bare_rock 44x, water_wetland 5xx/6xx).
- `class_group` = the schema's `vegetation_classes.class_group` list (plantations by leaf type); layer `vegetation_db` in the GeoPackage is ready for the `vegetation` table.

{_md(dsum)}

**Area within Tolosaldea** (exact intersection with the official boundary; `forest_area_by_class.csv`):

{_md(by)}

Vegetation for proximity (forest_* + scrub_heath) = **{FO['official_veg_ha']:,} ha = {FO['official_veg_share_pct']} % of Tolosaldea**. Natural conifer stands are
negligible (4 ha): conifers are plantations (Pinus radiata {F['top_species_tolosaldea_ha'].get('Pino radiata')} ha, larch {F['top_species_tolosaldea_ha'].get('Alerce')} ha,
P. nigra {F['top_species_tolosaldea_ha'].get('Pino laricio')} ha, Douglas fir {F['top_species_tolosaldea_ha'].get('Abeto Douglas')} ha); beech {F['top_species_tolosaldea_ha'].get('Haya')} ha,
Atlantic mixed broadleaf {F['top_species_tolosaldea_ha'].get('Bosque mixto atlántico')} ha, pedunculate oak {F['top_species_tolosaldea_ha'].get('Roble pedunculado')} ha. Eucalyptus 51 ha.

**Comparison with the OSM provisional layer** (inside the official boundary; one OSM class per location, forest > scrub_heath > grassland > none; ha):

{_md(M)}

- Forest + scrub: official {FO['official_veg_ha']:,} ha ({FO['official_veg_share_pct']} %) vs OSM {FO['osm_fuel_ha']:,} ha ({FO['osm_fuel_share_pct']} %); both {FO['both_ha']:,} ha.
  **IoU {FO['iou_pct']} %**; {FO['osm_confirmed_by_official_pct']} % of OSM fuel is official vegetation, but OSM only covers {FO['official_covered_by_osm_pct']} % of the official vegetation;
  overall agreement (veg / non-veg) **{FO['overall_agreement_pct']} %**.
- OSM misses ~{int(M.loc[M.official_class.isin(VEG_FOR_PROXIMITY), 'none'].sum()):,} ha of official forest/scrub (mostly small patches, riparian strips and plantations near farms and towns) and
  OSM scrub is almost absent (official scrub_heath is mapped as OSM forest or nothing). OSM "forest" includes {M.loc[M.official_class == 'grassland_pasture', 'forest'].iloc[0]:,} ha of official meadow/pasture.

### 7.3 Building–vegetation proximity (official)
- **Vegetation for proximity = `veg_class` in {{forest_conifer, forest_broadleaf, forest_mixed, forest_plantation, scrub_heath}}** (TIPES10 11, 12, 14, 21, 23).
  grassland_pasture (31, 73, 74) and non_forest_other are excluded. `dist_veg_m` = planar distance from the building **footprint** to the nearest such polygon (0 = touches/inside),
  1 km grid pieces + STRtree; brute-force check on 300 random buildings: max difference {P['validation_max_abs_diff_m']} m; NULL distances {P['dist_null']}.
  `veg_class_nearest` / `veg_subclass_nearest` / `veg_objectid_nearest` = the nearest polygon (ties: largest overlap with the footprint).
- `buildings_tolosaldea.gpkg` (layers `buildings`, `buildings_rep_points`): same columns as v0.2 + `veg_class_nearest`, `veg_subclass_nearest`, `veg_objectid_nearest`,
  `dist_veg_incl_grass_m`, `dist_forest_m`, `dist_veg_excl_mosaic_m`, `dist_veg_excl_riparian_m`, `dist_capv_edge_m`; `veg_source` = "{VEG_SOURCE}"; `near_veg_100` / `near_vegetation` = dist ≤ 100 m.

**Analysis set (residential AND dist_veg_m ≤ 100 m): {P['analysis_set']:,} buildings, {P['analysis_dwellings']:,} dwellings** (NULL dwellings {P['analysis_dw_null']})
→ `processed/buildings/buildings_analysis_set.csv` (v0.2 columns + `veg_class_nearest`). v0.2 (OSM): 1,747 buildings / 4,576 dwellings.
Nearest class in the set: {P['analysis_by_veg_class']}. Residential buildings inside/touching vegetation: {P['res_inside_veg']}; median residential distance {P['median_dist_veg_res_m']} m.

Sensitivity — residential buildings by threshold and vegetation definition (`sensitivity_veg_definition.csv`; dwellings there too):

{_md(vs)}

Including grassland would put 87 % of residential buildings within 100 m (the rule would stop discriminating); excluding the pasture-scrub mosaic changes 1 building;
riparian galleries alone bring {P['analysis_only_via_riparian']} buildings into the set (Asteasu 76, Tolosa 56, Berastegi 32, …).

**Diff vs the v0.2 OSM-based set** (`analysis_set_diff_vs_osm.csv`, `analysis_set_diff_by_municipality.csv`): kept {d['kept']:,}, **added {d['added']:,}**
({d['added_dwellings']:,} dwellings; {d['reasons'].get('official dist <= 100 m, OSM > 100 m', 0)} because the official map has vegetation ≤ 100 m where OSM had none,
{d['reasons'].get('entered pilot (official limits)', 0)} entered with the official limits), **removed {d['removed']:,}** ({d['removed_dwellings']:,} dwellings; all because official vegetation is > 100 m,
mostly OSM forest polygons over what the official map classes as meadow — Zizurkil −126, Villabona −85, Asteasu −84, Aduna −52).
Building IDs are unchanged (INSPIREID), so travel times can be reused for every building that existed in v0.2.

{_md(dm)}

### 7.4 Open issues (v0.3)
1. **link_build / DB not rebuilt here** (weather agent working; main agent rebuilds). Required: (a) the official limits add 12 buildings without travel times and change
   `municipality_code` for 99 → `building_snap.parquet` holds v0.2 municipalities and `stage_db` asserts every building has a snap: **run the `times` stage once without
   `--reuse-times`** (or snap/route only the 12 new ids); (b) `stage_db` still loads `vegetation_osm_provisional.gpkg` with OSM classes and labels municipalities/boundary with the OSM
   source id — switch to layer `vegetation_db` of `vegetation_forest_map_2024.gpkg` (+ `class_dictionary.csv` → `vegetation_classes`) and `{SRC_MUNI}`; (c) `DATA_VERSION` string still says v0.2-provisional-veg.
   Candidates were selected with the v0.2 (OSM) analysis set; the set nearly doubled, so the deficit clusters and possibly the candidates change on a `select` re-run.
2. **Navarra gap**: the forest map stops at the CAPV border ({F['clip_outside_capv_km2']} km² of the clip). Only {P['res_within_300m_capv_edge']} residential buildings are within 300 m of the CAPV edge
   ({P['res_within_100m_capv_edge']} within 100 m); adding OSM fuel outside the CAPV flips {P['res_near_capv_edge_would_flip_with_osm_navarra_veg']} of them → negligible, no mixing of sources.
3. Proximity threshold 100 m and the vegetation definition (riparian strips, pasture-scrub mosaic) remain team decisions; with the official map 62.9 % of residential buildings are ≤ 100 m.
4. `MODCOM_I` interpretation (fuel model) and the meaning of `FORMAT`/`FORARB`/`ATRIBUTO` codes to confirm in the ISO metadata (not reachable from the sandbox).
5. {P['unknown_named_house_le100']} unknown-use buildings named as house/farmhouse are ≤ 100 m from vegetation (excluded by the residential rule; was 165).
6. Official-limits page warns the lines are not official cartography and some are provisional; Udalmap/Eustat area check (±2 %) still to do offline.
"""
    out = REPORTS / "quality_territory_buildings.md"
    cur = out.read_text(encoding="utf-8")
    cur = cur.split(V03_MARKER, 1)[0].rstrip()
    banner = (f"{V03_BANNER}\n> **v0.3 (official layers):** limits = geoEuskadi MUNICIPIOS_5000, vegetation = Mapa Forestal 2024. See **§7**; §1–§6 are the v0.2 (OSM) record.\n")
    if V03_BANNER not in cur:
        lines = cur.split("\n", 1)
        cur = lines[0] + "\n\n" + banner + ("\n" + lines[1] if len(lines) > 1 else "")
    out.write_text(cur + "\n\n" + txt, encoding="utf-8")
    log("report: section 7 written")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["backup", "limits", "buildings", "forest", "proximity", "sources", "report"]
    for s in steps:
        globals()[s]()
