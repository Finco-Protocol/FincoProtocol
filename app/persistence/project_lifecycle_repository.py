"""WF03 owner lifecycle transactions and SQLite final-write fences.

Lifecycle is deliberately outside the financial composite identity. Every app
connection installs final-write TEMP triggers; trusted offline fixture/backup
connections are not application mutation ingress. Rollback requires this guarded
connection contract or read-only maintenance, never an older unguarded binary.
Receipts have no cascading parent FK:
identifiers/digests survive explicitly authorized terminal demo disposal.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import uuid


class LifecycleError(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


# Immutable copy-on-write bindings are safe across copied async/thread contexts.
# A second lookup cannot refresh an earlier admission across archive/restore ABA.
_admissions: ContextVar[dict | None] = ContextVar("wf03_admissions", default=None)
_actor: ContextVar[str | None] = ContextVar("wf03_actor", default=None)
_creator: ContextVar[bool] = ContextVar("wf03_creator", default=False)


@contextmanager
def admission_scope(actor=None, *, creator=False):
    token = _admissions.set({})
    actor_token = _actor.set(actor)
    creator_token = _creator.set(creator)
    try:
        yield
    finally:
        _admissions.reset(token)
        _actor.reset(actor_token)
        _creator.reset(creator_token)


def admit(record):
    bindings = _admissions.get()
    if record is not None and bindings is not None:
        key = (record.user_id, record.project_id)
        if key not in bindings:
            _admissions.set({**bindings, key: record.lifecycle_version})
    return record


def _epoch_matches(owner, project_id, epoch):
    if _actor.get() is not None and _actor.get() != owner:
        return 0
    bindings = _admissions.get()
    if bindings is None:
        # Non-request jobs must explicitly admit a previously transitioned
        # project. Never silently re-admit at commit time.
        return int(epoch == 0)
    return int(bindings.get((owner, project_id), 0 if epoch == 0 else None) == epoch)


def install_connection_functions(conn):
    conn.create_function("wf03_epoch_matches", 3, _epoch_matches)
    conn.create_function("wf03_lifecycle_command", 0, lambda: 0)
    conn.create_function("wf03_terminal_disposal", 0, lambda: 0)
    conn.create_function("wf03_creator_allowed", 0, lambda: int(_admissions.get() is None or _creator.get()))
    conn.create_function("wf03_was_admitted", 2,
                         lambda owner, project: int((owner, project) in (_admissions.get() or {})))


def ensure_schema(conn):
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        # Acquire the writer BEFORE any schema/data read. A deferred upgrade
        # can fail immediately with BUSY_SNAPSHOT during five-process startup,
        # even with busy_timeout, if another initializer committed meanwhile.
        conn.execute("BEGIN IMMEDIATE")
    conn.execute("SAVEPOINT wf03_expand")
    try:
        _expand_schema(conn)
        install_write_fences(conn)
        conn.execute("RELEASE wf03_expand")
        if owns_transaction:
            conn.commit()
    except BaseException:
        if owns_transaction:
            conn.rollback()
        else:
            conn.execute("ROLLBACK TO wf03_expand")
            conn.execute("RELEASE wf03_expand")
        raise


def _install_trigger(conn, sql):
    name=re.search(r"CREATE (?:TEMP )?TRIGGER IF NOT EXISTS (\w+)",sql).group(1)
    catalog="sqlite_temp_master" if "CREATE TEMP TRIGGER" in sql else "sqlite_master"
    existing=conn.execute(f"SELECT sql FROM {catalog} WHERE type='trigger' AND name=?",(name,)).fetchone()
    normalized=lambda text: " ".join(text.replace("IF NOT EXISTS ", "").replace("CREATE TEMP TRIGGER", "CREATE TRIGGER").split()).rstrip(";")
    if existing is not None and normalized(existing[0])!=normalized(sql):
        raise LifecycleError("LIFECYCLE_SCHEMA_MISMATCH",503)
    conn.execute(sql)


def _expand_schema(conn):
    from app.persistence.db import _ensure_column
    _ensure_column(conn, "projects", "lifecycle_version", "INTEGER NOT NULL DEFAULT 0 CHECK(lifecycle_version>=0)")
    _ensure_column(conn, "projects", "lifecycle_archived_at", "TEXT")
    _ensure_column(conn, "projects", "lifecycle_archive_origin",
                   "TEXT CHECK(lifecycle_archive_origin IN ('USER_ACTION','CREATE_ABANDONED','LEGACY_UNKNOWN'))")
    # Only previously unclassified rows are migrated. No financial data touched.
    conn.create_function("wf03_lifecycle_command", 0, lambda: 1)
    try:
        conn.execute("""UPDATE projects SET lifecycle_archive_origin=CASE
            WHEN json_valid(replay_metadata_json) THEN CASE WHEN
                 json_extract(replay_metadata_json,'$.create_request.state') IN ('CREATING','ABANDONED')
            THEN 'CREATE_ABANDONED' ELSE 'LEGACY_UNKNOWN' END ELSE 'LEGACY_UNKNOWN' END
            WHERE archived=1 AND lifecycle_archive_origin IS NULL""")
    finally:
        conn.create_function("wf03_lifecycle_command", 0, lambda: 0)
    conn.execute("""CREATE TABLE IF NOT EXISTS project_lifecycle_events (
        event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
        request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('ARCHIVE','UNARCHIVE')),
        from_archived INTEGER NOT NULL CHECK(from_archived IN (0,1)),
        to_archived INTEGER NOT NULL CHECK(to_archived IN (0,1)),
        from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,
        occurred_at TEXT NOT NULL, UNIQUE(user_id,project_id,request_id),
        CHECK(to_version=from_version+1), CHECK(from_archived!=to_archived))""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_projects_lifecycle
        ON projects(user_id,archived,lifecycle_archive_origin,project_id)""")
    for op in ("UPDATE", "DELETE"):
        _install_trigger(conn, f"""CREATE TRIGGER IF NOT EXISTS wf03_events_no_{op.lower()}
            BEFORE {op} ON project_lifecycle_events BEGIN
            SELECT RAISE(ABORT,'WF03_IMMUTABLE_RECEIPT'); END""")
    _install_trigger(conn, """CREATE TRIGGER IF NOT EXISTS wf03_events_authority
        BEFORE INSERT ON project_lifecycle_events WHEN wf03_lifecycle_command()!=1
        BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_AUTHORITY_REQUIRED'); END""")

