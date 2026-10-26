"""UX-07 Correction B — canonical scenario & revenue contract integrity tests.

Real-endpoint tests (no mocks) pinning:
* B1 the canonical rename form contract (``new_name``) with persistence;
* B2 inheritance-true scenario compare through ``resolve_scenario_snapshot``
  (zero differences for a fresh scenario; exact one-override diffs; explicit
  zero vs inherited; removed override restores inheritance; run evidence
  attributed per side and UNAVAILABLE rather than borrowed);
* B3 an end-to-end Revenue contracts Save through the canonical writer
  (composite CAS, bound CSRF) with malformed/stale/refusal cases;
* archived and foreign scenarios denied.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.persistence import db

OWNER = "cb-owner"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cb.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi import FastAPI
    from app.v2.grid_router import router as grid_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        other_client = TestClient(app)
        other_client.cookies.set(COOKIE_NAME, create_session_token(user_id="cb-other-owner", username="other-admin"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"CB {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        def make_scenario(code, name="Downside", session=None):
            session = session or client
            created = post_valid_mutation(session, "/v2/workbook/scenarios/create",
                                   data={"project": code, "scenario_name": name})
            assert created.status_code in (200, 303)
            scenarios = session.get("/v2/model-react/scenarios", params={"project": code}).json()
            return next(s for s in scenarios["scenarios"] if s["name"] == name)

        def create_as_other(kind="solar", name=None):
            return create_reference_seeded_project(
                user_id="cb-other-owner", requested_name=name or f"CB other {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, anonymous=anonymous, create=create,
                              make_scenario=make_scenario, other_client=other_client,
                              create_as_other=create_as_other)
    reset_model_executor_for_tests()


def _iter_nodes(node):
    """Yield every dict in a nested JSON structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v)


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


# ── B1: the canonical rename contract is `new_name` ──────────────────────────

def test_rename_with_new_name_persists(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Downside")
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/rename",
                               data={"project": record.project_code, "scenario_id": scenario["scenario_id"],
                                     "new_name": "Downside 2027"})
    assert response.status_code in (200, 303), response.text[:200]
    scenarios = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    names = {s["name"] for s in scenarios["scenarios"]}
    assert "Downside 2027" in names and "Downside" not in names


def test_rename_without_new_name_is_a_form_validation_failure(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Downside")
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/rename",
                               data={"project": record.project_code, "scenario_id": scenario["scenario_id"]})
    assert response.status_code == 422, "missing new_name must fail the form contract"
    scenarios = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    assert any(s["name"] == "Downside" for s in scenarios["scenarios"]), "nothing may change on a 422"


def test_renaming_the_base_case_is_refused(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    base = next(s for s in env.client.get("/v2/model-react/scenarios",
                                          params={"project": record.project_code}).json()["scenarios"]
                if s["is_base_case"])
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/rename",
                               data={"project": record.project_code, "scenario_id": base["scenario_id"],
                                     "new_name": "Not Base"})
    assert response.status_code in (403, 409, 422)



def _find_field_value(node, field_id: str):
    """Deep-search the canonical inputs projection for one field's value."""
    if isinstance(node, dict):
        if node.get("field_id") == field_id and "value" in node:
            return node["value"]
        for v in node.values():
            r = _find_field_value(v, field_id)
            if r is not None:
                return r
    if isinstance(node, list):
        for v in node:
            r = _find_field_value(v, field_id)
            if r is not None:
                return r
    return None

# ── B2: inheritance-true compare ─────────────────────────────────────────────

def test_fresh_scenario_with_no_overrides_has_zero_differences(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Fresh")
    compare = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    assert compare["ok"] is True and compare["differences"] == [], \
        "an inheriting scenario must report ZERO differences"


def test_single_override_reports_exactly_one_difference(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "One override")
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides",
                               data={"project": record.project_code, "scenario_id": scenario["scenario_id"],
                                     "tariff_eur_mwh": "71.5"})
    assert response.status_code in (200, 303)
    compare = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    assert len(compare["differences"]) == 1, compare["differences"]
    diff = compare["differences"][0]
    assert diff["field_id"] == "tariff_eur_mwh"
    assert diff["explicitly_overridden"] is True
    assert float(diff["scenario_value"]) == pytest.approx(71.5)


