"""Per-user alert + checkpoint persistence for Yield Alerts V1 (Agent A).

Uses the existing FINCO lazy SQLite-table convention (``FINCO_DB_PATH``).
Two narrow tables:

``yield_alerts`` — per-user typed alert records with deterministic
``alert_id`` PRIMARY KEY (same logical transition → same alert_id →
exactly one persisted record).

``yield_alert_state`` — per-user/per-opportunity evaluation checkpoint
(last processed observation hash, last freshness state, last support
state, the watch lifecycle stamp, evaluated_at).

Persistence guarantee (final correction): ``commit_alert_state`` is THE
one narrow transactional operation for evaluation — it inserts alert
records AND advances the checkpoint in a SINGLE SQLite transaction.
A checkpoint can therefore never advance past an alert event that has
not been durably persisted: any failure inside the transaction rolls
the whole unit back (alerts + checkpoint together), and a retry
re-derives the same transitions with the same deterministic alert_ids.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS yield_alerts (
    alert_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    opportunity_uid TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    field TEXT,
    previous_value_json TEXT,
    current_value_json TEXT,
    previous_observation_hash TEXT NOT NULL,
    current_observation_hash TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    read_at TEXT
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_yield_alerts_user_read
ON yield_alerts (user_id, read_at, detected_at)
"""

_CHECKPOINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS yield_alert_state (
    user_id TEXT NOT NULL,
    opportunity_uid TEXT NOT NULL,
    last_processed_observation_hash TEXT NOT NULL,
    last_freshness_state TEXT,
    last_support_state TEXT,
    watch_saved_at TEXT,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, opportunity_uid)
)
"""


def _db_path() -> str:
    import os
    return os.getenv("FINCO_DB_PATH",
                     str(Path(__file__).resolve().parents[1] / "data" / "finco_runs.db"))


def _ensure_checkpoint_columns(conn: sqlite3.Connection) -> None:
    """Lazy migration for checkpoints created by earlier builds."""
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(yield_alert_state)").fetchall()
    }
    if "watch_saved_at" not in columns:
        conn.execute("ALTER TABLE yield_alert_state ADD COLUMN watch_saved_at TEXT")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.execute(_CREATE_INDEX)
    conn.execute(_CHECKPOINT_SCHEMA)
    _ensure_checkpoint_columns(conn)
    conn.commit()
    return conn


def _utc_iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_ALERT_COLUMNS = (
    "alert_id, user_id, opportunity_uid, alert_type, label, field, "
    "previous_value_json, current_value_json, previous_observation_hash, "
    "current_observation_hash, detected_at, read_at"
)


def _insert_alert(conn: sqlite3.Connection, user_id: str, alert: dict[str, Any]) -> bool:
    """Insert ONE alert if its deterministic id is new. True when inserted."""
    alert_id = alert["alert_id"]
    already = conn.execute(
        "SELECT 1 FROM yield_alerts WHERE alert_id=?", (alert_id,)).fetchone()
    if already is not None:
        return False
    conn.execute(
        f"INSERT INTO yield_alerts ({_ALERT_COLUMNS}) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
        (alert_id, user_id, alert["opportunity_uid"],
         alert["alert_type"], alert.get("label", ""),
         alert.get("field"),
         json.dumps(alert["previous"]) if alert.get("previous") is not None else None,
         json.dumps(alert["current"]) if alert.get("current") is not None else None,
         alert["previous_observation_hash"],
         alert["current_observation_hash"],
         alert["detected_at"]))
    return True


# ── Transactional evaluation commit ───────────────────────────────────────────

def commit_alert_state(
    user_id: str, opportunity_uid: str, alerts: list[dict[str, Any]], *,
    last_processed_observation_hash: str,
    last_freshness_state: str | None,
    last_support_state: str | None,
    watch_saved_at: str | None = None,
) -> list[dict[str, Any]]:
    """Persist alert inserts AND advance the checkpoint ATOMICALLY.

    One SQLite transaction: every alert insert plus the checkpoint
    upsert commit together or roll back together.  If any statement
    fails, no alert is durable and the checkpoint keeps its previous
    value — it can never advance past unpersisted alert events.

    Deterministic ``alert_id`` makes retries safe: an already-committed
    alert is skipped (not duplicated) while the checkpoint still advances.

    Returns the list of newly inserted alert dicts (deduped ones skipped).
    """
    conn = _connect()
    try:
        with conn:
            created: list[dict[str, Any]] = []
            for alert in alerts:
                if _insert_alert(conn, user_id, alert):
                    created.append(alert)
            conn.execute(
                "INSERT INTO yield_alert_state "
                "(user_id, opportunity_uid, last_processed_observation_hash, "
                " last_freshness_state, last_support_state, watch_saved_at, "
                " evaluated_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT (user_id, opportunity_uid) DO UPDATE SET "
                "last_processed_observation_hash=excluded.last_processed_observation_hash, "
                "last_freshness_state=excluded.last_freshness_state, "
                "last_support_state=excluded.last_support_state, "
                "watch_saved_at=excluded.watch_saved_at, "
                "evaluated_at=excluded.evaluated_at",
                (user_id, opportunity_uid, last_processed_observation_hash,
                 last_freshness_state, last_support_state, watch_saved_at,
                 _utc_iso_now()))
        return created
    finally:
        conn.close()


# ── Alert records (plain inserts; evaluation uses commit_alert_state) ─────────

def create_alerts(user_id: str, alerts: list[dict[str, Any]], *,
                  dedupe: bool = True) -> list[dict[str, Any]]:
    """Persist typed alert dicts WITHOUT touching the checkpoint.

    Deterministic dedupe on alert_id.  Returns newly created alert dicts.
    """
    if not alerts:
        return []
    conn = _connect()
    try:
        with conn:
            created: list[dict[str, Any]] = []
            for alert in alerts:
                if not dedupe or _insert_alert(conn, user_id, alert):
                    created.append(alert)
        return created
    finally:
        conn.close()


def list_alerts(user_id: str, *, unread_only: bool = False) -> list[dict[str, Any]]:
    """List the user's alerts (newest first)."""
    conn = _connect()
    try:
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM yield_alerts WHERE user_id=? AND read_at IS NULL "
                "ORDER BY detected_at DESC", (user_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM yield_alerts WHERE user_id=? "
                "ORDER BY detected_at DESC", (user_id,)).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def mark_read(user_id: str, alert_id: str) -> bool:
    """Mark ONE alert read by deterministic alert_id.

    Returns True when the alert exists, belongs to the user, and was
    previously unread.  Unknown alert_id for that user → False (no mutation).
    User A can never mutate User B's alert (user_id is in the WHERE clause).
    """
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE yield_alerts SET read_at=? "
            "WHERE alert_id=? AND user_id=? AND read_at IS NULL",
            (_utc_iso_now(), alert_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_all_read(user_id: str) -> int:
    """Mark ALL the user's unread alerts read.  Returns marked count."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE yield_alerts SET read_at=? "
            "WHERE user_id=? AND read_at IS NULL",
            (_utc_iso_now(), user_id))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def unread_count(user_id: str) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM yield_alerts "
            "WHERE user_id=? AND read_at IS NULL", (user_id,)).fetchone()
        return row["n"]
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    previous = json.loads(row["previous_value_json"]) if row["previous_value_json"] else None
    current = json.loads(row["current_value_json"]) if row["current_value_json"] else None
    return {
        "alert_id": row["alert_id"],
        "user_id": row["user_id"],
        "opportunity_uid": row["opportunity_uid"],
        "alert_type": row["alert_type"],
        "label": row["label"],
        "field": row["field"],
        "previous": previous,
        "current": current,
        "previous_observation_hash": row["previous_observation_hash"],
        "current_observation_hash": row["current_observation_hash"],
        "detected_at": row["detected_at"],
        "read": row["read_at"] is not None,
    }


# ── Checkpoint state ─────────────────────────────────────────────────────────

def get_checkpoint(user_id: str, opportunity_uid: str) -> dict[str, Any] | None:
    """Return the checkpoint for (user, opportunity) or None if absent."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM yield_alert_state "
            "WHERE user_id=? AND opportunity_uid=?",
            (user_id, opportunity_uid)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "opportunity_uid": row["opportunity_uid"],
        "last_processed_observation_hash": row["last_processed_observation_hash"],
        "last_freshness_state": row["last_freshness_state"],
        "last_support_state": row["last_support_state"],
        "watch_saved_at": row["watch_saved_at"],
        "evaluated_at": row["evaluated_at"],
    }


def set_checkpoint(user_id: str, opportunity_uid: str, *,
                   last_processed_observation_hash: str,
                   last_freshness_state: str | None,
                   last_support_state: str | None,
                   watch_saved_at: str | None = None) -> None:
    """Upsert the checkpoint alone (baseline / re-watch lifecycle reset).

    Baselines carry no alert inserts, so a single atomic upsert preserves
    the persistence guarantee.
    """
    return commit_alert_state(
        user_id, opportunity_uid, [],
        last_processed_observation_hash=last_processed_observation_hash,
        last_freshness_state=last_freshness_state,
        last_support_state=last_support_state,
        watch_saved_at=watch_saved_at)


def remove_checkpoint(user_id: str, opportunity_uid: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM yield_alert_state "
            "WHERE user_id=? AND opportunity_uid=?",
            (user_id, opportunity_uid))
        conn.commit()
    finally:
        conn.close()
