"""flAIre · Persona 1 · Paso 3: meteorología histórica TODO EL AÑO (no solo julio-agosto).
Dos tipos de día de riesgo meteorológico (indicadores exploratorios del proyecto, NO FWI, NO probabilidad de incendio):
  CS-v1 calor seco  = ADV-v1: Tmax >= 25 °C, HRmin <= 40 %, sin día de lluvia >= 1 mm en los 3 días previos.
  VS-v1 viento sur seco: >= 18 registros de 10 min (3 h) con viento del sector S (135-225°) >= 3 m/s y HR <= 50 %,
        sin día de lluvia >= 1 mm en los 3 días previos.
Día de riesgo = CS o VS.  Zonas = estaciones con viento C026 Berastegi, C029 Zizurkil, C058 Bidania (C043 Ordizia, fuera, de control)."""
import json, numpy as np, pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parents[2] / "work"; O = R/"processed/prioridad"
rng = np.random.default_rng(20261002)
ZON = {"C026": "Berastegi", "C029": "Zizurkil", "C058": "Bidania"}; ALL = list(ZON) + ["C043"]
d = pd.read_csv(R/"processed/weather/daily_with_rules.csv")
w = pd.read_csv(O/"_wind_daily.csv").rename(columns={"station": "station_id"})
m = d[d.station_id.isin(ALL)].merge(w.rename(columns={"n_wind": "n_wind10"}), on=["station_id","date"], how="left")
m["wind_ok"] = m.n_wind10.fillna(0).ge(120) & m.n_dir.fillna(0).ge(120)
def vs(slots, rh_col="s_dry_slots"):
    valid = m.wind_ok & m.prev3_valid & m.valid_rh
    return valid, valid & m[rh_col].ge(slots) & m.prev3_norain
m["valid_cs"] = m.valid_R4N_T25_RH40_NORAIN3.astype(bool); m["cs"] = m.adv_R4N_T25_RH40_NORAIN3.astype(bool) & m.valid_cs
VS_SLOTS = 18  # decisión de Carlos 2-oct: ≥ 3 h
m["valid_vs"], m["vs"] = vs(VS_SLOTS)
m["riesgo"] = m.cs | m.vs
m["valid_riesgo"] = (m.valid_cs & m.valid_vs) | m.riesgo
for k in ("cs","vs","riesgo"): m[k] = m[k].astype(float).where(m[f"valid_{k}"])
# sensibilidad VS
sens = []
for sl in (18, 36, 72):
    v, a = vs(sl); sens.append(dict(regla=f"VS ≥{sl} registros (≈{sl/6:g} h)", dias_validos=int(v[m.station_id.isin(ZON)].sum()),
                                     dias_riesgo=int(a[m.station_id.isin(ZON)].sum())))
m["mes"] = m.month; m["anio"] = m.year
Z = m[m.station_id.isin(ZON)].copy()
# --- mensual (todas las estaciones) ---
mes = (m.groupby(["station_id","mes"]).agg(dias_validos=("valid_riesgo","sum"), dias_cs=("cs","sum"), dias_vs=("vs","sum"), dias_riesgo=("riesgo","sum"),
        validos_cs=("valid_cs","sum"), validos_vs=("valid_vs","sum")).reset_index())
