"""V9-P2a / OD-R - final-state SHL maturity authority (release-closed candidate).

Production-level acceptance of the explicit authority contract, on synthetic factory inputs:

* the SHL kernel keeps its canonical fail-closed behaviour unless a fixed-point owner passes a
  PROVISIONAL context, which records the breach of the unchanged predicate and changes no value;
* under the OD-R policy, provisional-only breaches are admitted, while a breach at any final
  check (returned G2A capacity / funded-or-strict, verification G2A, final waterfall) rejects
  with the original ``SHL_MATURITY_RESIDUAL_FAILS_CLOSED`` code and final-state evidence;
* previously feasible outputs are bit-identical; structural and numerical rejections are
  unchanged; authority never leaks across runs, threads or the policy-run memo;
* the default (deployed) policy remains canonical and no product path can select OD-R.

Injected failures below are negative controls of the decision path only; they are injected
into the real per-pass ledgers / real waterfall kernel call, never into a result object.
"""
from __future__ import annotations

import dataclasses as dc
import threading

import pytest

from app.services import production_financial_authority as pfa
from financial_engine.financing import generic_product_policy as gpp
from financial_engine.shl import maturity_authority as ma
from tools import v9p2a_odr_acceptance as acc

CODE = "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"
INJECTED = ma.ShlMaturityShortfall(closing_keur=123.456789, period_index=41, tolerance_keur=1e-7)

# Cheapest representatives of each matrix class with SHL, construction IDC and initial DSRA (the full
# 112-case matrix in tools/v9p2a_odr_acceptance.py covers every case): previously feasible with one
# superseded DSRA iteration; provisional-only admission; final-state infeasible.
FEASIBLE = "reference-wind"
ADMITTED = "X-W25-dscr2.5"
INFEASIBLE = "S16-raw-infeasible"


@pytest.fixture(scope="module")
def entries():
    return acc.cases()


def _run(entries, name, mode):
    return acc.run_case(name, mode, entries)


def _reject(entries, name, mode):
    with pytest.raises(pfa.CleanProductionRunUnavailable) as info:
        _run(entries, name, mode)
    return info.value


@pytest.fixture(scope="module")
def feasible_pair(entries):
    return _run(entries, FEASIBLE, "canonical"), _run(entries, FEASIBLE, "odr")


@pytest.fixture(scope="module")
def admitted(entries):
    return _run(entries, ADMITTED, "odr")


@pytest.fixture(autouse=True)
def _clean_memo():
    pfa._POLICY_RUN_CACHE.clear()
    yield
    pfa._POLICY_RUN_CACHE.clear()
    assert ma.current_attempt() is None


# ---------------------------------------------------------------------------- P0 / P1 contract

def test_context_contract_is_typed_and_provisional_needs_a_ledger():
    with pytest.raises(ValueError):
        ma.ShlMaturityContext(ma.ShlMaturityAuthority.PROVISIONAL)
    with pytest.raises(TypeError):
        ma.ShlMaturityContext("PROVISIONAL", ma.ShlMaturityLedger())
    ctx = ma.ShlMaturityContext.provisional_pass()
    assert ctx.provisional and ctx.ledger.shortfalls == ()
    assert not ma.ShlMaturityContext(ma.ShlMaturityAuthority.AUTHORITATIVE).provisional


def test_canonical_message_is_unchanged():
    error = ma.shl_maturity_residual_error(ma.ShlMaturityShortfall(53.682455361104, 41, 1e-7))
    assert str(error) == (
        "SHL_MATURITY_RESIDUAL_FAILS_CLOSED: closing balance 53.682455361104 kEUR "
        "remains at maturity period_index=41")


def _capacity_input(entries, name, candidate_shl):
    """A real G2A capacity-pass model input of a case, at a chosen SHL principal."""
    from financial_engine.adapters.project_inputs import build_senior_debt_model_input_from_project_inputs
    factory, _, _ = entries[name]
    pi = factory()
    pi = dc.replace(pi, financing=dc.replace(pi.financing, clean_shl_principal_keur=candidate_shl,
                                             sponsor_funding_mode=None, gearing_basis_mode=None))
    return build_senior_debt_model_input_from_project_inputs(pi)


