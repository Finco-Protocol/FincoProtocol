"""Phase 4A SHL inputs — facility definition and portfolio-level config.

No sculpting. No capitalization. No circular funding detection.
Immutable dataclasses with validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SHLFacility:
    """Single SHL (Subordinated HoldCo Loan) facility definition.

    Immutable. Represents an intercompany loan from lender to borrower.
    The loan is subordinated to senior debt in the waterfall.
    """
    lender_entity_code: str           # entity providing the loan
    borrower_entity_code: str         # entity receiving the loan
    principal_keur: float              # principal amount in kEUR
    interest_rate_pa: float            # annual interest rate (e.g. 0.08 = 8%)
    tenor_years: int                  # loan tenor in years
    sculpted: bool = False            # sculpted (cash flow matching) vs fixed schedule
    capitalization_allowed: bool = False  # accrued interest added to principal
    payment_frequency_per_year: int = 2   # number of payment periods per year (1=annual, 2=semi, 4=quarterly, 12=monthly)
    start_period_index: int = 0       # first period index for payment (0-based)

    def __post_init__(self):
        if not self.lender_entity_code or not self.lender_entity_code.strip():
            raise ValueError("lender_entity_code is required")
        if not self.borrower_entity_code or not self.borrower_entity_code.strip():
            raise ValueError("borrower_entity_code is required")
        if self.principal_keur < 0:
            raise ValueError(f"principal_keur must be >= 0, got {self.principal_keur}")
        if self.interest_rate_pa < 0:
            raise ValueError(f"interest_rate_pa must be >= 0, got {self.interest_rate_pa}")
        if self.tenor_years <= 0:
            raise ValueError(f"tenor_years must be > 0, got {self.tenor_years}")
        if self.payment_frequency_per_year not in {1, 2, 4, 12}:
            raise ValueError(
                f"payment_frequency_per_year must be in {{1, 2, 4, 12}}, "
                f"got {self.payment_frequency_per_year}"
            )
        if self.start_period_index < 0:
            raise ValueError(f"start_period_index must be >= 0, got {self.start_period_index}")


@dataclass(frozen=True)
class SHLPortfolioInputs:
    """Portfolio-level SHL configuration — collection of facilities."""
    facilities: tuple[SHLFacility, ...] = ()  # empty tuple allowed

    def __post_init__(self):
        # Check for duplicate lender/borrower pairs (exact same pair)
        seen: set[tuple[str, str]] = set()
        for f in self.facilities:
            pair = (f.lender_entity_code, f.borrower_entity_code)
            if pair in seen:
                raise ValueError(
                    f"Duplicate SHL facility: lender={f.lender_entity_code} "
                    f"borrower={f.borrower_entity_code}"
                )
            seen.add(pair)