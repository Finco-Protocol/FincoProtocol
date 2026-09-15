"""Immutable C2 Project NPV and lender-coverage result contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from finco_core.inputs.valuation import (
    CoverageCashflowBasis,
    CoverageCfadsCase,
    CoverageDenominatorBasis,
    DiscountConvention,
    PeriodicFirstCashflowTiming,
    PeriodicRateConversion,
)


class ProjectNpvStatus(str, Enum):
    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INVALID_DISCOUNT_RATE = "INVALID_DISCOUNT_RATE"
    VALUATION_DATE_UNAVAILABLE = "VALUATION_DATE_UNAVAILABLE"
    UPSTREAM_PROJECT_RETURN_UNAVAILABLE = "UPSTREAM_PROJECT_RETURN_UNAVAILABLE"
    CASHFLOW_BEFORE_UNSUPPORTED_VALUATION_DATE = (
        "CASHFLOW_BEFORE_UNSUPPORTED_VALUATION_DATE"
    )
    NON_FINITE_RESULT = "NON_FINITE_RESULT"


class CoverageMetric(str, Enum):
    LLCR = "LLCR"
    PLCR = "PLCR"


class CoverageStatus(str, Enum):
    OK = "OK"
    NOT_APPLICABLE_NO_SENIOR = "NOT_APPLICABLE_NO_SENIOR"
    DEBT_BALANCE_ZERO = "DEBT_BALANCE_ZERO"
    COVERAGE_CFADS_CASE_NOT_CONFIGURED = (
        "COVERAGE_CFADS_CASE_NOT_CONFIGURED"
    )
    COVERAGE_DISCOUNT_RATE_NOT_CONFIGURED = (
        "COVERAGE_DISCOUNT_RATE_NOT_CONFIGURED"
    )
    COVERAGE_CASHFLOW_BASIS_NOT_CONFIGURED = (
        "COVERAGE_CASHFLOW_BASIS_NOT_CONFIGURED"
    )
    COVERAGE_CASHFLOW_BASIS_UNSUPPORTED_FOR_METRIC = (
        "COVERAGE_CASHFLOW_BASIS_UNSUPPORTED_FOR_METRIC"
    )
    COVERAGE_ELIGIBILITY_AUTHORITY_UNAVAILABLE = (
        "COVERAGE_ELIGIBILITY_AUTHORITY_UNAVAILABLE"
    )
    COVERAGE_DISCOUNT_CONVENTION_UNSUPPORTED = (
        "COVERAGE_DISCOUNT_CONVENTION_UNSUPPORTED"
    )
    COVERAGE_CALCULATION_DATE_POLICY_UNSUPPORTED = (
        "COVERAGE_CALCULATION_DATE_POLICY_UNSUPPORTED"
    )
    COVERAGE_DENOMINATOR_AUTHORITY_UNAVAILABLE = (
        "COVERAGE_DENOMINATOR_AUTHORITY_UNAVAILABLE"
    )
    INVALID_DISCOUNT_RATE = "INVALID_DISCOUNT_RATE"
    SENIOR_MATURITY_UNAVAILABLE = "SENIOR_MATURITY_UNAVAILABLE"
    PROJECT_LIFE_HORIZON_UNAVAILABLE = "PROJECT_LIFE_HORIZON_UNAVAILABLE"
    PERIOD_AXIS_MISMATCH = "PERIOD_AXIS_MISMATCH"
    NON_FINITE_RESULT = "NON_FINITE_RESULT"


class LlcrThresholdStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DiscountAuditRow:
    period_index: int | None
    cashflow_date: date
    undiscounted_cashflow_keur: float
    included: bool
    exclusion_reason: str | None
    year_fraction: float | None
    discount_factor: float | None
    discounted_cashflow_keur: float | None
    raw_selected_cashflow_keur: float | None = None
    eligibility_factor: float | None = None
    eligible_cashflow_keur: float | None = None
    discount_exponent: float | None = None


@dataclass(frozen=True)
class ProjectNpvResult:
    status: ProjectNpvStatus
    npv_keur: float | None
    valuation_date: date | None
    annual_discount_rate: float | None
    discount_convention: DiscountConvention | None
    discount_authority: str | None
    cashflow_identity_authority: str
    periods: tuple[DiscountAuditRow, ...]
    upstream_project_return_status: str | None = None


@dataclass(frozen=True)
class CoverageRatioResult:
    metric: CoverageMetric
    status: CoverageStatus
    calculation_date: date | None
    cfads_case: CoverageCfadsCase | None
    annual_discount_rate: float | None
    discount_convention: DiscountConvention | None
    discount_authority: str | None
    cashflow_basis: CoverageCashflowBasis | None
    denominator_basis: CoverageDenominatorBasis | None
    periodic_rate_conversion: PeriodicRateConversion | None
    periods_per_year: int | None
    first_cashflow_timing: PeriodicFirstCashflowTiming | None
    effective_periodic_discount_rate: float | None
    debt_balance_denominator_keur: float | None
    pv_cfads_numerator_keur: float | None
    ratio: float | None
    periods: tuple[DiscountAuditRow, ...]


@dataclass(frozen=True)
class LenderCoverageResult:
    llcr: CoverageRatioResult
    plcr: CoverageRatioResult
    minimum_llcr: float | None
    llcr_headroom: float | None
    llcr_threshold_status: LlcrThresholdStatus


@dataclass(frozen=True)
class DecisionCompleteValuationSummary:
    project_npv: ProjectNpvResult
    lender_coverage: LenderCoverageResult
