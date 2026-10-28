"""Print every number docs/QA.md rests on (PLAN 10.8 Q&A drill).

Read-only: reads app/data/*.json, the FINAL agent's building table, sources.csv and
the candidate records. Run from the repo root:
    conda run -n flaire python 05_codigo/pipeline/qa_evidence.py
Each block is labelled E1..E9 so QA.md can cite it.
"""
import csv
import json
import math
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def e1_stability():
    print("E1 stability.json (exhaustive, 120 combinations of 3, every building weight 1)")
    for r in load("stability.json")["rows"]:
        short = lambda s: "+".join(c[-2:] for c in s)
        print(f"  {r['profile']:5} {r['threshold_min']:>2} min  today {r['today_covered']} ({r['today_pct']} %)"
              f"  pick {short(r['pick'])} {r['covered']} ({r['pct_covered']} %)"
              f"  runner-up {short(r['runner_up'])} {r['runner_up_covered']}"
              f"  ties {r['runner_up_ties']}  margin {r['margin']}")


def e2_baseline_split():
    g = load("gipuzkoa_baseline.json")
    print("E2 gipuzkoa_baseline.json: province totals and the Tolosaldea row")
    t = g["totals"]
    print(f"  province: {t['within_12_min']} of {t['exposed_buildings']} ({t['pct_within_12_min']} %), no route {t['no_route']}")
    for c in g["by_comarca"]:
        print(f"  {c['comarca']:13} {c['municipalities']:>2} munis  {c['within_12_min']}/{c['exposed_buildings']} ({c['pct_within_12_min']} %)")
    M = g["municipalities"]
    com = [m for m in M if m["comarca"] == "TOLOSALDEA"]
    study = [m for m in M if m["in_tolosaldea"]]
    tot = lambda L: (sum(m["exposed_buildings"] for m in L), sum(m["within_12_min"] for m in L))
    print(f"  comarca row: {len(com)} munis {tot(com)}; study area: {len(study)} munis {tot(study)}")
    for m in com:
        if not m["in_tolosaldea"]:
            print(f"  in comarca, not in study: {m['name']} {m['exposed_buildings']} buildings, {m['within_12_min']} within 12")
    print(f"  limits: {g['meta']['limits']}")


def e3_buildings():
    e = pd.read_csv(ROOT / "agent" / "data" / "edificios_prioridad.csv")
    no_route = e.sin_ruta.astype(str).str.lower().str.startswith("s")
    alta = e.prioridad == "Alta"
    print("E3 edificios_prioridad.csv (FINAL agent data)")
    print(f"  buildings {len(e)}, municipalities {e.municipio.nunique()}, dwellings {int(e.viviendas.sum())}")
    print(f"  priority {e.prioridad.value_counts().to_dict()}")
    print(f"  no route {int(no_route.sum())}, of them Alta {int((no_route & alta).sum())}, Alta with a route {int((~no_route & alta).sum())}")
    print(f"  Alta within 12 min today (light) {int((alta & (e.t_base_ligero_min <= 12)).sum())}; worst time {e.t_base_ligero_min.max()} min")
    print(f"  puntos_meteo: min {e.puntos_meteo.min()} max {e.puntos_meteo.max()}")
    w = e.peso_meteo_sensibilidad
    print(f"  peso_meteo_sensibilidad: min {w.min():.2f} max {w.max():.2f}, distinct {w.round(4).nunique()}")


def e4_weekly():
    w = load("weekly_calendar.json")
    print("E4 weekly_calendar.json")
    print(f"  rule {w['meta']['rule']}, years {w['meta']['years']}, stations {list(w['meta']['stations'].values())}")
    print(f"  risk days/year {w['summary']['risk_days_per_year']}, shares {w['summary']['season_share']}")
    print(f"  limits: {w['meta']['limits']}")


def e5_sources():
    rows = list(csv.DictReader((ROOT / "reports" / "sources.csv").open(encoding="utf-8")))
    text = " ".join(" ".join(r.values()) for r in rows).lower()
    print("E5 sources.csv")
    print(f"  rows {len(rows)}; mentions firescope: {'firescope' in text}; mentions speis/memoria: {'speis' in text or 'memoria' in text}")


def e6_optimizer():
    print("E6 optimizer.py")
    print(f"  combinations of 10 sites for k = 0..6: {sum(math.comb(10, k) for k in range(7))}; for k = 3: {math.comb(10, 3)}")
    for line in (ROOT / "pipeline" / "optimizer.py").read_text(encoding="utf-8").splitlines()[:20]:
        if "Strategy A" in line:
            print(f"  {line.strip()}")


def e7_candidates():
    text = (ROOT / "reports" / "fichas_candidatas_v03.md").read_text(encoding="utf-8")
    print("E7 fichas_candidatas_v03.md, selection rule")
    for line in text.splitlines():
        if line.startswith("## Regla") or "DBSCAN" in line:
            print(f"  {line.strip()[:420]}")


def e8_linker():
    text = (ROOT / "reports" / "linker_validation.md").read_text(encoding="utf-8")
    print("E8 linker_validation.md")
    for pat in (r"Hand checks: \*\*12/12 match\*\*", r"different selection in 9 of 42.*?coverage", r"Weights are nearly flat[^)]*\)"):
        m = re.search(pat, text)
        print(f"  {m.group(0) if m else 'NOT FOUND: ' + pat}")


def e9_repo():
    print("E9 repo facts")
    print(f"  tests_final/ exists: {any(ROOT.rglob('tests_final'))}")
    print(f"  audit_seat2.py exists: {any(p for p in ROOT.rglob('audit_seat2.py') if '_papelera' not in p.parts)}")


if __name__ == "__main__":
    for f in (e1_stability, e2_baseline_split, e3_buildings, e4_weekly, e5_sources, e6_optimizer, e7_candidates, e8_linker, e9_repo):
        f()
        print()
