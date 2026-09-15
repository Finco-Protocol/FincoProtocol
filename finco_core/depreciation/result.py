"""Result dataclasses for the offline book/tax depreciation ledger."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepreciationPeriodResult:
    """One asset-class row in one period."""

    period_index: int
    asset_class: str
    gross_asset_basis_keur: float
    book_depreciation_keur: float
    tax_depreciation_keur: float
    accumulated_book_depreciation_keur: float
    accumulated_tax_depreciation_keur: float
    nbv_book_keur: float
    nbv_tax_keur: float
    book_tax_difference_keur: float


@dataclass(frozen=True)
class DepreciationLedgerResult:
    """Full offline depreciation ledger result."""

    periods: tuple[DepreciationPeriodResult, ...]
    total_book_depreciation_keur: float
    total_tax_depreciation_keur: float
    ending_nbv_book_keur: float
    ending_nbv_tax_keur: float

    def periods_for_index(self, period_index: int) -> tuple[DepreciationPeriodResult, ...]:
        return tuple(period for period in self.periods if period.period_index == period_index)

    def aggregate_by_period(self, period_index: int) -> DepreciationPeriodResult:
        period_rows = self.periods_for_index(period_index)
        if not period_rows:
            raise ValueError(f"No depreciation rows for period {period_index}")
        return DepreciationPeriodResult(
            period_index=period_index,
            asset_class="TOTAL",
            gross_asset_basis_keur=sum(row.gross_asset_basis_keur for row in period_rows),
            book_depreciation_keur=sum(row.book_depreciation_keur for row in period_rows),
            tax_depreciation_keur=sum(row.tax_depreciation_keur for row in period_rows),
            accumulated_book_depreciation_keur=sum(
                row.accumulated_book_depreciation_keur for row in period_rows
            ),
            accumulated_tax_depreciation_keur=sum(
                row.accumulated_tax_depreciation_keur for row in period_rows
            ),
            nbv_book_keur=sum(row.nbv_book_keur for row in period_rows),
            nbv_tax_keur=sum(row.nbv_tax_keur for row in period_rows),
            book_tax_difference_keur=sum(row.book_tax_difference_keur for row in period_rows),
        )

    def aggregate_periods(self) -> tuple[DepreciationPeriodResult, ...]:
        period_indexes = sorted({period.period_index for period in self.periods})
        return tuple(self.aggregate_by_period(period_index) for period_index in period_indexes)