def install_write_fences(conn):
    # Closed table list, individually inventoried. References remain under their
    # existing protected authorities. No trigger on FAILED intent reconciliation.
    tables = ("workspace_states", "scenarios", "capex_sub_lines", "opex_sub_lines",
              "model_run_history", "scenario_exports", "save_all_requests", "model_run_intents",
              "model_m6_acquisition_cases")
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in tables:
        if table not in present:
            continue
        for op, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            # A failed old Run may still record its forensic refusal. Committed
            # history and finalization must pass the financial write fence.
            extra = " AND NEW.state!='FAILED'" if table == "model_run_intents" and op == "UPDATE" else ""
            tenant = "actor_id" if table == "model_run_intents" else "user_id"
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            owner_check = f" OR p.user_id!={row}.{tenant}" if tenant in cols else ""
            _install_trigger(conn, f"""CREATE TEMP TRIGGER IF NOT EXISTS wf03_{table}_{op.lower()}
                BEFORE {op} ON {table} WHEN wf03_terminal_disposal()!=1{extra}
                AND EXISTS(SELECT 1 FROM projects p WHERE p.project_id={row}.project_id
                  AND p.user_id!='__reference__' AND (p.archived!=0 OR p.is_readonly=1 OR p.is_protected=1
                    OR p.project_role='reference'{owner_check}
                    OR CASE WHEN json_valid(p.replay_metadata_json) THEN
                       json_extract(p.replay_metadata_json,'$.create_request.state')='CREATING'
                         AND wf03_creator_allowed()!=1 ELSE 1 END
                    OR wf03_epoch_matches(p.user_id,p.project_id,p.lifecycle_version)!=1))
                BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_CONFLICT'); END""")
    _install_trigger(conn, """CREATE TEMP TRIGGER IF NOT EXISTS wf03_projects_update
        BEFORE UPDATE ON projects WHEN OLD.user_id!='__reference__'
        AND wf03_lifecycle_command()!=1 AND wf03_terminal_disposal()!=1
        AND (OLD.archived!=0 OR OLD.is_readonly=1 OR OLD.is_protected=1 OR OLD.project_role='reference'
             OR NEW.archived!=OLD.archived
             OR NEW.lifecycle_version!=OLD.lifecycle_version
             OR NEW.lifecycle_archive_origin IS NOT OLD.lifecycle_archive_origin
             OR CASE WHEN json_valid(OLD.replay_metadata_json) THEN
                 json_extract(OLD.replay_metadata_json,'$.create_request.state')='CREATING'
                   AND wf03_creator_allowed()!=1 ELSE 1 END
             OR wf03_epoch_matches(OLD.user_id,OLD.project_id,OLD.lifecycle_version)!=1)
        BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_CONFLICT'); END""")
    # Legacy saved Run artifacts are keyed by owner/code rather than project_id.
    if "runs" in present:
        for op, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            _install_trigger(conn, f"""CREATE TEMP TRIGGER IF NOT EXISTS wf03_runs_{op.lower()}
                BEFORE {op} ON runs WHEN wf03_terminal_disposal()!=1
                AND EXISTS(SELECT 1 FROM projects p WHERE p.user_id={row}.user_id
                  AND (wf03_was_admitted(p.user_id,p.project_id)=1
                    OR p.project_code=json_extract({row}.inputs_json,'$.active_project')
                    OR p.project_id=json_extract({row}.replay_metadata_json,'$.project_id'))
                  AND p.user_id!='__reference__'
                  AND (p.archived!=0 OR wf03_epoch_matches(p.user_id,p.project_id,p.lifecycle_version)!=1))
                BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_CONFLICT'); END""")
    if "model_m6_acquisition_revisions" in present:
        for op, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            _install_trigger(conn, f"""CREATE TEMP TRIGGER IF NOT EXISTS wf03_acquisition_revisions_{op.lower()}
                BEFORE {op} ON model_m6_acquisition_revisions WHEN wf03_terminal_disposal()!=1
                AND EXISTS(SELECT 1 FROM model_m6_acquisition_cases c JOIN projects p ON p.project_id=c.project_id
                    WHERE c.case_id={row}.case_id AND (p.archived!=0
                      OR wf03_epoch_matches(p.user_id,p.project_id,p.lifecycle_version)!=1))
                BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_CONFLICT'); END""")
    _install_trigger(conn, """CREATE TEMP TRIGGER IF NOT EXISTS wf03_projects_delete
        BEFORE DELETE ON projects WHEN OLD.user_id!='__reference__'
        AND wf03_terminal_disposal()!=1
        AND (OLD.archived!=0 OR OLD.is_readonly=1 OR OLD.is_protected=1 OR OLD.project_role='reference'
             OR wf03_epoch_matches(OLD.user_id,OLD.project_id,OLD.lifecycle_version)!=1)
        BEGIN SELECT RAISE(ABORT,'WF03_LIFECYCLE_CONFLICT'); END""")


