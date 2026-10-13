"""R3 Deepstate historical MARKET composition (read-only, release-closed).

This is an additive *consumer* of reviewed source/identity authorities, not
another collector, registry representation, pricing engine or live quote.
The existing #179/#183 intelligence and current divergence remain unchanged.

No production Deepstate USDG/USD normalization eligibility policy is approved.
Callers MUST NOT supply a normalization_policy in production before an
independent source-specific approval. An explicit policy seam exists for
deterministic candidate evaluation only, never for current-price activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from finco_radar.authority.r_live_policy import (
    APPROVED_BY_CANONICAL_ID, QUOTE_AUTHORITY_VERSION,
)
from finco_radar.venues.basis import BASIS_MAX_CLOCK_SKEW_SECONDS, compute_basis_bps
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_BOOK_ID, DEEPSTATE_CHAIN_ID, DEEPSTATE_POOL_ID,
    DEEPSTATE_ROUTER, DEEPSTATE_VENUE, normalize_to_usd,
)
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import (
    FreshnessState, MarketObservation, ObservationStatus,
)
from finco_radar.venues.robinhood_live import COMPARISON_UNIT, EVIDENCE_CLOCK_CONTRACT

if TYPE_CHECKING:
    from finco_radar.venues.registry import VenueRegistry
    from finco_radar.venues.store import VenueMarketStore


HISTORY_WINDOW = timedelta(days=30)
MAX_HISTORICAL_FILLS = 120
RAW_COMPARISON_UNIT = "USDG_PER_NVDA"
NORMALIZED_COMPARISON_UNIT = COMPARISON_UNIT
CURRENT_CROSS_VENUE = "UNAVAILABLE"


@dataclass(frozen=True)
class ReviewedNormalizationPolicy:
    """Candidate *historical* quote-age test contract, not production approval.

    A future independently reviewed workflow must establish and pin the source
    and effective policy before a production caller may pass an instance.
    This contract does not authorize execution-market currentness.
    """
    source_authority: str
    max_quote_age_seconds: int


@dataclass(frozen=True)
class DeepstateMarketEvidence:
    canonical_asset_id: str
    venue_id: str
    chain_id: int
    instrument_id: str
    instrument_type: str
    source: str
    execution_timestamp: str | None
    collected_at: str
    transaction_hash: str | None
    block_number: int | None
    block_hash: str | None
    log_index: int | None
    match_index: int | None
    book_id: str | None
    event_type: str | None
    raw_price: str | None
    raw_unit: str
    normalized_usd_price: str | None
    normalized_unit: str | None
    normalization_source: str | None
    normalization_timestamp: str | None
    normalization_evidence_id: str | None
    normalization_state: str
    freshness_state: str
    current_market_state: str
    evidence_state: str
    evidence_reason: str | None
    digest: str


@dataclass(frozen=True)
class HistoricalCrossVenuePair:
    state: str
    reason: str | None
    deepstate_digest: str
    rlive_digest: str | None
    deepstate_timestamp: str | None
    rlive_market_timestamp: str | None
    source_skew_seconds: str | None
    deepstate_raw_price_usdg: str | None
    deepstate_normalized_price_usd: str | None
    rlive_price_usd: str | None
    divergence_bps: str | None
    low_venue: str | None
    high_venue: str | None
    original_deepstate_unit: str = RAW_COMPARISON_UNIT
    comparable_unit: str | None = None


@dataclass(frozen=True)
class DeepstateHistoricalMarketContext:
    canonical_asset_id: str
    state: str
    reason: str | None
    evidence: tuple[DeepstateMarketEvidence, ...]
    historical_comparisons: tuple[HistoricalCrossVenuePair, ...]
    current_cross_venue_state: str = CURRENT_CROSS_VENUE
    current_reason: str = "DEEPSTATE_CURRENT_FRESHNESS_POLICY_NOT_APPROVED"
    current_executable_quote_state: str = "UNAVAILABLE"


def _timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None or d.utcoffset() is None:
        return None
    return d.astimezone(timezone.utc)


def _positive(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _hex(value: object, size: int) -> bool:
    return (isinstance(value, str) and len(value) == size + 2
            and value.startswith("0x")
            and all(ch in "0123456789abcdefABCDEF" for ch in value[2:]))


def _nonnegative(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _rlive_binding(registry: VenueRegistry):
    """Bind the exact reviewed NVDA economic identity, not ticker similarity."""
    underlying = registry.get_underlying("NVDA")
    if underlying is None or underlying.canonical_symbol != "NVDA":
        return None
    matches = [
        (key, policy) for key, policy in APPROVED_BY_CANONICAL_ID.items()
        if policy.symbol == "NVDA"
        and key.chain_id == DEEPSTATE_CHAIN_ID
        and key.contract_address.lower() ==
            "0xd0601ce157db5bdc3162bbaC2a2c8af5320d9eec".lower()
    ]
    if len(matches) != 1:
        return None
    key, policy = matches[0]
    entries = [(entry, status) for entry, status
               in registry.representation_by_contract(
                   chain_id=key.chain_id,
                   contract_address=key.contract_address)
               if entry.platform == "robinhood"
               and entry.underlying_symbol == "NVDA"
               and status is RegistryStatus.ACTIVE]
    if len(entries) != 1:
        return None
    entry = entries[0][0]
    return policy, entry.network or entry.platform, (
        entry.contract_address or entry.representation_symbol), entry.instrument_type


def _valid_execution(row: MarketObservation) -> bool:
    """Explicit shape and canonical economic-fill provenance validation."""
    p = row.payload if isinstance(row.payload, dict) else {}
    valid = (
        row.canonical_asset_id == "NVDA"
        and row.venue_id == DEEPSTATE_VENUE
        and row.instrument_id == DEEPSTATE_POOL_ID
        and row.instrument_type == "tokenized_stock_book"
        and row.source == "DEEPSTATE_PROTOCOL_ROUTER_V1"
        and row.observation_status is ObservationStatus.OK
        and row.freshness_state is FreshnessState.UNAVAILABLE
        and p.get("deepstate_freshness_policy") == "NOT_YET_APPROVED"
        and p.get("chain_id") == DEEPSTATE_CHAIN_ID
        and p.get("venue") == DEEPSTATE_VENUE
        and p.get("venue_market_id") == DEEPSTATE_POOL_ID
        and p.get("pool_id") == DEEPSTATE_POOL_ID
        and str(p.get("router", "")).lower() == DEEPSTATE_ROUTER.lower()
        and str(p.get("book_id", "")).lower() == DEEPSTATE_BOOK_ID.lower()
        and p.get("event_type") in (
            "AskMatched", "BidMatched", "AsksMatched", "BidsMatched",
            "AskSubtreeMatched", "BidSubtreeMatched")
        and p.get("deepstate_execution_timestamp") == row.ts
        and _timestamp(row.ts) is not None
        and _timestamp(row.collected_at) is not None
        and _timestamp(row.collected_at) >= _timestamp(row.ts)
        and _hex(p.get("transaction_hash"), 64)
        and _hex(p.get("block_hash"), 64)
        and _nonnegative(p.get("block_number"))
        and _nonnegative(p.get("log_index"))
        and _nonnegative(p.get("match_index"))
        and _positive(row.price) is not None
    )
    if not valid:
        return False
    try:
        return (int(p["gross_base_amount_nvda"]) > 0
                and int(p["gross_quote_amount_usdg"]) > 0)
    except (ValueError, TypeError, KeyError):
        return False


def _normalization(row: MarketObservation, policy: ReviewedNormalizationPolicy | None,
                   feed_address: str) -> tuple[str, str | None]:
    """Return typed state + recomputed USD price without trusting a cached USD field."""
    p = row.payload
    rate = _positive(p.get("usdg_usd_value"))
    quote_at = _timestamp(p.get("usdg_usd_timestamp"))
    executed_at = _timestamp(row.ts)
    if rate is None or quote_at is None:
        return "MISSING_NORMALIZATION_EVIDENCE", None
    if (p.get("usdg_usd_source") != QUOTE_AUTHORITY_VERSION
            or str(p.get("usdg_usd_feed_address") or "").lower() != feed_address.lower()
            or p.get("usdg_usd_chain_id") != DEEPSTATE_CHAIN_ID
            or not _hex(p.get("usdg_usd_evidence_block_hash"), 64)
            or not isinstance(p.get("usdg_usd_evidence_id"), str)
            or not p["usdg_usd_evidence_id"].strip()):
        return "MISSING_NORMALIZATION_EVIDENCE", None
    if (policy is None or policy.source_authority != QUOTE_AUTHORITY_VERSION
            or not isinstance(policy.max_quote_age_seconds, int)
            or isinstance(policy.max_quote_age_seconds, bool)
            or policy.max_quote_age_seconds <= 0):
        return "NORMALIZATION_POLICY_UNAPPROVED", None
    if executed_at is None:
        return "INVALID_MARKET_EVIDENCE", None
    age = (executed_at - quote_at).total_seconds()
    if age < 0 or age > policy.max_quote_age_seconds:
        return "NORMALIZATION_OUTSIDE_APPROVED_TIME_POLICY", None
    normalized, _effective = normalize_to_usd(
        _positive(row.price), executed_at, rate, quote_at)
    cached = p.get("normalized_usd_price")
    if cached is not None and _positive(cached) != normalized:
        return "INVALID_MARKET_EVIDENCE", None
    return "AVAILABLE", str(normalized)


def _valid_rlive(row: MarketObservation, policy, venue_id, instrument_id,
                 instrument_type) -> bool:
    p = row.payload if isinstance(row.payload, dict) else {}
    return (
        row.canonical_asset_id == "NVDA"
        and row.venue_id == venue_id
        and row.instrument_id.lower() == instrument_id.lower()
        and row.instrument_type == instrument_type
        and row.observation_status is ObservationStatus.OK
        and row.freshness_state is FreshnessState.AVAILABLE
        and p.get("authority") == "R_LIVE"
        and p.get("asset_key") == policy.asset_key.canonical_id
        and p.get("economic_asset_uid") == policy.economic_asset_uid
        and p.get("evidence_clock_contract") == EVIDENCE_CLOCK_CONTRACT
        and p.get("comparison_unit") == NORMALIZED_COMPARISON_UNIT
        and p.get("market_observed_at") == row.ts
        and p.get("market_block_timestamp") == row.ts
        and _timestamp(row.ts) is not None
        and _hex(p.get("market_block_hash"), 64)
        and _nonnegative(p.get("market_block_number"))
        and p.get("twap_window_seconds") == policy.twap_window_seconds
        and _timestamp(p.get("twap_window_start_at")) is not None
        and _timestamp(p.get("normalization_oracle_observed_at")) is not None
        and _timestamp(p.get("reference_observed_at")) is not None
        and _positive(row.price) is not None
    )


def _unavailable_pair(evidence: DeepstateMarketEvidence, reason: str,
                      rlive_digest: str | None = None) -> HistoricalCrossVenuePair:
    return HistoricalCrossVenuePair(
        state="HISTORICAL_COMPARISON_UNAVAILABLE", reason=reason,
        deepstate_digest=evidence.digest, rlive_digest=rlive_digest,
        deepstate_timestamp=evidence.execution_timestamp,
        rlive_market_timestamp=None, source_skew_seconds=None,
        deepstate_raw_price_usdg=evidence.raw_price,
        deepstate_normalized_price_usd=evidence.normalized_usd_price,
        rlive_price_usd=None, divergence_bps=None, low_venue=None,
        high_venue=None,
        comparable_unit=NORMALIZED_COMPARISON_UNIT
            if evidence.normalized_usd_price is not None else None,
    )


def build_deepstate_historical_context(
    canonical_asset_id: str, *, registry: VenueRegistry, store: VenueMarketStore,
    as_of: datetime, normalization_policy: ReviewedNormalizationPolicy | None = None,
) -> DeepstateHistoricalMarketContext:
    """Read only exact, source-clock-bounded history; never acquire or mutate.

    In production the policy is intentionally omitted. Even a test-approved
    historical normalization never activates current market/executable quotes.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    now = as_of.astimezone(timezone.utc)
    if canonical_asset_id != "NVDA":
        return DeepstateHistoricalMarketContext(
            canonical_asset_id, "UNAVAILABLE", "EXACT_IDENTITY_UNAVAILABLE", (), ())
    binding = _rlive_binding(registry)
    if binding is None:
        return DeepstateHistoricalMarketContext(
            canonical_asset_id, "UNAVAILABLE", "EXACT_IDENTITY_UNAVAILABLE", (), ())
    policy, venue_id, instrument_id, instrument_type = binding
    since = now - HISTORY_WINDOW
    deepstate_rows = [
        row for row in store.get_window_for_identity(
            "NVDA", DEEPSTATE_VENUE, DEEPSTATE_POOL_ID, "tokenized_stock_book",
            since=since, until=now)
        if _timestamp(row.collected_at) is not None
        and _timestamp(row.collected_at) <= now
    ][-MAX_HISTORICAL_FILLS:]
    if not deepstate_rows:
        return DeepstateHistoricalMarketContext(
            canonical_asset_id, "UNAVAILABLE", "HISTORICAL_COMPARISON_UNAVAILABLE",
            (), ())
    rlive_rows = store.get_window_for_identity(
        "NVDA", venue_id, instrument_id, instrument_type,
        since=since, until=now)
    rlive = [r for r in rlive_rows
             if _timestamp(r.collected_at) is not None
             and _timestamp(r.collected_at) <= now
             and _valid_rlive(r, policy, venue_id, instrument_id, instrument_type)]
    evidence_rows = []
    pairs = []
    for row in deepstate_rows:
        p = row.payload if isinstance(row.payload, dict) else {}
        valid = _valid_execution(row)
        normalization_state, normalized = (
            _normalization(row, normalization_policy, policy.pool.quote_feed_address)
            if valid else ("INVALID_MARKET_EVIDENCE", None))
        ev = DeepstateMarketEvidence(
            canonical_asset_id="NVDA", venue_id=row.venue_id,
            chain_id=DEEPSTATE_CHAIN_ID, instrument_id=row.instrument_id,
            instrument_type=row.instrument_type, source=row.source,
            execution_timestamp=row.ts, collected_at=row.collected_at,
            transaction_hash=p.get("transaction_hash"),
            block_number=p.get("block_number"), block_hash=p.get("block_hash"),
            log_index=p.get("log_index"), match_index=p.get("match_index"),
            book_id=p.get("book_id"), event_type=p.get("event_type"),
            raw_price=row.price, raw_unit=RAW_COMPARISON_UNIT,
            normalized_usd_price=normalized,
            normalized_unit=NORMALIZED_COMPARISON_UNIT if normalized else None,
            normalization_source=p.get("usdg_usd_source"),
            normalization_timestamp=p.get("usdg_usd_timestamp"),
            normalization_evidence_id=p.get("usdg_usd_evidence_id"),
            normalization_state=normalization_state,
            freshness_state=row.freshness_state.value,
            current_market_state="UNAVAILABLE",
            evidence_state=(
                "HISTORICAL_EXECUTION_PROVEN" if valid else "INVALID_MARKET_EVIDENCE"),
            evidence_reason=None if valid else "INVALID_MARKET_EVIDENCE",
            digest=row.resolved_digest(),
        )
        evidence_rows.append(ev)
        if not valid:
            pairs.append(_unavailable_pair(ev, "INVALID_MARKET_EVIDENCE"))
            continue
        if normalization_state != "AVAILABLE":
            pairs.append(_unavailable_pair(ev, normalization_state))
            continue
        if not rlive:
            pairs.append(_unavailable_pair(ev, "HISTORICAL_COMPARISON_UNAVAILABLE"))
            continue
        dt = _timestamp(row.ts)
        nearest = min(rlive, key=lambda r: (
            abs((_timestamp(r.ts) - dt).total_seconds()),
            r.ts, r.resolved_digest()))
        skew = abs((_timestamp(nearest.ts) - dt).total_seconds())
        if skew > BASIS_MAX_CLOCK_SKEW_SECONDS:
            pairs.append(_unavailable_pair(
                ev, "SOURCE_TIME_SKEW_EXCEEDED", nearest.resolved_digest()))
            continue
        raw = _positive(row.price)
        usd = _positive(normalized)
        token = _positive(nearest.price)
        if raw is None or usd is None or token is None:
            pairs.append(_unavailable_pair(ev, "INVALID_MARKET_EVIDENCE"))
            continue
        high = max(token, usd)
        low = min(token, usd)
        low_venue = DEEPSTATE_VENUE if usd <= token else venue_id
        high_venue = DEEPSTATE_VENUE if usd >= token else venue_id
        pairs.append(HistoricalCrossVenuePair(
            state="HISTORICAL_COMPARISON_AVAILABLE", reason=None,
            deepstate_digest=ev.digest, rlive_digest=nearest.resolved_digest(),
            deepstate_timestamp=ev.execution_timestamp,
            rlive_market_timestamp=nearest.ts,
            source_skew_seconds=str(skew),
            deepstate_raw_price_usdg=ev.raw_price,
            deepstate_normalized_price_usd=normalized,
            rlive_price_usd=nearest.price,
            divergence_bps=str(compute_basis_bps(str(high), str(low))),
            low_venue=low_venue, high_venue=high_venue,
            comparable_unit=NORMALIZED_COMPARISON_UNIT,
        ))
    return DeepstateHistoricalMarketContext(
        canonical_asset_id, "HISTORICAL_EXECUTION_PROVEN", None,
        tuple(evidence_rows), tuple(pairs))
