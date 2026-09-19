"""Durable append-only snapshot store (P8).

SQLite persistence following the repository's established persistence
conventions (``app.persistence.db``: WAL, busy_timeout, env-overridable
path) but in a SEPARATE, dedicated database so the acquisition snapshot
ledger stays isolated and strictly append-only.

Invariants:
- ``snapshot_id`` is the primary/unique identity;
- the canonical payload is persisted verbatim;
- duplicate identical inserts are idempotent;
- the same ``snapshot_id`` with different payload is a hard failure;
- no update or delete API exists at all;
- snapshots survive process/service restart;
- reads are by exact ``snapshot_id`` and perform ZERO network calls.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .contracts import (
    AcquisitionSnapshot,
    RadarRuntimeError,
    canonical_json_bytes,
)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "radar_runtime.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS acquisition_snapshots (
    snapshot_id          TEXT PRIMARY KEY,
    request_fingerprint  TEXT NOT NULL,
    payload              TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    acquired_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acq_snap_fingerprint
    ON acquisition_snapshots (request_fingerprint);
"""


class SnapshotStore:
    """Append-only SQLite-backed snapshot store."""

    def __init__(self, path: "str | None" = None) -> None:
        db_path = path or os.getenv("RADAR_RUNTIME_DB_PATH", DEFAULT_DB_PATH)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            db_path, timeout=30.0, isolation_level=None,
            check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    # -- write path (append-only) ------------------------------------------
    def put(self, snapshot: AcquisitionSnapshot) -> str:
        """Insert one snapshot.  Returns "created" or "existing".

        Idempotent for byte-identical duplicates; the same snapshot_id
        with different content is a hard :class:`SnapshotConflictError`.
        There is no update or delete path."""
        payload = snapshot.to_payload()
        payload_text = canonical_json_bytes(payload).decode("utf-8")
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO acquisition_snapshots (snapshot_id, "
                    "request_fingerprint, payload, created_at, acquired_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (snapshot.snapshot_id, snapshot.request_fingerprint,
                     payload_text, snapshot.started_at, snapshot.completed_at))
                return "created"
            except sqlite3.IntegrityError:
                existing = self._conn.execute(
                    "SELECT payload FROM acquisition_snapshots "
                    "WHERE snapshot_id = ?",
                    (snapshot.snapshot_id,)).fetchone()
                if existing is not None and existing["payload"] == payload_text:
                    return "existing"
                raise RadarRuntimeError(
                    "snapshot conflict: snapshot_id "
                    f"{snapshot.snapshot_id} already exists with different "
                    "content") from None

    # -- read path (network-free, P14) --------------------------------------
    def get(self, snapshot_id: str) -> "AcquisitionSnapshot | None":
        """Read one snapshot by exact id.  Performs zero provider/network
        calls and never mutates the stored payload."""
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id, payload FROM acquisition_snapshots "
                "WHERE snapshot_id = ?",
                (snapshot_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        snapshot = AcquisitionSnapshot.from_payload(payload)
        if snapshot.snapshot_id != row["snapshot_id"]:
            raise RadarRuntimeError(
                "stored snapshot content does not reconstruct its "
                "snapshot_id (corrupted ledger)")
        return snapshot

    def snapshot_ids_for_fingerprint(
        self, request_fingerprint: str
    ) -> "list[str]":
        with self._lock:
            rows = self._conn.execute(
                "SELECT snapshot_id FROM acquisition_snapshots "
                "WHERE request_fingerprint = ? ORDER BY created_at",
                (request_fingerprint,)).fetchall()
        return [r["snapshot_id"] for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
