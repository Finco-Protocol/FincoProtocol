"""Offline construction schedule configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class CapexProfileType(Enum):
    """Supported construction uses profile types."""

    LINEAR = "linear"
    CUSTOM = "custom"


@dataclass(frozen=True)
class FundingSourceCaps:
    """Maximum construction funding available from each source."""

    equity_shares_keur: float
    shl_keur: float
    junior_keur: float
    senior_debt_keur: float

    @property
    def total_keur(self) -> float:
        return (
            self.equity_shares_keur
            + self.shl_keur
            + self.junior_keur
            + self.senior_debt_keur
        )


@dataclass(frozen=True)
class ConstructionConfig:
    """Offline inputs for construction funding and IDC bridge calculations."""

    project_code: str
    construction_start_date: date
    cod_date: date
    construction_months: int
    total_uses_keur: float
    profile_type: CapexProfileType = CapexProfileType.CUSTOM
    monthly_uses_keur: tuple[float, ...] = field(default_factory=tuple)
    funding_caps: FundingSourceCaps = field(
        default_factory=lambda: FundingSourceCaps(0.0, 0.0, 0.0, 0.0)
    )
    shl_interest_rate: float = 0.0
    shl_investment_date: date | None = None
    shl_day_count_denominator: float = 365.0
    senior_interest_rate: float = 0.0
    senior_base_rates: tuple[float, ...] = field(default_factory=tuple)
    senior_interest_period_fractions: tuple[float, ...] = field(default_factory=tuple)
    senior_idc_target_keur: float | None = None
    senior_idc_notes: str = ""
    senior_idc_capitalized: bool = False
    shl_idc_capitalized: bool = True


__all__ = ["CapexProfileType", "ConstructionConfig", "FundingSourceCaps"]
