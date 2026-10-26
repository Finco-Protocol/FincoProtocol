"""WF-React-2 — financial-authority regression for the editable workflows.

The editors only post to existing canonical writers; this file proves the
writers the React client uses leave the model's financial authority intact:

* the same input change made through the registry-field writer (what the
  guided editors use) and through the canonical grid writer yields the SAME
  committed Run results, for a representative Solar and Wind model;
* a changed input changes the results of the NEXT Run only: Save, scenario
  actions, override edits, cost-line management and export never create or alter
  a Run, and the committed Run identity stays reconciled with the workspace;
* a protected reference refuses every mutation the React editors can send.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import pytest

from tests.test_model_react_wf2_projections_v1 import STRANGER, OWNER, costlines, cas, env  # noqa: F401


def workspace(env, record):
    return env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()


def history(env, record):
    return env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["runs"]


def run(env, record):
    contract = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["run_contract"]
    ws = workspace(env, record)
    response = env.client.post(contract["url"], data={
        "project": record.project_code, "content_hash": ws["workbook"]["composite_hash"],
        "workbook_version": ws["workbook"]["version"], "csrf_token": contract["csrf_token"]}, follow_redirects=False)
    assert response.status_code == 303 and "v2_err" not in response.headers["location"], response.headers["location"]


def committed_metrics(env, record):
    payload = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()
    assert payload["state"] == "CURRENT", payload.get("state")
    return payload["results"]["metrics"]


def shared_numeric_field(env, record):
    """A bound registry field that is ALSO an editable scalar grid cell."""
    sheet = {f["field_id"]: f for f in env.client.get(
        "/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()["fields"]}
    grid = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
    cells = {row["field_id"] for s in grid["grid"]["sections"] for c in s["categories"] for row in c["rows"]
             if row.get("editable") and row.get("field_id")}
    for field_id in ("project_setup.technical.p50_hours", "project_setup.technical.capacity_mw"):
        f = sheet.get(field_id)
        if f and f["binding_label"] == "bound" and field_id in cells and f["value"] not in (None, ""):
            return f
    pytest.fail(f"no shared field; grid cells={sorted(cells)[:10]}")


def via_registry_writer(env, record, field, value):
    tokens = env.client.get("/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()["save"]
    response = post_valid_mutation(env.client, "/v2/workbook/update", data={
        "project": record.project_code, "field_id": field["field_id"], "value": value, "sheet_id": "project_setup",
        "workbook_version": tokens["workbook_version"], "content_hash": tokens["content_hash"],
        "csrf_token": tokens["csrf_token"]}, follow_redirects=False)
    assert response.status_code == 303 and "v2_err" not in response.headers["location"], response.headers["location"]


def via_grid_writer(env, record, field, value):
    save = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()["save"]
    response = env.client.post(save["url"], json={
        "project": record.project_code, "csrf_token": save["csrf_token"], "workbook_version": save["workbook_version"],
        "content_hash": save["content_hash"], "scenario_id": save["scenario_id"],
        "cells": [{"field_id": field["field_id"], "value": value}]})
    assert response.status_code == 200 and response.json()["ok"] is True, response.text
    assert response.json()["model_executed"] is False


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_registry_and_grid_writers_produce_identical_committed_runs_and_control_differs(env, kind):
    control, by_registry, by_grid = env.create(kind), env.create(kind), env.create(kind)
    field = shared_numeric_field(env, by_registry)
    value = str(float(field["value"]) * 1.05)
    via_registry_writer(env, by_registry, field, value)
    via_grid_writer(env, by_grid, field, value)
    for record in (control, by_registry, by_grid):
        assert history(env, record) == [], "no Save created a Run"
        run(env, record)
        ws = workspace(env, record)
        assert ws["freshness"]["state"] == "CURRENT"
        rows = history(env, record)
        assert len(rows) == 1 and rows[0]["runtime_snapshot_id"] == ws["identity"]["snapshot_id"]
    a, b, c = (committed_metrics(env, r) for r in (by_registry, by_grid, control))
    assert a and a == b, "the two canonical writers must yield identical committed results"
    assert a != c, "the changed input must change the committed result of the next Run"


def test_cost_line_management_scenarios_overrides_and_export_never_create_or_alter_a_run(env):
    record = env.create()
    run(env, record)
    before_rows = history(env, record)
    before_metrics = committed_metrics(env, record)
    assert len(before_rows) == 1

    capex = costlines(env, record, "capex")
    group = capex["line_management"]["eligible_groups"][0]["code"]
    assert post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": group, "label": "financial authority probe",
        "amount_keur": "100", "notes": "", **cas(capex)}, follow_redirects=False).status_code == 303
    stale = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()
    assert stale["state"] == "STALE" and stale["results"]["metrics"] == before_metrics, \
        "the committed results are the prior Run's, untouched by the new line"
    exported = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["exports"]["last_run"]
    assert exported["available"] is True, exported["unavailable_reason"]
    export = post_valid_mutation(env.client, "/v2/workbook/export", data={"project": record.project_code})
    assert export.status_code == 200 and export.content[:2] == b"PK", export.text[:600]
    created = post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={
        "project": record.project_code, "scenario_name": "authority scenario"}, follow_redirects=False)
    assert created.status_code == 303
    listing = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    child = next(s for s in listing["scenarios"] if s["name"] == "authority scenario")
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides", data={
        "project": record.project_code, "scenario_id": child["scenario_id"], "tariff_eur_mwh": "90"},
        follow_redirects=False).status_code == 303
    assert env.client.get("/v2/model-react/scenario-compare", params={
        "project": record.project_code, "scenario_id": child["scenario_id"]}).status_code == 200
    # the new scenario is active and has no committed Run: the projection says so and the server agrees
    runs_payload = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    assert runs_payload["exports"]["last_run"]["available"] is False
    assert "active scenario" in runs_payload["exports"]["last_run"]["unavailable_reason"]
    assert post_valid_mutation(env.client, "/v2/workbook/export", data={"project": record.project_code}).status_code == 400
    assert history(env, record) == before_rows, "committed Run History is immutable under every non-Run action"
    # the active scenario is now the new child with no committed Run of its own: it never borrows the Base Run
    assert workspace(env, record)["freshness"]["state"] == "NOT_RUN"


def committed_metrics_state(env, record):
    return env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()["state"]


def test_scenario_overrides_stay_isolated_between_scenarios_and_from_the_working_copy(env):
    record = env.create()
    base_snapshot = workspace(env, record)["workbook"]["composite_hash"]
    ids = {}
    for name in ("isolation A", "isolation B"):
        assert post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={
            "project": record.project_code, "scenario_name": name}, follow_redirects=False).status_code == 303
    listing = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    for s in listing["scenarios"]:
        ids[s["name"]] = s["scenario_id"]
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides", data={
        "project": record.project_code, "scenario_id": ids["isolation A"], "tariff_eur_mwh": "88"},
        follow_redirects=False).status_code == 303

    def override(name):
        return env.client.get("/v2/model-react/scenario-overrides", params={
            "project": record.project_code, "scenario_id": ids[name]}).json()["fields"][0]

    assert override("isolation A")["overridden"] is True and float(override("isolation A")["override_value"]) == 88
    assert override("isolation B")["overridden"] is False and override("isolation B")["override_value"] is None
    compare = env.client.get("/v2/model-react/scenario-compare", params={
        "project": record.project_code, "scenario_id": ids["isolation B"]}).json()
    assert compare["differences"] == [], "an untouched scenario inherits the Working Copy on every field"
    assert any(d["field_id"] == "tariff_eur_mwh" for d in env.client.get(
        "/v2/model-react/scenario-compare", params={"project": record.project_code,
                                                    "scenario_id": ids["isolation A"]}).json()["differences"])
    assert history(env, record) == []


def make_protected(record):
    """Shape a project exactly like a canonical protected reference (role, flag and factory origin)."""
    from app.persistence.db import get_connection
    with get_connection() as connection:
        connection.execute("UPDATE projects SET project_role='reference', is_protected=1, project_origin='factory_template' WHERE project_id=?", (record.project_id,))
        connection.commit()


def test_protected_reference_refuses_every_mutation_the_react_editors_can_send(env):
    record = env.create()
    capex = costlines(env, record, "capex")
    group = capex["line_management"]["eligible_groups"][0]["code"]
    fields = env.client.get("/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()
    row = next(f for f in fields["fields"] if f["binding_label"] == "bound" and f["field_type"] in ("float", "mw", "mwh"))
    revenue = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    make_protected(record)
    before = workspace(env, record)["workbook"]["composite_hash"]

    refusals = [
        post_valid_mutation(env.client, "/v2/workbook/update", data={
            "project": record.project_code, "field_id": row["field_id"], "value": "1", "sheet_id": "project_setup",
            "workbook_version": fields["save"]["workbook_version"], "content_hash": fields["save"]["content_hash"],
            "csrf_token": fields["save"]["csrf_token"]}, follow_redirects=False),
        post_valid_mutation(env.client, "/v2/capex/line/add", data={
            "project": record.project_code, "parent_category_code": group, "label": "x", "amount_keur": "1",
            "notes": "", **cas(capex)}, follow_redirects=False),
        env.client.post("/v2/workbook/revenue/contracts", data={
            "project": record.project_code, "csrf_token": revenue["csrf_token"], "content_hash": revenue["content_hash"],
            "contracts": "{}", "action": "save"}, follow_redirects=False),
        post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={
            "project": record.project_code, "scenario_name": "should not exist"}, follow_redirects=False),
    ]
    labels = ["registry field", "capex line", "revenue contracts", "scenario create"]
    for label, response in zip(labels, refusals):
        assert response.status_code in (403, 409, 303), (label, response.status_code)
        if response.status_code == 303:
            assert "v2_err" in response.headers["location"], (label, response.headers["location"])
    assert workspace(env, record)["workbook"]["composite_hash"] == before
    assert not [l for l in costlines(env, record, "capex")["lines"] if l["label"] == "x"]
    scenarios = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    assert not [s for s in scenarios["scenarios"] if s["name"] == "should not exist"]
    assert scenarios["project"]["protected_reference"] is True
