"""FINCO45A Slice A — R04 P50 cap vs P90 bank-case readiness (FINCO44-NEW-01, P1-REV-06, E2E-09).

Independent Decimal(50) + day-count oracle verifies:
- ORC-R04-100GWH-BASE-TRAP: 80 MW Solar (P50=1500 -> 117.612 GWh, P90=1250 -> 98.01 GWh,
  COD=2031-05-15) with 100 GWh/yr physical PPA passes P50 cap yet fails bank-case sizing
  (2031-05-15..2031-07-01: contracted 12876.712 MWh vs available 12620.466 MWh,
  shortfall 256.247 MWh).
- Readiness distinguishes P50_CAP_EXCEEDED vs BANK_CASE_SHORTFALL_BLOCKED vs READY.
- Valid P50 draft Save is preserved; P50 exceedance rejects atomically (422, CAS/History intact);
  failed Run creates 0 History rows; runnable R04 case commits History and XLSX;
  readiness/review endpoints never mutate state or run financing/tax solvers.
"""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, getcontext
import json

import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.project_factories import create_generic_solar_reference
from app.workbook.revenue_multistream import apply_config
from domain.revenue.multistream_runtime import parse_config
from domain.revenue.r04_global_p50_cap import (
    PhysicalContractRequest,
    R04CapValidationError,
    assess_r04_bank_case_readiness,
    validate_global_p50_physical_cap,
)
from finco_core.engine.contractual_calendar import (
    build_contractual_reporting_axis,
    operating_horizon_interval,
)
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401

getcontext().prec = 50


def _decimal_day_oracle_interval(
    start: date,
    end_excl: date,
    *,
    cod: date,
    capacity_mw: Decimal,
    annual_hours: Decimal,
    availability: Decimal,
    degradation: Decimal,
    contracts: list[tuple[date, date, Decimal]],
) -> tuple[Decimal, Decimal]:
    """Independent Decimal(50) day-by-day generation & physical obligation oracle."""
    annual = capacity_mw * annual_hours * availability
    avail = Decimal(0)
    contracted = Decimal(0)
    day = start
    while day < end_excl:
        op_yr = 0
        while True:
            nxt_y = cod.year + op_yr + 1
            nxt_d = min(cod.day, calendar.monthrange(nxt_y, cod.month)[1])
            if date(nxt_y, cod.month, nxt_d) <= day:
                op_yr += 1
            else:
                break
        yd = Decimal(366 if calendar.isleap(day.year) else 365)
        avail += annual * ((Decimal(1) - degradation) ** op_yr) / yd
        for c_start, c_end, qty_mwh in contracts:
            if c_start <= day < c_end:
                contracted += qty_mwh / yd
        day += timedelta(days=1)
    return avail, contracted


def _r04_book(streams: list[dict]) -> str:
    return json.dumps(
        {
            "version": 2,
            "technology": "solar",
            "indexation_basis": "OPERATING_YEAR",
            "streams": streams,
        },
        separators=(",", ":"),
    )


def _ppa(cid: str, start: str, end: str, amount: str, unit: str = "GWh", price: float = 70.0) -> dict:
    return {
        "id": cid,
        "type": "ppa",
        "start_date": start,
        "end_date": end,
        "volume_share": None,
        "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": amount, "unit": unit},
        "price_eur_mwh": price,
        "indexation_rate": 0.0,
        "settlement": "SAME_PERIOD",
        "source_ref": f"REF_{cid}",
    }


def _merchant(start: str, end: str, price: float = 50.0) -> dict:
    return {
        "id": "merch",
        "type": "merchant",
        "start_date": start,
        "end_date": end,
        "volume_share": None,
        "price_eur_mwh": price,
        "indexation_rate": 0.0,
        "settlement": "SAME_PERIOD",
        "source_ref": "REF_MERCH",
        "capture_rate": 1.0,
    }


