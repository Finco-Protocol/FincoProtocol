"""FINCO45C (FINCO44-NEW-06 / C1-Q-11 / C3-E-04): WF03 workspace freshness fence.

Neon observed ``UPDATE workspace_states SET dirty=0`` succeeding through a DB handle while project/intent writes were
fenced. On every APPLICATION connection a TEMP trigger now refuses a dirty->clean transition or a replacement of the
committed runtime binding (``last_runtime_snapshot_id`` / ``last_runtime_composite_hash``) unless the statement runs
inside one of the authoritative writers (``save_workspace_state``, ``v2_atomic_run_commit``, ``select_scenario``).
Marking dirty, draft edits and inserts are unchanged. TEMP triggers are connection-local by design: an independent raw
SQLite connection (offline fixture/backup tooling, or anyone with OS write access to the file) is outside this
boundary, which the last test documents explicitly.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from app.persistence import db
from app.persistence.project_lifecycle_repository import admission_scope, workspace_freshness_writer
from app.persistence.workspace_repository import get_workspace_state, save_workspace_state

ERR = "WF03_WORKSPACE_FRESHNESS_AUTHORITY_REQUIRED"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf03_fresh.sqlite"))
    db.init_db()
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id="wf03-fresh-owner", template_source="generic_solar_reference",
                                          requested_name="WF03 Fresh", capacity_mw=40)


def _row(rec):
    with db.get_cursor() as cur:
        return dict(cur.execute("SELECT dirty, last_runtime_snapshot_id, last_runtime_composite_hash, draft_snapshot_json "
                                "FROM workspace_states WHERE project_id=?", (rec.project_id,)).fetchone())


def _make_dirty(rec):
    with db.get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET dirty=1 WHERE project_id=?", (rec.project_id,))   # always allowed
    assert _row(rec)["dirty"] == 1


def test_direct_dirty_clear_is_refused_on_an_application_connection(world):
    _make_dirty(world)
    with pytest.raises(sqlite3.IntegrityError, match=ERR):
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))
    assert _row(world)["dirty"] == 1                       # rolled back


@pytest.mark.parametrize("column,value", [("last_runtime_snapshot_id", "forged-snapshot"),
                                          ("last_runtime_composite_hash", "f" * 64)])
def test_direct_runtime_binding_forgery_is_refused(world, column, value):
    before = _row(world)
    with pytest.raises(sqlite3.IntegrityError, match=ERR):
        with db.get_cursor() as cur:
            cur.execute(f"UPDATE workspace_states SET {column}=? WHERE project_id=?", (value, world.project_id))
    assert _row(world) == before


def test_marking_dirty_and_draft_edits_and_no_op_writes_stay_allowed(world):
    with db.get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET dirty=dirty, updated_at=updated_at WHERE project_id=?",
                    (world.project_id,))
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=draft_snapshot_json WHERE project_id=?",
                    (world.project_id,))
    _make_dirty(world)
    with db.get_cursor() as cur:                           # dirty -> dirty is not a clean transition
        cur.execute("UPDATE workspace_states SET dirty=1 WHERE project_id=?", (world.project_id,))


def test_authoritative_writer_can_clean_and_the_capability_ends_with_the_call(world):
    _make_dirty(world)
    ws = get_workspace_state(world.user_id, world.project_id)
    save_workspace_state(user_id=ws.user_id, project_id=ws.project_id, project_code=ws.project_code,
                         active_scenario_id=ws.active_scenario_id, active_scenario_name=ws.active_scenario_name,
                         draft_snapshot=ws.draft_snapshot, saved_snapshot=ws.saved_snapshot,
                         last_runtime_snapshot=ws.last_runtime_snapshot, last_runtime_summary=ws.last_runtime_summary,
                         last_runtime_snapshot_id=ws.last_runtime_snapshot_id, last_runtime_origin=ws.last_runtime_origin,
                         dirty=False, governance_state=ws.governance_state, replay_metadata=ws.replay_metadata)
    assert _row(world)["dirty"] == 0
    _make_dirty(world)
    with pytest.raises(sqlite3.IntegrityError, match=ERR):  # no leaked capability after the writer returned
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))


def test_writer_failure_rolls_back_and_capability_is_reset(world):
    _make_dirty(world)

    @workspace_freshness_writer
    def failing_writer():
        with db.lifecycle_transaction():                   # the real transaction boundary (BEGIN IMMEDIATE)
            with db.get_cursor() as cur:
                cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))
            raise RuntimeError("injected after the clean statement")

    with pytest.raises(RuntimeError, match="injected"):
        failing_writer()
    assert _row(world)["dirty"] == 1                       # transaction rolled back
    with pytest.raises(sqlite3.IntegrityError, match=ERR):
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))


def test_shared_lifecycle_transaction_connection_reuse_is_still_fenced(world):
    _make_dirty(world)
    with pytest.raises(sqlite3.IntegrityError, match=ERR):
        with db.lifecycle_transaction():
            with db.get_cursor() as cur:
                cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))
    assert _row(world)["dirty"] == 1


def test_capability_does_not_leak_across_threads(world):
    _make_dirty(world)
    seen = {}
    started, release = threading.Event(), threading.Event()

    @workspace_freshness_writer
    def holder():
        started.set()
        release.wait(10)

    t = threading.Thread(target=holder)
    t.start()
    started.wait(10)
    try:
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))
    except sqlite3.IntegrityError as exc:
        seen["error"] = str(exc)
    finally:
        release.set()
        t.join(10)
    assert ERR in seen.get("error", "")


def test_archived_project_writer_still_hits_the_lifecycle_fence_first(world):
    """The freshness capability never widens WF03: an archived project stays immutable even for the writer."""
    from tests.test_project_lifecycle import command
    from app.persistence.projects_repository import get_project_by_code
    with admission_scope():
        get_project_by_code(world.user_id, world.project_code)
        command(world)

        @workspace_freshness_writer
        def writer():
            with db.get_cursor() as cur:
                cur.execute("UPDATE workspace_states SET dirty=0 WHERE project_id=?", (world.project_id,))

        with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
            writer()


def test_trigger_is_connection_local_and_raw_connections_are_a_separate_trust_boundary(world):
    _make_dirty(world)
    raw = sqlite3.connect(db.DB_PATH)
    try:
        names = {r[0] for r in raw.execute("SELECT name FROM sqlite_temp_master WHERE type='trigger'")}
        assert "wf03_workspace_states_freshness" not in names          # documented limitation, not a promise
    finally:
        raw.close()
    conn = db.get_connection()
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_temp_master WHERE type='trigger'")}
        assert "wf03_workspace_states_freshness" in names
    finally:
        conn.close()
