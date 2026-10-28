"""Orthophotos of the study sites, for the chat app's mostrar_ortofoto tool.

Reads only what PLAN task 10.4 checked: the images in 04_informes_y_fuentes/ortofotos/ and the «Ortofoto» line of each
site in fichas_candidatas_v03.md. Sites without a checked photo (CAND-05..10) say so instead of guessing.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORTO_DIR = REPO / "reports" / "orthophotos"
FICHAS = REPO / "reports" / "fichas_candidatas_v03.md"
CREDITO = "Eusko Jaurlaritza / Gobierno Vasco. geoEuskadi (WMS ORTOARGAZKIAK, capa ORTO_2025)"
ESCALA = "120 × 120 m centrados en el punto (cruz roja); barra amarilla = 20 m"
VEREDICTOS = {"✓": "sirve", "✗": "no_sirve", "~": "dudoso"}


class ErrorFoto(ValueError):
    pass


def _id(candidato: str) -> str:
    m = re.search(r"(\d{1,2})\s*$", str(candidato or "").strip())
    if not m:
        raise ErrorFoto(f"'{candidato}' no es una candidata; use CAND-01 a CAND-10.")
    return f"CAND-{int(m.group(1)):02d}"


def _fichas() -> dict:
    """CAND id -> (name, municipality, orthophoto line or None), from the '## CAND-xx · name (municipality)' sections."""
    out, actual = {}, None
    for linea in FICHAS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"## (CAND-\d\d) · (.+) \((.+)\)\s*$", linea)
        if m:
            actual = m.group(1)
            out[actual] = [m.group(2), m.group(3), None]
        elif linea.startswith("## "):
            actual = None
        elif actual and linea.startswith("- **Ortofoto"):
            out[actual][2] = linea.split(":**", 1)[1].strip()
    return out


def ortofoto(candidato: str) -> dict:
    cid = _id(candidato)
    fichas = _fichas()
    if cid not in fichas:
        raise ErrorFoto(f"{cid} no existe; hay 10 candidatas de estudio, CAND-01 a CAND-10.")
    nombre, municipio, linea = fichas[cid]
    img = ORTO_DIR / f"{cid}_120m.jpg"
    if linea is None or not img.exists():
        return {"candidato": cid, "nombre": nombre, "municipio": municipio, "imagen": None, "veredicto": "sin_revisar",
                "descripcion": "Esta candidata aún no se ha revisado en ortofoto (solo CAND-01 a CAND-04).",
                "credito": None}
    return {"candidato": cid, "nombre": nombre, "municipio": municipio, "imagen": f"/ortofotos/{img.name}",
            "veredicto": VEREDICTOS.get(linea[0], "dudoso"), "descripcion": linea.lstrip("✓✗~ ").strip(),
            "credito": CREDITO, "escala": ESCALA, "revisada": "27 oct 2026 (PLAN 10.4)",
            "nota": "Lugar de ESTUDIO, no autorizado. La foto no comprueba titularidad, agua ni acceso de camión."}
