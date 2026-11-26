"""Workflow D authority, typed deltas, capability and render contracts."""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from app.v2.decision_workspace import scenario_assumptions, sensitivity_presentation, tender_presentation
from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection
from tests.model_react_test_helpers import react_workbook_tokens

def projection(name, **kpis):
    return build_scenario_projection(name, kpis, "2026-01-01T12:00:00Z", False)


def test_rate_ratio_and_amount_deltas_use_raw_authority_for_both_alternatives():
    rows = build_compare_rows([projection("Base", project_irr=.076, min_dscr=1.2, total_revenue_keur=100000),
                               projection("Upside", project_irr=.082, min_dscr=1.3, total_revenue_keur=105000),
                               projection("Downside", project_irr=.070, min_dscr=1.1, total_revenue_keur=95000)])
    rows = {r.key: r for r in rows}
    assert rows["project_irr"].deltas[1:] == ["+0.60 pp", "-0.60 pp"]
    assert rows["min_dscr"].deltas[1:] == ["+0.10x", "-0.10x"]
    assert rows["total_revenue_keur"].variances[1:] == ["+5.0%", "-5.0%"]
    assert rows["total_revenue_keur"].deltas[1:] == ["+5,000 kEUR", "-5,000 kEUR"]
    assert rows["project_irr"].variances == ["—"] * 3


@pytest.mark.parametrize("base", [None, 0, -100])
def test_relative_amount_variance_requires_positive_base(base):
    rows = build_compare_rows([projection("Base", total_revenue_keur=base), projection("Alt", total_revenue_keur=100)])
    assert next(r for r in rows if r.key == "total_revenue_keur").variances[1] == "—"


@pytest.mark.parametrize("value", [None, True, "8.5%", float("nan"), float("inf")])
def test_missing_evidence_is_never_zero_or_parsed_display(value):
    row = next(r for r in build_compare_rows([projection("Base", project_irr=.08), projection("Alt", project_irr=value)]) if r.key == "project_irr")
    assert row.raw_values[1] is None
    assert row.deltas[1] == "—"


@pytest.mark.parametrize("status", ["NO_SOLUTION_IN_BOUNDS", "NON_MONOTONIC_TARGET", "TARGET_METRIC_UNAVAILABLE", "MODEL_RUN_FAILED", "INVALID_REQUEST"])
def test_unsolved_result_cannot_become_tender_price(status):
    assert not tender_presentation({"status": status, "solved_input_value": 100, "started_from_value": 80})["accepted"]


def test_tender_deltas_are_presentation_only_and_exact_solved_value_unmodified():
    result = {"status": "SOLVED", "solved_input_value": 83.456789, "started_from_value": 80.0}
    view = tender_presentation(result)
    assert view == {"accepted": True, "delta": "+3.46 EUR/MWh", "variance": "+4.3%"}
    assert result["solved_input_value"] == 83.456789


def points(failed_base=False):
    return [{"label": label, "status": "FAILED" if label == "Base" and failed_base else "OK",
             "kpis_raw": {"project_irr": irr, "min_dscr": dscr}}
            for label, irr, dscr in [("-20%", .06, 1.1), ("-10%", .07, 1.2), ("Base", .08, 1.3), ("+10%", .09, 1.4), ("+20%", .10, 1.5)]]


def test_observed_single_driver_range_reuses_tornado_builder_without_evaluations():
    view = sensitivity_presentation(points(), "tariff", "PPA tariff")
    assert len(view["chart"]) == 5
    assert view["chart"][0]["delta"] == "-2.00 pp"
    assert view["chart"][2]["width"] == 0
    assert view["tornado"][0]["min_level"] == "-20%"
    assert view["tornado"][0]["max_level"] == "+20%"
    assert len(view["tornado"]) == 1


def test_failed_baseline_never_inferred_from_neighbors():
    view = sensitivity_presentation(points(True), "tariff", "Tariff")
    assert not view["has_baseline"]
    assert view["chart"] == view["tornado"] == view["delta_rows"] == []


def test_scoped_javascript_is_only_canonical_input_serialization():
    source = (Path(__file__).resolve().parents[1] / "static/js/model_merchant_curve.js").read_text(encoding="utf-8")
    assert "JSON.stringify" in source and "htmx:configRequest" in source
    assert "seen.has(year)" in source and "Number.isFinite(price)" in source
    assert "stopImmediatePropagation" in source
    assert not re.search(r"\b(irr|dscr|npv|cfads|ebitda|debt_service)\b", source, re.I)


def test_working_and_run_bound_overrides_are_independent():
    sc = SimpleNamespace(scenario_name="Case", overrides={"tariff_eur_mwh": 90},
                         last_run_summary={"scenario_overrides_at_run": {"tariff_eur_mwh": 80}})
    view = scenario_assumptions([sc])[0]
    assert view["working"][0][1] == "90"
    assert view["bound"][0][1] == "80"
    sc.last_run_summary = {}
    assert not scenario_assumptions([sc])[0]["bound_available"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.v2.react_workspace_router import router as react_workspace_router
    from app.v2.router import router
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "decision.db"))
    db.init_db()
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    app.include_router(react_workspace_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="decision-user", username="admin"))
        def create(kind="solar"):
            return create_reference_seeded_project(user_id="decision-user", requested_name="Decision " + kind,
                template_source="generic_" + kind + "_reference", capacity_mw=16)
        yield SimpleNamespace(client=client, create=create)
    reset_model_executor_for_tests()


