"""financial_engine.shl.waterfall — Clean SHL waterfall period formula (C3B3D2B0).

Single pure function with typed BULLET/CASH_SWEEP principal eligibility.

Natural waterfall formula (handles all settlement modes by arithmetic):
    gross          = opening × annual_rate × day_count_fraction
    cash_interest  = min(cash_available, gross)
    capitalised    = gross - cash_interest
    remaining_cash = cash_available - cash_interest
    principal      = max(0, min(remaining_cash, opening + capitalised)) when eligible
    closing        = opening + capitalised - principal

When cash_available = 0: full capitalisation.
When 0 < cash_available < gross: partial cash, partial capitalisation.
When cash_available >= gross: full cash interest; surplus sweeps principal.

Operating periods: no drawdown. Construction is handled by the C3B3D1 primitive
(compute_shl_period with drawdown_keur). Do NOT pass draw as opening balance here.

No hardcoded period boundaries or project-specific constants.
No imports from app, finco_core waterfall, or any production runtime.

Day-count convention (OPERATING_SHL_DAY_COUNT_SOURCE_VECTOR_PROVEN_ACTUAL_365_INCLUSIVE):
    dcf = ((end_date - start_date).days + 1) / 365
Proven against all 40 operating periods via independent source period dates
(max delta vs source-derived oracle: 1.11e-16, machine epsilon).
Denominator is always 365 even in leap years (actual/365-Fixed).
Use compute_shl_dcf_actual_365_inclusive() to compute it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from financial_engine.shl.contracts import ShlRepaymentMode


@dataclass(frozen=True)
class ShlWaterfallPeriodResult:
    """Result of one SHL waterfall period.

    Balance roll-forward identity:
        closing_balance_keur = opening_balance_keur + capitalised_interest_keur
                               - principal_repaid_keur

    Fields
    ------
    period_index : int
        0-based period index.
    opening_balance_keur : float
        SHL balance at period start.
    gross_accrued_interest_keur : float
        opening × annual_rate × day_count_fraction.
    cash_interest_keur : float
        Interest settled in cash = min(cash_available, gross).
    pik_interest_keur : float
        Interest capitalised into balance = gross - cash_interest.
    principal_repaid_keur : float
        Principal swept from remaining cash after interest, capped at outstanding.
    closing_balance_keur : float
        opening + capitalised - principal.
    shl_service_keur : float
        Total cash outflow = cash_interest + principal_repaid.
    """
    period_index: int
    opening_balance_keur: float
    gross_accrued_interest_keur: float
    cash_interest_keur: float
    pik_interest_keur: float
    principal_repaid_keur: float
    closing_balance_keur: float
    shl_service_keur: float


def compute_shl_dcf_actual_365_inclusive(
    period_start: date,
    period_end: date,
) -> float:
    """Compute the SHL day-count fraction using actual/365 with inclusive end date.

    Convention: actual calendar days from start to end (inclusive) divided by 365.
    The denominator is always 365 regardless of leap years.

    Proven independently against all 40 Generic Solar Reference operating periods:
    max delta vs source-implied DCF = 1.11e-16 (machine epsilon).

    Parameters
    ----------
    period_start : date
        First calendar day of the period (inclusive).
    period_end : date
        Last calendar day of the period (inclusive).

    Returns
    -------
    float
        Day-count fraction = ((end - start).days + 1) / 365.

    Raises
    ------
    ValueError
        If period_end is before period_start.
    """
    if period_end < period_start:
        raise ValueError(
            f"period_end ({period_end}) must be >= period_start ({period_start})"
        )
    return ((period_end - period_start).days + 1) / 365


def compute_shl_waterfall_period(
    opening_balance_keur: float,
    annual_rate: float,
    day_count_fraction: float,
    cash_available_for_shl_keur: float,
    period_index: int = 0,
    repayment_mode: ShlRepaymentMode = ShlRepaymentMode.CASH_SWEEP,
    is_maturity_period: bool = False,
) -> ShlWaterfallPeriodResult:
    """Compute one SHL waterfall period using the natural surplus-over-interest formula.

    This function handles operating periods only. Construction (opening=0, drawdown>0)
    is handled by financial_engine.shl.engine.compute_shl_period with drawdown_keur.

    Parameters
    ----------
    opening_balance_keur : float
        SHL balance at period start. Must be >= 0.
    annual_rate : float
        Annual simple interest rate (e.g. 0.08). Must be >= 0 and finite.
    day_count_fraction : float
        Day-count fraction for this period. Compute via
        compute_shl_dcf_actual_365_inclusive(start, end) for Generic Solar Reference.
        Must be > 0 and finite.
    cash_available_for_shl_keur : float
        Cash available for SHL service this period (from the FCF waterfall above SHL).
        0.0 for full-capitalisation periods. Must be >= 0 and finite.
    period_index : int
        0-based period index (for error messages and result labelling). Default 0.

    Returns
    -------
    ShlWaterfallPeriodResult

    Raises
    ------
    ValueError
        Any input is non-finite, or opening/rate/cash is negative, or dcf <= 0.
    """
    _check_finite("opening_balance_keur", opening_balance_keur)
    _check_finite("annual_rate", annual_rate)
    _check_finite("day_count_fraction", day_count_fraction)
    _check_finite("cash_available_for_shl_keur", cash_available_for_shl_keur)

    if opening_balance_keur < 0:
        raise ValueError(
            f"opening_balance_keur must be >= 0, got {opening_balance_keur!r} "
            f"(period_index={period_index})"
        )
    if annual_rate < 0:
        raise ValueError(
            f"annual_rate must be >= 0, got {annual_rate!r} "
            f"(period_index={period_index})"
        )
    if day_count_fraction <= 0:
        raise ValueError(
            f"day_count_fraction must be > 0, got {day_count_fraction!r} "
            f"(period_index={period_index})"
        )
    if cash_available_for_shl_keur < 0:
        raise ValueError(
            f"cash_available_for_shl_keur must be >= 0, got {cash_available_for_shl_keur!r} "
            f"(period_index={period_index})"
        )

    gross = opening_balance_keur * annual_rate * day_count_fraction
    cash_interest = min(cash_available_for_shl_keur, gross)
    capitalised = gross - cash_interest
    remaining_cash = cash_available_for_shl_keur - cash_interest
    outstanding = opening_balance_keur + capitalised
    if repayment_mode == ShlRepaymentMode.BULLET:
        principal = min(remaining_cash, outstanding) if is_maturity_period else 0.0
    elif repayment_mode == ShlRepaymentMode.CASH_SWEEP:
        principal = max(0.0, min(remaining_cash, outstanding))
    else:
        raise ValueError(
            "compute_shl_waterfall_period supports BULLET or CASH_SWEEP, "
            f"got {repayment_mode!r}"
        )
    closing = max(outstanding - principal, 0.0)  # absorb floating-point dust

    return ShlWaterfallPeriodResult(
        period_index=period_index,
        opening_balance_keur=opening_balance_keur,
        gross_accrued_interest_keur=gross,
        cash_interest_keur=cash_interest,
        pik_interest_keur=capitalised,
        principal_repaid_keur=principal,
        closing_balance_keur=closing,
        shl_service_keur=cash_interest + principal,
    )


def _check_finite(name: str, value: object) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a float, not bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric, got {type(value).__name__}")
    if not math.isfinite(value):  # type: ignore[arg-type]
        raise ValueError(f"{name} must be finite, got {value!r}")
