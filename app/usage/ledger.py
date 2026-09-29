"""B2.3 Usage/Metering — append-only usage event ledger.

Append-only: events are never updated or deleted.
Idempotency: repeated delivery of the same (subject_id, feature_key,
idempotency_key) tuple records one event. Cross-user and cross-feature
collisions on idempotency_key are safe: the UNIQUE constraint is scoped.
Concurrent safety: SQLite UNIQUE constraint + WAL mode serialises duplicates.
SQLITE_LOCKED (intra-process same-db contention) is handled by _acquire_immediate()
with bounded retry + jitter; SQLITE_BUSY is handled by the db-level busy_timeout.
Non-lock OperationalErrors are never swallowed.

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

    def get_by_scoped_key(
        self, subject_id: str, feature_key: str, idempotency_key: str
    ) -> UsageEvent | None:
        """Return the event for this (subject_id, feature_key, idempotency_key), or None."""
        ...


# ── SQLite store ────────────────────────────────────────────────────────────────────────

class SQLiteUsageLedgerStore:
    """SQLite-backed append-only usage ledger.

    The usage_events table is created lazily via _ensure_usage_schema().
    The UNIQUE(subject_id, feature_key, idempotency_key) constraint scopes
    idempotency per subject and feature — cross-user and cross-feature key
    collisions are independent and safe.
    BEGIN IMMEDIATE + explicit IntegrityError handling serialises concurrent
    duplicates without broad INSERT OR IGNORE suppression.
    Schema initialisation is serialised per-instance so concurrent calls to
    record() do not race on DDL (which cannot be retried by busy_timeout).
    """

    def __init__(self, db_path: str | None = None) -> None:
        import threading
        self._db_path = db_path  # None → use default from app.persistence.db
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def _ensure_schema(self, conn) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if not self._schema_ready:
                # WAL mode is a DB-level write needing an exclusive lock; serialised
                # here so concurrent threads don't race on it.  Connections that skip
                # this block inherit WAL automatically once the DB is in WAL mode.
                conn.execute("PRAGMA journal_mode=WAL")
                _maybe_migrate_usage_v0(conn)
                _ensure_usage_schema(conn)
                self._schema_ready = True

    def _get_conn(self):
        if self._db_path is not None:
            import sqlite3
            conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            # busy_timeout is per-connection; no DB lock needed.
            conn.execute("PRAGMA busy_timeout=30000")
            # journal_mode=WAL is serialised inside _ensure_schema.
            self._ensure_schema(conn)
            return conn
        from app.persistence.db import get_connection
        conn = get_connection()
        self._ensure_schema(conn)
        return conn

    def record(self, event: UsageEvent) -> UsageEvent:
        import sqlite3
        conn = self._get_conn()
        try:
            _acquire_immediate(conn)
            existing = conn.execute(
                "SELECT * FROM usage_events"
                " WHERE subject_id = ? AND feature_key = ? AND idempotency_key = ?",
                (event.subject_id, event.feature_key, event.idempotency_key),
            ).fetchone()
            if existing is not None:
                conn.execute("ROLLBACK")
                return _row_to_event(existing)
            try:
                conn.execute(
                    """
                    INSERT INTO usage_events (
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
            except sqlite3.IntegrityError:
                # Another writer beat us; read back the canonical row.
                conn.execute("ROLLBACK")
                row = conn.execute(
                    "SELECT * FROM usage_events"
                    " WHERE subject_id = ? AND feature_key = ? AND idempotency_key = ?",
                    (event.subject_id, event.feature_key, event.idempotency_key),
                ).fetchone()
                if row is not None:
                    return _row_to_event(row)
                # IntegrityError on a different constraint (e.g. UNIQUE event_id) — re-raise.
                raise
            row = conn.execute(
                "SELECT * FROM usage_events"
                " WHERE subject_id = ? AND feature_key = ? AND idempotency_key = ?",
                (event.subject_id, event.feature_key, event.idempotency_key),
            ).fetchone()
            conn.execute("COMMIT")
            return _row_to_event(row)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def get_by_scoped_key(
        self, subject_id: str, feature_key: str, idempotency_key: str
    ) -> UsageEvent | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM usage_events"
                " WHERE subject_id = ? AND feature_key = ? AND idempotency_key = ?",
                (subject_id, feature_key, idempotency_key),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_event(row) if row is not None else None


def _acquire_immediate(conn, max_retries: int = 8) -> None:
    """Issue BEGIN IMMEDIATE with bounded retry for intra-process SQLITE_LOCKED.

    SQLite returns SQLITE_LOCKED (not SQLITE_BUSY) when multiple connections
    within the same Python process compete for the write lock. Neither
    PRAGMA busy_timeout nor sqlite3.connect(timeout=...) retries on SQLITE_LOCKED;
    only SQLITE_BUSY is handled at the SQLite level. This function retries at the
    Python level with exponential backoff + jitter.

    Non-lock OperationalErrors are re-raised immediately without retry.
    """
    import sqlite3
    import time
    import random

    for attempt in range(max_retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise  # unrelated error — never swallowed
            if attempt == max_retries - 1:
                raise  # exhausted retries
            # Exponential backoff with jitter: 10–50 ms base, doubles each attempt,
            # capped at 500 ms.  Jitter prevents thundering herd.
            delay = min(0.5, (0.01 + random.uniform(0, 0.04)) * (2 ** attempt))
            time.sleep(delay)


def _maybe_migrate_usage_v0(conn) -> None:
    """Rename the old single-key-unique table if it exists.

    The original schema had UNIQUE(idempotency_key) as a solo inline constraint.
    If that table is detected, it is renamed to usage_events_v0_deprecated so
    the new scoped-unique schema can be created cleanly.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_events'"
    ).fetchone()
    if row is None:
        return
    # Inspect indexes: look for a unique index covering only idempotency_key.
    indexes = conn.execute(
        "PRAGMA index_list(usage_events)"
    ).fetchall()
    for idx in indexes:
        if not idx["unique"]:
            continue
        idx_info = conn.execute(
            f"PRAGMA index_info({idx['name']})"
        ).fetchall()
        col_names = [c["name"] for c in idx_info]
        if col_names == ["idempotency_key"]:
            # Old solo-unique schema detected — rename and let _ensure_usage_schema
            # create the new table.
            conn.execute(
                "ALTER TABLE usage_events RENAME TO usage_events_v0_deprecated"
            )
            return


def _ensure_usage_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id          TEXT    NOT NULL UNIQUE,
            idempotency_key   TEXT    NOT NULL,
            subject_id        TEXT    NOT NULL,
            wallet_address    TEXT,
            feature_key       TEXT    NOT NULL,
            quantity          INTEGER NOT NULL,
            unit              TEXT    NOT NULL,
            occurred_at       TEXT    NOT NULL,
            recorded_at       TEXT    NOT NULL,
            authority         TEXT    NOT NULL DEFAULT 'B2_3_V1',
            metadata_json     TEXT    NOT NULL DEFAULT '{}',
            UNIQUE(subject_id, feature_key, idempotency_key)
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
    """Thread-safe in-memory usage ledger for deterministic tests.

    Idempotency is scoped to (subject_id, feature_key, idempotency_key) —
    matching the SQLite UNIQUE(subject_id, feature_key, idempotency_key)
    constraint. Cross-user and cross-feature key collisions are safe.
    """

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._by_scoped_key: dict[tuple[str, str, str], UsageEvent] = {}
        self._events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> UsageEvent:
        scoped_key = (event.subject_id, event.feature_key, event.idempotency_key)
        with self._lock:
            existing = self._by_scoped_key.get(scoped_key)
            if existing is not None:
                return existing
            self._by_scoped_key[scoped_key] = event
            self._events.append(event)
            return event

    def get_by_scoped_key(
        self, subject_id: str, feature_key: str, idempotency_key: str
    ) -> UsageEvent | None:
        scoped_key = (subject_id, feature_key, idempotency_key)
        with self._lock:
            return self._by_scoped_key.get(scoped_key)

    def all_events(self) -> list[UsageEvent]:
        with self._lock:
            return list(self._events)


# ── Recorder ───────────────────────────────────────────────────────────────────────────────

class UsageRecorder:
    """Primary write surface for B2.3.

    Callers supply feature_key, quantity, unit, and optional metadata.
    subject_id is always derived from a verified session object — never
    accepted as a caller-supplied string.
    wallet_address is resolved internally from the canonical wallet_auth
    link — never accepted as a caller-supplied argument.

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
    ) -> UsageEvent:
        """Record one usage event for the authenticated session.

        session must be a SessionData (or SessionData-compatible) object from
        app.auth.resolve_request_session — never a raw user_id string.
        wallet_address is resolved from app.protocol.wallet_auth; callers
        cannot supply it directly.
        """
        subject_id: str = session.user_id
        # Resolve canonical wallet address from the authenticated session only.
        # Fail open: if wallet_auth is unavailable, record without wallet identity.
        wallet_address: str | None = None
        try:
            import app.protocol.wallet_auth as _wauth
            link = _wauth.get_verified_wallet(subject_id)
            wallet_address = link["wallet_address"] if link else None
        except Exception:
            wallet_address = None

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
