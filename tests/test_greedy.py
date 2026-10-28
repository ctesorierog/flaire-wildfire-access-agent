"""Greedy max coverage must match the exhaustive optimizer on the 10 delivered candidates.

Greedy is what a larger (e.g. province-wide) pool would need, where exhaustive search can't run. Here it is checked against the
exhaustive best count (`_matriz`, uniform weights, light, 12 min) for every k, and against the headline numbers when the
agent's data (agent/data/) is loaded.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "agent"))
import flaire_data as fd  # noqa: E402

fd.recargar(str(REPO / "agent" / "data"))

UMBRAL = 12.0
PERFIL = "ligero"
K_MAX = 6


def _arrays():
    D = fd.datos()
    base, _ = D.base(PERFIL)
    cubierto_base = base <= UMBRAL + fd.EPS
    cubre = D.cand_t(PERFIL) <= UMBRAL + fd.EPS          # (10, n), rows in D.cand_ids order
    return D, cubierto_base, cubre


def _exhaustive_best_count():
    X = fd._matriz(K_MAX, UMBRAL, PERFIL, "uniforme")
    return {k: int(X["n_cov"][X["ks"] == k].max()) for k in range(K_MAX + 1)}


def test_greedy_matches_exhaustive_every_k():
    D, cubierto_base, cubre = _arrays()
    best = _exhaustive_best_count()
    for k in range(1, min(K_MAX, len(D.cand_ids)) + 1):
        pasos = fd.greedy_cobertura(cubierto_base, cubre, k)
        total = int(cubierto_base.sum()) + sum(g for _, g in pasos)
        assert total == best[k], f"k={k}: greedy {total} vs exhaustive {best[k]}"


def test_greedy_is_nested_and_gains_do_not_grow():
    _, cubierto_base, cubre = _arrays()
    p3 = fd.greedy_cobertura(cubierto_base, cubre, 3)
    p6 = fd.greedy_cobertura(cubierto_base, cubre, 6)
    assert p6[:3] == p3
    gains = [g for _, g in p6]
    assert gains == sorted(gains, reverse=True)
    assert len({i for i, _ in p6}) == len(p6)


def test_greedy_counts_each_home_once():
    cubierto_base = np.array([True, False, False, False])
    cubre = np.array([[True, True, False, False],     # site 0: home 0 is already covered -> gain 1
                      [False, True, True, False],     # site 1: gain 2 first
                      [False, False, False, True]])   # site 2: gain 1
    assert fd.greedy_cobertura(cubierto_base, cubre, 3) == [(1, 2), (2, 1)]   # site 0 then adds nothing: stop
    assert fd.greedy_cobertura(cubierto_base, cubre, 0) == []


def test_headline_numbers():
    D, cubierto_base, cubre = _arrays()
    if D.n != 3331:
        pytest.skip("headline numbers need the real data (FLAIRE_TEST_DATOS)")
    assert int(cubierto_base.sum()) == 2712
    pasos = fd.greedy_cobertura(cubierto_base, cubre, 3)
    assert D.cand_ids[pasos[0][0]] == "CAND-02"
    assert 2712 + pasos[0][1] == 2958
    assert 2712 + sum(g for _, g in pasos) == 3187
