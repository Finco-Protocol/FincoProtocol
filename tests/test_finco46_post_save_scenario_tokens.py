"""FINCO46: the Scenarios sheet re-rendered by a Save keeps working mutation tokens.

A CAPEX/OPEX row Save and a workbook field Save refresh the Scenarios sheet out-of-band (post-Save STALE state). Those
call sites did not pass the request, so ``mutation_tokens(None, ...)`` rendered EMPTY tokens into the Select / Rename /
Archive forms and the user's next scenario switch was a false 403 (real browser: test_cost_editing_ux_v2_browser::
test_scenario_switch_with_staged_edits_offers_save_discard_or_stay). Synthetic data only.
"""
from __future__ import annotations

import re

import pytest

from app.persistence.scenarios_repository import list_scenarios
from app.persistence.workspace_repository import get_workspace_state
from tests.model_mutation_csrf import post_valid_mutation
from tests.test_correction_a_required_gates import _rendered_form_values
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()


def _scenario_select_tokens(html: str) -> list[str]:
    tokens = []
    for form in re.findall(r'<form[^>]*hx-post="/v2/workbook/scenarios/select".*?</form>', html, flags=re.S):
        found = re.search(r'name="csrf_token" value="([^"]*)"', form)
        assert found, "select form without a token field"
        tokens.append(found.group(1))
    return tokens


def _with_alternative_scenario(env, kind):
    record = env.create(kind)
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/create",
                                   data={"project": record.project_code, "scenario_name": "Token case"})
    assert response.status_code == 200
    assert any(not s.is_base_case for s in list_scenarios(OWNER, record.project_id))
    return record


@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_row_save_refreshes_scenarios_with_valid_select_tokens(env, monkeypatch, kind):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    from app.persistence import capex_sub_lines as capex_repo, opex_sub_lines as opex_repo
    record = _with_alternative_scenario(env, "solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200 and _scenario_select_tokens(page.text) and all(_scenario_select_tokens(page.text))
    repo = capex_repo if kind == "capex" else opex_repo
    getter = getattr(repo, "get_active_sub_lines_for_project")
    line = next(l for l in getter(record.project_id) if l.amount_keur > 0)
    form = _rendered_form_values(page.text, f"/v2/{kind}/line/update", line.sub_line_id)
    form["amount_keur"] = str(float(form["amount_keur"]) + 7)
    response = post_valid_mutation(env.client, f"/v2/{kind}/line/update", data=form, headers={"HX-Request": "true"})
    assert response.status_code == 200, response.text[:400]
    assert get_workspace_state(OWNER, record.project_id).dirty
    tokens = _scenario_select_tokens(response.text)
    assert tokens, "the post-Save response refreshes the Scenarios sheet"
    assert all(tokens), "every refreshed Select form carries a non-empty operation token"
    # ...and that token is accepted by the real select route.
    scenario = next(s for s in list_scenarios(OWNER, record.project_id) if not s.is_base_case)
    switched = env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "scenario_id": scenario.scenario_id,
                                     "csrf_token": tokens[0]})
    assert switched.status_code == 200, switched.text[:300]
    assert get_workspace_state(OWNER, record.project_id).active_scenario_id == scenario.scenario_id
