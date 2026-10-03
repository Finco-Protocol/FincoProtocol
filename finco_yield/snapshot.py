"""Current Yield snapshot: the latest accepted observation per opportunity.

* The snapshot is a derived, replaceable view; history is the audit trail.
* It is written atomically (temp file + fsync + ``os.replace``): a reader sees
  either the previous complete snapshot or the new complete one, never a
  partial file, and a failed write leaves the previous snapshot untouched.
* It is merged with the previous snapshot: opportunities whose refresh failed
  keep their last-good observation (which the canonical freshness rules will
  classify as STALE once it ages).  A provider failure can never replace a
  valid snapshot with ``[]`` and an empty provider result is not a valid
  empty FINCO universe.
* The FINCO universe is the reference registry.  The snapshot only overlays
  observation values; identity always comes from the reference row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import InvalidOperation
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .durable_io import write_all
from .evidence_v1 import canonical_hash, canonical_json
from .observation import (
    DATA_ORIGIN_REFERENCE_FIXTURE,
    DATA_ORIGIN_SOURCE_OBSERVED,
    SourceObservation,
)
from .registry import (
    RegistryError,
    YieldRegistry,
    _from_row,
    bundled_reference_rows,
)

SNAPSHOT_SCHEMA = "YIELD_CURRENT_SNAPSHOT_V1"
SNAPSHOT_PATH_ENV = "FINCO_YIELD_SNAPSHOT_PATH"

ORIGIN_SNAPSHOT = "SNAPSHOT"
ORIGIN_REFERENCE_FIXTURE = "REFERENCE_FIXTURE"
ORIGIN_REFERENCE_FALLBACK = "REFERENCE_FALLBACK"

# Observation-bearing keys a snapshot row may overlay.  Identity keys
# (chain, protocol, contract, underlying, share token, name) never come from it.
_OVERLAY_KEYS = (
    "tvl_usd", "apy_total", "apy_base", "apy_rewards", "apy_intrinsic",
    "apy_total_30d_avg", "apy_30d_avg_source",
    "observed_at", "block_number", "source_type", "adapter", "adapter_version",
    "data_origin", "provider", "source_record_id", "fetched_at",
    "observed_at_policy", "history_observation_hash", "source_native",
    "freshness_note",
)


class SnapshotError(RuntimeError):
    """The snapshot is missing, unreadable or fails validation (typed code)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SnapshotWriteError(RuntimeError):
    """The atomic replace failed; the previous snapshot is unchanged."""


@dataclass(frozen=True)
class Snapshot:
    generated_at: datetime
    rows: tuple[dict[str, Any], ...]
    content_hash: str


@dataclass(frozen=True)
class RegistrySourceStatus:
    """Why the active registry looks the way it does.  Shown, never hidden."""

    origin: str                      # SNAPSHOT | REFERENCE_FIXTURE | REFERENCE_FALLBACK
    reason: str | None               # typed code when not a clean SNAPSHOT
    generated_at: str | None
    live_rows: int
    reference_rows: int
    rejected_rows: int

    @property
    def is_live(self) -> bool:
        return self.origin == ORIGIN_SNAPSHOT and self.live_rows > 0


def snapshot_path_from_env(env: dict[str, str] | None = None) -> Path | None:
    raw = (env if env is not None else os.environ).get(SNAPSHOT_PATH_ENV, "").strip()
    return Path(raw) if raw else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal_text(value) -> str | None:
    if value is None:
        return None
    return "0" if value == 0 else format(value.normalize(), "f")


def is_valid_observation_hash(value) -> bool:
    """Canonical history observation hash: 64 lower-case hex characters."""
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


# ── building rows ───────────────────────────────────────────────────────────

