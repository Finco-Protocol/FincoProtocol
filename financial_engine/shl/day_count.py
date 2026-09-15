"""financial_engine.shl.day_count — Typed SHL day-count dispatch (C3B3D2B1).

SHL uses an INCLUSIVE end-date convention: the last calendar day of the period
counts as a full calendar day.  This differs from Senior Debt:

  Senior Debt (financial_engine.senior_debt.interest.period_day_fraction):
      days = (period_end - period_start).days          [exclusive end]
      dcf  = days / denominator

  SHL (this module):
      days = (period_end - period_start).days + 1      [inclusive end]
      dcf  = days / denominator

Do NOT unify these two implementations.  The date interval semantics are
different, and C3B3D2B0 proved the SHL inclusive convention against all 40
Generic Solar Reference operating periods to machine epsilon.  Any unification would silently
alter Senior Debt numeric behaviour.

The existing compute_shl_dcf_actual_365_inclusive() in waterfall.py is
governance-locked and unchanged.  compute_shl_dcf() delegates to it for
ACT_365_FIXED and implements ACT_360 with identical inclusive semantics.

Convention labels
-----------------
ACT_365_FIXED : SOURCE_PROVEN_FOR_GENERIC_SOLAR_REFERENCE_OPERATING_SHL
    Proven in C3B3D2B0 across all 40 operating periods.
    Max source-oracle delta: 1.11e-16 (machine epsilon).

ACT_360 : GENERIC_ENGINE_CAPABILITY
    Not policy-defined for Generic Solar Reference SHL.  A generic calculation capability.

PERIOD_AXIS_ACTUAL_YEAR : GENERIC_ENGINE_CAPABILITY
    Actual days divided by the actual calendar-year denominator, segmented at
    year boundaries, with the same inclusive SHL date semantics.
"""
from __future__ import annotations

from datetime import date
import calendar

from financial_engine.shl.contracts import ShlDayCountConvention
from financial_engine.shl.waterfall import compute_shl_dcf_actual_365_inclusive


def compute_shl_dcf(
    period_start: date,
    period_end: date,
    convention: ShlDayCountConvention,
) -> float:
    """Compute the SHL day-count fraction for one period.

    Uses INCLUSIVE end-date semantics for all conventions: the last calendar
    day of the period counts as a full calendar day.

    Parameters
    ----------
    period_start : date
        First calendar day of the period (inclusive).
    period_end : date
        Last calendar day of the period (inclusive).
    convention : ShlDayCountConvention
        Typed convention — ACT_365_FIXED, ACT_360, or PERIOD_AXIS_ACTUAL_YEAR.

    Returns
    -------
    float
        Day-count fraction = (actual_inclusive_days) / denominator.

    Raises
    ------
    ValueError
        If period_end < period_start, or convention is unknown.
    """
    if not isinstance(convention, ShlDayCountConvention):
        raise ValueError(
            f"convention must be ShlDayCountConvention, got {convention!r}"
        )
    if period_end < period_start:
        raise ValueError(
            f"period_end ({period_end}) must be >= period_start ({period_start})"
        )

    if convention == ShlDayCountConvention.ACT_365_FIXED:
        # Delegates to governance-locked C3B3D2B0 function.
        # SOURCE_PROVEN_FOR_GENERIC_SOLAR_REFERENCE_OPERATING_SHL
        return compute_shl_dcf_actual_365_inclusive(period_start, period_end)

    if convention == ShlDayCountConvention.ACT_360:
        # GENERIC_ENGINE_CAPABILITY — same inclusive semantics, denominator 360.
        # No Generic Solar Reference SHL source evidence for this convention.
        days_inclusive = (period_end - period_start).days + 1
        return days_inclusive / 360.0

    if convention == ShlDayCountConvention.PERIOD_AXIS_ACTUAL_YEAR:
        # Actual/actual by calendar-year segment, retaining SHL's inclusive
        # end-date convention. Typed construction dates remain the sole axis.
        fraction = 0.0
        cursor = period_start
        while cursor <= period_end:
            segment_end = min(period_end, date(cursor.year, 12, 31))
            days_inclusive = (segment_end - cursor).days + 1
            fraction += days_inclusive / (366.0 if calendar.isleap(cursor.year) else 365.0)
            cursor = segment_end.replace(year=segment_end.year + 1, month=1, day=1)
        return fraction

    raise ValueError(  # pragma: no cover — enum exhaustion guard
        f"Unsupported ShlDayCountConvention: {convention!r}"
    )
