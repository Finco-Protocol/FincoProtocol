"""RC-7C: the quarterly candidate (v2) preserves the economic calendar of the equivalent six-month project.

D-03 / D-04 / D-10. Changing 6/6 to 3/3 may change the timing of financing cash flows; it must not extend the project's life, move the model-year
(anniversary) clock that drives degradation, indexation, depreciation and OPEX steps, or move the Senior maturity date.

Expected values are derived independently here from dates with month arithmetic (never from the engine under test) and compared with the REAL
released six-month axis. Nothing in this file is owner approval of the candidate conventions.
"""
from __future__ import annotations

import calendar as pycal
import dataclasses
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from finco_core.engine.calendar_policy import (
    OperatingCalendarPolicy, quarterly_candidate_policy, quarterly_candidate_policy_v1, quarterly_candidate_policy_v2,
)
from finco_core.engine.period_engine import (
    PeriodAxisConvention, PeriodEngine, PeriodFrequency, hash_engine_for_cache, semiannual_row_ends,
    validate_canonical_period_axis,
)

Q, S = PeriodFrequency.QUARTERLY, PeriodFrequency.SEMESTRIAL
V1, V2 = quarterly_candidate_policy_v1(), quarterly_candidate_policy_v2()


def month_end(year: int, month: int) -> date:
    return date(year, month, pycal.monthrange(year, month)[1])


# ── independent date oracle (month arithmetic, not the engine's helper) ───────

def oracle_six_month_ends(cod: date, rows: int) -> list[date]:
    first = month_end(cod.year, 6) if cod < month_end(cod.year, 6) else (month_end(cod.year, 12) if cod < month_end(cod.year, 12) else month_end(cod.year + 1, 6))
    out = []
    for k in range(rows):
        shifted = first + relativedelta(months=6 * k)
        out.append(month_end(shifted.year, shifted.month))
    return out