mes["frec_riesgo"] = (mes.dias_riesgo/mes.dias_validos).round(4)
mes["dias_riesgo_por_mes"] = (mes.frec_riesgo * mes.mes.map({1:31,2:28.25,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31})).round(2)
mes["dias_cs_por_mes"] = (mes.dias_cs/mes.validos_cs*mes.mes.map({1:31,2:28.25,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31})).round(2)
mes["dias_vs_por_mes"] = (mes.dias_vs/mes.validos_vs*mes.mes.map({1:31,2:28.25,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31})).round(2)
mes.insert(1, "zona", mes.station_id.map(ZON).fillna("Ordizia (control, fuera)"))
mes.to_csv(O/"paso3_meteo_mensual.csv", index=False)
# --- anual por zona (años con >= 80 % de días válidos) ---
an = (Z.groupby(["station_id","anio"]).agg(dias_validos=("valid_riesgo","sum"), dias_riesgo=("riesgo","sum"), dias_cs=("cs","sum"), dias_vs=("vs","sum")).reset_index())
an["completo"] = an.dias_validos >= 0.8*365
an["dias_riesgo_por_anio"] = (an.dias_riesgo/an.dias_validos*365).round(1)
an.insert(1, "zona", an.station_id.map(ZON)); an.to_csv(O/"paso3_meteo_anual.csv", index=False)
# --- test de distinguibilidad sobre días comunes válidos en las 3 zonas ---
P = Z.pivot_table(index="date", columns="station_id", values="riesgo", aggfunc="first").dropna()
P["mes_bloque"] = P.index.str[:7]
res = []
for a, b in (("C026","C029"),("C026","C058"),("C029","C058")):
    diff = P[a] - P[b]; obs = diff.mean()*365
    g = diff.groupby(P.mes_bloque).agg(["sum","count"]); blocks = g.index.values
    boots = []
    for _ in range(5000):
        s = g.loc[rng.choice(blocks, len(blocks))]; boots.append(s["sum"].sum()/s["count"].sum()*365)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # permutación: intercambiar etiquetas a/b por bloque mensual
    sums = g["sum"].values; n = g["count"].sum()
    perm = np.array([(sums*rng.choice([-1,1], len(sums))).sum()/n*365 for _ in range(5000)])
    p = (np.abs(perm) >= abs(obs)).mean()
    yr = P.assign(y=P.index.str[:4]).groupby("y")[[a,b]].mean()
    yrs = int((yr[a] > yr[b]).sum()), int((yr[a] < yr[b]).sum())
    res.append(dict(zona_a=ZON[a], zona_b=ZON[b], dias_comunes=len(P), dif_dias_por_anio=round(obs,1), ic95_bajo=round(lo,1), ic95_alto=round(hi,1),
                    p_permutacion=round(p,4), anios_a_mayor=yrs[0], anios_b_mayor=yrs[1], n_anios=len(yr)))
T = pd.DataFrame(res)
# ±1 sd entre años (zona)
z = an[an.completo].groupby("station_id").dias_riesgo_por_anio.agg(["mean","std","count"]).round(1)
z["bajo_1sd"] = (z["mean"]-z["std"]).round(1); z["alto_1sd"] = (z["mean"]+z["std"]).round(1)
z.insert(0, "zona", z.index.map(ZON)); z.to_csv(O/"paso3_meteo_zona.csv")
# sincronía: proporción de días de riesgo que ocurren a la vez en las 3 zonas
r3 = P[list(ZON)].sum(1); sync = dict(dias_con_riesgo_en_alguna=int((r3>0).sum()), en_las_3=int((r3==3).sum()), en_1=int((r3==1).sum()))
# distinguible si: IC95 excluye 0 Y p < 0.05 Y mismo signo en todos los años menos uno Y |dif| >= 3 días/año
T["distinguible"] = ((T.ic95_bajo > 0) | (T.ic95_alto < 0)) & (T.p_permutacion < 0.05) & \
    (T[["anios_a_mayor","anios_b_mayor"]].max(1) >= T.n_anios - 1) & (T.dif_dias_por_anio.abs() >= 3)
