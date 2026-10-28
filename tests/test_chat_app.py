"""Local chat app around the FINAL agent (05_codigo/chat_app).

No model calls here: the photo tool, the tool list the app gives the agent, the static file guard and the
translation of agent updates into the events the page draws are all checked offline.
    python -m pytest -q 05_codigo/tests_pipeline/test_chat_app.py
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
import agent_local  # noqa: E402
import fotos  # noqa: E402
import server  # noqa: E402

CREDIT = "Eusko Jaurlaritza / Gobierno Vasco. geoEuskadi"


@pytest.mark.parametrize("cid,verdict", [("CAND-01", "no_sirve"), ("CAND-02", "sirve"), ("CAND-03", "sirve"),
                                         ("CAND-04", "dudoso")])
def test_photo_for_checked_sites(cid, verdict):
    r = fotos.ortofoto(cid)
    assert r["candidato"] == cid and r["veredicto"] == verdict
    assert (fotos.ORTO_DIR / Path(r["imagen"]).name).exists()
    assert r["imagen"] == f"/ortofotos/{cid}_120m.jpg"
    assert r["credito"].startswith(CREDIT)
    assert r["municipio"] and r["descripcion"]


def test_photo_accepts_loose_ids():
    assert fotos.ortofoto("cand 2")["candidato"] == "CAND-02"
    assert fotos.ortofoto("3")["candidato"] == "CAND-03"


def test_unchecked_site_says_so():
    r = fotos.ortofoto("CAND-07")
    assert r["imagen"] is None and r["veredicto"] == "sin_revisar"
    assert "Orendain" in r["municipio"]


def test_unknown_site_is_an_error():
    with pytest.raises(fotos.ErrorFoto):
        fotos.ortofoto("CAND-11")


def test_agent_gets_ten_working_tools():
    names = [t.name for t in agent_local.herramientas()]
    assert len(names) == 10
    assert "ejecutar_codigo" not in names and "mostrar_ortofoto" in names


def test_tool_returns_json_error_not_exception():
    out = json.loads(agent_local.mostrar_ortofoto.invoke({"candidato": "CAND-99"}))
    assert out["error"]["codigo"] == "PARAMETRO_INVALIDO"


@pytest.mark.parametrize("url,ok", [("/ortofotos/CAND-02_120m.jpg", True), ("/ortofotos/../../.env", False),
                                    ("/data/weekly_calendar.json", True), ("/data/../../.env", False),
                                    ("/data/../../05_codigo/chat_app/server.py", False),
                                    ("/ortofotos/README.md", False), ("/app.js", True), ("/../server.py", False)])
def test_static_guard(url, ok):
    assert (server.resolver(url) is not None) == ok


@pytest.mark.parametrize("host,origin,ctype,ok", [
    ("127.0.0.1:8770", "http://127.0.0.1:8770", "application/json; charset=utf-8", True),
    ("localhost:8770", "http://localhost:8770", "application/json", True),
    ("127.0.0.1:8770", "https://evil.example", "application/json", False),   # another site posting
    ("127.0.0.1:8770", "", "text/plain", False),                             # no-preflight form post
    ("evil.example:8770", "http://evil.example:8770", "application/json", False),  # DNS rebinding
])
def test_api_only_from_own_page(host, origin, ctype, ok):
    headers = {"Host": host, "Content-Type": ctype, **({"Origin": origin} if origin else {})}
    assert server.peticion_local(headers) == ok


def test_public_host_only_when_deployed(monkeypatch):
    # Render sets RENDER_EXTERNAL_HOSTNAME; the public page is https, without a port.
    headers = {"Host": "flaire.onrender.com", "Origin": "https://flaire.onrender.com", "Content-Type": "application/json"}
    assert not server.peticion_local(headers)
    monkeypatch.setattr(server, "PUBLIC_HOST", "flaire.onrender.com")
    assert server.peticion_local(headers)
    assert not server.peticion_local({**headers, "Origin": "http://flaire.onrender.com"})
    assert not server.peticion_local({**headers, "Origin": "https://evil.example"})


def _basic(user, pwd):
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()}


def test_password_only_when_set(monkeypatch):
    assert server.autorizado({})                                   # local: no password
    monkeypatch.setattr(server, "PASSWORD", "tolosa")
    assert not server.autorizado({})
    assert not server.autorizado(_basic("luca", "wrong"))
    assert not server.autorizado({"Authorization": "Basic %%%"})  # not base64
    assert server.autorizado(_basic("luca", "tolosa"))             # any user name, right password


def test_selection_from_real_tool_results():
    # The map lights the sites the answer placed: the optimizer's largest k, or a coverage call's selection.
    fd = agent_local.fd
    assert server._seleccion(json.dumps(fd.optimizar(3, "A", 12, "ligero", "prioridad", None, "edificios"),
                                        default=str)) == ["CAND-01", "CAND-02", "CAND-03"]
    assert server._seleccion(json.dumps(fd.cobertura("CAND-02", 12, "ligero", "prioridad", None, None, "A"),
                                        default=str)) == ["CAND-02"]
    # "¿Qué aporta el tercer retén?" can be answered with consultar_edificios(modo='ganados', k=3) alone.
    assert server._seleccion(json.dumps(fd.edificios_ganados(3, "A", 12, "ligero", "prioridad", None, 15, None),
                                        default=str)) == ["CAND-01", "CAND-02", "CAND-03"]
    assert server._seleccion(json.dumps(fotos.ortofoto("CAND-02"))) is None
    assert server._seleccion("not json") is None


def test_events_from_agent_updates():
    from langchain_core.messages import AIMessage, ToolMessage

    call = AIMessage(content="", tool_calls=[{"name": "mostrar_ortofoto", "args": {"candidato": "CAND-02"}, "id": "t1"}])
    tool = ToolMessage(content=json.dumps(fotos.ortofoto("CAND-02")), name="mostrar_ortofoto", tool_call_id="t1")
    final = AIMessage(content="Es un aparcamiento real.")
    ev = list(server.eventos({"model": {"messages": [call]}})) + list(server.eventos({"tools": {"messages": [tool]}})) \
        + list(server.eventos({"model": {"messages": [final]}}))
    assert [e["type"] for e in ev] == ["tool_start", "tool_end", "answer"]
    assert ev[1]["attachment"] == {"kind": "photo", **{k: fotos.ortofoto("CAND-02")[k] for k in
                                   ("candidato", "nombre", "municipio", "imagen", "veredicto", "descripcion", "credito")}}
    assert ev[2]["text"] == "Es un aparcamiento real."
