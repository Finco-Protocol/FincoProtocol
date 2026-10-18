"""V8-A: SQLite schema-cache safety without unclassified persistent metadata."""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.persistence import db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "v8a.sqlite"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return path


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(str(path)) as conn:
        return {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }


def _open_and_close():
    conn = db.get_connection()
    try:
        return {
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        }
    finally:
        conn.close()


def _first_boot_in_other_process(db_path: str, gate, output):
    """Top-level entrypoint for spawn-mode first-boot acceptance."""
    from app.persistence import db as child_db

    child_db.DB_PATH = db_path
    gate.wait(20)
    try:
        c = child_db.get_connection()
        try:
            c.execute("SELECT 1 FROM model_run_history LIMIT 1").fetchall()
            output.put(("ok",))
        finally:
            c.close()
    except Exception as exc:
        output.put(("error", str(exc)))


def test_no_new_schema_metadata_table_and_trust_registry_still_matches(isolated_db):
    _open_and_close()
    from app.trust_readiness.registry import DATA_STORES

    classified = [t for store in DATA_STORES for t in store.tables]
    assert set(classified) == _tables(isolated_db)
    assert len(classified) == len(set(classified))
    assert "_finco_schema_state" not in _tables(isolated_db)
    with sqlite3.connect(isolated_db) as conn:
        for table in classified:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert {"user_id", "project_id"} & columns, table


def test_schema_reused_without_repeating_ddl(isolated_db, monkeypatch):
    real = db._init_schema
    calls = []

    def recorded(conn, *, commit=True):
        calls.append(commit)
        return real(conn, commit=commit)

    monkeypatch.setattr(db, "_init_schema", recorded)
    _open_and_close()
    _open_and_close()
    _open_and_close()
    assert calls == [False]


def test_connection_pragmas_applied_every_time(isolated_db):
    one, two = _open_and_close(), _open_and_close()
    for settings in (one, two):
        assert settings["foreign_keys"] == 1
        assert settings["busy_timeout"] == 30000
        assert settings["journal_mode"].lower() == "wal"


def test_external_ddl_forces_full_schema_verification(isolated_db, monkeypatch):
    _open_and_close()
    original = db._init_schema
    checks = []

    def observed(conn, *, commit=True):
        checks.append(True)
        return original(conn, commit=commit)

    monkeypatch.setattr(db, "_init_schema", observed)
    with sqlite3.connect(isolated_db) as conn:
        conn.execute("CREATE TABLE unrelated_external_ddl (id INTEGER)")
    _open_and_close()
    assert len(checks) == 1


def test_database_delete_and_recreate_same_path(isolated_db):
    _open_and_close()
    isolated_db.unlink()
    for sidecar in (str(isolated_db) + "-wal", str(isolated_db) + "-shm"):
        if os.path.exists(sidecar):
            os.remove(sidecar)
    _open_and_close()
    assert "workspace_states" in _tables(isolated_db)
    assert "_finco_schema_state" not in _tables(isolated_db)


def test_database_replacement_with_older_schema(isolated_db, tmp_path):
    _open_and_close()
    other = tmp_path / "older.sqlite"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE incomplete_backup (id INTEGER)")
    os.replace(other, isolated_db)
    _open_and_close()
    assert "model_run_history" in _tables(isolated_db)


def test_failed_migration_rolls_back_and_retry_is_safe(isolated_db, monkeypatch):
    original = db._init_schema

    def interrupted(conn, *, commit=True):
        conn.execute("CREATE TABLE transient_failure (id INTEGER)")
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(db, "_init_schema", interrupted)
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        db.get_connection()
    assert "transient_failure" not in _tables(isolated_db)
    monkeypatch.setattr(db, "_init_schema", original)
    _open_and_close()
    assert "model_run_history" in _tables(isolated_db)


def test_concurrent_threads_do_not_duplicate_initialization(isolated_db, monkeypatch):
    original = db._init_schema
    count = [0]
    lock = threading.Lock()

    def observed(conn, *, commit=True):
        with lock:
            count[0] += 1
        return original(conn, commit=commit)

    monkeypatch.setattr(db, "_init_schema", observed)
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _i: _open_and_close(), range(5)))
    assert count == [1]
    assert all(r["foreign_keys"] == 1 for r in results)


def test_two_processes_concurrent_first_boot(isolated_db):
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Event()
    output = ctx.Queue()
    workers = [
        ctx.Process(target=_first_boot_in_other_process, args=(str(isolated_db), gate, output))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        gate.set()
        results = [output.get(timeout=45) for _ in workers]
        assert results == [("ok",), ("ok",)], results
    finally:
        for worker in workers:
            worker.join(timeout=10)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    assert all(worker.exitcode == 0 for worker in workers)
    assert "model_run_history" in _tables(isolated_db)


def test_cached_connections_do_not_repeat_create_statements(isolated_db, monkeypatch):
    """SQL trace verifies that steady-state connections skip schema DDL."""
    original_connect = sqlite3.connect
    traced = []

    def recording_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(traced.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    _open_and_close()
    first = tuple(traced)
    traced.clear()
    _open_and_close()
    second = tuple(traced)
    assert any(statement.lstrip().upper().startswith("CREATE TABLE") for statement in first)
    assert not any(
        statement.lstrip().upper().startswith(("CREATE TABLE", "CREATE INDEX", "ALTER TABLE"))
        for statement in second
    )
    assert len(second) < len(first), (len(first), len(second))


def test_same_inode_and_schema_cookie_replaced_database(isolated_db, tmp_path):
    """An in-place restore can retain both inode and PRAGMA schema_version."""
    _open_and_close()
    original_inode = isolated_db.stat().st_ino
    with sqlite3.connect(isolated_db) as conn:
        original_generation = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.close()

    donor = tmp_path / "restore-source.sqlite"
    with sqlite3.connect(donor) as conn:
        conn.execute("CREATE TABLE incomplete_restored_schema (id INTEGER)")
        conn.execute(f"PRAGMA schema_version={original_generation}")
    conn.close()
    # In-place bytes replacement deliberately retains the target inode,
    # unlike os.replace. All connections are closed before the overwrite.
    isolated_db.write_bytes(donor.read_bytes())
    assert isolated_db.stat().st_ino == original_inode
    with sqlite3.connect(isolated_db) as conn:
        assert conn.execute("PRAGMA schema_version").fetchone()[0] == original_generation
    conn.close()
    _open_and_close()
    assert "model_run_history" in _tables(isolated_db)
    assert "workspace_states" in _tables(isolated_db)
