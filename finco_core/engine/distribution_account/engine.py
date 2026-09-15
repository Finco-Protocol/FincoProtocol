"""DistributionAccount engine — canonical cash routing after senior debt and SHL.

Audit-only: equity_distribution_paid_keur is now computed from gate evaluation,
but remains AUDIT-ONLY. Outputs are NOT routed to WaterfallEngine.distribution_keur
or Sponsor. R99/R102 remain BLOCKED per G1/G8 governance rules.
"""

from __future__ import annotations

from finco_core.engine.distribution_account.inputs import (
    CovenantGatePolicy,
    DistributionAccountInputs,
    DistributionAccountPeriodInput,
    R99R102GateInputs,
)
from finco_core.engine.distribution_account.result import (
    DistributionAccountResult,
    DistributionAccountPeriodResult,
    DistributionGateResult,
    R99InputResult,
    BLOCKED_REASONS,
)
from finco_core.engine.distribution_account.gates import (
    evaluate_r99_gate,
    evaluate_r102_gate,
    evaluate_dscr_gate,
    evaluate_lockup_gate,
    evaluate_reference_scope_guard,
    evaluate_covenant_gate_policy,
    evaluate_cash_gate,
)


class DistributionAccountEngine:
    """Canonical DistributionAccount engine.

    All outputs remain AUDIT-ONLY. Do NOT route production cashflows.
    R99/R102 remain BLOCKED per G1/G8 governance.
    """

    @staticmethod
    def compute(inputs: DistributionAccountInputs) -> DistributionAccountResult:
        """Compute DistributionAccount results across all periods.

        This is AUDIT-ONLY. All outputs are candidate values.
        No production cashflow routing occurs.
        """
        project_name = inputs.project_name
        period_results: list[DistributionAccountPeriodResult] = []

        total_equity_candidate = 0.0
        total_equity_paid = 0.0
        total_shl_sweep = 0.0
        total_retained = 0.0

        # Single canonical authority: run-level covenant gate policy from DistributionAccountInputs.
        covenant_gate_policy = inputs.covenant_gate_policy

        for period_input in inputs.period_inputs:
            result = DistributionAccountEngine._compute_period(period_input, covenant_gate_policy)
            period_results.append(result)

            total_equity_candidate += result.equity_distribution_candidate_keur
            total_equity_paid += result.equity_distribution_paid_keur
            total_shl_sweep += result.cash_swept_to_shl_keur
            total_retained += result.cash_retained_keur

        final_closing = (
            period_results[-1].closing_distribution_account_balance_keur
            if period_results else 0.0
        )

        return DistributionAccountResult(
            project_name=project_name,
            period_results=tuple(period_results),
            total_equity_distribution_candidate_keur=total_equity_candidate,
            total_equity_distribution_paid_keur=total_equity_paid,
            total_cash_swept_to_shl_keur=total_shl_sweep,
            total_cash_retained_keur=total_retained,
            final_closing_balance_keur=final_closing,
            is_reference_wind=inputs.is_reference_wind,
            is_reference_solar=inputs.is_reference_solar,
        )

    @staticmethod
    def _compute_period(
        inp: DistributionAccountPeriodInput,
        covenant_gate_policy: CovenantGatePolicy,
    ) -> DistributionAccountPeriodResult:
        """Compute DistributionAccount result for a single period.

        covenant_gate_policy is the run-level authority from DistributionAccountInputs,
        not derived from inp.is_reference_wind / inp.is_reference_solar.
        """
        opening_balance = inp.opening_distribution_account_balance_keur

        cash_for_dist = inp.post_shl_cash_available_keur
        if cash_for_dist < 0:
            cash_for_dist = 0.0

        # DSRA top-up assessment
        dsra_top_up = 0.0
        if inp.dsra_current_balance_keur < inp.dsra_required_balance_keur:
            shortfall = inp.dsra_required_balance_keur - inp.dsra_current_balance_keur
            dsra_top_up = min(shortfall, cash_for_dist)
            cash_for_dist -= dsra_top_up

        # Minimum cash reserve
        cash_retained = 0.0
        if cash_for_dist < inp.minimum_cash_reserve_keur:
            cash_retained = cash_for_dist
            cash_for_dist = 0.0

        # R99/R102 gate evaluation — controlled by CovenantGatePolicy (run-level authority).
        # R99_R102_NOT_APPLICABLE: bypass covenant family; results are non-blocking diagnostics.
        # R99_R102_APPLICABLE: evaluate normally using period mode flags.
        if covenant_gate_policy == CovenantGatePolicy.R99_R102_NOT_APPLICABLE:
            r99_gate = DistributionGateResult(
                gate_name="r99_gate",
                passed=True,
                blocked_reason="",
                details=("NOT_APPLICABLE_BY_COVENANT_POLICY",),
            )
            r102_gate = DistributionGateResult(
                gate_name="r102_gate",
                passed=True,
                blocked_reason="",
                details=("NOT_APPLICABLE_BY_COVENANT_POLICY",),
            )
        else:
            r99_gate = evaluate_r99_gate(
                inp.r99_gate_inputs,
                cash_for_dist,
                inp.enable_r99_r102_runtime,
                audit_economic_mode=inp.audit_economic_mode,
                runtime_economic_mode=inp.runtime_economic_mode,
            )
            r102_gate = evaluate_r102_gate(
                inp.r102_gate_inputs,
                cash_for_dist,
                inp.enable_r99_r102_runtime,
                audit_economic_mode=inp.audit_economic_mode,
                runtime_economic_mode=inp.runtime_economic_mode,
            )

        dscr_gate = evaluate_dscr_gate(inp.actual_dscr, inp.target_distribution_dscr)
        lockup_gate = evaluate_lockup_gate(
            period_index=inp.period_index,
            senior_tenor_years=inp.senior_tenor_years,
            dsra_balance=inp.dsra_current_balance_keur,
            dsra_target=inp.dsra_required_balance_keur,
            jdsra_balance=inp.jdsra_current_balance_keur,
            jdsra_target=inp.jdsra_required_balance_keur,
            cash=cash_for_dist,
        )
        cash_gate = evaluate_cash_gate(cash_for_dist)

        # DEPRECATED: generic_solar_reference_gate is diagnostic-only metadata; NOT a financial gate.
        # is_reference_solar does not affect financial output. Kept for backward-compatible logging.
        generic_solar_reference_gate = evaluate_reference_scope_guard(inp.is_reference_solar)

        # Covenant gate diagnostic — records the active policy for the period.
        covenant_gate = evaluate_covenant_gate_policy(covenant_gate_policy)

        equity_candidate = cash_for_dist

        # all_gates_passed: generic_solar_reference_gate intentionally excluded — is_reference_solar is not
        # a financial authority. covenant_gate always passes (policy is applied upstream
        # via R99/R102 bypass). Financial decision depends on R99/R102, DSCR, lockup, cash.
        all_gates_passed = (
            r99_gate.passed and
            r102_gate.passed and
            dscr_gate.passed and
            lockup_gate.passed and
            cash_gate.passed
        )
        equity_paid = equity_candidate if all_gates_passed else 0.0

        shl_sweep = 0.0
        closing_balance = opening_balance + cash_retained + dsra_top_up

        # blocked_reason: generic_solar_reference_gate intentionally excluded — not a financial authority.
        blocked = ""
        if not r99_gate.passed and r99_gate.blocked_reason:
            blocked = r99_gate.blocked_reason
        elif not r102_gate.passed and r102_gate.blocked_reason:
            blocked = r102_gate.blocked_reason
        elif not dscr_gate.passed:
            blocked = dscr_gate.blocked_reason
        elif not lockup_gate.passed:
            blocked = lockup_gate.blocked_reason
        elif not cash_gate.passed:
            blocked = cash_gate.blocked_reason

        warnings: list[str] = []
        if inp.enable_r99_r102_runtime:
            warnings.append("enable_r99_r102_runtime=True — audit-only mode warning")
        if inp.audit_economic_mode:
            warnings.append("audit_economic_mode=True — economic gate evaluation for audit only")
        if covenant_gate_policy == CovenantGatePolicy.R99_R102_NOT_APPLICABLE:
            warnings.append("covenant_gate_policy=NOT_APPLICABLE — R99/R102 bypassed as non-applicable")

        return DistributionAccountPeriodResult(
            period_index=inp.period_index,
            opening_distribution_account_balance_keur=opening_balance,
            closing_distribution_account_balance_keur=closing_balance,
            cash_available_for_distribution_keur=cash_for_dist,
            equity_distribution_candidate_keur=equity_candidate,
            equity_distribution_paid_keur=equity_paid,
            cash_swept_to_shl_keur=shl_sweep,
            cash_retained_keur=cash_retained,
            dsra_top_up_keur=dsra_top_up,
            r99_gate_result=r99_gate,
            r102_gate_result=r102_gate,
            dscr_gate_result=dscr_gate,
            lockup_gate_result=lockup_gate,
            generic_solar_reference_gate_result=generic_solar_reference_gate,
            covenant_gate_result=covenant_gate,
            blocked_reason=blocked,
            warnings=tuple(warnings),
        )



