"""flAIre · carpeta ÚNICA con todos los datos que necesita el agente (Persona 1 + Persona 2), lista para subir a agentes/flaire/datos/."""
import json, shutil, zipfile, numpy as np, pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parents[2] / "work"; P1 = R/"processed/datos_agente_persona1"; A = R/"agent/datos"; O = R/"processed/datos_agente_completo"
if O.exists(): shutil.rmtree(O)
O.mkdir()
# Persona 1
for f in P1.iterdir():
    if f.name not in ("LEEME_QUE_SUBIR.md", "check_datos_persona1.py"): shutil.copy(f, O/f.name)
# edificios_prioridad: añadir los dos pesos alternativos antiguos (solo para análisis de sensibilidad del optimizador)
e = pd.read_csv(O/"edificios_prioridad.csv", dtype={"building_id": str, "muni_ine": str})
old = pd.read_csv(A/"edificios.csv", dtype={"building_id": str})[["building_id","peso_meteo","peso_firescope"]]
e = e.merge(old.rename(columns={"peso_meteo": "peso_meteo_sensibilidad", "peso_firescope": "peso_firescope_sensibilidad"}), on="building_id", how="left", validate="1:1")
e["viviendas"] = e.viviendas.astype("Int64")
e.to_csv(O/"edificios_prioridad.csv", index=False)
# Persona 2 (sin cambios)
for f in ("tiempos_ligero.csv", "tiempos_camion.csv", "parques.csv", "candidatos.csv", "escenarios.csv"): shutil.copy(A/f, O/f)
# fuentes.csv único
fp1 = pd.read_csv(P1/"fuentes_persona1.csv"); fa = pd.read_csv(A/"fuentes.csv")
p2 = fa[fa.source_id.isin(["SRC-B5M-FIREST","SRC-OSM-GEOFABRIK-PV-20260930","SRC-OSM-GEOFABRIK-NAV-20260930","SRC-FLAIRE-CAND-V031","SRC-FLAIRE-LINK-V031"])]
pd.concat([fp1, p2], ignore_index=True).assign(responsable=lambda x: np.where(x.source_id.isin(p2.source_id), "Persona 2", "Persona 1")) \
  .to_csv(O/"fuentes.csv", index=False)
(O/"fuentes_persona1.csv").unlink()
# metodologia.csv único (filas de Persona 2 sin cambios; filas de Persona 1 actualizadas)
m = pd.read_csv(A/"metodologia.csv")
upd = {
 "version_datos": ("v0.3.2 + P1-v1 (2026-10-03)", "Datos territoriales v0.3.2 (vegetación revisada) y prioridad PRIO-v1; tiempos y escenarios v0.3.1 (Persona 2)."),
 "pesos_meteo": ("solo sensibilidad", "peso_meteo_sensibilidad (jul-ago, ADV-v1) se conserva solo como análisis de sensibilidad: las zonas meteorológicas NO se distinguen con 2018-2023 (meteo_test_zonas.csv), por eso no entra en la prioridad."),
 "cobertura_ponderada": ("suma del peso elegido de los edificios cubiertos", "Peso recomendado: peso_optimizador (prioridad sin acceso). Alternativas: uniforme, peso_meteo_sensibilidad, peso_firescope_sensibilidad. NO es población protegida."),
 "regla_ADV-v1": ("CS-v1 calor seco = ADV-v1", "Tmax ≥ 25 °C y HRmin ≤ 40 % y sin día de lluvia (≥ 1 mm) en los 3 días previos. Indicador exploratorio (NO FWI)."),
 "temporada": ("todo el año: días de riesgo", "Días de riesgo = calor seco o viento sur seco. Julio-agosto solo tienen el 14 % de los días de riesgo; febrero-abril el 32 % y septiembre-octubre el 31 %. Propuesta: activar retenes en días de riesgo (meteo_mensual.csv, meteo_dias_riesgo.csv)."),
 "pesos_firescope": ("solo sensibilidad", "peso_firescope_sensibilidad: FireScope (INSAIT) normalizado a media 1. Referencia externa; no entra en la prioridad. Puntuación 0-100 = ráster/2,55 (fs_puntuacion_0_100, fs_clase)."),
}
for k, (v, x) in upd.items(): m.loc[m.clave.eq(k), ["valor","explicacion"]] = [v, x]
new = pd.DataFrame([
 ("regla_VS-v1", "viento sur seco", "≥ 18 registros de 10 min (≈ 3 h) con viento del sector S (135-225°) ≥ 3 m/s y HR ≤ 50 %, y sin día de lluvia (≥ 1 mm) en los 3 días previos. Detecta el episodio Bera-Aiako Harria (19-21/02/2021)."),
 ("prioridad", "Alta ≥ 6 · Media 4-5 · Baja ≤ 3 (puntos 1-8)", "Puntos: distancia a vegetación (1-3) + tipo de vegetación (0-2) + acceso actual (0-3) + meteorología (0 para todos). Prioridad de planificación, NO probabilidad de incendio. Ver REGLAS_prioridad.md."),
 ("peso_optimizador", "Alta 3 · Media 2 · Baja 1 → media 1, sin el componente de acceso", "Para el optimizador (el acceso ya está en su objetivo; así no se cuenta dos veces). peso_prioridad (con acceso) es para el ranking y los mapas."),
 ("incendios_previos", "capa FireScope «Previous Wildfires» 2018-2026 (aproximada)", "Solo referencia: dentro de Tolosaldea solo Amezketa 2019 (~39 ha); casi todo lo quemado está en Navarra."),
], columns=["clave","valor","explicacion"])
pd.concat([m, new], ignore_index=True).to_csv(O/"metodologia.csv", index=False)
with zipfile.ZipFile(R/"processed/flaire_datos_agente_completo.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(O.iterdir()): z.write(f, f.name)
for f in sorted(O.iterdir()): print(f.name, round(f.stat().st_size/1e6, 3), "MB")
print("zip", round((R/"processed/flaire_datos_agente_completo.zip").stat().st_size/1e6, 2), "MB")
