"""Offline, zero-source-write closeout audit for Tokenized Markets Radar V1.

Only committed registry and persisted observation evidence is used. The
VenueMarketStore schema initializer is NEVER pointed at the source DB.
This tool is an operator diagnostic, not a release approval or a provider.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any

from finco_radar.venues.store import VenueMarketStore, default_db_path
from finco_radar.venues.health import read_tokenized_collector_health
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.intelligence import build_tokenized_intelligence
from finco_radar.venues.relative_value import (
    MIN_USABLE_OBSERVATIONS, MIN_HISTORY_SPAN_SECONDS,
    compute_basis_distribution, compute_dislocation_persistence,
)
from finco_radar.venues.robinhood_live import EVIDENCE_CLOCK_CONTRACT
from finco_radar.venues.basis import BASIS_MAX_CLOCK_SKEW_SECONDS
from app.crypto_terminal.deepstate_composition import (
    RAW_COMPARISON_UNIT, CURRENT_CROSS_VENUE,
    build_deepstate_historical_context,
)

MAX_UNDERLYINGS = 60
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
AUDIT_CONTRACT = "RADAR_V1_READ_ONLY_CLOSEOUT_AUDIT_V1"
EXPECTED_COLUMNS = frozenset({
    "digest", "ts", "collected_at", "canonical_asset_id", "venue_id",
    "instrument_id", "instrument_type", "price", "reference_price",
    "basis_bps", "freshness_state", "observation_status", "payload",
})


class AuditBlocked(RuntimeError):
    """A source, provenance or boundedness problem; never interpret as PASS."""


def _as_of(raw: str | None) -> datetime:
    now = datetime.now(timezone.utc) if raw is None else datetime.fromisoformat(raw)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("--as-of must contain a timezone offset")
    return now.astimezone(timezone.utc)


def _git_sha() -> str | None:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            text=True, capture_output=True, timeout=3, check=True,
        ).stdout.strip()
        return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _source_signature(path: Path) -> tuple[int, int, int, int, int]:
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _existing_safe_source(path: Path, max_bytes: int) -> tuple[int, int, int, int, int]:
    if not path.is_file() or path.is_symlink():
        raise AuditBlocked("DATA_NOT_READY: observation database is missing or is a symlink")
    sig = _source_signature(path)
    if sig[2] <= 0 or sig[2] > max_bytes:
        raise AuditBlocked("DATA_NOT_READY: observation database size is outside the configured bound")
    # Immutable SQLite reads may ignore a live WAL. Such a snapshot would
    # silently omit real observations. Require an operator-produced checkpoint
    # or independent consistent DB copy instead of making that claim.
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise AuditBlocked("SOURCE_WAL_ACTIVE: supply a consistent checkpointed offline copy")
    return sig


def _readonly_snapshot(source: Path, destination: Path, max_bytes: int) -> dict:
    """Source immutable read-only URI; all schema work occurs on destination."""
    before = _existing_safe_source(source, max_bytes)
    uri = source.resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as src:
            src.execute("PRAGMA query_only=ON")
            if src.execute("PRAGMA database_list").fetchone()[2] != str(source.resolve()):
                raise AuditBlocked("SOURCE_PATH_IDENTITY_MISMATCH")
            with sqlite3.connect(destination) as dst:
                src.backup(dst, pages=256, sleep=0.02)
                dst.commit()
    except sqlite3.DatabaseError as exc:
        raise AuditBlocked("DATA_CORRUPT: SQLite read-only snapshot failed") from exc
    after = _existing_safe_source(source, max_bytes)
    if before != after:
        raise AuditBlocked("SOURCE_CHANGED_DURING_AUDIT")
    if destination.stat().st_size > max_bytes:
        raise AuditBlocked("AUDIT_COPY_SIZE_LIMIT_EXCEEDED")
    return {"source_bytes": before[2], "source_file_unchanged": before == after,
            "copy_kind": "TEMPORARY_OFFLINE_SNAPSHOT", "source_database_created": False}


def _snapshot_integrity(copy: Path) -> dict:
    uri = copy.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise AuditBlocked("DATA_CORRUPT: snapshot quick_check failed")
            columns = {r[1] for r in db.execute("PRAGMA table_info(market_observations)")}
            if not EXPECTED_COLUMNS.issubset(columns):
                raise AuditBlocked("DATA_CORRUPT: observation schema is missing required columns")
            rows = db.execute(
                "SELECT COUNT(*),COUNT(DISTINCT ts),MAX(ts),MAX(collected_at),"
                "SUM(CASE WHEN ts IS NULL THEN 1 ELSE 0 END) "
                "FROM market_observations"
            ).fetchone()
            clock_counts = db.execute(
                "SELECT SUM(CASE WHEN json_valid(payload) AND "
                "json_extract(payload,'$.evidence_clock_contract')=? THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN NOT json_valid(payload) OR "
                "COALESCE(json_extract(payload,'$.evidence_clock_contract'),'')<>? "
                "THEN 1 ELSE 0 END) FROM market_observations",
                (EVIDENCE_CLOCK_CONTRACT, EVIDENCE_CLOCK_CONTRACT),
            ).fetchone()
            # No source row is updated or silently migrated.
            return {
                "total_observations": rows[0], "distinct_source_times": rows[1],
                "latest_source_timestamp": rows[2],
                "latest_collected_at": rows[3], "missing_source_times": rows[4],
                "v2_clock_rows": clock_counts[0] or 0,
                "other_or_legacy_clock_rows": clock_counts[1] or 0,
            }
    except sqlite3.DatabaseError as exc:
        raise AuditBlocked("DATA_CORRUPT: bounded snapshot query failed") from exc


def _identity_counts(copy: Path, symbol: str, history: Any) -> dict:
    uri = copy.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        raw = db.execute(
            "SELECT COUNT(*),SUM(CASE WHEN observation_status='OK' "
            "AND price IS NOT NULL AND ts IS NOT NULL THEN 1 ELSE 0 END),"
            "COUNT(DISTINCT ts) FROM market_observations "
            "WHERE canonical_asset_id=? AND venue_id=? "
            "AND instrument_id=? AND instrument_type=?",
            (symbol, history.venue_id, history.instrument_id, history.representation_type),
        ).fetchone()
    return {
        "total_stored_observations": raw[0],
        "status_ok_priced_source_timed_rows": raw[1] or 0,
        "distinct_source_timestamps": raw[2],
    }


def _audit_assets(registry: VenueRegistry, store: VenueMarketStore,
                  copy: Path, now: datetime, max_assets: int) -> list[dict]:
    from finco_radar.venues.models import RegistryStatus
    eligible = [
        symbol for symbol in sorted(registry._underlyings)
        if any(r.status is RegistryStatus.ACTIVE
               for r in registry.representations_for_underlying(symbol))
    ][:max_assets]
    results = []
    for symbol in eligible:
        intel = build_tokenized_intelligence(
            symbol, registry=registry, store=store,
            as_of=now, include_points=True)
        for h in intel.representations:
            distribution = compute_basis_distribution(h, now=now)
            persistence = compute_dislocation_persistence(h, now=now)
            usable = [p.t for p in h.points if p.v is not None and p.t]
            rejected = Counter(p.reason or "UNAVAILABLE" for p in h.points if p.v is None)
            current = h.current_state == "AVAILABLE" and h.latest_basis_bps is not None
            results.append({
                "canonical_asset_id": symbol,
                "identity": {
                    "venue_id": h.venue_id, "instrument_id": h.instrument_id,
                    "instrument_type": h.representation_type,
                },
                **_identity_counts(copy, symbol, h),
                "basis_valid_history_points": len(usable),
                "basis_rejection_reasons": dict(sorted(rejected.items())),
                "earliest_usable_source_timestamp": min(usable) if usable else None,
                "latest_usable_source_timestamp": max(usable) if usable else None,
                "eligible_source_span_seconds": distribution.history_span_seconds,
                "clock_contract_valid": bool(usable),
                "basis_valid": h.latest_basis_bps is not None,
                "history_sufficient": (
                    distribution.usable_observation_count >= MIN_USABLE_OBSERVATIONS
                    and (distribution.history_span_seconds or 0) >= MIN_HISTORY_SPAN_SECONDS),
                "distribution_state": distribution.state,
                "distribution_available": distribution.historical_median_basis_bps is not None,
                "current_evidence_available": current,
                "current_basis_bps": h.latest_basis_bps if current else None,
                "last_canonical_basis_bps": h.latest_basis_bps,
                "latest_basis_reason": h.latest_basis_reason,
                "persistence_state": persistence.state,
                "dislocation_start_state": persistence.start_state,
                "proven_duration_seconds": persistence.duration_seconds,
            })
    return results


def run_audit(source: Path, *, as_of: datetime, max_assets: int = MAX_UNDERLYINGS,
              max_db_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    if not 1 <= max_assets <= MAX_UNDERLYINGS:
        raise ValueError("max_assets must be between 1 and 60")
    if not 4096 <= max_db_bytes <= 2 * 1024**3:
        raise ValueError("max_db_bytes must be between 4KiB and 2GiB")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    now = as_of.astimezone(timezone.utc)
    source = Path(source).expanduser().absolute()
    # Hold the full original signature across the entire computation, not
    # merely the backup step. Changes at the same byte length still block.
    source_signature = _existing_safe_source(source, max_db_bytes)
    # Missing data never causes a new SQLite file to be created.
    with tempfile.TemporaryDirectory(prefix="finco-radar-closeout-") as directory:
        offline_copy = Path(directory) / "snapshot.db"
        source_proof = _readonly_snapshot(source, offline_copy, max_db_bytes)
        db = _snapshot_integrity(offline_copy)
        registry = VenueRegistry.load()
        # VenueMarketStore initializes its schema; the only target is the
        # temporary copy. A source DB is NEVER passed to the constructor.
        store = VenueMarketStore(offline_copy)
        health = read_tokenized_collector_health(path=str(offline_copy), now=now)
        assets = _audit_assets(registry, store, offline_copy, now, max_assets)
        deepstate = build_deepstate_historical_context(
            "NVDA", registry=registry, store=store, as_of=now)
        proof_after = _existing_safe_source(source, max_db_bytes)
        if proof_after != source_signature:
            raise AuditBlocked("SOURCE_CHANGED_DURING_AUDIT")
    return {
        "contract": AUDIT_CONTRACT,
        "evaluated_git_sha": _git_sha(),
        "evaluated_at": now.isoformat(),
        "source": {"name": source.name, **source_proof,
                   "source_file_unchanged": True},
        "status": "EVIDENCE_AUDITED" if db["total_observations"] else "DATA_NOT_READY",
        "observation_store": db,
        "evidence_policies": {
            "clock_contract_v2": EVIDENCE_CLOCK_CONTRACT,
            "canonical_identity": "VENUE_REGISTRY_EXACT_IDENTITY",
            "min_usable_observations": MIN_USABLE_OBSERVATIONS,
            "min_history_span_seconds": MIN_HISTORY_SPAN_SECONDS,
            "basis_max_clock_skew_seconds": BASIS_MAX_CLOCK_SKEW_SECONDS,
        },
        "collector_health": health.public_dict(),
        "monitored_representations": len(assets),
        "representations": assets,
        "deepstate": {
            "historical_state": deepstate.state,
            "historical_reason": deepstate.reason,
            "real_historical_execution_count": sum(
                x.evidence_state == "HISTORICAL_EXECUTION_PROVEN"
                for x in deepstate.evidence),
            "historical_comparison_count": sum(
                x.state == "HISTORICAL_COMPARISON_AVAILABLE"
                for x in deepstate.historical_comparisons),
            "raw_unit": RAW_COMPARISON_UNIT,
            "normalization_authority": "NOT_APPROVED_FOR_CURRENT_MARKET",
            "current_cross_venue": CURRENT_CROSS_VENUE,
            "current_executable_quote": deepstate.current_executable_quote_state,
        },
        "release_gate": "NOT_ASSESSED_NO_DEPLOYMENT_EVIDENCE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=default_db_path())
    parser.add_argument("--as-of", default=None, help="Offset-aware ISO-8601 timestamp")
    parser.add_argument("--max-assets", type=int, default=MAX_UNDERLYINGS)
    parser.add_argument("--max-db-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    try:
        result = run_audit(
            Path(args.db_path), as_of=_as_of(args.as_of),
            max_assets=args.max_assets, max_db_bytes=args.max_db_bytes)
        code = 0 if result["status"] == "EVIDENCE_AUDITED" else 2
    except (AuditBlocked, ValueError, OSError) as exc:
        reason = str(exc).split(":")[0]
        result = {
            "contract": AUDIT_CONTRACT, "status": "DATA_NOT_READY"
            if reason.startswith("DATA_NOT_READY") else "BLOCKED",
            "reason": reason, "release_gate": "NOT_ASSESSED",
        }
        code = 2 if reason.startswith("DATA_NOT_READY") else 3
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    print("FINCO RADAR CLOSEOUT: " + result["status"], file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
