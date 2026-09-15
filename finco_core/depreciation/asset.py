"""Asset inputs for the offline book/tax depreciation ledger."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetClassConfig:
    """Single asset-class basis for book and tax depreciation."""

    asset_class: str
    gross_asset_basis_keur: float
    book_depreciable_basis_keur: float
    tax_depreciable_basis_keur: float
    placed_in_service_period: int
    depreciation_start_period: int
    source_label: str = ""

    def __post_init__(self) -> None:
        if not self.asset_class:
            raise ValueError("asset_class is required")
        if self.gross_asset_basis_keur < 0:
            raise ValueError("gross_asset_basis_keur must be non-negative")
        if self.book_depreciable_basis_keur < 0:
            raise ValueError("book_depreciable_basis_keur must be non-negative")
        if self.tax_depreciable_basis_keur < 0:
            raise ValueError("tax_depreciable_basis_keur must be non-negative")
        if self.placed_in_service_period < 0:
            raise ValueError("placed_in_service_period must be non-negative")
        if self.depreciation_start_period < 0:
            raise ValueError("depreciation_start_period must be non-negative")
