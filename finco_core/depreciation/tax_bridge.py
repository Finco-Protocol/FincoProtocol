"""domain/depreciation/tax_bridge — Canonical Depreciation → TaxEngine bridge.

Bridges canonical DepreciationEngine outputs into the tax calculation path
in a minimal, default-safe way.

Design
------
The canonical DepreciationEngine computes:
  - book_depreciation_keur per period (for P&L)
  - tax_depreciation_keur per period (for TaxEngine)

This adapter bridges tax_depreciation into the existing tax runtime path.
It does NOT rewrite TaxEngine or change default behavior.

When use_canonical_tax_depreciation_bridge=False (default):
  → Existing DepreciationSchedule / waterfall path unchanged

When use_canonical_tax_depreciation_bridge=True:
  → Canonical DepreciationEngine computes tax_depreciation
  → Exposed as audit output in TaxBridgeResult
  → NOT wired as runtime input unless explicitly configured

R99/R102: BLOCKED — this bridge does not touch R99/R102 gates.
No deferred tax, no HoldCo tax, no sponsor IRR.
"""
from dataclasses import dataclass
from typing import Optional

from finco_core.depreciation.engine import DepreciationEngine, DepreciationEngineInputs
from finco_core.depreciation.asset import AssetClassConfig
from finco_core.depreciation.schedule import DepreciationPolicy


@dataclass(frozen=True)
class DepreciationTaxBridgeResult:
    """Result of bridging canonical depreciation into tax path.

    Attributes
    ----------
    tax_depreciation_by_period_keur : tuple[float, ...]
        Tax depreciation per semiannual period (63 periods for Generic Wind Reference).
        Period index 0 = first semiannual period (construction, often 0).
    book_depreciation_by_period_keur : tuple[float, ...]
        Book depreciation per semiannual period.
    total_tax_depreciation_keur : float
        Sum of all tax depreciation over project life.
    total_book_depreciation_keur : float
        Sum of all book depreciation over project life.
    audit_rows : tuple[DepreciationTaxAuditRow, ...]
        Per-period audit rows for tax bridge verification.
    canonical_engine_version : str
        Version tag for the canonical engine used.
    """
    tax_depreciation_by_period_keur: tuple[float, ...]
    book_depreciation_by_period_keur: tuple[float, ...]
    total_tax_depreciation_keur: float
    total_book_depreciation_keur: float
    audit_rows: tuple["DepreciationTaxAuditRow", ...]
    canonical_engine_version: str = "1.0"


@dataclass(frozen=True)
class DepreciationTaxAuditRow:
    """Per-period audit row for tax bridge verification."""
    period_index: int
    asset_class: str
    book_depreciation_keur: float
    tax_depreciation_keur: float
    book_tax_difference_keur: float
    accumulated_book_depreciation_keur: float
    accumulated_tax_depreciation_keur: float
    nbv_book_keur: float
    nbv_tax_keur: float
    book_policy_years: int
    tax_policy_years: int
    is_financing_cost: bool
    is_land: bool


# Canonical engine version tag
CANONICAL_ENGINE_VERSION = "1.0"


