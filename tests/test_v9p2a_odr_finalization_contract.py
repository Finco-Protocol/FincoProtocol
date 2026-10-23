"""V9-P2a / OD-R Corrections E+F - final financial evidence contract (real engine evaluations + targeted fault injection).

Invariant: an OD-R result is returned only after every final check REQUIRED by the returned financing state was performed
on exactly that state and passed.

* Identity (P1-01): evidence binds to ``financial_state_digest`` - a deterministic SHA-256 of every financing-result field
  and the financing-dependent final model schedules (exact float bits) - recomputed at finalization. Python identity is
  neither required nor sufficient.
* G2A sites (P1-02): fixed roles; per required role exactly one CAPACITY and one FUNDED-or-STRICT; unknown sites / roles,
  extra or contradictory passes fail closed.
* Waterfall provenance (P1-03): each check carries its proof token (the evaluated maturity context), the exact inputs and
  the schedule it produced; the returned waterfall rows must equal a checked schedule; identical repeats are legitimate,
  re-registration of one proof, re-evaluation with different inputs and stale schedules are not.
* Financing authority (P1-04): exact-type table (ProjectFinancingResult deferred G2A; Junior delegated canonical;
  multi-senior without SHL); unknown types, subclasses and U2 post-evaluation attachments fail closed.

Injected faults only remove, duplicate, alter or misbind the real evidence / returned state of real evaluations.
The canonical (deployed default) path never consults this contract.
"""
from __future__ import annotations

import copy
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


def _wrap_waterfall(monkeypatch, transform):
    """``transform(self, context, kwargs, original)`` around the real waterfall registration."""
    original = ma.OdrAttempt.record_final_waterfall
    log = []

    def record(self, context, **kwargs):
        log.append(context)
        return transform(self, context, kwargs, original)

    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", record)
    return log


def _suppress_waterfall(monkeypatch):
    monkeypatch.setattr(ma.OdrAttempt, "record_final_waterfall", lambda self, context, **kwargs: None)


def _wrap_finalize(monkeypatch, substitute):
    """Replace the returned result handed to the real ``finalize`` (state-binding controls)."""
    original = ma.OdrAttempt.finalize
    seen = []

    def finalize(self, result):
        seen.append(self)
        return original(self, substitute(result))

    monkeypatch.setattr(ma.OdrAttempt, "finalize", finalize)
    return seen


def _with_financing(result, **changes):
    return dc.replace(result, financing_result=dc.replace(result.financing_result, **changes))


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


def test_state_digest_is_deterministic_exact_and_content_based(feasible_pair):
    canonical, odr = feasible_pair
    fin = odr.g2c_result.financing_result
    digest = ma.financial_state_digest(fin)
    assert digest == ma.financial_state_digest(copy.deepcopy(fin))          # different objects, identical content
    assert digest == ma.financial_state_digest(canonical.g2c_result.financing_result)
    bumped = fin.derived_shl_cash_principal_keur + 1e-9                     # smallest economically visible change
    assert ma.financial_state_digest(dc.replace(fin, derived_shl_cash_principal_keur=bumped)) != digest
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        ma.financial_state_digest(object())


def test_applicability_is_derived_from_the_final_state_not_from_evidence(feasible_pair):
    _, odr = feasible_pair
    g2c = odr.g2c_result
    fin = g2c.financing_result
    model = fin.project_model_result
    base = ma.required_final_checks(g2c)
    assert (base.g2a_roles, base.waterfall_required, base.authority) == (ma.CONSTRUCTION_G2A_ROLES, True, "G2A_DEFERRED")
    zero_schedule = dc.replace(model.shareholder_loan, **{
        name: tuple(0.0 for _ in getattr(model.shareholder_loan, name))
        for name in ("shl_drawdown_keur", "shl_opening_keur", "shl_closing_keur")})
    assert ma.required_final_checks(_with_financing(g2c, derived_shl_cash_principal_keur=1e-12)).waterfall_required
    assert ma.required_final_checks(_with_financing(g2c, derived_shl_cash_principal_keur=0.0)).waterfall_required
    none = ma.required_final_checks(_with_financing(
        g2c, derived_shl_cash_principal_keur=0.0, project_model_result=dc.replace(model, shareholder_loan=zero_schedule)))
    assert none.waterfall_required is False and none.g2a_roles == ma.CONSTRUCTION_G2A_ROLES
    absent = ma.required_final_checks(_with_financing(
        g2c, derived_shl_cash_principal_keur=0.0, project_model_result=dc.replace(model, shareholder_loan=None)))
    assert (absent.g2a_roles, absent.waterfall_required) == ((), False)
    assert ma.required_final_checks(_with_financing(g2c, construction_financing=None)).g2a_roles == ma.TOP_LEVEL_G2A_ROLES


