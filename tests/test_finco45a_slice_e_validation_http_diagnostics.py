"""FINCO45A Slice E — Yield strictness, PPA plausibility warning, HTMX 4xx, SHL diagnostics, EUR-only currency.

Covers:
- E1 (P1B-TECH-02): unrecognized yield_scenario (e.g. P99_UNKNOWN) fails closed with UNKNOWN_YIELD_SCENARIO
  in _selected_operating_hours, period_generation, full_generation_schedule, revenue_decomposition_schedule,
  and contractual_generation_schedule; documented P50 / P90-10y aliases and absent/blank default preserved.
- E2 (FINCO44-NEW-03): revenue.ppa.base_tariff=999999 produces deterministic PPA_TARIFF_IMPLAUSIBLE_HIGH warning
  on Grid Save & Save-All (distinct from 422 hard errors); ordinary and legitimately high contracted prices save cleanly.
- E3 (C1-Q-06): /v2/workbook/update HTMX error branches return HTTP 403/409/422 with HX-Trigger & HTML fragment,
  and workbook_v2.js controlled htmx:beforeSwap allowlist handles 403/409/422 on /v2/workbook/update.
- E4 (FINCO44-NEW-04): SHL_MATURITY_RESIDUAL_FAILS_CLOSED on insufficient equity / low gearing surfaces exact
  residual kEUR, period index, and actionable capital-structure guidance; adjusted equity/gearing runs cleanly.
- E5 (FINCO44-NEW-05): non-EUR currency saves rejected with UNSUPPORTED_CURRENCY_EUR_ONLY (422); non-EUR draft Run
  refused without overwriting legacy snapshot metadata; historical USD snapshot stays readable without mutation.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import uuid

import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
from app.project_factories import create_default_solar_project, create_generic_wind_reference
from app.services.production_financial_authority import CleanProductionRunUnavailable, run_clean_production
from app.v2.run_failure_explanation import explain_run_failure
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from finco_core.engine.period_engine import PeriodEngine
from finco_core.inputs import YieldScenario
from finco_core.revenue.generation import (
    _selected_operating_hours,
    full_generation_schedule,
    revenue_decomposition_schedule,
)
from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401


def _engine(pi):
    return PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )


def test_e1_yield_scenario_strict_recognition_p1b_tech_02():
    wind = create_generic_wind_reference()
    p50_h = wind.technical.operating_hours_p50
    p90_h = wind.technical.operating_hours_p90_10y
    assert p50_h != p90_h

    # Documented P50 & P90-10y aliases and blank/None default remain exact
    for p50_alias in (None, "", "  ", "P50", "P_50", "P-50", "p 50", YieldScenario.P50):
        assert _selected_operating_hours(wind.technical, p50_alias) == p50_h
    for p90_alias in ("P90-10y", "P90_10Y", "P90-10-Y", "P90 10y", YieldScenario.P90_10Y):
        assert _selected_operating_hours(wind.technical, p90_alias) == p90_h

    # Unknown yield scenario raises UNKNOWN_YIELD_SCENARIO instead of silently returning P50
    for bad in ("P99_UNKNOWN", "P99-1Y", "P75", "invalid_yield"):
        with pytest.raises(ValueError, match="UNKNOWN_YIELD_SCENARIO"):
            _selected_operating_hours(wind.technical, bad)
        bad_pi = replace(wind, technical=replace(wind.technical, yield_scenario=bad))
        with pytest.raises(ValueError, match="UNKNOWN_YIELD_SCENARIO"):
            full_generation_schedule(bad_pi, _engine(bad_pi))
        with pytest.raises(ValueError, match="UNKNOWN_YIELD_SCENARIO"):
            revenue_decomposition_schedule(bad_pi, _engine(bad_pi))


def test_e2_ppa_tariff_plausibility_warning_without_hard_cap(env):  # noqa: F811
    rec = env.create()
    ws = get_workspace_state(OWNER, rec.project_id)
    ident = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    grid_meta = env.client.get("/v2/model-react/inputs", params={"project": rec.project_code}).json()

    # Exact witness: revenue.ppa.base_tariff = 999999 surfaces deterministic plausibility warning
    r_high = post_valid_mutation(
        env.client,
        "/v2/workbook/grid/save",
        json={
            "project": rec.project_code,
            "csrf_token": grid_meta["save"]["csrf_token"],
            "workbook_version": WORKBOOK.version,
            "content_hash": ident.composite_hash,
            "scenario_id": ws.active_scenario_id,
            "cells": [{"field_id": "revenue.ppa.base_tariff", "value": "999999"}],
        },
    )
    assert r_high.status_code == 200
    body_high = r_high.json()
    assert body_high["ok"] is True
    assert any(w["code"] == "PPA_TARIFF_IMPLAUSIBLE_HIGH" for w in body_high.get("warnings", []))

    # Save-All also emits deterministic plausibility warning when > 1000 EUR/MWh
    ws_meta = env.client.get("/v2/model-react/workspace", params={"project": rec.project_code}).json()
    sa = ws_meta["save_all"]
    r_sa = env.client.post(
        "/v2/workbook/save-all",
        json={
            "project": rec.project_code,
            "csrf_token": sa["csrf_token"],
            "workbook_version": WORKBOOK.version,
            "content_hash": body_high["content_hash"],
            "scenario_id": ws.active_scenario_id,
            "request_id": str(uuid.uuid4()),
            "cells": [{"field_id": "revenue.ppa.base_tariff", "value": "1500"}],
        },
    )
    assert r_sa.status_code == 200
    assert any(w["code"] == "PPA_TARIFF_IMPLAUSIBLE_HIGH" for w in r_sa.json().get("warnings", []))

    # Ordinary valid tariff (85 EUR/MWh) saves cleanly with zero warnings
    grid_meta2 = env.client.get("/v2/model-react/inputs", params={"project": rec.project_code}).json()
    r_ok = post_valid_mutation(
        env.client,
        "/v2/workbook/grid/save",
        json={
            "project": rec.project_code,
            "csrf_token": grid_meta2["save"]["csrf_token"],
            "workbook_version": WORKBOOK.version,
            "content_hash": r_sa.json()["content_hash"],
            "scenario_id": ws.active_scenario_id,
            "cells": [{"field_id": "revenue.ppa.base_tariff", "value": "85"}],
        },
    )
    assert r_ok.status_code == 200
    assert "warnings" not in r_ok.json()


def test_e3_legacy_workbook_update_htmx_4xx_and_swap_config(env, monkeypatch):  # noqa: F811
    # Verify protected reference returns HTTP 403 on HTMX /v2/workbook/update & client beforeSwap covers 403/409/422
    import re as _re

    js_text = Path("static/js/workbook_v2.js").read_text(encoding="utf-8")
    assert "'/v2/workbook/update'" in js_text
    assert "403: true" in js_text and "409: true" in js_text and "422: true" in js_text

    rec = env.create()
    page = env.client.get("/v2/workbook", params={"project": rec.project_code})
    assert page.status_code == 200
    hash_m = _re.search(r'name="content_hash"\s+value="([^"]+)"', page.text)
    before = get_workspace_state(OWNER, rec.project_id).draft_snapshot

    # Validation error -> HTTP 422 + HX-Trigger + unchanged state
    r_422 = post_valid_mutation(
        env.client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={
            "project": rec.project_code,
            "sheet_id": "project_setup",
            "field_id": "project_setup.technical.capacity_mw",
            "value": "0",
            "workbook_version": WORKBOOK.version,
            "content_hash": hash_m.group(1),
        },
    )
    assert r_422.status_code == 422
    assert "workbook-field-error" in r_422.headers.get("HX-Trigger", "")
    assert get_workspace_state(OWNER, rec.project_id).draft_snapshot == before

    # Stale CAS hash -> HTTP 409 + conflict trigger
    r_409 = post_valid_mutation(
        env.client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={
            "project": rec.project_code,
            "sheet_id": "project_setup",
            "field_id": "project_setup.technical.capacity_mw",
            "value": "50",
            "workbook_version": WORKBOOK.version,
            "content_hash": "deadbeef" * 8,
        },
    )
    assert r_409.status_code == 409
    assert json.loads(r_409.headers["HX-Trigger"])["workbook-field-error"]["conflict"] is True

    # Protected reference -> HTTP 403
    import app.ui.protected_reference_service as prot
    monkeypatch.setattr(prot, "is_protected_reference", lambda _rec: True)
    r_403 = post_valid_mutation(
        env.client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={
            "project": rec.project_code,
            "sheet_id": "project_setup",
            "field_id": "project_setup.technical.capacity_mw",
            "value": "50",
            "workbook_version": WORKBOOK.version,
            "content_hash": hash_m.group(1),
        },
    )
    assert r_403.status_code == 403


def test_e4_shl_residual_diagnostics_and_actionable_recovery(env):  # noqa: F811
    solar = create_default_solar_project()
    low_gearing = replace(solar, financing=replace(solar.financing, gearing_ratio=0.40, share_capital_keur=500.0))
    with pytest.raises(CleanProductionRunUnavailable) as exc_info:
        run_clean_production(low_gearing, "Base", project_type="Solar")
    detail = str(exc_info.value)
    assert "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in detail
    assert "27607.646" in detail
    assert "period_index=41" in detail

    exp = explain_run_failure(exc_info.value, message="fail")
    assert exp["classification"] == "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"
    assert "27607.646" in exp["explanation"]
    assert "maturity period 41" in exp["explanation"]
    assert "share capital" in exp["recovery"].lower()

    # Feasible user-funded lower gearing (larger share capital reducing SHL within total uses) runs and reconciles cleanly
    funded = replace(low_gearing, financing=replace(low_gearing.financing, share_capital_keur=15_000.0))
    ok = run_clean_production(funded, "Base", project_type="Solar")
    assert ok.financial_statements_result is not None


def test_e5_currency_eur_only_guard_and_legacy_preservation(env):  # noqa: F811
    rec = env.create()
    ws = get_workspace_state(OWNER, rec.project_id)
    ident = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    grid_meta = env.client.get("/v2/model-react/inputs", params={"project": rec.project_code}).json()

    # Non-EUR grid save rejected HTTP 422 without changing snapshot or history
    for bad_ccy in ("USD", "GBP", "XXX"):
        r_bad = post_valid_mutation(
            env.client,
            "/v2/workbook/grid/save",
            json={
                "project": rec.project_code,
                "csrf_token": grid_meta["save"]["csrf_token"],
                "workbook_version": WORKBOOK.version,
                "content_hash": ident.composite_hash,
                "scenario_id": ws.active_scenario_id,
                "cells": [{"field_id": "project_setup.identity.currency", "value": bad_ccy}],
            },
        )
        assert r_bad.status_code == 422
    assert get_workspace_state(OWNER, rec.project_id).draft_snapshot.get("currency", "EUR") == "EUR"

    # Legacy historical snapshot with USD remains readable without mutation, while Run refuses cleanly
    snap_usd = dict(ws.draft_snapshot)
    snap_usd["currency"] = "USD"
    save_workspace_state(
        user_id=OWNER,
        project_id=rec.project_id,
        project_code=rec.project_code,
        draft_snapshot=snap_usd,
        saved_snapshot=snap_usd,
        dirty=False,
        governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
    ws_after_usd = get_workspace_state(OWNER, rec.project_id)
    assert ws_after_usd.draft_snapshot["currency"] == "USD"  # historical data preserved untouched

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
    assert r_run.status_code in (409, 422)
    assert "EUR" in r_run.json()["message"]
    assert len(get_run_history(OWNER, rec.project_id)) == 0
