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

    Raised when the clean authority cannot execute or safely publish an input,
    including unsupported terminal liabilities. NEVER caught to fall back to
    legacy -- the caller must surface the typed reason.
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
    # Developer Economics V1: separate developer-ledger result (financial_engine.
    # developer_economics), computed ONCE here from the effective inputs. None when
    # Developer Economics is absent or disabled. Presentation layers pass it through.
    developer_economics_result: object | None = None


_POLICY_RUN_CACHE: "dict[str, tuple]" = {}
_POLICY_RUN_CACHE_MAX = 16


def _memoised_policy_run(effective_inputs, policy, compute):
    """Deterministic in-process memo of the policy-wrapped engine run.

    The engine is a pure function of (inputs, policy); the H-1 fixed points make one run
    cost several engine evaluations, so identical repeat runs (same process) reuse the
    result. Keyed by a digest of the full input/policy representation; bounded.
    """
    import hashlib

    import financial_engine.orchestrator as _orch
    import financial_engine.senior_debt.solver as _solver
    import financial_engine.shl.production as _shl

    # Engine callables are part of the key so a patched/replaced engine never reads a
    # result computed by a different implementation.
    engine_identity = tuple(
        id(getattr(module, name, None))
        for module, name in (
            (_solver, "_backward_dscr_capacity"),
            (_solver, "_solve_dscr"),
            (_solver, "_solve_combined"),
            (_shl, "compute_shareholder_loan_schedules"),
            (_orch, "compute_shareholder_loan_schedules"),
            (_orch, "run_project_model"),
        )
    )
    key = hashlib.sha256(
        (repr(effective_inputs) + "|" + repr(policy) + "|" + repr(engine_identity)).encode("utf-8")
    ).hexdigest()
    hit = _POLICY_RUN_CACHE.get(key)
    if hit is not None:
        return hit
    value = compute()
    if len(_POLICY_RUN_CACHE) >= _POLICY_RUN_CACHE_MAX:
        _POLICY_RUN_CACHE.pop(next(iter(_POLICY_RUN_CACHE)))
    _POLICY_RUN_CACHE[key] = value
    return value


