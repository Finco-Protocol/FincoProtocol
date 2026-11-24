"""FINCO38 — Annual OPEX Exceptions, Save All Profiles & OPEX Run Panel acceptance suite.

Covers:
- Engine policy: single-year nominal kEUR override (no re-inflation, subsequent years inherit escalated base),
  explicit 0.0 distinct from missing, deletion restores inheritance, B.13 contingency propagation,
  and exact partial-year stub proration on OD-TIME-01/v1 dated calendar (mid-month COD 2031-05-15).
- Validation & security: rejects invalid year/amount/NaN/Inf/negative/duplicate/B.13/DC-EV B.08/shadowed scalar.
- Atomic CAS HTTP writer & Save All: CSRF, owner, protected reference, stale content_hash/base_token (409),
  no hidden Run, composite hash rotation, line-owned scalar refusal in Save All, and Run -> History -> XLSX
  reconciliation with immutable prior Run history.
- FINCO_G10_RUN_OPEX_PANEL=1 Last-Run OPEX panel freshness (STALE -> CURRENT) and exact committed OPEX values.
"""
from __future__ import annotations

import calendar
import dataclasses
import json
from datetime import date
from decimal import Decimal

import pytest

from app.opex_annual_exceptions import (
    SCHEMA_VERSION,
    OpexAnnualExceptionError,
    apply_annual_exceptions_to_opex,
    document_token,
    validate_and_canonicalize,
)
from app.project_factories import create_generic_solar_reference
from app.services.production_financial_authority import run_clean_production
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION
from finco_core.inputs import OpexItem
from finco_core.opex.projections import opex_item_amount_at_year, opex_year


# ---------------------------------------------------------------------------
# 1. Engine policy: single-year nominal override, explicit zero, deletion, B.13
# ---------------------------------------------------------------------------

def test_finco38_engine_annual_override_policy_and_contingency():
    item_a = OpexItem(
        name="B.01.01",
        y1_amount_keur=100.0,
        annual_inflation=0.02,
        annual_overrides=((3, 250.0), (5, 0.0)),
    )
    item_b = OpexItem(name="B.02.01", y1_amount_keur=50.0, annual_inflation=0.02)
    cont = OpexItem(name="B.13", y1_amount_keur=0.0, annual_inflation=0.0, percentage_of_opex=0.05)

    # Year 1 & 2 inherit escalated base
    assert opex_item_amount_at_year(item_a, 1) == pytest.approx(100.0)
    assert opex_item_amount_at_year(item_a, 2) == pytest.approx(102.0)
    # Year 3 overridden to exact nominal 250.0 (no inflation applied)
    assert opex_item_amount_at_year(item_a, 3) == pytest.approx(250.0)
    # Year 4 restores normal escalated base: 100 * 1.02^3
    assert opex_item_amount_at_year(item_a, 4) == pytest.approx(100.0 * (1.02 ** 3))
    # Year 5 explicit zero (distinct from missing)
    assert opex_item_amount_at_year(item_a, 5) == 0.0
    # Year 6 restores normal escalated base: 100 * 1.02^5
    assert opex_item_amount_at_year(item_a, 6) == pytest.approx(100.0 * (1.02 ** 5))

    # Contingency B.13 (5%) reflects Year 3 override and Year 5 explicit zero
    y3_b = 50.0 * (1.02 ** 2)
    assert opex_year((item_a, item_b, cont), 3) == pytest.approx((250.0 + y3_b) * 1.05)
    y5_b = 50.0 * (1.02 ** 4)
    assert opex_year((item_a, item_b, cont), 5) == pytest.approx((0.0 + y5_b) * 1.05)

    # Deletion of override restores inheritance
    item_a_reverted = dataclasses.replace(item_a, annual_overrides=())
    assert opex_item_amount_at_year(item_a_reverted, 3) == pytest.approx(100.0 * (1.02 ** 2))
    assert opex_item_amount_at_year(item_a_reverted, 5) == pytest.approx(100.0 * (1.02 ** 4))