def build_depreciation_tax_bridge(
    project_name: str,
    asset_classes: tuple[AssetClassConfig, ...],
    policies: dict[str, DepreciationPolicy],
    period_count: int = 63,
    cod_period: int = 2,
    period_frequency: str = "semiannual",
) -> DepreciationTaxBridgeResult:
    """Build canonical depreciation and bridge to tax path.

    Parameters
    ----------
    project_name : str
        Project name (e.g., "Generic Wind Reference", "Generic Solar Reference").
    asset_classes : tuple[AssetClassConfig, ...]
        Asset class configurations (from existing CapexLineItems).
    policies : dict[str, DepreciationPolicy]
        Depreciation policies per asset class.
        Include "default" policy for asset classes without explicit policy.
    period_count : int, default 63
        Total semiannual periods (Generic Wind Reference = 63).
    cod_period : int, default 2
        COD period index (Generic Wind Reference = 2, first operating period).
    period_frequency : str, default "semiannual"
        Period frequency.

    Returns
    -------
    DepreciationTaxBridgeResult
        Canonical depreciation bridged to tax path.
        tax_depreciation_by_period_keur is the key output for TaxEngine.

    Note
    ----
    This function does NOT wire to TaxEngine. It produces an audit result
    that can be used to verify or validate the existing tax depreciation path.
    R99/R102: BLOCKED — no interaction with distribution gates.
    """
    inputs = DepreciationEngineInputs(
        project_name=project_name,
        asset_classes=asset_classes,
        policies=policies,
        period_count=period_count,
        period_frequency=period_frequency,
        cod_period=cod_period,
    )

    canonical_result = DepreciationEngine.compute(inputs)

    # Aggregate all asset classes per period
    ledger_result = canonical_result.ledger_result
    aggregated_periods = ledger_result.aggregate_periods()

    # Build tax and book depreciation series
    tax_dep_series = []
    book_dep_series = []
    audit_rows = []

    for period_result in aggregated_periods:
        tax_dep_series.append(period_result.tax_depreciation_keur)
        book_dep_series.append(period_result.book_depreciation_keur)

        policy = policies.get(period_result.asset_class) or policies.get("default")
        book_years = policy.useful_life_book_periods * 2 if policy and policy.useful_life_book_periods else 0
        tax_years = policy.useful_life_tax_periods * 2 if policy and policy.useful_life_tax_periods else 0

        is_financing_cost = (
            "financing" in period_result.asset_class.lower()
        )
        is_land = (
            "land" in period_result.asset_class.lower()
            or period_result.book_depreciation_keur == 0
            and period_result.tax_depreciation_keur == 0
            and period_result.gross_asset_basis_keur > 0
        )

        audit_rows.append(
            DepreciationTaxAuditRow(
                period_index=period_result.period_index,
                asset_class=period_result.asset_class,
                book_depreciation_keur=period_result.book_depreciation_keur,
                tax_depreciation_keur=period_result.tax_depreciation_keur,
                book_tax_difference_keur=period_result.book_tax_difference_keur,
                accumulated_book_depreciation_keur=period_result.accumulated_book_depreciation_keur,
                accumulated_tax_depreciation_keur=period_result.accumulated_tax_depreciation_keur,
                nbv_book_keur=period_result.nbv_book_keur,
                nbv_tax_keur=period_result.nbv_tax_keur,
                book_policy_years=book_years,
                tax_policy_years=tax_years,
                is_financing_cost=is_financing_cost,
                is_land=is_land,
            )
        )

    return DepreciationTaxBridgeResult(
        tax_depreciation_by_period_keur=tuple(tax_dep_series),
        book_depreciation_by_period_keur=tuple(book_dep_series),
        total_tax_depreciation_keur=ledger_result.total_tax_depreciation_keur,
        total_book_depreciation_keur=ledger_result.total_book_depreciation_keur,
        audit_rows=tuple(audit_rows),
        canonical_engine_version=CANONICAL_ENGINE_VERSION,
    )


def validate_bridge_against_waterfall(
    canonical_bridge: DepreciationTaxBridgeResult,
    waterfall_tax_dep_by_period: tuple[float, ...],
    tolerance: float = 1.0,
) -> "BridgeValidationResult":
    """Validate canonical bridge against runtime waterfall tax depreciation.

    Parameters
    ----------
    canonical_bridge : DepreciationTaxBridgeResult
        Canonical bridge result.
    waterfall_tax_dep_by_period : tuple[float, ...]
        Tax depreciation per period from runtime waterfall.
    tolerance : float, default 1.0
        Tolerance in kEUR for matching.

    Returns
    -------
    BridgeValidationResult
        Validation result with match status per period.
    """
    mismatches = []
    for i, (canon, runtime) in enumerate(zip(
        canonical_bridge.tax_depreciation_by_period_keur,
        waterfall_tax_dep_by_period,
    )):
        if abs(canon - runtime) > tolerance:
            mismatches.append({
                "period_index": i,
                "canonical_keur": canon,
                "runtime_keur": runtime,
                "difference_keur": canon - runtime,
            })

    return BridgeValidationResult(
        total_periods=len(canonical_bridge.tax_depreciation_by_period_keur),
        matching_periods=len(canonical_bridge.tax_depreciation_by_period_keur) - len(mismatches),
        mismatched_periods=len(mismatches),
        mismatches=tuple(mismatches) if mismatches else (),
        all_match=len(mismatches) == 0,
    )


@dataclass(frozen=True)
class BridgeValidationResult:
    """Result of validating canonical bridge against runtime."""
    total_periods: int
    matching_periods: int
    mismatched_periods: int
    mismatches: tuple[dict, ...] = ()
    all_match: bool = False


# Re-export canonical engine for convenience
from finco_core.depreciation.engine import DepreciationEngine, DepreciationEngineInputs
from finco_core.depreciation.asset import AssetClassConfig
from finco_core.depreciation.schedule import DepreciationPolicy

__all__ = [
    "DepreciationTaxBridgeResult",
    "DepreciationTaxAuditRow",
    "DepreciationEngine",
    "DepreciationEngineInputs",
    "AssetClassConfig",
    "DepreciationPolicy",
    "build_depreciation_tax_bridge",
    "validate_bridge_against_waterfall",
    "BridgeValidationResult",
    "CANONICAL_ENGINE_VERSION",
]