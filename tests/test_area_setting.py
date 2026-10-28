"""The study area is one setting: Tolosaldea by default with today's paths and names, Gipuzkoa in its own folder."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "work"
sys.path.insert(0, str(REPO / "pipeline"))
import area  # noqa: E402


def test_default_is_tolosaldea():
    assert area.current(argv=["script.py"], env={}).tag == "tolosaldea"


def test_area_flag_selects_gipuzkoa():
    assert area.current(argv=["script.py", "--area", "gipuzkoa", "limits"], env={}).tag == "gipuzkoa"


def test_env_selects_gipuzkoa_when_no_flag():
    assert area.current(argv=["script.py"], env={"FLAIRE_AREA": "gipuzkoa"}).tag == "gipuzkoa"


def test_unknown_area_is_rejected():
    with pytest.raises(ValueError):
        area.current(argv=["script.py", "--area", "bizkaia"], env={})


def test_area_flag_is_stripped_from_step_arguments():
    assert area.strip_args(["--area", "gipuzkoa", "limits", "forest"]) == ["limits", "forest"]


def test_tolosaldea_keeps_todays_paths_and_names():
    t = area.get("tolosaldea")
    assert len(t.codes) == 28 and "20071" in t.codes          # Tolosa
    assert t.proc(ROOT) == ROOT / "processed"
    assert t.boundary_layer == "tolosaldea_boundary"
    assert t.municipalities_layer == "tolosaldea_municipalities"
    assert t.buildings_file == "buildings_tolosaldea.gpkg"
    assert t.legacy_comparisons and t.origins == "all"


def test_gipuzkoa_has_88_municipalities_in_its_own_folder():
    g = area.get("gipuzkoa")
    assert len(g.codes) == 88 and all(c.startswith("20") for c in g.codes)
    assert set(area.get("tolosaldea").codes) <= set(g.codes)
    assert g.proc(ROOT) == ROOT / "processed" / "gipuzkoa"
    assert g.boundary_layer == "gipuzkoa_boundary"
    assert g.buildings_file == "buildings_gipuzkoa.gpkg"
    assert not g.legacy_comparisons and g.origins == "stations"
