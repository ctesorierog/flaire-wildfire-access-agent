"""Paquete de datos SINTÉTICO con las columnas del contrato v0.3, para probar sin agent/datos/.
escenarios.csv se calcula con una implementación de fuerza bruta en Python puro (independiente de flaire_data)."""
import itertools, json, math, random
from pathlib import Path

MUNIS = [("20071", "Tolosa", "C029"), ("20008", "Amezketa", "C026"), ("20022", "Berastegi", "C026"),
         ("20024", "Bidania-Goiatz", "C058"), ("20075", "Villabona", "C029")]
FREQ = {"C026": 0.0847, "C029": 0.0524, "C058": 0.0766}
PARKS = ["GIP-ORIA", "GIP-GOIERRI", "DON-GARBERA"]
CANDS = [f"CAND-{i:02d}" for i in range(1, 11)]


def construir(dest: Path, n=300, seed=7):
    rnd = random.Random(seed)
    dest.mkdir(parents=True, exist_ok=True)
    centers = {"20071": (-2.07, 43.13), "20008": (-2.08, 43.04), "20022": (-1.97, 43.12), "20024": (-2.16, 43.14), "20075": (-2.05, 43.20)}
    edif, tl, tc = [], [], []
    mean_f = 0
    rows = []
    for i in range(n):
        ine, name, z = MUNIS[i % len(MUNIS)]
        lon = centers[ine][0] + rnd.uniform(-0.03, 0.03); lat = centers[ine][1] + rnd.uniform(-0.02, 0.02)
        rows.append((f"ES.GFA.BU.{1000 + i}", ine, name, z, lon, lat))
        mean_f += FREQ[z]
    mean_f /= n
    for bid, ine, name, z, lon, lat in rows:
        unr = rnd.random() < 0.03
        times = {}
        for o in PARKS + CANDS:
            base = rnd.uniform(4, 22) if o in PARKS else rnd.uniform(2, 30)
            times[o] = None if unr else round(base, 2)
        tr = {o: (None if v is None else round(v * 1.2, 2)) for o, v in times.items()}
        bp = min(PARKS, key=lambda o: times[o] if times[o] is not None else 1e9)
        edif.append(dict(building_id=bid, muni_ine=ine, municipio=name, lon=round(lon, 6), lat=round(lat, 6), viviendas=rnd.randint(1, 6),
                         uso_original="individualResidence 100%", residencial_regla="use", dist_veg_m=round(rnd.uniform(0, 100), 2),
                         veg_clase_cercana="forest_broadleaf", zona_meteo=z, peso_meteo=round(FREQ[z] / mean_f, 6), freq_adversa=FREQ[z],
                         estado_ruta="sin_ruta: snap>150m" if unr else "calculado", snap_m=200.0 if unr else round(rnd.uniform(1, 80), 1),
                         parque_base_ligero="" if unr else bp, t_base_ligero="" if unr else times[bp],
                         parque_base_camion="" if unr else bp, t_base_camion="" if unr else tr[bp]))
        tl.append(dict(building_id=bid, **{o: ("" if v is None else v) for o, v in times.items()}))
        tc.append(dict(building_id=bid, **{o: ("" if v is None else v) for o, v in tr.items()}))
    import csv
    def w(name, rows_, cols=None):
        cols = cols or list(rows_[0].keys())
        with open(dest / name, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows_)
    w("edificios.csv", edif); w("tiempos_ligero.csv", tl); w("tiempos_camion.csv", tc)
    w("parques.csv", [dict(origen_id=p, nombre=f"Parque {p}", municipio="Tolosa", lon=-2.08 + 0.01 * k, lat=43.13, en_base=1, fuente="SRC-B5M-FIREST", snap_m=10, nota="")
                      for k, p in enumerate(PARKS)] + [dict(origen_id="OTH-HONDARRIBIA", nombre="Aeropuerto", municipio="Hondarribia", lon=-1.79, lat=43.35, en_base=0, fuente="SRC-B5M-FIREST", snap_m=60, nota="excluido")])
    w("candidatos.csv", [dict(origen_id=c, nombre=f"Sitio {c}", tipo_sitio="parking", municipio=MUNIS[k % 5][1], lon=-2.1 + 0.02 * k, lat=43.05 + 0.015 * k,
                              osm_id=str(100 + k), area_m2=1000, via_acceso="GI-0000", snap_m=5, t_desde_parque_ligero=10, parque_mas_cercano="GIP-ORIA",
                              motivo="sintético", comprobaciones_pendientes="heavy_vehicle_space; ownership_permit; truck_access; water; traffic_restrictions; ortho_location")
                         for k, c in enumerate(CANDS)])
    w("municipios.csv", [dict(muni_ine=i, municipio=m, area_km2=10, zona_meteo=z, edificios_total=100, residenciales=50,
                              edificios_analisis=sum(1 for e in edif if e["muni_ine"] == i), viviendas_analisis=0) for i, m, z in MUNIS])
    feats = [{"type": "Feature", "properties": {"muni_ine": i, "municipio": m},
              "geometry": {"type": "Polygon", "coordinates": [[[centers[i][0] - .04, centers[i][1] - .03], [centers[i][0] + .04, centers[i][1] - .03],
                                                               [centers[i][0] + .04, centers[i][1] + .03], [centers[i][0] - .04, centers[i][1] - .03]]]}} for i, m, z in MUNIS]
    (dest / "municipios.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    w("meteo_estaciones.csv", [dict(codigo=c, nombre=n, tipo="KM", lon=-2, lat=43.1, municipio=n, altitud_proxy_m=100, mide_viento=1, usada_en_zonas=1)
                               for c, n in (("C026", "Berastegi"), ("C029", "Zizurkil"), ("C058", "Bidania"))])
    w("meteo_perfil.csv", [dict(codigo=c, temporada="jul-ago", anios="2019,2020,2022,2023", dias_validos=248, dias_adversos=round(f * 248), frecuencia=f,
                                media_anual=f, sd_anual=0.036, peso_normalizado=round(f / mean_f, 4), regla="ADV-v1") for c, f in FREQ.items()])
    w("meteo_anual.csv", [dict(codigo=c, anio=y, dias_validos=62, dias_adversos=2, frecuencia=0.0323) for c in FREQ for y in range(2018, 2024)])
    w("meteo_mensual.csv", [dict(codigo=c, mes=m, dias_validos=180, dias_adversos=(20 if m == 9 else 8 if m in (7, 8) else 1), frecuencia=0.05) for c in FREQ for m in range(1, 13)])
    w("meteo_dias_adversos.csv", [dict(codigo="C026", fecha="2022-07-18", tmax=35.1, hrmin=25.0, lluvia_3d_previos_mm=0.0),
                                  dict(codigo="C029", fecha="2022-09-10", tmax=29.0, hrmin=33.0, lluvia_3d_previos_mm=0.0)])
    w("fuentes.csv", [dict(source_id="SRC-B5M-BU", conjunto="Edificios INSPIRE", organismo="DFG/B5M", url="", licencia="por confirmar",
                           fecha_descarga="2026-10-01", edicion_periodo="2026-08", archivo="", sha256="", estado="ok")])
    w("metodologia.csv", [dict(clave="umbral_min_defecto", valor="12", explicacion="demostración")])
    (dest / "auditoria.json").write_text(json.dumps({"sintetico": True}), encoding="utf-8")
    # escenarios por fuerza bruta pura
    esc = []
    for perfil, T in (("ligero", tl), ("camion", tc)):
        tt = [{o: (None if r[o] == "" else float(r[o])) for o in PARKS + CANDS} for r in T]
        combos = [c for k in range(7) for c in itertools.combinations(CANDS, k)]
        bts = {}
        for combo in combos:
            act = PARKS + list(combo)
            bts[combo] = [min([r[o] for o in act if r[o] is not None], default=None) for r in tt]
        for pesos in ("meteo", "uniforme"):
            wv = [e["peso_meteo"] if pesos == "meteo" else 1.0 for e in edif]
            for u in (10, 12, 15):
                mets = {}
                for combo, bt in bts.items():
                    cov = [b is not None and b <= u + 1e-9 for b in bt]
                    mets[combo] = dict(sel=";".join(combo), ncov=sum(cov), nunr=sum(b is None for b in bt),
                                       wc=math.fsum(x for x, c in zip(wv, cov) if c),
                                       worst=max([b for b in bt if b is not None], default=math.inf))
                for est in ("A", "B"):
                    def key(m):
                        return (-round(m["wc"], 9), -m["ncov"], round(m["worst"], 9)) if est == "A" else (m["nunr"], round(m["worst"], 9), -round(m["wc"], 9), -m["ncov"])
                    k0 = None
                    for k in range(7):
                        ms = [mets[c] for c in combos if len(c) == k]
                        best = min(ms, key=lambda m: (key(m), m["sel"]))
                        ties = sum(1 for m in ms if key(m) == key(best))
                        if k == 0:
                            k0 = best
                        esc.append(dict(estrategia=est, k=k, umbral_min=u, perfil=perfil, pesos=pesos, seleccion=best["sel"],
                                        edificios_cubiertos=best["ncov"], pct_cubiertos=round(100 * best["ncov"] / n, 2),
                                        cobertura_ponderada=round(best["wc"], 3), pct_ponderada=round(100 * best["wc"] / sum(wv), 2),
                                        peor_tiempo=round(best["worst"], 2), sin_ruta=best["nunr"], mejora_vs_k0=best["ncov"] - k0["ncov"], empates=ties))
    w("escenarios.csv", esc)
    return dest
