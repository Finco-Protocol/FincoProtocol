"""financial_engine.senior_debt.interest — Period interest calculation.

interest_t = opening_balance_t × annual_rate_t × day_fraction_t

day_fraction_t is derived from the period's actual start/end dates and the
configured day-count convention (ACT/365 or ACT/360).
"""
from __future__ import annotations

import math
from datetime import date

from financial_engine.senior_debt.policy import DayCountConvention


def period_day_fraction(
    period_start: date,
    period_end: date,
    convention: DayCountConvention,
) -> float:
    """Return the day-count fraction for one model period.

    Args:
        period_start: inclusive start date of the period
        period_end:   exclusive end date (= start of next period)
        convention:   ACT_365 or ACT_360
    """
    days = (period_end - period_start).days
    if days < 0:
        raise ValueError(
            f"period_end {period_end} is before period_start {period_start}"
        )
    if convention == DayCountConvention.ACT_365:
        return days / 365.0
    if convention == DayCountConvention.ACT_360:
        return days / 360.0
    raise ValueError(f"Unsupported day-count convention: {convention!r}")


def period_interest(
    opening_balance_keur: float,
    annual_rate: float,
    day_frac: float,
) -> float:
    """Return the interest charge for one period.

    interest = opening_balance × annual_rate × day_fraction

    Both opening_balance and the result are in kEUR.
    """
    if not math.isfinite(opening_balance_keur):
        raise ValueError(f"Non-finite opening_balance_keur: {opening_balance_keur}")
    if not math.isfinite(annual_rate):
        raise ValueError(f"Non-finite annual_rate: {annual_rate}")
    if not math.isfinite(day_frac):
        raise ValueError(f"Non-finite day_frac: {day_frac}")
    return opening_balance_keur * annual_rate * day_frac


def build_rate_map(
    period_rates: tuple,       # tuple[PeriodRate, ...]
    period_indices: tuple[int, ...],
    annual_fixed_rate: float | None,
) -> dict[int, float]:
    """Return {period_index: annual_rate} for all relevant periods.

    Uses per-period explicit rates where provided; falls back to
    annual_fixed_rate for any period not explicitly listed.

    Raises ValueError if a period has no applicable rate.
    """
    explicit: dict[int, float] = {pr.period_index: pr.annual_rate for pr in period_rates}
    result: dict[int, float] = {}
    for idx in period_indices:
        if idx in explicit:
            result[idx] = explicit[idx]
        elif annual_fixed_rate is not None:
            result[idx] = annual_fixed_rate
        else:
            raise ValueError(
                f"Period {idx} has no applicable interest rate: "
                "no explicit period_rate and no policy.annual_fixed_rate"
            )
    return result
