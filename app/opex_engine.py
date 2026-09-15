"""OPEX line-item engine — granular OPEX with manual/hardcoded override support.

This module provides a line-item layer on top of the domain-level OpexParams.
It is fully backward-compatible: if no line items are provided, the existing
OpexParams-based calculation is used unchanged.

New layer:
- OpexLineItem  — individual OPEX line with name, category, amount, inflation
- OpexScheduleEntry — single year's computed value + metadata
- generate_opex_schedule() — build per-year schedule from line items

Design principles:
- Immutable dataclasses (frozen=True) for all data structures
- source: formula | manual | hardcoded
- is_hardcoded flag for amber/warning UI indicators
- Override note stored per line item
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CalculationMode(str, Enum):
    """How an OPEX line item is calculated each year."""
    INFLATED_FROM_BASE = "inflated_from_base"  # Compound inflation on base-year amount
    MANUAL_SCHEDULE = "manual_schedule"         # Explicit per-year values
    MIXED = "mixed"                            # Some years formula, others manual override


class OpexSource(str, Enum):
    """Provenance of the values in an OPEX line item."""
    FORMULA = "formula"      # Driven by a formula/rule
    MANUAL = "manual"        # User-entered values
    HARDCODED = "hardcoded"  # Manually entered and locked (spreadsheet-style hardcoded cell)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass(frozen=True)
class OpexLineItem:
    """A single OPEX line item.

    Examples:
        - "Technical Management" (B.01), category="operations", base=198 kEUR, inflation=2%
        - "Insurance", category="insurance", base=280 kEUR, inflation=1.5%
        - "Land Lease", category="land", base=150 kEUR, inflation=0%
    """
    name: str
    """Human-readable name, e.g. 'Technical Management'."""

    category: str
    """Category for grouping, e.g. 'operations', 'insurance', 'land', 'admin'."""

    base_year_amount_keur: float = 0.0
    """Base-year (Year 1) amount in kEUR."""

    inflation_rate: float = 0.0
    """Annual compound inflation rate (0.02 = 2%). 0 = no inflation."""

    calculation_mode: CalculationMode = CalculationMode.INFLATED_FROM_BASE
    """How to compute values for years > 1."""

    annual_values_keur: tuple[float, ...] = field(default_factory=lambda: ())
    """Explicit per-year values for MANUAL_SCHEDULE or MIXED mode. Index = year_index (0-based)."""

    manual_overrides_keur: tuple[float | None, ...] = field(default_factory=lambda: ())
    """Manual overrides for specific years. Index = year_index (0-based). None means no override for that year; a float value overrides the inflated value."""

    is_hardcoded: bool = False
    """True if this line was manually entered and should be visually flagged as hardcoded."""

    override_note: str = ""
    """Free-text note explaining why a manual/hardcoded value was entered."""

    source: OpexSource = OpexSource.FORMULA
    """Provenance of this line's values."""

    def __post_init__(self):
        # Validate that annual_values_keur and manual_overrides_keur are consistent with mode
        if self.calculation_mode == CalculationMode.MANUAL_SCHEDULE:
            if not self.annual_values_keur:
                raise ValueError(
                    f"OpexLineItem '{self.name}' has MANUAL_SCHEDULE mode "
                    "but annual_values_keur is empty."
                )

    def has_manual_overrides(self) -> bool:
        """Return True if any year has a non-None manual override."""
        return any(v is not None for v in self.manual_overrides_keur)

    def is_formula_driven(self) -> bool:
        """Return True if this line is purely formula-driven (no manual/hardcoded)."""
        return self.source == OpexSource.FORMULA and not self.has_manual_overrides()


@dataclass(frozen=True)
class OpexScheduleEntry:
    """A single year's computed OPEX value for one line item."""
    line_item_name: str
    category: str               # Copied directly from OpexLineItem.category
    year_index: int          # 0-based year index (year 1 = index 0)
    value_keur: float
    source: OpexSource
    is_override: bool        # True if this specific year's value was manually overridden
    is_hardcoded: bool       # Copied from OpexLineItem.is_hardcoded
    override_note: str = ""
    inflation_factor: float = 1.0  # Cumulative inflation factor applied


