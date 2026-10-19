"""Disabled V9 laboratory entry. No router, worker or normal Run imports this module.

Proposal timings are NOT accepted Run timings. Until skipped-state equivalence is
proved, guarded execution always re-decides through the original canonical Run.
"""
from __future__ import annotations

import dataclasses as dc
import hashlib
import math
import pickle
import time
from types import SimpleNamespace
from finco_core.inputs import ProjectInputs

from financial_engine.financing.generic_product_policy import (
    DEFAULT_GENERIC_FINANCING_POLICY, FinancingPolicyEvidence,
    apply_generic_financing_policy, _peak_forward_debt_service_keur,
)
from financial_engine.financing.v9_numerics import Anderson, JointSettings, ProposalRefused

ACTIVATION_ENABLED = False
FINANCIAL_PRECISION_APPROVED = False
INTERMEDIATE_FAILURE_EQUIVALENCE_PROVED = False
_FIELDS = ("senior_idc_keur", "senior_commitment_fee_keur", "structuring_fee_keur",
           "vat_idc_keur", "vat_commitment_fee_keur")


def require_production_activation():
    # No input, environment variable or registry field can enable this candidate.
    raise ProposalRefused("V9_PRODUCTION_ACTIVATION_CLOSED")


class JointContext:
    def __init__(self, inputs, policy, settings):
        self.inputs, self.policy = inputs, policy
        self.accelerator = Anderson(settings)
        self.funding = 0.
        self.residual = math.inf
        self.iterations = 0
        self.proposals = 0
        self.final_inputs = None

    def target(self, result):
        return _peak_forward_debt_service_keur(SimpleNamespace(financing_result=result)) * (
            int(self.inputs.financing.dsra_months) * 2 / 12.)

    def propose(self, costs, inner):
        if self.proposals >= self.accelerator.settings.maximum_iterations:
            raise ProposalRefused("V9_JOINT_BUDGET_EXHAUSTED")
        self.proposals += 1
        mapped = tuple(getattr(costs, name) for name in _FIELDS) + (self.target(inner),)
        vector, plain = self.accelerator.step(mapped)
        self.funding = vector[-1]
        applied, _, _ = apply_generic_financing_policy(
            self.inputs, self.policy, initial_dsra_keur=self.funding)
        if not plain:
            costs = dc.replace(costs, **dict(zip(_FIELDS, vector[:-1], strict=True)))
        return applied, costs, plain

    def observe(self, inner, iteration):
        self.iterations = iteration
        self.residual = abs(self.target(inner) - self.funding)
        if not math.isfinite(self.residual):
            raise ProposalRefused("V9_NONFINITE_DSRA_RESIDUAL")
        return self.residual <= self.policy.dsra_tolerance_keur


def _identity(inputs, source, base):
    return hashlib.sha256(pickle.dumps((inputs, source, base), protocol=5)).digest()


@dc.dataclass(frozen=True)
class FinancingBinding:
    identity: bytes
    result: object

    def consume(self, inputs, source, base, financing_income):
        if financing_income or _identity(inputs, source, base) != self.identity:
            raise ProposalRefused("V9_FINANCING_BINDING_MISMATCH")
        return self.result


