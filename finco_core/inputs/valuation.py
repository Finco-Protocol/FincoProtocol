"""Typed downstream valuation and lender-coverage input authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class DiscountConvention(str, Enum):
    """Supported canonical dated discount convention."""

    ACT_365_FIXED = "ACT_365_FIXED"
    PERIODIC_COMPOUNDING = "PERIODIC_COMPOUNDING"


class PeriodicRateConversion(str, Enum):
    """How a quoted coverage rate becomes the per-period NPV rate."""

    AS_QUOTED_PER_MODEL_PERIOD = "AS_QUOTED_PER_MODEL_PERIOD"


class PeriodicFirstCashflowTiming(str, Enum):
    """Timing of the first included cash flow in a periodic PV vector."""

    END_OF_FIRST_PERIOD = "END_OF_FIRST_PERIOD"


class ValuationDatePolicy(str, Enum):
    """Authority for the date from which Project cash flows are discounted."""

    EXPLICIT_DATE = "EXPLICIT_DATE"
    FIRST_PROJECT_CASHFLOW_DATE = "FIRST_PROJECT_CASHFLOW_DATE"


class CoverageCfadsCase(str, Enum):
    """Canonical lender cash-flow case selected by an explicit policy."""

    BASE = "BASE"
    BANK = "BANK"


class CoverageCashflowBasis(str, Enum):
    """Metric-specific transformation applied after economic-case selection."""

    RAW_SELECTED_CFADS = "RAW_SELECTED_CFADS"
    SENIOR_ELIGIBLE_CFADS = "SENIOR_ELIGIBLE_CFADS"


class CoverageDenominatorBasis(str, Enum):
    """Debt balance authority at the coverage measurement boundary."""

    SENIOR_OPENING_BALANCE = "SENIOR_OPENING_BALANCE"


class CoverageCalculationDatePolicy(str, Enum):
    """Supported coverage measurement boundary."""

    FIRST_SENIOR_PERIOD_OPENING = "FIRST_SENIOR_PERIOD_OPENING"


class LoanLifeConvention(str, Enum):
    CONTRACTUAL_MATURITY = "CONTRACTUAL_MATURITY"
    ACTUAL_REPAYMENT = "ACTUAL_REPAYMENT"


class SponsorValuationDatePolicy(str, Enum):
    FINANCIAL_CLOSE = "FINANCIAL_CLOSE"
    EXPLICIT_DATE = "EXPLICIT_DATE"


@dataclass(frozen=True)
class SponsorValuationPolicy:
    """Total Sponsor hurdle; quoted as an annual ratio, never inferred."""
    annual_discount_rate: float | None
    authority_label: str
    discount_convention: DiscountConvention = DiscountConvention.ACT_365_FIXED
    valuation_date_policy: SponsorValuationDatePolicy = SponsorValuationDatePolicy.FINANCIAL_CLOSE
    explicit_valuation_date: date | None = None


@dataclass(frozen=True)
class ProjectValuationPolicy:
    """Explicit Project NPV authority; never inferred from financing terms."""

    annual_discount_rate: float | None
    valuation_date_policy: ValuationDatePolicy
    discount_convention: DiscountConvention
    authority_label: str
    explicit_valuation_date: date | None = None
    periodic_rate_conversion: PeriodicRateConversion | None = None
    periods_per_year: int | None = None
    first_cashflow_timing: PeriodicFirstCashflowTiming | None = None


@dataclass(frozen=True)
class DebtCoverageValuationPolicy:
    """Explicit LLCR/PLCR rate, case and calculation-boundary authority."""

    annual_discount_rate: float | None
    cfads_case: CoverageCfadsCase | None
    calculation_date_policy: CoverageCalculationDatePolicy
    discount_convention: DiscountConvention
    authority_label: str
    llcr_cashflow_basis: CoverageCashflowBasis | None = None
    plcr_cashflow_basis: CoverageCashflowBasis | None = None
    denominator_basis: CoverageDenominatorBasis | None = None
    periodic_rate_conversion: PeriodicRateConversion | None = None
    periods_per_year: int | None = None
    first_cashflow_timing: PeriodicFirstCashflowTiming | None = None
    rolling_loan_life: LoanLifeConvention = LoanLifeConvention.ACTUAL_REPAYMENT


@dataclass(frozen=True)
class ValuationPolicies:
    """Optional C2 policies attached to typed ProjectInputs."""

    project: ProjectValuationPolicy | None = None
    coverage: DebtCoverageValuationPolicy | None = None
    sponsor: SponsorValuationPolicy | None = None
    policy_version: str | None = None
