"""domain/depreciation/canonical_wiring — Phase 8: Canonical DepreciationEngine runtime wiring.

This module wires the canonical DepreciationEngine (domain/depreciation/engine.py)
into the runtime waterfall when use_depreciation_canonical_engine=True, replacing
the legacy aggregate depreciation_keur and tax_depreciation_audit_keur fields.

Design
------
When the flag is True, the canonical engine computes per-asset-class book and
tax depreciation per period with full audit rows. The wiring layer aggregates
those into waterfall runtime fields:

  WaterfallPeriod.depreciation_keur          ← canonical book dep (tax shield / P&L)
  WaterfallPeriod.tax_depreciation_audit_keur ← canonical tax dep (R35 bridge)
  result._canonical_depreciation_wiring     ← full audit rows + diagnostics

Canonical → runtime field mapping (when flag=True):
  depreciation_keur              ← total book depreciation per period
  tax_depreciation_audit_keur    ← total tax depreciation per period
  book_depreciation_by_period    ← canonical DepreciationAuditRow per period
  total_book_depreciation_keur   ← sum across all operating periods
  total_tax_depreciation_keur    ← sum across all operating periods
  total_non_depreciable_basis    ← land / non-depreciable basis

NOT changed by this wiring:
  - Senior debt, SHL, DSRA, distributions, DSCR, IRR
  - Tax payable or cash tax (handled by TaxBridge or tax engine)
  - R99/R102 gates

R99/R102: BLOCKED — depreciation wiring affects tax-shield and P&L fields only.
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from finco_core.depreciation.engine import DepreciationEngineResult
    from finco_core.depreciation.engine import DepreciationAuditRow
    from finco_core.depreciation.asset import AssetClassConfig
    from finco_core.depreciation.schedule import DepreciationPolicy


# Generic Market B/Generic Market A tax regime: useful lives by CapexItem asset class
# These differ from IFRS book lives — book follows project life (25 yr for solar/wind),
# tax follows local tax codes.
_BOOK_LIFE_YEARS = 25  # straight-line over project horizon
_TAX_LIFE_YEARS_MAP = {
    "solar_panels": 25,
    "wind_turbines": 25,
    "bess_cells": 10,
    "bess_power_electronics": 15,
    "civil_grid": 30,
    "soft_costs": 5,
    "financial_costs": 14,
    # Generic non-generation technical plant (Generic Data Center Reference V1)
    "dc_plant": 15,
    # Fallback
    "other": 20,
    "grid": 20,
    "generation": 25,
    "epc": 25,
    "development": 5,
    "contingency": 5,
    "land": 0,
}


def _tax_life_for_asset_class(asset_class: str, fallback_years: int = 20) -> int:
    """Return tax useful life for an asset class string."""
    key = asset_class.lower()
    if key in _TAX_LIFE_YEARS_MAP:
        life = _TAX_LIFE_YEARS_MAP[key]
        return life if life > 0 else fallback_years
    # Try to find as substring
    for k, v in _TAX_LIFE_YEARS_MAP.items():
        if k in key:
            return v if v > 0 else fallback_years
    return fallback_years


@dataclass(frozen=True)
class CanonicalDepreciationWiringResult:
    """Result of wiring canonical DepreciationEngine into waterfall output.

    Attributes
    ----------
    book_depreciation_by_period : tuple[float, ...]
        Total book depreciation per period index (kEUR).
    tax_depreciation_by_period : tuple[float, ...]
        Total tax depreciation per period index (kEUR).
    book_tax_difference_by_period : tuple[float, ...]
        Book − tax depreciation difference per period (kEUR).
    non_depreciable_basis_by_period : tuple[float, ...]
        Non-depreciable basis (land) per period index (kEUR).
    total_book_depreciation_keur : float
        Sum of all book depreciation across operating periods.
    total_tax_depreciation_keur : float
        Sum of all tax depreciation across operating periods.
    total_non_depreciable_basis_keur : float
        Total land / non-depreciable asset basis (kEUR).
    all_book_non_negative : bool
        True if all book depreciation values are non-negative.
    all_tax_non_negative : bool
        True if all tax depreciation values are non-negative.
    canonical_engine_result : DepreciationEngineResult
        Full canonical engine result for audit export.
    """

    book_depreciation_by_period: tuple[float, ...]
    tax_depreciation_by_period: tuple[float, ...]
    book_tax_difference_by_period: tuple[float, ...]
    non_depreciable_basis_by_period: tuple[float, ...]
    total_book_depreciation_keur: float
    total_tax_depreciation_keur: float
    total_non_depreciable_basis_keur: float
    all_book_non_negative: bool = True
    all_tax_non_negative: bool = True
    canonical_engine_result: "DepreciationEngineResult | None" = None


def build_canonical_depreciation_wiring(
    project_name: str,
    capex_items: tuple,
    horizon_years: int,
    cod_period: int = 2,
    period_frequency: str = "semiannual",
    explicit_policies: Mapping[str, "DepreciationPolicy"] | None = None,
) -> CanonicalDepreciationWiringResult:
    """Build canonical DepreciationEngine result wired into waterfall-ready arrays.

    Parameters
    ----------
    project_name : str
        Project name, e.g. "Generic Wind Reference", "Generic Solar Reference".
    capex_items : tuple[CapexItem, ...]
        CapexItem tuple from CapexStructure (may contain items with amount_keur=0).
    horizon_years : int
        Number of operating years (30 for Generic Wind Reference/Generic Solar Reference).
    cod_period : int
        COD period index (1-based semiannual, default 2 = first operating period).
        Generic Wind Reference COD: 2 (P2 is first operating period after 6-month construction).
    period_frequency : str
        "semiannual" for Generic Wind Reference/Generic Solar Reference.
    explicit_policies : Mapping[str, DepreciationPolicy], optional
        Explicit DepreciationPolicy per asset class.
        If absent, policies are derived from CapexItem asset_class.

    Returns
    -------
    CanonicalDepreciationWiringResult
        Aggregated per-period values + full canonical result for audit.

    The canonical engine uses DepreciationPolicy with useful_life_book_periods
    and useful_life_tax_periods in **semiannual periods** (not years).
    Book lives are horizon-based (straight-line over project life).
    Tax lives use the _TAX_LIFE_YEARS_MAP (Generic Market B/Generic Market A regime).
    """
    from finco_core.depreciation.engine import DepreciationEngine, DepreciationEngineInputs
    from finco_core.depreciation.asset import AssetClassConfig
    from finco_core.depreciation.schedule import DepreciationPolicy
    from finco_core.debt.depreciation_schedule import useful_life_for_item

    # Filter to non-zero capex items
    active_items = [item for item in capex_items if item.amount_keur > 0]

    if not active_items:
        return CanonicalDepreciationWiringResult(
            book_depreciation_by_period=tuple([0.0] * horizon_years * 2),
            tax_depreciation_by_period=tuple([0.0] * horizon_years * 2),
            book_tax_difference_by_period=tuple([0.0] * horizon_years * 2),
            non_depreciable_basis_by_period=tuple([0.0] * horizon_years * 2),
            total_book_depreciation_keur=0.0,
            total_tax_depreciation_keur=0.0,
            total_non_depreciable_basis_keur=0.0,
            canonical_engine_result=None,
        )

    # Build AssetClassConfig for each capex item
    asset_configs: list[AssetClassConfig] = []
    policies: dict[str, DepreciationPolicy] = dict(explicit_policies) if explicit_policies else {}

    for item in active_items:
        asset_class_str = item.asset_class.value if hasattr(item.asset_class, 'value') else str(item.asset_class)
        tax_life_periods = _tax_life_for_asset_class(asset_class_str) * 2

        # When an item carries useful_life_override, use item.name as the policy key so
        # items with the same asset_class but different proven book lives (e.g. IDC=12y,
        # VAT=20y, both financial_costs) each get their own straight-line schedule.
        if getattr(item, 'useful_life_override', None) is not None:
            policy_key = f"{asset_class_str}:{item.name}"
            book_life_periods = item.useful_life_override * 2  # semiannual
        else:
            policy_key = asset_class_str
            # Use per-asset-class policy from ASSET_CLASS_USEFUL_LIFE, not model horizon.
            # Horizon-based default was incorrect: a 20y-life asset in a 30y model
            # was getting a 30y book life. Each asset class now carries its own book life.
            book_life_periods = useful_life_for_item(item) * 2  # semiannual

        asset_configs.append(
            AssetClassConfig(
                asset_class=policy_key,
                gross_asset_basis_keur=item.amount_keur,
                book_depreciable_basis_keur=item.amount_keur,
                tax_depreciable_basis_keur=item.amount_keur,
                placed_in_service_period=0,
                depreciation_start_period=0,
                source_label=f"capex:{item.name}",
            )
        )

        # Add policy if not already explicit
        if policy_key not in policies:
            policies[policy_key] = DepreciationPolicy(
                method="straight_line",
                useful_life_book_periods=book_life_periods,
                useful_life_tax_periods=tax_life_periods,
                period_frequency=period_frequency,
            )

    # Add "default" policy for items without explicit policies
    if "default" not in policies:
        policies["default"] = DepreciationPolicy(
            method="straight_line",
            useful_life_book_periods=horizon_years * 2,
            useful_life_tax_periods=20 * 2,
            period_frequency=period_frequency,
        )

    period_count = horizon_years * 2  # semiannual

    # Run canonical engine
    inputs = DepreciationEngineInputs(
        project_name=project_name,
        asset_classes=tuple(asset_configs),
        policies=policies,
        period_count=period_count,
        period_frequency=period_frequency,
        cod_period=cod_period,
    )

    canonical_result = DepreciationEngine.compute(inputs)

    # Aggregate per period (combine all asset classes)
    wiring = wire_canonical_depreciation_into_waterfall(canonical_result, period_count)

    # Attach canonical result for audit
    return CanonicalDepreciationWiringResult(
        book_depreciation_by_period=wiring.book_depreciation_by_period,
        tax_depreciation_by_period=wiring.tax_depreciation_by_period,
        book_tax_difference_by_period=wiring.book_tax_difference_by_period,
        non_depreciable_basis_by_period=wiring.non_depreciable_basis_by_period,
        total_book_depreciation_keur=wiring.total_book_depreciation_keur,
        total_tax_depreciation_keur=wiring.total_tax_depreciation_keur,
        total_non_depreciable_basis_keur=wiring.total_non_depreciable_basis_keur,
        all_book_non_negative=wiring.all_book_non_negative,
        all_tax_non_negative=wiring.all_tax_non_negative,
        canonical_engine_result=canonical_result,
    )


def wire_canonical_depreciation_into_waterfall(
    canonical_result: "DepreciationEngineResult",
    period_count: int,
) -> CanonicalDepreciationWiringResult:
    """Build wiring result from canonical DepreciationEngine output.

    Parameters
    ----------
    canonical_result : DepreciationEngineResult
        Output from DepreciationEngine.compute().
    period_count : int
        Number of semiannual operating periods to wire.

    Returns
    -------
    CanonicalDepreciationWiringResult
        Aggregated per-period values ready for waterfall runtime.
    """
    from finco_core.depreciation.engine import DepreciationAuditRow

    # Index audit rows by period_index, accumulating all asset classes per period
    rows_by_period: dict[int, "DepreciationAuditRow"] = {}
    for row in canonical_result.audit_rows:
        if row.period_index not in rows_by_period:
            rows_by_period[row.period_index] = row
        else:
            existing = rows_by_period[row.period_index]
            rows_by_period[row.period_index] = _accumulate_rows(existing, row)

    book_by_period = []
    tax_by_period = []
    btdiff_by_period = []
    non_dep_by_period = []

    for p in range(period_count):
        row = rows_by_period.get(p)
        if row:
            book_by_period.append(row.book_depreciation_keur)
            tax_by_period.append(row.tax_depreciation_keur)
            btdiff_by_period.append(row.book_tax_difference_keur)
            non_dep_by_period.append(
                row.gross_asset_basis_keur if (row.is_land or not row.is_depreciable) else 0.0
            )
        else:
            book_by_period.append(0.0)
            tax_by_period.append(0.0)
            btdiff_by_period.append(0.0)
            non_dep_by_period.append(0.0)

    all_book_non_neg = all(d >= -0.01 for d in book_by_period)
    all_tax_non_neg = all(d >= -0.01 for d in tax_by_period)

    return CanonicalDepreciationWiringResult(
        book_depreciation_by_period=tuple(book_by_period),
        tax_depreciation_by_period=tuple(tax_by_period),
        book_tax_difference_by_period=tuple(btdiff_by_period),
        non_depreciable_basis_by_period=tuple(non_dep_by_period),
        total_book_depreciation_keur=canonical_result.total_book_depreciation_keur,
        total_tax_depreciation_keur=canonical_result.total_tax_depreciation_keur,
        total_non_depreciable_basis_keur=canonical_result.total_non_depreciable_basis_keur,
        all_book_non_negative=all_book_non_neg,
        all_tax_non_negative=all_tax_non_neg,
    )


def _accumulate_rows(
    a: "DepreciationAuditRow",
    b: "DepreciationAuditRow",
) -> "DepreciationAuditRow":
    """Accumulate two audit rows (same period, different asset class)."""
    from finco_core.depreciation.engine import DepreciationAuditRow

    return DepreciationAuditRow(
        period_index=a.period_index,
        asset_class="COMBINED",
        gross_asset_basis_keur=a.gross_asset_basis_keur + b.gross_asset_basis_keur,
        book_depreciation_keur=a.book_depreciation_keur + b.book_depreciation_keur,
        tax_depreciation_keur=a.tax_depreciation_keur + b.tax_depreciation_keur,
        accumulated_book_depreciation_keur=(
            a.accumulated_book_depreciation_keur + b.accumulated_book_depreciation_keur
        ),
        accumulated_tax_depreciation_keur=(
            a.accumulated_tax_depreciation_keur + b.accumulated_tax_depreciation_keur
        ),
        nbv_book_keur=a.nbv_book_keur + b.nbv_book_keur,
        nbv_tax_keur=a.nbv_tax_keur + b.nbv_tax_keur,
        book_tax_difference_keur=a.book_tax_difference_keur + b.book_tax_difference_keur,
        book_policy_years=a.book_policy_years,
        tax_policy_years=a.tax_policy_years,
        is_financing_cost=a.is_financing_cost or b.is_financing_cost,
        is_land=a.is_land or b.is_land,
        is_depreciable=a.is_depreciable or b.is_depreciable,
        placed_in_service_period=a.placed_in_service_period or b.placed_in_service_period,
        warnings=a.warnings + b.warnings,
    )