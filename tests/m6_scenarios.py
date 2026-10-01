"""Deterministic senior-debt scenarios shared by the M-6 tests (no engine imports beyond senior_debt).

CFADS is a pure function of period interest (a simple cash-tax shield), so every scenario exercises
the interest -> tax -> CFADS handshake deterministically without the full project engine.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from financial_engine.senior_debt.inputs import (
    PeriodDebtServiceAvailability, PeriodDscrTarget, PeriodPrincipal, SeniorDebtInputs,
)
from financial_engine.senior_debt.policy import (
    DayCountConvention, SeniorDebtPolicy, SeniorDebtSizingMode,
)
from financial_engine.senior_debt.solver import solve_senior_debt

TARGET = 1.30
TAX_RATE = 0.25
TOL = 1e-4


def periods(n: int):
    out = []
    for i in range(n):
        year, half = 2030 + i // 2, i % 2
        start = date(year, 1 if half == 0 else 7, 1)
        end = date(year, 7, 1) if half == 0 else date(year + 1, 1, 1)
        out.append(SimpleNamespace(period_index=i + 1, is_operation=True,
                                   period_start=start, period_end=end))
    return tuple(out)


def policy(n, *, mode, rate=0.06, gearing=None, balloon=True, target=TARGET, method=None,
           start=1, maturity=None):
    kwargs = {}
    if method is not None:  # only pass the M-6 field when a scenario explicitly sets it
        kwargs["gearing_cap_repayment_method"] = method
    return SeniorDebtPolicy(
        policy_id="m6-test", policy_version="1", sizing_mode=mode, target_dscr=target,
        maximum_gearing=gearing, annual_fixed_rate=rate, periods_per_year=2,
        day_count_convention=DayCountConvention.ACT_365,
        repayment_start_period_index=start, maturity_period_index=maturity or n,
        convergence_tolerance_keur=TOL, convergence_relative_tolerance=1e-9,
        maximum_iterations=200, permit_terminal_balloon=balloon, damping_alpha=1.0, **kwargs)


def inputs(*, cost=100_000.0, guess=50_000.0, explicit=None, opening=0.0, dscr_targets=(),
           availability=()):
    return SeniorDebtInputs(
        eligible_project_cost_keur=cost, initial_debt_guess_keur=guess, period_rates=(),
        explicit_principal_schedule=explicit, opening_debt_balance_keur=opening,
        period_dscr_targets=tuple(PeriodDscrTarget(i, t) for i, t in dscr_targets),
        period_debt_service_availability=tuple(
            PeriodDebtServiceAvailability(i, a) for i, a in availability))


def make_tax_fn(pre_tax: dict[int, float], *, tax_rate: float = TAX_RATE, taxable: dict | None = None):
    """cash_tax = tax_rate * max(0, taxable_base - interest); cfads = pre_tax - cash_tax."""
    base = taxable if taxable is not None else {i: v * 0.8 for i, v in pre_tax.items()}
    calls: list[dict[int, float]] = []

    def fn(interest_by_period):
        calls.append(dict(interest_by_period))
        tax = {i: tax_rate * max(0.0, base[i] - interest_by_period.get(i, 0.0)) for i in pre_tax}
        cfads = {i: pre_tax[i] - tax[i] for i in pre_tax}
        return cfads, tax

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def flat(n: int, value: float = 6000.0) -> dict[int, float]:
    return {i: value for i in range(1, n + 1)}


def solve(n, *, mode, pre_tax, taxable=None, cost=100_000.0, guess=50_000.0, explicit=None,
          opening=0.0, dscr_targets=(), availability=(), **policy_kw):
    fn = make_tax_fn(pre_tax, taxable=taxable)
    result = solve_senior_debt(
        policy=policy(n, mode=mode, **policy_kw),
        inputs=inputs(cost=cost, guess=guess, explicit=explicit, opening=opening,
                      dscr_targets=dscr_targets, availability=availability),
        periods=periods(n), tax_cfads_fn=fn)
    return result, fn


def level_explicit(n: int, total: float):
    return tuple(PeriodPrincipal(i, total / n) for i in range(1, n + 1))


def summary(s):
    return {
        "termination": s.diagnostics.termination_reason,
        "authoritative": s.diagnostics.is_authoritative,
        "iterations": s.diagnostics.iteration_count,
        "binding": s.binding_constraint,
        "debt": repr(s.debt_size_keur),
        "interest_sum": repr(sum(s.senior_interest_keur)),
        "principal_sum": repr(sum(s.senior_principal_keur)),
        "closing_last": repr(s.senior_debt_closing_keur[-1]),
        "principal_first": repr(s.senior_principal_keur[0]),
        "principal_last": repr(s.senior_principal_keur[-1]),
        "interest_mid": repr(s.senior_interest_keur[len(s.senior_interest_keur) // 2]),
    }


BASELINE_CASES = {
    "gearing_default": dict(n=20, mode=SeniorDebtSizingMode.GEARING_CAP, gearing=0.6,
                            pre_tax=flat(20, 6000.0)),
    "gearing_default_short_rising": dict(
        n=6, mode=SeniorDebtSizingMode.GEARING_CAP, gearing=0.5, cost=40_000.0,
        pre_tax={i: 3000.0 + 500.0 * i for i in range(1, 7)}),
    "combined_gearing_binds": dict(n=20, mode=SeniorDebtSizingMode.COMBINED_MINIMUM, gearing=0.4,
                                   pre_tax=flat(20, 6000.0)),
    "combined_dscr_binds": dict(n=20, mode=SeniorDebtSizingMode.COMBINED_MINIMUM, gearing=0.95,
                                pre_tax=flat(20, 6000.0)),
    "dscr_sculpted": dict(n=20, mode=SeniorDebtSizingMode.DSCR_SCULPTED, pre_tax=flat(20, 6000.0)),
    "explicit_level": dict(n=10, mode=SeniorDebtSizingMode.EXPLICIT_SCHEDULE, opening=30_000.0,
                           explicit=level_explicit(10, 30_000.0), pre_tax=flat(10, 6000.0)),
}


def run_baseline_case(name: str):
    case = dict(BASELINE_CASES[name])
    n = case.pop("n")
    result, _ = solve(n, **case)
    return summary(result)