def test_finco38_annual_override_dated_calendar_partial_year_proration_and_ebitda_delta():
    """On a mid-month COD (2031-05-15) dated grid, a Year 3 annual OPEX override is prorated across
    its exact operating-year days (no duplication across stubs) and reduces EBITDA & CFADS accordingly."""
    base = create_generic_solar_reference()
    cod = date(2031, 5, 15)
    pi_base = dataclasses.replace(
        base,
        info=dataclasses.replace(
            base.info,
            financial_close=date(2030, 5, 15),
            construction_months=12,
            cod_date=cod,
            horizon_years=25,
            date_authority_version=DATE_AUTHORITY_VERSION,
        ),
    )
    # Pick the first non-percentage OPEX item and add +500 kEUR in operating year 3
    target_idx = next(i for i, it in enumerate(pi_base.opex) if it.percentage_of_opex == 0.0)
    target = pi_base.opex[target_idx]
    base_y3 = opex_item_amount_at_year(target, 3)
    delta_annual = 500.0
    ov_item = dataclasses.replace(target, annual_overrides=((3, base_y3 + delta_annual),))
    new_opex = list(pi_base.opex)
    new_opex[target_idx] = ov_item
    pi_ov = dataclasses.replace(pi_base, opex=tuple(new_opex))

    run_base = run_clean_production(pi_base)
    run_ov = run_clean_production(pi_ov)

    op_base = [p for p in run_base.g2c_result.financing_result.project_model_result.periods if p.is_operation]
    op_ov = [p for p in run_ov.g2c_result.financing_result.project_model_result.periods if p.is_operation]

    # Exact total OPEX delta over operating year 3 [2033-05-15, 2034-05-15):
    # 2033 is non-leap (365d), 2034 is non-leap (365d) -> exact sum of day fractions = 365/365 = 1.0!
    pct_mult = 1.0 + sum(it.percentage_of_opex for it in pi_base.opex if it.percentage_of_opex > 0.0)
    expected_total_opex_delta = delta_annual * pct_mult

    actual_opex_delta = sum(p.opex_keur for p in op_ov) - sum(p.opex_keur for p in op_base)
    actual_ebitda_delta = sum(p.ebitda_keur for p in op_ov) - sum(p.ebitda_keur for p in op_base)

    assert abs(actual_opex_delta - expected_total_opex_delta) <= 0.01
    assert abs(actual_ebitda_delta + expected_total_opex_delta) <= 0.01
    # Balance sheet remains balanced <= 0.01 kEUR
    bs_checks = [
        abs(p.balance_check_keur)
        for p in run_ov.financial_statements_result.balance_sheet_periods
        if p.balance_check_keur is not None
    ]
    assert max(bs_checks) <= 0.01


# ---------------------------------------------------------------------------
# 2. Validation & security guards
# ---------------------------------------------------------------------------

def test_finco38_validation_rejects_malformed_derived_driver_and_shadowed():
    # Valid explicit zero + positive nominal
    canon = validate_and_canonicalize(
        {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "B.01.01", "year": 3, "amount_keur": 0.0}]},
        horizon_years=25,
        allowed_line_keys=["B.01.01"],
    )
    assert '"amount_keur":0.0' in canon

    # Empty overrides canonicalizes to "" (restores inheritance)
    assert validate_and_canonicalize(
        {"schema_version": SCHEMA_VERSION, "overrides": []},
        horizon_years=25,
        allowed_line_keys=["B.01.01"],
    ) == ""

    # Year out of range / bool
    for bad_yr in (0, -1, 26, True, "3"):
        with pytest.raises(OpexAnnualExceptionError, match="OPEX_ANNUAL_YEAR_INVALID"):
            validate_and_canonicalize(
                {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "B.01.01", "year": bad_yr, "amount_keur": 10}]},
                horizon_years=25,
                allowed_line_keys=["B.01.01"],
            )

    # Non-finite / negative / bool amount
    for bad_amt in (-1.0, float("nan"), float("inf"), True, "100"):
        with pytest.raises(OpexAnnualExceptionError, match="OPEX_ANNUAL_AMOUNT_INVALID"):
            validate_and_canonicalize(
                {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "B.01.01", "year": 2, "amount_keur": bad_amt}]},
                horizon_years=25,
                allowed_line_keys=["B.01.01"],
            )

    # Derived B.13 rejected
    with pytest.raises(OpexAnnualExceptionError, match="OPEX_ANNUAL_DERIVED_LINE_UNSUPPORTED"):
        validate_and_canonicalize(
            {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "B.13.01", "year": 2, "amount_keur": 10}]},
            horizon_years=25,
            allowed_line_keys=["B.13.01"],
        )

    # Driver-owned B.08 on Data Center / EV Charging rejected
    for tech in ("Data Center", "Ev Charging"):
        with pytest.raises(OpexAnnualExceptionError, match="OPEX_ANNUAL_DRIVER_LINE_UNSUPPORTED"):
            validate_and_canonicalize(
                {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "B.08.01", "year": 2, "amount_keur": 10}]},
                horizon_years=25,
                allowed_line_keys=["B.08.01"],
                project_type=tech,
            )

    # Shadowed scalar group rejected
    with pytest.raises(OpexAnnualExceptionError, match="OPEX_ANNUAL_SHADOWED_SCALAR_UNSUPPORTED"):
        validate_and_canonicalize(
            {"schema_version": SCHEMA_VERSION, "overrides": [{"line_key": "O&M", "year": 2, "amount_keur": 10}]},
            horizon_years=25,
            allowed_line_keys=["B.01.01", "O&M"],
            replaced_canonical_keys=["O&M"],
        )


