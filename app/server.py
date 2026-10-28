#!/usr/bin/env python3
"""flAIre local chat app: a standard-library web server around the FINAL agent.

    conda run -n flaire python 05_codigo/chat_app/server.py        # then open http://127.0.0.1:8770/

POST /api/chat {"thread": id, "message": text} streams NDJSON events while the agent works:
  tool_start {id, name, args} · tool_end {id, name, ok, attachment?} · note {text} · answer {text} · done {seconds} · error
attachment is {"kind": "photo", ...} for mostrar_ortofoto and {"kind": "report", "url"} for generar_informe.
Every turn is appended to transcripts/chat_<thread>.json, so any screenshot quotes a saved run.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_local  # noqa: E402
import fotos  # noqa: E402

STATIC = HERE / "static"
TRANSCRIPTS = agent_local.REPO / "work" / "transcripts"
PORT = int(os.environ.get("PORT", 8770))
# Deployed on Render: it sets PORT and RENDER_EXTERNAL_HOSTNAME; FLAIRE_PASSWORD is ours (Render settings).
PUBLIC_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
PASSWORD = os.environ.get("FLAIRE_PASSWORD", "")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".jpg": "image/jpeg",
         ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json"}
# Only these folders are served, and only these file types from each.
ROUTES = {"/ortofotos/": (fotos.ORTO_DIR, {".jpg"}), "/informes/": (agent_local.INFORMES, {".html"}),
          "/data/": (agent_local.REPO / "app" / "data", {".json"})}  # the contract JSONs (weekly strip), read-only
PHOTO_KEYS = ("candidato", "nombre", "municipio", "imagen", "veredicto", "descripcion", "credito")

_agent = None


ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


def peticion_local(headers) -> bool:
    """Only our own page may call the API: right Host (stops DNS rebinding), right Origin and a JSON body
    (stops another website from posting here and spending the API key). When deployed, the public https
    address counts as our own page too."""
    origins = {f"http://{h}": h for h in ALLOWED_HOSTS}
    if PUBLIC_HOST:
        origins[f"https://{PUBLIC_HOST}"] = PUBLIC_HOST
    origin = headers.get("Origin", "")
    return (origin in origins and headers.get("Host", "") == origins[origin]
            and headers.get("Content-Type", "").split(";")[0].strip() == "application/json")


def autorizado(headers) -> bool:
    """With FLAIRE_PASSWORD set (the public deploy), every request needs it via HTTP Basic auth; any user name."""
    if not PASSWORD:
        return True
    kind, _, value = headers.get("Authorization", "").partition(" ")
    try:
        pwd = base64.b64decode(value, validate=True).decode("utf-8").partition(":")[2]
    except (ValueError, UnicodeDecodeError):
        return False
    return kind == "Basic" and hmac.compare_digest(pwd.encode(), PASSWORD.encode())


def resolver(url: str) -> Path | None:
    """URL path -> file to serve, or None. Never leaves the allowed folders."""
    path = url.split("?", 1)[0]
    base, allowed = STATIC, set(TYPES)
    for prefix, (folder, exts) in ROUTES.items():
        if path.startswith(prefix):
            base, allowed, path = folder, exts, path[len(prefix):]
            break
    path = path.lstrip("/") or "index.html"
    try:
        f = (base / path).resolve()
        f.relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return f if f.is_file() and f.suffix in allowed else None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _attachment(name: str, content: str):
    if name == "mostrar_ortofoto":
        r = json.loads(content)
        return None if "error" in r else {"kind": "photo", **{k: r.get(k) for k in PHOTO_KEYS}}
    if name == "generar_informe":
        # studio.artifacts() returns the tool's JSON, then "[adjuntos: <path>]".
        m = re.search(r"\[adjuntos: ([^\]]+)\]", content)
        if m:
            return {"kind": "report", "url": "/informes/" + Path(m.group(1).strip()).name}
    return None


def _seleccion(content: str):
    """Study sites a tool result placed, so the page's map can light them: the optimizer's largest k
    (por_k[-1].seleccion), else the first 'seleccion' list in the result (coverage, checks). None if it placed none."""
    try:
        r = json.loads(content)
    except ValueError:
        return None
    if isinstance(r, dict) and isinstance(r.get("por_k"), list) and r["por_k"]:
        return list(r["por_k"][-1].get("seleccion") or [])
    if isinstance(r, dict) and isinstance(r.get("seleccion_k"), list):  # "what does the k-th crew add?"
        return list(r["seleccion_k"])
    stack = [r]
    while stack:
        o = stack.pop(0)
        if isinstance(o, dict):
            if isinstance(o.get("seleccion"), list):
                return [s for s in o["seleccion"] if isinstance(s, str) and s.startswith("CAND-")]
            stack.extend(o.values())
    return None


def eventos(update: dict):
    """One agent stream update ({node: {"messages": [...]}}) -> the events the page draws."""
    for node in update.values():
        for m in (node or {}).get("messages", []):
            if m.type == "ai":
                text = _text(m.content).strip()
                if m.tool_calls:
                    if text:
                        yield {"type": "note", "text": text}
                    for c in m.tool_calls:
                        yield {"type": "tool_start", "id": c["id"], "name": c["name"], "args": c["args"]}
                elif text:
                    yield {"type": "answer", "text": text}
            elif m.type == "tool":
                content = _text(m.content)
                ok = not content.lstrip().startswith('{"error"')
                ev = {"type": "tool_end", "id": m.tool_call_id, "name": m.name, "ok": ok}
                try:
                    att = _attachment(m.name, content) if ok else None
                except (ValueError, KeyError):
                    att = None
                if att:
                    ev["attachment"] = att
                sel = _seleccion(content) if ok else None
                if sel is not None:
                    ev["selection"] = sel
                yield ev


def _save(thread: str, record: dict) -> None:
    TRANSCRIPTS.mkdir(exist_ok=True)
    path = TRANSCRIPTS / f"chat_{thread}.json"
    turns = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    turns.append(record)
    path.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002  quieter console: errors only
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
            super().log_message(format, *args)

    def pide_clave(self) -> bool:
        if autorizado(self.headers):
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="flAIre", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def do_GET(self):
        if self.pide_clave():
            return
        f = resolver(self.path)
        if f is None:
            self.send_error(404)
            return
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES[f.suffix])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.pide_clave():
            return
        if self.path != "/api/chat":
            self.send_error(404)
            return
        if not peticion_local(self.headers):
            self.send_error(403, "only the flAIre page on this machine can ask")
            return
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "body must be UTF-8 JSON")
            return
        thread = re.sub(r"[^A-Za-z0-9_-]", "", str(req.get("thread", "")))[:40] or "default"
        question = str(req.get("message", "")).strip()
        if not question:
            self.send_error(400, "empty message")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def send(ev):
            self.wfile.write((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        global _agent
        t0, events = time.perf_counter(), []
        try:
            if _agent is None:
                _agent = agent_local.build_agent()
            config = {"configurable": {"thread_id": thread}, "recursion_limit": 17}  # 8 iterations, as on the platform
            for update in _agent.stream({"messages": [{"role": "user", "content": question}]}, config,
                                        stream_mode="updates"):
                for ev in eventos(update):
                    events.append(ev)
                    send(ev)
        except Exception as e:  # noqa: BLE001  (shown in the page, and saved with the turn)
            ev = {"type": "error", "text": f"{type(e).__name__}: {e}"}
            events.append(ev)
            send(ev)
        seconds = round(time.perf_counter() - t0, 1)
        send({"type": "done", "seconds": seconds})
        _save(thread, {"question": question, "run_at": datetime.now().isoformat(timespec="seconds"),
                       "model": agent_local.MODEL, "seconds": seconds, "events": events})


def main():
    if PUBLIC_HOST and not PASSWORD:
        raise SystemExit("Deployed without FLAIRE_PASSWORD: anyone could spend the API key. Set it in Render.")
    bind = "0.0.0.0" if PUBLIC_HOST else "127.0.0.1"  # all interfaces only when deployed
    httpd = ThreadingHTTPServer((bind, PORT), Handler)
    print(f"flAIre chat on http://{bind}:{PORT}/  (Ctrl+C to stop)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
