"""Fiscal reintegration - non-deductible items added back to taxable profit.

During construction period, certain costs are capitalized (not expensed).
When these costs are depreciated, they become deductible for tax purposes.
But during construction, they are NOT deductible and must be added back.

Items subject to fiscal reintegration for Generic Solar Reference:
- IDC (Interest During Construction) - capitalized, not expensed during construction
- Bank Fees - capitalized as part of CAPEX, not expensed during construction
- Commitment Fees - same as above

After COD, the depreciation of these items becomes deductible (no reintegration).
"""
from typing import Sequence


def fiscal_reintegration(
    period_index: int,
    capex_distribution: dict[int, float],
    non_deductible_items: list[str],
    is_construction: bool,
) -> float:
    """Calculate fiscal reintegration for a period.

    Non-deductible items (IDC, bank fees, commitment fees) during construction
    are capitalized and NOT expensed. When calculating taxable profit, they
    must be added back (reintegrated) since they were never deductible.

    Args:
        period_index: Period index
        capex_distribution: CAPEX by period (kEUR)
        non_deductible_items: List of non-deductible item names
        is_construction: True if this is a construction period

    Returns:
        Amount to add back to taxable profit in this period (kEUR)
    """
    if not is_construction:
        return 0.0

    # During construction: non-deductible items are capitalized
    # Must add them back to taxable profit (fiscal reintegration)
    capex = capex_distribution.get(period_index, 0.0)

    # Typical non-deductible items: IDC, bank fees, commitment fees
    # These are a fraction of CAPEX (e.g., IDC = 6% of capex * construction_period/2)
    # Simple estimate: use total capex * average fraction
    non_deductible_fraction = 0.0
    for item in non_deductible_items:
        if 'idc' in item.lower():
            non_deductible_fraction += 0.03  # ~3% IDC
        elif 'fee' in item.lower() or 'bank' in item.lower():
            non_deductible_fraction += 0.02  # ~2% fees

    return capex * non_deductible_fraction


def fiscal_reintegration_schedule(
    period_indices: Sequence[int],
    is_construction_flags: Sequence[bool],
    idc_per_period: dict[int, float],
) -> list[float]:
    """Generate fiscal reintegration schedule.
    
    Args:
        period_indices: List of period indices
        is_construction_flags: List of construction flags
        idc_per_period: IDC amount by period
    
    Returns:
        List of fiscal reintegration amounts (kEUR)
    """
    reintegration = []
    
    for period, is_const in zip(period_indices, is_construction_flags):
        if is_const:
            # During construction, IDC and other pre-COD items are not deductible
            # Add back to taxable profit
            reintegration.append(idc_per_period.get(period, 0.0))
        else:
            reintegration.append(0.0)
    
    return reintegration


def total_fiscal_reintegration(
    idc_total_keur: float,
    construction_periods: int,
) -> float:
    """Calculate total fiscal reintegration over construction period.
    
    Args:
        idc_total_keur: Total IDC amount
        construction_periods: Number of construction periods
    
    Returns:
        Total fiscal reintegration (kEUR)
    """
    # IDC is not deductible during construction
    # It gets added back to taxable profit in each construction period
    return idc_total_keur / construction_periods if construction_periods > 0 else 0.0