@dataclass(frozen=True)
class OpexSchedule:
    """Full OPEX schedule for all line items across all years."""
    entries: tuple[OpexScheduleEntry, ...] = field(default_factory=lambda: ())
    """All individual entries. Access via items_for_year() or items_by_category()."""

    total_by_year: tuple[float, ...] = field(default_factory=lambda: ())
    """Total OPEX per year (0-based index). Sum of all line items, including overrides."""

    has_manual_overrides: bool = False
    """True if any line item has at least one manual override year."""

    has_hardcoded_items: bool = False
    """True if any line item is marked is_hardcoded=True."""

    def items_for_year(self, year_index: int) -> list[OpexScheduleEntry]:
        """Get all entries for a given year index."""
        return [e for e in self.entries if e.year_index == year_index]

    def items_by_category(self, category: str, year_index: int) -> list[OpexScheduleEntry]:
        """Get entries for a given category and year. Uses entry.category field."""
        return [e for e in self.entries
                if e.year_index == year_index and e.category == category]

    def total_for_year(self, year_index: int) -> float:
        """Get total OPEX for a given year (0-based index)."""
        if year_index < len(self.total_by_year):
            return self.total_by_year[year_index]
        return 0.0

    def summary_by_category(self, year_index: int) -> dict[str, float]:
        """Get total OPEX per category for a given year. Groups by entry.category."""
        result: dict[str, float] = {}
        for entry in self.items_for_year(year_index):
            result[entry.category] = result.get(entry.category, 0.0) + entry.value_keur
        return result


# =============================================================================
# SCHEDULE GENERATION
# =============================================================================

def generate_opex_schedule(
    line_items: tuple[OpexLineItem, ...],
    horizon_years: int,
) -> OpexSchedule:
    """Generate per-year OPEX schedule from line items.

    Args:
        line_items: Tuple of OpexLineItem objects.
        horizon_years: Number of operating years to schedule (1-based).

    Returns:
        OpexSchedule with per-year entries and totals.

    Behavior:
        - INFLATED_FROM_BASE: value[year] = base * (1 + inflation) ** year
        - MANUAL_SCHEDULE: value[year] = annual_values_keur[year]
        - MIXED: use inflated base, but override specific years from manual_overrides_keur
        - Years not in manual_overrides_keur use the calculated value
        - is_hardcoded items are flagged; all manual/hardcoded values are flagged as overrides
    """
    if not line_items:
        return OpexSchedule()  # Empty schedule — caller should fall back to legacy OPEX

    entries: list[OpexScheduleEntry] = []
    total_by_year: list[float] = [0.0] * horizon_years
    has_manual_overrides = False
    has_hardcoded_items = False

    for item in line_items:
        if item.is_hardcoded:
            has_hardcoded_items = True

        for year_idx in range(horizon_years):
            # Determine base value from calculation mode
            if item.calculation_mode == CalculationMode.INFLATED_FROM_BASE:
                value_keur = item.base_year_amount_keur * ((1 + item.inflation_rate) ** year_idx)
                is_override = False
                note = ""
                source = item.source  # Respect item's source (FORMULA or HARDCODED)

            elif item.calculation_mode == CalculationMode.MANUAL_SCHEDULE:
                if year_idx < len(item.annual_values_keur):
                    value_keur = item.annual_values_keur[year_idx]
                else:
                    value_keur = 0.0
                is_override = True
                note = item.override_note
                source = OpexSource.MANUAL if not item.is_hardcoded else OpexSource.HARDCODED

            else:  # MIXED — inflated base with per-year overrides
                base_value = item.base_year_amount_keur * ((1 + item.inflation_rate) ** year_idx)
                if year_idx < len(item.manual_overrides_keur) and item.manual_overrides_keur[year_idx] is not None:
                    value_keur = item.manual_overrides_keur[year_idx]
                    is_override = True
                    note = item.override_note
                    source = OpexSource.MANUAL if not item.is_hardcoded else OpexSource.HARDCODED
                else:
                    value_keur = base_value
                    is_override = False
                    note = ""
                    source = item.source  # Respect item's source

            # Override with explicit manual override if provided
            if (year_idx < len(item.manual_overrides_keur)
                    and item.manual_overrides_keur[year_idx] is not None
                    and item.calculation_mode == CalculationMode.MIXED):
                value_keur = item.manual_overrides_keur[year_idx]
                is_override = True
                note = item.override_note
                source = OpexSource.MANUAL if not item.is_hardcoded else OpexSource.HARDCODED

            inflation_factor = (1 + item.inflation_rate) ** year_idx

            entries.append(OpexScheduleEntry(
                line_item_name=item.name,
                category=item.category,  # Stored directly from line item
                year_index=year_idx,
                value_keur=value_keur,
                source=source,
                is_override=is_override,
                is_hardcoded=item.is_hardcoded,  # Carried from line item
                override_note=note,
                inflation_factor=inflation_factor,
            ))

            if is_override:
                has_manual_overrides = True

            total_by_year[year_idx] += value_keur

    return OpexSchedule(
        entries=tuple(entries),
        total_by_year=tuple(total_by_year),
        has_manual_overrides=has_manual_overrides,
        has_hardcoded_items=has_hardcoded_items,
    )


