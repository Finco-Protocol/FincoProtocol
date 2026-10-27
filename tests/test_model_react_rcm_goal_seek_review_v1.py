"""RC-M Lane B — review tests for the two state-changing paths' neighbours: Goal Seek Apply freshness and the expensive GETs.

* Apply can never reuse a candidate against a later Working Copy, another scenario or a tariff the model no longer treats as a
  plain input; the preview writes nothing (Working Copy, Last Run, Run History, scenarios) and records no Run.
* The expensive GETs (sensitivity strip / matrix, Goal Seek solve) spend engine capacity only after the flag, the React request
  header, the session, project ownership and the protected-reference check — and a busy engine is reported once (429), never
  retried by the server.
Synthetic data only.
"""
from __future__ import annotations

import json

import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.scenarios_repository import list_scenarios
from app.persistence.workspace_repository import get_workspace_state
from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_rcm_goal_seek_v1 import (  # noqa: F401  (fixtures and helpers shared with the contract tests)
    BASE, FIELD, HDR, OWNER, STRANGER, apply_body, baseline_irr_pct, call, env, solved_binding, state, with_sensitivity,
)

SENS = "/v2/model-react/analysis/sensitivity"


def _tariff(record) -> float:
    return float(get_workspace_state(record.user_id, record.project_id).draft_snapshot["rev_ppa_base_tariff"])


def _scenario_count(record) -> int:
    return len(list_scenarios(record.user_id, record.project_id))


def _everything(record):
    ws = get_workspace_state(record.user_id, record.project_id)
    return (state(record), len(get_run_history(record.user_id, record.project_id)), _scenario_count(record), ws.active_scenario_id)


# ── Apply freshness ────────────────────────────────────────────────────────

def test_the_preview_is_side_effect_free_for_workspace_runs_and_scenarios(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    before = _everything(record)
    binding, _result = solved_binding(env, record)
    assert binding["csrf_token"] and _everything(record) == before


def test_a_candidate_is_refused_after_a_later_working_copy_change(with_sensitivity):
    from app.workbook.update_service import WorkbookUpdateService

    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    tariff = _tariff(record)
    ws = get_workspace_state(record.user_id, record.project_id)
    WorkbookUpdateService.apply_draft_update(ws=ws, field_id="project_setup.technical.capacity_mw", raw_value="23.5",
                                             content_hash=binding["content_hash"], workbook_version=binding["workbook_version"],
                                             project_record=record)               # the canonical writer, from the same identity
    after_capacity = state(record)
    refused = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert refused.status_code == 409 and refused.json()["code"] == "STALE_CONTENT"
    assert _tariff(record) == tariff and state(record) == after_capacity            # the later edit is kept, the stale tariff never lands


def test_a_candidate_is_refused_after_the_active_scenario_changes(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    project = {"project": record.project_code}
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={**project, "scenario_name": "Other case"}).status_code == 200
    child = next(s for s in list_scenarios(record.user_id, record.project_id) if not s.is_base_case)
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/select", data={**project, "scenario_id": child.scenario_id}).status_code == 200
    tariff, before = _tariff(record), state(record)
    refused = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert refused.status_code == 409 and refused.json()["code"] == "STALE_CONTENT"
    assert _tariff(record) == tariff and state(record) == before
    fresh = call(env.client, "catalog", project=record.project_code).json()
    assert fresh["binding"]["content_hash"] != binding["content_hash"]                # the identity changed with the scenario


def test_a_candidate_is_refused_when_the_tariff_is_later_owned_by_a_contract_and_no_new_one_is_offered(with_sensitivity):
    from app.persistence.db import get_connection

    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    ws = get_workspace_state(record.user_id, record.project_id)
    snapshot = dict(ws.draft_snapshot)
    snapshot["rev_multistream_config_json"] = json.dumps({"streams": [{"id": "ppa-1"}]})        # a contract now owns the price
    conn = get_connection()
    try:
        conn.execute("UPDATE workspace_states SET draft_snapshot_json=?, dirty=1 WHERE user_id=? AND project_id=?",
                     (json.dumps(snapshot), record.user_id, record.project_id))
        conn.commit()
    finally:
        conn.close()
    tariff, before = _tariff(record), state(record)
    refused = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert refused.status_code == 409 and refused.json()["code"] == "STALE_CONTENT" and _tariff(record) == tariff and state(record) == before
    solved = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value="9")
    assert solved.status_code == 422 and solved.json().get("apply") is None                  # nothing is offered for a contract-owned price


