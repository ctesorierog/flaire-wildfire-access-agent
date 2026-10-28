"""flAIre · Persona 1 → agente: paquete de datos que SUSTITUYE a los datos territoriales/meteorológicos antiguos.
Salida: processed/datos_agente_persona1/ (cada archivo < 3,5 MB, UTF-8, coma, punto decimal, vacío = desconocido)."""
import json, numpy as np, pandas as pd, geopandas as gpd, shutil
from pathlib import Path
from scipy.spatial import cKDTree
R = Path(__file__).resolve().parents[2] / "work"; P = R/"processed/prioridad"; O = R/"processed/datos_agente_persona1"
if O.exists(): shutil.rmtree(O)
O.mkdir()
VER = "P1-v1 (2026-10-03) · datos v0.3.2 · reglas PRIO-v1"
SUB = {"natural_broadleaf": "frondosa natural", "riparian_broadleaf": "bosque de galería", "plantation_conifer": "plantación de coníferas",
       "plantation_broadleaf": "plantación de frondosas", "scrub": "matorral", "plantation_mixed": "plantación mixta",
       "natural_mixed": "bosque mixto natural", "pasture_scrub_mosaic": "mosaico pastizal-matorral"}
# 1 · edificios_prioridad.csv (3.331 viviendas del conjunto de análisis)
s4 = pd.read_parquet(P/"_step4.parquet"); com = pd.read_csv(P/"edificios_comun.csv", dtype={"building_id": str, "muni_ine": str})
fs = pd.read_csv(P/"paso5_firescope_edificios.csv", dtype={"building_id": str})[["building_id","fs_puntuacion_0_100","fs_clase"]]
s2 = pd.read_csv(P/"paso2_acceso.csv", dtype={"building_id": str})[["building_id","t_base_camion_min","parque_base_camion","t_segundo_parque_ligero_min"]]
d = s4[s4.cerca_vegetacion.eq("sí")].merge(com[["building_id","muni_ine","lon","lat","x_25830","y_25830","uso_original"]], on="building_id") \
      .merge(fs, on="building_id").merge(s2, on="building_id")
inc = pd.read_csv(P/"paso6_incendios_previos.csv")
ig = gpd.GeoSeries(gpd.points_from_xy(inc.lon, inc.lat), crs=4326).to_crs(25830)
dist, i = cKDTree(np.c_[ig.x, ig.y]).query(d[["x_25830","y_25830"]].values)
d["dist_incendio_previo_aprox_m"] = np.maximum(dist - np.sqrt(inc.area_m2.values[i]/np.pi), 0).round(0)
d["anio_incendio_previo_cercano"] = inc.anio.values[i]
d["vegetacion_cercana"] = d.subcategoria_vegetacion.map(SUB)
E = pd.DataFrame({
  "building_id": d.building_id, "muni_ine": d.muni_ine, "municipio": d.municipio, "lon": d.lon, "lat": d.lat,
  "viviendas": d.viviendas.astype("Int64"), "uso_original": d.uso_original,
  "dist_veg_m": d.dist_veg_m.round(1), "banda_distancia": d.banda_distancia, "vegetacion_cercana": d.vegetacion_cercana,
  "tipo_veg_nivel": d.tipo_veg_nivel.astype(int),
  "t_base_ligero_min": d.t_base_ligero_min, "parque_base_ligero": d.parque_base_ligero, "t_segundo_parque_ligero_min": d.t_segundo_parque_ligero_min,
  "t_base_camion_min": d.t_base_camion_min, "parque_base_camion": d.parque_base_camion,
  "banda_acceso": d.banda_acceso, "sin_ruta": d.acceso_desconocido, "zona_meteo": d.zona_meteo,
  "puntos_distancia": d.puntos_distancia.astype(int), "puntos_vegetacion": d.puntos_vegetacion.astype(int),
  "puntos_acceso": d.puntos_acceso.astype(int), "puntos_meteo": d.puntos_meteo.astype(int), "puntos_total": d.puntos_total.astype(int),
  "prioridad": d.prioridad, "peso_prioridad": d.peso_prioridad,
  "prioridad_sin_acceso": d.prioridad_sin_acceso, "peso_optimizador": d.peso_prioridad_sin_acceso,
  "motivo_prioridad": d.motivo_prioridad,
  "fs_puntuacion_0_100": d.fs_puntuacion_0_100, "fs_clase": d.fs_clase,
  "dist_incendio_previo_aprox_m": d.dist_incendio_previo_aprox_m.astype(int), "anio_incendio_previo_cercano": d.anio_incendio_previo_cercano})
