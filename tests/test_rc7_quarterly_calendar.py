"""Independent date/fraction checks for the unreleased RC-7 calendar contract."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from fractions import Fraction

import pytest
from dateutil.relativedelta import relativedelta

from financial_engine.quarterly import ACTIVATION_ENABLED
from financial_engine.quarterly.calendar import (
    ConstructionReportingRule, DayRule, FractionRule, HorizonRule,
    QuarterlyCalendarPolicy, QuarterlyCandidateAxis, QuarterlyCandidateCalendar,
    StubRule, YearRule,
)


def explicit_policy():
    return QuarterlyCalendarPolicy("rc7-quarterly-candidate-v1", 3, 3,
        StubRule.KEEP_ACTUAL_COD, DayRule.HALF_OPEN, FractionRule.ACTUAL_END_YEAR,
        YearRule.FOUR_OPERATING_PERIODS_INCLUDING_STUB,
        HorizonRule.FIXED_FOUR_PERIODS_PER_HORIZON_YEAR,
        ConstructionReportingRule.SINGLE_FC_TO_COD_COLUMN)


def candidate_calendar(cod=date(2027, 12, 31), horizon=2):
    return QuarterlyCandidateCalendar(financial_close=cod - relativedelta(years=1),
        construction_months=12, horizon_years=horizon, ppa_years=0,
        cod_date=cod, policy=explicit_policy())


@pytest.mark.parametrize("cod", [date(2027, 12, 31), date(2028, 1, 1), date(2028, 2, 29),
    date(2028, 3, 30), date(2028, 3, 31), date(2028, 4, 17), date(2028, 6, 29),
    date(2028, 6, 30), date(2028, 9, 30), date(2028, 12, 30)])
def test_exact_cod_no_short_stub_roll_and_independent_day_oracle(cod):
    # Construct FC first: EDATE subtraction is not reversible for every month-end.
    fc = cod - relativedelta(years=1)
    actual_cod = fc + relativedelta(years=1)
    cal = replace(candidate_calendar(), financial_close=fc, cod_date=actual_cod)
    axis = QuarterlyCandidateAxis.build(cal)
    assert len(axis.rows) == 9
    assert axis.rows[1].start_date == actual_cod
    for pos, row in enumerate(axis.rows[1:]):
        choices = [date(y, m, d) for y in range(actual_cod.year, actual_cod.year + 4)
                   for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)) if date(y, m, d) > row.start_date]
        assert row.end_date == min(choices)
        assert row.days_in_period == (row.end_date - row.start_date).days
        year = row.end_date.year
        year_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        assert row.day_fraction == float(Fraction(row.days_in_period, year_days))
        assert row.year_index == pos // 4 + 1
        assert row.period_in_year == pos % 4 + 1
    assert axis.canonical_contract(None).operating_axis == tuple(range(1, 9))


@pytest.mark.parametrize("year,days", [(2028, 366), (2029, 365)])
def test_complete_calendar_year_fraction_conserved(year, days):
    axis = QuarterlyCandidateAxis.build(candidate_calendar(date(year - 1, 12, 31), 1))
    assert sum(r.days_in_period for r in axis.rows[1:]) == days
    assert sum((Fraction(r.days_in_period, days) for r in axis.rows[1:]), Fraction()) == 1


def test_fixed_count_is_not_silently_cod_anniversary_horizon():
    axis = QuarterlyCandidateAxis.build(candidate_calendar(date(2028, 4, 17), 1))
    assert axis.horizon_end == date(2029, 3, 31)
    assert axis.horizon_end != date(2029, 4, 17)
    assert axis.rows[1].days_in_period == 74


@pytest.mark.parametrize("update", [{"version": "future"}, {"operating_months": 6},
    {"debt_service_months": 6}, {"operating_months": True}, {"stub": "KEEP_ACTUAL_COD"},
    {"day_rule": None}, {"model_year": "CALENDAR_YEAR"}])
def test_unknown_partial_or_mixed_policies_refused(update):
    with pytest.raises(ValueError):
        replace(explicit_policy(), **update)


def test_roundtrip_is_complete_and_immutable_without_activation():
    policy = explicit_policy()
    assert QuarterlyCalendarPolicy.from_dict(policy.to_dict()) == policy
    raw = policy.to_dict()
    raw.pop("day_rule")
    with pytest.raises(ValueError, match="COMPLETE_VERSIONED"):
        QuarterlyCalendarPolicy.from_dict(raw)
    with pytest.raises(FrozenInstanceError):
        policy.operating_months = 6
    assert ACTIVATION_ENABLED is False


@pytest.mark.parametrize("field,value", [("day_fraction", 0.5), ("year_index", 2),
    ("period_in_year", 4), ("days_in_period", 0), ("is_operation", False),
    ("start_date", date(2020, 1, 1))])
def test_mutated_axis_refused(field, value):
    axis = QuarterlyCandidateAxis.build(candidate_calendar())
    changed = replace(axis.rows[1], **{field: value})
    with pytest.raises(ValueError):
        replace(axis, rows=(axis.rows[0], changed, *axis.rows[2:])).validate()


def test_released_period_engine_still_rejects_quarters():
    from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
    with pytest.raises(ValueError, match="PERIOD_AXIS_FREQUENCY_UNSUPPORTED"):
        PeriodEngine(date(2027, 1, 1), 12, 2, 0, frequency=PeriodFrequency.QUARTERLY)
