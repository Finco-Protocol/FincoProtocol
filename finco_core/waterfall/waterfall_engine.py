"""Full Financial Waterfall - Senior Debt + SHL + DSRA + Lockup.

This module computes the complete cash flow waterfall:
1. Revenue - OPEX = EBITDA
2. EBITDA - Tax = CF after tax
3. CF - Senior Debt Service = CF to SHL
4. CF - SHL Service = CF after debt
5. CF after debt - DSRA funding = Cash available
6. Lockup check → Distribution
7. SHL cash sweep → Senior debt prepayment

Handles:
- Iterative debt sculpting (DSCR-based)
- Lockup (DSCR < 1.10 blocks distributions)
- DSRA reserve account
- SHL (subordinated hybrid loan)
- Cash sweep to senior debt
"""
from dataclasses import dataclass, field, replace
from typing import Optional
from datetime import date

from finco_core.debt.sculpting_iterative import (
    iterative_sculpt_debt, IterativeSculptResult,
    closed_form_sculpt, ClosedFormSculptResult,
    dsra_rolling_target, dsra_update,
    cash_sweep,
)
from finco_core.debt.schedule import senior_debt_amount
from finco_core.sponsor.xirr import xirr, xnpv
from finco_core.sponsor.sponsor_cashflows import build_sponsor_cashflows
from finco_core.engine.period_engine import hash_engine_for_cache
from finco_core.tax.engine import atad_adjustment
from finco_core.engine.distribution_account import compute_reference_covenant_input_period
from finco_core.shl.fcf_waterfall import compute_shl_fcf_waterfall_period
from finco_core.inputs.senior_sculpting import (
    SeniorSculptingMode,
    validate_explicit_debt_service_schedule,
)
from finco_core.waterfall.shl_engine import compute_shl_period_v3
from finco_core.waterfall.tax_engine import compute_period_tax, TaxPeriodResult
from utils.logging_config import get_logger

_log = get_logger(__name__)  # Module-level logger (defined once, not per-function)


@dataclass
class WaterfallPeriod:
    """Single period in the waterfall."""
    period: int
    date: date
    year_index: int
    period_in_year: int  # 1=H1, 2=H2 (for semi-annual model)
    is_operation: bool  # True if this is an operation period
    # Revenue section
    generation_mwh: float
    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    # Tax section
    depreciation_keur: float
    interest_senior_keur: float
    interest_shl_keur: float
    taxable_profit_keur: float
    tax_keur: float
    # After tax
    cf_after_tax_keur: float
    # Debt service
    senior_interest_keur: float
    senior_principal_keur: float
    senior_ds_keur: float
    shl_interest_keur: float
    shl_principal_keur: float
    shl_service_keur: float
    # Reserves
    dsra_contribution_keur: float
    dsra_balance_keur: float
    mra_contribution_keur: float
    mra_balance_keur: float
    # CF available
    cf_after_reserves_keur: float
    # Covenant checks
    dscr: float
    llcr: float
    plcr: float
    lockup_active: bool
    # Distribution
    distribution_keur: float
    cash_sweep_keur: float
    cum_distribution_keur: float
    # Cash balance
    cash_balance_keur: float
    # SHL balance (for tracking PIK accumulation)
    shl_balance_keur: float = 0.0  # Closing SHL balance after PIK capitalization
    shl_pik_keur: float = 0.0  # PIK amount capitalized this period
    shl_gross_accrued_interest_keur: float = 0.0  # Audit-only gross accrued SHL interest for P&L R27 bridge
    # Debt schedule tracking (for financial statements)
    senior_balance_keur: float = 0.0  # Closing balance after principal payment
    # Phase 7F C1d audit-only R99/R102 bridge fields. These values do not feed
    # runtime cash routing, SHL service, senior debt, tax, or distributions.
    corporate_tax_cash_keur: float = field(
        default=0.0,
        metadata={
            "sign": "positive cash tax paid in the period",
            "basis": "current Python H2-only cash-tax timing: tax_keur in H2, 0 in H1",
        },
    )
    r67_excel_style_cash_tax_diagnostic_keur: float = field(
        default=0.0,
        metadata={
            "sign": "negative cash tax outflow, matching Excel CF R67 convention",
            "basis": "audit-only annual H2 pairing: -(current tax_keur + previous period tax_keur) in H2, 0 in H1",
        },
    )
    # Phase 6 audit-only tax-basis bridge fields. These values expose inputs and
    # outputs already used by compute_period_tax; they do not feed runtime cashflows.
    # Phase 9C: Audit metadata for DA runtime wiring.
    # Set when use_distributionaccount_runtime_wiring=True.
    legacy_distribution_keur: float = 0.0  # Original runtime distribution before override
    da_paid_distribution_keur: float = 0.0  # DA equity_distribution_paid_keur
    distribution_source: str = ""  # "runtime" or "distribution_account"
    distribution_wiring_delta_keur: float = 0.0  # da - legacy for audit
    tax_depreciation_audit_keur: float = 0.0
    fiscal_reintegration_audit_keur: float = 0.0
    taxable_income_before_losses_audit_keur: float = 0.0
    tax_loss_opening_audit_keur: float = 0.0
    tax_loss_used_audit_keur: float = 0.0
    tax_loss_closing_audit_keur: float = 0.0
    taxable_profit_after_losses_audit_keur: float = 0.0
    cit_accrual_audit_keur: float = 0.0
    cash_tax_current_period_audit_keur: float = 0.0
    cash_tax_bridge_reconciliation_keur: float = 0.0
    cash_tax_excel_style_h2_diagnostic_keur: float = 0.0
    r69_fcf_banks_keur: float = 0.0
    r84_fcf_junior_keur: float = 0.0
    r98_distribution_account_keur: float = 0.0
    r99_fcf_for_distribution_keur: float = 0.0
    r100_carryforward_keur: float = 0.0
    r102_fcf_for_shl_keur: float = 0.0
    fcf_for_shl_keur: float = 0.0


@dataclass
class WaterfallResult:
    """Complete waterfall with all periods."""
    periods: list[WaterfallPeriod] = field(default_factory=list)
    # Summary
    total_revenue_keur: float = 0
    total_opex_keur: float = 0
    total_ebitda_keur: float = 0
    total_tax_keur: float = 0
    total_senior_ds_keur: float = 0
    total_shl_service_keur: float = 0
    total_distribution_keur: float = 0
    # Metrics
    avg_dscr: float = 0
    min_dscr: float = 0
    max_dscr: float = 0
    min_llcr: float = 0
    min_plcr: float = 0
    periods_in_lockup: int = 0
    # Returns
    project_irr: float = 0
    equity_irr: float = 0
    sponsor_irr: float = 0
    project_npv: float = 0
    equity_npv: float = 0
    # Sculpting
    sculpting_result: Optional[IterativeSculptResult] = None
    # DSCR reconciliation
    target_dscr: float = 0.0   # Target DSCR from financing inputs
    actual_min_dscr: float = 0.0  # Actual minimum DSCR achieved
    actual_avg_dscr: float = 0.0  # Actual average DSCR achieved
    project_code: str = ""
    use_shl_gross_accrued_for_pnl: bool = False
    # Phase 9C: Audit metadata for DA runtime wiring.
    # Set when use_distributionaccount_runtime_wiring=True.
    legacy_distribution_keur: float = 0.0
    da_paid_distribution_keur: float = 0.0
    distribution_source: str = ""
    distribution_wiring_delta_keur: float = 0.0


def compute_ebitda_schedule(
    revenue_schedule: dict[int, float],
    opex_schedule: dict[int, float],
    periods: list,
) -> list[float]:
    """Build EBITDA schedule from revenue and OPEX."""
    from finco_core.ebitda import calculate_ebitda_keur

    ebitda_by_period = []

    for p in periods:
        rev = revenue_schedule.get(p.index, 0)
        opex = opex_schedule.get(p.index, 0)
        ebitda_by_period.append(calculate_ebitda_keur(rev, opex))

    return ebitda_by_period


def compute_llcr(
    fcf_schedule: list[float],
    debt_balance: float,
    rate: float,
    periods_remaining: int,
) -> float:
    """Calculate LLCR = PV(FCF to debt maturity) / Debt."""
    if debt_balance <= 0:
        return float('inf')

    pv = sum(fcf / (1 + rate) ** (t + 1) for t, fcf in enumerate(fcf_schedule[:periods_remaining]))
    return pv / debt_balance


def compute_plcr(
    fcf_schedule: list[float],
    debt_balance: float,
    rate: float,
    total_periods: int,
) -> float:
    """Calculate PLCR = PV(FCF to project end) / Debt."""
    if debt_balance <= 0:
        return float('inf')

    pv = sum(fcf / (1 + rate) ** (t + 1) for t, fcf in enumerate(fcf_schedule[:total_periods]))
    return pv / debt_balance


