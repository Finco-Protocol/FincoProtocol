"""V9-P2a / OD-R Correction E - final financial evidence contract (real engine evaluations + targeted fault injection).

Invariant under test: an OD-R result is returned only after every final check REQUIRED by the returned financing state has been
performed on that exact state and passed. Applicability comes from the returned state (SHL liability, financing structure),
never from the presence of evidence. Missing, duplicate, contradictory, unbound, stale (other-state) or repeated evidence fails
closed; economic breaches keep ``SHL_MATURITY_RESIDUAL_FAILS_CLOSED``; upstream numerical/convergence errors keep precedence.

Injected faults only remove, duplicate or misbind the real per-pass evidence of real evaluations (decision-path controls).
The canonical (deployed default) path never consults this contract and is shown unchanged under the same injections.
"""
from __future__ import annotations

import dataclasses as dc
import threading

import pytest

from app.services import production_financial_authority as pfa
from financial_engine.shl import maturity_authority as ma
from tools import v9p2a_odr_acceptance as acc

CODE = "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"
FEASIBLE = "reference-wind"      # construction IDC + DSRA (one superseded DSRA evaluation) + SHL cash sweep
NO_SHL = "quarterly-solar"       # equity-only release-closed quarterly candidate: no SHL liability
NO_CONSTRUCTION = "W25-noCF"     # top-level G2A (construction financing not applied) + SHL
BREACH = ma.ShlMaturityShortfall(closing_keur=321.5, period_index=41, tolerance_keur=1e-7)


@pytest.fixture(scope="module")
def entries():
    return acc.cases()


@pytest.fixture(autouse=True)
def _clean():
    pfa._POLICY_RUN_CACHE.clear()
    yield
    pfa._POLICY_RUN_CACHE.clear()
    assert ma.current_attempt() is None


def _odr(entries, name):
    return acc.run_case(name, "odr", entries)


def _reject(entries, name, mode="odr"):
    with pytest.raises(Exception) as info:
        acc.run_case(name, mode, entries)
    assert not pfa._POLICY_RUN_CACHE, "a rejected evaluation must never be memoised"
    return str(info.value)


def _wrap_absorb(monkeypatch, transform):
    """``transform(self, evidence, final, role, state, original)``; returns call log."""
    original = ma.OdrAttempt.absorb_g2a
    log = []

    def absorb(self, evidence, *, final, role, state=None):
        log.append((role, final))
        return transform(self, evidence, final, role, state, original)

    monkeypatch.setattr(ma.OdrAttempt, "absorb_g2a", absorb)
    return log


@pytest.fixture(scope="module")
def feasible_pair(entries):
    pfa._POLICY_RUN_CACHE.clear()
    canonical = acc.run_case(FEASIBLE, "canonical", entries)
    pfa._POLICY_RUN_CACHE.clear()
    odr = acc.run_case(FEASIBLE, "odr", entries)
    pfa._POLICY_RUN_CACHE.clear()
    return canonical, odr


# ------------------------------------------------------------------------------------------------ baseline / applicability

def test_feasible_state_has_shl_liability_and_complete_bound_evidence(feasible_pair):
    canonical, odr = feasible_pair
    assert canonical.g2c_result.financing_result.derived_shl_cash_principal_keur > 11_000.0
    assert acc.financial_leaves(canonical) == acc.financial_leaves(odr)
    meta = odr.authority_metadata
    assert meta["shl_maturity_final_waterfall_check"] == "PASSED"
    assert meta["shl_maturity_final_checks"] == [
        "CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY", "CONSTRUCTION_RETURNED_G2A.FINAL_FUNDED",
        "CONSTRUCTION_VERIFICATION_G2A.FINAL_CAPACITY", "CONSTRUCTION_VERIFICATION_G2A.FINAL_FUNDED",
        ma.WATERFALL_FINAL_CHECK]
    assert meta["shl_maturity_superseded_dsra_attempts"] == 1