def _proposal(inputs, policy, settings):
    from financial_engine.financing.project import _run_with_construction_idc
    from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
    from financial_engine.run_scope import engine_run_scope

    if type(inputs) is not ProjectInputs:
        raise ProposalRefused("V9_TYPED_EXTENSION_CANONICAL_ONLY")
    if getattr(inputs.info, "operating_calendar_policy", None) is not None:
        raise ProposalRefused("V9_QUARTERLY_CANONICAL_ONLY")
    if getattr(inputs, "cash_reserve_interest_policy", None) is not None:
        raise ProposalRefused("V9_U2_FINANCING_INCOME_CANONICAL_ONLY")
    applied, construction_on, dsra_on = apply_generic_financing_policy(inputs, policy)
    if not (construction_on and dsra_on):
        raise ProposalRefused("V9_REQUIRES_GENERIC_CONSTRUCTION_AND_DSRA")
    ctx = JointContext(inputs, policy, settings)
    source = "pr8_clean_production_authority"
    with engine_run_scope():
        financing = _run_with_construction_idc(
            project_inputs=applied, source_id=source, baseline_commit_sha="",
            outer_tolerance_keur=1e-7, outer_max_iterations=50, _v9_joint=ctx)
        if ctx.final_inputs is None:
            raise ProposalRefused("V9_FINAL_INPUTS_MISSING")
        binding = FinancingBinding(_identity(ctx.final_inputs, source, ""), financing)
        g2c = run_project_shareholder_waterfall_model(
            ctx.final_inputs, source_id=source, _v9_financing=binding)
        final_residual = abs(_peak_forward_debt_service_keur(g2c) * (
            int(inputs.financing.dsra_months) * 2 / 12.) - ctx.funding)
        if not math.isfinite(final_residual) or final_residual > policy.dsra_tolerance_keur:
            raise ProposalRefused("V9_FINAL_DSRA_ACCEPTANCE_FAILED")
    evidence = FinancingPolicyEvidence(
        "V9_DISABLED_NON_AUTHORITATIVE_JOINT_PROPOSAL", True, True,
        ctx.funding, 0, final_residual)
    details = {"joint_iterations": ctx.iterations, "anderson_steps": ctx.accelerator.accepted,
               "anderson_refusals": ctx.accelerator.refused, "joint_dsra_residual_keur": final_residual,
               "original_policy_iteration_count": "NOT_APPLICABLE_TO_JOINT_PROPOSAL"}
    return g2c, ctx.final_inputs, evidence, details


def evaluate_candidate(inputs, *, policy=None, project_type="", verify_canonical=True, settings=None):
    """Return a LAB proposal, or the canonically re-decided result, plus separate evidence.

    ``verify_canonical=False`` exists for OD-1 comparisons and raw proposal timings
    only. It is not a product admission flag and never changes normal Run dispatch.
    """
    from financial_engine.run_scope import engine_run_scope
    with engine_run_scope():
        return _evaluate_in_scope(inputs, policy=policy, project_type=project_type,
                                  verify_canonical=verify_canonical, settings=settings)


def _evaluate_in_scope(inputs, *, policy, project_type, verify_canonical, settings):
    from app.services import production_financial_authority as pfa
    if type(verify_canonical) is not bool:
        raise TypeError("V9_VERIFY_CANONICAL_MUST_BE_EXPLICIT_BOOL")
    policy = policy or DEFAULT_GENERIC_FINANCING_POLICY
    settings = settings or JointSettings()
    decision = pfa.classify_production_authority(inputs)
    details = {"production_activation": False, "precision_approved": False,
               "failure_equivalence_proved": False, "candidate_eligible": False,
               "canonical_validation_required": True}
    proposed = None
    start = time.perf_counter()
    if decision.promoted:
        try:
            g2c, applied, evidence, metrics = _proposal(inputs, policy, settings)
            proposed = pfa._assemble_clean_run(g2c, applied, inputs, "Base", decision, evidence)
            proposed.authority_metadata["runtime_authority"] = "V9_DISABLED_NON_AUTHORITATIVE_PROPOSAL"
            details.update(metrics, candidate_eligible=True)
        except Exception as error:
            # Every proposal refusal/error is re-decided by the complete original
            # algorithm, including successful-baseline cases. Nothing is approved.
            details["proposal_error"] = {"type": type(error).__qualname__, "text": str(error)}
    else:
        details["proposal_error"] = {"type": "AdmissionClosed", "text": decision.reason_code}
    details["proposal_seconds"] = time.perf_counter() - start
    if proposed is not None and not verify_canonical:
        details["result_kind"] = "NON_AUTHORITATIVE_PROPOSAL_ONLY"
        return proposed, details
    start = time.perf_counter()
    try:
        result = pfa.run_clean_production(inputs, project_type=project_type, financing_policy=policy)
    except Exception as error:
        details["canonical_seconds"] = time.perf_counter() - start
        error.v9_candidate_evidence = details
        raise
    details["canonical_seconds"] = time.perf_counter() - start
    details["result_kind"] = "CANONICAL_REDECISION"
    return result, details
