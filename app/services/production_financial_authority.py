"""Single production financial-calculation authority.

Production routes resolve canonical ProjectInputs, classify typed runtime
readiness, execute the clean financial engine exactly once when ready, and
adapt the result for presentation. Inputs that are not ready fail closed with
a typed reason and zero calculations. Classification is project-identity-free
and never falls back to a second financial engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProductionAuthorityClassification(str, Enum):
    """Typed readiness classification of a ProjectInputs snapshot."""

    CLEAN_PRODUCTION_READY = "CLEAN_PRODUCTION_READY"
    BLOCKED_BY_DEFERRED_TAX_CAPABILITY = "BLOCKED_BY_DEFERRED_TAX_CAPABILITY"
    BLOCKED_BY_TYPED_INPUT_GAP = "BLOCKED_BY_TYPED_INPUT_GAP"
    UNSUPPORTED_REFERENCE_CONTRACT = "UNSUPPORTED_REFERENCE_CONTRACT"


# Classification and runtime execution are separate concepts. A non-promoted
# classification is not a production runtime and always fails closed with
# zero financial calculations.
_RUNTIME_AUTHORITY_BY_CLASSIFICATION = {
    ProductionAuthorityClassification.CLEAN_PRODUCTION_READY: "clean_g2c",
    ProductionAuthorityClassification.BLOCKED_BY_DEFERRED_TAX_CAPABILITY: (
        "clean_not_ready"
    ),
    ProductionAuthorityClassification.BLOCKED_BY_TYPED_INPUT_GAP: (
        "clean_not_ready"
    ),
    ProductionAuthorityClassification.UNSUPPORTED_REFERENCE_CONTRACT: (
        "clean_not_ready"
    ),
}


@dataclass(frozen=True)
class AuthorityDecision:
    """Typed routing decision for one ProjectInputs snapshot."""

    classification: ProductionAuthorityClassification
    reason_code: str
    detail: str

    @property
    def runtime_authority(self) -> str:
        return _RUNTIME_AUTHORITY_BY_CLASSIFICATION[self.classification]

    @property
    def promoted(self) -> bool:
        return (
            self.classification
            is ProductionAuthorityClassification.CLEAN_PRODUCTION_READY
        )

    def to_metadata(self) -> dict:
        return {
            "classification": self.classification.value,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "runtime_authority": self.runtime_authority,
        }


class CleanProductionRunUnavailable(Exception):
    """Fail-closed error: the clean production route refused/could not run.

    Raised only when a CLEAN_PRODUCTION_READY-classified input fails inside
    the clean engine. NEVER caught to fall back to legacy — the caller must
    surface the typed reason.
    """

    def __init__(self, reason_code: str, detail: str):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class ProductionAuthorityResolutionError(Exception):
    """Fail-closed routing error (PR-8 correction pass).

    Raised when resolution/classification PLUMBING fails for a recognised
    production project (factory/validation/classifier exception), or when a
    diagnostic-only flag is requested on a clean-ready production route.
    NEVER interpreted as permission to use the legacy engine — zero legacy
    financial calls may follow this error.
    """

    def __init__(self, reason_code: str, detail: str):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class CleanNotReadyError(Exception):
    """Phase B1 typed fail-closed: production project is not clean-promoted.

    Raised by the production router (run_project / execute_production_demo)
    when classify_production_authority() returns a non-promoted decision and
    the request arrived through a production route.

    This is the ONLY typed signal a production route emits for a non-promoted
    project — there is no legacy fallthrough (Phase B4: no production legacy
    engine exists; no alternative runtime is permitted).

    Attributes:
        classification: ProductionAuthorityClassification value (str)
        reason_code:    machine-readable blocker token
        detail:         human-readable explanation
        runtime_authority: always "clean_not_ready"
        calculation_count: always 0
    """

    def __init__(
        self,
        *,
        classification: str,
        reason_code: str,
        detail: str,
        runtime_authority: str = "clean_not_ready",
        calculation_count: int = 0,
    ):
        super().__init__(f"{reason_code}: {detail}")
        self.classification = classification
        self.reason_code = reason_code
        self.detail = detail
        self.runtime_authority = runtime_authority
        self.calculation_count = calculation_count

    def to_metadata(self) -> dict:
        return {
            "classification": self.classification,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "runtime_authority": self.runtime_authority,
            "calculation_count": self.calculation_count,
        }


def classify_production_authority(project_inputs) -> AuthorityDecision:
    """Classify a canonical ProjectInputs snapshot for production routing.

    Typed-field checks only; no project identity, no engine execution.
    Check order = depth of the deferred capability:
      1. clean cash-tax timing opt-in (deferred tax capability — the deep
         Generic Wind Reference-class blocker, closes with Country Tax Template work);
      2. explicit G2A financing contract fields (typed-input gap);
      3. unsupported compatibility-only financing flags.
    """
    tax = project_inputs.tax
    if not bool(getattr(tax, "clean_cash_tax_timing_enabled", False)):
        return AuthorityDecision(
            classification=(
                ProductionAuthorityClassification.BLOCKED_BY_DEFERRED_TAX_CAPABILITY
            ),
            reason_code="CLEAN_RUNTIME_TAX_POLICY_NOT_READY",
            detail=(
                "tax.clean_cash_tax_timing_enabled is not opted in: the clean "
                "cash-tax timing contract (TAX_YEAR_LAST_PERIOD, lag=0) is not "
                "typed-verified for this project. Deferred to the Country Tax "
                "Template stage. Until then this contract is not "
                "registered for production execution."
            ),
        )

    financing = project_inputs.financing
    if getattr(financing, "sponsor_funding_mode", None) is None or (
        getattr(financing, "gearing_basis_mode", None) is None
    ):
        return AuthorityDecision(
            classification=ProductionAuthorityClassification.BLOCKED_BY_TYPED_INPUT_GAP,
            reason_code="FINANCING_CONTRACT_FIELDS_NOT_TYPED",
            detail=(
                "financing.sponsor_funding_mode / financing.gearing_basis_mode "
                "are not explicitly configured, so the canonical G2A financing "
                "stack contract (run_project_financing_model) fails closed "
                "(SPONSOR_FUNDING_MODE_EXPLICIT_INPUT_REQUIRED). This "
                "contract is not registered for production execution until "
                "the required typed financing fields are configured and "
                "reviewed; production returns zero calculations. Historical "
                "no alternate runtime is permitted."
            ),
        )

    if bool(
        getattr(financing, "use_frozen_excel_senior_debt_schedule", False)
    ) or bool(getattr(financing, "use_shl_fcf_waterfall_engine", False)):
        return AuthorityDecision(
            classification=ProductionAuthorityClassification.UNSUPPORTED_REFERENCE_CONTRACT,
            reason_code="UNSUPPORTED_REFERENCE_CONTRACT_ACTIVE",
            detail=(
                "This ProjectInputs snapshot contains historical "
                "frozen-calibration markers (reference-policy senior debt "
                "service / SHL FCF waterfall flags) and is not registered "
                "for production execution. Production returns zero "
                "calculations (clean_not_ready). Historical calibration "
                "evidence is available offline only."
            ),
        )

    return AuthorityDecision(
        classification=ProductionAuthorityClassification.CLEAN_PRODUCTION_READY,
        reason_code="CLEAN_TYPED_CONTRACT_READY",
        detail=(
            "typed ProjectInputs satisfy the clean G2A/G2C contract; production "
            "financials are computed once by "
            "run_project_shareholder_waterfall_model."
        ),
    )


@dataclass
class CleanProductionRun:
    """One clean production calculation and its lineage metadata.

    Canonical complete production-run artifact.
    Owns the downstream C3 statement assembly result (assembled EXACTLY
    once here, downstream of the single clean G2C execution) so the
    presentation layer stays a pure pass-through.
    """

    g2c_result: object
    project_inputs: object          # effective inputs (scenario applied)
    base_project_inputs: object     # inputs before scenario mutation
    scenario: str
    decision: AuthorityDecision
    authority_metadata: dict = field(default_factory=dict)
    financial_statements_result: object | None = None


def run_clean_production(
    project_inputs,
    scenario: str = "Base",
    *,
    project_type: str = "",
) -> CleanProductionRun:
    """Execute the ONE clean production financial calculation.

    Applies the shared scenario mutation (same ScenarioManager authority the
    legacy runtime uses), then runs the canonical G2C entry point exactly
    once. Fail closed: engine errors propagate as CleanProductionRunUnavailable
    with a typed reason — never a legacy fallback.
    """
    decision = classify_production_authority(project_inputs)
    if not decision.promoted:
        raise CleanProductionRunUnavailable(
            reason_code=decision.reason_code,
            detail=(
                f"classification={decision.classification.value}; "
                "run_clean_production may not execute a non-promoted input "
                "(no silent legacy fallback exists at this seam)."
            ),
        )

    effective_inputs = project_inputs
    if scenario != "Base":
        from app.scenario_manager import ScenarioManager

        # Same shared scenario authority and registry key as the legacy
        # runtime (ui_runner passes project_type.lower()) — identical
        # multipliers, identical mutation semantics.
        mgr = ScenarioManager((project_type or "").lower())
        effective_inputs = mgr.apply_overrides(project_inputs, scenario)

    from financial_engine.shareholder_waterfall import (
        run_project_shareholder_waterfall_model,
    )

    try:
        g2c = run_project_shareholder_waterfall_model(
            effective_inputs, source_id="pr8_clean_production_authority"
        )
    except CleanProductionRunUnavailable:
        raise
    except Exception as exc:  # fail closed — never fall back to legacy
        raise CleanProductionRunUnavailable(
            reason_code="PR8_CLEAN_ENGINE_FAIL_CLOSED",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    metadata = decision.to_metadata() | {
        "clean_entry_point": (
            "financial_engine.shareholder_waterfall."
            "run_project_shareholder_waterfall_model"
        ),
        "scenario": scenario,
        "calculation_count": 1,
    }
    construction = getattr(g2c.financing_result, "construction_financing", None)
    if construction is not None:
        metadata.update(
            construction_authority=construction.authority,
            vat_facility_authority=construction.vat_authority,
            vat_facility_commitment_mode=construction.vat_commitment_mode,
            vat_effective_commitment_keur=construction.vat_effective_commitment_keur,
        )
    # Phase C3 Correction A: assemble the clean financial statements here,
    # EXACTLY once, downstream of the single G2C execution. The
    # presentation adapter only passes this result through. Assembly errors
    # propagate (fail closed) — never silently swallowed into a None.
    from financial_engine.financial_statements import (
        assemble_decision_complete_financial_statements,
    )
    financial_statements_result = assemble_decision_complete_financial_statements(
        g2c, effective_inputs
    )

    return CleanProductionRun(
        g2c_result=g2c,
        project_inputs=effective_inputs,
        base_project_inputs=project_inputs,
        scenario=scenario,
        decision=decision,
        authority_metadata=metadata,
        financial_statements_result=financial_statements_result,
    )
