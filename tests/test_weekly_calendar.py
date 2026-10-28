"""PLAN.md task 10.7: the weekly risk-day strip (app/data/weekly_calendar.json).

The JSON is written by 05_codigo/pipeline/export_weekly_calendar.py from the paso3 risk-day list. Here it is checked
against the numbers the talk already uses (26.3 risk days a year; 14 % Jul-Aug, 32 % Feb-Apr, 31 % Sep-Oct, from
cifras_clave_persona1.json) and against paso3's own monthly table, so the strip can't drift from the slide.
    python -m pytest -q 05_codigo/tests_pipeline/test_weekly_calendar.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))
import export_weekly_calendar as ew  # noqa: E402

WEEKLY = REPO / "app" / "data" / "weekly_calendar.json"
CIFRAS = REPO / "agent" / "data" / "cifras_clave_persona1.json"


@pytest.fixture(scope="module")
def cal():
    return json.loads(WEEKLY.read_text(encoding="utf-8"))


def test_json_is_current(cal):
    fresh = ew.build()
    fresh["meta"]["generated"] = cal["meta"]["generated"]
    assert cal == fresh


def test_52_weeks(cal):
    assert [w["week"] for w in cal["weeks"]] == list(range(1, 53))
    assert all(0 <= w["years_with_risk_day"] <= 6 for w in cal["weeks"])


def test_shares_match_the_talk(cal):
    cifras = json.loads(CIFRAS.read_text(encoding="utf-8"))
    assert cal["summary"]["risk_days_per_year"] == pytest.approx(cifras["meteo_dias_riesgo_anuales_media"], abs=0.1)
    published = {"feb_apr": "feb-abr", "jul_aug": "jul-ago", "sep_oct": "sep-oct"}
    for key, share in cal["summary"]["season_share"].items():
        assert round(share, 2) == cifras["meteo_reparto"][published[key]]


def test_weeks_add_up_to_the_year(cal):
    # paso3 uses 28.25 days for February, the calendar 28.17; 0.2 covers that.
    total = sum(w["risk_days"] for w in cal["weeks"])
    assert total == pytest.approx(cal["summary"]["risk_days_per_year"], abs=0.2)


def test_jul_aug_weeks_are_a_minority(cal):
    # The slide-5 claim, from the weeks themselves: weeks whose main month is Jul or Aug hold well under a fifth.
    total = sum(w["risk_days"] for w in cal["weeks"])
    julaug = sum(w["risk_days"] for w in cal["weeks"] if w["month"] in (7, 8))
    assert julaug / total < 0.2


def test_risk_list_matches_monthly_table():
    # The list the strip is built from has exactly the risk days paso3 counted per station and month.
    risk = pd.read_csv(ew.RISK_DAYS, parse_dates=["date"])
    risk = risk[risk.station_id.isin(ew.ZONE_STATIONS)]
    counted = risk.groupby([risk.station_id, risk.date.dt.month]).size()
    monthly = pd.read_csv(ew.MONTHLY)
    monthly = monthly[monthly.station_id.isin(ew.ZONE_STATIONS)].set_index(["station_id", "mes"]).dias_riesgo
    assert (counted.reindex(monthly.index, fill_value=0) == monthly).all()
    assert risk.date.dt.year.between(2018, 2023).all()
