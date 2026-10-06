"""Read-time R-LIVE last-canonical-price presentation.

Acquisition freshness remains strict. A stored latest snapshot is re-evaluated
against the canonical policy exactly as before; STALE still means "no NEW fresh
observation". Product presentation is intentionally separate:

  fresh current snapshot -> present it;
  otherwise -> present the latest complete exact-key AVAILABLE observation from
               the existing digest-verified B1.3 append-only ledger;
  otherwise -> UNAVAILABLE.

A historical fallback is one immutable observation snapshot. Token price,
Robinhood basis, premium, sources and evidence clocks are never mixed with a
newer acquisition. Original timestamps are preserved and only their read-time
ages are calculated. This module performs zero provider calls and zero writes.
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
HISTORY_SOURCE = "CANONICAL_B1_3_HISTORY"

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


def _history_freshness(point: dict, *, now: datetime) -> tuple[dict, dict]:
    """Original evidence clocks plus read-time ages for one B1.3 snapshot."""
    reference = point["independent_token_reference"]
    evidence = reference["evidence"]
    ages = {
        "market_activity_age_seconds": _age_seconds(now, evidence.get("lastPoolActivityAt")),
        "quote_feed_age_seconds": _age_seconds(now, evidence.get("quoteUpdatedAt")),
        "block_age_seconds": _age_seconds(now, evidence.get("blockTimestamp")),
    }
    freshness = {
        **ages,
        "last_pool_activity_at": evidence.get("lastPoolActivityAt"),
        "quote_updated_at": evidence.get("quoteUpdatedAt"),
        "block_timestamp": evidence.get("blockTimestamp"),
        "effective_evidence_at": evidence.get("effectiveObservedAt"),
        "retrieved_at": evidence.get("retrievedAt"),
    }
    return freshness, ages


def _history_fallback_view_row(
    canonical_id: str, record: dict, *, now: datetime,
) -> dict:
    """Project one already-verified B1.3 observation without recomposition."""
    policy = APPROVED_BY_CANONICAL_ID[canonical_id]
    point = record["point"]
    reference = point["independent_token_reference"]
    basis = point["robinhood_basis"]
    sources = point["premium_sources"]
    freshness, ages = _history_freshness(point, now=now)

    data = {
        "exact_asset_key": {
            "canonical_id": policy.asset_key.canonical_id,
            "chain_id": policy.asset_key.chain_id,
            "contract_address": policy.asset_key.contract_address,
        },
        "economic_asset_uid": point["economic_asset_uid"],
        "token_reference": {
            "state": STATE_AVAILABLE,
            "price_usd_per_token": reference["priceUsdPerToken"],
            "source": sources[1],
            "observed_at": reference["observedAt"],
            "reason": reference.get("reason"),
        },
        "robinhood_basis": {
            "state": STATE_AVAILABLE,
            "price_usd_per_token": basis["price_usd_per_token"],
            "source": basis["source"],
            "observed_at": basis["observed_at"],
            "reason": None,
        },
        "b1_0_premium": {
            "state": STATE_AVAILABLE,
            "value_bps": point["reference_premium_bps"],
            "formula": None,
            "reason": None,
        },
        "observed_at": point["observed_at"],
        "freshness": freshness,
    }
    return {
        "canonical_id": canonical_id,
        "display_symbol": policy.symbol,
        "state": STATE_AVAILABLE,
        "data": data,
        "reason": None,
        "source": HISTORY_SOURCE,
        "snapshot": {
            "collected_at": record["collection_clock"],
            "re_evaluated_at": now.isoformat(),
            "evidence_digest": record["digest"],
            "schema_version": None,
        },
        "snapshot_age_seconds": _age_seconds(now, record["collection_clock"]),
        "read_time_ages": ages,
    }


def _unavailable_after_freshness_row(stored_view: dict, *, now: datetime) -> dict:
    """Product state when current acquisition aged out and no B1.3 price exists."""
    return {
        "canonical_id": stored_view.get("canonical_id"),
        "display_symbol": stored_view.get("display_symbol"),
        "state": STATE_UNAVAILABLE,
        "data": {},
        "reason": stored_view.get("reason") or "LAST_CANONICAL_PRICE_UNAVAILABLE",
        "source": stored_view.get("source"),
        "snapshot": stored_view.get("snapshot") or {
            "collected_at": None,
            "re_evaluated_at": now.isoformat(),
            "evidence_digest": None,
            "schema_version": None,
        },
        "snapshot_age_seconds": stored_view.get("snapshot_age_seconds"),
        "read_time_ages": stored_view.get("read_time_ages") or {},
    }


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


REASON_SNAPSHOT_NOT_YET_COLLECTED = "SNAPSHOT_NOT_YET_COLLECTED"


def _uninitialized_view_row(canonical_id: str, *, now: datetime) -> dict:
    """Typed presentation row for an approved asset with NO stored snapshot
    yet (first partial batch / never successfully collected).  The row stays
    visible with an explicit typed reason; NO numeric field is fabricated —
    missing data is never zero."""
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
    return {
        "canonical_id": canonical_id,
        "display_symbol": policy.symbol if policy is not None else None,
        "state": STATE_UNAVAILABLE,
        "data": {},  # no evidence exists yet — nothing to show, nothing invented
        "reason": REASON_SNAPSHOT_NOT_YET_COLLECTED,
        "source": SNAPSHOT_SOURCE,
        "snapshot": {
            "collected_at": None,
            "re_evaluated_at": now.isoformat(),
            "evidence_digest": None,
            "schema_version": None,
        },
        "snapshot_age_seconds": None,
        "read_time_ages": {},
    }


def build_snapshot_view(*, path: str | None = None,
                        now: datetime | None = None) -> dict:
    """Full-universe product view with read-only last-canonical fallback.

    The canonical approved registry remains the universe. Current snapshot
    freshness is an admission/currentness signal only; it never erases a
    previously persisted canonical price. The B1.3 ledger is consulted once
    for the complete exact UID/AssetKey universe and is never mutated.
    """
    from app.radar_rwa.r_live_snapshot_store import read_snapshots_readonly
    from app.radar_rwa.bnb_history import read_latest_r_live_observations_batch_readonly

    started = datetime.now(timezone.utc)
    stored_rows = read_snapshots_readonly(path=path)
    stored_by_id = {row["canonical_id"]: row for row in stored_rows}
    current = now or datetime.now(timezone.utc)

    pairs = [
        (policy.economic_asset_uid, policy.asset_key)
        for policy in APPROVED_BY_CANONICAL_ID.values()
    ]
    try:
        history_by_id = read_latest_r_live_observations_batch_readonly(
            pairs, as_of=current)
    except Exception:
        history_by_id = {}

    rows: list[dict] = []
    for canonical_id in APPROVED_BY_CANONICAL_ID:
        stored = stored_by_id.pop(canonical_id, None)
        current_view = (reevaluate_snapshot_row(stored, now=current)
                        if stored is not None else None)

        if current_view is not None and current_view["state"] == STATE_AVAILABLE:
            rows.append(current_view)
            continue

        historical = history_by_id.get(canonical_id)
        if historical is not None:
            rows.append(_history_fallback_view_row(
                canonical_id, historical, now=current))
            continue

        if current_view is not None:
            rows.append(_unavailable_after_freshness_row(
                current_view, now=current))
        else:
            rows.append(_uninitialized_view_row(canonical_id, now=current))

    # Evidence for unknown ids is never presented (no second registry).
    rows.sort(key=_view_sort_key)
    counts = {
        "available": sum(1 for r in rows if r["state"] == STATE_AVAILABLE),
        "stale": 0,  # acquisition STALE is internal; product rows are LIVE/UNAVAILABLE
        "unavailable": sum(1 for r in rows if r["state"] == STATE_UNAVAILABLE),
        "approved_universe": len(APPROVED_BY_CANONICAL_ID),
    }
    finished = datetime.now(timezone.utc)

    has_persisted_price = any(r["state"] == STATE_AVAILABLE for r in rows)
    top_state = (STATE_INITIALIZING
                 if not stored_rows and not has_persisted_price
                 else STATE_AVAILABLE)
    view = {
        "state": top_state,
        "rows": rows,
        "counts": counts,
        "read_duration_ms": int((finished - started).total_seconds() * 1000),
        "detail": "Full approved R-LIVE universe; fresh current evidence when "
                  "available, otherwise the latest complete canonical B1.3 "
                  "observation with original evidence clocks.",
    }
    if top_state == STATE_INITIALIZING:
        view["reason"] = "NO_CURRENT_OBSERVATION_COLLECTED"
    return view


def _view_sort_key(row: dict):
    order = {STATE_AVAILABLE: 0, STATE_STALE: 1, STATE_UNAVAILABLE: 2}
    return (order.get(row["state"], 3), row["canonical_id"] or "")
