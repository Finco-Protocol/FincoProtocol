"""FINCO45C (C1-Q-08 / C3-E-08): shared, multi-process rate-limit authority for login and demo operations.

Production runs ``FINCO_WEB_WORKERS`` (default 2) uvicorn worker processes. Process-local dicts gave each worker its own
budget, so the effective login lockout and demo budgets scaled with the worker count. This store is one small SQLite
file shared by every worker on the host (single-host VPS; no new service):

* path: ``FINCO_RATE_LIMIT_DB_PATH`` or ``<FINCO_DB_PATH>.ratelimit`` (a SEPARATE file: no migration of, no lock
  contention with, and no WF03 fence on the financial database);
* atomicity: every check-and-consume is one ``BEGIN IMMEDIATE`` transaction (the SQLite writer lock is the cross-process
  mutex). No transaction is ever held across a model computation or a password hash;
* keys: ``sha256(namespace || subject)`` - never a raw address, session token, password or cookie;
* bounded keyspace/retention: demo events are pruned per key on every consume and globally (older than the longest
  window) by ``purge``; login rows whose last activity is older than ``LOGIN_RETENTION_SECONDS`` are pruned;
* failure contract: FAIL CLOSED. If the store is busy beyond ``BUSY_TIMEOUT_MS`` or unavailable, a check returns
  ``(False, UNAVAILABLE_RETRY_AFTER)`` (a 429 with Retry-After, never a 5xx and never a silent bypass). Recording a failed
  login is best effort (the next check fails closed anyway if the store is down).

This limits request RATES only. It is not a global Run-concurrency admission control (see FINCO45C evidence 04).
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 2000
UNAVAILABLE_RETRY_AFTER = 5
LOGIN_RETENTION_SECONDS = 24 * 3600
_SCHEMA = """
CREATE TABLE IF NOT EXISTS login_attempts (
    key TEXT PRIMARY KEY,
    failures INTEGER NOT NULL CHECK (failures >= 0),
    locked_until REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_updated ON login_attempts(updated_at);
CREATE TABLE IF NOT EXISTS operation_events (
    key TEXT NOT NULL,
    op TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operation_events_key ON operation_events(key, op, ts);
CREATE INDEX IF NOT EXISTS idx_operation_events_ts ON operation_events(ts);
"""

_clock: Callable[[], float] = time.time
_ready: set[str] = set()
_ready_lock = threading.Lock()


class RateLimitStoreUnavailable(RuntimeError):
    """The shared store could not answer within the bounded busy timeout."""


def store_path() -> str:
    explicit = os.getenv("FINCO_RATE_LIMIT_DB_PATH")
    if explicit:
        return explicit
    from app.persistence import db
    return f"{db.DB_PATH}.ratelimit"


def subject_key(namespace: str, subject: str) -> str:
    return hashlib.sha256(f"finco-rate-limit/v1\x00{namespace}\x00{subject}".encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    path = store_path()
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous=NORMAL")          # counters, not financial data: WAL + NORMAL is crash-safe
        if path not in _ready:
            with _ready_lock:
                if path not in _ready:
                    # Several worker processes can initialise the store at the same moment; the WAL switch and DDL can
                    # report SQLITE_BUSY without the busy handler. Bounded retry (< 1 s total), then fail closed.
                    for attempt in range(8):
                        try:
                            conn.execute("PRAGMA journal_mode=WAL")
                            conn.executescript(_SCHEMA)
                            break
                        except sqlite3.OperationalError:
                            if attempt == 7:
                                raise
                            time.sleep(0.02 * (attempt + 1))
                    for suffix in ("", "-wal", "-shm"):
                        try:
                            os.chmod(path + suffix, 0o600)
                        except OSError:
                            pass
                    _ready.add(path)
        return conn
    except BaseException:
        conn.close()
        raise


def _transaction(fn):
    """Run ``fn(conn, now)`` in one BEGIN IMMEDIATE transaction; raise RateLimitStoreUnavailable on any store error."""
    try:
        conn = _connect()
    except sqlite3.Error as exc:
        raise RateLimitStoreUnavailable(type(exc).__name__) from exc
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = fn(conn, _clock())
            conn.execute("COMMIT")
            return result
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise RateLimitStoreUnavailable(type(exc).__name__) from exc
    finally:
        conn.close()


def _unavailable(what: str, exc: Exception) -> tuple[bool, int]:
    log.warning("rate_limit_store_unavailable op=%s error=%s (failing closed)", what, type(exc.__cause__ or exc).__name__)
    return False, UNAVAILABLE_RETRY_AFTER


# ── login ─────────────────────────────────────────────────────────────────────

def _login_row(conn, key):
    row = conn.execute("SELECT failures, locked_until FROM login_attempts WHERE key=?", (key,)).fetchone()
    return (row[0], row[1]) if row else (0, None)


def _login_gate(conn, key, now, max_failures, lockout):
    """An active lock denies with its remaining time; reaching ``max_failures`` starts a lock of ``lockout`` seconds.
    When a lock has EXPIRED the failure count starts again from zero (FINCO45C review finding: the former in-memory
    limiter re-armed an expired lock forever, which only a restart cleared; persisted and shared, that would have
    locked an operator or a shared egress address out permanently). Returns (allowed, retry_after)."""
    failures, locked_until = _login_row(conn, key)
    if locked_until is not None and now < locked_until:
        return False, max(1, int(locked_until - now))
    if locked_until is not None:
        conn.execute("UPDATE login_attempts SET failures=0, locked_until=NULL, updated_at=? WHERE key=?", (now, key))
        failures = 0
    if failures >= max_failures:
        conn.execute("INSERT INTO login_attempts(key, failures, locked_until, updated_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET locked_until=excluded.locked_until, updated_at=excluded.updated_at",
                     (key, failures, now + lockout, now))
        return False, lockout
    return True, 0


def login_check(subject: str, max_failures: int, lockout: int) -> tuple[bool, int]:
    key = subject_key("login", subject)
    try:
        return _transaction(lambda conn, now: _login_gate(conn, key, now, max_failures, lockout))
    except RateLimitStoreUnavailable as exc:
        return _unavailable("login_check", exc)


def login_reserve(subject: str, max_failures: int, lockout: int) -> tuple[bool, int]:
    """Atomically admit ONE credential verification and pre-charge it as a failure (refunded by ``login_clear`` on
    success). Concurrent attempts from N workers can never exceed ``max_failures`` verifications before the lock."""
    key = subject_key("login", subject)

    def reserve(conn, now):
        allowed, retry = _login_gate(conn, key, now, max_failures, lockout)
        if not allowed:
            return allowed, retry
        conn.execute("INSERT INTO login_attempts(key, failures, locked_until, updated_at) VALUES (?,1,NULL,?) "
                     "ON CONFLICT(key) DO UPDATE SET failures=failures+1, updated_at=excluded.updated_at", (key, now))
        return True, 0
    try:
        return _transaction(reserve)
    except RateLimitStoreUnavailable as exc:
        return _unavailable("login_reserve", exc)


def login_record_failure(subject: str) -> None:
    key = subject_key("login", subject)
    try:
        _transaction(lambda conn, now: conn.execute(
            "INSERT INTO login_attempts(key, failures, locked_until, updated_at) VALUES (?,1,NULL,?) "
            "ON CONFLICT(key) DO UPDATE SET failures=failures+1, updated_at=excluded.updated_at", (key, now)))
    except RateLimitStoreUnavailable as exc:
        _unavailable("login_record_failure", exc)


def login_clear(subject: str) -> None:
    key = subject_key("login", subject)
    try:
        _transaction(lambda conn, now: conn.execute("DELETE FROM login_attempts WHERE key=?", (key,)))
    except RateLimitStoreUnavailable as exc:
        _unavailable("login_clear", exc)


# ── per-principal operation budgets (demo sessions) ───────────────────────────

def consume(namespace: str, subject: str, op: str, limit_max: int, window: int) -> tuple[bool, int]:
    """Sliding-window budget: atomically prune, count and (if under budget) record one event for (subject, op)."""
    key = subject_key(namespace, subject)

    def take(conn, now):
        conn.execute("DELETE FROM operation_events WHERE key=? AND op=? AND ts<=?", (key, op, now - window))
        count, oldest = conn.execute("SELECT count(*), min(ts) FROM operation_events WHERE key=? AND op=?",
                                     (key, op)).fetchone()
        if count >= limit_max:
            return False, max(1, int(window - (now - oldest)) + 1)
        conn.execute("INSERT INTO operation_events(key, op, ts) VALUES (?,?,?)", (key, op, now))
        return True, 0
    try:
        return _transaction(take)
    except RateLimitStoreUnavailable as exc:
        return _unavailable(f"consume:{namespace}:{op}", exc)


def purge(max_window: int, login_retention: int = LOGIN_RETENTION_SECONDS) -> dict:
    """Bounded retention: drop operation events older than the longest window, idle unlocked login rows."""
    def run(conn, now):
        ops = conn.execute("DELETE FROM operation_events WHERE ts<=?", (now - max_window,)).rowcount
        logins = conn.execute("DELETE FROM login_attempts WHERE updated_at<=? AND (locked_until IS NULL OR "
                              "locked_until<=?)", (now - login_retention, now)).rowcount
        return {"operation_events": ops, "login_attempts": logins}
    try:
        return _transaction(run)
    except RateLimitStoreUnavailable as exc:
        _unavailable("purge", exc)
        return {"operation_events": 0, "login_attempts": 0}


def counts() -> dict:
    def run(conn, _now):
        return {"operation_events": conn.execute("SELECT count(*) FROM operation_events").fetchone()[0],
                "login_attempts": conn.execute("SELECT count(*) FROM login_attempts").fetchone()[0]}
    return _transaction(run)


def reset_for_tests() -> None:
    """Delete every counter in the current store (test isolation only; never called by the application)."""
    _transaction(lambda conn, _now: (conn.execute("DELETE FROM operation_events"),
                                     conn.execute("DELETE FROM login_attempts")))
