"""SC-03: input freshness, engine currency and Run Integrity are independent, additive Run status dimensions."""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import dataclasses
import json
import re

import pytest

from app.workbook import runtime_authority as RA
from app.workbook.runtime_authority import EngineCurrency, RunContext
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

OWNER = "decision-user"


def dims(**kw):
    base = dict(run_context=RunContext.LAST_RUN, input_freshness="CURRENT", integrity="PASS",
                identity={"engine_version": "eng_v1"}, current_engine="eng_v1")
    base.update(kw)
    return RA.resolve_run_status_dimensions(**base)


# ───────────────────────────── pure contract ─────────────────────────────
def test_current_engine_only_when_persisted_identity_equals_running_engine():
    d = dims()
    assert d.engine.state is EngineCurrency.CURRENT_ENGINE and d.engine.persisted_engine_version == "eng_v1"


def test_engine_superseded_only_when_a_persisted_identity_is_known_and_differs():
    d = dims(identity={"engine_version": "eng_v0"})
    assert d.engine.state is EngineCurrency.ENGINE_SUPERSEDED
    assert (d.engine.persisted_engine_version, d.engine.current_engine_version) == ("eng_v0", "eng_v1")


@pytest.mark.parametrize("identity,replay,history", [
    (None, None, None), ({}, None, None), ({"engine_version": "NOT_AVAILABLE"}, None, None),
    ({"engine_version": ""}, {"engine_version": None}, ""), ({"engine_version": None}, None, "unknown"),
])
def test_old_run_without_engine_identity_is_unknown_never_inferred(identity, replay, history):
    d = dims(identity=identity, replay_metadata=replay, history_engine_version=history)
    assert d.engine.state is EngineCurrency.ENGINE_IDENTITY_UNKNOWN
    assert d.engine.persisted_engine_version is None and d.engine.reason == "NO_ENGINE_IDENTITY_PERSISTED"


def test_conflicting_persisted_engine_identities_fail_closed_to_unknown():
    d = dims(identity={"engine_version": "eng_v1"}, replay_metadata={"engine_version": "eng_v0"})
    assert d.engine.state is EngineCurrency.ENGINE_IDENTITY_UNKNOWN and d.engine.reason == "CONFLICTING_PERSISTED_ENGINE_IDENTITY"


def test_history_column_alone_can_prove_identity_and_agreeing_sources_are_accepted():
    assert dims(identity=None, history_engine_version="eng_v1").engine.state is EngineCurrency.CURRENT_ENGINE
    agree = dims(identity={"engine_version": "eng_v1"}, replay_metadata={"engine_version": "eng_v1"}, history_engine_version="eng_v1")
    assert agree.engine.state is EngineCurrency.CURRENT_ENGINE


def test_dimensions_are_independent_of_each_other():
    cases = [("STALE", "PASS", "eng_v1"), ("CURRENT", "PASS", "eng_v0"), ("CURRENT", "FAIL", "eng_v1"), ("STALE", "FAIL", "eng_v0"),
             ("NOT_RUN", "UNAVAILABLE", "eng_v1")]
    for freshness, integrity, engine in cases:
        d = dims(input_freshness=freshness, integrity=integrity, identity={"engine_version": engine})
        assert d.input_freshness == freshness and d.integrity == integrity
        assert (d.engine.state is EngineCurrency.CURRENT_ENGINE) == (engine == "eng_v1")


def test_integrity_fail_is_never_hidden_by_current_inputs_and_current_engine():
    d = dims(input_freshness="CURRENT", integrity="FAIL")
    assert d.integrity == "FAIL" and d.input_freshness == "CURRENT" and d.engine.state is EngineCurrency.CURRENT_ENGINE


def test_unrecognised_integrity_and_freshness_values_do_not_become_pass_or_current():
    d = dims(input_freshness="whatever", integrity="great")
    assert d.input_freshness is None and d.integrity == "UNAVAILABLE"


def test_governed_treatment_of_engine_superseded_is_off_until_d2(monkeypatch):
    assert RA.ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED is False
    assert dims(identity={"engine_version": "eng_v0"}).to_dict()["engine_superseded_treatment"] == "EVIDENCE_ONLY_D2_PENDING"
    monkeypatch.setattr(RA, "ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED", True)
    assert dims(identity={"engine_version": "eng_v0"}).to_dict()["engine_superseded_treatment"] == "GOVERNED"


def test_historical_context_is_a_separate_dimension():
    assert dims(run_context=RunContext.HISTORICAL_RUN).to_dict()["run_context"] == "HISTORICAL_RUN"
    assert dims().to_dict()["run_context"] == "LAST_RUN"


def test_existing_runtime_freshness_semantics_are_unchanged():
    ws = type("W", (), dict(last_runtime_snapshot_id="s", last_runtime_composite_hash="h", any_run_committed=True,
                            last_runtime_scenario_id=None, last_runtime_identity=None))()
    assert RA.resolve_runtime_freshness(ws, current_composite_hash="h").state is RA.RuntimeAuthorityState.CURRENT
    assert RA.resolve_runtime_freshness(ws, current_composite_hash="x").state is RA.RuntimeAuthorityState.STALE
    assert RA.resolve_runtime_freshness(ws, current_composite_hash=None).state is RA.RuntimeAuthorityState.STALE