def tokens(html):
    return {key: re.search(r'name="' + key + r'" value="([^"]*)"', html).group(1)
            for key in ("content_hash", "workbook_version")}


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_vertical_capability_and_route_render_context(env, kind):
    record = env.create(kind)
    ws = env.client.get("/v2/model-react/workspace", params={"project": record.project_code})
    assert ws.status_code == 200
    hdrs = {"x-finco-react-request": "1"}
    sens = env.client.get("/v2/model-react/analysis/sensitivity/catalog", params={"project": record.project_code}, headers=hdrs)
    gs = env.client.get("/v2/model-react/analysis/goal-seek/catalog", params={"project": record.project_code}, headers=hdrs)
    assert gs.status_code == 200
    grid = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()["grid"]
    field_ids = {row["field_id"] for sec in grid["sections"] for cat in sec["categories"] for row in cat["rows"]}
    debt_fields = env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()["fields"]
    debt_field_ids = {f["field_id"] for f in debt_fields}
    if kind == "data_center":
        assert sens.status_code == 200
        drivers = {d["key"] for d in sens.json()["drivers"]}
        assert {"dc_pue", "dc_it_mw", "dc_electricity_price"} <= drivers
        assert "tariff" not in drivers
    if kind in ("data_center", "ev_charging"):
        assert gs.json()["available"] is False
        assert "revenue.ppa.base_tariff" not in field_ids
        assert "project_setup.technical.p50_hours" not in field_ids
        assert "debt.senior.gearing_pct" in debt_field_ids
        assert "debt.senior.interest_rate_pct" in debt_field_ids
    if kind == "ev_charging":
        assert sens.status_code == 409 and sens.json()["code"] == "MATRIX_VERTICAL_UNSUPPORTED"
    else:
        assert sens.status_code == 200 and len(sens.json()["drivers"]) > 0
    if kind in ("solar", "wind"):
        assert "revenue.ppa.base_tariff" in field_ids
        assert "project_setup.technical.p50_hours" in field_ids
        assert gs.json()["available"] is True


@pytest.mark.parametrize("curve", [
    [{"year": 2030, "price_eur_mwh": 80}, {"year": 2030, "price_eur_mwh": 81}],
    [{"year": 2030, "price_eur_mwh": 80}, {"year": 2032, "price_eur_mwh": 81}],
    [{"year": 2030, "price_eur_mwh": -1}],
    [{"year": 2030.5, "price_eur_mwh": 80}],
])
def test_merchant_invalid_save_rejected_without_write(env, curve):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    toks = react_workbook_tokens(env.client, record.project_code)
    before = get_workspace_state("decision-user", record.project_id)
    response = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "sheet_id": "revenue", "field_id": "revenue.merchant.price_curve_json",
        "value": json.dumps(curve), **toks})
    assert response.status_code == 422  # C1-Q-06 HTMX field-error transport
    assert "workbook-field-error" in response.headers.get("HX-Trigger", "")
    assert "workbook-field-saved" not in response.headers.get("HX-Trigger", "")
    assert get_workspace_state("decision-user", record.project_id) == before


def test_merchant_valid_canonical_save_reload_and_stale_cas(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    toks = react_workbook_tokens(env.client, record.project_code)
    payload = {"project": record.project_code, "sheet_id": "revenue", "field_id": "revenue.merchant.price_curve_json",
               "value": '[{"year":2031,"price_eur_mwh":81},{"year":2030,"price_eur_mwh":80}]', **toks}
    response = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"}, data=payload)
    assert response.status_code == 200
    reload = env.client.get("/v2/model-react/fields/revenue", params={"project": record.project_code})
    assert reload.status_code == 200
    stored = get_workspace_state("decision-user", record.project_id)
    assert json.loads(stored.draft_snapshot["rev_merchant_price_curve_json"])[0]["price_eur_mwh"] == 81
    before = stored
    conflict = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"}, data=payload)
    assert conflict.status_code == 409  # C1-Q-06 CAS rejection is transported for HTMX swap
    assert "workbook-field-error" in conflict.headers.get("HX-Trigger", "")
    assert "Draft changed since page loaded" in conflict.text
    assert get_workspace_state("decision-user", record.project_id) == before


def test_compare_deduplicates_and_uses_base_as_reference_and_is_read_only(env):
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    for name in ("Upside", "Downside"):
        response = post_valid_mutation(env.client, "/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
                                  data={"project": record.project_code, "scenario_name": name})
        assert response.status_code == 200
    scenarios = list_scenarios("decision-user", record.project_id)
    base = next(s for s in scenarios if s.is_base_case)
    alt = next(s for s in scenarios if not s.is_base_case)
    before = get_workspace_state("decision-user", record.project_id)
    response = env.client.get("/v2/workbook/scenarios/compare", params={"project": record.project_code,
        "s1": alt.scenario_id, "s2": base.scenario_id, "s3": alt.scenario_id})
    assert response.status_code == 200
    assert f'Reference: {base.scenario_name}' in response.text
    assert '(Base Case)' in response.text
    assert response.text.count('class="v2-compare-sc-name"') == 2
    assert "Run-bound override evidence unavailable" in response.text
    assert get_workspace_state("decision-user", record.project_id) == before


def test_analysis_cross_owner_requests_fail_closed(env):
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create()
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="other-decision-user", username="admin"))
    assert env.client.get("/v2/workbook/scenarios/compare", params={"project": record.project_code}).status_code == 404
    assert env.client.post("/v2/workbook/scenarios/sensitivity/run", data={"project": record.project_code, "driver": "tariff"}).status_code == 404
    assert env.client.post("/v2/workbook/goal-seek/run", data={"project": record.project_code, "target_metric": "project_irr", "target_value": "9"}).status_code == 404
    assert env.client.get("/v2/workbook/decision/sensitivity", params={"project": record.project_code}).status_code == 404


