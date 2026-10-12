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
