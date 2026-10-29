"""Isolated owner-scoped M6 underwriting-case persistence; no Workbook writes."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import json
import uuid

from app.persistence.db import get_connection
from app.model_v2.acquisition.economics import AcquisitionTerms

CASE_SCHEMA = "finco.m6.acquisition-case-candidate"
CASE_VERSION = 1


class AcquisitionCaseConflict(ValueError):
    pass


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS model_m6_acquisition_cases (
        case_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
        source_history_id TEXT NOT NULL, revision INTEGER NOT NULL,
        document_json TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(project_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_m6_cases_owner_project ON model_m6_acquisition_cases(user_id,project_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS model_m6_acquisition_revisions (
        case_id TEXT NOT NULL, revision INTEGER NOT NULL, document_json TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(case_id,revision),
        FOREIGN KEY(case_id) REFERENCES model_m6_acquisition_cases(case_id)
    )""")
    # This independent append-only case revision log never mutates historical Runs.
    from app.persistence.project_lifecycle_repository import ensure_schema as _ensure_lifecycle_fences
    _ensure_lifecycle_fences(conn)



@contextmanager
def _read_connection():
    """Open the existing DB READ-ONLY; never run global schema bootstrap on GET.

    get_connection() initializes the global schema and is intentionally reserved
    for the controlled write boundary. Read-only URI mode cannot create a
    missing database; the first GET is therefore non-mutating as well.
    """
    from app.persistence import db as persistence_db

    path = Path(persistence_db.DB_PATH).resolve()
    if not path.is_file():
        yield None
        return
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


