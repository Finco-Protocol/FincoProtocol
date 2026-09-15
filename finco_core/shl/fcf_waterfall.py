"""Pure SHL FCF waterfall mechanics.

This module is intentionally independent from the runtime waterfall engine. It
computes one shareholder-loan period from an explicit cash-available input.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SHLFCFWaterfallPeriodResult:
    """Result of one SHL FCF waterfall period."""

    opening_balance_keur: float
    gross_interest_keur: float
    cash_interest_paid_keur: float
    interest_wht_keur: float
    pik_keur: float
    principal_paid_keur: float
    closing_balance_keur: float
    distribution_keur: float
    shl_service_keur: float
    retained_cash_keur: float
    available_cash_after_buffer_keur: float


def compute_shl_fcf_waterfall_period(
    *,
    opening_shl_balance_keur: float,
    shl_rate: float,
    day_fraction: float,
    fcf_for_shl_keur: float,
    withholding_tax_rate: float = 0.0,
    minimum_cash_retained_keur: float = 0.0,
) -> SHLFCFWaterfallPeriodResult:
    """Compute a cash-interest-first SHL FCF waterfall period.

    The cash input is expected to be an R99/R102-equivalent amount. The helper
    does not infer that source and does not mutate state.
    """
    if minimum_cash_retained_keur < 0:
        raise ValueError("minimum_cash_retained_keur must be non-negative")
    if day_fraction < 0:
        raise ValueError("day_fraction must be non-negative")
    if shl_rate < 0:
        raise ValueError("shl_rate must be non-negative")
    if withholding_tax_rate < 0:
        raise ValueError("withholding_tax_rate must be non-negative")

    opening = max(0.0, opening_shl_balance_keur)
    fcf_for_shl = max(0.0, fcf_for_shl_keur)
    available = max(0.0, fcf_for_shl - minimum_cash_retained_keur)
    retained_cash = fcf_for_shl - available

    gross_interest = opening * shl_rate * day_fraction
    cash_interest_paid = min(available, gross_interest)
    interest_wht = cash_interest_paid * withholding_tax_rate
    pik = max(0.0, gross_interest - cash_interest_paid)

    remaining_after_interest = max(0.0, available - cash_interest_paid)
    balance_after_pik = opening + pik
    principal_paid = min(remaining_after_interest, balance_after_pik)
    closing_balance = max(0.0, balance_after_pik - principal_paid)
    distribution = max(0.0, remaining_after_interest - principal_paid)
    shl_service = cash_interest_paid + principal_paid

    return SHLFCFWaterfallPeriodResult(
        opening_balance_keur=opening,
        gross_interest_keur=gross_interest,
        cash_interest_paid_keur=cash_interest_paid,
        interest_wht_keur=interest_wht,
        pik_keur=pik,
        principal_paid_keur=principal_paid,
        closing_balance_keur=closing_balance,
        distribution_keur=distribution,
        shl_service_keur=shl_service,
        retained_cash_keur=retained_cash,
        available_cash_after_buffer_keur=available,
    )