def test_kernel_default_raises_and_provisional_records_without_changing_values(entries, monkeypatch):
    from financial_engine import orchestrator
    from financial_engine.shl import production
    model_input = _capacity_input(entries, "S16-dscr3.0", 6000.0)
    with pytest.raises(ValueError, match=CODE):
        orchestrator.run_senior_debt_model(model_input)

    # Reference: the same calculation with the check switched off at every kernel call.
    original = production.compute_shareholder_loan_schedules

    def unchecked(*args, **kwargs):
        kwargs["enforce_maturity_residual"] = False
        kwargs.pop("maturity_context", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "compute_shareholder_loan_schedules", unchecked, raising=False)
    monkeypatch.setattr(production, "compute_shareholder_loan_schedules", unchecked)
    reference = orchestrator.run_senior_debt_model(model_input)
    monkeypatch.undo()

    ctx = ma.ShlMaturityContext.provisional_pass()
    provisional = orchestrator.run_senior_debt_model(model_input, shl_maturity_context=ctx)
    assert acc.flatten(provisional) == acc.flatten(reference)
    shortfall = ctx.ledger.first()
    assert shortfall is not None and shortfall.closing_keur > shortfall.tolerance_keur
    maturity = model_input.shareholder_loan.maturity_period_index
    closing = dict(zip(provisional.shareholder_loan.period_indices,
                       provisional.shareholder_loan.shl_closing_keur))[maturity]
    assert shortfall.closing_keur == closing and shortfall.period_index == maturity
    # An explicit AUTHORITATIVE context is the canonical behaviour.
    with pytest.raises(ValueError, match=CODE):
        orchestrator.run_senior_debt_model(
            model_input, shl_maturity_context=ma.ShlMaturityContext(ma.ShlMaturityAuthority.AUTHORITATIVE))


def test_provisional_context_never_suppresses_other_kernel_errors(entries):
    from financial_engine.shl.production import compute_shareholder_loan_schedules
    model_input = _capacity_input(entries, "S16", 2000.0)
    shl = dc.replace(model_input.shareholder_loan, maturity_period_index=10_000)
    ctx = ma.ShlMaturityContext.provisional_pass()
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    from app import project_factories as pf
    periods = run_operating_model(from_project_inputs(pf.create_default_solar_project())).periods
    with pytest.raises(ValueError, match="SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED"):
        compute_shareholder_loan_schedules(periods, shl, (0.0,) * len(periods),
                                           diagnostics=None, maturity_context=ctx)
    assert ctx.ledger.shortfalls == ()
    with pytest.raises(ValueError, match="maturity_context must be ShlMaturityContext"):
        compute_shareholder_loan_schedules((), shl, (), diagnostics=None, maturity_context="PROVISIONAL")


def test_senior_model_refuses_a_context_without_shareholder_loan(entries):
    from financial_engine.orchestrator import run_senior_debt_model
    model_input = dc.replace(_capacity_input(entries, "S16", 2000.0), shareholder_loan=None)
    with pytest.raises(ValueError, match="requires a shareholder-loan"):
        run_senior_debt_model(model_input, shl_maturity_context=ma.ShlMaturityContext.provisional_pass())


# ---------------------------------------------------------------------------- P6 representative

def test_previously_feasible_output_is_bit_identical(feasible_pair):
    canonical, odr = feasible_pair
    assert acc.financial_leaves(canonical) == acc.financial_leaves(odr)
    meta = {k: v for k, v in odr.authority_metadata.items() if k.startswith("shl_maturity_")}
    assert meta["shl_maturity_authority"] == ma.SHL_MATURITY_POLICY_OD_R
    assert meta["shl_maturity_provisional_violations"] == 0
    assert not any(k.startswith("shl_maturity_") for k in canonical.authority_metadata)
    finals = meta["shl_maturity_final_checks"]
    assert any(c.startswith("CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY") for c in finals)
    assert any(c.startswith("CONSTRUCTION_VERIFICATION_G2A.FINAL_") for c in finals)


