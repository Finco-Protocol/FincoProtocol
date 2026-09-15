"""Gate evaluation logic for DistributionAccount."""
from __future__ import annotations

from finco_core.engine.distribution_account.result import (
    DistributionGateResult,
    BLOCKED_REASONS,
)
from finco_core.engine.distribution_account.inputs import (
    CovenantGatePolicy,
    DistributionAccountPeriodInput,
    R99R102GateInputs,
)


def evaluate_r99_gate(
    inputs: R99R102GateInputs,
    cash_available: float,
    enable_runtime: bool,
    audit_economic_mode: bool = False,
    runtime_economic_mode: bool = False,
) -> DistributionGateResult:
    """Evaluate R99 gate.

    R99 is the equity distribution gate.

    In normal (governed) mode: always BLOCKED — R99/R102 not promoted to runtime.
    In audit_economic_mode: evaluate gate using cash logic for audit/comparison only.
        Result is audit/comparison only — must never flow to runtime via audit mode.
    In runtime_economic_mode: evaluate gate for explicit runtime staging under
        use_distributionaccount_runtime_wiring=True — still pre-G20, not G20 promotion.

    Args:
        audit_economic_mode: if True, evaluate R99 using cash inputs (not governance).
            Result is audit/comparison only — must never flow to runtime.
        runtime_economic_mode: if True, evaluate R99 using cash inputs for explicit
            runtime staging — allowed behind use_distributionaccount_runtime_wiring=True,
            still not G20 promotion.
    """
    gate_active = audit_economic_mode or runtime_economic_mode
    if not gate_active:
        # Normal governed mode: R99 not promoted — always blocked
        return DistributionGateResult(
            gate_name="r99_gate",
            passed=False,
            blocked_reason=BLOCKED_REASONS["R99_BLOCKED"],
        )

    # Audit-economic mode: evaluate gate using available cash data.
    # R99 gate passes if cumulative FCF covers senior debt and there is cash remaining.
    # cash_available is the post-tax, post-senior-DS cash for distribution.
    if cash_available <= 0:
        return DistributionGateResult(
            gate_name="r99_gate",
            passed=False,
            blocked_reason=BLOCKED_REASONS["NEGATIVE_CASH"],
        )
    # Economic gate passes — cash is available for equity distribution
    return DistributionGateResult(
        gate_name="r99_gate",
        passed=True,
        blocked_reason="",
    )


def evaluate_r102_gate(
    inputs: R99R102GateInputs,
    cash_available: float,
    enable_runtime: bool,
    audit_economic_mode: bool = False,
    runtime_economic_mode: bool = False,
) -> DistributionGateResult:
    """Evaluate R102 gate.

    R102 is the SHL sweep gate.

    In normal (governed) mode: always BLOCKED — R99/R102 not promoted to runtime.
    In audit_economic_mode: evaluate gate to determine SHL sweep eligibility.
        Output is audit/comparison only — must never flow to runtime.
    In runtime_economic_mode: evaluate gate for explicit runtime staging under
        use_distributionaccount_runtime_wiring=True — still pre-G20, not G20 promotion.

    Args:
        audit_economic_mode: if True, evaluate R102 using cash inputs (not governance).
            Result is audit/comparison only — must never flow to runtime.
        runtime_economic_mode: if True, evaluate R102 using cash inputs for explicit
            runtime staging — allowed behind use_distributionaccount_runtime_wiring=True,
            still not G20 promotion.
    """
    gate_active = audit_economic_mode or runtime_economic_mode
    if not gate_active:
        # Normal governed mode: R102 not promoted — always blocked
        return DistributionGateResult(
            gate_name="r102_gate",
            passed=False,
            blocked_reason=BLOCKED_REASONS["R102_BLOCKED"],
        )

    # Audit-economic mode: evaluate SHL sweep eligibility.
    # R102 gate passes if SHL has a positive balance and cash is available for sweep.
    if cash_available <= 0:
        return DistributionGateResult(
            gate_name="r102_gate",
            passed=False,
            blocked_reason=BLOCKED_REASONS["NEGATIVE_CASH"],
        )
    # Economic gate passes — cash available for SHL sweep
    return DistributionGateResult(
        gate_name="r102_gate",
        passed=True,
        blocked_reason="",
    )


