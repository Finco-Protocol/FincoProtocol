"""Operational health for the Tokenized Markets collector.

Health is separate from market authority. It never changes canonical history,
pricing, basis, identity, or derived intelligence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

from finco_radar.venues.store import default_db_path

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNHEALTHY = "UNHEALTHY"
LIVENESS_LIVE = "LIVE"
LIVENESS_STALE = "STALE"
LIVENESS_STOPPED = "STOPPED"
LIVENESS_UNKNOWN = "UNKNOWN"

HEARTBEAT_INTERVAL_SECONDS = 300
HEARTBEAT_DEGRADED_AFTER_SECONDS = 3 * HEARTBEAT_INTERVAL_SECONDS
HEARTBEAT_UNHEALTHY_AFTER_SECONDS = 12 * HEARTBEAT_INTERVAL_SECONDS

_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokenized_collector_health (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    last_attempt_at TEXT,
    last_success_at TEXT,
    outcome TEXT NOT NULL,
    assets_attempted INTEGER NOT NULL,
    available_count INTEGER NOT NULL,
    stale_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    quarantined_count INTEGER NOT NULL,
    persisted_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    failure_reason TEXT,
    consecutive_failures INTEGER NOT NULL,
    health_state TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class TokenizedCollectorHealth:
    last_attempt_at: str | None
    last_success_at: str | None
    outcome: str
    assets_attempted: int
    available_count: int
    stale_count: int
    unavailable_count: int
    quarantined_count: int
    persisted_count: int
    duplicate_count: int
    failure_reason: str | None
    consecutive_failures: int
    health_state: str
    updated_at: str | None
    liveness: str = LIVENESS_UNKNOWN
    heartbeat_age_seconds: int | None = None
    stored_health_state: str | None = None

    def public_dict(self) -> dict:
        return asdict(self)


_EMPTY = TokenizedCollectorHealth(
    None, None, "NEVER_RUN", 0, 0, 0, 0, 0, 0, 0,
    "NO_RECORDED_COLLECTION", 0, UNHEALTHY, None,
)


def _safe_reason(reason: object) -> str:
    if isinstance(reason, str) and _REASON.fullmatch(reason):
        return reason
    return "TOKENIZED_COLLECTOR_FAILURE"


def _stamp(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TOKENIZED_COLLECTOR_HEALTH_CLOCK_MUST_BE_AWARE")
    return value.astimezone(timezone.utc).isoformat()


class TokenizedCollectorHealthStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or default_db_path()
        if self.path == ":memory:":
            raise ValueError("TOKENIZED_COLLECTOR_HEALTH_REQUIRES_DURABLE_PATH")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=5)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _read(self) -> TokenizedCollectorHealth:
        row = self._conn.execute(
            "SELECT last_attempt_at,last_success_at,outcome,assets_attempted,"
            "available_count,stale_count,unavailable_count,quarantined_count,"
            "persisted_count,duplicate_count,failure_reason,consecutive_failures,"
            "health_state,updated_at FROM tokenized_collector_health WHERE singleton=1"
        ).fetchone()
        return TokenizedCollectorHealth(*row) if row else _EMPTY

    def _write(self, value: TokenizedCollectorHealth) -> TokenizedCollectorHealth:
        self._conn.execute(
            "INSERT INTO tokenized_collector_health "
            "(singleton,last_attempt_at,last_success_at,outcome,assets_attempted,"
            "available_count,stale_count,unavailable_count,quarantined_count,"
            "persisted_count,duplicate_count,failure_reason,consecutive_failures,"
            "health_state,updated_at) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(singleton) DO UPDATE SET "
            "last_attempt_at=excluded.last_attempt_at,"
            "last_success_at=excluded.last_success_at,outcome=excluded.outcome,"
            "assets_attempted=excluded.assets_attempted,"
            "available_count=excluded.available_count,stale_count=excluded.stale_count,"
            "unavailable_count=excluded.unavailable_count,"
            "quarantined_count=excluded.quarantined_count,"
            "persisted_count=excluded.persisted_count,"
            "duplicate_count=excluded.duplicate_count,"
            "failure_reason=excluded.failure_reason,"
            "consecutive_failures=excluded.consecutive_failures,"
            "health_state=excluded.health_state,updated_at=excluded.updated_at",
            (
                value.last_attempt_at, value.last_success_at, value.outcome,
                value.assets_attempted, value.available_count, value.stale_count,
                value.unavailable_count, value.quarantined_count,
                value.persisted_count, value.duplicate_count, value.failure_reason,
                value.consecutive_failures, value.health_state, value.updated_at,
            ),
        )
        self._conn.commit()
        return value

    def record_attempt(self, *, now: datetime | None = None) -> TokenizedCollectorHealth:
        current = self._read()
        stamp = _stamp(now)
        return self._write(TokenizedCollectorHealth(
            stamp, current.last_success_at, "ATTEMPTING", 0, 0, 0, 0, 0, 0, 0,
            None, current.consecutive_failures, current.health_state, stamp,
        ))

    def record_complete(
        self, *, attempted: int, available: int, stale: int, unavailable: int,
        quarantined: int, persisted: int, duplicates: int,
        degraded: bool = False, now: datetime | None = None,
    ) -> TokenizedCollectorHealth:
        current = self._read()
        stamp = _stamp(now)
        successful = available > 0 or (attempted > 0 and unavailable == 0 and stale == 0)
        state = DEGRADED if degraded or unavailable or stale else HEALTHY
        last_success = stamp if successful else current.last_success_at
        return self._write(TokenizedCollectorHealth(
            stamp, last_success, "DEGRADED" if state == DEGRADED else "SUCCESS",
            attempted, available, stale, unavailable, quarantined, persisted,
            duplicates, None, 0, state, stamp,
        ))

    def record_failure(
        self, reason: str, *, attempted: int = 0,
        now: datetime | None = None,
    ) -> TokenizedCollectorHealth:
        current = self._read()
        stamp = _stamp(now)
        return self._write(TokenizedCollectorHealth(
            stamp, current.last_success_at, "SYSTEMIC_FAILURE", attempted,
            0, 0, attempted, 0, 0, 0, _safe_reason(reason),
            current.consecutive_failures + 1, UNHEALTHY, stamp,
        ))


def apply_liveness(
    value: TokenizedCollectorHealth,
    *, now: datetime | None = None,
) -> TokenizedCollectorHealth:
    stored = value.health_state
    if not value.last_attempt_at:
        return replace(value, stored_health_state=stored)
    try:
        beat = datetime.fromisoformat(value.last_attempt_at)
        if beat.tzinfo is None or beat.utcoffset() is None:
            raise ValueError
    except ValueError:
        return replace(value, health_state=UNHEALTHY,
                       liveness=LIVENESS_UNKNOWN, stored_health_state=stored)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = max(0, int((current - beat.astimezone(timezone.utc)).total_seconds()))
    if age >= HEARTBEAT_UNHEALTHY_AFTER_SECONDS:
        liveness, effective = LIVENESS_STOPPED, UNHEALTHY
    elif age >= HEARTBEAT_DEGRADED_AFTER_SECONDS:
        liveness = LIVENESS_STALE
        effective = UNHEALTHY if stored == UNHEALTHY else DEGRADED
    else:
        liveness, effective = LIVENESS_LIVE, stored
    return replace(value, health_state=effective, liveness=liveness,
                   heartbeat_age_seconds=age, stored_health_state=stored)


def read_tokenized_collector_health(
    *, path: str | None = None, now: datetime | None = None,
) -> TokenizedCollectorHealth:
    location = path or default_db_path()
    if location == ":memory:" or not Path(location).is_file():
        return _EMPTY
    uri = Path(location).resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            row = conn.execute(
                "SELECT last_attempt_at,last_success_at,outcome,assets_attempted,"
                "available_count,stale_count,unavailable_count,quarantined_count,"
                "persisted_count,duplicate_count,failure_reason,consecutive_failures,"
                "health_state,updated_at FROM tokenized_collector_health WHERE singleton=1"
            ).fetchone()
    except (sqlite3.Error, OSError):
        return _EMPTY
    return apply_liveness(TokenizedCollectorHealth(*row), now=now) if row else _EMPTY
