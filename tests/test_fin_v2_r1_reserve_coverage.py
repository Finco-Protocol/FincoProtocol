"""FIN-V2-R1 — forward-looking Cash DSRA requirement, typed reserve authority and coverage evidence.

Oracles are INDEPENDENT of the production helper: calendar arithmetic is re-derived with day sets and
``calendar`` month lengths, never with ``add_months_eom`` / ``compute_forward_coverage``.
"""
from __future__ import annotations

import calendar
import dataclasses as dc
import json
import math
from datetime import date, timedelta

import pytest

from financial_engine.dsra.forward_coverage import (
    CoverageConvention as C,
    CoverageStatus as S,
    POLICY_VERSION,
    ReserveRequirementKind as K,
    add_months_eom,
    compute_forward_coverage,
)
from financial_engine.dsra.reserve_authority import (
    CODE_AUTOMATIC_NOT_REALISED,
    CODE_CALENDAR_FUNDING_GATED,
    CODE_GATED_MODE,
    CODE_UNRECOGNISED,
    ReserveActivation as A,
    ReserveAuthorityError,
    ReservePolicyKind as RK,
    ReservePolicyVersion as RV,
    assert_selection_realised,
    classify_financing,
    selection_from_editor,
)
from financial_engine.dsra.target import (
    DsraTargetPolicy,
    build_dsra_required_balance_schedule,
)

# ── independent oracle ──────────────────────────────────────────────────────────────────────────

def oracle_add_months(d: date, m: int) -> date:
    """EOM-preserving month addition, derived from month lengths only."""
    is_last = (d + timedelta(days=1)).month != d.month
    total = d.year * 12 + d.month - 1 + m
    y, mo = total // 12, total % 12 + 1
    length = calendar.monthrange(y, mo)[1]
    return date(y, mo, length if is_last else min(d.day, length))


def oracle_requirement(test: date, months: int, periods, convention) -> float:
    """periods: [(start, end, ds)] operating periods. Day-set evaluation of the documented convention."""
    window_end = oracle_add_months(test, months)
    window_days = {test.toordinal() + k for k in range(1, (window_end - test).days + 1)}  # days in (T, W]
    total = 0.0
    for start, end, ds in periods:
        if ds is None:
            raise AssertionError("oracle requires known debt service")
        if convention == "due":
            total += ds if end.toordinal() in window_days else 0.0
        else:
            period_days = {start.toordinal() + k for k in range(1, (end - start).days + 1)}  # days in (start, end]
            total += ds * len(period_days & window_days) / len(period_days)
    return total


def semi_axis(first_end=date(2031, 6, 30), n=8, cod=date(2031, 1, 1), stub_start=None):
    """Two construction periods then n semiannual operating periods ending 30-Jun / 31-Dec."""
    starts, ends, constr = [date(2029, 7, 1), cod], [cod, cod], [True, True]
    starts[0], ends[0] = date(2030, 1, 1), date(2030, 7, 1)
    starts[1], ends[1] = date(2030, 7, 1), cod
    prev = cod if stub_start is None else stub_start
    end = first_end
    for _ in range(n):
        starts.append(prev)
        ends.append(end)
        constr.append(False)
        prev = end
        end = oracle_add_months(end, 6)
    return list(range(len(starts))), starts, ends, constr


def ops(idx, starts, ends, constr, ds):
    return [(starts[i], ends[i], ds[i]) for i in range(len(idx)) if not constr[i]]


def run(idx, starts, ends, constr, ds, months, conv, maturity="auto"):
    if maturity == "auto":
        maturity = ends[-1]
    return compute_forward_coverage(
        period_indices=idx, period_start_dates=starts, period_end_dates=ends, is_construction=constr,
        senior_debt_service_keur=ds, coverage_months=months, convention=conv, senior_maturity_date=maturity)


DS = [0.0, 0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 650.0, 700.0, 800.0]  # unequal future service


# ── 1. month arithmetic ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("d", [date(2031, 6, 30), date(2031, 12, 31), date(2032, 2, 29), date(2031, 1, 31),
                               date(2031, 3, 1), date(2031, 5, 15), date(2030, 11, 30), date(2031, 8, 31)])