def eligible(row, *, restoring=False):
    if (row["project_role"] not in ("user_project", "working_copy")
            or row["project_origin"] not in ("user_project", "user_created")
            or row["is_protected"] or row["is_readonly"] or row["user_id"] == "__reference__"):
        return False
    try:
        creation = json.loads(row["replay_metadata_json"]).get("create_request", {}).get("state")
    except (ValueError, AttributeError, TypeError):
        return False
    if creation not in (None, "COMPLETE"):
        return False
    if restoring and row["lifecycle_archive_origin"] != "USER_ACTION":
        return False
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


def require_write_cursor(cur, owner, project_id):
    row = cur.execute("""SELECT * FROM projects WHERE user_id=? AND project_id=?
        AND archived=0 AND CASE WHEN json_valid(replay_metadata_json) THEN
            (json_extract(replay_metadata_json,'$.create_request.state') IS NULL OR
             json_extract(replay_metadata_json,'$.create_request.state')='COMPLETE') ELSE 0 END AND (
          (user_id='__reference__' AND project_role='reference' AND is_protected=1
            AND template_source IN ('generic_solar_reference','generic_wind_reference',
                'generic_data_center_reference','generic_ev_charging_reference','generic_storage_reference'))
          OR (user_id!='__reference__' AND is_readonly=0 AND is_protected=0 AND project_role!='reference'
            AND wf03_epoch_matches(user_id,project_id,lifecycle_version)=1))""", (owner, project_id)).fetchone()
    if row is None:
        raise LifecycleError("LIFECYCLE_CONFLICT")
    return row


def _current(row):
    return {"archived": bool(row["archived"]), "lifecycle_version": row["lifecycle_version"],
            "archive_origin": row["lifecycle_archive_origin"], "archived_at": row["lifecycle_archived_at"]}


