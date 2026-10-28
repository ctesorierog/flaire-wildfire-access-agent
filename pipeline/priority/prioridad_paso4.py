"""flAIre · Persona 1 · Paso 4: puntos, prioridad Alta/Media/Baja, pesos, sensibilidad y vista previa del optimizador.
PRIORIDAD DE PLANIFICACIÓN: no predice incendios ni es una probabilidad de incendio."""
import sys, json, numpy as np, pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parents[2] / "work"; O = R/"processed/prioridad"
s1 = pd.read_parquet(O/"_step1.parquet")
s2 = pd.read_csv(O/"paso2_acceso.csv", dtype={"building_id": str})
s3 = pd.read_csv(O/"paso3_meteo_edificios.csv", dtype={"building_id": str})
d = s1.merge(s2[["building_id","t_base_ligero_min","parque_base_ligero","banda_acceso","acceso_desconocido"]], on="building_id", validate="1:1") \
      .merge(s3[["building_id","zona_meteo","puntos_meteo"]], on="building_id", validate="1:1")
assert len(d) == 14015
PD = {"dentro": 3, "0–25": 3, "25–50": 2, "50–100": 1}
PV = {3: 2, 2: 1, 1: 0}
PA = {"≤8": 0, "8–12": 1, "12–15": 2, ">15": 3, "sin ruta": 3}
CUT = dict(alta=6, media=4)           # total 1..8: Alta ≥ 6 · Media 4–5 · Baja ≤ 3
CUT_SA = dict(alta=4, media=3)        # sin acceso 1..5: Alta ≥ 4 · Media 3 · Baja ≤ 2
A = d.cerca_vegetacion.eq("sí")
def clase(x, c): return np.where(x >= c["alta"], "Alta", np.where(x >= c["media"], "Media", "Baja"))
d["puntos_distancia"] = d.banda_distancia.map(PD).where(A)
d["puntos_vegetacion"] = d.tipo_veg_nivel.map(PV).where(A)
d["puntos_acceso"] = d.banda_acceso.map(PA).where(A)
d["puntos_meteo"] = d.puntos_meteo.where(A)
d["puntos_total"] = (d.puntos_distancia + d.puntos_vegetacion + d.puntos_acceso + d.puntos_meteo).where(A)
d["puntos_sin_acceso"] = (d.puntos_distancia + d.puntos_vegetacion + d.puntos_meteo).where(A)
d["prioridad"] = np.where(A, clase(d.puntos_total.fillna(-1), CUT), "fuera del conjunto")
d["prioridad_sin_acceso"] = np.where(A, clase(d.puntos_sin_acceso.fillna(-1), CUT_SA), "fuera del conjunto")
d["motivo_exclusion"] = np.select([A, d.residencial.eq("no"), d.residencial.eq("desconocido") & d.dist_veg_m.le(100), d.residencial.eq("desconocido")],
    ["", "no residencial", "uso desconocido en B5M (≤ 100 m de vegetación)", "uso desconocido en B5M (> 100 m de vegetación)"], "residencial a > 100 m de vegetación")
W = {"Alta": 3, "Media": 2, "Baja": 1}
for col, src in (("peso_prioridad", "prioridad"), ("peso_prioridad_sin_acceso", "prioridad_sin_acceso")):
    raw = d[src].map(W).where(A); d[col] = (raw / raw[A].mean()).round(4)
SUB = {"natural_broadleaf": "frondosa natural", "riparian_broadleaf": "bosque de galería", "plantation_conifer": "plantación de coníferas",
       "plantation_broadleaf": "plantación de frondosas", "scrub": "matorral", "scrub_heath": "matorral", "plantation_mixed": "plantación mixta",
       "natural_mixed": "bosque mixto natural", "forest_mixed": "bosque mixto natural", "pasture_scrub_mosaic": "mosaico pastizal-matorral", "plantation_eucalyptus": "eucalipto",
       "natural_conifer": "conífera natural"}
