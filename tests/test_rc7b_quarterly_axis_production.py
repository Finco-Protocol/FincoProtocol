"""RC-7B Workstream A: production quarterly period axis and frequency authority.

Expected values are derived independently (calendar arithmetic + exact Fraction),
never from the engine under test. Admission remains closed elsewhere; nothing
here is owner approval of the candidate conventions.
"""
from __future__ import annotations

import calendar as pycal
import dataclasses
from datetime import date, timedelta
from fractions import Fraction

import pytest
from dateutil.relativedelta import relativedelta

from finco_core.engine.calendar_policy import (
    QUARTERLY_CANDIDATE_POLICY_VERSION, OperatingCalendarPolicy, quarterly_candidate_policy,
)
from finco_core.engine.period_engine import (
    PeriodAxisConvention, PeriodEngine, PeriodFrequency, PeriodMeta,
    hash_engine_for_cache, validate_canonical_period_axis,
)

Q = PeriodFrequency.QUARTERLY
S = PeriodFrequency.SEMESTRIAL


def quarterly(fc, months, horizon=2, ppa=1, policy=None, **kw):
    return PeriodEngine(fc, months, horizon, ppa, frequency=Q,
                        operating_calendar_policy=policy or quarterly_candidate_policy(), **kw)


# ── independent oracle ────────────────────────────────────────────────────────

def _quarter_end_after(d):
    candidates = [date(d.year, m, pycal.monthrange(d.year, m)[1]) for m in (3, 6, 9, 12)]
    candidates.append(date(d.year + 1, 3, 31))
    return min(c for c in candidates if c > d)