def _retyped(financing, cls):
    probe = object.__new__(cls)
    for field in dc.fields(financing):
        object.__setattr__(probe, field.name, getattr(financing, field.name))
    for field in dc.fields(cls):
        if not hasattr(probe, field.name):
            object.__setattr__(probe, field.name, None)
    return probe


def test_p1_04_exact_type_authority_table(feasible_pair):
    from financial_engine.financing.contracts import ProjectFinancingResult
    from financial_engine.financing.junior_debt import JuniorFinancingResult
    from financial_engine.financing.multisenior import MultiSeniorFinancingResult
    g2c = feasible_pair[1].g2c_result
    fin = g2c.financing_result
    junior = ma.required_final_checks(dc.replace(g2c, financing_result=_retyped(fin, JuniorFinancingResult)))
    assert (junior.authority, junior.g2a_roles, junior.waterfall_required) == ("DELEGATED_CANONICAL", (), True)
    for subclass_of in (ProjectFinancingResult, JuniorFinancingResult):
        probe = type("UnreviewedSubtype", (subclass_of,), {})
        with pytest.raises(ma.OdrFinalizationError, match=ma.UNSUPPORTED_FINANCING):
            ma.required_final_checks(dc.replace(g2c, financing_result=_retyped(fin, probe)))
    with pytest.raises(ma.OdrFinalizationError, match=ma.UNSUPPORTED_FINANCING):     # multi-senior has no SHL facility
        ma.required_final_checks(dc.replace(g2c, financing_result=_retyped(fin, MultiSeniorFinancingResult)))
    no_shl = dc.replace(fin, derived_shl_cash_principal_keur=0.0,
                        project_model_result=dc.replace(fin.project_model_result, shareholder_loan=None))
    multi = ma.required_final_checks(dc.replace(g2c, financing_result=_retyped(no_shl, MultiSeniorFinancingResult)))
    assert (multi.authority, multi.waterfall_required) == ("NO_SHL_FACILITY", False)


def test_p1_04_junior_is_delegated_canonical_on_the_real_engine(monkeypatch):
    from financial_engine import orchestrator
    from tests.test_financing_f3_junior_contract import case
    pi, _ = case("solar")
    contexts = []
    original = orchestrator.run_senior_debt_model

    def spy(model_input, **kwargs):
        contexts.append(kwargs.get("shl_maturity_context"))
        return original(model_input, **kwargs)

    # Junior imports the orchestrator entry at call time; the G2A owner keeps its own module reference, so this spy sees
    # exactly the Junior path's Senior/SHL/tax evaluations.
    monkeypatch.setattr(orchestrator, "run_senior_debt_model", spy)
    canonical = pfa.run_clean_production(pi)
    pfa._POLICY_RUN_CACHE.clear()
    contexts.clear()
    odr = pfa.run_clean_production(pi, financing_policy=acc.policy_for("odr", None))
    assert contexts and all(context is None for context in contexts)       # canonical immediate check inside Junior
    assert acc.financial_leaves(canonical) == acc.financial_leaves(odr)
    assert ma.required_final_checks(odr.g2c_result).authority == "DELEGATED_CANONICAL"


def test_equity_only_state_is_not_applicable_by_its_own_financing(entries):
    result = _odr(entries, NO_SHL)
    assert result.g2c_result.financing_result.derived_shl_cash_principal_keur == 0.0
    assert result.policy_evidence.shl_maturity.final_waterfall_check == "NOT_APPLICABLE_NO_SHL"


# ------------------------------------------------------------------------------------------------ P1-01 state identity

