#!/usr/bin/env python3
"""Map data for the chat app's forest map (static/forest.jpg + static/map.json).

    conda run -n flaire python 05_codigo/chat_app/build_map.py

- forest.jpg: the Mapa Forestal 2024 (Gobierno Vasco) clipped to Tolosaldea, drawn once in the page's colours:
  woodland green, shrub darker, everything else near-black. No homes on it; the page draws those live.
- map.json: the 3,331 homes (position as a fraction of the image, priority, travel time from the nearest of the
  9 parks and from each of the 10 study sites, light vehicle, delivered CSVs), the parks, the sites and the nested
  steps. The page decides "within 12 min" itself, with the same rule as the agent's tools; the numbers are pinned
  by 05_codigo/tests_pipeline/test_map_data.py (2,712 / 2,958 / 3,083 / 3,187, Alta 49 / 119 / 165 / 177).
"""
from __future__ import annotations

import io
import json
import math
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd
from PIL import Image
from pyproj import Transformer

import fotos

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "agent" / "data"
FOREST = REPO / "data" / "external" / "vegetation_forest_map_2024.gpkg"
SCREENS = REPO / "app" / "data" / "tolosaldea.json"
BOUNDARY = REPO / "data" / "external" / "flaire_lite.gpkg"
OUT_IMG = HERE / "static" / "forest.jpg"
OUT_JSON = HERE / "static" / "map.json"

WIDTH_PX = 2000
PAD = 0.06  # margin around the homes, as a share of the extent
FILL = {"Bosque": "#22402f", "Bosque de Galeria": "#22402f", "Bosque de Plantacion": "#1b3326",
        "Arbustedos": "#1a2a22", "Pastizal-Matorral": "#172520", "Cursos de agua": "#14212a",
        "Pantano, embalse": "#14212a"}
OTHER, GROUND = "#121619", "#0e1013"
CANDS = [f"CAND-{i:02d}" for i in range(1, 11)]
STEPS = [[], ["CAND-02"], ["CAND-01", "CAND-02"], ["CAND-01", "CAND-02", "CAND-03"]]


def extent(xs, ys):
    """Homes' bounding box plus a margin, EPSG:25830."""
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    px, py = (x1 - x0) * PAD, (y1 - y0) * PAD
    return x0 - px, y0 - py, x1 + px, y1 + py


def draw_forest(box) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    h_px = round(WIDTH_PX * (y1 - y0) / (x1 - x0))
    v = gpd.read_file(FOREST, layer="vegetation_forest_map_2024").to_crs(25830)
    fig = plt.figure(figsize=(WIDTH_PX / 100, h_px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    fig.patch.set_facecolor(GROUND)
    ax.set_facecolor(GROUND)
    v.plot(ax=ax, color=v.TIPES_es.map(FILL).fillna(OTHER), linewidth=0)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=GROUND)
    plt.close(fig)
    img = Image.open(buf).convert("RGB")
    img.save(OUT_IMG, "JPEG", quality=84, optimize=True, progressive=True)
    return img.size


def _t(v):
    # Round UP to 0.1 min: plain rounding turns 12.04 into 12.0 and wrongly lights the home at "≤ 12 min".
    return None if pd.isna(v) else math.ceil(float(v) * 10 - 1e-9) / 10


def main():
    screens = json.loads(SCREENS.read_text(encoding="utf-8"))
    times = pd.read_csv(DATA / "tiempos_ligero.csv").set_index("building_id")
    prio = pd.read_csv(DATA / "edificios_prioridad.csv").set_index("building_id").prioridad
    parks = [c for c in times.columns if c not in CANDS]
    to25830 = Transformer.from_crs(4326, 25830, always_xy=True)

    b = screens["buildings"]
    xs, ys = to25830.transform([h["lon"] for h in b], [h["lat"] for h in b])
    box = extent(xs, ys)
    x0, y0, x1, y1 = box
    fx = lambda x: round((x - x0) / (x1 - x0), 4)  # noqa: E731  (0 = left edge of the image)
    fy = lambda y: round((y1 - y) / (y1 - y0), 4)  # noqa: E731  (0 = top edge)

    homes = []
    for h, x, y in zip(b, xs, ys):
        row = times.loc[h["id"]]
        homes.append([fx(x), fy(y), prio[h["id"]][0], _t(row[parks].min())] + [_t(row[c]) for c in CANDS])

    def place(items):
        out = []
        for it in items:
            x, y = to25830.transform(it["lon"], it["lat"])
            out.append({k: it[k] for k in ("id", "name") if k in it} | {"x": fx(x), "y": fy(y),
                       **({"municipality": it["municipality"]} if "municipality" in it else {})})
        return out

    # Stations outside Tolosaldea still count for coverage, but the page only draws the ones inside it.
    area = gpd.read_file(BOUNDARY, layer="boundary").to_crs(25830).geometry.union_all()
    parks = place(screens["parks"])
    for p, src in zip(parks, screens["parks"]):
        p["on_map"] = bool(area.contains(gpd.points_from_xy(*to25830.transform([src["lon"]], [src["lat"]]))[0]))

    w, h = draw_forest(box)
    sites = place(screens["sites"])
    for s in sites:
        f = fotos.ortofoto(s["id"])  # the 10.4 orthophoto review, so a click on a site can show it
        s["photo"] = f["imagen"]
        s["verdict"] = f["veredicto"]
    data = {
        "meta": {"generated": date.today().isoformat(), "threshold_min": 12, "profile": "light vehicle",
                 "image": {"file": OUT_IMG.name, "width": w, "height": h},
                 "extent_epsg25830": [round(c, 1) for c in box],
                 "sources": "Homes, priority and travel times: agent_final_data (delivered). Forest: Mapa Forestal "
                            "del País Vasco 2024, Gobierno Vasco (sources.csv SRC-GV-INVFORESTAL-2024).",
                 "home_columns": ["x", "y", "priority (A/M/B)", "min from 9 parks"] + CANDS},
        "homes": homes,
        "parks": parks,
        "sites": sites,
        "steps": STEPS,
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT_IMG.name} {w}x{h} ({OUT_IMG.stat().st_size // 1024} kB) and {OUT_JSON.name} "
          f"({OUT_JSON.stat().st_size // 1024} kB, {len(homes)} homes)")


if __name__ == "__main__":
    main()