def compute_reference_covenant_input_period(
    *,
    revenue_keur: float,
    opex_keur: float,
    local_tax_keur: float,
    cash_interest_on_reserves_keur: float,
    corporate_tax_cash_keur: float,
    senior_ds_keur: float,
    dsra_release_or_funding_keur: float,
    junior_ds_keur: float,
    reserve_sweep_keur: float,
    previous_r100_carryforward_keur: float,
    year_index: int,
    senior_tenor_years: int,
    dscr: float,
    lockup_dscr: float,
    dsra_balance_keur: float,
    dsra_target_keur: float,
    jdsra_balance_keur: float,
    jdsra_target_keur: float,
) -> R99InputResult:
    """Compute one Generic Wind Reference spreadsheet-style R99/R102 SHL cash input period.

    `corporate_tax_cash_keur` is the cash tax paid in this period, not accrued
    full-year tax. Positive values reduce R69.
    """

    r69 = (
        revenue_keur
        - opex_keur
        + local_tax_keur
        + cash_interest_on_reserves_keur
        - corporate_tax_cash_keur
    )
    r84 = r69 - senior_ds_keur + dsra_release_or_funding_keur
    r98 = r84 + junior_ds_keur + reserve_sweep_keur + previous_r100_carryforward_keur

    reasons: list[str] = []
    if dscr < lockup_dscr:
        reasons.append("dscr_below_lockup")
    if year_index == 0:
        reasons.append("year_zero")
    if r98 < 0:
        reasons.append("negative_r98")
    if dsra_balance_keur < dsra_target_keur:
        reasons.append("dsra_below_target")
    if jdsra_balance_keur < jdsra_target_keur:
        reasons.append("jdsra_below_target")

    locked = year_index <= senior_tenor_years and bool(reasons)

    if locked:
        r99 = 0.0
        r100 = r98
    else:
        r99 = r98
        r100 = 0.0

    r102 = r99
    fcf_for_shl = max(0.0, r102)

    return R99InputResult(
        r69_fcf_banks_keur=r69,
        r84_fcf_junior_keur=r84,
        r98_distribution_account_keur=r98,
        r99_fcf_for_distribution_keur=r99,
        r100_carryforward_keur=r100,
        r102_fcf_for_shl_keur=r102,
        fcf_for_shl_keur=fcf_for_shl,
        locked=locked,
        lockup_reasons=tuple(reasons) if locked else (),
    )