def compute_shl_period(
    shl_balance: float,
    shl_rate_per_period: float,
    cf_after_senior_ds: float,
    method: str,
    wht_rate: float = 0.0,
    pik_switch_triggered: bool = False,
    is_final_shl_period: bool = False,
) -> tuple[float, float, float, float]:
    """Compatibility wrapper for the v3 SHL engine.

    Args:
        shl_balance: Current SHL balance
        shl_rate_per_period: SHL interest rate per period (e.g., 0.04 for semi-annual 8%)
        cf_after_senior_ds: CF available after senior debt service (cf_after_tax)
        method: "bullet" | "cash_sweep" | "pik" | "accrued" | "pik_then_sweep" | "partial_pay_sweep"
        wht_rate: Withholding tax rate on SHL interest (e.g., 0.18)
        pik_switch_triggered: True when available CF exceeds the annual SHL interest
            threshold, switching from PIK phase (partial cash interest + PIK capitalization)
            to SWEEP phase (cash interest capped at available CF + principal sweep).
            The trigger is cash-based, not senior-balance-based.

    Returns:
        (shl_interest_paid, shl_principal, shl_pik_addition, new_shl_balance)
        shl_interest_paid = net amount investor receives after WHT
        shl_principal = principal repayment
        shl_pik_addition = gross PIK capitalized
        new_shl_balance = updated balance
    """
    result = compute_shl_period_v3(
        shl_balance=shl_balance,
        shl_rate_per_period=shl_rate_per_period,
        cf_available=cf_after_senior_ds,
        method=method,
        wht_rate=wht_rate,
        pik_switch_triggered=pik_switch_triggered,
        is_final_period=is_final_shl_period,
    )
    return (
        result.interest_paid_keur,
        result.principal_keur,
        result.pik_addition_keur,
        result.new_balance_keur,
    )


