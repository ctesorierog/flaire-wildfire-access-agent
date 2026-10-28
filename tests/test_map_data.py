"""Chat app forest map data (05_codigo/chat_app/static/map.json, written by build_map.py).

The page lights a home when its nearest origin (a park or a chosen study site) is within 12 min. Here that same rule
must give the headline numbers, so the map can never show a different story from the slides.
    python -m pytest -q 05_codigo/tests_pipeline/test_map_data.py
"""
import json
from pathlib import Path

import pytest
from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CANDS = [f"CAND-{i:02d}" for i in range(1, 11)]


@pytest.fixture(scope="module")
def m():
    return json.loads((STATIC / "map.json").read_text(encoding="utf-8"))


def covered(m, selection, threshold=12):
    cols = [4 + CANDS.index(c) for c in selection]
    inside = alta = 0
    for h in m["homes"]:
        ts = [t for t in [h[3]] + [h[i] for i in cols] if t is not None]
        if ts and min(ts) <= threshold:
            inside += 1
            alta += h[2] == "A"
    return inside, alta


@pytest.mark.parametrize("step,expected", [(0, (2712, 49)), (1, (2958, 119)), (2, (3083, 165)), (3, (3187, 177))])
def test_steps_give_headline_numbers(m, step, expected):
    assert covered(m, m["steps"][step]) == expected


def test_shape(m):
    assert len(m["homes"]) == 3331
    assert sum(h[2] == "A" for h in m["homes"]) == 243
    assert all(0 <= h[0] <= 1 and 0 <= h[1] <= 1 for h in m["homes"])
    assert [s["id"] for s in m["sites"]] == CANDS and len(m["parks"]) == 9
    assert [bool(s["photo"]) for s in m["sites"]] == [True] * 4 + [False] * 6
    assert [s["verdict"] for s in m["sites"][:4]] == ["no_sirve", "sirve", "sirve", "dudoso"]
    # Only Tolosa's station (GIP-ORIA) is inside Tolosaldea; the other 8 count but aren't drawn.
    assert [p["id"] for p in m["parks"] if p["on_map"]] == ["GIP-ORIA"]


def test_image_matches_meta(m):
    img = Image.open(STATIC / m["meta"]["image"]["file"])
    assert img.size == (m["meta"]["image"]["width"], m["meta"]["image"]["height"])
    assert (STATIC / "map.json").stat().st_size < 400_000