def test_applicability_is_derived_from_the_final_state_not_from_evidence(feasible_pair):
    _, odr = feasible_pair
    g2c = odr.g2c_result
    fin = g2c.financing_result
    model = fin.project_model_result
    base = ma.required_final_checks(g2c)
    assert base == ma.OdrFinalRequirements(ma.CONSTRUCTION_G2A_ROLES, True, "derived-SHL/Senior fixed point")

    def with_financing(**changes):
        return dc.replace(g2c, financing_result=dc.replace(fin, **changes))

    zero_schedule = dc.replace(model.shareholder_loan, **{
        name: tuple(0.0 for _ in getattr(model.shareholder_loan, name))
        for name in ("shl_drawdown_keur", "shl_opening_keur", "shl_closing_keur")})
    no_shl_model = dc.replace(model, shareholder_loan=None)
    # very small positive principal is still a liability
    assert ma.required_final_checks(with_financing(derived_shl_cash_principal_keur=1e-12)).waterfall_required
    # zero principal but a positive SHL balance in the final schedule is still a liability
    assert ma.required_final_checks(with_financing(derived_shl_cash_principal_keur=0.0)).waterfall_required
    # genuinely no liability: zero principal and an all-zero schedule
    none = ma.required_final_checks(with_financing(
        derived_shl_cash_principal_keur=0.0, project_model_result=dc.replace(model, shareholder_loan=zero_schedule)))
    assert none.waterfall_required is False and none.g2a_roles == ma.CONSTRUCTION_G2A_ROLES
    # no SHL schedule in the final model: no deferred SHL pass exists
    absent = ma.required_final_checks(with_financing(derived_shl_cash_principal_keur=0.0, project_model_result=no_shl_model))
    assert absent == ma.OdrFinalRequirements((), False, "no SHL schedule in the final model")
    # top-level G2A when construction financing is absent
    assert ma.required_final_checks(with_financing(construction_financing=None)).g2a_roles == ma.TOP_LEVEL_G2A_ROLES
    # junior / multi-senior subclasses enforce canonically on every evaluation: no deferred G2A role
    from financial_engine.financing.junior_debt import JuniorFinancingResult
    junior = type("Probe", (JuniorFinancingResult,), {})
    probe = object.__new__(junior)
    for field in dc.fields(fin):
        object.__setattr__(probe, field.name, getattr(fin, field.name))
    requirements = ma.required_final_checks(dc.replace(g2c, financing_result=probe))
    assert requirements.g2a_roles == () and requirements.waterfall_required


def test_equity_only_state_is_not_applicable_by_its_own_financing(entries):
    result = _odr(entries, NO_SHL)
    assert result.g2c_result.financing_result.derived_shl_cash_principal_keur == 0.0
    assert result.policy_evidence.shl_maturity.final_waterfall_check == "NOT_APPLICABLE_NO_SHL"


# ------------------------------------------------------------------------------------------------ missing evidence

def test_missing_final_waterfall_check_with_shl_liability_fails_closed(entries, monkeypatch, feasible_pair):
    """Correction D reproduction: suppressing the real waterfall registration was previously accepted as NOT_APPLICABLE."""
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", lambda self, shortfall, *, state=None: None)
    error = _reject(entries, FEASIBLE)
    assert f"OdrFinalizationError: {ma.FINAL_EVIDENCE_MISSING}: {ma.WATERFALL_FINAL_CHECK}" in error
    assert "shl_liability=True" in error and CODE not in error
    # canonical path never consults the contract: unchanged under the same injection
    pfa._POLICY_RUN_CACHE.clear()
    assert acc.financial_leaves(acc.run_case(FEASIBLE, "canonical", entries)) == acc.financial_leaves(feasible_pair[0])


@pytest.mark.parametrize("dropped", ma.CONSTRUCTION_G2A_ROLES)
def test_missing_returned_or_verification_g2a_fails_closed(entries, monkeypatch, dropped):
    def transform(self, evidence, final, role, state, original):
        if final and role == dropped:
            return None
        return original(self, evidence, final=final, role=role, state=state)

    log = _wrap_absorb(monkeypatch, transform)
    error = _reject(entries, FEASIBLE)
    assert (dropped, True) in log
    assert f"{ma.FINAL_EVIDENCE_MISSING}: {dropped}.FINAL_CAPACITY, {dropped}.FINAL_FUNDED_OR_STRICT" in error


@pytest.mark.parametrize("site,label", [("CAPACITY", "FINAL_CAPACITY"), ("FUNDED", "FINAL_FUNDED_OR_STRICT")])
def test_missing_final_capacity_or_funded_pass_fails_closed(entries, monkeypatch, site, label):
    def transform(self, evidence, final, role, state, original):
        if final and role == "CONSTRUCTION_RETURNED_G2A":
            evidence.final_passes = [(s, v) for s, v in evidence.final_passes
                                     if s != site and not (site == "FUNDED" and s == "STRICT")]
        return original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    error = _reject(entries, FEASIBLE)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: CONSTRUCTION_RETURNED_G2A.{label}" in error


