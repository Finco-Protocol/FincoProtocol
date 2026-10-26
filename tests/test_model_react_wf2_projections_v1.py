"""WF-React-2 — contract tests for the editable-workflow projections.

Read-only additions to ``/v2/model-react``: cost-line management contract
(eligible groups + canonical add/deactivate/reactivate routes), the scenario
override-editor projection, the export entry points and the corrected rename
field hint.  The mutations themselves stay on the existing canonical routes and
are exercised here exactly as the React client posts them (urlencoded forms,
composite CAS), so the wire contract the client relies on is pinned.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.persistence import db

OWNER = "wf2-owner"
STRANGER = "wf2-stranger"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf2.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi import FastAPI
    from app.v2.capex_router import capex_router
    from app.v2.grid_router import router as grid_router
    from app.v2.opex_router import opex_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(capex_router, prefix="/v2/capex")
    app.include_router(opex_router, prefix="/v2/opex")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))

        def create(kind="solar", user=OWNER):
            return create_reference_seeded_project(
                user_id=user, requested_name=f"WF2 {kind}", template_source=f"generic_{kind}_reference",
                capacity_mw=16)

        yield SimpleNamespace(client=client, stranger=stranger, create=create)
    reset_model_executor_for_tests()


def costlines(env, record, sheet):
    return env.client.get("/v2/model-react/costlines", params={"sheet": sheet, "project": record.project_code}).json()


def cas(payload):
    return {"workbook_version": payload["save"]["workbook_version"], "content_hash": payload["save"]["content_hash"]}


# ── cost-line management contract ────────────────────────────────────────────


@pytest.mark.parametrize("sheet,field,derived,rejected", [
    ("capex", "parent_category_code", "C.13", {"C.17", "C.18"}),
    ("opex", "parent_group_code", "B.13", set()),
])
def test_cost_line_management_contract_lists_only_groups_that_accept_custom_lines(env, sheet, field, derived, rejected):
    record = env.create()
    payload = costlines(env, record, sheet)
    mgmt = payload["line_management"]
    assert mgmt["add"] == {"url": f"/v2/{sheet}/line/add", "group_field": field}
    assert mgmt["deactivate"]["url"] == f"/v2/{sheet}/line/deactivate"
    assert mgmt["reactivate"]["url"] == f"/v2/{sheet}/line/reactivate"
    codes = [g["code"] for g in mgmt["eligible_groups"]]
    assert codes and derived not in codes and not rejected & set(codes)
    assert all(g["label"] for g in mgmt["eligible_groups"])
    assert "CSRF" in mgmt["csrf_note"]          # the inventoried gap is stated, not hidden
    assert all(line["category"] for line in payload["lines"]), "every line carries its group"


def test_capex_add_deactivate_reactivate_round_trip_matches_the_react_client_wire_format(env):
    record = env.create()
    before = costlines(env, record, "capex")
    group = before["line_management"]["eligible_groups"][0]["code"]
    add = post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": group, "label": "WF2 test line",
        "amount_keur": "125.5", "notes": "", **cas(before)}, follow_redirects=False)
    assert add.status_code == 303 and urlparse(add.headers["location"]).path == "/v2/workbook"
    after = costlines(env, record, "capex")
    added = [l for l in after["lines"] if l["label"] == "WF2 test line"]
    assert len(added) == 1 and added[0]["category"] == group and float(added[0]["amount_keur"]) == 125.5 and added[0]["active"]
    assert after["save"]["content_hash"] != before["save"]["content_hash"], "a committed change moves the composite CAS identity"

    line = added[0]
    off = post_valid_mutation(env.client, "/v2/capex/line/deactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(after)},
        follow_redirects=False)
    assert off.status_code == 303
    mid = costlines(env, record, "capex")
    row = next(l for l in mid["lines"] if l["sub_line_id"] == line["sub_line_id"])
    assert row["active"] is False
    on = post_valid_mutation(env.client, "/v2/capex/line/reactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": row["row_version"], **cas(mid)},
        follow_redirects=False)
    assert on.status_code == 303
    final = costlines(env, record, "capex")
    assert next(l for l in final["lines"] if l["sub_line_id"] == line["sub_line_id"])["active"] is True


def test_cost_line_add_with_a_stale_hash_changes_nothing(env):
    record = env.create()
    before = costlines(env, record, "opex")
    group = before["line_management"]["eligible_groups"][0]["code"]
    stale = dict(cas(before), content_hash="0" * 64)
    response = post_valid_mutation(env.client, "/v2/opex/line/add", data={
        "project": record.project_code, "parent_group_code": group, "label": "should not exist",
        "amount_keur": "1", "inflation_pct": "0", "notes": "", **stale}, follow_redirects=False)
    assert response.status_code in (303, 409)
    after = costlines(env, record, "opex")
    assert not [l for l in after["lines"] if l["label"] == "should not exist"]
    assert after["save"]["content_hash"] == before["save"]["content_hash"]


def test_cost_line_add_to_a_derived_group_is_refused_by_the_server(env):
    record = env.create()
    before = costlines(env, record, "capex")
    response = post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": "C.13", "label": "derived", "amount_keur": "1",
        "notes": "", **cas(before)}, follow_redirects=False)
    assert response.status_code == 422 and "error" in response.json()
    assert not [l for l in costlines(env, record, "capex")["lines"] if l["label"] == "derived"]


# ── runs / exports ───────────────────────────────────────────────────────────


def test_runs_projection_declares_read_only_export_entry_points(env):
    record = env.create()
    payload = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    exports = payload["exports"]
    assert exports["last_run"]["url"] == "/v2/workbook/export" and exports["last_run"]["authority"] == "CANONICAL_LAST_RUN"
    assert exports["last_run"]["available"] is False, "nothing committed yet -> nothing to export"
    assert exports["last_run"]["unavailable_reason"]
    assert exports["historical"]["url"] == "/v2/workbook/run-history/export"
    assert exports["historical"]["query"] == ["project", "history_id"]


def test_last_run_export_without_a_committed_run_fails_closed_without_running_the_engine(env, monkeypatch):
    record = env.create()
    monkeypatch.setattr("app.api.project_runner.run_project",
                        lambda *a, **k: pytest.fail("an export must never execute the engine"))
    response = post_valid_mutation(env.client, "/v2/workbook/export", data={"project": record.project_code})
    assert response.status_code == 400 and "spreadsheetml" not in response.headers.get("content-type", "")


# ── scenarios ────────────────────────────────────────────────────────────────


def make_scenario(env, record, name="WF2 child"):
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={
        "project": record.project_code, "scenario_name": name}, follow_redirects=False)
    assert response.status_code == 303
    scenarios = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    return next(s for s in scenarios["scenarios"] if s["name"] == name), scenarios


def overrides(client, record, scenario_id):
    return client.get("/v2/model-react/scenario-overrides",
                      params={"project": record.project_code, "scenario_id": scenario_id})


def test_scenarios_projection_names_the_real_rename_field(env):
    record = env.create()
    _child, listing = make_scenario(env, record)
    assert listing["mutations"]["rename"]["fields"] == ["project", "scenario_id", "new_name"]


def test_override_editor_lists_only_fields_the_canonical_run_applies(env):
    record = env.create()
    child, _ = make_scenario(env, record)
    payload = overrides(env.client, record, child["scenario_id"]).json()
    assert payload["ok"] is True and payload["editable"] is True
    assert [f["field_id"] for f in payload["fields"]] == ["tariff_eur_mwh"]
    field = payload["fields"][0]
    assert field["overridden"] is False and field["override_value"] is None and field["unit"] == "€/MWh"
    assert payload["unsupported_override_keys"] == []
    assert payload["mutations"]["update"]["url"] == "/v2/workbook/scenarios/update-overrides"


def test_override_save_and_reset_round_trip_without_running_the_model(env, monkeypatch):
    record = env.create()
    child, _ = make_scenario(env, record)
    monkeypatch.setattr("app.api.project_runner.run_project",
                        lambda *a, **k: pytest.fail("saving an override must never execute the engine"))
    saved = post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides", data={
        "project": record.project_code, "scenario_id": child["scenario_id"], "tariff_eur_mwh": "77.5"}, follow_redirects=False)
    assert saved.status_code == 303
    field = overrides(env.client, record, child["scenario_id"]).json()["fields"][0]
    assert field["overridden"] is True and float(field["override_value"]) == 77.5
    reset = post_valid_mutation(env.client, "/v2/workbook/scenarios/remove-override", data={
        "project": record.project_code, "scenario_id": child["scenario_id"], "field": "tariff_eur_mwh"}, follow_redirects=False)
    assert reset.status_code == 303
    field = overrides(env.client, record, child["scenario_id"]).json()["fields"][0]
    assert field["overridden"] is False and field["override_value"] is None


def test_unbound_override_is_refused_by_the_server_and_not_stored(env):
    record = env.create()
    child, _ = make_scenario(env, record)
    refused = post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides", data={
        "project": record.project_code, "scenario_id": child["scenario_id"], "gearing_pct": "55"}, follow_redirects=False)
    assert refused.status_code == 422 and refused.json()["code"] == "SCENARIO_OVERRIDE_UNBOUND"
    payload = overrides(env.client, record, child["scenario_id"]).json()
    assert payload["unsupported_override_keys"] == []


def test_base_case_overrides_are_not_editable_and_foreign_or_unknown_scenarios_are_hidden(env):
    record = env.create()
    child, listing = make_scenario(env, record)
    base = next(s for s in listing["scenarios"] if s["is_base_case"])
    assert overrides(env.client, record, base["scenario_id"]).json()["editable"] is False
    assert overrides(env.client, record, "does-not-exist").status_code == 404
    assert overrides(env.stranger, record, child["scenario_id"]).status_code == 404
    # a scenario of one project is never addressable under another project of the same owner
    sibling = env.create(kind="wind")
    assert sibling.project_id != record.project_id
    assert overrides(env.client, sibling, child["scenario_id"]).status_code == 404


def test_archived_scenario_override_projection_is_hidden(env):
    record = env.create()
    child, _ = make_scenario(env, record)
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/archive", data={
        "project": record.project_code, "scenario_id": child["scenario_id"]}, follow_redirects=False).status_code == 303
    assert overrides(env.client, record, child["scenario_id"]).status_code == 404


def test_scenario_select_and_rename_never_run_the_model(env, monkeypatch):
    record = env.create()
    child, listing = make_scenario(env, record)
    monkeypatch.setattr("app.api.project_runner.run_project",
                        lambda *a, **k: pytest.fail("scenario actions must never execute the engine"))
    base = next(s for s in listing["scenarios"] if s["is_base_case"])
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/select", data={
        "project": record.project_code, "scenario_id": base["scenario_id"]}, follow_redirects=False).status_code == 303
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/rename", data={
        "project": record.project_code, "scenario_id": child["scenario_id"], "new_name": "Renamed"}, follow_redirects=False).status_code == 303
    after = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    assert after["active_scenario_id"] == base["scenario_id"]
    assert any(s["name"] == "Renamed" for s in after["scenarios"])
