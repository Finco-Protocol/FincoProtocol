"""The independent reviewer's V10 counterexamples, re-run against the corrected candidate.

Each probe compares the canonical outcome with the candidate outcome on a REAL Senior-solver context
captured from a canonical Solar Run: either the candidate serves bit-identically, or it declines before
any effect and the canonical code produces exactly the same value / exception (including how many
times an independent fault point is reached)."""
from __future__ import annotations

import ctypes as C
import gc
import os
import subprocess
import sys
import threading
import types
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import financial_engine.senior_debt.solver as solver
import financial_engine.tax.engine as tax
import financial_engine.tax.loss_ledger as loss_ledger
from financial_engine.native_v10.config import NativeConfig, current_config, native_run
from financial_engine.policies.tax import CashTaxTiming, TaxPolicy
from financial_engine.run_scope import current_run_scope
from tests.native_v10_support import STAGE1, acceptance

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("native_artifacts")


def _outcome(call):
    acc = acceptance()
    try:
        return {"verdict": "RETURN", "digest": acc.digest(acc.flatten(call()))}
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "RAISE", "type": type(exc).__name__, "message": str(exc)}


@pytest.fixture(scope="module")
def solar_context():
    """Keyword arguments of a real ``_solve_dscr`` call from a canonical (OFF) Solar Run."""
    from app import project_factories as pf
    from app.services import production_financial_authority as pfa

    captured, real = [], solver._solve_dscr

    def capture(**kw):
        if not captured:
            captured.append(kw)
        return real(**kw)

    solver._solve_dscr = capture
    try:
        pfa._POLICY_RUN_CACHE.clear()
        pfa.run_clean_production(pf.create_generic_solar_reference(), project_type="Solar")
    finally:
        solver._solve_dscr = real
        pfa._POLICY_RUN_CACHE.clear()
    return captured[0]


def test_baseline_real_context_is_served_bit_identically(solar_context):
    canonical = _outcome(lambda: solver._solve_dscr(**solar_context))
    with native_run(STAGE1) as stats:
        candidate = _outcome(lambda: solver._solve_dscr(**solar_context))
    assert candidate == canonical and canonical["verdict"] == "RETURN"
    assert stats.native_solves == 1 and not stats.declines


def test_v10_02_spoofed_callback_with_canonical_qualname_declines(solar_context):
    original = solar_context["tax_cfads_fn"]
    cells = {n: c.cell_contents for n, c in zip(original.__code__.co_freevars, original.__closure__)}
    names = sorted(cells)
    src = ("def factory(original, calls, " + ", ".join(names) + "):\n"
           "    def callback(interest_by):\n        retained = (" + ", ".join(names) + ",)\n"
           "        calls['n'] += 1\n        if calls['n'] == 3: raise RuntimeError('INDEPENDENT_CALLBACK_FAULT_3')\n"
           "        return original(interest_by)\n    return callback\n")
    ns: dict = {}
    exec(src, ns)  # noqa: S102 - deliberately foreign code object
    calls = {"n": 0}
    spoof = ns["factory"](original, calls, **cells)
    spoof.__qualname__ = original.__qualname__
    ctx = dict(solar_context, tax_cfads_fn=spoof)
    canonical = _outcome(lambda: solver._solve_dscr(**ctx))
    canonical_calls, calls["n"] = calls["n"], 0
    with native_run(STAGE1) as stats:
        candidate = _outcome(lambda: solver._solve_dscr(**ctx))
    assert canonical == candidate == {"verdict": "RAISE", "type": "RuntimeError", "message": "INDEPENDENT_CALLBACK_FAULT_3"}
    assert calls["n"] == canonical_calls == 3
    assert stats.native_solves == 0 and stats.declines