def test_missing_top_level_g2a_evidence_fails_closed(entries, monkeypatch):
    result = _odr(entries, NO_CONSTRUCTION)
    assert result.g2c_result.financing_result.construction_financing is None
    assert "G2A.FINAL_CAPACITY" in result.authority_metadata["shl_maturity_final_checks"]
    pfa._POLICY_RUN_CACHE.clear()

    def transform(self, evidence, final, role, state, original):
        if final and role == "G2A":
            return None
        return original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: G2A.FINAL_CAPACITY" in _reject(entries, NO_CONSTRUCTION)


# ------------------------------------------------------------------------------------------------ stale / duplicate / contradictory

def test_duplicate_registration_for_one_state_fails_closed(entries, monkeypatch):
    def transform(self, evidence, final, role, state, original):
        original(self, evidence, final=final, role=role, state=state)
        if final and role == "CONSTRUCTION_RETURNED_G2A":
            original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    assert f"{ma.FINAL_EVIDENCE_DUPLICATE}: CONSTRUCTION_RETURNED_G2A" in _reject(entries, FEASIBLE)


def test_evidence_bound_to_another_state_cannot_satisfy_finalization(entries, monkeypatch):
    foreign = object()

    def transform(self, evidence, final, role, state, original):
        if final and role == "CONSTRUCTION_RETURNED_G2A":
            evidence.final_passes = [(s, BREACH) for s, _ in evidence.final_passes]
            return original(self, evidence, final=final, role=role, state=foreign)
        return original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    error = _reject(entries, FEASIBLE)
    # the stale breach is a diagnostic of another state; the returned state lacks its own evidence
    assert f"{ma.FINAL_EVIDENCE_MISSING}: CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in error and CODE not in error


def test_waterfall_check_of_another_state_cannot_satisfy_finalization(entries, monkeypatch):
    original = ma.OdrAttempt.record_final_waterfall
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall",
                        lambda self, shortfall, *, state=None: original(self, shortfall, state=object()))
    assert f"{ma.FINAL_EVIDENCE_MISSING}: {ma.WATERFALL_FINAL_CHECK}" in _reject(entries, FEASIBLE)


def test_waterfall_evidence_for_a_state_without_liability_is_contradictory(entries, monkeypatch):
    original = ma.OdrAttempt.finalize

    def finalize(self, result):
        self.record_final_waterfall(None, state=result.financing_result.project_model_result)
        return original(self, result)

    monkeypatch.setattr(ma.OdrAttempt, "finalize", finalize)
    assert f"{ma.FINAL_EVIDENCE_CONTRADICTORY}: {ma.WATERFALL_FINAL_CHECK}" in _reject(entries, NO_SHL)


def test_finalization_is_single_and_evidence_must_be_bound():
    attempt = ma.OdrAttempt()
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        attempt.record_final_waterfall(None)
    evidence = ma.G2aShlMaturityEvidence()
    evidence.record_iteration(1, [], final=True)
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        attempt.absorb_g2a(evidence, final=True, role="G2A")
    attempt._finalized = True
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINALIZATION_REPEATED):
        attempt.record_final_waterfall(None, state=object())
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINALIZATION_REPEATED):
        attempt.finalize(object())


def test_superseded_dsra_evaluation_evidence_stays_diagnostic(entries, monkeypatch):
    original = ma.OdrAttempt.record_final_waterfall
    first: list = []

    def record(self, shortfall, *, state=None):
        if not first:                       # the first OD-R evaluation is the superseded DSRA iteration
            first.append(self)
            return original(self, BREACH, state=state)
        return original(self, shortfall, state=state)

    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", record)
    result = _odr(entries, FEASIBLE)
    evidence = result.policy_evidence.shl_maturity if hasattr(result, "policy_evidence") else None
    meta = result.authority_metadata
    assert meta["shl_maturity_superseded_dsra_attempts"] == 1
    assert meta["shl_maturity_max_provisional_shortfall_keur"] >= BREACH.closing_keur
    assert evidence is None or evidence.final_waterfall_check == "PASSED"


# ------------------------------------------------------------------------------------------------ precedence

def test_economic_breach_takes_precedence_over_missing_evidence(entries, monkeypatch):
    def transform(self, evidence, final, role, state, original):
        if final and role == "CONSTRUCTION_VERIFICATION_G2A":
            return None
        return original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    original = ma.OdrAttempt.record_final_waterfall
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall",
                        lambda self, shortfall, *, state=None: original(self, BREACH, state=state))
    error = _reject(entries, FEASIBLE)
    assert f"ValueError: {CODE}" in error and f"od_r_final_check={ma.WATERFALL_FINAL_CHECK}" in error


