"""Exporta el grafo EXACTO usado para los tiempos v0.3.1 en un kit autocontenido (processed/kit_rutas)."""
import geopandas as gpd, pandas as pd, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parents[1] / "work"; K = R/"processed/kit_rutas"; K.mkdir(exist_ok=True)
E = gpd.read_file(R/"processed/network/roads.gpkg", layer="road_edges", engine="pyogrio", use_arrow=True)
E["row"] = np.arange(len(E))
topo = ["row","edge_id","u","v","fclass","fclass_osm","oneway","length_m","maxspeed_osm","speed_used_kmh","speed_source","speed_truck_kmh",
        "t_light_s","t_truck_s","is_track","in_main_component","in_scc_with_tracks","region","ref","name"]
pd.DataFrame(E[topo]).to_parquet(K/"red_tramos_topologia.parquet", compression="zstd")
B = gpd.read_file(R/"processed/territory/tolosaldea_boundary.geojson").to_crs(25830)
zona = B.geometry.union_all().buffer(15000)
G = E[E.intersects(zona)][["row","edge_id","fclass","in_main_component","in_scc_with_tracks","is_track","geometry"]]
G.to_parquet(K/"red_tramos_geometria_tolosaldea_15km.parquet", compression="zstd")
pd.read_parquet(R/"processed/network/graph_nodes.parquet").to_parquet(K/"red_nodos.parquet", compression="zstd")
S = pd.read_parquet(R/"processed/links/building_snap_v0.3.1.parquet")
S.drop(columns=[c for c in ("x","y") if False]).to_csv(K/"snap_edificios.csv", index=False)
O = pd.read_parquet(R/"processed/links/origin_snap_v0.3.1.parquet")
c = pd.read_csv(R/"processed/candidates/candidates_10.csv")[["cand_id","pool_id"]]
O = O.merge(c, left_on="origin_id", right_on="pool_id", how="left")
O["id_agente"] = np.where(O.cand_id.notna(), O.cand_id, O.origin_id)
st = pd.read_csv(R/"agent/datos/parques.csv")[["origen_id","en_base"]]
O = O.merge(st, left_on="id_agente", right_on="origen_id", how="left").drop(columns=["origen_id","pool_id"])
O = O[O.origin_type.eq("station") | O.cand_id.notna()].copy()
O.to_csv(K/"snap_origenes.csv", index=False)
print(len(E), len(G), len(S)); print(O[["id_agente","origin_id","origin_type","name","snap_m","en_base"]].to_string())
for f in sorted(K.iterdir()): print(f.name, round(f.stat().st_size/1e6,1), "MB")
