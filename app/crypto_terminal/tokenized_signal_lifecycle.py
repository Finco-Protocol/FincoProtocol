"""R5/WF-03: read-only factual Tokenized dislocation lifecycle projection.

This is not the legacy R5 quote-size/route signal engine. Source authority:
#179 Tokenized Intelligence facts and basis crossing, #183 own-history
distribution/persistence, immutable VenueMarketStore, and #21 canonical
SHA-256 JSON serialization convention. No provider acquisition or writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json

from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.intelligence import (
    BasisPoint, _basis_from_observation, _events,
    build_tokenized_intelligence, dislocation_threshold_bps,
    effective_observation_state,
)
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import FreshnessState, MarketObservation, ObservationStatus
from finco_radar.venues.robinhood_live import COMPARISON_UNIT
from finco_radar.venues.relative_value import (
    _classify, compute_basis_distribution, compute_dislocation_persistence,
)

CONTRACT_VERSION = "TOKENIZED_DISLOCATION_LIFECYCLE_V1"
HISTORY_WINDOW = timedelta(days=7)  # #179/#183 own-history, NOT an evidence freshness ceiling
MAX_REPRESENTATIONS = 20
MAX_OBSERVATIONS_PER_REPRESENTATION = 256
MAX_FEED_EVENTS = 60


class LifecycleKind(str, Enum):
    DISLOCATION_APPEARED = "DISLOCATION_APPEARED"
    DISLOCATION_CLEARED = "DISLOCATION_CLEARED"
    DISLOCATION_DIRECTION_CHANGED = "DISLOCATION_DIRECTION_CHANGED"
    DISLOCATION_PERSISTENCE_UPDATED = "DISLOCATION_PERSISTENCE_UPDATED"
    EVIDENCE_BECAME_STALE = "EVIDENCE_BECAME_STALE"
    EVIDENCE_BECAME_UNAVAILABLE = "EVIDENCE_BECAME_UNAVAILABLE"
    EVIDENCE_RECOVERED = "EVIDENCE_RECOVERED"
    NO_MATERIAL_CHANGE = "NO_MATERIAL_CHANGE"


@dataclass(frozen=True)
class ExactRepresentation:
    canonical_asset_id: str
    venue_id: str
    chain_id: int
    instrument_id: str
    contract_address: str
    representation_type: str


@dataclass(frozen=True)
class DistributionContext:
    state: str
    current_basis_percentile: str | None
    median_basis_bps: str | None
    usable_observation_count: int
    history_span_seconds: int | None


@dataclass(frozen=True)
class SignalLifecycleEvent:
    event_id: str
    kind: LifecycleKind
    identity: ExactRepresentation
    source_observed_at: str
    current_observation_digest: str
    prior_observation_digest: str | None
    basis_bps: str | None
    basis_reason: str | None
    threshold_bps: str
    previous_classification: str
    current_classification: str
    persistence_start_state: str | None
    proven_crossing_source_timestamp: str | None
    observed_span_seconds: int | None
    continuity_state: str
    evidence_state: str
    temporal_classification: str
    suppression_reason: str | None
    eligible_for_future_alert: bool
    description: str
    distribution: DistributionContext | None


@dataclass(frozen=True)
class TokenizedLifecycleFeed:
    canonical_asset_id: str
    as_of: str
    events: tuple[SignalLifecycleEvent, ...]
    identities_examined: int
    source_observations_examined: int
    policy_version: str = CONTRACT_VERSION
    notifications_enabled: bool = False
    current_deepstate_signals: str = "UNAVAILABLE"


def _stamp(text: str | None) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    try:
        d = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None or d.utcoffset() is None:
        return None
    return d.astimezone(timezone.utc)


def _usable_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _exact_identity(underlying: str, entry) -> ExactRepresentation | None:
    """Require registry-chain-contract identity; no symbol-only fallback."""
    if (entry.underlying_symbol != underlying
            or not isinstance(entry.chain_id, int) or isinstance(entry.chain_id, bool)
            or entry.chain_id <= 0 or not isinstance(entry.contract_address, str)
            or not entry.contract_address.startswith("0x")
            or len(entry.contract_address) != 42):
        return None
    return ExactRepresentation(
        canonical_asset_id=underlying,
        venue_id=entry.network or entry.platform,
        chain_id=entry.chain_id,
        instrument_id=entry.contract_address,
        contract_address=entry.contract_address,
        representation_type=entry.instrument_type,
    )


def _observation_matches(row: MarketObservation, identity: ExactRepresentation) -> bool:
    """Check immutable store index PLUS independent embedded provenance."""
    if (row.observation_status is ObservationStatus.QUARANTINED
            or row.source == "DEEPSTATE_PROTOCOL_ROUTER_V1"
            or row.venue_id == "DEEPSTATE"
            or row.canonical_asset_id != identity.canonical_asset_id
            or row.venue_id != identity.venue_id
            or row.instrument_id != identity.instrument_id
            or row.instrument_type != identity.representation_type):
        return False
    p = row.payload if isinstance(row.payload, dict) else {}
    # A basis stream cannot cross currency or economic-unit policies.
    # Do not read Deepstate USDG/NVDA as canonical USD/share evidence.
    if p.get("comparison_unit") != COMPARISON_UNIT:
        return False
    # Exact-chain provenance must be present in the persisted claim; the
    # registry chain alone is not evidence that a MARKET row belongs there.
    embedded_asset_key = p.get("asset_key")
    expected_asset_key = f"{identity.chain_id}:{identity.contract_address.lower()}"
    if ("chain_id" not in p and embedded_asset_key is None):
        return False
    if "chain_id" in p and p["chain_id"] != identity.chain_id:
        return False
    if embedded_asset_key is not None and embedded_asset_key != expected_asset_key:
        return False
    if ("contract_address" in p and
            str(p["contract_address"]).lower() != identity.contract_address.lower()):
        return False
    if p.get("authority") == "R_LIVE":
        key = f"{identity.chain_id}:{identity.contract_address.lower()}"
        approved = APPROVED_BY_CANONICAL_ID.get(key)
        if (approved is None or approved.symbol != identity.canonical_asset_id
                or p.get("asset_key") != key
                or p.get("economic_asset_uid") != approved.economic_asset_uid):
            return False
    # Deepstate execution rows are never tokenized *representations*, even
    # if malicious input attempts to relabel their registry identity.
    if p.get("deepstate_freshness_policy") is not None:
        return False
    return True


def _distribution(history, now) -> DistributionContext:
    d = compute_basis_distribution(history, now=now)
    return DistributionContext(
        state=d.state, current_basis_percentile=d.current_basis_percentile,
        median_basis_bps=d.historical_median_basis_bps,
        usable_observation_count=d.usable_observation_count,
        history_span_seconds=d.history_span_seconds)


def _class_from_evidence(row, *, threshold: Decimal, state: str) -> tuple[str, str | None, str | None]:
    if state != "AVAILABLE":
        return state, None, state
    basis, reason = _basis_from_observation(row)  # canonical #179 basis evidence policy
    parsed = _usable_decimal(basis)
    if parsed is None:
        return "UNAVAILABLE", None, reason or "BASIS_EVIDENCE_UNAVAILABLE"
    return _classify(parsed, threshold), basis, None  # canonical #183 boundary


def _dislocated(state: str) -> bool:
    return state in ("PREMIUM_DISLOCATION", "DISCOUNT_DISLOCATION")


def _kind(before: str, after: str, crossing: bool) -> LifecycleKind:
    if before in ("STALE", "UNAVAILABLE", "UNKNOWN_PRIOR") and after in (
            "WITHIN_THRESHOLD", "PREMIUM_DISLOCATION", "DISCOUNT_DISLOCATION"):
        return (LifecycleKind.EVIDENCE_RECOVERED if before != "UNKNOWN_PRIOR"
                else LifecycleKind.NO_MATERIAL_CHANGE)
    if after == "STALE":
        return LifecycleKind.EVIDENCE_BECAME_STALE
    if after == "UNAVAILABLE":
        return LifecycleKind.EVIDENCE_BECAME_UNAVAILABLE
    if before == "WITHIN_THRESHOLD" and _dislocated(after) and crossing:
        return LifecycleKind.DISLOCATION_APPEARED
    if _dislocated(before) and after == "WITHIN_THRESHOLD":
        return LifecycleKind.DISLOCATION_CLEARED
    if _dislocated(before) and _dislocated(after) and before != after and crossing:
        return LifecycleKind.DISLOCATION_DIRECTION_CHANGED
    if _dislocated(before) and before == after:
        return LifecycleKind.DISLOCATION_PERSISTENCE_UPDATED
    return LifecycleKind.NO_MATERIAL_CHANGE


def _canonical_hash(body: dict) -> str:
    # Exactly #21's canonical JSON / SHA-256 convention (not the legacy
    # R5 SignalSnapshot itself, which has different input authorities).
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _description(kind: LifecycleKind, identity: ExactRepresentation, state: str) -> str:
    asset, venue = identity.canonical_asset_id, identity.venue_id
    texts = {
        LifecycleKind.DISLOCATION_APPEARED: "a threshold crossing was observed",
        LifecycleKind.DISLOCATION_CLEARED: "a within-threshold observation followed a dislocation",
        LifecycleKind.DISLOCATION_DIRECTION_CHANGED: "a sign-reversal observation was recorded",
        LifecycleKind.DISLOCATION_PERSISTENCE_UPDATED: "another same-direction dislocated observation was recorded",
        LifecycleKind.EVIDENCE_BECAME_STALE: "market evidence became stale, not economically cleared",
        LifecycleKind.EVIDENCE_BECAME_UNAVAILABLE: "comparable evidence became unavailable, not cleared",
        LifecycleKind.EVIDENCE_RECOVERED: "comparable evidence recovered; earlier dislocation continuity is unproven",
        LifecycleKind.NO_MATERIAL_CHANGE: "no proven material transition",
    }
    return f"{asset} ({venue}): {texts[kind]} [{state}]. Not a trade recommendation."


def _event(kind: LifecycleKind, identity: ExactRepresentation, row: MarketObservation,
           prior: MarketObservation | None, *, previous: str, current: str,
           basis: str | None, reason: str | None, threshold: Decimal,
           persistence, distribution: DistributionContext,
           gap: bool, is_current: bool) -> SignalLifecycleEvent:
    """Event IDs exclude evaluation/transport time; original source clock only."""
    timestamp = row.ts
    previous_digest = prior.resolved_digest() if prior is not None else None
    economic = kind in (
        LifecycleKind.DISLOCATION_APPEARED,
        LifecycleKind.DISLOCATION_CLEARED,
        LifecycleKind.DISLOCATION_DIRECTION_CHANGED,
    )
    eligible = economic and is_current and current not in ("STALE", "UNAVAILABLE")
    if not economic:
        suppression = "FACTUAL_CONTEXT_ONLY"
    elif not is_current:
        suppression = "HISTORICAL_EVENT_ONLY"
    elif gap:
        suppression = "PRIOR_CONTINUITY_UNPROVEN"
        eligible = False
    else:
        suppression = None
    crossing_at = (
        persistence.started_at if persistence and persistence.start_state in (
            "PROVEN_CROSSING", "SIGN_REVERSAL") else None)
    span = (int((_stamp(timestamp) - _stamp(crossing_at)).total_seconds())
            if crossing_at and _stamp(timestamp) is not None else None)
    payload = {
        "policy_version": CONTRACT_VERSION,
        "identity": asdict(identity),
        "kind": kind.value,
        "source_observed_at": timestamp,
        "current_observation_digest": row.resolved_digest(),
        "prior_observation_digest": previous_digest,
        "basis_bps": basis,
        "basis_reason": reason,
        "threshold_bps": str(threshold),
        "previous_classification": previous,
        "current_classification": current,
        "continuity_state": "GAP_OR_UNKNOWN" if gap else "ADJACENT_OBSERVATIONS_ONLY",
    }
    return SignalLifecycleEvent(
        event_id=_canonical_hash(payload), kind=kind,
        identity=identity, source_observed_at=timestamp,
        current_observation_digest=row.resolved_digest(),
        prior_observation_digest=previous_digest,
        basis_bps=basis, basis_reason=reason, threshold_bps=str(threshold),
        previous_classification=previous, current_classification=current,
        persistence_start_state=persistence.start_state if persistence else None,
        proven_crossing_source_timestamp=crossing_at,
        observed_span_seconds=span,
        continuity_state=payload["continuity_state"],
        evidence_state="AVAILABLE" if current not in ("STALE", "UNAVAILABLE") else current,
        temporal_classification="CURRENT" if is_current else "HISTORICAL",
        suppression_reason=suppression,
        eligible_for_future_alert=eligible,
        description=_description(kind, identity, current),
        distribution=distribution,
    )


def build_tokenized_signal_lifecycle(
    canonical_asset_id: str, *, registry, store, as_of: datetime,
    include_no_change: bool = False, max_events: int = MAX_FEED_EVENTS,
) -> TokenizedLifecycleFeed:
    """Bounded deterministic read of eligible #179/#183 Tokenized MARKET facts.

    The service caller owns access checks. This adapter is NOT an independent
    API route, notification service, pricing authority, scheduler or publisher.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not isinstance(max_events, int) or isinstance(max_events, bool) or not (1 <= max_events <= MAX_FEED_EVENTS):
        raise ValueError("max_events must be between 1 and MAX_FEED_EVENTS")
    now = as_of.astimezone(timezone.utc)
    underlying = registry.get_underlying(canonical_asset_id)
    if underlying is None or underlying.canonical_symbol != canonical_asset_id:
        raise KeyError("EXACT_CANONICAL_ASSET_UNAVAILABLE")

    intel = build_tokenized_intelligence(
        canonical_asset_id, registry=registry, store=store, as_of=now, include_points=True)
    by_identity = {(h.venue_id, h.instrument_id, h.representation_type): h
                   for h in intel.representations}
    representations = [
        r.entry for r in registry.representations_for_underlying(canonical_asset_id)
        if r.status is RegistryStatus.ACTIVE and _exact_identity(canonical_asset_id, r.entry) is not None
    ][:MAX_REPRESENTATIONS]
    threshold = dislocation_threshold_bps()  # SINGLE approved #179 threshold
    output: list[SignalLifecycleEvent] = []
    examined = 0
    for entry in representations:
        identity = _exact_identity(canonical_asset_id, entry)
        history = by_identity.get((
            identity.venue_id, identity.instrument_id, identity.representation_type))
        if history is None:
            continue
        distribution = _distribution(history, now)
        source_rows = store.get_window_for_identity(
            identity.canonical_asset_id, identity.venue_id,
            identity.instrument_id, identity.representation_type,
            since=now - HISTORY_WINDOW, until=now,
        )
        latest = store.get_latest_for_identity(
            identity.canonical_asset_id, identity.venue_id,
            identity.instrument_id, identity.representation_type)
        # The bounded tail is explicit; its first predecessor is UNKNOWN.
        rows = source_rows[-MAX_OBSERVATIONS_PER_REPRESENTATION:]
        prior = None
        prior_class = "UNKNOWN_PRIOR"
        prior_stamp = None
        gap = True
        prefix_points: list[BasisPoint] = []
        seen_digests: set[str] = set()
        for row in rows:
            examined += 1
            digest = row.resolved_digest()
            if digest in seen_digests:
                continue
            seen_digests.add(digest)
            stamp = _stamp(row.ts)
            collected = _stamp(row.collected_at)
            if stamp is None or collected is None or collected > now:
                prior = None
                prior_class = "UNKNOWN_PRIOR"
                gap = True
                continue
            if not _observation_matches(row, identity):
                # Quarantine and wrong-lineage rows NEVER create an event.
                # They do break continuity rather than allow a synthetic crossing.
                prior = None
                prior_class = "UNKNOWN_PRIOR"
                gap = True
                continue
            is_current = latest is not None and digest == latest.resolved_digest()
            effective = (effective_observation_state(row, as_of=now)
                         if is_current else row.freshness_state.value)
            current_class, basis, reason = _class_from_evidence(
                row, threshold=threshold, state=effective)
            if prior_stamp is not None and stamp <= prior_stamp:
                # Equal-clock distinct evidence has no causal ordering;
                # never invent an economic transition between these rows.
                current_class, basis, reason = ("UNAVAILABLE", None,
                                               "SOURCE_TIMESTAMP_COLLISION" if stamp == prior_stamp
                                               else "SOURCE_TIME_ORDER_INVALID")
            prefix_points.append(BasisPoint(t=row.ts, v=basis, reason=reason))
            prior_point = prefix_points[-2] if len(prefix_points) > 1 else None
            crossing = False
            if (prior_point is not None and prior_class in (
                    "WITHIN_THRESHOLD", "PREMIUM_DISLOCATION", "DISCOUNT_DISLOCATION")
                    and current_class in ("PREMIUM_DISLOCATION", "DISCOUNT_DISLOCATION")
                    and not gap and stamp > prior_stamp):
                # Reuse #179's exact crossing/sign reversal event facts.
                facts = _events((replace(history, points=(prior_point, prefix_points[-1])),))
                crossing = any(f.event_type == "REFERENCE_DIVERGENCE"
                               and f.observed_at == row.ts
                               and f.instrument_id == identity.instrument_id
                               and f.venue_id == identity.venue_id
                               and f.threshold_bps == str(threshold)
                               for f in facts)
            kind = _kind(prior_class, current_class, crossing)
            if prior is None:
                # A first-ever row (including stale/unavailable evidence)
                # cannot prove that a state *became* anything.
                kind = LifecycleKind.NO_MATERIAL_CHANGE
            if (prior is not None and prior_class not in ("STALE", "UNAVAILABLE")
                    and current_class in ("STALE", "UNAVAILABLE")):
                kind = (LifecycleKind.EVIDENCE_BECAME_STALE
                        if current_class == "STALE" else LifecycleKind.EVIDENCE_BECAME_UNAVAILABLE)
            if kind is not LifecycleKind.NO_MATERIAL_CHANGE or include_no_change:
                # #183 exact persistence semantics; evaluate at original
                # source time, never manufacture elapsed wall-clock uptime.
                partial_history = replace(
                    history, current_state=effective, points=tuple(prefix_points))
                persistence = (
                    compute_dislocation_persistence(partial_history, now=stamp)
                    if current_class != "UNAVAILABLE" else None
                )
                output.append(_event(
                    kind, identity, row, prior, previous=prior_class,
                    current=current_class, basis=basis, reason=reason,
                    threshold=threshold, persistence=persistence,
                    distribution=distribution, gap=gap,
                    is_current=is_current,
                    ))
            # A missing basis always breaks economic continuity, including
            # when its availability recovers at the next real observation.
            gap = current_class in ("STALE", "UNAVAILABLE")
            prior_class = current_class
            prior_stamp = stamp
            prior = row

    # Stable ordering across contracts: source clock, exact identity and ID.
    output.sort(key=lambda e: (e.source_observed_at,
                               e.identity.canonical_asset_id, e.identity.venue_id,
                               e.identity.chain_id, e.identity.instrument_id, e.event_id))
    return TokenizedLifecycleFeed(
        canonical_asset_id=canonical_asset_id, as_of=now.isoformat(),
        events=tuple(output[-max_events:]),
        identities_examined=len(representations), source_observations_examined=examined)
