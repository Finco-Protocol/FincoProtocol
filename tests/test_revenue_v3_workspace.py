"""Reuse the real Revenue writer, authorization, scenario CAS and immutable export."""

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf
import copy
import json
from io import BytesIO

import pytest

from tests.model_react_test_helpers import react_workbook_tokens, react_workspace_payload
from tests.test_model_decision_workspace_v2 import env
from tests.test_revenue_v3_products import candidate
from tests.revenue_v3_cases import book


def _rev_payload(client, project_code: str) -> dict:
    res = client.get("/v2/model-react/revenue", params={"project": project_code})
    assert res.status_code == 200, res.text[:500]
    return res.json()


def _rev_tokens(client, project_code: str) -> dict[str, str]:
    save = _rev_payload(client, project_code)["save"]
    return {
        "csrf_token": save["csrf_token"],
        "content_hash": save["content_hash"],
        "workbook_version": save["workbook_version"],
    }


@pytest.fixture(autouse=True)
def _legacy_calendar_creation(monkeypatch):
    """FINCO45B: this module exercises a LEGACY_CALENDAR/v0-only feature (Revenue V3 advanced products, legacy-grid axis); new Solar/Wind projects default to
    OD-TIME-01/v1, where it is a typed refusal. Its projects are created through the explicit creation rollback."""
    monkeypatch.setenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", "legacy")



@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_candidate_save_scenario_stale_run_history_and_product_export(env, candidate, monkeypatch, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    from app.workbook.revenue_multistream import SNAPSHOT_KEY
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    from app.services.v2_export_service import build_canonical_last_run_institutional_workbook_export
    record = env.create(kind)
    project = {"project": record.project_code}
    def ws():
        return get_workspace_state("decision-user", record.project_id)
    def save(payload, **extra):
        return env.client.post("/v2/workbook/revenue/contracts",
            data={**project, **_rev_tokens(env.client, record.project_code), "contracts": json.dumps(payload), **extra})
    def run():
        response = post_valid_csrf(env.client, "/v2/workbook/run", data={**project, **react_workbook_tokens(env.client, record.project_code)})
        assert response.status_code == 200, response.text[:2000]
        ws_payload = react_workspace_payload(env.client, record.project_code)
        assert ws_payload["freshness"]["state"] == "CURRENT"
        assert not ws().dirty
        assert ws_payload["identity"]["snapshot_id"] == ws().last_runtime_snapshot_id
        assert ws().last_runtime_summary["revenue_multistream_audit"][0]["products"]
        return copy.deepcopy(ws().last_runtime_summary)
    raw, axis = book(WorkbookService.build_draft_input_set_from_workspace(ws()).to_projectinputs(), kind)
    rev_contracts = _rev_payload(env.client, record.project_code)["contracts"]
    assert rev_contracts["v3_enabled"] is True and any(p["period_start"] == axis[0].start_date.isoformat() for p in rev_contracts["period_axis"])
    assert save(raw).status_code == 200
    assert ws().dirty
    assert json.loads(ws().draft_snapshot[SNAPSHOT_KEY]) == raw
    baseline = run()
    assert baseline["revenue_multistream_audit"][0]["products"]
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={**project, "scenario_name": "Service contract alternative"}).status_code == 200
    sc = next(s for s in list_scenarios("decision-user", record.project_id) if not s.is_base_case)
    changed = copy.deepcopy(raw)
    changed["products"][0]["price_eur"] = 25
    draft_before = copy.deepcopy(ws().draft_snapshot)
    assert save(changed).status_code == 200
    assert ws().draft_snapshot == draft_before
    assert json.loads(get_scenario(sc.scenario_id, "decision-user").overrides[SNAPSHOT_KEY]) == changed
    result = run()
    assert result["total_revenue_keur"] > baseline["total_revenue_keur"]
    history = get_run_history("decision-user", record.project_id)
    later = copy.deepcopy(changed)
    later["products"][0]["price_eur"] = 30
    assert save(later).status_code == 200
    assert ws().dirty
    assert get_run_history("decision-user", record.project_id) == history
    authority = resolve_canonical_last_run_from_workspace(record, "decision-user", ws())
    assert authority.working_changed_since_run
    assert json.loads(authority.project_inputs.revenue.multistream_config_json) == changed
    def forbidden(*args, **kwargs):
        raise AssertionError("GET / export must not calculate finances")
    with monkeypatch.context() as patch:
        patch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
        patch.setattr("app.runtime.model_execution.run_model_process", forbidden)
        assert react_workspace_payload(env.client, record.project_code)["freshness"]["state"] == "STALE"
        assert ws().last_runtime_summary["revenue_multistream_audit"][0]["products"]
        exported = build_canonical_last_run_institutional_workbook_export("generic_" + kind + "_reference",
            safe_project=record.project_code, project_record=record, user_id="decision-user")
        assert exported.status_code == 200, exported.error_content
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(exported.bytes_data), read_only=True, data_only=True)
        try:
            rows = list(workbook["Revenue_Products"].iter_rows(min_row=8, values_only=True))
            assert any(r[2] == "capacity_market" and r[6] == 25 for r in rows)
            assert not any(r[2] == "capacity_market" and r[6] == 30 for r in rows)
            assert {r[5] for r in rows} == {"MW", "CERTIFICATE_MWH"}
        finally:
            workbook.close()


def test_closed_release_route_and_cas_csrf_owner(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from domain.revenue import advanced_products
    record = env.create()
    project = {"project": record.project_code}
    rev_state = _rev_payload(env.client, record.project_code)["contracts"]
    initial = get_workspace_state("decision-user", record.project_id)
    raw, _ = book(WorkbookService.build_draft_input_set_from_workspace(initial).to_projectinputs())
    data = {**project, **_rev_tokens(env.client, record.project_code), "contracts": json.dumps(raw)}
    assert rev_state["v3_enabled"] is False
    assert rev_state["products"] == []
    response = env.client.post("/v2/workbook/revenue/contracts", data=data)
    assert response.status_code == 422 and "RELEASE_CLOSED" in response.text
    assert get_workspace_state("decision-user", record.project_id) == initial
    monkeypatch.setattr(advanced_products, "ACTIVATION_ENABLED", True)
    for token in ("", "forged"):
        assert env.client.post("/v2/workbook/revenue/contracts", data={**data, "csrf_token": token}).status_code == 403
        assert get_workspace_state("decision-user", record.project_id) == initial
    assert env.client.post("/v2/workbook/revenue/contracts", data=data).status_code == 200
    saved = get_workspace_state("decision-user", record.project_id)
    assert env.client.post("/v2/workbook/revenue/contracts", data=data).status_code == 409
    assert get_workspace_state("decision-user", record.project_id) == saved
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="different-service-owner", username="different"))
    assert env.client.post("/v2/workbook/revenue/contracts", data=data).status_code == 404
    assert get_workspace_state("decision-user", record.project_id) == saved
