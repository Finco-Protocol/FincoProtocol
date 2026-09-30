"""Read-time freshness re-evaluation for stored R-LIVE snapshots.

A stored observation is NOT automatically current.  At every presentation
read the view re-evaluates the stored evidence against the existing
canonical R-LIVE policy (``finco_radar/authority/r_live_policy.py`` —
imported, never modified):

  AVAILABLE  — every re-checkable freshness dimension is still inside its
               canonical window at read time;
  STALE      — at least one dimension has aged past its canonical window
               (the observation is honest history, clearly labelled);
  UNAVAILABLE— the stored evidence is incomplete/invalid (no fabricated
               currentness).

Integrity rules:
  - the stored evidence timestamps are read as-is; ages are computed as
    ``now - evidence_timestamp`` and NEVER written back into the payload;
  - ``collected_at`` (collector clock) is presentation metadata only and is
    never substituted for an evidence timestamp;
  - no evidence is refreshed, re-fetched or fabricated on the read path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from finco_radar.authority.r_live_policy import (
    APPROVED_BY_CANONICAL_ID,
    MAX_BLOCK_AGE_SECONDS,
    MAX_QUOTE_AGE_SECONDS,
    TWAP_WINDOW_SECONDS,
)

SNAPSHOT_SOURCE = "LATEST_SNAPSHOT"

STATE_AVAILABLE = "AVAILABLE"
STATE_STALE = "STALE"
STATE_UNAVAILABLE = "UNAVAILABLE"
STATE_INITIALIZING = "INITIALIZING"

# Typed stale reasons (stable uppercase tokens; safe for logs and UI).
STALE_BLOCK = "SNAPSHOT_EVIDENCE_BLOCK_EXPIRED"
STALE_POOL_ACTIVITY = "SNAPSHOT_EVIDENCE_POOL_ACTIVITY_EXPIRED"
STALE_QUOTE = "SNAPSHOT_EVIDENCE_QUOTE_EXPIRED"
UNAVAILABLE_INCOMPLETE_EVIDENCE = "SNAPSHOT_EVIDENCE_INCOMPLETE"


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age_seconds(now: datetime, evidence_iso: Any) -> Optional[int]:
    evidence = _parse_iso(evidence_iso)
    if evidence is None:
        return None
    seconds = (now - evidence).total_seconds()
    return int(seconds) if seconds >= 0 else None


def _pool_activity_max_age(canonical_id: str) -> int:
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
    if policy is None:
        return TWAP_WINDOW_SECONDS
    return int(getattr(policy, "max_pool_activity_age_seconds", TWAP_WINDOW_SECONDS))


def reevaluate_snapshot_row(stored: dict, *, now: datetime | None = None) -> dict:
    """Re-evaluate ONE stored snapshot row against canonical freshness policy.

    ``stored`` is a row from ``read_snapshots_readonly``: canonical_id,
    state, payload ({"canonical_id","state","data"}), evidence_digest,
    collected_at.  Returns a presentation row carrying the ORIGINAL evidence
    payload unchanged plus re-evaluated state and typed reason.
    """
    current = now or datetime.now(timezone.utc)
    payload = stored.get("payload") or {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = {}
    canonical_id = stored.get("canonical_id") or payload.get("canonical_id") or ""
    stored_state = payload.get("state") or stored.get("state")

    if stored_state == STATE_UNAVAILABLE:
        return _view_row(stored, data, STATE_UNAVAILABLE, now=current,
                         reason=stored.get("payload", {}).get("state"))

    freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
    block_age = _age_seconds(current, freshness.get("block_timestamp"))
    pool_age = _age_seconds(current, freshness.get("last_pool_activity_at"))
    quote_age = _age_seconds(current, freshness.get("quote_updated_at"))

    # Incomplete evidence can never be presented as current.
    if block_age is None or pool_age is None:
        return _view_row(stored, data, STATE_UNAVAILABLE, now=current,
                         reason=UNAVAILABLE_INCOMPLETE_EVIDENCE)

    reasons = []
    if block_age > MAX_BLOCK_AGE_SECONDS:
        reasons.append(STALE_BLOCK)
    if pool_age > _pool_activity_max_age(canonical_id):
        reasons.append(STALE_POOL_ACTIVITY)
    if quote_age is not None and quote_age > MAX_QUOTE_AGE_SECONDS:
        reasons.append(STALE_QUOTE)

    if reasons:
        return _view_row(stored, data, STATE_STALE, now=current, reason=reasons[0],
                         ages={"block_age_seconds": block_age,
                               "market_activity_age_seconds": pool_age,
                               "quote_feed_age_seconds": quote_age})
    return _view_row(stored, data, STATE_AVAILABLE, now=current,
                     ages={"block_age_seconds": block_age,
                           "market_activity_age_seconds": pool_age,
                           "quote_feed_age_seconds": quote_age})


def _view_row(stored: dict, data: dict, state: str, *, now: datetime,
              reason: str | None = None, ages: dict | None = None) -> dict:
    collected_at = stored.get("collected_at")
    return {
        "canonical_id": stored.get("canonical_id"),
        "display_symbol": _display_symbol(stored.get("canonical_id")),
        "state": state,
        "data": data,  # original acquisition evidence — byte-identical content
        "reason": reason,
        "source": SNAPSHOT_SOURCE,
        "snapshot": {
            "collected_at": collected_at,
            "re_evaluated_at": now.isoformat(),
            "evidence_digest": stored.get("evidence_digest"),
            "schema_version": stored.get("payload", {}).get("schema_version")
            if isinstance(stored.get("payload"), dict) else None,
        },
        "snapshot_age_seconds": _age_seconds(now, collected_at),
        "read_time_ages": ages or {},
    }


def _display_symbol(canonical_id: str | None) -> str | None:
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id or "")
    return policy.symbol if policy is not None else None


def build_snapshot_view(*, path: str | None = None,
                        now: datetime | None = None) -> dict:
    """Full snapshot view for the presentation endpoint.

    Cold start (no snapshot yet): typed INITIALIZING — the page renders
    immediately and never blocks on live acquisition.
    """
    from app.radar_rwa.r_live_snapshot_store import read_snapshots_readonly

    started = datetime.now(timezone.utc)
    stored_rows = read_snapshots_readonly(path=path)
    if not stored_rows:
        return {
            "state": STATE_INITIALIZING,
            "reason": "NO_CURRENT_OBSERVATION_COLLECTED",
            "rows": [],
            "detail": "No current observation has been collected yet. "
                      "The background collector fills the snapshot independently.",
        }
    current = now or datetime.now(timezone.utc)
    rows = [reevaluate_snapshot_row(stored, now=current) for stored in stored_rows]
    rows.sort(key=_view_sort_key)
    counts = {
        "available": sum(1 for r in rows if r["state"] == STATE_AVAILABLE),
        "stale": sum(1 for r in rows if r["state"] == STATE_STALE),
        "unavailable": sum(1 for r in rows if r["state"] == STATE_UNAVAILABLE),
    }
    finished = datetime.now(timezone.utc)
    return {
        "state": "AVAILABLE",
        "rows": rows,
        "counts": counts,
        "read_duration_ms": int((finished - started).total_seconds() * 1000),
        "detail": "Latest collected observations, freshness re-evaluated at "
                  "read time against the canonical R-LIVE policy.",
    }


def _view_sort_key(row: dict):
    order = {STATE_AVAILABLE: 0, STATE_STALE: 1, STATE_UNAVAILABLE: 2}
    return (order.get(row["state"], 3), row["canonical_id"] or "")