T.to_csv(O/"paso3_test_zonas.csv", index=False)
# --- validación con eventos y totales de Gipuzkoa (Diputación Foral, 2018-2023) ---
ev = m[(m.date >= "2021-02-17") & (m.date <= "2021-02-22")][["station_id","date","cs","vs","s_dry_slots","rhmin_pct","tmax_c","gust_max_s"]]
dfg = pd.DataFrame({"anio":[2018,2019,2020,2021,2022,2023],"incendios_gipuzkoa":[11,39,42,38,36,47],"ha_gipuzkoa":[10.80,89.74,49.02,381.00,73.00,54.97]})
reg = (m[m.station_id.isin(["C029","C043"])].groupby("anio").agg(riesgo=("riesgo","sum"), vs=("vs","sum"), cs=("cs","sum"), val=("valid_riesgo","sum")).reset_index())
reg = (m[m.station_id.isin(ALL)].groupby(["anio","station_id"]).agg(r=("riesgo","sum"),v=("vs","sum"),c=("cs","sum"),n=("valid_riesgo","sum")).reset_index())
reg = reg[reg.n >= 0.8*365].assign(r=lambda x: x.r/x.n*365, v=lambda x: x.v/x.n*365, c=lambda x: x.c/x.n*365).groupby("anio")[["r","v","c"]].mean().round(1).reset_index()
reg.columns = ["anio","dias_riesgo_media_estaciones","dias_vs","dias_cs"]; val = dfg.merge(reg, on="anio")
val.to_csv(O/"paso3_validacion_anual.csv", index=False)
# --- días de riesgo (lista) ---
dl = m[m.riesgo.eq(1)][["station_id","date","cs","vs","tmax_c","rhmin_pct","s_dry_slots","gust_max_s","precip_mm"]].copy()
dl.insert(1, "zona", dl.station_id.map(ZON).fillna("Ordizia (control)")); dl["tipo"] = np.select([dl.cs.eq(1)&dl.vs.eq(1), dl.cs.eq(1)], ["CS+VS","CS"], "VS")
dl.drop(columns=["cs","vs"]).to_csv(O/"paso3_dias_riesgo.csv", index=False)
json.dump(dict(sens=sens, sync=sync), open(O/"_paso3.json","w"), ensure_ascii=False, indent=1)
pd.set_option("display.width", 250)
print(mes[mes.station_id.isin(ZON)].pivot_table(index="mes", columns="zona", values=["dias_cs_por_mes","dias_vs_por_mes","dias_riesgo_por_mes"]).round(1))
print(mes[mes.station_id=="C043"][["mes","dias_cs_por_mes","dias_vs_por_mes","dias_riesgo_por_mes"]].to_string())
print(an.to_string()); print(z); print(T.to_string()); print(sens); print(sync); print(ev.to_string()); print(val.to_string())
print("spearman fires", val[["incendios_gipuzkoa","ha_gipuzkoa","dias_riesgo_media_estaciones","dias_vs","dias_cs"]].corr("spearman").round(2))
print(dl.tipo.value_counts(), dl[dl.station_id.isin(ZON)].groupby("tipo").size())

# --- por edificio: zona y puntos meteo (neutros si no es distinguible) ---
bz = pd.read_csv(R/"processed/weather/building_zone.csv", dtype={"building_id": str})[["building_id","station_id"]]
e = pd.read_parquet(O/"_step1.parquet")[["building_id","municipio","residencial","cerca_vegetacion"]].merge(bz, on="building_id", how="left", validate="1:1")
zz = z["mean"].to_dict(); ja = mes[mes.mes.isin([7,8])].groupby("station_id").dias_riesgo_por_mes.sum().round(1).to_dict()
DIST = bool(T.distinguible.any())
e = e.assign(zona_meteo=e.station_id, nombre_zona=e.station_id.map(ZON), dias_riesgo_anio_zona=e.station_id.map(zz),
             dias_riesgo_julago_zona=e.station_id.map(ja), puntos_meteo=0 if not DIST else np.nan,
             motivo_meteo="zonas no distinguibles con los datos 2018-2023 (paso3_test_zonas.csv): puntos neutros" if not DIST else "",
             version_regla="CS-v1(=ADV-v1)+VS-v1")
e.drop(columns="station_id").to_csv(O/"paso3_meteo_edificios.csv", index=False)
print(e.groupby("nombre_zona").size(), "distinguible:", DIST)
