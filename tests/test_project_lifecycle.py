"""WF03 independent disposable-DB lifecycle, authorization and final-write oracles."""
from contextlib import contextmanager
import json
import sqlite3
import uuid

import pytest

from app.persistence import db
from app.persistence.project_lifecycle_repository import (
    LifecycleError, admission_scope, status, transition,
)
from app.persistence.projects_repository import get_project_by_code


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf03.sqlite"))
    db.init_db()
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id="wf03-owner", template_source="generic_wind_reference",
                                          requested_name="WF03", capacity_mw=40)


def command(rec, action="ARCHIVE", version=0, key=None):
    return transition(rec.user_id, rec.project_code, action,
                      {"request_id": key or uuid.uuid4().hex, "expected_archived": action == "UNARCHIVE",
                       "lifecycle_version": version})


def financial_state(rec):
    with db.get_cursor() as cur:
        return {table: [tuple(row) for row in cur.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY rowid", (rec.project_id,))]
                for table in ("workspace_states", "scenarios", "capex_sub_lines", "opex_sub_lines", "model_run_history")}


def test_archive_restore_are_financially_neutral_and_receipt_replay_cannot_restore_old_state(world):
    rec = world
    before = financial_state(rec)
    first = command(rec)
    assert first["current"]["archived"] is True and first["current"]["lifecycle_version"] == 1
    second = command(rec, "UNARCHIVE", 1)
    assert second["current"]["archived"] is False and second["current"]["lifecycle_version"] == 2
    replay = command(rec, key=first["receipt"]["request_id"])
    assert replay["replayed"] and replay["receipt"] == first["receipt"]
    assert replay["current"] == second["current"]
    assert financial_state(rec) == before
    assert status(rec.user_id, rec.project_code, first["receipt"]["request_id"])["receipt"] == first["receipt"]
    with pytest.raises(LifecycleError, match="LIFECYCLE_KEY_REUSED"):
        command(rec, "UNARCHIVE", 1, first["receipt"]["request_id"])
    with pytest.raises(LifecycleError, match="LIFECYCLE_STALE"):
        command(rec)


def test_tenant_and_body_scope(world):
    with pytest.raises(LifecycleError) as exc:
        transition("other", world.project_code, "ARCHIVE", {"request_id": uuid.uuid4().hex, "expected_archived": False, "lifecycle_version": 0})
    assert exc.value.status == 404
    for body in ({}, {"request_id": "a"*32, "expected_archived": 0, "lifecycle_version": 0},
                 {"request_id": "A"*32, "expected_archived": False, "lifecycle_version": 0},
                 {"request_id": "a"*32, "expected_archived": False, "lifecycle_version": True},
                 {"request_id": "a"*32, "expected_archived": False, "lifecycle_version": -1}):
        with pytest.raises(LifecycleError) as exc:
            transition(world.user_id, world.project_code, "ARCHIVE", body)
        assert exc.value.status == 422


@pytest.mark.parametrize("table,column", [("workspace_states", "dirty"), ("scenarios", "archived"),
                                        ("capex_sub_lines", "is_active"), ("opex_sub_lines", "is_active")])
def test_every_existing_writer_is_fenced_at_sql_boundary_even_after_aba(world, table, column):
    rec = world
    # No-key/Legacy and keyed Run final writers share this same admission epoch
    # and SQLite boundary; neither route visibility nor composite CAS is the oracle.
    with admission_scope():
        get_project_by_code(rec.user_id, rec.project_code)
        command(rec)
        before = financial_state(rec)
        with db.get_cursor() as cur:
            count = cur.execute(f"SELECT count(*) FROM {table} WHERE project_id=?", (rec.project_id,)).fetchone()[0]
        if count == 0:
            assert table == "scenarios"  # scenario creation INSERT is covered separately
        else:
            with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
                with db.get_cursor() as cur:
                    cur.execute(f"UPDATE {table} SET {column}={column} WHERE project_id=?", (rec.project_id,))
        command(rec, "UNARCHIVE", 1)
        # Another lookup must not silently refresh the old admission.
        get_project_by_code(rec.user_id, rec.project_code)
        if count:
            with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
                with db.get_cursor() as cur:
                    cur.execute(f"UPDATE {table} SET {column}={column} WHERE project_id=?", (rec.project_id,))
        assert financial_state(rec) == before
    with admission_scope():
        get_project_by_code(rec.user_id, rec.project_code)
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET dirty=dirty WHERE project_id=?", (rec.project_id,))


def test_fault_in_event_insert_rolls_back_project_and_receipt(world):
    with db.get_cursor() as cur:
        cur.execute("CREATE TRIGGER inject_wf03_fault BEFORE INSERT ON project_lifecycle_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        command(world)
    rec = get_project_by_code(world.user_id, world.project_code)
    assert rec.archived is False and rec.lifecycle_version == 0
    with db.get_cursor() as cur:
        assert cur.execute("SELECT count(*) FROM project_lifecycle_events").fetchone()[0] == 0


def test_ledger_immutable_and_generic_project_upsert_cannot_unarchive(world):
    command(world)
    with pytest.raises(sqlite3.IntegrityError, match="WF03_IMMUTABLE_RECEIPT"):
        with db.get_cursor() as cur:
            cur.execute("DELETE FROM project_lifecycle_events")
    from app.persistence.projects_repository import save_project
    with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
        save_project(user_id=world.user_id, project_code=world.project_code,
                     project_name=world.project_name, source_project_template=world.source_project_template)
    assert get_project_by_code(world.user_id, world.project_code).archived


def test_https_operation_tokens_and_status_owner_scope(world):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.workbook.financing_csrf import issue_token
    from types import SimpleNamespace
    import main_web
    client = TestClient(main_web.app, base_url="https://testserver")
    path = f"/library/projects/{world.project_code}/archive"
    body = {"request_id": uuid.uuid4().hex, "expected_archived": False, "lifecycle_version": 0}
    assert client.post(path, json=body).status_code == 401
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=world.user_id, username="admin"))
    req = SimpleNamespace(cookies=dict(client.cookies), state=SimpleNamespace())
    assert client.post(path, json=body).status_code == 403
    wrong = issue_token(req, world.project_code, purpose="wf03-lifecycle:UNARCHIVE")
    assert client.post(path, json=body, headers={"X-CSRF-Token": wrong}).status_code == 403
    token = issue_token(req, world.project_code, purpose="wf03-lifecycle:ARCHIVE")
    assert client.post(path, json=body, headers={"X-CSRF-Token": token, "Origin": "https://evil.test"}).status_code == 403
    result = client.post(path, json=body, headers={"X-CSRF-Token": token, "Origin": "https://testserver"})
    assert result.status_code == 200, result.text
    assert client.post(path, json=body, headers={"X-CSRF-Token": token}).json()["replayed"]
    read = f"/library/projects/{world.project_code}/lifecycle/status?request_id={body['request_id']}"
    assert client.get(read).json()["outcome"] == "COMMITTED"
    client.cookies.set(COOKIE_NAME, create_session_token(user_id="stranger", username="admin"))
    assert client.get(read).status_code == 404