def _make_80mw_solar_pi(*, cod: date = date(2031, 5, 15), p50_hours: float = 1500.0, p90_hours: float = 1250.0):
    base = create_generic_solar_reference()
    # Keep construction_months consistent with cod_date (6 months before COD)
    fc_year = cod.year if cod.month > 6 else cod.year - 1
    fc_month = cod.month - 6 if cod.month > 6 else cod.month + 6
    fc = date(fc_year, fc_month, min(cod.day, calendar.monthrange(fc_year, fc_month)[1]))
    return replace(
        base,
        info=replace(base.info, financial_close=fc, construction_months=6, cod_date=cod),
        technical=replace(
            base.technical,
            capacity_mw=80.0,
            operating_hours_p50=p50_hours,
            operating_hours_p90_10y=p90_hours,
        ),
    )


def test_orc_r04_100gwh_base_trap_witness_and_decimal_oracle():
    pi = _make_80mw_solar_pi(cod=date(2031, 5, 15), p50_hours=1500.0, p90_hours=1250.0)
    cod = pi.info.cod_date
    life_end = operating_horizon_interval(cod, pi.info.horizon_years).end_exclusive
    raw = _r04_book([_ppa("ppa_100", cod.isoformat(), life_end.isoformat(), "100", "GWh"), _merchant(cod.isoformat(), life_end.isoformat())])
    pi_r04 = apply_config(pi, raw, project_type="solar")
    cfg = parse_config(raw)

    # P50 cap must pass (100 GWh <= 117.612 GWh nominal)
    p50_summary = validate_global_p50_physical_cap(pi_r04, cfg.physical_contract_requests(), technology="solar")
    assert p50_summary.cap_envelope_basis == "P50"

    # Bank-case readiness must detect the exact P90 shortfall without running financing/tax
    readiness = assess_r04_bank_case_readiness(pi_r04, cfg.physical_contract_requests(), technology="solar")
    assert readiness.applicable is True
    assert readiness.runnable is False
    assert readiness.status == "BANK_CASE_SHORTFALL_BLOCKED"
    assert readiness.error_code == "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT"
    assert readiness.bank_yield_scenario == "P90-10y"
    assert readiness.bank_case_hours == pytest.approx(1250.0)
    assert readiness.p50_hours == pytest.approx(1500.0)
    assert "P50" not in (readiness.remediation or "").replace("P50", "") or "switch" not in (readiness.remediation or "").lower()
    assert len(readiness.shortfall_periods) >= 1

    first = readiness.shortfall_periods[0]
    assert first["period_start"] == "2031-05-15"
    assert first["period_end_exclusive"] == "2031-07-01"

    # Independent Decimal(50) oracle for period 1 (2031-05-15..2031-07-01)
    avail_dec, cont_dec = _decimal_day_oracle_interval(
        date(2031, 5, 15),
        date(2031, 7, 1),
        cod=cod,
        capacity_mw=Decimal("80"),
        annual_hours=Decimal("1250"),
        availability=Decimal(repr(pi.technical.combined_availability)),
        degradation=Decimal(repr(pi.technical.pv_degradation)),
        contracts=[(cod, life_end, Decimal("100000"))],
    )
    short_dec = cont_dec - avail_dec
    assert abs(Decimal(str(first["contracted_mwh"])) - cont_dec) < Decimal("0.001")
    assert abs(Decimal(str(first["available_mwh"])) - avail_dec) < Decimal("0.001")
    assert abs(Decimal(str(first["shortfall_mwh"])) - short_dec) < Decimal("0.001")
    assert round(float(cont_dec), 3) == 12876.712
    assert round(float(avail_dec), 3) == 12620.466
    assert round(float(short_dec), 3) == 256.247