E.to_csv(O/"edificios_prioridad.csv", index=False)
# 2 · municipios.csv (resumen) + geojson
mu_old = pd.read_csv(R/"agent/datos/municipios.csv", dtype={"muni_ine": str})
g = E.groupby("municipio")
mu = pd.DataFrame({"edificios_analisis": g.size(), "viviendas_analisis": g.viviendas.sum(),
                   "alta": g.prioridad.apply(lambda s: (s=="Alta").sum()), "media": g.prioridad.apply(lambda s: (s=="Media").sum()),
                   "baja": g.prioridad.apply(lambda s: (s=="Baja").sum()), "viviendas_alta": E[E.prioridad.eq("Alta")].groupby("municipio").viviendas.sum(),
                   "sin_ruta": g.sin_ruta.apply(lambda s: (s=="sí").sum()),
                   "t_base_mediana_min": g.t_base_ligero_min.median().round(1), "t_base_max_min": g.t_base_ligero_min.max().round(1),
                   "fs_mediana": g.fs_puntuacion_0_100.median().round(1)}).reset_index()
mu = mu_old[["muni_ine","municipio","area_km2","zona_meteo","edificios_total","residenciales"]].merge(mu, on="municipio", how="left")
for c in ["alta","media","baja","viviendas_alta","sin_ruta"]: mu[c] = mu[c].fillna(0).astype(int)
ii = inc[inc.zona.eq("Tolosaldea")].groupby("municipio_tolosaldea").ha.sum()
mu["ha_incendios_previos_2018_2026_aprox"] = mu.municipio.map(ii).fillna(0).round(1)
mu.to_csv(O/"municipios.csv", index=False)
shutil.copy(R/"agent/datos/municipios.geojson", O/"municipios.geojson")
# 3 · meteorología todo el año
mm = pd.read_csv(P/"paso3_meteo_mensual.csv")
mm = mm[["station_id","zona","mes","dias_validos","dias_cs","dias_vs","dias_riesgo","dias_cs_por_mes","dias_vs_por_mes","dias_riesgo_por_mes"]] \
       .rename(columns={"station_id": "codigo", "dias_cs": "dias_calor_seco", "dias_vs": "dias_viento_sur", "dias_cs_por_mes": "media_calor_seco_por_mes",
                        "dias_vs_por_mes": "media_viento_sur_por_mes", "dias_riesgo_por_mes": "media_dias_riesgo_por_mes"})
mm.to_csv(O/"meteo_mensual.csv", index=False)
ma = pd.read_csv(P/"paso3_meteo_anual.csv").rename(columns={"station_id": "codigo","dias_cs": "dias_calor_seco","dias_vs": "dias_viento_sur","completo": "anio_completo"})
ma["anio_completo"] = np.where(ma.anio_completo, "sí", "no"); ma.to_csv(O/"meteo_anual.csv", index=False)
dr = pd.read_csv(P/"paso3_dias_riesgo.csv").rename(columns={"station_id": "codigo","date": "fecha","tmax_c": "tmax_c","rhmin_pct": "hr_min_pct",
       "s_dry_slots": "registros_viento_sur_seco_10min","gust_max_s": "racha_max_sur_ms","precip_mm": "lluvia_dia_mm"})
dr["tipo"] = dr.tipo.map({"CS": "calor seco", "VS": "viento sur seco", "CS+VS": "calor seco + viento sur"}); dr.to_csv(O/"meteo_dias_riesgo.csv", index=False)
tz = pd.read_csv(P/"paso3_test_zonas.csv"); tz["distinguible"] = np.where(tz.distinguible, "sí", "no"); tz.to_csv(O/"meteo_test_zonas.csv", index=False)
shutil.copy(R/"agent/datos/meteo_estaciones.csv", O/"meteo_estaciones.csv")
# 4 · incendios previos
inc2 = inc.rename(columns={"area_m2": "superficie_m2", "ha": "superficie_ha_aprox", "dist_borde_aprox_conjunto_m": "dist_vivienda_conjunto_aprox_m",
                           "dist_borde_aprox_alta_m": "dist_vivienda_alta_aprox_m"})
