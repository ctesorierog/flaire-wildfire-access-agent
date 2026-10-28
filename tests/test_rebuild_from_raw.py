"""Gate for the Gipuzkoa expansion: a rebuild of Tolosaldea from raw/ must reproduce the delivered numbers.

Run the pipeline first (network.py, territory_buildings.py, official_layers.py forest proximity,
link_build.py --stages times), then:
    python -m pytest -q 05_codigo/tests_pipeline
Skips when the rebuilt outputs in work/processed/ are missing.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
PROC = REPO / "work" / "processed"
DELIVERED = REPO / "agent" / "data"
TAG = "v0.3.1"

ANALYSIS_SET = PROC / "buildings" / "buildings_analysis_set.csv"
TIMES = PROC / "links" / f"travel_times_{TAG}.parquet"
POOL_TIMES = PROC / "links" / f"travel_times_pool_{TAG}.parquet"

# Fire parks in the baseline (OTH-HONDARRIBIA, the airport service, is excluded).
PARKS = ["DON-GARBERA", "GIP-ARRATE", "GIP-BIDASOA", "GIP-GOIERRI", "GIP-KOROSTI",
         "GIP-KOSTA", "GIP-ORIA", "GIP-UROLA", "GIP-ZUBILLAGA"]
# CAND -> candidate-pool id, from 04_informes_y_fuentes/fichas_candidatas_v03.md.
CANDS = {"CAND-01": "POOL-0005", "CAND-02": "POOL-0044", "CAND-03": "POOL-0050"}
THRESHOLD_MIN = 12.0

pytestmark = pytest.mark.skipif(not (ANALYSIS_SET.exists() and TIMES.exists()),
                                reason="rebuilt pipeline outputs not found in work/processed/")


@pytest.fixture(scope="module")
def analysis_ids():
    return set(pd.read_csv(ANALYSIS_SET).building_id)


@pytest.fixture(scope="module")
def light_minutes(analysis_ids):
    """Wide table: one row per analysis-set building, one column per origin (light vehicle, minutes)."""
    frames = [pd.read_parquet(TIMES, columns=["origin_id", "building_id", "profile", "minutes"])]
    if POOL_TIMES.exists():
        frames.append(pd.read_parquet(POOL_TIMES, columns=["origin_id", "building_id", "profile", "minutes"]))
    t = pd.concat(frames)
    t = t[(t.profile == "light") & t.building_id.isin(analysis_ids)]
    return t.pivot_table(index="building_id", columns="origin_id", values="minutes", aggfunc="first")


def covered(minutes, origins):
    # Unroutable buildings have NaN minutes and count as not covered.
    return int((minutes[origins].min(axis=1, skipna=True) <= THRESHOLD_MIN).sum())


def test_analysis_set_matches_delivery(analysis_ids):
    delivered = set(pd.read_csv(DELIVERED / "edificios_prioridad.csv").building_id)
    assert len(analysis_ids) == 3331
    assert analysis_ids == delivered


def test_park_minutes_match_delivery(light_minutes):
    delivered = pd.read_csv(DELIVERED / "tiempos_ligero.csv").set_index("building_id")[PARKS]
    rebuilt = light_minutes.reindex(delivered.index)[PARKS]
    both_nan = rebuilt.isna() & delivered.isna()
    diff = (rebuilt - delivered).abs().where(~both_nan, 0.0)
    assert not diff.isna().any().any(), "a building is routable in one version and not in the other"
    assert float(np.nanmax(diff.values)) <= 0.01


def test_baseline_today_2712(light_minutes):
    assert covered(light_minutes, PARKS) == 2712


def test_baseline_today_is_81_4_percent(light_minutes, analysis_ids):
    # Denominator is the whole analysis set: buildings with no route at all are not in light_minutes.
    assert round(100 * covered(light_minutes, PARKS) / len(analysis_ids), 1) == 81.4


@pytest.mark.skipif(not POOL_TIMES.exists(), reason="pool travel times not rebuilt")
def test_three_crews_3187(light_minutes):
    assert covered(light_minutes, PARKS + list(CANDS.values())) == 3187


@pytest.mark.skipif(not POOL_TIMES.exists(), reason="pool travel times not rebuilt")
def test_three_crews_is_95_7_percent(light_minutes, analysis_ids):
    assert round(100 * covered(light_minutes, PARKS + list(CANDS.values())) / len(analysis_ids), 1) == 95.7
