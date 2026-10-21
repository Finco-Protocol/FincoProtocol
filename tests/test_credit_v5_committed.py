"""Real completed Runs, authorized routes and immutable history acceptance."""
from dataclasses import asdict
from decimal import Decimal

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_credit_decision_v3_real_runs import cenv, history, last  # noqa: F401
from tests.test_model_financing_f2 import config, run, save


def get(cenv, record, **kwargs):
    return cenv.client.get("/v2/credit-decision/v5", params={"project": record.project_code, "format": "json", **kwargs})


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_real_run_full_precision_headroom_readonly_and_render(cenv, monkeypatch, kind):
    from app.persistence.workspace_repository import get_workspace_state
    record = cenv.create(kind)
    run(cenv, record)
    before = [asdict(e) for e in history(record)]
    ws = get_workspace_state("decision-user", record.project_id)
    def forbidden(*a, **k):
        pytest.fail("Credit V5 must never execute a financial Run")
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    response = get(cenv, record, min_dscr=1.25)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    result = data["runs"][0]
    assert result["history_id"] == last(record).history_id
    assert result["freshness"] == "HISTORICAL_NOT_ASSERTED_CURRENT"
    assert response.headers["cache-control"] == "private, no-store"
    assessment = result["constraints"][0]
    committed = last(record)
    periods = {p["period_index"]: p for p in committed.integrity_evidence["senior_debt"]["periods"]}
    actual_rows = [r for r in assessment["observations"] if r["absolute"] is not None]
    assert actual_rows, assessment
    for row in actual_rows:
        actual = periods[row["index"]]["reported_dscr"]
        assert row["value"] == actual
        assert row["absolute"] == float(Decimal(str(actual)) - Decimal("1.25"))
    html = cenv.client.get("/v2/credit-decision/v5", params={"project": record.project_code, "min_dscr": 1.25})
    assert html.status_code == 200 and 'data-testid="credit-v5"' in html.text
    assert "Hypothetical lender analysis" in html.text
    assert [asdict(e) for e in history(record)] == before
    assert get_workspace_state("decision-user", record.project_id) == ws
    assert cenv.client.post("/v2/credit-decision/v5", data={"project": record.project_code}).status_code == 405


def test_no_committed_run_and_missing_scenario_run_not_estimated(cenv):
    record = cenv.create()
    response = get(cenv, record)
    assert response.status_code == 200 and response.json() == {"state": "NO_COMMITTED_RUN", "data": None}
    assert get(cenv, record, run="unrun-scenario").status_code == 404


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "0", "invalid"])
def test_invalid_threshold_cannot_trigger_a_run(cenv, value):
    assert get(cenv, cenv.create(), min_dscr=value).status_code == 422


def test_history_owner_scope_protected_reference_and_authentication(cenv, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record = cenv.create("wind")
    run(cenv, record)
    hid = last(record).history_id
    other_project = cenv.create("solar")
    assert get(cenv, other_project, run=hid).status_code == 404
    from fastapi.testclient import TestClient
    with TestClient(cenv.client.app) as other:
        other.cookies.set(COOKIE_NAME, create_session_token(user_id="foreign", username="other"))
        assert other.get("/v2/credit-decision/v5", params={"project": record.project_code, "run": hid}).status_code == 404
        other.cookies.clear()
        assert other.get("/v2/credit-decision/v5", params={"project": record.project_code}, follow_redirects=False).status_code == 302
    monkeypatch.setattr("app.services.project_library_service.is_protected_reference", lambda rec: True)
    assert get(cenv, record).status_code == 409


def test_stale_working_terms_never_replace_historical_analysis(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    first = get(cenv, record, min_dscr=1.3).json()
    assert save(cenv, record, config(lender_case="P90-10y")).status_code == 200
    assert get(cenv, record, min_dscr=1.3).json() == first


def test_two_real_runs_keep_scenario_identity_and_old_payload(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    first = last(record)
    original = asdict(first)
    assert save(cenv, record, config(lender_case="P90-10y")).status_code == 200
    run(cenv, record)
    second = last(record)
    params = [("project", record.project_code), ("format", "json"), ("min_dscr", "1.25"),
              ("run", first.history_id), ("run", second.history_id)]
    response = cenv.client.get("/v2/credit-decision/v5", params=params)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [r["history_id"] for r in data["runs"]] == [first.history_id, second.history_id]
    assert data["comparisons"][0]["state"] in ("OBSERVED_CHANGE", "NOT_COMPARABLE")
    assert next(asdict(e) for e in history(record) if e.history_id == first.history_id) == original
