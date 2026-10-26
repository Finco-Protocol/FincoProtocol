"""RC-UX-B: read-only, same-Run evidence and minimal immutable History summaries."""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rc-ux-b.db"))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_workspace_router import router as react_router
    from app.v2.router import router as v2_router
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_router, prefix="/v2")
    record = create_reference_seeded_project(user_id="rc-ux-b", requested_name="UX B", capacity_mw=16,
                                             template_source="generic_solar_reference")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="rc-ux-b", username="admin"))
        def get(surface):
            response = client.get(f"/v2/model-react/{surface}", params={"project": record.project_code})
            assert response.status_code == 200, response.text
            return response.json()
        def run():
            page = client.get("/v2/workbook", params={"project": record.project_code})
            from bs4 import BeautifulSoup
            form = BeautifulSoup(page.text, "html.parser").select_one("#v2-canonical-run-form")
            assert form is not None
            tokens = {field["name"]: field.get("value", "") for field in form.select("input[name]")}
            response = client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                                   data={"project": record.project_code, **tokens})
            assert response.status_code == 200, response.text
            assert response.headers.get("X-Finco-Run-Outcome") != "FAILED"
        yield SimpleNamespace(client=client, record=record, get=get, run=run)
    reset_model_executor_for_tests()


def test_current_integrity_and_diagnostics_share_committed_identity(env):
    env.run()
    workspace, statements, diagnostics, trust = [env.get(x) for x in ("workspace", "statements", "diagnostics", "trust")]
    assert workspace["freshness"]["state"] == diagnostics["run_state"] == trust["run_state"] == "CURRENT"
    assert workspace["integrity"]["status"] == statements["integrity"]["status"]
    assert workspace["integrity"]["status"] == diagnostics["integrity"]["overall"] == trust["integrity"]["overall"]
    snapshot = workspace["identity"]["snapshot_id"]
    assert diagnostics["insight"]["identity"]["snapshot_id"] == snapshot
    assert trust["identity"]["snapshot_id"] == snapshot
    assert diagnostics["integrity"]["run_identity"]["snapshot_id"] == snapshot
    assert diagnostics["diagnostics"]["checks"], "CURRENT must evaluate actual persisted checks"


def test_trust_get_never_executes_reference_or_signing_and_does_not_mutate(env, monkeypatch):
    env.run()
    from app.ui import trust_pack
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from dataclasses import asdict
    before_ws = asdict(get_workspace_state("rc-ux-b", env.record.project_id))
    before_history = [x.to_dict() for x in get_run_history("rc-ux-b", env.record.project_id)]
    def forbidden(*args, **kwargs):
        pytest.fail("GET must not execute a regression, issue a certificate, or run an engine")
    monkeypatch.setattr(trust_pack, "build_validation_fragment", forbidden)
    monkeypatch.setattr(trust_pack, "build_certificate_fragment", forbidden)
    monkeypatch.setattr(trust_pack, "issue_run_certificate", forbidden)
    from app.api.v1_1 import institutional
    monkeypatch.setattr(institutional, "get_institutional_validation", forbidden)
    for _ in range(2):
        payload = env.get("trust")
        assert payload["validation"]["state"] == "DEFERRED"
        assert "not validation of this Working Copy" in payload["validation"]["scope"]
        assert payload["certificate"]["state"] == "DEFERRED"
        assert payload["certificate"]["not_verify"] is True
    assert asdict(get_workspace_state("rc-ux-b", env.record.project_id)) == before_ws
    assert [x.to_dict() for x in get_run_history("rc-ux-b", env.record.project_id)] == before_history


def test_history_summary_uses_canonical_fields_without_financial_payload(env):
    env.run()
    from app.persistence.run_history_repository import get_run_history
    original = get_run_history("rc-ux-b", env.record.project_id)[0].to_dict()
    entry = env.get("runs")["runs"][0]
    assert entry["runtime_snapshot_id"] == original["runtime_snapshot_id"]
    assert entry["runtime_origin"] == original["runtime_origin"]
    assert entry["composite_hash"] == original["composite_hash"]
    assert entry["active_scenario_name"] == original["active_scenario_name"]
    assert set(entry) == {"history_id", "project_code", "runtime_snapshot_id", "runtime_origin", "ran_at",
                          "engine_version", "workbook_version", "active_scenario_id", "active_scenario_name",
                          "last_runtime_scenario_id", "composite_hash"}
    assert not {"user_id", "financial_statements", "runtime_summary", "debt_schedule", "last_runtime_identity"} & entry.keys()


def test_not_run_stays_unavailable_without_deferred_actions(env):
    payload = env.get("trust")
    assert payload["identity"] is None and payload["integrity"] is None
    assert payload["run_state"] == "NOT_RUN"
    for key in ("certificate", "validation"):
        assert payload[key]["state"] == "UNAVAILABLE" and payload[key]["load_url"] is None
    diagnostics = env.get("diagnostics")
    assert diagnostics["run_state"] == "NOT_RUN"
    assert diagnostics["diagnostics"]["state"] == "NOT_RUN"


@pytest.mark.parametrize("surface", ["runs", "trust", "diagnostics"])
def test_evidence_surfaces_preserve_owner_non_disclosure(env, surface):
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="stranger", username="stranger"))
    response = env.client.get(f"/v2/model-react/{surface}", params={"project": env.record.project_code})
    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.parametrize("verdict", ["FAIL", "INCOMPLETE"])
def test_nonpassing_integrity_is_preserved_everywhere(env, monkeypatch, verdict):
    env.run()
    from app.api.v1_1 import institutional
    original = institutional.get_run_integrity_checks
    def report(*args, **kwargs):
        state, evidence = original(*args, **kwargs)
        return state, {**evidence, "overall": verdict}
    monkeypatch.setattr(institutional, "get_run_integrity_checks", report)
    for surface in ("workspace", "statements"):
        assert env.get(surface)["integrity"]["status"] == verdict
    for surface in ("diagnostics", "trust"):
        assert env.get(surface)["integrity"]["overall"] == verdict


def test_stale_diagnostics_keep_committed_snapshot_not_active_working_copy(env):
    env.run()
    snapshot = env.get("workspace")["identity"]["snapshot_id"]
    fields = env.get("fields/project_setup")
    field = next(x for x in fields["fields"] if x["binding_label"] == "bound" and x["field_id"] == "project_setup.identity.project_name")
    response = post_valid_mutation(env.client, "/v2/workbook/update", data={
        "project": env.record.project_code, "field_id": field["field_id"], "value": "Changed Working Copy",
        "workbook_version": fields["save"]["workbook_version"], "content_hash": fields["save"]["content_hash"],
        "csrf_token": fields["save"]["csrf_token"]}, follow_redirects=False)
    assert response.status_code == 303 and "v2_err" not in response.headers["location"]
    diagnostics = env.get("diagnostics")
    assert diagnostics["run_state"] == "STALE"
    assert diagnostics["insight"]["identity"]["snapshot_id"] == snapshot
    assert diagnostics["insight"]["terms_bound"] is False
    assert env.get("trust")["identity"]["snapshot_id"] == snapshot


@pytest.mark.parametrize("surface", ["workspace", "diagnostics", "trust"])
def test_changed_context_fails_closed(env, monkeypatch, surface):
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    def changed(self):
        raise PostRunContextChanged("changed")
    monkeypatch.setattr(PostRunRequestContext, "validate_current", changed)
    response = env.client.get(f"/v2/model-react/{surface}", params={"project": env.record.project_code})
    assert response.status_code == 503
    assert response.json()["ok"] is False