def oracle_quarter_ends_between(cod: date, end: date) -> list[date]:
    out, cursor = [], cod
    while cursor < end:
        month = ((cursor.month - 1) // 3 + 1) * 3                    # last month of the quarter that contains the cursor
        candidate = month_end(cursor.year, month)
        if candidate <= cursor:                                       # the cursor is exactly on a quarter end: take the next quarter
            nxt = month + 3
            candidate = month_end(cursor.year + (nxt - 1) // 12, (nxt - 1) % 12 + 1)
        out.append(candidate)
        cursor = candidate
    return out


def oracle(cod: date, horizon: int):
    """(rows, economic_end): (start, end, model_year, slot_in_year) for every quarterly row of the date-authoritative axis."""
    six = oracle_six_month_ends(cod, 2 * horizon)
    economic_end = six[-1]
    ends = oracle_quarter_ends_between(cod, economic_end)
    rows, start, seen = [], cod, {}
    for end in ends:
        parent = next(k for k, boundary in enumerate(six) if end <= boundary)
        year = parent // 2 + 1
        seen[year] = seen.get(year, 0) + 1
        rows.append((start, end, year, seen[year]))
        start = end
    return rows, economic_end


def in_roll_window(cod: date) -> bool:
    boundary = date(cod.year, 6, 30) if cod.month <= 6 else date(cod.year, 12, 31)
    return 0 < (boundary - cod).days < 7


FCS = [date(2027, 1, 1), date(2027, 4, 17), date(2027, 8, 31), date(2027, 9, 17), date(2028, 2, 29), date(2027, 11, 15), date(2027, 12, 31),
       date(2029, 12, 31), date(2028, 5, 31), date(2031, 3, 30), date(2027, 2, 10), date(2027, 7, 1)]
MONTHS = [1, 5, 12, 13, 14, 15, 17, 24]


def _cases():
    for fc in FCS:
        for months in MONTHS:
            if not in_roll_window(fc + relativedelta(months=months)):
                yield fc, months


def q2(fc, months, horizon, ppa=1, policy=V2):
    return PeriodEngine(fc, months, horizon, ppa, frequency=Q, operating_calendar_policy=policy)


def s6(fc, months, horizon, ppa=1):
    return PeriodEngine(fc, months, horizon, ppa, frequency=S)


# ── D-03: the economic horizon is a date, and it is the six-month project's date ───

@pytest.mark.parametrize("fc,months", list(_cases()))
@pytest.mark.parametrize("horizon", [1, 2, 5, 25])
def test_v2_rows_match_the_independent_date_oracle(fc, months, horizon):
    engine = q2(fc, months, horizon)
    rows, economic_end = oracle(engine.cod, horizon)
    ops = engine.operation_periods()
    assert [(p.start_date, p.end_date, p.year_index, p.period_in_year) for p in ops] == rows
    assert [p.operating_year_index for p in ops] == [r[2] for r in rows]
    assert [p.operating_period_index for p in ops] == list(range(len(rows)))
    assert engine.economic_end_date == economic_end == engine.horizon_end
    assert engine.operating_period_count == len(rows)


@pytest.mark.parametrize("fc,months", list(_cases()))
@pytest.mark.parametrize("horizon", [1, 3, 25])
def test_switching_6_6_to_3_3_never_changes_the_economic_end_date_or_operating_days(fc, months, horizon):
    quarterly, semiannual = q2(fc, months, horizon), s6(fc, months, horizon)
    assert quarterly.horizon_end == semiannual.horizon_end
    assert quarterly.operating_start == semiannual.operating_start == quarterly.cod
    q_days = sum(p.days_in_period for p in quarterly.operation_periods())
    s_days = sum((p.end_date - p.start_date).days for p in semiannual.operation_periods())
    assert q_days == (quarterly.horizon_end - quarterly.cod).days == s_days     # no operating day added or removed by the frequency
    # the construction axis is the same object of record under both frequencies
    assert [p for p in quarterly.periods() if p.is_construction] == [p for p in semiannual.periods() if p.is_construction]


@pytest.mark.parametrize("fc,months", list(_cases()))
@pytest.mark.parametrize("horizon", [2, 6, 25])
def test_each_quarterly_row_lies_inside_exactly_one_six_month_row_and_inherits_its_model_year(fc, months, horizon):
    quarterly, semiannual = q2(fc, months, horizon), s6(fc, months, horizon)
    semester_rows = semiannual.operation_periods()
    for row in quarterly.operation_periods():
        parents = [p for p in semester_rows if p.start_date <= row.start_date and row.end_date <= p.end_date]
        assert len(parents) == 1, (row.start_date, row.end_date)
        assert row.year_index == parents[0].year_index and row.operating_year_index == parents[0].operating_year_index


@pytest.mark.parametrize("fc,months", list(_cases()))
def test_every_model_year_spans_exactly_the_same_dates_as_in_the_six_month_project(fc, months):
    quarterly, semiannual = q2(fc, months, 6), s6(fc, months, 6)

    def spans(engine):
        out = {}
        for p in engine.operation_periods():
            lo, hi = out.get(p.year_index, (p.start_date, p.end_date))
            out[p.year_index] = (min(lo, p.start_date), max(hi, p.end_date))
        return out
    assert spans(quarterly) == spans(semiannual)


# ── D-10: the Senior maturity date is the six-month project's maturity date ───

@pytest.mark.parametrize("fc,months", list(_cases()))
def test_senior_maturity_is_the_same_date_under_both_frequencies(fc, months):
    horizon = 12
    quarterly, semiannual = q2(fc, months, horizon), s6(fc, months, horizon)
    six_ends = [p.end_date for p in semiannual.operation_periods()]
    quarter_ends = {p.end_date for p in quarterly.operation_periods()}
    for tenor in range(1, 11):
        expected = six_ends[2 * tenor - 1]
        assert quarterly.senior_maturity_end_date(tenor) == expected
        assert expected in quarter_ends                                            # maturity is the end of a quarterly service row
    assert semiannual.senior_maturity_end_date(3) is None                           # released axis: unchanged, row-count based
    assert q2(fc, months, horizon, policy=V1).senior_maturity_end_date(3) is None   # v1: row-count based


# ── what v1 got wrong, stated as a fact about dates ───────────────────────────────

@pytest.mark.parametrize("fc,months", list(_cases()))
def test_v1_extends_the_horizon_by_exactly_one_quarter_only_when_cod_is_in_the_second_quarter_of_a_half_year(fc, months):
    v1, v2, six = q2(fc, months, 5, policy=V1), q2(fc, months, 5), s6(fc, months, 5)
    first_row_day = v2.cod + relativedelta(days=1)                               # a COD exactly on a quarter end starts the NEXT quarter
    second_quarter_of_half = (first_row_day.month - 1) // 3 % 2 == 1
    assert v2.horizon_end == six.horizon_end
    if second_quarter_of_half:
        assert (v1.horizon_end - v2.horizon_end).days in (90, 91, 92)               # one extra quarter of operating days and revenue
        assert len(v1.operation_periods()) == len(v2.operation_periods()) + 1
    else:
        assert v1.horizon_end == v2.horizon_end and len(v1.operation_periods()) == len(v2.operation_periods())


def test_the_reviewed_solar_example_shape_17_april_cod_25_years():
    engine = q2(date(2027, 4, 17), 12, 25)
    legacy = q2(date(2027, 4, 17), 12, 25, policy=V1)
    six = s6(date(2027, 4, 17), 12, 25)
    assert engine.horizon_end == six.horizon_end == date(2052, 12, 31)
    assert legacy.horizon_end == date(2053, 3, 31)
    assert len(engine.operation_periods()) == 99 and len(legacy.operation_periods()) == 100
    extra_days = (legacy.horizon_end - engine.horizon_end).days
    assert extra_days == 90 and 0.0099 < extra_days / (engine.horizon_end - engine.cod).days < 0.0100   # ~1 % of the operating life


# ── the date-authoritative validator fails closed ──────────────────────────────────

def _validate(engine, periods, **overrides):
    kwargs = dict(expected_operating_periods=engine.operating_period_count, cod_date=engine.cod,
                  period_convention=PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS, periods_per_year=4,
                  year_alignment="SEMIANNUAL_ALIGNED", expected_economic_end=engine.economic_end_date)
    kwargs.update(overrides)
    validate_canonical_period_axis(periods, **kwargs)


def test_validator_accepts_the_real_axis_and_rejects_every_calendar_defect():
    engine = q2(date(2027, 4, 17), 12, 5)
    periods = list(engine.periods())
    _validate(engine, periods)
    ops = [i for i, p in enumerate(periods) if p.is_operation]
    # a row-count year clock (the v1 clock) is rejected under the date-authoritative alignment
    wrong_year = list(periods)
    wrong_year[ops[3]] = dataclasses.replace(wrong_year[ops[3]], year_index=1, operating_year_index=1)
    with pytest.raises(ValueError, match="OPERATING_YEAR_INDEX_INVALID"):
        _validate(engine, wrong_year)
    wrong_slot = list(periods)
    wrong_slot[ops[1]] = dataclasses.replace(wrong_slot[ops[1]], period_in_year=4)
    with pytest.raises(ValueError, match="PERIOD_IN_YEAR_INVALID"):
        _validate(engine, wrong_slot)
    # one row short, or one quarter too long (the v1 defect)
    with pytest.raises(ValueError, match="ECONOMIC_END_DATE_MISMATCH"):          # the horizon end is a date: one row short ends on the wrong date
        _validate(engine, periods[:-1])
    with pytest.raises(ValueError, match="ECONOMIC_END_DATE_MISMATCH"):
        _validate(engine, periods[:-1], expected_operating_periods=len(ops) - 1)
    with pytest.raises(ValueError, match="OPERATING_COUNT_MISMATCH"):            # right end date, wrong row count
        _validate(engine, periods, expected_operating_periods=len(ops) + 1)
    extended = q2(date(2027, 4, 17), 12, 5, policy=V1)
    with pytest.raises(ValueError, match="OPERATING_YEAR_INDEX_INVALID|OPERATING_COUNT_MISMATCH|ECONOMIC_END_DATE_MISMATCH"):
        _validate(engine, list(extended.periods()), expected_operating_periods=extended.operating_period_count)


def test_semiannual_alignment_is_defined_for_the_quarterly_axis_only():
    engine = q2(date(2027, 4, 17), 12, 2)
    with pytest.raises(ValueError, match="YEAR_ALIGNMENT_UNSUPPORTED"):
        _validate(engine, list(engine.periods()), periods_per_year=2)
    with pytest.raises(ValueError, match="YEAR_ALIGNMENT_UNSUPPORTED"):
        _validate(engine, list(engine.periods()), year_alignment="UNKNOWN")


def test_released_six_month_axis_is_byte_identical_to_before():
    engine = s6(date(2027, 4, 17), 12, 3)
    assert engine.year_alignment == "FIXED_ROWS" and engine.economic_end_date is None
    assert engine.operating_period_count == 6 and len(hash_engine_for_cache(engine)) == 7
    assert [p.period_in_year for p in engine.operation_periods()] == [1, 2, 1, 2, 1, 2]


def test_policy_versions_never_mix_and_v1_stays_decodable():
    raw = V2.to_dict()
    for field, value in (("horizon", "FIXED_FOUR_PERIODS_PER_HORIZON_YEAR"), ("model_year", "FOUR_OPERATING_PERIODS_INCLUDING_STUB"),
                         ("maturity", "ROW_COUNT_SERVICE_ENDPOINT")):
        with pytest.raises(ValueError, match="QUARTERLY_POLICY_RULESET_MISMATCH"):
            OperatingCalendarPolicy.from_dict({**raw, field: value})
    v1_raw = V1.to_dict()
    for field, value in (("horizon", "SEMIANNUAL_ECONOMIC_END_DATE_PRESERVED"), ("model_year", "SEMIANNUAL_MODEL_YEAR_ALIGNED"),
                         ("maturity", "SEMIANNUAL_MATURITY_DATE_PRESERVED")):
        with pytest.raises(ValueError, match="QUARTERLY_POLICY_RULESET_MISMATCH"):
            OperatingCalendarPolicy.from_dict({**v1_raw, field: value})
    assert OperatingCalendarPolicy.from_dict(v1_raw) == V1 and OperatingCalendarPolicy.from_dict(raw) == V2
    assert quarterly_candidate_policy() == V2 and V2.date_authoritative and not V1.date_authoritative
    assert V1.cache_key() != V2.cache_key()


def test_helper_matches_the_released_axis_for_every_cod():
    for fc, months in _cases():
        engine = s6(fc, months, 4)
        assert semiannual_row_ends(engine.operating_start, 8) == tuple(p.end_date for p in engine.operation_periods())


# ── explicit economic end date: a properly dated final quarterly stub ──────────────

def q_end(fc, months, horizon, end, ppa=1, policy=V2):
    return PeriodEngine(fc, months, horizon, ppa, frequency=Q, operating_calendar_policy=policy, economic_end_date=end)


@pytest.mark.parametrize("end,stub_days", [(date(2032, 10, 17), 17), (date(2032, 11, 30), 61), (date(2032, 7, 2), 2), (date(2032, 12, 31), 92),
                                           (date(2032, 1, 15), 15)])
def test_explicit_end_date_gives_an_exactly_dated_final_stub_inside_the_last_model_year(end, stub_days):
    default = q2(date(2027, 4, 17), 12, 5)
    engine = q_end(date(2027, 4, 17), 12, 5, end)
    ops = list(engine.operation_periods())
    assert engine.economic_end_date == end and ops[-1].end_date == end
    assert ops[-1].start_date == oracle_quarter_ends_between(date(2027, 4, 17), end)[-2] if stub_days != 15 else ops[-1].start_date == date(2031, 12, 31)
    assert (ops[-1].end_date - ops[-1].start_date).days == stub_days
    # contiguous rows, one clock: every stub row belongs to the final model year (5) like the six-month row it lies in
    assert all(a.end_date == b.start_date for a, b in zip(ops, ops[1:]))
    assert ops[-1].year_index == 5 and all(p.year_index == d.year_index for p, d in zip(ops, default.operation_periods()))
    # the stub never starts at or after its own end, and the earlier rows are the default rows
    assert all(p.start_date < p.end_date for p in ops)
    assert [p.end_date for p in ops[:-1]] == [p.end_date for p in default.operation_periods()][:len(ops) - 1]
    # day fraction is days / 365|366 of the year of the end date (D-02 candidate), never a quarter
    assert ops[-1].days_in_period == stub_days
    assert ops[-1].day_fraction == pytest.approx(stub_days / (366 if pycal.isleap(end.year) else 365))


def test_explicit_end_equal_to_the_default_changes_nothing_but_the_cache_key():
    default = q2(date(2027, 4, 17), 12, 5)
    same = q_end(date(2027, 4, 17), 12, 5, default.economic_end_date)
    assert [(p.start_date, p.end_date, p.year_index) for p in same.periods()] == [(p.start_date, p.end_date, p.year_index) for p in default.periods()]
    assert hash_engine_for_cache(same) != hash_engine_for_cache(default)
    assert hash_engine_for_cache(q_end(date(2027, 4, 17), 12, 5, date(2032, 10, 17))) != hash_engine_for_cache(same)


def test_one_day_terminal_stub_is_refused_by_the_validator():
    with pytest.raises(ValueError, match="TERMINAL_STUB"):
        q_end(date(2027, 4, 17), 12, 5, date(2032, 7, 1))             # Jun 30 + 1 day


@pytest.mark.parametrize("end", [date(2031, 12, 31), date(2031, 6, 30), date(2033, 1, 1), date(2040, 1, 1), date(2028, 4, 17)])
def test_explicit_end_outside_the_final_model_year_is_refused(end):
    with pytest.raises(ValueError, match="ECONOMIC_END_DATE_OUTSIDE_FINAL_MODEL_YEAR"):
        q_end(date(2027, 4, 17), 12, 5, end)


def test_explicit_end_requires_the_date_authoritative_policy_and_a_date():
    with pytest.raises(ValueError, match="REQUIRES_DATE_AUTHORITATIVE_POLICY"):
        q_end(date(2027, 4, 17), 12, 5, date(2032, 10, 17), policy=V1)
    with pytest.raises(ValueError, match="REQUIRES_DATE_AUTHORITATIVE_POLICY"):
        PeriodEngine(date(2027, 4, 17), 12, 5, 1, frequency=S, economic_end_date=date(2032, 10, 17))
    with pytest.raises(ValueError, match="ECONOMIC_END_DATE_INVALID"):
        q_end(date(2027, 4, 17), 12, 5, "2032-10-17")


def test_explicit_end_in_a_one_year_horizon():
    engine = q_end(date(2027, 1, 1), 12, 1, date(2028, 9, 15))
    ops = list(engine.operation_periods())
    assert ops[-1].end_date == date(2028, 9, 15) and {p.year_index for p in ops} == {1}
