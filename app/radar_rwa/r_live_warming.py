"""ONE background collector authority for the R-LIVE latest snapshot.

Warming architecture (instant R-LIVE UX master stream):

  BACKGROUND CANONICAL ACQUISITION  →  IMMUTABLE LATEST SNAPSHOT  →
  INSTANT READ-ONLY WEB PRESENTATION

Exactly ONE warming loop runs per host even with multiple Uvicorn workers:
a cross-process SQLite lease (``r_live_warming_lease``, singleton row with
an expiry) admits a single holder — every other worker's loop idles.  There
is no Redis/Celery/distributed infrastructure: one small SQLite lease in
the snapshot database is the whole coordination layer.

Per cycle:
  - the canonical batch authority ``collect_r_live_batch()`` is used
    unchanged (ONE shared registry fetch per batch, bounded RPC worker
    pool 1..4, per-asset failure isolation — the existing acquisition
    controls);
  - a non-blocking cycle lock guarantees NO overlapping batch refreshes
    within the warming loop;
  - the batch is written atomically to the snapshot store (UNAVAILABLE
    rows skipped — a failed refresh never destroys the last valid
    snapshot);
  - the existing Collector Health semantics receive the heartbeat:
    record_attempt before the batch, record_success / record_degraded /
    record_systemic_failure after it, so the operator view in
    ``/radar/r-live/assets`` reflects the warming collector.

Cadence: default 60 s, overridable via ``FINCO_RLIVE_WARMING_INTERVAL_SECONDS``.
The canonical freshness windows (block age ≤ 120 s, pool activity ≤ 300 s,
registry ≤ 300 s) mean a 60 s cadence re-collects well inside every window;
the cycle lock plus acquisition duration keep the effective rate bounded.

The read path NEVER calls any function in this module: presentation reads
the snapshot store only.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WARMING_SCHEMA_VERSION = "finco-r-live-warming-v1"

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 15
MAX_INTERVAL_SECONDS = 600
DEFAULT_RPC_WORKERS = 2  # delegated to collect_r_live_batch (bounded 1..4)

_LEASE_SINGLETON_GUARD = threading.Lock()


def _interval_seconds() -> int:
    raw = os.getenv("FINCO_RLIVE_WARMING_INTERVAL_SECONDS", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, value))


def warming_enabled() -> bool:
    return os.getenv("FINCO_RLIVE_WARMING_ENABLED", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def warm_snapshot_once(rpc_url: str, *, store_path: str | None = None,
                       now: datetime | None = None) -> dict:
    """Run ONE canonical batch and atomically persist the snapshot.

    Failure semantics: a whole-batch acquisition failure records a systemic
    collector-health outcome and leaves the previous snapshot untouched;
    per-asset UNAVAILABLE rows are skipped by the store.  Never raises to
    the caller — returns a typed summary dict.
    """
    from app.radar_rwa.collector_health import CollectorHealthStore
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from app.radar_rwa.r_live_service import collect_r_live_batch

    started = datetime.now(timezone.utc)
    with CollectorHealthStore(path=store_path) as health:
        health.record_attempt(now=now)
    try:
        rows = list(collect_r_live_batch(rpc_url=rpc_url))
    except Exception as exc:
        with CollectorHealthStore(path=store_path) as health:
            health.record_systemic_failure(
                getattr(exc, "REASON", None) or "R_LIVE_BATCH_ACQUISITION_FAILED",
                now=now,
            )
        return {"state": "SYSTEMIC_FAILURE", "written": 0, "available": 0,
                "stale": 0, "unavailable": 0}

    available = sum(1 for _, state, _ in rows if state == "AVAILABLE")
    stale = sum(1 for _, state, _ in rows if state == "STALE")
    unavailable = sum(1 for _, state, _ in rows if state == "UNAVAILABLE")
    try:
        with RLiveSnapshotStore(path=store_path) as store:
            written = store.write_batch(rows, collected_at=now or started)
    except Exception:
        with CollectorHealthStore(path=store_path) as health:
            health.record_systemic_failure("SNAPSHOT_STORE_UNAVAILABLE", now=now)
        return {"state": "SYSTEMIC_FAILURE", "written": 0, "available": available,
                "stale": stale, "unavailable": unavailable}

    with CollectorHealthStore(path=store_path) as health:
        if available:
            health.record_success(attempted=len(rows), available=available,
                                  stale=stale, unavailable=unavailable, now=now)
        elif stale:
            health.record_degraded(attempted=len(rows), available=available,
                                   stale=stale, unavailable=unavailable, now=now)
        else:
            health.record_systemic_failure(
                "R_LIVE_BATCH_ACQUISITION_FAILED", attempted=len(rows),
                available=available, stale=stale, unavailable=unavailable, now=now)
    return {"state": "OK", "written": written, "available": available,
            "stale": stale, "unavailable": unavailable}


class _SnapshotLease:
    """Cross-process single-holder lease stored in the snapshot database.

    Exactly ONE warming loop per host holds the lease; the holder renews it
    each cycle.  Other processes/threads skip their cycles while the lease
    is valid.  A crashed holder's lease simply expires and may be taken
    over.

    Holder identity is STABLE for the lifetime of this instance (created
    once in ``__init__`` as pid + a random discriminator — never the PID
    alone): ``acquire_or_renew`` from the SAME instance RENEWS the expiry
    instead of fighting its own lease, so the warming cadence equals the
    interval regardless of the lease TTL.
    """

    def __init__(self, path: str | None) -> None:
        import uuid
        from app.radar_rwa.r_live_snapshot_store import _db_path
        self.path = _db_path(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.path if self.path == ":memory:" else self.path, timeout=10,
            check_same_thread=False)  # serialized by _LEASE_SINGLETON_GUARD
        self._conn.isolation_level = None  # manual transactions (BEGIN IMMEDIATE)
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS r_live_warming_lease ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "holder TEXT NOT NULL, expires_at TEXT NOT NULL, "
            "schema_version TEXT NOT NULL)"
        )
        # Stable per-instance identity: process id + random discriminator.
        self._holder = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts)

    def acquire_or_renew(self, *, ttl_seconds: int, now: datetime | None = None) -> bool:
        """Acquire the lease, or RENEW it when this instance already holds it.

        - no valid lease            → acquire (also covers expired foreign
                                      leases: takeover);
        - valid lease, same holder  → renew the expiry (never self-reject);
        - valid lease, other holder → deny.
        """
        current = now or datetime.now(timezone.utc)
        expiry = (current + timedelta(seconds=ttl_seconds)).isoformat()
        with _LEASE_SINGLETON_GUARD:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    row = self._conn.execute(
                        "SELECT holder, expires_at FROM r_live_warming_lease "
                        "WHERE singleton=1"
                    ).fetchone()
                    if row is not None and row[0] == self._holder:
                        # Same instance: RENEW — never reject our own lease.
                        self._conn.execute(
                            "UPDATE r_live_warming_lease SET expires_at=?, "
                            "schema_version=? WHERE singleton=1 AND holder=?",
                            (expiry, WARMING_SCHEMA_VERSION, self._holder),
                        )
                        self._conn.execute("COMMIT")
                        return True
                    if row is not None:
                        try:
                            held_expiry = self._parse(row[1])
                        except ValueError:
                            held_expiry = None
                        if held_expiry is not None and held_expiry > current:
                            self._conn.execute("ROLLBACK")
                            return False  # a live foreign holder owns the lease
                    # No lease, or an expired/invalid foreign lease → take over.
                    self._conn.execute(
                        "INSERT INTO r_live_warming_lease "
                        "(singleton,holder,expires_at,schema_version) VALUES (1,?,?,?) "
                        "ON CONFLICT(singleton) DO UPDATE SET holder=excluded.holder, "
                        "expires_at=excluded.expires_at, "
                        "schema_version=excluded.schema_version",
                        (self._holder, expiry, WARMING_SCHEMA_VERSION),
                    )
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                self._conn.execute("COMMIT")
                return True
            except sqlite3.Error:
                return False

    def release(self) -> None:
        with _LEASE_SINGLETON_GUARD:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "DELETE FROM r_live_warming_lease WHERE singleton=1 "
                    "AND holder=?", (self._holder,),
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                pass


class RLiveSnapshotWarmer:
    """The single warming loop. Start via :func:`start_background_warmer`.

    Lease ownership spans the ENTIRE acquisition cycle: the loop renews the
    cross-process lease before each cycle AND a bounded heartbeat renews it
    while ``collect_r_live_batch`` is running, so a slow/degraded batch can
    never outlive the TTL and let a second worker start an overlapping
    canonical batch.  A genuinely dead owner still recovers: its lease
    simply expires and a foreign worker takes over.
    """

    def __init__(self, *, store_path: str | None = None,
                 interval_seconds: int | None = None,
                 lease_ttl_seconds: int | None = None,
                 heartbeat_period_seconds: float | None = None) -> None:
        self.store_path = store_path
        self.interval = interval_seconds or _interval_seconds()
        self.lease_ttl = lease_ttl_seconds or self.interval * 3
        # Heartbeat period: bounded well inside the TTL (≤ 1/3 of it).
        self.heartbeat_period = heartbeat_period_seconds or max(
            1.0, self.lease_ttl / 3.0)
        self._cycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_summary: dict | None = None
        self._lease: _SnapshotLease | None = None

    def _lease_or_none(self) -> "_SnapshotLease":
        if self._lease is None:
            self._lease = _SnapshotLease(self.store_path)
        return self._lease

    def _renew_until(self, stop: threading.Event()) -> None:
        """Renew this warmer's lease while the batch is in flight.

        Keeps lease ownership valid for the entire active cycle even when a
        single acquisition outlasts the nominal TTL.  Stops promptly when
        the cycle ends; a crash of the owner simply stops the heartbeat and
        the lease expires normally (dead-owner recovery unchanged).
        """
        lease = self._lease_or_none()
        while not stop.wait(self.heartbeat_period):
            if not lease.acquire_or_renew(ttl_seconds=self.lease_ttl):
                return  # lost ownership (should not happen while admitted)

    def run_cycle(self, *, rpc_url: str | None = None) -> dict | None:
        """One non-overlapping, lease-guarded warming cycle.

        Returns None when this warmer does not own the cross-process lease
        (a foreign worker is actively collecting) or when a cycle is already
        running in this process — in both cases it does NOT enter
        ``collect_r_live_batch``.
        """
        if not self._cycle_lock.acquire(blocking=False):
            return None  # no overlapping batch refreshes in this process
        try:
            lease = self._lease_or_none()
            if not lease.acquire_or_renew(ttl_seconds=self.lease_ttl):
                return None  # foreign holder owns the lease: never double-collect
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=self._renew_until, args=(heartbeat_stop,), daemon=True,
                name="finco-r-live-lease-heartbeat")
            heartbeat.start()
            try:
                rpc = rpc_url or os.getenv("ROBINHOOD_RPC_URL")
                if not rpc:
                    summary = {"state": "RPC_NOT_CONFIGURED", "written": 0}
                else:
                    summary = warm_snapshot_once(rpc, store_path=self.store_path)
                self.last_summary = summary
                return summary
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=5)
        finally:
            self._cycle_lock.release()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self.run_cycle()  # None when a foreign worker owns the lease
                self._stop.wait(self.interval)
        finally:
            if self._lease is not None:
                self._lease.release()
                self._lease.close()
                self._lease = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="finco-r-live-snapshot-warmer")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()


_WARMER: RLiveSnapshotWarmer | None = None
_WARMER_LOCK = threading.Lock()


def start_background_warmer() -> bool:
    """Start the process-local warmer thread (idempotent).

    The SQLite lease guarantees that, across all Uvicorn workers on the
    host, exactly ONE loop actually collects; the others idle.  Disabled
    entirely when ``FINCO_RLIVE_WARMING_ENABLED=0`` (e.g. the dedicated
    systemd collector owns warming in that deployment).
    """
    global _WARMER
    if not warming_enabled():
        return False
    with _WARMER_LOCK:
        if _WARMER is None:
            _WARMER = RLiveSnapshotWarmer()
        started = _WARMER.start()
    return started


def main(argv: list[str] | None = None) -> int:
    """CLI for a dedicated single collector process / systemd service.

    ``--once``  run exactly one warming cycle and print a typed summary.
    ``--loop``  run the warming loop in the foreground (no-overlap + lease
                guards apply; use with the deploy systemd unit).
    """
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(
        description="R-LIVE latest-snapshot warmer (background canonical "
                    "acquisition -> immutable latest snapshot). Read-only "
                    "for the web; no trading path.")
    parser.add_argument("--once", action="store_true",
                        help="run one warming cycle and exit")
    parser.add_argument("--loop", action="store_true",
                        help="run the warming loop in the foreground")
    args = parser.parse_args(argv)

    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        print(_json.dumps({"state": "RPC_NOT_CONFIGURED", "written": 0}))
        return 1
    if args.once:
        summary = warm_snapshot_once(rpc_url)
        print(_json.dumps(summary, sort_keys=True))
        return 0 if summary.get("state") == "OK" else 1
    if args.loop:
        warmer = RLiveSnapshotWarmer()
        warmer.start()
        try:
            while True:
                time.sleep(_interval_seconds())
        except KeyboardInterrupt:
            warmer.stop()
        return 0
    parser.print_usage(_sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
