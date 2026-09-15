"""Phase 7C-3 — Waterfall allocation result schemas.

Immutable, frozen result schemas for the waterfall allocation engine.
Schema-only: no allocation logic, no mutation of inputs.

Design goals:
- Deterministic, audit-safe, frozen dataclasses
- Immutable per-period and per-tier allocation snapshots
- Future multi-investor compatibility
- Serialization-friendly (all JSON-serializable scalars)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from finco_core.sponsor.sponsor_waterfall_tier import (
    TierType,
    SponsorShare,
)

__all__ = [
    "TierAllocationEntry",
    "PeriodWaterfallResult",
    "WaterfallAllocationResult",
]


# ── Validation helpers ─────────────────────────────────────────────────────────

def _finite(value: float, name: str) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be float, got {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _non_negative(value: float, name: str) -> None:
    _finite(value, name)
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0, got {value}")


# ── TierAllocationEntry ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierAllocationEntry:
    """Immutable allocation result for a single tier in a single period.

    Attributes
    ----------
    tier_index : int
        Tier index matching SponsorWaterfallTier.tier_index.
    tier_type : TierType
        Type of this tier.
    available_cash_before_tier_keur : float
        Cash available at the START of this tier's allocation (kEUR).
        Must be >= 0.
    allocated_amount_keur : float
        Total amount allocated to this tier (kEUR). Must be >= 0.
    allocated_per_sponsor_keur : tuple[tuple[str, float], ...]
        Ordered tuple of (sponsor_code, amount) pairs for this tier.
    remaining_cash_after_tier_keur : float
        Cash remaining after this tier's allocation (kEUR).
        Must be >= 0.
    audit_note : str
        Fixed audit note.
    """
    tier_index: int
    tier_type: TierType
    available_cash_before_tier_keur: float
    allocated_amount_keur: float
    allocated_per_sponsor_keur: tuple[tuple[str, float], ...]
    remaining_cash_after_tier_keur: float
    audit_note: str = (
        "AUDIT-ONLY: waterfall tier allocation entry — read-only accrual artifact, "
        "not a distribution commitment"
    )

    def __post_init__(self):
        _non_negative(self.available_cash_before_tier_keur, "available_cash_before_tier_keur")
        _non_negative(self.allocated_amount_keur, "allocated_amount_keur")
        _non_negative(self.remaining_cash_after_tier_keur, "remaining_cash_after_tier_keur")
        if not isinstance(self.tier_index, int):
            raise TypeError("tier_index must be int")
        if not isinstance(self.tier_type, TierType):
            raise TypeError("tier_type must be TierType")
        if not isinstance(self.allocated_per_sponsor_keur, tuple):
            raise TypeError("allocated_per_sponsor_keur must be tuple")
        # Sum of per-sponsor allocations must equal total allocated
        total_per_sponsor = sum(a for _, a in self.allocated_per_sponsor_keur)
        if abs(total_per_sponsor - self.allocated_amount_keur) > 1e-6:
            raise ValueError(
                f"per-sponsor sum ({total_per_sponsor:.4f}) must equal "
                f"allocated_amount_keur ({self.allocated_amount_keur:.4f})"
            )

    @property
    def sponsor_codes(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.allocated_per_sponsor_keur)

    def allocation_for(self, sponsor_code: str) -> float:
        """Return allocation amount for a given sponsor_code. 0.0 if not in this tier."""
        for code, amount in self.allocated_per_sponsor_keur:
            if code == sponsor_code:
                return amount
        return 0.0


# ── PeriodWaterfallResult ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PeriodWaterfallResult:
    """Immutable per-period waterfall allocation snapshot.

    Attributes
    ----------
    period_index : int
        Semiannual period index (0-based).
    available_cash_keur : float
        Total cash available for allocation this period (kEUR). Must be >= 0.
    tier_entries : tuple[TierAllocationEntry, ...]
        Ordered tuple of tier allocation entries for this period.
        Sorted by tier_index.
    total_allocated_keur : float
        Sum of all tier allocations in this period. Must be >= 0.
    total_remaining_cash_keur : float
        Cash remaining after all tiers processed.
    cumulative_distributions_by_sponsor_keur : tuple[tuple[str, float], ...]
        Cumulative total distributions paid to each sponsor across all periods
        up to and including this period.
    audit_note : str
        Fixed audit note.
    """
    period_index: int
    available_cash_keur: float
    tier_entries: tuple[TierAllocationEntry, ...]
    total_allocated_keur: float
    total_remaining_cash_keur: float
    cumulative_distributions_by_sponsor_keur: tuple[tuple[str, float], ...]
    audit_note: str = "AUDIT-ONLY: period waterfall result — read-only allocation snapshot"

    def __post_init__(self):
        if not isinstance(self.period_index, int):
            raise TypeError("period_index must be int")
        if self.period_index < 0:
            raise ValueError(f"period_index must be >= 0, got {self.period_index}")
        _non_negative(self.available_cash_keur, "available_cash_keur")
        _non_negative(self.total_allocated_keur, "total_allocated_keur")
        _non_negative(self.total_remaining_cash_keur, "total_remaining_cash_keur")
        if not isinstance(self.tier_entries, tuple):
            raise TypeError("tier_entries must be tuple")
        # Verify cash conservation: available = total_allocated + total_remaining ± tolerance
        eps = 1e-6
        if abs(self.available_cash_keur - self.total_allocated_keur - self.total_remaining_cash_keur) > eps:
            raise ValueError(
                f"cash conservation violated: available={self.available_cash_keur}, "
                f"allocated={self.total_allocated_keur}, remaining={self.total_remaining_cash_keur}"
            )
        # Reconcile tier_entries total with total_allocated
        tier_total = sum(e.allocated_amount_keur for e in self.tier_entries)
        if abs(tier_total - self.total_allocated_keur) > eps:
            raise ValueError(
                f"tier_entries sum ({tier_total:.4f}) must equal "
                f"total_allocated_keur ({self.total_allocated_keur:.4f})"
            )
        # Validate cumulative_distributions
        if not isinstance(self.cumulative_distributions_by_sponsor_keur, tuple):
            raise TypeError("cumulative_distributions_by_sponsor_keur must be tuple")

    def tier_for(self, tier_index: int) -> TierAllocationEntry | None:
        for e in self.tier_entries:
            if e.tier_index == tier_index:
                return e
        return None

    def tier_for_type(self, tier_type: TierType) -> TierAllocationEntry | None:
        for e in self.tier_entries:
            if e.tier_type == tier_type:
                return e
        return None


# ── WaterfallAllocationResult ─────────────────────────────────────────────────

@dataclass(frozen=True)
class WaterfallAllocationResult:
    """Immutable full waterfall allocation result across all periods.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier.
    period_results : tuple[PeriodWaterfallResult, ...]
        Per-period waterfall allocation snapshots.
    total_allocated_keur : float
        Total cash allocated across all periods.
    total_distributions_by_sponsor_keur : tuple[tuple[str, float], ...]
        Final cumulative distributions by sponsor (after all periods).
    audit_note : str
        Fixed audit note.
    notes : tuple[str, ...]
        Human-readable notes.
    """
    investor_id: str
    period_results: tuple[PeriodWaterfallResult, ...]
    total_allocated_keur: float
    total_distributions_by_sponsor_keur: tuple[tuple[str, float], ...]
    audit_note: str = "AUDIT-ONLY: waterfall allocation result — read-only allocation artifact"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.investor_id, str) or not self.investor_id.strip():
            raise ValueError("investor_id must be non-empty string")
        if not isinstance(self.period_results, (list, tuple)):
            raise TypeError("period_results must be tuple")
        object.__setattr__(self, "period_results", tuple(self.period_results))
        _finite(self.total_allocated_keur, "total_allocated_keur")
        if not isinstance(self.total_distributions_by_sponsor_keur, tuple):
            raise TypeError("total_distributions_by_sponsor_keur must be tuple")
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))

    @property
    def num_periods(self) -> int:
        return len(self.period_results)

    @property
    def period_count(self) -> int:
        return len(self.period_results)
