"""Tokenized Markets composition (PR 3b) — read-only cross-venue view.

Composes, for one canonical underlying at a time:

    exact registry representations (VenueRegistry, Correction-B semantics)
    + underlying reference (existing MarketReadService bound-reference
      authority — no new TradFi provider)
    + persisted market observations (VenueMarketStore, where collected)
    + Hyperliquid perp evidence ONLY through the existing adapter/service
      seams where an exact instrument mapping exists

Identity authority: ``finco_radar.venues.VenueRegistry`` — exact lookup
only (no fuzzy ticker matching, no name similarity, no symbol guessing).
QUARANTINED and CONFLICT representations are excluded from canonical
active composition.

Truth rules carried over from the foundation:
  - missing market data is UNAVAILABLE — never zero, never faked live;
  - an xStocks representation with registry identity but no verified
    market observation is "identity available / market data unavailable";
  - basis exists ONLY when a representation price AND a compatible
    underlying reference price exist on exact identity binding within the
    existing freshness authority; otherwise basis is None with a reason;
  - history is rendered only from persisted/canonical observations —
    never synthesized, never interpolated through missing evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore

BASIS_SCALE = Decimal(10_000)
# A representation/reference pair is comparable only when both evidence
# stamps are within this window of each other (existing R2/R6-style skew
# authority; foundation freshness policies already bound each side).
BASIS_MAX_CLOCK_SKEW_SECONDS = 300


@dataclass(frozen=True)
class RepresentationMarketView:
    """One venue representation of one canonical underlying, with whatever
    market evidence actually exists right now."""

    venue_id: str                    # platform / network key
    instrument_id: str               # exact venue symbol or 0x-contract identity
    representation_type: str
    network: str | None
    contract_address: str | None
    status: str                      # registry-derived (ACTIVE/INACTIVE)

    price: str | None = None
    source_timestamp: str | None = None   # provider evidence stamp (None when absent)
    collected_at: str | None = None       # FINCO collection clock
    basis_bps: str | None = None
    basis_reason: str | None = None       # why basis is unavailable
    volume_24h: str | None = None
    funding_rate: str | None = None
    open_interest: str | None = None
    freshness_state: str = "UNAVAILABLE"
    observation_status: str | None = None
    source: str | None = None
    provenance: str = ""                  # registry source_ref (identity)
    history_available: bool = False

    @property
    def has_market_data(self) -> bool:
        return self.price is not None


@dataclass(frozen=True)
class TokenizedUnderlyingView:
    """The composed current-state view for one canonical underlying."""

    canonical_asset_id: str
    underlying_name: str | None
    underlying_isin: str | None
    reference: dict[str, Any]        # bound-reference authority row (or UNAVAILABLE)
    representations: tuple[RepresentationMarketView, ...]
    evaluation_time: str
    overall_state: str               # FRESH / STALE / PARTIAL / UNAVAILABLE
    history_available: bool = False

    @property
    def priced_representations(self) -> tuple[RepresentationMarketView, ...]:
        return tuple(r for r in self.representations if r.has_market_data)


def compute_basis_bps(
    representation_price: str, reference_price: str,
) -> Decimal:
    """Deterministic basis in basis points:

        (rep_price / reference_price - 1) × 10,000

    Decimal arithmetic, quantized to whole bps (ROUND_HALF_UP).  The caller
    guarantees both prices exist and are comparable (exact identity +
    freshness authority); this function is pure arithmetic.
    """
    ratio = (Decimal(representation_price) / Decimal(reference_price)) - 1
    return (ratio * BASIS_SCALE).quantize(Decimal("1"))


def _basis_for(view: RepresentationMarketView, reference: dict[str, Any]) -> tuple[str | None, str | None]:
    reference_price = reference.get("price")
    reference_observed_at = reference.get("observed_at")
    if view.price is None:
        return None, "REPRESENTATION_PRICE_UNAVAILABLE"
    if reference_price is None or reference.get("state") == "UNAVAILABLE":
        return None, "REFERENCE_UNAVAILABLE"
    try:
        rep_stamp = datetime.fromisoformat(view.source_timestamp or view.collected_at or "")
        ref_stamp = datetime.fromisoformat(str(reference_observed_at))
    except ValueError:
        return None, "EVIDENCE_TIMESTAMP_UNAVAILABLE"
    if rep_stamp.tzinfo is None or ref_stamp.tzinfo is None:
        return None, "EVIDENCE_TIMESTAMP_UNAVAILABLE"
    skew = abs((rep_stamp - ref_stamp).total_seconds())
    if skew > BASIS_MAX_CLOCK_SKEW_SECONDS:
        return None, "EVIDENCE_SKEW_EXCEEDS_POLICY"
    try:
        basis = compute_basis_bps(view.price, str(reference_price))
    except (InvalidOperation, ZeroDivisionError):
        return None, "BASIS_ARITHMETIC_INVALID"
    return str(basis), None


def _store_observation_view(store: VenueMarketStore | None,
                            entry) -> RepresentationMarketView:
    """Persisted-observation market view for one exact registry row (or
    unavailable when nothing was ever collected)."""
    base = RepresentationMarketView(
        venue_id=entry.network or entry.platform,
        instrument_id=entry.contract_address or entry.representation_symbol,
        representation_type=entry.instrument_type,
        network=entry.network,
        contract_address=entry.contract_address,
        status=RegistryStatus.ACTIVE.value,
        provenance=entry.source_ref,
    )
    if store is None:
        return base
    instrument_id = (entry.contract_address
                     or entry.representation_symbol.strip().upper())
    latest = store.get_latest_for_instrument(instrument_id)
    if latest is None or latest.price is None:
        return base
    return RepresentationMarketView(
        venue_id=latest.venue_id,
        instrument_id=latest.instrument_id,
        representation_type=latest.instrument_type,
        network=entry.network,
        contract_address=entry.contract_address,
        status=RegistryStatus.ACTIVE.value,
        price=latest.price,
        source_timestamp=latest.ts,
        collected_at=latest.collected_at,
        volume_24h=latest.volume_24h,
        funding_rate=latest.funding_rate,
        open_interest=latest.open_interest,
        freshness_state=latest.freshness_state.value,
        observation_status=latest.observation_status.value,
        source=latest.source,
        provenance=entry.source_ref,
        history_available=True,
    )


def compose_underlying(
    canonical_asset_id: str, *,
    registry: VenueRegistry,
    reference_reader: Callable[[str], list[dict]],
    store: VenueMarketStore | None = None,
    perp_lookup: Callable[[str], dict | None] | None = None,
    now: datetime | None = None,
) -> TokenizedUnderlyingView:
    """Compose the current-state view for one canonical underlying.

    ``reference_reader(symbol)`` is the existing cached bound-reference
    board authority (MarketReadService.read(featured_symbols=(sym,))) —
    reused, not reimplemented.  ``perp_lookup(canonical_symbol)`` is an
    optional exact Hyperliquid mapping seam returning
    ``{"price","funding_rate","open_interest","source_timestamp","source",...}``
    or None; it is consulted ONLY by exact canonical symbol, never by
    fuzzy ticker inference.
    """
    now = now or datetime.now(timezone.utc)
    symbol = canonical_asset_id.strip().upper()
    underlying = registry.get_underlying(symbol)

    reference_rows = reference_reader(symbol) if reference_reader else []
    reference = reference_rows[0] if reference_rows else {
        "state": "UNAVAILABLE", "price": None, "observed_at": None,
        "source": None, "symbol": symbol,
    }

    representations: list[RepresentationMarketView] = []
    for resolved in registry.representations_for_underlying(symbol):
        entry = resolved.entry
        view = _store_observation_view(store, entry)
        if view.price is not None:
            basis, reason = _basis_for(view, reference)
        else:
            basis, reason = None, "REPRESENTATION_PRICE_UNAVAILABLE"
        view = RepresentationMarketView(
            **{**view.__dict__, "basis_bps": basis, "basis_reason": reason})
        representations.append(view)

    # Exact Hyperliquid perp seam (existing adapter/service authority; only
    # where an exact canonical mapping exists).
    if perp_lookup is not None:
        perp = perp_lookup(symbol)
        if perp:
            raw_stamp = perp.get("source_timestamp")
            parsed_stamp = (datetime.fromisoformat(str(raw_stamp))
                            if raw_stamp else None)
            ts, collected = MarketObservation_clocks(parsed_stamp, now)
            view = RepresentationMarketView(
                venue_id="hyperliquid",
                instrument_id=str(perp.get("instrument_id") or symbol),
                representation_type="perpetual",
                network="hyperliquid",
                contract_address=None,
                status=RegistryStatus.ACTIVE.value,
                price=perp.get("price"),
                source_timestamp=ts,
                collected_at=collected,
                basis_bps=perp.get("basis_bps"),
                volume_24h=perp.get("volume_24h"),
                funding_rate=perp.get("funding_rate"),
                open_interest=perp.get("open_interest"),
                freshness_state="AVAILABLE" if perp.get("price") else "UNAVAILABLE",
                source=perp.get("source"),
                provenance="hyperliquid-exact-mapping",
            )
            if view.price is not None and "basis_bps" not in perp:
                basis, reason = _basis_for(view, reference_reader(symbol)[0]
                                           if reference_reader(symbol) else {})
                view = RepresentationMarketView(
                    **{**view.__dict__, "basis_bps": basis, "basis_reason": reason})
            representations.append(view)

    priced = [r for r in representations if r.price is not None]
    fresh = [r for r in priced if r.freshness_state == "AVAILABLE"]
    if representations and len(priced) == len(representations) and all(
            r.freshness_state == "AVAILABLE" for r in priced):
        overall = "FRESH" if priced else "UNAVAILABLE"
    elif priced:
        overall = "PARTIAL"
    elif representations:
        overall = "UNAVAILABLE"
    else:
        overall = "UNAVAILABLE"
    _ = fresh  # reserved for finer-grained state in PR 3b follow-ups

    return TokenizedUnderlyingView(
        canonical_asset_id=symbol,
        underlying_name=underlying.underlying_name if underlying else None,
        underlying_isin=underlying.underlying_isin if underlying else None,
        reference=reference,
        representations=tuple(representations),
        evaluation_time=now.isoformat(),
        overall_state=overall,
        history_available=bool(store is not None and store.count() > 0),
    )


def MarketObservation_clocks(source_timestamp, collected_at):
    """Foundation clock contract reused for the perp seam (never substitute
    the collection clock for a missing provider stamp)."""
    from finco_radar.venues.observations import MarketObservation
    return MarketObservation.clocks(source_timestamp, collected_at)


def list_supported_underlyings(
    registry: VenueRegistry, *, limit: int | None = None,
) -> list[dict]:
    """Canonical underlyings with active tokenized representations (exact,
    quarantine/conflict-excluded), for the landing surface.  Deterministic
    order by canonical symbol."""
    rows = []
    for symbol in sorted(registry._underlyings):
        resolved = registry.representations_for_underlying(symbol)
        if not resolved:
            continue
        venues = sorted({r.entry.platform for r in resolved})
        rows.append({
            "canonical_asset_id": symbol,
            "underlying_name": registry._underlyings[symbol].underlying_name,
            "venues": venues,
            "representation_count": len(resolved),
        })
        if limit is not None and len(rows) >= limit:
            break
    return rows