def test_provisional_only_case_is_admitted_with_valid_final_state(entries, admitted):
    _reject(entries, ADMITTED, "canonical")  # canonical: rejected on a provisional breach
    meta = admitted.authority_metadata
    assert meta["shl_maturity_provisional_violations"] > 0
    assert meta["shl_maturity_max_provisional_shortfall_keur"] > 0.0
    assert meta["shl_maturity_final_waterfall_check"] == "PASSED"
    assert ma.WATERFALL_FINAL_CHECK in meta["shl_maturity_final_checks"]
    finals = meta["shl_maturity_final_checks"]
    assert [c for c in finals if c.startswith("CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY")]
    assert [c for c in finals if c.startswith("CONSTRUCTION_RETURNED_G2A.FINAL_") and not c.endswith("CAPACITY")]
    assert [c for c in finals if c.startswith("CONSTRUCTION_VERIFICATION_G2A.")]
    # Independent final-state checks: SHL repaid at maturity, Senior repaid, S = U, Integrity PASS.
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    assert run_integrity_checks(build_run_integrity_evidence(admitted)).to_dict()["overall"] == "PASS"
    fr = admitted.g2c_result.financing_result
    shl = fr.project_model_result.shareholder_loan
    maturity = fr.shareholder_loan_model_input.maturity_period_index if fr.shareholder_loan_model_input else None
    closing = dict(zip(shl.period_indices, shl.shl_closing_keur))
    assert closing[maturity if maturity is not None else shl.period_indices[-1]] <= 1e-7 + 1e-9
    funding = fr.construction_funding
    assert abs(funding.total_audit_sources_keur - funding.total_audit_uses_keur) <= 1e-6
    term = admitted.g2c_result.return_summary.terminal
    # Unchanged settlement gate (1e-4 kEUR). The terminal label is NOT relabelled: residuals between
    # the 1e-7 classification and 1e-4 settlement thresholds keep OUTSTANDING_AT_MATURITY exactly as
    # in six canonical previously-feasible Runs (separate Financial Owner labelling decision).
    assert term.senior.status.name in ("REPAID", "OUTSTANDING_AT_MATURITY")
    assert term.senior.balance_at_contractual_maturity_keur <= 1e-4


def test_final_state_infeasible_case_still_rejected_with_final_evidence(entries):
    canonical = _reject(entries, INFEASIBLE, "canonical")
    odr = _reject(entries, INFEASIBLE, "odr")
    assert canonical.reason_code == odr.reason_code == "PR8_CLEAN_ENGINE_FAIL_CLOSED"
    assert f"ValueError: {CODE}: closing balance " in odr.detail
    assert "od_r_final_check=CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in odr.detail
    assert isinstance(odr.__cause__, ValueError) and str(odr.__cause__).startswith(CODE)
    assert not pfa._POLICY_RUN_CACHE


@pytest.mark.parametrize("name", ["S16-shl-small", "W25-tenor18", "S16-gear0"])
def test_structural_and_numerical_rejections_are_unchanged(entries, name):
    canonical = _reject(entries, name, "canonical")
    odr = _reject(entries, name, "odr")
    assert (canonical.reason_code, canonical.detail) == (odr.reason_code, odr.detail)


# ---------------------------------------------------------------------------- P7 negative controls

def _inject_final(monkeypatch, sites, roles=None):
    """Record an extra breach in the real ledger of chosen final passes (decision-path control)."""
    original = ma.OdrAttempt.absorb_g2a
    injected = []

    def absorb(self, evidence, *, final, role, **bound):
        if final and (roles is None or role in roles):
            evidence.final_passes = [
                (site, INJECTED if site in sites else shortfall) for site, shortfall in evidence.final_passes]
            injected.append(role)
        return original(self, evidence, final=final, role=role, **bound)

    monkeypatch.setattr(ma.OdrAttempt, "absorb_g2a", absorb)
    return injected


def _inject_ledger(monkeypatch, sites):
    """Record a breach in the real ledger of chosen passes of every converging G2A iteration.

    Superseded (seed / outer-iteration) G2As are later demoted to diagnostics by their owner;
    only the returned and verification G2As can carry it into a final check.
    """
    original = ma.G2aShlMaturityEvidence.record_iteration
    hits = []

    def record(self, iteration, passes, *, final):
        if final:
            for site, ctx in passes:
                if site in sites:
                    ctx.ledger.record(INJECTED)
                    hits.append(site)
        return original(self, iteration, passes, final=final)

    monkeypatch.setattr(ma.G2aShlMaturityEvidence, "record_iteration", record)
    return hits


