"""flAIre · Persona 1 · Paso 2: acceso desde los parques existentes (tiempo actual, 0 retenes extra)."""
import numpy as np, pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parents[2] / "work"; O = R / "processed/prioridad"
b = pd.read_csv(R/"processed/links/baseline_buildings_v0.3.1.csv", dtype={"building_id": str})
s = pd.read_parquet(R/"processed/links/building_snap_v0.3.1.parquet")[["building_id","nearest_any_m","nearest_any_class"]]
t = pd.read_csv(R/"processed/links/tracks_variant_unroutable_v0.3.1.csv", dtype={"building_id": str})
p1 = pd.read_parquet(O/"_step1.parquet")[["building_id","municipio","residencial","viviendas","dist_veg_m","cerca_vegetacion"]]
d = p1.merge(b, on="building_id", how="left", validate="1:1").merge(s, on="building_id", how="left", validate="1:1")
d = d.merge(t[["building_id","base_light_min_with_tracks","base_light_station_with_tracks","snap_edge_class_with_tracks"]], on="building_id", how="left")
assert len(d) == 14015 and d.base_light_min.isna().eq(d.routable.eq(0)).all()
def banda(x):
    if pd.isna(x): return "sin ruta"
    return "≤8" if x <= 8 else "8–12" if x <= 12 else "12–15" if x <= 15 else ">15"
d["banda_acceso"] = d.base_light_min.map(banda)
d["acceso_desconocido"] = np.where(d.routable.eq(0), "sí", "no")
d["motivo_sin_ruta"] = np.where(d.routable.eq(0), "edificio a más de 150 m de una vía de la red (snap>150m)", "")
out = pd.DataFrame({
 "building_id": d.building_id, "municipio": d.municipio, "residencial": d.residencial, "cerca_vegetacion": d.cerca_vegetacion,
 "t_base_ligero_min": d.base_light_min.round(2), "parque_base_ligero": d.base_light_station, "km_ligero": d.base_light_km.round(3),
 "t_segundo_parque_ligero_min": d.second_light_min.round(2),
 "t_base_camion_min": d.base_truck_min.round(2), "parque_base_camion": d.base_truck_station, "km_camion": d.base_truck_km.round(3),
 "km_navarra_ligero": d.base_light_nav_km.round(3),
 "banda_acceso": d.banda_acceso, "acceso_desconocido": d.acceso_desconocido, "motivo_sin_ruta": d.motivo_sin_ruta,
 "snap_m": d.snap_m.round(1), "via_snap": d.snap_road, "clase_via_snap": d.snap_edge_class,
 "via_mas_cercana_m": d.nearest_any_m.round(1), "clase_via_mas_cercana": d.nearest_any_class,
 "t_ligero_con_pistas_min": d.base_light_min_with_tracks.round(2), "parque_con_pistas": d.base_light_station_with_tracks,
 "version_datos": "v0.3.1-red/v0.3.2-veg"})
out.to_csv(O/"paso2_acceso.csv", index=False)
d.to_parquet(O/"_step2.parquet")
A = d[d.cerca_vegetacion.eq("sí")]
order = ["≤8","8–12","12–15",">15","sin ruta"]
tab = pd.crosstab(A.municipio, A.banda_acceso).reindex(columns=order, fill_value=0)
tab["total"] = tab.sum(1); tab["mediana_min"] = A.groupby("municipio").base_light_min.median().round(1)
tab["max_min"] = A.groupby("municipio").base_light_min.max().round(1)
tab = tab.sort_values(">15", ascending=False); tab.to_csv(O/"paso2_banda_x_municipio.csv")
print(tab.to_string()); print(tab[order].sum())
print("viviendas por banda", A.groupby("banda_acceso").viviendas.sum().reindex(order))
print("resid all", d[d.residencial.eq("sí")].banda_acceso.value_counts().reindex(order))
print("all", d.banda_acceso.value_counts().reindex(order))
print(A.base_light_min.describe(percentiles=[.5,.9,.95]))
w = A.dropna(subset=["base_light_min"]).nlargest(10,"base_light_min")[["building_id","municipio","base_light_min","base_light_station","base_truck_min","second_light_min","snap_road","snap_edge_class","snap_m","viviendas"]]
w.to_csv(O/"paso2_peores10.csv", index=False); print(w.to_string())
u = A[A.routable.eq(0)][["building_id","municipio","viviendas","dist_veg_m","snap_m","nearest_any_m","nearest_any_class","base_light_min_with_tracks","base_light_station_with_tracks"]].sort_values("snap_m")
u.to_csv(O/"paso2_sin_ruta.csv", index=False); print(len(u)); print(u.to_string())
print(u.municipio.value_counts()); print(u.nearest_any_class.value_counts()); print(u.snap_m.describe()); print("viv", u.viviendas.sum(), u.viviendas.isna().sum())
print("tracks variant band", u.base_light_min_with_tracks.map(banda).value_counts())
print("truck", A.base_truck_min.map(lambda x: banda(x)).value_counts().reindex(order))
# agreement with agent data
e = pd.read_csv(R/"agent/datos/edificios.csv", dtype={"building_id": str})[["building_id","t_base_ligero"]].merge(A[["building_id","base_light_min"]])
print("agent match", len(e), (e.t_base_ligero.fillna(-1)-e.base_light_min.fillna(-1)).abs().max())
print("stations", A.base_light_station.value_counts())