@pytest.mark.parametrize("m", [1, 3, 6, 9, 12, 18])
def test_add_months_matches_independent_oracle(d, m):
    assert add_months_eom(d, m) == oracle_add_months(d, m)


def test_eom_semiannual_chain_lands_on_period_ends():
    assert add_months_eom(date(2031, 12, 31), 6) == date(2032, 6, 30)
    assert add_months_eom(date(2032, 6, 30), 6) == date(2032, 12, 31)


# ── 2. 6 / 9 / 12 month requirements reconcile with hand values AND the oracle ──────────────────

HAND = {  # test date index 3 (31-Dec-2031, next DS 300 @30-Jun-32, then 400 @31-Dec-32, then 500)
    (6, C.DUE_DATE_WINDOW): 300.0,
    (9, C.DUE_DATE_WINDOW): 300.0,                       # only one payment is DUE within 9 months
    (12, C.DUE_DATE_WINDOW): 700.0,
    (6, C.PRORATED_PERIOD): 300.0,
    (9, C.PRORATED_PERIOD): 300.0 + 400.0 * 92 / 184,    # one full period + 92 of 184 days of the next
    (12, C.PRORATED_PERIOD): 700.0,
}


@pytest.mark.parametrize("months,conv", list(HAND))
def test_requirement_matches_hand_value_and_oracle(months, conv):
    idx, st, en, co = semi_axis()
    res = run(idx, st, en, co, DS, months, conv)
    row = next(r for r in res.rows if r.test_date == date(2031, 12, 31))
    assert row.status is S.COMPUTED
    assert row.required_keur == pytest.approx(HAND[(months, conv)], rel=1e-12)
    for r in res.rows:
        if r.status is S.COMPUTED or r.status is S.NO_FURTHER_DEBT_SERVICE:
            expected = oracle_requirement(r.test_date, months, ops(idx, st, en, co, DS),
                                          "due" if conv is C.DUE_DATE_WINDOW else "pro")
            assert r.required_keur == pytest.approx(expected, rel=1e-12, abs=1e-12), r.test_date


def test_nine_month_is_not_the_legacy_shortcut_when_future_service_differs():
    idx, st, en, co = semi_axis()
    legacy = build_dsra_required_balance_schedule(
        period_indices=tuple(idx), period_start_dates=tuple(st), period_end_dates=tuple(en),
        is_construction=tuple(co), senior_debt_service_keur=tuple(DS), coverage_months=9, periods_per_year=2)
    new = run(idx, st, en, co, DS, 9, C.PRORATED_PERIOD)
    # legacy = next_ds * 9*2/12 = 1.5 x next period; calendar = next + half of the one after.
    i = idx.index(3)
    assert legacy[i] == pytest.approx(DS[4] * 1.5)
    row = next(r for r in new.rows if r.test_period_index == 3)
    assert row.required_keur == pytest.approx(DS[4] + DS[5] * 0.5)
    assert abs(row.required_keur - legacy[i]) > 1.0


def test_six_month_due_date_window_reconciles_with_legacy_shortcut_for_semiannual():
    idx, st, en, co = semi_axis()
    legacy = build_dsra_required_balance_schedule(
        period_indices=tuple(idx), period_start_dates=tuple(st), period_end_dates=tuple(en),
        is_construction=tuple(co), senior_debt_service_keur=tuple(DS), coverage_months=6, periods_per_year=2)
    new = run(idx, st, en, co, DS, 6, C.DUE_DATE_WINDOW)
    for r in new.rows:
        if not r.is_cod_test:
            assert r.required_keur == pytest.approx(legacy[idx.index(r.test_period_index)], abs=1e-9)


# ── 3. FORWARD vs PEAK_FORWARD are distinct ─────────────────────────────────────────────────────

