"""Phase 7C-2 — Preferred return result schemas.

Immutable, frozen result schemas for preferred return accrual calculation.
Schema-only: no allocation logic, no waterfall state mutation.

Audit note: all result objects are read-only accrual snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

__all__ = [
    "PreferredReturnAccrualEntry",
    "PreferredReturnResult",
]


# ── Per-period accrual entry ──────────────────────────────────────────────────

@dataclass(frozen=True)
class PreferredReturnAccrualEntry:
    """Immutable per-period preferred return accrual snapshot.

    Attributes
    ----------
    period_index : int
        Semiannual period index (0-based).
    opening_invested_capital_keur : float
        Opening invested capital balance at start of period (max(0, running_balance)).
        Used as the accrual base for this period.
    invested_capital_delta_keur : float
        Net capital injected during this period (>= 0).
    hurdle_rate_pa : float
        Annual hurdle rate applied (decimal, e.g. 0.08 for 8%).
    compounding_convention : str
        Compounding convention applied: "ANNUAL", "SIMPLE", or "SEMIANNUAL".
    accrual_periods : float
        Year-fraction for this period (0.5 for semiannual, 1.0 for annual).
    accrued_pref_keur : float
        Preferred return accrued this period.
    cumulative_accrued_pref_keur : float
        Cumulative total preferred return accrued through this period.
    cumulative_distributions_keur : float
        Cumulative total distributions applied to preferred return balance.
    unpaid_pref_balance_keur : float
        Outstanding preferred return balance = cumulative_accrued - cumulative_distributions.
        Always >= 0 in valid runs.
    hurdle_satisfied : bool
        True once cumulative_accrued_pref >= cumulative_invested_capital * hurdle_rate.
        Once True, stays True for remaining periods.
    audit_note : str
        Fixed audit note confirming read-only accrual artifact.
    """
    period_index: int
    opening_invested_capital_keur: float
    invested_capital_delta_keur: float
    hurdle_rate_pa: float
    compounding_convention: str
    accrual_periods: float
    accrued_pref_keur: float
    cumulative_accrued_pref_keur: float
    cumulative_distributions_keur: float
    unpaid_pref_balance_keur: float
    hurdle_satisfied: bool
    audit_note: str = "AUDIT-ONLY: preferred return accrual snapshot — read-only, not a distribution commitment"

    def __post_init__(self):
        if not isinstance(self.period_index, int):
            raise TypeError("period_index must be int")
        if self.period_index < 0:
            raise ValueError(f"period_index must be >= 0, got {self.period_index}")
        # Validate all float fields are finite
        for fname in [
            "opening_invested_capital_keur",
            "invested_capital_delta_keur",
            "hurdle_rate_pa",
            "accrual_periods",
            "accrued_pref_keur",
            "cumulative_accrued_pref_keur",
            "cumulative_distributions_keur",
            "unpaid_pref_balance_keur",
        ]:
            val = getattr(self, fname)
            if not isinstance(val, (int, float)):
                raise TypeError(f"{fname} must be float, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{fname} must be finite, got {val}")


# ── Full preferred return result ──────────────────────────────────────────────

@dataclass(frozen=True)
class PreferredReturnResult:
    """Immutable full preferred return accrual result for a sponsor.

    Attributes
    ----------
    sponsor_code : str
        Investor identifier from SponsorWaterfallTier.
    hurdle_rate_pa : float
        Annual hurdle rate (decimal, e.g. 0.08 for 8%).
    compounding_convention : str
        Compounding convention: "ANNUAL", "SIMPLE", or "SEMIANNUAL".
    entries : tuple[PreferredReturnAccrualEntry, ...]
        Ordered immutable tuple of per-period accrual entries.
        Sorted by period_index.
    total_accrued_pref_keur : float
        Total preferred return accrued across all periods.
    total_unpaid_pref_keur : float
        Final unpaid preferred return balance.
    all_periods_hurdle_satisfied : bool
        True if hurdle was satisfied in the final period.
    audit_note : str
        Fixed audit note.
    """
    sponsor_code: str
    hurdle_rate_pa: float
    compounding_convention: str
    entries: tuple[PreferredReturnAccrualEntry, ...]
    total_accrued_pref_keur: float = field()
    total_unpaid_pref_keur: float = field()
    all_periods_hurdle_satisfied: bool = field()
    audit_note: str = "AUDIT-ONLY: preferred return result — read-only accrual artifact"

    def __post_init__(self):
        # Validate entries is a non-empty tuple
        if not isinstance(self.entries, (list, tuple)):
            raise TypeError(f"entries must be tuple, got {type(self.entries).__name__}")
        entries = tuple(self.entries)
        object.__setattr__(self, "entries", entries)
        if len(entries) == 0:
            raise ValueError("entries cannot be empty")
        # Validate sponsor_code
        if not isinstance(self.sponsor_code, str) or not self.sponsor_code.strip():
            raise ValueError(f"sponsor_code must be non-empty string, got {self.sponsor_code!r}")
        # Validate float scalars
        for fname in ["hurdle_rate_pa", "total_accrued_pref_keur", "total_unpaid_pref_keur"]:
            val = getattr(self, fname)
            if not isinstance(val, (int, float)):
                raise TypeError(f"{fname} must be float, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{fname} must be finite, got {val}")
        # Validate bool
        if not isinstance(self.all_periods_hurdle_satisfied, bool):
            raise TypeError(f"all_periods_hurdle_satisfied must be bool")

    @property
    def num_periods(self) -> int:
        return len(self.entries)

    def entry_for(self, period_index: int) -> PreferredReturnAccrualEntry | None:
        """Return the entry for a given period_index, or None if not found."""
        for e in self.entries:
            if e.period_index == period_index:
                return e
        return None
