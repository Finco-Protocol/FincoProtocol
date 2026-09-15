"""Tax engine - corporate tax calculation with ATAD and loss carryforward.

For Generic Solar Reference (Generic Market A):
- Corporate tax rate: 10%
- ATAD EBITDA limit: 30% (interest deduction limit)
- Loss carryforward: 5 years, 100% cap
- Thin cap applies for related party interest
- Tax is paid annually (every 2nd semester)

Key complexity:
- Fiscal reintegration: pre-COD items (IDC, bank fees) added back to taxable profit
- Losses from prior years reduce current taxable profit
- ATAD limits interest deduction to 30% of EBITDA
"""
from typing import Optional
from dataclasses import dataclass


# =============================================================================
# TAX PERIOD HELPERS
# =============================================================================

def is_tax_payment_period(period_in_year: int) -> bool:
    """Income tax is paid once per year — always in H2.

    Generic reference policy: tax is determined annually,
    advance payments are made monthly but in the model we use annual.
    In semi-annual model: tax is shown in H2 (period_in_year == 2).
    """
    return period_in_year == 2


def annual_tax_for_period(
    h1_taxable: float,
    h2_taxable: float,
    tax_rate: float,
) -> tuple[float, float]:
    """Calculate annual tax and allocate to H2.

    Tax is calculated annually but shown in H2 period.
    H1 tax is always 0, all annual tax is in H2.

    Args:
        h1_taxable: Taxable profit in H1
        h2_taxable: Taxable profit in H2
        tax_rate: Corporate tax rate (decimal)

    Returns:
        (h1_tax, h2_tax) — h1_tax is always 0
    """
    annual_taxable = h1_taxable + h2_taxable
    annual_tax = max(0.0, annual_taxable * tax_rate)
    return 0.0, annual_tax  # All tax in H2


@dataclass
class TaxResult:
    """Result of tax calculation for a period."""
    period: int
    ebitda_keur: float
    depreciation_keur: float
    interest_keur: float
    fiscal_reintegration_keur: float
    atad_adjustment_keur: float
    loss_cf_applied_keur: float
    taxable_profit_keur: float
    tax_rate: float
    tax_keur: float
    effective_rate: float


def taxable_profit(
    ebitda_keur: float,
    depreciation_keur: float,
    interest_keur: float,
    fiscal_reintegration_keur: float = 0,
    atad_addback_keur: float = 0,
    loss_carryforward_keur: float = 0,
) -> float:
    """Calculate taxable profit.
    
    Taxable Profit = EBITDA - Depreciation - Interest + Fiscal Reintegration + ATAD Adjustment - Loss CF
    
    Args:
        ebitda_keur: EBITDA in kEUR
        depreciation_keur: Depreciation in kEUR
        interest_keur: Deductible interest in kEUR
        fiscal_reintegration_keur: Add-back for non-deductible items
        atad_addback_keur: ATAD adjustment (interest above 30% EBITDA limit)
        loss_carryforward_keur: Prior year losses applied
    
    Returns:
        Taxable profit in kEUR
    """
    profit = ebitda_keur - depreciation_keur - interest_keur
    profit += fiscal_reintegration_keur  # Add back non-deductible items
    profit += atad_addback_keur  # Add back disallowed interest
    profit -= loss_carryforward_keur  # Apply loss carryforward
    
    return max(0, profit)


def tax_liability(
    taxable_profit_keur: float,
    tax_rate: float,
) -> float:
    """Calculate tax liability.
    
    Args:
        taxable_profit_keur: Taxable profit in kEUR
        tax_rate: Tax rate (e.g., 0.10 for 10%)
    
    Returns:
        Tax liability in kEUR
    """
    return max(0, taxable_profit_keur * tax_rate)


def atad_limit(
    ebitda_keur: float,
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur: float = 3000.0,
) -> float:
    """Calculate ATAD interest deduction limit.
    
    ATAD (Anti-Tax Avoidance Directive) limits interest deduction to:
    - 30% of EBITDA (before interest and tax)
    - OR minimum threshold (3,000 kEUR for large projects)
    
    The higher of the two limits applies.
    
    Args:
        ebitda_keur: EBITDA in kEUR
        atad_ebitda_limit: ATAD EBITDA limit (default 30%)
        atad_min_interest_keur: Minimum interest threshold
    
    Returns:
        Maximum deductible interest in kEUR
    """
    ebitda_limit = ebitda_keur * atad_ebitda_limit
    
    # ATAD allows the higher of 30% EBITDA limit or 3M EUR threshold
    return max(ebitda_limit, atad_min_interest_keur)


def atad_adjustment(
    interest_keur: float,
    ebitda_keur: float,
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur: float = 3000.0,
) -> tuple[float, float]:
    """Calculate ATAD adjustment for excess interest.
    
    Returns:
        Tuple of (deductible_interest, disallowed_interest_addback)
    
    Args:
        interest_keur: Total interest in kEUR
        ebitda_keur: EBITDA in kEUR
        atad_ebitda_limit: ATAD EBITDA limit percentage
        atad_min_interest_keur: Minimum interest threshold (default 3000.0)
    
    Returns:
        (deductible_interest, excess_interest_addback)
    """
    limit = atad_limit(ebitda_keur, atad_ebitda_limit, atad_min_interest_keur=atad_min_interest_keur)
    
    if interest_keur <= limit:
        return interest_keur, 0.0
    else:
        # Excess interest is added back to taxable profit
        return limit, interest_keur - limit


