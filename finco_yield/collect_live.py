"""One-shot FINCO Yield live collector.

    python -m finco_yield.collect_live

SOURCE -> RAW OBSERVATION -> CANONICAL NORMALIZATION -> CURRENT SNAPSHOT
       -> APPEND-ONLY HISTORY -> existing Yield product.

Read-only and credential-free: it performs no transaction, signing or custody
and never touches the execution flag.  It is disabled unless
``FINCO_YIELD_COLLECTOR_ENABLED`` is truthy.

Environment (no secrets are ever printed):

    FINCO_YIELD_COLLECTOR_ENABLED             1 to allow a run (default off)
    FINCO_YIELD_SNAPSHOT_PATH                 current snapshot JSON (required)
    FINCO_YIELD_HISTORY_PATH                  append-only history JSONL (required)
    FINCO_YIELD_MORPHO_API_URL                optional endpoint override
    FINCO_YIELD_SOURCE_TIMEOUT_SECONDS        per-request timeout (default 8)
    FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS  unchanged-observation heartbeat
                                              (default 900, max 1500)

Exit codes (explicit, tested):

    0   OK        every attempted target accepted; snapshot + history updated
    2   FAILED    nothing usable persisted (no accepted observation, or the
                  snapshot write failed); previous snapshot is untouched
    3   PARTIAL   >=1 observation accepted and snapshot updated, but some
                  targets/providers failed, were rejected, or history failed
    4   DISABLED / CONFIG_ERROR   collector not enabled or paths missing
    75  LOCKED    another collector run holds the lock (matches ``flock -E 75``)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable

from .flags import _TRUE
from .history import HistoryCorruptionError, YieldHistoryStore
from .live_sources import MorphoGraphQLAdapter, SourceAdapter, SourceTarget, source_timeout_seconds
from .observation import SourceObservation
from .registry import _from_row, bundled_reference_rows
from .snapshot import (
    SnapshotError,
    SnapshotWriteError,
    build_snapshot_payload,
    merge_rows,
    read_snapshot,
    snapshot_path_from_env,
    snapshot_row,
    write_snapshot_atomic,
)

REPORT_SCHEMA = "YIELD_COLLECTION_REPORT_V1"
EXIT_OK, EXIT_FAILED, EXIT_PARTIAL, EXIT_CONFIG, EXIT_LOCKED = 0, 2, 3, 4, 75
DEFAULT_MIN_INTERVAL_SECONDS = 900
# Must stay below the NATIVE_ENRICHED freshness window (1800 s) so the latest
# history row never ages into STALE while the collector is healthy.
MAX_MIN_INTERVAL_SECONDS = 1500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def history_min_interval(env: dict[str, str]) -> int:
    raw = env.get("FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MIN_INTERVAL_SECONDS
    except ValueError:
        return DEFAULT_MIN_INTERVAL_SECONDS
    return max(0, min(value, MAX_MIN_INTERVAL_SECONDS))


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "fetched_at"}


def _append_history(
    store: YieldHistoryStore, observations: list[SourceObservation], min_interval: int,
) -> tuple[dict[str, str | None], dict[str, Any]]:
    """Append each observation unless it is an exact retry or an unchanged
    re-observation inside the heartbeat interval.  Returns (uid -> history
    hash covering the observation, counts)."""
    covering: dict[str, str | None] = {}
    counts = {"appended": 0, "skipped_duplicate": 0, "skipped_unchanged": 0, "failed": 0}
    for obs in observations:
        try:
            record = obs.to_history_record()
            latest = store.latest(obs.uid)
            if (latest is not None
                    and _content(latest.get("payload") or {}) == _content(record.payload)
                    and timedelta(0) <= obs.observed_at - datetime.fromisoformat(
                        str(latest["observed_at"]).replace("Z", "+00:00"))
                    < timedelta(seconds=min_interval)):
                covering[obs.uid] = latest.get("observation_hash")
                counts["skipped_unchanged"] += 1
                continue
            digest, appended = store.append_idempotent(record)
            covering[obs.uid] = digest
            counts["appended" if appended else "skipped_duplicate"] += 1
        except (HistoryCorruptionError, OSError, ValueError, KeyError, TypeError):
            covering[obs.uid] = None
            counts["failed"] += 1
    counts["result"] = (
        "FAILED" if counts["failed"] and not (counts["appended"] or counts["skipped_duplicate"] or counts["skipped_unchanged"])
        else "PARTIAL" if counts["failed"] else "OK"
    ) if observations else "SKIPPED"
    return covering, counts


def run_collection(
    *,
    adapters: list[SourceAdapter],
    store: YieldHistoryStore,
    snapshot_path: Path,
    min_interval: int,
    now: Callable[[], datetime] = _utcnow,
) -> dict[str, Any]:
    started = now()
    base_rows = bundled_reference_rows()
    reference = [_from_row(r) for r in base_rows]
    base_by_uid = {o.uid: row for o, row in zip(reference, base_rows)}
    targets = [SourceTarget.from_opportunity(o) for o in reference]

    provider_detail: dict[str, Any] = {}
    accepted: dict[str, SourceObservation] = {}
    rejected = 0
    in_run_duplicates = 0
    for adapter in adapters:
        try:
            result = adapter.fetch([t for t in targets if adapter.supports(t)])
        except Exception:
            provider_detail[adapter.provider_id] = {
                "status": "FAILED", "targets_attempted": 0, "accepted": 0,
                "failures": [{"uid": None, "code": "SOURCE_ADAPTER_ERROR", "rejected": False}],
            }
            continue
        rejected += sum(1 for f in result.failures if f.rejected)
        provider_detail[adapter.provider_id] = {
            "status": result.status,
            "targets_attempted": result.targets_attempted,
            "accepted": len(result.observations),
            "failures": [{"uid": f.uid, "code": f.code, "rejected": f.rejected} for f in result.failures],
        }
        for obs in result.observations:
            known = accepted.get(obs.uid)
            if known is not None:
                in_run_duplicates += 1
                if obs.observed_at <= known.observed_at:
                    continue
            accepted[obs.uid] = obs
    ordered = [accepted[uid] for uid in sorted(accepted)]

    # History first (audit trail), then the derived current snapshot.
    covering, history = _append_history(store, ordered, min_interval) if ordered else ({}, {
        "appended": 0, "skipped_duplicate": 0, "skipped_unchanged": 0, "failed": 0, "result": "SKIPPED"})

    snapshot_update: dict[str, Any] = {"result": "SKIPPED", "rows": None, "previous_preserved": True, "reason": None}
    if ordered:
        previous_rows: tuple[dict[str, Any], ...] = ()
        try:
            previous_rows = read_snapshot(snapshot_path).rows
        except SnapshotError as exc:
            if exc.code != "SNAPSHOT_MISSING":
                try:  # keep the unusable file as evidence before replacing it
                    shutil.copy2(snapshot_path, snapshot_path.with_name(snapshot_path.name + ".corrupt"))
                except OSError:
                    pass
        new_rows = [snapshot_row(base_by_uid[o.uid], o, covering.get(o.uid)) for o in ordered]
        try:
            payload = build_snapshot_payload(merge_rows(previous_rows, new_rows), now())
            write_snapshot_atomic(snapshot_path, payload)
            snapshot_update = {"result": "UPDATED", "rows": len(payload["rows"]),
                               "previous_preserved": False, "reason": None}
        except (SnapshotWriteError, ValueError, KeyError):
            snapshot_update = {"result": "FAILED", "rows": None, "previous_preserved": True,
                               "reason": "SNAPSHOT_WRITE_FAILED"}
    else:
        snapshot_update["reason"] = "NO_ACCEPTED_OBSERVATIONS"

    any_failure = (
        rejected > 0
        or any(d["failures"] or d["status"] != "SUCCEEDED" for d in provider_detail.values())
        or history["failed"] > 0
    )
    if not ordered or snapshot_update["result"] == "FAILED":
        status, code = "FAILED", EXIT_FAILED
    elif any_failure:
        status, code = "PARTIAL", EXIT_PARTIAL
    else:
        status, code = "OK", EXIT_OK

    finished = now()
    attempted = list(provider_detail)
    succeeded = [p for p, d in provider_detail.items() if d["accepted"] > 0]
    return {
        "schema": REPORT_SCHEMA,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "providers_attempted": attempted,
        "providers_succeeded": succeeded,
        "providers_failed": [p for p in attempted if p not in succeeded],
        "provider_detail": provider_detail,
        "observations_fetched": len(ordered) + rejected + in_run_duplicates,
        "observations_accepted": len(ordered),
        "observations_rejected": rejected,
        "duplicates_skipped": (
            in_run_duplicates + history["skipped_duplicate"] + history["skipped_unchanged"]),
        "history_append": history,
        "snapshot_update": snapshot_update,
        "status": status,
        "exit_code": code,
    }


def _emit(report: dict[str, Any], out) -> None:
    out.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    out.flush()


def _early(status: str, code: int, now: datetime, reason: str) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA, "started_at": _iso(now), "finished_at": _iso(now),
        "providers_attempted": [], "providers_succeeded": [], "providers_failed": [],
        "observations_fetched": 0, "observations_accepted": 0, "observations_rejected": 0,
        "duplicates_skipped": 0,
        "history_append": {"result": "SKIPPED"}, "snapshot_update": {"result": "SKIPPED"},
        "status": status, "reason": reason, "exit_code": code,
    }


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    adapters: list[SourceAdapter] | None = None,
    now: Callable[[], datetime] = _utcnow,
    out=None,
) -> int:
    argparse.ArgumentParser(
        prog="python -m finco_yield.collect_live",
        description="One-shot FINCO Yield live collection (read-only).",
    ).parse_args(argv)
    env = dict(os.environ) if env is None else env
    out = out or sys.stdout

    if env.get("FINCO_YIELD_COLLECTOR_ENABLED", "0").strip().lower() not in _TRUE:
        _emit(_early("DISABLED", EXIT_CONFIG, now(), "FINCO_YIELD_COLLECTOR_ENABLED is not set"), out)
        return EXIT_CONFIG
    snapshot_path = snapshot_path_from_env(env)
    history_raw = env.get("FINCO_YIELD_HISTORY_PATH", "").strip()
    if snapshot_path is None or not history_raw:
        _emit(_early("CONFIG_ERROR", EXIT_CONFIG, now(),
                     "FINCO_YIELD_SNAPSHOT_PATH and FINCO_YIELD_HISTORY_PATH are required"), out)
        return EXIT_CONFIG

    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(snapshot_path.with_name(snapshot_path.name + ".collect.lock"), "a+")
    except OSError:
        _emit(_early("CONFIG_ERROR", EXIT_CONFIG, now(), "snapshot directory is not writable"), out)
        return EXIT_CONFIG
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _emit(_early("LOCKED", EXIT_LOCKED, now(), "another collector run is active"), out)
            return EXIT_LOCKED
        if adapters is None:
            try:
                adapters = [MorphoGraphQLAdapter(
                    url=env.get("FINCO_YIELD_MORPHO_API_URL", "").strip() or None,
                    timeout=source_timeout_seconds(env))]
            except ValueError:
                _emit(_early("CONFIG_ERROR", EXIT_CONFIG, now(), "invalid provider endpoint configuration"), out)
                return EXIT_CONFIG
        report = run_collection(
            adapters=adapters,
            store=YieldHistoryStore(history_raw),
            snapshot_path=snapshot_path,
            min_interval=history_min_interval(env),
            now=now,
        )
        _emit(report, out)
        return int(report["exit_code"])
    finally:
        lock.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
