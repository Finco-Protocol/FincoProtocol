"""financial_engine.dsra.forward_coverage — calendar-based forward Cash DSRA requirement (FIN-V2-R1).

Policy version ``FORWARD_CALENDAR_COVERAGE_V1``. Pure computation: no app, workbook or engine
imports, no project-identity dispatch, no Senior sizing. It consumes the FINAL Senior debt service
schedule and the canonical period dates and returns the reserve that must be held on each test date
to cover the next ``coverage_months`` CALENDAR months of Senior debt service.

This replaces, for the new versioned policy only, the historical shortcut
``next_period_service * coverage_months * periods_per_year / 12`` (kept unchanged in
``financial_engine.dsra.target`` as ``SHORTCUT_V0``), which equals the true requirement only when all
future periods carry equal debt service and the coverage is a whole number of periods.

Convention (documented, explicit, never defaulted)
--------------------------------------------------
Period ``j`` spans the boundary dates ``(start_j, end_j]`` and its Senior debt service falls DUE on
``end_j`` (the model books debt service at period end). A requirement is measured on a TEST DATE ``T``:
the end of each operating period, plus the COD date (end of the last construction period) for the
initial funding requirement. The coverage window is ``(T, W]`` with
``W = T + coverage_months`` calendar months (end-of-month preserving: if ``T`` is the last day of its
month, ``W`` is the last day of the target month, so 31-Dec + 6m = 30-Jun and 30-Jun + 6m = 31-Dec).

* ``DUE_DATE_WINDOW``: a payment is covered in FULL iff its due date ``end_j`` lies in ``(T, W]``. This
  reserves exactly the contractual payments that fall due inside the window. 9 months of semiannual
  payments therefore cover ONE payment (the next), because the following one is due at month 12.
* ``PRORATED_PERIOD``: each future period contributes its debt service times the share of its days
  that overlap the window, ``days((start_j, end_j] ∩ (T, W]) / days((start_j, end_j])``. 9 months of
  semiannual payments cover one full next period and about half of the following one. This is a
  smoothed liquidity convention: it does NOT claim the prorated amount is contractually due inside the
  window, and it is therefore never selected implicitly.

Neither convention is the product default: the caller must name one. FORWARD is the requirement on each
test date. PEAK_FORWARD is the maximum FORWARD requirement over all test dates, held while any further
Senior debt service is due after the test date and released (0) afterwards.

Fail-closed behaviour
---------------------
Unavailable data is never reported as zero. A requirement is ``None`` with a typed status when a
future debt-service period needed by the window is missing, or when the window reaches beyond the
supplied schedule and no contractual maturity proves that no later payment exists. A zero requirement
is reported only with status ``NO_FURTHER_DEBT_SERVICE`` (all covered debt service is genuinely zero:
zero Senior debt, early actual extinguishment, or after the final Senior payment).
"""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Optional, Sequence

POLICY_VERSION = "FORWARD_CALENDAR_COVERAGE_V1"


class CoverageConvention(Enum):
    DUE_DATE_WINDOW = "due_date_window"
    PRORATED_PERIOD = "prorated_period"


class ReserveRequirementKind(Enum):
    FORWARD = "forward"
    PEAK_FORWARD = "peak_forward"


class CoverageStatus(Enum):
    COMPUTED = "COMPUTED"
    NO_FURTHER_DEBT_SERVICE = "NO_FURTHER_DEBT_SERVICE"
    FUTURE_DEBT_SERVICE_MISSING = "FUTURE_DEBT_SERVICE_MISSING"
    BEYOND_SCHEDULE_UNPROVEN_MATURITY = "BEYOND_SCHEDULE_UNPROVEN_MATURITY"


_UNAVAILABLE = frozenset({
    CoverageStatus.FUTURE_DEBT_SERVICE_MISSING,
    CoverageStatus.BEYOND_SCHEDULE_UNPROVEN_MATURITY,
})


def add_months_eom(d: date, months: int) -> date:
    """Calendar month addition; end-of-month dates stay end-of-month, other days clamp to month end."""
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    is_eom = d.day == calendar.monthrange(d.year, d.month)[1]
    return date(year, month, last if is_eom else min(d.day, last))


