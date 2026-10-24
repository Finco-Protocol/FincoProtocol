"""SQLite schema initialisation once per file and schema version per process (app.persistence.db).

The full idempotent schema routine runs on the first connection to a database file and again whenever the file
identity or SQLite's schema cookie (PRAGMA schema_version) changes; every connection keeps its PRAGMAs and the
per-connection reference-role backfill. Nothing is recorded before a successful full initialisation."""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
import threading

import pytest

from app.persistence import db

REAL_INIT_SCHEMA = db._init_schema           # the unmodified full routine (captured before any spy wraps it)

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    path = tmp_path / "finco.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db._reset_schema_cache_for_tests()
    yield path
    db._reset_schema_cache_for_tests()


@pytest.fixture
def spy(monkeypatch):
    calls = {"init": 0, "backfill": 0}
    real_init, real_backfill = db._init_schema, db._backfill_reference_roles

    def init(conn):
        calls["init"] += 1
        return real_init(conn)

    def backfill(conn):
        calls["backfill"] += 1
        return real_backfill(conn)

    monkeypatch.setattr(db, "_init_schema", init)
    monkeypatch.setattr(db, "_backfill_reference_roles", backfill)
    return calls


def schema(path) -> dict:
    """Every table, index and column definition (the complete persisted schema)."""
    con = sqlite3.connect(path)
    try:
        objects = sorted(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        columns = {t: con.execute(f"PRAGMA table_info({t})").fetchall()
                   for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        return {"objects": objects, "columns": columns}
    finally:
        con.close()


def reference_schema(tmp_path) -> dict:
    """The schema produced by the unmodified full routine on a fresh file."""
    path = tmp_path / "reference.db"
    con = sqlite3.connect(path, isolation_level=None)
    REAL_INIT_SCHEMA(con)
    con.close()
    return schema(path)


def connect():
    conn = db.get_connection()
    conn.close()


# ── first connection, repeat connections, PRAGMAs ─────────────────────────────────

def test_first_connection_creates_the_complete_schema_and_repeats_skip_only_ddl(fresh_db, spy, tmp_path):
    expected = reference_schema(tmp_path)
    spy.update(init=0, backfill=0)                            # count only get_connection's own calls
    connect()
    assert spy == {"init": 1, "backfill": 1}
    assert schema(fresh_db) == expected
    for _ in range(5):
        connect()
    assert spy == {"init": 1, "backfill": 6}                  # backfill still runs on every connection
    assert schema(fresh_db) == expected                       # nothing lost


@pytest.mark.parametrize("warm", [False, True])
def test_every_connection_keeps_its_pragmas_and_autocommit(fresh_db, warm):
    if warm:
        connect()
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert conn.isolation_level is None and not conn.in_transaction
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_get_cursor_commits_and_rolls_back_as_before(fresh_db):
    connect()
    with db.get_cursor() as cur:
        cur.execute("INSERT INTO runs (run_id, user_id, project_type, scenario, created_at, inputs_json, kpis_json)"
                    " VALUES ('r1','u','Solar','Base','2026','{}','{}')")
    with pytest.raises(RuntimeError):
        with db.get_cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("INSERT INTO runs (run_id, user_id, project_type, scenario, created_at, inputs_json, kpis_json)"
                        " VALUES ('r2','u','Solar','Base','2026','{}','{}')")
            raise RuntimeError("abort")
    con = sqlite3.connect(fresh_db)
    assert [r[0] for r in con.execute("SELECT run_id FROM runs ORDER BY run_id")] == ["r1"]
    con.close()


# ── migrations and schema changes ────────────────────────────────────────────────────

def test_legacy_database_is_migrated_on_its_first_connection(fresh_db, spy, tmp_path):
    con = sqlite3.connect(fresh_db)
    con.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_code TEXT,"
                " project_name TEXT, created_at TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE workspace_states (user_id TEXT, project_id TEXT, PRIMARY KEY(user_id, project_id))")
    con.execute("CREATE INDEX ux_projects_system_reference_source ON projects(project_code)")      # superseded name
    con.execute("INSERT INTO projects VALUES ('p1','__reference__','REF','Ref','2026','2026')")
    con.commit(); con.close()
    connect()
    assert spy["init"] == 1
    con = sqlite3.connect(fresh_db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(projects)")}
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    con.close()
    assert {"project_role", "is_protected", "template_source", "model_perspective"} <= cols
    assert "ux_projects_system_reference_source" not in names and "ux_projects_canonical_reference_source" in names
    connect()
    assert spy["init"] == 1                                   # migrated once, then recorded


@pytest.mark.parametrize("change", ["drop-index", "add-column", "drop-table"])
def test_any_external_schema_change_reruns_the_full_routine_and_repairs(fresh_db, spy, tmp_path, change):
    connect()
    con = sqlite3.connect(fresh_db)
    if change == "drop-index":
        con.execute("DROP INDEX ux_projects_canonical_reference_source")
    elif change == "add-column":
        con.execute("ALTER TABLE runs ADD COLUMN external_note TEXT")
    else:
        con.execute("DROP TABLE model_run_history")
    con.commit(); con.close()
    connect()
    assert spy["init"] == 2                                   # schema cookie changed: full routine again
    repaired = schema(fresh_db)
    expected = reference_schema(tmp_path)
    if change == "add-column":
        expected["columns"]["runs"] = repaired["columns"]["runs"]
        expected["objects"] = [o for o in repaired["objects"]]
    assert repaired == expected
    connect()
    assert spy["init"] == 2


def test_deleted_recreated_and_replaced_files_are_initialised_again(fresh_db, spy, tmp_path):
    connect()
    for suffix in ("", "-wal", "-shm"):
        p = f"{fresh_db}{suffix}"
        if os.path.exists(p):
            os.remove(p)
    connect()
    assert spy["init"] == 2 and schema(fresh_db) == reference_schema(tmp_path)
    other = tmp_path / "restored.db"
    sqlite3.connect(other).close()                            # an empty restored file replaces the database
    os.replace(other, fresh_db)
    connect()
    assert spy["init"] == 3 and schema(fresh_db) == reference_schema(tmp_path)


def test_db_path_changes_initialise_each_database(fresh_db, spy, tmp_path, monkeypatch):
    connect()
    second = tmp_path / "second.db"
    monkeypatch.setattr(db, "DB_PATH", str(second))
    connect(); connect()
    assert spy["init"] == 2 and schema(second) == reference_schema(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", str(fresh_db))
    connect()
    assert spy["init"] == 2                                   # the first file is still recorded and unchanged


@pytest.mark.parametrize("name", [":memory:", "file:finco_uri_test?mode=memory&cache=shared", ""])
def test_memory_temporary_and_uri_databases_are_never_recorded(monkeypatch, spy, name, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", name)
    db._reset_schema_cache_for_tests()
    for _ in range(3):
        conn = db.get_connection()
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='model_run_history'").fetchone()[0] == 1
        conn.close()
    assert spy["init"] == 3 and db._SCHEMA_READY == {}


# ── failures and concurrency ─────────────────────────────────────────────────────────

def test_a_failed_initialisation_is_never_recorded(fresh_db, monkeypatch):
    real = db._ensure_column
    state = {"fail": True}

    def flaky(conn, table, column, sql):
        if state["fail"] and column == "model_v2_working_state_json":
            raise sqlite3.OperationalError("disk I/O error (injected)")
        return real(conn, table, column, sql)

    monkeypatch.setattr(db, "_ensure_column", flaky)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        db.get_connection()
    assert db._SCHEMA_READY == {}
    state["fail"] = False
    connect()
    assert len(db._SCHEMA_READY) == 1
    con = sqlite3.connect(fresh_db)
    assert "model_v2_working_state_json" in {r[1] for r in con.execute("PRAGMA table_info(workspace_states)")}
    con.close()


def test_concurrent_first_connections_all_succeed_with_a_complete_schema(fresh_db, tmp_path):
    barrier, errors = threading.Barrier(8), []

    def worker():
        try:
            barrier.wait(10)
            for _ in range(5):
                connect()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert schema(fresh_db) == reference_schema(tmp_path)
    assert len(db._SCHEMA_READY) == 1


# ── data repair and process isolation ────────────────────────────────────────────────

def test_reference_role_backfill_still_repairs_on_every_connection(fresh_db):
    connect()
    con = sqlite3.connect(fresh_db)
    con.execute("INSERT INTO projects (project_id, user_id, project_code, project_name, created_at, updated_at,"
                " source_project_template, governance_state_json, last_run_summary_json,"
                " template_source, project_role, is_protected) VALUES ('ref1','__reference__','RS','Ref',"
                " '2026','2026','t','{}','{}','generic_solar_reference','user_project',0)")
    con.execute("INSERT INTO projects (project_id, user_id, project_code, project_name, created_at, updated_at,"
                " source_project_template, governance_state_json, last_run_summary_json,"
                " template_source, project_role, is_protected) VALUES ('own1','someone','US','Mine',"
                " '2026','2026','t','{}','{}','generic_solar_reference','user_project',0)")
    con.commit(); con.close()
    connect()                                                 # recorded path: DDL skipped, repair applied
    con = sqlite3.connect(fresh_db)
    rows = dict((r[0], r[1:]) for r in con.execute("SELECT project_id, project_role, is_protected FROM projects"))
    con.close()
    assert rows == {"ref1": ("reference", 1), "own1": ("user_project", 0)}


def _child_connect(path, queue):
    from app.persistence import db as child_db
    child_db.DB_PATH = path
    conn = child_db.get_connection()
    queue.put((len(child_db._SCHEMA_READY), conn.execute("PRAGMA foreign_keys").fetchone()[0]))
    conn.close()


@pytest.mark.parametrize("method", ["spawn", "fork"])
def test_spawned_and_forked_processes_initialise_or_validate_independently(fresh_db, method):
    connect()
    ctx = multiprocessing.get_context(method)
    queue = ctx.Queue()
    proc = ctx.Process(target=_child_connect, args=(str(fresh_db), queue))
    proc.start()
    recorded, fk = queue.get(timeout=60)
    proc.join(60)
    assert proc.exitcode == 0 and recorded == 1 and fk == 1
    connect()                                                 # the parent's record is still valid
    assert len(db._SCHEMA_READY) == 1


def test_concurrent_first_connections_run_full_schema_once(fresh_db, monkeypatch):
    """Readiness and WAL setup are serialised, while returned connections stay independent."""
    calls = []
    count_lock = threading.Lock()
    barrier = threading.Barrier(8)
    errors = []

    def counted(conn):
        with count_lock:
            calls.append(threading.get_ident())
        REAL_INIT_SCHEMA(conn)

    monkeypatch.setattr(db, "_init_schema", counted)

    def worker():
        try:
            barrier.wait(10)
            for _ in range(5):
                conn = db.get_connection()
                assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                conn.close()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(calls) == 1
    assert schema(fresh_db) == reference_schema(fresh_db.parent)


def test_failed_schema_initialisation_closes_its_connection(fresh_db, monkeypatch):
    closed = []
    real_connect = sqlite3.connect

    class Tracked(sqlite3.Connection):
        def close(self):
            closed.append(self)
            return super().close()

    def connect_tracked(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=Tracked)

    def fail(conn):
        raise sqlite3.OperationalError("injected original initialisation failure")

    monkeypatch.setattr(sqlite3, "connect", connect_tracked)
    monkeypatch.setattr(db, "_init_schema", fail)
    with pytest.raises(sqlite3.OperationalError, match="injected original initialisation failure"):
        db.get_connection()
    assert len(closed) == 1 and db._SCHEMA_READY == {}
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        closed[0].execute("SELECT 1")


def test_fork_while_parent_initialisation_mutex_is_held_does_not_deadlock(fresh_db):
    connect()
    held, release = threading.Event(), threading.Event()

    def hold_parent_lock():
        with db._SCHEMA_INIT_LOCK:
            held.set()
            release.wait(60)

    thread = threading.Thread(target=hold_parent_lock)
    thread.start()
    assert held.wait(10)
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    proc = ctx.Process(target=_child_connect, args=(str(fresh_db), queue))
    try:
        proc.start()
        # The child must finish before the parent releases the inherited mutex.
        recorded, foreign_keys = queue.get(timeout=10)
        proc.join(10)
        assert proc.exitcode == 0 and recorded == 1 and foreign_keys == 1
    finally:
        release.set()
        thread.join(10)
        if proc.is_alive():
            proc.terminate()
            proc.join(10)
        queue.close()
        queue.join_thread()
    assert not thread.is_alive()
