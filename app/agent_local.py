"""The FINAL flAIre agent, set up for the local chat app.

Same prompt, same deterministic tools, same data as the delivered agent (agent_final + agent_final_data);
its files are imported, never edited. Two local changes, both forced by running off the hackathon platform:
- ejecutar_codigo needs the platform's `ejecucion` module, which isn't in the repo, so its slot goes to
  mostrar_ortofoto (the orthophotos checked in PLAN task 10.4). Still 10 tools, the platform limit.
- generar_informe writes its HTML report into 05_codigo/chat_app/_informes/, which the server serves.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from langchain.tools import tool

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
AGENT = REPO / "agent"
DATA = REPO / "agent" / "data"
INFORMES = HERE / "_informes"
MODEL = "claude-opus-5-5"

# studio.py (the platform stand-in) lives next to the one-off runner.
sys.path[:0] = [str(HERE), str(AGENT)]
import flaire_data as fd  # noqa: E402
import fotos  # noqa: E402
import instrucciones  # noqa: E402
import mapas  # noqa: E402
import tools as final_tools  # noqa: E402

fd.recargar(str(DATA))
mapas.CARPETA_RESULTADOS = str(INFORMES)

PROMPT_LOCAL = """

## Versión local (app de chat)
- No hay ejecutar_codigo en esta versión. Si ninguna herramienta responde, dilo y propone qué pregunta sí se puede responder.
- Fotos: «enséñame / foto / cómo es el sitio de CAND-xx» → mostrar_ortofoto(candidato). La app muestra la imagen sola;
  tú resume el veredicto en una o dos frases, di que es un lugar de ESTUDIO y cita «geoEuskadi (Gobierno Vasco)».
  Solo CAND-01 a CAND-04 tienen ortofoto revisada; para las demás dilo, sin describir lo que no se ha visto.
- Mapas: generar_informe adjunta el informe con los mapas; la app lo muestra. No pegues la ruta del archivo.
- Respuestas breves: primero la cifra decisiva, luego una tabla corta si ayuda, al final los límites en una línea."""


@tool
def mostrar_ortofoto(candidato: str) -> str:
    """Ortofoto (geoEuskadi ORTO_2025, 120 × 120 m) de una candidata, con el veredicto de la revisión del 27 oct 2026:
    'sirve' (aparcamiento real), 'no_sirve', 'dudoso' o 'sin_revisar' (CAND-05 a CAND-10 aún no se han revisado).
    Usar cuando pidan ver, una foto o cómo es el sitio de una candidata.

    Args:
        candidato: id de la candidata, p. ej. 'CAND-02' (también vale '2').
    """
    try:
        return json.dumps(fotos.ortofoto(candidato), ensure_ascii=False)
    except fotos.ErrorFoto as e:
        return json.dumps({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": str(e)}}, ensure_ascii=False)


def herramientas() -> list:
    return [t for t in final_tools.TOOLS if t.name != "ejecutar_codigo"] + [mostrar_ortofoto]


def load_env(path: Path = REPO / ".env") -> None:
    # Same minimal .env reader as run_agent_once.py.
    if not path.exists():
        if os.environ.get("ANTHROPIC_API_KEY"):  # deployed: the key comes from the host's settings
            return
        raise SystemExit(f"Missing {path}: add ANTHROPIC_API_KEY=... there.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_agent():
    from langchain.agents import create_agent
    from langchain_anthropic import ChatAnthropic
    from langgraph.checkpoint.memory import InMemorySaver

    load_env()
    # Public API pinned (a shell may carry Claude Code's own ANTHROPIC_BASE_URL); no temperature, current models reject it.
    model = ChatAnthropic(model=MODEL, max_tokens=4096, base_url="https://api.anthropic.com")
    # The checkpointer keeps each conversation's history by thread_id, so follow-up questions work.
    return create_agent(model=model, tools=herramientas(), system_prompt=instrucciones.COORDINADOR + PROMPT_LOCAL,
                        checkpointer=InMemorySaver(), name="flaire_local")
