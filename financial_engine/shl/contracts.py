"""financial_engine.shl.contracts — Typed enums and dataclasses for canonical SHL schedule.

All types are frozen dataclasses. No project-identity dispatch.
No imports from app, finco_core, or any framework.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class ShlDayCountConvention(str, Enum):
    """Typed day-count convention for SHL interest accrual (C3B3D2B1).

    SHL uses INCLUSIVE end-date convention: the last calendar day of the period
    IS counted as a full calendar day.  This differs from Senior Debt, which uses
    an EXCLUSIVE end-date convention.  Do NOT share a DCF implementation between
    Senior Debt and SHL.

    Conventions
    -----------
    ACT_365_FIXED : SOURCE_PROVEN_FOR_GENERIC_SOLAR_REFERENCE_OPERATING_SHL
        day_count_fraction = actual_period_days_inclusive / 365
        Denominator is always 365, even in leap years (actual/365-Fixed).
        Proven against all 40 Generic Solar Reference operating periods; max source-oracle
        delta = 1.11e-16 (machine epsilon), C3B3D2B0.

    ACT_360 : GENERIC_ENGINE_CAPABILITY
        day_count_fraction = actual_period_days_inclusive / 360
        Same inclusive day-boundary semantics as ACT_365_FIXED.
        No Generic Solar Reference SHL source proof for this convention; capability only.
    """
    ACT_365_FIXED = "ACT_365_FIXED"
    ACT_360 = "ACT_360"
    PERIOD_AXIS_ACTUAL_YEAR = "PERIOD_AXIS_ACTUAL_YEAR"


class ShlInterestRateMode(str, Enum):
    """Supported interest rate mode for canonical SHL."""
    FIXED = "FIXED"
    # FLOATING, STEP — deferred, not C3B3D1 scope


class ShlInterestPaymentMode(str, Enum):
    """How accrued interest is settled each period."""
    CASH_PAID = "CASH_PAID"   # full gross interest paid in cash each period
    PIK = "PIK"               # interest capitalised into principal each period
    # MIXED (PIK-then-cash): multi-mode support is C3B3D2 scope


class ShlRepaymentMode(str, Enum):
    """Principal repayment mechanism."""
    BULLET = "BULLET"                     # full principal at maturity_period_index
    CASH_SWEEP = "CASH_SWEEP"             # surplus after interest sweeps principal
    EXPLICIT_SCHEDULE = "EXPLICIT_SCHEDULE"  # per-period scheduled_principal_keur
    # FCF_WATERFALL, CASH_SWEEP — fail-closed (C3B3D2+ scope)


@dataclass(frozen=True)
class ShlSchedulePolicy:
    """Interest and repayment policy for a canonical SHL schedule.

    Fields
    ------
    annual_rate : float
        Annual simple interest rate (e.g. 0.08 for 8%). Must be non-negative
        and finite.
    rate_mode : ShlInterestRateMode
        Rate mode — currently only FIXED is supported.
    payment_mode : ShlInterestPaymentMode
        Whether accrued interest is cash-paid or PIK each period.
    repayment_mode : ShlRepaymentMode
        Principal repayment mechanic.
    """
    annual_rate: float
    rate_mode: ShlInterestRateMode = ShlInterestRateMode.FIXED
    payment_mode: ShlInterestPaymentMode = ShlInterestPaymentMode.CASH_PAID
    repayment_mode: ShlRepaymentMode = ShlRepaymentMode.BULLET

    def __post_init__(self) -> None:
        if isinstance(self.annual_rate, bool):
            raise ValueError(
                f"annual_rate must be a float, not bool: {self.annual_rate!r}"
            )
        if not isinstance(self.annual_rate, (int, float)):
            raise ValueError(
                f"annual_rate must be numeric, got {type(self.annual_rate).__name__}"
            )
        if not math.isfinite(self.annual_rate):
            raise ValueError(
                f"annual_rate must be finite, got {self.annual_rate!r}"
            )
        if self.annual_rate < 0:
            raise ValueError(
                f"annual_rate must be non-negative, got {self.annual_rate!r}"
            )
        if not isinstance(self.rate_mode, ShlInterestRateMode):
            raise ValueError(
                f"rate_mode must be ShlInterestRateMode, got {self.rate_mode!r}"
            )
        if not isinstance(self.payment_mode, ShlInterestPaymentMode):
            raise ValueError(
                f"payment_mode must be ShlInterestPaymentMode, got {self.payment_mode!r}"
            )
        if not isinstance(self.repayment_mode, ShlRepaymentMode):
            raise ValueError(
                f"repayment_mode must be ShlRepaymentMode, got {self.repayment_mode!r}"
            )


@dataclass(frozen=True)
class ShlPeriodInput:
    """Canonical input for one model period in the SHL schedule.

    Fields
    ------
    period_index : int
        0-based period index.
    day_count_fraction : float
        Day-count fraction for this period (e.g. 0.5 for semiannual). Must
        be positive and finite.
    drawdown_keur : float
        New SHL funding drawn at the START of this period (period-start draw
        convention). 0.0 if no drawdown.
    scheduled_principal_keur : float
        Principal due for repayment this period. 0.0 for bullet / non-maturity
        periods. Ignored when repayment_mode == BULLET (the schedule runner
        sets this automatically at maturity_period_index).
    """
    period_index: int
    day_count_fraction: float
    drawdown_keur: float = 0.0
    scheduled_principal_keur: float = 0.0


@dataclass(frozen=True)
class ShlPeriodResult:
    """Canonical output for one model period in the SHL schedule.

    Balance roll-forward identity:
        closing_balance = opening_balance + drawdown + pik_interest - scheduled_principal

    Fields
    ------
    period_index : int
        0-based period index.
    opening_balance_keur : float
        SHL balance at the start of the period (before drawdown).
    gross_accrued_interest_keur : float
        Interest accrued on (opening + drawdown) × annual_rate × day_count_fraction.
        This is the gross accounting SHL interest — flows into PeriodInterestInput.shl_interest_keur
        as an input to the tax engine; deductibility is determined by TaxPolicy, not here.
    cash_interest_keur : float
        Cash settled interest. Equals gross when CASH_PAID, 0 when PIK.
    pik_interest_keur : float
        Interest capitalised into balance. Equals gross when PIK, 0 when CASH_PAID.
    scheduled_principal_keur : float
        Principal repaid this period (from the schedule or bullet at maturity).
    closing_balance_keur : float
        SHL balance at period end after accrual, PIK, and principal repayment.
    """
    period_index: int
    opening_balance_keur: float
    gross_accrued_interest_keur: float
    cash_interest_keur: float
    pik_interest_keur: float
    scheduled_principal_keur: float
    closing_balance_keur: float


# Immutable collection alias for a full schedule
ShlScheduleResult = tuple[ShlPeriodResult, ...]


@dataclass(frozen=True)
class ShlWaterfallPolicy:
    """Policy governing the clean SHL waterfall formula (C3B3D2B1).

    Covers operating-period computation only.  Construction is handled by the
    C3B3D1 engine (compute_shl_period with opening=0, drawdown_keur, DCF=1.0,
    payment_mode=PIK).

    This policy is per-instrument: Senior Debt has its own DayCountConvention
    inside SeniorDebtPolicy.  Changing ShlWaterfallPolicy.day_count_convention
    does NOT affect Senior Debt, and vice versa.

    Fields
    ------
    annual_rate : float
        Annual simple interest rate (e.g. 0.08 for 8%). Must be >= 0 and finite.
    day_count_convention : ShlDayCountConvention
        How day-count fractions are derived from period calendar dates.
        ACT_365_FIXED is policy-defined for Generic Solar Reference operating SHL (C3B3D2B0).
        ACT_360 is a generic engine capability without Generic Solar Reference SHL source proof.
    """
    annual_rate: float
    day_count_convention: ShlDayCountConvention

    def __post_init__(self) -> None:
        if isinstance(self.annual_rate, bool):
            raise ValueError(
                f"annual_rate must be a float, not bool: {self.annual_rate!r}"
            )
        if not isinstance(self.annual_rate, (int, float)):
            raise ValueError(
                f"annual_rate must be numeric, got {type(self.annual_rate).__name__}"
            )
        if not math.isfinite(self.annual_rate):
            raise ValueError(
                f"annual_rate must be finite, got {self.annual_rate!r}"
            )
        if self.annual_rate < 0:
            raise ValueError(
                f"annual_rate must be non-negative, got {self.annual_rate!r}"
            )
        if not isinstance(self.day_count_convention, ShlDayCountConvention):
            raise ValueError(
                f"day_count_convention must be ShlDayCountConvention, "
                f"got {self.day_count_convention!r}"
            )