@pytest.mark.parametrize("change", [
    {"share_premium_keur": 1.0},                       # different financing object sharing one ProjectModelResult
    {"derived_shl_cash_principal_keur": 0.5},          # same model object, changed SHL principal
])
def test_p1_01_other_financing_sharing_the_model_cannot_use_the_evidence(entries, monkeypatch, change):
    def substitute(result):
        fin = result.financing_result
        changes = {k: getattr(fin, k) + v for k, v in change.items()}
        return _with_financing(result, **changes)

    _wrap_finalize(monkeypatch, substitute)
    error = _reject(entries, FEASIBLE)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in error
    assert ma.WATERFALL_FINAL_CHECK in error


@pytest.mark.parametrize("label", ["cash_reserve_interest_schedule", "financing_income_vector"])
def test_p1_01_changed_cash_reserve_or_financing_income_schedule_is_rejected(entries, monkeypatch, label):
    @dc.dataclass(frozen=True)
    class Schedule:                                    # stand-in carrying a per-period financing-income vector
        financing_income_keur: tuple

    _wrap_finalize(monkeypatch, lambda result: _with_financing(
        result, cash_reserve_interest_schedules=Schedule((0.0, 1.0 if label == "financing_income_vector" else 0.5))))
    assert ma.UNSUPPORTED_FINANCING in _reject(entries, FEASIBLE)


def test_p1_01_mutation_after_registration_is_detected(entries, monkeypatch):
    def substitute(result):
        fin = result.financing_result
        object.__setattr__(fin, "share_premium_keur", fin.share_premium_keur + 1.0)   # bypass frozen dataclass
        return result

    _wrap_finalize(monkeypatch, substitute)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in _reject(entries, FEASIBLE)


def test_p1_01_semantically_identical_reuse_is_accepted(entries, monkeypatch, feasible_pair):
    _wrap_finalize(monkeypatch, copy.deepcopy)         # every object differs, the financial content is identical
    result = _odr(entries, FEASIBLE)
    assert acc.financial_leaves(result) == acc.financial_leaves(feasible_pair[1])


def test_p1_01_other_attempt_superseded_and_provisional_evidence_never_authorise(entries, monkeypatch, feasible_pair):
    attempts = _wrap_finalize(monkeypatch, lambda result: result)
    returned = _odr(entries, FEASIBLE).g2c_result
    monkeypatch.undo()
    # evidence of another attempt / another Run
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_MISSING):
        ma.OdrAttempt().finalize(returned)
    # the same attempt's evidence after it was superseded (non-final DSRA iteration)
    stale = attempts[-1]
    stale._finalized = False
    stale.demote("DSRA_ITER_SUPERSEDED")
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_MISSING):
        stale.finalize(returned)
    # provisional (non-final) G2A evidence of the returned state
    attempt = ma.OdrAttempt()
    evidence = ma.G2aShlMaturityEvidence()
    evidence.record_iteration(1, [("CAPACITY", ma.ShlMaturityContext.provisional_pass()),
                                  ("FUNDED", ma.ShlMaturityContext.provisional_pass())], final=True)
    attempt.absorb_g2a(evidence, final=False, role="CONSTRUCTION_RETURNED_G2A", state=returned.financing_result)
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_MISSING):
        attempt.finalize(returned)


# ------------------------------------------------------------------------------------------------ P1-02 strict G2A sites

def _transform_sites(edit, role="CONSTRUCTION_RETURNED_G2A"):
    def transform(self, evidence, final, role_, state, original):
        if final and role_ == role:
            evidence.final_passes = edit(list(evidence.final_passes))
        return original(self, evidence, final=final, role=role_, state=state)
    return transform


@pytest.mark.parametrize("edit,expected", [
    (lambda passes: passes + [("BOGUS", None)], "unknown site(s) ['BOGUS']"),
    (lambda passes: passes + [("CAPACITY", None)], "CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY"),
    (lambda passes: passes + [("STRICT", None)], "CONSTRUCTION_RETURNED_G2A.FINAL_FUNDED_OR_STRICT"),
])
def test_p1_02_unknown_extra_or_duplicate_sites_are_contradictory(entries, monkeypatch, edit, expected):
    _wrap_absorb(monkeypatch, _transform_sites(edit))
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_CONTRADICTORY in error and expected in error