def _observe_provisional(monkeypatch):
    """Capture every genuine breach the SHL kernel records under a provisional context."""
    original = ma.ShlMaturityLedger.record
    seen = []

    def record(self, shortfall):
        seen.append(shortfall)
        return original(self, shortfall)

    monkeypatch.setattr(ma.ShlMaturityLedger, "record", record)
    return seen


def _fail_construction_idempotence(monkeypatch):
    """Perturb only the final strict Stage B2 so the existing idempotence validation fails."""
    from finco_core.construction import stage_b2
    original = stage_b2.run_stage_b2
    calls = []

    def perturbed(config):
        result = original(config)
        calls.append(1)
        costs = dc.replace(result.capitalized_financing_costs,
                           senior_idc_keur=result.capitalized_financing_costs.senior_idc_keur + 1.0)
        return dc.replace(result, capitalized_financing_costs=costs)

    monkeypatch.setattr(stage_b2, "run_stage_b2", perturbed)
    return calls


def _final_sites(admitted):
    return [c.rsplit(".FINAL_", 1)[1] for c in admitted.authority_metadata["shl_maturity_final_checks"]
            if c.startswith("CONSTRUCTION_RETURNED_G2A.")]


def test_final_capacity_only_breach_rejects(entries, admitted, monkeypatch):
    injected = _inject_ledger(monkeypatch, {"CAPACITY"})
    error = _reject(entries, ADMITTED, "odr")
    assert injected and f"closing balance {INJECTED.closing_keur:.12f} kEUR" in error.detail
    assert "od_r_final_check=CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in error.detail


def test_final_funded_only_breach_rejects(entries, admitted, monkeypatch):
    funded_site = [s for s in _final_sites(admitted) if s != "CAPACITY"]
    assert funded_site in (["FUNDED"], ["STRICT"])
    _inject_ledger(monkeypatch, set(funded_site))
    error = _reject(entries, ADMITTED, "odr")
    assert f"od_r_final_check=CONSTRUCTION_RETURNED_G2A.FINAL_{funded_site[0]}" in error.detail


def test_both_final_passes_breached_reject_with_capacity_first(entries, monkeypatch):
    _inject_ledger(monkeypatch, {"CAPACITY", "FUNDED", "STRICT"})
    error = _reject(entries, ADMITTED, "odr")
    assert "od_r_final_check=CONSTRUCTION_RETURNED_G2A.FINAL_CAPACITY" in error.detail
    assert "od_r_failed_final_checks=4" in error.detail


def test_verification_g2a_breach_alone_rejects(entries, monkeypatch):
    injected = _inject_final(monkeypatch, {"CAPACITY"}, roles={"CONSTRUCTION_VERIFICATION_G2A"})
    error = _reject(entries, ADMITTED, "odr")
    assert injected == ["CONSTRUCTION_VERIFICATION_G2A"]
    assert "od_r_final_check=CONSTRUCTION_VERIFICATION_G2A.FINAL_CAPACITY" in error.detail


def test_breach_injected_only_into_superseded_g2a_stays_provisional(entries, monkeypatch):
    original = ma.OdrAttempt.absorb_g2a
    seen = []

    def absorb(self, evidence, *, final, role, **bound):
        if not final:
            evidence.final_passes = [(site, INJECTED) for site, _ in evidence.final_passes]
            seen.append(role)
        return original(self, evidence, final=final, role=role, **bound)

    monkeypatch.setattr(ma.OdrAttempt, "absorb_g2a", absorb)
    result = _run(entries, ADMITTED, "odr")
    assert seen and result.authority_metadata["shl_maturity_max_provisional_shortfall_keur"] >= INJECTED.closing_keur


