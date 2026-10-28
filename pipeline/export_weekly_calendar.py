#!/usr/bin/env python3
"""
flAIre · weekly risk-day strip for the web app and slide 5 (PLAN.md task 10.7, shortlist item 2).

    python 05_codigo/pipeline/export_weekly_calendar.py

For each ISO week of the year: mean weather risk days at the 3 Tolosaldea zone stations (C026 Berastegi, C029 Zizurkil,
C058 Bidania), 2018-2023, and in how many of the 6 years that week had at least one. Risk day = CS-v1 dry heat OR
VS-v1 dry south wind (05_codigo/prioridad/prioridad_paso3.py; exploratory project rules, NOT FWI, NOT fire probability).

Reads the paso3 outputs, not daily.csv: daily.csv has no wind direction, so it can't give VS-v1 (the Feb-Apr season),
and the 10-min wind inputs paso3 used are not in the repo. Missing days are not filled: each risk day is scaled by
calendar days / valid days of its station-month, the same normalisation as paso3_meteo_mensual.csv, so the 52 weeks
add up to the published 26.3 risk days a year. ISO week 53 (2020 only) is folded into week 52.
Writes app/data/weekly_calendar.json. Guarded by 05_codigo/tests_pipeline/test_weekly_calendar.py.
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PASO3 = REPO / "data" / "priority"
RISK_DAYS = PASO3 / "paso3_dias_riesgo.csv"
MONTHLY = PASO3 / "paso3_meteo_mensual.csv"
APP_JSON = REPO / "app" / "data" / "weekly_calendar.json"

ZONE_STATIONS = {"C026": "Berastegi", "C029": "Zizurkil", "C058": "Bidania"}
YEARS = range(2018, 2024)
SEASONS = {"feb_apr": [2, 3, 4], "jul_aug": [7, 8], "sep_oct": [9, 10]}


def week_of(dates):
    """ISO week number, with week 53 folded into 52 so the strip always has 52 cells."""
    return dates.dt.isocalendar().week.astype(int).clip(upper=52)


def weekly_table():
    risk = pd.read_csv(RISK_DAYS, parse_dates=["date"])
    risk = risk[risk.station_id.isin(ZONE_STATIONS)].copy()
    monthly = pd.read_csv(MONTHLY)
    valid = monthly[monthly.station_id.isin(ZONE_STATIONS)].set_index(["station_id", "mes"]).dias_validos

    cal = pd.DataFrame({"date": pd.date_range(f"{YEARS[0]}-01-01", f"{YEARS[-1]}-12-31")})
    cal["month"], cal["week"] = cal.date.dt.month, week_of(cal.date)
    cal_days = cal.month.value_counts()

    risk["week"] = week_of(risk.date)
    risk["weight"] = [cal_days[d.month] / valid[(s, d.month)] for s, d in zip(risk.station_id, risk.date)]
    n = len(YEARS) * len(ZONE_STATIONS)
    weeks = range(1, 53)
    out = pd.DataFrame({
        "week": weeks,
        "risk_days": (risk.groupby("week").weight.sum() / n).reindex(weeks, fill_value=0).values,
        "years_with_risk_day": risk.groupby("week").date.apply(lambda s: s.dt.year.nunique())
                                   .reindex(weeks, fill_value=0).astype(int).values,
        "days_in_week": (cal.groupby("week").size() / len(YEARS)).reindex(weeks).values,
        "month": cal.groupby("week").month.agg(lambda s: s.mode().iloc[0]).reindex(weeks).values,
    })
    return out, monthly[monthly.station_id.isin(ZONE_STATIONS)]


def season_shares(monthly):
    """Share of the year's risk days per season, from paso3's own monthly table (the source of '14 % in Jul-Aug')."""
    per_month = monthly.groupby("mes").dias_riesgo_por_mes.mean()
    total = per_month.sum()
    return round(float(total), 1), {k: round(float(per_month[ms].sum() / total), 3) for k, ms in SEASONS.items()}


def build():
    weeks, monthly = weekly_table()
    annual, shares = season_shares(monthly)
    return {
        "meta": {
            "area": "tolosaldea",
            "generated": date.today().isoformat(),
            "years": [YEARS[0], YEARS[-1]],
            "stations": ZONE_STATIONS,
            "rule": "CS-v1 OR VS-v1",
            "method": ("Risk day = dry heat (Tmax ≥ 25 °C, RH min ≤ 40 %, no rain ≥ 1 mm in the 3 days before) OR dry "
                       "south wind (≥ 3 h of S wind ≥ 3 m/s with RH ≤ 50 %, same rain condition). Euskalmet stations, "
                       "2018–2023. risk_days = mean per station and year in that ISO week, missing days scaled out."),
            "limits": [
                "Exploratory project rules, not FWI and not fire probability.",
                "Only 6 years: single weeks are noisy. Read the seasons, not one week.",
                "Not checked against fire records; it shows when the weather was risky, not when fires happened.",
                "Seasonal staffing only: the sites don't change by week (the 3 zones can't be told apart).",
            ],
        },
        "summary": {"risk_days_per_year": annual, "season_share": shares},
        "weeks": [
            {"week": int(r.week), "month": int(r.month), "risk_days": round(float(r.risk_days), 2),
             "years_with_risk_day": int(r.years_with_risk_day), "days_in_week": round(float(r.days_in_week), 2)}
            for r in weeks.itertuples()
        ],
    }


def main():
    data = build()
    APP_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    s = data["summary"]
    print(f"wrote {APP_JSON.relative_to(REPO)}: {s['risk_days_per_year']} risk days/year, shares {s['season_share']}")


if __name__ == "__main__":
    main()