def oracle_operating_rows(fc, months, horizon, ppa):
    cod = fc + relativedelta(months=months)
    ppa_end = cod + relativedelta(years=ppa)
    rows, start = [], cod
    for k in range(4 * horizon):
        end = _quarter_end_after(start)
        days = (end - start).days
        denom = 366 if pycal.isleap(end.year) else 365
        rows.append(dict(start=start, end=end, days=days, fraction=Fraction(days, denom),
                         year=k // 4 + 1, slot=k % 4 + 1, ppa=start < ppa_end, op_index=k))
        start = end
    return cod, rows


def in_roll_window(cod):
    boundary = date(cod.year, 6, 30) if cod.month <= 6 else date(cod.year, 12, 31)
    return 0 < (boundary - cod).days < 7


FCS = [date(2027, 1, 1), date(2027, 8, 31), date(2028, 2, 29), date(2027, 12, 31),
       date(2030, 1, 1), date(2029, 12, 31), date(2028, 5, 31), date(2031, 3, 30)]
MONTHS = [1, 5, 12, 13, 14, 15, 17, 24]


def _cases():
    for fc in FCS:
        for months in MONTHS:
            if not in_roll_window(fc + relativedelta(months=months)):
                yield fc, months


@pytest.mark.parametrize("fc,months", list(_cases()))
@pytest.mark.parametrize("horizon", [1, 3])
def test_quarterly_operating_rows_match_independent_rational_geometry(fc, months, horizon):
    engine = quarterly(fc, months, horizon, ppa=2)
    cod, expected = oracle_operating_rows(fc, months, horizon, 2)
    ops = engine.operation_periods()
    assert engine.cod == cod and engine.operating_start == cod
    assert len(ops) == 4 * horizon == len(expected)
    for p, e in zip(ops, expected):
        assert (p.start_date, p.end_date, p.days_in_period) == (e["start"], e["end"], e["days"])
        assert p.day_fraction == float(e["fraction"])  # correctly-rounded, exact equality
        assert p.is_leap_year is pycal.isleap(e["end"].year)
        assert (p.year_index, p.period_in_year, p.operating_year_index) == (e["year"], e["slot"], e["year"])
        assert p.operating_period_index == e["op_index"] and p.is_ppa_active is e["ppa"]
    # Total operating days conserve the calendar span; no day is gained or lost.
    assert sum(p.days_in_period for p in ops) == (ops[-1].end_date - cod).days
    assert engine.horizon_end == expected[-1]["end"]


@pytest.mark.parametrize("fc,months", list(_cases()))
def test_construction_columns_are_identical_to_the_released_six_month_axis(fc, months):
    q = quarterly(fc, months)
    s = PeriodEngine(fc, months, 2, 1, frequency=S)
    assert [p for p in q.periods() if p.is_construction] == [p for p in s.periods() if p.is_construction]


def test_one_day_initial_stub_is_retained_not_rolled():
    # FC + 3 months = 30 Mar 2031; the next quarter end is 31 Mar 2031.
    engine = quarterly(date(2030, 12, 30), 3, 1)
    first = engine.operation_periods()[0]
    assert (first.start_date, first.end_date, first.days_in_period) == (date(2031, 3, 30), date(2031, 3, 31), 1)
    assert first.day_fraction == 1 / 365
    assert len(engine.operation_periods()) == 4  # stub counts as a model-year row (D-03/D-04 candidate)


def test_cod_on_first_of_month_is_half_open_without_inclusive_day():
    engine = quarterly(date(2030, 1, 1), 15, 1)  # COD 1 Apr 2031
    first = engine.operation_periods()[0]
    assert (first.start_date, first.end_date, first.days_in_period) == (date(2031, 4, 1), date(2031, 6, 30), 90)
    semi = PeriodEngine(date(2030, 1, 1), 15, 1, 1, frequency=S).operation_periods()[0]
    assert semi.days_in_period == (semi.end_date - semi.start_date).days + 1  # released rule unchanged


def test_leap_year_denominators_follow_period_end_year():
    engine = quarterly(date(2027, 1, 31), 11, 2)  # COD 31 Dec 2027
    rows = {p.end_date: p for p in engine.operation_periods()}
    assert rows[date(2028, 3, 31)].day_fraction == 91 / 366
    assert rows[date(2028, 3, 31)].is_leap_year is True
    assert rows[date(2029, 3, 31)].day_fraction == 90 / 365


@pytest.mark.parametrize("cod_offset", [1, 2, 6])
@pytest.mark.parametrize("boundary", [date(2031, 6, 30), date(2031, 12, 31)])
def test_released_roll_window_is_refused_pending_d01(boundary, cod_offset):
    cod = boundary - timedelta(days=cod_offset)
    fc = cod - relativedelta(months=12)
    if fc + relativedelta(months=12) != cod:
        pytest.skip("month-end clamping changes the COD")
    with pytest.raises(ValueError, match="QUARTERLY_COD_ROLL_WINDOW_PENDING_D01"):
        quarterly(fc, 12)


@pytest.mark.parametrize("cod", [date(2031, 6, 30), date(2031, 6, 23), date(2031, 3, 29), date(2031, 9, 29)])
def test_outside_roll_window_or_at_quarter_boundaries_is_accepted(cod):
    engine = quarterly(cod - relativedelta(months=12), 12)
    assert engine.cod == cod


def test_unsupported_frequency_combinations_fail_closed():
    with pytest.raises(ValueError, match="PERIOD_AXIS_FREQUENCY_UNSUPPORTED"):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=Q)  # no policy: unchanged rejection
    with pytest.raises(ValueError, match="PERIOD_AXIS_FREQUENCY_UNSUPPORTED"):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=PeriodFrequency.ANNUAL)
    with pytest.raises(ValueError, match="QUARTERLY_POLICY_FREQUENCY_MISMATCH"):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=S, operating_calendar_policy=quarterly_candidate_policy())
    with pytest.raises(ValueError, match="QUARTERLY_POLICY_FREQUENCY_MISMATCH"):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=PeriodFrequency.ANNUAL,
                     operating_calendar_policy=quarterly_candidate_policy())
    with pytest.raises(ValueError, match="QUARTERLY_PERIOD_AXIS_CONVENTION_UNSUPPORTED"):
        quarterly(date(2028, 1, 1), 12,
                  period_axis_convention=PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN)
    with pytest.raises(ValueError, match="QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED"):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=Q,
                     operating_calendar_policy=quarterly_candidate_policy().to_dict())


# ── typed, versioned policy contract ─────────────────────────────────────────

def test_policy_round_trip_is_strict_and_complete():
    policy = quarterly_candidate_policy()
    raw = policy.to_dict()
    assert raw["version"] == QUARTERLY_CANDIDATE_POLICY_VERSION
    assert OperatingCalendarPolicy.from_dict(raw) == policy
    assert policy.periods_per_year == 4
    for bad in ({k: v for k, v in raw.items() if k != "stub"}, {**raw, "extra": 1},
                {**raw, "version": "rc7b-quarterly-candidate-v0"}, {**raw, "stub": "ROLL_UNDER_SEVEN_DAYS"},
                {**raw, "operating_months": 3.0}, {**raw, "operating_months": True}, list(raw.items()), None):
        with pytest.raises(ValueError):
            OperatingCalendarPolicy.from_dict(bad)


