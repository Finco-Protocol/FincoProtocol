"""Explicit candidate calendar; the released PeriodEngine remains unchanged."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, fields
from datetime import date
from enum import Enum

from dateutil.relativedelta import relativedelta

from financial_engine.inputs import CalendarInput, OperatingModelInput, PeriodAxisConvention
from finco_core.engine.axis_contract import CanonicalAxisContract
from finco_core.engine.period_engine import PeriodFrequency, PeriodMeta, map_period_vector


class StubRule(str, Enum):
    KEEP_ACTUAL_COD = "KEEP_ACTUAL_COD"


class DayRule(str, Enum):
    HALF_OPEN = "HALF_OPEN"


class FractionRule(str, Enum):
    ACTUAL_END_YEAR = "ACTUAL_END_YEAR"


class YearRule(str, Enum):
    FOUR_OPERATING_PERIODS_INCLUDING_STUB = "FOUR_OPERATING_PERIODS_INCLUDING_STUB"


class HorizonRule(str, Enum):
    FIXED_FOUR_PERIODS_PER_HORIZON_YEAR = "FIXED_FOUR_PERIODS_PER_HORIZON_YEAR"


class ConstructionReportingRule(str, Enum):
    SINGLE_FC_TO_COD_COLUMN = "SINGLE_FC_TO_COD_COLUMN"


@dataclass(frozen=True)
class QuarterlyCalendarPolicy:
    """All conventions must be chosen explicitly; none represents owner approval."""

    version: str
    operating_months: int
    debt_service_months: int
    stub: StubRule
    day_rule: DayRule
    fraction: FractionRule
    model_year: YearRule
    horizon: HorizonRule
    construction_reporting: ConstructionReportingRule

    def __post_init__(self):
        if self.version != "rc7-quarterly-candidate-v1":
            raise ValueError("QUARTERLY_POLICY_VERSION_UNSUPPORTED")
        for name in ("operating_months", "debt_service_months"):
            if type(getattr(self, name)) is not int or getattr(self, name) != 3:
                raise ValueError("QUARTERLY_MATCHED_3_3_REQUIRED")
        for name, enum in _POLICY_ENUMS.items():
            if type(getattr(self, name)) is not enum:
                raise ValueError(f"QUARTERLY_EXPLICIT_POLICY_REQUIRED: {name}")

    def to_dict(self):
        return {f.name: getattr(self, f.name).value if f.name in _POLICY_ENUMS
                else getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, raw):
        expected = {f.name for f in fields(cls)}
        if type(raw) is not dict or set(raw) != expected:
            raise ValueError("QUARTERLY_COMPLETE_VERSIONED_POLICY_REQUIRED")
        values = dict(raw)
        for name, enum in _POLICY_ENUMS.items():
            values[name] = enum(values[name])
        return cls(**values)


_POLICY_ENUMS = {"stub": StubRule, "day_rule": DayRule, "fraction": FractionRule,
                 "model_year": YearRule, "horizon": HorizonRule,
                 "construction_reporting": ConstructionReportingRule}


class RenewableTechnology(str, Enum):
    SOLAR = "SOLAR"
    WIND = "WIND"


@dataclass(frozen=True, kw_only=True)
class QuarterlyOperatingModelInput(OperatingModelInput):
    """Research-only clean contract; no production ProjectInputs admission."""

    technology: RenewableTechnology

    def __post_init__(self):
        if type(self.calendar) is not QuarterlyCandidateCalendar:
            raise ValueError("QUARTERLY_TYPED_CALENDAR_REQUIRED")
        if type(self.technology) is not RenewableTechnology:
            raise ValueError("QUARTERLY_TECHNOLOGY_UNSUPPORTED")


@dataclass(frozen=True, kw_only=True)
class QuarterlyCandidateCalendar(CalendarInput):
    policy: QuarterlyCalendarPolicy

    def __post_init__(self):
        if type(self.policy) is not QuarterlyCalendarPolicy:
            raise ValueError("QUARTERLY_EXPLICIT_POLICY_REQUIRED")
        if self.period_axis_convention is not PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS:
            raise ValueError("QUARTERLY_LEGACY_CONVENTION_OVERRIDE_UNSUPPORTED")
        if type(self.financial_close) is not date or type(self.cod_date) is not date:
            raise ValueError("QUARTERLY_EXACT_PROJECT_DATES_REQUIRED")
        if type(self.construction_months) is not int or not 1 <= self.construction_months <= 1200:
            raise ValueError("QUARTERLY_CONSTRUCTION_MONTHS_UNSUPPORTED")
        if type(self.horizon_years) is not int or not 1 <= self.horizon_years <= 100:
            raise ValueError("QUARTERLY_HORIZON_UNSUPPORTED")
        if self.cod_date != self.financial_close + relativedelta(months=self.construction_months):
            raise ValueError("PERIOD_AXIS_COD_MISMATCH")
        if isinstance(self.ppa_years, bool) or not isinstance(self.ppa_years, (int, float)):
            raise ValueError("QUARTERLY_PPA_TERM_INVALID")
        if self.ppa_years < 0 or self.ppa_years > 100 or not float(self.ppa_years).is_integer():
            raise ValueError("QUARTERLY_PPA_TERM_UNSUPPORTED")


def next_quarter_end(start: date) -> date:
    for month in (3, 6, 9, 12):
        end = date(start.year, month, calendar.monthrange(start.year, month)[1])
        if end > start:
            return end
    return date(start.year + 1, 3, 31)


@dataclass(frozen=True)
class QuarterlyCandidateAxis:
    calendar_input: QuarterlyCandidateCalendar
    rows: tuple[PeriodMeta, ...]

    @classmethod
    def build(cls, cal: QuarterlyCandidateCalendar):
        if type(cal) is not QuarterlyCandidateCalendar:
            raise ValueError("QUARTERLY_TYPED_CALENDAR_REQUIRED")
        cod = cal.cod_date
        days = (cod - cal.financial_close).days
        leap = calendar.isleap(cod.year)
        rows = [PeriodMeta(0, cal.financial_close, cod, 0, 1, True, False,
                           False, days, days / (366 if leap else 365), leap)]
        start = cod
        ppa_end = cod + relativedelta(years=int(cal.ppa_years))
        for pos in range(cal.horizon_years * 4):
            end = next_quarter_end(start)
            days = (end - start).days
            leap = calendar.isleap(end.year)
            rows.append(PeriodMeta(pos + 1, start, end, pos // 4 + 1, pos % 4 + 1,
                                   False, True, start < ppa_end, days,
                                   days / (366 if leap else 365), leap, pos, pos // 4 + 1))
            start = end
        axis = cls(cal, tuple(rows))
        axis.validate()
        return axis

    def validate(self):
        cal = self.calendar_input
        if type(cal) is not QuarterlyCandidateCalendar or type(self.rows) is not tuple:
            raise ValueError("QUARTERLY_TYPED_AXIS_REQUIRED")
        if len(self.rows) != 1 + 4 * cal.horizon_years:
            raise ValueError("QUARTERLY_AXIS_LENGTH_MISMATCH")
        map_period_vector(tuple(p.index for p in self.rows), self.rows,
                          label="quarterly_candidate", expected_indices=tuple(range(len(self.rows))))
        previous = cal.financial_close
        ppa_end = cal.cod_date + relativedelta(years=int(cal.ppa_years))
        for idx, p in enumerate(self.rows):
            if type(p) is not PeriodMeta or any(type(getattr(p, name)) is not int for name in (
                    "index", "year_index", "period_in_year", "days_in_period",
                    "operating_period_index", "operating_year_index")):
                raise ValueError("QUARTERLY_TYPED_COUNTER_REQUIRED")
            end = cal.cod_date if idx == 0 else next_quarter_end(previous)
            days = (end - previous).days
            leap = calendar.isleap(end.year)
            if type(p) is not PeriodMeta or p.start_date != previous or p.end_date != end or days <= 0:
                raise ValueError("QUARTERLY_AXIS_DATE_MISMATCH")
            if (p.days_in_period != days or p.day_fraction != days / (366 if leap else 365)
                    or p.is_leap_year is not leap):
                raise ValueError("QUARTERLY_AXIS_FRACTION_MISMATCH")
            if (p.is_construction is not (idx == 0) or p.is_operation is not (idx > 0)
                    or p.year_index != (0 if idx == 0 else (idx - 1) // 4 + 1)
                    or p.period_in_year != (1 if idx == 0 else (idx - 1) % 4 + 1)
                    or p.operating_period_index != idx - 1
                    or p.operating_year_index != p.year_index
                    or p.is_ppa_active is not (idx > 0 and previous < ppa_end)):
                raise ValueError("QUARTERLY_AXIS_COUNTER_OR_FLAG_MISMATCH")
            previous = end

    @property
    def cod(self):
        return self.calendar_input.cod_date

    @property
    def freq(self):
        return PeriodFrequency.QUARTERLY

    @property
    def horizon_end(self):
        return self.rows[-1].end_date

    def periods(self):
        return self.rows

    def operation_periods(self):
        return self.rows[1:]

    def canonical_contract(self, senior_policy):
        self.validate()
        if senior_policy is not None:
            indices = tuple(p.index for p in self.rows[1:])
            if (senior_policy.periods_per_year != 4
                    or senior_policy.repayment_start_period_index not in indices
                    or senior_policy.maturity_period_index not in indices
                    or senior_policy.repayment_start_period_index > senior_policy.maturity_period_index):
                raise ValueError("QUARTERLY_DEBT_AXIS_MISMATCH")
        return CanonicalAxisContract.from_periods_and_policy(self.rows, senior_policy)