def run_waterfall(
    ebitda_schedule: list[float],
    revenue_schedule: list[float],
    generation_schedule: list[float],
    depreciation_schedule: list[float],
    periods: list,
    total_capex: float,
    rate_per_period: float,
    tenor_periods: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
    tax_rate: float = 0.10,
    dsra_months: int = 6,
    shl_amount: float = 0,
    shl_rate: float = 0,
    shl_idc_keur: float = 0.0,  # SHL IDC - added to opening balance
    shl_repayment_method: str = "bullet",  # "bullet" | "cash_sweep" | "pik" | "accrued" | "pik_then_sweep" | "partial_pay_sweep"
    shl_tenor_years: int = 0,  # 0 = bullet at end of senior tenor; >0 = bullet in specific year
    shl_wht_rate: float = 0.0,  # Withholding tax rate on SHL interest
    use_shl_fcf_waterfall_engine: bool = False,
    shl_fcf_waterfall_cash_schedule_keur: tuple[float, ...] = (),
    shl_fcf_waterfall_minimum_cash_retained_keur: float = 0.0,
    discount_rate_project: float = 0.0641,
    discount_rate_equity: float = 0.0965,
    financial_close: 'date' = None,
    gearing_ratio: float = 0.80,  # Used for sizing cap in closed_form_sculpt
    fixed_debt_keur: float | None = None,  # Override sculpted debt (for P90 sizing scenarios)
    fixed_ds_keur: float | None = None,  # Fixed debt service per period (kEUR)
    rate_schedule: list[float] | None = None,  # Per-period rate schedule (Euribor curve). If None, uses flat rate_per_period.
    senior_sculpting_config: object | None = None,
    # Fiscal reintegration components (IDC + bank fees + commitment fees during construction)
    idc_keur: float = 0.0,
    bank_fees_keur: float = 0.0,
    commitment_fees_keur: float = 0.0,
    opex_schedule: list[float] | None = None,  # Per-period OPEX. If None, inferred from rev-ebitda.
    prior_tax_loss_keur: float = 0.0,  # Initial tax loss carryforward from construction period
    # Equity IRR method: "equity_only" = capex-debt-SHL, "combined" = capex-debt
    equity_irr_method: str = "equity_only",
    share_capital_keur: float = 0.0,  # Only used when equity_irr_method="combined"
    sculpt_capex_keur: float = 0.0,  # CAPEX for equity base (ex-IDC); used in "combined" method for equity_irr = sculpt_capex - debt
    # Debt sizing method: "dscr_sculpt" = min(DSCR-based, gearing_cap), "gearing_cap" = max(gearing, dscr) - gearing wins
    debt_sizing_method: str = "dscr_sculpt",
    # Per-period DSCR schedule for dual-DSCR sculpting (PPA vs merchant periods)
    dscr_schedule: list[float] | None = None,
    # Generic Wind Reference-specific: cap SHL sweep cash at R99-equivalent (reference-compatible).
    # Prevents SHL principal from consuming cash that Excel would hold back as
    # sculpted FCF reserve. Generic Solar Reference keeps this False (its R99 ≈ cf, no effective change).
    use_senior_sweep_cash_cap_for_shl: bool = False,
    use_reference_shl_repayment_alignment: bool = False,
    reference_shl_principal_eligibility_start_period: int | None = None,
    # Phase 9 CO2→CIT bridge: CO2 revenue added to taxable income (not EBITDA).
    # Must be used with use_co2_revenue_bridge=False to avoid double-counting.
    # R99/R102: BLOCKED — only taxable income is affected.
    co2_cit_bridge_by_period: dict[int, float] | None = None,
    # Explicit tax-depreciation schedule (per period, kEUR). When provided, this value is
    # passed to compute_period_tax() as the fiscal deduction, decoupling tax from book dep.
    # When None, falls back to depreciation_schedule (book dep = tax dep, legacy behaviour).
    # Set by waterfall_core when inputs.tax.tax_depreciation_mode is not None.
    tax_depreciation_schedule: list[float] | None = None,
    # C3B3C: SHL interest deductibility mode — governs which fraction of gross SHL interest
    # enters the ATAD pool. SUBJECT_TO_LIMITATIONS is not implemented; pass None for that mode.
    shl_interest_deductibility: object | None = None,
    shl_interest_deductible_pct: float | None = None,
) -> WaterfallResult:
    """Run full waterfall with iterative debt sculpting.

    Args:
        ebitda_schedule: EBITDA per period
        revenue_schedule: Revenue per period
        generation_schedule: Generation per period
        depreciation_schedule: Depreciation per period
        periods: Period objects with index, date, year_index
        total_capex: Total CAPEX in kEUR
        rate_per_period: Interest rate per period
        tenor_periods: Senior debt tenor in periods
        target_dscr: Target DSCR (default 1.15)
        lockup_dscr: Lockup DSCR threshold (default 1.10)
        tax_rate: Corporate tax rate
        dsra_months: DSRA reserve months
        shl_amount: SHL amount in kEUR
        shl_rate: SHL interest rate
        discount_rate_project: Discount rate for project NPV
        discount_rate_equity: Discount rate for equity NPV
        financial_close: Financial close date
        gearing_ratio: Gearing ratio cap (CAPEX * gearing_ratio)
        fixed_debt_keur: If provided, overrides sculpted debt (for P90 sizing)

    Returns:
        WaterfallResult with all periods and metrics

    .. TODO:: BESS revenue integration into waterfall
        Required:
        - BESS dispatch model (charge/discharge scheduling)
        - BESS revenue line item in WaterfallPeriod
        - Hybrid project revenue aggregation (solar + wind + BESS)
        Currently: BESS status is "partial" — revenue shown but waterfall not fully instrumented
    """
    if shl_repayment_method == "fcf_waterfall":
        if not use_shl_fcf_waterfall_engine:
            raise ValueError(
                "shl_repayment_method='fcf_waterfall' requires "
                "use_shl_fcf_waterfall_engine=True"
            )
        if len(shl_fcf_waterfall_cash_schedule_keur) < len(periods):
            raise ValueError(
                "shl_fcf_waterfall_cash_schedule_keur must cover all operating periods"
            )
    elif use_shl_fcf_waterfall_engine:
        raise ValueError(
            "use_shl_fcf_waterfall_engine=True requires "
            "shl_repayment_method='fcf_waterfall'"
        )

    # Step 1: Iterative sculpting to find debt amount
    # Use provided rate_schedule if available, otherwise use flat rate
    if rate_schedule is None:
        rate_schedule = [rate_per_period] * tenor_periods
    else:
        # Extend or trim to match tenor_periods
        if len(rate_schedule) < tenor_periods:
            rate_schedule = list(rate_schedule) + [rate_schedule[-1]] * (tenor_periods - len(rate_schedule))
        elif len(rate_schedule) > tenor_periods:
            rate_schedule = rate_schedule[:tenor_periods]
    # Preserve the signed EBITDA-derived proxy for DSCR and audit. The debt
    # sculpting kernel applies the zero bound only when it converts this
    # financial flow into non-negative debt-service capacity.
    signed_cfads_for_sculpt = [
        ebitda * (1.0 - tax_rate)
        if index >= len(periods) or periods[index].is_operation
        else 0.0
        for index, ebitda in enumerate(ebitda_schedule[:tenor_periods])
    ]

    # Compute DSCR-constrained debt (no gearing cap) as base
    sculpt_result = closed_form_sculpt(
        cfads_schedule=signed_cfads_for_sculpt,
        rate_schedule=rate_schedule,
        tenor_periods=tenor_periods,
        target_dscr=target_dscr,
        gearing_cap_keur=float('inf'),  # No gearing constraint - we handle it below
        dscr_schedule=dscr_schedule,
    )
    dscr_debt = sculpt_result.debt_keur

    # Compute gearing cap based on sculpt_capex (ex-IDC capex)
    # Use sculpt_capex if provided (> 0), otherwise fall back to total_capex for sizing
    sizing_base = sculpt_capex_keur if sculpt_capex_keur > 0 else total_capex

    # For "gearing_cap" method: exclude IDC from the gearing base
    # because the model's gearing calculation uses sculpt_capex - IDC
    # This gives: (57,967 - 1,086) * 0.7524 = 42,815
    if idc_keur > 0 and sculpt_capex_keur > 0:
        sizing_base_for_gearing = sizing_base - idc_keur
    else:
        sizing_base_for_gearing = sizing_base

    gearing_cap_keur = sizing_base_for_gearing * gearing_ratio

    # Apply debt sizing method
    if debt_sizing_method == "gearing_cap":
        # Gearing wins: use max of DSCR-constrained and gearing cap
        sizing_debt = max(dscr_debt, gearing_cap_keur)
    else:
        # Default: DSCR wins (min of DSCR and gearing)
        sizing_debt = min(dscr_debt, gearing_cap_keur)

    # If fixed_debt_keur is provided, it overrides everything
    if fixed_debt_keur is not None and fixed_debt_keur > 0:
        sizing_debt = fixed_debt_keur

    # Rescale balance schedule if sizing_debt differs from dscr_debt
    if abs(sizing_debt - dscr_debt) > 0.01 and (fixed_debt_keur is None or fixed_debt_keur <= 0):
        scale = sizing_debt / dscr_debt if dscr_debt > 0 else 1.0
        balance_schedule = [b * scale for b in sculpt_result.balance_schedule]
        # Use per-period DSCR targets if provided
        if dscr_schedule is not None:
            allowable_ds = [
                max(0.0, signed_cfads_for_sculpt[t] / dscr_schedule[t]) * scale
                for t in range(tenor_periods)
            ]
        else:
            allowable_ds = [
                max(0.0, signed_cfads_for_sculpt[t] / target_dscr) * scale
                for t in range(tenor_periods)
            ]
        interest_schedule = []
        principal_schedule = []
        payment_schedule = []
        dscr_sched_rescaled = []
        balance = sizing_debt
        for t in range(tenor_periods):
            interest = balance * rate_schedule[t]
            principal = max(0.0, min(allowable_ds[t] - interest, balance))
            payment = interest + principal
            dscr = signed_cfads_for_sculpt[t] / payment if payment > 0 else float('inf')
            interest_schedule.append(interest)
            principal_schedule.append(principal)
            payment_schedule.append(payment)
            dscr_sched_rescaled.append(dscr)
            balance = max(0.0, balance - principal)
        valid_dsrs = [d for d in dscr_sched_rescaled if not (d == float('inf'))]
        avg_dscr = sum(valid_dsrs) / len(valid_dsrs) if valid_dsrs else 0.0
        min_dscr = min(valid_dsrs) if valid_dsrs else 0.0
        sculpt_result = replace(
            sculpt_result,
            debt_keur=sizing_debt,
            balance_schedule=balance_schedule,
            interest_schedule=interest_schedule,
            principal_schedule=principal_schedule,
            payment_schedule=payment_schedule,
            dscr_schedule=dscr_sched_rescaled,
            avg_dscr=avg_dscr,
            min_dscr=min_dscr,
        )
        payments = payment_schedule  # Use the rescaled payment schedule
    elif fixed_debt_keur is not None and fixed_debt_keur > 0:
        # Rescale from dscr_debt to fixed_debt
        scale = fixed_debt_keur / dscr_debt if dscr_debt > 0 else 1.0
        balance_schedule = [b * scale for b in sculpt_result.balance_schedule]
        payments = [p * scale for p in sculpt_result.payment_schedule]
        # Interest and principal must also be scaled to match scaled balance schedule
        interest_schedule = [b * rate_schedule[t] for t, b in enumerate(balance_schedule)]
        principal_schedule = [payments[t] - interest_schedule[t] for t in range(tenor_periods)]
        debt = fixed_debt_keur
        # Recompute DSCR schedule
        dscr_sched_scaled = []
        for t in range(tenor_periods):
            dscr = signed_cfads_for_sculpt[t] / payments[t] if payments[t] > 0 else float('inf')
            dscr_sched_scaled.append(dscr)
        # DSCR recomputed from scaled payments (interest/principal not needed in replace)
        sculpt_result = replace(
            sculpt_result,
            debt_keur=fixed_debt_keur,
            balance_schedule=balance_schedule,
            payment_schedule=payments,
            dscr_schedule=dscr_sched_scaled,
        )
    else:
        debt = sculpt_result.debt_keur
        payments = sculpt_result.payment_schedule
        interest_schedule = sculpt_result.interest_schedule
        principal_schedule = sculpt_result.principal_schedule
        balance_schedule = sculpt_result.balance_schedule

    # Override with fixed debt service if provided (annuity-type amortization)
    if fixed_ds_keur is not None and fixed_ds_keur > 0:
        fixed_ds = fixed_ds_keur
        payments = [fixed_ds] * tenor_periods
        # First compute principal based on sculpted balances (initial approximation)
        interest_schedule = [balance_schedule[t] * rate_schedule[t] for t in range(tenor_periods)]
        principal_schedule = [max(0.0, fixed_ds - interest_schedule[t]) for t in range(tenor_periods)]
        principal_schedule = [
            min(principal_schedule[t], max(0.0, balance_schedule[t]))
            for t in range(tenor_periods)
        ]
        debt = balance_schedule[0]  # Initial debt from balance schedule
        # Recompute proper declining balance schedule for fixed DS amortization
        # (sculpted balance_schedule doesn't match fixed_DS principal_schedule)
        balance_schedule_fixed = [debt]
        bal = debt
        for t in range(tenor_periods):
            bal = max(0.0, bal - principal_schedule[t])
            balance_schedule_fixed.append(bal)
        balance_schedule = balance_schedule_fixed
        # Recompute interest_schedule using the corrected balance_schedule
        interest_schedule = [balance_schedule[t] * rate_schedule[t] for t in range(tenor_periods)]
        # Recompute principal_schedule using corrected interest
        principal_schedule = [max(0.0, fixed_ds - interest_schedule[t]) for t in range(tenor_periods)]
        principal_schedule = [
            min(principal_schedule[t], max(0.0, balance_schedule[t]))
            for t in range(tenor_periods)
        ]

    explicit_senior_ds_schedule_active = False
    if senior_sculpting_config is not None and getattr(senior_sculpting_config, "enabled", False):
        mode = senior_sculpting_config.mode
        if mode == SeniorSculptingMode.LEGACY:
            pass
        elif mode == SeniorSculptingMode.EXPLICIT_DEBT_SERVICE_SCHEDULE:
            explicit_senior_ds_schedule_active = True
            explicit_ds = validate_explicit_debt_service_schedule(
                senior_sculpting_config,
                tenor_periods,
            )
            debt = balance_schedule[0] if balance_schedule else sculpt_result.debt_keur
            balance_schedule_explicit = []
            interest_schedule = []
            principal_schedule = []
            payments = []
            dscr_sched_explicit = []
            balance = debt
            for t in range(tenor_periods):
                balance_schedule_explicit.append(balance)
                interest = balance * rate_schedule[t]
                principal = min(balance, max(0.0, explicit_ds[t] - interest))
                payment = interest + principal
                dscr = signed_cfads_for_sculpt[t] / payment if payment > 0 else float("inf")
                interest_schedule.append(interest)
                principal_schedule.append(principal)
                payments.append(payment)
                dscr_sched_explicit.append(dscr)
                balance = max(0.0, balance - principal)
            balance_schedule = balance_schedule_explicit + [balance]
            valid_dsrs = [d for d in dscr_sched_explicit if not (d == float("inf"))]
            sculpt_result = replace(
                sculpt_result,
                debt_keur=debt,
                balance_schedule=balance_schedule,
                interest_schedule=interest_schedule,
                principal_schedule=principal_schedule,
                payment_schedule=payments,
                dscr_schedule=dscr_sched_explicit,
                avg_dscr=sum(valid_dsrs) / len(valid_dsrs) if valid_dsrs else 0.0,
                min_dscr=min(valid_dsrs) if valid_dsrs else 0.0,
            )
        else:
            raise ValueError(f"Senior sculpting mode is not implemented: {mode.value}")

    # Step 2: Run waterfall for each period
    waterfall_periods = []

    # State variables
    dsra_balance = (dsra_months / 12) * (sculpt_result.payment_schedule[0] * 2) if dsra_months > 0 and sculpt_result.payment_schedule else 0  # noqa: E501  mathematically equivalent to: dsra_months * payment / 6, clearer intent
    shl_balance = shl_amount + shl_idc_keur  # Opening balance = disbursed + IDC
    mra_balance = 0
    cash_balance = 0
    cum_distribution = 0
    # Initialize prior_tax_loss: use inputs value if supplied, otherwise
    # estimate from construction-period financial costs (IDC + bank fees + commitment fees)
    if prior_tax_loss_keur > 0:
        prior_tax_loss = prior_tax_loss_keur
    else:
        # Estimate from construction-period financial costs as conservative fallback
        prior_tax_loss = idc_keur + bank_fees_keur + commitment_fees_keur
    fiscal_reintegration = 0.0
    fiscal_reintegration_applied = True  # Already accounted for in prior_tax_loss
    loss_carryforward_cap = 1.0  # ATAD: loss cap at 100% of EBITDA
    op_period_counter = 0  # BUG-3 fix: counter for operation periods (not year_index)
    # Stack N: actual post-sweep senior balance for pik_then_sweep tier switch.
    # balance_schedule stays non-zero for all sculpted tenor periods even after cash
    # sweeps pre-pay the actual debt; using it causes the SHL repayment tier to
    # activate too late (P30 vs Excel P26). running_senior_balance tracks reality.
    running_senior_balance = balance_schedule[0] if balance_schedule else 0.0

    # For returns calculation
    # "combined": equity_investment = sculpt_capex - debt, equity_cfs = distributions only
    if equity_irr_method == "combined":
        # equity base = sculpt_capex (ex-IDC) - debt; equity CFs = distributions only
        equity_investment = sculpt_capex_keur - sculpt_result.debt_keur
        equity_cfs = [-equity_investment]
    elif equity_irr_method == "shl_interest_only":
        # bullet SHL: investor puts in SHL + share capital, receives SHL interest + principal at maturity
        equity_investment = shl_amount + share_capital_keur
        equity_cfs = [-equity_investment]
    elif equity_irr_method == "shl_plus_dividends":
        # amortizing SHL: equity CF = SHL interest + SHL principal + dividends
        equity_investment = shl_amount + share_capital_keur
        equity_cfs = [-equity_investment]
    else:
        # "equity_only" style: equity base = total_capex - debt - SHL
        equity_investment = max(0, total_capex - sculpt_result.debt_keur - shl_amount)
        equity_cfs = [-equity_investment]
    # Start with initial investment - dates array now includes financial_close
    # project_cfs: all capital invested (total_capex, including debt)
    project_cfs = [-total_capex]
    equity_cf_list = []
    shi_list = []
    shp_list = []
    shl_balance_list = []
    # Sponsor CF: same initial outflow as equity (share_capital + shl + shl_idc)
    sponsor_investment = share_capital_keur + shl_amount + shl_idc_keur
    sponsor_cfs = [-sponsor_investment]

    # Track all periods
    all_dsrs = []
    lockup_count = 0
    audit_previous_r100 = 0.0
    previous_operating_tax_keur = 0.0
    _h1_cit_accrual_keur = 0.0  # Stack T2: carry H1 accrual to H2 cash settlement

    for i, period in enumerate(periods):
        if not period.is_operation:
            # Construction period: no revenue, just costs
            waterfall_periods.append(WaterfallPeriod(
                is_operation=False,
                period=period.index,
                date=period.end_date,
                year_index=period.year_index,
                period_in_year=period.period_in_year,
                generation_mwh=0,
                revenue_keur=0,
                opex_keur=0,
                ebitda_keur=0,
                depreciation_keur=0,
                interest_senior_keur=0,
                interest_shl_keur=0,
                taxable_profit_keur=0,
                tax_keur=0,
                cf_after_tax_keur=0,
                senior_interest_keur=0,
                senior_principal_keur=0,
                senior_ds_keur=0,
                shl_interest_keur=0,
                shl_principal_keur=0,
                shl_service_keur=0,
                dsra_contribution_keur=0,
                dsra_balance_keur=dsra_balance,
                mra_contribution_keur=0,
                mra_balance_keur=mra_balance,
                cf_after_reserves_keur=0,
                dscr=0,
                llcr=0,
                plcr=0,
                lockup_active=False,
                distribution_keur=0,
                cash_sweep_keur=0,
                cum_distribution_keur=cum_distribution,
                cash_balance_keur=cash_balance,
                senior_balance_keur=0.0,
            ))
            project_cfs.append(0)
            equity_cfs.append(0)
            continue

        # Operation period
        rev = revenue_schedule[i] if i < len(revenue_schedule) else 0
        gen = generation_schedule[i] if i < len(generation_schedule) else 0
        ebitda = ebitda_schedule[i]
        dep = depreciation_schedule[i] if i < len(depreciation_schedule) else 0
        # Explicit tax depreciation: use policy-derived schedule if provided (BOOK_BASED_PERCENTAGE
        # or STATUTORY_TAX_SCHEDULE). Falls back to book dep for legacy callers.
        tax_dep = (tax_depreciation_schedule[i]
                   if tax_depreciation_schedule and i < len(tax_depreciation_schedule)
                   else dep)

        # Senior debt service - compute from balance schedule + fixed DS
        # For fixed_ds_keur approach: interest = balance * rate, principal = fixed_ds - interest
        period_in_tenor = op_period_counter
        if period_in_tenor < tenor_periods:
            # Get current period balance (opening balance for this period)
            opening_balance = balance_schedule[period_in_tenor] if period_in_tenor < len(balance_schedule) else 0
            si = interest_schedule[period_in_tenor]

            # Fixed DS approach: fixed payment = interest + principal
            # Principal = fixed_ds - interest (but cap at remaining balance for balloon)
            if period_in_tenor == tenor_periods - 1 and not explicit_senior_ds_schedule_active:
                # Last period: balloon - pay off entire remaining balance
                sp = opening_balance
                senior_ds = si + sp
            else:
                # Normal period: fixed DS → principal = fixed_ds - interest (capped at balance)
                sp = min(fixed_ds_keur - si, opening_balance) if fixed_ds_keur else principal_schedule[period_in_tenor]
                senior_ds = payments[period_in_tenor]
        else:
            si = 0
            sp = 0
            senior_ds = 0
        op_period_counter += 1

        # Remaining senior debt balance for this period
        # For balloon period: this is the balance BEFORE payment (opening)
        # After balloon: remaining should be 0 since balance is paid off
        if period_in_tenor < len(balance_schedule):
            if period_in_tenor == tenor_periods - 1:
                # Balloon period: remaining is the PRE-BALLOON balance (opening)
                # After balloon payment, closing balance = 0
                remaining_senior_balance = balance_schedule[period_in_tenor]
            else:
                # Normal period: remaining = balance at START of next period (closing)
                if period_in_tenor + 1 < len(balance_schedule):
                    remaining_senior_balance = balance_schedule[period_in_tenor + 1]
                else:
                    remaining_senior_balance = 0
        else:
            remaining_senior_balance = 0

        # Force senior balance to 0 after tenor ends (post-tenor period has no senior debt)
        if period_in_tenor >= tenor_periods:
            remaining_senior_balance = 0.0

        # SHL placeholders — shp/svc/pik will be set below; shi set in Pass 1 or SHL block
        shp = 0; shl_svc = 0; shl_interest_pik = 0.0

        # Fiscal reintegration: IDC + bank fees + commitment fees capitalized during
        # construction, added back to taxable profit in first year of operation
        # Applied once in the first operational year when fiscal reintegration is enabled.
        if not fiscal_reintegration_applied:
            fiscal_reintegration = idc_keur + bank_fees_keur + commitment_fees_keur
            fiscal_reintegration_applied = True
        else:
            fiscal_reintegration = 0.0

        tax_loss_opening = prior_tax_loss

        # Phase 9 CO2→CIT bridge: extract CO2 for this period from bridge dict
        co2_cit_bridge_keur = (
            co2_cit_bridge_by_period.get(i, 0.0) if co2_cit_bridge_by_period else 0.0
        )

        # Cash tax is paid in the second period of each fiscal year.
        is_tax_period = period.period_in_year == 2

        # ── Stack T1: Two-pass tax + SHL re-pass — resolves the circular dependency ─
        # Dependency chain: tax → cf_after_tax → _cf_for_shl → shi → tax
        # Pass 1: provisional tax with shi=0 → _cf_for_shl_p1 → SHL block → real shi
        # Pass 2: final tax with real shi → cf_after_tax_final → _cf_for_shl_final
        # SHL re-pass: recompute SHL with _cf_for_shl_final → correct shp/shl_balance
        # shi is verified unchanged in the re-pass (guard raises RuntimeError if it moves).
        # Two tax passes are sufficient because shi does not change between passes
        # (cf_available >> net_interest in all sweep-phase periods).

        # ── Pass 1: provisional tax (shl_interest = 0) ──────────────────────────
        _tax_result_p1: TaxPeriodResult = compute_period_tax(
            ebitda_keur=ebitda,
            depreciation_keur=tax_dep,
            senior_interest_keur=si,
            shl_interest_keur=0.0,
            loss_carryforward_keur=prior_tax_loss,
            tax_rate=tax_rate,
            fiscal_reintegration_keur=fiscal_reintegration,
            atad_applies=True,
            atad_ebitda_limit=0.30,
            atad_min_threshold_keur=3000.0,
            loss_carryforward_cap=loss_carryforward_cap,
            co2_revenue_keur=co2_cit_bridge_keur,
            shl_interest_deductibility=shl_interest_deductibility,
            shl_interest_deductible_pct=shl_interest_deductible_pct,
        )
        _tax_p1 = _tax_result_p1.tax_keur
        # NOTE: prior_tax_loss is NOT updated from Pass 1 — Pass 2 owns the update
        _tax_this_period_p1 = _tax_p1 if is_tax_period else 0.0
        _cf_after_tax_p1 = ebitda - _tax_this_period_p1

        # Determine cash available for SHL service using provisional post-tax CF.
        # For pik_then_sweep, use post-tax cash after senior debt service and reserves.
        # Other methods use post-tax cash before senior debt service.
        # dsra_contrib is initialized here (updated later in DSRA block)
        dsra_contrib = 0.0
        if shl_repayment_method == "pik_then_sweep":
            # Available SHL cash is reduced by senior debt service and DSRA funding.
            # Stack N: once running_senior_balance hits 0 (actual debt fully repaid),
            # do not deduct sculpted senior_ds — it's a phantom payment on zero balance.
            _senior_ds_for_shl = senior_ds if running_senior_balance > 0 else 0.0
            _cf_for_shl = max(0.0, _cf_after_tax_p1 - _senior_ds_for_shl - dsra_contrib)
        else:
            _cf_for_shl = _cf_after_tax_p1

        # Pik switch triggers when available CF exceeds annual SHL interest threshold.
        # This is cash-based (not senior-balance-based) — transitions from PIK phase
        # (partial cash + capitalization) to SWEEP phase (cash interest capped at CF
        # + principal sweep). The per-method override (_pik_trigger) is set below.
        pik_switch_triggered = (_cf_for_shl > shl_balance * shl_rate)
        _pik_trigger = pik_switch_triggered  # per-period working copy, can be overridden

        # Y1-H1 is disbursement period: SHL just disbursed, no operating DS yet
        # No SHL interest, no SHL payment - just opening balance (already includes IDC)
        is_shl_disbursement_period = (op_period_counter == 1 and shl_repayment_method == "pik_then_sweep")

        shl_rate_per = shl_rate * getattr(period, "day_fraction", 0.5)
        if (
            use_reference_shl_repayment_alignment
            and shl_repayment_method == "pik_then_sweep"
            and reference_shl_principal_eligibility_start_period is not None
            and op_period_counter >= reference_shl_principal_eligibility_start_period
            and _cf_for_shl >= max(0.0, shl_balance * shl_rate_per)
        ):
            _pik_trigger = True

        # SHL tenor - when does bullet repay?
        # shl_tenor_years = 0 means bullet at end of senior tenor (default)
        # shl_tenor_years > 0 means bullet in specific year
        if shl_tenor_years > 0:
            shl_tenor_periods = shl_tenor_years * 2
        else:
            shl_tenor_periods = tenor_periods + 2  # bullet 1 year after senior payoff
        is_final_shl_period = (shl_balance > 0 and op_period_counter == shl_tenor_periods - 1)
        shl_opening_balance = shl_balance
        shl_gross_accrued_interest = (
            max(0.0, shl_opening_balance) * shl_rate_per
            if shl_opening_balance > 0 and shl_rate_per > 0
            else 0.0
        )

        # ── Generic Wind Reference SHL cash-cap (Excel R99-equivalent) — INVALID, disabled for PR A ──
        # CURRENTLY DISABLED: The previous implementation used remaining_senior_balance
        # as the R99-equivalent, which is a DEBT BALANCE not a CASH FLOW.
        # This caused the cap to go to 0 when senior debt was repaid, blocking SHL
        # repayment in the sweep phase — the opposite of the intended behavior.
        #
        # VALID R99-EQUIVALENT: Should be cf_after_tax - senior_ds - senior_sweep_amount.
        # The senior_sweep_amount is computed in the distribution section (lines 756-765)
        # AFTER the SHL call, so it is not available at this point in the code.
        #
        # SPLIT: PR A (flag + tests), PR B (reorder waterfall to compute senior sweep
        # cash before SHL service call).
        #
        # TODO (PR B): Reorder so senior sweep amount is computed before SHL call.
        # Then re-enable with: r99_equivalent_cf = max(0.0, cf_after_tax - senior_ds - senior_sweep_amount - dsra_contrib)
        # For now, no cap is applied (flag still propagated, tests still run).
        if use_senior_sweep_cash_cap_for_shl and shl_repayment_method == "pik_then_sweep":
            pass  # DISABLED — awaiting PR B senior-sweep reorder

        fcf_waterfall_result = None
        if shl_repayment_method == "fcf_waterfall":
            fcf_waterfall_result = compute_shl_fcf_waterfall_period(
                opening_shl_balance_keur=shl_balance,
                shl_rate=shl_rate,
                day_fraction=0.5,
                fcf_for_shl_keur=shl_fcf_waterfall_cash_schedule_keur[i],
                withholding_tax_rate=shl_wht_rate,
                minimum_cash_retained_keur=shl_fcf_waterfall_minimum_cash_retained_keur,
            )
            shi = fcf_waterfall_result.cash_interest_paid_keur
            shp = fcf_waterfall_result.principal_paid_keur
            shl_pik = fcf_waterfall_result.pik_keur
            shl_balance = fcf_waterfall_result.closing_balance_keur
        elif is_shl_disbursement_period:
            # Y1-H1: disbursement period - balance already includes IDC
            # No SHL interest, no PIK, no payments
            shi = 0.0; shp = 0.0; shl_pik = 0.0
            # shl_balance stays unchanged (= shl_amount + shl_idc)
        else:
            (shi, shp, shl_pik, shl_balance) = compute_shl_period(
                shl_balance=shl_balance,
                shl_rate_per_period=shl_rate_per,
                cf_after_senior_ds=_cf_for_shl,
                method=shl_repayment_method,
                wht_rate=shl_wht_rate,
                pik_switch_triggered=_pik_trigger,
                is_final_shl_period=is_final_shl_period,
            )
        shl_svc = shi + shp  # Total SHL service = interest + principal (for records)

        # ── Pass 2: final tax with real shl_interest_keur ───────────────────────
        # prior_tax_loss is the same as Pass 1 input (not updated from Pass 1).
        # fiscal_reintegration and co2_cit_bridge_keur are unchanged from above.
        total_interest = si + shi
        tax_result: TaxPeriodResult = compute_period_tax(
            ebitda_keur=ebitda,
            depreciation_keur=tax_dep,
            senior_interest_keur=si,
            shl_interest_keur=shi,
            loss_carryforward_keur=prior_tax_loss,
            tax_rate=tax_rate,
            fiscal_reintegration_keur=fiscal_reintegration,
            atad_applies=True,
            atad_ebitda_limit=0.30,
            atad_min_threshold_keur=3000.0,
            loss_carryforward_cap=loss_carryforward_cap,
            co2_revenue_keur=co2_cit_bridge_keur,
            shl_interest_deductibility=shl_interest_deductibility,
            shl_interest_deductible_pct=shl_interest_deductible_pct,
        )

        # Use Pass 2 result — SHL interest is now correctly deductible
        taxable_profit = tax_result.taxable_income_keur
        tax = tax_result.tax_keur
        prior_tax_loss = tax_result.loss_carryforward_remaining_keur

        # ── Stack T2: H1 CIT cash settlement ────────────────────────────────────
        # Pre-T: H2 paid only its own tax; H1 accrual evaporated each year.
        # Post-T2: H1 accrual is carried and settled in the same year's H2.
        if is_tax_period:
            # H2: settle H1 accrual + H2 tax
            tax_this_period = _h1_cit_accrual_keur + tax
            _h1_cit_accrual_keur = 0.0
        else:
            # H1: accrue only — carry forward to H2 settlement
            tax_this_period = 0.0
            _h1_cit_accrual_keur = tax

        r67_excel_style_cash_tax_diagnostic = (
            -(previous_operating_tax_keur + tax) if is_tax_period else 0.0
        )

        # CF after tax (final, from Pass 2 tax and T2 cash timing)
        cf_after_tax = ebitda - tax_this_period

        # ── Stack T1: SHL re-pass — update shp/shl_balance from final cf_after_tax ──
        # Pass 1 computed _cf_for_shl from _cf_after_tax_p1 (provisional tax).
        # Pass 2 corrected tax; now cf_after_tax may differ → _cf_for_shl changes.
        # shi (interest paid) must stay the same (it drives the tax already computed);
        # shp (principal) and shl_balance are updated to reflect the correct cashflow.
        # If shi were to change, three-pass iteration would be required — guarded below.
        _SHL_REPASS_TOL = 0.01  # kEUR
        if (
            not is_shl_disbursement_period
            and shl_repayment_method not in ("fcf_waterfall", "accrued")
            and shl_opening_balance > 0
        ):
            if shl_repayment_method == "pik_then_sweep":
                _cf_for_shl = max(0.0, cf_after_tax - _senior_ds_for_shl)
            else:
                _cf_for_shl = cf_after_tax
            _pik_trig_r = _cf_for_shl > shl_opening_balance * shl_rate
            if (
                use_reference_shl_repayment_alignment
                and shl_repayment_method == "pik_then_sweep"
                and reference_shl_principal_eligibility_start_period is not None
                and op_period_counter >= reference_shl_principal_eligibility_start_period
                and _cf_for_shl >= max(0.0, shl_opening_balance * shl_rate_per)
            ):
                _pik_trig_r = True
            _shi_r, _shp_r, _shl_pik_r, _shl_bal_r = compute_shl_period(
                shl_balance=shl_opening_balance,
                shl_rate_per_period=shl_rate_per,
                cf_after_senior_ds=_cf_for_shl,
                method=shl_repayment_method,
                wht_rate=shl_wht_rate,
                pik_switch_triggered=_pik_trig_r,
                is_final_shl_period=is_final_shl_period,
            )
            if abs(_shi_r - shi) > _SHL_REPASS_TOL:
                raise RuntimeError(
                    f"SHL re-pass: shi changed by {abs(_shi_r - shi):.4f} kEUR at "
                    f"period {getattr(period, 'period', '?')} — three-pass iteration required."
                )
            shp = _shp_r
            shl_pik = _shl_pik_r
            shl_balance = _shl_bal_r
            shl_svc = shi + shp

        # CF after senior and SHL debt service
        cf_after_ds = cf_after_tax - senior_ds - shi  # SHL principal repayment reduces the balance sheet, not P&L cash flow.

        # DSRA funding (6 months of debt service)
        # DSRA funding - rolling target based on future debt service
        # dsra_rolling_target() uses future payments (not historical)
        if dsra_months > 0 and period_in_tenor < tenor_periods:
            future_payments = payments[period_in_tenor:]  # Remaining payments
            dsra_target = dsra_rolling_target(future_payments, dsra_months, periods_per_year=2)
            withdrawal_needed = max(0, -cf_after_ds)  # Only withdraw if CF negative
            dsra_balance, dsra_contrib, dsra_withdrawal = dsra_update(
                prior_balance=dsra_balance,
                target=dsra_target,
                available_cash=cf_after_ds,
                withdrawal_needed=withdrawal_needed,
            )
        else:
            dsra_contrib = 0
            dsra_withdrawal = 0
        cf_after_reserves = cf_after_ds + dsra_withdrawal - dsra_contrib

        # DSCR - industrijski standard: CFADS / Senior Debt Service
        # CFADS = EBITDA - Taxes (PRIJE debt service, PRIJE DSRA movements)
        ebitda_minus_tax = ebitda - tax_this_period if ebitda is not None else 0
        dscr = ebitda_minus_tax / senior_ds if senior_ds > 0 else float('inf')
        all_dsrs.append(dscr)

        # Lockup check
        lockup = dscr < lockup_dscr if senior_ds > 0 else False
        if lockup:
            lockup_count += 1

        # Distribution with SHL amortization priority
        # Cash flow waterfall priority:
        # 1. Senior debt service (from balance_schedule)
        # 2. SHL repayment (after senior debt repaid)
        # 3. Dividends (after SHL repaid)
    # For "pik_then_sweep": use 3-tier waterfall
    # For other SHL methods (bullet, cash_sweep): 2-tier
        sweep_dscr_threshold = 1.35
        remaining_senior_balance = balance_schedule[period_in_tenor] if period_in_tenor < len(balance_schedule) else 0

        if shl_repayment_method == "fcf_waterfall":
            dist = fcf_waterfall_result.distribution_keur if fcf_waterfall_result else 0.0
            sweep_amount = 0.0
        elif shl_repayment_method == "pik_then_sweep":
    # 3-tier waterfall: senior → SHL → dividends
            if lockup:
                dist = 0
                sweep_amount = 0.0
            elif running_senior_balance > 0:
                # Senior debt still outstanding: sweep to senior first
                if dscr > sweep_dscr_threshold:
                    dist, sweep_amount = cash_sweep(
                        cf_after_reserves=cf_after_reserves,
                        senior_debt_balance=remaining_senior_balance,
                        sweep_dscr=sweep_dscr_threshold,
                        actual_dscr=dscr,
                        sweep_pct=1.0,
                    )
                else:
                    dist = 0
                    sweep_amount = 0.0
            elif shl_balance > 0:
                # Senior debt repaid, SHL outstanding: all FCF to SHL repayment
                # SHL principal = min(cf_after_reserves, remaining shl_balance)
                shl_repayment = max(0, cf_after_reserves)
                # Update shl_balance will happen in SHL section below
                dist = 0
                sweep_amount = 0.0
            else:
                # Both senior and SHL repaid: dividends to equity
                dist = max(0, cf_after_reserves)
                sweep_amount = 0.0
        elif shl_repayment_method == "partial_pay_sweep":
            # 3-tier waterfall: senior → SHL interest/PIK/sweep → dividends
            # No annual-interest threshold trigger. Every period the waterfall runs.
            if lockup:
                dist = 0
                sweep_amount = 0.0
            elif shl_balance > 0:
                # SHL outstanding: all CF after reserves goes to SHL Service.
                # Distribution only after SHL is fully repaid.
                # SHL interest + PIK + principal sweep are computed in the SHL block above.
                dist = 0
                sweep_amount = 0.0
            else:
                # SHL repaid: dividends to equity
                dist = max(0, cf_after_reserves)
                sweep_amount = 0.0
        else:
            # Standard 2-tier waterfall: senior → equity distributions
            if lockup:
                dist = 0
                sweep_amount = 0.0
            elif remaining_senior_balance > 0 and dscr > sweep_dscr_threshold:
                dist, sweep_amount = cash_sweep(
                    cf_after_reserves=cf_after_reserves,
                    senior_debt_balance=remaining_senior_balance,
                    sweep_dscr=sweep_dscr_threshold,
                    actual_dscr=dscr,
                    sweep_pct=1.0,
                )
            else:
                # Guard (Phase 23H): block equity distribution when SHL service obligations
                # exceed available cash for the SHL/distribution step.
                #
                # shl_svc = shi + shp = cash outflow for SHL (interest + principal)
                # _cf_for_shl = cash available for SHL step (= cf_after_tax for non-pik_then_sweep)
                #
                # If shl_svc > _cf_for_shl there is a CASH SHORTFALL — SHL obligations
                # cannot be fully paid from available cash. All cash must be retained;
                # distributing would pay equity before SHL is made whole.
                #
                # This fixes a Python waterfall bug: Excel CF tab confirms no dividends
                # in 2046 periods — cash flows to SHL/Net SHL column instead.
                #
                # Notes:
                # - shl_gross_accrued_interest is NOT a standalone blocker (it accrues
                #   every period even when cleared in the same SHL service step)
                # - shl_balance > 0 alone does NOT block (PIK methods may have balance
                #   while in PIK phase — the cash shortfall check covers that case)
                # - pik_then_sweep, partial_pay_sweep, fcf_waterfall: already guarded
                #   in their own 3-tier branches above
                TOLERANCE = 0.01
                if shl_svc > _cf_for_shl + TOLERANCE:
                    dist = 0.0
                elif shl_balance > TOLERANCE and shl_repayment_method == "bullet":
                    # Phase 23O: Generic Solar Reference bullet SHL distribution lock-up policy parity
                    #
                    # Python previously allowed distributions while shl_balance > 0 and
                    # shl_service was covered (shl_svc <= _cf_for_shl). Per manual Excel
                    # CF tab inspection, dividends are blank/zero until SHL principal
                    # is fully repaid (~2050). The correct lock-up gate is:
                    #
                    #   No distributions while SHL principal remains outstanding.
                    #
                    # This is strictly tighter than the Phase 23H cash-shortfall gate
                    # (shl_svc > _cf_for_shl). For Generic Solar Reference bullet SHL, we add:
                    #
                    #   shl_balance > tolerance → dist = 0
                    #
                    # Notes:
                    # - shl_repayment_method check ensures this is scoped to Generic Solar Reference
                    #   (bullet SHL); pik_then_sweep/partial_pay_sweep/fcf_waterfall use
                    #   their own 3-tier branches above and are unaffected
                    # - shl_gross_accrued_interest is NOT a standalone blocker
                    #   (accrues every period, cleared in same SHL service step)
                    # - shl_balance alone does NOT block for PIK methods (PIK methods
                    #   have balance while in PIK phase — they use 3-tier branches)
                    # - Phase 23H guard (shl_svc > _cf_for_shl) remains active for all
                    #   methods as the cash-shortfall backstop
                    dist = 0.0
                else:
                    dist = max(0, cf_after_reserves)
                sweep_amount = 0.0

        # Stack N: update actual running senior balance after principal repayment and sweeps
        if shl_repayment_method == "pik_then_sweep":
            running_senior_balance = max(0.0, running_senior_balance - sp - sweep_amount)

        cum_distribution += dist  # jednom, na kraju svih logika

        # DSRA release in last 2 periods - add to distribution
        if shl_repayment_method != "fcf_waterfall" and i >= len(periods) - 2 and dsra_balance > 0:
            dsra_release = dsra_balance
            dsra_balance = 0.0
            dsra_contribution_keur = -dsra_release  # negative = release
            dist += dsra_release  # DSRA release goes to distributions
            cum_distribution += dsra_release

        # Cash balance - after sweep
        cash_balance = cash_balance + cf_after_reserves - dist

        opex_val = opex_schedule[i] if opex_schedule is not None and i < len(opex_schedule) else max(0.0, rev - ebitda)
        dsra_release_or_funding = dsra_withdrawal - dsra_contrib
        r99_audit = compute_reference_covenant_input_period(
            revenue_keur=rev,
            opex_keur=opex_val,
            local_tax_keur=0.0,
            cash_interest_on_reserves_keur=0.0,
            corporate_tax_cash_keur=tax_this_period,
            senior_ds_keur=senior_ds,
            dsra_release_or_funding_keur=dsra_release_or_funding,
            junior_ds_keur=0.0,
            reserve_sweep_keur=0.0,
            previous_r100_carryforward_keur=audit_previous_r100,
            year_index=period.year_index,
            senior_tenor_years=tenor_periods // 2,
            dscr=dscr,
            lockup_dscr=lockup_dscr,
            dsra_balance_keur=dsra_balance,
            dsra_target_keur=0.0,
            jdsra_balance_keur=0.0,
            jdsra_target_keur=0.0,
        )
        audit_previous_r100 = r99_audit.r100_carryforward_keur

        # LLCR/PLCR - remaining FCF from next period onwards (not including current)
        # Use waterfall index i (not op_period_counter) to correctly index ebitda_schedule
        remaining_fcf = ebitda_schedule[i + 1:] if i + 1 < len(ebitda_schedule) else []
        # Closing balance: next period's balance, capped at last index
        balance_idx = min(period_in_tenor + 1, len(balance_schedule) - 1) if balance_schedule else 0
        remaining_balance = balance_schedule[balance_idx] if balance_schedule else 0
        # Use period-specific rate from schedule if available
        rate_for_llcr = rate_schedule[period_in_tenor] if rate_schedule and period_in_tenor < len(rate_schedule) else rate_per_period
        llcr_val = compute_llcr(remaining_fcf, remaining_balance, rate_for_llcr, tenor_periods - period_in_tenor)
        plcr_val = compute_plcr(remaining_fcf, remaining_balance, rate_for_llcr, len(remaining_fcf))
        wp = WaterfallPeriod(
            period=period.index,
            date=period.end_date,
            year_index=period.year_index,
            period_in_year=period.period_in_year,
            is_operation=True,
            generation_mwh=gen,
            revenue_keur=rev,
            opex_keur=opex_val,
            ebitda_keur=ebitda,
            depreciation_keur=dep,
            interest_senior_keur=si,
            interest_shl_keur=shi,
            taxable_profit_keur=ebitda - dep - si - shi,
            tax_keur=tax,
            cf_after_tax_keur=cf_after_tax,
            senior_interest_keur=si,
            senior_principal_keur=sp,
            senior_ds_keur=senior_ds,
            shl_interest_keur=shi,
            shl_principal_keur=shp,
            shl_service_keur=shl_svc,
            shl_balance_keur=shl_balance,
            shl_pik_keur=shl_pik,
            shl_gross_accrued_interest_keur=shl_gross_accrued_interest,
            dsra_contribution_keur=dsra_contrib,
            dsra_balance_keur=dsra_balance,
            mra_contribution_keur=0,
            mra_balance_keur=mra_balance,
            cf_after_reserves_keur=cf_after_reserves,
            dscr=dscr,
            llcr=llcr_val,
            plcr=plcr_val,
            lockup_active=lockup,
            distribution_keur=dist,
            cash_sweep_keur=sweep_amount,
            cum_distribution_keur=cum_distribution,
            cash_balance_keur=cash_balance,
            senior_balance_keur=max(0.0, remaining_senior_balance - sp),  # Closing balance after principal payment
            corporate_tax_cash_keur=tax_this_period,
            r67_excel_style_cash_tax_diagnostic_keur=r67_excel_style_cash_tax_diagnostic,
            tax_depreciation_audit_keur=dep,
            fiscal_reintegration_audit_keur=fiscal_reintegration,
            taxable_income_before_losses_audit_keur=tax_result.taxable_income_before_losses_keur,
            tax_loss_opening_audit_keur=tax_loss_opening,
            tax_loss_used_audit_keur=tax_result.loss_carryforward_applied_keur,
            tax_loss_closing_audit_keur=tax_result.loss_carryforward_remaining_keur,
            taxable_profit_after_losses_audit_keur=tax_result.taxable_income_keur,
            cit_accrual_audit_keur=tax,
            cash_tax_current_period_audit_keur=tax_this_period,
            cash_tax_excel_style_h2_diagnostic_keur=r67_excel_style_cash_tax_diagnostic,
            r69_fcf_banks_keur=r99_audit.r69_fcf_banks_keur,
            r84_fcf_junior_keur=r99_audit.r84_fcf_junior_keur,
            r98_distribution_account_keur=r99_audit.r98_distribution_account_keur,
            r99_fcf_for_distribution_keur=r99_audit.r99_fcf_for_distribution_keur,
            r100_carryforward_keur=r99_audit.r100_carryforward_keur,
            r102_fcf_for_shl_keur=r99_audit.r102_fcf_for_shl_keur,
            fcf_for_shl_keur=r99_audit.fcf_for_shl_keur,
        )

        waterfall_periods.append(wp)
        previous_operating_tax_keur = tax

        # Track CFs for returns
        # Project IRR = unlevered (EBITDA - unlevered tax)
        # Unlevered tax = tax_rate * max(0, EBITDA - dep) — financing-independent
        # Equity IRR = levered (distributions after debt service)
        dep = depreciation_schedule[i] if i < len(depreciation_schedule) else 0
        unlev_tax = tax_rate * max(0.0, ebitda - dep)
        project_cfs.append(ebitda - unlev_tax if ebitda else 0)
    # Equity CF: Row 28 "Total" = SHL interest + SHL principal + dividends
        # When SHL is outstanding: equity receives SHL cash flows (interest + principal)
        # When SHL is repaid (shl_balance <= 0): equity receives distributions (dividends)
        if equity_irr_method == "shl_interest_only":
            # Bullet SHL: equity CF = SHL interest + principal at maturity
            equity_cf_for_period = shi + shp
        elif equity_irr_method == "shl_plus_dividends":
    # Equity CF = SHL Net Interests + Dividends
            # R17: Net Interests only (principal = 0 throughout Y1-Y20)
            # R21 Total = R17 + R20 (dividends start ~Y20 when SHL repaid)
            # SHL principal is NOT returned as cash flow in equity IRR stream
            if shl_balance > 0:
                # Disbursement period: shi=0 by design (SHL just drawn, no interest sweep).
                # Excel records FCF-available (_cf_for_shl) as the P1 equity cash flow
                # rather than the swept SHL interest. Use _cf_for_shl to match Excel
                # golden methodology for parity. All other SHL-outstanding periods use shi.
                if is_shl_disbursement_period:
                    equity_cf_for_period = max(0.0, _cf_for_shl)
                else:
                    equity_cf_for_period = shi  # Net interest ONLY - no principal in equity CF
            else:
                equity_cf_for_period = dist  # Dividends after SHL fully repaid
        else:
            # combined/equity_only: equity CF = distributions to equity
            equity_cf_for_period = dist
        equity_cfs.append(equity_cf_for_period)
        equity_cf_list.append(equity_cf_for_period)
        shi_list.append(shi)
        shp_list.append(shp)
        shl_balance_list.append(shl_balance)

    # Build sponsor cash flows (uses pure function from sponsor_cashflows.py)
    sponsor_cfs = build_sponsor_cashflows(
        equity_irr_method=equity_irr_method,
        share_capital_keur=share_capital_keur,
        shl_amount_keur=shl_amount,
        shl_idc_keur=shl_idc_keur,
        shl_balance_by_period=shl_balance_list,
        equity_cf_per_period=equity_cf_list,
        shl_interest_paid_per_period=shi_list,
        shl_principal_paid_per_period=shp_list,
    )

    # Calculate returns

    # Calculate returns - prepend financial_close date for initial investment
    # This makes dates array match project_cfs/equity_cfs (initial + per-period)
    if financial_close:
        dates = [financial_close] + [p.end_date for p in periods]
    else:
        dates = [p.end_date for p in periods]

    # Verify lengths match before XIRR
    if len(project_cfs) != len(dates):
        _log.warning("XIRR length mismatch: project_cfs=%d, dates=%d",
                    len(project_cfs), len(dates))

    # WARN-1 fix: xirr returns None when no convergence - handle with `or 0.0`
    try:
        project_irr = xirr(project_cfs, dates, guess=0.08) or 0.0
        project_npv = xnpv(discount_rate_project, project_cfs, dates)
    except Exception as exc:
        _log.warning("XIRR/XNPV failed for project CFs: %s", exc)
        project_irr = 0.0
        project_npv = 0.0

    try:
        equity_irr = xirr(equity_cfs, dates, guess=0.10) or 0.0
        equity_npv = xnpv(discount_rate_equity, equity_cfs, dates)
    except Exception as exc:
        _log.warning("XIRR/XNPV failed for equity CFs: %s", exc)
        equity_irr = 0.0
        equity_npv = 0.0

    try:
        sponsor_irr = xirr(sponsor_cfs, dates, guess=0.10) or 0.0
    except Exception as exc:
        _log.warning("XIRR failed for sponsor CFs: %s", exc)
        sponsor_irr = 0.0

    # Build result
    result = WaterfallResult(
        periods=waterfall_periods,
        total_revenue_keur=sum(wp.revenue_keur for wp in waterfall_periods),
        total_opex_keur=sum(wp.opex_keur for wp in waterfall_periods),
        total_ebitda_keur=sum(wp.ebitda_keur for wp in waterfall_periods),
        total_tax_keur=sum(wp.tax_keur for wp in waterfall_periods),
        total_senior_ds_keur=sum(wp.senior_ds_keur for wp in waterfall_periods),
        total_shl_service_keur=sum(wp.shl_service_keur for wp in waterfall_periods),
        total_distribution_keur=cum_distribution,
        avg_dscr=sculpt_result.avg_dscr,
        min_dscr=sculpt_result.min_dscr,
        max_dscr=max(sculpt_result.dscr_schedule) if sculpt_result.dscr_schedule else 0.0,
        target_dscr=target_dscr,
        actual_min_dscr=min((d for d in all_dsrs if d != float('inf')), default=0.0),
        actual_avg_dscr=(sum(d for d in all_dsrs if d != float('inf')) / sum(1 for d in all_dsrs if d != float('inf'))) if any(d != float('inf') for d in all_dsrs) else 0.0,
        # WARN-2 fix: filter out inf values for min calculation
        min_llcr=min((wp.llcr for wp in waterfall_periods if 0 < wp.llcr < float('inf')), default=0.0),
        min_plcr=min((wp.plcr for wp in waterfall_periods if 0 < wp.plcr < float('inf')), default=0.0),
        periods_in_lockup=lockup_count,
        project_irr=project_irr,
        equity_irr=equity_irr,
        sponsor_irr=sponsor_irr,
        project_npv=project_npv,
        equity_npv=equity_npv,
        sculpting_result=sculpt_result,
    )

    return result


