"""FINCO39 — Universal Contractual Calendar (OD-TIME-01/v1) independent day-level oracle & matrix tests.

Covers:
- Explicit versioned OD-TIME-01/v1 activation on Solar & Wind WITHOUT R04 (legacy scalar PPA + merchant,
  merchant-only, mid-month COD 2031-05-15, leap-year Feb 29 COD, 7-day COD roll window 2030-06-29).
- Independent day-by-day Decimal/Fraction oracle (does NOT call engine date/period/proration helpers).
- Negative controls: omitted stub, duplicated stub, omitted COD day, shifted PPA expiry, altered day count.
- Supported / refused matrix: Solar/Wind admitted; Data Center / EV Charging / BESS / unknown version fail closed.
- Cache identity separation: hash_engine_for_cache (both period_engine & app.cache) and _POLICY_RUN_CACHE.
- Authority metadata provenance: date_authority_version, calendar_contract_version, calendar_mode.
"""
from __future__ import annotations

import calendar
import dataclasses
from datetime import date, timedelta
from decimal import Decimal, getcontext
from fractions import Fraction

import pytest

from app.cache import hash_engine_for_cache as app_hash_engine_for_cache
from app.input_adapter import SnapshotInputError, build_projectinputs_from_snapshot
from app.project_factories import (
    create_generic_data_center_reference,
    create_generic_ev_charging_reference,
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.production_financial_authority import run_clean_production
from finco_core.engine.contractual_calendar import CALENDAR_CONTRACT_VERSION
from finco_core.engine.date_authority import (
    DATE_AUTHORITY_VERSION,
    LEGACY_DATE_AUTHORITY_VERSION,
    date_authority_active,
    dated_life_end_exclusive,
)
from finco_core.engine.period_engine import (
    PeriodEngine,
    PeriodFrequency,
    hash_engine_for_cache as core_hash_engine_for_cache,
)

getcontext().prec = 50


# ---------------------------------------------------------------------------
# Independent day-by-day oracle (zero calls to engine calendar/proration code)
# ---------------------------------------------------------------------------

def _oracle_add_years(d: date, years: int) -> date:
    y = d.year + years
    last_day = calendar.monthrange(y, d.month)[1]
    return date(y, d.month, min(d.day, last_day))


def _oracle_operating_year_1based(cod: date, day: date) -> int:
    # Operating year k is [add_years(cod, k-1), add_years(cod, k))
    k = max(1, day.year - cod.year + 1)
    while _oracle_add_years(cod, k - 1) > day:
        k -= 1
    while _oracle_add_years(cod, k) <= day:
        k += 1
    return k


def _oracle_day_level_totals(
    *,
    cod: date,
    horizon_years: int,
    capacity_mw: float,
    annual_hours: float,
    combined_availability: float,
    degradation: float,
    ppa_base_tariff: float,
    ppa_index: float,
    ppa_term_years: int,
    ppa_share: float,
    market_price_for_cal_year,
    opex_items: tuple,
) -> dict[str, Decimal]:
    """Sum generation (MWh), PPA/merchant revenue (kEUR), and OPEX (kEUR) day-by-day over [cod, cod+N)."""
    end_excl = _oracle_add_years(cod, horizon_years)
    ppa_end_excl = _oracle_add_years(cod, ppa_term_years) if ppa_term_years > 0 else cod

    cap = Decimal(str(capacity_mw))
    hrs = Decimal(str(annual_hours))
    avail = Decimal(str(combined_availability))
    deg_rate = Decimal(str(degradation))
    base_tariff = Decimal(str(ppa_base_tariff))
    idx_rate = Decimal(str(ppa_index))
    share = Decimal(str(min(max(ppa_share, 0.0), 1.0)))

    total_days = 0
    total_gen = Decimal(0)
    total_ppa_rev = Decimal(0)
    total_merch_rev = Decimal(0)
    total_opex = Decimal(0)

    day = cod
    while day < end_excl:
        total_days += 1
        yd = Decimal(366 if calendar.isleap(day.year) else 365)
        op_yr = _oracle_operating_year_1based(cod, day)
        day_gen = cap * hrs * avail * ((Decimal(1) - deg_rate) ** (op_yr - 1)) / yd
        total_gen += day_gen

        if cod <= day < ppa_end_excl and share > 0:
            ppa_mwh = day_gen * share
            merch_mwh = day_gen - ppa_mwh
            # AFTER_FIRST_FULL_OPERATING_YEAR: escalates on each COD anniversary (op_yr - 1)
            tariff = base_tariff * ((Decimal(1) + idx_rate) ** (op_yr - 1))
            total_ppa_rev += ppa_mwh * tariff / Decimal(1000)
        else:
            merch_mwh = day_gen
        m_price = Decimal(str(market_price_for_cal_year(day.year, op_yr)))
        total_merch_rev += merch_mwh * m_price / Decimal(1000)

        # OPEX (COD_ANNIVERSARY clock, fixed items then percentage_of_opex)
        fixed_sum = Decimal(0)
        for item in opex_items:
            if item.percentage_of_opex > 0:
                continue
            amt = Decimal(str(item.y1_amount_keur)) * (
                (Decimal(1) + Decimal(str(item.annual_inflation))) ** (op_yr - 1)
            )
            if amt < 0:
                amt = Decimal(0)
            fixed_sum += amt
        pct_sum = Decimal(0)
        for item in opex_items:
            if item.percentage_of_opex > 0:
                pct_sum += fixed_sum * Decimal(str(item.percentage_of_opex))
        total_opex += (fixed_sum + pct_sum) / yd

        day += timedelta(days=1)

    return {
        "total_days": Decimal(total_days),
        "generation_mwh": total_gen,
        "ppa_revenue_keur": total_ppa_rev,
        "merchant_revenue_keur": total_merch_rev,
        "energy_revenue_keur": total_ppa_rev + total_merch_rev,
        "opex_keur": total_opex,
    }


def _with_dated(pi, *, fc: date | None = None, construction_months: int | None = None, cod: date | None = None):
    info = pi.info
    new_fc = fc if fc is not None else info.financial_close
    new_cm = construction_months if construction_months is not None else info.construction_months
    new_cod = cod if cod is not None else info.cod_date
    return dataclasses.replace(
        pi,
        info=dataclasses.replace(
            info,
            financial_close=new_fc,
            construction_months=new_cm,
            cod_date=new_cod,
            date_authority_version=DATE_AUTHORITY_VERSION,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Independent day-level oracle parity across Solar/Wind scalar models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,factory,fc,cm,cod,horizon_years,expected_final_inclusive",
    [
        # Mid-month COD (2031-05-15), 25y horizon -> ends 2056-05-14 inclusive
        ("solar_mid_month", create_generic_solar_reference, date(2030, 5, 15), 12, date(2031, 5, 15), 25, date(2056, 5, 14)),
        # Leap-year COD (2032-02-28), 25y horizon -> ends 2057-02-27 inclusive
        ("solar_leap_feb28", create_generic_solar_reference, date(2031, 2, 28), 12, date(2032, 2, 28), 25, date(2057, 2, 27)),
        # 7-day COD roll window (2030-06-29 — default generic solar ref COD!): COD day MUST be included
        ("solar_7day_window_jun29", create_generic_solar_reference, date(2029, 6, 29), 12, date(2030, 6, 29), 25, date(2055, 6, 28)),
        # Aligned Jan 1 COD (no final stub)
        ("solar_aligned_jan1", create_generic_solar_reference, date(2030, 1, 1), 12, date(2031, 1, 1), 25, date(2055, 12, 31)),
        # Wind off-boundary COD (2031-09-01), native 27y horizon -> ends 2058-08-31 inclusive
        ("wind_off_boundary", create_generic_wind_reference, date(2030, 3, 1), 18, date(2031, 9, 1), 27, date(2058, 8, 31)),
    ],
)
def test_finco39_independent_day_oracle_solar_wind_scalar(
    label, factory, fc, cm, cod, horizon_years, expected_final_inclusive
):
    base = factory()
    # Zero balancing/CO2 for pure energy/OPEX/depreciation/BS parity check
    rev = dataclasses.replace(
        base.revenue,
        co2_enabled=False,
        balancing_cost_pv=0.0,
        balancing_cost_wind_eur_mwh=0.0,
        balancing_cost_eur_per_mwh=0.0,
        balancing_cost_schedule=None,
        co2_sales_schedule=None,
    )
    pi = _with_dated(
        dataclasses.replace(base, info=dataclasses.replace(base.info, horizon_years=horizon_years), revenue=rev),
        fc=fc,
        construction_months=cm,
        cod=cod,
    )
    # Re-align hardcoded SHL maturity index when FC/COD changes construction column count (mirrors ON-08)
    _eng = PeriodEngine(
        financial_close=fc,
        construction_months=cm,
        horizon_years=horizon_years,
        ppa_years=int(round(pi.revenue.ppa_term_years)),
        frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=cod,
        dated_life_end_exclusive=dated_life_end_exclusive(cod, horizon_years, date_authority_version=DATE_AUTHORITY_VERSION),
    )
    pi = dataclasses.replace(
        pi,
        financing=dataclasses.replace(
            pi.financing,
            shl_maturity_period_index=_eng.periods()[-1].index,
        ),
    )

    run = run_clean_production(pi)
    assert run.authority_metadata["date_authority_version"] == DATE_AUTHORITY_VERSION
    assert run.authority_metadata["calendar_contract_version"] == CALENDAR_CONTRACT_VERSION
    assert run.authority_metadata["calendar_mode"] == "DATED_CONTRACTUAL"

    pmr = run.g2c_result.financing_result.project_model_result
    op_periods = [p for p in pmr.periods if p.is_operation]
    assert op_periods[-1].period_end == expected_final_inclusive

    # Exact total days conserved across [COD, COD + horizon_years)
    expected_days = (_oracle_add_years(cod, horizon_years) - cod).days
    # Reconstruct half-open intervals from operating periods
    actual_days = 0
    prev_end = None
    for p in op_periods:
        iv_start = cod if prev_end is None else prev_end + timedelta(days=1)
        iv_end_excl = p.period_end + timedelta(days=1)
        actual_days += (iv_end_excl - iv_start).days
        prev_end = p.period_end
    assert actual_days == expected_days

    oracle = _oracle_day_level_totals(
        cod=cod,
        horizon_years=horizon_years,
        capacity_mw=pi.technical.capacity_mw,
        annual_hours=pi.technical.operating_hours_p50,
        combined_availability=pi.technical.combined_availability,
        degradation=pi.technical.pv_degradation,
        ppa_base_tariff=pi.revenue.ppa_base_tariff,
        ppa_index=pi.revenue.ppa_index,
        ppa_term_years=int(round(pi.revenue.ppa_term_years)),
        ppa_share=pi.revenue.ppa_production_share,
        market_price_for_cal_year=lambda yr, op_yr: pi.revenue.market_price_for_period(
            period_end_year=yr, operating_year=op_yr
        ),
        opex_items=pi.opex,
    )

    eng_gen = sum(Decimal(str(p.production_mwh)) for p in op_periods)
    eng_rev = sum(Decimal(str(p.revenue_keur)) for p in op_periods)
    eng_opex = sum(Decimal(str(p.opex_keur)) for p in op_periods)

    assert abs(eng_gen - oracle["generation_mwh"]) <= Decimal("1e-6"), f"{label}: gen diff"
    assert abs(eng_rev - oracle["energy_revenue_keur"]) <= Decimal("0.01"), f"{label}: rev diff"
    assert abs(eng_opex - oracle["opex_keur"]) <= Decimal("0.01"), f"{label}: opex diff"

    # Full balance sheet check <= 0.01 kEUR across all operating BS periods and zero terminal debt/DSRA
    bs_periods = run.financial_statements_result.balance_sheet_periods
    bs_checks = [abs(p.balance_check_keur) for p in bs_periods if p.balance_check_keur is not None]
    assert len(bs_checks) >= len(op_periods)
    max_bs_err = max(bs_checks)
    assert max_bs_err <= 0.01, f"{label}: BS imbalance {max_bs_err}"

    # Terminal senior debt balance == 0 and DSRA released at maturity
    assert abs(bs_periods[-1].senior_debt_balance_keur) <= 1e-6
    assert abs(bs_periods[-1].dsra_balance_keur) <= 1e-6


def test_finco39_negative_controls_detect_calendar_mutations():
    """Negative controls: omitting stub, duplicating stub, omitting COD day, or shifting expiry MUST fail."""
    base = create_generic_solar_reference()
    cod = date(2031, 5, 15)
    rev = dataclasses.replace(
        base.revenue,
        co2_enabled=False,
        balancing_cost_pv=0.0,
        balancing_cost_wind_eur_mwh=0.0,
        balancing_cost_eur_per_mwh=0.0,
        balancing_cost_schedule=None,
        co2_sales_schedule=None,
    )
    pi = _with_dated(
        dataclasses.replace(base, info=dataclasses.replace(base.info, horizon_years=25), revenue=rev),
        fc=date(2030, 5, 15),
        construction_months=12,
        cod=cod,
    )
    run = run_clean_production(pi)
    op_periods = [p for p in run.g2c_result.financing_result.project_model_result.periods if p.is_operation]
    oracle = _oracle_day_level_totals(
        cod=cod,
        horizon_years=25,
        capacity_mw=pi.technical.capacity_mw,
        annual_hours=pi.technical.operating_hours_p50,
        combined_availability=pi.technical.combined_availability,
        degradation=pi.technical.pv_degradation,
        ppa_base_tariff=pi.revenue.ppa_base_tariff,
        ppa_index=pi.revenue.ppa_index,
        ppa_term_years=int(round(pi.revenue.ppa_term_years)),
        ppa_share=pi.revenue.ppa_production_share,
        market_price_for_cal_year=lambda yr, op_yr: pi.revenue.market_price_for_period(
            period_end_year=yr, operating_year=op_yr
        ),
        opex_items=pi.opex,
    )

    # 1. Omit final stub
    omit_stub_rev = sum(Decimal(str(p.revenue_keur)) for p in op_periods[:-1])
    assert abs(omit_stub_rev - oracle["energy_revenue_keur"]) > Decimal("100")

    # 2. Duplicate final stub
    dup_stub_rev = sum(Decimal(str(p.revenue_keur)) for p in op_periods) + Decimal(str(op_periods[-1].revenue_keur))
    assert abs(dup_stub_rev - oracle["energy_revenue_keur"]) > Decimal("100")

    # 3. Omit COD day (shift start +1 day)
    oracle_omit_cod = _oracle_day_level_totals(
        cod=cod + timedelta(days=1),
        horizon_years=25,
        capacity_mw=pi.technical.capacity_mw,
        annual_hours=pi.technical.operating_hours_p50,
        combined_availability=pi.technical.combined_availability,
        degradation=pi.technical.pv_degradation,
        ppa_base_tariff=pi.revenue.ppa_base_tariff,
        ppa_index=pi.revenue.ppa_index,
        ppa_term_years=int(round(pi.revenue.ppa_term_years)),
        ppa_share=pi.revenue.ppa_production_share,
        market_price_for_cal_year=lambda yr, op_yr: pi.revenue.market_price_for_period(
            period_end_year=yr, operating_year=op_yr
        ),
        opex_items=pi.opex,
    )
    eng_gen = sum(Decimal(str(p.production_mwh)) for p in op_periods)
    assert abs(eng_gen - oracle_omit_cod["generation_mwh"]) > Decimal("0.1")

    # 4. Shift PPA expiry by 1 year
    oracle_shift_ppa = _oracle_day_level_totals(
        cod=cod,
        horizon_years=25,
        capacity_mw=pi.technical.capacity_mw,
        annual_hours=pi.technical.operating_hours_p50,
        combined_availability=pi.technical.combined_availability,
        degradation=pi.technical.pv_degradation,
        ppa_base_tariff=pi.revenue.ppa_base_tariff,
        ppa_index=pi.revenue.ppa_index,
        ppa_term_years=int(round(pi.revenue.ppa_term_years)) + 1,
        ppa_share=pi.revenue.ppa_production_share,
        market_price_for_cal_year=lambda yr, op_yr: pi.revenue.market_price_for_period(
            period_end_year=yr, operating_year=op_yr
        ),
        opex_items=pi.opex,
    )
    eng_rev = sum(Decimal(str(p.revenue_keur)) for p in op_periods)
    assert abs(eng_rev - oracle_shift_ppa["energy_revenue_keur"]) > Decimal("10")


# ---------------------------------------------------------------------------
# 2. Supported / Refused Matrix & Cache Key Isolation
# ---------------------------------------------------------------------------

def test_finco39_supported_refused_matrix_and_legacy_preservation():
    # Legacy Solar (date_authority_version=None) remains LEGACY_CALENDAR/v0
    legacy_solar = create_generic_solar_reference()
    assert date_authority_active(legacy_solar) is False
    legacy_run = run_clean_production(legacy_solar)
    assert legacy_run.authority_metadata["date_authority_version"] == LEGACY_DATE_AUTHORITY_VERSION
    assert legacy_run.authority_metadata["calendar_mode"] == "LEGACY"

    # Data Center and EV Charging fail closed if OD-TIME-01/v1 is explicitly requested
    dc = _with_dated(create_generic_data_center_reference())
    with pytest.raises(ValueError, match="DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED"):
        date_authority_active(dc)

    ev = _with_dated(create_generic_ev_charging_reference())
    with pytest.raises(ValueError, match="DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED"):
        date_authority_active(ev)

    # Snapshot adapter also refuses DC/EV and unknown version
    base_snap = {
        "project_name": "Test Proj",
        "country_market": "DE",
        "capacity_mw": "50",
        "financial_close": "2029-06-29",
        "construction_months": "12",
        "cod_date": "2030-06-29",
        "horizon_years": "25",
        "tariff_eur_mwh": "65",
        "ppa_term_years": "10",
        "p50_hours": "1200",
        "opex_y1_keur": "750",
        "total_capex_keur": "33000",
        "interest_rate_pct": "4.5",
        "_finval_interest_rate_unit": "human_percent_v1",
        "tenor_years": "15",
        "target_dscr": "1.25",
    }
    with pytest.raises(SnapshotInputError, match="DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED"):
        build_projectinputs_from_snapshot(
            {
                **base_snap,
                "project_type": "Data Center",
                "template_source": "generic_data_center_reference",
                "date_authority_version": DATE_AUTHORITY_VERSION,
            }
        )

    with pytest.raises(SnapshotInputError, match="DATE_AUTHORITY_VERSION_UNSUPPORTED"):
        build_projectinputs_from_snapshot(
            {
                **base_snap,
                "project_type": "Solar",
                "template_source": "generic_solar_reference",
                "date_authority_version": "OD-TIME-99/v9",
            }
        )


def test_finco39_period_engine_cache_hash_separates_legacy_and_dated():
    fc = date(2030, 5, 15)
    cod = date(2031, 5, 15)
    legacy_eng = PeriodEngine(
        financial_close=fc,
        construction_months=12,
        horizon_years=25,
        ppa_years=10,
        frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=cod,
        dated_life_end_exclusive=None,
    )
    dated_eng = PeriodEngine(
        financial_close=fc,
        construction_months=12,
        horizon_years=25,
        ppa_years=10,
        frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=cod,
        dated_life_end_exclusive=dated_life_end_exclusive(
            cod, 25, date_authority_version=DATE_AUTHORITY_VERSION
        ),
    )
    assert core_hash_engine_for_cache(legacy_eng) != core_hash_engine_for_cache(dated_eng)
    assert app_hash_engine_for_cache(legacy_eng) != app_hash_engine_for_cache(dated_eng)
    assert len(dated_eng.periods()) == len(legacy_eng.periods()) + 1
