"""WF-23: released six-month authority vs NON-PRODUCTION calendar experiments."""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from finco_core.engine.period_engine import (
    PeriodAxisConvention, PeriodEngine, PeriodFrequency, validate_canonical_period_axis,
)
from tools.period_frequency_shadow import (
    EventPosition, FractionRule, HorizonRule, ShadowPolicy, StubRule,
    add_months, build_shadow_calendar, coarse_geometry, event_position,
)


def policy(months=6, *, source=False, keep_stub=False, exact_horizon=False, inclusive=True):
    return ShadowPolicy(months=months,
        stub=StubRule.KEEP_COD if keep_stub else StubRule.ROLL_UNDER_SEVEN_DAYS,
        fraction=FractionRule.LEGACY_H2_NEXT_YEAR if source else FractionRule.END_YEAR_ACTUAL,
        cod_first_day_inclusive=inclusive,
        horizon=HorizonRule.COD_ANNIVERSARY if exact_horizon else HorizonRule.FIXED_PERIOD_COUNT)


def axis(cod=date(2028, 6, 30), months=6, **kwargs):
    return build_shadow_calendar(cod=cod, horizon_years=2, policy=policy(months, **kwargs))


@pytest.mark.parametrize('source', [False, True])
@pytest.mark.parametrize('fc,months', [
    (date(2027, 6, 30), 12), (date(2027, 6, 29), 12),
    (date(2027, 6, 23), 12), (date(2027, 6, 24), 12),
    (date(2027, 1, 1), 12), (date(2028, 1, 31), 1),
    (date(2028, 2, 29), 13), (date(2029, 1, 31), 17),
    (date(2027, 12, 30), 12), (date(2027, 3, 17), 5),
])
def test_released_semesters_match_independent_rational_geometry_exactly(source, fc, months):
    cod = add_months(fc, months)
    convention = (PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN if source
                  else PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS)
    engine = PeriodEngine(fc, months, 3, 1.25, cod_date=cod, period_axis_convention=convention)
    shadow = build_shadow_calendar(cod=cod, horizon_years=3, policy=policy(source=source))
    assert len(shadow.rows) == len(engine.operation_periods()) == 6
    for expected, actual in zip(shadow.rows, engine.operation_periods(), strict=True):
        assert (actual.start_date, actual.end_date, actual.days_in_period) == (
            expected.start, expected.end, expected.accrual_days)
        assert actual.day_fraction == float(expected.year_fraction)  # exact, not approximate
        assert (actual.year_index, actual.operating_year_index, actual.period_in_year,
                actual.operating_period_index) == (
                    expected.model_year, expected.model_year, expected.slot, expected.position)
    assert engine.cod == cod  # a rolled operating boundary never replaces actual COD
    assert engine.horizon_end == shadow.rows[-1].end
    assert all(p.is_ppa_active == (p.start_date < engine.ppa_end) for p in engine.operation_periods())
    validate_canonical_period_axis(engine.periods(), expected_operating_periods=6,
                                  cod_date=cod, period_convention=convention)


@pytest.mark.parametrize('months', [3, 6])
@pytest.mark.parametrize('cod', [date(2028, 1, 1), date(2028, 2, 29), date(2028, 3, 30),
                               date(2028, 6, 30), date(2029, 12, 31)])
