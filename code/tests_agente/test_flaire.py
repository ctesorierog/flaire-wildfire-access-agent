"""Pruebas de flaire_data, mapas, tools y main (locales; no se suben a la plataforma)."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import flaire_data as fd

AGENT = Path(__file__).resolve().parents[1]


def D():
    return fd.datos()


def _param_sets():
    e = D().esc
    return sorted({(r.estrategia, float(r.umbral_min), r.perfil, r.pesos) for r in e.itertuples()})


# ----------------------------------------------------------------------------- validación de entradas
@pytest.mark.parametrize("call", [
    lambda: fd.optimizar(k_max=7), lambda: fd.optimizar(k_max=-1), lambda: fd.optimizar(k_max=2.5),
    lambda: fd.cobertura(umbral=0), lambda: fd.cobertura(umbral=61), lambda: fd.cobertura(umbral="doce"),
    lambda: fd.cobertura(perfil="moto"), lambda: fd.optimizar(estrategia="C"), lambda: fd.cobertura(pesos="raros"),
    lambda: fd.cobertura(seleccion="CAND-11"), lambda: fd.cobertura(seleccion="CAND-01;CAND-02;CAND-03;CAND-04;CAND-05;CAND-06;CAND-07"),
    lambda: fd.cobertura(municipio="Donostia"), lambda: fd.edificio("ES.GFA.BU.0"), lambda: fd.contexto(temporada="septiembre"),
    lambda: fd.contexto(anio_plan=1999), lambda: fd.minimo_k(150), lambda: fd.minimo_k(95, metrica="viviendas"),
    lambda: fd.edificios_ganados(0), lambda: fd.perfil_meteo(zona="C999"), lambda: fd.comparar(),
])
def test_entradas_invalidas(call):
    with pytest.raises(fd.ErrorConsulta):
        call()


def test_municipio_desconocido_lista_validos():
    with pytest.raises(fd.ErrorConsulta) as ei:
        fd.v_municipio("Donostia")
    msg = str(ei.value)
    for m in D().muni_nombres:
        assert m in msg


def test_municipio_acentos_mayusculas():
    nombres = D().muni_nombres
    m = nombres[0]
    assert fd.v_municipio(m.upper()) == m
    assert fd.v_municipio(" " + m.lower() + " ") == m
    if "Bidania-Goiatz" in nombres:
        assert fd.v_municipio("bidania goiatz") == "Bidania-Goiatz"
        assert fd.v_municipio("BIDANIA") == "Bidania-Goiatz"
    if "Berastegi" in nombres:
        assert fd.v_municipio("Berastegui") == "Berastegi"


def test_normaliza_candidatas_y_perfiles():
    assert fd.v_seleccion("cand-2, CAND-01") == ["CAND-01", "CAND-02"]
    assert fd.v_seleccion("") == [] and fd.v_seleccion(None) == []
    assert fd.v_perfil("Camión") == "camion" and fd.v_perfil("truck") == "camion"
    assert fd.v_estrategia("b") == "B"


def test_k_no_supera_candidatas():
    with pytest.raises(fd.ErrorConsulta) as ei:
        fd.optimizar(8)
    assert "candidatas" in str(ei.value)


# ----------------------------------------------------------------------------- reglas de conteo
def test_edificio_cuenta_una_vez():
    ed = pd.read_csv(D().carpeta / "edificios.csv", dtype={"building_id": str})
    assert ed.building_id.is_unique
    r = fd.cobertura(k=2)
    assert r["resultado"]["edificios_total"] == len(ed)
    pm = r["por_municipio"]
    assert sum(x["edificios"] for x in pm) == len(ed)
    assert sum(x["dentro"] for x in pm) == r["resultado"]["edificios_dentro"]
    assert sum(x["sin_ruta"] for x in pm) == r["resultado"]["sin_ruta"]
    orig = r["edificios_por_origen_mas_rapido"]
    assert sum(orig.values()) == len(ed) - r["resultado"]["sin_ruta"]


def test_sin_ruta_preservado_y_constante():
    ed = pd.read_csv(D().carpeta / "edificios.csv", dtype={"building_id": str})
    n_sr = int((ed.estado_ruta != "calculado").sum())
    for p in fd.PERFILES:
        o = fd.optimizar(6, "B", 12, p)
        assert all(f["sin_ruta"] == n_sr for f in o["por_k"])
        assert all(f["edificios_dentro"] <= len(ed) - n_sr for f in o["por_k"])
    # los sin ruta tienen tiempos vacíos en los dos ficheros
    for p in fd.PERFILES:
        t = pd.read_csv(D().carpeta / f"tiempos_{p}.csv", dtype={"building_id": str}).set_index("building_id")
        sr = ed[ed.estado_ruta != "calculado"].building_id
        assert t.loc[sr].isna().all().all()


def test_porcentaje_sobre_todos():
    r = fd.cobertura()
    m = r["resultado"]
    assert abs(m["pct_dentro"] - 100 * m["edificios_dentro"] / m["edificios_total"]) < 0.01


# ----------------------------------------------------------------------------- optimizador
def test_monotonia_todos_los_escenarios():
    for est, u, p, w in _param_sets():
        o = fd.optimizar(6, est, u, p, w)
        assert o["objetivo_monotono"], (est, u, p, w)
        if est == "A":
            assert o["edificios_monotono"], (est, u, p, w)
        assert o["combinaciones_evaluadas"] == sum(__import__("math").comb(len(D().cand_ids), k) for k in range(7))


def test_igual_a_escenarios_csv():
    e = D().esc
    malos = []
    for (est, u, p, w), g in e.groupby(["estrategia", "umbral_min", "perfil", "pesos"]):
        o = fd.optimizar(int(g.k.max()), est, float(u), p, w)
        for f in o["por_k"]:
            row = g[g.k == f["k"]].iloc[0]
            ok = (str(row.seleccion if isinstance(row.seleccion, str) else "") == ";".join(f["seleccion"])
                  and int(row.edificios_cubiertos) == f["edificios_dentro"]
                  and int(row.sin_ruta) == f["sin_ruta"]
                  and abs(float(row.peor_tiempo) - f["peor_tiempo_min"]) <= 0.006
                  and abs(float(row.cobertura_ponderada) - f["cobertura_ponderada"]) <= 0.006
                  and abs(float(row.pct_cubiertos) - f["pct_dentro"]) <= 0.006)
            if "empates" in row and not pd.isna(row.empates):
                ok = ok and int(row.empates) == f["empates"]
            if "mejora_vs_k0" in row and not pd.isna(row.mejora_vs_k0) and float(row.mejora_vs_k0) == int(float(row.mejora_vs_k0)):
                ok = ok and int(row.mejora_vs_k0) == f["mejora_vs_k0_edificios"]
            if not ok:
                malos.append((est, u, p, w, f["k"], row.seleccion, f["seleccion"], int(row.edificios_cubiertos), f["edificios_dentro"]))
    assert not malos, malos[:10]


def test_rendimiento():
    fd._optimizar_cache.cache_clear()
    o = fd.optimizar(6, "A", 13.5, "ligero", "meteo")
    assert o["segundos"] < 5


def test_coincide_con_optimizador_del_manager():
    import sys
    p = AGENT.parent / "code" / "manager"
    if not (p / "optimizer.py").exists():
        pytest.skip("optimizer.py del manager no disponible")
    sys.path.insert(0, str(p))
    import optimizer as opt
    d = D()
    for perfil in fd.PERFILES:
        T = d.tiempos[perfil].T
        pr = opt.Problem(T, d.parques_base + d.cand_ids, d.cand_ids, list(d.ids), d.peso["meteo"])
        for est in fd.ESTRATEGIAS:
            res = opt.optimize(pr, 11.0, 6, est, keep_all=False)
            mine = fd.optimizar(6, est, 11.0, perfil, "meteo")
            for a, b in zip(res["per_k"], mine["por_k"]):
                assert a["selection"].replace("|", ";") == ";".join(b["seleccion"])
                assert a["n_covered"] == b["edificios_dentro"] and a["ties"] == b["empates"]


def test_anio_plan_no_cambia_resultados():
    a, b = fd.contexto(2027), fd.contexto(2031)
    for k in ("periodo_historico", "ambito", "origenes", "parametros_defecto"):
        assert a[k] == b[k]
    assert "2031" in b["titulo_plan"]


# ----------------------------------------------------------------------------- consultas
def test_edificios_ganados_consistente():
    for est in fd.ESTRATEGIAS:
        o = fd.optimizar(6, est)
        for k in range(1, 7):
            g = fd.edificios_ganados(k, est)
            f = o["por_k"][k]
            assert g["n_ganados"] - g["n_perdidos"] == f["mejora_vs_k_anterior_edificios"]
            assert g["anidada"] == f["reutiliza_k_anterior"]
            assert g["n_siguen_fuera_con_ruta"] + g["n_sin_ruta"] + f["edificios_dentro"] == D().n


def test_minimo_k():
    o = fd.optimizar(6, "A")
    objetivo = o["por_k"][2]["pct_dentro"]
    r = fd.minimo_k(objetivo)
    assert r["alcanzado"] and r["k_minimo"] <= 2
    assert "dotación operativa" in r["aviso"]
    if o["sin_ruta"]["n"] > 0:
        assert fd.minimo_k(100)["alcanzado"] is False


def test_comparar_consistente():
    c = fd.comparar(k=3)
    da = c["metricas_a"]["edificios_dentro"] - c["metricas_b"]["edificios_dentro"]
    assert c["edificios_dentro_solo_con_a"] - c["edificios_dentro_solo_con_b"] == da
    assert c["parametros"]["seleccion_a"] == fd.optimizar(3, "A")["por_k"][3]["seleccion"]


def test_fuera_umbral_cuenta():
    r = fd.fuera_umbral(k=2)
    cov = fd.cobertura(k=2)["resultado"]
    assert r["n_fuera_con_ruta"] + r["n_sin_ruta"] + cov["edificios_dentro"] == D().n
    tiempos = [x["min"] for x in r["edificios_fuera"]]
    assert tiempos == sorted(tiempos, reverse=True) and all(t > 12 for t in tiempos)


def test_ficha_edificio():
    bid = D().ids[0]
    r = fd.edificio(bid.split(".")[-1], k=1)
    assert r["parametros"]["building_id"] == bid
    assert len(r["tiempos_por_origen"]) == len(D().parques_base) + len(D().cand_ids)


def test_perfil_meteo_mensual_y_planitud():
    r = fd.perfil_meteo()
    assert {z["codigo"] for z in r["zonas"]} == set(D().zonas)
    for z in r["zonas"]:
        assert len(z["por_mes_todos_los_anios"]) == 12
        assert "mes_pico" in z
    assert isinstance(r["intervalos_1sd_solapan"], bool)
    m = D().muni_nombres[0]
    assert fd.perfil_meteo(municipio=m)["parametros"]["municipio"] == m


def test_comprobar_independiente():
    for est in fd.ESTRATEGIAS:
        r = fd.comprobar(est, 3)
        assert r["todo_coincide"], [c for c in r["comparaciones"] if not c["coincide"]]
    r = fd.comprobar(seleccion="CAND-05", perfil="camion", umbral=15)
    assert r["todo_coincide"]


def test_limitaciones_y_fuentes():
    lim = fd.limitaciones()["limitaciones"]
    assert any(l["id"] == "L2" and l["n"] == fd.cobertura()["resultado"]["sin_ruta"] for l in lim)
    assert fd.fuentes()["n_fuentes"] >= 1


# ----------------------------------------------------------------------------- informe HTML
def test_informe_html_y_manifiesto():
    import mapas
    r = mapas.informe_html(k=3, estrategia="A")
    html_p = Path(r["html"]) if Path(r["html"]).is_absolute() else Path.cwd() / r["html"]
    man_p = Path(r["manifiesto"]) if Path(r["manifiesto"]).is_absolute() else Path.cwd() / r["manifiesto"]
    txt = html_p.read_text(encoding="utf-8")
    assert html_p.stat().st_size < 2_000_000
    assert not re.search(r'(src|href)\s*=\s*"https?://', txt), "recursos externos en el HTML"
    assert "<script src" not in txt
    assert "Plan preventivo · Julio–agosto 2027" in txt and "temporadas históricas" in txt
    assert txt.count('<svg id="m') == 2
    man = json.loads(man_p.read_text(encoding="utf-8"))
    cov = fd.cobertura(k=3, estrategia="A")
    cov0 = fd.cobertura()
    for c in ("edificios_dentro", "pct_dentro", "pct_ponderada", "peor_tiempo_min", "sin_ruta"):
        assert man["cifras"]["propuesta"][c] == cov["resultado"][c]
        assert man["cifras"]["k0"][c] == cov0["resultado"][c]
    for est in fd.ESTRATEGIAS:
        o = fd.optimizar(6, est)
        assert [c["edificios_dentro"] for c in man["cifras"]["curvas"][est]] == [f["edificios_dentro"] for f in o["por_k"]]
    assert all(x["coincide"] for x in man["comprobacion_escenarios_csv"])
    # cifras del texto: los números de la tarjeta están en el manifiesto
    n_in = f'{man["cifras"]["propuesta"]["edificios_dentro"]:,}'.replace(",", ".")
    assert n_in in txt
    chk = fd.comprobar("A", 3, manifiesto=str(man_p))
    assert chk["todo_coincide"]
    # mismo informe con otro año: mismas cifras
    r2 = mapas.informe_html(k=3, estrategia="A", anio_plan=2030)
    assert r2["cifras_principales"] == r["cifras_principales"]


# ----------------------------------------------------------------------------- herramientas
def test_herramientas_json_y_errores():
    import tools
    assert len(tools.TOOLS) <= 10
    for t in tools.TOOLS:
        assert t.__doc__ and len(t.__doc__) > 80, t.__name__
    casos = [
        (tools.consultar_contexto, {}), (tools.consultar_contexto, {"apartado": "fuentes"}),
        (tools.consultar_contexto, {"apartado": "limitaciones"}), (tools.perfil_meteorologico, {}),
        (tools.calcular_cobertura, {"seleccion": "CAND-02"}), (tools.calcular_cobertura, {"k": 2, "estrategia": "B"}),
        (tools.optimizar_despliegue, {"k_max": 3}), (tools.minimo_retenes, {"objetivo_pct": 90}),
        (tools.comparar_selecciones, {"k": 2}), (tools.comparar_selecciones, {"seleccion_a": "CAND-01", "seleccion_b": "CAND-02"}),
        (tools.edificios_ganados, {"k": 3}), (tools.consultar_edificios, {}), (tools.consultar_edificios, {"building_id": str(D().ids[0])}),
        (tools.comprobar_cifra, {"estrategia": "A", "k": 2}),
    ]
    for t, kw in casos:
        out = json.loads(t(**kw))
        assert "error" not in out, (t.__name__, out)
        assert "metodo" in out and "limites" in out
    for t, kw in [(tools.optimizar_despliegue, {"k_max": 9}), (tools.calcular_cobertura, {"umbral": 0}),
                  (tools.calcular_cobertura, {"municipio": "Bilbao"}), (tools.consultar_contexto, {"temporada": "septiembre"}),
                  (tools.consultar_contexto, {"apartado": "otra"}), (tools.edificios_ganados, {"k": 0})]:
        out = json.loads(t(**kw))
        assert out["error"]["codigo"] == "PARAMETRO_INVALIDO" and out["error"]["mensaje"]
    art = tools.generar_informe(k=2)
    assert isinstance(art, dict) and art["artifacts"][0].endswith(".html")
    assert json.loads(art["message"])["cifras_principales"]["propuesta"]["edificios_dentro"] == fd.cobertura(k=2)["resultado"]["edificios_dentro"]
    err = tools.generar_informe(k=9)
    assert "PARAMETRO_INVALIDO" in err


# ----------------------------------------------------------------------------- paquete
def test_tamanos_y_numero_de_ficheros():
    excl = {"tests", "__pycache__", "resultados", ".pytest_cache"}
    files = [p for p in AGENT.rglob("*") if p.is_file() and not (set(p.relative_to(AGENT).parts) & excl)]
    assert len(files) < 60, len(files)
    grandes = [(str(p), p.stat().st_size) for p in files if p.stat().st_size > 3_500_000]
    assert not grandes, grandes


def test_main_importa_y_construye():
    lc = pytest.importorskip("langchain")
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    import main

    class Falso(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kw):
            return self

    respuestas = [AIMessage(content="", tool_calls=[{"name": "optimizar_despliegue", "args": {"k_max": 2, "estrategia": "A"}, "id": "c1"}]),
                  AIMessage(content="Hallazgo: ok")]
    from langchain_core.tools import tool as lc_tool
    import tools as T
    # en la plataforma studio.tool ya convierte; aquí convertimos con langchain para probar el cableado
    main.TOOLS = [lc_tool(t) for t in T.TOOLS]
    agente = main.build_agent(Falso(responses=respuestas))
    out = agente.invoke({"messages": [{"role": "user", "content": "¿Dónde pongo 2 retenes?"}]})
    msgs = out["messages"]
    tool_msgs = [m for m in msgs if m.type == "tool"]
    assert tool_msgs and json.loads(tool_msgs[0].content)["por_k"][2]["k"] == 2
    assert msgs[-1].content == "Hallazgo: ok"
    main.TOOLS = list(T.TOOLS)
    assert main.AGENT_NAME == "flAIre · retenes preventivos Tolosaldea" and main.STUDIO_MAX_ITERATIONS == 8
    for f in main.STUDIO_CONTEXT_FILES:
        if True:
            assert (AGENT / f.removeprefix("agentes/flaire/")).exists(), f  # la plataforma resuelve desde la raíz del workspace


def test_main_con_subagente_revision():
    pytest.importorskip("langchain")
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool as lc_tool
    import main
    import tools as T

    class Falso(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kw):
            return self

    viejo_tools = main.TOOLS
    main.TOOLS = [lc_tool(t) for t in T.TOOLS]
    viejo_cc = main.comprobar_cifra
    main.comprobar_cifra = main.TOOLS[-1]
    main.calcular_cobertura, main.consultar_edificios = main.TOOLS[2], main.TOOLS[7]
    main.USAR_SUBAGENTE_REVISION = True
    try:
        resp = [AIMessage(content="", tool_calls=[{"name": "revisar_propuesta", "args": {"tarea": "Comprueba A k=2 12 min ligero meteo"}, "id": "r1"}]),
                AIMessage(content="", tool_calls=[{"name": "comprobar_cifra", "args": {"estrategia": "A", "k": 2}, "id": "r2"}]),
                AIMessage(content="CIFRA COMPROBADA: coincide"), AIMessage(content="Hallazgo: revisado")]
        out = main.build_agent(Falso(responses=resp)).invoke({"messages": [{"role": "user", "content": "revisa"}]})
        tm = [m for m in out["messages"] if m.type == "tool"]
        assert tm and "CIFRA COMPROBADA" in tm[0].content
    finally:
        main.USAR_SUBAGENTE_REVISION = False
        main.comprobar_cifra = viejo_cc
        main.TOOLS = viejo_tools
