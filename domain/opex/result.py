"""Offline OPEX result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpexItemAnnualResult:
    year_index: int
    group_code: str
    group_name: str
    item_code: str
    item_name: str
    active: bool
    basis: str
    budget_keur: float
    calculated_keur: float
    manual_override_keur: float | None
    inflation_rate: float
    wth_rate: float
    wth_keur: float
    total_keur: float
    is_manual_override: bool = False


@dataclass(frozen=True)
class OpexGroupAnnualResult:
    year_index: int
    group_code: str
    group_name: str
    item_results: tuple[OpexItemAnnualResult, ...]
    group_total_keur: float
    contingency_from_groups_keur: float = 0.0
    contingency_method: str = "fixed_amount"  # "fixed_amount" | "percentage_of_opex"
    contingency_pct: float = 0.0
    contingency_base_keur: float = 0.0  # sum of non-contingency OPEX used as base

    def item_result(self, item_code: str) -> OpexItemAnnualResult | None:
        for item in self.item_results:
            if item.item_code == item_code:
                return item
        return None


@dataclass(frozen=True)
class OpexAnnualResult:
    years: tuple[int, ...]
    group_results: tuple[OpexGroupAnnualResult, ...]
    total_by_year_keur: tuple[float, ...]
    grand_total_keur: float

    def year_index_to_position(self, year_index: int) -> int:
        return self.years.index(year_index)

    def total_for_year(self, year_index: int) -> float:
        return self.total_by_year_keur[self.year_index_to_position(year_index)]

    def group_result(self, year_index: int, group_code: str) -> OpexGroupAnnualResult | None:
        for group in self.group_results:
            if group.year_index == year_index and group.group_code == group_code:
                return group
        return None

    def item_result(
        self,
        year_index: int,
        group_code: str,
        item_code: str,
    ) -> OpexItemAnnualResult | None:
        group = self.group_result(year_index, group_code)
        return group.item_result(item_code) if group else None


OpexResult = OpexAnnualResult
