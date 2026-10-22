"""flAIre · Persona 1 · Paso 6 (versión rápida): incendios anteriores 2018-2026 de la capa «Previous Wildfires» de FireScope.
Solo comprobación: no cambia la prioridad. Cada fila = un trozo de polígono (las teselas cortan polígonos grandes); se usa centroide + área."""
import pandas as pd, geopandas as gpd, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parents[1]; O = R/"processed/prioridad"
t = (R/"processed/incendios/firescope_incendios_previos_resumen.txt").read_text().strip()
f = pd.DataFrame([r.split(",") for r in t.split(";")], columns=["anio","lon","lat","area_m2"]).astype({"anio": int, "lon": float, "lat": float, "area_m2": float})
f = f.drop_duplicates()
g = gpd.GeoDataFrame(f, geometry=gpd.points_from_xy(f.lon, f.lat), crs=4326).to_crs(25830)
M = gpd.read_file(R/"processed/territory/territory.gpkg", layer="tolosaldea_municipalities").to_crs(25830)
ncol = [c for c in M.columns if c.lower() in ("name","municipio","muni_name","nombre")][0]
G = gpd.read_file(R/"processed/territory/territory.gpkg", layer="municipalities_gipuzkoa").to_crs(25830)
gcol = [c for c in G.columns if c.lower() in ("name","municipio","muni_name","nombre")][0]
g = gpd.sjoin(g, M[[ncol,"geometry"]].rename(columns={ncol: "municipio_tolosaldea"}), how="left", predicate="within").drop(columns="index_right")
g = gpd.sjoin(g, G[[gcol,"geometry"]].rename(columns={gcol: "municipio_gipuzkoa"}), how="left", predicate="within").drop(columns="index_right")
Cn = gpd.read_file(R/"processed/territory/territory.gpkg", layer="context_non_municipal").to_crs(25830)
Cn = Cn[Cn.eustat.astype(str).str.startswith("20")][["name","geometry"]].rename(columns={"name": "comun_gipuzkoa"})
g = gpd.sjoin(g, Cn, how="left", predicate="within").drop(columns="index_right")
g["municipio_gipuzkoa"] = g.municipio_gipuzkoa.fillna(g.comun_gipuzkoa); g = g.drop(columns="comun_gipuzkoa")
g["zona"] = np.where(g.municipio_tolosaldea.notna(), "Tolosaldea", np.where(g.municipio_gipuzkoa.notna(), "resto de Gipuzkoa", "Navarra"))
g["ha"] = (g.area_m2/1e4).round(2)
# distancia del centroide a la vivienda del conjunto más cercana y a la Alta más cercana (menos radio equivalente ≈ borde)
p = pd.read_parquet(O/"_step4.parquet"); e = pd.read_csv(O/"edificios_comun.csv", dtype={"building_id": str})[["building_id","x_25830","y_25830"]]
A = p[p.cerca_vegetacion.eq("sí")].merge(e, on="building_id")
from scipy.spatial import cKDTree
r_eq = np.sqrt(g.area_m2/np.pi)
for nom, sub in (("conjunto", A), ("alta", A[A.prioridad.eq("Alta")])):
    d, i = cKDTree(sub[["x_25830","y_25830"]].values).query(np.c_[g.geometry.x, g.geometry.y])
    g[f"dist_borde_aprox_{nom}_m"] = np.maximum(d - r_eq, 0).round(0)
    if nom == "alta": g["alta_mas_cercana"] = sub.building_id.values[i]; g["muni_alta_mas_cercana"] = sub.municipio.values[i]
out = g.drop(columns="geometry").sort_values(["zona","anio"])
out.to_csv(O/"paso6_incendios_previos.csv", index=False)
s = out.groupby("zona").agg(trozos=("ha","size"), ha=("ha","sum"), anios=("anio", lambda s: ",".join(map(str, sorted(set(s)))))).round(1)
print(s); print(out[out.zona.ne("Navarra")].to_string())
print(out.groupby(["zona","anio"]).ha.sum().round(1).unstack(0))
print("conjunto <=1km:", (out.dist_borde_aprox_conjunto_m<=1000).sum(), " alta<=2km:", (out.dist_borde_aprox_alta_m<=2000).sum())
print(out.nsmallest(8,"dist_borde_aprox_alta_m")[["anio","zona","municipio_gipuzkoa","ha","dist_borde_aprox_alta_m","muni_alta_mas_cercana","dist_borde_aprox_conjunto_m"]])