def test_upstream_idempotence_failure_keeps_precedence_over_missing_evidence(entries, monkeypatch):
    from finco_core.construction import stage_b2
    original_b2 = stage_b2.run_stage_b2

    def perturbed(config):
        result = original_b2(config)
        costs = dc.replace(result.capitalized_financing_costs,
                           senior_idc_keur=result.capitalized_financing_costs.senior_idc_keur + 1.0)
        return dc.replace(result, capitalized_financing_costs=costs)

    monkeypatch.setattr(stage_b2, "run_stage_b2", perturbed)
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", lambda self, shortfall, *, state=None: None)
    error = _reject(entries, FEASIBLE)
    assert "RuntimeError: PR9_OUTER_G2A_IDEMPOTENCE_FAILED" in error and ma.FINAL_EVIDENCE_MISSING not in error


def test_upstream_inner_non_convergence_keeps_precedence(entries, monkeypatch):
    from financial_engine.shareholder_waterfall import model as waterfall
    original = waterfall.run_project_financing_model

    def capped(*args, **kwargs):
        kwargs["maximum_iterations"] = 2
        return original(*args, **kwargs)

    monkeypatch.setattr(waterfall, "run_project_financing_model", capped)
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", lambda self, shortfall, *, state=None: None)
    error = _reject(entries, FEASIBLE)
    assert "DID_NOT_CONVERGE" in error and ma.FINAL_EVIDENCE_MISSING not in error


# ------------------------------------------------------------------------------------------------ real P0 configuration

def _cash_reserve_inputs():
    from app import project_factories as pf
    from finco_core.inputs.cash_reserve_interest_policy import (
        BalanceConvention, CashReserveInterestAuthority, CashReserveInterestPolicy, DayCountConvention, EligibilityStatus)
    from finco_core.inputs.distribution_accounting_policy import (
        DistributionAccountingAuthority, DistributionAccountingPolicy, OpeningUCAuthority)
    pi = pf.create_generic_wind_reference()
    return dc.replace(
        pi,
        cash_reserve_interest_policy=CashReserveInterestPolicy(
            authority=CashReserveInterestAuthority.GENERIC_FINCO_POLICY,
            eligible_unrestricted_cash=EligibilityStatus.ELIGIBLE, eligible_dsra=EligibilityStatus.ELIGIBLE,
            annual_rate=0.02, balance_convention=BalanceConvention.OPENING,
            day_count_convention=DayCountConvention.ACTUAL_365, enabled=True),
        distribution_accounting_policy=DistributionAccountingPolicy(
            enabled=True, authority=DistributionAccountingAuthority.GENERIC_FINCO_POLICY,
            dividend_wht_rate=pi.tax.wht_sponsor_dividends, opening_uc_authority=OpeningUCAuthority.CAUSALLY_DERIVED_ZERO))


def test_cash_reserve_final_financing_without_its_own_waterfall_check_fails_closed():
    """P0 (no injection): with cash-reserve interest + distribution accounting the waterfall returns the final U2 re-run
    financing, whose SHL waterfall schedule is never evaluated (only earlier U2 states were). The approved 32b9478f candidate
    accepted this from stale checks of other states; the contract rejects it. Canonical behaviour is unchanged."""
    pi = _cash_reserve_inputs()
    canonical = pfa.run_clean_production(pi, project_type="Wind")
    assert canonical.g2c_result.financing_result.derived_shl_cash_principal_keur > 11_000.0
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as info:
        pfa.run_clean_production(pi, project_type="Wind", financing_policy=acc.policy_for("odr", None))
    assert f"{ma.FINAL_EVIDENCE_MISSING}: {ma.WATERFALL_FINAL_CHECK}" in info.value.detail


# ------------------------------------------------------------------------------------------------ isolation

def test_concurrent_odr_evaluations_are_isolated(entries, feasible_pair):
    results, errors = {}, []

    def run(name):
        try:
            results[name] = acc.run_case(name, "odr", entries)
        except Exception as exc:                         # noqa: BLE001
            errors.append((name, exc))

    threads = [threading.Thread(target=run, args=(name,)) for name in (FEASIBLE, NO_SHL)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert acc.financial_leaves(results[FEASIBLE]) == acc.financial_leaves(feasible_pair[1])
    assert results[FEASIBLE].authority_metadata["shl_maturity_final_waterfall_check"] == "PASSED"
    assert results[NO_SHL].policy_evidence.shl_maturity.final_waterfall_check == "NOT_APPLICABLE_NO_SHL"


def test_failed_run_followed_by_successful_run_carries_no_evidence(entries, monkeypatch, feasible_pair):
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", lambda self, shortfall, *, state=None: None)
    _reject(entries, FEASIBLE)
    monkeypatch.undo()
    again = _odr(entries, FEASIBLE)
    assert acc.flatten(again) == acc.flatten(feasible_pair[1])
