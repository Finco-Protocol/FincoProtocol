"""FINCO45A Slice C — EV Charging operating-year ramp & construction-duration alignment (FINCO44-NEW-02 / ORC-EV-ALIGN-01).

Verifies with an independent Decimal(50) oracle (no EV helper calls):
- 6m, 12m, 18m, 24m (FC=2029/COD=2031), 36m construction durations produce exact
  Y1=2400.00 kEUR, Y2=3264.00 kEUR, Y3=4161.60 kEUR (5 MW, 0.40 EUR/kWh, +2%/yr)
  and exact Y1 electricity OPEX 1725.9574468085107 kEUR.
- Non-Jan-1 cross-year COD (2031-05-15) keeps both semestrial periods of Operating Year 1
  at the Y1 effective rate without leaking into Y2 on period_end.year == 2032.
- Full clean production engine run (P&L, CFADS, tax, debt, SHL, BS, XIRR) + HTTP Run + XLSX export.
- OD-TIME-01/v1 dated calendar on EV fails closed explicitly.
- Unaffected Solar, Wind, and Data Center canonical runs execute cleanly.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, getcontext
import io
import math
import uuid

import openpyxl
import pytest

from app import ev_charging_economics as ev
from app.project_factories import (
    create_default_ev_charging_project,
    create_generic_data_center_reference,
    create_generic_ev_charging_reference,
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.production_financial_authority import (
    CleanProductionRunUnavailable,
    run_clean_production,
)
from finco_core.engine.period_engine import PeriodEngine
from finco_core.inputs import PeriodFrequency
from finco_core.revenue.generation import revenue_decomposition_schedule
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401

getcontext().prec = 50


def _decimal_ev_year_revenue_keur(
    *,
    capacity_mw: Decimal = Decimal("5"),
    stabilized_hours: Decimal = Decimal("2000"),
    y1_hours: Decimal = Decimal("1200"),
    y2_hours: Decimal = Decimal("1600"),
    price_eur_kwh: Decimal = Decimal("0.40"),
    price_esc: Decimal = Decimal("0.02"),
    operating_year: int,
    day_fraction_sum: Decimal = Decimal("1"),
) -> Decimal:
    hours = y1_hours if operating_year == 1 else (y2_hours if operating_year == 2 else stabilized_hours)
    rate_eur_mwh = (
        price_eur_kwh * Decimal("1000")
        * (hours / stabilized_hours)
        * ((Decimal("1") + price_esc) ** (operating_year - 1))
    )
    energy_mwh = capacity_mw * stabilized_hours * day_fraction_sum
    return energy_mwh * rate_eur_mwh / Decimal("1000")


def _decimal_ev_year_electricity_opex_keur(
    *,
    capacity_mw: Decimal = Decimal("5"),
    stabilized_hours: Decimal = Decimal("2000"),
    y1_hours: Decimal = Decimal("1200"),
    y2_hours: Decimal = Decimal("1600"),
    efficiency: Decimal = Decimal("0.94"),
    elec_price_eur_kwh: Decimal = Decimal("0.12"),
    elec_esc: Decimal = Decimal("0.02"),
    operating_year: int,
) -> Decimal:
    hours = y1_hours if operating_year == 1 else (y2_hours if operating_year == 2 else stabilized_hours)
    purchased_mwh = capacity_mw * hours / efficiency
    price_eur_mwh = elec_price_eur_kwh * Decimal("1000") * ((Decimal("1") + elec_esc) ** (operating_year - 1))
    return purchased_mwh * price_eur_mwh / Decimal("1000")


def _ev_project_for_timing(fc: date, construction_months: int, cod: date):
    base = create_generic_ev_charging_reference()
    constr_semesters = math.ceil(construction_months / 6)
    senior_tenor = int(base.financing.senior_tenor_years)
    horizon = int(base.info.horizon_years)
    info = replace(
        base.info,
        financial_close=fc,
        construction_months=construction_months,
        cod_date=cod,
    )
    financing = replace(
        base.financing,
        shl_principal_eligibility_start_period=constr_semesters + senior_tenor * 2,
        shl_maturity_period_index=constr_semesters + horizon * 2 - 1,
    )
    capex = base.capex
    if constr_semesters == 1:
        capex_updates = {}
        for f_name, f_val in vars(capex).items():
            if hasattr(f_val, "spending_profile") and f_val.spending_profile:
                capex_updates[f_name] = replace(f_val, y0_share=1.0, spending_profile=())
        if capex_updates:
            capex = replace(capex, **capex_updates)
    replaced = replace(base, info=info, capex=capex, financing=financing)
    return ev.apply_ev_charging_runtime_adapter(replaced, ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS)


@pytest.mark.parametrize(
    "label,fc,construction_months,cod",
    [
        ("6m", date(2030, 1, 1), 6, date(2030, 7, 1)),
        ("12m_ref", date(2030, 1, 1), 12, date(2031, 1, 1)),
        ("18m", date(2029, 7, 1), 18, date(2031, 1, 1)),
        ("24m_orc_ev_align_01", date(2029, 1, 1), 24, date(2031, 1, 1)),
        ("36m", date(2028, 1, 1), 36, date(2031, 1, 1)),
        ("12m_cross_year_cod", date(2030, 5, 15), 12, date(2031, 5, 15)),
    ],
)
def test_ev_durations_and_cross_year_cod_match_decimal50_oracle(label, fc, construction_months, cod):
    pi = _ev_project_for_timing(fc, construction_months, cod)
    assert pi.revenue.market_prices_by_calendar_year_eur_mwh == ()
    assert pi.revenue.market_price_calendar_start_year is None

    clean_run = run_clean_production(pi, "Base", project_type="EV Charging")
    periods = clean_run.g2c_result.financing_result.project_model_result.periods
    op_periods = [p for p in periods if p.is_operation]
    assert len(op_periods) == pi.info.horizon_years * 2

    # Group semestrial operating periods by operating year (year_index 1..20)
    by_year: dict[int, list] = {}
    for p in op_periods:
        by_year.setdefault(int(p.year_index), []).append(p)

    assert sorted(by_year.keys()) == list(range(1, 21))

    # Also compute decomposition directly for day_fraction / cross-year verification
    eng = PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )
    decomps = revenue_decomposition_schedule(pi, eng)
    eng_by_idx = {ep.index: ep for ep in eng.periods()}

    for op_year in (1, 2, 3, 10, 20):
        yp = by_year[op_year]
        assert len(yp) == 2, label
        day_frac_sum = sum(Decimal(str(eng_by_idx[p.period_index].day_fraction)) for p in yp)
        expected_rev = _decimal_ev_year_revenue_keur(
            operating_year=op_year, day_fraction_sum=day_frac_sum
        )
        actual_rev = sum(Decimal(str(p.revenue_keur)) for p in yp)
        assert abs(actual_rev - expected_rev) <= Decimal("1e-9"), (label, op_year, actual_rev, expected_rev)

        # In Jan-1 and mid-year full-365/366 years, confirm exact ORC-EV-ALIGN-01 anchor numbers for Y1/Y2/Y3
        if day_frac_sum == Decimal("1"):
            if op_year == 1:
                assert abs(actual_rev - Decimal("2400")) <= Decimal("1e-9")
            elif op_year == 2:
                assert abs(actual_rev - Decimal("3264")) <= Decimal("1e-9")
            elif op_year == 3:
                assert abs(actual_rev - Decimal("4161.6")) <= Decimal("1e-9")

        # Verify each semestrial decomposition row uses canonical operating-year price (never year-2 price inside year 1)
        expected_rate = (
            Decimal("400")
            * (Decimal("1200" if op_year == 1 else ("1600" if op_year == 2 else "2000")) / Decimal("2000"))
            * (Decimal("1.02") ** (op_year - 1))
        )
        for p in yp:
            d = decomps[p.period_index]
            assert abs(Decimal(str(d["market_price_eur_mwh"])) - expected_rate) <= Decimal("1e-9")

    # Verify Y1 electricity OPEX + total run health (BS balance, XIRR finite, no NaN)
    fs = clean_run.financial_statements_result
    assert fs is not None
    bs_periods = fs.balance_sheet_periods
    assert len(bs_periods) > 0
    for bs_p in bs_periods:
        if bs_p.balance_check_keur is not None:
            assert abs(float(bs_p.balance_check_keur)) <= 1e-4

    # Y1 total OPEX = fixed non-power 960 kEUR + B.08 electricity 765.9574468085107 kEUR = 1725.9574468085107 kEUR
    exp_y1_elec = _decimal_ev_year_electricity_opex_keur(operating_year=1)
    y1_day_frac = sum(Decimal(str(eng_by_idx[p.period_index].day_fraction)) for p in by_year[1])
    exp_y1_total_opex = (Decimal("960") + exp_y1_elec) * y1_day_frac
    actual_y1_opex = sum(Decimal(str(p.opex_keur)) for p in by_year[1])
    assert abs(actual_y1_opex - exp_y1_total_opex) <= Decimal("1e-9")
    if y1_day_frac == Decimal("1"):
        assert abs(actual_y1_opex - Decimal("1725.9574468085106382978723404255319148936170212766")) <= Decimal("1e-9")
    xirr = float(clean_run.g2c_result.return_summary.project.project_xirr)
    assert math.isfinite(xirr)


def test_ev_factory_12m_identical_and_24m_http_run_xlsx_parity(env):  # noqa: F811
    from app.api.project_runner import run_project
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from tests.test_model_react_wf2_projections_v1 import OWNER

    # 1. Default 12m factory keeps exact historical numbers
    pi_12 = create_default_ev_charging_project(construction_months=12)
    run_12 = run_clean_production(pi_12, "Base", project_type="EV Charging")
    op_12 = [p for p in run_12.g2c_result.financing_result.project_model_result.periods if p.is_operation]
    assert sum(p.revenue_keur for p in op_12[:2]) == pytest.approx(2400.0, abs=1e-9)

    # 2. Authentic EV workspace saved with 24m construction (FC=2029-01-01, COD=2031-01-01) -> HTTP Run + XLSX
    ensure_reference_models()
    rec = create_reference_seeded_project(
        user_id=OWNER,
        template_source="generic_ev_charging_reference",
        requested_name="FINCO45A EV 24m",
        capacity_mw=5.0,
    )
    ws = get_workspace_state(OWNER, rec.project_id)
    snap = dict(ws.draft_snapshot)
    snap["financial_close"] = "2029-01-01"
    snap["construction_months"] = "24"
    snap["cod_date"] = "2031-01-01"
    save_workspace_state(
        user_id=OWNER,
        project_id=rec.project_id,
        project_code=rec.project_code,
        draft_snapshot=snap,
        saved_snapshot=snap,
        dirty=False,
        governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
    ws_shell = env.client.get("/v2/model-react/workspace", params={"project": rec.project_code}).json()
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": rec.project_code}).json()
    r_run = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": rec.project_code,
            "csrf_token": runs_meta["run_contract"]["csrf_token"],
            "content_hash": ws_shell["workbook"]["composite_hash"],
            "workbook_version": ws_shell["workbook"]["version"],
            "run_intent_id": str(uuid.uuid4()),
        },
    )
    assert r_run.status_code == 200, r_run.text
    assert r_run.json()["outcome"] == "COMMITTED"
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": rec.project_code}).json()
    assert len(runs_meta["runs"]) >= 1

    stmt = env.client.get("/v2/model-react/statements", params={"project": rec.project_code}).json()
    pnl_sheet = next(
        s for s in stmt["snapshot"]["sheets"]
        if any(r["id"] == "revenues_keur" for r in s["rows"])
    )
    rev_row = next(r for r in pnl_sheet["rows"] if r["id"] == "revenues_keur")
    # In FINCO45A EV 24m (FC=2029, COD=2031), 2031=Y1 (2400), 2032=Y2 (3264), 2033=Y3 (4161.6)
    yr_rev = dict(zip(stmt["snapshot"]["annualPeriods"], rev_row["annual_v"]))
    assert float(yr_rev["2031"]) == pytest.approx(2400.0, abs=0.02)
    assert float(yr_rev["2032"]) == pytest.approx(3264.0, abs=0.02)
    assert float(yr_rev["2033"]) == pytest.approx(4161.6, abs=0.02)

    from app.persistence.run_history_repository import get_latest_history_entry
    entry = get_latest_history_entry(OWNER, rec.project_id)
    assert entry is not None
    op_pnl = entry.financial_statements["pnl"]["periods"][4:]
    assert len(op_pnl) == 40
    assert op_pnl[0]["revenues_keur"] + op_pnl[1]["revenues_keur"] == pytest.approx(2400.0, abs=0.02)
    assert op_pnl[2]["revenues_keur"] + op_pnl[3]["revenues_keur"] == pytest.approx(3264.0, abs=0.02)
    assert op_pnl[4]["revenues_keur"] + op_pnl[5]["revenues_keur"] == pytest.approx(4161.6, abs=0.02)

    r_xlsx = env.client.post(
        "/v2/workbook/export",
        data={"project": rec.project_code, "csrf_token": runs_meta["exports"]["last_run"]["csrf_token"]},
    )
    assert r_xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content), data_only=True)
    assert len(wb.sheetnames) >= 1


def test_ev_od_time_01_dated_calendar_fails_closed():
    base = create_generic_ev_charging_reference()
    dated = replace(
        base,
        info=replace(
            base.info,
            date_authority_version="OD-TIME-01/v1",
        ),
    )
    with pytest.raises(ValueError, match="(DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED|EV_DATED_CALENDAR_UNSUPPORTED)"):
        ev.apply_ev_charging_runtime_adapter(dated, ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS)


def test_unaffected_solar_wind_dc_runs_succeed():
    for kind, pi in (
        ("Solar", create_generic_solar_reference()),
        ("Wind", create_generic_wind_reference()),
        ("Data Center", create_generic_data_center_reference()),
    ):
        res = run_clean_production(pi, "Base", project_type=kind)
        assert res.financial_statements_result is not None
        assert math.isfinite(float(res.g2c_result.return_summary.project.project_xirr))
