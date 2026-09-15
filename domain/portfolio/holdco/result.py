"""Phase 3A/3B HoldCo domain skeleton — result structures and aggregation runner.

No cash flow calculations. No SHL. No tax template.
Pure dataclass layer representing HoldCo-level output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HoldCoSPVContribution:
    """Per-period contribution from a single SPV to HoldCo.

    Phase 3A/3B: holdco_share_keur computed by Phase 3B aggregation runner.
    dividend_keur, shl_interest_keur, shl_principal_keur are SHL-ready fields
    (all 0.0 until SHL is implemented).
    """
    period: int
    spv_code: str
    ownership_pct: float  # 0.0–1.0
    spv_distribution_keur: float = 0.0  # raw SPV distribution from waterfall
    holdco_share_keur: float = 0.0  # ownership_pct * spv_distribution_keur
    currency: str = "EUR"
    # SHL-ready fields (schema prep only — no SHL logic implemented)
    dividend_keur: float = 0.0      # dividend component of distribution
    shl_interest_keur: float = 0.0  # SHL interest income (0.0 until SHL)
    shl_principal_keur: float = 0.0  # SHL principal repayment (0.0 until SHL)

    def __post_init__(self):
        if self.period < 0:
            raise ValueError(f"period must be >= 0, got {self.period}")
        if not (0.0 <= self.ownership_pct <= 1.0):
            raise ValueError(f"ownership_pct must be in [0.0, 1.0], got {self.ownership_pct}")
        if self.spv_distribution_keur < 0:
            raise ValueError(f"spv_distribution_keur must be >= 0, got {self.spv_distribution_keur}")


@dataclass
class HoldCoPeriodResult:
    """Per-period HoldCo aggregation result.

    Phase 3A/3B: populated by Phase 3B aggregation runner.
    opex, tax, and net-to-sponsor values are computed per period.

    Fields:
    - period: period index
    - contributions: list of SPV contributions this period
    - gross_income_keur: sum of holdco_share_keur across all SPVs
    - holdco_opex_keur: annual OpEx deducted (per period, split from annual)
    - taxable_income_keur: gross - opex if positive else 0
    - tax_keur: taxable_income * tax_rate_pa
    - distribution_to_sponsor_keur: net after opex and tax
    - holdco_irr: always None (HoldCo IRR deferred beyond Phase 3B)
    """
    period: int
    contributions: list[HoldCoSPVContribution] = field(default_factory=list)
    gross_income_keur: float = 0.0
    holdco_opex_keur: float = 0.0
    taxable_income_keur: float = 0.0
    tax_keur: float = 0.0
    distribution_to_sponsor_keur: float = 0.0
    holdco_irr: Optional[float] = None  # HoldCo IRR deferred beyond Phase 3B
    currency: str = "EUR"
    # SHL-ready fields (schema prep only — no SHL logic implemented)
    dividend_keur: float = 0.0        # sum of dividend components this period
    shl_interest_keur: float = 0.0   # sum of SHL interest this period
    shl_principal_keur: float = 0.0   # sum of SHL principal this period

    def __post_init__(self):
        if self.period < 0:
            raise ValueError(f"period must be >= 0, got {self.period}")
        if self.gross_income_keur < 0:
            raise ValueError(f"gross_income_keur must be >= 0, got {self.gross_income_keur}")
        if self.holdco_opex_keur < 0:
            raise ValueError(f"holdco_opex_keur must be >= 0, got {self.holdco_opex_keur}")
        if self.tax_keur < 0:
            raise ValueError(f"tax_keur must be >= 0, got {self.tax_keur}")
        if self.distribution_to_sponsor_keur < 0:
            raise ValueError(f"distribution_to_sponsor_keur must be >= 0, got {self.distribution_to_sponsor_keur}")


@dataclass
class HoldCoResult:
    """Top-level HoldCo computation result.

    Phase 3A/3B: populated by Phase 3B aggregation runner.
    Actual aggregation (SPV distribution → HoldCo share → sponsor net)
    is computed by the Phase 3B aggregation runner (domain/portfolio/holdco/runner.py).

    Fields:
    - name: HoldCo entity name
    - periods: per-period breakdown
    - total_spv_distributions_keur: sum across all SPVs and periods
    - total_gross_income_keur: sum of gross income
    - total_opex_keur: sum of HoldCo OpEx (all periods)
    - total_tax_keur: sum of HoldCo tax
    - total_distribution_to_sponsor_keur: sum to sponsor
    - holdco_irr: always None (HoldCo IRR deferred beyond Phase 3B)
    - spv_codes: list of SPV codes included
    """
    name: str
    periods: list[HoldCoPeriodResult] = field(default_factory=list)
    total_spv_distributions_keur: float = 0.0
    total_gross_income_keur: float = 0.0
    total_opex_keur: float = 0.0
    total_tax_keur: float = 0.0
    total_distribution_to_sponsor_keur: float = 0.0
    holdco_irr: Optional[float] = None  # HoldCo IRR deferred beyond Phase 3B
    spv_codes: list[str] = field(default_factory=list)
    currency: str = "EUR"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    # SHL-ready totals (schema prep only — no SHL logic implemented)
    total_dividend_keur: float = 0.0
    total_shl_interest_keur: float = 0.0
    total_shl_principal_keur: float = 0.0

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("HoldCoResult.name is required")
        if self.total_spv_distributions_keur < 0:
            raise ValueError(f"total_spv_distributions_keur must be >= 0, got {self.total_spv_distributions_keur}")
        if self.total_gross_income_keur < 0:
            raise ValueError(f"total_gross_income_keur must be >= 0, got {self.total_gross_income_keur}")
        if self.total_opex_keur < 0:
            raise ValueError(f"total_opex_keur must be >= 0, got {self.total_opex_keur}")
        if self.total_tax_keur < 0:
            raise ValueError(f"total_tax_keur must be >= 0, got {self.total_tax_keur}")
        if self.total_distribution_to_sponsor_keur < 0:
            raise ValueError(f"total_distribution_to_sponsor_keur must be >= 0, got {self.total_distribution_to_sponsor_keur}")

    @property
    def is_placeholder(self) -> bool:
        """True when no aggregation was performed (empty result).
        
        False when produced by build_holdco_result with at least one period.
        """
        return not self.periods

    @property
    def spv_count(self) -> int:
        return len(self.spv_codes)