def validate_body(data):
    if not isinstance(data, dict) or set(data) != {"request_id", "expected_archived", "lifecycle_version"}:
        raise LifecycleError("INVALID_LIFECYCLE_BODY", 422)
    if (not isinstance(data["request_id"], str) or re.fullmatch(r"[0-9a-f]{32}", data["request_id"]) is None
            or type(data["expected_archived"]) is not bool or type(data["lifecycle_version"]) is not int
            or not 0 <= data["lifecycle_version"] <= 2**63-2):
        raise LifecycleError("INVALID_LIFECYCLE_BODY", 422)


def transition(owner, code, action, data):
    from app.persistence.db import get_connection
    validate_body(data)
    if action not in ("ARCHIVE", "UNARCHIVE"):
        raise LifecycleError("INVALID_ACTION", 422)
    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT * FROM projects WHERE user_id=? AND project_code=?", (owner, code)).fetchone()
        if row is None:
            raise LifecycleError("PROJECT_NOT_FOUND", 404)
        digest = hashlib.sha256(json.dumps({**data, "action": action, "owner": owner,
                                           "project_id": row["project_id"]}, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        prior = conn.execute("SELECT * FROM project_lifecycle_events WHERE user_id=? AND project_id=? AND request_id=?",
                             (owner, row["project_id"], data["request_id"])).fetchone()
        if prior:
            if prior["request_digest"] != digest:
                raise LifecycleError("LIFECYCLE_KEY_REUSED")
            conn.rollback()
            return {"ok": True, "replayed": True, "receipt": dict(prior), "current": _current(row)}
        target = action == "ARCHIVE"
        if not eligible(row, restoring=not target):
            raise LifecycleError("LIFECYCLE_NOT_ELIGIBLE")
        if conn.execute("SELECT 1 FROM workspace_states WHERE user_id=? AND project_id=?",
                        (owner, row["project_id"])).fetchone() is None:
            raise LifecycleError("LIFECYCLE_INCOMPLETE_PROJECT")
        if bool(row["archived"]) != data["expected_archived"] or row["lifecycle_version"] != data["lifecycle_version"] or bool(row["archived"]) == target:
            raise LifecycleError("LIFECYCLE_STALE")
        stamp = _now()
        conn.create_function("wf03_lifecycle_command", 0, lambda: 1)
        changed = conn.execute("""UPDATE projects SET archived=?, lifecycle_version=lifecycle_version+1,
            lifecycle_archived_at=?, lifecycle_archive_origin='USER_ACTION'
            WHERE user_id=? AND project_id=? AND archived=? AND lifecycle_version=?""",
            (int(target), stamp if target else None, owner, row["project_id"], int(row["archived"]), row["lifecycle_version"]))
        if changed.rowcount != 1:
            raise LifecycleError("LIFECYCLE_STALE")
        event = (uuid.uuid4().hex, owner, row["project_id"], data["request_id"], digest, action,
                 int(row["archived"]), int(target), row["lifecycle_version"], row["lifecycle_version"]+1, stamp)
        conn.execute("INSERT INTO project_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", event)
        current = conn.execute("SELECT * FROM projects WHERE project_id=? AND user_id=?", (row["project_id"], owner)).fetchone()
        receipt = dict(conn.execute("SELECT * FROM project_lifecycle_events WHERE event_id=?", (event[0],)).fetchone())
        conn.commit()
        return {"ok": True, "replayed": False, "receipt": receipt, "current": _current(current)}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def status(owner, code, request_id):
    from app.persistence.db import get_cursor
    if not isinstance(request_id, str) or re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
        raise LifecycleError("INVALID_REQUEST_ID", 422)
    with get_cursor() as cur:
        if not cur.connection.in_transaction:
            cur.execute("BEGIN DEFERRED")
        row = cur.execute("SELECT * FROM projects WHERE user_id=? AND project_code=?", (owner, code)).fetchone()
        if row is None:
            raise LifecycleError("PROJECT_NOT_FOUND", 404)
        event = cur.execute("SELECT * FROM project_lifecycle_events WHERE user_id=? AND project_id=? AND request_id=?",
                            (owner, row["project_id"], request_id)).fetchone()
        return {"ok": True, "outcome": "COMMITTED" if event else "UNKNOWN", "receipt": dict(event) if event else None,
                "current": _current(row)}
