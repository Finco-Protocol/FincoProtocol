"""Phase 5A cash ledger inputs — movement types and cash movement records."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CashMovementType(str, Enum):
    """Enumeration of cash movement types for ledger tracking."""
    OPENING_CASH = "OPENING_CASH"
    OPERATING_CASHFLOW = "OPERATING_CASHFLOW"
    SENIOR_DEBT_SERVICE = "SENIOR_DEBT_SERVICE"
    TAX = "TAX"
    DSRF_DRAW = "DSRF_DRAW"
    DSRF_REPAYMENT = "DSRF_REPAYMENT"
    DSRF_INTEREST = "DSRF_INTEREST"
    DSRF_COMMITMENT_FEE = "DSRF_COMMITMENT_FEE"
    SHL_INTEREST = "SHL_INTEREST"
    SHL_PRINCIPAL = "SHL_PRINCIPAL"
    EQUITY_DISTRIBUTION = "EQUITY_DISTRIBUTION"
    HOLDCO_OPEX = "HOLDCO_OPEX"
    HOLDCO_TAX = "HOLDCO_TAX"
    SPONSOR_DISTRIBUTION = "SPONSOR_DISTRIBUTION"
    RETAINED_CASH = "RETAINED_CASH"
    OTHER = "OTHER"


@dataclass(frozen=True)
class CashMovement:
    """Single cash movement entry in the ledger."""
    period: int
    entity_code: str
    movement_type: CashMovementType
    amount_keur: float
    description: str = ""

    def __post_init__(self):
        if self.period < 0:
            raise ValueError(f"period must be >= 0, got {self.period}")
        if not self.entity_code or not self.entity_code.strip():
            raise ValueError("entity_code is required")
        if not isinstance(self.movement_type, CashMovementType):
            raise ValueError(
                f"movement_type must be a CashMovementType, got {type(self.movement_type).__name__}"
            )
