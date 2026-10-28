"""PLAN.md task 10.2: the stability table (app/data/stability.json).

Which 3 sites win at 10 / 12 / 15 min, light and truck, and by how much over the runner-up. The JSON is written by
05_codigo/pipeline/export_stability.py from the rebuilt times with 05_codigo/manager/optimizer.py. Here every row is
checked against a plain brute force on the delivered CSVs (agent_final_data), so the check depends on neither
the rebuild nor the optimizer.
    python -m pytest -q 05_codigo/tests_pipeline/test_stability.py
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))
import export_stability as es  # noqa: E402

DELIVERED = REPO / "agent" / "data"
STABILITY = REPO / "app" / "data" / "stability.json"
CSV = {"light": "tiempos_ligero.csv", "truck": "tiempos_camion.csv"}
PARKS = ["DON-GARBERA", "GIP-ARRATE", "GIP-BIDASOA", "GIP-GOIERRI", "GIP-KOROSTI",
         "GIP-KOSTA", "GIP-ORIA", "GIP-UROLA", "GIP-ZUBILLAGA"]
CANDS = [f"CAND-{i:02d}" for i in range(1, 11)]


@pytest.fixture(scope="module")
def table():
    return json.loads(STABILITY.read_text(encoding="utf-8"))


def brute_force(profile, threshold):
    """Every 3-site combination on the delivered times: [(covered, sorted ids)], best first, then today's count."""
    T = pd.read_csv(DELIVERED / CSV[profile]).set_index("building_id")
    reach = (T.fillna(np.inf) <= threshold + 1e-9)
    today = reach[PARKS].any(axis=1)
    combos = [(int((today | reach[list(c)].any(axis=1)).sum()), list(c)) for c in itertools.combinations(CANDS, 3)]
    combos.sort(key=lambda r: (-r[0], r[1]))
    return combos, int(today.sum())


def test_six_scenarios(table):
    assert sorted((r["profile"], r["threshold_min"]) for r in table["rows"]) == \
        sorted(itertools.product(["light", "truck"], [10, 12, 15]))
    assert table["meta"]["n_buildings"] == 3331


@pytest.mark.parametrize("profile", ["light", "truck"])
@pytest.mark.parametrize("threshold", [10, 12, 15])
def test_row_matches_brute_force(table, profile, threshold):
    row = next(r for r in table["rows"] if r["profile"] == profile and r["threshold_min"] == threshold)
    combos, today = brute_force(profile, threshold)
    (best_n, best), (second_n, _) = combos[0], combos[1]
    assert row["today_covered"] == today
    assert row["pick"] == best and row["covered"] == best_n
    # Runner-up can be tied (light 15 min: 02+03+06 and 01+02+03, both 3,277); the optimizer breaks ties by worst
    # time, so accept any combination with the second-best count.
    assert row["runner_up_covered"] == second_n
    assert row["runner_up"] in [c for n, c in combos if n == second_n]
    assert row["runner_up_ties"] == sum(1 for n, _ in combos if n == second_n)
    assert row["margin"] == best_n - second_n
    assert row["margin"] > 0, "a tie: the pick would be arbitrary"


def test_headline_row(table):
    row = next(r for r in table["rows"] if r["profile"] == "light" and r["threshold_min"] == 12)
    assert row["today_covered"] == 2712
    assert row["pick"] == ["CAND-01", "CAND-02", "CAND-03"]
    assert row["covered"] == 3187
    assert row["margin"] == 6


def test_amezketa_and_cand03_win_everywhere(table):
    for row in table["rows"]:
        assert {"CAND-02", "CAND-03"} <= set(row["pick"]), row


def test_candidates_matched_by_position_give_delivered_times():
    # Pool ids drift between the delivered pool and the rebuild (CAND-04 and CAND-06 are one id off), so the
    # export matches candidates to rebuilt sites by coordinates. The rebuilt minutes must equal the delivered ones.
    if not es.POOL_TIMES.exists():
        pytest.skip("rebuilt pool travel times not found in work/processed/")
    for profile in ("light", "truck"):
        rebuilt = es.minutes_table(profile)                     # buildings x (parks + CAND-01..10)
        delivered = pd.read_csv(DELIVERED / CSV[profile]).set_index("building_id")[PARKS + CANDS]
        rebuilt = rebuilt.reindex(index=delivered.index, columns=delivered.columns)
        assert (rebuilt.isna() == delivered.isna()).all().all(), profile
        assert float(np.nanmax((rebuilt - delivered).abs().values)) <= 0.01, profile