def test_forward_moves_peak_forward_is_constant_while_service_is_due():
    idx, st, en, co = semi_axis()
    res = run(idx, st, en, co, DS, 12, C.DUE_DATE_WINDOW)
    fwd = [r for r in res.required_schedule(K.FORWARD)]
    pk = res.required_schedule(K.PEAK_FORWARD)
    assert len({round(x, 9) for x in fwd if x}) > 1
    peak = max(fwd)
    assert res.peak_required_keur == pytest.approx(peak)
    assert [p for p, f in zip(pk, fwd) if f > 0] == [peak] * sum(1 for f in fwd if f > 0)
    assert all(p == 0.0 for p, f in zip(pk, fwd) if f == 0.0)
    assert fwd != list(pk)


# ── 4. required edge cases ──────────────────────────────────────────────────────────────────────

def test_cod_test_row_is_the_initial_requirement_and_construction_has_no_target():
    idx, st, en, co = semi_axis()
    res = run(idx, st, en, co, DS, 6, C.DUE_DATE_WINDOW)
    cod = [r for r in res.rows if r.is_cod_test]
    assert len(cod) == 1 and cod[0].test_period_index == 1 and cod[0].test_date == date(2031, 1, 1)
    assert cod[0].required_keur == pytest.approx(DS[2])
    assert [r.test_period_index for r in res.rows if not r.is_cod_test] == [i for i in idx if not co[i]]


def test_short_first_operating_period_is_prorated_by_actual_days_not_by_period_count():
    # COD 1-Mar-2031, first operating period ends 30-Jun-2031 (121 days, a stub).
    idx, st, en, co = semi_axis(first_end=date(2031, 6, 30), cod=date(2031, 3, 1))
    ds = [0, 0, 60.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0]
    res = run(idx, st, en, co, ds, 9, C.PRORATED_PERIOD)
    cod = next(r for r in res.rows if r.is_cod_test)
    expected = oracle_requirement(date(2031, 3, 1), 9, ops(idx, st, en, co, ds), "pro")
    assert cod.required_keur == pytest.approx(expected, rel=1e-12)
    # window to 1-Dec-2031: stub fully + 154 of 184 days of the next period
    assert cod.required_keur == pytest.approx(60.0 + 200.0 * 154 / 184)
    assert cod.window_end == date(2031, 12, 1)


def test_irregular_calendar_boundaries_quarterly_then_odd_period():
    starts = [date(2031, 1, 1), date(2031, 4, 1), date(2031, 7, 1), date(2031, 12, 15), date(2032, 3, 31)]
    ends = [date(2031, 4, 1), date(2031, 7, 1), date(2031, 12, 15), date(2032, 3, 31), date(2032, 9, 30)]
    idx = [0, 1, 2, 3, 4]
    co = [True, False, False, False, False]
    ds = [0.0, 110.0, 230.0, 310.0, 470.0]
    for conv, tag in ((C.DUE_DATE_WINDOW, "due"), (C.PRORATED_PERIOD, "pro")):
        for months in (3, 6, 9, 12):
            res = run(idx, starts, ends, co, ds, months, conv)
            for r in res.rows:
                if r.required_keur is None:
                    continue
                assert r.required_keur == pytest.approx(
                    oracle_requirement(r.test_date, months, ops(idx, starts, ends, co, ds), tag), rel=1e-12, abs=1e-12)


def test_final_senior_payment_releases_requirement_to_a_legitimate_zero():
    idx, st, en, co = semi_axis(n=4)
    ds = [0, 0, 100.0, 200.0, 300.0, 400.0]
    res = run(idx, st, en, co, ds, 12, C.DUE_DATE_WINDOW)
    tail = res.rows[-1]
    assert tail.status is S.NO_FURTHER_DEBT_SERVICE and tail.required_keur == 0.0
    assert res.rows[-2].required_keur == pytest.approx(400.0)  # 1 payment left