def print_waterfall_summary(result: WaterfallResult) -> str:
    """Generate text summary of waterfall result."""
    lines = [
        "=" * 60,
        "WATERFALL SUMMARY",
        "=" * 60,
        f"Total Revenue:    {result.total_revenue_keur:>12,.0f} k€",
        f"Total OPEX:       {result.total_opex_keur:>12,.0f} k€",
        f"Total EBITDA:     {result.total_ebitda_keur:>12,.0f} k€",
        f"Total Tax:        {result.total_tax_keur:>12,.0f} k€",
        f"Total Senior DS: {result.total_senior_ds_keur:>12,.0f} k€",
        f"Total SHL Svce:   {result.total_shl_service_keur:>12,.0f} k€",
        f"Total Distrib:    {result.total_distribution_keur:>12,.0f} k€",
        "-" * 60,
    ]
    # Sculpting info - appended after list closes
    converged_str = (
        f"{'CONVERGED' if result.sculpting_result.converged else 'FAILED'}"
        f" ({result.sculpting_result.iterations} iterations)"
        if result.sculpting_result and hasattr(result.sculpting_result, 'converged')
        else "N/A"
    )
    lines.append(f"Sculpting:       {converged_str}")
    if result.sculpting_result and hasattr(result.sculpting_result, 'debt_keur'):
        lines.append(f"Debt Amount:      {result.sculpting_result.debt_keur:>12,.0f} k€")
    lines.append(f"Avg DSCR:         {result.avg_dscr:>12.2f}x")
    lines.append(f"Min DSCR:         {result.min_dscr:>12.2f}x")
    lines.append(f"Max DSCR:         {result.max_dscr:>12.2f}x")
    lines.append(f"Min LLCR:         {result.min_llcr:>12.2f}x")
    lines.append(f"Min PLCR:         {result.min_plcr:>12.2f}x")
    lines.append(f"Periods in Lockup:{result.periods_in_lockup:>12}")
    lines.append("-" * 60)
    lines.append(f"Project IRR:      {result.project_irr * 100:>11.2f}%")
    lines.append(f"Equity IRR:       {result.equity_irr * 100:>11.2f}%")
    lines.append(f"Project NPV:      {result.project_npv:>12,.0f} k€")
    lines.append(f"Equity NPV:       {result.equity_npv:>12,.0f} k€")
    lines.append("=" * 60)
    return "\n".join(lines)