@dataclass(frozen=True)
class CoveredPayment:
    period_index: int
    due_date: date
    debt_service_keur: float
    covered_fraction: float
    covered_keur: float


@dataclass(frozen=True)
class CoverageRow:
    """Requirement on one test date. ``required_keur`` is None iff the status is unavailable."""
    test_period_index: int
    test_date: date
    window_end: date
    is_cod_test: bool
    status: CoverageStatus
    required_keur: Optional[float]
    payments: tuple[CoveredPayment, ...]


@dataclass(frozen=True)
class ForwardCoverageResult:
    policy_version: str
    convention: CoverageConvention
    coverage_months: int
    rows: tuple[CoverageRow, ...]
    # PEAK_FORWARD: None whenever any test date is unavailable (a peak over missing data is unknown).
    peak_required_keur: Optional[float]
    peak_test_date: Optional[date]
    peak_status: CoverageStatus
    peak_held_schedule_keur: tuple[Optional[float], ...]

    def required_schedule(self, kind: ReserveRequirementKind) -> tuple[Optional[float], ...]:
        if kind is ReserveRequirementKind.FORWARD:
            return tuple(r.required_keur for r in self.rows)
        return self.peak_held_schedule_keur


def _check_number(name: str, i: int, value, *, allow_none: bool) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"DSRA_COVERAGE_INVALID_SENIOR_DS: {name}[{i}]={value!r} must be numeric.")
    if not math.isfinite(value):
        raise ValueError(f"DSRA_COVERAGE_INVALID_SENIOR_DS: {name}[{i}]={value!r} must be finite.")
    if value < 0.0:
        raise ValueError(
            f"DSRA_COVERAGE_NEGATIVE_SENIOR_DS: {name}[{i}]={value!r} is negative; "
            "Senior debt service must be an unsigned cash outflow.")


