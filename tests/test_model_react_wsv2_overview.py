"""WS1: immutable, owner-scoped Overview evidence; real canonical Runs, no fixtures of outputs."""
from __future__ import annotations

import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.run_clone_csrf import post_valid_csrf
from tests.model_mutation_csrf import post_valid_mutation


@pytest.fixture
def overview(env, monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    return env


def read(env, code):
    return env.client.get("/v2/model-react/overview", params={"project": code})


def dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                              data={"project": record.project_code, **tokens(page.text)})
    assert response.status_code == 200
    from app.persistence.workspace_repository import get_workspace_state
    state = get_workspace_state("decision-user", record.project_id)
    assert state.last_runtime_snapshot_id
    return state


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_overview_not_run_and_committed_run_never_write_or_use_the_draft(overview, kind):
    record = overview.create(kind)
    before = dump()
    response = read(overview, record.project_code)
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_id"] is None and response.json()["assumptions"] == []
    assert dump() == before
    committed = run(overview, record)
    before = dump()
    result = read(overview, record.project_code)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["snapshot_id"] == committed.last_runtime_snapshot_id
    assert body["content_hash"] == committed.last_runtime_composite_hash
    assert body["scenario_id"] == committed.last_runtime_scenario_id
    assert body["assumptions"] and body["sources_uses"]["available"]
    assert dump() == before
    # A real canonical mutation makes the draft differ, while Last Run evidence stays immutable.
    page = overview.client.get("/v2/workbook", params={"project": record.project_code})
    saved = post_valid_mutation(overview.client, "/v2/workbook/update", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "sheet_id": "project_setup", "field_id": "project_setup.technical.horizon_years",
        "value": "31", **tokens(page.text)})
    assert "workbook-field-saved" in saved.headers.get("HX-Trigger", ""), saved.text[:300]
    before = dump()
    stale = read(overview, record.project_code).json()
    assert stale["snapshot_id"] == body["snapshot_id"]
    assert stale["assumptions"] == body["assumptions"]
    assert stale["sources_uses"]["view"]["freshness"] == "STALE"
    assert dump() == before


def test_overview_auth_flag_and_other_owner_are_refused(overview, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record = overview.create()
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert read(overview, record.project_code).status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    overview.client.cookies.set(COOKIE_NAME, create_session_token(user_id="different-owner", username="admin"))
    assert read(overview, record.project_code).status_code == 404
    overview.client.cookies.clear()
    assert read(overview, record.project_code).status_code == 401


def test_overview_race_or_malformed_evidence_fails_closed(overview, monkeypatch):
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    record = overview.create()
    def changed(self):
        raise PostRunContextChanged("private data must not leak")
    monkeypatch.setattr(PostRunRequestContext, "validate_current", changed)
    response = read(overview, record.project_code)
    assert response.status_code == 503
    assert response.json()["code"] == "OVERVIEW_UNAVAILABLE"
    assert "private data" not in response.text


def test_wind_overview_prefers_committed_canonical_ppa_over_legacy_values(overview):
    record = overview.create('wind')
    for field, value in [('revenue.ppa.base_tariff', '81.25'), ('revenue.ppa.term_years', '17')]:
        page = overview.client.get('/v2/workbook', params={'project': record.project_code})
        response = post_valid_mutation(overview.client, '/v2/workbook/update', headers={'HX-Request': 'true'}, data={
            'project': record.project_code, 'sheet_id': 'revenue', 'field_id': field, 'value': value, **tokens(page.text)})
        assert 'workbook-field-saved' in response.headers.get('HX-Trigger', ''), response.text[:300]
    state = run(overview, record)
    from app.workbook.input_set import ProjectInputSet
    saved = ProjectInputSet.from_snapshot(state.last_runtime_snapshot)
    assert saved.get('revenue.ppa.base_tariff') != saved.get('revenue.ppa.tariff_legacy')
    body = read(overview, record.project_code).json()
    fields = {field['field_id']: field for field in body['assumptions']}
    assert fields['revenue.ppa.base_tariff']['display'] == '81.25'
    assert fields['revenue.ppa.term_years']['display'] == '17'
    assert 'revenue.ppa.tariff_legacy' not in fields and 'revenue.ppa.ppa_term_legacy' not in fields
