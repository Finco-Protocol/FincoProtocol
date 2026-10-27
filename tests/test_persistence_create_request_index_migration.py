"""Migration of the atomic create-request identity index (app.persistence.db).

The partial unique index ``ux_projects_user_create_request`` reads ``projects.replay_metadata_json``. A database created before that
column existed must gain the column first and the index second, without touching a row, and a conflict in pre-existing data must fail
closed (nothing dropped, nothing recorded as migrated) with a diagnostic an operator can act on."""
from __future__ import annotations

import json
import multiprocessing
import sqlite3

import pytest

from app.persistence import db

INDEX = "ux_projects_user_create_request"
INSERT_SQL = ("INSERT INTO projects (project_id, user_id, project_code, project_name, source_project_template, governance_state_json, "
              "last_run_summary_json, created_at, updated_at, replay_metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)")
LEGACY_PROJECTS = ("CREATE TABLE projects (project_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_code TEXT, "
                   "project_name TEXT, created_at TEXT, updated_at TEXT)")


@pytest.fixture
def path(tmp_path, monkeypatch):
    target = str(tmp_path / "finco.db")
    monkeypatch.setattr(db, "DB_PATH", target)
    db._reset_schema_cache_for_tests()
    yield target
    db._reset_schema_cache_for_tests()


def _legacy(path, rows=()):
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_PROJECTS)
    conn.execute("CREATE UNIQUE INDEX idx_projects_user_code ON projects(user_id, project_code)")
    for row in rows:
        conn.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()


def _current(path, rows=()):
    """A database that already has the current schema, then a few rows with explicit metadata."""
    db.init_db()
    conn = sqlite3.connect(path)
    for pid, user, code, meta in rows:
        conn.execute(INSERT_SQL, (pid, user, code, code, "t", "{}", "{}", "2026", "2026", meta))
    conn.commit()
    conn.close()