from tests.test_model_decision_workspace_v2 import env as run_env  # real engine/SQLite fixture


@pytest.mark.parametrize("keyed", [False, True], ids=["unkeyed", "keyed"])
@pytest.mark.parametrize("restore", [False, True], ids=["archive", "archive-restore-ABA"])
def test_real_v2_run_cannot_commit_after_archive_wins(run_env, monkeypatch, keyed, restore):
    import concurrent.futures
    import threading
    from tests.test_d029_run_idempotency_http import run_form, post, intents
    from tests.test_model_credit_decision_v3_real_runs import history
    import app.api.project_runner as runner
    record=run_env.create("solar")
    form=run_form(run_env,record,str(uuid.uuid4()) if keyed else None)
    entered, release=threading.Event(),threading.Event()
    original=runner.run_project
    def paused(*args,**kwargs):
        entered.set()
        assert release.wait(45), "race controller never released engine"
        return original(*args,**kwargs)
    monkeypatch.setattr(runner,"run_project",paused)
    before=financial_state(record)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(post,run_env,form)
        try:
            assert entered.wait(45), "Run never reached real engine admission"
            command(record)
            if restore: command(record,"UNARCHIVE",1)
        finally:
            release.set()
        response=result.result(timeout=90)
    assert response.status_code in (200,303,409)
    assert financial_state(record)==before
    assert history(record)==[]
    rows=intents(record)
    assert not rows or all(row["state"]!="COMMITTED" and row["history_id"] is None for row in rows)


def test_complete_committed_run_replays_after_archive_without_last_run_overwrite(run_env):
    from tests.test_d029_run_idempotency_http import run_form, post
    record=run_env.create("solar")
    form=run_form(run_env,record,str(uuid.uuid4()))
    first=post(run_env,form)
    assert first.status_code==200 and first.json()["outcome"]=="COMMITTED",first.text
    before=financial_state(record)
    command(record)
    replay=post(run_env,form)
    assert replay.status_code==200 and replay.json()["outcome"]=="REPLAYED",replay.text
    assert replay.json()["history_id"]==first.json()["history_id"]
    assert financial_state(record)==before