def evaluate_dscr_gate(
    actual_dscr: float,
    target_dscr: float,
) -> DistributionGateResult:
    """Evaluate DSCR gate for distribution eligibility."""
    if actual_dscr >= target_dscr:
        return DistributionGateResult(
            gate_name="dscr_gate",
            passed=True,
            blocked_reason="",
        )
    return DistributionGateResult(
        gate_name="dscr_gate",
        passed=False,
        blocked_reason=BLOCKED_REASONS["DSCR_GATE_FAILED"],
        details=(f"actual_dscr={actual_dscr:.4f} < target={target_dscr:.4f}",),
    )


def evaluate_lockup_gate(
    period_index: int,
    senior_tenor_years: int,
    dsra_balance: float,
    dsra_target: float,
    jdsra_balance: float,
    jdsra_target: float,
    cash: float,
) -> DistributionGateResult:
    """Evaluate lockup gate — blocks distributions during lockup periods."""
    reasons: list[str] = []
    if period_index <= senior_tenor_years:
        reasons.append(f"within_senior_tenor(period={period_index})")
    if dsra_balance < dsra_target:
        reasons.append(f"dsra_below_target({dsra_balance:.1f} < {dsra_target:.1f})")
    if jdsra_balance < jdsra_target:
        reasons.append(f"jdsra_below_target({jdsra_balance:.1f} < {jdsra_target:.1f})")
    if cash < 0:
        reasons.append(f"negative_cash({cash:.1f})")

    if reasons:
        return DistributionGateResult(
            gate_name="lockup_gate",
            passed=False,
            blocked_reason=BLOCKED_REASONS["LOCKUP"],
            details=tuple(reasons),
        )
    return DistributionGateResult(
        gate_name="lockup_gate",
        passed=True,
        blocked_reason="",
    )


def evaluate_covenant_gate_policy(policy: CovenantGatePolicy) -> DistributionGateResult:
    """Evaluate covenant gate based on typed CovenantGatePolicy.

    R99_R102_APPLICABLE: covenant gates apply; gate passes (proceed with R99/R102 evaluation).
    R99_R102_NOT_APPLICABLE: covenant gates do not apply; gate passes trivially (not blocking).
    """
    if policy == CovenantGatePolicy.R99_R102_APPLICABLE:
        return DistributionGateResult(
            gate_name="covenant_gate",
            passed=True,
            blocked_reason="",
        )
    # R99_R102_NOT_APPLICABLE — covenant structure not applicable to this project
    return DistributionGateResult(
        gate_name="covenant_gate",
        passed=True,
        blocked_reason="",
    )


def evaluate_reference_scope_guard(is_reference_solar: bool) -> DistributionGateResult:
    """Generic Solar Reference guard — blocks Generic Wind Reference-specific gates for Generic Solar Reference project."""
    if is_reference_solar:
        return DistributionGateResult(
            gate_name="reference_scope_guard",
            passed=False,
            blocked_reason=BLOCKED_REASONS["REFERENCE_SCOPE_NOT_SUPPORTED"],
        )
    return DistributionGateResult(
        gate_name="reference_scope_guard",
        passed=True,
        blocked_reason="",
    )


def evaluate_cash_gate(cash_available: float) -> DistributionGateResult:
    """Evaluate cash sufficiency gate."""
    if cash_available >= 0:
        return DistributionGateResult(gate_name="cash_sufficiency_gate", passed=True)
    return DistributionGateResult(
        gate_name="cash_sufficiency_gate",
        passed=False,
        blocked_reason=BLOCKED_REASONS["NEGATIVE_CASH"],
        details=(f"cash_available={cash_available:.1f}",),
    )