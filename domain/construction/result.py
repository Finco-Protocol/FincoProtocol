"""Offline construction schedule result objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConstructionMonthlyEntry:
    """Single monthly construction funding row."""

    month_index: int
    monthly_uses_keur: float
    cumulative_uses_keur: float
    equity_draw_keur: float
    shl_draw_keur: float
    junior_draw_keur: float
    senior_draw_keur: float
    cumulative_equity_keur: float
    cumulative_shl_keur: float
    cumulative_junior_keur: float
    cumulative_senior_keur: float
    senior_idc_keur: float = 0.0
    cumulative_senior_idc_keur: float = 0.0


@dataclass(frozen=True)
class ConstructionScheduleResult:
    """Offline construction funding bridge result."""

    project_code: str
    monthly_entries: tuple[ConstructionMonthlyEntry, ...]
    total_uses_keur: float
    total_equity_draw_keur: float
    total_shl_draw_keur: float
    total_junior_draw_keur: float
    total_senior_draw_keur: float
    total_shl_idc_keur: float
    total_senior_idc_keur: float
    opening_shl_balance_keur: float
    opening_senior_balance_keur: float
    uses_funding_delta_keur: float
    senior_idc_delta_to_target_keur: float | None = None

    def monthly_entry(self, month_index: int) -> ConstructionMonthlyEntry:
        for entry in self.monthly_entries:
            if entry.month_index == month_index:
                return entry
        raise KeyError(f"No construction month {month_index}")


__all__ = ["ConstructionMonthlyEntry", "ConstructionScheduleResult"]
