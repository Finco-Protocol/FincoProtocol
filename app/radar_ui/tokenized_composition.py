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
from typing import Any, Callable

from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore
from finco_radar.venues.basis import basis_for_evidence, compute_basis_bps
from finco_radar.venues.intelligence import effective_observation_state


class UnknownCanonicalUnderlying(KeyError):
    """The requested canonical underlying does not exist in the registry
    (typed, fail-closed — raised before any reference/provider/store
    read)."""
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
    has_market_data: bool | None = None   # None = derived from price

    def __post_init__(self) -> None:
        if self.has_market_data is None:
            # Default derivation: a priced row is active market data.
            # Callers may explicitly force False (e.g. QUARANTINED
            # evidence: inspectable, never active composition data).
            object.__setattr__(self, "has_market_data", self.price is not None)


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


def _basis_for(view: RepresentationMarketView, reference: dict[str, Any]) -> tuple[str | None, str | None]:
    """Shared canonical basis authority; see finco_radar.venues.basis."""
    return basis_for_evidence(
        representation_price=view.price,
        representation_state=view.freshness_state,
        representation_source_timestamp=view.source_timestamp,
        reference_price=reference.get("price"),
        reference_state=str(reference.get("state") or "UNAVAILABLE"),
        reference_source_timestamp=reference.get("observed_at"),
    )

def _expected_venue_id(entry) -> str:
    """Exact expected observation venue key for a registry row, per the
    PR #175 observation convention (venue_id = network for chain rows,
    platform for venue rows)."""
    return entry.network or entry.platform