def _query(path, sql, args=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _meta(request_id):
    return json.dumps({"create_request": {"request_id": request_id, "state": "COMPLETE"}})


def _index_sql(path):
    return _query(path, "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (INDEX,))[0][0]


def _insert(path, pid, user, meta, code=None):
    conn = sqlite3.connect(path)
    try:
        conn.execute(INSERT_SQL, (pid, user, code or pid, pid, "t", "{}", "{}", "2026", "2026", meta))
        conn.commit()
    finally:
        conn.close()


# ── A. fresh database ─────────────────────────────────────────────────────────────

def test_a_fresh_database_has_the_column_and_the_exact_partial_unique_index(path):
    db.init_db()
    assert "replay_metadata_json" in {r[1] for r in _query(path, "PRAGMA table_info(projects)")}
    assert _index_sql(path) == (
        f"CREATE UNIQUE INDEX {INDEX} ON projects(user_id, "
        "(CASE WHEN json_valid(replay_metadata_json) THEN json_extract(replay_metadata_json, '$.create_request.request_id') END)) "
        "WHERE (CASE WHEN json_valid(replay_metadata_json) THEN json_extract(replay_metadata_json, '$.create_request.request_id') END) IS NOT NULL")
    assert _query(path, "SELECT \"unique\", partial FROM pragma_index_list('projects') WHERE name=?", (INDEX,)) == [(1, 1)]


# ── B. existing legacy database ───────────────────────────────────────────────────

def test_b_a_legacy_database_is_migrated_column_first_index_second_without_data_loss(path):
    _legacy(path, rows=[("ref", "__reference__", "REF", "Reference", "2026", "2026"),
                        ("u1", "alice", "ALICE-1", "Alice one", "2025", "2025")])
    before = _query(path, "SELECT project_id, user_id, project_code, project_name, created_at, updated_at FROM projects ORDER BY 1")
    assert "replay_metadata_json" not in {r[1] for r in _query(path, "PRAGMA table_info(projects)")}
    db.init_db()
    assert "replay_metadata_json" in {r[1] for r in _query(path, "PRAGMA table_info(projects)")}
    assert _index_sql(path).startswith(f"CREATE UNIQUE INDEX {INDEX} ON projects(")
    after = _query(path, "SELECT project_id, user_id, project_code, project_name, created_at, updated_at FROM projects ORDER BY 1")
    assert after == before                                                     # no row lost or rewritten
    assert {r[0] for r in _query(path, "SELECT replay_metadata_json FROM projects")} == {"{}"}      # the column default, not an invented identity
    names = {r[0] for r in _query(path, "SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_projects_user_code", INDEX} <= names                          # the legacy index survives


def test_b_historical_replay_metadata_is_preserved_byte_for_byte(path):
    historical = json.dumps({"replay": {"engine": "v1", "inputs_digest": "abc"}, "note": "kept"}, sort_keys=True)
    _current(path, rows=[("h1", "alice", "H1", historical), ("h2", "alice", "H2", _meta("req-9"))])
    db._reset_schema_cache_for_tests()
    db.init_db()                                                                # a second full routine over existing data
    assert _query(path, "SELECT replay_metadata_json FROM projects WHERE project_id='h1'") == [(historical,)]
    assert _query(path, "SELECT replay_metadata_json FROM projects WHERE project_id='h2'") == [(_meta("req-9"),)]


# ── C. idempotency ────────────────────────────────────────────────────────────────

def test_c_the_first_connection_migrates_and_later_connections_do_not_rebuild(path, monkeypatch):
    _legacy(path)
    calls = []
    real = db._init_schema
    monkeypatch.setattr(db, "_init_schema", lambda conn: (calls.append(1), real(conn))[1])
    db.init_db()
    db.init_db()
    db.init_db()
    assert len(calls) == 1


def test_c_a_schema_change_triggers_a_recheck_that_restores_the_index_and_keeps_rows(path, monkeypatch):
    _current(path, rows=[("p1", "alice", "P1", _meta("req-1"))])
    conn = sqlite3.connect(path)
    conn.execute(f"DROP INDEX {INDEX}")
    conn.commit()
    conn.close()
    db.init_db()                                                               # the schema cookie changed -> the full routine runs again
    assert _index_sql(path).startswith("CREATE UNIQUE INDEX")
    assert _query(path, "SELECT project_id FROM projects") == [("p1",)]


def test_c_rerunning_the_routine_never_destroys_records(path):
    _current(path, rows=[("p1", "alice", "P1", _meta("req-1")), ("p2", "bob", "P2", _meta("req-1"))])
    for _ in range(3):
        db._reset_schema_cache_for_tests()
        db.init_db()
    assert _query(path, "SELECT project_id FROM projects ORDER BY 1") == [("p1",), ("p2",)]
    assert _query(path, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (INDEX,)) == [(1,)]


# ── D. atomic request identity (database layer; the service/HTTP layers are covered by the atomic and multi-process suites) ──

def test_d_the_database_refuses_a_second_project_for_one_user_and_request(path):
    db.init_db()
    _insert(path, "p1", "alice", _meta("req-1"))
    with pytest.raises(sqlite3.IntegrityError):
        _insert(path, "p2", "alice", _meta("req-1"))
    assert _query(path, "SELECT COUNT(*) FROM projects") == [(1,)]


def test_d_other_users_and_other_request_ids_are_independent(path):
    db.init_db()
    _insert(path, "p1", "alice", _meta("req-1"))
    _insert(path, "p2", "bob", _meta("req-1"))                                 # same id, another user
    _insert(path, "p3", "alice", _meta("req-2"))                               # same user, another id
    assert _query(path, "SELECT COUNT(*) FROM projects") == [(3,)]


def test_d_the_index_ignores_rows_without_a_request_identity(path):
    db.init_db()
    for index, meta in enumerate(["{}", "{}", "not json", "not json", json.dumps({"create_request": {}}), json.dumps({"create_request": {}}),
                                  json.dumps({"other": 1}), json.dumps({"other": 1})]):
        _insert(path, f"n{index}", "alice", meta)
    assert _query(path, "SELECT COUNT(*) FROM projects") == [(8,)]


def _same_request_worker(args):
    db_path, pid = args
    import sqlite3 as sq
    conn = sq.connect(db_path, timeout=30.0)
    try:
        conn.execute(INSERT_SQL, (pid, "alice", pid, pid, "t", "{}", "{}", "2026", "2026", _meta("req-race")))
        conn.commit()
        return "inserted"
    except sq.IntegrityError:
        return "refused"
    finally:
        conn.close()


def test_d_concurrent_processes_cannot_create_two_projects_for_one_request(path):
    db.init_db()
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        outcomes = pool.map(_same_request_worker, [(path, f"race-{i}") for i in range(8)])
    assert sorted(outcomes) == ["inserted"] + ["refused"] * 7
    assert _query(path, "SELECT COUNT(*) FROM projects") == [(1,)]


# ── E. negatives ──────────────────────────────────────────────────────────────────

def test_e_malformed_and_null_metadata_in_a_legacy_database_do_not_block_the_migration(path):
    _legacy(path, rows=[("a", "alice", "A", "A", "2025", "2025"), ("b", "alice", "B", "B", "2025", "2025")])
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE projects ADD COLUMN replay_metadata_json TEXT")           # an older shape with NULLable, never-validated values
    conn.execute("UPDATE projects SET replay_metadata_json='{broken' WHERE project_id='a'")
    conn.commit()
    conn.close()
    db.init_db()
    assert _index_sql(path)
    assert _query(path, "SELECT project_id, replay_metadata_json FROM projects ORDER BY 1") == [("a", "{broken"), ("b", None)]


def test_e_duplicate_identities_in_an_existing_database_fail_closed_with_an_actionable_diagnostic(path):
    _current(path)
    conn = sqlite3.connect(path)
    conn.execute(f"DROP INDEX {INDEX}")
    for pid in ("d1", "d2"):
        conn.execute(INSERT_SQL, (pid, "alice", pid, pid, "t", "{}", "{}", "2026", "2026", _meta("req-dup")))
    conn.commit()
    conn.close()
    before = _query(path, "SELECT project_id, replay_metadata_json FROM projects ORDER BY 1")
    db._reset_schema_cache_for_tests()                                                   # a fresh process meeting the database as it now is
    for _ in range(2):                                                                   # every connection fails; the failure is never cached as success
        with pytest.raises(RuntimeError) as failure:
            db.get_connection()
        assert INDEX in str(failure.value) and "GROUP BY" in str(failure.value) and "No row was changed" in str(failure.value)
    assert db._SCHEMA_READY == {}
    assert _query(path, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (INDEX,)) == [(0,)]
    assert _query(path, "SELECT project_id, replay_metadata_json FROM projects ORDER BY 1") == before    # nothing dropped or rewritten
    conn = sqlite3.connect(path)                                                         # the operator archives the superseded duplicate…
    conn.execute("UPDATE projects SET replay_metadata_json='{}' WHERE project_id='d2'")
    conn.commit()
    conn.close()
    db.init_db()                                                                         # …and the retry completes
    assert _index_sql(path)
    assert _query(path, "SELECT COUNT(*) FROM projects") == [(2,)]


def test_e_lock_contention_fails_visibly_is_not_recorded_and_retry_succeeds(path, monkeypatch):
    _legacy(path, rows=[("u1", "alice", "A1", "A1", "2025", "2025")])
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    real_connect = sqlite3.connect
    with monkeypatch.context() as impatient:
        impatient.setattr(sqlite3, "connect", lambda target, *args, **kwargs: real_connect(target, *args, **{**kwargs, "timeout": 0.05}))
        with pytest.raises(sqlite3.OperationalError):
            db.get_connection()
    assert db._SCHEMA_READY == {}
    holder.execute("ROLLBACK")
    holder.close()
    db.init_db()
    assert _index_sql(path)
    assert _query(path, "SELECT project_id FROM projects") == [("u1",)]


def test_e_an_incomplete_migration_is_not_recorded_and_the_retry_completes(path, monkeypatch):
    _legacy(path, rows=[("u1", "alice", "A1", "A1", "2025", "2025")])
    real = db._ensure_column
    state = {"fail": True}

    def flaky(conn, table, column, ddl):
        if state["fail"] and column == "full_inputs_json":
            raise sqlite3.OperationalError("simulated interruption")
        return real(conn, table, column, ddl)

    monkeypatch.setattr(db, "_ensure_column", flaky)
    with pytest.raises(sqlite3.OperationalError):
        db.get_connection()
    assert db._SCHEMA_READY == {}
    assert _query(path, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (INDEX,)) == [(0,)]       # the index is not created ahead of its column
    state["fail"] = False
    db.init_db()
    assert _index_sql(path)
    assert _query(path, "SELECT project_id, replay_metadata_json FROM projects") == [("u1", "{}")]
