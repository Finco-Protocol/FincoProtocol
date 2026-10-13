"""F3.5-B closes proposal presentation and production activation boundaries."""
import json

from bs4 import BeautifulSoup
import pytest

from app.workbook import junior_debt_config as junior, multisenior_config as config
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_financing_f2 import save, run
from tests.test_financing_f3_junior_workspace import state, working_case


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_saved_junior_proposal_has_real_commitment_closed_activation_and_no_policy_guess(env, kind):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create(kind)
    ws = get_workspace_state("decision-user", record.project_id)
    candidate = working_case(ws)
    proposal = json.loads(state(candidate))
    proposal["scopes"]["base"]["activation"] = None
    response = save(env, record, json.dumps(proposal), field=config.FIELD_ID)
    assert response.status_code == 200 and "field-error-banner" not in response.text
    before = get_workspace_state("decision-user", record.project_id)
    html = env.client.get("/v2/workbook", params={"project": record.project_code, "sheet": "debt"}).text
    soup = BeautifulSoup(html, "html.parser")
    expected = next(i.commitment_keur for i in candidate.financing_collection.instruments if i.seniority_rank == 2)
    assert f"{expected:,.2f}" in soup.select_one('[data-testid="cs-working-junior"]').text
    assert "Senior first" in soup.select_one('[data-testid="cs-summary-working"]').text
    checkbox = soup.select_one("[data-f3-activate]")
    assert checkbox.has_attr("disabled") and not checkbox.has_attr("checked")
    assert soup.select_one('[data-testid="cs-junior-policy"]').text.count("Not available") == 4
    assert len(soup.select("[data-cs-readonly-instrument]")) == 1
    assert not soup.select('[data-testid="cs-summary-last-run"]')
    assert get_workspace_state("decision-user", record.project_id) == before
    assert junior.ACTIVATION_ENABLED is False


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("bind", [False, True])
def test_customer_json_cannot_activate_candidate_or_replace_last_run(env, kind, bind):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create(kind)
    previous, _ = run(env, record)
    candidate = working_case(previous)
    request = json.loads(state(candidate))
    if bind:
        request["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    response = save(env, record, json.dumps(request), field=config.FIELD_ID)
    assert "field-error-banner" in response.text
    assert get_workspace_state("decision-user", record.project_id) == previous
    assert junior.ACTIVATION_ENABLED is False


@pytest.mark.parametrize("extra", ["senior", "junior"])
def test_extra_facility_is_not_an_implicit_financial_extension(env, extra):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    # The first workbook GET performs existing seed hydration. Capture the
    # transaction baseline after that authorized lifecycle step, before POST.
    env.client.get("/v2/workbook", params={"project": record.project_code})
    before = get_workspace_state("decision-user", record.project_id)
    candidate = working_case(before)
    request = json.loads(state(candidate))
    instruments = request["scopes"]["base"]["proposal"]["instruments"]
    added = dict(instruments[0 if extra == "senior" else 1], instrument_id="unsupported-extra")
    instruments.append(added)
    request["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    response = save(env, record, json.dumps(request), field=config.FIELD_ID)
    assert "field-error-banner" in response.text
    assert get_workspace_state("decision-user", record.project_id) == before


def test_junior_day_count_cannot_inherit_senior_policy():
    from app.v2.capital_stack_projection import build_capital_stack
    from tests.test_capital_stack_projection_v1 import _junior_view
    view, _ = _junior_view()
    result = build_capital_stack(view, None, day_count="act_365")
    senior_row, junior_row = result["rows"]
    assert senior_row["day_count"] == "Actual / 365"
    assert junior_row["day_count"] == "Not available"
    assert not result["release_enabled"]
    assert all(not row["executable"] for row in result["rows"])


def test_projection_uses_explicit_candidate_policy_only():
    from app.v2.capital_stack_projection import build_capital_stack
    from tests.test_capital_stack_projection_v1 import _junior_view
    view, _ = _junior_view()
    view["entry"]["activation"] = {"junior_policy": {
        "day_count": "act_360", "idc_book_life_years": 9,
        "idc_tax_treatment": "EXCLUDED_BY_EXISTING_POLICY", "maximum_total_debt_gearing": .65}}
    result = build_capital_stack(view, None, day_count="act_365")
    assert result["rows"][1]["day_count"] == "Actual / 360"
    assert result["junior_policy"]["idc_book_life_years"] == 9
    assert not result["release_enabled"] and result["last_run"] is None