def test_explicit_zero_override_differs_from_inherited_value(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    # The seeded Base tariff is deterministic and NONZERO: the canonical inputs
    # grid projects `revenue.ppa.base_tariff` = 50 €/MWh for the solar reference.
    grid = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
    base_cell = next((c for c in _iter_nodes(grid["grid"]) if isinstance(c, dict)
                      and c.get("field_id") == "revenue.ppa.base_tariff"), None)
    assert base_cell is not None and float(base_cell["value"]) != 0, \
        "the deterministic fixture requires a nonzero Base tariff"
    base_tariff = float(base_cell["value"])

    scenario = env.make_scenario(record.project_code, "Zero tariff")
    # a fresh scenario inherits the Base tariff: no differences yet
    before = env.client.get("/v2/model-react/scenario-compare",
                            params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    assert not any(d["field_id"] == "tariff_eur_mwh" for d in before["differences"])

    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides",
                               data={"project": record.project_code, "scenario_id": scenario["scenario_id"],
                                     "tariff_eur_mwh": "0"})
    assert response.status_code in (200, 303), "the canonical writer must accept an explicit zero"

    compare = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    tariff_diff = next(d for d in compare["differences"] if d["field_id"] == "tariff_eur_mwh")
    assert float(tariff_diff["scenario_value"]) == 0.0, "the effective scenario value is exactly zero"
    assert tariff_diff["explicitly_overridden"] is True, "an explicit zero must never be reported as inherited"
    assert float(tariff_diff["base_value"]) == pytest.approx(base_tariff), "the Base side stays nonzero"
    assert len(compare["differences"]) == 1, "only the tariff assumption changed"


def test_removed_override_restores_inheritance(env, monkeypatch):
    from app.persistence.db import get_connection
    from app.persistence.scenarios_repository import get_scenario

    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Temp override")

    # 1. set an override DIFFERENT from Base (Base tariff is the seeded 50)
    post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides",
                    data={"project": record.project_code, "scenario_id": scenario["scenario_id"],
                          "tariff_eur_mwh": "70"})
    with_over = env.client.get("/v2/model-react/scenario-compare",
                               params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    tariff_with = next(d for d in with_over["differences"] if d["field_id"] == "tariff_eur_mwh")
    assert float(tariff_with["scenario_value"]) == pytest.approx(70.0)

    # 2. the override key is genuinely persisted on the scenario record
    persisted = get_scenario(scenario["scenario_id"], OWNER)
    assert "tariff_eur_mwh" in (persisted.overrides or {})

    # 3. remove it through the canonical removal route (repeatable `field` form)
    removal = post_valid_mutation(env.client, "/v2/workbook/scenarios/remove-override",
                              content=f"project={record.project_code}&scenario_id={scenario['scenario_id']}"
                                      f"&field=tariff_eur_mwh",
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert removal.status_code in (200, 303), removal.text[:200]

    # 4. the key is actually ABSENT from the persisted scenario
    persisted_after = get_scenario(scenario["scenario_id"], OWNER)
    assert "tariff_eur_mwh" not in (persisted_after.overrides or {}), \
        "removal must delete the override key, not set it to zero or the base value"

    # 5. the effective scenario value inherits Base again
    without = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    assert not any(d["field_id"] == "tariff_eur_mwh" for d in without["differences"]), \
        "a removed override must restore inheritance"


def test_scenario_selection_never_fabricates_run_history(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Selected")
    response = post_valid_mutation(env.client, "/v2/workbook/scenarios/select",
                               data={"project": record.project_code, "scenario_id": scenario["scenario_id"]})
    assert response.status_code in (200, 303)
    runs = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    assert runs["runs"] == [], "selecting a scenario must never fabricate a committed Run"


def test_scenario_run_evidence_attributed_per_side(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "Evidence")
    compare = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": scenario["scenario_id"]}).json()
    assert compare["scenario"]["run_evidence"]["state"] == "UNAVAILABLE", \
        "a scenario with no committed Run is UNAVAILABLE — never borrowed from the workspace"
    assert compare["base"]["run_evidence"]["state"] == "UNAVAILABLE"


def test_archived_scenario_compare_is_denied(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    scenario = env.make_scenario(record.project_code, "ToArchive")
    post_valid_mutation(env.client, "/v2/workbook/scenarios/archive",
                    data={"project": record.project_code, "scenario_id": scenario["scenario_id"]})
    response = env.client.get("/v2/model-react/scenario-compare",
                              params={"project": record.project_code, "scenario_id": scenario["scenario_id"]})
    assert response.status_code == 404, "an archived scenario must not be comparable"


def test_foreign_scenario_compare_is_denied(env, monkeypatch):
    flag_on(monkeypatch)
    mine = env.create()
    # the foreign project AND its scenario are created by the OTHER owner's
    # own authenticated session (a cross-user create through the OWNER session
    # is already denied with 404 by resolve_accessible_project)
    foreign = env.create_as_other(name="CB Foreign Solar")
    foreign_scenario = env.make_scenario(foreign.project_code, "Foreign", session=env.other_client)
    assert foreign_scenario["scenario_id"]

    response = env.client.get("/v2/model-react/scenario-compare",
                              params={"project": mine.project_code, "scenario_id": foreign_scenario["scenario_id"]})
    assert response.status_code == 404
    assert response.json()["code"] == "SCENARIO_NOT_FOUND"
    assert "Foreign" not in response.text, "no foreign scenario data may be disclosed"


# ── B3: end-to-end Revenue contracts Save through the canonical writer ───────

def test_revenue_contracts_save_commits_and_updates_the_projection(env, monkeypatch):
    flag_on(monkeypatch)
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from tests.test_wf07_revenue_multistream import contracts

    record = env.create()
    inputs = WorkbookService.build_draft_input_set_from_workspace(
        get_workspace_state(OWNER, record.project_id)).to_projectinputs()
    payload = contracts(inputs, "solar", price=95, merchant_price=90, strike=100, index=0.02)
    before = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert before["contracts"]["active"] is False, "the seeded project starts without a contract"
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1)
              for k in ("content_hash", "workbook_version", "csrf_token")}
    tokens["csrf_token"] = _revenue_form_csrf(page.text)
    response = env.client.post("/v2/workbook/revenue/contracts",
                               data={"project": record.project_code, **tokens,
                                     "contracts": json.dumps(payload), "action": "save"})
    assert response.status_code in (200, 303), response.text[:300]
    after = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert after["contracts"]["active"] is True, "the committed contract must be visible in the projection"
    saved = json.loads(after["contracts"]["raw"])
    assert saved == json.loads(json.dumps(payload)), "the canonical raw payload must round-trip"
    assert after["save"]["content_hash"] != before["save"]["content_hash"], "composite CAS must advance"


def test_revenue_contracts_stale_cas_is_refused(env, monkeypatch):
    flag_on(monkeypatch)
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from tests.test_wf07_revenue_multistream import contracts

    record = env.create()
    inputs = WorkbookService.build_draft_input_set_from_workspace(
        get_workspace_state(OWNER, record.project_id)).to_projectinputs()
    payload = contracts(inputs, "solar", price=95, merchant_price=90)
    stale_hash = "0" * 64
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1)
              for k in ("workbook_version", "csrf_token")}
    tokens["csrf_token"] = _revenue_form_csrf(page.text)
    response = env.client.post("/v2/workbook/revenue/contracts",
                               data={"project": record.project_code, **tokens,
                                     "content_hash": stale_hash,
                                     "contracts": json.dumps(payload), "action": "save"})
    assert response.status_code in (403, 409), "a stale composite hash must be refused"
    after = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert after["contracts"]["active"] is False, "a refused save must not create the contract"


