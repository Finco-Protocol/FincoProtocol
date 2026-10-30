"""M6 acquisition persistence x WF-03 lifecycle fences: canonical schema vs isolated minimal schema.

The WF-03 database-level fences are installed on the CANONICAL ``projects`` schema. An isolated/older minimal schema is never thereby
writable: ``save_case`` always runs the explicit owner / archived / protected / read-only permission and fails closed on a missing row or a
missing security column. Failed saves leave schema and rows exactly unchanged. Canonical and minimal variants are tested separately.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace as NS

import pytest

import app.persistence.acquisition_repository as repo
from app.persistence.acquisition_repository import AcquisitionCaseConflict, make_document, save_case
from tests.test_m6_institutional_acquisition_candidate import _db, _db_state, terms

ENTRY = NS(history_id="h-1", runtime_snapshot_id="snapshot-123", composite_hash="c" * 64, last_runtime_scenario_id=None)


def _document():
    return make_document(ENTRY, terms())


def _set(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(sql)
        conn.commit()


# ── isolated minimal schema ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_minimal_schema_owner_save_works_and_does_not_expand_the_schema(tmp_path, monkeypatch):
    path = _db(tmp_path, monkeypatch)
    with closing(sqlite3.connect(path)) as conn:
        assert not repo._canonical_projects_schema(conn)
    case, revision = save_case(owner_id="owner-A", project_id="project-A", document=_document())
    assert revision == 1 and case
    with closing(sqlite3.connect(path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        triggers = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'wf03%'").fetchone()[0]
    assert "lifecycle_version" not in columns and triggers == 0     # the lifecycle migration is a canonical-schema operation only


@pytest.mark.parametrize("update", [
    "UPDATE projects SET archived=1",
    "UPDATE projects SET is_protected=1",
    "UPDATE projects SET is_readonly=1",
    "UPDATE projects SET user_id='someone-else'",
    "DELETE FROM projects",
], ids=["archived", "protected", "read-only", "other-owner", "missing-project"])
def test_minimal_schema_is_never_silently_writable(tmp_path, monkeypatch, update):
    path = _db(tmp_path, monkeypatch)
    _set(path, update)
    before = _db_state(path)
    with pytest.raises(AcquisitionCaseConflict, match="DENIED"):
        save_case(owner_id="owner-A", project_id="project-A", document=_document())
    assert _db_state(path) == before                                 # nothing written, no DDL survives, history untouched


def test_minimal_schema_missing_a_security_column_fails_closed(tmp_path, monkeypatch):
    path = _db(tmp_path, monkeypatch)
    _set(path, "ALTER TABLE projects DROP COLUMN is_protected")
    before = _db_state(path)
    with pytest.raises(sqlite3.OperationalError):
        save_case(owner_id="owner-A", project_id="project-A", document=_document())
    assert _db_state(path) == before                                 # a missing security column never implies permission


# ── canonical schema: the full WF-03 boundary stays active ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def canonical(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "canonical.db"))
    db.init_db()
    return db


def test_canonical_schema_is_recognised_and_lifecycle_fences_are_installed(canonical):
    with closing(canonical.get_connection()) as conn:
        assert repo._canonical_projects_schema(conn)
        repo._table(conn)
        conn.commit()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        fences = {row[0] for row in conn.execute("SELECT name FROM sqlite_temp_master WHERE type='trigger'")}
    assert "lifecycle_version" in columns
    assert "wf03_model_m6_acquisition_cases_insert" in fences      # the DB-level fence covers the M6 table on a canonical DB


def test_canonical_archived_project_is_denied_by_permission_and_by_the_database_fence(canonical):
    from app.persistence.project_lifecycle_repository import transition
    from app.services.reference_seed_service import create_reference_seeded_project
    owner = "m6-boundary-owner"
    record = create_reference_seeded_project(user_id=owner, template_source="generic_solar_reference",
                                             requested_name="M6 boundary", capacity_mw=40)
    transition(owner, record.project_code, "ARCHIVE",
               {"request_id": "a" * 32, "expected_archived": False, "lifecycle_version": 0})
    # 1. the explicit application permission refuses before any case row exists
    with pytest.raises(AcquisitionCaseConflict, match="DENIED"):
        save_case(owner_id=owner, project_id=record.project_id, document=_document())
    # 2. the database fence refuses a raw write that bypasses the application guard
    with closing(canonical.get_connection()) as conn:
        repo._table(conn)
        with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
            conn.execute("INSERT INTO model_m6_acquisition_cases (case_id,user_id,project_id,source_history_id,revision,"
                         "document_json,created_at,updated_at) VALUES ('x',?,?,'h',1,'{}','t','t')", (owner, record.project_id))
        conn.rollback()


def test_canonical_other_owner_is_denied(canonical):
    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(user_id="m6-real-owner", template_source="generic_solar_reference",
                                             requested_name="M6 owner", capacity_mw=40)
    with pytest.raises(AcquisitionCaseConflict, match="DENIED"):
        save_case(owner_id="m6-intruder", project_id=record.project_id, document=_document())