def test_final_waterfall_breach_rejects_through_the_real_predicate(entries, monkeypatch):
    from financial_engine.shareholder_waterfall import model as waterfall
    original = waterfall.compute_shareholder_loan_schedules
    calls = []

    def starved(periods, shl_input, cash, **kwargs):
        calls.append(kwargs.get("maturity_context"))
        return original(periods, shl_input, (0.0,) * len(cash), **kwargs)

    monkeypatch.setattr(waterfall, "compute_shareholder_loan_schedules", starved)
    error = _reject(entries, ADMITTED, "odr")
    # The DSRA seed run is outside any OD-R evaluation (canonical, failure swallowed as before);
    # every waterfall SHL check inside an OD-R evaluation carries a provisional context.
    assert calls[0] is None and calls[1:] and all(c is not None and c.provisional for c in calls[1:])
    assert f"ValueError: {CODE}" in error.detail and not pfa._POLICY_RUN_CACHE
    assert f"od_r_final_check={ma.WATERFALL_FINAL_CHECK}" in error.detail
    # Outside OD-R the same starved waterfall is the canonical immediate fail-closed check.
    calls.clear()
    from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
    plain_inputs, _, _ = gpp.apply_generic_financing_policy(
        entries[FEASIBLE][0](), gpp.DISABLED_GENERIC_FINANCING_POLICY)
    with pytest.raises(ValueError, match=CODE):
        run_project_shareholder_waterfall_model(plain_inputs)
    assert calls == [None]


def test_waterfall_breach_in_superseded_dsra_attempt_is_provisional():
    attempt = ma.OdrAttempt()
    context = ma.ShlMaturityContext.provisional_pass()
    context.ledger.record(INJECTED)
    attempt.record_final_waterfall(context, financing=_FinancingState(), shl_input=_ShlInput(), cash=(0.0,),
                                   schedule=_Schedule())
    attempt.demote("DSRA_ITER1")
    assert attempt.first_final_failure() is None
    assert attempt.provisional_violations == [(f"DSRA_ITER1.{ma.WATERFALL_FINAL_CHECK}", INJECTED)]


@dc.dataclass(frozen=True)
class _FinancingState:          # minimal typed financing state for contract unit tests (identity by content)
    project_model_result: object = None
    derived_shl_cash_principal_keur: float = 1.0


@dc.dataclass(frozen=True)
class _ShlInput:
    maturity_period_index: int = 41
    repayment_mode: str = "CASH_SWEEP"


@dc.dataclass(frozen=True)
class _Schedule:
    period_indices: tuple = (41,)
    shl_closing_keur: tuple = (INJECTED.closing_keur,)
    shl_gross_interest_keur: tuple = (0.0,)
    shl_principal_keur: tuple = (0.0,)


def _cap_iterations(monkeypatch, cap):
    from financial_engine.shareholder_waterfall import model as waterfall
    original = waterfall.run_project_financing_model

    def capped(*args, **kwargs):
        kwargs["maximum_iterations"] = cap
        return original(*args, **kwargs)

    monkeypatch.setattr(waterfall, "run_project_financing_model", capped)


def test_non_convergent_inner_g2a_keeps_numerical_rejection(entries, monkeypatch):
    """Combined control 3: provisional maturity breaches + inner G2A non-convergence.

    Only inner G2A invocations made by the construction owner are capped, and only after the
    kernel has recorded genuine provisional breaches, so the breaches precede the failure.
    """
    from financial_engine.financing import project
    seen = _observe_provisional(monkeypatch)
    original = project.run_project_financing_model
    capped = []

    def inner(*args, **kwargs):
        if kwargs.get("_shl_maturity_evidence") is not None and seen:
            kwargs["maximum_iterations"] = 2
            capped.append(len(seen))
        return original(*args, **kwargs)

    monkeypatch.setattr(project, "run_project_financing_model", inner)
    error = _reject(entries, ADMITTED, "odr")
    assert seen and capped and capped[0] > 0, "genuine provisional breaches must precede the failure"
    assert "RuntimeError: G2A_SHL_SENIOR_FIXED_POINT_DID_NOT_CONVERGE" in error.detail
    assert CODE not in error.detail


def test_non_convergent_construction_outer_loop_keeps_numerical_rejection(entries, monkeypatch):
    """Combined control 4: provisional maturity breaches + construction outer non-convergence."""
    seen = _observe_provisional(monkeypatch)
    _cap_iterations(monkeypatch, 4)
    error = _reject(entries, "W25-dscr2.0", "odr")
    assert seen, "the control must contain genuine provisional maturity breaches"
    assert "PR9_OUTER_G2A_CONSTRUCTION_FIXED_POINT_DID_NOT_CONVERGE" in error.detail
    assert CODE not in error.detail


