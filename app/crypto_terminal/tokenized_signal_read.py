"""R6 Tokenized Signal Feed V1: read-only, entitlement-guarded R5 presentation.

No signal calculations, event IDs, event store, provider acquisition, writes,
or notification delivery. This is a shared HTML / Crypto API V1 projection of
the immutable R5 Tokenized lifecycle authority.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from app.crypto_terminal.tokenized_signal_lifecycle import (
    CONTRACT_VERSION, MAX_FEED_EVENTS, build_tokenized_signal_lifecycle,
)

MAX_VISIBLE_EVENTS = 30  # bounded detail read; the canonical R5 maximum is 60


def can_read_feed(gates) -> bool:
    """Both existing holder resources are required, including at the caller boundary."""
    return bool(
        gates is not None
        and gates.history.access_allowed
        and gates.dislocation.access_allowed
    )


def _present_event(event) -> dict:
    """Preserve *every* original R5 evidence field, ID and raw source clock."""
    payload = asdict(event)
    payload["kind"] = event.kind.value
    # Historical/current and alert eligibility are canonical R5 facts.
    # Do not reinterpret event time using today's clock or a transport clock.
    payload["temporal_classification"] = event.temporal_classification
    payload["eligible_for_future_alert"] = event.eligible_for_future_alert
    payload["identity"] = asdict(event.identity)
    payload["distribution"] = (
        asdict(event.distribution) if event.distribution is not None else None
    )
    return payload


def read_tokenized_signals(
    canonical_asset_id: str, *,
    gates, registry=None, store=None, as_of: datetime | None = None,
    max_events: int = MAX_VISIBLE_EVENTS,
) -> dict | None:
    """Authorised, bounded shared projection; denied calls perform NO reads.

    Returns None when both entitlements are not granted. The caller MUST
    gate *before* calling, too. If the canonical identity is unknown, raises
    KeyError (handled as HTTP 404 by the existing API vocabulary). A missing
    store yields an honest empty feed without invented observation history.
    """
    if not can_read_feed(gates):
        return None
    if type(max_events) is not int or not (1 <= max_events <= min(MAX_VISIBLE_EVENTS, MAX_FEED_EVENTS)):
        raise ValueError("INVALID_SIGNAL_FEED_LIMIT")
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("SIGNAL_FEED_REQUIRES_AWARE_TIME")

    # This exact identity check is a public registry proof, not an alternative
    # symbol matcher, and must precede any history read.
    if registry is None:
        from app.crypto_terminal.tokenized_read import registry as read_registry
        registry = read_registry()
    underlying = registry.get_underlying(canonical_asset_id)
    if underlying is None or underlying.canonical_symbol != canonical_asset_id:
        raise KeyError("EXACT_CANONICAL_ASSET_UNAVAILABLE")

    if store is None:
        from app.crypto_terminal.tokenized_read import store as read_store
        store = read_store()
    if store is None:
        return {
            "policy_version": CONTRACT_VERSION,
            "canonical_asset_id": canonical_asset_id,
            "as_of": now.astimezone(timezone.utc).isoformat(),
            "state": "HISTORY_UNAVAILABLE",
            "events": [],
            "identities_examined": 0,
            "source_observations_examined": 0,
            "notifications_enabled": False,
            "current_deepstate_signals": "UNAVAILABLE",
        }

    source = build_tokenized_signal_lifecycle(
        canonical_asset_id, registry=registry, store=store,
        as_of=now, include_no_change=False, max_events=max_events,
    )
    # R5 internally computes chronological evidence. Only presentation order
    # changes, and stable IDs/timestamps/digests are preserved byte-for-byte.
    ordered = list(reversed(source.events))
    events = [_present_event(item) for item in ordered]
    return {
        "policy_version": source.policy_version,
        "canonical_asset_id": source.canonical_asset_id,
        "as_of": source.as_of,
        "state": "AVAILABLE" if events else "NO_OBSERVED_EVENTS",
        "events": events,
        "identities_examined": source.identities_examined,
        "source_observations_examined": source.source_observations_examined,
        "notifications_enabled": source.notifications_enabled,
        "current_deepstate_signals": source.current_deepstate_signals,
    }
