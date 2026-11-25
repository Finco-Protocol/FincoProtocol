"""FINCO43 (#322 O8 port): the Senior solver's diagnostic ``maximum_absolute_difference_keur`` is computed only on
the iteration that RETURNS, and the reported float is bit-identical to the value the previous eager loop reported.

Contract pinned here, independently of how the solver schedules the computation:

* the reported value equals ``_compute_max_abs_diff`` evaluated on exactly the arguments of the convergence check of
  the returning iteration (the converged one, or the last one when the iteration budget is exhausted);
* with ``maximum_iterations == 1`` no convergence check ever runs, so the value stays ``inf`` (unchanged contract);
* convergence decisions, iteration counts, termination reasons and schedules are untouched (the converged result is
  compared leaf-by-leaf, ``float.hex``, against a run whose diagnostic is forced to be computed eagerly);
* the optimisation is real: one ``_compute_max_abs_diff`` call per returning solve (was: one per iteration >= 2).

The spy wraps ``_schedules_converged`` (it receives the very same 8 operands as ``_compute_max_abs_diff``) and
``_finalise_authoritative`` (to separate the outer-loop check from the finalisation handshake's own checks).
"""
from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import pytest

import financial_engine.senior_debt.solver as solver_mod
from financial_engine.senior_debt.inputs import SeniorDebtInputs
from financial_engine.senior_debt.policy import (
    DayCountConvention,
    GearingCapRepaymentMethod,
    SeniorDebtPolicy,
    SeniorDebtSizingMode,
)

N = 24


