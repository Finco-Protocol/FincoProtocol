"""RC-UX B1 (Audit A GAP-R4) — React What-if over the REAL Q4 authority and a REAL committed Solar / Wind lifecycle.

Preview writes nothing and runs nothing; the scenario is created ``NOT_RUN`` through the EXISTING signed-token commit route; the Base Case
and every committed Run stay immutable; the committed scenario Run compares against the Base Run.
"""
from __future__ import annotations

import json
import re
import sqlite3

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.run_clone_csrf import post_valid_csrf
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)

OWNER = "decision-user"
OPTIONS = "/v2/model-react/whatif/options"
PREVIEW = "/v2/model-react/whatif/preview"
COMMIT = "/v2/workbook/whatif/commit"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture
def wi(env, monkeypatch):  # noqa: F811
    from app.v2.react_compare import router as compare_router
    from app.v2.react_whatif import router
    from app.v2.whatif_router import router as legacy_whatif
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    env.client.app.include_router(compare_router, prefix="/v2")
    if not any(getattr(r, "path", "") == COMMIT for r in env.client.app.routes):
        env.client.app.include_router(legacy_whatif, prefix="/v2")
    return env


def run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                           data={"project": record.project_code, **tokens(page.text)}).status_code == 200
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(OWNER, record.project_id)[0]


def options(env, record):
    response = env.client.get(OPTIONS, params={"project": record.project_code})
    assert response.status_code == 200, response.text[:400]
    return response.json()


def preview(env, record, check_id="QM-SD-007", value="1.35", name="DSCR 1.35 what-if"):
    return env.client.get(PREVIEW, headers=HDR, params={"project": record.project_code, "check_id": check_id, "proposed_value": value, "scenario_name": name})


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in ("/model-react/whatif/options", "/model-react/whatif/preview"):
        assert paths.count(path) == 1 and paths.index(path) < paths.index("/model-react/{project_code}")


def test_nothing_is_offered_before_a_committed_run(wi):
    record = wi.create("solar")
    data = options(wi, record)
    assert data["run_state"] == "NOT_RUN" and data["candidates"] == [] and data["reason"] == "Q4_REQUIRES_Q1_COMMITTED_FINDING"
    assert preview(wi, record).status_code == 409                                         # the authority refuses; no preview without a Run


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_lifecycle_preview_commit_run_and_compare(wi, kind):
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.workspace_repository import get_workspace_state
    record = wi.create(kind)
    base = run(wi, record)
    data = options(wi, record)
    by_field = {c["field_id"]: c for c in data["candidates"]}
    assert set(by_field) == {"debt.senior.target_dscr", "debt.senior.gearing_pct"}          # QM-SD-004/007 share one field: offered once
    dscr = by_field["debt.senior.target_dscr"]
    assert dscr["unit"] == "x" and dscr["original"] is not None and dscr["eligible"] is True and dscr["finding_status"] in ("FAIL", "WARNING", "PASS")
    ws_before = get_workspace_state(OWNER, record.project_id)
    before = db_dump()
    response = preview(wi, record, value=str(round(dscr["original"] + 0.15, 4)))
    assert response.status_code == 200, response.text[:500]
    body = response.json()["preview"]
    assert response.headers["cache-control"] == "private, no-store"
    assert body["assumption"]["original"] == dscr["original"] and body["assumption"]["proposed"] == pytest.approx(dscr["original"] + 0.15)
    assert body["assumption"]["delta"] == pytest.approx(0.15) and body["semantics"]["is_a_run"] is False and body["semantics"]["shows_projected_kpi"] is False
    assert set(body) == {"finding", "assumption", "scenario_name", "stale", "last_run_snapshot", "token", "commit", "semantics"}     # no KPI field exists
    assert db_dump() == before and get_workspace_state(OWNER, record.project_id) == ws_before   # preview wrote nothing
    assert [s for s in list_scenarios(user_id=OWNER, project_id=record.project_id) if not s.is_base_case] == []     # only the Base Case exists
    # commit through the EXISTING route with the signed token (what the React panel posts)
    result = wi.client.post(COMMIT, data={"project": record.project_code, "token": body["token"], "confirmed": "yes"})
    assert result.status_code == 200 and 'data-testid="q4-created"' in result.text, result.text[:500]
    scenario = next(s for s in list_scenarios(user_id=OWNER, project_id=record.project_id) if s.scenario_name == "DSCR 1.35 what-if")
    assert scenario.overrides == {"target_dscr": pytest.approx(dscr["original"] + 0.15)} and not scenario.is_base_case
    assert [h.history_id for h in __import__("app.persistence.run_history_repository", fromlist=["x"]).get_run_history(OWNER, record.project_id)] == [base.history_id]   # no Run
    again = wi.client.post(COMMIT, data={"project": record.project_code, "token": body["token"], "confirmed": "yes"})
    assert 'data-testid="q4-created"' not in again.text                                      # a replayed confirmation creates nothing
    assert len([s for s in list_scenarios(user_id=OWNER, project_id=record.project_id) if s.scenario_name == "DSCR 1.35 what-if"]) == 1
    # run the scenario explicitly, then compare with the Base Run
    assert post_valid_mutation(wi.client, "/v2/workbook/scenarios/select", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "scenario_id": scenario.scenario_id}).status_code == 200
    child = run(wi, record)
    assert child.last_runtime_scenario_id == scenario.scenario_id and child.history_id != base.history_id
    cmp = wi.client.get("/v2/model-react/compare", params=[("project", record.project_code), ("run", base.history_id), ("run", child.history_id)])
    assert cmp.status_code == 200
    rows = {r["key"]: r for r in cmp.json()["rows"]}
    assert rows["target_dscr"]["raw_values"][1] == pytest.approx(dscr["original"] + 0.15)       # the committed scenario Run carries the change
    assert rows["target_dscr"]["raw_values"][0] == dscr["original"]                              # the Base Run is untouched
    assert base.to_dict() == __import__("app.persistence.run_history_repository", fromlist=["x"]).get_run_history_entry(OWNER, record.project_id, base.history_id).to_dict()


