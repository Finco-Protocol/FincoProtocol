"""Tests-only OFFLINE seeding of historical / noncanonical ``workspace_states`` values.

WF03 (C2) installs a per-APPLICATION-connection TEMP trigger that refuses dirty->clean transitions and changes to
``last_runtime_snapshot_id`` / ``last_runtime_composite_hash`` outside the authoritative repository writers. Some tests
must start from an OLD or CORRUPT persisted shape (legacy rows, stale composite hash, deliberately synthetic committed
identity) and then prove that the normal application read/recovery paths behave correctly. Such a state cannot be made
through the guarded app path, so it is written here by a separate raw ``sqlite3`` connection (the TEMP trigger is
connection-local; a raw file writer is the documented, separate trust boundary).

Safeguards: explicit path required (never defaults to the production path), the path must be the disposable database
currently configured as ``db.DB_PATH`` and must not be the production default, a single explicit transaction, a
precise ``user_id`` + ``project_id`` predicate that must match exactly one row, closed afterwards. Never import this from
``app/``; never use it to perform production mutations.
"""
from __future__ import annotations

import os
import sqlite3

from app.persistence import db

_ALLOWED_COLUMNS = frozenset({
    "dirty", "any_run_committed", "last_runtime_snapshot_id", "last_runtime_composite_hash",
    "last_runtime_summary_json", "last_runtime_scenario_id", "last_runtime_at", "last_runtime_identity_json",
    "last_integrity_evidence_json", "last_sponsor_schedule_json",
})


def seed_historical_workspace_state(db_path: str, user_id: str, project_id: str, **columns) -> None:
    if not db_path:
        raise ValueError("explicit database path required")
    real = os.path.realpath(db_path)
    production = os.path.realpath(os.path.join(db.DATA_DIR, "finco_runs.db"))
    if real == production:
        raise ValueError("refusing to seed the production database path")
    if real != os.path.realpath(db.DB_PATH):
        raise ValueError("path is not the disposable test database currently configured as db.DB_PATH")
    if not os.path.exists(real):
        raise ValueError("test database does not exist")
    unknown = set(columns) - _ALLOWED_COLUMNS
    if not columns or unknown:
        raise ValueError(f"unsupported columns: {sorted(unknown)}")
    names = sorted(columns)
    conn = sqlite3.connect(real, timeout=30.0, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                f"UPDATE workspace_states SET {', '.join(n + '=?' for n in names)} WHERE user_id=? AND project_id=?",
                tuple(columns[n] for n in names) + (user_id, project_id))
            if cur.rowcount != 1:
                raise AssertionError(f"offline fixture must match exactly one workspace row, matched {cur.rowcount}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
