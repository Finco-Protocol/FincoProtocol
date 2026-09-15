"""Phase 4A SHL result structures — period, facility, and portfolio results.

No sculpting. No capitalization. No tax logic.
Immutable dataclasses with validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from domain.portfolio.shl.inputs import SHLFacility


@dataclass(frozen=True)
class SHLPeriodResult:
    """Single period result for an SHL facility.

    Tracks opening balance, interest accrual/payment, principal payment,
    and closing balance.
    """
    period_index: int
    opening_balance_keur: float
    interest_accrued_keur: float
    interest_paid_keur: float
    principal_paid_keur: float
    closing_balance_keur: float

    def __post_init__(self):
        if self.period_index < 0:
            raise ValueError(f"period_index must be >= 0, got {self.period_index}")
        if self.opening_balance_keur < 0:
            raise ValueError(f"opening_balance_keur must be >= 0, got {self.opening_balance_keur}")
        if self.closing_balance_keur < 0:
            raise ValueError(f"closing_balance_keur must be >= 0, got {self.closing_balance_keur}")


@dataclass(frozen=True)
class SHLFacilityResult:
    """Full result for a single SHL facility — all periods + totals."""
    facility: SHLFacility
    periods: tuple[SHLPeriodResult, ...]
    total_interest_paid_keur: float
    total_principal_paid_keur: float

    def __post_init__(self):
        if self.total_interest_paid_keur < 0:
            raise ValueError(f"total_interest_paid_keur must be >= 0, got {self.total_interest_paid_keur}")
        if self.total_principal_paid_keur < 0:
            raise ValueError(f"total_principal_paid_keur must be >= 0, got {self.total_principal_paid_keur}")


@dataclass(frozen=True)
class SHLPortfolioResult:
    """Portfolio-level SHL aggregation result."""
    facilities: tuple[SHLFacilityResult, ...] = ()
    total_interest_paid_keur: float = 0.0
    total_principal_paid_keur: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.total_interest_paid_keur < 0:
            raise ValueError(f"total_interest_paid_keur must be >= 0, got {self.total_interest_paid_keur}")
        if self.total_principal_paid_keur < 0:
            raise ValueError(f"total_principal_paid_keur must be >= 0, got {self.total_principal_paid_keur}")