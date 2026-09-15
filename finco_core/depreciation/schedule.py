"""Depreciation policy and straight-line schedule helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepreciationPolicy:
    """Book and tax depreciation policy for an asset class."""

    method: str = "straight_line"
    useful_life_book_periods: int | None = None
    useful_life_tax_periods: int | None = None
    period_frequency: str = "semiannual"
    partial_period_convention: str = "none"

    def __post_init__(self) -> None:
        if self.method != "straight_line":
            raise ValueError("Only straight_line depreciation is implemented")
        if self.useful_life_book_periods is not None and self.useful_life_book_periods <= 0:
            raise ValueError("useful_life_book_periods must be positive")
        if self.useful_life_tax_periods is not None and self.useful_life_tax_periods <= 0:
            raise ValueError("useful_life_tax_periods must be positive")
        if not self.period_frequency:
            raise ValueError("period_frequency is required")


def straight_line_depreciation_for_period(
    *,
    basis_keur: float,
    useful_life_periods: int | None,
    period_index: int,
    depreciation_start_period: int,
) -> float:
    """Return straight-line depreciation for one period."""

    if basis_keur <= 0 or useful_life_periods is None:
        return 0.0
    elapsed_periods = period_index - depreciation_start_period
    if elapsed_periods < 0 or elapsed_periods >= useful_life_periods:
        return 0.0

    periodic_depreciation = basis_keur / useful_life_periods
    already_depreciated = periodic_depreciation * elapsed_periods
    remaining_basis = max(0.0, basis_keur - already_depreciated)
    return min(periodic_depreciation, remaining_basis)