inc2["fuente"] = "FireScope «Previous Wildfires» (firescope.ai); fuente original no documentada; aproximado"
inc2.to_csv(O/"incendios_previos.csv", index=False)
# 5 · fuentes de Persona 1
f = pd.read_csv(R/"agent/datos/fuentes.csv")
keep = ["SRC-B5M-BU","SRC-GV-INVFORESTAL-2024","SRC-GV-MUNICIPIOS5000-20250507","SRC-EUSKALMET-STATIONS"] + [x for x in f.source_id if x.startswith("SRC-EUSKALMET-MET")] + ["SRC-INSAIT-FIRESCOPE-2026"]
F = f[f.source_id.isin(keep)].copy()
F = pd.concat([F, pd.DataFrame([
  dict(source_id="SRC-FIRESCOPE-WEB-COT", conjunto="FireScope · valores del visor web (celdas de 10,23 km) usados para calibrar la escala", organismo="INSAIT (firescope.ai)",
       url="https://firescope.ai/", licencia="CC BY 4.0 (según el conjunto de datos de INSAIT)", fecha_descarga="2026-10-03", edicion_periodo="mapa 2026",
       archivo="03_datos_procesados/firescope/web_cot_celdas_raw.json", sha256="", estado="referencia"),
  dict(source_id="SRC-FIRESCOPE-INCENDIOS-PREVIOS", conjunto="FireScope · capa «Previous Wildfires» 2018-2026 (polígonos con año)", organismo="INSAIT (firescope.ai)",
       url="https://tiles.firescope.ai/mixed_eurasia_fires.pmtiles", licencia="sin licencia explícita en el visor; fuente original no documentada", fecha_descarga="2026-10-03",
       edicion_periodo="2018-2026", archivo="03_datos_procesados/incendios/firescope_incendios_previos_resumen.txt", sha256="", estado="referencia aproximada"),
  dict(source_id="SRC-DFG-INCENDIOS-ESTADISTICA", conjunto="Estadística de incendios forestales de Gipuzkoa 2012-2023 (número y hectáreas por año)", organismo="Diputación Foral de Gipuzkoa",
       url="https://www.gipuzkoa.eus/es/web/mendiak-eremunaturalak/gestion-montes/forestal/incendios-forestales", licencia="consulta web", fecha_descarga="2026-10-02",
       edicion_periodo="2012-2023", archivo="(tabla web)", sha256="", estado="contexto")])], ignore_index=True)
F.to_csv(O/"fuentes_persona1.csv", index=False)
# 6 · resumen de cifras clave (para que el agente no tenga que recalcular)
A = E
k = {"version": VER, "edificios_analisis": len(A), "viviendas_analisis": int(A.viviendas.sum()),
     "prioridad": A.prioridad.value_counts().to_dict(), "viviendas_por_prioridad": A.groupby("prioridad").viviendas.sum().astype(int).to_dict(),
     "prioridad_sin_acceso": A.prioridad_sin_acceso.value_counts().to_dict(),
     "alta_sin_ruta": int(((A.prioridad=="Alta")&(A.sin_ruta=="sí")).sum()),
     "acceso_bandas": A.banda_acceso.value_counts().to_dict(),
     "alta_dentro_12min_k0": 49, "alta_dentro_12min_k3_CAND01_02_03": 177,
     "meteo_zonas_distinguibles": "no", "meteo_dias_riesgo_anuales_media": 26.3,
     "meteo_reparto": {"feb-abr": 0.32, "jul-ago": 0.14, "sep-oct": 0.31},
     "firescope_clases_conjunto": A.fs_clase.value_counts().to_dict(),
     "incendios_previos_ha_aprox": inc.groupby("zona").ha.sum().round(1).to_dict()}
json.dump(k, open(O/"cifras_clave_persona1.json","w"), ensure_ascii=False, indent=1)
for x in sorted(O.iterdir()): print(x.name, round(x.stat().st_size/1e6, 3), "MB")
print(json.dumps(k, ensure_ascii=False))
