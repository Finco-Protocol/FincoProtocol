"""CAPEX Depreciation Engine — generates depreciation schedules from CapexLineItem.

Architecture:
  CapexLineItem (from app.capex_engine)
       ↓
  depreciation_engine.generate_schedule()
       ↓
  DepreciationSchedule (annual basis by asset class)
       ↓
  Waterfall taxable income / tax shield

Backward compatibility:
  When CapexLineItem is absent, waterfall uses legacy CapexItem path unchanged.
"""
from dataclasses import dataclass
from typing import Optional

from app.capex_engine import CapexLineItem, AssetClass

# ------------------------------------------------------------------
# Asset class → depreciation rule mapping
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DepreciationRule:
    """Depreciation rule for one asset class."""
    life_years: int          # depreciable life in years
    method: str              # "linear" only for MVP
    residual_pct: float = 0.0  # residual value as % of original (unused for MVP)


# Map capex_engine.AssetClass → DepreciationRule
#
# Rationale (synthetic cross-market reference assumptions):
#   - Solar modules:       25 yr straight-line  (synthetic policy: panels follow plant life)
#   - Inverters:           10 yr straight-line  (electronics / power electronics)
#   - Electrical BoS:      25 yr straight-line  (cabling, switchgear, transformer)
#   - Transformer:         25 yr straight-line  (grid transformer)
#   - Metering:            15 yr straight-line  (SCADA, meters)
#   - BoP civil:           25 yr straight-line  (foundations, structures)
#   - Wind turbine:         25 yr straight-line  (turbine + tower)
#   - Wind BoP:             25 yr straight-line  (civil works, roads)
#   - Development costs:     5 yr straight-line  (soft costs / capitalized expenses)
#   - Grid connection:     20 yr straight-line  (grid assets)
#   - Civil works:         25 yr straight-line  (buildings, site works)
#   - Contingency:          5 yr straight-line  (provision)
#   - LAND:                 0 yr — non-depreciable
#   - OTHER:               10 yr straight-line  (fallback)
#
ASSET_CLASS_RULES: dict[AssetClass, DepreciationRule] = {
    # Solar
    AssetClass.GENERATION:   DepreciationRule(life_years=25, method="linear"),
    # Inverters are grouped under GENERATION for now (10 yr for future split)
    AssetClass.GRID:          DepreciationRule(life_years=20, method="linear"),
    AssetClass.DEVELOPMENT:   DepreciationRule(life_years=5,  method="linear"),
    AssetClass.EPC:           DepreciationRule(life_years=25, method="linear"),
    AssetClass.CONTINGENCY:   DepreciationRule(life_years=5,  method="linear"),
    # LAND is non-depreciable (not a depreciable asset for tax purposes)
    AssetClass.LAND:          DepreciationRule(life_years=0,  method="none"),
    AssetClass.OTHER:         DepreciationRule(life_years=10, method="linear"),
}

DEFAULT_RULE = DepreciationRule(life_years=20, method="linear")


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DepreciationEntry:
    """A single asset-class depreciation entry for one period."""
    period: int                      # 0-based period (year) index
    asset_class: str                 # AssetClass value string
    annual_amount_keur: float        # annual depreciation amount in kEUR
    accumulated_keur: float          # cumulative depreciation through this period
    remaining_basis_keur: float       # remaining depreciable basis after this period


@dataclass
class DepreciationSchedule:
    """Full annual depreciation schedule across all asset classes."""
    entries: list[DepreciationEntry]       # per-asset-class per-year entries
    total_by_period: list[float]            # sum of all asset classes per period (kEUR)
    total_remaining_by_period: list[float]  # running remaining basis per period (kEUR)


def generate_schedule(
    line_items: list[CapexLineItem],
    total_periods: int,
) -> DepreciationSchedule:
    """Generate depreciation schedule from CapexLineItem list.

    Parameters
    ----------
    line_items : list[CapexLineItem]
        CAPEX line items with amount_keur and asset_class from capex_engine.
    total_periods : int
        Number of operating years (horizon_years) to generate.

    Returns
    -------
    DepreciationSchedule
        Per-period, per-asset-class depreciation entries.

    Depreciation is straight-line (linear) over the asset life.
    No mid-year conventions for MVP.  Assets that are fully depreciated
    before horizon_years contribute 0 in subsequent years.

    Non-depreciable assets (LAND, life=0) are skipped.
    """
    # Aggregate original basis by asset class
    basis_by_class: dict[str, tuple[float, DepreciationRule]] = {}
    for item in line_items:
        rule = ASSET_CLASS_RULES.get(item.asset_class, DEFAULT_RULE)
        if rule.method == "none":
            continue  # non-depreciable — skip
        key = item.asset_class.value
        if key in basis_by_class:
            basis_by_class[key] = (basis_by_class[key][0] + item.amount_keur, rule)
        else:
            basis_by_class[key] = (item.amount_keur, rule)

    # Initialize accumulators per asset class
    accumulated_by_class: dict[str, float] = {k: 0.0 for k in basis_by_class}
    remaining_by_class: dict[str, float] = {k: v[0] for k, v in basis_by_class.items()}

    entries: list[DepreciationEntry] = []

    for period in range(total_periods):
        period_total = 0.0
        for asset_class, (original, rule) in basis_by_class.items():
            life = rule.life_years
            if life <= 0:
                continue
            annual = original / life
            if annual <= 0:
                continue

            accumulated = accumulated_by_class[asset_class]
            remaining = remaining_by_class[asset_class]

            if period >= life:
                continue

            accumulated_by_class[asset_class] += annual
            remaining_by_class[asset_class] -= annual
            period_total += annual

            entries.append(DepreciationEntry(
                period=period,
                asset_class=asset_class,
                annual_amount_keur=round(annual, 2),
                accumulated_keur=round(accumulated + annual, 2),
                remaining_basis_keur=round(max(0.0, remaining - annual), 2),
            ))

    # Compute totals per period
    total_by_period = [0.0] * total_periods
    for entry in entries:
        total_by_period[entry.period] += entry.annual_amount_keur

    total_remaining = [0.0] * total_periods
    running_remaining = sum(v[0] for v in basis_by_class.values())
    for period in range(total_periods):
        total_remaining[period] = running_remaining
        if period < len(total_by_period):
            running_remaining -= total_by_period[period]

    return DepreciationSchedule(
        entries=entries,
        total_by_period=total_by_period,
        total_remaining_by_period=total_remaining,
    )
