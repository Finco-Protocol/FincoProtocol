"""REAL HTTP/ASGI Model Run with V10 native ACTIVATION: authenticated HTMX POST /v2/workbook/run through the full
application (auth, ModelExecutor worker process, CAS commit, persistence, template render) with
``FINCO_NATIVE_V10_RUN`` off / ``stage1`` / ``stage1+2``, each on a fresh byte-identical copy of a seeded database and a
fresh worker pool. Status, outcome header, rendered body, every row of every table, Run History and commit state are
identical to the canonical Run (volatile ids/timestamps/CSRF masked by the same closed, counted list as the shadow
route test); the activated feasible Run is proven native by the parent's own evidence, the rejected Run fails closed
identically."""
from __future__ import annotations

import json
import shutil

import pytest

from app.runtime import model_execution as me
from app.runtime import native_activation as na
from tests.test_native_shadow_http_route import OWNER, _db_rows, _mask, _volatile, seeds  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("native_artifacts")


def _post(seed, mode, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    seed_db, meta = seed
    target = tmp_path / f"run-{mode}.db"
    shutil.copyfile(seed_db, target)
    monkeypatch.setattr(db, "DB_PATH", str(target))
    monkeypatch.setenv(na.ENV_RUN, mode)
    monkeypatch.setenv(na.ENV_KILL_SWITCH, str(tmp_path / "native_v10_run.disabled"))
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
def test_http_model_run_identical_with_activation_off_and_on(seeds, kind, tmp_path, monkeypatch):  # noqa: F811
    runs = {mode: _post(seeds[kind], mode, tmp_path, monkeypatch) for mode in ("off", "stage1", "stage1+2")}
    off = runs["off"]
    assert off["status"] == 200 and off["bound"]["failed"] == 0 and off["native"]["totals"] == {}
    if kind == "feasible":
        assert off["committed"] and off["history"] == 1 and off["bound"]["verified"] > 0
    else:
        assert off["outcome_header"] == "FAILED" and not off["committed"] and off["history"] == 0
    for mode in ("stage1", "stage1+2"):
        run = runs[mode]
        for field in ("status", "outcome_header", "body", "db", "masks", "bound", "history", "committed"):
            assert run[field] == off[field], (mode, field)
        if kind == "feasible":
            last = run["native"]["last_run"]
            assert run["native"]["totals"]["runs_with_native_calls"] == 1, run["native"]
            assert last["native_solves"] > 0 and (last["stage2_native_calls"] > 0) == (mode == "stage1+2")
