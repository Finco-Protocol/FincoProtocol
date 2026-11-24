"""FINCO39 Slice D — empirical bit-identity of V10 Stage 1/2 & V11 Stage 3 native kernels on dated Solar/Wind grids."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app import project_factories as pf
from app.services import production_financial_authority as pfa
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION, dated_life_end_exclusive
from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
from financial_engine.native_v10.config import NativeConfig, native_run
from financial_engine.native_v11.config import Stage3Config, stage3_run
from tests.native_v10_support import evidence_of
from tests.test_fable_batch3_date_authority_generation import _with_r04

pytestmark = pytest.mark.usefixtures("stage3_artifacts")


def _make_dated(base, cod: date, start: date, months: int = 12, *, with_opex_override: bool = False):
    info = replace(
        base.info,
        date_authority_version=DATE_AUTHORITY_VERSION,
        cod_date=cod,
        financial_close=start,
        construction_months=months,
    )
    eng = PeriodEngine(
        financial_close=start,
        construction_months=months,
        horizon_years=info.horizon_years,
        ppa_years=int(round(base.revenue.ppa_term_years)),
        frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=cod,
        dated_life_end_exclusive=dated_life_end_exclusive(
            cod, info.horizon_years, date_authority_version=DATE_AUTHORITY_VERSION
        ),
    )
    fin = replace(base.financing, shl_maturity_period_index=eng.periods()[-1].index)
    opex = base.opex
    if with_opex_override and opex:
        first = opex[0]
        opex = (replace(first, annual_overrides=((1, 123.45), (5, 0.0), (10, 999.99))),) + tuple(opex[1:])
    return replace(base, info=info, financing=fin, opex=opex)


def _run_production_arm(inputs, project_type: str, v10_cfg: NativeConfig, v11_cfg: Stage3Config):
    pfa._POLICY_RUN_CACHE.clear()
    with native_run(v10_cfg) as s10, stage3_run(v11_cfg) as s11:
        res = pfa.run_clean_production(inputs, project_type=project_type)
    pfa._POLICY_RUN_CACHE.clear()
    return res, s10.as_dict(), s11.as_dict()


@pytest.mark.parametrize(
    ("label", "project_type", "builder"),
    [
        ("solar_jan1_dated", "solar", lambda: _make_dated(pf.create_generic_solar_reference(), date(2030, 1, 1), date(2029, 1, 1))),
        ("solar_mid_month_dated", "solar", lambda: _make_dated(pf.create_generic_solar_reference(), date(2031, 5, 15), date(2030, 5, 15))),
        ("solar_leap_dated", "solar", lambda: _make_dated(pf.create_generic_solar_reference(), date(2032, 2, 29), date(2031, 1, 29), 13)),
        ("solar_7day_window_dated", "solar", lambda: _make_dated(pf.create_generic_solar_reference(), date(2030, 6, 29), date(2029, 6, 29))),
        ("solar_r04_dated", "solar", lambda: _with_r04(pf.create_generic_solar_reference(), "solar")),
        ("solar_opex_override_dated", "solar", lambda: _make_dated(pf.create_generic_solar_reference(), date(2031, 5, 15), date(2030, 5, 15), with_opex_override=True)),
        ("wind_sep1_dated", "wind", lambda: _make_dated(pf.create_generic_wind_reference(), date(2031, 9, 1), date(2030, 3, 1), 18)),
        ("wind_r04_dated", "wind", lambda: _with_r04(pf.create_generic_wind_reference(), "wind")),
    ],
)
def test_dated_solar_wind_v10_and_v11_native_bit_identical_to_python(label, project_type, builder):
    pi = builder()
    off_res, off10, off11 = _run_production_arm(
        pi, project_type, NativeConfig(mode="off"), Stage3Config(mode="off")
    )
    assert off10["native_solves"] == 0 and off11["native_models"] == 0
    assert off_res.authority_metadata["calendar_mode"] == "DATED_CONTRACTUAL"
    base_ev = evidence_of(off_res)

    v10_res, s10, _ = _run_production_arm(
        pi, project_type, NativeConfig(mode="candidate", stage2_experimental=True), Stage3Config(mode="off")
    )
    assert s10["native_solves"] > 0 and s10["stage2_native_calls"] > 0 and s10["native_tax_evaluations"] > 0, (label, s10)
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in s10["declines"]
    assert evidence_of(v10_res) == base_ev

    s3_res, _, s11 = _run_production_arm(
        pi, project_type, NativeConfig(mode="off"), Stage3Config(mode="candidate")
    )
    assert s11["native_models"] > 0 and s11["native_full_tax"] > 0, (label, s11)
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in s11["declines"]
    assert evidence_of(s3_res) == base_ev

    both_res, b10, b11 = _run_production_arm(
        pi, project_type, NativeConfig(mode="candidate", stage2_experimental=True), Stage3Config(mode="candidate")
    )
    assert b10["stage2_native_calls"] > 0 and b11["native_models"] > 0 and b11["native_full_tax"] > 0, (label, b10, b11)
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in b10["declines"]
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in b11["declines"]
    assert evidence_of(both_res) == base_ev
