"""Local stand-in for the hackathon platform's `studio` module, so the FINAL agent's tools.py imports off-platform.

Only what tools.py uses: `tool` (the LangChain decorator) and `artifacts` (on the platform it attaches files to the
chat; here it returns the tool's text message plus the file paths, so the model sees the same JSON).
"""
from langchain.tools import tool  # noqa: F401  (re-exported for tools.py)


def artifacts(*paths, message=""):
    return f"{message}\n[adjuntos: {', '.join(str(p) for p in paths)}]"