def test_shadow_explicit_calendars_are_contiguous_and_immutable(months, cod):
    shadow = axis(cod, months, keep_stub=True, inclusive=False)
    assert shadow.classification == 'SHADOW_NOT_FINANCIAL_RUN'
    assert len(shadow.rows) == 24 // months
    for i, row in enumerate(shadow.rows):
        assert row.position == i and row.end > row.start
        assert row.accrual_days == (row.end - row.start).days
        assert row.slot == i % (12 // months) + 1
        assert row.model_year == i // (12 // months) + 1
        if i:
            assert row.start == shadow.rows[i - 1].end
    with pytest.raises(FrozenInstanceError):
        shadow.rows[0].start = cod
    assert not hasattr(shadow.rows[0], 'period_index') and not hasattr(shadow.rows[0], 'is_operation')


def test_stub_and_horizon_choices_are_visible_not_silently_decided():
    cod = date(2028, 3, 30)
    kept = axis(cod, 3, keep_stub=True, inclusive=False)
    rolled = axis(cod, 3, inclusive=False)
    assert kept.actual_cod == rolled.actual_cod == cod
    assert kept.rows[0].accrual_days == 1 and kept.rows[0].start == cod
    assert rolled.rows[0].start == date(2028, 3, 31)
    # Fixed count and exact COD anniversary differ even with identical frequency.
    fixed = axis(date(2028, 4, 17), 3, keep_stub=True)
    dated = axis(date(2028, 4, 17), 3, keep_stub=True, exact_horizon=True)
    assert fixed.rows[-1].end == date(2030, 3, 31)
    assert dated.rows[-1].end == date(2030, 4, 17)
    assert len(dated.rows) == len(fixed.rows) + 1


def test_leap_year_and_first_day_rules_are_separate_from_senior_interest():
    from financial_engine.senior_debt.interest import period_day_fraction
    from financial_engine.senior_debt.policy import DayCountConvention
    included = axis(date(2028, 1, 1), 3, keep_stub=True)
    excluded = axis(date(2028, 1, 1), 3, keep_stub=True, inclusive=False)
    a, b = included.rows[0], excluded.rows[0]
    assert a.end == b.end == date(2028, 3, 31)
    assert a.accrual_days == 91 and b.accrual_days == 90
    assert a.year_fraction == Fraction(91, 366)
    assert period_day_fraction(a.start, a.end, DayCountConvention.ACT_360) == 90 / 360
    assert period_day_fraction(a.start, a.end, DayCountConvention.ACT_365) == 90 / 365
    # H2 metadata uses the next year's leap status only under the released source convention.
    source = axis(date(2027, 6, 30), source=True).rows[0]
    generic = axis(date(2027, 6, 30)).rows[0]
    assert source.year_fraction == Fraction(184, 366)
    assert generic.year_fraction == Fraction(184, 365)


@pytest.mark.parametrize('months', [1, 5, 13, 17])
def test_odd_month_construction_and_month_end_interest_remain_existing_authority(months):
    from financial_engine.construction.adapter import _compute_interest_fraction
    from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention
    fc = date(2028, 1, 31)
    cod = add_months(fc, months)
    assert PeriodEngine(fc, months, 2, 1, cod_date=cod).cod == cod
    assert add_months(fc, 1) == date(2028, 2, 29)
    assert add_months(fc, 2) == date(2028, 3, 31)
    assert _compute_interest_fraction(date(2028, 2, 1), date(2028, 2, 29),
        SeniorDayCountConvention.ACT_360, 0, ()) == 29 / 360  # inclusive construction authority


def test_four_frequency_pairs_have_geometry_not_financial_permission():
    q = axis(date(2028, 1, 1), 3, keep_stub=True, exact_horizon=True, inclusive=False)
    h = axis(date(2028, 1, 1), 6, keep_stub=True, exact_horizon=True, inclusive=False)
    assert coarse_geometry(fine=q, coarse=q) == tuple((i,) for i in range(len(q.rows)))
    assert coarse_geometry(fine=h, coarse=h) == tuple((i,) for i in range(len(h.rows)))
    grouped = coarse_geometry(fine=q, coarse=h)
    assert grouped[:2] == ((0, 1), (2, 3))
    assert tuple(i for group in grouped for i in group) == tuple(range(len(q.rows)))
    with pytest.raises(ValueError, match='DISAGGREGATION_POLICY_REQUIRED'):
        coarse_geometry(fine=h, coarse=q)


def test_mixed_grids_refuse_different_horizons_and_uncovered_rows():
    q = axis(date(2028, 4, 17), 3, keep_stub=True)
    h = axis(date(2028, 4, 17), 6, keep_stub=True)
    assert q.rows[-1].end != h.rows[-1].end
    with pytest.raises(ValueError, match='HORIZON_OR_STUB_MISMATCH'):
        coarse_geometry(fine=q, coarse=h)
    broken = replace(q, rows=(q.rows[0], q.rows[0], *q.rows[2:]))
    with pytest.raises(ValueError, match='SHADOW_AXIS'):
        coarse_geometry(fine=broken, coarse=q)


def test_ppa_expiry_and_nondivisible_debt_tenor_are_not_moved_to_a_boundary():
    q = axis(date(2028, 6, 30), 3)
    maturity = add_months(q.actual_cod, 17)
    assert maturity == date(2029, 11, 30)
    assert event_position(q, maturity) is EventPosition.WITHIN_PERIOD
    assert event_position(q, date(2029, 9, 30)) is EventPosition.BOUNDARY
    assert event_position(q, date(2028, 5, 15)) is EventPosition.BEFORE_AXIS
    assert event_position(q, date(2031, 1, 1)) is EventPosition.AFTER_AXIS
    assert event_position(q, date(2029, 7, 15)) is EventPosition.WITHIN_PERIOD  # PPA expiry, not whole-period sales


@pytest.mark.parametrize('months', [3, 6])
def test_existing_statement_rollup_sums_flows_and_retains_last_stock(months):
    from app.workbook.runtime_projection import aggregate_to_annual
    shadow = axis(date(2027, 12, 31), months, inclusive=False)
    rows = [dict(key='flow', label='Flow', is_stock=False, values=[Decimal('12.5')] * len(shadow.rows)),
            dict(key='stock', label='Stock', is_stock=True, values=list(range(len(shadow.rows))))]
    rolled, years = aggregate_to_annual(rows, [r.end.isoformat()[:7] for r in shadow.rows])
    n = 12 // months
    assert years == ['2028', '2029']
    assert rolled[0]['values'] == [Decimal('12.5') * n] * 2
    assert rolled[1]['values'] == [n - 1, 2 * n - 1]


@pytest.mark.parametrize('frequency', [PeriodFrequency.QUARTERLY, PeriodFrequency.ANNUAL])
def test_production_period_engine_still_rejects_unsupported_frequency(frequency):
    with pytest.raises(ValueError, match='PERIOD_AXIS_FREQUENCY_UNSUPPORTED'):
        PeriodEngine(date(2028, 1, 1), 12, 2, 1, frequency=frequency)


def test_clean_calendar_frequency_bridge_refuses_quarterly_production_admission():
    from app.project_factories import create_generic_solar_reference
    from finco_core.inputs import PeriodFrequency as InputFrequency
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.inputs import CalendarInput
    from financial_engine.orchestrator import _build_period_engine
    pi = create_generic_solar_reference()
    unapproved = replace(pi, info=replace(pi.info, period_frequency=InputFrequency.QUARTERLY))
    assert 'period_frequency' not in {f.name for f in fields(CalendarInput)}
    with pytest.raises(ValueError, match='CLEAN_CALENDAR_FREQUENCY_UNSUPPORTED'):
        from_project_inputs(unapproved)
    assert _build_period_engine(from_project_inputs(pi)).freq is PeriodFrequency.SEMESTRIAL


@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_shadow_study_cannot_change_six_month_canonical_financial_results(kind):
    from app import project_factories as pf
    from app.services import production_financial_authority as authority
    from finco_core.inputs import project_inputs_to_dict, hash_inputs_for_cache
    pi = getattr(pf, 'create_generic_' + kind + '_reference')()
    identity = hash_inputs_for_cache(pi)
    inputs = project_inputs_to_dict(pi)
    authority._POLICY_RUN_CACHE.clear()  # existing test discipline: force both canonical evaluations
    before = asdict(authority.run_clean_production(pi))
    for months in (3, 6):
        shadow = axis(pi.info.cod_date, months)
        assert shadow.classification == 'SHADOW_NOT_FINANCIAL_RUN'
    assert project_inputs_to_dict(pi) == inputs and hash_inputs_for_cache(pi) == identity
    authority._POLICY_RUN_CACHE.clear()
    after = asdict(authority.run_clean_production(pi))
    assert after == before  # every unrounded financial field; no tolerance or golden refresh


@pytest.mark.parametrize('change', [{'months':True}, {'months':12}, {'stub':'KEEP_COD'},
    {'fraction':'END_YEAR_ACTUAL'}, {'horizon':'FIXED_PERIOD_COUNT'}, {'cod_first_day_inclusive':1},
    {'months':3, 'fraction':FractionRule.LEGACY_H2_NEXT_YEAR}])
def test_shadow_rejects_untyped_or_unauthorized_convention_inference(change):
    values = dict(months=6, stub=StubRule.KEEP_COD, fraction=FractionRule.END_YEAR_ACTUAL,
                  horizon=HorizonRule.FIXED_PERIOD_COUNT, cod_first_day_inclusive=False)
    with pytest.raises(ValueError):
        ShadowPolicy(**{**values, **change})


def test_shadow_module_has_no_production_imports_or_runtime_consumers():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'tools/period_frequency_shadow.py').read_text(encoding='utf-8'))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert modules <= {'__future__', 'calendar', 'dataclasses', 'datetime', 'enum', 'fractions'}
    for directory in ('app', 'finco_core', 'financial_engine', 'domain'):
        assert not any('period_frequency_shadow' in path.read_text(encoding='utf-8')
                       for path in (root / directory).rglob('*.py'))
