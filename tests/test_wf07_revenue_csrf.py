"""Contract writes require signed CSRF before the authorized atomic writer."""
import json
import time

import pytest

from tests.test_model_decision_workspace_v2 import env
from tests.test_wf07_revenue_workspace import contract_tokens
from tests.test_wf07_revenue_multistream import contracts


def form_data(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    record = env.create()
    response = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert response.status_code == 200
    ws = get_workspace_state("decision-user", record.project_id)
    raw = contracts(WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs())
    return record, ws, {"project": record.project_code, **contract_tokens(response.text), "contracts": json.dumps(raw)}


@pytest.mark.parametrize("kind", ["missing", "forged", "expired"])
def test_invalid_csrf_rejected_before_writer_without_any_mutation(env, monkeypatch, kind):
    from app.auth import generate_csrf_token, validate_csrf_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios
    from itsdangerous import TimestampSigner
    record, before, data = form_data(env)
    def scenario_state():
        return [tuple(getattr(row, key) for key in row.__slots__)
                for row in list_scenarios("decision-user", record.project_id)]
    scenarios_before = scenario_state()
    if kind == "missing":
        data.pop("csrf_token")
    elif kind == "forged":
        data["csrf_token"] += "forged"
    else:
        old_time = int(time.time()) - 86401
        with monkeypatch.context() as patcher:
            patcher.setattr(TimestampSigner, "get_timestamp", lambda self: old_time)
            data["csrf_token"] = generate_csrf_token()
        assert not validate_csrf_token(data["csrf_token"])
    def forbidden(**kwargs):
        pytest.fail("Invalid CSRF must not reach the contract writer")
    monkeypatch.setattr("app.workbook.revenue_contracts_service.save_contracts", forbidden)
    response = env.client.post("/v2/workbook/revenue/contracts", data=data)
    assert response.status_code == 403
    assert response.json()["error"] == "REVENUE_CONTRACTS_CSRF_INVALID"
    assert get_workspace_state("decision-user", record.project_id) == before
    assert scenario_state() == scenarios_before


def test_valid_form_csrf_save_reload_and_refresh_do_not_execute_engine(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.revenue_multistream import SNAPSHOT_KEY
    record, before, data = form_data(env)
    def forbidden(*args, **kwargs):
        pytest.fail("GET and Save must not calculate financial outputs")
    monkeypatch.setattr("app.runtime.model_execution.run_model_process", forbidden)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    response = env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"}, data=data)
    assert response.status_code == 200
    contract_tokens(response.text)
    after = get_workspace_state("decision-user", record.project_id)
    assert after.dirty
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert json.loads(after.draft_snapshot[SNAPSHOT_KEY]) == json.loads(data["contracts"])
    reload = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert reload.status_code == 200
    contract_tokens(reload.text)


@pytest.mark.parametrize("scope", ["anonymous", "other_owner", "protected"])
def test_valid_csrf_does_not_grant_project_write_authority(env, monkeypatch, scope):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    from app.persistence.workspace_repository import get_workspace_state
    record, before, data = form_data(env)
    if scope == "anonymous":
        env.client.cookies.clear()
        expected = 401
    elif scope == "other_owner":
        env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="other-contract-owner", username="other"))
        expected = 404
    else:
        conn = get_connection()
        try:
            conn.execute("UPDATE projects SET is_readonly=1, is_protected=1, project_role='reference' WHERE project_id=?", (record.project_id,))
            conn.commit()
        finally:
            conn.close()
        expected = 409
        page = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert page.status_code == 200
        assert 'data-testid="revenue-contracts-form"' not in page.text
    def forbidden(**kwargs):
        pytest.fail("Rejected project authority must not reach the writer")
    monkeypatch.setattr("app.workbook.revenue_contracts_service.save_contracts", forbidden)
    response = env.client.post("/v2/workbook/revenue/contracts", data=data)
    assert response.status_code == expected
    assert get_workspace_state("decision-user", record.project_id) == before
