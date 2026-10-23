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
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager, nullcontext
from pathlib import Path

from app.background_lifecycle import ShutdownIncomplete

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
                       now: datetime | None = None, lease_holder: str | None = None,
                       lease_authority: _SnapshotLease | None = None) -> dict:
    """Run ONE canonical batch and atomically persist the snapshot.

    Failure semantics: a whole-batch acquisition failure records a systemic
    collector-health outcome and leaves the previous snapshot untouched;
    per-asset UNAVAILABLE rows are skipped by the store.  Never raises to
    the caller — returns a typed summary dict.
    """
    from app.radar_rwa.collector_health import CollectorHealthStore
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore, LeaseOwnershipLost
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
        with (lease_authority.publication_guard() if lease_authority is not None else nullcontext()):
            if lease_authority is not None and (not lease_holder or lease_holder != lease_authority._holder):
                raise LeaseOwnershipLost("missing or mismatched warming epoch")
            with RLiveSnapshotStore(path=store_path) as store:
                written = store.write_batch(rows, collected_at=now or started, lease_holder=lease_holder)
    except LeaseOwnershipLost:
        return {"state": "LEASE_OWNERSHIP_LOST", "written": 0, "available": available,
                "stale": stale, "unavailable": unavailable}
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
    """One ownership epoch. Lost authority can never be resurrected.

    Acquisition and renewal serialize with publication through the existing
    process guard and SQLite BEGIN IMMEDIATE. A new instance is required after
    loss/release; the warmer closes the old instance only after work is joined.
    """

    def __init__(self, path: str | None, *, clock=None) -> None:
        import uuid
        from app.radar_rwa.r_live_snapshot_store import _db_path
        self.path = _db_path(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._conn.isolation_level = None
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS r_live_warming_lease ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "holder TEXT NOT NULL, expires_at TEXT NOT NULL, "
            "schema_version TEXT NOT NULL)"
        )
        self._holder = f"{os.getpid()}-{uuid.uuid4().hex}"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._acquired = False
        self._lost = False

    def close(self) -> None:
        with _LEASE_SINGLETON_GUARD:
            self._lost = True
            self._conn.close()

    @staticmethod
    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts)

    def _change(self, *, renewal: bool, ttl_seconds: int,
                now: datetime | None = None) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("lease TTL must be positive")
        with _LEASE_SINGLETON_GUARD:
            if self._lost or renewal != self._acquired:
                return False
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                # Production time is sampled AFTER both locks, including any
                # SQLite writer wait. Explicit time is a deterministic test seam.
                current = now if now is not None else self._clock()
                row = self._conn.execute(
                    "SELECT holder, expires_at FROM r_live_warming_lease WHERE singleton=1"
                ).fetchone()
                try:
                    live = row is not None and self._parse(row[1]) > current
                except (TypeError, ValueError):
                    live = False
                expiry = (current + timedelta(seconds=ttl_seconds)).isoformat()
                if renewal:
                    if not live or row[0] != self._holder:
                        self._lost = True
                        self._conn.execute("ROLLBACK")
                        return False
                    self._conn.execute(
                        "UPDATE r_live_warming_lease SET expires_at=?, schema_version=? "
                        "WHERE singleton=1 AND holder=?",
                        (expiry, WARMING_SCHEMA_VERSION, self._holder))
                else:
                    if live:
                        self._conn.execute("ROLLBACK")
                        return False
                    self._conn.execute(
                        "INSERT INTO r_live_warming_lease "
                        "(singleton,holder,expires_at,schema_version) VALUES (1,?,?,?) "
                        "ON CONFLICT(singleton) DO UPDATE SET holder=excluded.holder, "
                        "expires_at=excluded.expires_at, schema_version=excluded.schema_version",
                        (self._holder, expiry, WARMING_SCHEMA_VERSION))
                self._conn.execute("COMMIT")
                self._acquired = True
                return True
            except BaseException as exc:
                self._lost = True
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                if not isinstance(exc, sqlite3.Error):
                    raise
                return False

    def acquire(self, *, ttl_seconds: int, now: datetime | None = None) -> bool:
        """Initial acquisition only; never replace an already acquired epoch."""
        return self._change(renewal=False, ttl_seconds=ttl_seconds, now=now)

    def renew(self, *, ttl_seconds: int, now: datetime | None = None) -> bool:
        """Renew only an existing live exact epoch; any loss is permanent."""
        return self._change(renewal=True, ttl_seconds=ttl_seconds, now=now)

    def acquire_or_renew(self, *, ttl_seconds: int, now: datetime | None = None) -> bool:
        """Compatibility dispatcher; an expired acquired epoch NEVER reacquires."""
        return self._change(renewal=self._acquired, ttl_seconds=ttl_seconds, now=now)

    @contextmanager
    def publication_guard(self):
        """Serialize local invalidation with the store's SQLite publication fence."""
        from app.radar_rwa.r_live_snapshot_store import LeaseOwnershipLost
        with _LEASE_SINGLETON_GUARD:
            if not self._acquired or self._lost:
                raise LeaseOwnershipLost("warming ownership epoch permanently invalid")
            try:
                yield
            except BaseException:
                self._lost = True
                raise

    def release(self) -> None:
        with _LEASE_SINGLETON_GUARD:
            self._lost = True
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "DELETE FROM r_live_warming_lease WHERE singleton=1 "
                    "AND holder=?", (self._holder,),
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                # A failed release cannot be reported as successful shutdown.
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise


