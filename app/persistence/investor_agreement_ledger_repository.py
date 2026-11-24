"""Durable monotonic/tombstone (agreement_id, version) ledger for F4 investor agreements (C1F-B-2).

Prevents (agreement_id, version) reuse after working-agreement removal or rename
(e.g. AGR-1 v2 -> remove -> AGR-1 v1, or AGR-1 v2 -> AGR-2 v1 -> AGR-1 v1)
while scoping strictly by (owner_id, project_id, scenario_id, agreement_id).
"""
from __future__ import annotations

import sqlite3

from app.persistence.db import get_connection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investor_agreement_version_ledger (
    owner_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL DEFAULT '',
    agreement_id TEXT NOT NULL,
    max_version INTEGER NOT NULL CHECK (max_version >= 1),
    tombstoned_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, project_id, scenario_id, agreement_id)
);
CREATE INDEX IF NOT EXISTS idx_investor_agreement_ledger_scope
    ON investor_agreement_version_ledger (owner_id, project_id, scenario_id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the investor_agreement_version_ledger table idempotently."""
    conn.executescript(_SCHEMA)
    conn.commit()


def get_max_version(
    cur: sqlite3.Cursor,
    *,
    owner_id: str,
    project_id: str,
    scenario_id: str,
    agreement_id: str,
) -> int:
    """Return the highest committed version ever used for this agreement_id in scope, or 0."""
    row = cur.execute(
        """
        SELECT max_version FROM investor_agreement_version_ledger
        WHERE owner_id = ? AND project_id = ? AND scenario_id = ? AND agreement_id = ?
        """,
        (owner_id, project_id, scenario_id or "", agreement_id),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def record_version(
    cur: sqlite3.Cursor,
    *,
    owner_id: str,
    project_id: str,
    scenario_id: str,
    agreement_id: str,
    version: int,
    updated_at: str,
    tombstoned_at: str | None = None,
) -> None:
    """Record a strictly monotonic version for (owner_id, project_id, scenario_id, agreement_id)."""
    cur.execute(
        """
        INSERT INTO investor_agreement_version_ledger (
            owner_id, project_id, scenario_id, agreement_id, max_version, tombstoned_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner_id, project_id, scenario_id, agreement_id) DO UPDATE SET
            max_version = CASE
                WHEN excluded.max_version > investor_agreement_version_ledger.max_version
                THEN excluded.max_version
                ELSE investor_agreement_version_ledger.max_version
            END,
            tombstoned_at = excluded.tombstoned_at,
            updated_at = excluded.updated_at
        """,
        (owner_id, project_id, scenario_id or "", agreement_id, int(version), tombstoned_at, updated_at),
    )


def tombstone_agreement(
    cur: sqlite3.Cursor,
    *,
    owner_id: str,
    project_id: str,
    scenario_id: str,
    agreement_id: str,
    min_version: int,
    now_iso: str,
) -> None:
    """Tombstone an agreement_id on remove or rename so prior versions can never be reused."""
    existing = get_max_version(
        cur,
        owner_id=owner_id,
        project_id=project_id,
        scenario_id=scenario_id,
        agreement_id=agreement_id,
    )
    record_version(
        cur,
        owner_id=owner_id,
        project_id=project_id,
        scenario_id=scenario_id,
        agreement_id=agreement_id,
        version=max(existing, int(min_version)),
        updated_at=now_iso,
        tombstoned_at=now_iso,
    )


def next_version_for_agreement(
    owner_id: str,
    project_id: str,
    scenario_id: str,
    agreement_id: str,
    *,
    current_version: int = 0,
) -> int:
    """Return the next strictly monotonic version number for agreement_id in scope."""
    if not agreement_id:
        return 1
    conn = get_connection()
    try:
        ledger_max = get_max_version(
            conn.cursor(),
            owner_id=owner_id,
            project_id=project_id,
            scenario_id=scenario_id or "",
            agreement_id=agreement_id,
        )
        return max(ledger_max, int(current_version)) + 1
    finally:
        conn.close()