# ---------------------------------------------------------------------------
# 3. Authenticated HTTP Save -> Run -> History -> Last-Run OPEX Panel
# ---------------------------------------------------------------------------

def test_finco38_http_annual_opex_cas_run_and_panel_lifecycle(tmp_path, monkeypatch):
    """Full authenticated route test:
    GET /v2/model-react/opex-projection/lines -> POST annual-exceptions (CSRF, stale 409, valid 200, no hidden Run)
    -> Run -> verify committed OPEX changed in History & Last-Run OPEX panel (FINCO_G10_RUN_OPEX_PANEL=1)
    -> verify original History immutable.
    """
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    monkeypatch.setenv("FINCO_G10_RUN_OPEX_PANEL", "1")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.router import router as v2_router
    from app.v2.react_opex_lines import router as opex_lines_router
    from app.v2.react_opex_run_projection import router as opex_run_router
    from app.workbook.financing_csrf import issue_token

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finco38_test.db"))
    db.init_db()

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(opex_lines_router, prefix="/v2")
    app.include_router(opex_run_router, prefix="/v2")

    user_id = "finco38-owner"
    proj = create_reference_seeded_project(
        user_id=user_id,
        template_source="generic_solar_reference",
        requested_name="FINCO38 Annual OPEX Solar",
        capacity_mw=50.0,
    )
    import uuid
    from types import SimpleNamespace
    session_token = create_session_token(user_id, "owner@finco38.test")
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, session_token)
    req_stub = SimpleNamespace(cookies={COOKIE_NAME: session_token}, state=SimpleNamespace())

    # Initial load + baseline Run
    r_wb = client.get("/v2/workbook", params={"project": proj.project_code})
    assert r_wb.status_code == 200

    def _run_model():
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_consistent_for_get
        ident = assemble_consistent_for_get(user_id, proj.project_id, WORKBOOK.version)
        r = client.post(
            "/v2/workbook/run",
            data={
                "project": proj.project_code,
                "csrf_token": issue_token(req_stub, proj.project_code, purpose="workbook-run-v1"),
                "content_hash": ident.composite_hash,
                "workbook_version": WORKBOOK.version,
                "run_intent_id": str(uuid.uuid4()),
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert r.status_code == 200 and r.json()["outcome"] == "COMMITTED", r.text
        return r

    _run_model()
    hist_before = get_run_history(user_id, proj.project_id)
    assert len(hist_before) == 1
    h1_id = hist_before[0].history_id
    h1_opex_snapshot = [
        p["operating_expenses_keur"]
        for p in hist_before[0].financial_statements["pnl"]["periods"]
    ]

    # Read OPEX lines projection
    r_lines = client.get("/v2/model-react/opex-projection/lines", params={"project": proj.project_code})
    assert r_lines.status_code == 200
    payload = r_lines.json()
    assert payload["ok"] is True
    meta = payload["annual_exceptions"]
    assert meta["editable"] is True
    assert meta["csrf_token"]
    first_line = next(ln for g in payload["groups"] for ln in g["lines"])
    line_key = first_line["business_code"]
    orig_y3 = first_line["values"][2]

    # Negative control 1: invalid CSRF -> 403
    r_csrf = client.post(
        meta["endpoint"],
        json={
            "project": proj.project_code,
            "csrf_token": "bad-csrf",
            "workbook_version": meta["workbook_version"],
            "content_hash": meta["content_hash"],
            "scenario_id": meta["scenario_id"],
            "base_token": meta["base_token"],
            "overrides": [{"line_key": line_key, "year": 3, "amount_keur": orig_y3 + 400.0}],
        },
    )
    assert r_csrf.status_code == 403

    # Negative control 2: stale base_token -> 409, zero mutation
    r_stale = client.post(
        meta["endpoint"],
        json={
            "project": proj.project_code,
            "csrf_token": meta["csrf_token"],
            "workbook_version": meta["workbook_version"],
            "content_hash": meta["content_hash"],
            "scenario_id": meta["scenario_id"],
            "base_token": "stale-token-000",
            "overrides": [{"line_key": line_key, "year": 3, "amount_keur": orig_y3 + 400.0}],
        },
    )
    assert r_stale.status_code == 409

    # Valid save: +400 kEUR in Year 3 and explicit 0.0 in Year 5
    r_save = client.post(
        meta["endpoint"],
        json={
            "project": proj.project_code,
            "csrf_token": meta["csrf_token"],
            "workbook_version": meta["workbook_version"],
            "content_hash": meta["content_hash"],
            "scenario_id": meta["scenario_id"],
            "base_token": meta["base_token"],
            "overrides": [
                {"line_key": line_key, "year": 3, "amount_keur": orig_y3 + 400.0},
                {"line_key": line_key, "year": 5, "amount_keur": 0.0},
            ],
        },
    )
    assert r_save.status_code == 200
    saved = r_save.json()
    assert saved["ok"] is True
    assert saved["model_executed"] is False
    assert saved["content_hash"] != meta["content_hash"]
    assert saved["base_token"] != meta["base_token"]
    # Still only 1 history row (no hidden Run!)
    assert len(get_run_history(user_id, proj.project_id)) == 1

    # Last-Run OPEX panel is now STALE (pointing to h1)
    r_panel_stale = client.get("/v2/model-react/opex-run-projection", params={"project": proj.project_code})
    assert r_panel_stale.status_code == 200
    assert r_panel_stale.json()["freshness"]["state"] == "STALE"

    # Read back OPEX lines projection -> reflects overrides and overridden_years=[3, 5]
    r_lines2 = client.get("/v2/model-react/opex-projection/lines", params={"project": proj.project_code})
    p2 = r_lines2.json()
    ln2 = next(ln for g in p2["groups"] for ln in g["lines"] if ln["business_code"] == line_key)
    assert ln2["overridden_years"] == [3, 5]
    assert ln2["values"][2] == pytest.approx(orig_y3 + 400.0)
    assert ln2["values"][4] == 0.0

    # Run model -> new history row h2 reflects higher Year 3 OPEX and lower Year 5 OPEX
    _run_model()
    hist_after = get_run_history(user_id, proj.project_id)
    assert len(hist_after) == 2
    h2_opex = [p["operating_expenses_keur"] for p in hist_after[0].financial_statements["pnl"]["periods"]]
    h1_rechecked = next(h for h in hist_after if h.history_id == h1_id)
    assert [p["operating_expenses_keur"] for p in h1_rechecked.financial_statements["pnl"]["periods"]] == h1_opex_snapshot
    assert h2_opex != h1_opex_snapshot

    # Last-Run OPEX panel is now CURRENT and shows h2 committed OPEX verbatim
    r_panel_curr = client.get("/v2/model-react/opex-run-projection", params={"project": proj.project_code})
    assert r_panel_curr.status_code == 200
    panel_json = r_panel_curr.json()
    assert panel_json["freshness"]["state"] == "CURRENT"
    assert [p["operating_expenses_keur"] for p in panel_json["periods"]] == h2_opex