@pytest.mark.parametrize("site", ["CAPACITY", "FUNDED"])
def test_final_breach_with_failed_idempotence_keeps_the_idempotence_rejection(
        entries, admitted, monkeypatch, site):
    """Combined controls 1-2: a breach in a candidate final pass never masks failed idempotence.

    Final authority exists only after idempotence succeeds, so the original validation error stands.
    """
    sites = {site} if site == "CAPACITY" else set(_final_sites(admitted)) - {"CAPACITY"}
    hits = _inject_ledger(monkeypatch, sites)
    stage_b2_calls = _fail_construction_idempotence(monkeypatch)
    error = _reject(entries, ADMITTED, "odr")
    assert hits and stage_b2_calls
    assert "RuntimeError: PR9_OUTER_G2A_IDEMPOTENCE_FAILED" in error.detail
    assert CODE not in error.detail and "od_r_final_check" not in error.detail
    assert not isinstance(error.__cause__, ValueError)
    assert not pfa._POLICY_RUN_CACHE


def test_failed_idempotence_alone_is_the_same_rejection_in_both_authorities(entries, monkeypatch):
    _fail_construction_idempotence(monkeypatch)
    for mode in ("canonical", "odr"):
        pfa._POLICY_RUN_CACHE.clear()
        error = _reject(entries, FEASIBLE, mode)
        assert "RuntimeError: PR9_OUTER_G2A_IDEMPOTENCE_FAILED" in error.detail


def test_non_convergent_dsra_fixed_point_keeps_numerical_rejection(entries):
    factory, vertical, _ = entries[FEASIBLE]
    for authority in ma.SHL_MATURITY_POLICIES:
        policy = gpp.GenericFinancingPolicy(dsra_max_iterations=1, shl_maturity_authority=authority)
        pfa._POLICY_RUN_CACHE.clear()
        with pytest.raises(pfa.CleanProductionRunUnavailable, match="H1_DSRA_INITIAL_FUNDING_NOT_CONVERGED"):
            pfa.run_clean_production(factory(), project_type=vertical, financing_policy=policy)


def test_an_exception_escaping_an_evaluation_is_never_reclassified():
    """No final authority exists for an evaluation that raised: its own error always stands.

    Even with a breach already recorded, the escaping exception (here an idempotence-style
    validation failure) propagates unchanged and unchained; the breach is never surfaced.
    """
    attempt = ma.OdrAttempt()
    evidence = ma.G2aShlMaturityEvidence()
    ctx = ma.ShlMaturityContext.provisional_pass()
    ctx.ledger.record(INJECTED)
    evidence.record_iteration(3, [("CAPACITY", ctx)], final=True)
    validation = RuntimeError("PR9_OUTER_G2A_IDEMPOTENCE_FAILED: residual=1.0 kEUR")
    with pytest.raises(RuntimeError) as info:
        with ma.odr_attempt(attempt):
            attempt.absorb_g2a(evidence, final=True, role="G2A", state=_FinancingState())
            raise validation
    assert info.value is validation and info.value.__cause__ is None
    with pytest.raises(RuntimeError, match="downstream failure"):
        with ma.odr_attempt(ma.OdrAttempt()):
            raise RuntimeError("downstream failure")
    assert ma.current_attempt() is None


def test_final_authority_requires_a_converged_g2a():
    with pytest.raises(RuntimeError, match="OD_R_FINAL_G2A_EVIDENCE_INCOMPLETE"):
        ma.OdrAttempt().absorb_g2a(ma.G2aShlMaturityEvidence(), final=True, role="G2A")
    with pytest.raises(RuntimeError, match="OD_R_EVIDENCE_REQUESTED_FOR_UNFINALIZED_OR_REJECTED_STATE"):
        attempt = ma.OdrAttempt()
        attempt.final_checks.append(ma.OdrFinalCheck("G2A.FINAL_CAPACITY", INJECTED))
        ma.summarize(attempt, [], ma.OdrFinalRequirements(("G2A",), True, "unit"))


