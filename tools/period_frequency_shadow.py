"""WF-23 geometry experiment. NOT a financial engine or a production period axis.

No FINCO imports, money, cash-flow allocation, persistence or activation. Callers
must choose every convention; successful geometry is NOT financial approval.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from fractions import Fraction


class StubRule(str, Enum):
    KEEP_COD = "KEEP_COD"
    ROLL_UNDER_SEVEN_DAYS = "ROLL_UNDER_SEVEN_DAYS"


class FractionRule(str, Enum):
    END_YEAR_ACTUAL = "END_YEAR_ACTUAL"
    LEGACY_H2_NEXT_YEAR = "LEGACY_H2_NEXT_YEAR"


class HorizonRule(str, Enum):
    FIXED_PERIOD_COUNT = "FIXED_PERIOD_COUNT"
    COD_ANNIVERSARY = "COD_ANNIVERSARY"


class EventPosition(str, Enum):
    BEFORE_AXIS = "BEFORE_AXIS"
    BOUNDARY = "BOUNDARY"
    WITHIN_PERIOD = "WITHIN_PERIOD"
    AFTER_AXIS = "AFTER_AXIS"


@dataclass(frozen=True)
class ShadowPolicy:
    months: int
    stub: StubRule
    fraction: FractionRule
    cod_first_day_inclusive: bool
    horizon: HorizonRule

    def __post_init__(self):
        if type(self.months) is not int or self.months not in (3, 6):
            raise ValueError("SHADOW_FREQUENCY: expected 3 or 6 months")
        if not isinstance(self.stub, StubRule) or not isinstance(self.fraction, FractionRule):
            raise ValueError("SHADOW_POLICY: explicit typed stub and fraction rules required")
        if not isinstance(self.horizon, HorizonRule) or type(self.cod_first_day_inclusive) is not bool:
            raise ValueError("SHADOW_POLICY: explicit horizon and COD-day rules required")
        if self.months != 6 and self.fraction is FractionRule.LEGACY_H2_NEXT_YEAR:
            raise ValueError("SHADOW_POLICY: legacy H2 convention has no quarterly authority")


@dataclass(frozen=True)
class ShadowPeriod:
    # Deliberately NOT the production PeriodMeta/OperatingPeriodResult interface.
    position: int
    start: date
    end: date
    model_year: int
    slot: int
    accrual_days: int
    year_fraction: Fraction


@dataclass(frozen=True)
class ShadowCalendar:
    actual_cod: date
    policy: ShadowPolicy
    rows: tuple[ShadowPeriod, ...]
    classification: str = field(default="SHADOW_NOT_FINANCIAL_RUN", init=False)


def add_months(anchor: date, months: int) -> date:
    """Single-anchor month arithmetic; never chain through a shortened February."""
    if type(anchor) is not date or type(months) is not int or months < 0:
        raise ValueError("SHADOW_DATE: exact date and nonnegative integer months required")
    year, month0 = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    try:
        return date(year, month0 + 1, min(anchor.day, calendar.monthrange(year, month0 + 1)[1]))
    except (ValueError, OverflowError) as exc:
        raise ValueError("SHADOW_DATE: date outside supported calendar") from exc


def _boundary(anchor: date, months: int, *, strictly_after: bool) -> date:
    for month in range(months, 13, months):
        candidate = date(anchor.year, month, calendar.monthrange(anchor.year, month)[1])
        if candidate > anchor or (not strictly_after and candidate == anchor):
            return candidate
    return date(anchor.year + 1, months, calendar.monthrange(anchor.year + 1, months)[1])


def build_shadow_calendar(*, cod: date, horizon_years: int, policy: ShadowPolicy) -> ShadowCalendar:
    if type(cod) is not date or type(horizon_years) is not int or not 1 <= horizon_years <= 100:
        raise ValueError("SHADOW_INPUT: date and 1..100 whole years required (experiment bound)")
    if not isinstance(policy, ShadowPolicy):
        raise ValueError("SHADOW_POLICY: explicit policy required")
    stop = add_months(cod, horizon_years * 12)
    start = cod
    nearby = _boundary(cod, policy.months, strictly_after=False)
    if policy.stub is StubRule.ROLL_UNDER_SEVEN_DAYS and (nearby - cod).days < 7:
        start = nearby
    rows = []
    periods_per_year = 12 // policy.months
    count = horizon_years * periods_per_year
    while (len(rows) < count if policy.horizon is HorizonRule.FIXED_PERIOD_COUNT else start < stop):
        end = _boundary(start, policy.months, strictly_after=True)
        if policy.horizon is HorizonRule.COD_ANNIVERSARY:
            end = min(end, stop)
        position = len(rows)
        days = (end - start).days
        if position == 0 and start == cod and cod.day == 1 and policy.cod_first_day_inclusive:
            days += 1
        reference_year = end.year
        if policy.fraction is FractionRule.LEGACY_H2_NEXT_YEAR and end.month == 12:
            reference_year += 1
        denominator = 366 if calendar.isleap(reference_year) else 365
        rows.append(ShadowPeriod(position, start, end, position // periods_per_year + 1,
                                 position % periods_per_year + 1, days, Fraction(days, denominator)))
        start = end
    return ShadowCalendar(cod, policy, tuple(rows))


def event_position(axis: ShadowCalendar, event: date) -> EventPosition:
    """Classify a date, never move it or calculate a price/payment for it."""
    _validate_geometry(axis)
    if type(event) is not date:
        raise ValueError("SHADOW_EVENT: exact date required")
    if event < axis.rows[0].start:
        return EventPosition.BEFORE_AXIS
    if event > axis.rows[-1].end:
        return EventPosition.AFTER_AXIS
    if event == axis.rows[0].start or any(event == row.end for row in axis.rows):
        return EventPosition.BOUNDARY
    return EventPosition.WITHIN_PERIOD


def _validate_geometry(axis: ShadowCalendar) -> None:
    if not isinstance(axis, ShadowCalendar) or type(axis.rows) is not tuple or not axis.rows:
        raise ValueError("SHADOW_AXIS: nonempty immutable geometry required")
    for position, row in enumerate(axis.rows):
        if (not isinstance(row, ShadowPeriod) or row.position != position
                or type(row.start) is not date or type(row.end) is not date or row.start >= row.end
                or (position and row.start != axis.rows[position - 1].end)):
            raise ValueError("SHADOW_AXIS: duplicate, missing, reordered or noncontiguous interval")


def coarse_geometry(*, fine: ShadowCalendar, coarse: ShadowCalendar) -> tuple[tuple[int, ...], ...]:
    """Whole-interval membership ONLY. Does not aggregate CFADS or approve DSCR.

    In particular six-month cash cannot be split into quarterly cash by this tool.
    A different horizon/stub is refused, not repaired with invented period weights.
    """
    _validate_geometry(fine)
    _validate_geometry(coarse)
    if fine.policy.months > coarse.policy.months:
        raise ValueError("SHADOW_DISAGGREGATION_POLICY_REQUIRED")
    if (fine.rows[0].start, fine.rows[-1].end) != (coarse.rows[0].start, coarse.rows[-1].end):
        raise ValueError("SHADOW_HORIZON_OR_STUB_MISMATCH")
    result = []
    cursor = 0
    for parent in coarse.rows:
        members = []
        expected_start = parent.start
        while cursor < len(fine.rows) and fine.rows[cursor].end <= parent.end:
            child = fine.rows[cursor]
            if child.start != expected_start:
                raise ValueError("SHADOW_NONCONTIGUOUS_MEMBERSHIP")
            members.append(child.position)
            expected_start = child.end
            cursor += 1
        if not members or expected_start != parent.end:
            raise ValueError("SHADOW_EVENT_SPLIT_POLICY_REQUIRED")
        result.append(tuple(members))
    if cursor != len(fine.rows):
        raise ValueError("SHADOW_UNMAPPED_PERIOD")
    return tuple(result)
