"""Asset-class depreciation schedule with configurable useful lives."""

from typing import Optional
from finco_core.inputs import CapexItem, AssetClass, ASSET_CLASS_USEFUL_LIFE


def useful_life_for_item(item: CapexItem) -> int:
    """Get useful life for a CapexItem based on asset class."""
    if item.useful_life_override is not None:
        return item.useful_life_override
    return ASSET_CLASS_USEFUL_LIFE.get(item.asset_class, 14)


def build_depreciation_schedule(
    capex_items: tuple[CapexItem, ...],
    horizon_years: int,
    senior_tenor_years: int = 14,
) -> dict[int, float]:
    """
    Build annual depreciation schedule for all capex items.

    Each item is depreciated straight-line over its useful life.
    Financial costs are amortized over senior_tenor_years.

    Args:
        capex_items: Tuple of CapexItems
        horizon_years: Number of years to compute depreciation
        senior_tenor_years: Tenor for financial cost amortization (default 14)

    Returns:
        Dict mapping year_index (1-based) → total depreciation in kEUR
    """
    schedule = {y: 0.0 for y in range(1, horizon_years + 1)}

    for item in capex_items:
        if item.asset_class == AssetClass.FINANCIAL_COSTS and item.useful_life_override is None:
            # Fall back to senior_tenor_years only when no per-item override is provided.
            # When useful_life_override is set (e.g. IDC=12y, VAT=20y from
            # book_depreciable_capex_items()), honour the per-component evidence.
            life = senior_tenor_years
        else:
            life = useful_life_for_item(item)

        annual_dep = item.amount_keur / life if life > 0 else 0.0

        for year in range(1, horizon_years + 1):
            if year <= life:
                schedule[year] += annual_dep

    return schedule


def depreciation_per_period(
    annual_schedule: dict[int, float],
    periods: list,
) -> dict[int, float]:
    """
    Split annual depreciation to periods using day_fraction.

    Args:
        annual_schedule: Dict mapping year_index → annual depreciation in kEUR
        periods: List of period metadata objects with year_index, day_fraction, is_operation

    Returns:
        Dict mapping period_index → depreciation in kEUR for that period
    """
    result = {}
    for p in periods:
        if not p.is_operation:
            result[p.index] = 0.0
        else:
            annual_dep = annual_schedule.get(p.year_index, 0.0)
            result[p.index] = annual_dep * p.day_fraction
    return result