@pytest.mark.parametrize("site,label", [("CAPACITY", "FINAL_CAPACITY"), ("FUNDED", "FINAL_FUNDED_OR_STRICT")])
def test_p1_02_missing_mandatory_site_fails_closed(entries, monkeypatch, site, label):
    _wrap_absorb(monkeypatch, _transform_sites(
        lambda passes: [(s, v) for s, v in passes if s != site and not (site == "FUNDED" and s == "STRICT")]))
    assert f"{ma.FINAL_EVIDENCE_MISSING}: CONSTRUCTION_RETURNED_G2A.{label}" in _reject(entries, FEASIBLE)


@pytest.mark.parametrize("dropped", ma.CONSTRUCTION_G2A_ROLES)
def test_p1_02_missing_returned_or_verification_g2a_fails_closed(entries, monkeypatch, dropped):
    def transform(self, evidence, final, role, state, original):
        if final and role == dropped:
            return None
        return original(self, evidence, final=final, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: {dropped}.FINAL_CAPACITY, {dropped}.FINAL_FUNDED_OR_STRICT" in _reject(
        entries, FEASIBLE)


def test_p1_02_unexpected_role_for_the_returned_structure_is_contradictory(entries, monkeypatch):
    def transform(self, evidence, final, role, state, original):
        original(self, evidence, final=final, role=role, state=state)
        if final and role == "CONSTRUCTION_RETURNED_G2A":
            twin = ma.G2aShlMaturityEvidence()       # a separate proof token, top-level role on a construction state
            twin.final_passes, twin.converged = list(evidence.final_passes), True
            original(self, twin, final=True, role="G2A", state=state)

    _wrap_absorb(monkeypatch, transform)
    assert "G2A evaluated SHL passes for a state that requires none" in _reject(entries, FEASIBLE)


def test_p1_02_unknown_role_and_reregistered_proof_are_refused():
    attempt = ma.OdrAttempt()
    evidence = ma.G2aShlMaturityEvidence()
    evidence.record_iteration(1, [], final=True)
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNKNOWN):
        attempt.absorb_g2a(evidence, final=True, role="G2A_EXTRA", state=object())
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        attempt.absorb_g2a(evidence, final=True, role="G2A")


def test_p1_02_top_level_g2a_evidence_is_required(entries, monkeypatch):
    result = _odr(entries, NO_CONSTRUCTION)
    assert result.g2c_result.financing_result.construction_financing is None
    assert "G2A.FINAL_CAPACITY" in result.authority_metadata["shl_maturity_final_checks"]
    pfa._POLICY_RUN_CACHE.clear()
    _wrap_absorb(monkeypatch, lambda self, evidence, final, role, state, original:
                 None if final and role == "G2A" else original(self, evidence, final=final, role=role, state=state))
    assert f"{ma.FINAL_EVIDENCE_MISSING}: G2A.FINAL_CAPACITY" in _reject(entries, NO_CONSTRUCTION)


# ------------------------------------------------------------------------------------------------ P1-03 waterfall provenance

def test_p1_03_missing_final_waterfall_check_with_shl_liability_fails_closed(entries, monkeypatch, feasible_pair):
    _suppress_waterfall(monkeypatch)
    error = _reject(entries, FEASIBLE)
    assert f"OdrFinalizationError: {ma.FINAL_EVIDENCE_MISSING}: {ma.WATERFALL_FINAL_CHECK}" in error
    assert "shl_liability=True" in error and CODE not in error
    pfa._POLICY_RUN_CACHE.clear()
    assert acc.financial_leaves(acc.run_case(FEASIBLE, "canonical", entries)) == acc.financial_leaves(feasible_pair[0])


def test_p1_03_reregistering_one_proof_is_a_duplicate(entries, monkeypatch):
    def transform(self, context, kwargs, original):
        original(self, context, **kwargs)
        original(self, context, **kwargs)

    _wrap_waterfall(monkeypatch, transform)
    assert f"{ma.FINAL_EVIDENCE_DUPLICATE}: one evaluation registered twice" in _reject(entries, FEASIBLE)


def _replay(context):
    """A separate evaluation token with the identical recorded outcome (legitimate repeated calculation)."""
    twin = ma.ShlMaturityContext.provisional_pass()
    for shortfall in context.ledger.shortfalls:
        twin.ledger.record(shortfall)
    return twin


