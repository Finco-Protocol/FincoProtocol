"""REAL HTTP/ASGI route with the dormant V10 shadow: authenticated HTMX POST /v2/workbook/run through the
full application (auth, ModelExecutor process pool, persistence, template render) with the shadow OFF,
``stage1`` and ``stage2``, each on a fresh byte-identical copy of a seeded database and a fresh worker pool.

Identical across arms: HTTP status, outcome header, rendered body, every row of every table, Run History
count, commit state. Volatile tokens are masked by an explicit, closed list and the NUMBER of masked
tokens must be identical across arms (masking can never hide a difference):
  * Run / snapshot ids and ran_at (also ids of reference rows written by the app's startup bootstrap);
  * timestamps incl. compact ``YYYYMMDDTHHMMSSffffffZ`` and the minute-resolution displays of ran_at;
  * the per-request CSRF token;
  * snapshot-bound evidence digests (sha256 over evidence that includes ``binding.snapshot_id``), each
    RECOMPUTED from its unsigned content and required to verify before it is treated as volatile.
The shadow records MATCH for the feasible and for the rejected (fail-closed) Run.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3

import pytest

from app.runtime import model_execution as me
from app.runtime import native_shadow as ns

pytestmark = pytest.mark.usefixtures("native_artifacts")

OWNER = "v10-http-shadow"
TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\+00:00|Z)?|\d{8}T\d{6}(?:\.?\d+)?(?:\+0000|Z)?"
                r"|\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}, \d{2}:\d{2}\b")
CSRF = re.compile(r'(csrf[_-]token"?\s*(?:value|content)?\s*[=:]\s*")[^"]+(")')


def _seed(tmp_path_factory, name, template, capacity, factory_override=None):
    from app import project_factories as pf
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project

    path = tmp_path_factory.mktemp("seed") / f"seed-{name}.db"
    previous = db.DB_PATH
    db.DB_PATH = str(path)
    attr = f"create_generic_{template}_reference"
    real = getattr(pf, attr)
    try:
        db.init_db()
        if factory_override is not None:
            setattr(pf, attr, lambda *a, **k: factory_override())
        rec = create_reference_seeded_project(user_id=OWNER, requested_name=f"V10 {name}",
                                              template_source=f"generic_{template}_reference", capacity_mw=capacity)
    finally:
        setattr(pf, attr, real)
        db.DB_PATH = previous
    con = sqlite3.connect(path)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    return path, {"project_id": rec.project_id, "project_code": rec.project_code}


@pytest.fixture(scope="module")
def seeds(tmp_path_factory):
    from tools import v9p2a_odr_acceptance as acc
    return {"feasible": _seed(tmp_path_factory, "reference-solar", "solar", 64.0),
            "rejected": _seed(tmp_path_factory, "W25-factory-seed", "wind", 25.0, acc.cases()["W25"][0])}


def _db_rows(path):
    con = sqlite3.connect(path)
    out = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        out[t] = [json.dumps(list(r), default=str) for r in con.execute(f"SELECT * FROM '{t}'")]
    con.close()
    return out


def _volatile(path):
    from app.model_v2.acquisition.evidence import _canonical

    con = sqlite3.connect(path)
    vals = [v for row in con.execute("SELECT history_id, runtime_snapshot_id, ran_at FROM model_run_history") for v in row]
    vals += [v for (v,) in con.execute("SELECT last_runtime_snapshot_id FROM workspace_states")]
    bound = {"verified": 0, "failed": 0}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("binding"), dict) and "snapshot_id" in o["binding"] and isinstance(o.get("digest"), str):
                unsigned = {k: v for k, v in o.items() if k != "digest"}
                if hashlib.sha256(_canonical(unsigned).encode()).hexdigest() == o["digest"]:
                    bound["verified"] += 1
                    vals.append(o["digest"])
                else:
                    bound["failed"] += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for table in ("model_run_history", "workspace_states"):
        for row in con.execute(f"SELECT * FROM {table}"):
            for cell in row:
                if isinstance(cell, str) and cell[:1] in "{[" and "binding" in cell:
                    try:
                        walk(json.loads(cell))
                    except ValueError:
                        pass
    con.close()
    return [str(v) for v in vals if v], bound


def _mask(text, volatile):
    n = 0
    for v in sorted(set(volatile), key=len, reverse=True):
        n += text.count(v)
        text = text.replace(v, "<VOLATILE>")
    text, n_csrf = CSRF.subn(r"\1<CSRF>\2", text)
    text, n_ts = TS.subn("<TS>", text)
    return text, {"volatile": n, "csrf": n_csrf, "ts": n_ts}


def _post(seed, shadow, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    seed_db, meta = seed
    target = tmp_path / f"run-{shadow or 'off'}.db"
    shutil.copyfile(seed_db, target)
    monkeypatch.setattr(db, "DB_PATH", str(target))
    if shadow:
        monkeypatch.setenv(ns.ENV_SHADOW, shadow)
    else:
        monkeypatch.delenv(ns.ENV_SHADOW, raising=False)
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="process", concurrency=1)))
    records = []
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
        observer = me.get_model_executor().native_shadow_observer()
        if observer is not None:
            assert observer.drain(900)
            records = observer.records()
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
            "history": len(history), "committed": committed, "shadow": records}


@pytest.mark.parametrize("kind", ["feasible", "rejected"])
def test_http_route_identical_with_shadow_off_and_on(seeds, kind, tmp_path, monkeypatch):
    runs = {mode: _post(seeds[kind], mode, tmp_path, monkeypatch) for mode in (None, "stage1", "stage2")}
    off = runs[None]
    assert off["status"] == 200 and off["bound"]["failed"] == 0
    if kind == "feasible":
        assert off["committed"] and off["history"] == 1 and off["bound"]["verified"] > 0
    else:
        assert off["outcome_header"] == "FAILED" and not off["committed"] and off["history"] == 0
    for mode in ("stage1", "stage2"):
        run = runs[mode]
        for field in ("status", "outcome_header", "body", "db", "masks", "bound", "history", "committed"):
            assert run[field] == off[field], (mode, field)
        (record,) = run["shadow"]
        assert record["outcome"] == "MATCH", record
        assert record["canonical"]["kind"] == ("return" if kind == "feasible" else "raise")
        if kind == "feasible":
            assert record["native"]["native_solves"] > 0
            assert (record["native"]["stage2_native_calls"] > 0) == (mode == "stage2")