@pytest.mark.parametrize("operating,debt", [(3, 6), (6, 3), (6, 6), (12, 12), (1, 1)])
def test_mixed_and_non_quarterly_pairs_are_refused(operating, debt):
    raw = {**quarterly_candidate_policy().to_dict(), "operating_months": operating, "debt_service_months": debt}
    with pytest.raises(ValueError, match="QUARTERLY_MATCHED_3_3_REQUIRED"):
        OperatingCalendarPolicy.from_dict(raw)


def test_policy_is_immutable_and_enum_typed():
    policy = quarterly_candidate_policy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.version = "x"  # type: ignore[misc]
    with pytest.raises(ValueError, match="QUARTERLY_EXPLICIT_POLICY_REQUIRED"):
        dataclasses.replace(policy, stub="KEEP_ACTUAL_COD")


# ── canonical validator ──────────────────────────────────────────────────────

def _validate(periods, ppy, cod):
    validate_canonical_period_axis(periods, expected_operating_periods=sum(p.is_operation for p in periods),
                                   cod_date=cod, period_convention=PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS,
                                   periods_per_year=ppy)


def test_validator_counters_are_frequency_explicit():
    engine = quarterly(date(2030, 1, 1), 15, 2)
    periods = engine.periods()
    _validate(periods, 4, engine.cod)
    with pytest.raises(ValueError, match="PERIOD_AXIS_OPERATING_YEAR_INDEX_INVALID|PERIOD_AXIS_PERIOD_IN_YEAR_INVALID"):
        _validate(periods, 2, engine.cod)
    for ppy in (3, 12, 2.0, True):
        with pytest.raises(ValueError, match="PERIOD_AXIS_PERIODS_PER_YEAR_UNSUPPORTED"):
            _validate(periods, ppy, engine.cod)
    semi = PeriodEngine(date(2030, 1, 1), 15, 2, 1, frequency=S)
    with pytest.raises(ValueError):
        _validate(semi.periods(), 4, semi.cod)


@pytest.mark.parametrize("mutation", ["duplicate", "gap", "slot", "year", "fraction", "leap", "extra_day"])
def test_validator_rejects_mutated_quarterly_rows(mutation):
    engine = quarterly(date(2030, 1, 1), 15, 2)
    rows = list(engine.periods())
    k = len(rows) - 3
    p = rows[k]
    if mutation == "duplicate":
        rows[k] = dataclasses.replace(p, index=rows[k - 1].index)
    elif mutation == "gap":
        rows[k] = dataclasses.replace(p, start_date=p.start_date + timedelta(days=1),
                                      days_in_period=p.days_in_period - 1,
                                      day_fraction=(p.days_in_period - 1) / (366.0 if p.is_leap_year else 365.0))
    elif mutation == "slot":
        rows[k] = dataclasses.replace(p, period_in_year=(p.period_in_year % 4) + 1)
    elif mutation == "year":
        rows[k] = dataclasses.replace(p, operating_year_index=p.operating_year_index + 1)
    elif mutation == "fraction":
        rows[k] = dataclasses.replace(p, day_fraction=p.days_in_period / 360.0)
    elif mutation == "leap":
        rows[k] = dataclasses.replace(p, is_leap_year=not p.is_leap_year)
    elif mutation == "extra_day":
        rows[k] = dataclasses.replace(p, days_in_period=p.days_in_period + 1)
    with pytest.raises(ValueError):
        _validate(tuple(rows), 4, engine.cod)


def test_cache_identity_keeps_six_month_key_and_separates_quarterly():
    semi = PeriodEngine(date(2030, 1, 1), 15, 2, 1, frequency=S)
    assert len(hash_engine_for_cache(semi)) == 7  # released key shape unchanged
    q = quarterly(date(2030, 1, 1), 15, 2)
    assert hash_engine_for_cache(q)[:4] == hash_engine_for_cache(semi)[:4]
    assert hash_engine_for_cache(q) != hash_engine_for_cache(semi)
    assert ("operating_calendar_policy", quarterly_candidate_policy().cache_key()) in hash_engine_for_cache(q)


def test_period_meta_contract_is_unchanged():
    assert [f.name for f in dataclasses.fields(PeriodMeta)] == [
        "index", "start_date", "end_date", "year_index", "period_in_year", "is_construction",
        "is_operation", "is_ppa_active", "days_in_period", "day_fraction", "is_leap_year",
        "operating_period_index", "operating_year_index"]


# ── typed project timeline, serialization and clean bridge ───────────────────