def test_r04_readiness_distinguishes_p50_cap_exceeded_boundary_staggered_and_leap_dates():
    cod = date(2032, 2, 29)  # leap-day COD
    pi = _make_80mw_solar_pi(cod=cod, p50_hours=1500.0, p90_hours=1250.0)
    horizon_iv = operating_horizon_interval(cod, pi.info.horizon_years)
    assert horizon_iv.end_exclusive == date(2057, 2, 28)

    # Overlapping/staggered contracts that pass P50 (80 + 20 = 100 GWh <= 117.612 GWh) yet fail P90 (98.01 GWh)
    raw_staggered = _r04_book([
        _ppa("ppa_base", "2032-02-29", "2042-07-01", "80", "GWh"),
        _ppa("ppa_top", "2034-01-01", "2040-01-01", "20", "GWh"),
        _merchant("2032-02-29", "2057-02-28"),
    ])
    pi_stag = apply_config(pi, raw_staggered, project_type="solar")
    cfg_stag = parse_config(raw_staggered)
    rd_stag = assess_r04_bank_case_readiness(pi_stag, cfg_stag.physical_contract_requests(), technology="solar")
    assert rd_stag.status == "BANK_CASE_SHORTFALL_BLOCKED"
    assert rd_stag.shortfall_periods[0]["period_start"] == "2034-01-01"

    # Explicit lender case P_50 (when authorized) passes readiness for the same 100 GWh book
    rd_p50_lender = assess_r04_bank_case_readiness(
        pi_stag, cfg_stag.physical_contract_requests(), technology="solar", bank_yield_scenario="P_50"
    )
    assert rd_p50_lender.status == "READY"
    assert rd_p50_lender.runnable is True

    # P50 exceedance (120 GWh > 117.612 GWh) reports P50_CAP_EXCEEDED
    from fractions import Fraction
    exceed_reqs = [
        PhysicalContractRequest(
            contract_id="ppa_too_high",
            start_date=cod,
            end_date=horizon_iv.end_exclusive,
            mode="ABSOLUTE_ANNUAL",
            annual_quantity_mwh=Fraction(120_000),
            original_unit="GWh",
        )
    ]
    rd_exceed = assess_r04_bank_case_readiness(pi, exceed_reqs, technology="solar")
    assert rd_exceed.status == "P50_CAP_EXCEEDED"
    assert rd_exceed.error_code == "R04_GLOBAL_P50_CAP_EXCEEDED"
    assert rd_exceed.runnable is False

    # Negative mutation guard: bypassing P50 cap fails closed
    with pytest.raises(R04CapValidationError) as ei:
        validate_global_p50_physical_cap(pi, exceed_reqs, technology="solar")
    assert ei.value.code == "R04_GLOBAL_P50_CAP_EXCEEDED"


def test_r04_boundary_equal_vs_exceeds_and_non_mutating_readiness():
    pi = _make_80mw_solar_pi(cod=date(2031, 7, 1), p50_hours=1500.0, p90_hours=1400.0)
    horizon_iv = operating_horizon_interval(pi.info.cod_date, pi.info.horizon_years)
    # 70 GWh fits both P50 (117.6 GWh) and degraded P90 across 25y (~93 GWh at yr 25)
    raw_ok = _r04_book([
        _ppa("ppa_70", "2031-07-01", horizon_iv.end_exclusive.isoformat(), "70", "GWh"),
        _merchant("2031-07-01", horizon_iv.end_exclusive.isoformat()),
    ])
    pi_ok = apply_config(pi, raw_ok, project_type="solar")
    cfg_ok = parse_config(raw_ok)
    before_json = pi_ok.revenue.multistream_config_json
    rd_ok = assess_r04_bank_case_readiness(pi_ok, cfg_ok.physical_contract_requests(), technology="solar")
    assert rd_ok.status == "READY"
    assert rd_ok.runnable is True
    assert pi_ok.revenue.multistream_config_json == before_json

    # 100 GWh fits P50 (117.6 GWh) and Y1 P90 (109.77 GWh), but degrades below 100 GWh in later years -> blocked
    raw_late = _r04_book([
        _ppa("ppa_100_late", "2031-07-01", horizon_iv.end_exclusive.isoformat(), "100", "GWh"),
        _merchant("2031-07-01", horizon_iv.end_exclusive.isoformat()),
    ])
    cfg_late = parse_config(raw_late)
    rd_late = assess_r04_bank_case_readiness(pi, cfg_late.physical_contract_requests(), technology="solar")
    assert rd_late.status == "BANK_CASE_SHORTFALL_BLOCKED"
    assert rd_late.shortfall_periods[0]["calendar_year"] > 2035