def test_p1_03_legitimate_identical_repeat_is_accepted(entries, monkeypatch, feasible_pair):
    def transform(self, context, kwargs, original):
        original(self, context, **kwargs)
        original(self, _replay(context), **kwargs)

    _wrap_waterfall(monkeypatch, transform)
    assert acc.financial_leaves(_odr(entries, FEASIBLE)) == acc.financial_leaves(feasible_pair[1])


def test_p1_03_repeat_with_changed_inputs_for_the_same_schedule_is_contradictory(entries, monkeypatch):
    def transform(self, context, kwargs, original):
        original(self, context, **kwargs)
        changed = dict(kwargs, cash=tuple(value * 1.01 for value in kwargs["cash"]))
        original(self, _replay(context), **changed)

    _wrap_waterfall(monkeypatch, transform)
    assert "evaluated with different inputs for one returned schedule" in _reject(entries, FEASIBLE)


def test_p1_03_check_of_a_different_schedule_is_stale(entries, monkeypatch):
    def transform(self, context, kwargs, original):
        schedule = kwargs["schedule"]
        closing = list(schedule.shl_closing_keur)
        closing[len(closing) // 3] += 1e-6
        original(self, context, **dict(kwargs, schedule=dc.replace(schedule, shl_closing_keur=tuple(closing))))

    _wrap_waterfall(monkeypatch, transform)
    assert "no check evaluated the returned SHL schedule" in _reject(entries, FEASIBLE)


def test_p1_03_check_of_another_financing_state_cannot_satisfy(entries, monkeypatch):
    def transform(self, context, kwargs, original):
        other = dc.replace(kwargs["financing"], share_premium_keur=kwargs["financing"].share_premium_keur + 1.0)
        original(self, context, **dict(kwargs, financing=other))

    _wrap_waterfall(monkeypatch, transform)
    error = _reject(entries, FEASIBLE)
    assert f"{ma.FINAL_EVIDENCE_MISSING}: {ma.WATERFALL_FINAL_CHECK}" in error and "no check evaluated" not in error


def test_p1_03_waterfall_evidence_needs_its_evaluation_context():
    attempt = ma.OdrAttempt()
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        attempt.record_final_waterfall(None)
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINAL_EVIDENCE_UNBOUND):
        attempt.record_final_waterfall(ma.ShlMaturityContext.provisional_pass())


def test_waterfall_evidence_for_a_state_without_liability_is_contradictory(entries, monkeypatch, feasible_pair):
    feasible = feasible_pair[1]
    original = ma.OdrAttempt.finalize

    def finalize(self, result):
        # a real waterfall registration made for this returned state, which has no SHL liability
        fin = result.financing_result
        schedule = feasible.g2c_result.financing_result.project_model_result.shareholder_loan

        @dc.dataclass(frozen=True)
        class ShlInput:
            maturity_period_index: int = 41
            repayment_mode: str = "CASH_SWEEP"

        self.record_final_waterfall(ma.ShlMaturityContext.provisional_pass(), financing=fin, shl_input=ShlInput(),
                                    cash=(0.0,), schedule=schedule)
        return original(self, result)

    monkeypatch.setattr(ma.OdrAttempt, "finalize", finalize)
    assert f"{ma.WATERFALL_FINAL_CHECK} recorded for a state without SHL liability" in _reject(entries, NO_SHL)


def test_superseded_dsra_evaluation_evidence_stays_diagnostic(entries, monkeypatch):
    first: list = []

    def transform(self, context, kwargs, original):
        if not first:                       # the first OD-R evaluation is the superseded DSRA iteration
            first.append(self)
            context.ledger.record(BREACH)
        return original(self, context, **kwargs)

    _wrap_waterfall(monkeypatch, transform)
    meta = _odr(entries, FEASIBLE).authority_metadata
    assert meta["shl_maturity_superseded_dsra_attempts"] == 1
    assert meta["shl_maturity_max_provisional_shortfall_keur"] >= BREACH.closing_keur
    assert meta["shl_maturity_final_waterfall_check"] == "PASSED"


def test_finalization_is_single():
    attempt = ma.OdrAttempt()
    attempt._finalized = True
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINALIZATION_REPEATED):
        attempt.record_final_waterfall(ma.ShlMaturityContext.provisional_pass(), financing=1, shl_input=1, cash=(),
                                       schedule=1)
    with pytest.raises(ma.OdrFinalizationError, match=ma.FINALIZATION_REPEATED):
        attempt.finalize(object())


