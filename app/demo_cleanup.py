"""Terminal disposal of temporary demo sessions, with immutable history otherwise.

TTL authority is MAX(activity) across projects, scenarios, workspaces, runs,
exports and Run History (both ran_at and created_at). A fresh object preserves
the entire session. Explicit operator reset may dispose fresh demo sessions.
Only canonical demo owners with unprotected, consistently owned state qualify.
No permanent, admin, reference or protected evidence may be deleted.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
import sqlite3
from types import SimpleNamespace

from app.auth import DEMO_TTL_HOURS, DEMO_USER_ID_PREFIX

logger = logging.getLogger(__name__)

# Explicit child-first order, including the bounded demo-history exception.
_TABLES_WITH_USER_ID = (
    "scenario_exports", "workspace_states", "scenarios", "runs", "model_run_history",
)
_SUBLINE_TABLES = ("capex_sub_lines", "opex_sub_lines")
_ACTIVITY = (
    ("projects", "updated_at"), ("scenarios", "updated_at"),
    ("workspace_states", "updated_at"), ("runs", "created_at"),
    ("scenario_exports", "created_at"), ("model_run_history", "ran_at"),
    ("model_run_history", "created_at"),
)


class DemoCleanupError(RuntimeError):
    """Disposal refused or failed; no selected session was partially committed."""


@contextmanager
def _disposal_transaction(conn: sqlite3.Connection):
    if conn.in_transaction:
        raise DemoCleanupError("Disposal requires its own transaction")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise DemoCleanupError("Disposal requires foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.create_function("wf03_terminal_disposal", 0, lambda: 0)


def _cutoff_iso(ttl_hours: int) -> str:
    if ttl_hours < 0:
        raise DemoCleanupError("Demo TTL must be non-negative")
    return (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()


def _timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (AttributeError, ValueError) as exc:
        raise DemoCleanupError("Invalid demo activity timestamp") from exc


def _demo_activity(conn: sqlite3.Connection) -> dict[str, list[datetime]]:
    activity: dict[str, list[datetime]] = {}
    for table, column in _ACTIVITY:
        rows = conn.execute(
            f"SELECT user_id, {column} AS activity FROM {table} "
            "WHERE substr(user_id, 1, ?) = ? COLLATE BINARY",
            (len(DEMO_USER_ID_PREFIX), DEMO_USER_ID_PREFIX),
        )
        for row in rows:
            activity.setdefault(row["user_id"], []).append(_timestamp(row["activity"]))
    return activity


def _find_expired_demo_users(conn: sqlite3.Connection, cutoff: str) -> list[str]:
    limit = _timestamp(cutoff)
    return sorted(owner for owner, stamps in _demo_activity(conn).items()
                  if max(stamps) < limit)


def _validate_owned_state(conn: sqlite3.Connection, user_ids: list[str]) -> None:
    from app.services.project_library_service import is_protected_reference

    if not user_ids:
        return
    if any(not owner.startswith(DEMO_USER_ID_PREFIX) for owner in user_ids):
        raise DemoCleanupError("Only canonical demo owners may be disposed")
    marks = ",".join("?" for _ in user_ids)
    for row in conn.execute(f"SELECT * FROM projects WHERE user_id IN ({marks})", user_ids):
        record = SimpleNamespace(**dict(row))
        if record.is_readonly or is_protected_reference(record):
            raise DemoCleanupError("Protected/reference demo state cannot be disposed")

    # Validate both sides: selecting children by owner alone must not delete
    # another tenant's evidence, nor leave foreign-owned children of this parent.
    for table in ("scenarios", "scenario_exports", "workspace_states", "model_run_history"):
        mismatch = conn.execute(
            f"SELECT 1 FROM {table} c LEFT JOIN projects p ON p.project_id=c.project_id "
            f"WHERE (c.user_id IN ({marks}) OR p.user_id IN ({marks})) "
            "AND (p.project_id IS NULL OR c.user_id != p.user_id "
            "OR c.project_code != p.project_code) LIMIT 1", user_ids + user_ids,
        ).fetchone()
        if mismatch:
            raise DemoCleanupError("Demo child/project ownership mismatch")
    for table, column in (("scenario_exports", "scenario_id"),
                          ("workspace_states", "last_runtime_scenario_id")):
        mismatch = conn.execute(
            f"SELECT 1 FROM {table} c LEFT JOIN scenarios s ON s.scenario_id=c.{column} "
            f"WHERE c.user_id IN ({marks}) AND c.{column} IS NOT NULL "
            "AND (s.scenario_id IS NULL OR c.user_id != s.user_id "
            "OR c.project_id != s.project_id) LIMIT 1", user_ids,
        ).fetchone()
        if mismatch:
            raise DemoCleanupError("Demo scenario ownership mismatch")


def _delete_owned_state(conn: sqlite3.Connection, user_ids: list[str], summary: dict) -> None:
    if not user_ids:
        return
    if not conn.in_transaction:
        raise DemoCleanupError("Demo disposal must be atomic")
    _validate_owned_state(conn, user_ids)
    # Only this already-authorized, tenant-validated terminal disposal may
    # remove archived financial state. Lifecycle receipts remain tombstones,
    # with no cascading FK or automatic receipt deletion.
    conn.create_function("wf03_terminal_disposal", 0, lambda: 1)
    marks = ",".join("?" for _ in user_ids)
    for table in _SUBLINE_TABLES:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE project_id IN "
            f"(SELECT project_id FROM projects WHERE user_id IN ({marks}))", user_ids,
        )
        if cur.rowcount:
            summary[table] = cur.rowcount
    for table in _TABLES_WITH_USER_ID:
        cur = conn.execute(f"DELETE FROM {table} WHERE user_id IN ({marks})", user_ids)
        if cur.rowcount:
            summary[table] = cur.rowcount
    cur = conn.execute(f"DELETE FROM projects WHERE user_id IN ({marks})", user_ids)
    if cur.rowcount:
        summary["projects"] = cur.rowcount
    for table in ("projects",) + _TABLES_WITH_USER_ID:
        if conn.execute(f"SELECT 1 FROM {table} WHERE user_id IN ({marks}) LIMIT 1", user_ids).fetchone():
            raise DemoCleanupError("Demo disposal post-condition failed")


def _cleanup(*, cutoff: str | None) -> dict:
    from app.persistence.db import get_connection

    conn = get_connection()
    summary: dict[str, int] = {}
    try:
        with _disposal_transaction(conn):
            owners = (_find_expired_demo_users(conn, cutoff) if cutoff is not None
                      else sorted(_demo_activity(conn)))
            _delete_owned_state(conn, owners, summary)
    finally:
        conn.close()
    logger.info("demo_cleanup: committed terminal disposal %s", summary)
    return summary


def cleanup_expired_demo_data(ttl_hours: int = DEMO_TTL_HOURS) -> dict:
    """Atomically dispose only sessions whose latest activity is beyond TTL."""
    return _cleanup(cutoff=_cutoff_iso(ttl_hours))


def cleanup_all_demo_data() -> dict:
    """Explicit operator/test reset: terminal disposal of complete demo sessions.

    Production entry is the safety-gated tools/demo_reset.py, not a ledger
    mutation API. Fresh sessions are included; protected/permanent data is not.
    """
    return _cleanup(cutoff=None)


def _bootstrap_preflight(conn: sqlite3.Connection) -> list[str]:
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise DemoCleanupError("Bootstrap refuses inconsistent foreign-key state")
    for table in ("projects",) + _TABLES_WITH_USER_ID:
        for row in conn.execute(f"SELECT DISTINCT user_id FROM {table}"):
            owner = row["user_id"]
            if owner != "__reference__" and not owner.startswith(DEMO_USER_ID_PREFIX):
                raise DemoCleanupError("Bootstrap refuses permanent/admin state before mutation")
    owners = sorted(_demo_activity(conn))
    _validate_owned_state(conn, owners)
    return owners


def _bootstrap_postcondition(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM projects WHERE user_id='__reference__'").fetchone()[0] != 5:
        raise ValueError("bootstrap_staging_db post-condition failed: expected 5 canonical references")
    for table in ("projects",) + _TABLES_WITH_USER_ID:
        if conn.execute(f"SELECT 1 FROM {table} WHERE user_id != '__reference__' LIMIT 1").fetchone():
            raise ValueError(f"bootstrap_staging_db post-condition failed: {table}")


def bootstrap_staging_db(conn: sqlite3.Connection) -> dict:
    """Bounded demo reset; existing references remain byte-for-byte untouched.

    An empty database uses the standard, non-destructive reference initializer.
    Existing demo databases must already have their references initialized:
    the multi-connection initializer cannot participate in disposal's transaction.
    Permanent/admin/protected data refuses the reset before any modification.
    """
    summary: dict = {"deleted": {}, "seeded": 0}
    initialize = False
    with _disposal_transaction(conn):
        owners = _bootstrap_preflight(conn)
        ref_count = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id='__reference__'").fetchone()[0]
        if ref_count == 0:
            if owners:
                raise DemoCleanupError("Initialize references before resetting existing demo state")
            initialize = True
        else:
            if ref_count != 5:
                raise DemoCleanupError("Bootstrap refuses incomplete reference state")
            _delete_owned_state(conn, owners, summary["deleted"])
            _bootstrap_postcondition(conn)
    if initialize:
        # No destructive statements have run. Reuse the existing initializer,
        # never mutate existing reference evidence as part of a session reset.
        from app.services.project_library_service import ensure_reference_models
        summary["seeded"] = len(ensure_reference_models())
        _bootstrap_postcondition(conn)
    summary["post_condition"] = "PASS"
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(cleanup_expired_demo_data())
