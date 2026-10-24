"""REAL HTTP/ASGI Model Run with V11 Stage 3 native ACTIVATION: authenticated HTMX POST /v2/workbook/run through the
full application (auth, ModelExecutor worker process, CAS commit, persistence, statements, Integrity digests, template
render) canonical / ``FINCO_NATIVE_V11_RUN=on`` alone / the production configuration (V10 Stage 1+2 + V11 Stage 3, both
build-ID pinned, exactly what the release transaction writes), each on a fresh byte-identical copy of a seeded database
and a fresh worker pool. Status, outcome header, rendered body, every row of every table, Run History and commit state
are identical to the canonical Run (volatile ids/timestamps/CSRF masked by the same closed, counted list as the shadow
route test); the activated feasible Run is proven native by the parent's own evidence, the rejected Run fails closed
identically."""
from __future__ import annotations

import json
import shutil

import pytest

from app.runtime import model_execution as me
from app.runtime import native_activation as na
from tests.test_native_shadow_http_route import OWNER, _db_rows, _mask, _volatile, seeds  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("stage3_artifacts")


def _production():
    from tools import native_release as rel
    return dict(line.split("=", 1) for line in rel.activation_text().splitlines() if line and not line.startswith("#"))


ARMS = {"off": {}, "v11": {na.ENV_V11_RUN: "on"}, "production": None}


def _post(seed, arm, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    seed_db, meta = seed
    target = tmp_path / f"run-{arm}.db"
    shutil.copyfile(seed_db, target)
    monkeypatch.setattr(db, "DB_PATH", str(target))
    for name in (na.ENV_RUN, na.ENV_BUILD_ID, na.ENV_V11_RUN, na.ENV_V11_BUILD_ID):
        monkeypatch.delenv(name, raising=False)
    for name, value in (_production() if ARMS[arm] is None else ARMS[arm]).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(na.ENV_KILL_SWITCH, str(tmp_path / "native_v10_run.disabled"))
    monkeypatch.setenv(na.ENV_V11_KILL_SWITCH, str(tmp_path / "native_v11_run.disabled"))
    na._reset_for_tests()
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="process", concurrency=1)))
    with TestClient(main_web.app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        assert client.get("/v2/workbook", params={"project": meta["project_code"]}).status_code == 200
        ws = get_workspace_state(OWNER, meta["project_id"])
        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        ident = assemble_consistent_for_get(user_id=OWNER, project_id=meta["project_id"],
                                            workbook_version=pis.workbook_version)
        resp = client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                           data={"project": meta["project_code"], "workbook_version": pis.workbook_version,
                                 "content_hash": ident.composite_hash})
        history = get_run_history(OWNER, meta["project_id"])
        committed = bool(get_workspace_state(OWNER, meta["project_id"]).last_runtime_snapshot_id)
    assert me.reset_model_executor_for_tests(None) == []
    volatile, bound = _volatile(target)
    volatile += [h.history_id for h in history] + [h.runtime_snapshot_id for h in history] + [str(h.ran_at) for h in history]
    body, body_masks = _mask(resp.text, volatile)
    db_text, db_masks = _mask(json.dumps(_db_rows(target), sort_keys=True), volatile)
    db_sorted = json.dumps({t: sorted(v) for t, v in json.loads(db_text).items()}, sort_keys=True)
    return {"status": resp.status_code, "outcome_header": resp.headers.get("X-Finco-Run-Outcome"), "body": body,
            "db": db_sorted, "masks": {"body": body_masks, "db": db_masks}, "bound": bound,
            "history": len(history), "committed": committed, "native": na.snapshot()}


@pytest.mark.parametrize("kind", ["feasible", "rejected"])
def test_http_model_run_identical_with_v11_off_alone_and_in_production(seeds, kind, tmp_path, monkeypatch):  # noqa: F811
    runs = {arm: _post(seeds[kind], arm, tmp_path, monkeypatch) for arm in ARMS}
    off = runs["off"]
    assert off["status"] == 200 and off["bound"]["failed"] == 0 and off["native"]["totals"] == {}
    if kind == "feasible":
        assert off["committed"] and off["history"] == 1 and off["bound"]["verified"] > 0
    else:
        assert off["outcome_header"] == "FAILED" and not off["committed"] and off["history"] == 0
    for arm in ("v11", "production"):
        run = runs[arm]
        for field in ("status", "outcome_header", "body", "db", "masks", "bound", "history", "committed"):
            assert run[field] == off[field], (arm, field)
        if kind == "feasible":
            last = run["native"]["last_run"]
            assert run["native"]["totals"]["v11_runs_with_native_models"] == 1, run["native"]
            assert last["v11"]["native_models"] > 0 and last["v11"]["loader_reason"] is None
            assert (last["stage2"] is True) == (arm == "production")
