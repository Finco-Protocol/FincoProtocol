"""Isolated Tokenized-Markets collector (PR 3a — BUILD, DO NOT WIRE).

Turns provider observations into normalized append-only market
observations.  This module is callable from unit/integration tests and
explicit manual invocation ONLY: it is deliberately NOT attached to
application startup, the R-Live warmer, systemd, or any background loop.
Runtime scheduling is a separate post-PR-1 integration step.

Intended (documented, NOT deployed) runtime cadence policy:
    spot / reference  ≈ 300 seconds
    perpetuals        ≈  60 seconds

Authority rules (Correction A):
  - the official assets endpoint is IDENTITY/discovery data; identity rows
    are NEVER written into market_observations (the canonical registry owns
    identity), so a newer identity row can never shadow priced history;
  - market observations come ONLY from an explicitly injected price-evidence
    provider over an exact, bounded instrument set chosen by the caller;
  - a provider failure raises typed and never rewrites prior history;
  - a missing/unavailable price is reported skipped — never fabricated as
    zero, never persisted as an identity-only market row;
  - a halted instrument stays explicitly typed (QUARANTINED) but gets no
    fabricated price;
  - the official xStocks price endpoint could not be contract-verified
    without credentials (403 unauthenticated), so no price fetcher is
    invented here: callers inject one (fixtures in tests; the verified
    official adapter lands with credentials in the integration step).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from finco_radar.venues.models import canonical_underlying_symbol
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.store import VenueMarketStore

SPOT_CADENCE_SECONDS = 300   # intended runtime policy — NOT scheduled here
PERP_CADENCE_SECONDS = 60    # intended runtime policy — NOT scheduled here


class PriceEvidenceUnavailable(RuntimeError):
    """The injected price-evidence provider could not produce a price for an
    exact instrument (typed, operational — never fabricated as zero)."""


@dataclass(frozen=True)
class PriceEvidence:
    """One exact price-evidence fact from an injected provider."""

    symbol: str                       # exact venue symbol
    price: str                        # decimal string
    source_timestamp: datetime | None # provider evidence stamp when supplied
    source: str = "xstocks-official-price"


@dataclass(frozen=True)
class CollectReport:
    """Typed collection outcome (Correction A reporting contract)."""

    requested: int                    # exact instruments the caller asked for
    priced: int                       # provider returned a price
    persisted: int                    # new rows appended
    duplicates: int                   # same evidence already stored
    skipped_unavailable: int          # no price available (reported, never faked)
    halted_quarantined: int           # priced but explicitly typed halted


def xstocks_market_observation(
    *, symbol: str, underlying_symbol: str,
    evidence: PriceEvidence, collected_at: datetime,
    is_trading_halted: bool | None = None,
) -> MarketObservation:
    """One official price-evidence fact → one normalized market observation.

    ts is the provider evidence stamp ONLY when the provider supplies one;
    otherwise ts is None (the collection clock never masquerades as source
    evidence).  A halted instrument keeps explicit QUARANTINED typing.
    """
    canonical = canonical_underlying_symbol(underlying_symbol)
    ts, collected = MarketObservation.clocks(
        evidence.source_timestamp, collected_at)
    return MarketObservation(
        ts=ts,
        collected_at=collected,
        canonical_asset_id=canonical,
        venue_id="xstocks",
        instrument_id=evidence.symbol,
        instrument_type="xstock",
        price=evidence.price,
        source=evidence.source,
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=(ObservationStatus.QUARANTINED
                            if is_trading_halted else ObservationStatus.OK),
        payload={
            "trading_halted": is_trading_halted,
            "source_timestamp_present": evidence.source_timestamp is not None,
        },
    )


def collect_xstocks_prices(
    *, store: VenueMarketStore,
    symbols: Iterable[str],
    price_fetcher: Callable[[str], PriceEvidence],
    underlying_lookup: Callable[[str], str | None],
    halt_lookup: Callable[[str], bool | None] | None = None,
    collected_at: datetime | None = None,
) -> CollectReport:
    """Collect official price evidence for an EXACT, bounded symbol set.

    ``price_fetcher(symbol) -> PriceEvidence`` is injected by the caller
    (fixture in tests; the verified official adapter lands with
    credentials in the integration step).  ``halt_lookup(symbol)`` is an
    optional canonical registry/adapter halt state.

    ``underlying_lookup(symbol) -> canonical underlying symbol | None`` is
    injected from the canonical registry (exact mapping; e.g. AAPLx → AAPL).
    A symbol whose canonical underlying cannot be resolved exactly is
    reported skipped — identity is never guessed from the venue ticker.

    Contract:
      - provider failure (PriceEvidenceUnavailable) is reported per symbol
        as skipped_unavailable — never fabricated as zero, never persisted;
      - unexpected provider programming errors propagate;
      - identical evidence re-collected dedupes by digest (collected_at is
        excluded from evidence identity).
    """
    collected_at = collected_at or datetime.now(timezone.utc)
    requested = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]

    report = CollectReport(requested=len(requested), priced=0, persisted=0,
                           duplicates=0, skipped_unavailable=0,
                           halted_quarantined=0)
    observations: list[MarketObservation] = []
    for symbol in requested:
        canonical = underlying_lookup(symbol)
        if not canonical:
            report = CollectReport(
                requested=report.requested, priced=report.priced,
                persisted=report.persisted, duplicates=report.duplicates,
                skipped_unavailable=report.skipped_unavailable + 1,
                halted_quarantined=report.halted_quarantined)
            continue
        try:
            evidence = price_fetcher(symbol)
        except PriceEvidenceUnavailable:
            report = CollectReport(
                requested=report.requested, priced=report.priced,
                persisted=report.persisted, duplicates=report.duplicates,
                skipped_unavailable=report.skipped_unavailable + 1,
                halted_quarantined=report.halted_quarantined)
            continue
        halted = halt_lookup(symbol) if halt_lookup else None
        observation = xstocks_market_observation(
            symbol=symbol,
            underlying_symbol=canonical,
            evidence=evidence,
            collected_at=collected_at,
            is_trading_halted=halted,
        )
        report = CollectReport(
            requested=report.requested, priced=report.priced + 1,
            persisted=report.persisted, duplicates=report.duplicates,
            skipped_unavailable=report.skipped_unavailable,
            halted_quarantined=report.halted_quarantined
            + (1 if observation.observation_status is ObservationStatus.QUARANTINED
               else 0))
        observations.append(observation)

    created = store.append_many_batched(observations)
    persisted = sum(1 for _digest, was_created in created if was_created)
    return CollectReport(
        requested=report.requested, priced=report.priced,
        persisted=persisted, duplicates=len(created) - persisted,
        skipped_unavailable=report.skipped_unavailable,
        halted_quarantined=report.halted_quarantined)


def collect_xstocks_universe_identity(
    *, base_url: str | None = None, timeout_seconds: float = 15.0,
    client=None,
) -> tuple[list[XStocksAsset], int]:
    """Identity/discovery refresh over the official assets endpoint.

    Returns the typed asset universe for REGISTRY identity use.  This path
    NEVER touches market_observations: identity belongs to the canonical
    registry, and writing identity-only UNAVAILABLE rows would let a newer
    identity row shadow valid priced history.
    """
    kwargs: dict = {"timeout_seconds": timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    if client is not None:
        kwargs["client"] = client
    return fetch_assets(**kwargs)


# Backwards-compat import surface (xstocks adapter pieces used by tests).
from finco_radar.venues.xstocks import (  # noqa: E402,F401
    XStocksAsset,
    XStocksUnavailable,
    fetch_assets,
)