def test_database_guard_requires_current_request_actor_inside_write_transaction(world):
    with admission_scope("another-owner"):
        # Even an accidentally mis-scoped service lookup cannot authorize this
        # actor's financial write, independently of the HTTP route precheck.
        get_project_by_code(world.user_id,world.project_code)
        with pytest.raises(sqlite3.IntegrityError,match="WF03_LIFECYCLE_CONFLICT"):
            with db.get_cursor() as cur:
                cur.execute("UPDATE workspace_states SET dirty=dirty WHERE project_id=?",(world.project_id,))


def test_repeatable_migration_rejects_a_corrupted_same_name_write_fence(world):
    from app.persistence.project_lifecycle_repository import ensure_schema
    conn=db.get_connection()
    try:
        ensure_schema(conn)
        conn.execute("DROP TRIGGER temp.wf03_workspace_states_update")
        conn.execute("CREATE TEMP TRIGGER wf03_workspace_states_update BEFORE UPDATE ON workspace_states BEGIN SELECT 1; END")
        with pytest.raises(LifecycleError,match="LIFECYCLE_SCHEMA_MISMATCH"):
            ensure_schema(conn)
    finally:
        conn.close()


def test_library_all_filters_counts_and_unicode_search_precede_page_for_over_1000_projects(world,monkeypatch):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    import main_web
    monkeypatch.setenv("FINCO_MODEL_REACT_V1","1")
    with db.get_cursor() as cur:
        project=dict(cur.execute("SELECT * FROM projects WHERE project_id=?",(world.project_id,)).fetchone())
        workspace=dict(cur.execute("SELECT * FROM workspace_states WHERE project_id=?",(world.project_id,)).fetchone())
        for i in range(1001):
            pid,code=uuid.uuid4().hex,f"wf03-library-{i:04}"
            p={**project,"project_id":pid,"project_code":code,
               "project_name":"Rare ß match" if i==0 else f"Other {i:04}",
               "updated_at":"2000-01-01T00:00:00+00:00" if i==0 else "2026-10-29T00:00:00+00:00"}
            cur.execute(f"INSERT INTO projects ({','.join(p)}) VALUES ({','.join('?' for _ in p)})",tuple(p.values()))
            w={**workspace,"workspace_id":uuid.uuid4().hex,"project_id":pid,"project_code":code,"updated_at":p["updated_at"]}
            cur.execute(f"INSERT INTO workspace_states ({','.join(w)}) VALUES ({','.join('?' for _ in w)})",tuple(w.values()))
        expected=cur.execute("SELECT count(*) FROM projects WHERE user_id=? AND archived=0",(world.user_id,)).fetchone()[0]
    client=TestClient(main_web.app,base_url="https://testserver",
                      cookies={COOKIE_NAME:create_session_token(user_id=world.user_id,username="admin")})
    result=client.get("/v2/model-react/my-projects",params={"search":"RARE SS","sort":"name","page":99999})
    assert result.status_code==200,result.text
    payload=result.json()
    assert payload["total"]==1 and payload["projects"][0]["name"]=="Rare ß match"
    assert payload["page"]==1 and payload["total_all"]==expected and expected>1000
    assert payload["limits"]=={"considered":expected,"capped":False}
    assert sum(row["count"] for row in payload["facets"]["technologies"])==expected
    own=client.get("/v2/model-react/my-projects",params={"sort":"name","page":2}).json()
    assert own["total"]==expected and len(own["projects"])==12


@pytest.mark.parametrize("creation",["CREATING","ABANDONED",None])
def test_legacy_archives_are_quarantined_not_user_restorable(world,creation):
    from app.persistence.project_lifecycle_repository import ensure_schema
    conn=db.get_connection()
    try:
        # Historical pre-migration fixture, not a product mutation action.
        conn.create_function("wf03_lifecycle_command",0,lambda:1)
        metadata={"create_request":{"state":creation}} if creation else {}
        conn.execute("UPDATE projects SET archived=1,replay_metadata_json=?,lifecycle_archive_origin=NULL WHERE project_id=?",
                     (json.dumps(metadata),world.project_id))
        conn.create_function("wf03_lifecycle_command",0,lambda:0)
        ensure_schema(conn)
        row=conn.execute("SELECT * FROM projects WHERE project_id=?",(world.project_id,)).fetchone()
        assert row["lifecycle_archive_origin"]==("CREATE_ABANDONED" if creation else "LEGACY_UNKNOWN")
    finally: conn.close()
    with pytest.raises(LifecycleError,match="LIFECYCLE_NOT_ELIGIBLE"):
        command(world,"UNARCHIVE",0)
