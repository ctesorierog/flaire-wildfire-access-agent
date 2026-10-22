"""Comprueba la carpeta completa de datos del agente antes de subirla (solo Python estándar).
Uso: python check_datos_agente.py [carpeta]"""
import csv, json, sys
from pathlib import Path

D = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
err = []
leer = lambda n: list(csv.DictReader(open(D / n, encoding="utf-8")))
ARCHIVOS = ["edificios_prioridad.csv", "municipios.csv", "municipios.geojson", "meteo_mensual.csv", "meteo_anual.csv", "meteo_dias_riesgo.csv",
            "meteo_test_zonas.csv", "meteo_estaciones.csv", "incendios_previos.csv", "fuentes.csv", "metodologia.csv", "cifras_clave_persona1.json",
            "REGLAS_prioridad.md", "DICCIONARIO_datos.md", "tiempos_ligero.csv", "tiempos_camion.csv", "parques.csv", "candidatos.csv", "escenarios.csv"]
for n in ARCHIVOS:
    p = D / n
    if not p.exists(): err.append(f"falta {n}")
    elif p.stat().st_size > 3.5e6: err.append(f"{n} pesa más de 3,5 MB (límite de la plataforma: 4 MB)")
if err: print("\n".join(err)); sys.exit(1)
E = leer("edificios_prioridad.csv"); ids = {r["building_id"] for r in E}
if len(E) != 3331 or len(ids) != 3331: err.append(f"edificios_prioridad: {len(E)} filas / {len(ids)} IDs (esperados 3.331)")
P = leer("parques.csv"); C = leer("candidatos.csv")
origenes = [r["origen_id"] for r in P if r["en_base"] == "1"] + [r["origen_id"] for r in C]
for t in ("tiempos_ligero.csv", "tiempos_camion.csv"):
    T = leer(t)
    if {r["building_id"] for r in T} != ids: err.append(f"{t}: los building_id no coinciden con edificios_prioridad")
    falt = [o for o in origenes if o not in T[0]]
    if falt: err.append(f"{t}: faltan columnas {falt}")
    # coherencia: tiempo base de Persona 1 = mínimo de los parques en tiempos_ligero
    if t == "tiempos_ligero.csv":
        base = {r["building_id"]: r["t_base_ligero_min"] for r in E}
        mal = 0
        for r in T:
            v = [float(r[o]) for o in origenes if o.startswith(("GIP", "DON")) and r[o] != ""]
            b = base[r["building_id"]]
            if (not v) != (b == ""): mal += 1
            elif v and abs(min(v) - float(b)) > 0.011: mal += 1
        if mal: err.append(f"t_base_ligero_min no coincide con el mínimo de los parques en {mal} edificios")
cand = {r["origen_id"] for r in C}
for r in leer("escenarios.csv"):
    for c in filter(None, (r["seleccion"] or "").split(";")):
        if c not in cand: err.append(f"escenarios: candidata desconocida {c}"); break
M = leer("municipios.csv")
if len(M) != 28: err.append(f"municipios: {len(M)} filas")
k = json.load(open(D / "cifras_clave_persona1.json", encoding="utf-8"))
cl = {}
for r in E: cl[r["prioridad"]] = cl.get(r["prioridad"], 0) + 1
if cl != k["prioridad"]: err.append("cifras_clave no coincide con edificios_prioridad")
print(f"edificios {len(E)} · orígenes {len(origenes)} · candidatas {len(cand)} · municipios {len(M)} · prioridad {cl}")
print("RESULTADO:", "OK" if not err else "ERRORES"); [print(" -", e) for e in err]
sys.exit(1 if err else 0)
