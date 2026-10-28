"""flAIre · Persona 1 → Persona 2: paquete de integración de la prioridad (v1, 2-oct-2026)."""
import numpy as np, pandas as pd, sys
from pathlib import Path
R = Path(__file__).resolve().parents[2] / "work"; O = R/"processed/prioridad"; E = O/"entrega_persona2"; E.mkdir(exist_ok=True)
d = pd.read_parquet(O/"_step4.parquet")
PD = {"dentro": 3, "0–25": 3, "25–50": 2, "50–100": 1}; PV = {3: 2, 2: 1, 1: 0}; PA = {"≤8": 0, "8–12": 1, "12–15": 2, ">15": 3, "sin ruta": 3}
d["posible_caserio"] = np.where(d.farmhouse_nombre.fillna(False).astype(bool) & d.residencial.eq("desconocido"), "sí", "no")
m = d.posible_caserio.eq("sí") & d.dist_veg_m.le(100)
pt = d.banda_distancia.map(PD) + d.tipo_veg_nivel.map(PV) + d.banda_acceso.map(PA)
d["prioridad_si_caserio"] = np.where(m, np.where(pt >= 6, "Alta", np.where(pt >= 4, "Media", "Baja")), "")
A = d[d.cerca_vegetacion.eq("sí")].copy()
cols = ["building_id","municipio","viviendas","prioridad_sin_acceso","peso_prioridad_sin_acceso","prioridad","peso_prioridad",
        "puntos_distancia","puntos_vegetacion","puntos_acceso","puntos_meteo","puntos_total","banda_acceso","acceso_desconocido","motivo_prioridad"]
o = A[cols].copy(); o["version_reglas"] = "PRIO-v1 (2026-10-02)"
for c in ["puntos_distancia","puntos_vegetacion","puntos_acceso","puntos_meteo","puntos_total"]: o[c] = o[c].astype(int)
o.to_csv(E/"prioridad_v1_optimizador.csv", index=False)
# viviendas Alta que no quedan dentro de 12 min con k = 3 (CAND-01,02,03) y sin ruta
v = pd.read_csv(O/"paso4_vista_previa_optimizador.csv")
sys.path.insert(0, str(R/"agent")); import flaire_data as F
ev = F._evaluar(["CAND-01","CAND-02","CAND-03"], 12.0, "ligero", "uniforme"); D = F.datos()
cub = pd.Series(ev["cubierto"], index=D.ids); best = pd.Series(ev["best"], index=D.ids)
al = A[A.prioridad.eq("Alta")].copy(); al["t_con_k3_min"] = al.building_id.map(best).replace(np.inf, np.nan).round(2)
al["situacion_k3_12min"] = np.where(al.acceso_desconocido.eq("sí"), "sin ruta: ningún retén lo mejora",
                               np.where(al.building_id.map(cub), "dentro de 12 min con k=3", "fuera de 12 min con k=3"))
al[["building_id","municipio","viviendas","puntos_total","t_base_ligero_min","t_con_k3_min","situacion_k3_12min","motivo_prioridad"]] \
  .sort_values(["situacion_k3_12min","municipio"]).to_csv(E/"alta_y_cobertura_k3.csv", index=False)
print(al.situacion_k3_12min.value_counts())
cas = d[m][["building_id","municipio","dist_veg_m","banda_distancia","subcategoria_vegetacion","t_base_ligero_min","banda_acceso","prioridad_si_caserio"]]
cas.to_csv(E/"caserios_uso_desconocido_revisar.csv", index=False); print(cas.prioridad_si_caserio.value_counts())
# valores esperados para comprobar la integración
ref = v[(v.pesos.isin(["prioridad_sin_acceso","prioridad"])) & (v.k <= 6)][["umbral_min","pesos","k","seleccion","edificios_dentro","pct_ponderada","alta_dentro","peor_min"]]
ref.to_csv(E/"valores_esperados_optimizador.csv", index=False)
# también al archivo general
out = pd.read_csv(O/"paso4_puntos.csv", dtype={"building_id": str})
out = out.merge(d[["building_id","posible_caserio","prioridad_si_caserio"]], on="building_id", validate="1:1")
cl = list(out.columns); cl.remove("version_reglas"); out[cl + ["version_reglas"]].to_csv(O/"paso4_puntos.csv", index=False)
print(o.peso_prioridad_sin_acceso.mean(), o.isna().sum().sum(), len(o))
