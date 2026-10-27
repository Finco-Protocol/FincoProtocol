"""RC-M — durable per-user request-id claims: the cross-process fence for React state-changing adapters.

The React New Project wizard must create AT MOST one working copy per ``(user, request id)`` even when several server workers
(separate OS processes) receive the same request at the same time.  An in-process lock cannot give that, and stamping the new
project AFTER it exists leaves a window in which a second worker has already created a duplicate.  This module closes the
window with one uniqueness decision made by the shared database BEFORE any project is written:

* ``claim`` is a single atomic ``INSERT OR IGNORE`` on ``PRIMARY KEY (user_id, request_id, purpose)``; exactly one caller wins.
* The winner writes through the canonical creator, then ``finish`` records the resulting project code; a clean failure is
  recorded with ``fail``.  A crash between ``claim`` and ``finish`` leaves the row ``CLAIMED`` for good.
* A row is NEVER reclaimed, overwritten, expired or retried automatically: every later request with the same id observes the
  existing state (``CLAIMED`` = in flight or crashed, outcome unknown; ``DONE``; ``FAILED``) and creates nothing.  The user
  reconciles in the Project Library and starts a new request id.
* Optional ``rate_limit=(max, window_seconds)`` is evaluated inside the same atomic statement, so a per-user budget holds
  across workers (the canonical in-process demo limiter only counts per process).

Scope and honesty: this fences the React adapter's own creates.  It does not make the canonical creator itself atomic — the
project row and this claim are two writes in one database, not one transaction — and it does not fence the Legacy
``/projects/create`` path.  The exactly-once-at-the-writer change is an owner-gated item
(docs/react_migration/rc_m_integrated/08_OPEN_OWNER_AUTHORIZATIONS.md).  The table is created lazily by this module; no
schema, repository or seed writer is modified.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

TABLE = "react_request_claims"
CLAIMED, DONE, FAILED = "CLAIMED", "DONE", "FAILED"

_DDL = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    user_id      TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('{CLAIMED}', '{DONE}', '{FAILED}')),
    project_code TEXT,
    detail       TEXT,
    claimed_at   REAL NOT NULL,
    finished_at  REAL,
    PRIMARY KEY (user_id, request_id, purpose)
)"""
_INDEX = f"CREATE INDEX IF NOT EXISTS {TABLE}_budget ON {TABLE} (user_id, purpose, claimed_at)"


@dataclass(frozen=True)
class Claim:
    won: bool                       # True only for the single caller that must perform the write
    state: str                      # CLAIMED | DONE | FAILED ("" when rate limited and no row exists)
    project_code: Optional[str] = None
    detail: Optional[str] = None
    rate_limited: bool = False
    retry_after: int = 0


def _connect():
    from app.persistence.db import get_connection

    conn = get_connection()
    conn.execute(_DDL)
    conn.execute(_INDEX)
    return conn


def _row(conn, user_id: str, request_id: str, purpose: str) -> Optional[Claim]:
    row = conn.execute(f"SELECT state, project_code, detail FROM {TABLE} WHERE user_id = ? AND request_id = ? AND purpose = ?",
                       (user_id, request_id, purpose)).fetchone()
    return None if row is None else Claim(False, row["state"], row["project_code"], row["detail"])


def lookup(user_id: str, request_id: str, purpose: str) -> Optional[Claim]:
    """Read-only view of a claim; ``None`` when no request with this id has been claimed by this user."""
    conn = _connect()
    try:
        return _row(conn, user_id, request_id, purpose)
    finally:
        conn.close()


def claim(user_id: str, request_id: str, purpose: str, *, rate_limit: Optional[tuple[int, int]] = None,
          now: Optional[float] = None) -> Claim:
    """Atomically claim ``(user, request id, purpose)``; exactly one concurrent caller across all processes gets ``won=True``."""
    stamp = time.time() if now is None else now
    limit, window = rate_limit if rate_limit else (0, 0)
    cutoff = stamp - window
    conn = _connect()
    try:
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} (user_id, request_id, purpose, state, claimed_at) "
            f"SELECT ?, ?, ?, '{CLAIMED}', ? WHERE ? = 1 OR "
            f"(SELECT COUNT(*) FROM {TABLE} WHERE user_id = ? AND purpose = ? AND claimed_at > ?) < ?",
            (user_id, request_id, purpose, stamp, 0 if rate_limit else 1, user_id, purpose, cutoff, limit))
        if cursor.rowcount == 1:
            return Claim(True, CLAIMED)
        existing = _row(conn, user_id, request_id, purpose)
        if existing is not None:
            return existing
        oldest = conn.execute(f"SELECT MIN(claimed_at) FROM {TABLE} WHERE user_id = ? AND purpose = ? AND claimed_at > ?",
                              (user_id, purpose, cutoff)).fetchone()[0]
        retry = int(window - (stamp - float(oldest))) + 1 if oldest is not None else 1
        return Claim(False, "", rate_limited=True, retry_after=max(retry, 1))
    finally:
        conn.close()


def _finalise(user_id: str, request_id: str, purpose: str, state: str, project_code: Optional[str], detail: Optional[str]) -> bool:
    conn = _connect()
    try:
        cursor = conn.execute(
            f"UPDATE {TABLE} SET state = ?, project_code = ?, detail = ?, finished_at = ? "
            f"WHERE user_id = ? AND request_id = ? AND purpose = ? AND state = '{CLAIMED}'",
            (state, project_code, detail, time.time(), user_id, request_id, purpose))
        return cursor.rowcount == 1
    finally:
        conn.close()


def finish(user_id: str, request_id: str, purpose: str, project_code: str) -> bool:
    """Record the created project; only a still-``CLAIMED`` row can be finished, a terminal row is never rewritten."""
    return _finalise(user_id, request_id, purpose, DONE, project_code, None)


def fail(user_id: str, request_id: str, purpose: str, code: str) -> bool:
    """Record that the writer reported a failure.  The id stays consumed: it is never reused or retried."""
    return _finalise(user_id, request_id, purpose, FAILED, None, code)