def motivo(r):
    if r.prioridad == "fuera del conjunto": return ""
    veg = SUB.get(r.subcategoria_vegetacion, str(r.subcategoria_vegetacion))
    dist = "dentro de" if r.banda_distancia == "dentro" else f"a {r.dist_veg_m:.0f} m de"
    acc = "sin ruta (a > 150 m de la red)" if r.banda_acceso == "sin ruta" else f"{r.t_base_ligero_min:.1f} min desde {r.parque_base_ligero}".replace(".", ",", 1)
    return (f"{dist} {veg} (nivel {int(r.tipo_veg_nivel)}) · {acc} · puntos {int(r.puntos_distancia)}+{int(r.puntos_vegetacion)}+"
            f"{int(r.puntos_acceso)}+{int(r.puntos_meteo)} = {int(r.puntos_total)}")
d["motivo_prioridad"] = d.apply(motivo, axis=1)
cols = ["building_id","municipio","residencial","viviendas","cerca_vegetacion","dist_veg_m","banda_distancia","subcategoria_vegetacion","tipo_veg_nivel",
        "t_base_ligero_min","parque_base_ligero","banda_acceso","acceso_desconocido","zona_meteo",
        "puntos_distancia","puntos_vegetacion","puntos_acceso","puntos_meteo","puntos_total","prioridad","peso_prioridad",
        "puntos_sin_acceso","prioridad_sin_acceso","peso_prioridad_sin_acceso","motivo_prioridad","motivo_exclusion"]
out = d[cols].copy(); out["version_reglas"] = "PRIO-v1 (2026-10-02)"
out.to_csv(O/"paso4_puntos.csv", index=False); d.to_parquet(O/"_step4.parquet")
S = d[A]
res = {}
res["dist_total"] = S.puntos_total.value_counts().sort_index().to_dict()
res["clases"] = S.prioridad.value_counts().to_dict(); res["clases_sin_acceso"] = S.prioridad_sin_acceso.value_counts().to_dict()
res["viviendas_clase"] = S.groupby("prioridad").viviendas.sum().to_dict()
res["cruce"] = pd.crosstab(S.prioridad, S.prioridad_sin_acceso).to_dict()
mun = pd.crosstab(S.municipio, S.prioridad).reindex(columns=["Alta","Media","Baja"], fill_value=0)
mun["total"] = mun.sum(axis=1); mun["pct_alta"] = (100*mun.Alta/mun.total).round(1)
mun["viviendas_alta"] = S[S.prioridad.eq("Alta")].groupby("municipio").viviendas.sum().reindex(mun.index).fillna(0).astype(int)
mun = mun.sort_values(["Alta","pct_alta"], ascending=False); mun.to_csv(O/"paso4_prioridad_x_municipio.csv")
# --- sensibilidad ---
base = S.prioridad
sens = []
def add(nombre, nueva):
    nueva = pd.Series(nueva, index=S.index)
    sens.append(dict(variante=nombre, alta=int((nueva=="Alta").sum()), media=int((nueva=="Media").sum()), baja=int((nueva=="Baja").sum()),
                     cambian_clase=int((nueva != base).sum()), alta_que_sigue_alta=int(((nueva=="Alta")&(base=="Alta")).sum())))
add("BASE (Alta ≥ 6, Media 4–5)", base)
add("Corte Alta ≥ 5, Media 3–4", clase(S.puntos_total, dict(alta=5, media=3)))
add("Corte Alta ≥ 7, Media 5–6", clase(S.puntos_total, dict(alta=7, media=5)))
add("Tipo de vegetación = peor a ≤ 25 m", clase(S.puntos_distancia + S.tipo_veg_nivel_25m.map(PV) + S.puntos_acceso, CUT))
add("Distancia: solo «dentro» = 3 (0–25 = 2)", clase(S.banda_distancia.map({"dentro":3,"0–25":2,"25–50":2,"50–100":1}) + S.puntos_vegetacion + S.puntos_acceso, CUT))
for comp, mx in (("puntos_distancia", 3), ("puntos_vegetacion", 2), ("puntos_acceso", 3)):
    rest = S.puntos_total - S[comp]
    add(f"Sin {comp.replace('puntos_','')} (cortes reescalados)", clase(rest/(8-mx)*8, CUT))
