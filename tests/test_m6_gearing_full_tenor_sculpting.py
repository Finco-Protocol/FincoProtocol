"""M-6 — optional full-tenor DSCR sculpting for GEARING_CAP debt.

Canonical default is unchanged (GEARING_CAP -> LEVEL_PRINCIPAL). The new behaviour is an explicit,
typed opt-in: GEARING_CAP sizing + gearing_cap_repayment_method=DSCR_SCULPTED keeps the debt size at
eligible_project_cost x maximum_gearing and sculpts it over the tenor; it never resizes to DSCR capacity
and it fails closed when the CFADS cannot repay the balance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from financial_engine.senior_debt.interest import period_day_fraction
from financial_engine.senior_debt.policy import (
    GearingCapRepaymentMethod as Method,
    SeniorDebtPolicy,
    SeniorDebtSizingMode as Mode,
)
from financial_engine.senior_debt.solver import DSCR_SCULPTING_INFEASIBLE
import m6_scenarios as sc

GEAR, DSCR_MODE = Mode.GEARING_CAP, Method.DSCR_SCULPTED
BASELINE = json.loads((Path(__file__).parent / "m6_baseline_pre_change.json").read_text())


def sculpted(n=20, *, gearing=0.3, pre_tax=None, **kw):
    return sc.solve(n, mode=GEAR, gearing=gearing, pre_tax=pre_tax or sc.flat(n, 6000.0),
                    method=DSCR_MODE, **kw)


def allowed(cfads, target=sc.TARGET, availability=1.0):
    return max(0.0, cfads / target) * availability


# ── A. default is unchanged ─────────────────────────────────────────────────────────────
def test_default_repayment_method_is_level_principal():
    p = sc.policy(20, mode=GEAR, gearing=0.5)
    assert p.gearing_cap_repayment_method is Method.LEVEL_PRINCIPAL
    assert sc.policy(20, mode=GEAR, gearing=0.5) == p


def test_default_gearing_repayment_is_straight_line_level_principal():
    result, _ = sc.solve(20, mode=GEAR, gearing=0.6, pre_tax=sc.flat(20, 6000.0))
    assert result.diagnostics.termination_reason == "CONVERGED"
    principal = result.senior_principal_keur
    assert max(principal) == pytest.approx(min(principal), rel=1e-12)
    assert principal[0] == pytest.approx(60_000.0 / 20)


# ── B / L / M / N / O. nothing else changed (values captured from the pre-change solver) ─────────
@pytest.mark.parametrize("case", sorted(sc.BASELINE_CASES))
def test_pre_change_outputs_are_identical(case):
    now, before = sc.run_baseline_case(case), BASELINE[case]
    assert {k: v for k, v in now.items() if not isinstance(v, str) or k in
            ("termination", "binding")} == {k: v for k, v in before.items()
                                            if not isinstance(v, str) or k in ("termination", "binding")}
    for key in ("debt", "interest_sum", "principal_sum", "closing_last", "principal_first",
                "principal_last", "interest_mid"):
        assert float(now[key]) == pytest.approx(float(before[key]), rel=1e-12, abs=1e-9), key


def test_combined_minimum_is_still_min_of_dscr_capacity_and_gearing_cap():
    dscr, _ = sc.solve(20, mode=Mode.DSCR_SCULPTED, pre_tax=sc.flat(20))
    gearing_binds, _ = sc.solve(20, mode=Mode.COMBINED_MINIMUM, gearing=0.4, pre_tax=sc.flat(20))
    dscr_binds, _ = sc.solve(20, mode=Mode.COMBINED_MINIMUM, gearing=0.95, pre_tax=sc.flat(20))
    assert gearing_binds.debt_size_keur == pytest.approx(40_000.0)
    assert gearing_binds.binding_constraint == "GEARING"
    assert dscr_binds.debt_size_keur == pytest.approx(dscr.debt_size_keur)
    assert dscr_binds.binding_constraint == "DSCR"


def test_combined_minimum_ignores_nothing_and_rejects_the_gearing_only_option():
    result, _ = sc.solve(20, mode=Mode.COMBINED_MINIMUM, gearing=0.4, pre_tax=sc.flat(20),
                         method=DSCR_MODE)
    assert result.diagnostics.termination_reason == "INVALID_INPUT"
    assert result.diagnostics.is_authoritative is False


@pytest.mark.parametrize("mode", [Mode.DSCR_SCULPTED, Mode.EXPLICIT_SCHEDULE])
def test_option_is_invalid_with_every_other_sizing_mode(mode):
    kw = dict(explicit=sc.level_explicit(10, 30_000.0), opening=30_000.0) \
        if mode is Mode.EXPLICIT_SCHEDULE else {}
    result, _ = sc.solve(10, mode=mode, pre_tax=sc.flat(10), method=DSCR_MODE, **kw)
    assert result.diagnostics.termination_reason == "INVALID_INPUT"


def test_method_must_be_the_typed_enum():
    result, _ = sc.solve(10, mode=GEAR, gearing=0.3, pre_tax=sc.flat(10), method="DSCR_SCULPTED")
    assert result.diagnostics.termination_reason == "INVALID_INPUT"


# ── C / J. gearing-sized debt is preserved, never resized to DSCR capacity ────────────────────
@pytest.mark.parametrize("gearing", [0.1, 0.3, 0.45, 0.9])
def test_initial_debt_is_cost_times_gearing(gearing):
    result, _ = sculpted(gearing=gearing, balloon=True)
    assert result.debt_size_keur == pytest.approx(100_000.0 * gearing, rel=1e-12)
    assert result.senior_debt_opening_keur[0] == pytest.approx(100_000.0 * gearing, rel=1e-12)
    assert result.binding_constraint == "GEARING"


def test_solver_never_resizes_down_to_dscr_capacity():
    dscr, _ = sc.solve(20, mode=Mode.DSCR_SCULPTED, pre_tax=sc.flat(20))
    result, _ = sculpted(gearing=0.9, balloon=False)        # 90 000 > DSCR capacity (~58 000)
    assert dscr.debt_size_keur < 90_000.0
    assert result.debt_size_keur == pytest.approx(90_000.0)  # not silently reduced
    assert result.senior_debt_opening_keur[0] == pytest.approx(90_000.0)
    assert result.diagnostics.termination_reason == DSCR_SCULPTING_INFEASIBLE


# ── D / E / F / G / H. schedule properties ──────────────────────────────────────────────────
def _utilisation(result, cfads, targets=None, availability=None):
    """debt_service / DSCR-allowed per period, for periods that repay principal."""
    tmap, amap = dict(targets or ()), dict(availability or ())
    out = {}
    for i, idx in enumerate(result.period_indices):
        limit = allowed(cfads[idx], tmap.get(idx, sc.TARGET), amap.get(idx, 1.0))
        if result.senior_principal_keur[i] > 1e-9 and result.senior_debt_closing_keur[i] > 1e-9:
            out[idx] = result.senior_debt_service_keur[i] / limit
    return out


def test_repayment_uses_dscr_target_and_debt_service_availability_per_period():
    n = 20
    targets = ((1, 1.6), (2, 1.6), (9, 1.45))
    availability = ((3, 0.8), (4, 0.8), (9, 0.9))
    result, fn = sculpted(n, gearing=0.2, dscr_targets=targets, availability=availability)
    assert result.diagnostics.termination_reason == "CONVERGED"
    cfads, _ = fn(dict(zip(result.period_indices, result.senior_interest_keur)))
    k = _utilisation(result, cfads, targets, availability)
    assert len(k) >= 10
    ratios = list(k.values())
    assert max(ratios) - min(ratios) < 1e-6          # ONE uniform fraction of the allowed service
    assert 0.0 < ratios[0] < 1.0                     # debt below DSCR capacity is spread, not swept
    tmap, amap = dict(targets), dict(availability)
    for i, idx in enumerate(result.period_indices):  # per-period target and availability are honoured
        limit = allowed(cfads[idx], tmap.get(idx, sc.TARGET), amap.get(idx, 1.0))
        assert result.senior_debt_service_keur[i] <= limit + 1e-6
        if result.senior_debt_service_keur[i] > 0:
            assert result.senior_dscr[i] >= tmap.get(idx, sc.TARGET) - 1e-9
    # period 1 has full availability, so realised DSCR = target / k there (see the dedicated
    # availability < 1 relationship test below for the general formula)
    assert result.senior_dscr[0] == pytest.approx(1.6 / ratios[0], rel=1e-6)


def test_realised_dscr_is_target_over_availability_times_k_where_the_budget_is_consumed():
    """Wording-truth test: with availability < 1 and k < 1, a period that consumes its scaled budget
    has debt_service = CFADS / target * availability * k, hence CFADS / debt_service =
    target / (availability * k). A period clipped by the remaining balance is excluded."""
    targets, availability = ((5, 1.5), (6, 1.5)), ((3, 0.8), (4, 0.8), (5, 0.7), (6, 0.9))
    result, fn = sculpted(20, gearing=0.2, dscr_targets=targets, availability=availability)
    assert result.diagnostics.termination_reason == "CONVERGED"
    cfads, _ = fn(dict(zip(result.period_indices, result.senior_interest_keur)))
    tmap, amap = dict(targets), dict(availability)
    k = max(_utilisation(result, cfads, targets, availability).values())  # utilisation of the allowed budget
    assert 0.0 < k < 1.0 and any(a < 1.0 for a in amap.values())
    checked = 0
    for i, idx in enumerate(result.period_indices):
        if not (result.senior_principal_keur[i] > 1e-9 and result.senior_debt_closing_keur[i] > 1e-9):
            continue                                   # clipped / terminal periods are not asserted
        target, avail = tmap.get(idx, sc.TARGET), amap.get(idx, 1.0)
        assert result.senior_debt_service_keur[i] == pytest.approx(
            cfads[idx] / target * avail * k, rel=1e-6)
        assert cfads[idx] / result.senior_debt_service_keur[i] == pytest.approx(
            target / (avail * k), rel=1e-6)
        checked += 1
    assert checked >= 10
    final = result.senior_debt_service_keur[-1]        # the clipped final period realises MORE than budget
    assert final <= cfads[20] / sc.TARGET * k + 1e-6


def test_gearing_at_dscr_capacity_reproduces_the_dscr_sculpted_schedule():
    dscr, _ = sc.solve(20, mode=Mode.DSCR_SCULPTED, pre_tax=sc.flat(20))
    gearing = dscr.debt_size_keur / 100_000.0
    result, _ = sculpted(20, gearing=gearing, balloon=False)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert result.senior_principal_keur == pytest.approx(dscr.senior_principal_keur, rel=1e-6, abs=1e-3)


@pytest.mark.parametrize("n,gearing,cfads", [
    (20, 0.30, sc.flat(20)),
    (2, 0.05, sc.flat(2)),                                                        # short tenor
    (16, 0.25, {i: 4000.0 + 400.0 * i for i in range(1, 17)}),                      # uneven
    (16, 0.25, {i: 9000.0 - 300.0 * i for i in range(1, 17)}),                      # declining
])
def test_no_negative_principal_or_balance_and_rolling_interest(n, gearing, cfads):
    result, _ = sculpted(n, gearing=gearing, pre_tax=cfads)
    assert result.diagnostics.termination_reason == "CONVERGED", result.diagnostics
    starts = {p.period_index: (p.period_start, p.period_end) for p in sc.periods(n)}
    for i, idx in enumerate(result.period_indices):
        assert result.senior_principal_keur[i] >= 0.0
        assert result.senior_debt_closing_keur[i] >= 0.0
        opening = result.senior_debt_opening_keur[i]
        frac = period_day_fraction(*starts[idx], sc.policy(n, mode=GEAR, gearing=gearing).day_count_convention)
        assert result.senior_interest_keur[i] == pytest.approx(opening * 0.06 * frac, rel=1e-12)
        assert result.senior_debt_closing_keur[i] == pytest.approx(
            opening - result.senior_principal_keur[i], abs=1e-9)
        if i:
            assert opening == pytest.approx(result.senior_debt_closing_keur[i - 1], abs=1e-9)


def test_feasible_case_amortises_through_the_contractual_tenor():
    result, _ = sculpted(20, gearing=0.3)
    closing = result.senior_debt_closing_keur
    assert closing[-1] == 0.0                                     # repaid exactly at maturity
    assert closing[-2] > 0.0 and closing[9] > 1_000.0             # NOT retired early
    assert all(p > 0.0 for p in result.senior_principal_keur)     # every period repays
    assert sum(result.senior_principal_keur) == pytest.approx(30_000.0, rel=1e-9)
    assert all(d >= sc.TARGET - 1e-9 for d in result.senior_dscr if d is not None)


def test_zero_rate_is_valid_and_repays_in_full():
    result, _ = sculpted(10, gearing=0.3, rate=0.0)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert sum(result.senior_interest_keur) == 0.0
    assert result.senior_debt_closing_keur[-1] == pytest.approx(0.0, abs=1e-6)


def test_final_period_repayment_clears_the_balance_exactly():
    result, _ = sculpted(6, gearing=0.15)
    assert result.senior_debt_closing_keur[-1] == 0.0
    assert result.senior_principal_keur[-1] > 0.0
    assert result.senior_debt_closing_keur[-2] > 0.0


# ── I. infeasibility fails closed ───────────────────────────────────────────────────────────────
def test_infeasible_balance_without_balloon_is_not_authoritative():
    result, _ = sculpted(20, gearing=0.9, balloon=False)
    d = result.diagnostics
    assert (d.termination_reason, d.converged, d.is_authoritative) == (
        DSCR_SCULPTING_INFEASIBLE, False, False)
    assert min(result.senior_principal_keur) >= 0.0 and min(result.senior_debt_closing_keur) >= 0.0
    assert result.senior_debt_closing_keur[-1] > 1_000.0          # the unpaid debt is visible, not hidden


def test_weak_early_cfads_cannot_fund_interest_so_no_capitalisation_even_with_balloon():
    weak_early = {i: (1500.0 if i <= 4 else 9000.0) for i in range(1, 21)}
    result, _ = sculpted(20, gearing=0.5, pre_tax=weak_early, balloon=True)
    assert result.diagnostics.termination_reason == DSCR_SCULPTING_INFEASIBLE
    assert result.diagnostics.is_authoritative is False
    assert all(result.senior_debt_closing_keur[i] <= result.senior_debt_opening_keur[i] + 1e-9
               for i in range(20))                                # interest never capitalised


def test_infeasible_maturity_case_short_tenor_high_gearing():
    result, _ = sculpted(4, gearing=0.9, balloon=False)
    assert result.diagnostics.termination_reason == DSCR_SCULPTING_INFEASIBLE
    assert result.diagnostics.is_authoritative is False


def test_permitted_balloon_keeps_its_existing_authoritative_semantics():
    """permit_terminal_balloon=True is an explicit policy decision: a residual is a disclosed
    balloon (balance visible in the schedule), exactly as for the other sculpted modes."""
    result, _ = sculpted(20, gearing=0.9, balloon=True)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert result.senior_debt_closing_keur[-1] > 1_000.0
    assert result.debt_size_keur == pytest.approx(90_000.0)


# ── K. tax / CFADS / returned-interest handshake ────────────────────────────────────────────────
def test_returned_interest_is_the_interest_used_by_the_final_tax_cfads_call():
    result, fn = sculpted(20, gearing=0.3)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert fn.calls[-1] == dict(zip(result.period_indices, result.senior_interest_keur))
    cfads, _ = fn(fn.calls[-1])
    k = _utilisation(result, cfads)                               # schedule consistent with final CFADS
    assert len(k) > 10 and max(k.values()) - min(k.values()) < 1e-6 and 0.0 < min(k.values()) < 1.0


def test_interest_really_feeds_cash_tax_and_changes_cfads():
    r1, fn1 = sc.solve(20, mode=GEAR, gearing=0.3, pre_tax=sc.flat(20), method=DSCR_MODE)
    cfads_low, _ = fn1({i: 0.0 for i in range(1, 21)})
    cfads_actual, _ = fn1(dict(zip(r1.period_indices, r1.senior_interest_keur)))
    assert cfads_actual[1] > cfads_low[1]                         # interest shield raises CFADS


def test_solve_is_deterministic():
    a, fa = sculpted(20, gearing=0.3)
    b, fb = sculpted(20, gearing=0.3)
    assert sc.summary(a) == sc.summary(b) and len(fa.calls) == len(fb.calls)
    assert a.senior_principal_keur == b.senior_principal_keur


# ── provenance ──────────────────────────────────────────────────────────────────────────────────
def _fingerprint(policy_obj, monkeypatch):
    from types import SimpleNamespace
    import financial_engine.provenance as prov
    monkeypatch.setattr(prov, "compute_tax_cfads_fingerprint", lambda _i: "phase2b-stub")
    inputs = SimpleNamespace(operating=None, tax=None, debt_sizing_case=None, shareholder_loan=None,
                             senior_debt_policy=policy_obj, senior_debt_inputs=sc.inputs())
    return prov.compute_senior_debt_fingerprint(inputs)


def test_default_fingerprint_is_unchanged_and_opt_in_fingerprints_differently(monkeypatch):
    import dataclasses
    from types import SimpleNamespace
    default = sc.policy(10, mode=GEAR, gearing=0.3)
    pre_change = SimpleNamespace(**{f.name: getattr(default, f.name)
                                    for f in dataclasses.fields(default)
                                    if f.name != "gearing_cap_repayment_method"})  # the old contract
    opted = dataclasses.replace(default, gearing_cap_repayment_method=DSCR_MODE)
    assert _fingerprint(default, monkeypatch) == _fingerprint(pre_change, monkeypatch)
    assert _fingerprint(opted, monkeypatch) != _fingerprint(default, monkeypatch)


# ── latent feasibility protection (documented scope) ────────────────────────────────────────────
def test_default_level_principal_terminal_balance_is_repaid_by_construction():
    result, _ = sc.solve(20, mode=GEAR, gearing=0.6, pre_tax=sc.flat(20), balloon=False)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert result.senior_debt_closing_keur[-1] == pytest.approx(0.0, abs=1e-6)


def test_characterisation_default_gearing_does_not_check_cash_service_today():
    """CHARACTERISATION, not endorsement. The default GEARING_CAP / EXPLICIT paths never sized to a
    DSCR, so a schedule whose debt service exceeds CFADS is still reported CONVERGED. Adding a
    cash-service guard would change the authority class of such historical results, so it is left
    as a documented follow-up (see docs/engine/SENIOR_DEBT_GEARING_SCULPTING.md) rather than
    widened into this PR. The NEW opt-in mode above is fully guarded."""
    thin = sc.flat(20, 2500.0)
    result, _ = sc.solve(20, mode=GEAR, gearing=0.6, pre_tax=thin)
    assert result.diagnostics.termination_reason == "CONVERGED"
    assert min(d for d in result.senior_dscr if d) < 1.0
    explicit, _ = sc.solve(10, mode=Mode.EXPLICIT_SCHEDULE, opening=60_000.0,
                           explicit=sc.level_explicit(10, 60_000.0), pre_tax=sc.flat(10, 2500.0))
    assert explicit.diagnostics.termination_reason == "CONVERGED"
