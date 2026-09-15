"""PreferredReturnAllocation — multi-investor preferred return result adapter.

Wraps per-investor PreferredReturnResult objects into a single aggregate
adapter compatible with the Phase 7C waterfall allocation interface.

Also exposes LP's cumulative preferred-return distributions by period, needed
to compute the GP catch-up threshold:
    GP_catch_up_target = promote_rate / (1 - promote_rate) × max(0, lp_cumulative_pref - lp_invested_capital)

The adapter implements the same interface as PreferredReturnResult so that
the existing _allocate_preferred_return() function works unchanged:
    - sponsor_code: str  (returns "LP" as the primary LP identifier)
    - entry_for(period_index) -> PreferredReturnAccrualEntry | None
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from finco_core.sponsor.preferred_return_result import (
    PreferredReturnAccrualEntry,
    PreferredReturnResult,
)


@dataclass(frozen=True)
class PreferredReturnAllocationEntry:
    """Aggregate preferred return entry across all investors for one period.

    Used internally by PreferredReturnAllocation to expose per-period data.
    """
    period_index: int
    total_unpaid_pref_keur: float
    lp_cumulative_pref_keur: float
    lp_invested_capital_keur: float

    @property
    def lp_catch_up_trigger_keur(self) -> float:
        """LP cumulative preferred return above invested capital.

        This is the base for the GP catch-up threshold:
            gp_target = (promote_rate / (1 - promote_rate)) × max(0, lp_catch_up_trigger)

        Returns 0 if LP hasn't yet earned preferred return above their capital.
        """
        return max(0.0, self.lp_cumulative_pref_keur - self.lp_invested_capital_keur)


@dataclass(frozen=True)
class PreferredReturnAllocation:
    """Multi-investor preferred return allocation adapter.

    Aggregates per-investor PreferredReturnResult objects into a single
    adapter compatible with _allocate_preferred_return().

    Also provides LP catch-up trigger amounts by period.

    Usage in waterfall cascade:
        allocation = PreferredReturnAllocation(
            per_investor_results={"LP-1": lp_pref_result, "GP-1": gp_pref_result},
            lp_investor_id="LP-1",
            lp_invested_capital_keur=8000.0,
        )
        # allocation.sponsor_code → "LP-1"
        # allocation.entry_for(p) → aggregate PreferredReturnAccrualEntry
        # allocation.lp_cumulative_pref_by_period[p] → LP cumulative PREF for catch-up
    """

    # Per-investor preferred return results (keyed by investor_id)
    per_investor_results: tuple[tuple[str, PreferredReturnResult], ...]
    lp_investor_id: str
    lp_invested_capital_keur: float

    def __post_init__(self):
        if not isinstance(self.per_investor_results, (list, tuple)):
            raise TypeError("per_investor_results must be tuple of (id, result) pairs")
        if not isinstance(self.lp_investor_id, str) or not self.lp_investor_id.strip():
            raise TypeError("lp_investor_id must be non-empty str")
        if self.lp_invested_capital_keur < 0:
            raise ValueError(f"lp_invested_capital_keur must be >= 0, got {self.lp_invested_capital_keur}")
        object.__setattr__(self, "per_investor_results", tuple(self.per_investor_results))

    @property
    def sponsor_code(self) -> str:
        """Returns the LP investor_id — used by _allocate_preferred_return."""
        return self.lp_investor_id

    def lp_cumulative_pref_by_period(self) -> tuple[float, ...]:
        """LP's cumulative preferred return distributions by period.

        Used by GP catch-up threshold calculation.
        """
        if not self.per_investor_results:
            return tuple()
        # Find LP's result
        lp_result: Optional[PreferredReturnResult] = None
        for inv_id, result in self.per_investor_results:
            if inv_id == self.lp_investor_id:
                lp_result = result
                break
        if lp_result is None:
            return tuple(0.0 for _ in range(len(lp_result.entries) if lp_result else 0))
        return tuple(
            entry.cumulative_distributions_keur
            for entry in lp_result.entries
        )

    def lp_catch_up_trigger_by_period(self) -> tuple[float, ...]:
        """LP catch-up trigger (cumulative PREF minus invested capital) by period.

        Each period's value = max(0, lp_cumulative_pref_keur - lp_invested_capital_keur).
        This is the base for GP catch-up threshold.
        """
        cumulative = self.lp_cumulative_pref_by_period()
        return tuple(max(0.0, c - self.lp_invested_capital_keur) for c in cumulative)

    def entry_for(self, period_index: int) -> Optional[PreferredReturnAccrualEntry]:
        """Return the LP's preferred return entry for the given period.

        Used for the GP catch-up threshold computation.
        """
        if not self.per_investor_results:
            return None
        for inv_id, result in self.per_investor_results:
            if inv_id == self.lp_investor_id:
                entry = result.entry_for(period_index)
                if entry is not None:
                    return entry
        return None

    def lp_catch_up_trigger_at_period(self, period_index: int) -> float:
        """Return LP catch-up trigger for a specific period."""
        triggers = self.lp_catch_up_trigger_by_period()
        if period_index < len(triggers):
            return triggers[period_index]
        return 0.0
