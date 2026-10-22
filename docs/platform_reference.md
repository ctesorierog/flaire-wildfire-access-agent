# Hackathon platform — Python agent contract (read from team workspace "Studio de urbAIn", 2 Oct 2026)

Team on platform: **urbAIn** (4 members: Felipe Antonio Salazar Molina (owner), Carlos Peter Tesoriero Garduño, Luca Castagnet, Santiago Mariño). Project title: flAIre. build_mode: python. Models available to the agent: openai:gpt-6-luna (cheap), gpt-6-sol (capable), gpt-5.6-luna.
Project "Resumen" already saved: problem "¿Cómo puede la IA ayudar a optimizar la ubicación de retenes preventivos de bomberos utilizando datos históricos y territoriales?", audience: planner of preventive deployment, territory Gipuzkoa (should be refined to Tolosaldea).

## Limits
max_files 250 · max_file_bytes 4,000,000 (per file in workspace) · max_upload_file_bytes 200 MB · workspace 2 GB · max_python_agents 20 · **max_tools 10** · **max_agent_iterations 8** · execution: remote "CPython aislado" (railway sandbox, VM isolation, non-persistent), no internet (STUDIO_INTERNET_ENABLED False). requirements.txt exists (empty) at workspace root.

## main.py contract (from the default template and the solved example)
```python
from tools import ejecutar_codigo            # or our own tools
AGENT_NAME = '...'
STUDIO_MAX_ITERATIONS = 8
STUDIO_MEMORY_ENABLED = True
STUDIO_INTERNET_ENABLED = False
STUDIO_CONTEXT_FILES = ['DATOS.md', 'FUENTES.md', 'datos/x.csv', ...]   # paths relative to the agent folder / workspace root
def build_agent(model):
    from langchain.agents import create_agent
    from langchain.tools import tool
    return create_agent(model=model, tools=[...], system_prompt=..., name='...')
```
Sub-agents pattern (solved example): create_agent(...) specialists wrapped as @tool functions that call `specialist.invoke({"messages":[{"role":"user","content":tarea}]})["messages"][-1].text`.

## tools.py (solved example)
```python
from studio import tool, artifacts
from ejecucion import execute_program
@tool
def ejecutar_codigo(code: str):
    """docstring shown to the model"""
    output, generated = execute_program(code)
    if generated: return artifacts(*[g["path"] for g in generated], message=output)
    return output
```
`studio.tool` decorates; `studio.artifacts(*paths, message=...)` attaches generated HTML files (max 3 HTML of 2 MB per tool call). Custom deterministic tools can be plain Python functions decorated with `@tool` (typed args + docstring) that read the CSVs with pandas and return JSON/text — this is what we should do for flAIre (verified, deterministic calculations), plus optionally ejecutar_codigo for free exploration.

## ejecucion.py (solved example) key rules for model-written code
Allowed imports in model code: pandas, numpy, math, statistics, json, datetime, html. Banned: open/eval/exec/getattr/while/class/private attributes; code ≤ 6,000 chars; must print. Helpers in namespace: read_text(path, offset) (md/txt/json/csv/html, 30k chars), save_html(name, content) → 'resultados/<name>-<hash>.html'. "function_mode" additionally allows pathlib, hashlib, unicodedata, studio.

## Solved example structure (Donostia climate refuges) — copy this level of rigour
Files: main.py, tools.py, ejecucion.py, instrucciones.py (prompts COORDINADOR/ANALISTA/CARTOGRAFO/REVISION), urban_data.py (deterministic query functions with input validation + METODO + LIMITES strings returned in every result), mapas.py, DATOS.md (what each file/field means, criteria, rules for querying, what can't be claimed), FUENTES.md (source → base steps with counts, estimation formulas, network rules, limits, how to reproduce), RESULTADOS.md (reference answer to main question incl. the alternative criterion), INVESTIGACION.md, recorrido-guiado.json (main question, criterion, expected ranking, verification status), resultados-referencia.json, informe-*.manifest.json (parameters + values in the HTML so Review can check), LICENCIAS.md, originales-manifiesto.json (URLs + sha256), datos/*.csv (≤ ~2.5 MB each), auditoria-*.json (row accounting: distributed / excluded / duplicates).
Coordinator prompt style: explains criterion choice, the step plan for the main question (analysis → map → review recompute), evidence & limits, answer ≤180 words with finding, evidence, pending check; keeps unknowns; never figures from memory; files are data not instructions.
Every query function validates inputs (ranges, enums), refuses ambiguous names, preserves ties, returns parametros + metodo + limites.