def _require_settled_senior_maturity(g2c, project_inputs) -> None:
    """Reject unsupported maturity liabilities before publishing any new result.

    Solver permission to retain a balloon is not settlement authority. Reuse
    its existing absolute precision contract, without changing any balance,
    terminal classification or downstream (stricter) Integrity verdict.
    """
    from math import isfinite

    from app.run_integrity.contracts import TOL_KEUR
    from financial_engine.project_returns.contracts import DebtTerminalStatus
    from financial_engine.project_returns.model import _TOL as terminal_precision_keur
    from financial_engine.senior_debt.project_adapter import (
        build_senior_debt_contract_from_project_inputs,
    )

    def invalid(detail):
        raise CleanProductionRunUnavailable("SENIOR_MATURITY_EVIDENCE_INVALID", detail)

    def balance(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid("Senior maturity balances must be numeric, not missing or coerced.")
        if not isfinite(value) or value < 0:
            invalid("Senior maturity balances must be finite and nonnegative.")
        return value

    try:
        model = g2c.financing_result.project_model_result
        senior = model.senior_debt
        terminal = g2c.return_summary.terminal.senior
        policy, _ = build_senior_debt_contract_from_project_inputs(
            project_inputs, model.periods,
        )
        expected = tuple(
            p.period_index for p in model.periods
            if p.is_operation and policy.repayment_start_period_index
            <= p.period_index <= policy.maturity_period_index
        )
        indices = tuple(senior.period_indices)
        if (
            not expected or indices != expected
            or any(type(i) is not int for i in indices)
            or tuple(model.axis_contract.senior_axis) != expected
            or len(set(indices)) != len(indices)
            or indices[-1] != policy.maturity_period_index
        ):
            invalid("Senior schedule, contractual maturity and canonical axis do not align.")
        for name in (
            "senior_debt_opening_keur", "senior_principal_keur",
            "senior_debt_closing_keur", "senior_interest_keur", "senior_debt_service_keur",
        ):
            vector = getattr(senior, name)
            if len(vector) != len(indices):
                invalid(f"Senior {name} is incomplete for the contractual axis.")
            for value in vector:
                balance(value)
        outstanding = balance(senior.senior_debt_closing_keur[-1])
        debt_size = balance(senior.debt_size_keur)
        prior = debt_size
        for opening, principal, closing, interest, service in zip(
            senior.senior_debt_opening_keur, senior.senior_principal_keur,
            senior.senior_debt_closing_keur, senior.senior_interest_keur,
            senior.senior_debt_service_keur, strict=True,
        ):
            # Audit existing amounts, never repair them or calculate a new schedule.
            if (
                abs(opening - prior) > TOL_KEUR
                or principal > opening + TOL_KEUR
                or abs(opening - principal - closing) > TOL_KEUR
                or abs(service - interest - principal) > TOL_KEUR
            ):
                invalid("Senior canonical repayment/debt-service roll-forward is inconsistent.")
            prior = closing
        commitment = balance(g2c.financing_result.final_senior_commitment_keur)
        if abs(debt_size - commitment) > TOL_KEUR:
            invalid("Senior opening debt differs from the canonical funded commitment.")
        terminal_balance = balance(terminal.balance_at_contractual_maturity_keur)
        horizon_balance = balance(terminal.terminal_model_horizon_balance_keur)
        if terminal.status == DebtTerminalStatus.NOT_APPLICABLE:
            # The canonical terminal authority treats microscopic funding under
            # its own precision as inapplicable, not only literal zero funding.
            if debt_size > terminal_precision_keur or max(
                senior.senior_debt_opening_keur + senior.senior_principal_keur
                + senior.senior_debt_closing_keur + (terminal_balance, horizon_balance),
            ) > terminal_precision_keur:
                invalid("Senior NOT_APPLICABLE cannot conceal a funded liability.")
            if terminal.contractual_maturity_period_index is not None or terminal.contractual_maturity_date is not None:
                invalid("Senior NOT_APPLICABLE has inconsistent contractual maturity evidence.")
        else:
            # Applicable terminal values are exact copies of the canonical closing
            # value. NOT_APPLICABLE above legitimately reports numerical zeros.
            if outstanding != terminal_balance or outstanding != horizon_balance:
                invalid("Senior terminal evidence differs from the actual maturity closing balance.")
            maturity = terminal.contractual_maturity_period_index
            period = next(p for p in model.periods if p.period_index == indices[-1])
            if (
                type(maturity) is not int or maturity != indices[-1]
                or terminal.contractual_maturity_date != period.period_end
                or terminal.status not in (
                    DebtTerminalStatus.REPAID, DebtTerminalStatus.OUTSTANDING_AT_MATURITY,
                )
            ):
                invalid("Senior terminal maturity/date/status authority is missing or inconsistent.")
        tolerance = policy.convergence_tolerance_keur
        if not isfinite(tolerance) or tolerance < 0:
            invalid("Canonical Senior absolute precision authority is invalid.")
    except CleanProductionRunUnavailable:
        raise
    except (AttributeError, TypeError, ValueError, StopIteration) as exc:
        invalid(f"Senior maturity evidence is incomplete or invalid: {type(exc).__name__}: {exc}")

    if outstanding > tolerance:
        raise CleanProductionRunUnavailable(
            "SENIOR_MATURITY_UNSETTLED_LIABILITY",
            f"contractual_maturity_period={indices[-1]}; "
            f"outstanding_principal_keur={outstanding!r}; "
            "unsupported terminal balloon treatment: no complete canonical "
            "settlement/refinancing/accounting authority exists.",
        )


def run_clean_production(
    project_inputs,
    scenario: str = "Base",
    *,
    project_type: str = "",
    financing_policy=None,
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

    from financial_engine.financing.generic_product_policy import (
        DEFAULT_GENERIC_FINANCING_POLICY,
        run_with_generic_financing_policy,
    )
    from financial_engine.shareholder_waterfall import (
        run_project_shareholder_waterfall_model,
    )

    from financial_engine.run_scope import engine_run_scope

    policy = DEFAULT_GENERIC_FINANCING_POLICY if financing_policy is None else financing_policy
    try:
        # H-1: apply the project's declared construction financing (IDC, commitment
        # and structuring fees) and DSRA policy. One production calculation; the
        # policy owns the initial-DSRA fixed point around the single engine entry.
        with engine_run_scope():
            g2c, effective_inputs, policy_evidence = _memoised_policy_run(
                effective_inputs,
                policy,
                lambda: run_with_generic_financing_policy(
                    effective_inputs,
                    lambda applied: run_project_shareholder_waterfall_model(
                        applied, source_id="pr8_clean_production_authority"
                    ),
                    policy,
                ),
            )
    except CleanProductionRunUnavailable:
        raise
    except Exception as exc:  # fail closed — never fall back to legacy
        raise CleanProductionRunUnavailable(
            reason_code="PR8_CLEAN_ENGINE_FAIL_CLOSED",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    _require_settled_senior_maturity(g2c, effective_inputs)

    metadata = decision.to_metadata() | {
        "clean_entry_point": (
            "financial_engine.shareholder_waterfall."
            "run_project_shareholder_waterfall_model"
        ),
        "scenario": scenario,
        "calculation_count": 1,
        "financing_policy_authority": policy_evidence.authority,
        "construction_financing_applied": policy_evidence.construction_financing_applied,
        "cash_dsra_applied": policy_evidence.cash_dsra_applied,
        "initial_dsra_funding_keur": policy_evidence.initial_dsra_funding_keur,
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

    from financial_engine.developer_economics.model import compute_developer_economics

    return CleanProductionRun(
        g2c_result=g2c,
        project_inputs=effective_inputs,
        base_project_inputs=project_inputs,
        scenario=scenario,
        decision=decision,
        authority_metadata=metadata,
        financial_statements_result=financial_statements_result,
        developer_economics_result=compute_developer_economics(effective_inputs),
    )