def compute_forward_coverage(
    *,
    period_indices: Sequence[int],
    period_start_dates: Sequence[date],
    period_end_dates: Sequence[date],
    is_construction: Sequence[bool],
    senior_debt_service_keur: Sequence[Optional[float]],
    coverage_months: int,
    convention: CoverageConvention,
    senior_maturity_date: Optional[date] = None,
) -> ForwardCoverageResult:
    """Calendar-based FORWARD and PEAK_FORWARD requirement schedule. See the module docstring.

    ``senior_debt_service_keur[k] is None`` marks a period whose debt service is UNKNOWN (missing);
    ``0.0`` means no payment is due. ``senior_maturity_date`` is the contractual final Senior payment
    date; when supplied, it proves that nothing falls due after it, so a window may extend past the
    supplied schedule up to that date without being "missing".
    """
    n = len(period_indices)
    for name, seq in (("period_start_dates", period_start_dates), ("period_end_dates", period_end_dates),
                      ("is_construction", is_construction), ("senior_debt_service_keur", senior_debt_service_keur)):
        if len(seq) != n:
            raise ValueError(f"DSRA_COVERAGE_LENGTH_MISMATCH: {name} length {len(seq)} != period_indices length {n}.")
    if not isinstance(convention, CoverageConvention):
        raise ValueError("DSRA_COVERAGE_CONVENTION_REQUIRED: an explicit CoverageConvention must be supplied.")
    if isinstance(coverage_months, bool) or not isinstance(coverage_months, int) or coverage_months <= 0:
        raise ValueError(f"DSRA_COVERAGE_INVALID_COVERAGE_MONTHS: {coverage_months!r} must be an integer > 0.")
    if len(set(period_indices)) != n:
        raise ValueError("DSRA_COVERAGE_DUPLICATE_PERIOD_INDICES: period_indices contains duplicates.")
    for i, (s, e) in enumerate(zip(period_start_dates, period_end_dates)):
        if not (isinstance(s, date) and isinstance(e, date)):
            raise ValueError(f"DSRA_COVERAGE_INVALID_DATES: period {i} dates must be datetime.date.")
        if e <= s:
            raise ValueError(f"DSRA_COVERAGE_INVALID_DATES: period_end_dates[{i}] ({e}) <= start ({s}).")
        if i and period_end_dates[i] <= period_end_dates[i - 1]:
            raise ValueError(f"DSRA_COVERAGE_NON_CHRONOLOGICAL_PERIODS: period_end_dates[{i}] is not ascending.")
        if i and period_start_dates[i] < period_end_dates[i - 1]:
            raise ValueError(f"DSRA_COVERAGE_OVERLAPPING_PERIODS: period {i} starts before period {i - 1} ends.")
    for i, v in enumerate(senior_debt_service_keur):
        _check_number("senior_debt_service_keur", i, v, allow_none=True)
    if senior_maturity_date is not None:
        if not isinstance(senior_maturity_date, date):
            raise ValueError("DSRA_COVERAGE_INVALID_MATURITY: senior_maturity_date must be datetime.date.")
        for i in range(n):
            ds = senior_debt_service_keur[i]
            if ds and ds > 0.0 and period_end_dates[i] > senior_maturity_date:
                raise ValueError(
                    f"DSRA_COVERAGE_DEBT_SERVICE_AFTER_MATURITY: period {period_indices[i]} carries debt "
                    f"service due {period_end_dates[i]} after contractual maturity {senior_maturity_date}.")

    last_end = period_end_dates[-1] if n else None
    test_positions: list[tuple[int, date, bool]] = []
    for i in range(n):
        if is_construction[i]:
            if i + 1 < n and not is_construction[i + 1]:
                test_positions.append((i, period_end_dates[i], True))
        else:
            test_positions.append((i, period_end_dates[i], False))

    rows: list[CoverageRow] = []
    for pos, test_date, is_cod in test_positions:
        window_end = add_months_eom(test_date, coverage_months)
        # Periods that can contribute: due after T and (for proration) overlapping the window.
        involved = [j for j in range(n) if not is_construction[j] and period_end_dates[j] > test_date
                    and (period_start_dates[j] < window_end)]
        status = CoverageStatus.COMPUTED
        payments: list[CoveredPayment] = []
        total = 0.0
        # Beyond-schedule check: the schedule must prove completeness up to the window end.
        horizon = window_end if senior_maturity_date is None else min(window_end, senior_maturity_date)
        if last_end is None or horizon > last_end:
            status = CoverageStatus.BEYOND_SCHEDULE_UNPROVEN_MATURITY
        for j in involved:
            ds = senior_debt_service_keur[j]
            if convention is CoverageConvention.DUE_DATE_WINDOW:
                fraction = 1.0 if test_date < period_end_dates[j] <= window_end else 0.0
            else:
                span = (period_end_dates[j] - period_start_dates[j]).days
                lo = max(period_start_dates[j], test_date)
                hi = min(period_end_dates[j], window_end)
                overlap = (hi - lo).days
                fraction = 0.0 if overlap <= 0 else overlap / span if span > 0 else 0.0
                fraction = min(fraction, 1.0)
            if fraction == 0.0:
                continue
            if ds is None:
                status = CoverageStatus.FUTURE_DEBT_SERVICE_MISSING
                continue
            covered = ds * fraction
            total += covered
            payments.append(CoveredPayment(period_indices[j], period_end_dates[j], float(ds), fraction, covered))
        if status in _UNAVAILABLE:
            rows.append(CoverageRow(period_indices[pos], test_date, window_end, is_cod, status, None, tuple(payments)))
            continue
        if total <= 0.0:
            status = CoverageStatus.NO_FURTHER_DEBT_SERVICE
            total = 0.0
        rows.append(CoverageRow(period_indices[pos], test_date, window_end, is_cod, status, total, tuple(payments)))

    unavailable = [r for r in rows if r.status in _UNAVAILABLE]
    if unavailable:
        peak, peak_date, peak_status = None, None, unavailable[0].status
        held: tuple[Optional[float], ...] = tuple(None for _ in rows)
    else:
        peak, peak_date = 0.0, None
        for r in rows:
            if r.required_keur is not None and r.required_keur > peak:
                peak, peak_date = r.required_keur, r.test_date
        peak_status = CoverageStatus.COMPUTED if rows and peak > 0.0 else CoverageStatus.NO_FURTHER_DEBT_SERVICE
        held = tuple(peak if (r.required_keur or 0.0) > 0.0 else 0.0 for r in rows)
    return ForwardCoverageResult(POLICY_VERSION, convention, coverage_months, tuple(rows),
                                 peak, peak_date, peak_status, held)
