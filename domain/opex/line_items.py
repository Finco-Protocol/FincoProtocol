"""Offline OPEX line-item schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OpexBasis(Enum):
    """How an OPEX item budget is interpreted."""

    FIXED_ANNUAL_KEUR = "fixed_annual_keur"
    FIXED_PERIOD_KEUR = "fixed_period_keur"
    EUR_PER_MW_YEAR = "eur_per_mw_year"
    EUR_PER_MWH = "eur_per_mwh"
    PCT_OF_REVENUE = "pct_of_revenue"
    PCT_OF_GROUP = "pct_of_group"
    PCT_OF_SELECTED_GROUPS = "pct_of_selected_groups"
    EXPLICIT_SCHEDULE = "explicit_schedule"
    INACTIVE = "inactive"


class OpexContingencyMethod(Enum):
    """How OPEX contingency is calculated.

    FIXED_AMOUNT:
        Contingency is a fixed kEUR amount (budget_keur) that escalates
        by the group's inflation_rate each year.

    PERCENTAGE_OF_OPEX:
        Contingency = contingency_pct × sum(non-contingency OPEX).
        No separate inflation is applied to the contingency itself;
        inflation is already embedded in the underlying OPEX lines.
    """

    FIXED_AMOUNT = "fixed_amount"
    PERCENTAGE_OF_OPEX = "percentage_of_opex"


@dataclass(frozen=True)
class OpexItemStep:
    """Step change that resets an item's pre-inflation base from a year."""

    year_index: int
    new_budget_keur: float
    description: str = ""


@dataclass(frozen=True)
class ManualOverride:
    """Year-level final-value override; values are used as-is."""

    year_index: int
    value_keur: float
    source: str = "manual"


@dataclass(frozen=True)
class OpexItem:
    """Single offline OPEX line item."""

    code: str
    name: str
    budget_keur: float = 0.0
    basis: OpexBasis = OpexBasis.FIXED_ANNUAL_KEUR
    group_code: str = ""
    inflation_rate: float | None = None
    wth_rate: float | None = None
    active_flags: tuple[bool, ...] = field(default_factory=tuple)
    explicit_schedule_keur: tuple[float, ...] = field(default_factory=tuple)
    manual_overrides: tuple[ManualOverride, ...] = field(default_factory=tuple)
    step_changes: tuple[OpexItemStep, ...] = field(default_factory=tuple)
    selected_group_codes: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    inflation_start_exponent: int = 0

    def is_active(self, year_index: int) -> bool:
        idx = year_index - 1
        if self.basis == OpexBasis.INACTIVE:
            return False
        if self.active_flags and idx < len(self.active_flags):
            return bool(self.active_flags[idx])
        return True

    def override_for(self, year_index: int) -> ManualOverride | None:
        for override in self.manual_overrides:
            if override.year_index == year_index:
                return override
        return None

    def step_at_or_before(self, year_index: int) -> OpexItemStep | None:
        steps = [step for step in self.step_changes if step.year_index <= year_index]
        if not steps:
            return None
        return max(steps, key=lambda step: step.year_index)

    def effective_budget(self, year_index: int) -> float:
        step = self.step_at_or_before(year_index)
        return step.new_budget_keur if step else self.budget_keur


@dataclass(frozen=True)
class OpexGroup:
    """A named OPEX group containing line items."""

    code: str
    name: str
    inflation_rate: float = 0.0
    wth_rate: float = 0.0
    items: tuple[OpexItem, ...] = field(default_factory=tuple)
    order: int = 0
    editable: bool = True
    contingency_pct: float = 0.0
    contingency_method: OpexContingencyMethod = OpexContingencyMethod.FIXED_AMOUNT

    def item_by_code(self, code: str) -> OpexItem | None:
        for item in self.items:
            if item.code == code:
                return item
        return None

    def is_contingency_group(self) -> bool:
        """True when this group contains only contingency items."""
        return self.contingency_pct > 0.0 or any(
            item.basis == OpexBasis.PCT_OF_SELECTED_GROUPS for item in self.items
        )