def test_early_actual_extinguishment_drops_requirement_before_contractual_maturity():
    idx, st, en, co = semi_axis(n=8)
    ds = [0, 0, 100.0, 200.0, 300.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # paid off after the 3rd operating period
    res = run(idx, st, en, co, ds, 12, C.DUE_DATE_WINDOW, maturity=en[-1])
    by_date = {r.test_date: r for r in res.rows}
    assert by_date[en[4]].status is S.NO_FURTHER_DEBT_SERVICE and by_date[en[4]].required_keur == 0.0
    assert by_date[en[3]].required_keur == pytest.approx(300.0)
    assert res.peak_required_keur == pytest.approx(max(r.required_keur for r in res.rows))


def test_missing_future_debt_service_period_is_unavailable_never_zero():
    idx, st, en, co = semi_axis()
    ds = list(DS)
    ds[5] = None
    res = run(idx, st, en, co, ds, 12, C.DUE_DATE_WINDOW)
    hit = [r for r in res.rows if r.status is S.FUTURE_DEBT_SERVICE_MISSING]
    assert hit and all(r.required_keur is None for r in hit)
    # a window not touching the missing period is still computed
    assert any(r.status is S.COMPUTED for r in res.rows)
    assert res.peak_required_keur is None and res.peak_status is S.FUTURE_DEBT_SERVICE_MISSING
    assert all(p is None for p in res.required_schedule(K.PEAK_FORWARD))


def test_window_beyond_schedule_without_proven_maturity_is_unavailable():
    idx, st, en, co = semi_axis()
    res = run(idx, st, en, co, DS, 12, C.DUE_DATE_WINDOW, maturity=None)
    assert res.rows[-1].status is S.BEYOND_SCHEDULE_UNPROVEN_MATURITY and res.rows[-1].required_keur is None
    assert res.peak_required_keur is None
    ok = run(idx, st, en, co, DS, 12, C.DUE_DATE_WINDOW, maturity=en[-1])
    assert ok.rows[-1].required_keur == 0.0


def test_zero_senior_debt_is_an_explicit_zero_not_a_failure():
    idx, st, en, co = semi_axis()
    res = run(idx, st, en, co, [0.0] * len(idx), 9, C.PRORATED_PERIOD)
    assert all(r.status is S.NO_FURTHER_DEBT_SERVICE and r.required_keur == 0.0 for r in res.rows)
    assert res.peak_required_keur == 0.0 and res.peak_status is S.NO_FURTHER_DEBT_SERVICE


@pytest.mark.parametrize("bad,code", [
    (-1.0, "DSRA_COVERAGE_NEGATIVE_SENIOR_DS"), (float("nan"), "DSRA_COVERAGE_INVALID_SENIOR_DS"),
    (float("inf"), "DSRA_COVERAGE_INVALID_SENIOR_DS"), (True, "DSRA_COVERAGE_INVALID_SENIOR_DS"),
    ("5", "DSRA_COVERAGE_INVALID_SENIOR_DS")])
def test_invalid_debt_service_is_rejected(bad, code):
    idx, st, en, co = semi_axis()
    ds = list(DS)
    ds[4] = bad
    with pytest.raises(ValueError, match=code):
        run(idx, st, en, co, ds, 6, C.DUE_DATE_WINDOW)


@pytest.mark.parametrize("months", [0, -6, 6.0, True, None])
def test_invalid_coverage_months_rejected(months):
    idx, st, en, co = semi_axis()
    with pytest.raises(ValueError, match="DSRA_COVERAGE_INVALID_COVERAGE_MONTHS"):
        run(idx, st, en, co, DS, months, C.DUE_DATE_WINDOW)


def test_convention_must_be_explicit_and_structure_is_validated():
    idx, st, en, co = semi_axis()
    with pytest.raises(ValueError, match="DSRA_COVERAGE_CONVENTION_REQUIRED"):
        run(idx, st, en, co, DS, 6, None)
    with pytest.raises(ValueError, match="DSRA_COVERAGE_LENGTH_MISMATCH"):
        run(idx, st, en, co, DS[:-1], 6, C.DUE_DATE_WINDOW)
    bad_en = list(en)
    bad_en[4] = bad_en[3]
    with pytest.raises(ValueError, match="DSRA_COVERAGE_(NON_CHRONOLOGICAL|INVALID)"):
        run(idx, st, bad_en, co, DS, 6, C.DUE_DATE_WINDOW)
    ds = list(DS)
    with pytest.raises(ValueError, match="DEBT_SERVICE_AFTER_MATURITY"):
        run(idx, st, en, co, ds, 6, C.DUE_DATE_WINDOW, maturity=en[-3])


def test_policy_version_is_explicit_and_legacy_builder_is_unchanged():
    assert POLICY_VERSION == "FORWARD_CALENDAR_COVERAGE_V1"
    idx, st, en, co = semi_axis(n=3)
    ds = (0.0, 0.0, 100.0, 250.0, 125.5)
    out = build_dsra_required_balance_schedule(
        period_indices=tuple(idx), period_start_dates=tuple(st), period_end_dates=tuple(en), is_construction=tuple(co),
        senior_debt_service_keur=ds, coverage_months=9, periods_per_year=2)
    assert [x.hex() for x in out] == [float(v).hex() for v in (0.0, 0.0, 250.0 * 1.5, 125.5 * 1.5, 0.0)]
    fixed = build_dsra_required_balance_schedule(
        period_indices=tuple(idx), period_start_dates=tuple(st), period_end_dates=tuple(en), is_construction=tuple(co),
        senior_debt_service_keur=ds, coverage_months=6, periods_per_year=2,
        policy=DsraTargetPolicy.FIXED_AMOUNT, fixed_amount_keur=77.0)
    assert fixed == (0.0, 0.0, 77.0, 77.0, 77.0)


# ── 5. typed reserve authority ──────────────────────────────────────────────────────────────────

def _fin(**kw):
    from finco_core.inputs import DebtServiceReserveSupportMode as M
    base = dict(dsra_support_mode=M.NONE, dsra_months=6, dsra_target_policy=None, debt_service_reserve_requirement_keur=0.0)
    base.update(kw)
    return type("F", (), base)()


def test_classification_distinguishes_none_fixed_forward_and_peak_forward():
    from finco_core.inputs import DebtServiceReserveSupportMode as M
    none = classify_financing(_fin(dsra_months=0, dsra_target_policy="fixed_amount"))
    assert (none.kind, none.activation) == (RK.NONE, A.NOT_APPLICABLE)
    auto = classify_financing(_fin())
    assert (auto.kind, auto.version, auto.activation, auto.coverage_months) == (
        RK.PEAK_FORWARD, RV.SHORTCUT_V0, A.ACTIVE_VIA_GENERIC_POLICY_H1, 6)
    fixed = classify_financing(_fin(dsra_support_mode=M.CASH_DSRA, dsra_months=0, dsra_target_policy="fixed_amount",
                                    debt_service_reserve_requirement_keur=500.0))
    assert (fixed.kind, fixed.version, fixed.initial_funding_keur) == (RK.FIXED_AMOUNT, RV.STATIC_V0, 500.0)
    legacy_fixed = classify_financing(_fin(dsra_support_mode=M.CASH_DSRA, dsra_target_policy=None,
                                           debt_service_reserve_requirement_keur=500.0))
    assert legacy_fixed.kind is RK.FIXED_AMOUNT  # historical None => static, unchanged
    fwd = classify_financing(_fin(dsra_support_mode=M.CASH_DSRA, dsra_target_policy="forward_debt_service_months",
                                  debt_service_reserve_requirement_keur=100.0))
    pk = classify_financing(_fin(dsra_support_mode=M.CASH_DSRA, dsra_target_policy="peak_forward_debt_service_months",
                                 debt_service_reserve_requirement_keur=100.0))
    assert (fwd.kind, pk.kind) == (RK.FORWARD, RK.PEAK_FORWARD)
    assert classify_financing(_fin(dsra_support_mode=M.DSRF, dsra_months=0)).instrument == "DSRF"


def test_unrecognised_policy_string_fails_closed_with_typed_code():
    with pytest.raises(ReserveAuthorityError) as exc:
        classify_financing(_fin(dsra_target_policy="forward_v9"))
    assert exc.value.code == CODE_UNRECOGNISED


@pytest.mark.parametrize("mode,code", [("automatic_forward", CODE_GATED_MODE),
                                       ("automatic_forward_calendar", CODE_CALENDAR_FUNDING_GATED),
                                       ("automatic_peak_forward_calendar", CODE_CALENDAR_FUNDING_GATED)])
def test_calendar_modes_are_gated_with_a_typed_reason(mode, code):
    with pytest.raises(ReserveAuthorityError) as exc:
        selection_from_editor(dict(mode=mode, months=9, requirement_keur=0, commitment_keur=0, fee_pct=0))
    assert exc.value.code == code and "fixed-point" in exc.value.detail


def test_automatic_selection_that_would_become_none_is_refused():
    requested = selection_from_editor(dict(mode="automatic_peak", months=6, requirement_keur=0, commitment_keur=0, fee_pct=0))
    assert assert_selection_realised(requested, _fin(dsra_months=6)).kind is RK.PEAK_FORWARD
    for broken in (_fin(dsra_months=0), _fin(dsra_months=6, dsra_target_policy="fixed_amount"),
                   _fin(dsra_months=9)):
        with pytest.raises(ReserveAuthorityError) as exc:
            assert_selection_realised(requested, broken)
        assert exc.value.code == CODE_AUTOMATIC_NOT_REALISED


# ── 6. editor (R0), four verticals ───────────────────────────────────────────────────────────────

VERTICALS = ("solar", "wind", "data_center", "ev_charging")
BASELINE_HEX = {  # float.hex identities of the current reference Runs (main 1f25903), no new policy selected
    "solar": dict(dsra="0x1.e3619de423a32p+10", senior="0x1.a59d53a2ff90ep+14", uses="0x1.19138d17550b4p+15", ds="0x1.1bb100f21f480p+15"),
    "wind": dict(dsra="0x1.78858e2bfe403p+11", senior="0x1.1d3250e010c3bp+15", uses="0x1.7c431680165a4p+15", ds="0x1.730af03d2676fp+15"),
    "data_center": dict(dsra="0x1.5a8e14c04b205p+12", senior="0x1.c855ec7065648p+15", uses="0x1.96a44b9bf5b39p+17", ds="0x1.3120ea853867fp+16"),
    "ev_charging": dict(dsra="0x1.7ac2d235989bcp+9", senior="0x1.94d5a429cc875p+12", uses="0x1.37694333d8681p+13", ds="0x1.0133ca50bd657p+13"),
}


def _project(kind):
    from app import project_factories
    return getattr(project_factories, f"create_generic_{kind}_reference")()


def _cfg(**reserve):
    return json.dumps(dict(version=1, reserve=reserve))


def _reserve(mode, months=0, requirement=0, commitment=0, fee=0):
    return dict(mode=mode, months=months, requirement_keur=requirement, commitment_keur=commitment, fee_pct=fee)


@pytest.fixture(scope="module")
def runs():
    from app.services.production_financial_authority import run_clean_production
    return {k: run_clean_production(_project(k), "Base", project_type=k) for k in VERTICALS}


@pytest.mark.parametrize("kind", VERTICALS)
def test_automatic_peak_is_explicit_typed_and_never_silently_none(kind):
    from app.workbook.bankability_config import apply_config, build_view
    pi = _project(kind)
    for months in (1, 6, 9, 12):
        eff = apply_config(pi, _cfg(**_reserve("automatic_peak", months)), project_type=kind.title())
        sel = classify_financing(eff.financing, eff.capex)
        assert (sel.kind, sel.activation, sel.coverage_months) == (RK.PEAK_FORWARD, A.ACTIVE_VIA_GENERIC_POLICY_H1, months)
        # the historical signature is preserved bit-for-bit (the H-1 policy keys on it)
        assert eff.financing.dsra_months == months and eff.financing.dsra_target_policy is None
        assert eff.financing.debt_service_reserve_requirement_keur == 0.0
    view = build_view(pi, None, project_type=kind.title())
    assert view["reserve_selection"]["effective"]["kind"] == "peak_forward"
    assert view["reserve_selection"]["effective"]["activation"] == "ACTIVE_VIA_GENERIC_POLICY_H1"
    assert "automatic_forward_calendar" in view["reserve_selection"]["gated_modes"]


@pytest.mark.parametrize("mode", ["automatic_forward", "automatic_forward_calendar", "automatic_peak_forward_calendar"])
def test_gated_reserve_modes_are_rejected_at_save_time_with_a_typed_reason(mode):
    from app.workbook.bankability_config import parse_config
    with pytest.raises(ReserveAuthorityError) as exc:
        parse_config(_cfg(**_reserve(mode, 9)))
    assert exc.value.code in (CODE_GATED_MODE, CODE_CALENDAR_FUNDING_GATED)
    assert isinstance(exc.value, ValueError)  # existing router/save error handling still catches it


@pytest.mark.parametrize("kind", VERTICALS)
def test_other_reserve_modes_keep_their_historical_mapping(kind):
    from finco_core.inputs import DebtServiceReserveSupportMode as M
    from app.workbook.bankability_config import apply_config
    pi = _project(kind)
    none = apply_config(pi, _cfg(**_reserve("none")), project_type=kind.title()).financing
    assert (none.dsra_support_mode, none.dsra_months, none.dsra_target_policy) == (M.NONE, 0, "fixed_amount")
    cash = apply_config(pi, _cfg(**_reserve("cash_fixed", requirement=500)), project_type=kind.title()).financing
    assert (cash.dsra_support_mode, cash.dsra_target_policy, cash.debt_service_reserve_requirement_keur) == (
        M.CASH_DSRA, "fixed_amount", 500.0)
    dsrf = apply_config(pi, _cfg(**_reserve("dsrf", requirement=500, commitment=500, fee=.75)), project_type=kind.title()).financing
    assert dsrf.dsra_support_mode == M.DSRF
    assert apply_config(pi, None) is pi


def test_save_reload_round_trip_resolves_the_same_selection_from_persisted_json():
    from app.workbook.bankability_config import apply_config, parse_config
    pi = _project("solar")
    raw = _cfg(**_reserve("automatic_peak", 9))
    persisted = json.dumps(json.loads(raw))  # a stored/reloaded snapshot string
    assert parse_config(persisted) == parse_config(raw)
    a, b = apply_config(pi, raw, project_type="Solar"), apply_config(pi, persisted, project_type="Solar")
    assert a == b and classify_financing(b.financing, b.capex).coverage_months == 9


def test_competing_legacy_reserve_authority_still_refuses_automatic_selection():
    from app.workbook.bankability_config import apply_config
    pi = _project("solar")
    pi = dc.replace(pi, capex=dc.replace(pi.capex, reserve_accounts_keur=100.0))
    with pytest.raises(ValueError):
        apply_config(pi, _cfg(**_reserve("automatic_peak", 6)), project_type="Solar")


# ── 7. historical identity and financial reconciliation (four verticals) ─────────────────────────

@pytest.mark.parametrize("kind", VERTICALS)
def test_reference_runs_are_bit_identical_when_no_new_policy_is_selected(kind, runs):
    from financial_engine.financing.generic_product_policy import build_sources_and_uses
    fr = runs[kind].g2c_result.financing_result
    su = build_sources_and_uses(fr)
    sd = fr.project_model_result.senior_debt
    got = dict(dsra=float(su.initial_dsra_funding_keur).hex(), senior=float(su.senior_debt_keur).hex(),
               uses=float(su.total_uses_keur).hex(), ds=float(sum(sd.senior_debt_service_keur)).hex())
    assert got == BASELINE_HEX[kind]
    assert runs[kind].authority_metadata["cash_dsra_applied"] is True


def _evidence(run):
    from app.run_integrity.reserve_coverage_evidence import build_from_clean_run
    return build_from_clean_run(run)


def _independent_service(run):
    """Per-period service re-read directly from the canonical result, as raw floats, with period dates."""
    m = run.g2c_result.financing_result.project_model_result
    svc = dict(zip((int(i) for i in m.senior_debt.period_indices), m.senior_debt.senior_debt_service_keur))
    return m, svc


@pytest.mark.parametrize("kind", VERTICALS)
@pytest.mark.parametrize("months", [6, 9, 12])
def test_evidence_requirements_reconcile_with_independent_oracle(kind, months, runs):
    from app.run_integrity.reserve_coverage_evidence import build_from_clean_run
    ev = build_from_clean_run(runs[kind], coverage_months=months)
    assert ev["status"] == "RECORDED", ev
    m, svc = _independent_service(runs[kind])
    periods = [(p.period_start, p.period_end, float(svc.get(p.period_index, 0.0))) for p in m.periods if not p.is_construction]
    for conv, tag in (("due_date_window", "due"), ("prorated_period", "pro")):
        block = ev["conventions"][conv]
        peak = 0.0
        for row in block["rows"]:
            assert row["required_reserve_keur"] is not None, row
            expected = oracle_requirement(date.fromisoformat(row["test_date"]), months, periods, tag)
            assert row["required_reserve_keur"] == pytest.approx(expected, rel=1e-9, abs=1e-6)
            peak = max(peak, expected)
        assert block["peak_reserve_requirement_keur"] == pytest.approx(peak, rel=1e-9)


@pytest.mark.parametrize("kind", VERTICALS)
def test_six_month_due_date_peak_reconciles_with_the_recorded_h1_funding(kind, runs):
    """The H-1 fixed point funds the peak next-period service; for 6 months the calendar peak is that number."""
    from financial_engine.financing.generic_product_policy import build_sources_and_uses
    ev = _evidence(runs[kind])
    funded = build_sources_and_uses(runs[kind].g2c_result.financing_result).initial_dsra_funding_keur
    block = ev["conventions"]["due_date_window"]
    assert block["peak_reserve_requirement_keur"] == pytest.approx(funded, rel=1e-9, abs=1e-6)
    assert ev["selected_policy"]["kind"] == "peak_forward"


@pytest.mark.parametrize("kind", VERTICALS)
def test_evidence_states_maturity_and_payoff_from_the_merged_senior_authority_and_is_read_only(kind, runs):
    from app.run_integrity.senior_debt_evidence import build_from_clean_run as senior
    m, _ = _independent_service(runs[kind])
    before = [float(x).hex() for x in m.senior_debt.senior_debt_service_keur]
    ev = _evidence(runs[kind])
    rep = senior(runs[kind])["repayment"]
    assert ev["contractual_senior_maturity_date"] == rep["contractual_maturity_date"]
    assert ev["actual_senior_payoff_date"] == rep["actual_payoff_date"]
    assert ev["senior_payoff_status"] == rep["payoff_status"]
    assert [float(x).hex() for x in m.senior_debt.senior_debt_service_keur] == before
    assert ev["funding_activation"]["calendar_v1_automatic_funding"] == "UNAVAILABLE"
    assert ev["recorded_cash_dsra_status"] == "RECORDED"
    for block in ev["conventions"].values():
        for r in block["rows"]:
            if r["reserve_shortfall_keur"] is not None:
                assert r["reserve_shortfall_keur"] >= 0.0 and r["excess_coverage_keur"] >= 0.0
                assert min(r["reserve_shortfall_keur"], r["excess_coverage_keur"]) == 0.0


@pytest.mark.parametrize("kind", VERTICALS)
def test_early_senior_payoff_is_reflected_in_requirement(kind, runs):
    ev = _evidence(runs[kind])
    if ev["senior_payoff_status"] != "EXTINGUISHED_BEFORE_CONTRACTUAL_MATURITY":
        pytest.skip("reference Run extinguishes at contractual maturity")
    payoff = ev["actual_senior_payoff_date"]
    for block in ev["conventions"].values():
        after = [r for r in block["rows"] if r["test_date"] >= payoff]
        assert after and all(r["required_reserve_keur"] == 0.0 and r["status"] == "NO_FURTHER_DEBT_SERVICE" for r in after)


def test_evidence_unavailable_inputs_are_typed_never_zero(runs):
    from app.run_integrity.reserve_coverage_evidence import (
        build_reserve_coverage_evidence, project_reserve_coverage_evidence, build_from_clean_run)
    assert project_reserve_coverage_evidence({"financing_evidence": {}})["status"] == "NOT_RECORDED"
    assert project_reserve_coverage_evidence(None)["status"] == "NOT_RECORDED"
    assert build_from_clean_run(object())["status"] == "EVIDENCE_UNAVAILABLE"
    ev = build_from_clean_run(runs["solar"], coverage_months=0)
    assert ev["status"] == "EVIDENCE_UNAVAILABLE" and ev["reason"] == "RESERVE_COVERAGE_MONTHS_NOT_SELECTED"
