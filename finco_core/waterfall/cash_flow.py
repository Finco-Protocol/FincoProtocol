"""Cash flow waterfall - full model computation.

This module brings together:
- Revenue (PPA + spot + CO2)
- OPEX
- Tax (with ATAD, loss CF, fiscal reintegration)
- Debt service (senior + SHL)
- Reserve accounts
- Distribution (after lockup check)
"""
import math
from dataclasses import dataclass
from typing import Optional

from finco_core.ebitda import calculate_ebitda_keur


@dataclass
class WaterfallResult:
    """Result of full cash flow waterfall computation."""
    period: int
    # Top section
    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    # Tax section
    depreciation_keur: float
    interest_senior_keur: float
    interest_shl_keur: float
    fiscal_reintegration_keur: float
    tax_keur: float
    # After tax
    cf_after_tax_keur: float
    # Debt service
    senior_ds_keur: float
    shl_service_keur: float
    # Reserves
    dsra_contribution_keur: float
    dsra_balance_keur: float
    # Cash available
    cash_after_ds_keur: float
    # Lockup check
    dscr: float
    lockup_active: bool
    # Distribution
    distribution_keur: float
    cum_distribution_keur: float
    # Running balance
    cash_balance_keur: float


def compute_waterfall(
    period: int,
    year_index: int,
    revenue_keur: float,
    opex_keur: float,
    depreciation_keur: float,
    interest_senior_keur: float,
    interest_shl_keur: float,
    fiscal_reintegration_keur: float,
    tax_keur: float,
    senior_ds_keur: float,
    shl_service_keur: float,
    dsra_contribution_keur: float,
    prior_cash_balance: float,
    target_dscr: float,
    lockup_dscr: float,
    dsra_balance_prior: float,
    dsra_target_keur: float,
) -> WaterfallResult:
    """Compute waterfall for a single period.
    
    The waterfall flows:
    1. EBITDA = Revenue - OpEx
    2. CF after tax = EBITDA - Tax
    3. CF to Banks = CF after tax - Senior DS - SHL Service
    4. CF after DS = CF to Banks - DSRA contribution
    5. Lockup check: if DSCR < lockup, distribution = 0
    6. Distribution = CF after DS (if not locked up)
    
    Args:
        period: Period index
        year_index: Year index (1-based)
        revenue_keur: Revenue in kEUR
        opex_keur: OPEX in kEUR
        depreciation_keur: Depreciation in kEUR
        interest_senior_keur: Senior debt interest in kEUR
        interest_shl_keur: SHL interest in kEUR
        fiscal_reintegration_keur: Fiscal reintegration add-back
        tax_keur: Tax liability in kEUR
        senior_ds_keur: Senior debt service (interest + principal)
        shl_service_keur: SHL interest + repayment
        dsra_contribution_keur: DSRA contribution
        prior_cash_balance: Cash balance from prior period
        target_dscr: Target DSCR (1.15)
        lockup_dscr: Lockup DSCR threshold (1.10)
        dsra_balance_prior: DSRA balance from prior period
        dsra_target_keur: Target DSRA balance
    
    Returns:
        WaterfallResult for this period
    """
    # EBITDA
    ebitda = calculate_ebitda_keur(revenue_keur, opex_keur)
    
    # CF after tax = EBITDA - Tax (tax already deducted above interest in real model)
    # Actually: EBIT = EBITDA - D&A, EBT = EBIT - Interest, Tax = EBT × rate
    # For simplicity, use: CF after tax = EBITDA - Tax
    cf_after_tax = ebitda - tax_keur
    
    # CF after debt service
    cf_after_ds = cf_after_tax - senior_ds_keur - shl_service_keur
    
    # CF after DSRA contribution (CFADS = Cash Flow Available for Debt Service)
    cf_after_reserves = cf_after_ds - dsra_contribution_keur

    # CFADS (industry standard for DSCR calculation)
    cfads = cf_after_reserves  # This is CFADS after reserves

    # DSCR calculation (industry standard: CFADS, not EBITDA)
    if senior_ds_keur > 0:
        dscr = cfads / senior_ds_keur
    else:
        dscr = float('inf')
    
    # Lockup check
    lockup_active = dscr < lockup_dscr
    
    # Distribution
    if lockup_active:
        distribution = 0.0
    else:
        distribution = max(0, cf_after_reserves)
    
    # DSRA balance update
    dsra_balance = dsra_balance_prior + dsra_contribution_keur
    
    # Cash balance update
    cash_balance = prior_cash_balance + cf_after_reserves - distribution
    
    return WaterfallResult(
        period=period,
        revenue_keur=revenue_keur,
        opex_keur=opex_keur,
        ebitda_keur=ebitda,
        depreciation_keur=depreciation_keur,
        interest_senior_keur=interest_senior_keur,
        interest_shl_keur=interest_shl_keur,
        fiscal_reintegration_keur=fiscal_reintegration_keur,
        tax_keur=tax_keur,
        cf_after_tax_keur=cf_after_tax,
        senior_ds_keur=senior_ds_keur,
        shl_service_keur=shl_service_keur,
        dsra_contribution_keur=dsra_contribution_keur,
        dsra_balance_keur=dsra_balance,
        cash_after_ds_keur=cf_after_reserves,
        dscr=dscr,
        lockup_active=lockup_active,
        distribution_keur=distribution,
        cum_distribution_keur=0,  # Will be set by caller
        cash_balance_keur=cash_balance,
    )


def distribution_after_lockup(
    cf_after_ds_keur: float,
    dscr: float,
    lockup_dscr: float,
    reserves_funded_pct: float,
) -> float:
    """Calculate distribution after lockup check.
    
    Args:
        cf_after_ds_keur: CF after debt service in kEUR
        dscr: Current DSCR
        lockup_dscr: Lockup threshold
        reserves_funded_pct: % of reserves funded
    
    Returns:
        Distribution amount in kEUR (0 if locked up)
    """
    # Lockup conditions
    if dscr < lockup_dscr:
        return 0.0
    
    if reserves_funded_pct < 1.0:
        return 0.0
    
    # Otherwise, distribute available cash
    return max(0, cf_after_ds_keur)


def summary_metrics(
    waterfall_results: list[WaterfallResult],
) -> dict[str, float]:
    """Calculate summary metrics from waterfall results.
    
    Args:
        waterfall_results: List of WaterfallResult for each period
    
    Returns:
        Dict with avg_dscr, min_dscr, total_distribution, etc.
    """
    if not waterfall_results:
        return {}
    
    dscr_values = [
        r.dscr for r in waterfall_results
        if r.senior_ds_keur > 0 and not math.isinf(r.dscr) and r.dscr > 0
    ]
    
    total_dist = sum(r.distribution_keur for r in waterfall_results)
    total_revenue = sum(r.revenue_keur for r in waterfall_results)
    total_opex = sum(r.opex_keur for r in waterfall_results)
    total_tax = sum(r.tax_keur for r in waterfall_results)
    total_senior_ds = sum(r.senior_ds_keur for r in waterfall_results)
    
    return {
        "avg_dscr": sum(dscr_values) / len(dscr_values) if dscr_values else 0,
        "min_dscr": min(dscr_values) if dscr_values else 0,
        "max_dscr": max(dscr_values) if dscr_values else 0,
        "total_distribution_keur": total_dist,
        "total_revenue_keur": total_revenue,
        "total_opex_keur": total_opex,
        "total_tax_keur": total_tax,
        "total_senior_ds_keur": total_senior_ds,
    }
