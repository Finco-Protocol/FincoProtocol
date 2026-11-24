"""FINCO 37 Batch 4 — Slice C (C1-Q-09 / C3-E-07): _POLICY_RUN_CACHE ownership and isolation.

Proves:
1. Miss and hit callers receive defensively isolated copies: mutating nested mutable leaves
   (e.g. ``g2c_result.financing_result.project_model_result.senior_debt.diagnostics``) on either the
   initial miss or a subsequent hit cannot pollute cached state or subsequent callers.
2. Negative control: disabling defensive cloning reproduces the pre-fix cross-caller mutation bleed.
3. Bounded size (max 16) and safe concurrent lookup/insert/eviction (lock never held across compute()).
4. Failed engine computations are never cached.
5. V10/V11 native config modes and dated-R04 vs legacy inputs bind distinct cache keys.
6. Exact numerical parity between cold and warm runs across Solar, Wind, Data Center, EV Charging,
   and dated R04 Solar/Wind.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import threading
import pytest

from app import project_factories as pf
from app.services import production_financial_authority as pfa
from app.services.production_financial_authority import (
    _POLICY_RUN_CACHE,
    _POLICY_RUN_CACHE_MAX,
    _memoised_policy_run,
    run_clean_production,
)
from app.workbook.revenue_multistream import apply_config
from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa


def _clear_cache() -> None:
    with pfa._POLICY_RUN_CACHE_LOCK:
        _POLICY_RUN_CACHE.clear()


def _numeric_digest(run) -> str:
    rs = run.g2c_result.return_summary
    sd = run.g2c_result.financing_result.project_model_result.senior_debt
    payload = {
        "project_xirr": rs.project.project_xirr,
        "pure_equity_xirr": run.g2c_result.pure_equity_xirr,
        "total_sponsor_xirr": run.g2c_result.total_sponsor_xirr,
        "senior_debt_size": sd.debt_size_keur,
        "senior_closing": list(sd.senior_debt_closing_keur),
        "bs_count": len(run.financial_statements_result.balance_sheet_periods),
        "last_date": str(run.financial_statements_result.balance_sheet_periods[-1].period_end),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def test_slice_c_miss_and_hit_mutations_cannot_corrupt_cached_result():
    _clear_cache()
    pi = pf.create_generic_solar_reference()

    # 1. Cold miss -> mutate nested mutable diagnostics dict on returned object
    r1 = run_clean_production(pi, "Base", project_type="solar")
    diag1 = r1.g2c_result.financing_result.project_model_result.senior_debt.diagnostics
    assert isinstance(diag1, dict) and diag1.get("converged") is True
    orig_snapshot = dict(diag1)
    diag1["poison_from_miss"] = "CORRUPTED"
    diag1["converged"] = False

    # 2. Warm hit -> must be completely unaffected by miss-caller mutation
    r2 = run_clean_production(pi, "Base", project_type="solar")
    assert r2.g2c_result is not r1.g2c_result
    diag2 = r2.g2c_result.financing_result.project_model_result.senior_debt.diagnostics
    assert diag2 == orig_snapshot
    assert "poison_from_miss" not in diag2

    # 3. Mutate hit return -> third hit must remain canonical
    diag2["poison_from_hit"] = 999
    diag2["final_debt_size_keur"] = -1.0
    r3 = run_clean_production(pi, "Base", project_type="solar")
    assert r3.g2c_result is not r2.g2c_result
    diag3 = r3.g2c_result.financing_result.project_model_result.senior_debt.diagnostics
    assert diag3 == orig_snapshot
    assert "poison_from_hit" not in diag3


def test_slice_c_negative_control_uncloned_cache_reproduces_mutation_bleed(monkeypatch):
    """Negative control: removing defensive cloning reproduces the exact C1-Q-09/C3-E-07 alias bleed."""
    _clear_cache()
    monkeypatch.setattr(pfa, "_clone_cached_policy_value", lambda v: v)
    shared = ({"diagnostics": {"converged": True}}, "inputs", "evidence")
    hit1 = _memoised_policy_run("neg-ctrl-in", "neg-ctrl-pol", lambda: shared)
    hit1[0]["diagnostics"]["poison"] = True
    hit2 = _memoised_policy_run("neg-ctrl-in", "neg-ctrl-pol", lambda: (_ for _ in ()).throw(AssertionError("should hit")))
    assert hit2[0]["diagnostics"].get("poison") is True, "Negative control must reproduce alias bleed when cloning is disabled"
    _clear_cache()


def test_slice_c_bounded_eviction_and_failed_compute_not_cached():
    _clear_cache()
    # Bounded max 16 eviction
    for i in range(_POLICY_RUN_CACHE_MAX + 5):
        out = _memoised_policy_run(f"in-{i}", "pol", lambda i=i: ({"k": i},))
        assert out[0]["k"] == i
    with pfa._POLICY_RUN_CACHE_LOCK:
        assert len(_POLICY_RUN_CACHE) == _POLICY_RUN_CACHE_MAX

    # Failed compute must not be cached
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ENGINE_BOOM")
        return ({"ok": True},)

    with pytest.raises(RuntimeError, match="ENGINE_BOOM"):
        _memoised_policy_run("fail-case", "pol", flaky)
    recovered = _memoised_policy_run("fail-case", "pol", flaky)
    assert recovered == ({"ok": True},) and calls["n"] == 2
    _clear_cache()


def test_slice_c_concurrent_threads_isolated_and_compute_not_serialized():
    _clear_cache()
    barrier = threading.Barrier(4)
    in_flight = threading.Barrier(2)

    # 1. Prove two distinct keys execute compute() concurrently (lock is NOT held across compute())
    def concurrent_compute(tag: str):
        in_flight.wait(timeout=5.0)
        return ({"tag": tag, "nested": [tag]},)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_memoised_policy_run, "conc-a", "pol", lambda: concurrent_compute("a"))
        f2 = pool.submit(_memoised_policy_run, "conc-b", "pol", lambda: concurrent_compute("b"))
        assert f1.result()[0]["tag"] == "a"
        assert f2.result()[0]["tag"] == "b"

    # 2. Concurrent hits on same key: each thread mutates its copy; final hit stays clean
    _memoised_policy_run("shared-key", "pol", lambda: ({"items": [1, 2, 3]},))

    def worker(idx: int):
        barrier.wait(timeout=5.0)
        res = _memoised_policy_run("shared-key", "pol", lambda: (_ for _ in ()).throw(AssertionError("unexpected miss")))
        assert res[0]["items"] == [1, 2, 3]
        res[0]["items"].append(f"mutated-{idx}")
        return res[0]["items"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))
    assert len(results) == 4
    final = _memoised_policy_run("shared-key", "pol", lambda: (_ for _ in ()).throw(AssertionError("unexpected miss")))
    assert final[0]["items"] == [1, 2, 3]
    _clear_cache()


def test_slice_c_v10_v11_native_modes_bind_distinct_cache_keys(monkeypatch):
    _clear_cache()
    from financial_engine.native_v10 import config as v10_cfg
    from financial_engine.native_v11 import config as v11_cfg

    class _Cfg:
        def __init__(self, mode: str):
            self.mode = mode

        def __repr__(self) -> str:
            return f"Cfg(mode={self.mode!r})"

    monkeypatch.setattr(v10_cfg, "current_config", lambda: _Cfg("off"))
    monkeypatch.setattr(v11_cfg, "current_config", lambda: _Cfg("off"))
    a = _memoised_policy_run("same-input", "same-pol", lambda: ({"src": "off"},))

    monkeypatch.setattr(v11_cfg, "current_config", lambda: _Cfg("shadow"))
    b = _memoised_policy_run("same-input", "same-pol", lambda: ({"src": "v11-shadow"},))

    monkeypatch.setattr(v10_cfg, "current_config", lambda: _Cfg("candidate"))
    c = _memoised_policy_run("same-input", "same-pol", lambda: ({"src": "v10-cand-v11-shadow"},))

    assert a[0]["src"] == "off"
    assert b[0]["src"] == "v11-shadow"
    assert c[0]["src"] == "v10-cand-v11-shadow"
    _clear_cache()


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_slice_c_cold_warm_exact_numeric_parity_all_verticals(kind):
    _clear_cache()
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    cold = run_clean_production(pi, "Base", project_type=kind)
    warm = run_clean_production(pi, "Base", project_type=kind)
    assert cold.g2c_result is not warm.g2c_result
    assert _numeric_digest(cold) == _numeric_digest(warm)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_slice_c_dated_r04_vs_legacy_keys_isolated_and_cold_warm_parity(kind):
    _clear_cache()
    base = getattr(pf, f"create_generic_{kind}_reference")()
    cod = base.info.cod_date
    horizon_end = f"{cod.year + int(base.info.horizon_years)}-{cod.month:02d}-{cod.day:02d}"
    merchant = {**MERCHANT, "start_date": cod.isoformat(), "end_date": horizon_end}
    r04_json = json.dumps(
        {
            "version": 2,
            "technology": kind,
            "indexation_basis": "OPERATING_YEAR",
            "streams": [_ppa("ppa1", cod.isoformat(), f"{cod.year + 1}-{cod.month:02d}-{cod.day:02d}", 1000), merchant],
        },
        separators=(",", ":"),
    )
    dated = apply_config(base, r04_json, project_type=kind)

    leg_cold = run_clean_production(base, "Base", project_type=kind)
    dated_cold = run_clean_production(dated, "Base", project_type=kind)
    dated_warm = run_clean_production(dated, "Base", project_type=kind)

    assert _numeric_digest(dated_cold) == _numeric_digest(dated_warm)
    assert _numeric_digest(leg_cold) != _numeric_digest(dated_cold)
