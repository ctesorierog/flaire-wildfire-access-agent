"""Gipuzkoa-wide baseline must agree with the delivered Tolosaldea numbers on the 28 Tolosaldea municipalities.

Run the pipeline with --area gipuzkoa and then `export_area_baseline.py --area gipuzkoa` first, then:
    python -m pytest -q 05_codigo/tests_pipeline
Skips when the Gipuzkoa outputs are missing.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))
import area  # noqa: E402

GIP = REPO / "work" / "processed" / "gipuzkoa"
DELIVERED = REPO / "agent" / "data"
APP_JSON = REPO / "app" / "data" / "gipuzkoa_baseline.json"
THRESHOLD_MIN = 12.0

pytestmark = pytest.mark.skipif(not (GIP / "baseline_buildings.csv").exists(), reason="Gipuzkoa outputs not built")


@pytest.fixture(scope="module")
def baseline():
    return pd.read_csv(GIP / "baseline_buildings.csv", dtype={"muni_ine": str})


@pytest.fixture(scope="module")
def tolosaldea(baseline):
    return baseline[baseline.muni_ine.isin(area.TOLOSALDEA)]


def test_tolosaldea_subset_is_the_delivered_analysis_set(tolosaldea):
    delivered = set(pd.read_csv(DELIVERED / "edificios_prioridad.csv").building_id)
    assert set(tolosaldea.building_id) == delivered


def test_tolosaldea_subset_reproduces_2712(tolosaldea):
    assert int((tolosaldea.t_nearest_light <= THRESHOLD_MIN).sum()) == 2712


def test_second_park_is_never_closer_than_nearest(baseline):
    both = baseline.dropna(subset=["t_nearest_light", "t_second_light"])
    assert (both.t_second_light >= both.t_nearest_light).all()


def test_app_json_covers_all_88_municipalities_and_adds_up(baseline):
    data = json.loads(APP_JSON.read_text(encoding="utf-8"))
    munis = data["municipalities"]
    assert len(munis) == 88
    assert sum(m["exposed_buildings"] for m in munis) == len(baseline) == data["totals"]["exposed_buildings"]
    assert sum(m["within_12_min"] for m in munis) == int((baseline.t_nearest_light <= THRESHOLD_MIN).sum())
    tol = [m for m in munis if m["ine_code"] in area.TOLOSALDEA]
    assert sum(m["within_12_min"] for m in tol) == 2712
