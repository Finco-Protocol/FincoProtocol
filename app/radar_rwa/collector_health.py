"""Durable operational health for the R-LIVE collector.

This state is operator metadata only. It never changes R-LIVE asset authority,
history evidence, identity, price/premium math, Verify, or Model outputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal

from .bnb_history import DEFAULT_DB_PATH

CollectorHealthState = Literal["HEALTHY", "DEGRADED", "UNHEALTHY"]

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNHEALTHY = "UNHEALTHY"

_OUTCOME_ATTEMPTING = "ATTEMPTING"
_OUTCOME_SUCCESS = "SUCCESS"
_OUTCOME_DEGRADED = "DEGRADED"
_OUTCOME_SYSTEMIC_FAILURE = "SYSTEMIC_FAILURE"
_OUTCOME_NEVER_RUN = "NEVER_RUN"

_REASON_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS r_live_collector_health (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_attempt_at TEXT,
    last_success_at TEXT,
    batch_outcome TEXT NOT NULL,
    assets_attempted INTEGER NOT NULL,
    available_count INTEGER NOT NULL,
    stale_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    systemic_failure_reason TEXT,
    consecutive_systemic_failures INTEGER NOT NULL,
    health_state TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("COLLECTOR_HEALTH_CLOCK_MUST_BE_AWARE")
    return value.astimezone(timezone.utc).isoformat()


def _safe_reason(reason: object) -> str | None:
    return reason if isinstance(reason, str) and _REASON_PATTERN.fullmatch(reason) else None


def _db_path(path: str | None = None) -> str:
    return path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)


@dataclass(frozen=True)
class CollectorHealthSnapshot:
    last_attempt_at: str | None
    last_success_at: str | None
    batch_outcome: str
    assets_attempted: int
    available_count: int
    stale_count: int
    unavailable_count: int
    systemic_failure_reason: str | None
    consecutive_systemic_failures: int
    health_state: CollectorHealthState
    updated_at: str | None

    def public_dict(self) -> dict:
        return asdict(self)


_EMPTY = CollectorHealthSnapshot(
    last_attempt_at=None,
    last_success_at=None,
    batch_outcome=_OUTCOME_NEVER_RUN,
    assets_attempted=0,
    available_count=0,
    stale_count=0,
    unavailable_count=0,
    systemic_failure_reason="NO_RECORDED_COLLECTION",
    consecutive_systemic_failures=0,
    health_state=UNHEALTHY,
    updated_at=None,
)


class CollectorHealthStore:
    """Single-row durable writer for collector operational health."""

    def __init__(self, *, path: str | None = None) -> None:
        self.path = _db_path(path)
        if self.path == ":memory:":
            raise ValueError("COLLECTOR_HEALTH_REQUIRES_DURABLE_PATH")
        location = Path(self.path)
        location.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(location, timeout=5)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CollectorHealthStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _current(self) -> CollectorHealthSnapshot:
        row = self._conn.execute(
            "SELECT last_attempt_at,last_success_at,batch_outcome,assets_attempted,"
            "available_count,stale_count,unavailable_count,systemic_failure_reason,"
            "consecutive_systemic_failures,health_state,updated_at "
            "FROM r_live_collector_health WHERE singleton=1"
        ).fetchone()
        if row is None:
            return _EMPTY
        return CollectorHealthSnapshot(*row)

    def _write(self, snapshot: CollectorHealthSnapshot) -> CollectorHealthSnapshot:
        self._conn.execute(
            "INSERT INTO r_live_collector_health "
            "(singleton,last_attempt_at,last_success_at,batch_outcome,assets_attempted,"
            "available_count,stale_count,unavailable_count,systemic_failure_reason,"
            "consecutive_systemic_failures,health_state,updated_at) "
            "VALUES (1,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(singleton) DO UPDATE SET "
            "last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,"
            "batch_outcome=excluded.batch_outcome,assets_attempted=excluded.assets_attempted,"
            "available_count=excluded.available_count,stale_count=excluded.stale_count,"
            "unavailable_count=excluded.unavailable_count,"
            "systemic_failure_reason=excluded.systemic_failure_reason,"
            "consecutive_systemic_failures=excluded.consecutive_systemic_failures,"
            "health_state=excluded.health_state,updated_at=excluded.updated_at",
            (
                snapshot.last_attempt_at, snapshot.last_success_at, snapshot.batch_outcome,
                snapshot.assets_attempted, snapshot.available_count, snapshot.stale_count,
                snapshot.unavailable_count, snapshot.systemic_failure_reason,
                snapshot.consecutive_systemic_failures, snapshot.health_state,
                snapshot.updated_at,
            ),
        )
        self._conn.commit()
        return snapshot

    def record_attempt(self, *, now: datetime | None = None) -> CollectorHealthSnapshot:
        current = self._current()
        stamp = _now_iso(now)
        return self._write(CollectorHealthSnapshot(
            last_attempt_at=stamp,
            last_success_at=current.last_success_at,
            batch_outcome=_OUTCOME_ATTEMPTING,
            assets_attempted=0,
            available_count=0,
            stale_count=0,
            unavailable_count=0,
            systemic_failure_reason=None,
            consecutive_systemic_failures=current.consecutive_systemic_failures,
            health_state=current.health_state,
            updated_at=stamp,
        ))

    def record_success(
        self,
        *, attempted: int, available: int, stale: int, unavailable: int,
        now: datetime | None = None,
    ) -> CollectorHealthSnapshot:
        stamp = _now_iso(now)
        return self._write(CollectorHealthSnapshot(
            last_attempt_at=stamp,
            last_success_at=stamp,
            batch_outcome=_OUTCOME_SUCCESS,
            assets_attempted=attempted,
            available_count=available,
            stale_count=stale,
            unavailable_count=unavailable,
            systemic_failure_reason=None,
            consecutive_systemic_failures=0,
            health_state=HEALTHY,
            updated_at=stamp,
        ))

    def record_degraded(
        self,
        *, attempted: int, available: int, stale: int, unavailable: int,
        now: datetime | None = None,
    ) -> CollectorHealthSnapshot:
        current = self._current()
        stamp = _now_iso(now)
        return self._write(CollectorHealthSnapshot(
            last_attempt_at=stamp,
            last_success_at=current.last_success_at,
            batch_outcome=_OUTCOME_DEGRADED,
            assets_attempted=attempted,
            available_count=available,
            stale_count=stale,
            unavailable_count=unavailable,
            systemic_failure_reason=None,
            consecutive_systemic_failures=0,
            health_state=DEGRADED,
            updated_at=stamp,
        ))

    def record_systemic_failure(
        self,
        reason: str,
        *, attempted: int = 0, available: int = 0, stale: int = 0,
        unavailable: int = 0, now: datetime | None = None,
    ) -> CollectorHealthSnapshot:
        safe_reason = _safe_reason(reason)
        if safe_reason is None:
            safe_reason = "COLLECTOR_SYSTEMIC_FAILURE"
        current = self._current()
        stamp = _now_iso(now)
        return self._write(CollectorHealthSnapshot(
            last_attempt_at=stamp,
            last_success_at=current.last_success_at,
            batch_outcome=_OUTCOME_SYSTEMIC_FAILURE,
            assets_attempted=attempted,
            available_count=available,
            stale_count=stale,
            unavailable_count=unavailable,
            systemic_failure_reason=safe_reason,
            consecutive_systemic_failures=current.consecutive_systemic_failures + 1,
            health_state=UNHEALTHY,
            updated_at=stamp,
        ))


def read_collector_health_readonly(*, path: str | None = None) -> CollectorHealthSnapshot:
    """Read health without creating a database/table or fabricating success."""
    location = _db_path(path)
    if location == ":memory:" or not Path(location).is_file():
        return _EMPTY
    uri = Path(location).resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            row = conn.execute(
                "SELECT last_attempt_at,last_success_at,batch_outcome,assets_attempted,"
                "available_count,stale_count,unavailable_count,systemic_failure_reason,"
                "consecutive_systemic_failures,health_state,updated_at "
                "FROM r_live_collector_health WHERE singleton=1"
            ).fetchone()
    except (sqlite3.Error, OSError):
        return _EMPTY
    if row is None:
        return _EMPTY
    return CollectorHealthSnapshot(*row)
