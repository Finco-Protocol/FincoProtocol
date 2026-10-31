"""Terminal demo-retention exception; real SQLite/FK/rollback evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Event

import pytest

from app import demo_cleanup as cleanup
from app.persistence import db, run_history_repository as history
from tests.wf03_fixture_seams import foreign_row_forgery

TABLES = ("projects", "scenario_exports", "workspace_states", "scenarios", "runs",
          "model_run_history", "capex_sub_lines", "opex_sub_lines")
OLD = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "disposable.db"))
    conn = db.get_connection()
    yield conn
    conn.close()


def insert(conn, table, **values):
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    row = {c["name"]: "{}" if c["name"].endswith("_json") else "synthetic"
           for c in columns if c["notnull"] and c["dflt_value"] is None}
    row.update(values)
    conn.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                 tuple(row.values()))


def seed(conn, owner, *, stamp=OLD, with_history=True, children=True, protected=False):
    pid = owner + "-project"
    insert(conn, "projects", project_id=pid, user_id=owner, project_code=pid,
           project_role="reference" if protected else "user_created",
           is_protected=int(protected), is_readonly=int(protected),
           source_project_template="synthetic", created_at=stamp, updated_at=stamp)
    if with_history:
        payload = history.prepare_run_history_payload(
            user_id=owner, project_id=pid, project_code=pid, ran_at=stamp,
            runtime_snapshot_id=owner + "-run", runtime_origin="synthetic-test",
            runtime_summary={"evidence": True}, financial_statements={},
            debt_schedule={}, tax_schedule={}, distribution_schedule={}, sponsor_schedule={})
        conn.execute("BEGIN IMMEDIATE")
        history.append_run_history_cursor(conn.cursor(), payload)
        conn.commit()
        assert len(history.get_run_history(owner, pid)) == 1
    if children:
        sid = owner + "-scenario"
        insert(conn, "scenarios", scenario_id=sid, project_id=pid, user_id=owner,
               project_code=pid, created_at=stamp, updated_at=stamp)
        insert(conn, "workspace_states", workspace_id=owner + "-workspace", project_id=pid,
               user_id=owner, project_code=pid, last_runtime_scenario_id=sid,
               created_at=stamp, updated_at=stamp)
        insert(conn, "scenario_exports", export_id=owner + "-export", project_id=pid,
               scenario_id=sid, user_id=owner, project_code=pid, created_at=stamp)
        insert(conn, "capex_sub_lines", sub_line_id=owner + "-capex", project_id=pid,
               parent_category_code="C.02", business_code="C.02.U001", display_order=1,
               label="Synthetic CAPEX", created_at=stamp, updated_at=stamp)
        insert(conn, "opex_sub_lines", sub_line_id=owner + "-opex", project_id=pid,
               parent_group_code="O.01", business_code="O.01.U001", display_order=1,
               label="Synthetic OPEX", created_at=stamp, updated_at=stamp)
        insert(conn, "runs", run_id=owner + "-legacy-run", user_id=owner, created_at=stamp)
    return pid


def snapshot(conn):
    return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in TABLES}


def assert_fk(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def references(conn):
    for index in range(5):
        insert(conn, "projects", project_id=f"reference-{index}", user_id="__reference__",
               project_code=f"reference-{index}", project_role="reference",
               is_protected=1, is_readonly=1, source_project_template="synthetic",
               created_at=OLD, updated_at=OLD)


@pytest.mark.parametrize("with_history", [False, True])
@pytest.mark.parametrize("ttl_hours", [0, 24])
def test_expired_complete_session_is_removed_atomically(database, with_history, ttl_hours):
    seed(database, "demo_expired", with_history=with_history)
    result = cleanup.cleanup_expired_demo_data(ttl_hours=ttl_hours)
    assert result["projects"] == 1
    assert result.get("model_run_history", 0) == int(with_history)
    assert all(not rows for rows in snapshot(database).values())
    assert cleanup.cleanup_expired_demo_data() == {}
    assert_fk(database)


def test_history_only_session_does_not_block_new_demo_cleanup(database):
    seed(database, "demo_old", children=False)
    seed(database, "demo_new", children=False, with_history=False)
    result = cleanup.cleanup_all_demo_data()
    assert result == {"model_run_history": 1, "projects": 2}
    assert all(not rows for rows in snapshot(database).values())
    assert_fk(database)


@pytest.mark.parametrize("table,column", cleanup._ACTIVITY)
def test_each_fresh_activity_preserves_entire_session(database, table, column):
    seed(database, "demo_fresh")
    # Fixture timestamp setup, never a product history mutation API.
    database.execute(f"UPDATE {table} SET {column}=?", (NOW,))
    before = snapshot(database)
    assert cleanup.cleanup_expired_demo_data() == {}
    assert snapshot(database) == before
    assert_fk(database)


@pytest.mark.parametrize("owner", ["permanent-user", "1", "__reference__", "demox_user", "DEMO_user"])
@pytest.mark.parametrize("explicit", [False, True])
def test_other_owner_history_and_full_state_preserved(database, owner, explicit):
    seed(database, owner, protected=owner == "__reference__")
    before = snapshot(database)
    seed(database, "demo_expired")
    (cleanup.cleanup_all_demo_data if explicit else cleanup.cleanup_expired_demo_data)()
    assert snapshot(database) == before
    assert_fk(database)


@pytest.mark.parametrize("flag,value", [("is_protected", 1), ("is_readonly", 1),
                                         ("project_role", "reference"),
                                         ("source_project_template", "generic_solar_reference")])
def test_protected_demo_rejects_entire_disposal(database, flag, value):
    seed(database, "demo_protected")
    seed(database, "demo_other")
    database.execute(f"UPDATE projects SET {flag}=? WHERE user_id='demo_protected'", (value,))
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="Protected"):
        cleanup.cleanup_all_demo_data()
    assert snapshot(database) == before
    assert_fk(database)


@pytest.mark.parametrize("table", ["scenarios", "scenario_exports", "workspace_states", "model_run_history"])
@pytest.mark.parametrize("direction", ["foreign_child", "foreign_parent"])
def test_mismatched_ownership_aborts_before_deletion(database, table, direction):
    seed(database, "demo_owner")
    seed(database, "permanent-owner")
    owner = "permanent-owner" if direction == "foreign_child" else "demo_owner"
    source = "demo_owner" if direction == "foreign_child" else "permanent-owner"
    # Legacy-corruption fixture only: the live WF-03 tenant fence correctly forbids
    # this ownership rewrite, so use the existing scoped test-only forgery seam.
    # It restores the fence before the real disposal path is exercised.
    with foreign_row_forgery(database.cursor()) as fixture_cursor:
        fixture_cursor.execute(f"UPDATE {table} SET user_id=? WHERE user_id=?", (owner, source))
    with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
        database.execute(f"UPDATE {table} SET user_id=user_id WHERE user_id=?", (owner,))
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="ownership mismatch"):
        cleanup.cleanup_all_demo_data()
    assert snapshot(database) == before
    assert_fk(database)


@pytest.mark.parametrize("table", TABLES)
def test_any_required_delete_failure_rolls_back_all_sessions(database, table):
    seed(database, "demo_first")
    seed(database, "demo_second")
    database.execute(f"CREATE TRIGGER fail_delete BEFORE DELETE ON {table} "
                     "BEGIN SELECT RAISE(ABORT, 'disposal_failure'); END")
    before = snapshot(database)
    with pytest.raises(sqlite3.IntegrityError, match="disposal_failure"):
        cleanup.cleanup_all_demo_data()
    assert snapshot(database) == before
    assert not database.in_transaction
    assert_fk(database)


def test_postcondition_failure_rolls_back_history_and_parents(database):
    seed(database, "demo_retained")
    database.execute("CREATE TRIGGER retain_run BEFORE DELETE ON runs "
                     "BEGIN SELECT RAISE(IGNORE); END")
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="post-condition"):
        cleanup.cleanup_all_demo_data()
    assert snapshot(database) == before
    assert_fk(database)


def test_transaction_and_fk_guards_do_not_take_caller_authority(database):
    database.execute("BEGIN IMMEDIATE")
    with pytest.raises(cleanup.DemoCleanupError, match="own transaction"):
        cleanup.bootstrap_staging_db(database)
    assert database.in_transaction
    database.rollback()
    database.execute("PRAGMA foreign_keys=OFF")
    with pytest.raises(cleanup.DemoCleanupError, match="foreign_keys=ON"):
        cleanup.bootstrap_staging_db(database)
    assert not database.in_transaction
    database.execute("PRAGMA foreign_keys=ON")
    assert_fk(database)


@pytest.mark.parametrize("owner", ["permanent-owner", "1", "demox_owner"])
def test_bootstrap_refuses_permanent_state_before_first_write(database, owner):
    references(database)
    seed(database, owner)
    seed(database, "demo_expired")
    before = snapshot(database)
    statements = []
    database.set_trace_callback(statements.append)
    with pytest.raises(cleanup.DemoCleanupError, match="permanent/admin"):
        cleanup.bootstrap_staging_db(database)
    database.set_trace_callback(None)
    assert not any(s.lstrip().upper().startswith(("DELETE", "UPDATE", "INSERT")) for s in statements)
    assert snapshot(database) == before
    assert_fk(database)


def test_bootstrap_disposes_only_demo_and_never_reseeds_existing_references(database, monkeypatch):
    references(database)
    before = snapshot(database)
    seed(database, "demo_expired")
    monkeypatch.setattr("app.services.project_library_service.ensure_reference_models",
                        lambda: pytest.fail("Existing reference evidence must not be reseeded"))
    result = cleanup.bootstrap_staging_db(database)
    assert result["post_condition"] == "PASS"
    assert result["deleted"]["model_run_history"] == 1
    assert snapshot(database) == before
    assert cleanup.bootstrap_staging_db(database)["deleted"] == {}
    assert_fk(database)


def test_bootstrap_failed_deletion_rolls_back_before_reference_changes(database):
    references(database)
    seed(database, "demo_expired")
    database.execute("CREATE TRIGGER fail_parent BEFORE DELETE ON projects "
                     "BEGIN SELECT RAISE(ABORT, 'bootstrap_failure'); END")
    before = snapshot(database)
    with pytest.raises(sqlite3.IntegrityError, match="bootstrap_failure"):
        cleanup.bootstrap_staging_db(database)
    assert snapshot(database) == before
    assert_fk(database)


def test_bootstrap_missing_references_refuses_before_demo_deletion(database):
    seed(database, "demo_expired")
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="Initialize references"):
        cleanup.bootstrap_staging_db(database)
    assert snapshot(database) == before


def test_bootstrap_orphan_state_refused_before_initialization(database, monkeypatch):
    # Deliberately invalid fixture; production never disables FK protection.
    database.execute("PRAGMA foreign_keys=OFF")
    insert(database, "capex_sub_lines", sub_line_id="orphan-capex", project_id="absent-parent",
           parent_category_code="C.02", business_code="C.02.U001", display_order=1,
           label="Synthetic orphan", created_at=OLD, updated_at=OLD)
    database.execute("PRAGMA foreign_keys=ON")
    before = snapshot(database)
    monkeypatch.setattr("app.services.project_library_service.ensure_reference_models",
                        lambda: pytest.fail("Orphan state must be refused before initialization"))
    with pytest.raises(cleanup.DemoCleanupError, match="inconsistent foreign-key"):
        cleanup.bootstrap_staging_db(database)
    assert snapshot(database) == before
    assert database.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reference_history_survives_bootstrap_exactly(database):
    references(database)
    payload = history.prepare_run_history_payload(
        user_id="__reference__", project_id="reference-0", project_code="reference-0",
        ran_at=OLD, runtime_snapshot_id="reference-run", runtime_origin="synthetic-test",
        runtime_summary={}, financial_statements={}, debt_schedule={}, tax_schedule={},
        distribution_schedule={}, sponsor_schedule={})
    database.execute("BEGIN IMMEDIATE")
    history.append_run_history_cursor(database.cursor(), payload)
    database.commit()
    before = snapshot(database)
    seed(database, "demo_expired")
    cleanup.bootstrap_staging_db(database)
    assert snapshot(database) == before
    assert_fk(database)


def test_bootstrap_protected_demo_refused_before_first_mutation(database):
    references(database)
    # Preserve full history and child evidence before the record becomes protected;
    # protected projects rightly refuse new history writes through the WF-03 fence.
    seed(database, "demo_protected")
    database.execute("UPDATE projects SET is_protected=1, is_readonly=1, "
                     "project_role='reference' WHERE user_id='demo_protected'")
    before = snapshot(database)
    statements = []
    database.set_trace_callback(statements.append)
    with pytest.raises(cleanup.DemoCleanupError, match="Protected"):
        cleanup.bootstrap_staging_db(database)
    database.set_trace_callback(None)
    assert not any(s.lstrip().upper().startswith(("DELETE", "INSERT", "UPDATE")) for s in statements)
    assert snapshot(database) == before


@pytest.mark.parametrize("table,column", [("scenario_exports", "scenario_id"),
                                         ("workspace_states", "last_runtime_scenario_id")])
def test_cross_project_scenario_binding_refuses_disposal(database, table, column):
    seed(database, "demo_owner")
    seed(database, "permanent-owner")
    database.execute(f"UPDATE {table} SET {column}='permanent-owner-scenario' WHERE user_id='demo_owner'")
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="scenario ownership"):
        cleanup.cleanup_all_demo_data()
    assert snapshot(database) == before
    assert_fk(database)


def test_invalid_activity_fails_closed_without_mutation(database):
    seed(database, "demo_owner")
    database.execute("UPDATE model_run_history SET created_at='invalid-fixture-timestamp'")
    before = snapshot(database)
    with pytest.raises(cleanup.DemoCleanupError, match="activity timestamp"):
        cleanup.cleanup_expired_demo_data()
    assert snapshot(database) == before


def test_concurrent_history_activity_is_read_after_write_lock(database, monkeypatch):
    seed(database, "demo_active")
    # Cleanup must wait for a canonical writer, then see its fresh history.
    other = sqlite3.connect(db.DB_PATH, isolation_level=None, check_same_thread=False, timeout=5)
    other.row_factory = sqlite3.Row
    other.execute("PRAGMA foreign_keys=ON")
    started = Event()
    class TracedConnection:
        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                started.set()
            return other.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(other, name)
    monkeypatch.setattr(db, "get_connection", lambda: TracedConnection())
    database.execute("BEGIN IMMEDIATE")
    payload = history.prepare_run_history_payload(
        user_id="demo_active", project_id="demo_active-project", project_code="demo_active-project",
        ran_at=NOW, runtime_snapshot_id="demo_active-fresh-run", runtime_origin="synthetic-test",
        runtime_summary={}, financial_statements={}, debt_schedule={}, tax_schedule={},
        distribution_schedule={}, sponsor_schedule={})
    history.append_run_history_cursor(database.cursor(), payload)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(cleanup.cleanup_expired_demo_data)
        assert started.wait(5)
        assert not future.done()
        database.commit()
        before = snapshot(database)
        assert future.result(timeout=5) == {}
    assert snapshot(database) == before
    assert_fk(database)
