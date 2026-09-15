"""domain/shl/canonical_wiring — Phase 8.1: Minimal canonical SHL runtime wiring.

This module wires the canonical ShlEngine into the runtime waterfall when
use_shl_canonical_engine=True, replacing legacy SHL output fields only.

Design
------
When the flag is True, the waterfall runs legacy SHL first (for cash-flow
feedback), then the canonical ShlEngine is called with the pre-computed
post-senior cash values, and the canonical SHL fields override the legacy
fields in the output WaterfallPeriods.

Canonical → runtime field mapping (when flag=True):
  shl_interest_keur     ← canonical.cash_interest_paid_keur
  shl_principal_keur   ← canonical.principal_repaid_keur
  shl_balance_keur      ← canonical.closing_balance_keur
  shl_pik_keur          ← canonical.pik_capitalized_keur

NOT changed (audit-only or non-SHL):
  - senior_ds_keur, senior_interest_keur, senior_principal_keur
  - dscr, distribution_keur, cash_sweep_keur
  - r99/r102 fields (BLOCKED)
  - cf_after_tax, ebitda, etc.

R99/R102: BLOCKED — this wiring does not promote R99/R102 gates.
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.waterfall.waterfall_engine import WaterfallPeriod, WaterfallResult


@dataclass(frozen=True)
class CanonicalShlWiringResult:
    """Result of wiring canonical SHL into waterfall output.

    Attributes
    ----------
    shl_interest_by_period : tuple[float, ...]
        SHL cash interest paid per period (kEUR).
    shl_principal_by_period : tuple[float, ...]
        SHL principal repaid per period (kEUR).
    shl_balance_by_period : tuple[float, ...]
        SHL closing balance per period (kEUR).
    shl_pik_by_period : tuple[float, ...]
        SHL PIK capitalized per period (kEUR).
    canonical_vs_legacy_diff_interest : tuple[float, ...]
        Difference: canonical - legacy interest per period (kEUR).
    canonical_vs_legacy_diff_principal : tuple[float, ...]
        Difference: canonical - legacy principal per period (kEUR).
    all_interest_within_tolerance : bool
        True if all interest differences are within tolerance.
    all_principal_within_tolerance : bool
        True if all principal differences are within tolerance.
    """
    shl_interest_by_period: tuple[float, ...]
    shl_principal_by_period: tuple[float, ...]
    shl_balance_by_period: tuple[float, ...]
    shl_pik_by_period: tuple[float, ...]
    canonical_vs_legacy_diff_interest: tuple[float, ...]
    canonical_vs_legacy_diff_principal: tuple[float, ...]
    all_interest_within_tolerance: bool = True
    all_principal_within_tolerance: bool = True


def wire_canonical_shl_into_waterfall(
    waterfall_result: "WaterfallResult",
    shl_amount_keur: float,
    shl_rate: float,
    shl_idc_keur: float = 0.0,
    shl_repayment_method: str = "pik_then_sweep",
    shl_wht_rate: float = 0.0,
    shl_tenor_years: int = 0,
    interest_tolerance_keur: float = 10.0,
    principal_tolerance_keur: float = 10.0,
) -> CanonicalShlWiringResult:
    """Wire canonical ShlEngine output into waterfall result.

    Parameters
    ----------
    waterfall_result : WaterfallResult
        Runtime waterfall result (with legacy SHL fields populated).
    shl_amount_keur : float
        Initial SHL funding amount (kEUR).
    shl_rate : float
        Annual SHL interest rate.
    shl_idc_keur : float, default 0.0
        SHL IDC amount.
    shl_repayment_method : str, default "pik_then_sweep"
        SHL repayment method.
    shl_wht_rate : float, default 0.0
        WHT rate on SHL interest.
    shl_tenor_years : int, default 0
        SHL tenor in years (0 = bullet at senior payoff).
    interest_tolerance_keur : float, default 10.0
        Tolerance for interest difference (kEUR).
    principal_tolerance_keur : float, default 10.0
        Tolerance for principal difference (kEUR).

    Returns
    -------
    CanonicalShlWiringResult
        Canonical SHL values and diff vs legacy.

    Note
    ----
    This function does NOT modify the waterfall_result in place.
    Callers must explicitly copy canonical values into WaterfallPeriod fields.
    R99/R102: BLOCKED — only SHL-specific fields are wired.
    """
    from finco_core.shl.engine import ShlEngine
    from finco_core.shl.inputs import ShlEngineInputs, ShlPeriodInput

    periods = waterfall_result.periods

    # Build per-period inputs for canonical engine
    # Key input: post_senior_cash_available_keur = cf_after_tax - senior_ds
    # (DSRA contribution is tracked separately in the waterfall and doesn't
    # affect the SHL tranche's post-senior-cash input in the canonical model)

    tranche_opening_total = shl_amount_keur + shl_idc_keur

    # SHL tenor
    if shl_tenor_years > 0:
        shl_tenor_periods = shl_tenor_years * 2
    else:
        # Default: bullet 1 year after senior payoff
        shl_tenor_periods = len(periods) + 2

    period_inputs = []
    operating_count = sum(1 for p in periods if getattr(p, "is_operation", False))
    op_counter = 0

    for i, period in enumerate(periods):
        period_idx = getattr(period, "period", i + 1)
        day_frac = getattr(period, "day_fraction", 0.5)
        is_op = getattr(period, "is_operation", False)

        # Post-senior cash: CFADS - senior DS
        cf_after_tax = getattr(period, "cf_after_tax_keur", 0.0)
        senior_ds = getattr(period, "senior_ds_keur", 0.0)
        post_senior_cash = max(0.0, cf_after_tax - senior_ds)

        # Opening balance: first period uses shl_amount + shl_idc;
        # subsequent periods use prior closing balance
        if i == 0:
            opening_balance = tranche_opening_total
        else:
            # Get prior period's closing balance from legacy output
            prior_period = periods[i - 1]
            opening_balance = getattr(prior_period, "shl_balance_keur", tranche_opening_total)

        # Drawdown: only in construction periods
        # Generic Wind Reference draws at period 0 (first period)
        if not is_op and i == 0:
            drawdown = shl_amount_keur
        else:
            drawdown = 0.0

        # PIK allowed for pik_then_sweep, pik, accrued methods
        pik_allowed = shl_repayment_method in ("pik", "pik_then_sweep", "accrued", "partial_pay_sweep")  # partial_pay also allows PIK

        # PIK trigger: for pik_then_sweep, PIK triggers when cash available > interest
        # (senior debt repayment tracked separately via remaining_senior_balance)
        pik_trigger = post_senior_cash > opening_balance * shl_rate * day_frac

        period_inputs.append(
            ShlPeriodInput(
                period_index=period_idx,
                opening_balance_keur=opening_balance,
                drawdown_keur=drawdown,
                interest_rate=shl_rate,
                day_count_fraction=day_frac,
                post_senior_cash_available_keur=post_senior_cash,
                pik_allowed=pik_allowed,
                maintain_minimum_cash_reserve=False,
                minimum_cash_reserve_keur=0.0,
            )
        )

        if is_op:
            op_counter += 1

    # Build canonical engine inputs
    shl_inputs = ShlEngineInputs(
        project_name="waterfall_project",  # PR-7: neutral audit label (provenance only)
        period_count=len(periods),
        period_inputs=tuple(period_inputs),
        total_shl_funding_keur=tranche_opening_total,
        tranche_rates=(shl_rate,),
        tranche_day_fracs=(0.5,),
        tranche_opening_balances_keur=(tranche_opening_total,),
        pik_allowed=True,
        maintain_minimum_cash_reserve=False,
        minimum_cash_reserve_keur=0.0,
    )

    # Run canonical engine
    canonical_result = ShlEngine.compute(shl_inputs)

    # Extract per-period canonical values
    shl_interest_list = []
    shl_principal_list = []
    shl_balance_list = []
    shl_pik_list = []
    diff_interest_list = []
    diff_principal_list = []

    for i, canon_period in enumerate(canonical_result.period_results):
        # Map canonical output to runtime field names
        canon_shi = canon_period.cash_interest_paid_keur
        canon_shp = canon_period.principal_repaid_keur
        canon_balance = canon_period.closing_balance_keur
        canon_pik = canon_period.pik_capitalized_keur

        # Get legacy SHL fields for comparison
        legacy_period = periods[i]
        legacy_shi = getattr(legacy_period, "shl_interest_keur", 0.0)
        legacy_shp = getattr(legacy_period, "shl_principal_keur", 0.0)

        shl_interest_list.append(canon_shi)
        shl_principal_list.append(canon_shp)
        shl_balance_list.append(canon_balance)
        shl_pik_list.append(canon_pik)

        diff_interest_list.append(canon_shi - legacy_shi)
        diff_principal_list.append(canon_shp - legacy_shp)

    # Check tolerances
    all_interest_within = all(
        abs(d) <= interest_tolerance_keur for d in diff_interest_list
    )
    all_principal_within = all(
        abs(d) <= principal_tolerance_keur for d in diff_principal_list
    )

    return CanonicalShlWiringResult(
        shl_interest_by_period=tuple(shl_interest_list),
        shl_principal_by_period=tuple(shl_principal_list),
        shl_balance_by_period=tuple(shl_balance_list),
        shl_pik_by_period=tuple(shl_pik_list),
        canonical_vs_legacy_diff_interest=tuple(diff_interest_list),
        canonical_vs_legacy_diff_principal=tuple(diff_principal_list),
        all_interest_within_tolerance=all_interest_within,
        all_principal_within_tolerance=all_principal_within,
    )


def apply_canonical_shl_wiring(
    waterfall_result: "WaterfallResult",
    wiring_result: CanonicalShlWiringResult,
) -> None:
    """Apply canonical SHL wiring into waterfall result periods (in-place).

    Parameters
    ----------
    waterfall_result : WaterfallResult
        Runtime waterfall result to modify in-place.
    wiring_result : CanonicalShlWiringResult
        Pre-computed canonical SHL wiring result.

    Note
    ----
    This modifies WaterfallPeriod objects in-place.
    Only SHL-specific fields are overridden; all other fields are unchanged.
    R99/R102: BLOCKED — r99/r102 fields are NOT modified.
    """
    periods = waterfall_result.periods

    for i, period in enumerate(periods):
        period.shl_interest_keur = wiring_result.shl_interest_by_period[i]
        period.shl_principal_keur = wiring_result.shl_principal_by_period[i]
        period.shl_balance_keur = wiring_result.shl_balance_by_period[i]
        period.shl_pik_keur = wiring_result.shl_pik_by_period[i]
        # shl_service_keur = interest + principal
        period.shl_service_keur = (
            wiring_result.shl_interest_by_period[i]
            + wiring_result.shl_principal_by_period[i]
        )
        # R99/R102: NOT modified (BLOCKED)
        # senior_ds, dscr, distribution: NOT modified