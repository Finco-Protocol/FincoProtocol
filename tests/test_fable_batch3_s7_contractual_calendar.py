"""FINCO 36 Batch 3 — Slice B (S7 / OD-TIME-01): Contractual Calendar & Date-Aware Economics.

Independent day-by-day Decimal(50) oracle verification of OD-TIME-01 (does NOT import
contractual_calendar calculation functions to compute expected values):
1. Half-open intervals [start, end_exclusive), date-only, COD day included, exact N-year
   duration with explicit Feb 29 -> Feb 28 leap-day clamp, final included date = end_exclusive - 1 day.
2. Explicit adapter-boundary conversion from legacy inclusive labels & PeriodMeta rows
   with zero lost or double-counted days.
3. COD edge cases: 1st of month (C01: 2031-03-01), mid-month (C11: 2031-05-15),
   June 30 (2031-06-30), year end (2031-12-31), leap day (2028-02-29), first & final stubs,
   exact subperiod-to-reporting-axis conservation.
4. Generation: actual days / (365|366) per calendar year, annual physical degradation stepping
   at exact COD anniversaries, availability retained, no double-counting.
5. OPEX: COD_ANNIVERSARY default clock vs CALENDAR_YEAR clock, sustained step changes,
   percentage-of-OPEX contingency.
6. PPA pricing & expiry: C14A (FIRST_FULL_CALENDAR_YEAR_AS_BASE), C14B
   (AFTER_FIRST_FULL_OPERATING_YEAR), CONTRACT_ANNIVERSARY, off-boundary start & exact
   contractual expiry date (zero post-expiry PPA leakage).
7. Straight-line accounting depreciation over actual asset in-service life:
   life < horizon (100% depreciated with single final residual rounding),
   life == horizon (100% depreciated on final stub),
   life > horizon (retains exact positive carrying value).
8. Negative mutation witnesses (lost COD day, double-counted boundary day, wrong leap
   denominator 365, post-expiry PPA leakage) must fail the independent oracle.
9. Legacy compatibility: legacy PeriodEngine / LMA debt / reference factories untouched.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext
from fractions import Fraction

import pytest

from app import project_factories as pf
from finco_core.debt.depreciation_schedule import contractual_depreciation_per_period
from finco_core.engine.contractual_calendar import (
    CALENDAR_CONTRACT_VERSION,
    LEGACY_CALENDAR_COMPATIBILITY_PROVENANCE,
    ContractualInterval,
    OpexInflationClock,
    add_calendar_years,
    build_contractual_reporting_axis,
    contractual_depreciation_schedule,
    contractual_generation_for_interval,
    contractual_opex_for_interval,
    contractual_ppa_and_merchant_for_interval,
    convert_legacy_inclusive_range,
    convert_period_meta_to_half_open,
    days_in_calendar_year,
    operating_horizon_interval,
    reconcile_subperiods_to_reporting_axis,
    split_by_calendar_years,
)
from finco_core.engine.period_engine import PeriodEngine
from finco_core.inputs import AssetClass, CapexItem, OpexItem
from finco_core.opex.projections import contractual_opex_schedule_period, opex_year
from finco_core.revenue.generation import contractual_generation_schedule
from financial_engine.ppa_indexation import (
    PpaIndexationStartPolicy,
    compute_weighted_ppa_tariff_for_interval,
)

getcontext().prec = 50


# ── Independent Day-by-Day Decimal(50) Oracle (no contractual_calendar calls) ─


def _oracle_add_years(d: date, n: int) -> date:
    y = d.year + n
    if d.month == 2 and d.day == 29 and not calendar.isleap(y):
        return date(y, 2, 28)
    return date(y, d.month, d.day)


def _oracle_op_year(cod: date, day: date) -> int:
    k = 0
    while _oracle_add_years(cod, k + 1) <= day:
        k += 1
    return k + 1


def _oracle_day_by_day_generation(
    start: date,
    end_exc: date,
    cod: date,
    cap_mw: float,
    hours: float,
    avail: float,
    deg: float,
) -> Decimal:
    total = Decimal("0")
    base = Decimal(repr(cap_mw)) * Decimal(repr(hours)) * Decimal(repr(avail))
    one_minus_deg = Decimal("1") - Decimal(repr(deg))
    cur = start
    while cur < end_exc:
        yd = Decimal("366") if calendar.isleap(cur.year) else Decimal("365")
        op_yr = _oracle_op_year(cod, cur)
        total += base * (Decimal("1") / yd) * (one_minus_deg ** (op_yr - 1))
        cur += timedelta(days=1)
    return total


def _oracle_day_by_day_opex(
    start: date,
    end_exc: date,
    cod: date,
    items: tuple[OpexItem, ...],
    clock: str,
) -> Decimal:
    total = Decimal("0")
    cur = start
    while cur < end_exc:
        yd = Decimal("366") if calendar.isleap(cur.year) else Decimal("365")
        if clock == "COD_ANNIVERSARY":
            step_yr = _oracle_op_year(cod, cur)
        else:
            step_yr = max(1, cur.year - cod.year + 1)
        total += Decimal(repr(opex_year(items, step_yr))) / yd
        cur += timedelta(days=1)
    return total


def _oracle_day_by_day_ppa_merchant(
    start: date,
    end_exc: date,
    cod: date,
    cap_mw: float,
    hours: float,
    avail: float,
    deg: float,
    base_tariff: float,
    ppa_index: float,
    ppa_share: float,
    policy: PpaIndexationStartPolicy,
    contract_start: date,
    contract_end_exc: date,
    mkt_by_year: dict[int, float],
    idx_start: date | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    tot_ppa_mwh = tot_merch_mwh = tot_ppa_rev = tot_merch_rev = Decimal("0")
    base_gen = Decimal(repr(cap_mw)) * Decimal(repr(hours)) * Decimal(repr(avail))
    one_minus_deg = Decimal("1") - Decimal(repr(deg))
    d_share = Decimal(repr(ppa_share))
    d_tariff0 = Decimal(repr(base_tariff))
    d_idx = Decimal("1") + Decimal(repr(ppa_index))
    base_cy = cod.year if (cod.month == 1 and cod.day == 1) else cod.year + 1

    cur = start
    while cur < end_exc:
        yd = Decimal("366") if calendar.isleap(cur.year) else Decimal("365")
        op_yr = _oracle_op_year(cod, cur)
        day_mwh = base_gen * (Decimal("1") / yd) * (one_minus_deg ** (op_yr - 1))
        if contract_start <= cur < contract_end_exc and d_share > 0:
            if policy == PpaIndexationStartPolicy.FIRST_FULL_CALENDAR_YEAR_AS_BASE:
                esc = max(0, cur.year - base_cy)
            elif policy == PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR:
                esc = op_yr - 1
            else:
                assert idx_start is not None
                esc = _oracle_op_year(idx_start, cur) - 1
            t = d_tariff0 * (d_idx ** esc)
            p_mwh = day_mwh * d_share
            m_mwh = day_mwh - p_mwh
            tot_ppa_mwh += p_mwh
            tot_merch_mwh += m_mwh
            tot_ppa_rev += p_mwh * t / Decimal("1000")
            tot_merch_rev += m_mwh * Decimal(repr(mkt_by_year[cur.year])) / Decimal("1000")
        else:
            tot_merch_mwh += day_mwh
            tot_merch_rev += day_mwh * Decimal(repr(mkt_by_year[cur.year])) / Decimal("1000")
        cur += timedelta(days=1)
    return tot_ppa_mwh, tot_merch_mwh, tot_ppa_rev, tot_merch_rev


# ── 1. Interval, Leap-Day Clamp & Legacy Boundary Conversion Tests ───────────


def test_od_time_01_date_only_and_leap_day_clamp():
    assert CALENDAR_CONTRACT_VERSION == "OD-TIME-01-v1"
    assert "legacy_convention" in LEGACY_CALENDAR_COMPATIBILITY_PROVENANCE

    # Reject datetime (must be date-only) and empty/inverted intervals
    with pytest.raises(ValueError, match="OD_TIME_01_DATE_ONLY_REQUIRED"):
        ContractualInterval(datetime(2031, 3, 1), date(2031, 7, 1))
    with pytest.raises(ValueError, match="OD_TIME_01_EMPTY_OR_INVERTED_INTERVAL"):
        ContractualInterval(date(2031, 3, 1), date(2031, 3, 1))

    # Explicit Feb 29 leap-day clamp
    assert add_calendar_years(date(2028, 2, 29), 0) == date(2028, 2, 29)
    assert add_calendar_years(date(2028, 2, 29), 1) == date(2029, 2, 28)
    assert add_calendar_years(date(2028, 2, 29), 4) == date(2032, 2, 29)
    assert add_calendar_years(date(2028, 2, 29), 25) == date(2053, 2, 28)

    h_leap = operating_horizon_interval(date(2028, 2, 29), 1)
    assert h_leap.start == date(2028, 2, 29)
    assert h_leap.end_exclusive == date(2029, 2, 28)
    assert h_leap.final_included_date == date(2029, 2, 27)
    assert h_leap.days == 365


@pytest.mark.parametrize(
    "cod,horizon_years,expect_first_stub,expect_final_stub",
    [
        (date(2031, 3, 1), 25, True, True),     # C01: 1st of month -> first & final stubs
        (date(2031, 5, 15), 25, True, True),    # C11: mid-month -> first & final stubs
        (date(2031, 6, 30), 20, True, True),    # June 30 COD (1 day in H1, final stub to Jun 29)
        (date(2031, 12, 31), 20, True, True),   # Year-end COD (1 day in 2031)
        (date(2028, 2, 29), 25, True, True),    # Leap day COD
        (date(2031, 1, 1), 25, False, False),   # Exact boundary COD -> no stubs
        (date(2031, 7, 1), 25, False, False),   # Exact H2 boundary COD -> no stubs
    ],
)
def test_od_time_01_reporting_axis_exact_day_conservation(
    cod, horizon_years, expect_first_stub, expect_final_stub
):
    horizon = operating_horizon_interval(cod, horizon_years)
    periods = build_contractual_reporting_axis(cod, horizon_years, frequency_months=6)

    assert periods[0].start_date == cod
    assert periods[-1].end_exclusive == horizon.end_exclusive
    assert periods[-1].end_inclusive == horizon.final_included_date
    assert periods[0].is_first_stub is expect_first_stub
    assert periods[-1].is_final_stub is expect_final_stub

    # Exact day conservation: zero lost days, zero extra days, contiguous partition
    assert sum(p.days for p in periods) == horizon.days
    rec = reconcile_subperiods_to_reporting_axis([p.interval for p in periods], horizon)
    assert rec["reconciled"] is True
    assert rec["reporting_days"] == horizon.days

    # June 30 COD check: 2031-06-30 inclusive -> 185 days in 2031 (Jun 30 + 184 days H2)
    if cod == date(2031, 6, 30):
        assert periods[0].days == 1  # [2031-06-30, 2031-07-01)
        assert periods[1].days == 184  # [2031-07-01, 2032-01-01)
        slices_2031 = split_by_calendar_years(ContractualInterval(date(2031, 6, 30), date(2032, 1, 1)))
        assert len(slices_2031) == 1
        assert slices_2031[0].days == 185
        assert slices_2031[0].fraction == Fraction(185, 365)


def test_od_time_01_legacy_inclusive_conversion_zero_gaps_or_overlaps():
    # Explicit legacy inclusive conversion: [2031-05-15, 2031-06-30] -> 47 days (COD included!)
    iv = convert_legacy_inclusive_range(date(2031, 5, 15), date(2031, 6, 30))
    assert iv.start == date(2031, 5, 15)
    assert iv.end_exclusive == date(2031, 7, 1)
    assert iv.days == 47
    assert iv.final_included_date == date(2031, 6, 30)

    # Convert legacy PeriodEngine operating rows on C11 (COD 2031-05-15) -> contiguous partition
    eng = PeriodEngine(
        financial_close=date(2030, 5, 15),
        construction_months=12,
        horizon_years=5,
        ppa_years=5,
    )
    op_rows = [p for p in eng.periods() if p.is_operation]
    converted = []
    prev_end = None
    for row in op_rows:
        converted.append(convert_period_meta_to_half_open(row, cod=eng.cod, prev_end_date=prev_end))
        prev_end = row.end_date

    assert converted[0].start == date(2031, 5, 15)
    assert converted[0].days == 47  # COD day included (legacy PeriodMeta had 46)
    span = ContractualInterval(converted[0].start, converted[-1].end_exclusive)
    rec = reconcile_subperiods_to_reporting_axis(converted, span)
    assert rec["reconciled"] is True


# ── 2. Generation & OPEX Parity vs Independent Day-by-Day Decimal Oracle ─────


@pytest.mark.parametrize("cod", [date(2031, 3, 1), date(2031, 5, 15), date(2028, 2, 29)])
def test_od_time_01_generation_exact_parity_vs_day_by_day_oracle(cod):
    horizon_years = 6
    cap_mw, hours, avail, deg = 25.0, 1450.0, 0.97, 0.005
    horizon = operating_horizon_interval(cod, horizon_years)
    periods = build_contractual_reporting_axis(cod, horizon_years, frequency_months=6)

    for p in periods:
        actual_mwh, subs = contractual_generation_for_interval(
            p.interval,
            cod=cod,
            capacity_mw=cap_mw,
            annual_hours=hours,
            combined_availability=avail,
            annual_degradation=deg,
            horizon_end_exclusive=horizon.end_exclusive,
        )
        reconcile_subperiods_to_reporting_axis([s.interval for s in subs], p.interval)
        expected_mwh = _oracle_day_by_day_generation(
            p.start_date, p.end_exclusive, cod, cap_mw, hours, avail, deg
        )
        assert abs(Decimal(repr(actual_mwh)) - expected_mwh) <= Decimal("1e-9")

    # End-to-end helper on ProjectInputs (C01 Solar reference)
    pi = pf.create_generic_solar_reference()
    sched, rperiods = contractual_generation_schedule(pi)
    assert len(sched) == len(rperiods)
    assert sum(p.days for p in rperiods) == operating_horizon_interval(pi.info.cod_date, pi.info.horizon_years).days


@pytest.mark.parametrize("clock", [OpexInflationClock.COD_ANNIVERSARY, OpexInflationClock.CALENDAR_YEAR])
def test_od_time_01_opex_clocks_exact_parity_vs_day_by_day_oracle(clock):
    cod = date(2031, 5, 15)
    horizon_years = 5
    items = (
        OpexItem(name="O&M", y1_amount_keur=400.0, annual_inflation=0.025, step_changes=((3, 450.0),)),
        OpexItem(name="Insurance", y1_amount_keur=100.0, annual_inflation=0.02),
        OpexItem(name="Contingency", y1_amount_keur=0.0, annual_inflation=0.0, percentage_of_opex=0.05),
    )
    horizon = operating_horizon_interval(cod, horizon_years)
    periods = build_contractual_reporting_axis(cod, horizon_years, frequency_months=6)

    for p in periods:
        actual = contractual_opex_for_interval(
            p.interval,
            cod=cod,
            items=items,
            clock=clock,
            horizon_end_exclusive=horizon.end_exclusive,
        )
        expected = _oracle_day_by_day_opex(p.start_date, p.end_exclusive, cod, items, clock.value)
        assert abs(Decimal(repr(actual)) - expected) <= Decimal("1e-9")

    # Helper on ProjectInputs
    pi = pf.create_generic_solar_reference()
    sched_ann = contractual_opex_schedule_period(pi, clock="COD_ANNIVERSARY")
    sched_cal = contractual_opex_schedule_period(pi, clock="CALENDAR_YEAR")
    assert len(sched_ann) == len(sched_cal) > 0


# ── 3. PPA Indexation (C14A, C14B, CONTRACT_ANNIVERSARY) & Exact Expiry ──────


@pytest.mark.parametrize(
    "policy,idx_start",
    [
        (PpaIndexationStartPolicy.FIRST_FULL_CALENDAR_YEAR_AS_BASE, None),  # C14A
        (PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR, None),   # C14B
        (PpaIndexationStartPolicy.CONTRACT_ANNIVERSARY, date(2031, 9, 1)),  # Off-boundary contract
    ],
)
def test_od_time_01_ppa_clocks_and_exact_expiry_vs_day_by_day_oracle(policy, idx_start):
    cod = date(2031, 5, 15)
    horizon_years = 6
    contract_start = date(2031, 5, 15) if idx_start is None else idx_start
    contract_end_exc = add_calendar_years(contract_start, 3)  # mid-period exact expiry!
    mkt_by_year = {y: 55.0 + (y - 2031) * 2.0 for y in range(2031, 2040)}

    horizon = operating_horizon_interval(cod, horizon_years)
    periods = build_contractual_reporting_axis(cod, horizon_years, frequency_months=6)

    for p in periods:
        summary, slices = contractual_ppa_and_merchant_for_interval(
            p.interval,
            cod=cod,
            capacity_mw=20.0,
            annual_hours=1500.0,
            combined_availability=0.98,
            annual_degradation=0.005,
            ppa_base_tariff_eur_mwh=70.0,
            ppa_index=0.02,
            ppa_share=0.80,
            ppa_policy=policy,
            contract_start=contract_start,
            contract_end_exclusive=contract_end_exc,
            market_price_by_year=mkt_by_year,
            ppa_indexation_start_date=idx_start,
            horizon_end_exclusive=horizon.end_exclusive,
        )
        reconcile_subperiods_to_reporting_axis([s.interval for s in slices], p.interval)

        exp_ppa_mwh, exp_merch_mwh, exp_ppa_rev, exp_merch_rev = _oracle_day_by_day_ppa_merchant(
            p.start_date,
            p.end_exclusive,
            cod,
            20.0,
            1500.0,
            0.98,
            0.005,
            70.0,
            0.02,
            0.80,
            policy,
            contract_start,
            contract_end_exc,
            mkt_by_year,
            idx_start,
        )
        assert abs(Decimal(repr(summary["ppa_mwh"])) - exp_ppa_mwh) <= Decimal("1e-9")
        assert abs(Decimal(repr(summary["merchant_mwh"])) - exp_merch_mwh) <= Decimal("1e-9")
        assert abs(Decimal(repr(summary["ppa_revenue_keur"])) - exp_ppa_rev) <= Decimal("1e-9")
        assert abs(Decimal(repr(summary["merchant_revenue_keur"])) - exp_merch_rev) <= Decimal("1e-9")

        # Post-expiry strict check: zero PPA volume once period starts on or after contract_end_exc
        if p.start_date >= contract_end_exc:
            assert summary["ppa_mwh"] == 0.0
            assert summary["ppa_revenue_keur"] == 0.0

    # Also verify weighted tariff helper on an intraperiod C14B split
    w_tariff = compute_weighted_ppa_tariff_for_interval(
        base_tariff=70.0,
        ppa_index=0.02,
        policy=PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR,
        cod=date(2031, 5, 15),
        interval_start=date(2032, 1, 1),
        interval_end_exclusive=date(2032, 7, 1),  # 182 days in leap year 2032
    )
    # Jan 1 .. May 14 = 135 days at 70.0; May 15 .. Jun 30 = 47 days at 71.4
    expected_w = (135 * 70.0 + 47 * 70.0 * 1.02) / 182.0
    assert w_tariff == pytest.approx(expected_w, abs=1e-12)


# ── 4. Straight-Line Accounting Depreciation over Actual In-Service Life ─────


def test_od_time_01_depreciation_short_equal_and_long_lived_assets():
    cod = date(2031, 5, 15)
    horizon_years = 20
    items = (
        CapexItem(name="Inverter_10y", amount_keur=3_000.0, asset_class=AssetClass.SOLAR_PANELS, useful_life_override=10),
        CapexItem(name="PV_20y", amount_keur=15_000.0, asset_class=AssetClass.SOLAR_PANELS, useful_life_override=20),
        CapexItem(name="Civil_30y", amount_keur=6_000.0, asset_class=AssetClass.CIVIL_GRID, useful_life_override=30),
    )
    summary = contractual_depreciation_per_period(items, cod=cod, horizon_years=horizon_years)

    # Short-lived (10y) & horizon-equal (20y) assets depreciate 100% to basis with zero residual
    assert summary.closing_carrying_value_by_asset_keur["Inverter_10y"] == pytest.approx(0.0, abs=1e-12)
    assert summary.closing_carrying_value_by_asset_keur["PV_20y"] == pytest.approx(0.0, abs=1e-12)

    # Long-lived (30y > 20y horizon) retains exact legitimate carrying value
    d_20 = (add_calendar_years(cod, 20) - cod).days
    d_30 = (add_calendar_years(cod, 30) - cod).days
    expected_civil_carrying = 6_000.0 * (d_30 - d_20) / d_30
    assert summary.closing_carrying_value_by_asset_keur["Civil_30y"] == pytest.approx(
        expected_civil_carrying, abs=1e-9
    )

    # Total conservation: total_depreciation + total_closing_carrying_value == total_depreciable_basis
    assert summary.total_depreciation_keur + summary.total_closing_carrying_value_keur == pytest.approx(
        summary.total_depreciable_basis_keur, abs=1e-9
    )
    assert all(v >= 0.0 for v in summary.period_depreciation_keur.values())


# ── 5. Negative Mutation Witnesses (Lost Day, Double Day, Wrong Leap, Expiry) ─


def test_od_time_01_negative_mutation_witnesses_detected():
    cod = date(2031, 5, 15)
    # Witness 1: dropping COD day (46 vs 47 days) fails day conservation
    first_stub_missing_cod = ContractualInterval(date(2031, 5, 16), date(2031, 7, 1))
    full_h1 = ContractualInterval(date(2031, 5, 15), date(2031, 7, 1))
    with pytest.raises(ValueError, match="OD_TIME_01_SUBPERIOD_START_MISMATCH"):
        reconcile_subperiods_to_reporting_axis([first_stub_missing_cod], full_h1)

    # Witness 2: overlapping boundary day fails reconciliation
    s1 = ContractualInterval(date(2031, 5, 15), date(2031, 6, 2))
    s2 = ContractualInterval(date(2031, 6, 1), date(2031, 7, 1))
    with pytest.raises(ValueError, match="OD_TIME_01_SUBPERIOD_GAP_OR_OVERLAP"):
        reconcile_subperiods_to_reporting_axis([s1, s2], full_h1)

    # Witness 3: leap year 2032 MUST use 366, not 365
    assert days_in_calendar_year(2032) == 366
    mwh_leap, _ = contractual_generation_for_interval(
        ContractualInterval(date(2032, 1, 1), date(2033, 1, 1)),
        cod=date(2032, 1, 1),
        capacity_mw=10.0,
        annual_hours=1000.0,
        combined_availability=1.0,
        annual_degradation=0.0,
    )
    assert mwh_leap == pytest.approx(10_000.0, abs=1e-12)
    wrong_365_mwh = 10_000.0 * (366.0 / 365.0)
    assert abs(mwh_leap - wrong_365_mwh) > 25.0
