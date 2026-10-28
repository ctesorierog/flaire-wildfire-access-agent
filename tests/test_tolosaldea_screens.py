"""PLAN.md task 10.3: the screen data for Tolosaldea today and with 1..3 crews (app/data/tolosaldea.json).

The JSON is written by 05_codigo/pipeline/export_tolosaldea.py from the delivered CSVs (agent_final_data). Here
the headline numbers are pinned, the picks are checked against escenarios.csv (the optimizer's output, an independent
source), and every count is re-derived from the per-building rows the app will draw.
    python -m pytest -q 05_codigo/tests_pipeline/test_tolosaldea_screens.py
"""
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
DELIVERED = REPO / "agent" / "data"
SCREENS = REPO / "app" / "data" / "tolosaldea.json"


@pytest.fixture(scope="module")
def data():
    return json.loads(SCREENS.read_text(encoding="utf-8"))


def test_headline_numbers(data):
    assert data["meta"]["n_buildings"] == 3331
    assert data["meta"]["threshold_min"] == 12
    assert [s["covered"] for s in data["steps"]] == [2712, 2958, 3083, 3187]
    assert [s["alta_covered"] for s in data["steps"]][0] == 49
    assert data["steps"][-1]["alta_covered"] == 177
    assert data["meta"]["n_alta"] == 243


def test_picks_match_optimizer_scenarios(data):
    sc = pd.read_csv(DELIVERED / "escenarios.csv")
    sc = sc[(sc.estrategia == "A") & (sc.umbral_min == 12) & (sc.perfil == "ligero") & (sc.pesos == "uniforme")]
    for step in data["steps"]:
        row = sc[sc.k == step["k"]].iloc[0]
        expected = [] if pd.isna(row.seleccion) else row.seleccion.split(";")
        assert step["pick"] == expected, step["k"]
        assert step["covered"] == row.edificios_cubiertos


def test_picks_are_nested_so_each_crew_has_one_gain(data):
    steps = data["steps"]
    for prev, cur in zip(steps, steps[1:]):
        assert set(prev["pick"]) < set(cur["pick"])
        assert cur["added_site"] == (set(cur["pick"]) - set(prev["pick"])).pop()
        assert cur["gain"] == cur["covered"] - prev["covered"]
    assert [s["gain"] for s in steps[1:]] == [246, 125, 104]


def test_building_rows_add_up(data):
    b = data["buildings"]
    assert len(b) == 3331 and len({r["id"] for r in b}) == 3331
    for step in data["steps"]:
        covered = [r for r in b if r["covered_by_step"] is not None and r["covered_by_step"] <= step["k"]]
        assert len(covered) == step["covered"], step["k"]
        assert sum(r["priority"] == "Alta" for r in covered) == step["alta_covered"], step["k"]
    # A building rescued at step k is newly reached by that step's crew within 12 min.
    for r in b:
        if r["covered_by_step"]:
            assert r["rescued_by"] == data["steps"][r["covered_by_step"]]["added_site"]
            assert r["t_today_min"] is None or r["t_today_min"] > 12
            assert r["t_final_min"] <= 12
        else:
            assert r["rescued_by"] is None


def test_villages_rescued_are_computed_from_buildings(data):
    for step in data["steps"][1:]:
        rescued = Counter(r["municipality"] for r in data["buildings"] if r["covered_by_step"] == step["k"])
        assert {v["municipality"]: v["buildings"] for v in step["villages_rescued"]} == dict(rescued)
        assert sum(v["buildings"] for v in step["villages_rescued"]) == step["gain"]
    # The first crew (Amezketa) rescues mostly Amezketa and Abaltzisketa, as in fichas cluster 3.
    top2 = [v["municipality"] for v in data["steps"][1]["villages_rescued"][:2]]
    assert set(top2) == {"Amezketa", "Abaltzisketa"}


def test_sites_and_parks_have_positions(data):
    assert {s["id"] for s in data["sites"]} == {f"CAND-{i:02d}" for i in range(1, 11)}
    assert len(data["parks"]) == 9
    for p in data["sites"] + data["parks"]:
        assert -2.6 < p["lon"] < -1.7 and 42.9 < p["lat"] < 43.45, p["id"]
    assert data["meta"]["limits"]
