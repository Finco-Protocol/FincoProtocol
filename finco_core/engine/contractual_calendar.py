"""OD-TIME-01 Authoritative Contractual Calendar & Date-Aware Economic Primitives.

Implements the FINCO36 owner-approved contractual calendar policy (OD-TIME-01):
- Half-open date-only intervals ``[start, end_exclusive)`` with COD day included.
- Operating end = ``add_calendar_years(cod, horizon_years)`` with explicit Feb 29
  clamp to Feb 28 in non-leap target years; final included date = ``end_exclusive - 1 day``.
- Explicit adapter-boundary conversion from legacy inclusive end labels
  (never blindly treating inclusive end labels as half-open).
- Exact calendar-year day-count fractions (``365`` / ``366`` per calendar year)
  with subperiod splitting across Jan 1, COD anniversaries, contract start/expiry,
  and indexation review dates, reconciling exactly to the reporting axis.
- Annual physical degradation stepping at exact COD anniversaries.
- OPEX inflation with explicit clock (``COD_ANNIVERSARY`` default for new annual
  operating assumptions; ``CALENDAR_YEAR`` when calendar-specific OPEX selected).
- Independent PPA pricing/indexation clocks per contract/stream
  (``FIRST_FULL_CALENDAR_YEAR_AS_BASE``, ``AFTER_FIRST_FULL_OPERATING_YEAR``,
  ``CONTRACT_ANNIVERSARY``) and exact contractual expiry date.
- Straight-line accounting depreciation over actual asset in-service life
  ``[cod, add_calendar_years(cod, life))`` with single final residual rounding
  and legitimate carrying value for assets whose life exceeds the operating horizon.

Legacy compatibility & LMA debt preservation:
- This module NEVER mutates legacy stored contracts, sealed Run history,
  LMA senior debt interest day-count (ACT/360), tax-year cutoff, or construction
  funding timing. Legacy implicit-step conventions remain inventoried and
  preserved under ``LEGACY_CALENDAR_COMPATIBILITY_PROVENANCE``.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from fractions import Fraction
from typing import Iterable, Sequence

from finco_core.inputs import ASSET_CLASS_USEFUL_LIFE, AssetClass, CapexItem, OpexItem

CALENDAR_CONTRACT_VERSION = "OD-TIME-01-v1"

LEGACY_CALENDAR_COMPATIBILITY_PROVENANCE = {
    "contract_version": CALENDAR_CONTRACT_VERSION,
    "legacy_convention": "SEMIANNUAL_IMPLICIT_STEP_BOUNDARY_END",
    "legacy_semantics": (
        "Legacy PeriodEngine semiannual rows use period-end-to-period-end day counts "
        "(excluding COD day on mid-month stubs), fixed 2*N rows ending on Jun 30 / Dec 31, "
        "and model-year stepping every two semiannual rows."
    ),
    "migration_policy": (
        "No silent reinterpretation of legacy stored data or sealed historical Runs. "
        "Contractual/date-aware calculations use explicit half-open [start, end_exclusive) "
        "intervals with explicit adapter conversion of legacy inclusive end labels."
    ),
    "debt_and_tax_preservation": (
        "Contractual senior debt draw/repay, LMA ACT/360 interest day-count, "
        "tax-year cutoff, and construction funding timing are preserved unchanged."
    ),
}


class OpexInflationClock(str, Enum):
    """Explicit OPEX escalation clock under OD-TIME-01."""
    COD_ANNIVERSARY = "COD_ANNIVERSARY"
    CALENDAR_YEAR = "CALENDAR_YEAR"


def _require_date_only(value: object, name: str) -> date:
    if type(value) is not date:
        raise ValueError(
            f"OD_TIME_01_DATE_ONLY_REQUIRED: {name} must be a datetime.date (not datetime), "
            f"got {type(value).__name__!r}"
        )
    return value


def days_in_calendar_year(year: int) -> int:
    """Return exact calendar days in ``year`` (366 for leap years, 365 otherwise)."""
    if type(year) is not int or year < 1:
        raise ValueError(f"OD_TIME_01_INVALID_YEAR: {year!r}")
    return 366 if calendar.isleap(year) else 365


def add_calendar_years(anchor: date, years: int) -> date:
    """Add ``years`` calendar years to ``anchor``, clamping Feb 29 -> Feb 28 in non-leap years."""
    _require_date_only(anchor, "anchor")
    if type(years) is not int or years < 0:
        raise ValueError(f"OD_TIME_01_INVALID_YEARS: years must be non-negative int, got {years!r}")
    target_year = anchor.year + years
    if anchor.month == 2 and anchor.day == 29 and not calendar.isleap(target_year):
        return date(target_year, 2, 28)
    return date(target_year, anchor.month, anchor.day)


@dataclass(frozen=True)
class ContractualInterval:
    """Half-open date-only interval ``[start, end_exclusive)``."""
    start: date
    end_exclusive: date

    def __post_init__(self) -> None:
        _require_date_only(self.start, "start")
        _require_date_only(self.end_exclusive, "end_exclusive")
        if self.end_exclusive <= self.start:
            raise ValueError(
                f"OD_TIME_01_EMPTY_OR_INVERTED_INTERVAL: "
                f"[{self.start.isoformat()}, {self.end_exclusive.isoformat()})"
            )

    @property
    def days(self) -> int:
        return (self.end_exclusive - self.start).days

    @property
    def final_included_date(self) -> date:
        return self.end_exclusive - timedelta(days=1)


@dataclass(frozen=True)
class CalendarYearSlice:
    """One calendar-year subinterval of a half-open interval."""
    year: int
    start: date
    end_exclusive: date
    days: int
    year_days: int
    fraction: Fraction

    @property
    def interval(self) -> ContractualInterval:
        return ContractualInterval(self.start, self.end_exclusive)


@dataclass(frozen=True)
class ContractualReportingPeriod:
    """One reporting period on the canonical OD-TIME-01 half-open axis."""
    index: int
    operating_period_index: int
    interval: ContractualInterval
    is_first_stub: bool
    is_final_stub: bool
    calendar_year_slices: tuple[CalendarYearSlice, ...]

    @property
    def start_date(self) -> date:
        return self.interval.start

    @property
    def end_exclusive(self) -> date:
        return self.interval.end_exclusive

    @property
    def end_inclusive(self) -> date:
        return self.interval.final_included_date

    @property
    def days(self) -> int:
        return self.interval.days

    @property
    def exact_year_fraction(self) -> Fraction:
        return sum((s.fraction for s in self.calendar_year_slices), Fraction(0))


def operating_horizon_interval(cod: date, horizon_years: int) -> ContractualInterval:
    """Return canonical operating horizon ``[cod, add_calendar_years(cod, horizon_years))``."""
    _require_date_only(cod, "cod")
    if type(horizon_years) is not int or horizon_years <= 0:
        raise ValueError(f"OD_TIME_01_INVALID_HORIZON: horizon_years must be positive int, got {horizon_years!r}")
    return ContractualInterval(start=cod, end_exclusive=add_calendar_years(cod, horizon_years))


def convert_legacy_inclusive_range(
    start_inclusive: date,
    end_inclusive: date,
) -> ContractualInterval:
    """Explicit adapter-boundary conversion from legacy inclusive ``[start, end]`` to ``[start, end + 1 day)``."""
    _require_date_only(start_inclusive, "start_inclusive")
    _require_date_only(end_inclusive, "end_inclusive")
    if end_inclusive < start_inclusive:
        raise ValueError(
            f"OD_TIME_01_LEGACY_INCLUSIVE_INVERTED: "
            f"[{start_inclusive.isoformat()}, {end_inclusive.isoformat()}]"
        )
    return ContractualInterval(
        start=start_inclusive,
        end_exclusive=end_inclusive + timedelta(days=1),
    )


def convert_period_meta_to_half_open(
    period,
    *,
    cod: date,
    prev_end_date: date | None = None,
) -> ContractualInterval:
    """Explicitly convert a legacy ``PeriodMeta`` operating row to a half-open ``[start, end_exclusive)``.

    Legacy ``PeriodEngine`` semantics:
    - First operating period: ``start_date == cod`` (inclusive), ``end_date`` is Jun 30 / Dec 31 (inclusive)
      -> half-open ``[cod, end_date + 1 day)`` (COD day included).
    - Subsequent operating periods: ``start_date`` equals the previous period's inclusive ``end_date``
      (e.g. Jun 30 or Dec 31), so the first newly included day is ``prev_end_date + 1 day``
      -> half-open ``[prev_end_date + 1 day, end_date + 1 day)``.
    """
    _require_date_only(cod, "cod")
    p_start = _require_date_only(period.start_date, "period.start_date")
    p_end = _require_date_only(period.end_date, "period.end_date")
    if prev_end_date is None:
        start_inc = cod if p_start == cod else p_start
    else:
        _require_date_only(prev_end_date, "prev_end_date")
        start_inc = prev_end_date + timedelta(days=1) if p_start == prev_end_date else p_start
    return convert_legacy_inclusive_range(start_inc, p_end)


def intersect_intervals(
    a: ContractualInterval,
    b: ContractualInterval,
) -> ContractualInterval | None:
    """Return exact half-open overlap ``a ∩ b``, or ``None`` if disjoint."""
    start = max(a.start, b.start)
    end_exc = min(a.end_exclusive, b.end_exclusive)
    if end_exc <= start:
        return None
    return ContractualInterval(start=start, end_exclusive=end_exc)


def split_at_dates(
    interval: ContractualInterval,
    cut_dates: Iterable[date],
) -> tuple[ContractualInterval, ...]:
    """Partition ``interval`` at all strictly interior ``cut_dates`` with zero gaps/overlaps."""
    cuts = sorted(
        {
            _require_date_only(d, "cut_date")
            for d in cut_dates
            if interval.start < _require_date_only(d, "cut_date") < interval.end_exclusive
        }
    )
    points = [interval.start, *cuts, interval.end_exclusive]
    return tuple(
        ContractualInterval(points[i], points[i + 1])
        for i in range(len(points) - 1)
    )


def split_by_calendar_years(interval: ContractualInterval) -> tuple[CalendarYearSlice, ...]:
    """Split ``interval`` at Jan 1 boundaries with exact ``days / (365|366)`` Fractions."""
    jan1_cuts = [
        date(y, 1, 1)
        for y in range(interval.start.year + 1, interval.end_exclusive.year + 1)
    ]
    subs = split_at_dates(interval, jan1_cuts)
    slices: list[CalendarYearSlice] = []
    for sub in subs:
        yr = sub.start.year
        yd = days_in_calendar_year(yr)
        slices.append(
            CalendarYearSlice(
                year=yr,
                start=sub.start,
                end_exclusive=sub.end_exclusive,
                days=sub.days,
                year_days=yd,
                fraction=Fraction(sub.days, yd),
            )
        )
    return tuple(slices)


def operating_year_index(cod: date, day: date) -> int:
    """Return 1-based operating year index stepping on exact ``add_calendar_years(cod, k)``."""
    _require_date_only(cod, "cod")
    _require_date_only(day, "day")
    if day < cod:
        return 0
    k = max(0, day.year - cod.year - 1)
    while add_calendar_years(cod, k + 1) <= day:
        k += 1
    return k + 1


def _next_reporting_boundary_exclusive(d: date, frequency_months: int) -> date:
    """Return the next exclusive reporting boundary strictly after ``d``.

    For ``frequency_months == 6``: Jan 1 or Jul 1 strictly after ``d``
    (corresponding to inclusive period ends Dec 31 and Jun 30).
    For ``frequency_months == 3``: Jan 1, Apr 1, Jul 1, or Oct 1 strictly after ``d``.
    """
    if frequency_months == 6:
        candidates = (date(d.year, 7, 1), date(d.year + 1, 1, 1))
    elif frequency_months == 3:
        candidates = (
            date(d.year, 4, 1),
            date(d.year, 7, 1),
            date(d.year, 10, 1),
            date(d.year + 1, 1, 1),
        )
    elif frequency_months == 12:
        candidates = (date(d.year + 1, 1, 1),)
    else:
        raise ValueError(f"OD_TIME_01_UNSUPPORTED_FREQUENCY_MONTHS: {frequency_months!r}")
    for c in candidates:
        if c > d:
            return c
    return date(d.year + 1, 1, 1)


def build_contractual_reporting_axis(
    cod: date,
    horizon_years: int,
    *,
    frequency_months: int = 6,
    first_period_index: int = 1,
) -> tuple[ContractualReportingPeriod, ...]:
    """Build canonical half-open reporting periods covering ``[cod, cod + N years)``.

    Guarantees:
    - Exact first stub if COD is not on a reporting boundary (COD day included).
    - Exact final stub if horizon end is not on a reporting boundary (no lost or extra days).
    - ``sum(p.days for p in periods) == (add_calendar_years(cod, horizon_years) - cod).days``.
    """
    horizon = operating_horizon_interval(cod, horizon_years)
    periods: list[ContractualReportingPeriod] = []
    cursor = horizon.start
    op_idx = 0
    while cursor < horizon.end_exclusive:
        next_b = _next_reporting_boundary_exclusive(cursor, frequency_months)
        end_exc = min(next_b, horizon.end_exclusive)
        iv = ContractualInterval(cursor, end_exc)
        is_first = op_idx == 0 and cursor not in (
            date(cursor.year, m, 1) for m in range(1, 13, frequency_months)
        )
        is_final = end_exc == horizon.end_exclusive and end_exc not in (
            date(end_exc.year, m, 1) for m in range(1, 13, frequency_months)
        )
        periods.append(
            ContractualReportingPeriod(
                index=first_period_index + op_idx,
                operating_period_index=op_idx,
                interval=iv,
                is_first_stub=is_first,
                is_final_stub=is_final,
                calendar_year_slices=split_by_calendar_years(iv),
            )
        )
        cursor = end_exc
        op_idx += 1
    return tuple(periods)


def reconcile_subperiods_to_reporting_axis(
    subperiods: Sequence[ContractualInterval],
    reporting_period: ContractualInterval,
) -> dict[str, object]:
    """Verify that ``subperiods`` partition ``reporting_period`` with zero gaps/overlaps."""
    if not subperiods:
        raise ValueError("OD_TIME_01_EMPTY_SUBPERIODS")
    ordered = sorted(subperiods, key=lambda iv: iv.start)
    if ordered[0].start != reporting_period.start:
        raise ValueError(
            f"OD_TIME_01_SUBPERIOD_START_MISMATCH: {ordered[0].start} != {reporting_period.start}"
        )
    if ordered[-1].end_exclusive != reporting_period.end_exclusive:
        raise ValueError(
            f"OD_TIME_01_SUBPERIOD_END_MISMATCH: {ordered[-1].end_exclusive} != {reporting_period.end_exclusive}"
        )
    for i in range(len(ordered) - 1):
        if ordered[i].end_exclusive != ordered[i + 1].start:
            raise ValueError(
                f"OD_TIME_01_SUBPERIOD_GAP_OR_OVERLAP: "
                f"{ordered[i].end_exclusive} != {ordered[i + 1].start}"
            )
    total_days = sum(iv.days for iv in ordered)
    if total_days != reporting_period.days:
        raise ValueError(
            f"OD_TIME_01_SUBPERIOD_DAY_CONSERVATION_FAILED: {total_days} != {reporting_period.days}"
        )
    return {
        "reporting_start": reporting_period.start.isoformat(),
        "reporting_end_exclusive": reporting_period.end_exclusive.isoformat(),
        "reporting_days": reporting_period.days,
        "subperiod_count": len(ordered),
        "reconciled": True,
    }


def _cod_anniversary_cuts(cod: date, interval: ContractualInterval) -> list[date]:
    cuts: list[date] = []
    k = max(1, interval.start.year - cod.year)
    while True:
        ann = add_calendar_years(cod, k)
        if ann >= interval.end_exclusive:
            break
        if ann > interval.start:
            cuts.append(ann)
        k += 1
    return cuts


@dataclass(frozen=True)
class GenerationSubperiodResult:
    interval: ContractualInterval
    calendar_year: int
    operating_year: int
    days: int
    year_days: int
    day_fraction: Fraction
    degradation_factor: float
    generation_mwh: float


def contractual_generation_for_interval(
    interval: ContractualInterval,
    *,
    cod: date,
    capacity_mw: float,
    annual_hours: float,
    combined_availability: float,
    annual_degradation: float,
    horizon_end_exclusive: date | None = None,
) -> tuple[float, tuple[GenerationSubperiodResult, ...]]:
    """Compute OD-TIME-01 generation (MWh) for ``interval`` with exact subperiod splitting.

    - Clips to ``[cod, horizon_end_exclusive)`` if ``horizon_end_exclusive`` is supplied.
    - Splits at Jan 1 boundaries (365/366 denominator) and COD anniversaries (degradation step).
    - Never double-applies availability, degradation, or day fraction.
    """
    active = interval
    if horizon_end_exclusive is not None:
        horizon_iv = ContractualInterval(cod, horizon_end_exclusive)
        active = intersect_intervals(interval, horizon_iv)
        if active is None:
            return 0.0, ()
    elif interval.end_exclusive <= cod:
        return 0.0, ()
    elif interval.start < cod:
        active = ContractualInterval(cod, interval.end_exclusive)

    jan1_cuts = [date(y, 1, 1) for y in range(active.start.year + 1, active.end_exclusive.year + 1)]
    ann_cuts = _cod_anniversary_cuts(cod, active)
    subs = split_at_dates(active, (*jan1_cuts, *ann_cuts))

    base_annual_mwh = capacity_mw * annual_hours * combined_availability
    results: list[GenerationSubperiodResult] = []
    total_mwh = 0.0
    for sub in subs:
        yr = sub.start.year
        yd = days_in_calendar_year(yr)
        frac = Fraction(sub.days, yd)
        op_yr = operating_year_index(cod, sub.start)
        deg_factor = (1.0 - annual_degradation) ** (op_yr - 1)
        mwh = base_annual_mwh * float(frac) * deg_factor
        total_mwh += mwh
        results.append(
            GenerationSubperiodResult(
                interval=sub,
                calendar_year=yr,
                operating_year=op_yr,
                days=sub.days,
                year_days=yd,
                day_fraction=frac,
                degradation_factor=deg_factor,
                generation_mwh=mwh,
            )
        )
    return total_mwh, tuple(results)


def contractual_opex_for_interval(
    interval: ContractualInterval,
    *,
    cod: date,
    items: Sequence[OpexItem],
    clock: OpexInflationClock = OpexInflationClock.COD_ANNIVERSARY,
    horizon_end_exclusive: date | None = None,
) -> float:
    """Compute OD-TIME-01 OPEX (kEUR) for ``interval`` with explicit escalation clock.

    - ``OpexInflationClock.COD_ANNIVERSARY`` (default): escalation & steps advance on exact COD anniversaries.
    - ``OpexInflationClock.CALENDAR_YEAR``: escalation & steps advance on Jan 1 of each calendar year.
    - Subperiod weights use exact ``days / (365|366)`` per calendar year.
    """
    from finco_core.opex.projections import opex_year

    active = interval
    if horizon_end_exclusive is not None:
        active = intersect_intervals(interval, ContractualInterval(cod, horizon_end_exclusive))
        if active is None:
            return 0.0
    elif interval.end_exclusive <= cod:
        return 0.0
    elif interval.start < cod:
        active = ContractualInterval(cod, interval.end_exclusive)

    jan1_cuts = [date(y, 1, 1) for y in range(active.start.year + 1, active.end_exclusive.year + 1)]
    cuts = (*jan1_cuts, *_cod_anniversary_cuts(cod, active)) if clock == OpexInflationClock.COD_ANNIVERSARY else jan1_cuts
    subs = split_at_dates(active, cuts)

    total_keur = 0.0
    for sub in subs:
        yr = sub.start.year
        yd = days_in_calendar_year(yr)
        frac = float(Fraction(sub.days, yd))
        if clock == OpexInflationClock.COD_ANNIVERSARY:
            step_yr = operating_year_index(cod, sub.start)
        else:
            step_yr = max(1, yr - cod.year + 1)
        total_keur += opex_year(items, step_yr) * frac
    return total_keur


@dataclass(frozen=True)
class ContractualPpaSliceResult:
    interval: ContractualInterval
    is_ppa_active: bool
    escalation_count: int
    ppa_tariff_eur_mwh: float
    generation_mwh: float
    ppa_mwh: float
    merchant_mwh: float
    ppa_revenue_keur: float
    merchant_revenue_keur: float


def contractual_ppa_and_merchant_for_interval(
    interval: ContractualInterval,
    *,
    cod: date,
    capacity_mw: float,
    annual_hours: float,
    combined_availability: float,
    annual_degradation: float,
    ppa_base_tariff_eur_mwh: float,
    ppa_index: float,
    ppa_share: float,
    ppa_policy,
    contract_start: date,
    contract_end_exclusive: date,
    market_price_by_year: dict[int, float],
    ppa_indexation_start_date: date | None = None,
    horizon_end_exclusive: date | None = None,
) -> tuple[dict[str, float], tuple[ContractualPpaSliceResult, ...]]:
    """Compute OD-TIME-01 PPA & merchant energy revenue for ``interval`` with exact subperiod splitting.

    Handles:
    - Exact contract start and expiry dates ``[contract_start, contract_end_exclusive)``;
      days ``>= contract_end_exclusive`` settle 100% merchant with zero PPA leakage.
    - Independent PPA indexation clocks:
      - ``FIRST_FULL_CALENDAR_YEAR_AS_BASE`` (C14A): steps on Jan 1 after base year.
      - ``AFTER_FIRST_FULL_OPERATING_YEAR`` (C14B): steps on exact COD anniversaries.
      - ``CONTRACT_ANNIVERSARY``: steps on exact ``ppa_indexation_start_date`` anniversaries.
    - Exact calendar-year market price lookup per subperiod.
    """
    from financial_engine.ppa_indexation import (
        PpaIndexationStartPolicy,
        count_ppa_escalation_events,
    )

    policy_enum = (
        ppa_policy
        if isinstance(ppa_policy, PpaIndexationStartPolicy)
        else PpaIndexationStartPolicy(str(ppa_policy))
    )
    _require_date_only(contract_start, "contract_start")
    _require_date_only(contract_end_exclusive, "contract_end_exclusive")
    if contract_end_exclusive < contract_start:
        raise ValueError("OD_TIME_01_CONTRACT_END_BEFORE_START")
    if policy_enum == PpaIndexationStartPolicy.CONTRACT_ANNIVERSARY and ppa_indexation_start_date is None:
        raise ValueError("OD_TIME_01_CONTRACT_ANNIVERSARY_START_DATE_REQUIRED")

    active = interval
    if horizon_end_exclusive is not None:
        active = intersect_intervals(interval, ContractualInterval(cod, horizon_end_exclusive))
        if active is None:
            return {
                "generation_mwh": 0.0,
                "ppa_mwh": 0.0,
                "merchant_mwh": 0.0,
                "ppa_revenue_keur": 0.0,
                "merchant_revenue_keur": 0.0,
                "energy_revenue_keur": 0.0,
            }, ()
    elif interval.end_exclusive <= cod:
        return {
            "generation_mwh": 0.0,
            "ppa_mwh": 0.0,
            "merchant_mwh": 0.0,
            "ppa_revenue_keur": 0.0,
            "merchant_revenue_keur": 0.0,
            "energy_revenue_keur": 0.0,
        }, ()
    elif interval.start < cod:
        active = ContractualInterval(cod, interval.end_exclusive)

    cut_dates: list[date] = [
        *(date(y, 1, 1) for y in range(active.start.year + 1, active.end_exclusive.year + 1)),
        *_cod_anniversary_cuts(cod, active),
        contract_start,
        contract_end_exclusive,
    ]
    if policy_enum == PpaIndexationStartPolicy.CONTRACT_ANNIVERSARY and ppa_indexation_start_date is not None:
        cut_dates.extend(_cod_anniversary_cuts(ppa_indexation_start_date, active))

    subs = split_at_dates(active, cut_dates)
    bounded_share = min(max(float(ppa_share), 0.0), 1.0)
    base_annual_mwh = capacity_mw * annual_hours * combined_availability

    slices: list[ContractualPpaSliceResult] = []
    tot_gen = tot_ppa_mwh = tot_merch_mwh = tot_ppa_rev = tot_merch_rev = 0.0

    for sub in subs:
        yr = sub.start.year
        yd = days_in_calendar_year(yr)
        frac = float(Fraction(sub.days, yd))
        op_yr = operating_year_index(cod, sub.start)
        deg = (1.0 - annual_degradation) ** (op_yr - 1)
        mwh = base_annual_mwh * frac * deg

        is_ppa = contract_start <= sub.start and sub.end_exclusive <= contract_end_exclusive and bounded_share > 0.0
        if is_ppa:
            esc = count_ppa_escalation_events(
                policy_enum,
                cod=cod,
                period_end=sub.start,
                ppa_indexation_start_date=ppa_indexation_start_date,
            )
            tariff = ppa_base_tariff_eur_mwh * ((1.0 + ppa_index) ** esc)
            ppa_mwh = mwh * bounded_share
            merch_mwh = mwh - ppa_mwh
        else:
            esc = 0
            tariff = 0.0
            ppa_mwh = 0.0
            merch_mwh = mwh

        if merch_mwh > 0.0:
            if yr not in market_price_by_year:
                raise ValueError(
                    f"MERCHANT_PRICE_COVERAGE_MISSING: calendar year {yr} has positive merchant volume "
                    f"({merch_mwh:.4f} MWh) but no explicit merchant price."
                )
            mkt_price = float(market_price_by_year[yr])
        else:
            mkt_price = float(market_price_by_year.get(yr, 0.0))

        ppa_rev = ppa_mwh * tariff / 1000.0
        merch_rev = merch_mwh * mkt_price / 1000.0

        tot_gen += mwh
        tot_ppa_mwh += ppa_mwh
        tot_merch_mwh += merch_mwh
        tot_ppa_rev += ppa_rev
        tot_merch_rev += merch_rev

        slices.append(
            ContractualPpaSliceResult(
                interval=sub,
                is_ppa_active=is_ppa,
                escalation_count=esc,
                ppa_tariff_eur_mwh=tariff,
                generation_mwh=mwh,
                ppa_mwh=ppa_mwh,
                merchant_mwh=merch_mwh,
                ppa_revenue_keur=ppa_rev,
                merchant_revenue_keur=merch_rev,
            )
        )

    summary = {
        "generation_mwh": tot_gen,
        "ppa_mwh": tot_ppa_mwh,
        "merchant_mwh": tot_merch_mwh,
        "ppa_revenue_keur": tot_ppa_rev,
        "merchant_revenue_keur": tot_merch_rev,
        "energy_revenue_keur": tot_ppa_rev + tot_merch_rev,
    }
    return summary, tuple(slices)


@dataclass(frozen=True)
class ContractualDepreciationSummary:
    period_depreciation_keur: dict[int, float]
    closing_carrying_value_by_asset_keur: dict[str, float]
    total_depreciable_basis_keur: float
    total_depreciation_keur: float
    total_closing_carrying_value_keur: float


def contractual_depreciation_schedule(
    capex_items: Sequence[CapexItem],
    *,
    cod: date,
    reporting_periods: Sequence[ContractualReportingPeriod],
    senior_tenor_years: int = 14,
) -> ContractualDepreciationSummary:
    """Straight-line accounting depreciation over actual asset in-service life (OD-TIME-01).

    For each depreciable asset with useful life ``L`` years:
    - In-service interval is ``[cod, add_calendar_years(cod, L))`` with total days ``D_life``.
    - Each reporting period overlapping the in-service interval by ``d_overlap`` days receives
      ``basis * (d_overlap / D_life)``.
    - Single final residual rounding on the final active in-service period when the asset's
      life completes within the reporting horizon, guaranteeing cumulative depreciation equals
      depreciable basis exactly (never below zero or above depreciable basis).
    - Assets with useful life beyond the operating horizon retain legitimate positive carrying value.
    """
    per_period: dict[int, float] = {p.index: 0.0 for p in reporting_periods}
    closing_by_asset: dict[str, float] = {}
    total_basis = 0.0
    total_dep = 0.0

    for item in capex_items:
        basis = float(item.amount_keur)
        if basis <= 0.0:
            closing_by_asset[item.name] = 0.0
            continue
        if item.asset_class == AssetClass.FINANCIAL_COSTS and item.useful_life_override is None:
            life = int(senior_tenor_years)
        elif item.useful_life_override is not None:
            life = int(item.useful_life_override)
        else:
            life = int(ASSET_CLASS_USEFUL_LIFE.get(item.asset_class, 14))

        if life <= 0:
            # Non-depreciable asset (e.g. land): retains full carrying value
            total_basis += basis
            closing_by_asset[item.name] = basis
            continue

        life_iv = ContractualInterval(cod, add_calendar_years(cod, life))
        d_life = life_iv.days
        total_basis += basis

        overlaps: list[tuple[int, int]] = []
        for p in reporting_periods:
            ov = intersect_intervals(p.interval, life_iv)
            if ov is not None:
                overlaps.append((p.index, ov.days))

        covered_days = sum(d for _, d in overlaps)
        completes_within_horizon = covered_days == d_life

        cumulative_item_dep = 0.0
        for pos, (p_idx, d_ov) in enumerate(overlaps):
            is_last_overlap = pos == len(overlaps) - 1
            if completes_within_horizon and is_last_overlap:
                dep = max(0.0, basis - cumulative_item_dep)
            else:
                dep = basis * (d_ov / d_life)
                if cumulative_item_dep + dep > basis:
                    dep = max(0.0, basis - cumulative_item_dep)
            per_period[p_idx] += dep
            cumulative_item_dep += dep

        total_dep += cumulative_item_dep
        closing_by_asset[item.name] = max(0.0, basis - cumulative_item_dep)

    return ContractualDepreciationSummary(
        period_depreciation_keur=per_period,
        closing_carrying_value_by_asset_keur=closing_by_asset,
        total_depreciable_basis_keur=total_basis,
        total_depreciation_keur=total_dep,
        total_closing_carrying_value_keur=sum(closing_by_asset.values()),
    )


__all__ = [
    "CALENDAR_CONTRACT_VERSION",
    "LEGACY_CALENDAR_COMPATIBILITY_PROVENANCE",
    "OpexInflationClock",
    "ContractualInterval",
    "CalendarYearSlice",
    "ContractualReportingPeriod",
    "GenerationSubperiodResult",
    "ContractualPpaSliceResult",
    "ContractualDepreciationSummary",
    "days_in_calendar_year",
    "add_calendar_years",
    "operating_horizon_interval",
    "convert_legacy_inclusive_range",
    "convert_period_meta_to_half_open",
    "intersect_intervals",
    "split_at_dates",
    "split_by_calendar_years",
    "operating_year_index",
    "build_contractual_reporting_axis",
    "reconcile_subperiods_to_reporting_axis",
    "contractual_generation_for_interval",
    "contractual_opex_for_interval",
    "contractual_ppa_and_merchant_for_interval",
    "contractual_depreciation_schedule",
]
