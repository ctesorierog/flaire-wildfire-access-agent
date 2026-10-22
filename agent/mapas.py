"""flAIre FINAL · informe HTML autocontenido «Plan preventivo flAIre · Tolosaldea <año>».

Un único HTML sin recursos externos: dos mapas SVG sincronizados (izquierda: solo parques, k=0; derecha:
parques + retenes propuestos) con las viviendas coloreadas por PRIORIDAD de planificación (Alta / Media / Baja)
y un halo para las que quedan fuera del umbral o sin ruta; gráficos de beneficio por retén (A y B: % de edificios
y edificios Alta dentro), tabla de indicadores (con la cobertura de las Alta), retenes propuestos, «cuándo activar»
(días de riesgo por mes), fuentes y límites. Proyección equirrectangular local en km, norte arriba.
Junto al HTML se escribe un manifiesto JSON con los parámetros y TODAS las cifras mostradas.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import flaire_data as fd

MAX_BYTES = 2_000_000
CARPETA_RESULTADOS = None  # los tests la fijan; en la plataforma: ./resultados
MESES = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]


def _carpeta_salida(carpeta=None) -> Path:
    c = Path(carpeta or CARPETA_RESULTADOS or (Path.cwd() / "resultados"))
    c.mkdir(parents=True, exist_ok=True)
    return c


def _ruta_publica(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


class _Proy:
    def __init__(self, lons, lats):
        self.lat0 = float(np.mean(lats))
        self.lon_min, self.lat_max = float(np.min(lons)), float(np.max(lats))
        self.kx = math.cos(math.radians(self.lat0)) * 111.32
        self.ky = 110.574

    def xy(self, lon, lat):
        return (np.asarray(lon, float) - self.lon_min) * self.kx, (self.lat_max - np.asarray(lat, float)) * self.ky


def _puntos_path(x, y) -> str:
    return "".join(f"M{a:.2f} {b:.2f}h0" for a, b in zip(x, y))


def _geo_paths(gj, pr: _Proy):
    out = []
    for f in gj.get("features", []):
        g = f.get("geometry") or {}
        polys = g.get("coordinates", [])
        if g.get("type") == "Polygon":
            polys = [polys]
        elif g.get("type") != "MultiPolygon":
            continue
        d = []
        for poly in polys:
            for ring in poly:
                a = np.asarray(ring, float)
                x, y = pr.xy(a[:, 0], a[:, 1])
                d.append("M" + "L".join(f"{p:.2f} {q:.2f}" for p, q in zip(x, y)) + "Z")
        out.append(("".join(d), (f.get("properties") or {}).get("municipio", "")))
    return out


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


def _fmt(v, nd=1, suf=""):
    if v is None:
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}".replace(",", ".") + suf
    return f"{float(v):,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suf


def _paso(rango):
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200):
        if rango / s <= 6:
            return s
    return 500


def _grafico(curvas: dict, campo: str, aria: str, suf: str, nd: int, k_sel, estrategia_sel) -> str:
    """Gráfico de líneas por nº de retenes (A y B) para el campo indicado."""
    W, H, ml, mr, mt, mb = 560, 230, 46, 96, 14, 36
    vals = [p[campo] for c in curvas.values() for p in c if p[campo] is not None]
    if not vals:
        return ""
    step = _paso(max(vals) - min(vals) + 2)
    lo = math.floor((min(vals) - step * 0.3) / step) * step
    hi = math.ceil((max(vals) + step * 0.2) / step) * step
    lo = max(0.0, lo)
    if suf == " %":
        hi = min(100.0, hi)
    if hi <= lo:
        hi = lo + step
    ks = sorted({p["k"] for c in curvas.values() for p in c})
    X = lambda k: ml + (W - ml - mr) * (k - ks[0]) / max(1, ks[-1] - ks[0])
    Y = lambda v: mt + (H - mt - mb) * (hi - v) / (hi - lo)
    s = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(aria)}">']
    v = lo
    for _ in range(50):
        if v > hi + 1e-9:
            break
        s.append(f'<line class="grid" x1="{ml}" x2="{W - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="tick" x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{_fmt(v, 0)}{suf}</text>')
        v += step
    for k in ks:
        s.append(f'<text class="tick" x="{X(k):.1f}" y="{H - mb + 16}" text-anchor="middle">{k}</text>')
    s.append(f'<text class="tick" x="{(ml + W - mr) / 2:.1f}" y="{H - 4}" text-anchor="middle">retenes adicionales (k)</text>')
    ends = []
    for est, var in (("A", "--serie-a"), ("B", "--serie-b")):
        c = curvas.get(est) or []
        if not c:
            continue
        d = "M" + "L".join(f"{X(p['k']):.1f} {Y(p[campo]):.1f}" for p in c)
        s.append(f'<path d="{d}" fill="none" stroke="var({var})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        for p in c:
            big = est == estrategia_sel and p["k"] == k_sel
            tip = (f"Estrategia {est} · k={p['k']} · {_fmt(p['pct_dentro'], 1)} % edificios dentro ({p['edificios_dentro']}) · "
                   f"Alta dentro {p['alta_dentro']} · peor {_fmt(p['peor_tiempo_min'], 1)} min · {';'.join(p['seleccion']) or 'solo parques'}")
            s.append(f'<g class="pt"><circle cx="{X(p["k"]):.1f}" cy="{Y(p[campo]):.1f}" r="{6 if big else 4}" fill="var({var})" '
                     f'stroke="var(--surface)" stroke-width="2"/><circle cx="{X(p["k"]):.1f}" cy="{Y(p[campo]):.1f}" r="11" '
                     f'fill="transparent"><title>{_esc(tip)}</title></circle></g>')
        ends.append([est, var, Y(c[-1][campo]), c[-1]])
    ends.sort(key=lambda e: e[2])
    if len(ends) == 2 and abs(ends[1][2] - ends[0][2]) < 14:
        ends[0][2] -= 7
        ends[1][2] += 7
    for est, var, yy, last in ends:
        s.append(f'<line x1="{W - mr + 6}" x2="{W - mr + 16}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var({var})" stroke-width="2"/>'
                 f'<text class="lbl" x="{W - mr + 20}" y="{yy + 4:.1f}">{est} · {_fmt(last[campo], nd)}{suf}</text>')
    s.append("</svg>")
    return "".join(s)


def _grafico_meses(meses: list) -> str:
    """Barras: días de riesgo medios por mes (media de las 3 zonas); ventanas feb-abr y sep-oct resaltadas."""
    if not meses:
        return ""
    W, H, ml, mr, mt, mb = 560, 170, 30, 10, 18, 26
    vmax = max((m["dias_riesgo"] or 0) for m in meses) or 1
    bw = (W - ml - mr) / 12
    s = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Días de riesgo medios por mes">']
    s.append(f'<line class="grid" x1="{ml}" x2="{W - mr}" y1="{H - mb}" y2="{H - mb}"/>')
    for i, m in enumerate(meses):
        v = m["dias_riesgo"] or 0
        h = (H - mt - mb) * v / vmax
        x = ml + i * bw + 3
        ventana = m["mes"] in (2, 3, 4, 9, 10)
        s.append(f'<rect x="{x:.1f}" y="{H - mb - h:.1f}" width="{bw - 6:.1f}" height="{h:.1f}" rx="2" fill="var({"--serie-a" if ventana else "--muni"})">'
                 f'<title>Mes {m["mes"]}: {_fmt(v, 1)} días de riesgo (calor seco {_fmt(m["calor_seco"], 1)} · viento sur {_fmt(m["viento_sur"], 1)})</title></rect>'
                 f'<text class="tick" x="{x + (bw - 6) / 2:.1f}" y="{H - mb - h - 4:.1f}" text-anchor="middle">{_fmt(v, 1)}</text>'
                 f'<text class="tick" x="{x + (bw - 6) / 2:.1f}" y="{H - 8}" text-anchor="middle">{MESES[m["mes"] - 1]}</text>')
    s.append("</svg>")
    return "".join(s)


def informe_html(seleccion=None, k=None, estrategia="A", umbral=fd.UMBRAL_DEF, perfil="ligero", pesos=fd.PESOS_DEF,
                 anio_plan=2027, carpeta_salida=None) -> dict:
    """Genera el informe HTML + manifiesto. Selección explícita, o la mejor de `estrategia` con `k` retenes
    (por defecto k=3 si no se da nada)."""
    u, p, w, e = fd.v_umbral(umbral), fd.v_perfil(perfil), fd.v_pesos(pesos), fd.v_estrategia(estrategia)
    try:
        anio = int(anio_plan)
    except (TypeError, ValueError):
        raise fd.ErrorConsulta("anio_plan debe ser un año.")
    if not 2024 <= anio <= 2040:
        raise fd.ErrorConsulta("anio_plan debe estar entre 2024 y 2040 (solo etiqueta).")
    if seleccion is None and k is None:
        k = 3
    sel, origen_sel = fd._resolver_seleccion(seleccion, k, e, u, p, w)
    D = fd.datos()
    ev0, ev = fd._evaluar([], u, p, w), fd._evaluar(sel, u, p, w)
    m0, m1 = fd._metricas(ev0), fd._metricas(ev)
    kmax = min(fd.K_MAX_ABS, len(D.cand_ids))
    opt = {est: fd.optimizar(kmax, est, u, p, w) for est in fd.ESTRATEGIAS}
    curvas = {est: [{"k": f["k"], "pct_dentro": f["pct_dentro"], "edificios_dentro": f["edificios_dentro"], "alta_dentro": f["alta_dentro"],
                     "pct_ponderada": f["pct_ponderada"], "peor_tiempo_min": f["peor_tiempo_min"], "sin_ruta": f["sin_ruta"],
                     "seleccion": f["seleccion"]} for f in o["por_k"]] for est, o in opt.items()}
    meteo = fd._meteo_resumen()

    # ---------- geometría
    edf = D.edif
    gj_path = D.carpeta / "municipios.geojson"
    gj = json.loads(gj_path.read_text(encoding="utf-8")) if gj_path.exists() else {"features": []}
    lons, lats = [edf.lon.to_numpy(float)], [edf.lat.to_numpy(float)]
    for f in gj.get("features", []):
        g = f.get("geometry") or {}
        arr = g.get("coordinates", [])
        flat = np.asarray([pt for poly in (arr if g.get("type") == "MultiPolygon" else [arr]) for ring in poly for pt in ring], float)
        if len(flat):
            lons.append(flat[:, 0])
            lats.append(flat[:, 1])
    pr = _Proy(np.concatenate(lons), np.concatenate(lats))
    bx, by = pr.xy(edf.lon.to_numpy(float), edf.lat.to_numpy(float))
    allx, ally = pr.xy(np.concatenate(lons), np.concatenate(lats))
    pad = 1.0
    x0, y0, x1, y1 = float(allx.min()) - pad, float(ally.min()) - pad, float(allx.max()) + pad, float(ally.max()) + pad
    vb = f"{x0:.2f} {y0:.2f} {x1 - x0:.2f} {y1 - y0:.2f}"
    munis_svg = "".join(f'<path class="muni" d="{d}"><title>{_esc(n)}</title></path>' for d, n in _geo_paths(gj, pr))
    pq = D.parques[D.parques.origen_id.isin(D.parques_base)]
    px, py = pr.xy(pq.lon.to_numpy(float), pq.lat.to_numpy(float))
    inside = (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
    cx, cy = pr.xy(D.cands.lon.to_numpy(float), D.cands.lat.to_numpy(float))
    fuera_vista = [r.nombre for r, ok in zip(pq.itertuples(), inside) if not ok]

    def capa_edificios(ev_):
        dentro = ev_["cubierto"]
        sinr = ~ev_["routable"]
        fuera = ev_["routable"] & ~dentro
        s = [f'<path class="h-out" d="{_puntos_path(bx[fuera], by[fuera])}"/>',
             f'<path class="h-nr" d="{_puntos_path(bx[sinr], by[sinr])}"/>']
        for c, cls in (("Baja", "p-baja"), ("Media", "p-media"), ("Alta", "p-alta")):
            m = D.clase == c
            s.append(f'<path class="{cls}" d="{_puntos_path(bx[m], by[m])}"/>')
        return "".join(s)

    def capa_origenes(con_sel):
        s = []
        for r, a, b, ok in zip(pq.itertuples(), px, py, inside):
            if ok:
                s.append(f'<g class="parque sc" data-x="{a:.2f}" data-y="{b:.2f}" transform="translate({a:.2f} {b:.2f})"><rect class="mk" x="-.45" y="-.45" width=".9" height=".9"/>'
                         f'<title>{_esc(fd.etiqueta_candidata(r.nombre, r.municipio))}</title></g>')
        for r, a, b in zip(D.cands.itertuples(), cx, cy):
            on = con_sel and r.origen_id in sel
            cls = "cand-sel" if on else "cand"
            s.append(f'<g class="{cls} sc" data-x="{a:.2f}" data-y="{b:.2f}" transform="translate({a:.2f} {b:.2f})"><path class="mk" d="M0 -.6L.55 .4L-.55 .4Z"/>'
                     + (f'<text class="clabel" x=".7" y=".3">{_esc(r.origen_id[-2:])}</text>' if on else "")
                     + f'<title>{_esc(r.origen_id)} · {_esc(fd.etiqueta_candidata(r.nombre, r.municipio))}{" · PROPUESTO" if on else " · candidata de estudio"}</title></g>')
        return "".join(s)

    def panel(titulo, ev_, con_sel, pid):
        return (f'<figure class="panel"><figcaption>{titulo}</figcaption><div class="mapbox">'
                f'<svg id="{pid}" class="map" viewBox="{vb}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{_esc(titulo)}">'
                f'<g class="munis">{munis_svg}</g><g>{capa_edificios(ev_)}</g><g class="origs">{capa_origenes(con_sel)}</g></svg>'
                f'<div class="north" aria-hidden="true"><svg viewBox="0 0 20 30" width="20" height="30"><path d="M10 2L16 22L10 18L4 22Z" fill="currentColor"/>'
                f'<text x="10" y="30" text-anchor="middle" font-size="9" fill="currentColor">N</text></svg></div>'
                f'<div class="scale" aria-hidden="true"><div class="bar"></div><span class="sl">—</span></div></div></figure>')

    # ---------- textos y tablas
    titulo = f"Plan preventivo flAIre · Tolosaldea {anio}"
    subt = "Dónde colocar retenes preventivos adicionales para las viviendas del borde forestal y cuándo activarlos"
    sel_txt = ", ".join(sel) if sel else "ninguno (solo parques)"
    mej_ed = m1["edificios_dentro"] - m0["edificios_dentro"]
    mej_alta = m1["alta_dentro"] - m0["alta_dentro"]
    mej_pt = round((m1["pct_dentro"] or 0) - (m0["pct_dentro"] or 0), 2)
    mej_pp = round((m1["pct_ponderada"] or 0) - (m0["pct_ponderada"] or 0), 2)
    etiqueta_pesos = {"prioridad": "prioridad sin acceso", "uniforme": "uniformes", "meteo": "meteo (legado jul-ago, solo sensibilidad)",
                      "firescope": "FireScope (solo sensibilidad)"}[w]
    filas = [
        (f"Edificios de prioridad Alta dentro (de {m0['alta_total']})", _fmt(m0["alta_dentro"]), _fmt(m1["alta_dentro"]), f"+{_fmt(mej_alta)}"),
        ("Edificios dentro del umbral", _fmt(m0["edificios_dentro"]), _fmt(m1["edificios_dentro"]), f"+{_fmt(mej_ed)}"),
        ("% de edificios dentro", _fmt(m0["pct_dentro"], 1, " %"), _fmt(m1["pct_dentro"], 1, " %"), f"+{_fmt(mej_pt, 1)} pp"),
        (f"Cobertura ponderada (pesos {etiqueta_pesos})", _fmt(m0["pct_ponderada"], 1, " %"), _fmt(m1["pct_ponderada"], 1, " %"), f"+{_fmt(mej_pp, 1)} pp"),
        ("Peor tiempo estimado (con ruta)", _fmt(m0["peor_tiempo_min"], 1, " min"), _fmt(m1["peor_tiempo_min"], 1, " min"),
         _fmt(round((m1["peor_tiempo_min"] or 0) - (m0["peor_tiempo_min"] or 0), 2), 1, " min")),
        ("Edificios sin ruta (no se eliminan) · de ellos Alta", f"{_fmt(m0['sin_ruta'])} · {_fmt(m0['alta_sin_ruta'])}",
         f"{_fmt(m1['sin_ruta'])} · {_fmt(m1['alta_sin_ruta'])}", _fmt(m1["sin_ruta"] - m0["sin_ruta"])),
    ]
    tabla = ("<table class='met'><thead><tr><th>Indicador</th><th>Sin refuerzo (k=0)</th>"
             f"<th>Propuesta (k={len(sel)})</th><th>Mejora vs k=0</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{_esc(a)}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>" for a, b, c, d in filas) + "</tbody></table>")
    cm = D.cands.set_index("origen_id")
    ret_rows = []
    for c in sel:
        primero = (ev["origen"] == c) & ev["cubierto"]
        pend = fd.traducir_comprobaciones(cm.comprobaciones_pendientes.get(c, "")) if "comprobaciones_pendientes" in cm.columns else ""
        ret_rows.append({"id": c, "nombre": str(cm.nombre.get(c)), "municipio": str(cm.municipio.get(c)), "tipo": str(cm.tipo_sitio.get(c)),
                         "edificios_dentro_atendidos_primero": int(primero.sum()), "alta_dentro_atendidos_primero": int((primero & D.alta).sum()),
                         "comprobaciones_pendientes": pend})
    tabla_ret = ("<table class='met'><thead><tr><th>Retén</th><th>Lugar de estudio</th><th>Municipio</th><th>Edificios dentro que atiende primero</th>"
                 "<th>de ellos Alta</th><th>Comprobaciones de campo pendientes</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{_esc(r['id'])}</td><td>{_esc(r['nombre'])} <span class='muted'>({_esc(r['tipo'])})</span></td><td>{_esc(r['municipio'])}</td>"
                           f"<td>{_fmt(r['edificios_dentro_atendidos_primero'])}</td><td>{_fmt(r['alta_dentro_atendidos_primero'])}</td>"
                           f"<td class='small'>{_esc(r['comprobaciones_pendientes'])}</td></tr>" for r in ret_rows)
                 + "</tbody></table>") if ret_rows else "<p>Sin retenes adicionales.</p>"
    tabla_curva = ("<details><summary>Tabla de los gráficos</summary><table class='met'><thead><tr><th>k</th>"
                   "<th>A: % dentro</th><th>A: Alta dentro</th><th>A: selección</th><th>B: % dentro</th><th>B: Alta dentro</th><th>B: peor min</th>"
                   "<th>B: selección</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{a['k']}</td><td>{_fmt(a['pct_dentro'], 1)}</td><td>{_fmt(a['alta_dentro'])}</td>"
                             f"<td class='small'>{_esc(';'.join(a['seleccion']) or '—')}</td><td>{_fmt(b['pct_dentro'], 1)}</td><td>{_fmt(b['alta_dentro'])}</td>"
                             f"<td>{_fmt(b['peor_tiempo_min'], 1)}</td><td class='small'>{_esc(';'.join(b['seleccion']) or '—')}</td></tr>"
                             for a, b in zip(curvas["A"], curvas["B"])) + "</tbody></table></details>")
    rep = meteo.get("reparto_pct") or {}
    cuando_txt = (f"Unos {_fmt(meteo.get('dias_riesgo_por_anio'), 1)} días de riesgo al año (calor seco o viento sur seco, media de 3 zonas, 2018–2023): "
                  f"febrero–abril {_fmt(rep.get('feb-abr'), 0)} %, septiembre–octubre {_fmt(rep.get('sep-oct'), 0)} %, julio–agosto solo {_fmt(rep.get('jul-ago'), 0)} %. "
                  "Las zonas no se distinguen: la meteorología dice CUÁNDO activar los retenes, no DÓNDE colocarlos.")
    grupos = {}
    if D.fuentes is not None:
        for f in D.fuentes.fillna("").to_dict("records"):
            est = str(f.get("estado", "")).lower()
            if est and ("superada" in est or "compar" in est):
                continue
            grupos.setdefault(f.get("organismo") or f.get("source_id"), []).append(f.get("source_id", ""))
    fuentes_txt = "; ".join(f"{_esc(o)} ({_esc(', '.join(sorted(set(v))))})" for o, v in grupos.items()) + ". Registro completo en fuentes.csv"
    limites = fd.LIMITES_BASE + [fd.LIMITE_PESOS[w], fd.LIMITE_PONDERADA, fd.AVISO_PRIORIDAD,
                                 "FireScope e incendios previos: solo referencia, no suman a la prioridad."]
    perfil_txt = "vehículo ligero" if p == "ligero" else "camión"
    estr_txt = {"A": "A · máxima cobertura ponderada", "B": "B · mejorar el peor acceso"}[e]
    params_txt = (f"Umbral {_fmt(u, 0)} min (demostración, no oficial) · perfil {perfil_txt} · pesos {etiqueta_pesos}"
                  f" · selección: {'mejor de la estrategia ' + estr_txt if origen_sel.startswith('mejor') else 'elegida por el usuario'}")
    if fuera_vista:
        params_txt += f" · parques fuera del encuadre (cuentan en el cálculo): {', '.join(fuera_vista)}"

    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clave = json.dumps({"sel": sel, "u": u, "p": p, "w": w, "anio": anio, "e": e, "n": D.n, "ver": fd.VERSION,
                        "t": float(np.nansum(D.tiempos[p]))}, sort_keys=True)
    nombre = f"informe-{hashlib.sha256(clave.encode()).hexdigest()[:10]}"

    css = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f4f3f0;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--line:#dddcd7;
--alta:#c8322b;--media:#e39a1f;--baja:#7d97b3;--out:#0b0b0b;--nr:#8a8984;--sel:#4a3aa7;--serie-a:#2a78d6;--serie-b:#eb6834;--muni:#b9b8b2}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--surface:#1a1a19;--page:#111110;--ink:#fff;--ink2:#c3c2b7;
--muted:#8f8e88;--line:#383835;--alta:#f0564a;--media:#e8a93c;--baja:#6d87a4;--out:#ffffff;--nr:#8f8e88;--sel:#9085e9;--serie-a:#3987e5;--serie-b:#d95926;--muni:#5a5955}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--page:#111110;--ink:#fff;--ink2:#c3c2b7;--muted:#8f8e88;--line:#383835;
--alta:#f0564a;--media:#e8a93c;--baja:#6d87a4;--out:#ffffff;--nr:#8f8e88;--sel:#9085e9;--serie-a:#3987e5;--serie-b:#d95926;--muni:#5a5955}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1240px;margin:0 auto;padding:20px 16px 40px}h1{font-size:24px;margin:0 0 2px}h2{font-size:16px;margin:24px 0 8px}
.sub{color:var(--ink2);margin:0 0 4px}.params{color:var(--ink2);font-size:13px;margin:4px 0 14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media (max-width:820px){.panels{grid-template-columns:1fr}}
.panel{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px;min-width:0}
figcaption{font-weight:600;margin:0 0 6px 4px}.mapbox{position:relative}
svg.map{width:100%;height:auto;aspect-ratio:1/1;max-height:560px;display:block;cursor:grab;touch-action:none;background:var(--surface)}
svg.map:active{cursor:grabbing}
.muni{fill:none;stroke:var(--muni);stroke-width:.8;vector-effect:non-scaling-stroke;stroke-linejoin:round}
.h-out,.h-nr,.p-alta,.p-media,.p-baja{fill:none;stroke-linecap:round;vector-effect:non-scaling-stroke}
.h-out{stroke:var(--out);stroke-width:6.5}.h-nr{stroke:var(--nr);stroke-width:8;opacity:.8}
.p-baja{stroke:var(--baja);stroke-width:3}.p-media{stroke:var(--media);stroke-width:3.6}.p-alta{stroke:var(--alta);stroke-width:4.4}
.origs .mk{vector-effect:non-scaling-stroke}.parque .mk{fill:var(--ink);stroke:var(--surface);stroke-width:2}
.cand .mk{fill:none;stroke:var(--muted);stroke-width:1.5}.cand-sel .mk{fill:var(--sel);stroke:var(--surface);stroke-width:2}
.clabel{font-size:1px;fill:var(--ink);font-weight:700;paint-order:stroke;stroke:var(--surface);stroke-width:.25}
.north{position:absolute;top:8px;right:8px;color:var(--ink2)}.scale{position:absolute;left:10px;bottom:8px;font-size:11px;color:var(--ink2)}
.scale .bar{height:5px;border:1px solid var(--ink2);border-top:none;width:80px}
.tools{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}.tools button{font:inherit;padding:4px 10px;border-radius:6px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2);margin:8px 2px}
.legend i{display:inline-block;vertical-align:middle;margin-right:5px}.dot{width:9px;height:9px;border-radius:50%}
.ring{width:11px;height:11px;border-radius:50%;border:2px solid var(--out);background:var(--baja)}
.grid2{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:12px}@media (max-width:820px){.grid2{grid-template-columns:1fr}}
.tw{overflow-x:auto}table.met{border-collapse:collapse;width:100%;font-size:13px}table.met th,table.met td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
table.met th{color:var(--ink2);font-weight:600}td:nth-child(n+2){font-variant-numeric:tabular-nums}.small{font-size:12px}.muted{color:var(--muted)}
svg.chart{width:100%;height:auto}.grid{stroke:var(--line);stroke-width:1}.tick{fill:var(--ink2);font-size:11px}.lbl{fill:var(--ink);font-size:12px}
.pt circle:last-child{cursor:pointer}footer{color:var(--ink2);font-size:12px;margin-top:20px}footer li{margin:2px 0}
details summary{cursor:pointer;color:var(--ink2);margin-top:8px}h3{font-size:14px;margin:14px 0 4px;color:var(--ink2)}
"""
    js = """
(function(){var ids=['m0','m1'],svgs=ids.map(function(i){return document.getElementById(i)});
var vb0=svgs[0].getAttribute('viewBox').split(' ').map(Number),vb=vb0.slice();
var marks=document.querySelectorAll('.sc');
function apply(){var s=vb.join(' '),z=vb[2]/vb0[2];svgs.forEach(function(g){g.setAttribute('viewBox',s)});
marks.forEach(function(m){m.setAttribute('transform','translate('+m.dataset.x+' '+m.dataset.y+') scale('+z+')')});
var px=svgs[0].getBoundingClientRect().width||1,kmpx=Math.max(vb[2],vb[3])/px,target=kmpx*90,nice=[.1,.2,.5,1,2,5,10,20],L=nice[0];
nice.forEach(function(n){if(n<=target)L=n});document.querySelectorAll('.scale').forEach(function(s){s.querySelector('.bar').style.width=(L/kmpx)+'px';
s.querySelector('.sl').textContent=(L<1?(L*1000)+' m':L+' km')})}
function zoom(f,cx,cy){var nw=Math.min(vb0[2]*1.5,Math.max(vb0[2]/40,vb[2]*f)),r=nw/vb[2];vb=[cx-(cx-vb[0])*r,cy-(cy-vb[1])*r,vb[2]*r,vb[3]*r];apply()}
function pt(svg,e){var r=svg.getBoundingClientRect(),s=Math.max(vb[2]/r.width,vb[3]/r.height),ox=(r.width*s-vb[2])/2,oy=(r.height*s-vb[3])/2;
return [vb[0]-ox+(e.clientX-r.left)*s,vb[1]-oy+(e.clientY-r.top)*s,s]}
svgs.forEach(function(svg){svg.addEventListener('wheel',function(e){e.preventDefault();var p=pt(svg,e);zoom(e.deltaY<0?0.8:1.25,p[0],p[1])},{passive:false});
var drag=null;svg.addEventListener('pointerdown',function(e){drag=[e.clientX,e.clientY,vb[0],vb[1],pt(svg,e)[2]];svg.setPointerCapture(e.pointerId)});
svg.addEventListener('pointermove',function(e){if(!drag)return;vb[0]=drag[2]-(e.clientX-drag[0])*drag[4];vb[1]=drag[3]-(e.clientY-drag[1])*drag[4];apply()});
svg.addEventListener('pointerup',function(){drag=null});svg.addEventListener('pointercancel',function(){drag=null})});
function c(){return [vb[0]+vb[2]/2,vb[1]+vb[3]/2]}
document.getElementById('zin').onclick=function(){var p=c();zoom(0.7,p[0],p[1])};document.getElementById('zout').onclick=function(){var p=c();zoom(1.4,p[0],p[1])};
document.getElementById('zrst').onclick=function(){vb=vb0.slice();apply()};window.addEventListener('resize',apply);apply()})();
"""
    sel_flag = e if origen_sel.startswith("mejor") else None
    cuerpo = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(titulo)}</title><style>{css}</style></head><body><main>