def build_opex_line_items_from_defaults(
    technology: str = "solar",
) -> tuple[OpexLineItem, ...]:
    """Build a default set of line items as a starting point for OPEX modeling.

    .. note:: These are **starter defaults**, not an exact reproduction of the
       legacy ``OpexParams`` totals. The legacy ``OpexParams.annual_opex_keur()``
       includes capacity-weighted variable O&M and insurance that depend on
       generation and CAPEX assumptions. The line-item defaults here represent
       a simplified but transparent flat-cost starting point for user editing.
       Total Y1 sums will differ from ``OpexParams`` defaults until the user
       calibrates individual line items.

    Args:
        technology: "solar" or "wind"

    Returns:
        Tuple of OpexLineItem objects representing starter defaults.
    """
    if technology == "solar":
        return (
            OpexLineItem(
                name="Technical Management (B.01)",
                category="operations",
                base_year_amount_keur=198.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Infrastructure Maintenance (B.02)",
                category="infrastructure",
                base_year_amount_keur=244.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Clean Material (B.04)",
                category="clean_material",
                base_year_amount_keur=40.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Power Expenses (B.08)",
                category="power_expenses",
                base_year_amount_keur=177.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Environmental & Social (B.12)",
                category="environmental_social",
                base_year_amount_keur=32.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Insurance",
                category="insurance",
                base_year_amount_keur=280.0,
                inflation_rate=0.015,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Land Lease",
                category="land",
                base_year_amount_keur=150.0,
                inflation_rate=0.0,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
        )
    elif technology == "wind":
        return (
            OpexLineItem(
                name="Technical Management (B.01)",
                category="operations",
                base_year_amount_keur=300.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Infrastructure Maintenance (B.02)",
                category="infrastructure",
                base_year_amount_keur=180.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Power Expenses (B.08)",
                category="power_expenses",
                base_year_amount_keur=200.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Environmental & Social (B.12)",
                category="environmental_social",
                base_year_amount_keur=120.0,
                inflation_rate=0.02,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Insurance",
                category="insurance",
                base_year_amount_keur=380.0,
                inflation_rate=0.015,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
            OpexLineItem(
                name="Land Lease",
                category="land",
                base_year_amount_keur=200.0,
                inflation_rate=0.0,
                calculation_mode=CalculationMode.INFLATED_FROM_BASE,
                source=OpexSource.FORMULA,
            ),
        )
    else:
        return ()


def apply_opex_line_items_to_project(
    line_items: tuple[OpexLineItem, ...],
    horizon_years: int,
) -> tuple[float, ...]:
    """Compute total annual OPEX from line items.

    This is the integration point with the existing model.
    Returns total_by_year tuple. If line_items is empty,
    the caller should fall back to the existing OpexParams path.

    Args:
        line_items: Tuple of OpexLineItem objects.
        horizon_years: Number of operating years.

    Returns:
        Total OPEX per year (0-based index) in kEUR.
    """
    if not line_items:
        return ()
    schedule = generate_opex_schedule(line_items, horizon_years)
    return schedule.total_by_year


__all__ = [
    "CalculationMode",
    "OpexSource",
    "OpexLineItem",
    "OpexScheduleEntry",
    "OpexSchedule",
    "generate_opex_schedule",
    "build_opex_line_items_from_defaults",
    "apply_opex_line_items_to_project",
]