def _store_observation_view(store: VenueMarketStore | None,
                            entry, *,
                            as_of: datetime | None = None) -> RepresentationMarketView:
    """Persisted-observation market view for one exact registry row (or
    unavailable when nothing was ever collected).

    Correction A: the store read is bound to the EXACT expected venue, and
    the returned observation's canonical_asset_id must equal the row's
    exact underlying symbol.  Cross-venue or cross-underlying evidence
    fails closed to market unavailable — no fuzzy fallback.
    """
    expected_venue = _expected_venue_id(entry)
    instrument_id = (entry.contract_address
                     or entry.representation_symbol.strip().upper())
    base = RepresentationMarketView(
        venue_id=expected_venue,
        instrument_id=instrument_id,
        representation_type=entry.instrument_type,
        network=entry.network,
        contract_address=entry.contract_address,
        status=RegistryStatus.ACTIVE.value,
        provenance=entry.source_ref,
    )
    if store is None:
        return base
    expected_symbol = (str(entry.underlying_symbol).strip().upper()
                       if entry.underlying_symbol else None)
    if expected_symbol is None:
        return base
    latest = store.get_latest_for_identity(
        expected_symbol,
        expected_venue,
        instrument_id,
        entry.instrument_type,
    )
    if latest is None or latest.price is None:
        return base
    view = RepresentationMarketView(
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
        freshness_state=(
            effective_observation_state(latest, as_of=as_of)
            if as_of is not None
            else latest.freshness_state.value
        ),
        observation_status=latest.observation_status.value,
        source=latest.source,
        provenance=entry.source_ref,
        history_available=True,
    )
    if latest.observation_status.value == "QUARANTINED":
        # Correction B: quarantined evidence (e.g. halted instruments) is
        # inspectable but is NEVER active market data — has_market_data is
        # false and basis authority reports REPRESENTATION_QUARANTINED.
        quarantined_view = dict(view.__dict__)
        quarantined_view["has_market_data"] = False
        quarantined_view["basis_bps"] = None
        quarantined_view["basis_reason"] = "REPRESENTATION_QUARANTINED"
        return RepresentationMarketView(**quarantined_view)
    return view


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
    if underlying is None:
        # Unknown canonical underlying: fail closed BEFORE any reference
        # read, provider seam, or store composition.
        raise UnknownCanonicalUnderlying(symbol)

    # ONE reference read per composition — the perp seam reuses this exact
    # reference instead of re-acquiring (Correction A #7).
    reference_rows = reference_reader(symbol) if reference_reader else []
    reference = reference_rows[0] if reference_rows else {
        "state": "UNAVAILABLE", "price": None, "observed_at": None,
        "source": None, "symbol": symbol,
    }

    representations: list[RepresentationMarketView] = []
    for resolved in registry.representations_for_underlying(symbol):
        entry = resolved.entry
        view = _store_observation_view(store, entry, as_of=now)
        if view.price is None:
            basis, reason = None, "REPRESENTATION_PRICE_UNAVAILABLE"
        elif not view.has_market_data:
            # QUARANTINED evidence: basis authority already reports the
            # typed reason — never re-evaluate as active market data.
            basis, reason = None, view.basis_reason
        else:
            basis, reason = _basis_for(view, reference)
        view = RepresentationMarketView(
            **{**view.__dict__, "basis_bps": basis, "basis_reason": reason})
        representations.append(view)

    # Exact Hyperliquid perp seam.  SCOPE TRUTH (Correction A #8): the
    # merged Hyperliquid provider is bounded to its supported exact
    # universe — there is NO equity stock-perp coverage today, so this seam
    # is exercised ONLY when the caller supplies an exact canonical mapping.
    # Nothing here implies NVDA/TSLA-style stock perps exist.
    if perp_lookup is not None:
        perp = perp_lookup(symbol)
        if perp:
            raw_stamp = perp.get("source_timestamp")
            parsed_stamp = (datetime.fromisoformat(str(raw_stamp))
                            if raw_stamp else None)
            ts, collected = MarketObservation_clocks(parsed_stamp, now)
            is_halted = bool(perp.get("trading_halted"))
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
                volume_24h=perp.get("volume_24h"),
                funding_rate=perp.get("funding_rate"),
                open_interest=perp.get("open_interest"),
                freshness_state="AVAILABLE" if perp.get("price") else "UNAVAILABLE",
                observation_status="QUARANTINED" if is_halted else "OK",
                source=perp.get("source"),
                provenance="hyperliquid-exact-mapping",
                has_market_data=False if is_halted else None,
            )
            # Tokenized Markets basis is always FINCO-computed against the
            # canonical underlying reference.  Provider-native basis_bps may
            # represent a different concept (for example mark-vs-oracle) and
            # is deliberately ignored on this product surface.
            if is_halted:
                basis, reason = None, "REPRESENTATION_QUARANTINED"
            else:
                basis, reason = _basis_for(view, reference)
            view = RepresentationMarketView(
                **{**view.__dict__, "basis_bps": basis, "basis_reason": reason})
            representations.append(view)

    # Overall state is complete only when the reference is fresh AND
    # every active representation in the composed view has usable AVAILABLE
    # market evidence.  Identity-only, stale, or quarantined siblings make an
    # otherwise usable view PARTIAL rather than FRESH.
    usable_representations = [
        r for r in representations
        if r.has_market_data and r.freshness_state == "AVAILABLE"
    ]
    stale_representations = [
        r for r in representations
        if r.has_market_data and r.price is not None
        and r.freshness_state == "STALE"
    ]
    reference_usable = (reference.get("price") is not None
                        and reference.get("state") == "FRESH")
    all_representations_usable = (
        bool(representations)
        and len(usable_representations) == len(representations)
    )
    if reference_usable and all_representations_usable:
        overall = "FRESH"
    elif usable_representations:
        overall = "PARTIAL"
    elif stale_representations:
        overall = "STALE"
    else:
        overall = "UNAVAILABLE"

    # Per-underlying history truth (Correction A #9/#10): history_available
    # means at least one persisted observation exists for THIS canonical
    # asset — global store counts never promote unrelated history.
    history_available = (
        store is not None
        and store.get_latest_for_underlying(symbol) is not None)

    return TokenizedUnderlyingView(
        canonical_asset_id=symbol,
        underlying_name=underlying.underlying_name,
        underlying_isin=underlying.underlying_isin,
        reference=reference,
        representations=tuple(representations),
        evaluation_time=now.isoformat(),
        overall_state=overall,
        history_available=history_available,
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
