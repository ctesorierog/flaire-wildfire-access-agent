"""flAIre · Persona 1 · Paso 5: FireScope (INSAIT) como REFERENCIA externa. No entra en la puntuación."""
import json, numpy as np, pandas as pd
from pathlib import Path
from pyproj import Transformer
R = Path(__file__).resolve().parents[2] / "work"; O = R/"processed/prioridad"
m = json.loads((R/"raw/firescope/firescope_tolosaldea_window.json").read_text())
a = np.fromfile(R/"raw/firescope/firescope_tolosaldea_window.bin", dtype=np.uint8).reshape(m["height"], m["width"]).astype(float); a[a == 255] = np.nan
ESC = 2.55   # web = raster / 2,55  (0-255 -> 0-100)
CUTS = [(25, "Seguro"), (50, "Bajo"), (75, "Moderado"), (1e9, "Alto")]   # leyenda oficial de firescope.ai (función riskCategory)
def clase(v):
    if pd.isna(v): return ""
    for c, n in CUTS:
        if v < c: return n
# --- calibración: celdas de 10.230 m del visor web frente a la media del ráster en la celda ---
C = 10230.0; cal = []
for tx, ty, v in json.load(open(R/"processed/firescope/web_cot_celdas_raw.json")):
    x0, x1, y0, y1 = tx*C, (tx+1)*C, ty*C, (ty+1)*C
    c0, c1 = int((x0-m["window_x0"])/30), int((x1-m["window_x0"])/30); r0, r1 = int((m["window_y0"]-y1)/30), int((m["window_y0"]-y0)/30)
    if c0 < 0 or r0 < 0 or c1 > m["width"] or r1 > m["height"]: continue
    s = a[r0:r1, c0:c1]
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform((x0+x1)/2, (y0+y1)/2)
    cal.append(dict(celda_tx=tx, celda_ty=ty, lon_centro=round(lon, 4), lat_centro=round(lat, 4), valor_web=v,
                    raster_media=round(np.nanmean(s), 1), raster_mediana=float(np.nanmedian(s)), web_estimado=round(np.nanmean(s)/ESC, 1)))
cal = pd.DataFrame(cal); cal["error"] = (cal.web_estimado - cal.valor_web).round(1)
cal.to_csv(O/"paso5_calibracion_firescope.csv", index=False)
# --- por edificio (los 14.015) ---
e = pd.read_csv(O/"edificios_comun.csv", dtype={"building_id": str})[["building_id","lon","lat"]]
X, Y = Transformer.from_crs(4326, 3857, always_xy=True).transform(e.lon.values, e.lat.values)
c = ((X-m["window_x0"])/30).astype(int); r = ((m["window_y0"]-Y)/30).astype(int); k = 4
e["fs_px_0_255"] = a[r, c]
e["fs_media_9x9_0_255"] = [np.nanmean(a[i-k:i+k+1, j-k:j+k+1]) for i, j in zip(r, c)]
e["fs_puntuacion_0_100"] = (e.fs_media_9x9_0_255/ESC).round(1)
e["fs_clase"] = e.fs_puntuacion_0_100.map(clase)
p = pd.read_parquet(O/"_step4.parquet")[["building_id","municipio","cerca_vegetacion","prioridad","puntos_total","puntos_distancia","puntos_vegetacion","puntos_acceso",
                                         "dist_veg_m","tipo_veg_nivel","subcategoria_vegetacion"]]
d = p.merge(e, on="building_id", validate="1:1")
out = d[["building_id","municipio","fs_px_0_255","fs_media_9x9_0_255","fs_puntuacion_0_100","fs_clase","prioridad","puntos_total"]].copy()
out["fs_media_9x9_0_255"] = out.fs_media_9x9_0_255.round(1); out["uso"] = "solo referencia: no entra en la prioridad"
out.to_csv(O/"paso5_firescope_edificios.csv", index=False)
A = d[d.cerca_vegetacion.eq("sí")]
res = dict(
  cal_n=len(cal), cal_err_abs_max=float(cal.error.abs().max()), cal_err_abs_mean=float(cal.error.abs().mean()),
  cal_spearman=float(cal[["valor_web","raster_media"]].corr("spearman").iloc[0,1]),
  todos=d.fs_clase.value_counts().to_dict(), conjunto=A.fs_clase.value_counts().to_dict(),
  conj_desc=A.fs_puntuacion_0_100.describe().round(1).to_dict(), resto_desc=d[~d.cerca_vegetacion.eq("sí")].fs_puntuacion_0_100.describe().round(1).to_dict(),
  spearman={k: round(float(A[["fs_puntuacion_0_100", k]].corr("spearman").iloc[0,1]), 2) for k in ["puntos_total","puntos_distancia","puntos_vegetacion","puntos_acceso","dist_veg_m"]},
  por_prioridad=A.groupby("prioridad").fs_puntuacion_0_100.describe()[["count","mean","50%"]].round(1).to_dict(),
  por_nivel_veg=A.groupby("tipo_veg_nivel").fs_puntuacion_0_100.median().round(1).to_dict(),
  por_subcat=A.groupby("subcategoria_vegetacion").fs_puntuacion_0_100.median().round(1).to_dict(),
)
ct = pd.crosstab(A.prioridad, A.fs_clase).reindex(index=["Alta","Media","Baja"], columns=["Seguro","Bajo","Moderado","Alto"], fill_value=0)
ct.to_csv(O/"paso5_cruce_prioridad_firescope.csv"); print(ct)
mu = A.groupby("municipio").agg(edificios=("building_id","size"), fs_mediana=("fs_puntuacion_0_100","median"), alta_flaire=("prioridad", lambda s: (s=="Alta").sum()),
                                fs_moderado_o_alto=("fs_clase", lambda s: s.isin(["Moderado","Alto"]).sum())).round(1).sort_values("fs_mediana", ascending=False)
mu.to_csv(O/"paso5_firescope_x_municipio.csv"); print(mu.to_string())
# discrepancias
dis = pd.concat([A[(A.prioridad=="Alta") & A.fs_clase.isin(["Seguro","Bajo"])].assign(tipo="Alta en flAIre, Seguro/Bajo en FireScope"),
                 A[(A.prioridad=="Baja") & A.fs_clase.isin(["Alto"])].assign(tipo="Baja en flAIre, Alto en FireScope")])
dis[["tipo","building_id","municipio","prioridad","puntos_total","fs_puntuacion_0_100","fs_clase","dist_veg_m","subcategoria_vegetacion"]].to_csv(O/"paso5_discrepancias.csv", index=False)
res["discrepancias"] = dis.tipo.value_counts().to_dict()
json.dump(res, open(O/"_paso5.json","w"), ensure_ascii=False, indent=1, default=str)
print(cal.to_string()); print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
