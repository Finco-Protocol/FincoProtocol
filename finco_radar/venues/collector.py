"""Isolated Tokenized-Markets collector (PR 3a — BUILD, DO NOT WIRE).

Turns provider observations (official xStocks API today; further venues in
the follow-up integration step) into normalized append-only market
observations.  This module is callable from unit/integration tests and
explicit manual invocation ONLY: it is deliberately NOT attached to
application startup, the R-Live warmer, systemd, or any background loop.
Runtime scheduling is a separate post-PR-1 integration step.

Intended (documented, NOT deployed) runtime cadence policy:
    spot / reference  ≈ 300 seconds
    perpetuals        ≈  60 seconds

Failure contract: a provider failure raises typed (XStocksUnavailable /
XStocksParseError) — the collector NEVER fabricates observation values,
never writes fake zero rows, and never rewrites prior history.  Unavailable
evidence, when the caller chooses to persist it, is explicitly typed
(FreshnessState.UNAVAILABLE) and carries no price.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from finco_radar.venues.models import canonical_underlying_symbol
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.store import VenueMarketStore
from finco_radar.venues.xstocks import (
    XStocksAsset,
    XStocksUnavailable,
    fetch_assets,
)

SPOT_CADENCE_SECONDS = 300   # intended runtime policy — NOT scheduled here
PERP_CADENCE_SECONDS = 60    # intended runtime policy — NOT scheduled here


@dataclass(frozen=True)
class CollectReport:
    persisted: int
    duplicates: int
    observations: int


def xstocks_observation(
    asset: XStocksAsset, *, price: str | None,
    collected_at: datetime, source_timestamp: datetime | None = None,
    reference_price: str | None = None,
) -> MarketObservation | None:
    """One official xStocks asset → one normalized observation.

    The underlying symbol is the exact canonical identity from the official
    API; an asset without an underlying symbol cannot become an observation
    (identity would be guesswork).  Missing price stays missing: an
    observation is only persisted with typed freshness/status, never with a
    fabricated zero.
    """
    if not asset.underlying_symbol:
        return None
    canonical = canonical_underlying_symbol(asset.underlying_symbol)
    ts, collected = MarketObservation.clocks(source_timestamp, collected_at)
    persisted_ts = ts or collected  # ordering key only when source lacks a stamp
    return MarketObservation(
        ts=persisted_ts,
        collected_at=collected,
        canonical_asset_id=canonical,
        venue_id="xstocks",
        instrument_id=asset.symbol,
        instrument_type="xstock",
        price=price,
        reference_price=reference_price,
        basis_bps=None,
        volume_24h=None,
        open_interest=None,
        funding_rate=None,
        source="xstocks-official-api",
        freshness_state=FreshnessState.AVAILABLE if price else FreshnessState.UNAVAILABLE,
        observation_status=ObservationStatus.QUARANTINED if (
            asset.is_trading_halted) else ObservationStatus.OK,
        payload={
            "deployments": [
                {"network": d.network, "contract_address": d.contract_address,
                 "decimals": d.decimals}
                for d in asset.deployments
            ],
            "trading_halted": asset.is_trading_halted,
            "source_timestamp_present": source_timestamp is not None,
        },
    )


def collect_xstocks_once(
    *, store: VenueMarketStore, collected_at: datetime | None = None,
    base_url: str | None = None, timeout_seconds: float = 15.0,
    client=None,
) -> CollectReport:
    """One collection cycle over the official xStocks universe.

    Typed failures propagate (XStocksUnavailable / XStocksParseError):
    nothing unavailable is ever persisted as a price row, and prior history
    is never touched.
    """
    collected_at = collected_at or datetime.now(timezone.utc)
    kwargs: dict = {"timeout_seconds": timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    if client is not None:
        kwargs["client"] = client
    assets, _pages = fetch_assets(**kwargs)

    observations = []
    for asset in assets:
        # The public assets endpoint carries identity + deployment + halt
        # state; the official price-data endpoint is a separate follow-up
        # call.  This cycle persists identity/freshness evidence WITHOUT a
        # price rather than inventing one.
        observation = xstocks_observation(
            asset, price=None, collected_at=collected_at)
        if observation is not None:
            observations.append(observation)

    created = store.append_many_batched(observations)
    persisted = sum(1 for _digest, was_created in created if was_created)
    return CollectReport(
        persisted=persisted,
        duplicates=len(created) - persisted,
        observations=len(observations),
    )