# ------------------------------------------------------------------------------------------------ precedence

def test_economic_breach_takes_precedence_over_missing_evidence(entries, monkeypatch):
    _wrap_absorb(monkeypatch, lambda self, evidence, final, role, state, original: None
                 if final and role == "CONSTRUCTION_VERIFICATION_G2A"
                 else original(self, evidence, final=final, role=role, state=state))

    def transform(self, context, kwargs, original):
        context.ledger.record(BREACH)
        return original(self, context, **kwargs)

    _wrap_waterfall(monkeypatch, transform)
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
    _suppress_waterfall(monkeypatch)
    error = _reject(entries, FEASIBLE)
    assert "RuntimeError: PR9_OUTER_G2A_IDEMPOTENCE_FAILED" in error and ma.FINAL_EVIDENCE_MISSING not in error


def test_upstream_inner_non_convergence_keeps_precedence(entries, monkeypatch):
    from financial_engine.shareholder_waterfall import model as waterfall
    original = waterfall.run_project_financing_model

    def capped(*args, **kwargs):
        kwargs["maximum_iterations"] = 2
        return original(*args, **kwargs)

    monkeypatch.setattr(waterfall, "run_project_financing_model", capped)
    _suppress_waterfall(monkeypatch)
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


def test_p0_cash_reserve_u2_financing_is_unsupported_under_odr_and_canonical_unchanged():
    """The approved 32b9478f candidate accepted this real configuration from stale checks of earlier U2 states. The
    returned financing carries post-evaluation cash-reserve schedules and its own waterfall check was never evaluated:
    OD-R now refuses it explicitly; the canonical (deployed) result is unchanged."""
    pi = _cash_reserve_inputs()
    canonical = pfa.run_clean_production(pi, project_type="Wind")
    assert canonical.g2c_result.financing_result.derived_shl_cash_principal_keur > 11_000.0
    assert canonical.g2c_result.financing_result.cash_reserve_interest_schedules is not None
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as info:
        pfa.run_clean_production(pi, project_type="Wind", financing_policy=acc.policy_for("odr", None))
    assert ma.UNSUPPORTED_FINANCING in info.value.detail and "U2 cash-reserve" in info.value.detail


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
    assert results[NO_SHL].policy_evidence.shl_maturity.final_waterfall_check == "NOT_APPLICABLE_NO_SHL"


def test_failed_run_followed_by_successful_run_carries_no_evidence(entries, monkeypatch, feasible_pair):
    _suppress_waterfall(monkeypatch)
    _reject(entries, FEASIBLE)
    monkeypatch.undo()
    assert acc.flatten(_odr(entries, FEASIBLE)) == acc.flatten(feasible_pair[1])


# ------------------------------------------------------------------------------------------------ Review Fix A

def test_rfa_duplicate_final_role_with_distinct_tokens_is_contradictory(entries, monkeypatch):
    """Two distinct proof tokens with otherwise valid passes under one required role are not two legitimate checks."""
    def transform(self, evidence, final, role, state, original):
        original(self, evidence, final=final, role=role, state=state)
        if final and role == "CONSTRUCTION_RETURNED_G2A":
            twin = ma.G2aShlMaturityEvidence()
            twin.final_passes, twin.converged = list(evidence.final_passes), True
            original(self, twin, final=True, role=role, state=state)

    _wrap_absorb(monkeypatch, transform)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_CONTRADICTORY in error and "CONSTRUCTION_RETURNED_G2A registered 2 times" in error


def _edit_schedule(monkeypatch, edit):
    """Alter the schedule a real waterfall check reports (vectors / indices), keeping the real kernel outcome."""
    def transform(self, context, kwargs, original):
        schedule, shl_input = edit(kwargs["schedule"], kwargs["shl_input"])
        return original(self, context, **dict(kwargs, schedule=schedule, shl_input=shl_input))

    _wrap_waterfall(monkeypatch, transform)


_VECTORS = ("period_indices", "shl_closing_keur", "shl_gross_interest_keur", "shl_principal_keur")


def _rows(schedule):
    return [list(getattr(schedule, name)) for name in _VECTORS]


