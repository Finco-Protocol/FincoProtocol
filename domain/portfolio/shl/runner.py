"""Phase 4A SHL engine — straight-line amortization schedule generator.

No sculpting. No capitalization. No circular funding.
Simple deterministic schedule for architectural foundation.

Architecture:
  SPV waterfall
    → dividend upstream
    → SHL interest upstream
    → SHL principal upstream
    → HoldCo aggregation
    → future tax engine
    → future sponsor layer
"""
from __future__ import annotations

from domain.portfolio.shl.inputs import SHLFacility, SHLPortfolioInputs
from domain.portfolio.shl.result import (
    SHLPeriodResult,
    SHLFacilityResult,
    SHLPortfolioResult,
)


def run_shl_facility(facility: SHLFacility) -> SHLFacilityResult:
    """Run straight-line amortization for a single SHL facility.

    No sculpting. No capitalization.
    - Principal paid in equal portions each period (straight-line)
    - Interest = opening_balance * rate / frequency
    - Final period closing balance = 0
    - No negative balances at any point
    - period_index starts at facility.start_period_index

    Parameters
    ----------
    facility : SHLFacility
        SHL facility definition

    Returns
    -------
    SHLFacilityResult
        Full period-by-period schedule
    """
    num_periods = facility.tenor_years * facility.payment_frequency_per_year

    if num_periods == 0 or facility.principal_keur == 0:
        return SHLFacilityResult(
            facility=facility,
            periods=(),
            total_interest_paid_keur=0.0,
            total_principal_paid_keur=0.0,
        )

    principal_per_period = facility.principal_keur / num_periods
    rate_per_period = facility.interest_rate_pa / facility.payment_frequency_per_year

    periods: list[SHLPeriodResult] = []
    balance = facility.principal_keur
    total_interest = 0.0
    total_principal = 0.0

    for idx in range(num_periods):
        opening = balance

        interest = opening * rate_per_period

        if idx < num_periods - 1:
            # Regular period: straight-line principal (fixed installment)
            principal = principal_per_period
        else:
            # Final period: pay entire remaining balance as principal
            # (interest already computed on opening balance; closing = 0)
            principal = opening

        closing = max(0.0, opening - principal)
        if closing < 1e-6:
            closing = 0.0

        total_interest += interest
        total_principal += principal
        balance = closing

        # period_index is offset by start_period_index
        actual_index = facility.start_period_index + idx
        periods.append(SHLPeriodResult(
            period_index=actual_index,
            opening_balance_keur=opening,
            interest_accrued_keur=interest,
            interest_paid_keur=interest,
            principal_paid_keur=principal,
            closing_balance_keur=closing,
        ))

    return SHLFacilityResult(
        facility=facility,
        periods=tuple(periods),
        total_interest_paid_keur=total_interest,
        total_principal_paid_keur=total_principal,
    )


def run_shl_portfolio(inputs: SHLPortfolioInputs) -> SHLPortfolioResult:
    """Run SHL schedule for all facilities in portfolio."""
    facilities_results: list[SHLFacilityResult] = []
    total_interest = 0.0
    total_principal = 0.0

    for facility in inputs.facilities:
        result = run_shl_facility(facility)
        facilities_results.append(result)
        total_interest += result.total_interest_paid_keur
        total_principal += result.total_principal_paid_keur

    return SHLPortfolioResult(
        facilities=tuple(facilities_results),
        total_interest_paid_keur=total_interest,
        total_principal_paid_keur=total_principal,
        warnings=(),
    )