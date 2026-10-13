"""Authenticated Revenue stress route guard tests.

No financial mock is used to claim numerical correctness: these cases prove
rejected requests never reach the production financial runner. The actual
read-only Solar/Wind run is tested in test_revenue_v2_advanced_curves.py.
"""
from __future__ import annotations

import json
import pytest

from tests.test_model_decision_workspace_v2 import env
from tests.test_wf07_revenue_workspace import contract_tokens
from tests.test_wf07_revenue_multistream import contracts


@pytest.mark.parametrize("invalid", ["csrf", "stale_cas", "other_owner", "protected", "unknown_driver"])
def test_readonly_commercial_stress_fails_closed_without_financial_run(env, monkeypatch, invalid):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService

    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200
    ws = get_workspace_state("decision-user", record.project_id)
    payload = contracts(WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs())
    tokens = contract_tokens(page.text)
    saved = env.client.post("/v2/workbook/revenue/contracts", data={
        "project": record.project_code, **tokens, "contracts": json.dumps(payload)})
    assert saved.status_code == 303 or saved.status_code == 200
    current = env.client.get("/v2/workbook", params={"project": record.project_code})
    refreshed = contract_tokens(current.text)
    data = {"project": record.project_code, **refreshed,
            "shock": "merchant_down", "amount_pct": "10", "expiry_date": ""}
    if invalid == "csrf":
        data["csrf_token"] = "forged"
        expected = 403
    elif invalid == "stale_cas":
        data["content_hash"] = "0" * 64
        expected = 409
    elif invalid == "other_owner":
        env.client.cookies.set(COOKIE_NAME, create_session_token(
            user_id="foreign-revenue-stress", username="foreign"))
        expected = 404
    elif invalid == "protected":
        conn = get_connection()
        try:
            conn.execute("UPDATE projects SET is_readonly=1, is_protected=1, "
                         "project_role='reference' WHERE project_id=?", (record.project_id,))
            conn.commit()
        finally:
            conn.close()
        expected = 409
    else:
        data["shock"] = "bank_price_override"
        expected = 422

    def forbidden(*args, **kwargs):
        pytest.fail("Denied request must not execute any canonical model")
    monkeypatch.setattr("app.services.sensitivity_service._run_once", forbidden)
    before = get_workspace_state("decision-user", record.project_id)
    reply = env.client.post("/v2/workbook/revenue/stress", data=data)
    assert reply.status_code == expected, reply.text[:2000]
    assert get_workspace_state("decision-user", record.project_id) == before


def test_readonly_stress_form_reuses_existing_csrf_and_composite_identity(env):
    from bs4 import BeautifulSoup
    record = env.create()
    response = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert response.status_code == 200
    page = BeautifulSoup(response.text, "html.parser")
    editor = page.select_one('[data-testid="revenue-contracts-form"]')
    stress = page.select_one('[data-testid="revenue-stress-form"]')
    assert stress and stress["hx-post"] == "/v2/workbook/revenue/stress"
    assert editor.select_one('input[name="csrf_token"]')["value"] == stress.select_one('input[name="csrf_token"]')["value"]
    assert editor.select_one('input[name="content_hash"]')["value"] == stress.select_one('input[name="content_hash"]')["value"]
    assert not stress.select_one('input[name="contracts"]')


@pytest.mark.parametrize("selected_scenario", ["base", "child"])
def test_successful_readonly_stress_preserves_working_copy_history_and_scenario(
        env, selected_scenario):
    """Actual canonical comparison must not write even when child is selected."""
    from copy import deepcopy
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import get_scenario
    from app.persistence.records import ScenarioRecord
    from app.workbook.service import WorkbookService

    def persisted_scenario_snapshot(record):
        """Value snapshot of every persisted ScenarioRecord slot, not object identity."""
        assert isinstance(record, ScenarioRecord)
        slots = ScenarioRecord.__slots__
        assert len(slots) == 20 and len(set(slots)) == len(slots)
        return {name: deepcopy(getattr(record, name)) for name in slots}

    owner = "decision-user"
    record = env.create()
    project = {"project": record.project_code}

    def page():
        response = env.client.get("/v2/workbook", params=project)
        assert response.status_code == 200
        return response.text

    def state():
        return get_workspace_state(owner, record.project_id)

    payload = contracts(WorkbookService.build_draft_input_set_from_workspace(
        state()).to_projectinputs(), price=90, merchant_price=80)
    response = env.client.post("/v2/workbook/revenue/contracts", data={
        **project, **contract_tokens(page()), "contracts": json.dumps(payload)})
    assert response.status_code in (200, 303), response.text[:500]

    if selected_scenario == "child":
        created = env.client.post("/v2/workbook/scenarios/create",
            data={**project, "scenario_name": "Synthetic Commercial Child"})
        assert created.status_code == 200
        active = state().active_scenario_id
        assert active is not None
        selection_before = persisted_scenario_snapshot(
            get_scenario(scenario_id=active, user_id=owner))
    else:
        selection_before = None

    original_ws = deepcopy(state())
    original_history = deepcopy(get_run_history(owner, record.project_id))
    data = {**project, **contract_tokens(page()), "shock": "merchant_down",
            "amount_pct": "10", "expiry_date": ""}
    result = env.client.post("/v2/workbook/revenue/stress", data=data)
    assert result.status_code == 200, result.text[:1500]
    assert "revenue-stress-results" in result.text
    assert "Bank-specific case: UNAVAILABLE" in result.text
    assert state() == original_ws  # Includes Working Copy, Last Run and selected scenario
    assert state().active_scenario_id == original_ws.active_scenario_id
    assert get_run_history(owner, record.project_id) == original_history
    if selection_before is not None:
        persisted_after = persisted_scenario_snapshot(
            get_scenario(scenario_id=original_ws.active_scenario_id, user_id=owner))
        assert persisted_after == selection_before  # Every persisted slot, recursively and by value
