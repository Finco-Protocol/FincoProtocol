"""Offline book/tax depreciation ledger engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from finco_core.depreciation.asset import AssetClassConfig
from finco_core.depreciation.result import DepreciationLedgerResult, DepreciationPeriodResult
from finco_core.depreciation.schedule import (
    DepreciationPolicy,
    straight_line_depreciation_for_period,
)


@dataclass(frozen=True)
class DepreciationLedgerInput:
    """Inputs for the offline depreciation ledger."""

    asset_classes: tuple[AssetClassConfig, ...]
    policies: Mapping[str, DepreciationPolicy]
    period_count: int
    period_frequency: str
    cod_period: int

    def __post_init__(self) -> None:
        if not self.asset_classes:
            raise ValueError("asset_classes is required")
        if self.period_count <= 0:
            raise ValueError("period_count must be positive")
        if self.cod_period < 0:
            raise ValueError("cod_period must be non-negative")
        if not self.period_frequency:
            raise ValueError("period_frequency is required")


def build_depreciation_ledger(ledger_input: DepreciationLedgerInput) -> DepreciationLedgerResult:
    """Build an offline book/tax depreciation ledger."""

    rows: list[DepreciationPeriodResult] = []
    accumulated_book_by_asset = {asset.asset_class: 0.0 for asset in ledger_input.asset_classes}
    accumulated_tax_by_asset = {asset.asset_class: 0.0 for asset in ledger_input.asset_classes}

    for period_index in range(ledger_input.period_count):
        for asset in ledger_input.asset_classes:
            policy = _policy_for_asset(asset.asset_class, ledger_input.policies)
            book_depreciation = straight_line_depreciation_for_period(
                basis_keur=asset.book_depreciable_basis_keur,
                useful_life_periods=policy.useful_life_book_periods,
                period_index=period_index,
                depreciation_start_period=asset.depreciation_start_period,
            )
            tax_depreciation = straight_line_depreciation_for_period(
                basis_keur=asset.tax_depreciable_basis_keur,
                useful_life_periods=policy.useful_life_tax_periods,
                period_index=period_index,
                depreciation_start_period=asset.depreciation_start_period,
            )

            accumulated_book = min(
                asset.book_depreciable_basis_keur,
                accumulated_book_by_asset[asset.asset_class] + book_depreciation,
            )
            accumulated_tax = min(
                asset.tax_depreciable_basis_keur,
                accumulated_tax_by_asset[asset.asset_class] + tax_depreciation,
            )
            accumulated_book_by_asset[asset.asset_class] = accumulated_book
            accumulated_tax_by_asset[asset.asset_class] = accumulated_tax

            gross_asset_basis = (
                asset.gross_asset_basis_keur
                if period_index >= asset.placed_in_service_period
                else 0.0
            )
            nbv_book = max(0.0, gross_asset_basis - accumulated_book)
            nbv_tax = max(0.0, asset.tax_depreciable_basis_keur - accumulated_tax)

            rows.append(
                DepreciationPeriodResult(
                    period_index=period_index,
                    asset_class=asset.asset_class,
                    gross_asset_basis_keur=gross_asset_basis,
                    book_depreciation_keur=book_depreciation,
                    tax_depreciation_keur=tax_depreciation,
                    accumulated_book_depreciation_keur=accumulated_book,
                    accumulated_tax_depreciation_keur=accumulated_tax,
                    nbv_book_keur=nbv_book,
                    nbv_tax_keur=nbv_tax,
                    book_tax_difference_keur=book_depreciation - tax_depreciation,
                )
            )

    total_book = sum(row.book_depreciation_keur for row in rows)
    total_tax = sum(row.tax_depreciation_keur for row in rows)
    final_period = ledger_input.period_count - 1
    final_rows = [row for row in rows if row.period_index == final_period]
    return DepreciationLedgerResult(
        periods=tuple(rows),
        total_book_depreciation_keur=total_book,
        total_tax_depreciation_keur=total_tax,
        ending_nbv_book_keur=sum(row.nbv_book_keur for row in final_rows),
        ending_nbv_tax_keur=sum(row.nbv_tax_keur for row in final_rows),
    )


def _policy_for_asset(
    asset_class: str,
    policies: Mapping[str, DepreciationPolicy],
) -> DepreciationPolicy:
    policy = policies.get(asset_class) or policies.get("default")
    if policy is None:
        raise ValueError(f"No depreciation policy for asset class {asset_class!r}")
    return policy
