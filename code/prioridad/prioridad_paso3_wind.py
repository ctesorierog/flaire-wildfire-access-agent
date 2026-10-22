"""Daily south-wind metrics per wind station from Euskalmet 10-min data (UTC days)."""
import numpy as np, pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parents[1]
t = pd.read_parquet(R/"processed/weather/obs_10min.parquet", columns=["station","ts_utc","variable","value_used","usable","is_duplicate"],
    filters=[("variable","in",["wind_speed","wind_dir","wind_gust","rh","tair"]),("station","in",["C026","C029","C058","C043"])])
t = t[t.usable & ~t.is_duplicate]
w = t.pivot_table(index=["station","ts_utc"], columns="variable", values="value_used", observed=True).reset_index()
w["date"] = w.ts_utc.dt.strftime("%Y-%m-%d")
w["s_sector"] = w.wind_dir.between(135, 225)
for thr in (3, 4, 5):
    w[f"s{thr}"] = w.s_sector & (w.wind_speed >= thr)
w["s_dry"] = w.s_sector & (w.wind_speed >= 3) & (w.rh <= 50)
g = w.groupby(["station","date"])
d = pd.DataFrame({
  "n_wind": g.wind_speed.count(), "n_dir": g.wind_dir.count(),
  "s_slots": g.s_sector.sum(), "s3_slots": g.s3.sum(), "s4_slots": g.s4.sum(), "s5_slots": g.s5.sum(), "s_dry_slots": g.s_dry.sum(),
  "gust_max_s": w[w.s_sector].groupby(["station","date"]).wind_gust.max(),
  "rhmin_s": w[w.s_sector].groupby(["station","date"]).rh.min(),
}).reset_index()
d.to_csv(R/"processed/prioridad/_wind_daily.csv", index=False)
print(d.describe().T)
