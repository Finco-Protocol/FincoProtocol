"""domain/depreciation/engine — Canonical Depreciation Engine."""
from dataclasses import dataclass
from typing import Tuple

from finco_core.depreciation.asset import AssetClassConfig
from finco_core.depreciation.ledger import DepreciationLedgerInput, build_depreciation_ledger
from finco_core.depreciation.result import DepreciationLedgerResult, DepreciationPeriodResult
from finco_core.depreciation.schedule import DepreciationPolicy


@dataclass(frozen=True)
class DepreciationEngineInputs:
    """Canonical inputs for the DepreciationEngine.

    Attributes
    ----------
    project_name : str
        Project name (e.g., "Generic Wind Reference", "Generic Solar Reference").
    asset_classes : Tuple[AssetClassConfig, ...]
        Per-asset-class configurations.
    policies : dict[str, DepreciationPolicy]
        Depreciation policy per asset class.
        Include a "default" policy for asset classes without explicit policy.
    period_count : int
        Total number of semiannual periods.
    period_frequency : str
        "semiannual" (Generic Wind Reference default).
    cod_period : int
        Commercial operation date period index (1-based).
    """
    project_name: str
    asset_classes: Tuple[AssetClassConfig, ...]
    policies: dict[str, DepreciationPolicy]
    period_count: int
    period_frequency: str = "semiannual"
    cod_period: int = 2  # Generic Wind Reference: COD at period 2 (P2 = first operating period)


@dataclass(frozen=True)
class DepreciationEngineResult:
    """Full DepreciationEngine result.

    Attributes
    ----------
    project_name : str
    period_count : int
    ledger_result : DepreciationLedgerResult
        The underlying ledger result.
    audit_rows : Tuple[DepreciationAuditRow, ...]
        Per-period, per-asset-class audit rows.
    total_book_depreciation_keur : float
    total_tax_depreciation_keur : float
    total_non_depreciable_basis_keur : float
        Sum of land and non-depreciable asset bases.
    """
    project_name: str
    period_count: int
    ledger_result: DepreciationLedgerResult
    audit_rows: Tuple["DepreciationAuditRow", ...]
    total_book_depreciation_keur: float
    total_tax_depreciation_keur: float
    total_non_depreciable_basis_keur: float


@dataclass(frozen=True)
class DepreciationAuditRow:
    """One row of the Depreciation audit export.

    Attributes
    ----------
    period_index : int
    asset_class : str
    gross_asset_basis_keur : float
    book_depreciation_keur : float
    tax_depreciation_keur : float
    accumulated_book_depreciation_keur : float
    accumulated_tax_depreciation_keur : float
    nbv_book_keur : float
    nbv_tax_keur : float
    book_tax_difference_keur : float
    book_policy_years : int
    tax_policy_years : int
    is_financing_cost : bool
    is_land : bool
    is_depreciable : bool
    placed_in_service_period : int
    warnings : Tuple[str, ...]
    """
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
    book_policy_years: int
    tax_policy_years: int
    is_financing_cost: bool
    is_land: bool
    is_depreciable: bool
    placed_in_service_period: int
    warnings: Tuple[str, ...] = ()


class DepreciationEngine:
    """Canonical depreciation engine.

    Computes book and tax depreciation per asset class, per period.
    Separates book depreciation (for P&L / financial statements)
    from tax depreciation (for TaxEngine).

    Does NOT compute:
        - Tax payable or cash tax
        - Senior debt, SHL, distribution, or sponsor IRR
        - R99/R102 gates

    Usage
    -----
        inputs = DepreciationEngineInputs(
            project_name="Generic Wind Reference",
            asset_classes=tuple(assets),
            policies={"default": policy, ...},
            period_count=63,
            period_frequency="semiannual",
            cod_period=2,
        )
        result = DepreciationEngine.compute(inputs)
    """

    @staticmethod
    def compute(inputs: DepreciationEngineInputs) -> DepreciationEngineResult:
        ledger_input = DepreciationLedgerInput(
            asset_classes=inputs.asset_classes,
            policies=inputs.policies,
            period_count=inputs.period_count,
            period_frequency=inputs.period_frequency,
            cod_period=inputs.cod_period,
        )

        ledger_result = build_depreciation_ledger(ledger_input)

        # Build audit rows
        audit_rows = []
        non_depreciable_basis = 0.0

        for period_result in ledger_result.periods:
            asset = next(
                (a for a in inputs.asset_classes if a.asset_class == period_result.asset_class),
                None,
            )
            policy = inputs.policies.get(period_result.asset_class) or inputs.policies.get("default")

            # Check flags
            is_land = (asset and "land" in asset.asset_class.lower()) if asset else False
            is_financing_cost = (
                asset and "financing" in asset.asset_class.lower()
            ) or (
                policy and "financing" in str(getattr(policy, "label", "")).lower()
            )

            # Accumulate non-depreciable basis
            if is_land or (asset and not _is_depreciable(asset)):
                non_depreciable_basis += period_result.gross_asset_basis_keur

            # Warnings
            warnings = _compute_warnings(period_result, policy, is_land)

            book_years = policy.useful_life_book_periods * 2 if policy and policy.useful_life_book_periods else None
            tax_years = policy.useful_life_tax_periods * 2 if policy and policy.useful_life_tax_periods else None

            audit_rows.append(
                DepreciationAuditRow(
                    period_index=period_result.period_index,
                    asset_class=period_result.asset_class,
                    gross_asset_basis_keur=period_result.gross_asset_basis_keur,
                    book_depreciation_keur=period_result.book_depreciation_keur,
                    tax_depreciation_keur=period_result.tax_depreciation_keur,
                    accumulated_book_depreciation_keur=period_result.accumulated_book_depreciation_keur,
                    accumulated_tax_depreciation_keur=period_result.accumulated_tax_depreciation_keur,
                    nbv_book_keur=period_result.nbv_book_keur,
                    nbv_tax_keur=period_result.nbv_tax_keur,
                    book_tax_difference_keur=period_result.book_tax_difference_keur,
                    book_policy_years=book_years,
                    tax_policy_years=tax_years,
                    is_financing_cost=is_financing_cost,
                    is_land=is_land,
                    is_depreciable=not is_land and _is_depreciable(asset) if asset else True,
                    placed_in_service_period=asset.placed_in_service_period if asset else 0,
                    warnings=tuple(warnings),
                )
            )

        return DepreciationEngineResult(
            project_name=inputs.project_name,
            period_count=inputs.period_count,
            ledger_result=ledger_result,
            audit_rows=tuple(audit_rows),
            total_book_depreciation_keur=ledger_result.total_book_depreciation_keur,
            total_tax_depreciation_keur=ledger_result.total_tax_depreciation_keur,
            total_non_depreciable_basis_keur=non_depreciable_basis,
        )


def _is_depreciable(asset: AssetClassConfig) -> bool:
    """Check if an asset class is depreciable."""
    if asset.book_depreciable_basis_keur <= 0 and asset.tax_depreciable_basis_keur <= 0:
        return False
    return True


def _compute_warnings(
    period_result: DepreciationPeriodResult,
    policy: DepreciationPolicy | None,
    is_land: bool,
) -> list[str]:
    warnings = []
    if is_land and period_result.book_depreciation_keur > 0:
        warnings.append("land_should_not_be_depreciated")
    if period_result.book_depreciation_keur < 0:
        warnings.append("negative_book_depreciation")
    if period_result.tax_depreciation_keur < 0:
        warnings.append("negative_tax_depreciation")
    if policy is None:
        warnings.append("no_policy_found")
    return warnings