def test_an_apply_never_runs_and_never_writes_history_or_scenarios(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    history, scenarios = len(get_run_history(record.user_id, record.project_id)), _scenario_count(record)
    last_run = get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id
    assert env.client.post(f"{BASE}/apply", json=apply_body(record, binding)).status_code == 200
    ws = get_workspace_state(record.user_id, record.project_id)
    assert ws.last_runtime_snapshot_id == last_run                                              # no Run was recorded
    assert len(get_run_history(record.user_id, record.project_id)) == history and _scenario_count(record) == scenarios


def test_a_binding_issued_to_one_session_is_useless_to_another(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    before = state(record)
    stolen = env.stranger.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert stolen.status_code == 403 and stolen.json()["code"] == "CSRF_INVALID" and state(record) == before


# ── expensive GETs: guards before engine capacity ──────────────────────────

@pytest.fixture()
def engine_calls(monkeypatch):
    calls = []

    async def counting(*args, **kwargs):
        calls.append(args)
        raise AssertionError("the engine must not be reached")

    monkeypatch.setattr("app.runtime.model_execution.run_model_process", counting)
    return calls


HEAVY = (
    ("strip", f"{SENS}/strip", {"driver": "tariff"}),
    ("matrix", f"{SENS}/matrix", {"driver_a": "tariff", "driver_b": "capex", "metric": "project_irr"}),
    ("solve", f"{BASE}/solve", {"target_metric": "project_irr", "target_value": "9"}),
)


@pytest.mark.parametrize("name,path,params", HEAVY)
def test_heavy_reads_refuse_before_any_engine_capacity_is_spent(with_sensitivity, engine_calls, name, path, params):
    env = with_sensitivity
    record = env.create()
    mine = {"project": record.project_code, **params}
    assert env.client.get(path, params=mine).status_code == 400                                    # no React request header
    assert env.anonymous.get(path, params=mine, headers=HDR).status_code == 401
    assert env.stranger.get(path, params=mine, headers=HDR).status_code == 404                     # not the owner: indistinguishable
    assert env.client.get(path, params={**mine, "project": "no-such-project"}, headers=HDR).status_code == 404
    assert engine_calls == []


@pytest.mark.parametrize("name,path,params", HEAVY)
def test_heavy_reads_refuse_a_protected_reference_without_the_engine(env, engine_calls, name, path, params):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    from app.v2.react_analysis import router as analysis_router

    env.app.include_router(analysis_router, prefix="/v2")
    ensure_reference_models()
    reference = get_reference_by_template_source("generic_solar_reference")
    response = env.client.get(path, params={"project": reference.project_code, **params}, headers=HDR)
    assert response.status_code in (404, 409) and engine_calls == []


@pytest.fixture()
def busy_engine(monkeypatch):
    from app.runtime.model_execution import ModelExecutionBusy

    calls = []

    async def busy(*args, **kwargs):
        calls.append(args)
        raise ModelExecutionBusy()

    monkeypatch.setattr("app.runtime.model_execution.run_model_process", busy)
    return calls


@pytest.mark.parametrize("name,path,params", HEAVY)
def test_a_busy_engine_is_reported_once_with_no_server_side_retry_and_nothing_changes(with_sensitivity, busy_engine, name, path, params):
    env = with_sensitivity
    record = env.create()
    before = _everything(record)
    response = env.client.get(path, params={"project": record.project_code, **params}, headers=HDR)
    assert response.status_code == 429 and response.json()["code"] == "MODEL_BUSY"
    assert response.headers["Retry-After"] == "5" and response.headers["X-Finco-Model-Busy"] == "1"
    assert len(busy_engine) == 1                                                                   # one attempt: no automatic retry
    assert _everything(record) == before