def _periods():
    return tuple(
        SimpleNamespace(
            period_index=i + 1, is_operation=True,
            period_start=date(2030 + i // 2, 1 if i % 2 == 0 else 7, 1),
            period_end=(date(2030 + i // 2, 7, 1) if i % 2 == 0 else date(2031 + i // 2, 1, 1)),
        )
        for i in range(N)
    )


def _policy(*, mode=SeniorDebtSizingMode.DSCR_SCULPTED, max_iter=200, alpha=0.7, **extra):
    return SeniorDebtPolicy(
        policy_id="finco43-o8", policy_version="1", sizing_mode=mode, target_dscr=1.30,
        maximum_gearing=0.85, annual_fixed_rate=0.06, periods_per_year=2,
        day_count_convention=DayCountConvention.ACT_365,
        repayment_start_period_index=1, maturity_period_index=N,
        convergence_tolerance_keur=1e-6, convergence_relative_tolerance=1e-12,
        maximum_iterations=max_iter, permit_terminal_balloon=True, damping_alpha=alpha, **extra,
    )


def _inputs():
    return SeniorDebtInputs(eligible_project_cost_keur=120_000.0, initial_debt_guess_keur=60_000.0,
                            period_rates=(), explicit_principal_schedule=None)


def _tax_cfads_fn(interest_by):
    # Interest-dependent tax shield: CFADS feeds back through interest, so the fixed point needs several iterations.
    cfads, tax = {}, {}
    for idx in range(1, N + 1):
        ebitda = 2000.0 if idx <= 2 else 6500.0 + 15.0 * idx
        taxable = max(0.0, ebitda - 900.0 - interest_by.get(idx, 0.0))
        tax[idx] = 0.19 * taxable
        cfads[idx] = ebitda - tax[idx]
    return cfads, tax


class _Spy:
    def __init__(self, monkeypatch, *, force_not_converged=False):
        self.events: list = []
        self.max_abs_calls = 0
        self.diff_args: list = []
        real_conv = solver_mod._schedules_converged
        real_fin = solver_mod._finalise_authoritative
        real_diff = solver_mod._compute_max_abs_diff

        def conv(*args):
            self.events.append(("check", args[:8]))
            result = real_conv(*args)
            return False if force_not_converged else result

        def fin(*args, **kwargs):
            self.events.append(("finalise", None))
            return real_fin(*args, **kwargs)

        def diff(*args):
            self.max_abs_calls += 1
            self.diff_args.append(args)
            return real_diff(*args)

        monkeypatch.setattr(solver_mod, "_schedules_converged", conv)
        monkeypatch.setattr(solver_mod, "_finalise_authoritative", fin)
        monkeypatch.setattr(solver_mod, "_compute_max_abs_diff", diff)
        self.real_diff = real_diff

    def assert_diff_operands_are(self, check_args):
        """The diagnostic must be computed on EXACTLY the returning check's operands (same objects, same floats),
        so a wrong / stale operand (e.g. ``D, D`` instead of ``D, new_D``) is caught even when its term is
        dominated by other fields."""
        assert len(self.diff_args) == 1
        got = self.diff_args[0]
        assert len(got) == len(check_args) == 8
        for g, c in zip(got, check_args):
            if isinstance(c, float):
                assert type(g) is float and g.hex() == c.hex()
            else:
                assert g is c

    def outer_checks(self):
        """Outer-loop convergence checks: every check recorded before the first finalisation."""
        out = []
        for kind, args in self.events:
            if kind == "finalise":
                break
            out.append(args)
        return out


def _solve(policy):
    return solver_mod.solve_senior_debt(policy=policy, inputs=_inputs(), periods=_periods(),
                                        tax_cfads_fn=_tax_cfads_fn)


def _leaves(result):
    d = result.diagnostics
    rows = (result.senior_debt_opening_keur, result.senior_interest_keur, result.senior_principal_keur,
            result.senior_debt_service_keur, result.senior_debt_closing_keur)
    return (
        tuple(tuple(float(v).hex() for v in vec) for vec in rows),
        tuple(None if v is None else float(v).hex() for v in result.senior_dscr),
        float(result.debt_size_keur).hex(), result.binding_constraint,
        d.converged, d.iteration_count, d.termination_reason, d.is_authoritative,
        float(d.maximum_absolute_difference_keur).hex(), float(d.maximum_relative_difference).hex(),
        float(d.initial_debt_guess_keur).hex(), float(d.final_debt_size_keur).hex(),
    )


@pytest.mark.parametrize("alpha", [1.0, 0.7, 0.35])
def test_converged_dscr_reports_returning_iteration_value_bit_identically(monkeypatch, alpha):
    spy = _Spy(monkeypatch)
    result = _solve(_policy(alpha=alpha))
    diag = result.diagnostics
    assert diag.termination_reason == "CONVERGED" and diag.iteration_count >= 2
    checks = spy.outer_checks()
    assert len(checks) == diag.iteration_count - 1       # iteration 1 has no previous rows -> no check
    expected = spy.real_diff(*checks[-1])
    assert diag.maximum_absolute_difference_keur.hex() == expected.hex()
    assert math.isfinite(expected)
    assert spy.max_abs_calls == 1                         # lazy: only the returning iteration
    spy.assert_diff_operands_are(checks[-1])


def test_exhausted_budget_reports_last_iteration_value(monkeypatch):
    spy = _Spy(monkeypatch, force_not_converged=True)
    result = _solve(_policy(max_iter=5, alpha=0.5))
    diag = result.diagnostics
    assert diag.termination_reason == "MAX_ITERATIONS_REACHED" and diag.iteration_count == 5
    assert not diag.is_authoritative
    checks = spy.outer_checks()
    assert len(checks) == 4
    expected_last = spy.real_diff(*checks[-1])
    assert diag.maximum_absolute_difference_keur.hex() == expected_last.hex()
    # a stale (earlier-iteration) value would be a different float for this damped trajectory
    assert expected_last.hex() != spy.real_diff(*checks[-2]).hex()
    assert spy.max_abs_calls == 1
    spy.assert_diff_operands_are(checks[-1])


def test_single_iteration_budget_keeps_infinite_diagnostic(monkeypatch):
    spy = _Spy(monkeypatch, force_not_converged=True)
    diag = _solve(_policy(max_iter=1)).diagnostics
    assert diag.termination_reason == "MAX_ITERATIONS_REACHED" and diag.iteration_count == 1
    assert diag.maximum_absolute_difference_keur == float("inf")
    assert spy.outer_checks() == [] and spy.max_abs_calls == 0


@pytest.mark.parametrize("mode", [SeniorDebtSizingMode.DSCR_SCULPTED, SeniorDebtSizingMode.COMBINED_MINIMUM])
def test_full_result_identical_to_eager_diagnostic_reference(monkeypatch, mode):
    """Negative control against the pre-FINCO43 schedule: force the diagnostic to be (re)computed on EVERY check
    (the eager loop's work) and compare the complete solver result leaf-by-leaf."""
    lazy = _leaves(_solve(_policy(mode=mode)))
    real_conv = solver_mod._schedules_converged
    eager_calls = []

    def eager(*args):
        eager_calls.append(solver_mod._compute_max_abs_diff(*args[:8]))   # eager extra work, result unused
        return real_conv(*args)

    monkeypatch.setattr(solver_mod, "_schedules_converged", eager)
    eager_result = _leaves(_solve(_policy(mode=mode)))
    assert eager_calls, "eager reference did not run any convergence check"
    assert lazy == eager_result


def test_gearing_sculpted_converged_and_exhausted(monkeypatch):
    sculpted = dict(mode=SeniorDebtSizingMode.GEARING_CAP,
                    gearing_cap_repayment_method=GearingCapRepaymentMethod.DSCR_SCULPTED)
    spy = _Spy(monkeypatch)
    diag = _solve(_policy(**sculpted)).diagnostics
    checks = spy.outer_checks()
    assert checks, "gearing-sculpted loop ran no convergence check"
    assert diag.maximum_absolute_difference_keur.hex() == spy.real_diff(*checks[-1]).hex()
    assert spy.max_abs_calls == 1
    spy.assert_diff_operands_are(checks[-1])

    monkeypatch.undo()
    spy = _Spy(monkeypatch, force_not_converged=True)
    diag = _solve(_policy(max_iter=4, **sculpted)).diagnostics
    assert diag.termination_reason == "MAX_ITERATIONS_REACHED" and diag.iteration_count == 4
    checks = spy.outer_checks()
    assert len(checks) == 4                               # gearing-sculpted checks from iteration 1
    assert diag.maximum_absolute_difference_keur.hex() == spy.real_diff(*checks[-1]).hex()
    assert spy.max_abs_calls == 1
    spy.assert_diff_operands_are(checks[-1])
