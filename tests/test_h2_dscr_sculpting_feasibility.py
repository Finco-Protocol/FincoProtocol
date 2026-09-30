"""Opus H-2 — DSCR sculpting feasibility and false-CONVERGED regression.

Backward debt sizing used to implicitly capitalise interest when allowed debt
service was below interest, while the forward roll floored principal at zero and
paid interest in full.  The sized debt therefore could not be serviced, yet the
solver reported CONVERGED.  These tests pin the corrected contract:

* a sculpted result is authoritative only if every repayment period's debt
  service fits inside CFADS / target_dscr (interest and principal fully funded);
* backward sizing and forward roll use the same no-capitalisation treatment;
* an infeasible structure fails closed as DSCR_SCULPTING_INFEASIBLE.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import financial_engine.senior_debt.solver as solver_mod
from financial_engine.senior_debt.inputs import SeniorDebtInputs
from financial_engine.senior_debt.interest import period_day_fraction
from financial_engine.senior_debt.policy import (
    DayCountConvention,
    SeniorDebtPolicy,
    SeniorDebtSizingMode,
)
from financial_engine.senior_debt.sculpting import PeriodDebtRow
from financial_engine.senior_debt.solver import (
    DSCR_SCULPTING_INFEASIBLE,
    _dscr_sculpting_infeasibility,
    _forward_roll,
    solve_senior_debt,
)

TARGET = 1.30
RATE = 0.06
TOL = 1e-4
LEGACY_INFEASIBLE_DC_DEBT_KEUR = 80436.496435994  # DC reference before the H-2 fix


def _periods(n: int):
    out = []
    for i in range(n):
        year, half = 2030 + i // 2, i % 2
        start = date(year, 1 if half == 0 else 7, 1)
        end = date(year, 7, 1) if half == 0 else date(year + 1, 1, 1)
        out.append(SimpleNamespace(
            period_index=i + 1, is_operation=True, period_start=start, period_end=end,
        ))
    return tuple(out)


def _policy(n: int, *, mode=SeniorDebtSizingMode.DSCR_SCULPTED, balloon=True,
            gearing=None) -> SeniorDebtPolicy:
    return SeniorDebtPolicy(
        policy_id="h2-test", policy_version="1", sizing_mode=mode, target_dscr=TARGET,
        maximum_gearing=gearing, annual_fixed_rate=RATE, periods_per_year=2,
        day_count_convention=DayCountConvention.ACT_365,
        repayment_start_period_index=1, maturity_period_index=n,
        convergence_tolerance_keur=TOL, convergence_relative_tolerance=1e-9,
        maximum_iterations=200, permit_terminal_balloon=balloon, damping_alpha=1.0,
    )


def _inputs(guess: float = 100_000.0, cost: float = 200_000.0) -> SeniorDebtInputs:
    return SeniorDebtInputs(
        eligible_project_cost_keur=cost, initial_debt_guess_keur=guess,
        period_rates=(), explicit_principal_schedule=None,
    )


def _solve(cfads: dict[int, float], n: int, **policy_kw):
    """CFADS is independent of interest (no tax feedback) so runs are deterministic."""
    def tax_cfads_fn(_interest):
        return dict(cfads), {idx: 0.0 for idx in cfads}

    return solve_senior_debt(
        policy=_policy(n, **policy_kw), inputs=_inputs(), periods=_periods(n),
        tax_cfads_fn=tax_cfads_fn,
    )


def _ramp_up_cfads(n: int = 24, weak: float = 2000.0, strong: float = 6500.0):
    return {i: (weak if i <= 2 else strong) for i in range(1, n + 1)}


def _legacy_backward_capacity(cfads_by, rate_map, period_start_end, period_indices,
                              policy, dscr_map=None, availability_map=None):
    """The pre-H-2 induction: implicitly capitalises interest (opening < closing)."""
    closing = 0.0
    for idx in reversed(period_indices):
        ds = max(0.0, cfads_by.get(idx, 0.0) / policy.target_dscr)
        start, end = period_start_end[idx]
        f = rate_map.get(idx, 0.0) * period_day_fraction(start, end, policy.day_count_convention)
        closing = max(0.0, (closing + ds) / (1.0 + f))
    return closing


def _assert_serviceable(sched, cfads, tol=1e-6):
    """Interest and principal are fully funded inside CFADS / target."""
    for i, idx in enumerate(sched.period_indices):
        allowed = max(0.0, cfads[idx] / TARGET)
        assert sched.senior_debt_service_keur[i] <= allowed + tol, idx
        assert sched.senior_interest_keur[i] <= allowed + tol, idx
        assert sched.senior_principal_keur[i] >= 0.0, idx
        assert cfads[idx] - sched.senior_debt_service_keur[i] >= -tol, idx  # no hidden funding
        if sched.senior_debt_service_keur[i] > 0.0:
            assert cfads[idx] / sched.senior_debt_service_keur[i] >= TARGET - 1e-9, idx


def _assert_roll_forward_identity(sched):
    """opening + draws(0) - principal = closing; no capitalisation; balances chain."""
    for i in range(len(sched.period_indices)):
        assert sched.senior_debt_opening_keur[i] - sched.senior_principal_keur[i] == pytest.approx(
            sched.senior_debt_closing_keur[i], abs=1e-6)
        assert sched.senior_debt_closing_keur[i] <= sched.senior_debt_opening_keur[i] + 1e-9
        if i:
            assert sched.senior_debt_opening_keur[i] == pytest.approx(
                sched.senior_debt_closing_keur[i - 1], abs=1e-6)


# ---------------------------------------------------------------------------
# 1. Existing Data Center reproduction
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dc():
    from app.project_factories import create_generic_data_center_reference
    from app.services.production_financial_authority import run_clean_production

    run = run_clean_production(
        create_generic_data_center_reference(), "Base", project_type="Data Center")
    model = run.g2c_result.financing_result.project_model_result
    return model.senior_debt, model.post_senior_cash


class TestDataCenterReproduction:
    def test_false_converged_state_is_gone(self, dc):
        senior, post = dc
        diag = senior.diagnostics
        assert diag["termination_reason"] == "CONVERGED" and diag["is_authoritative"]
        dscrs = [d for d, ds in zip(senior.base_dscr, senior.senior_debt_service_keur)
                 if ds > 0.0 and d is not None]
        assert min(dscrs) >= TARGET - 1e-6, f"achieved DSCR {min(dscrs)} below target"
        assert min(post.cash_after_senior_before_reserves_keur) >= -1e-6
        assert senior.debt_size_keur < LEGACY_INFEASIBLE_DC_DEBT_KEUR

    def test_debt_service_is_fully_funded_and_rolls_forward(self, dc):
        senior, post = dc
        cash = dict(zip(post.period_indices, post.cash_after_senior_before_reserves_keur))
        for i, idx in enumerate(senior.period_indices):
            assert senior.senior_interest_keur[i] <= senior.senior_debt_service_keur[i] + 1e-9
            assert cash[idx] >= -1e-6, idx
            assert senior.senior_debt_opening_keur[i] - senior.senior_principal_keur[i] == pytest.approx(
                senior.senior_debt_closing_keur[i], abs=1e-6)
        assert senior.senior_debt_closing_keur[-1] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 2. CFADS below scheduled interest
# ---------------------------------------------------------------------------

class TestCfadsBelowInterest:
    def test_ramp_up_is_sized_to_what_it_can_service(self):
        cfads = _ramp_up_cfads()
        sched = _solve(cfads, 24)
        assert sched.diagnostics.is_authoritative
        _assert_serviceable(sched, cfads)
        _assert_roll_forward_identity(sched)

        # The legacy induction would have sized more debt than the weak first
        # periods can carry.
        rate_map = {i: RATE for i in cfads}
        pse = {p.period_index: (p.period_start, p.period_end) for p in _periods(24)}
        legacy = _legacy_backward_capacity(
            cfads, rate_map, pse, tuple(range(1, 25)), _policy(24))
        assert sched.debt_size_keur < legacy - 1.0

    def test_zero_cfads_period_carries_no_debt_and_is_not_authoritative(self):
        cfads = _ramp_up_cfads()
        cfads[1] = 0.0
        sched = _solve(cfads, 24)
        assert not sched.diagnostics.is_authoritative
        assert sched.diagnostics.termination_reason == "NO_DEBT_CAPACITY"
        assert sched.debt_size_keur == 0.0

    def test_backward_capacity_never_capitalises_interest(self):
        cfads = _ramp_up_cfads()
        n = 24
        pse = {p.period_index: (p.period_start, p.period_end) for p in _periods(n)}
        rate_map = {i: RATE for i in cfads}
        capacity = solver_mod._backward_dscr_capacity(
            cfads, rate_map, pse, tuple(range(1, n + 1)), _policy(n))
        f1 = RATE * period_day_fraction(*pse[1], DayCountConvention.ACT_365)
        # opening balance must not exceed the balance whose interest fits period-1 DS
        assert capacity <= cfads[1] / TARGET / f1 + 1e-6


# ---------------------------------------------------------------------------
# 3. Genuinely feasible sculpted cases stay successful
# ---------------------------------------------------------------------------

class TestFeasibleCasesRemainSuccessful:
    def test_flat_cfads_sculpts_to_target_and_repays_fully(self):
        n = 20
        cfads = {i: 5000.0 for i in range(1, n + 1)}
        sched = _solve(cfads, n)
        assert sched.diagnostics.termination_reason == "CONVERGED"
        assert sched.diagnostics.is_authoritative
        _assert_serviceable(sched, cfads)
        _assert_roll_forward_identity(sched)
        assert sched.senior_debt_closing_keur[-1] == pytest.approx(0.0, abs=1e-3)
        for d in sched.senior_dscr:
            assert d == pytest.approx(TARGET, abs=1e-6)

    def test_combined_minimum_with_binding_gearing_stays_successful(self):
        n = 20
        cfads = {i: 5000.0 for i in range(1, n + 1)}
        sched = _solve(cfads, n, mode=SeniorDebtSizingMode.COMBINED_MINIMUM, gearing=0.10)
        assert sched.diagnostics.is_authoritative
        assert sched.binding_constraint == "GEARING"
        _assert_serviceable(sched, cfads)


# ---------------------------------------------------------------------------
# 4. Boundary / tolerance behaviour of the feasibility guard
# ---------------------------------------------------------------------------

def _row(idx: int, ds: float, interest: float = 100.0, closing: float = 0.0) -> PeriodDebtRow:
    return PeriodDebtRow(period_index=idx, opening_keur=closing + (ds - interest),
                         interest_keur=interest, principal_keur=ds - interest,
                         debt_service_keur=ds, closing_keur=closing, dscr=None)


class TestFeasibilityBoundary:
    ALLOWED = 1000.0
    CFADS = {1: ALLOWED * TARGET}

    def _check(self, ds: float):
        return _dscr_sculpting_infeasibility(
            (_row(1, ds),), self.CFADS, _policy(1), None, None)

    def test_exactly_at_allowed_is_feasible(self):
        assert self._check(self.ALLOWED) is None

    def test_within_absolute_tolerance_is_feasible(self):
        assert self._check(self.ALLOWED + 0.5 * TOL) is None

    def test_beyond_tolerance_is_infeasible(self):
        assert self._check(self.ALLOWED + 10.0) is not None

    def test_terminal_balance_is_infeasible_only_without_balloon(self):
        row = _row(1, self.ALLOWED, closing=50.0)
        with_balloon = _dscr_sculpting_infeasibility(
            (row,), self.CFADS, _policy(1, balloon=True), None, None)
        without = _dscr_sculpting_infeasibility(
            (row,), self.CFADS, _policy(1, balloon=False), None, None)
        assert with_balloon is None and without is not None


# ---------------------------------------------------------------------------
# 5. No hidden negative funding: the guard catches the legacy false success
# ---------------------------------------------------------------------------

class TestNoHiddenFundingFailsClosed:
    def test_legacy_sizing_schedule_is_flagged_infeasible(self):
        cfads = _ramp_up_cfads()
        n = 24
        idxs = tuple(range(1, n + 1))
        pse = {p.period_index: (p.period_start, p.period_end) for p in _periods(n)}
        rate_map = {i: RATE for i in idxs}
        legacy_d = _legacy_backward_capacity(cfads, rate_map, pse, idxs, _policy(n))
        rows = _forward_roll(legacy_d, idxs, rate_map, pse, cfads, _policy(n), "dscr_sculpted")
        assert any(cfads[r.period_index] - r.debt_service_keur < 0 for r in rows)  # deficit exists
        assert _dscr_sculpting_infeasibility(rows, cfads, _policy(n), None, None) is not None

    def test_solver_reports_typed_infeasible_when_sizing_is_inconsistent(self, monkeypatch):
        monkeypatch.setattr(solver_mod, "_backward_dscr_capacity", _legacy_backward_capacity)
        cfads = _ramp_up_cfads()
        sched = _solve(cfads, 24)
        diag = sched.diagnostics
        assert diag.termination_reason == DSCR_SCULPTING_INFEASIBLE
        assert diag.is_authoritative is False and diag.converged is False

    def test_data_center_run_fails_closed_when_sizing_is_inconsistent(self, monkeypatch):
        """Re-inject the legacy sizing: the production run must reject, not report CONVERGED."""
        from app.project_factories import create_generic_data_center_reference
        from app.services.production_financial_authority import run_clean_production

        monkeypatch.setattr(solver_mod, "_backward_dscr_capacity", _legacy_backward_capacity)
        with pytest.raises(Exception) as excinfo:
            run_clean_production(
                create_generic_data_center_reference(), "Base", project_type="Data Center")
        assert DSCR_SCULPTING_INFEASIBLE in str(excinfo.value) or (
            "non-authoritative" in str(excinfo.value).lower()
            or "SeniorDebtNonConvergenceError" in type(excinfo.value).__name__
            or "Unavailable" in type(excinfo.value).__name__)


# ---------------------------------------------------------------------------
# 6. Debt roll-forward identity across scenarios
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("weak", [0.0001, 500.0, 2000.0, 4000.0, 6500.0])
def test_authoritative_results_always_serviceable_and_identity_holds(weak):
    cfads = _ramp_up_cfads(weak=weak)
    sched = _solve(cfads, 24)
    if not sched.diagnostics.is_authoritative:
        assert sched.diagnostics.termination_reason in {
            "NO_DEBT_CAPACITY", DSCR_SCULPTING_INFEASIBLE}
        return
    _assert_serviceable(sched, cfads)
    _assert_roll_forward_identity(sched)
