"""Period Engine: transforms financial close date into a sequence of dated periods.

This module establishes the temporal axis for all financial calculations.
It generates period metadata (start/end dates, year indices, flags) matching
the structure of the Excel CF sheets.

FINCO Model calibration note:
- Excel semi-annual models use period-end to period-end day counts for operating
  rows, not inclusive calendar-day counts.
- Near-zero COD stubs at June 30 / Dec 31 are rolled into the next meaningful
  operating period.
- Generic Solar Reference COD 2030-06-29 therefore produces first operating period ending
  2030-12-31 with 184 days (2030-06-30 to 2030-12-31).
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, List, Sequence
from dateutil.relativedelta import relativedelta
import calendar

from finco_core.engine.calendar_policy import OperatingCalendarPolicy


class PeriodFrequency(Enum):
    """Frequency of periods within a year."""
    ANNUAL = 1
    SEMESTRIAL = 2
    QUARTERLY = 4


class PeriodAxisConvention(str, Enum):
    """Explicit policy for construction and operating-period boundary semantics."""
    COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS = "cod_anchor_two_construction_columns"
    OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN = "operating_boundary_single_construction_column"


@dataclass(frozen=True)
class PeriodMeta:
    """Immutable metadata for a single period."""
    index: int
    start_date: date
    end_date: date
    year_index: int
    period_in_year: int
    is_construction: bool
    is_operation: bool
    is_ppa_active: bool
    days_in_period: int
    day_fraction: float
    is_leap_year: bool
    # Derived operating-period counters. Construction periods keep defaults.
    operating_period_index: int = -1
    operating_year_index: int = 0


def semiannual_boundary_after(d: date) -> date:
    """The next Jun 30 / Dec 31 STRICTLY after ``d`` (the released six-month row boundary)."""
    jun_30, dec_31 = date(d.year, 6, 30), date(d.year, 12, 31)
    if d < jun_30:
        return jun_30
    if d < dec_31:
        return dec_31
    return date(d.year + 1, 6, 30)


def semiannual_row_ends(start: date, rows: int) -> tuple[date, ...]:
    """End dates of the first ``rows`` rows of the released six-month operating axis that starts at ``start``.

    The first row (the stub) ends at the next Jun 30 / Dec 31 after ``start``; every following row is one more six-month step. This is the
    DATE authority the date-authoritative quarterly policy (RC-7C v2) preserves for the economic horizon, model years and Senior maturity.
    """
    if type(rows) is not int or rows < 0:
        raise ValueError("PERIOD_AXIS_SEMIANNUAL_ROWS_INVALID")
    ends: list[date] = []
    current = start
    for _ in range(rows):
        current = semiannual_boundary_after(current)
        ends.append(current)
    return tuple(ends)


class PeriodEngine:
    """Generates period sequence from financial close to end of horizon."""

    def __init__(
        self,
        financial_close: date,
        construction_months: int,
        horizon_years: int,
        ppa_years: int,
        frequency: PeriodFrequency = PeriodFrequency.SEMESTRIAL,
        cod_date: date | None = None,
        period_axis_convention: PeriodAxisConvention | str = (
            PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS
        ),
        operating_calendar_policy: OperatingCalendarPolicy | None = None,
        economic_end_date: date | None = None,
    ) -> None:
        self.fc = financial_close
        self.construction_months = construction_months
        self.horizon_years = horizon_years
        self.ppa_years = ppa_years
        self.freq = self._coerce_frequency(frequency)
        self.period_axis_convention = self._coerce_period_axis_convention(
            period_axis_convention
        )
        derived_cod = self._add_months(financial_close, construction_months)
        if cod_date is not None and cod_date != derived_cod:
            raise ValueError(
                "PERIOD_AXIS_COD_MISMATCH: explicit cod_date "
                f"{cod_date.isoformat()} != financial_close + construction_months "
                f"{derived_cod.isoformat()}"
            )
        self._cod = cod_date or derived_cod
        self._operating_calendar_policy: OperatingCalendarPolicy | None = None
        if operating_calendar_policy is not None:
            # RC-7B matched 3/3 candidate: explicit typed policy only. The
            # released six-month path below is never entered with a policy.
            self._operating_calendar_policy = self._require_quarterly_policy(
                operating_calendar_policy
            )
            self._operating_start = self._cod
        else:
            self._operating_start = self._last_semiannual_end_on_or_after_cod()
        self._periods_per_year = self.freq.value
        if self.freq != PeriodFrequency.SEMESTRIAL and self._operating_calendar_policy is None:
            raise ValueError(
                "PERIOD_AXIS_FREQUENCY_UNSUPPORTED: canonical runtime axis currently "
                "requires SEMESTRIAL frequency"
            )
        if isinstance(horizon_years, bool) or int(horizon_years) != horizon_years or horizon_years <= 0:
            raise ValueError("PERIOD_AXIS_HORIZON_INVALID: horizon_years must be a positive integer")
        if ppa_years < 0:
            raise ValueError("PERIOD_AXIS_PPA_TERM_INVALID: ppa_years must be >= 0")
        self._economic_end_date = None
        self._explicit_economic_end = economic_end_date
        if economic_end_date is not None and not (
                self._operating_calendar_policy is not None and self._operating_calendar_policy.date_authoritative):
            raise ValueError(
                "PERIOD_AXIS_ECONOMIC_END_DATE_REQUIRES_DATE_AUTHORITATIVE_POLICY: an explicit economic end date is defined "
                "only for the date-authoritative quarterly candidate; the released six-month axis is unchanged")
        if self._operating_calendar_policy is not None and self._operating_calendar_policy.date_authoritative:
            # RC-7C v2 (D-03): the economic end date is the end of the equivalent six-month horizon; quarterly rows only subdivide it.
            equivalent_end = semiannual_row_ends(self._operating_start, 2 * int(horizon_years))[-1]
            if economic_end_date is None:
                self._economic_end_date = equivalent_end
            else:
                # An explicit end date (for example a contractual anniversary of a NEW project) must lie inside the final model year, so every annual
                # input array (degradation, indexation, depreciation, OPEX) keeps its length; the last row is then a properly dated stub.
                if type(economic_end_date) is not date:
                    raise ValueError("PERIOD_AXIS_ECONOMIC_END_DATE_INVALID: a datetime.date is required")
                year_start = (semiannual_row_ends(self._operating_start, 2 * int(horizon_years) - 2)[-1]
                              if int(horizon_years) > 1 else self._operating_start)
                if not (year_start < economic_end_date <= equivalent_end):
                    raise ValueError(
                        "PERIOD_AXIS_ECONOMIC_END_DATE_OUTSIDE_FINAL_MODEL_YEAR: "
                        f"{economic_end_date.isoformat()} is not in ({year_start.isoformat()}, {equivalent_end.isoformat()}]")
                self._economic_end_date = economic_end_date
            count, cursor = 0, self._operating_start
            while cursor < self._economic_end_date:
                cursor = min(self._next_quarter_end_after(cursor), self._economic_end_date)
                count += 1
            self._operating_period_count = count
        else:
            self._operating_period_count = int(horizon_years) * self._periods_per_year
        ppa_anchor = (
            self._operating_start
            if self.period_axis_convention
            == PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN
            else self._cod
        )
        self._ppa_end = self._add_years(ppa_anchor, ppa_years)
        self._periods = self._build_periods()
        validate_canonical_period_axis(
            self._periods,
            expected_operating_periods=self._operating_period_count,
            cod_date=self._cod,
            period_convention=self.period_axis_convention,
            periods_per_year=self._periods_per_year,
            year_alignment=self.year_alignment,
            expected_economic_end=self._economic_end_date,
        )
        self._horizon_end = self._periods[-1].end_date

    def _require_quarterly_policy(self, policy: object) -> OperatingCalendarPolicy:
        """Fail closed unless frequency, policy and project dates admit matched 3/3."""
        if type(policy) is not OperatingCalendarPolicy:
            raise ValueError("QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED")
        if self.freq != PeriodFrequency.QUARTERLY or policy.periods_per_year != 4:
            raise ValueError(
                "QUARTERLY_POLICY_FREQUENCY_MISMATCH: an operating calendar policy "
                f"requires QUARTERLY frequency, got {self.freq!r}"
            )
        if self.period_axis_convention != PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS:
            raise ValueError(
                "QUARTERLY_PERIOD_AXIS_CONVENTION_UNSUPPORTED: the source-aligned "
                "next-year denominator convention has no quarterly definition (D-02)"
            )
        # D-01 boundary: where the released six-month axis would roll the
        # operating start to Jun 30 / Dec 31, the quarterly KEEP_ACTUAL_COD rule
        # would end the construction columns on a different date. Refuse rather
        # than let the operating frequency move construction dates.
        boundary = date(self._cod.year, 6, 30) if self._cod.month <= 6 else date(self._cod.year, 12, 31)
        if 0 < (boundary - self._cod).days < 7:
            raise ValueError(
                "QUARTERLY_COD_ROLL_WINDOW_PENDING_D01: COD "
                f"{self._cod.isoformat()} is within the released six-month roll window "
                f"before {boundary.isoformat()}; stub treatment awaits owner decision D-01"
            )
        return policy

    @property
    def operating_calendar_policy(self) -> OperatingCalendarPolicy | None:
        """The explicit 3/3 policy, or None for the released six-month axis."""
        return self._operating_calendar_policy

    @property
    def periods_per_year(self) -> int:
        return self._periods_per_year

    @property
    def operating_period_count(self) -> int:
        """Number of operating rows. ``horizon_years * periods_per_year`` except under the date-authoritative quarterly policy."""
        return self._operating_period_count

    @property
    def year_alignment(self) -> str:
        """``FIXED_ROWS`` (released six-month axis, quarterly v1) or ``SEMIANNUAL_ALIGNED`` (quarterly v2)."""
        policy = self._operating_calendar_policy
        return "SEMIANNUAL_ALIGNED" if policy is not None and policy.date_authoritative else "FIXED_ROWS"

    @property
    def economic_end_date(self) -> date | None:
        """The explicit economic end date under the date-authoritative policy; None where the horizon is a row count."""
        return self._economic_end_date

    def senior_maturity_end_date(self, tenor_years: int) -> date | None:
        """Date-authoritative Senior maturity (end of six-month row ``2 * tenor_years``); None where maturity is a row count."""
        if self._operating_calendar_policy is None or not self._operating_calendar_policy.date_authoritative:
            return None
        if type(tenor_years) is not int or tenor_years <= 0:
            raise ValueError("PERIOD_AXIS_TENOR_INVALID: tenor_years must be a positive integer")
        return semiannual_row_ends(self._operating_start, 2 * tenor_years)[-1]

    @property
    def operating_start(self) -> date:
        return self._operating_start

    @property
    def cod(self) -> date:
        """Commercial Operation Date (end of construction)."""
        return self._cod

    @property
    def ppa_end(self) -> date:
        """End date of PPA tariff period."""
        return self._ppa_end

    @property
    def horizon_end(self) -> date:
        """End of investment horizon."""
        return self._horizon_end

    def _add_months(self, d: date, months: int) -> date:
        """Add months to a date."""
        return d + relativedelta(months=months)

    def _add_years(self, d: date, years: float) -> date:
        """Add years (int or float) to a date. Supports fractional years like 12.5."""
        if isinstance(years, float) and not years.is_integer():
            whole = int(years)
            months = int((years - whole) * 12)
            return d + relativedelta(years=whole, months=months)
        return d + relativedelta(years=int(years))

    def _coerce_period_axis_convention(
        self,
        value: PeriodAxisConvention | str,
    ) -> PeriodAxisConvention:
        """Resolve explicit period-axis policy values."""
        if isinstance(value, PeriodAxisConvention):
            return value
        try:
            return PeriodAxisConvention(str(value))
        except ValueError as exc:
            allowed = ", ".join(v.value for v in PeriodAxisConvention)
            raise ValueError(
                f"Unknown period_axis_convention={value!r}; expected one of: {allowed}"
            ) from exc

    def _coerce_frequency(self, value: object) -> PeriodFrequency:
        """Accept the typed input enum without weakening supported frequencies."""
        if isinstance(value, PeriodFrequency):
            return value
        member_name = getattr(value, "name", None)
        if isinstance(member_name, str) and member_name in PeriodFrequency.__members__:
            return PeriodFrequency[member_name]
        try:
            return PeriodFrequency(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"PERIOD_AXIS_FREQUENCY_INVALID: {value!r}") from exc

    def _days_between(self, start: date, end: date) -> int:
        """Days between two period-boundary dates (end - start)."""
        return (end - start).days

    def _next_semiannual_end_after(self, d: date) -> date:
        """Return the next June 30 / Dec 31 date strictly after d."""
        jun_30 = date(d.year, 6, 30)
        dec_31 = date(d.year, 12, 31)
        if d < jun_30:
            return jun_30
        if d < dec_31:
            return dec_31
        return date(d.year + 1, 6, 30)

    def _last_semiannual_end_on_or_after_cod(self, threshold_days: int = 7) -> date:
        """Return starting boundary for first meaningful operating period.

        Excel rolls very short COD-to-period-end stubs into the next full-ish
        operating period. The start boundary is the nearby semi-annual end date
        when COD is within threshold days before it; otherwise COD itself.
        """
        if self._cod.month <= 6:
            boundary = date(self._cod.year, 6, 30)
        else:
            boundary = date(self._cod.year, 12, 31)
        days_to_boundary = (boundary - self._cod).days
        if 0 <= days_to_boundary < threshold_days:
            return boundary
        return self._cod

    def _semiannual_operating_denominator(self, period_end: date) -> float:
        """Reference methodology denominator for semiannual operating periods."""
        if period_end.month == 6:
            return 366.0 if calendar.isleap(period_end.year) else 365.0
        if period_end.month == 12:
            next_year = period_end.year + 1
            return 366.0 if calendar.isleap(next_year) else 365.0
        return 366.0 if calendar.isleap(period_end.year) else 365.0

    def periods(self) -> tuple[PeriodMeta, ...]:
        """Return the immutable canonical construction and operating axis."""
        return self._periods

    def _build_periods(self) -> tuple[PeriodMeta, ...]:
        if self._operating_calendar_policy is not None:
            return self._quarterly_candidate_periods()
        if self.period_axis_convention == PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN:
            return self._source_aligned_operating_boundary_periods()
        return self._cod_anchor_two_construction_column_periods()

    def _source_aligned_operating_boundary_periods(self) -> tuple[PeriodMeta, ...]:
        """Generate source-aligned periods with one construction column."""
        periods: List[PeriodMeta] = []

        # === Y0: Construction period (FC to operating boundary) ===
        #
        # Reference methodologys expose one pre-operating model column, followed by
        # operating periods that start on the semiannual boundary on or just
        # after COD. Splitting construction into two semiannual columns creates
        # an extra non-source period and shifts Base CFADS, senior debt service,
        # and SHL cash one period downstream.
        construction_end = self._operating_start
        days_y0 = self._days_between(self.fc, construction_end)
        y0_is_leap = calendar.isleap(construction_end.year)
        periods.append(PeriodMeta(
            index=0,
            start_date=self.fc,
            end_date=construction_end,
            year_index=0,
            period_in_year=1,
            is_construction=True,
            is_operation=False,
            is_ppa_active=False,
            days_in_period=days_y0,
            day_fraction=days_y0 / (366.0 if y0_is_leap else 365.0),
            is_leap_year=y0_is_leap,
        ))

        # === Operation periods ===
        current_date = construction_end
        period_index = 1
        year_index = 1
        period_in_year = 1
        operating_period_index = 0
        operating_year_index = 1

        while operating_period_index < self._operating_period_count:
            end = self._next_semiannual_end_after(current_date)
            days = self._days_between(current_date, end)
            if current_date == self._cod and current_date.day == 1:
                days += 1
            ppa_active = current_date < self._ppa_end
            denominator = self._semiannual_operating_denominator(end)
            is_leap = denominator == 366.0
            periods.append(PeriodMeta(
                index=period_index,
                start_date=current_date,
                end_date=end,
                year_index=year_index,
                period_in_year=period_in_year,
                is_construction=False,
                is_operation=True,
                is_ppa_active=ppa_active,
                days_in_period=days,
                day_fraction=days / denominator,
                is_leap_year=is_leap,
                operating_period_index=operating_period_index,
                operating_year_index=operating_year_index,
            ))

            period_index += 1
            current_date = end
            if period_in_year == 1:
                period_in_year = 2
            else:
                period_in_year = 1
                year_index += 1
                operating_year_index += 1
            operating_period_index += 1

        return tuple(periods)

    def _cod_anchor_construction_segments(self) -> List[PeriodMeta]:
        """Meaningful six-month construction segments from FC to operating start.

        Shared by the released six-month axis and the RC-7B quarterly candidate,
        so construction reporting columns cannot diverge between frequencies.
        """
        periods: List[PeriodMeta] = []

        construction_start = self.fc
        construction_index = 0
        while construction_start < self._operating_start:
            candidate = self._add_months(construction_start, 6)
            # Fold a near-boundary remainder into the current meaningful segment.
            if candidate >= self._operating_start or (
                self._operating_start - candidate
            ).days < 7:
                construction_end = self._operating_start
            else:
                construction_end = candidate
            days = self._days_between(construction_start, construction_end)
            is_leap = calendar.isleap(construction_end.year)
            periods.append(PeriodMeta(
                index=construction_index,
                start_date=construction_start,
                end_date=construction_end,
                year_index=0,
                period_in_year=(construction_index % 2) + 1,
                is_construction=True,
                is_operation=False,
                is_ppa_active=False,
                days_in_period=days,
                day_fraction=days / (366.0 if is_leap else 365.0),
                is_leap_year=is_leap,
            ))
            construction_index += 1
            construction_start = construction_end
        return periods

    def _cod_anchor_two_construction_column_periods(self) -> tuple[PeriodMeta, ...]:
        """Generate meaningful six-month construction segments and operation."""
        periods: List[PeriodMeta] = self._cod_anchor_construction_segments()
        construction_index = len(periods)

        # === Operation periods ===
        current_date = self._last_semiannual_end_on_or_after_cod()
        period_index = construction_index
        year_index = 1
        period_in_year = 1
        operating_period_index = 0
        operating_year_index = 1

        while operating_period_index < self._operating_period_count:
            end = self._next_semiannual_end_after(current_date)
            days = self._days_between(current_date, end)
            if current_date == self._cod and current_date.day == 1:
                days += 1
            ppa_active = current_date < self._ppa_end
            is_leap = calendar.isleap(end.year)
            denominator = 366.0 if is_leap else 365.0
            periods.append(PeriodMeta(
                index=period_index,
                start_date=current_date,
                end_date=end,
                year_index=year_index,
                period_in_year=period_in_year,
                is_construction=False,
                is_operation=True,
                is_ppa_active=ppa_active,
                days_in_period=days,
                day_fraction=days / denominator,
                is_leap_year=is_leap,
                operating_period_index=operating_period_index,
                operating_year_index=operating_year_index,
            ))

            period_index += 1
            current_date = end
            if period_in_year == 1:
                period_in_year = 2
            else:
                period_in_year = 1
                year_index += 1
                operating_year_index += 1
            operating_period_index += 1

        return tuple(periods)

    @staticmethod
    def _next_quarter_end_after(d: date) -> date:
        """Return the next Mar 31 / Jun 30 / Sep 30 / Dec 31 strictly after d."""
        for month in (3, 6, 9, 12):
            end = date(d.year, month, calendar.monthrange(d.year, month)[1])
            if end > d:
                return end
        return date(d.year + 1, 3, 31)

    def _quarterly_candidate_periods(self) -> tuple[PeriodMeta, ...]:
        """Matched 3/3 candidate axis (policy-explicit, release-closed).

        Construction columns: the released six-month segments, ending at actual
        COD (identical to the six-month axis because the roll window is refused).
        Operation: KEEP_ACTUAL_COD, half-open quarters, end-year 365/366 fraction.

        v1 (rc7b): exactly ``4 * horizon_years`` operating rows and four rows per model year, stub included.
        v2 (rc7c, date-authoritative): rows run to the economic end date of the equivalent six-month horizon and each
        row carries the model year of the six-month row that contains it, so degradation, indexation, depreciation
        and OPEX steps fall on the same dates as in the six-month project.
        """
        periods: List[PeriodMeta] = self._cod_anchor_construction_segments()
        period_index = len(periods)
        current_date = self._operating_start
        semester_ends = (semiannual_row_ends(self._operating_start, 2 * int(self.horizon_years))
                         if self.year_alignment == "SEMIANNUAL_ALIGNED" else ())
        rows_in_year: dict[int, int] = {}
        for operating_period_index in range(self._operating_period_count):
            end = self._next_quarter_end_after(current_date)
            if self._economic_end_date is not None and end > self._economic_end_date:
                end = self._economic_end_date                    # explicit economic end date: the final row is a dated stub
            days = self._days_between(current_date, end)
            is_leap = calendar.isleap(end.year)
            if semester_ends:
                parent = next(k for k, boundary in enumerate(semester_ends) if end <= boundary)
                model_year = parent // 2 + 1
                rows_in_year[model_year] = rows_in_year.get(model_year, 0) + 1
                period_in_year = rows_in_year[model_year]
            else:
                model_year = operating_period_index // 4 + 1
                period_in_year = operating_period_index % 4 + 1
            periods.append(PeriodMeta(
                index=period_index,
                start_date=current_date,
                end_date=end,
                year_index=model_year,
                period_in_year=period_in_year,
                is_construction=False,
                is_operation=True,
                is_ppa_active=current_date < self._ppa_end,
                days_in_period=days,
                day_fraction=days / (366.0 if is_leap else 365.0),
                is_leap_year=is_leap,
                operating_period_index=operating_period_index,
                operating_year_index=model_year,
            ))
            period_index += 1
            current_date = end
        return tuple(periods)

    def operation_periods(self) -> tuple[PeriodMeta, ...]:
        """Returns only operation periods (excludes construction)."""
        return tuple(p for p in self.periods() if p.is_operation)

    def ppa_periods(self) -> tuple[PeriodMeta, ...]:
        """Returns only PPA-active operation periods."""
        return tuple(p for p in self.periods() if p.is_ppa_active)

    def period_dates(self) -> tuple[date, ...]:
        """Returns end_dates for all periods."""
        return tuple(p.end_date for p in self.periods())


def validate_canonical_period_axis(
    periods: Sequence[PeriodMeta],
    *,
    expected_operating_periods: int | None = None,
    cod_date: "date | None" = None,
    period_convention: "PeriodAxisConvention | None" = None,
    periods_per_year: int = 2,
    year_alignment: str = "FIXED_ROWS",
    expected_economic_end: "date | None" = None,
) -> None:
    """Fail closed when a consumer receives a malformed financial axis.

    ``periods_per_year`` (default 2, the released six-month axis) sets the
    operating year / period-in-year counter cycle. 4 is accepted only for the
    RC-7B matched quarterly candidate; any other value fails closed.

    Checks (in order):
      1.  Axis is non-empty.
      2.  Indices are unique and form 0-based contiguous range.
      3.  Per-period: positive duration, mutually exclusive phase flags,
          date continuity, finite+positive day_fraction,
          days_in_period consistent with date span (COD-inclusive +1 rule),
          day_fraction reconciled numerically to days_in_period / approved_denominator.
      4.  Construction periods form one contiguous prefix (no construction
          after operation begins).
      5.  Operating periods form one contiguous suffix.
      6.  Operating period counters are coherent (operating_period_index,
          operating_year_index, period_in_year).
      7.  Operating count equals expected_operating_periods when supplied.
      8.  Operating sequential indices are 0-based and contiguous.
      9.  Final operating period has more than one day (no terminal one-day stub).

    COD-inclusive +1 rule (TASK 2):
      days_in_period = calendar_days + 1 is permitted ONLY for the first operating
      period (operating_period_index == 0) when its start_date.day == 1 (COD falls on
      the first day of a month).  Construction periods and all other operating periods
      must have days_in_period == calendar_days exactly.

    day_fraction reconciliation (Correction D):
      The approved denominator is derived INDEPENDENTLY from period dates and the
      typed period_convention — never from period.is_leap_year.

      Denominator convention by axis type:
        COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS (default/generic):
          All periods: ref_year = end.year; denom = 366 if leap(ref_year) else 365.
        OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN (source-aligned H2):
          Operating periods ending in December: ref_year = end.year + 1 (H2/next-year).
          All other periods: ref_year = end.year.

      When period_convention is None (non-authoritative compatibility mode):
        Both plain and H2 denominators are computed.  When they agree, strict
        validation applies.  When they disagree (only possible for December-ending
        periods where end.year vs end.year+1 differ in leap status), the period
        is accepted if its day_fraction is consistent with either; is_leap_year is
        not validated against the convention.  Production code ALWAYS passes
        period_convention (via PeriodEngine) so this mode is never reached in
        production paths.

      Validation steps (authoritative mode):
        (a) is_leap_year == (independently_derived_denom == 366) — PERIOD_AXIS_IS_LEAP_YEAR_MISMATCH
        (b) day_fraction == days_in_period / independently_derived_denom — PERIOD_AXIS_DAY_FRACTION_RECONCILIATION_FAILED
      Both checks fire separately and catch coordinated mutations (flip both fields).
    """
    import math as _math

    if type(periods_per_year) is not int or periods_per_year not in (2, 4):
        raise ValueError(f"PERIOD_AXIS_PERIODS_PER_YEAR_UNSUPPORTED: {periods_per_year!r}")
    if year_alignment not in ("FIXED_ROWS", "SEMIANNUAL_ALIGNED"):
        raise ValueError(f"PERIOD_AXIS_YEAR_ALIGNMENT_UNSUPPORTED: {year_alignment!r}")
    if year_alignment == "SEMIANNUAL_ALIGNED" and periods_per_year != 4:
        raise ValueError("PERIOD_AXIS_YEAR_ALIGNMENT_UNSUPPORTED: semiannual alignment is defined for the quarterly candidate only")
    if not periods:
        raise ValueError("PERIOD_AXIS_EMPTY")
    indices = tuple(p.index for p in periods)
    if len(set(indices)) != len(indices):
        raise ValueError("PERIOD_AXIS_DUPLICATE_INDICES")
    if indices != tuple(range(len(periods))):
        raise ValueError("PERIOD_AXIS_NON_CONTIGUOUS_OR_OUT_OF_ORDER")

    operation_started = False
    for position, period in enumerate(periods):
        # 3a. positive duration
        if period.days_in_period <= 0 or period.end_date <= period.start_date:
            raise ValueError(
                f"PERIOD_AXIS_NON_POSITIVE_DURATION: period_index={period.index}"
            )
        # 3b. mutually exclusive phase flags
        if period.is_construction == period.is_operation:
            raise ValueError(
                f"PERIOD_AXIS_PHASE_FLAGS_INVALID: period_index={period.index}"
            )
        # 3c. date continuity
        if position and period.start_date != periods[position - 1].end_date:
            raise ValueError(
                f"PERIOD_AXIS_GAP_OR_OVERLAP: period_index={period.index}"
            )
        # 3d. day_fraction finite and positive
        if not _math.isfinite(period.day_fraction) or period.day_fraction <= 0.0:
            raise ValueError(
                f"PERIOD_AXIS_DAY_FRACTION_INVALID: period_index={period.index} "
                f"day_fraction={period.day_fraction!r}"
            )
        # 3e. days_in_period consistent with date span.
        # COD-inclusive +1 rule: the sole permitted exception is the FIRST operating
        # period (operating_period_index == 0) when start_date is the actual COD and
        # COD falls on the first of a month.  Construction periods never get +1.
        # All other operating periods must be exactly calendar_days.
        #
        # When cod_date is provided (authoritative), +1 is allowed ONLY when
        # start_date == cod_date (actual COD match, not inferred proxy).
        # When cod_date is None, falls back to the day==1 proxy for backward compat.
        calendar_days = (period.end_date - period.start_date).days
        if cod_date is not None:
            _cod_inclusive_allowed = (
                period.is_operation
                and period.operating_period_index == 0
                and period.start_date == cod_date
                and cod_date.day == 1
            )
        else:
            _cod_inclusive_allowed = (
                period.is_operation
                and period.operating_period_index == 0
                and period.start_date.day == 1
            )
        _allowed_days: tuple[int, ...]
        if _cod_inclusive_allowed:
            _allowed_days = (calendar_days, calendar_days + 1)
        else:
            _allowed_days = (calendar_days,)
        if period.days_in_period not in _allowed_days:
            raise ValueError(
                f"PERIOD_AXIS_DAYS_IN_PERIOD_MISMATCH: period_index={period.index} "
                f"days_in_period={period.days_in_period} calendar_days={calendar_days} "
                f"cod_inclusive_allowed={_cod_inclusive_allowed}"
            )
        # 3f. Independent denominator derivation from period dates (Correction D).
        # The approved denominator is derived from calendar.isleap applied to a
        # reference year computed from end_date and the typed period_convention.
        # This is INDEPENDENT of period.is_leap_year, catching coordinated mutations.
        import calendar as _calendar
        _end = period.end_date

        # Convention-aware reference-year derivation:
        #   COD_ANCHOR: always end.year (generic/plain convention).
        #   OPERATING_BOUNDARY: operating periods in December use end.year+1 (H2/source-aligned).
        #   None (non-authoritative): try both; strict only when they agree.
        if period_convention == PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN:
            _is_h2_op = period.is_operation and _end.month == 12
            _ref_year = _end.year + 1 if _is_h2_op else _end.year
            _independent_denom = 366.0 if _calendar.isleap(_ref_year) else 365.0
            _authoritative = True
        elif period_convention == PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS:
            _ref_year = _end.year
            _independent_denom = 366.0 if _calendar.isleap(_ref_year) else 365.0
            _authoritative = True
        else:
            # Non-authoritative compatibility fallback (period_convention=None).
            # Production callers always pass period_convention via PeriodEngine.
            _ref_plain = _end.year
            _ref_h2 = _end.year + 1 if _end.month == 12 else _end.year
            _denom_plain = 366.0 if _calendar.isleap(_ref_plain) else 365.0
            _denom_h2 = 366.0 if _calendar.isleap(_ref_h2) else 365.0
            if _denom_plain == _denom_h2:
                # Both conventions agree — derive strictly from dates.
                _independent_denom = _denom_plain
                _ref_year = _ref_plain
                _authoritative = True
            else:
                # Conventions disagree (December-ending, different leap status for
                # end.year vs end.year+1). Non-authoritative: accept if either matches.
                _exp_plain = period.days_in_period / _denom_plain
                _exp_h2 = period.days_in_period / _denom_h2
                if (abs(period.day_fraction - _exp_plain) > 1e-9
                        and abs(period.day_fraction - _exp_h2) > 1e-9):
                    raise ValueError(
                        f"PERIOD_AXIS_DAY_FRACTION_RECONCILIATION_FAILED: period_index={period.index} "
                        f"day_fraction={period.day_fraction!r} "
                        f"expected={_exp_plain!r} (plain end.year={_ref_plain}) or "
                        f"{_exp_h2!r} (H2 ref_year={_ref_h2}) "
                        f"(days_in_period={period.days_in_period})"
                    )
                # Pass — cannot validate is_leap_year without typed convention.
                _authoritative = False
                _independent_denom = _denom_plain  # placeholder, not used below
                _ref_year = _ref_plain

        if _authoritative:
            # 3f-i. Validate is_leap_year against independently derived denominator.
            # This catches single-field flip AND coordinated (both-fields) mutations.
            _expected_is_leap = (_independent_denom == 366.0)
            if period.is_leap_year != _expected_is_leap:
                raise ValueError(
                    f"PERIOD_AXIS_IS_LEAP_YEAR_MISMATCH: period_index={period.index} "
                    f"is_leap_year={period.is_leap_year} but independently derived "
                    f"denominator={_independent_denom} from end_date={_end.isoformat()} "
                    f"(ref_year={_ref_year}) implies is_leap={_expected_is_leap}"
                )
            # 3f-ii. Validate day_fraction against independently derived denominator.
            _expected_fraction = period.days_in_period / _independent_denom
            if abs(period.day_fraction - _expected_fraction) > 1e-9:
                raise ValueError(
                    f"PERIOD_AXIS_DAY_FRACTION_RECONCILIATION_FAILED: period_index={period.index} "
                    f"day_fraction={period.day_fraction!r} expected={_expected_fraction!r} "
                    f"(days_in_period={period.days_in_period} / independent_denominator={_independent_denom})"
                )
        # 4. no construction after operation begins
        if period.is_operation:
            operation_started = True
        elif operation_started and period.is_construction:
            raise ValueError(
                f"PERIOD_AXIS_CONSTRUCTION_AFTER_OPERATION: period_index={period.index}"
            )

    # 5. operating periods form contiguous suffix (already implied by 4, but verify)
    construction = tuple(p for p in periods if p.is_construction)
    operating = tuple(p for p in periods if p.is_operation)
    if construction and operating:
        if construction[-1].index >= operating[0].index:
            raise ValueError(
                "PERIOD_AXIS_PHASE_ORDER_INVALID: construction and operating overlap"
            )

    # 6. operating period counters coherent
    aligned_clock: list[tuple[int, int]] = []
    if year_alignment == "SEMIANNUAL_ALIGNED" and operating:
        # Date-authoritative clock, recomputed here from the dates alone: a row's model year is the year of the six-month row that contains it.
        boundaries: list[date] = []
        cursor = operating[0].start_date
        while not boundaries or boundaries[-1] < operating[-1].end_date:
            cursor = semiannual_boundary_after(cursor)
            boundaries.append(cursor)
        seen: dict[int, int] = {}
        for op in operating:
            parent = next(k for k, boundary in enumerate(boundaries) if op.end_date <= boundary)
            year = parent // 2 + 1
            seen[year] = seen.get(year, 0) + 1
            aligned_clock.append((year, seen[year]))
        if expected_economic_end is not None and operating[-1].end_date != expected_economic_end:
            raise ValueError(
                "PERIOD_AXIS_ECONOMIC_END_DATE_MISMATCH: "
                f"expected={expected_economic_end.isoformat()} actual={operating[-1].end_date.isoformat()}"
            )
    for op_pos, op in enumerate(operating):
        if op.operating_period_index != op_pos:
            raise ValueError(
                f"PERIOD_AXIS_OPERATING_INDICES_INVALID: period_index={op.index} "
                f"expected_op_idx={op_pos} actual={op.operating_period_index}"
            )
        if aligned_clock:
            expected_year, expected_pip = aligned_clock[op_pos]
        else:
            expected_year = op_pos // periods_per_year + 1
            expected_pip = op_pos % periods_per_year + 1
        if op.operating_year_index != expected_year:
            raise ValueError(
                f"PERIOD_AXIS_OPERATING_YEAR_INDEX_INVALID: period_index={op.index} "
                f"expected={expected_year} actual={op.operating_year_index}"
            )
        if op.period_in_year != expected_pip:
            raise ValueError(
                f"PERIOD_AXIS_PERIOD_IN_YEAR_INVALID: period_index={op.index} "
                f"expected={expected_pip} actual={op.period_in_year}"
            )

    # 7. operating count check
    if expected_operating_periods is not None and len(operating) != expected_operating_periods:
        raise ValueError(
            "PERIOD_AXIS_OPERATING_COUNT_MISMATCH: "
            f"expected={expected_operating_periods}, actual={len(operating)}"
        )

    # 8. operating sequential indices (already validated above via 6)

    # 9. no terminal one-day stub in operating periods
    if operating and operating[-1].days_in_period <= 1:
        raise ValueError(
            f"PERIOD_AXIS_TERMINAL_STUB: final operating period has "
            f"days_in_period={operating[-1].days_in_period}"
        )


def map_period_vector(
    period_indices: Sequence[int],
    values: Sequence[Any],
    *,
    label: str,
    expected_indices: tuple[int, ...] | None = None,
) -> dict[int, Any]:
    """Map an axis-aligned vector without truncation, overwrite, or reordering.

    When ``expected_indices`` is provided (the independently-derived canonical
    axis), this function compares the supplied ``period_indices`` against it
    using an exact immutable tuple comparison BEFORE any dict construction.
    This catches missing, extra, shifted, and reordered periods that would
    otherwise be silently swallowed by the dict.

    Error codes:
      AXIS_PERIOD_DUPLICATE  — duplicate raw indices in the supplied vector
      AXIS_LENGTH_MISMATCH   — len(period_indices) != len(expected_indices)
      AXIS_PERIOD_MISSING    — expected index absent from supplied indices
      AXIS_PERIOD_EXTRA      — supplied index not in expected_indices
      AXIS_PERIOD_SHIFTED    — indices match as a set but are offset/reordered
      PERIOD_VECTOR_LENGTH_MISMATCH — len(period_indices) != len(values)
      PERIOD_VECTOR_DUPLICATE_INDICES — duplicate raw indices (no expected given)
      PERIOD_VECTOR_OUT_OF_ORDER     — not strictly increasing (no expected given)
    """
    indices = tuple(period_indices)
    vector = tuple(values)

    # --- Step 1: duplicate check (must fire before anything else) ---
    if len(set(indices)) != len(indices):
        raise ValueError(f"AXIS_PERIOD_DUPLICATE: {label}")

    # --- Step 2: exact-axis membership check (authoritative comparison) ---
    if expected_indices is not None:
        expected = tuple(expected_indices)
        if len(indices) != len(expected):
            supplied_set = set(indices)
            expected_set = set(expected)
            missing = expected_set - supplied_set
            extra = supplied_set - expected_set
            if missing and not extra:
                raise ValueError(
                    f"AXIS_PERIOD_MISSING: {label} missing={sorted(missing)}"
                )
            if extra and not missing:
                raise ValueError(
                    f"AXIS_PERIOD_EXTRA: {label} extra={sorted(extra)}"
                )
            raise ValueError(
                f"AXIS_LENGTH_MISMATCH: {label} "
                f"expected={len(expected)} supplied={len(indices)}"
            )
        if indices != expected:
            supplied_set = set(indices)
            expected_set = set(expected)
            missing = expected_set - supplied_set
            extra = supplied_set - expected_set
            if missing:
                raise ValueError(
                    f"AXIS_PERIOD_MISSING: {label} missing={sorted(missing)}"
                )
            if extra:
                raise ValueError(
                    f"AXIS_PERIOD_EXTRA: {label} extra={sorted(extra)}"
                )
            # same set, wrong order/offset within same length — shifted or reordered
            raise ValueError(
                f"AXIS_PERIOD_SHIFTED: {label} "
                f"expected={expected} supplied={indices}"
            )

    # --- Step 3: parallel-vector length check ---
    if len(indices) != len(vector):
        raise ValueError(
            f"PERIOD_VECTOR_LENGTH_MISMATCH: {label} indices={len(indices)} "
            f"values={len(vector)}"
        )

    # --- Step 4: order check (when no expected_indices provided) ---
    if expected_indices is None:
        if any(curr <= prev for prev, curr in zip(indices, indices[1:])):
            raise ValueError(f"PERIOD_VECTOR_OUT_OF_ORDER: {label}")

    return {idx: vector[position] for position, idx in enumerate(indices)}


def hash_engine_for_cache(e: "PeriodEngine") -> tuple:
    """Deterministic hash for PeriodEngine inputs (for cache key)."""
    key = (
        e.fc,
        e.construction_months,
        e.horizon_years,
        e.ppa_years,
        e.freq,
        e.cod,
        e.period_axis_convention.value,
    )
    policy = getattr(e, "operating_calendar_policy", None)
    if policy is not None:
        key = key + (("operating_calendar_policy", policy.cache_key()),)
        explicit_end = getattr(e, "_explicit_economic_end", None)
        if explicit_end is not None:
            key = key + (("economic_end_date", explicit_end.isoformat()),)
    return key