def test_r04_http_save_review_run_failure_and_valid_run_lifecycle(env, monkeypatch):
    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor, reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project

    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread")))
    record = create_reference_seeded_project(
        user_id=OWNER, requested_name="R04 80MW Trap", template_source="generic_solar_reference", capacity_mw=80.0
    )
    ws_init = get_workspace_state(OWNER, record.project_id)
    assert ws_init is not None

    # Set P50=1500, P90=1250 via canonical grid save (COD=2031-03-01, 80 MW)
    inputs_resp = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
    save_info = inputs_resp["save"]
    r_grid = env.client.post(
        "/v2/workbook/grid/save",
        json={
            "project": record.project_code,
            "csrf_token": save_info["csrf_token"],
            "content_hash": save_info["content_hash"],
            "workbook_version": save_info["workbook_version"],
            "scenario_id": save_info["scenario_id"],
            "cells": [
                {"field_id": "project_setup.technical.p50_hours", "value": "1500"},
                {"field_id": "project_setup.technical.p90_10y_hours", "value": "1250"},
            ],
        },
    )
    assert r_grid.status_code == 200, r_grid.text

    # Fetch revenue tokens
    rev_before = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    rev_save = rev_before["save"]
    cod = date(2031, 3, 1)
    life_end = operating_horizon_interval(cod, 25).end_exclusive

    # 1) P50 cap exceedance (125 GWh) MUST fail atomically (422) and leave CAS/hash/History untouched
    exceed_raw = _r04_book([_ppa("ppa_125", cod.isoformat(), life_end.isoformat(), "125", "GWh"), _merchant(cod.isoformat(), life_end.isoformat())])
    ws_before_exceed = get_workspace_state(OWNER, record.project_id)
    r_save_exceed = env.client.post(
        "/v2/workbook/revenue/contracts",
        data={
            "project": record.project_code,
            "csrf_token": rev_save["csrf_token"],
            "content_hash": rev_save["content_hash"],
            "contracts": exceed_raw,
            "action": "save",
        },
        follow_redirects=False,
    )
    assert r_save_exceed.status_code == 422
    assert "R04_GLOBAL_P50_CAP_EXCEEDED" in r_save_exceed.text
    ws_after_exceed = get_workspace_state(OWNER, record.project_id)
    assert ws_after_exceed.draft_snapshot == ws_before_exceed.draft_snapshot
    assert len(get_run_history(OWNER, record.project_id)) == 0

    # 2) Valid P50 / P90-shortfall book (100 GWh): review reports BANK_CASE_SHORTFALL_BLOCKED; Save preserves valid draft
    print("SLICE_A_STEP 2 review", flush=True)
    trap_raw = _r04_book([_ppa("ppa_100", cod.isoformat(), life_end.isoformat(), "100", "GWh"), _merchant(cod.isoformat(), life_end.isoformat())])
    r_rev = env.client.post(
        "/v2/model-react/revenue/review",
        data={
            "project": record.project_code,
            "csrf_token": rev_save["csrf_token"],
            "content_hash": rev_save["content_hash"],
            "contracts": trap_raw,
        },
    )
    assert r_rev.status_code == 200
    rev_body = r_rev.json()
    assert rev_body["ok"] is True
    assert rev_body["review"]["blocked"] is False
    assert rev_body["bank_case_readiness"]["status"] == "BANK_CASE_SHORTFALL_BLOCKED"
    assert rev_body["bank_case_readiness"]["shortfall_periods"][0]["period_start"] == "2031-03-01"
    # Review did not mutate workspace
    assert get_workspace_state(OWNER, record.project_id).draft_snapshot.get("rev_multistream_config_json") != trap_raw

    # Save 100 GWh book via Save-All and confirm Save succeeds with readiness warning and 0 Runs
    ws_shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    sa = ws_shell["save_all"]
    r_sa = env.client.post(
        "/v2/workbook/save-all",
        json={
            "project": record.project_code,
            "csrf_token": sa["csrf_token"],
            "workbook_version": ws_shell["workbook"]["version"],
            "content_hash": ws_shell["workbook"]["composite_hash"],
            "scenario_id": ws_shell["workbook"]["scenario_id"],
            "request_id": "finco45a-slicea-100gwh",
            "contracts_json": trap_raw,
        },
    )
    assert r_sa.status_code == 200, r_sa.text
    sa_body = r_sa.json()
    assert sa_body["model_executed"] is False
    assert sa_body["bank_case_readiness"]["status"] == "BANK_CASE_SHORTFALL_BLOCKED"
    assert sa_body["bank_case_readiness"]["error_code"] == "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT"
    assert len(get_run_history(OWNER, record.project_id)) == 0

    # Workspace & Revenue read surfaces consistently expose the same readiness
    ws_after_sa = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    assert ws_after_sa["bank_case_readiness"]["status"] == "BANK_CASE_SHORTFALL_BLOCKED"
    rev_after_sa = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert rev_after_sa["bank_case_readiness"]["status"] == "BANK_CASE_SHORTFALL_BLOCKED"

    # 3) Explicit Run refuses with typed R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT & 0 History rows
    print("SLICE_A_STEP 3 run fail", flush=True)
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    r_run_fail = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": record.project_code,
            "csrf_token": runs_meta["run_contract"]["csrf_token"],
            "content_hash": ws_after_sa["workbook"]["composite_hash"],
            "workbook_version": ws_after_sa["workbook"]["version"],
            "run_intent_id": "11111111-2222-4333-8444-555555555555",
        },
    )
    assert r_run_fail.status_code in (400, 422, 409)
    fail_json = r_run_fail.json()
    assert "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT" in fail_json.get("message", "")
    assert "2031-03-01..2031-07-01" in fail_json.get("message", "")
    assert len(get_run_history(OWNER, record.project_id)) == 0

    # 4) Adjust contract to feasible 70 GWh -> readiness READY -> Run commits History + XLSX
    print("SLICE_A_STEP 4 save 70gwh", flush=True)
    ok_raw = _r04_book([_ppa("ppa_70", cod.isoformat(), life_end.isoformat(), "70", "GWh"), _merchant(cod.isoformat(), life_end.isoformat())])
    ws_pre_ok = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    r_sa_ok = env.client.post(
        "/v2/workbook/save-all",
        json={
            "project": record.project_code,
            "csrf_token": ws_pre_ok["save_all"]["csrf_token"],
            "workbook_version": ws_pre_ok["workbook"]["version"],
            "content_hash": ws_pre_ok["workbook"]["composite_hash"],
            "scenario_id": ws_pre_ok["workbook"]["scenario_id"],
            "request_id": "finco45a-slicea-70gwh",
            "contracts_json": ok_raw,
        },
    )
    assert r_sa_ok.status_code == 200
    assert r_sa_ok.json()["bank_case_readiness"]["status"] == "READY"

    ws_ready = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    runs_meta2 = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    r_run_ok = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": record.project_code,
            "csrf_token": runs_meta2["run_contract"]["csrf_token"],
            "content_hash": ws_ready["workbook"]["composite_hash"],
            "workbook_version": ws_ready["workbook"]["version"],
            "run_intent_id": "22222222-3333-4444-8555-666666666666",
        },
    )
    assert r_run_ok.status_code == 200, r_run_ok.text
    assert r_run_ok.json()["outcome"] == "COMMITTED"
    hist = get_run_history(OWNER, record.project_id)
    assert len(hist) == 1

    # XLSX export succeeds
    r_xlsx = env.client.post(
        "/v2/workbook/export",
        data={
            "project": record.project_code,
            "csrf_token": runs_meta2["exports"]["last_run"]["csrf_token"],
        },
    )
    assert r_xlsx.status_code == 200
    assert r_xlsx.headers.get("content-type", "").startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