def _cases_table_exists(conn):
    """Missing optional M6 schema is a supported old-database read state."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='model_m6_acquisition_cases'"
    ).fetchone() is not None

def _require_uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise AcquisitionCaseConflict("CASE_ID_INVALID") from None
    if str(parsed) != value:
        raise AcquisitionCaseConflict("CASE_ID_INVALID")
    return value


def _terms_from_doc(document):
    if type(document) is not dict or set(document) != {
        "_schema", "schema_version", "methodology_version", "source",
        "terms", "closing_bridge",
    } or document["_schema"] != CASE_SCHEMA or document["schema_version"] != CASE_VERSION or document["methodology_version"] != "M6_ACQUISITION_CANDIDATE_V1":
        raise AcquisitionCaseConflict("CASE_SCHEMA_INVALID")
    source = document["source"]
    if type(source) is not dict or set(source) != {
        "history_id", "snapshot_id", "composite_hash", "scenario_id",
    } or any(type(source[k]) is not str or not source[k] for k in (
        "history_id", "snapshot_id", "composite_hash")):
        raise AcquisitionCaseConflict("CASE_SOURCE_IDENTITY_INVALID")
    if source["scenario_id"] is not None and (type(source["scenario_id"]) is not str or not source["scenario_id"]):
        raise AcquisitionCaseConflict("CASE_SCENARIO_ID_INVALID")
    raw = document["terms"]
    fields = set(AcquisitionTerms.__dataclass_fields__)
    if type(raw) is not dict or set(raw) != fields:
        raise AcquisitionCaseConflict("CASE_TERMS_INVALID")
    try:
        vals = dict(raw)
        vals["closing_date"] = date.fromisoformat(vals["closing_date"])
        if vals["closing_date"].isoformat() != raw["closing_date"]:
            raise ValueError("CLOSING_DATE_NOT_CANONICAL")
        if vals["exit_date"] is not None:
            vals["exit_date"] = date.fromisoformat(vals["exit_date"])
            if vals["exit_date"].isoformat() != raw["exit_date"]:
                raise ValueError("EXIT_DATE_NOT_CANONICAL")
        terms = AcquisitionTerms(**vals)
        terms.check()
    except (ValueError, TypeError) as exc:
        raise AcquisitionCaseConflict("CASE_TERMS_REJECTED: " + str(exc)) from None
    bridge = document["closing_bridge"]
    if bridge is not None:
        if type(bridge) is not dict or set(bridge) != {
            "balance_date", "enterprise_value_keur", "senior_debt_keur",
            "unrestricted_cash_keur", "restricted_cash_keur",
            "shl_balance_keur", "debt_like_keur", "working_capital_adjustment_keur",
            "transaction_adjustment_keur", "basis",
        }:
            raise AcquisitionCaseConflict("CASE_BRIDGE_FIELDS_INVALID")
        try:
            d = date.fromisoformat(bridge["balance_date"])
        except (ValueError, TypeError):
            raise AcquisitionCaseConflict("CASE_BRIDGE_DATE_INVALID") from None
        if d.isoformat() != bridge["balance_date"] or d != terms.closing_date:
            raise AcquisitionCaseConflict("CASE_BRIDGE_DATE_NOT_CLOSING")
        if bridge["basis"] != "EXPLICIT_USER_UNDERWRITING":
            # No fabricated exact-committed closing balance provenance in V1.
            raise AcquisitionCaseConflict("CASE_BRIDGE_BASIS_NOT_APPROVED")
        from app.model_v2.acquisition.economics import _finite
        for key, value in bridge.items():
            if key not in ("balance_date", "basis"):
                _finite(value, key, nonnegative=key not in (
                    "working_capital_adjustment_keur", "transaction_adjustment_keur"))
    return terms


def make_document(entry, terms: AcquisitionTerms, *, closing_bridge=None):
    terms.check()
    values = asdict(terms)
    values["closing_date"] = terms.closing_date.isoformat()
    values["exit_date"] = terms.exit_date.isoformat() if terms.exit_date else None
    source = dict(history_id=entry.history_id, snapshot_id=entry.runtime_snapshot_id,
                  composite_hash=entry.composite_hash, scenario_id=entry.last_runtime_scenario_id)
    doc = dict(_schema=CASE_SCHEMA, schema_version=CASE_VERSION,
               methodology_version="M6_ACQUISITION_CANDIDATE_V1",
               source=source, terms=values, closing_bridge=closing_bridge)
    _terms_from_doc(doc)
    return doc


def _source_matches(cur, *, owner_id, project_id, document):
    source = document["source"]
    row = cur.execute(
        "SELECT runtime_snapshot_id,composite_hash,last_runtime_scenario_id FROM model_run_history "
        "WHERE user_id=? AND project_id=? AND history_id=?",
        (owner_id, project_id, source["history_id"])).fetchone()
    if row is None or (row["runtime_snapshot_id"], row["composite_hash"],
                       row["last_runtime_scenario_id"]) != (
        source["snapshot_id"], source["composite_hash"], source["scenario_id"]):
        raise AcquisitionCaseConflict("CASE_COMMITTED_SOURCE_MISMATCH")


def _project_write_permission(cur, owner_id, project_id):
    row = cur.execute("SELECT archived,is_protected,is_readonly FROM projects WHERE user_id=? AND project_id=?",
                      (owner_id, project_id)).fetchone()
    if row is None or row["archived"] or row["is_protected"] or row["is_readonly"]:
        raise AcquisitionCaseConflict("CASE_OWNER_OR_PROTECTED_REFERENCE_DENIED")


def save_case(*, owner_id, project_id, document, case_id=None, expected_revision=0):
    """Transactionally create/update one case; revision CAS; never mutate a Run."""
    _terms_from_doc(document)
    if type(expected_revision) is not int or expected_revision < 0:
        raise AcquisitionCaseConflict("CASE_REVISION_INVALID")
    if case_id is not None:
        _require_uuid(case_id)
    with closing(get_connection()) as conn:
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # DDL is a WRITE operation: transactional and rollback-safe.
            # Never invoked by read_case/list_cases or an HTTP GET.
            _table(conn)
            cur = conn.cursor()
            _project_write_permission(cur, owner_id, project_id)
            _source_matches(cur, owner_id=owner_id, project_id=project_id, document=document)
            if case_id is None:
                if expected_revision != 0:
                    raise AcquisitionCaseConflict("CASE_NEW_REVISION_MISMATCH")
                case_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO model_m6_acquisition_cases (case_id,user_id,project_id,source_history_id,"
                    "revision,document_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (case_id,owner_id,project_id,document["source"]["history_id"],
                     1,_encode(document),now,now))
                revision = 1
            else:
                existing = cur.execute(
                    "SELECT revision,source_history_id FROM model_m6_acquisition_cases "
                    "WHERE case_id=? AND user_id=? AND project_id=?",
                    (case_id, owner_id, project_id)).fetchone()
                if existing is None or existing["revision"] != expected_revision:
                    raise AcquisitionCaseConflict("CASE_CAS_CONFLICT")
                if existing["source_history_id"] != document["source"]["history_id"]:
                    raise AcquisitionCaseConflict("CASE_SOURCE_REBIND_FORBIDDEN")
                revision = expected_revision + 1
                cur.execute(
                    "UPDATE model_m6_acquisition_cases SET document_json=?,revision=?,updated_at=? "
                    "WHERE case_id=? AND user_id=? AND project_id=? AND revision=?",
                    (_encode(document),revision,now,case_id,owner_id,project_id,expected_revision))
                if cur.rowcount != 1:
                    raise AcquisitionCaseConflict("CASE_CAS_CONFLICT")
            # The previous revisions remain immutable. Failure to append this
            # evidence aborts the new case save and rolls back the case UPDATE.
            cur.execute(
                "INSERT INTO model_m6_acquisition_revisions "
                "(case_id,revision,document_json,created_at) VALUES (?,?,?,?)",
                (case_id, revision, _encode(document), now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return case_id, revision


def read_case(*, owner_id, project_id, case_id):
    _require_uuid(case_id)
    with _read_connection() as conn:
        if conn is None or not _cases_table_exists(conn):
            return None
        row = conn.execute(
            "SELECT * FROM model_m6_acquisition_cases WHERE user_id=? AND project_id=? AND case_id=?",
            (owner_id,project_id,case_id)).fetchone()
    if row is None:
        return None
    try:
        doc = json.loads(row["document_json"])
    except (TypeError, json.JSONDecodeError):
        raise AcquisitionCaseConflict("CASE_STORED_JSON_INVALID") from None
    _terms_from_doc(doc)
    if row["source_history_id"] != doc["source"]["history_id"]:
        raise AcquisitionCaseConflict("CASE_STORED_SOURCE_CORRUPT")
    return {"case_id": row["case_id"], "revision": row["revision"], "document": doc,
            "updated_at": row["updated_at"]}


def list_cases(*, owner_id, project_id):
    with _read_connection() as conn:
        if conn is None or not _cases_table_exists(conn):
            return []
        rows = conn.execute(
            "SELECT case_id,revision,source_history_id,updated_at FROM model_m6_acquisition_cases "
            "WHERE user_id=? AND project_id=? ORDER BY updated_at DESC,case_id DESC LIMIT 50",
            (owner_id,project_id)).fetchall()
        return [dict(row) for row in rows]