def test_v10_02b_canonical_code_with_forged_closure_cell_declines(solar_context):
    original = solar_context["tax_cfads_fn"]

    def raising_calc(periods, tax_input):
        raise RuntimeError("FORGED_CELL_FAULT")

    cells = tuple(types.CellType(raising_calc) if n == "calculate_cfads_and_cash_tax" else c
                  for n, c in zip(original.__code__.co_freevars, original.__closure__))
    forged = types.FunctionType(original.__code__, original.__globals__, original.__name__, None, cells)
    ctx = dict(solar_context, tax_cfads_fn=forged)
    canonical = _outcome(lambda: solver._solve_dscr(**ctx))
    with native_run(STAGE1) as stats:
        candidate = _outcome(lambda: solver._solve_dscr(**ctx))
    assert canonical == candidate == {"verdict": "RAISE", "type": "RuntimeError", "message": "FORGED_CELL_FAULT"}
    assert stats.native_solves == 0
    assert any(r.startswith("CALLBACK_CELL_INVALID") for r in stats.declines)


def test_v10_03_repeated_canonical_helper_fault_declines(solar_context, monkeypatch):
    real_open, calls = loss_ledger._opening_states_from_inputs, {"n": 0}

    def opening(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("INDEPENDENT_OPENING_FAULT_2")
        return real_open(*a, **k)

    monkeypatch.setattr(loss_ledger, "_opening_states_from_inputs", opening)
    canonical = _outcome(lambda: solver._solve_dscr(**solar_context))
    canonical_calls, calls["n"] = calls["n"], 0
    with native_run(STAGE1) as stats:
        candidate = _outcome(lambda: solver._solve_dscr(**solar_context))
    assert canonical == candidate == {"verdict": "RAISE", "type": "RuntimeError", "message": "INDEPENDENT_OPENING_FAULT_2"}
    assert calls["n"] == canonical_calls == 2
    assert stats.native_solves == 0


@pytest.mark.parametrize("label,years,lag,ebitda,admitted", [
    ("ordinary", 5, 0, [-100., 100.], True),
    ("loss_year_INT_MAX", 2147483647, 0, [-100., 100.], True),
    ("payment_lag_2pow32", 5, 4294967296, [100., 100.], True),
    ("loss_year_2pow53_plus1", 2 ** 53 + 1, 0, [-100., 100.], False),
    ("loss_year_2pow62", 2 ** 62, 0, [-100., 100.], False),
    ("payment_lag_2pow63", 5, 2 ** 63, [100., 100.], False),
])
def test_v10_01_integer_representation(label, years, lag, ebitda, admitted):
    from financial_engine.native_v10 import dispatch, loader

    native, why = loader.get_native()
    assert native is not None, why
    roll = SimpleNamespace(period_indices=(0, 1), rates=(0., 0.), day_fracs=(1., 1.), in_repayment=(True, True),
                           dscr_targets=(1., 1.), availabilities=(1., 1.), repayment_method="dscr_sculpted",
                           debt_service_scale=1.)
    spol = SimpleNamespace(damping_alpha=.5, maximum_iterations=100, convergence_tolerance_keur=1e-6,
                           convergence_relative_tolerance=1e-6)
    periods = tuple(SimpleNamespace(period_index=i, period_start=date(2026 + i, 1, 1), period_end=date(2027 + i, 1, 1),
                                    ebitda_keur=e, tax_depreciation_keur=0.) for i, e in enumerate(ebitda))
    plan = tax._tax_plan_for(periods)
    pol = TaxPolicy(policy_id="INDEPENDENT", policy_version="1", corporate_rate=.2, periods_per_tax_year=1,
                    loss_carryforward_years=years, atad_enabled=False, atad_ebitda_limit=.3,
                    atad_de_minimis_threshold_keur_annual=3000., cash_tax_timing=CashTaxTiming.TAX_YEAR_LAST_PERIOD,
                    cash_tax_payment_lag_periods=lag)
    zero = [0., 0.]
    canonical = tax._evaluate_numeric_tax_vectors_uncached(
        periods, policy=pol, opening_loss_vintages=(), plan=plan, gross_interest_by_row=tuple(zero),
        shl_non_deductible_by_row=tuple(zero), reintegration_by_row=tuple(zero), financing_income_by_row=tuple(zero))
    ctx = {"periods": periods, "plan": plan, "policy": pol, "opening": (),
           **{k: list(zero) for k in ("other", "elig", "nd", "sgross", "snd", "reint", "fin")}}
    if not admitted:
        with pytest.raises(dispatch._Decline) as declined:
            dispatch._build_plan(ctx, roll, spol)
        assert declined.value.reason.startswith("INT_NOT_REPRESENTABLE")
        return
    P, keep, _ = dispatch._build_plan(ctx, roll, spol)
    cf, tx = (C.c_double * 2)(), (C.c_double * 2)()
    assert native.lib.fk_tax(C.byref(P), (C.c_double * 2)(0., 0.), 2, cf, tx, 2) == 0
    assert [[v.hex() for v in (cf[0], cf[1])], [v.hex() for v in (tx[0], tx[1])]] == \
        [[v.hex() for v in canonical[0].values()], [v.hex() for v in canonical[1].values()]]
    assert (P.lcf_years, P.lag) == (years, lag)


def test_v10_06_geometry_is_run_scoped_and_released(monkeypatch):
    from app import project_factories as pf
    from app.services import production_financial_authority as pfa
    from financial_engine.native_v10 import dispatch

    seen, real = [], dispatch._geometry
    monkeypatch.setattr(dispatch, "_geometry", lambda tp, periods: (seen.append(id(tp)), real(tp, periods))[1])
    with native_run(STAGE1) as stats:
        for _ in range(2):
            pfa._POLICY_RUN_CACHE.clear()
            pfa.run_clean_production(pf.create_generic_solar_reference(), project_type="Solar")
    pfa._POLICY_RUN_CACHE.clear()
    gc.collect()
    assert seen and stats.native_solves > 0
    assert current_run_scope() is None
    assert not [n for n, v in vars(dispatch).items() if "GEOM" in n and isinstance(v, dict)]
    ids = set(seen)
    assert sum(1 for o in gc.get_objects() if type(o).__name__ == "_TaxPlan" and id(o) in ids) == 0


def test_v10_07_run_mode_is_context_local_across_threads(solar_context):
    acc = acceptance()
    reference = acc.digest(acc.flatten(solver._solve_dscr(**solar_context)))
    entered, switched, done = threading.Event(), threading.Event(), threading.Event()
    seen: dict = {}

    def intended_off():
        with native_run(NativeConfig()) as s_off:
            entered.set()
            switched.wait(30)
            r = solver._solve_dscr(**solar_context)
            seen.update(off_mode=current_config().mode, off_native=s_off.native_solves,
                        off_equal=acc.digest(acc.flatten(r)) == reference)
        done.set()

    def other_candidate():
        entered.wait(30)
        with native_run(STAGE1) as s_c:
            switched.set()
            solver._solve_dscr(**solar_context)
            seen["candidate_native"] = s_c.native_solves
            done.wait(30)

    threads = [threading.Thread(target=intended_off), threading.Thread(target=other_candidate)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert seen == {"off_mode": "off", "off_native": 0, "off_equal": True, "candidate_native": 1}


def test_v10_08_candidate_run_with_missing_binary_is_canonical(tmp_path):
    """In a separate interpreter the loader points at an empty directory: the candidate Run completes
    canonically with a recorded loader decline and no native solve."""
    code = (
        "import json, pathlib\n"
        "import financial_engine.native_v10.loader as L\n"
        f"L.HERE = pathlib.Path({str(tmp_path)!r})\n"
        "from financial_engine.native_v10.config import NativeConfig, native_run\n"
        "from app.services import production_financial_authority as pfa\n"
        "from app import project_factories as pf\n"
        "with native_run(NativeConfig(mode='candidate')) as st:\n"
        "    pfa.run_clean_production(pf.create_generic_solar_reference(), project_type='Solar')\n"
        "print(json.dumps(st.as_dict()))\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env,
                          timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    import json
    stats = json.loads(proc.stdout.strip().splitlines()[-1])
    assert stats["native_solves"] == 0
    assert stats["loader_reason"].startswith("LOADER_ARTIFACT_UNAVAILABLE")