def snapshot_row(
    base_row: dict[str, Any], observation: SourceObservation, history_hash: str | None,
) -> dict[str, Any]:
    """Bundled-schema-compatible row for ``observation`` on top of its
    reference identity row.  Absent metrics are ``None`` (UNAVAILABLE) and
    deliberately do NOT fall back to the reference value."""
    if not is_valid_observation_hash(history_hash):
        # Authority rule: the current snapshot is derived from canonical history.
        raise ValueError("a snapshot row requires a valid canonical history observation hash")
    row = dict(base_row)
    row.update({
        "opportunity_uid": observation.uid,
        "tvl_usd": _decimal_text(observation.tvl_usd),
        "apy_total": _decimal_text(observation.apy_total),
        "apy_base": _decimal_text(observation.apy_base),
        "apy_rewards": _decimal_text(observation.apy_rewards),
        "apy_total_30d_avg": _decimal_text(observation.apy_total_30d_avg),
        "apy_30d_avg_source": observation.apy_30d_avg_source,
        "apy_intrinsic": None,
        "observed_at": _iso(observation.observed_at),
        "block_number": None,
        "source_type": observation.source_type.value,
        "adapter": observation.adapter,
        "adapter_version": observation.adapter_version,
        "data_origin": DATA_ORIGIN_SOURCE_OBSERVED,
        "provider": observation.provider,
        "source_record_id": observation.source_record_id,
        "fetched_at": _iso(observation.fetched_at),
        "observed_at_policy": observation.observed_at_policy,
        "history_observation_hash": history_hash,
        "source_native": dict(observation.source_native),
        "freshness_note": (
            "Source-observed via the provider API; observed_at follows the "
            f"{observation.observed_at_policy} policy; no direct block-bound "
            "read; not DIRECT_ONCHAIN."
        ),
    })
    return row


def _observed_at(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))


