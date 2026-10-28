"""Run the FINAL flAIre agent once, off-platform, and save the raw transcript (PLAN task 10.5).

The prompt, tools and data are the delivered ones (agent_final + agent_final_data); only the platform's
`studio` module is replaced by the local stand-in next to this file. The model is ours, not the platform's.

Usage (repo root, key in a gitignored .env as ANTHROPIC_API_KEY=...):
    conda run -n flaire python 05_codigo/agent_run/run_agent_once.py "¿Dónde pongo el primer retén y por qué?"
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
DATA = ROOT / "agent" / "data"
OUT = ROOT / "work" / "transcripts"
MODEL = "claude-opus-5-5"


def load_env(path: Path) -> None:
    # Minimal .env reader, so we don't add python-dotenv for one variable.
    if not path.exists():
        sys.exit(f"Missing {path}: add ANTHROPIC_API_KEY=... there.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def text_of(content) -> str:
    # Anthropic messages can be a list of blocks; keep only the text ones.
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def main(question: str) -> None:
    load_env(ROOT / ".env")
    sys.path[:0] = [str(Path(__file__).parent), str(AGENT)]

    import flaire_data as fd
    import main as agent_main
    from langchain_anthropic import ChatAnthropic

    fd.recargar(str(DATA))
    # Pin the public API: a shell may carry another ANTHROPIC_BASE_URL (e.g. Claude Code's own).
    # No temperature: the current models reject it.
    model = ChatAnthropic(model=MODEL, max_tokens=4096, base_url="https://api.anthropic.com")
    agent = agent_main.build_agent(model)

    t0 = time.perf_counter()
    # One "iteration" = a model call plus its tool calls; the platform allowed 8.
    res = agent.invoke({"messages": [{"role": "user", "content": question}]},
                       {"recursion_limit": 2 * agent_main.STUDIO_MAX_ITERATIONS + 1})
    seconds = round(time.perf_counter() - t0, 1)

    steps = []
    for m in res["messages"]:
        step = {"role": m.type, "text": text_of(m.content)}
        if getattr(m, "tool_calls", None):
            step["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in m.tool_calls]
        if m.type == "tool":
            step["tool"] = m.name
        steps.append(step)

    record = {
        "question": question,
        "answer": steps[-1]["text"],
        "model": MODEL,
        "agent": "agent_final (instrucciones.COORDINADOR, tools.TOOLS)",
        "data": "agent_final_data",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": seconds,
        "model_calls": sum(1 for s in steps if s["role"] == "ai"),
        "messages": steps,
    }
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{datetime.now():%Y-%m-%d_%H%M}_agent_final.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {path.relative_to(ROOT)} ({seconds} s, {record['model_calls']} model calls)\n")
    print(record["answer"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "¿Dónde pongo el primer retén y por qué?")