def _with(schedule, vectors):
    return dc.replace(schedule, **{name: tuple(values) for name, values in zip(_VECTORS, vectors)})


def _signed_zero(schedule, shl_input):
    idx, closing, gross, principal = _rows(schedule)
    # the last checked operating period that holds an exact +0.0 closing balance (after full repayment)
    k = max(i for i, (p, v) in enumerate(zip(idx, closing)) if v == 0.0 and p <= shl_input.maturity_period_index)
    assert closing[k] == 0.0 and str(closing[k]) == "0.0"
    closing[k] = -0.0
    return _with(schedule, (idx, closing, gross, principal)), shl_input


def _duplicate_index(schedule, shl_input):
    idx, *values = _rows(schedule)
    k = len(idx) // 2
    idx[k] = idx[k - 1]
    return _with(schedule, (idx, *values)), shl_input


def _missing_row(schedule, shl_input):
    vectors = _rows(schedule)
    k = len(vectors[0]) // 2
    return _with(schedule, [v[:k] + v[k + 1:] for v in vectors]), shl_input


def _reordered_rows(schedule, shl_input):
    vectors = _rows(schedule)
    k = len(vectors[0]) // 2
    for v in vectors:
        v[k], v[k + 1] = v[k + 1], v[k]
    return _with(schedule, vectors), shl_input


def _truncated_vector(schedule, shl_input):
    idx, closing, gross, principal = _rows(schedule)
    return _with(schedule, (idx, closing[:-1], gross, principal)), shl_input


def _mismatched_maturity(schedule, shl_input):
    return schedule, dc.replace(shl_input, maturity_period_index=shl_input.maturity_period_index - 1)


@pytest.mark.parametrize("edit", [_signed_zero, _duplicate_index, _missing_row, _reordered_rows, _truncated_vector,
                                  _mismatched_maturity], ids=lambda f: f.__name__.strip("_"))
def test_rfa_checked_schedule_identity_is_exact_and_complete(entries, monkeypatch, edit):
    _edit_schedule(monkeypatch, edit)
    error = _reject(entries, FEASIBLE)
    assert (ma.FINAL_EVIDENCE_MISSING in error or ma.FINAL_EVIDENCE_CONTRADICTORY in error
            or ma.FINAL_EVIDENCE_UNBOUND in error), error
    assert CODE not in error


def _returned_rows_edit(monkeypatch, edit):
    def substitute(result):
        return dc.replace(result, waterfall_periods=edit(tuple(result.waterfall_periods)))
    _wrap_finalize(monkeypatch, substitute)