add("Acceso con camión", clase(S.puntos_distancia + S.puntos_vegetacion +
    pd.cut(pd.to_numeric(d.loc[A].building_id.map(pd.read_csv(O/"paso2_acceso.csv", dtype={"building_id": str}).set_index("building_id").t_base_camion_min)),
           [-1,8,12,15,1e9], labels=[0,1,2,3]).astype(float).fillna(3), CUT))
SE = pd.DataFrame(sens); SE.to_csv(O/"paso4_sensibilidad.csv", index=False)
# caseríos posibles (uso desconocido con nombre de caserío y ≤ 100 m): qué prioridad tendrían
c = d[d.farmhouse_nombre.fillna(False).astype(bool) & d.residencial.eq("desconocido") & d.dist_veg_m.le(100)].copy()
cp = c.banda_distancia.map(PD) + c.tipo_veg_nivel.map(PV) + c.banda_acceso.map(PA)
res["caserios_posibles"] = dict(n=len(c), **pd.Series(clase(cp, CUT)).value_counts().to_dict())
# --- vista previa del optimizador (solo lectura: pesos inyectados en memoria, nada se sobrescribe) ---
sys.path.insert(0, str(R/"agent")); import flaire_data as F
D = F.datos(); ix = pd.Series(range(len(D.ids)), index=D.ids)
for nombre, col in (("prioridad", "peso_prioridad"), ("prioridad_sin_acceso", "peso_prioridad_sin_acceso")):
    w = np.full(len(D.ids), np.nan); m = d.set_index("building_id")[col].reindex(D.ids); w[:] = m.to_numpy(float); D.peso[nombre] = w
prev = []
for u in (12.0, 15.0):
    for w in ("uniforme", "meteo", "prioridad", "prioridad_sin_acceso"):
        r = F._optimizar_cache(6, "A", u, "ligero", w)
        for m in r["per_k"]:
            prev.append(dict(umbral_min=u, pesos=w, k=m["k"], seleccion=";".join(m["seleccion"]), edificios_dentro=m["n_cub"],
                             pct_dentro=round(100*m["n_cub"]/D.n, 1), pct_ponderada=round(100*m["pond"]/r["wt"], 1),
                             alta_dentro=int((r["cub_best"][m["k"]] & (d.set_index("building_id").prioridad.reindex(D.ids).to_numpy()=="Alta")).sum()),
                             peor_min=round(m["peor"], 2), empates=m["empates"]))
PR = pd.DataFrame(prev); PR.to_csv(O/"paso4_vista_previa_optimizador.csv", index=False)
json.dump(res, open(O/"_paso4.json","w"), ensure_ascii=False, indent=1, default=str)
pd.set_option("display.width", 250)
print(json.dumps(res, ensure_ascii=False, indent=0, default=str)); print(mun.head(15)); print(SE.to_string())
print(PR[PR.k<=4].pivot_table(index=["umbral_min","k"], columns="pesos", values="seleccion", aggfunc="first").to_string())
print(PR[PR.k<=4].pivot_table(index=["umbral_min","k"], columns="pesos", values="alta_dentro", aggfunc="first").to_string())
print("alta total", (S.prioridad=="Alta").sum(), "alta sin ruta", ((S.prioridad=="Alta")&S.banda_acceso.eq("sin ruta")).sum())
print(S[S.prioridad.eq("Alta")].nlargest(5, "puntos_total")[["building_id","municipio","motivo_prioridad"]].to_string())