<h1>{_esc(titulo)}</h1><p class="sub">{_esc(subt)} · 28 municipios · {_fmt(D.n)} edificios residenciales a ≤100 m de bosque o matorral ({_fmt(m0['alta_total'])} de prioridad Alta)</p>
<p class="params">{_esc(params_txt)}</p>
<div class="card"><strong>Dónde:</strong> {_esc(sel_txt)}. Con {len(sel)} retén(es) adicional(es) quedan dentro de {_fmt(u, 0)} min
{_fmt(m1['alta_dentro'])} de {_fmt(m1['alta_total'])} edificios de prioridad Alta (frente a {_fmt(m0['alta_dentro'])} solo con parques) y
{_fmt(m1['edificios_dentro'])} de {_fmt(D.n)} edificios ({_fmt(m1['pct_dentro'], 1, ' %')}; +{_fmt(mej_ed)}). {_fmt(m1['alta_sin_ruta'])} Alta sin ruta
no mejoran con ningún retén (necesitan otra medida: acceso, autoprotección).<br><strong>Cuándo:</strong> {_esc(cuando_txt)}<br>
<span class="muted small">Prioridad de planificación, no probabilidad de incendio. Tiempos = estimaciones de desplazamiento, no tiempos de respuesta. Candidatas = lugares de estudio, no autorizados.</span></div>
<h2>Mapas sincronizados</h2>
<div class="tools"><button id="zin" type="button" aria-label="Acercar">+</button><button id="zout" type="button" aria-label="Alejar">−</button>
<button id="zrst" type="button">Encuadre inicial</button><span class="muted small">Rueda o arrastre en cualquiera de los dos mapas: ambos se mueven juntos (misma escala).</span></div>
<div class="panels">{panel("Sin refuerzo · solo parques (k=0)", ev0, False, "m0")}{panel(f"Propuesta · parques + {len(sel)} retén(es)", ev, True, "m1")}</div>
<div class="legend"><span><i class="dot" style="background:var(--alta)"></i>Prioridad Alta</span>
<span><i class="dot" style="background:var(--media)"></i>Media</span><span><i class="dot" style="background:var(--baja)"></i>Baja</span>
<span><i class="ring"></i>Con halo oscuro: fuera de {_fmt(u, 0)} min</span>
<span><i class="ring" style="border-color:var(--nr)"></i>Halo gris: sin ruta (a &gt;150 m de la red)</span>
<span><i style="width:9px;height:9px;background:var(--ink)"></i>Parque de bomberos</span>
<span><svg width="12" height="11" style="vertical-align:middle;margin-right:5px"><path d="M6 1L11 10H1Z" fill="none" stroke="var(--muted)" stroke-width="1.5"/></svg>Candidata de estudio</span>
<span><svg width="12" height="11" style="vertical-align:middle;margin-right:5px"><path d="M6 1L11 10H1Z" fill="var(--sel)"/></svg>Retén propuesto</span>
<span>Contornos: municipios (geoEuskadi)</span></div>
<div class="grid2"><section class="card"><h2 style="margin-top:0">Indicadores</h2><div class="tw">{tabla}</div>
<h3>Cuándo activar · días de riesgo medios por mes</h3>{_grafico_meses(meteo.get('por_mes_media_zonas') or [])}
<p class="small muted">Barras azules: ventanas febrero–abril y septiembre–octubre. Reglas exploratorias (no FWI); 3 estaciones de valle.</p></section>
<section class="card"><h2 style="margin-top:0">Beneficio por retén (A y B, {_fmt(u, 0)} min)</h2>
<div class="legend"><span><i style="width:14px;height:2px;background:var(--serie-a)"></i>A · máx. cobertura ponderada</span>
<span><i style="width:14px;height:2px;background:var(--serie-b)"></i>B · mejorar el peor acceso</span></div>
<h3>Edificios de prioridad Alta dentro (de {_fmt(m0['alta_total'])})</h3>{_grafico(curvas, "alta_dentro", "Edificios Alta dentro por número de retenes", "", 0, len(sel), sel_flag)}
<h3>% de edificios dentro</h3>{_grafico(curvas, "pct_dentro", "Porcentaje de edificios dentro por número de retenes", " %", 1, len(sel), sel_flag)}{tabla_curva}</section></div>
<h2>Retenes propuestos (lugares de estudio)</h2><div class="card tw">{tabla_ret}</div>
<footer><p><strong>Fuentes:</strong> {fuentes_txt}.</p><p><strong>Límites:</strong></p><ul>{''.join(f'<li>{_esc(x)}</li>' for x in limites)}</ul>
<p>Generado {gen} por flAIre (mapas.py, {_esc(fd.VERSION)}) · cifras verificables en <code>{nombre}.manifest.json</code> · datos: {_esc(D.carpeta.name)}/.</p></footer>
</main><script>{js}</script></body></html>"""
    out_dir = _carpeta_salida(carpeta_salida)
    ruta = out_dir / f"{nombre}.html"
    ruta.write_text(cuerpo, encoding="utf-8")
    nbytes = ruta.stat().st_size
    if nbytes > MAX_BYTES:
        raise RuntimeError(f"El informe ocupa {nbytes} bytes (> 2 MB)")
    manifiesto = {
        "titulo": titulo, "subtitulo": subt, "generado_utc": gen, "html": ruta.name, "bytes_html": nbytes,
        "sha256_html": hashlib.sha256(cuerpo.encode("utf-8")).hexdigest(),
        "parametros": {"seleccion": sel, "origen_seleccion": origen_sel, "estrategia": e, "umbral_min": u, "perfil": p, "pesos": w,
                       "anio_plan": anio, "parques_en_base": D.parques_base},
        "cifras": {"k0": m0, "propuesta": m1,
                   "mejora_vs_k0": {"edificios": mej_ed, "alta": mej_alta, "puntos_pct": mej_pt, "puntos_pct_ponderada": mej_pp},
                   "curvas": curvas, "retenes": ret_rows,
                   "cuando": {"dias_riesgo_por_anio": meteo.get("dias_riesgo_por_anio"), "reparto_pct": rep,
                              "por_mes": meteo.get("por_mes_media_zonas"), "zonas_distinguibles": meteo.get("zonas_distinguibles")},
                   "mapa": {"edificios_dentro_k0": int(ev0["cubierto"].sum()), "edificios_fuera_k0": int((ev0["routable"] & ~ev0["cubierto"]).sum()),
                            "edificios_dentro_propuesta": int(ev["cubierto"].sum()), "edificios_fuera_propuesta": int((ev["routable"] & ~ev["cubierto"]).sum()),
                            "sin_ruta": int((~ev["routable"]).sum()), "por_prioridad": {c: int((D.clase == c).sum()) for c in fd.CLASES},
                            "parques_fuera_de_encuadre": fuera_vista}},
        "comprobacion_escenarios_csv": [], "nota_escenarios": fd._nota_escenarios(e, u, p, w),
        "metodo": fd.METODO_COBERTURA, "limites": limites,
    }
    for est in fd.ESTRATEGIAS:
        for c in curvas[est]:
            g = fd._escenario_guardado(est, c["k"], u, p, w)
            if g is not None:
                manifiesto["comprobacion_escenarios_csv"].append(
                    {"estrategia": est, "k": c["k"], "coincide": str(g["seleccion"]) == ";".join(c["seleccion"]) and int(g["edificios_cubiertos"]) == c["edificios_dentro"]})
    ruta_m = out_dir / f"{nombre}.manifest.json"
    ruta_m.write_text(json.dumps(manifiesto, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    claves = ("edificios_dentro", "pct_dentro", "pct_ponderada", "alta_dentro", "alta_sin_ruta", "peor_tiempo_min", "sin_ruta")
    return {"parametros": manifiesto["parametros"], "html": _ruta_publica(ruta), "manifiesto": _ruta_publica(ruta_m), "bytes": nbytes,
            "cifras_principales": {"k0": {k2: m0[k2] for k2 in claves}, "propuesta": {k2: m1[k2] for k2 in claves},
                                   "mejora_vs_k0": manifiesto["cifras"]["mejora_vs_k0"],
                                   "cuando": {"dias_riesgo_por_anio": meteo.get("dias_riesgo_por_anio"), "reparto_pct": rep}},
            "metodo": "Informe HTML autocontenido (SVG, sin recursos externos) + manifiesto JSON con todas las cifras mostradas.",
            "limites": limites}