def test_rfa_duplicate_returned_waterfall_row_fails_closed(entries, monkeypatch):
    def edit(rows):
        operating = [r for r in rows if r.shl_closing_balance_keur > 0.0]
        return rows + (operating[len(operating) // 2],)
    _returned_rows_edit(monkeypatch, edit)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_MISSING in error or ma.FINAL_EVIDENCE_CONTRADICTORY in error


def test_rfa_returned_signed_zero_differs_from_checked_positive_zero(entries, monkeypatch):
    def edit(rows):
        k = next(i for i, r in enumerate(rows) if not r.is_construction and r.shl_closing_balance_keur == 0.0
                 and str(r.shl_closing_balance_keur) == "0.0")
        return rows[:k] + (dc.replace(rows[k], shl_closing_balance_keur=-0.0),) + rows[k + 1:]
    _returned_rows_edit(monkeypatch, edit)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_MISSING in error or ma.FINAL_EVIDENCE_CONTRADICTORY in error


def test_rfa_unchanged_valid_schedule_and_identical_repeat_still_accepted(entries, monkeypatch, feasible_pair):
    _edit_schedule(monkeypatch, lambda schedule, shl_input: (schedule, shl_input))
    assert acc.financial_leaves(_odr(entries, FEASIBLE)) == acc.financial_leaves(feasible_pair[1])


def test_rfa_positive_shl_liability_without_final_schedule_is_unsupported(feasible_pair):
    g2c = feasible_pair[1].g2c_result
    fin = g2c.financing_result
    assert fin.derived_shl_cash_principal_keur > 0.0
    no_schedule = _with_financing(g2c, project_model_result=dc.replace(fin.project_model_result, shareholder_loan=None))
    with pytest.raises(ma.OdrFinalizationError, match=ma.UNSUPPORTED_FINANCING):
        ma.required_final_checks(no_schedule)


# ------------------------------------------------------------------------------------------------ Final contract closure

def _off_axis_checked_row(schedule, shl_input):
    """An extra checked row whose period is not on the model axis (strictly increasing order preserved)."""
    vectors = _rows(schedule)
    assert vectors[0][0] > -1
    return _with(schedule, [[-1] + vectors[0]] + [[0.0] + v for v in vectors[1:]]), shl_input


def test_fcc_off_axis_checked_row_is_rejected(entries, monkeypatch):
    _edit_schedule(monkeypatch, _off_axis_checked_row)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_MISSING in error or ma.FINAL_EVIDENCE_CONTRADICTORY in error


def _operating_positions(rows, result_periods):
    operating = {p.period_index for p in result_periods if p.is_operation}
    return [i for i, r in enumerate(rows) if not r.is_construction and r.period_index in operating]


def test_fcc_off_axis_returned_operating_row_is_rejected(entries, monkeypatch):
    def substitute(result):
        rows = tuple(result.waterfall_periods)
        k = _operating_positions(rows, result.financing_result.project_model_result.periods)[3]
        extra = dc.replace(rows[k], period_index=-1)                  # non-construction row outside the model axis
        return dc.replace(result, waterfall_periods=rows[:k] + (extra,) + rows[k:])
    _wrap_finalize(monkeypatch, substitute)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_CONTRADICTORY in error or ma.FINAL_EVIDENCE_MISSING in error


def test_fcc_reordered_returned_operating_rows_are_rejected(entries, monkeypatch):
    def substitute(result):
        rows = list(result.waterfall_periods)
        a, b = _operating_positions(rows, result.financing_result.project_model_result.periods)[5:7]
        rows[a], rows[b] = rows[b], rows[a]
        return dc.replace(result, waterfall_periods=tuple(rows))
    _wrap_finalize(monkeypatch, substitute)
    error = _reject(entries, FEASIBLE)
    assert ma.FINAL_EVIDENCE_CONTRADICTORY in error or ma.FINAL_EVIDENCE_MISSING in error


def test_fcc_source_functions_on_real_objects(feasible_pair, monkeypatch, entries):
    """Smallest deterministic demonstration on the actual source functions with a real returned result."""
    captured = {}
    original = ma.OdrAttempt.finalize

    def finalize(self, result):
        captured["attempt"], captured["result"] = self, result
        return original(self, result)

    monkeypatch.setattr(ma.OdrAttempt, "finalize", finalize)
    _odr(entries, FEASIBLE)
    attempt, result = captured["attempt"], captured["result"]
    registration = next(r for r in attempt._waterfall if r.state == ma.financial_state_digest(result.financing_result))
    returned, operating, axis, maturity, problem = ma.OdrAttempt._returned_rows(result)
    assert problem is None and ma.OdrAttempt._rows_match(registration, returned, operating, axis, maturity)
    # G1: checked off-axis row
    zero = ma._bits(0.0)
    off_axis = dc.replace(registration, rows=((-1, zero, zero, zero),) + registration.rows)
    assert not ma.OdrAttempt._rows_match(off_axis, returned, operating, axis, maturity)
    # G2 / G3: returned off-axis row and reordered operating rows
    rows = tuple(result.waterfall_periods)
    positions = _operating_positions(rows, result.financing_result.project_model_result.periods)
    extra = dc.replace(rows[positions[3]], period_index=-1)
    with_extra = dc.replace(result, waterfall_periods=rows[:positions[3]] + (extra,) + rows[positions[3]:])
    assert ma.OdrAttempt._returned_rows(with_extra)[4] == "returned waterfall row -1 is not an operating model period"
    swapped = list(rows)
    a, b = positions[5:7]
    swapped[a], swapped[b] = swapped[b], swapped[a]
    assert ma.OdrAttempt._returned_rows(dc.replace(result, waterfall_periods=tuple(swapped)))[4] == (
        "returned operating waterfall rows are missing, extra or out of model order")
    # construction row sharing an operating index (real shape) stays supported
    assert any(r.is_construction for r in rows) and problem is None
