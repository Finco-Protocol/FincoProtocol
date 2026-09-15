"""Generic Market A template helpers for the offline depreciation ledger."""

from __future__ import annotations

from domain.depreciation.schedule import DepreciationPolicy


def generic_market_a_straight_line_policy(
    *,
    useful_life_book_periods: int,
    useful_life_tax_periods: int,
    period_frequency: str = "semiannual",
) -> DepreciationPolicy:
    """Return a straight-line Generic Market A template policy."""

    return DepreciationPolicy(
        method="straight_line",
        useful_life_book_periods=useful_life_book_periods,
        useful_life_tax_periods=useful_life_tax_periods,
        period_frequency=period_frequency,
        partial_period_convention="none",
    )
