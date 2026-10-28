"""flAIre study area: one setting for the whole pipeline.

    python official_layers.py --area gipuzkoa limits buildings forest proximity
    python link_build.py --area gipuzkoa --stages times

No flag (and no FLAIRE_AREA env var) = Tolosaldea, with exactly the paths, layer names and file names used before
this module existed. Any other area writes under processed/<subdir>/ so Tolosaldea outputs are never touched.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Tolosaldea pilot: 28 municipalities (INE code -> name), = Área Funcional de Tolosa.
TOLOSALDEA = {
    "20001": "Abaltzisketa", "20002": "Aduna", "20004": "Albiztur", "20005": "Alegia", "20006": "Alkiza",
    "20007": "Altzo", "20008": "Amezketa", "20010": "Anoeta", "20014": "Asteasu", "20904": "Baliarrain",
    "20021": "Belauntza", "20022": "Berastegi", "20023": "Berrobi", "20024": "Bidania-Goiatz", "20031": "Elduain",
    "20907": "Gaztelu", "20041": "Hernialde", "20042": "Ibarra", "20044": "Ikaztegieta", "20046": "Irura",
    "20048": "Larraul", "20050": "Leaburu", "20054": "Lizartza", "20905": "Orendain", "20060": "Orexa",
    "20071": "Tolosa", "20075": "Villabona", "20028": "Zizurkil",
}
# All 88 Gipuzkoa municipalities (INE 20001-20081 + 20901-20907), as in geoEuskadi MUNICIPIOS_5000.
GIPUZKOA = [f"200{i:02d}" for i in range(1, 82)] + [f"2090{i}" for i in range(1, 8)]


@dataclass(frozen=True)
class Area:
    tag: str
    subdir: str                 # "" = processed/ itself
    codes: tuple                # INE municipality codes in the study area
    legacy_comparisons: bool    # v0.1 / v0.2 OSM comparisons and candidate checks (Tolosaldea only)
    origins: str                # "all" = parks + candidate pool + v0.1 sites; "stations" = the 9 parks only

    def proc(self, root: Path) -> Path:
        return root / "processed" / self.subdir if self.subdir else root / "processed"

    @property
    def boundary_layer(self):
        return f"{self.tag}_boundary"

    @property
    def municipalities_layer(self):
        return f"{self.tag}_municipalities"

    @property
    def buildings_file(self):
        return f"buildings_{self.tag}.gpkg"


AREAS = {
    "tolosaldea": Area("tolosaldea", "", tuple(TOLOSALDEA), legacy_comparisons=True, origins="all"),
    "gipuzkoa": Area("gipuzkoa", "gipuzkoa", tuple(GIPUZKOA), legacy_comparisons=False, origins="stations"),
}


def get(name: str) -> Area:
    if name not in AREAS:
        raise ValueError(f"unknown area {name!r}; choose one of {sorted(AREAS)}")
    return AREAS[name]


def current(argv=None, env=None) -> Area:
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env
    if "--area" in argv:
        return get(argv[argv.index("--area") + 1])
    return get(env.get("FLAIRE_AREA", "tolosaldea"))


def strip_args(args):
    """Step arguments without '--area X'."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--area":
            skip = True
        else:
            out.append(a)
    return out