def test_revenue_contracts_malformed_payload_is_refused(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1)
              for k in ("content_hash", "workbook_version", "csrf_token")}
    tokens["csrf_token"] = _revenue_form_csrf(page.text)
    response = env.client.post("/v2/workbook/revenue/contracts",
                               data={"project": record.project_code, **tokens,
                                     "contracts": json.dumps({"version": 999, "nonsense": True}),
                                     "action": "save"})
    assert response.status_code in (200, 303, 422)
    if response.status_code in (200, 303):
        after = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
        assert after["contracts"]["active"] is False, "an invalid schema must not persist"


def test_revenue_contracts_without_session_never_succeeds(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = env.anonymous.post("/v2/workbook/revenue/contracts",
                                  data={"project": record.project_code, "csrf_token": "x",
                                        "content_hash": "h", "contracts": "{}", "action": "save"})
    assert response.status_code == 401 and "Unauthenticated" in response.json().get("error", "")


def test_revenue_contracts_on_protected_reference_is_refused(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    from app.persistence.db import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' "
                     "WHERE project_id=?", (record.project_id,))
    projection = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert projection["project"]["protected_reference"] is True
    save = projection["save"]
    response = env.client.post(save["url"],
                               data={"project": record.project_code, "csrf_token": save["csrf_token"],
                                     "content_hash": save["content_hash"],
                                     "workbook_version": save["workbook_version"],
                                     "contracts": json.dumps({"version": 1, "technology": "solar", "streams": []}),
                                     "action": "save"})
    assert response.status_code == 409 and "rotected" in response.json().get("error", "")
    after = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert after["contracts"]["active"] is False, "a protected-reference write must never persist"


def _revenue_form_csrf(html):
    """Use the released Revenue form token, not another form's first token."""
    from bs4 import BeautifulSoup
    form = BeautifulSoup(html, "html.parser").select_one(
        'form[hx-post="/v2/workbook/revenue/contracts"], form[action="/v2/workbook/revenue/contracts"]')
    return form.select_one('input[name="csrf_token"]')["value"]
