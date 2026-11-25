"""FINCO45A Correction A — Balancing Schedule Precedence (D-CORR-01),
OPEX Preview Authority & Snapshot Coherence (B-CORR-01), and Narrow R04/PPA Guards.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, getcontext
import json
import threading
import uuid

import pytest

from app.input_adapter import build_projectinputs_from_snapshot
from app.persistence.db import get_cursor
from app.persistence.run_history_repository import get_run_history
from app.persistence.scenarios_repository import add_scenario, get_or_create_base_case_scenario
from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from app.v2.opex_commands import add_opex_line
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from finco_core.engine.period_engine import PeriodEngine
from finco_core.inputs import RevenueAdjustmentSchedule
from finco_core.revenue.generation import revenue_decomposition_schedule, validate_balancing_cost_inputs
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401

getcontext().prec = 50


def _engine(pi):
    return PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )


# ── D-CORR-01: Balancing Schedule Precedence ───────────────────────────────────


def test_dcorr01_zero_schedule_masks_nonzero_scalars_and_matches_decimal50_oracle():
    solar = create_generic_solar_reference()
    # Canonical case from prompt: pct=0.025 + constant_value=0.0 schedule + shadowed scalar=8.0 & wind_fallback=8.0
    masked = replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(constant_value=0.0),
            balancing_cost_eur_per_mwh=8.0,
            balancing_cost_wind_eur_mwh=8.0,
        ),
    )
    validate_balancing_cost_inputs(masked.revenue, horizon_years=masked.info.horizon_years)
    decomps = revenue_decomposition_schedule(masked, _engine(masked))
    op_rows = [d for d in decomps.values() if d["is_operation"]]
    assert op_rows
    for d in op_rows:
        assert d["balancing_cost_eur_mwh"] == 0.0
        assert d["balancing_cost_wind_keur"] == 0.0
        expected_pct = Decimal(str(d["gross_merchant_revenue_keur"])) * Decimal("0.025")
        assert abs(Decimal(str(d["balancing_cost_keur"])) - expected_pct) <= Decimal("1e-9")

    # Partial semiannual schedule (0.0, 0.0) masking annual_values[0]=5.0 still succeeds when remaining periods are 0.0
    masked_annual = replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(
                constant_value=0.0,
                annual_values=(5.0, 0.0),
                semiannual_values=(0.0, 0.0),
            ),
            balancing_cost_eur_per_mwh=8.0,
            balancing_cost_wind_eur_mwh=8.0,
        ),
    )
    validate_balancing_cost_inputs(masked_annual.revenue, horizon_years=masked_annual.info.horizon_years)
    decomps_masked = revenue_decomposition_schedule(masked_annual, _engine(masked_annual))
    assert all(d["balancing_cost_wind_keur"] == 0.0 for d in decomps_masked.values() if d["is_operation"])

    # Entries strictly beyond active horizon do not trigger false dual rejection when active horizon is all 0.0
    beyond_horizon = replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(
                constant_value=0.0,
                annual_values=(0.0,) * int(solar.info.horizon_years) + (9.0,),
            ),
            balancing_cost_eur_per_mwh=8.0,
        ),
    )
    validate_balancing_cost_inputs(beyond_horizon.revenue, horizon_years=beyond_horizon.info.horizon_years)
    decomps_beyond = revenue_decomposition_schedule(beyond_horizon, _engine(beyond_horizon))
    assert all(d["balancing_cost_wind_keur"] == 0.0 for d in decomps_beyond.values() if d["is_operation"])


def test_dcorr01_genuine_dual_and_invalid_values_still_rejected():
    solar = create_generic_solar_reference()
    # Unmasked partial semiannual exposing nonzero annual_values[0]=5.0 in H2 -> REJECTED
    exposed_h2 = replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_production_share=0.5,
            balancing_cost_pv=0.025,
            balancing_cost_schedule=RevenueAdjustmentSchedule(
                constant_value=0.0,
                annual_values=(5.0, 0.0),
                semiannual_values=(0.0,),
            ),
        ),
    )
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        validate_balancing_cost_inputs(exposed_h2.revenue, horizon_years=exposed_h2.info.horizon_years)
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        revenue_decomposition_schedule(exposed_h2, _engine(exposed_h2))

    # Direct legacy RevenueParams with sched=None, per_mwh=0.0, wind_mwh=8.0 + pct=0.025 -> REJECTED
    legacy_wind = create_generic_wind_reference()
    dual_legacy = replace(
        legacy_wind,
        revenue=replace(legacy_wind.revenue, balancing_cost_pv=0.025, balancing_cost_eur_per_mwh=0.0, balancing_cost_wind_eur_mwh=8.0),
    )
    assert dual_legacy.revenue.balancing_cost_schedule is None
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        validate_balancing_cost_inputs(dual_legacy.revenue, horizon_years=dual_legacy.info.horizon_years)

    # Nonfinite / negative checks unchanged (even if shadowed!)
    bad_shadowed = replace(
        solar,
        revenue=replace(
            solar.revenue,
            balancing_cost_pv=0.0,
            balancing_cost_schedule=RevenueAdjustmentSchedule(constant_value=0.0, annual_values=(-1.0,)),
        ),
    )
    with pytest.raises(ValueError, match="BALANCING_COST_INVALID"):
        validate_balancing_cost_inputs(bad_shadowed.revenue)

    bad_scalar = replace(solar, revenue=replace(solar.revenue, balancing_cost_eur_per_mwh=float("nan")))
    with pytest.raises(ValueError, match="BALANCING_COST_INVALID"):
        validate_balancing_cost_inputs(bad_scalar.revenue)

    # Explicit 0.0 at snapshot adapter overrides Wind default 8.0 (F2-NEW-01)
    pi_explicit_zero = build_projectinputs_from_snapshot({
        "project_type": "Wind",
        "project_name": "Wind F2-NEW-01",
        "country_market": "DE",
        "capacity_mw": "50",
        "cod_date": "2031-01-01",
        "construction_months": "12",
        "horizon_years": "25",
        "p50_hours": "3000",
        "tariff_eur_mwh": "60",
        "ppa_term_years": "12",
        "total_capex_keur": "55000",
        "opex_y1_keur": "1500",
        "interest_rate_pct": "5.5",
        "_finval_interest_rate_unit": "human_percent_v1",
        "tenor_years": "15",
        "target_dscr": "1.2",
        "rev_ppa_production_share": "60.0",
        "rev_merchant_balancing_pct": "2.5",
        "rev_balancing_cost_eur_per_mwh": "0.0",
    })
    assert pi_explicit_zero.revenue.balancing_cost_eur_per_mwh == 0.0
    assert pi_explicit_zero.revenue.balancing_cost_wind_eur_mwh == 0.0
    decomps_z = revenue_decomposition_schedule(pi_explicit_zero, _engine(pi_explicit_zero))
    assert all(d["balancing_cost_wind_keur"] == 0.0 for d in decomps_z.values() if d["is_operation"])


# ── B-CORR-01: OPEX Preview Authority Parity, History Freshness & Concurrency ───


def _grid_save(client, project_code, ws, ident, cells):
    inputs = client.get("/v2/model-react/inputs", params={"project": project_code}).json()
    return client.post(
        "/v2/workbook/grid/save",
        json={
            "project": project_code,
            "csrf_token": inputs["save"]["csrf_token"],
            "workbook_version": WORKBOOK.version,
            "content_hash": ident.composite_hash,
            "scenario_id": ws.active_scenario_id,
            "cells": cells,
        },
    )


def _create_custom_scenario(record, *, name: str, overrides: dict, replay_metadata: dict | None = None, base_input_set: dict | None = None, switch: bool = True):
    ws = get_workspace_state(OWNER, record.project_id)
    base_snap = dict(base_input_set if base_input_set is not None else ws.draft_snapshot)
    base_sc = get_or_create_base_case_scenario(
        user_id=OWNER,
        project_id=record.project_id,
        project_code=record.project_code,
        project_name=record.project_name,
        project_type=record.project_type,
        source_project_template=record.template_source,
        base_input_set=base_snap,
        governance_state=ws.governance_state or {},
    )
    sc = add_scenario(
        user_id=OWNER,
        project_id=record.project_id,
        project_code=record.project_code,
        scenario_name=name,
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=base_snap,
        overrides=overrides,
        replay_metadata=replay_metadata or {},
    )
    if replay_metadata:
        meta = dict(sc.replay_metadata or {})
        meta.update(replay_metadata)
        with get_cursor() as cur:
            cur.execute("UPDATE scenarios SET replay_metadata_json=? WHERE scenario_id=?", (json.dumps(meta), sc.scenario_id))
    if switch:
        ws_now = get_workspace_state(OWNER, record.project_id)
        save_workspace_state(
            user_id=OWNER,
            project_id=record.project_id,
            project_code=record.project_code,
            draft_snapshot=ws_now.draft_snapshot,
            saved_snapshot=ws_now.saved_snapshot,
            dirty=ws_now.dirty,
            governance_state=ws_now.governance_state,
            replay_metadata=ws_now.replay_metadata,
            active_scenario_id=sc.scenario_id,
            active_scenario_name=name,
        )
    return sc


def test_bcorr01_q4_stale_unbound_invalid_scenarios_and_run_parity(env, monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    rec = env.create()
    ws0 = get_workspace_state(OWNER, rec.project_id)

    # 1. Valid Q4 scenario (QM-SD-006 -> debt.senior.gearing_pct -> gearing_pct) -> preview OK & NOT_RUN
    sc_q4 = _create_custom_scenario(
        rec,
        name="Q4 Gearing 68",
        overrides={"gearing_pct": "68"},
        replay_metadata={
            "action": "q4_finding_whatif_v1",
            "finding_id": "QM-SD-006",
            "field_id": "debt.senior.gearing_pct",
        },
        base_input_set=ws0.draft_snapshot,
    )
    proj_q4 = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code})
    assert proj_q4.status_code == 200
    prev_q4 = proj_q4.json()["operating_preview"]
    assert prev_q4["available"] is True and prev_q4["status"] == "OK"
    assert prev_q4["freshness"]["scenario_id"] == sc_q4.scenario_id
    assert prev_q4["freshness"]["state"] == "NOT_RUN"
    assert prev_q4["freshness"]["last_run_history_id"] is None

    # 1b. Invalid Q4 finding_id rejected identically to Run
    _create_custom_scenario(
        rec,
        name="Invalid Q4 Key",
        overrides={"rev_ppa_base_tariff": "88"},
        replay_metadata={
            "action": "q4_finding_whatif_v1",
            "finding_id": "tariff_eur_mwh",
            "field_id": "revenue.ppa.base_tariff",
        },
        base_input_set=ws0.draft_snapshot,
    )
    proj_bad_q4 = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_bad_q4["operating_preview"]["available"] is False
    assert proj_bad_q4["operating_preview"]["code"] in (
        "SCENARIO_OVERRIDE_UNBOUND",
        "Q4_SCENARIO_OVERRIDE_AUTHORITY_INVALID",
    )

    # Re-activate valid Q4 scenario before unrelated draft edit
    save_workspace_state(
        user_id=OWNER,
        project_id=rec.project_id,
        project_code=rec.project_code,
        draft_snapshot=ws0.draft_snapshot,
        saved_snapshot=ws0.saved_snapshot,
        dirty=ws0.dirty,
        governance_state=ws0.governance_state,
        replay_metadata=ws0.replay_metadata,
        active_scenario_id=sc_q4.scenario_id,
        active_scenario_name="Q4 Gearing 68",
    )

    # 2. Unrelated draft edit invalidates Q4 source -> preview MUST refuse Q4_SCENARIO_SOURCE_CHANGED_REPREVIEW_REQUIRED (same as Run)
    ws_q4 = get_workspace_state(OWNER, rec.project_id)
    ident_q4 = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    r_edit = _grid_save(env.client, rec.project_code, ws_q4, ident_q4, [{"field_id": "project_setup.technical.p50_hours", "value": "1525"}])
    assert r_edit.status_code == 200, r_edit.text
    proj_stale_q4 = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_stale_q4["operating_preview"]["available"] is False
    assert proj_stale_q4["operating_preview"]["code"] == "Q4_SCENARIO_SOURCE_CHANGED_REPREVIEW_REQUIRED"
    # HTTP Run must also reject stale Q4 identically and append zero History rows
    hist_before_stale = len(get_run_history(OWNER, rec.project_id))
    runs_q4 = env.client.get("/v2/model-react/runs", params={"project": rec.project_code}).json()
    ident_stale = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    r_run_stale = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": rec.project_code,
            "csrf_token": runs_q4["run_contract"]["csrf_token"],
            "content_hash": ident_stale.composite_hash,
            "workbook_version": WORKBOOK.version,
            "run_intent_id": str(uuid.uuid4()),
        },
        follow_redirects=False,
    )
    assert r_run_stale.status_code == 303, r_run_stale.text
    assert "Q4_SCENARIO_SOURCE_CHANGED_REPREVIEW_REQUIRED" in r_run_stale.headers.get("location", "")
    assert len(get_run_history(OWNER, rec.project_id)) == hist_before_stale

    # 3. Invalid / unbound override scenario -> preview fails closed SCENARIO_OVERRIDE_UNBOUND (same as Run)
    _create_custom_scenario(
        rec,
        name="Unbound Geared",
        overrides={"gearing_pct": "65"},
    )
    proj_unbound = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_unbound["operating_preview"]["available"] is False
    assert proj_unbound["operating_preview"]["code"] == "SCENARIO_OVERRIDE_UNBOUND"

    # 4. Archived scenario -> SCENARIO_ARCHIVED
    from app.persistence.db import get_cursor
    ws_cur = get_workspace_state(OWNER, rec.project_id)
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET archived=1 WHERE scenario_id=?", (ws_cur.active_scenario_id,))
    proj_arch = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_arch["operating_preview"]["available"] is False
    assert proj_arch["operating_preview"]["code"] == "SCENARIO_ARCHIVED"

    # 5. Missing scenario row -> SCENARIO_NOT_FOUND
    with get_cursor() as cur:
        cur.execute("DELETE FROM scenarios WHERE scenario_id=?", (ws_cur.active_scenario_id,))
    proj_missing = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_missing["operating_preview"]["available"] is False
    assert proj_missing["operating_preview"]["code"] == "SCENARIO_NOT_FOUND"

    # 6. Wrong-project scenario -> SCENARIO_PROJECT_MISMATCH
    rec_other = env.create()
    sc_other = _create_custom_scenario(
        rec_other,
        name="Foreign",
        overrides={"tariff_eur_mwh": "72"},
        base_input_set=get_workspace_state(OWNER, rec_other.project_id).draft_snapshot,
        switch=False,
    )
    with get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET active_scenario_id=?, active_scenario_name=? WHERE project_id=?", (sc_other.scenario_id, "Foreign", rec.project_id))
    proj_wrong = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert proj_wrong["operating_preview"]["available"] is False
    assert proj_wrong["operating_preview"]["code"] == "SCENARIO_PROJECT_MISMATCH"

    # 7. Valid tariff scenario -> preview OK matches Run operating total
    sc_tariff = _create_custom_scenario(rec_other, name="Valid 77", overrides={"tariff_eur_mwh": "77"})
    ident_ok = assemble_consistent_for_get(OWNER, rec_other.project_id, WORKBOOK.version)
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": rec_other.project_code}).json()
    prev_tariff = env.client.get("/v2/model-react/opex-projection", params={"project": rec_other.project_code}).json()["operating_preview"]
    assert prev_tariff["available"] is True and prev_tariff["freshness"]["scenario_id"] == sc_tariff.scenario_id
    r_run = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": rec_other.project_code,
            "csrf_token": runs_meta["run_contract"]["csrf_token"],
            "content_hash": ident_ok.composite_hash,
            "workbook_version": WORKBOOK.version,
            "run_intent_id": str(uuid.uuid4()),
        },
    )
    assert r_run.status_code == 200, r_run.text
    run_hist = get_run_history(OWNER, rec_other.project_id)
    assert len(run_hist) == 1
    after_run = env.client.get("/v2/model-react/opex-projection", params={"project": rec_other.project_code}).json()["operating_preview"]
    assert after_run["freshness"]["state"] == "CURRENT"
    assert after_run["freshness"]["matches_last_run"] is True
    assert after_run["freshness"]["last_run_scenario_id"] == sc_tariff.scenario_id
    assert after_run["freshness"]["last_run_history_id"] == run_hist[0].history_id
    # Revenue/OPEX/EBITDA kpis in preview match Run summary within 1e-4 kEUR
    assert abs(after_run["kpis"]["total_operating_revenue_keur"] - prev_tariff["kpis"]["total_operating_revenue_keur"]) <= 1e-4
    assert abs(after_run["kpis"]["total_operating_opex_keur"] - prev_tariff["kpis"]["total_operating_opex_keur"]) <= 1e-4
    assert abs(after_run["kpis"]["total_operating_ebitda_keur"] - prev_tariff["kpis"]["total_operating_ebitda_keur"]) <= 1e-4

    # Switching to a brand-new NOT_RUN scenario must NOT attribute previous scenario's run as CURRENT match
    sc_new = _create_custom_scenario(rec_other, name="Fresh Unrun", overrides={"tariff_eur_mwh": "65"})
    on_new = env.client.get("/v2/model-react/opex-projection", params={"project": rec_other.project_code}).json()["operating_preview"]
    assert on_new["freshness"]["state"] == "STALE"
    assert on_new["freshness"]["matches_last_run"] is False
    assert on_new["freshness"]["scenario_id"] == sc_new.scenario_id
    assert on_new["freshness"]["last_run_scenario_id"] == sc_tariff.scenario_id


def test_bcorr01_deterministic_concurrent_mutation_never_mismatches_identity(env, monkeypatch):
    rec = env.create()
    ws0 = get_workspace_state(OWNER, rec.project_id)
    ident0 = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)

    # Hook fires deterministically AFTER initial read snapshot & _build_opex_vm_ctx, BEFORE run_operating_model fold
    from app.services import opex_sub_lines_integration as osl
    real_fold = osl.apply_user_sub_lines_to_opex
    fired = {"done": False}
    errors: list[str] = []

    def _mutate_concurrently():
        if fired["done"]:
            return
        fired["done"] = True
        entered = threading.Event()
        release = threading.Event()

        def _worker():
            entered.set()
            release.wait(timeout=5.0)
            try:
                add_opex_line(
                    project_record=rec,
                    user_id=OWNER,
                    parent_group_code="B.12",
                    label="Concurrent New Line",
                    amount_keur=15.0,
                    inflation_pct=2.0,
                    notes="",
                    workbook_version=WORKBOOK.version,
                    expected_content_hash=ident0.composite_hash,
                )
                _create_custom_scenario(
                    rec,
                    name="Concurrent Switch",
                    overrides={"tariff_eur_mwh": "91"},
                    base_input_set=ws0.draft_snapshot,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        assert entered.wait(timeout=5.0)
        release.set()
        t.join(timeout=10.0)
        assert not t.is_alive()

    def _wrapped_fold(*args, **kwargs):
        _mutate_concurrently()
        return real_fold(*args, **kwargs)

    monkeypatch.setattr(osl, "apply_user_sub_lines_to_opex", _wrapped_fold)
    resp = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code})
    assert errors == []
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "OPEX_PROJECTION_STATE_CHANGED"
    assert len(get_run_history(OWNER, rec.project_id)) == 0


def test_bcorr01_non_eur_and_unsupported_project_fail_closed(env):
    rec = env.create()
    ws = get_workspace_state(OWNER, rec.project_id)
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
    body = env.client.get("/v2/model-react/opex-projection", params={"project": rec.project_code}).json()
    assert body["operating_preview"]["available"] is False
    assert body["operating_preview"]["code"] == "UNSUPPORTED_CURRENCY_EUR_ONLY"


# ── Narrow R04 Scenario Guard & PPA Reload Visibility ──────────────────────────


def test_narrow_evidence_r04_scenario_guard_and_ppa_reload_warnings(env):
    rec = env.create()
    ws0 = get_workspace_state(OWNER, rec.project_id)
    snap_r04 = dict(ws0.draft_snapshot)
    snap_r04["date_authority_version"] = "OD-TIME-01/v1"
    cod_str = str(snap_r04.get("cod_date") or "2028-01-01")
    from datetime import date as _dt
    cod_d = _dt.fromisoformat(cod_str)
    end_d = _dt(cod_d.year + int(float(snap_r04.get("horizon_years") or 25)), cod_d.month, min(cod_d.day, 28))
    snap_r04["rev_multistream_config_json"] = json.dumps({
        "version": 2,
        "technology": "solar",
        "indexation_basis": "OPERATING_YEAR",
        "streams": [
            {
                "id": "ppa1",
                "type": "ppa",
                "start_date": cod_d.isoformat(),
                "end_date": _dt(cod_d.year + 10, cod_d.month, min(cod_d.day, 28)).isoformat(),
                "volume_share": None,
                "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": "10", "unit": "GWh"},
                "price_eur_mwh": 70.0,
                "indexation_rate": 0.0,
                "settlement": "SAME_PERIOD",
                "source_ref": "REF1",
            },
            {
                "id": "m1",
                "type": "merchant",
                "start_date": cod_d.isoformat(),
                "end_date": end_d.isoformat(),
                "volume_share": None,
                "price_eur_mwh": 50.0,
                "indexation_rate": 0.0,
                "settlement": "SAME_PERIOD",
                "source_ref": "REF2",
                "capture_rate": 1.0,
            },
        ],
    })
    snap_r04["rev_ppa_base_tariff"] = "1500"
    save_workspace_state(
        user_id=OWNER,
        project_id=rec.project_id,
        project_code=rec.project_code,
        draft_snapshot=snap_r04,
        saved_snapshot=snap_r04,
        dirty=False,
        governance_state=ws0.governance_state,
        replay_metadata=ws0.replay_metadata,
    )

    # PPA warning surfaces on GET /v2/model-react/inputs reload with explicit advisory scope
    inputs_reload = env.client.get("/v2/model-react/inputs", params={"project": rec.project_code}).json()
    assert any(
        w["code"] == "PPA_TARIFF_IMPLAUSIBLE_HIGH"
        and w.get("advisory_only") is True
        and w.get("confirmation_scope") == "react_grid_ui_only"
        for w in inputs_reload.get("warnings", [])
    ), inputs_reload

    # Unbound active scenario with R04 book MUST return SCENARIO_UNAVAILABLE (not falsely READY!)
    _create_custom_scenario(rec, name="R04 Unbound", overrides={"gearing_pct": "60"})
    ws_shell = env.client.get("/v2/model-react/workspace", params={"project": rec.project_code}).json()
    bcr = ws_shell["bank_case_readiness"]
    assert bcr is not None
    assert bcr["runnable"] is False
    assert bcr["status"] == "SCENARIO_UNAVAILABLE"
    assert bcr["error_code"] == "SCENARIO_OVERRIDE_UNBOUND"
