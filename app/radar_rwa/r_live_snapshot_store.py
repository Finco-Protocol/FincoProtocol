"""Persistent latest-snapshot projection for canonical R-LIVE observations.

Instant R-LIVE UX (master stream): background canonical acquisition writes
the latest completed observation per approved asset into ONE small SQLite
table; web presentation reads this snapshot instantly and never triggers
live chain acquisition.

Evidence integrity rules (non-negotiable):
  - the stored ``payload`` is the byte-exact canonical JSON of the
    acquisition row ``(canonical_id, state, data)`` — evidence timestamps
    (retrieved_at, observed_at, block timestamp, pool activity, quote
    updated) are NEVER rewritten, re-stamped or refreshed by this store;
  - ``collected_at`` is separate collector-clock metadata (when the batch
    wrote the snapshot), never mixed into evidence;
  - writes are atomic: one transaction upserts every row of a batch, so a
    reader always sees a consistent complete batch;
  - a failed refresh must not destroy the last valid snapshot: rows whose
    acquisition state is UNAVAILABLE are deliberately NOT written — the
    previously stored valid observation is kept and is re-evaluated to
    STALE/UNAVAILABLE at read time by the freshness view instead;
  - readers open the database read-only and perform zero network I/O.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

SNAPSHOT_SCHEMA_VERSION = "finco-r-live-snapshot-v1"

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "r_live_snapshots.db")

# States that may overwrite the stored latest observation.  A live
# UNAVAILABLE outcome is an acquisition failure, not new market evidence:
# keeping the prior valid row (later re-evaluated stale) preserves the last
# valid snapshot across transient RPC failures.
_STOREABLE_STATES = frozenset({"AVAILABLE", "STALE"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS r_live_latest_snapshot (
    canonical_id    TEXT PRIMARY KEY,
    state           TEXT NOT NULL,
    payload         TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    collected_at    TEXT NOT NULL,
    schema_version  TEXT NOT NULL
)
"""


def _db_path(path: str | None = None) -> str:
    return path or os.getenv("R_LIVE_SNAPSHOT_DB_PATH", DEFAULT_DB_PATH)


def _utc_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SNAPSHOT_CLOCK_MUST_BE_AWARE")
    return value.astimezone(timezone.utc).isoformat()


class RLiveSnapshotStore:
    """Durable latest-observation projection (one row per approved asset)."""

    def __init__(self, *, path: str | None = None) -> None:
        self.path = _db_path(path)
        if self.path == ":memory:":
            # Allow :memory: for tests only via explicit path "file::memory:"
            location = ":memory:"
        else:
            location = self.path
            Path(location).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(location, timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RLiveSnapshotStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def write_batch(
        self,
        rows: Iterable[tuple[str, str, dict]],
        *,
        collected_at: datetime | None = None,
    ) -> int:
        """Atomically upsert one batch of acquisition rows.

        The payload stored is the canonical JSON of the row exactly as the
        acquisition authority produced it (sorted keys, compact separators,
        UTF-8) — no timestamp rewriting, no enrichment.  UNAVAILABLE rows
        are skipped so a failed refresh never destroys the last valid
        snapshot.  Returns the number of rows written.
        """
        stamp = _utc_iso(collected_at)
        written = 0
        with self._conn:  # one transaction: readers see a complete batch
            for canonical_id, state, data in rows:
                if state not in _STOREABLE_STATES:
                    continue
                payload = json.dumps(
                    {"canonical_id": canonical_id, "state": state, "data": data},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode("utf-8")
                digest = hashlib.sha256(payload).hexdigest()
                self._conn.execute(
                    "INSERT INTO r_live_latest_snapshot "
                    "(canonical_id,state,payload,evidence_digest,collected_at,schema_version) "
                    "VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(canonical_id) DO UPDATE SET "
                    "state=excluded.state,payload=excluded.payload,"
                    "evidence_digest=excluded.evidence_digest,"
                    "collected_at=excluded.collected_at,"
                    "schema_version=excluded.schema_version",
                    (canonical_id, state, payload.decode("utf-8"), digest, stamp,
                     SNAPSHOT_SCHEMA_VERSION),
                )
                written += 1
        return written

    def _read(self, canonical_id: str | None = None):
        if canonical_id is None:
            return self._conn.execute(
                "SELECT canonical_id,state,payload,evidence_digest,collected_at "
                "FROM r_live_latest_snapshot ORDER BY canonical_id"
            ).fetchall()
        return self._conn.execute(
            "SELECT canonical_id,state,payload,evidence_digest,collected_at "
            "FROM r_live_latest_snapshot WHERE canonical_id=?",
            (canonical_id,),
        ).fetchall()


def _parse_rows(rows) -> list[dict]:
    parsed: list[dict] = []
    for canonical_id, state, payload, digest, collected_at in rows:
        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            continue  # corrupt row is never served; fail closed per asset
        if hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
        ).hexdigest() != digest:
            continue  # digest-verified reads: tampered rows are dropped
        parsed.append({
            "canonical_id": canonical_id,
            "state": state,
            "payload": body,
            "evidence_digest": digest,
            "collected_at": collected_at,
        })
    return parsed


def read_snapshots_readonly(*, path: str | None = None,
                            canonical_id: Optional[str] = None) -> list[dict]:
    """Digest-verified snapshot read. Zero writes, zero network, zero waits."""
    location = _db_path(path)
    if location != ":memory:" and not Path(location).is_file():
        return []
    if location == ":memory:":
        return []
    uri = Path(location).resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            if canonical_id is None:
                rows = conn.execute(
                    "SELECT canonical_id,state,payload,evidence_digest,collected_at "
                    "FROM r_live_latest_snapshot ORDER BY canonical_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT canonical_id,state,payload,evidence_digest,collected_at "
                    "FROM r_live_latest_snapshot WHERE canonical_id=?",
                    (canonical_id,),
                ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return _parse_rows(rows)


def snapshot_exists_readonly(*, path: str | None = None) -> bool:
    location = _db_path(path)
    if location == ":memory:" or not Path(location).is_file():
        return False
    uri = Path(location).resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            row = conn.execute(
                "SELECT 1 FROM r_live_latest_snapshot LIMIT 1"
            ).fetchone()
    except (sqlite3.Error, OSError):
        return False
    return row is not None