@pytest.mark.parametrize("surface", ["sensitivity", "goal-seek"])
def test_decision_lazy_refresh_coherent_context_and_concurrent_change_fails_closed(env, monkeypatch, surface):
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    env.client.get("/v2/model-react/workspace", params={"project": record.project_code})
    before = get_workspace_state("decision-user", record.project_id)
    url = "/v2/workbook/decision/" + surface
    result = env.client.get(url, params={"project": record.project_code})
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    def changed(self):
        raise PostRunContextChanged("Concurrent scenario selection")
    monkeypatch.setattr(PostRunRequestContext, "validate_current", changed)
    result = env.client.get(url, params={"project": record.project_code})
    assert result.status_code == 409
    assert "workspace changed" in result.text
    assert get_workspace_state("decision-user", record.project_id) == before


def test_revenue_context_reads_the_persisted_derivation_not_missing_raw_payload(env):
    from app.v2.router import _build_revenue_ctx
    from app.workbook.service import WorkbookService
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    ws = get_workspace_state("decision-user", record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    derivation = {"sample_generation_mwh": "12,000 MWh", "sample_period_label": "Y1-H1",
                  "display_value_keur": "1,234 kEUR"}
    proj = SimpleNamespace(fs=SimpleNamespace(runtime_summary={"revenue_derivation": derivation},
                           meta=SimpleNamespace(has_runtime=True, is_dirty=False)))
    ctx = _build_revenue_ctx(pis, ws, projection=proj)
    assert ctx["revenue_output_context"] == {"generation": "12,000 MWh", "period": "Y1-H1", "persisted_revenue": "1,234 kEUR"}


def test_sensitivity_real_canonical_points_do_not_write_workspace_or_history(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    record = env.create()
    env.client.get("/v2/model-react/workspace", params={"project": record.project_code})
    before = get_workspace_state("decision-user", record.project_id)
    response = env.client.post("/v2/workbook/scenarios/sensitivity/run", data={"project": record.project_code, "driver": "tariff"})
    assert response.status_code == 200
    assert "sensitivity-range" in response.text
    assert "+20%" in response.text and "-20%" in response.text
    assert " pp" in response.text
    assert get_workspace_state("decision-user", record.project_id) == before
    assert not get_run_history(user_id="decision-user", project_id=record.project_id)


def test_tender_apply_refreshes_canonical_run_tokens_without_touching_last_run(env):
    import uuid
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    record = env.create()
    toks0 = react_workbook_tokens(env.client, record.project_code)
    run = post_valid_csrf(env.client, "/v2/workbook/run", headers={"Accept": "application/json"},
                          data={"project": record.project_code, "run_intent_id": str(uuid.uuid4()), **toks0})
    assert run.status_code == 200 and run.json()["outcome"] == "COMMITTED"
    toks1 = react_workbook_tokens(env.client, record.project_code)
    before = get_workspace_state("decision-user", record.project_id)
    history = get_run_history("decision-user", record.project_id)
    result = env.client.post("/v2/workbook/goal-seek/apply", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "field_id": "revenue.ppa.base_tariff", "value": "51.23456789",
        "target_metric": "project_irr", "target_value": "9", **toks1})
    assert result.status_code == 200
    after = get_workspace_state("decision-user", record.project_id)
    assert after.dirty
    assert float(after.draft_snapshot["rev_ppa_base_tariff"]) == 51.23456789
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.last_runtime_at == before.last_runtime_at
    assert get_run_history("decision-user", record.project_id) == history
    toks2 = react_workbook_tokens(env.client, record.project_code)
    assert toks2["content_hash"] != toks1["content_hash"]
    rerun = post_valid_csrf(env.client, "/v2/workbook/run", headers={"Accept": "application/json"},
                            data={"project": record.project_code, "run_intent_id": str(uuid.uuid4()), **toks2})
    assert rerun.status_code == 200 and rerun.json()["outcome"] == "COMMITTED"
    assert not get_workspace_state("decision-user", record.project_id).dirty