def test_strict_resolve_replaces_the_funded_pass_as_final():
    evidence = ma.G2aShlMaturityEvidence()
    funded, strict = ma.ShlMaturityContext.provisional_pass(), ma.ShlMaturityContext.provisional_pass()
    funded.ledger.record(INJECTED)
    evidence.record_iteration(5, [("CAPACITY", ma.ShlMaturityContext.provisional_pass()),
                                  ("FUNDED", funded), ("STRICT", strict)], final=True)
    assert evidence.final_passes == [("CAPACITY", None), ("STRICT", None)]
    assert evidence.provisional_passes == [("FUNDED", 5, INJECTED)]


# ---------------------------------------------------------------------------- isolation / release-closed

def test_repeated_runs_and_run_scope_isolation(entries, admitted):
    again = _run(entries, ADMITTED, "odr")
    assert acc.flatten(again) == acc.flatten(admitted)
    assert ma.current_attempt() is None
    # A later canonical run of the same inputs is not affected by the OD-R evaluation.
    _reject(entries, ADMITTED, "canonical")


def test_policy_memo_never_shares_canonical_and_odr_results(entries):
    factory, vertical, _ = entries[ADMITTED]
    inputs = factory()
    odr_policy = acc.policy_for("odr", None)
    pfa.run_clean_production(inputs, project_type=vertical, financing_policy=odr_policy)
    assert len(pfa._POLICY_RUN_CACHE) == 1
    with pytest.raises(pfa.CleanProductionRunUnavailable, match=CODE):
        pfa.run_clean_production(inputs, project_type=vertical)
    assert len(pfa._POLICY_RUN_CACHE) == 1


def test_attempt_is_context_local_and_refuses_nesting():
    seen = []
    with ma.odr_attempt(ma.OdrAttempt()):
        worker = threading.Thread(target=lambda: seen.append(ma.current_attempt()))
        worker.start()
        worker.join()
        with pytest.raises(RuntimeError, match="OD_R_ATTEMPT_NESTING_REFUSED"):
            with ma.odr_attempt(ma.OdrAttempt()):
                pass
    assert seen == [None] and ma.current_attempt() is None


def test_default_policy_is_canonical_and_unknown_authority_fails_closed():
    assert gpp.DEFAULT_GENERIC_FINANCING_POLICY.shl_maturity_authority == ma.SHL_MATURITY_POLICY_CANONICAL
    assert gpp.DISABLED_GENERIC_FINANCING_POLICY.shl_maturity_authority == ma.SHL_MATURITY_POLICY_CANONICAL
    with pytest.raises(gpp.GenericFinancingPolicyError, match="H1_UNKNOWN_SHL_MATURITY_AUTHORITY"):
        gpp.GenericFinancingPolicy(shl_maturity_authority="od_r")


def test_no_product_path_can_select_the_odr_authority():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for base in ("app", "finco_app", "main_web.py", "main_api.py", "main_mcp.py"):
        path = root / base
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file in files:
            text = file.read_text(encoding="utf-8", errors="replace")
            if ("SHL_MATURITY_POLICY_OD_R" in text or "OD_R_FINAL_STATE_SHL_MATURITY_V1" in text
                    or "shl_maturity_authority=" in text or "financing_policy=" in text.replace(
                        "financing_policy=None", "")):
                offenders.append(str(file.relative_to(root)))
    # No product module passes a financing policy or names the OD-R authority; the production
    # authority only declares the defaulted (None -> canonical) parameter.
    assert offenders == [], offenders
    import inspect
    assert inspect.signature(pfa.run_clean_production).parameters["financing_policy"].default is None


def test_canonical_policy_evidence_type_and_fields_are_unchanged(feasible_pair):
    canonical, odr = feasible_pair
    assert [f.name for f in dc.fields(gpp.FinancingPolicyEvidence)] == [
        "authority", "construction_financing_applied", "cash_dsra_applied",
        "initial_dsra_funding_keur", "dsra_iterations", "dsra_residual_keur"]
    assert canonical.authority_metadata["financing_policy_authority"] == gpp.POLICY_AUTHORITY
    assert odr.authority_metadata["financing_policy_authority"] == gpp.POLICY_AUTHORITY
