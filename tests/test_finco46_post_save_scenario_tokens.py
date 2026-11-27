"""FINCO46: the Scenarios sheet re-rendered by a Save keeps working mutation tokens.

A CAPEX/OPEX row Save and a workbook field Save refresh the Scenarios sheet out-of-band (post-Save STALE state). Those
call sites did not pass the request, so ``mutation_tokens(None, ...)`` rendered EMPTY tokens into the Select / Rename /
Archive forms and the user's next scenario switch was a false 403 (real browser: test_cost_editing_ux_v2_browser::
test_scenario_switch_with_staged_edits_offers_save_discard_or_stay). Synthetic data only.
"""
from __future__ import annotations

import json

import pytest

from app.persistence.scenarios_repository import list_scenarios
from app.persistence.workspace_repository import get_workspace_state
from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)


def _with_alternative_scenario(env, kind):
    record = env.create(kind)
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/create",
                                   data={"project": record.project_code, "scenario_name": "Token case"})
    assert response.status_code == 200
    assert any(not s.is_base_case for s in list_scenarios(OWNER, record.project_id))
    return record


@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_row_save_refreshes_scenarios_with_valid_select_tokens(env, kind):
    record = _with_alternative_scenario(env, "solar")
    cl = env.client.get("/v2/model-react/costlines", params={"project": record.project_code, "sheet": kind}).json()
    line = next(l for l in cl["lines"] if l["amount_keur"] > 0 and l["active"])
    new_amount = float(line["amount_keur"]) + 7
    payload = [{
        "kind": kind,
        "sub_line_id": line["sub_line_id"],
        "label": line["label"],
        "amount_keur": str(new_amount),
        "row_version": line["row_version"],
    }]
    save_resp = env.client.post(
        "/v2/workbook/grid/cost-lines/save",
        headers={"HX-Request": "true"},
        data={
            "project": record.project_code,
            "csrf_token": cl["save"]["csrf_token"],
            "workbook_version": cl["save"]["workbook_version"],
            "content_hash": cl["save"]["content_hash"],
            "sheet": kind,
            "payload": json.dumps(payload),
        },
    )
    assert save_resp.status_code == 200, save_resp.text[:400]
    assert get_workspace_state(OWNER, record.project_id).dirty
    sc = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    select_tok = sc["mutations"]["select"]["csrf_token"]
    assert select_tok, "React scenarios endpoint provides a non-empty select operation token after costline save"
    scenario = next(s for s in list_scenarios(OWNER, record.project_id) if not s.is_base_case)
    switched = env.client.post(
        "/v2/workbook/scenarios/select",
        headers={"Accept": "application/json"},
        data={"project": record.project_code, "scenario_id": scenario.scenario_id, "csrf_token": select_tok},
    )
    assert switched.status_code == 200, switched.text[:300]
    assert get_workspace_state(OWNER, record.project_id).active_scenario_id == scenario.scenario_id