def apply_loss_carryforward(
    losses: list[float],
    taxable_profit_keur: float,
    max_years: int = 5,
    cap_pct: float = 1.0,
) -> tuple[float, list[float]]:
    """Apply loss carryforward to current period's taxable profit using FIFO.

    Losses are applied in order (oldest first), up to cap_pct of current profit.

    Args:
        losses: List of historical losses (index 0 = most recent year, -1 = oldest)
        taxable_profit_keur: Current period taxable profit
        max_years: Maximum carryforward years (default 5)
        cap_pct: Maximum % of current profit that can be offset (1.0 = 100%)

    Returns:
        Tuple of (loss_applied, remaining_losses)
    """
    if not losses or taxable_profit_keur <= 0:
        return 0.0, losses

    # Take only eligible (up to max_years) - already ordered oldest to newest in the list
    eligible = losses[:max_years]

    # Cap at cap_pct of current profit
    max_offset = taxable_profit_keur * cap_pct

    # FIFO: apply losses in order (index 0 = oldest remaining loss)
    loss_applied = 0.0
    remaining_losses = []

    for loss in eligible:
        if loss_applied >= max_offset:
            remaining_losses.append(loss)  # Can't use this loss
        else:
            available = max_offset - loss_applied
            used = min(loss, available)
            loss_applied += used
            if loss > used:
                remaining_losses.append(loss - used)  # Partial consumption

    # Add any years beyond max_years (older losses that expired)
    remaining_losses = remaining_losses + list(losses[max_years:])

    return min(loss_applied, max_offset), remaining_losses


def loss_carryforward_simple(
    prior_year_losses: list[float],
    current_profit_keur: float,
    years: int = 5,
    cap: float = 1.0,
) -> float:
    """Simple loss carryforward calculation.
    
    Args:
        prior_year_losses: List of losses by year (most recent first)
        current_profit_keur: Current year taxable profit
        years: Carryforward period (default 5)
        cap: Maximum offset as % of profit (default 1.0 = 100%)
    
    Returns:
        Loss amount applied to current profit
    """
    if current_profit_keur <= 0 or not prior_year_losses:
        return 0.0
    
    # Take losses from most recent years first
    available = sum(prior_year_losses[:years])
    max_offset = current_profit_keur * cap
    
    return min(available, max_offset)


def effective_tax_rate(
    tax_keur: float,
    ebitda_keur: float,
) -> float:
    """Calculate effective tax rate.
    
    Args:
        tax_keur: Tax liability in kEUR
        ebitda_keur: EBITDA in kEUR
    
    Returns:
        Effective tax rate (e.g., 0.08 for 8%)
    """
    if ebitda_keur <= 0:
        return 0.0
    return tax_keur / ebitda_keur


def full_tax_schedule(
    ebitda_schedule: list[float],
    depreciation_schedule: list[float],
    interest_schedule: list[float],
    fiscal_reintegration_schedule: list[float],
    tax_rate: float,
    atad_ebitda_limit: float = 0.30,
    loss_cf_initial: list[float] = None,
) -> list[TaxResult]:
    """Calculate full tax schedule over project life.
    
    Args:
        ebitda_schedule: EBITDA per period
        depreciation_schedule: Depreciation per period
        interest_schedule: Interest per period
        fiscal_reintegration_schedule: Fiscal reintegration per period
        tax_rate: Corporate tax rate
        atad_ebitda_limit: ATAD limit percentage
        loss_cf_initial: Initial losses by year
    
    Returns:
        List of TaxResult for each period
    """
    if loss_cf_initial is None:
        loss_cf_initial = []
    
    schedule = []
    accumulated_losses = list(loss_cf_initial)
    
    for period in range(len(ebitda_schedule)):
        ebitda = ebitda_schedule[period]
        depreciation = depreciation_schedule[period] if period < len(depreciation_schedule) else 0
        interest = interest_schedule[period] if period < len(interest_schedule) else 0
        fis_reint = fiscal_reintegration_schedule[period] if period < len(fiscal_reintegration_schedule) else 0
        
        # ATAD adjustment
        deductible_interest, atad_addback = atad_adjustment(interest, ebitda, atad_ebitda_limit)
        
        # Apply loss carryforward
        taxable_before_loss = taxable_profit(
            ebitda, depreciation, deductible_interest, fis_reint, atad_addback, 0
        )
        
        loss_applied, accumulated_losses = apply_loss_carryforward(
            accumulated_losses, taxable_before_loss, max_years=5, cap_pct=1.0
        )
        
        # Final taxable profit
        taxable = max(0, taxable_before_loss - loss_applied)
        
        # Tax
        tax = tax_liability(taxable, tax_rate)
        
        # Effective rate
        eff_rate = effective_tax_rate(tax, ebitda)
        
        schedule.append(TaxResult(
            period=period,
            ebitda_keur=ebitda,
            depreciation_keur=depreciation,
            interest_keur=interest,
            fiscal_reintegration_keur=fis_reint,
            atad_adjustment_keur=atad_addback,
            loss_cf_applied_keur=loss_applied,
            taxable_profit_keur=taxable,
            tax_rate=tax_rate,
            tax_keur=tax,
            effective_rate=eff_rate,
        ))
    
    return schedule