@pytest.mark.parametrize("value,code", [("abc", "Q4_VALUE_INVALID"), ("nan", None), ("-1", "Q4_VALUE_INVALID"), ("x" * 120, "Q4_INPUT_TOO_LONG")])
def test_invalid_values_are_typed_refusals(wi, value, code):
    record = wi.create("solar")
    run(wi, record)
    response = preview(wi, record, value=value)
    assert response.status_code in (409, 422) and response.json()["ok"] is False
    if code:
        assert response.json()["code"] == code and "Nothing was changed" in response.json()["message"]


def test_preview_guards_header_unknown_finding_vertical_name_and_unknown_query(wi):
    record = wi.create("solar")
    run(wi, record)
    assert wi.client.get(PREVIEW, params={"project": record.project_code, "check_id": "QM-SD-007", "proposed_value": "1.3", "scenario_name": "x"}).status_code == 400
    assert preview(wi, record, check_id="QM-COV-001").status_code == 422
    assert preview(wi, record, name=" ").status_code == 422
    assert wi.client.get(PREVIEW, headers=HDR, params={"project": record.project_code, "check_id": "QM-SD-007", "proposed_value": "1.3",
                                                      "scenario_name": "x", "extra": "1"}).status_code == 400
    dc = wi.create("data_center")
    run(wi, dc)
    assert options(wi, dc)["candidates"] == [] or all(not c["eligible"] for c in options(wi, dc)["candidates"])      # DC / EV are not enabled for What-if
    assert preview(wi, dc).status_code == 422


def test_security_foreign_unauthenticated_protected_and_flag(wi, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record = wi.create("solar")
    run(wi, record)
    for who in (None, "foreign-user"):
        with wi.client.__class__(wi.client.app) as client:
            if who:
                client.cookies.set(COOKIE_NAME, create_session_token(user_id=who, username="other"))
            assert client.get(OPTIONS, params={"project": record.project_code}, follow_redirects=False).status_code == (404 if who else 401)
            assert client.get(PREVIEW, headers=HDR, params={"project": record.project_code, "check_id": "QM-SD-007", "proposed_value": "1.3",
                                                            "scenario_name": "x"}, follow_redirects=False).status_code == (404 if who else 401)
    with monkeypatch.context() as scoped:
        scoped.setattr("app.services.project_library_service.is_protected_reference", lambda r: True)
        assert wi.client.get(OPTIONS, params={"project": record.project_code}).status_code == 403
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert wi.client.get(OPTIONS, params={"project": record.project_code}).status_code == 404