class RLiveSnapshotWarmer:
    """The single warming loop. Start via :func:`start_background_warmer`.

    Lease authority is renewed throughout the acquisition cycle: the loop renews the
    cross-process lease before each cycle AND a bounded heartbeat renews it
    while ``collect_r_live_batch`` is running, so a slow/degraded batch
    normally retains its authority. A missed TTL permanently
    fences the old epoch from publication. Expiry permits foreign takeover; a
    paused old process may still finish RPC work, but cannot publish stale work.
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
        self._lifecycle_lock = threading.Lock()
        self._heartbeat: threading.Thread | None = None
        self._failure: BaseException | None = None
        self._cleanup_thread: threading.Thread | None = None

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
            try:
                if lease.renew(ttl_seconds=self.lease_ttl):
                    continue
                failure = ShutdownIncomplete("snapshot heartbeat lost lease ownership")
            except Exception as exc:
                failure = exc
            self._failure = failure
            self._stop.set()  # no further cycles; in-flight publication is fenced in SQLite
            return

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
            if self._stop.is_set():
                return None  # stop prevents admission of another acquisition
            lease = self._lease_or_none()
            if not lease.acquire_or_renew(ttl_seconds=self.lease_ttl):
                if lease._lost:
                    self._failure = ShutdownIncomplete("snapshot cycle lost lease authority")
                    self._stop.set()
                    raise self._failure
                return None  # foreign holder owns the lease: never double-collect
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=self._renew_until, args=(heartbeat_stop,), daemon=True,
                name="finco-r-live-lease-heartbeat")
            self._heartbeat = heartbeat
            heartbeat.start()
            try:
                rpc = rpc_url or os.getenv("ROBINHOOD_RPC_URL")
                if not rpc:
                    summary = {"state": "RPC_NOT_CONFIGURED", "written": 0}
                else:
                    summary = warm_snapshot_once(rpc, store_path=self.store_path,
                        lease_holder=lease._holder, lease_authority=lease)
                    if summary.get("state") == "LEASE_OWNERSHIP_LOST":
                        raise ShutdownIncomplete("snapshot acquisition lost publication authority")
                if self._failure is not None:
                    raise ShutdownIncomplete("snapshot heartbeat failed during acquisition") from self._failure
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=5)
                if heartbeat.is_alive():
                    self._failure = ShutdownIncomplete("snapshot lease heartbeat is still active")
                    self._stop.set()
                    raise self._failure
                if self._failure is not None and sys.exc_info()[1] is None:   # == sys.exception() (3.11+), 3.10-safe
                    raise ShutdownIncomplete("snapshot heartbeat failed during acquisition") from self._failure
            self.last_summary = summary
            return summary
        finally:
            self._cycle_lock.release()

    def _close_resources_if_idle(self) -> None:
        heartbeat = self._heartbeat
        if heartbeat is not None and heartbeat.is_alive():
            raise ShutdownIncomplete("snapshot lease heartbeat still owns resources")
        if self._lease is not None:
            self._lease.release()
            self._lease.close()
            self._lease = None

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self.run_cycle()
                self._stop.wait(self.interval)
        except BaseException as exc:
            self._failure = exc
        finally:
            try:
                with self._cycle_lock:
                    self._close_resources_if_idle()
            except BaseException as exc:
                self._failure = exc

    def start(self) -> bool:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise ShutdownIncomplete("snapshot warmer is still stopping")
                return False
            if self._failure is not None or (self._cleanup_thread is not None and self._cleanup_thread.is_alive()):
                raise ShutdownIncomplete("snapshot warmer requires completed resource cleanup")
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="finco-r-live-snapshot-warmer")
            try:
                self._thread.start()
            except BaseException:
                self._thread = None
                raise
            return True

    def stop(self) -> None:
        """Request cooperative stop only; use shutdown() to prove completion."""
        self._stop.set()

    def _finish_resource_cleanup(self) -> None:
        try:
            with self._cycle_lock:
                self._close_resources_if_idle()
        except BaseException as exc:
            self._failure = exc

    def shutdown(self, timeout: float = 30.0) -> None:
        """Bound all waiting, including SQLite cleanup and concurrent shutdown.

        An owned cleanup thread may finish a previously admitted database release
        after a failed deadline. Success requires it joined; ownership is retained
        on every failure and no connection is closed under a live acquisition.
        """
        if timeout < 0:
            raise ValueError("negative shutdown deadline")
        deadline = time.monotonic() + timeout
        if not self._lifecycle_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise ShutdownIncomplete("snapshot lifecycle lock deadline")
        try:
            self.stop()
            thread = self._thread
            if thread is not None:
                if thread is threading.current_thread():
                    raise ShutdownIncomplete("snapshot warmer cannot join itself")
                thread.join(max(0, deadline - time.monotonic()))
                if thread.is_alive():
                    raise ShutdownIncomplete("snapshot acquisition is still active")
            heartbeat = self._heartbeat
            if heartbeat is not None:
                heartbeat.join(max(0, deadline - time.monotonic()))
                if heartbeat.is_alive():
                    raise ShutdownIncomplete("snapshot heartbeat is still active")
            cycle_idle = self._cycle_lock.acquire(blocking=False)
            if cycle_idle:
                self._cycle_lock.release()
            # A direct run_cycle may own admission before it creates its lease.
            # Lease absence therefore cannot prove that no writer is in flight.
            needs_cleanup = self._lease is not None or not cycle_idle
            if needs_cleanup and (self._cleanup_thread is None or not self._cleanup_thread.is_alive()):
                self._cleanup_thread = threading.Thread(target=self._finish_resource_cleanup,
                    name="finco-r-live-resource-cleanup", daemon=True)
                self._cleanup_thread.start()
            if self._cleanup_thread is not None:
                self._cleanup_thread.join(max(0, deadline - time.monotonic()))
                if self._cleanup_thread.is_alive():
                    raise ShutdownIncomplete("snapshot resource cleanup deadline")
            if self._lease is not None:
                raise ShutdownIncomplete("snapshot lease cleanup incomplete")
            if self._failure is not None:
                raise ShutdownIncomplete("snapshot warmer failed before clean shutdown") from self._failure
        finally:
            self._lifecycle_lock.release()


_WARMER: RLiveSnapshotWarmer | None = None
_WARMER_LOCK = threading.Lock()
_WARMER_OWNER: object | None = None


def start_background_warmer(*, owner: object | None = None) -> bool:
    """Start the process-local warmer thread (idempotent).

    The SQLite lease guarantees that, across all Uvicorn workers on the
    host, exactly ONE loop actually collects; the others idle.  Disabled
    entirely when ``FINCO_RLIVE_WARMING_ENABLED=0`` (e.g. the dedicated
    systemd collector owns warming in that deployment).
    """
    global _WARMER, _WARMER_OWNER
    if not warming_enabled():
        return False
    with _WARMER_LOCK:
        if _WARMER is not None and _WARMER_OWNER is not owner:
            raise ShutdownIncomplete("snapshot warmer belongs to another lifespan")
        if _WARMER is None:
            _WARMER = RLiveSnapshotWarmer()
            _WARMER_OWNER = owner
        return _WARMER.start()


def stop_background_warmer(*, owner: object, timeout: float = 30.0) -> bool:
    """Stop only this owner's instance. Failed shutdown retains its ownership."""
    global _WARMER, _WARMER_OWNER
    if timeout < 0:
        raise ValueError("negative shutdown deadline")
    deadline = time.monotonic() + timeout
    if not _WARMER_LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
        raise ShutdownIncomplete("snapshot owner lock deadline")
    try:
        if _WARMER is None or _WARMER_OWNER is not owner:
            return False
        _WARMER.shutdown(max(0, deadline - time.monotonic()))
        _WARMER = None
        _WARMER_OWNER = None
        return True
    finally:
        _WARMER_LOCK.release()


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
        warmer = RLiveSnapshotWarmer()
        try:
            summary = warmer.run_cycle(rpc_url=rpc_url)
        finally:
            warmer.shutdown()
        if summary is None:
            summary = {"state": "LEASE_NOT_ACQUIRED", "written": 0}
        print(_json.dumps(summary, sort_keys=True))
        return 0 if summary.get("state") == "OK" else 1
    if args.loop:
        warmer = RLiveSnapshotWarmer()
        warmer.start()
        try:
            while True:
                time.sleep(_interval_seconds())
        except KeyboardInterrupt:
            warmer.shutdown()
        return 0
    parser.print_usage(_sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