# ───────────────────────────── real Runs, rendered page ─────────────────────────────
def get_outputs(env, record):
    r = env.client.get("/v2/workbook/outputs", params={"project": record.project_code})
    assert r.status_code == 200
    return r.text


def dim(page, name):
    m = re.search(r'data-testid="outputs-dim-%s" data-state="([^"]*)"' % name, page)
    assert m, name
    return m.group(1)


def test_real_run_current_inputs_current_engine_pass(env):
    record = env.create("solar")
    run(env, record)
    page = get_outputs(env, record)
    assert (dim(page, "context"), dim(page, "inputs"), dim(page, "engine")) == ("LAST_RUN", "CURRENT", "CURRENT_ENGINE")
    assert dim(page, "integrity") in ("PASS", "INCOMPLETE")


def test_current_inputs_on_a_run_with_proven_superseded_engine_stay_distinct(env, monkeypatch):
    record = env.create("solar")
    ws, _ = run(env, record)
    persisted = ws.last_runtime_identity["engine_version"]
    monkeypatch.setattr(RA, "current_engine_version", lambda: persisted + "_next")
    page = get_outputs(env, record)
    assert dim(page, "inputs") == "CURRENT"                       # unchanged inputs are still CURRENT ...
    assert dim(page, "engine") == "ENGINE_SUPERSEDED"            # ... and the engine is proven superseded
    assert 'data-superseded-treatment="EVIDENCE_ONLY_D2_PENDING"' in page
    assert "ENGINE SUPERSEDED" not in page and "Recorded engine" in page    # no governed treatment before D2
    monkeypatch.setattr(RA, "ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED", True)
    governed = get_outputs(env, record)
    assert "ENGINE SUPERSEDED" in governed and dim(governed, "inputs") == "CURRENT"


def test_stale_inputs_remain_distinct_from_engine_currency(env):
    record = env.create("solar")
    run(env, record)
    from tests.test_model_decision_workspace_v2 import tokens
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    r = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, sheet_id="project_setup", field_id="project_setup.technical.p50_hours", value="1700", **tokens(page)))
    assert r.status_code == 200
    out = get_outputs(env, record)
    assert (dim(out, "inputs"), dim(out, "engine")) == ("STALE", "CURRENT_ENGINE")


def test_old_run_without_engine_identity_renders_unknown(env):
    from app.v2.output_workspace_projection import build_output_workspace
    from app.workbook.runtime_authority import resolve_runtime_freshness
    record = env.create("solar")
    ws, rr = run(env, record)
    old = dataclasses.replace(ws, last_runtime_identity={k: v for k, v in (ws.last_runtime_identity or {}).items() if k != "engine_version"},
                              replay_metadata=None)
    out = build_output_workspace(runtime_result=rr, workspace=old, freshness=resolve_runtime_freshness(
        old, current_composite_hash=old.last_runtime_composite_hash), last_run_scenario="Base")
    d = out["status_dimensions"]
    assert d["engine_currency"] == "ENGINE_IDENTITY_UNKNOWN" and d["engine_persisted_version"] is None
    assert d["input_freshness"] == "CURRENT"                       # unknown engine does not change input freshness


def test_integrity_fail_is_shown_with_current_inputs(env):
    from app.v2.output_workspace_projection import build_output_workspace
    from app.workbook.runtime_authority import resolve_runtime_freshness
    record = env.create("solar")
    ws, rr = run(env, record)
    report = {"overall": "FAIL", "counts": {"FAIL": 1}, "checks": [{"check_id": "X", "title": "Synthetic failure", "status": "FAIL", "reason_code": "R"}]}
    out = build_output_workspace(runtime_result=rr, workspace=ws, freshness=resolve_runtime_freshness(
        ws, current_composite_hash=ws.last_runtime_composite_hash), last_run_scenario="Base", integrity_report=report)
    d = out["status_dimensions"]
    assert (d["input_freshness"], d["integrity"]) == ("CURRENT", "FAIL")


def test_status_projection_is_read_only_and_never_changes_the_committed_run(env):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    run(env, record)
    before_ws = get_workspace_state(OWNER, record.project_id)
    before_hist = [h.to_dict() for h in get_run_history(OWNER, record.project_id)]
    for _ in range(2):
        get_outputs(env, record)
    after_ws = get_workspace_state(OWNER, record.project_id)
    assert json.dumps(after_ws.last_runtime_summary, sort_keys=True, default=str) == json.dumps(before_ws.last_runtime_summary, sort_keys=True, default=str)
    assert after_ws.last_runtime_snapshot_id == before_ws.last_runtime_snapshot_id and after_ws.last_runtime_identity == before_ws.last_runtime_identity
    assert [h.to_dict() for h in get_run_history(OWNER, record.project_id)] == before_hist


def test_get_never_executes_the_engine(env, monkeypatch):
    from app.services import production_financial_authority as P
    record = env.create("solar")
    run(env, record)
    monkeypatch.setattr(P, "run_clean_production", lambda *a, **k: pytest.fail("GET executed the engine"))
    get_outputs(env, record)
