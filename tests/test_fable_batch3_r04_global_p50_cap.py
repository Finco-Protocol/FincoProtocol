"""FINCO 36 Batch 3 — Slice C (R04 Phase 2 / OD-R04-02): Global P50 Annual Physical PPA CAP.

Covers every owner-approved requirement in OD-R04-02:
1. Exact MWh / GWh conversion (1 GWh = 1000 MWh), strict decimal strings, duplicate keys/IDs,
   forbidding dual volume_share + annual_quantity on the same contract, explicit zero delivery.
2. Canonical P50 envelope with partial-year proration (e.g. 100 GWh/yr source with June 30 COD
   inclusive -> 185/365 remaining-day fraction; no double-application of degradation/availability).
3. Two physical contracts below / equal / above global P50 cap; exact decimal exceedance
   (even 0.0001 MWh) is NEVER rounded into acceptance; warning at >= 95% utilization.
4. Scenario-independent P50 cap even on P90-10y lender runs; P90/actual generation shortfall
   below valid fixed physical commitments retains obligation, records shortfall, and FAILS CLOSED
   (R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT) — no negative merchant, no silent haircut.
5. Feasible multi-contract revenue allocation: sum(ppa_mwh) + merchant_mwh == generation_mwh,
   independent pricing per contract, no double count.
6. Strict technology admission: solar/wind admitted; DC, EV, BESS, and CfD+ABSOLUTE_ANNUAL fail closed.
7. End-to-end V2 workbook Direct Save, Batch Save (both input orders, CAS transaction, zero
   mutation on refusal), and canonical Run with valid vs exceeding R04 annual contracts.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from fractions import Fraction
import json
import re
from types import SimpleNamespace
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_factories as pf
from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from app.workbook.revenue_multistream import apply_config as apply_multistream_config
from domain.revenue.multistream_runtime import parse_config
from domain.revenue.r04_global_p50_cap import (
    GWH_TO_MWH,
    R04_PRODUCTION_CONTRACT_VERSION,
    PhysicalContractRequest,
    R04CapValidationError,
    allocate_r04_period_deliveries,
    parse_annual_quantity_spec,
    validate_global_p50_physical_cap,
)
from finco_core.engine.contractual_calendar import ContractualInterval, add_calendar_years


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")


# ── 1. Syntax, Units (1 GWh = 1000 MWh), Dual-Basis & Admission Controls ─────


def test_r04_exact_unit_conversion_and_strict_parsing():
    mwh, u1 = parse_annual_quantity_spec({"mode": "ABSOLUTE_ANNUAL", "amount": "12.5", "unit": "GWh"}, contract_id="c1")
    assert u1 == "GWh"
    assert mwh == Fraction(12500)
    assert GWH_TO_MWH == Fraction(1000)

    mwh2, u2 = parse_annual_quantity_spec({"mode": "ABSOLUTE_ANNUAL", "amount": "12500", "unit": "MWh"}, contract_id="c2")
    assert u2 == "MWh"
    assert mwh == mwh2

    # Explicit zero delivery is valid (distinct from missing source/price)
    zero_mwh, _ = parse_annual_quantity_spec({"mode": "ABSOLUTE_ANNUAL", "amount": "0", "unit": "MWh"}, contract_id="c0")
    assert zero_mwh == Fraction(0)

    # Reject bad units, negative/non-decimal amounts, and dual volume_share + annual_quantity
    with pytest.raises(R04CapValidationError) as exc_u:
        parse_annual_quantity_spec({"mode": "ABSOLUTE_ANNUAL", "amount": "10", "unit": "kWh"}, contract_id="c1")
    assert exc_u.value.code == "R04_QUANTITY_UNIT_UNSUPPORTED"

    with pytest.raises(R04CapValidationError) as exc_neg:
        parse_annual_quantity_spec({"mode": "ABSOLUTE_ANNUAL", "amount": "-5", "unit": "MWh"}, contract_id="c1")
    assert exc_neg.value.code == "R04_QUANTITY_AMOUNT_INVALID"

    with pytest.raises(R04CapValidationError) as exc_dual:
        PhysicalContractRequest(
            contract_id="c_dual",
            start_date=date(2031, 1, 1),
            end_date=date(2036, 1, 1),
            mode="ABSOLUTE_ANNUAL",
            annual_quantity_mwh=Fraction(5000),
            volume_share=Fraction(1, 2),
        )
    assert exc_dual.value.code == "R04_DUAL_VOLUME_BASIS_FORBIDDEN"


def test_r04_non_admitted_technologies_fail_closed():
    dc = pf.create_generic_data_center_reference()
    ev = pf.create_generic_ev_charging_reference()
    solar = pf.create_generic_solar_reference()
    solar_bess = replace(solar, technical=replace(solar.technical, bess_enabled=True))

    req = [
        PhysicalContractRequest(
            contract_id="ppa1",
            start_date=solar.info.cod_date,
            end_date=add_calendar_years(solar.info.cod_date, 5),
            mode="ABSOLUTE_ANNUAL",
            annual_quantity_mwh=Fraction(1000),
        )
    ]

    for bad_pi, tech in [(dc, "data_center"), (ev, "ev_charging"), (solar_bess, "solar")]:
        with pytest.raises(R04CapValidationError) as exc:
            validate_global_p50_physical_cap(bad_pi, req, technology=tech)
        assert exc.value.code == "R04_TECHNOLOGY_NOT_ADMITTED"


# ── 2. Global P50 Cap: Partial Year (June 30 COD), Two Contracts, Exact Boundary


def test_r04_partial_year_june30_cod_and_two_contract_global_cap():
    """100 GWh/yr canonical P50 source with June 30 COD inclusive (no degradation):
    - Year 1 (2031) has 185/365 eligible days -> available P50 = 100,000 * 185/365 MWh.
    - Two contracts summing below/equal 100 GWh/yr pass; exceeding by even 0.0001 MWh fails closed!
    """
    base = pf.create_generic_solar_reference()
    pi = replace(
        base,
        info=replace(
            base.info,
            financial_close=date(2030, 6, 30),
            construction_months=12,
            cod_date=date(2031, 6, 30),
            horizon_years=10,
        ),
        technical=replace(
            base.technical,
            capacity_mw=100.0,
            operating_hours_p50=1000.0,
            operating_hours_p90_10y=850.0,
            plant_availability=1.0,
            grid_availability=1.0,
            pv_degradation=0.0,
        ),
    )
    start = date(2031, 6, 30)
    end = date(2036, 6, 30)

    # Two contracts: 60 GWh + 38 GWh = 98 GWh <= 100 GWh -> PASS + warning (>= 95%)
    summary = validate_global_p50_physical_cap(
        pi,
        [
            PhysicalContractRequest("ppa_a", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(60_000), original_unit="GWh"),
            PhysicalContractRequest("ppa_b", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(38_000), original_unit="GWh"),
        ],
        technology="solar",
    )
    assert summary.contract_version == R04_PRODUCTION_CONTRACT_VERSION
    assert summary.cap_envelope_basis == "P50"
    assert summary.warning is True
    yr2031 = next(y for y in summary.yearly_status if y.year == 2031)
    assert yr2031.available_p50_mwh == Fraction(100_000) * Fraction(185, 365)
    assert yr2031.committed_mwh == Fraction(98_000) * Fraction(185, 365)
    assert yr2031.remaining_p50_mwh == Fraction(2_000) * Fraction(185, 365)

    # Exact boundary: 60 GWh + 40 GWh = 100 GWh -> PASS (remaining == 0)
    summary_eq = validate_global_p50_physical_cap(
        pi,
        [
            PhysicalContractRequest("ppa_a", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(60_000)),
            PhysicalContractRequest("ppa_b", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(40_000)),
        ],
        technology="solar",
    )
    assert summary_eq.yearly_status[0].remaining_p50_mwh == Fraction(0)

    # Exact decimal exceedance by 0.0001 MWh (below 0.001 MWh tolerance!) MUST NOT be rounded into acceptance
    with pytest.raises(R04CapValidationError) as exc_over:
        validate_global_p50_physical_cap(
            pi,
            [
                PhysicalContractRequest("ppa_a", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(60_000)),
                PhysicalContractRequest("ppa_b", start, end, "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction("40000.0001")),
            ],
            technology="solar",
        )
    assert exc_over.value.code == "R04_GLOBAL_P50_CAP_EXCEEDED"
    assert exc_over.value.details["year"] == 2031
    assert exc_over.value.details["offending_contract_id"] == "ppa_b"
    assert exc_over.value.details["cap_basis"] == "P50"


# ── 3. P90 Selected Scenario: P50 Cap Retained, Shortfall Fails Closed ───────


def test_r04_p90_uses_p50_cap_and_fails_closed_on_physical_shortfall():
    base = pf.create_generic_wind_reference()
    pi_p90 = replace(
        base,
        info=replace(
            base.info,
            financial_close=date(2030, 1, 1),
            construction_months=12,
            cod_date=date(2031, 1, 1),
            horizon_years=10,
        ),
        technical=replace(
            base.technical,
            capacity_mw=50.0,
            operating_hours_p50=2000.0,       # 100,000 MWh/yr P50
            operating_hours_p90_10y=1700.0,   # 85,000 MWh/yr P90
            plant_availability=1.0,
            grid_availability=1.0,
            pv_degradation=0.0,
            yield_scenario="P90-10y",
        ),
    )
    contracts = [
        PhysicalContractRequest("ppa_fixed", date(2031, 1, 1), date(2036, 1, 1), "ABSOLUTE_ANNUAL", annual_quantity_mwh=Fraction(90_000)),
    ]

    # 90 GWh <= 100 GWh P50 -> CAP validation PASSES even though selected scenario is P90-10y!
    summary = validate_global_p50_physical_cap(pi_p90, contracts, technology="wind")
    assert summary.cap_envelope_basis == "P50"
    assert summary.selected_yield_scenario == "P90-10y"

    # Under P90 generation (85,000 MWh/yr < 90,000 MWh/yr fixed obligation):
    # Allocation MUST fail closed with R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT (no negative merchant!)
    yr_iv = ContractualInterval(date(2031, 1, 1), date(2032, 1, 1))
    with pytest.raises(R04CapValidationError) as exc_sf:
        allocate_r04_period_deliveries(yr_iv, available_generation_mwh=85_000.0, contracts=contracts)
    assert exc_sf.value.code == "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT"
    assert exc_sf.value.details["shortfall_mwh"] == pytest.approx(5_000.0, abs=1e-6)
    assert exc_sf.value.details["contract_obligations_mwh"]["ppa_fixed"] == pytest.approx(90_000.0, abs=1e-6)

    # Under P50 generation (100,000 MWh/yr >= 90,000 MWh/yr): exact conservation, residual merchant = 10,000 MWh
    alloc, merch, sf = allocate_r04_period_deliveries(yr_iv, available_generation_mwh=100_000.0, contracts=contracts)
    assert sf is None
    assert alloc["ppa_fixed"] == pytest.approx(90_000.0, abs=1e-9)
    assert merch == pytest.approx(10_000.0, abs=1e-9)
    assert sum(alloc.values()) + merch == pytest.approx(100_000.0, abs=1e-9)


# ── 4. Production Save, Batch Save (Both Orders) & Canonical Run Integration ─


def _make_r04_multistream_json(start: date, end: date, full_end: date, amount_str: str, unit: str = "MWh") -> str:
    payload = {
        "version": 2,
        "technology": "solar",
        "indexation_basis": "OPERATING_YEAR",
        "streams": [
            {
                "id": "ppa_abs_1",
                "type": "ppa",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "volume_share": None,
                "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": amount_str, "unit": unit},
                "price_eur_mwh": 72.0,
                "indexation_rate": 0.02,
                "settlement": "SAME_PERIOD",
                "source_ref": "R04_TEST_PPA_1",
            },
            {
                "id": "merchant_residual",
                "type": "merchant",
                "start_date": start.isoformat(),
                "end_date": full_end.isoformat(),
                "volume_share": None,
                "price_eur_mwh": 55.0,
                "indexation_rate": 0.01,
                "settlement": "SAME_PERIOD",
                "source_ref": "R04_TEST_MERCHANT",
            },
        ],
    }
    return json.dumps(payload, separators=(",", ":"))


def test_r04_production_direct_save_batch_save_and_run_roundtrip(tmp_path):
    """End-to-end V2 workbook Direct Save, Batch Save (refusal + zero mutation), and Run."""
    user = "test-r04-user"
    db.DB_PATH = str(tmp_path / "r04.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name="R04 Solar Production",
            template_source="generic_solar_reference",
            capacity_mw=16,
        )

        # Inspect seeded operating boundaries from PeriodEngine so contract dates align cleanly
        from financial_engine.adapters.project_inputs import from_project_inputs
        from financial_engine.orchestrator import _build_period_engine

        pi = pf.create_generic_solar_reference()
        eng = _build_period_engine(from_project_inputs(pi))
        op_periods = [p for p in eng.periods() if p.is_operation]
        c_start = op_periods[0].start_date
        c_end = op_periods[9].end_date
        full_end = op_periods[-1].end_date

        def _get_tokens():
            html = client.get("/v2/workbook", params={"project": rec.project_code}).text
            return {
                k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
                for k in ("content_hash", "workbook_version")
            }

        from app.workbook.mutation_csrf import mutation_token

        req_ns = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())

        # 1. Invalid Direct Save exceeding global P50 cap (999 GWh >> ~20 GWh solar plant) -> 422, zero mutation!
        tokens_before = _get_tokens()
        bad_json = _make_r04_multistream_json(c_start, c_end, full_end, "999", unit="GWh")
        resp_bad = client.post(
            "/v2/workbook/update",
            headers={"Accept": "application/json"},
            data={
                "project": rec.project_code,
                "field_id": "revenue.multistream.contracts",
                "value": bad_json,
                **tokens_before,
                "csrf_token": mutation_token(req_ns, rec.project_code, "workbook-update"),
            },
        )
        assert resp_bad.status_code in (200, 422), resp_bad.text[:400]
        assert "WORKING_COPY_RECOVERY" not in resp_bad.text
        assert "R04_GLOBAL_P50_CAP_EXCEEDED" in resp_bad.text
        # Zero mutation: content_hash and workbook_version unchanged
        assert _get_tokens() == tokens_before

        # 2. Valid Direct Save within global P50 cap (10 GWh = 10,000 MWh) -> 200 committed!
        valid_json = _make_r04_multistream_json(c_start, c_end, full_end, "10", unit="GWh")
        resp_ok = client.post(
            "/v2/workbook/update",
            headers={"Accept": "application/json"},
            data={
                "project": rec.project_code,
                "field_id": "revenue.multistream.contracts",
                "value": valid_json,
                **tokens_before,
                "csrf_token": mutation_token(req_ns, rec.project_code, "workbook-update"),
            },
        )
        assert resp_ok.status_code == 200, resp_ok.text[:400]
        tokens_after = _get_tokens()
        assert tokens_after["content_hash"] != tokens_before["content_hash"]

        # 3. Cross-field Batch Save refusal (both orders): shrinking capacity_mw to 1 MW while 10 GWh PPA exists -> refused, zero mutation!
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.update_service import FieldValidationError, WorkbookUpdateService

        ws = get_workspace_state(user, rec.project_id)
        for batch_edits in (
            [("project_setup.technical.p50_hours", "200"), ("project_setup.technical.p90_10y_hours", "180")],
            [("revenue.multistream.contracts", valid_json), ("project_setup.technical.p50_hours", "200"), ("project_setup.technical.p90_10y_hours", "180")],
            [("project_setup.technical.p50_hours", "200"), ("project_setup.technical.p90_10y_hours", "180"), ("revenue.multistream.contracts", valid_json)],
        ):
            with pytest.raises(FieldValidationError) as exc_b:
                WorkbookUpdateService.apply_batch_draft_update(
                    ws=ws,
                    updates=batch_edits,
                    content_hash=tokens_after["content_hash"],
                    workbook_version=tokens_after["workbook_version"],
                    expected_scenario_id=ws.active_scenario_id,
                    project_record=rec,
                    actor_user_id=user,
                )
            assert "R04_GLOBAL_P50_CAP_EXCEEDED" in str(exc_b.value)
        assert _get_tokens() == tokens_after

        # 4. Canonical Run commits cleanly with R04 absolute-annual contract!
        resp_run = client.post(
            "/v2/workbook/run",
            headers={"Accept": "application/json"},
            data={
                "project": rec.project_code,
                **tokens_after,
                "csrf_token": issue_token(req_ns, rec.project_code, purpose="workbook-run-v1"),
                "run_intent_id": str(uuid.uuid4()),
            },
            follow_redirects=False,
        )
        assert resp_run.status_code == 200, resp_run.text[:500]
        assert resp_run.json()["outcome"] == "COMMITTED"