def _quarterly_solar(policy=None):
    from app.project_factories import create_generic_solar_reference
    from finco_core.inputs import PeriodFrequency as F
    from finco_core.inputs._models import QuarterlyProjectInfo
    pi = create_generic_solar_reference()
    values = {f.name: getattr(pi.info, f.name) for f in dataclasses.fields(pi.info)}
    values["period_frequency"] = F.QUARTERLY
    info = QuarterlyProjectInfo(**values, operating_calendar_policy=policy or quarterly_candidate_policy())
    return pi, dataclasses.replace(pi, info=info)


def test_quarterly_project_info_is_an_explicit_subtype():
    from finco_core.inputs import PeriodFrequency as F, ProjectInfo
    from finco_core.inputs._models import QuarterlyProjectInfo
    pi, q = _quarterly_solar()
    assert type(pi.info) is ProjectInfo and isinstance(q.info, QuarterlyProjectInfo)
    values = {f.name: getattr(pi.info, f.name) for f in dataclasses.fields(pi.info)}
    with pytest.raises(ValueError, match="QUARTERLY_PROJECT_INFO_FREQUENCY_MISMATCH"):
        QuarterlyProjectInfo(**values, operating_calendar_policy=quarterly_candidate_policy())
    with pytest.raises(ValueError, match="QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED"):
        QuarterlyProjectInfo(**{**values, "period_frequency": F.QUARTERLY}, operating_calendar_policy=None)


def test_serialization_round_trips_quarterly_and_keeps_legacy_bytes():
    import json
    from finco_core.inputs import project_inputs_from_dict, project_inputs_to_dict
    pi, q = _quarterly_solar()
    legacy = project_inputs_to_dict(pi)
    assert "operating_calendar_policy" not in legacy["info"]
    assert project_inputs_from_dict(legacy) == pi
    raw = project_inputs_to_dict(q)
    assert raw["info"]["operating_calendar_policy"] == quarterly_candidate_policy().to_dict()
    assert project_inputs_from_dict(json.loads(json.dumps(raw))) == q
    tampered = json.loads(json.dumps(raw))
    tampered["info"]["operating_calendar_policy"]["debt_service_months"] = 6
    with pytest.raises(ValueError, match="QUARTERLY_MATCHED_3_3_REQUIRED"):
        project_inputs_from_dict(tampered)
    mismatched = json.loads(json.dumps(raw))
    mismatched["info"]["period_frequency"] = "Semestrial"
    with pytest.raises(ValueError, match="QUARTERLY_PROJECT_INFO_FREQUENCY_MISMATCH"):
        project_inputs_from_dict(mismatched)


def test_cache_key_is_unchanged_for_six_month_and_distinct_for_quarterly():
    from finco_core.inputs import hash_inputs_for_cache
    pi, q = _quarterly_solar()
    assert hash_inputs_for_cache(q)[:-1] == hash_inputs_for_cache(pi)
    assert hash_inputs_for_cache(q)[-1][0] == "OPERATING_CALENDAR"


def test_clean_bridge_transmits_frequency_or_fails_closed():
    from finco_core.inputs import PeriodFrequency as F
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.inputs import CalendarInput, QuarterlyCalendarInput
    from financial_engine.provenance import compute_input_fingerprint
    pi, q = _quarterly_solar()
    semi_clean, quarter_clean = from_project_inputs(pi), from_project_inputs(q)
    assert type(semi_clean.calendar) is CalendarInput
    assert type(quarter_clean.calendar) is QuarterlyCalendarInput
    assert quarter_clean.calendar.operating_calendar_policy == quarterly_candidate_policy()
    assert compute_input_fingerprint(semi_clean) != compute_input_fingerprint(quarter_clean)
    for frequency in (F.QUARTERLY, F.ANNUAL):
        unapproved = dataclasses.replace(pi, info=dataclasses.replace(pi.info, period_frequency=frequency))
        with pytest.raises(ValueError, match="QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED|PERIOD_FREQUENCY_UNSUPPORTED_AT_CLEAN_BRIDGE"):
            from_project_inputs(unapproved)


def test_clean_quarterly_calendar_requires_typed_policy():
    from financial_engine.inputs import PeriodAxisConvention as C, QuarterlyCalendarInput
    base = dict(financial_close=date(2030, 1, 1), construction_months=15, horizon_years=2, ppa_years=1.0,
                cod_date=date(2031, 4, 1))
    with pytest.raises(ValueError, match="QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED"):
        QuarterlyCalendarInput(**base, operating_calendar_policy=quarterly_candidate_policy().to_dict())
    with pytest.raises(ValueError, match="QUARTERLY_PERIOD_AXIS_CONVENTION_UNSUPPORTED"):
        QuarterlyCalendarInput(**base, period_axis_convention=C.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN,
                               operating_calendar_policy=quarterly_candidate_policy())
