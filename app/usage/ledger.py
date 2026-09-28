"""B2.3 Usage/Metering — append-only usage event ledger.

Append-only: events are never updated or deleted.
Idempotency: repeated delivery of the same idempotency_key records one event.
Concurrent safety: SQLite UNIQUE constraint + WAL mode serialises duplicates.

No financial math. No verification truth. No billing engine.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from app.usage.contracts import (
    USAGE_AUTHORITY,
    USAGE_SCHEMA,
    UsageEvent,
    _sanitise_metadata,
)


# ── Storage protocol ────────────────────────────────────────────────────────────────────

@runtime_checkable
class UsageLedgerStore(Protocol):
    """Write-only storage interface for usage events."""

    def record(self, event: UsageEvent) -> UsageEvent:
        """Persist one event; return it (or the existing event if already recorded)."""
        ...

    def get_by_idempotency_key(self, idempotency_key: str) -> UsageEvent | None:
        """Return the event for this idempotency key, or None."""
        ...


# ── SQLite store ────────────────────────────────────────────────────────────────────────

class SQLiteUsageLedgerStore:
    """SQLite-backed append-only usage ledger.

    The usage_events table is created lazily via _ensure_usage_schema().
    The UNIQUE(idempotency_key) constraint serialises concurrent duplicates:
    the loser of a race gets an IntegrityError and reads back the winner's row.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path  # None → use default from app.persistence.db

    def _get_conn(self):
        if self._db_path is not None:
            import sqlite3
            conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            _ensure_usage_schema(conn)
            return conn
        from app.persistence.db import get_connection
        conn = get_connection()
        _ensure_usage_schema(conn)
        return conn

    def record(self, event: UsageEvent) -> UsageEvent:
        import sqlite3
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO usage_events (
                    event_id, idempotency_key, subject_id, wallet_address,
                    feature_key, quantity, unit,
                    occurred_at, recorded_at, authority, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.idempotency_key,
                    event.subject_id,
                    event.wallet_address,
                    event.feature_key,
                    event.quantity,
                    event.unit,
                    event.occurred_at.isoformat(),
                    event.recorded_at.isoformat(),
                    event.authority,
                    json.dumps(event.metadata),
                ),
            )
            conn.commit()
            # Return the canonical row (ours if inserted, existing if duplicate)
            row = conn.execute(
                "SELECT * FROM usage_events WHERE idempotency_key = ?",
                (event.idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_event(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> UsageEvent | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM usage_events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_event(row) if row is not None else None


def _ensure_usage_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id          TEXT    NOT NULL UNIQUE,
            idempotency_key   TEXT    NOT NULL UNIQUE,
            subject_id        TEXT    NOT NULL,
            wallet_address    TEXT,
            feature_key       TEXT    NOT NULL,
            quantity          INTEGER NOT NULL,
            unit              TEXT    NOT NULL,
            occurred_at       TEXT    NOT NULL,
            recorded_at       TEXT    NOT NULL,
            authority         TEXT    NOT NULL DEFAULT 'B2_3_V1',
            metadata_json     TEXT    NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_subject_feature"
        " ON usage_events(subject_id, feature_key, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_subject_occurred"
        " ON usage_events(subject_id, occurred_at DESC)"
    )


def _row_to_event(row) -> UsageEvent:
    occurred = datetime.fromisoformat(row["occurred_at"])
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    recorded = datetime.fromisoformat(row["recorded_at"])
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    raw_meta = row["metadata_json"] or "{}"
    try:
        metadata = json.loads(raw_meta)
    except (ValueError, TypeError):
        metadata = {}
    return UsageEvent(
        event_id=row["event_id"],
        idempotency_key=row["idempotency_key"],
        subject_id=row["subject_id"],
        wallet_address=row["wallet_address"],
        feature_key=row["feature_key"],
        quantity=row["quantity"],
        unit=row["unit"],
        occurred_at=occurred,
        recorded_at=recorded,
        authority=row["authority"],
        metadata=metadata,
    )


# ── In-memory store (for testing) ──────────────────────────────────────────────────────────────

class InMemoryUsageLedgerStore:
    """Thread-safe in-memory usage ledger for deterministic tests."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._by_idempotency: dict[str, UsageEvent] = {}
        self._events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> UsageEvent:
        with self._lock:
            existing = self._by_idempotency.get(event.idempotency_key)
            if existing is not None:
                return existing
            self._by_idempotency[event.idempotency_key] = event
            self._events.append(event)
            return event

    def get_by_idempotency_key(self, idempotency_key: str) -> UsageEvent | None:
        with self._lock:
            return self._by_idempotency.get(idempotency_key)

    def all_events(self) -> list[UsageEvent]:
        with self._lock:
            return list(self._events)


# ── Recorder ───────────────────────────────────────────────────────────────────────────────

class UsageRecorder:
    """Primary write surface for B2.3.

    Callers supply feature_key, quantity, unit, and optional metadata.
    subject_id is always derived from a verified session object — never
    accepted as a caller-supplied string.

    Usage recording is always performed AFTER the B2.2 access decision.
    The outcome of usage recording must never affect financial math or
    verification truth.
    """

    def __init__(self, store: UsageLedgerStore | None = None) -> None:
        self._store: UsageLedgerStore = store or SQLiteUsageLedgerStore()

    def record(
        self,
        *,
        session,
        feature_key: str,
        quantity: int = 1,
        unit: str = "request",
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict | None = None,
        wallet_address: str | None = None,
    ) -> UsageEvent:
        """Record one usage event for the authenticated session.

        session must be a SessionData (or SessionData-compatible) object from
        app.auth.resolve_request_session — never a raw user_id string.
        """
        subject_id: str = session.user_id
        now = datetime.now(timezone.utc)
        event = UsageEvent(
            event_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            subject_id=subject_id,
            wallet_address=wallet_address,
            feature_key=feature_key,
            quantity=quantity,
            unit=unit,
            occurred_at=occurred_at if occurred_at is not None else now,
            recorded_at=now,
            authority=USAGE_AUTHORITY,
            metadata=metadata or {},
        )
        return self._store.record(event)


# ── Default singleton ───────────────────────────────────────────────────────────────────

_default_recorder: UsageRecorder | None = None


def get_recorder() -> UsageRecorder:
    """Return the process-level default UsageRecorder (SQLite-backed)."""
    global _default_recorder
    if _default_recorder is None:
        _default_recorder = UsageRecorder()
    return _default_recorder