# CACHED WRAPPER moved to utils/cache.py (v3 refactoring)
def _resolve_shl_deductibility_for_legacy_runtime(mode: object) -> object:
    """Return the SHL deductibility mode for the legacy waterfall runtime.

    Modes that have no legacy implementation (SUBJECT_TO_LIMITATIONS) must not be
    promoted to compute_period_tax() — doing so would raise NotImplementedError at
    runtime. For those modes, return None to preserve legacy SHL-fully-deductible
    behavior.

    SOURCE_POLICY_CAPTURED_RUNTIME_NOT_PROMOTED: SUBJECT_TO_LIMITATIONS stores
    source metadata only. The legacy runtime continues with unchanged behavior until
    the thin-cap formula is implemented and explicitly promoted.
    """
    if mode is None:
        return None
    # Use the typed property when available; fall back to name-based check.
    legacy_ok = getattr(mode, "legacy_runtime_supported", None)
    if legacy_ok is not None:
        return mode if legacy_ok else None
    # Fallback for unrecognized objects — pass through unchanged.
    return mode


# See utils/cache.py:cached_run_waterfall_v3()
def cached_run_waterfall(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
    rate_per_period: float,
    tenor_periods: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
    tax_rate: float = 0.10,
    dsra_months: int = 6,
    shl_amount: float = 0.0,
    shl_rate: float = 0.0,
    discount_rate_project: float = 0.0641,
    discount_rate_equity: float = 0.0965,
) -> "WaterfallResult":
    """Cached wrapper around run_waterfall for UI layer.

    This function rebuilds schedules from inputs and calls run_waterfall.
    Cache is invalidated automatically when inputs or engine change.

    Args:
        inputs: ProjectInputs instance
        engine: PeriodEngine instance
        rate_per_period: Interest rate per period (e.g., 0.0565/2 for semi-annual)
        tenor_periods: Senior debt tenor in periods
        target_dscr: Target DSCR for sculpting
        lockup_dscr: Lockup DSCR threshold
        tax_rate: Corporate tax rate
        dsra_months: DSRA reserve months
        shl_amount: Subordinated hybrid loan amount
        shl_rate: SHL interest rate
        discount_rate_project: Discount rate for project NPV
        discount_rate_equity: Discount rate for equity NPV

    Returns:
        WaterfallResult with all computed periods and metrics
    """
    # V2-7: generation extracted to finco_core.revenue.
    # V2-8: opex extracted to finco_core.opex.
    from finco_core.ebitda import calculate_ebitda_keur
    from finco_core.revenue.generation import full_revenue_schedule, full_generation_schedule
    from finco_core.opex.projections import opex_schedule_annual

    # Build schedules
    periods_list = list(engine.periods())
    revenue_dict = full_revenue_schedule(inputs, engine)
    generation_dict = full_generation_schedule(inputs, engine)
    opex_annual = opex_schedule_annual(inputs, inputs.info.horizon_years)

    # Build EBITDA schedule
    op_periods = [p for p in periods_list if p.is_operation]
    dep_per_year = inputs.capex.total_capex / inputs.info.horizon_years

    ebitda_schedule = []
    revenue_schedule = []
    generation_schedule = []
    depreciation_schedule = []

    for p in periods_list:
        rev = revenue_dict.get(p.index, 0)
        gen = generation_dict.get(p.index, 0)
        if p.is_operation:
            # Semi-annual: split annual values evenly
            opex = opex_annual.get(p.year_index, 0) / 2
            ebitda = calculate_ebitda_keur(rev, opex)
            dep = dep_per_year / 2
        else:
            opex = 0
            ebitda = 0
            dep = 0

        revenue_schedule.append(rev)
        generation_schedule.append(gen)
        ebitda_schedule.append(ebitda)
        depreciation_schedule.append(dep)

    return run_waterfall(
        ebitda_schedule=ebitda_schedule,
        revenue_schedule=revenue_schedule,
        generation_schedule=generation_schedule,
        depreciation_schedule=depreciation_schedule,
        periods=periods_list,
        total_capex=inputs.capex.total_capex,
        rate_per_period=rate_per_period,
        tenor_periods=tenor_periods,
        target_dscr=target_dscr,
        lockup_dscr=lockup_dscr,
        tax_rate=tax_rate,
        dsra_months=dsra_months,
        shl_amount=shl_amount,
        shl_rate=shl_rate,
        shl_repayment_method=inputs.financing.shl_repayment_method,
        shl_tenor_years=inputs.financing.shl_tenor_years,
        shl_wht_rate=inputs.tax.wht_sponsor_shl_interest,
        equity_irr_method=inputs.financing.equity_irr_method,
        discount_rate_project=discount_rate_project,
        discount_rate_equity=discount_rate_equity,
        financial_close=inputs.info.financial_close,
        idc_keur=inputs.capex.idc_keur,
        bank_fees_keur=inputs.capex.bank_fees_keur,
        commitment_fees_keur=inputs.capex.commitment_fees_keur,
        prior_tax_loss_keur=inputs.tax.prior_tax_loss_keur,
        fixed_debt_keur=inputs.financing.fixed_debt_keur,
        fixed_ds_keur=inputs.financing.fixed_ds_keur,
        use_reference_shl_repayment_alignment=getattr(
            inputs.financing,
            "use_reference_shl_repayment_alignment",
            False,
        ),
        reference_shl_principal_eligibility_start_period=getattr(
            inputs.financing,
            "reference_shl_principal_eligibility_start_period",
            None,
        ),
        # SOURCE_POLICY_CAPTURED_RUNTIME_NOT_PROMOTED:
        # Only promote modes that have a legacy implementation. SUBJECT_TO_LIMITATIONS
        # stores source metadata but has no legacy-engine implementation; passing None
        # preserves legacy SHL-fully-deductible behavior until the thin-cap formula is
        # proven and explicitly activated (THIN_CAP_FORMULA_NOT_CONFIGURED).
        shl_interest_deductibility=_resolve_shl_deductibility_for_legacy_runtime(
            getattr(inputs.tax, "shl_interest_deductibility", None)
        ),
        shl_interest_deductible_pct=getattr(
            inputs.tax,
            "shl_interest_deductible_pct",
            None,
        ),
    )