def merge_rows(
    previous: tuple[dict[str, Any], ...], new_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry every previous row forward; a new row replaces its predecessor
    only when it is not older.  Nothing is ever removed.  Stable uid order."""
    merged = {row["opportunity_uid"]: row for row in previous}
    for row in new_rows:
        existing = merged.get(row["opportunity_uid"])
        if existing is None or _observed_at(row) >= _observed_at(existing):
            merged[row["opportunity_uid"]] = row
    return [merged[uid] for uid in sorted(merged)]


def build_snapshot_payload(rows: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: r["opportunity_uid"])
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_at": _iso(generated_at),
        "content_hash": canonical_hash(ordered),
        "rows": ordered,
    }


# ── persistence ─────────────────────────────────────────────────────────────

def write_snapshot_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Replace ``path`` atomically.  On any failure the previous file is
    untouched and the temp file is removed."""
    path = Path(path)
    data = (canonical_json(payload) + "\n").encode("utf-8")
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            write_all(fd, data)       # complete payload first ...
            os.fsync(fd)              # ... then fsync ...
        finally:
            os.close(fd)
        os.chmod(tmp_name, 0o640)     # ... and only then rename over the previous snapshot
        os.replace(tmp_name, path)
        tmp_name = None
        try:  # make the rename itself durable where supported
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception as exc:
        raise SnapshotWriteError("SNAPSHOT_WRITE_FAILED") from exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def read_snapshot(path: Path) -> Snapshot:
    """Validated read.  Missing/corrupt/tampered files raise ``SnapshotError``
    (never an empty snapshot)."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SnapshotError("SNAPSHOT_MISSING") from None
    except (OSError, UnicodeError):
        raise SnapshotError("SNAPSHOT_UNREADABLE") from None
    try:
        payload = json.loads(raw)
    except ValueError:
        raise SnapshotError("SNAPSHOT_MALFORMED") from None
    if not isinstance(payload, dict) or payload.get("schema") != SNAPSHOT_SCHEMA:
        raise SnapshotError("SNAPSHOT_SCHEMA_UNSUPPORTED")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("opportunity_uid") for r in rows):
        raise SnapshotError("SNAPSHOT_MALFORMED")
    if canonical_hash(rows) != payload.get("content_hash"):
        raise SnapshotError("SNAPSHOT_INTEGRITY_FAILED")
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise SnapshotError("SNAPSHOT_MALFORMED") from None
    if generated_at.tzinfo is None:
        raise SnapshotError("SNAPSHOT_MALFORMED")
    return Snapshot(generated_at.astimezone(timezone.utc), tuple(rows), str(payload["content_hash"]))


# ── registry overlay ────────────────────────────────────────────────────────

def load_active_registry(env: dict[str, str] | None = None) -> tuple[YieldRegistry, RegistrySourceStatus]:
    """Reference universe overlaid with the current snapshot when available.

    * snapshot path unset            -> REFERENCE_FIXTURE (not live)
    * snapshot unavailable/invalid   -> REFERENCE_FALLBACK + typed reason
    * snapshot valid                 -> SNAPSHOT; rows without a (valid) live
                                        observation stay REFERENCE_FIXTURE
    """
    base_rows = bundled_reference_rows()
    reference = [_from_row(r, default_origin=DATA_ORIGIN_REFERENCE_FIXTURE) for r in base_rows]
    path = snapshot_path_from_env(env)
    if path is None:
        return YieldRegistry(reference), RegistrySourceStatus(
            ORIGIN_REFERENCE_FIXTURE, "SNAPSHOT_NOT_CONFIGURED", None, 0, len(reference), 0)
    try:
        snapshot = read_snapshot(path)
    except SnapshotError as exc:
        return YieldRegistry(reference), RegistrySourceStatus(
            ORIGIN_REFERENCE_FALLBACK, exc.code, None, 0, len(reference), 0)

    by_uid = {o.uid: row for o, row in zip(reference, base_rows)}
    live: dict[str, Any] = {}
    rejected = 0
    for snap_row in snapshot.rows:
        base_row = by_uid.get(snap_row["opportunity_uid"])
        if base_row is None:      # not in the FINCO universe: ignored, counted
            rejected += 1
            continue
        if not is_valid_observation_hash(snap_row.get("history_observation_hash")):
            # Not backed by canonical history: never presented as source-observed.
            rejected += 1
            continue
        merged = dict(base_row)
        for key in _OVERLAY_KEYS:
            if key in snap_row:
                merged[key] = snap_row[key]
        try:
            candidate = _from_row(merged, default_origin=DATA_ORIGIN_SOURCE_OBSERVED)
        except (RegistryError, ValueError, KeyError, TypeError, InvalidOperation):
            rejected += 1
            continue
        # Identity is the reference identity: a snapshot row may never move it.
        if candidate.uid != snap_row["opportunity_uid"] or candidate.data_origin != DATA_ORIGIN_SOURCE_OBSERVED:
            rejected += 1
            continue
        live[candidate.uid] = candidate
    opportunities = [live.get(o.uid, o) for o in reference]
    status = RegistrySourceStatus(
        ORIGIN_SNAPSHOT, None if live else "SNAPSHOT_HAS_NO_LIVE_ROWS",
        _iso(snapshot.generated_at), len(live), len(opportunities) - len(live), rejected)
    return YieldRegistry(opportunities), status


# ── presentation guards (no second freshness classifier) ───────────────────

def origin_label(opportunity) -> str:
    if opportunity.data_origin == DATA_ORIGIN_SOURCE_OBSERVED:
        return "Source-observed"
    if opportunity.data_origin == DATA_ORIGIN_REFERENCE_FIXTURE:
        return "Reference fixture — not live"
    return "Unspecified origin"


def displayed_freshness(opportunity, canonical_state: str) -> str:
    """Canonical freshness state, except that a reference fixture is never shown
    as CURRENT (reference != live).  STALE/INVALID etc. pass through unchanged."""
    if opportunity.data_origin == DATA_ORIGIN_REFERENCE_FIXTURE and canonical_state == "CURRENT":
        return "REFERENCE"
    return canonical_state
