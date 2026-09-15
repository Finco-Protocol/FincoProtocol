"""Phase 5A cash ledger result structures."""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.portfolio.cash_ledger.inputs import CashMovement


@dataclass(frozen=True)
class CashLedgerPeriod:
    """Single period for an entity cash ledger."""
    period: int
    entity_code: str
    opening_cash_keur: float = 0.0
    movements: tuple[CashMovement, ...] = ()
    closing_cash_keur: float = 0.0
    retained_cash_keur: float = 0.0
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        if self.period < 0:
            raise ValueError(f"period must be >= 0, got {self.period}")
        # closing_cash = opening + sum(movements)
        movement_sum = sum(m.amount_keur for m in self.movements)
        if abs(self.closing_cash_keur - (self.opening_cash_keur + movement_sum)) > 1e-6:
            raise ValueError(
                f"closing_cash_keur ({self.closing_cash_keur}) must equal "
                f"opening_cash_keur ({self.opening_cash_keur}) + movement_sum ({movement_sum})"
            )


@dataclass(frozen=True)
class EntityCashLedger:
    """Cash ledger for a single entity across all periods."""
    entity_code: str
    periods: tuple[CashLedgerPeriod, ...]
    total_movements_keur: float
    ending_cash_keur: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioCashLedger:
    """Portfolio-level cash ledger aggregating all entities."""
    entities: tuple[EntityCashLedger, ...] = ()
    total_ending_cash_keur: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)
