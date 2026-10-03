"""Exact R-LIVE -> Tokenized Markets observation bridge.

This adapter consumes the existing reviewed R-LIVE authority output. It does
not discover identities, does not call providers, and never guesses by ticker.
"""
from __future__ import annotations

from datetime import datetime

from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry

COMPARISON_UNIT = "USD_PER_TOKENIZED_SHARE_EQUIVALENT"


class TokenizedLiveIdentityMismatch(ValueError):
    pass


def _parse_canonical_id(canonical_id: str) -> tuple[int, str]:
    try:
        chain_text, contract = canonical_id.split(":", 1)
        chain_id = int(chain_text)
    except (AttributeError, ValueError):
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_ASSET_KEY_INVALID") from None
    if chain_id <= 0 or not contract.startswith("0x") or len(contract) != 42:
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_ASSET_KEY_INVALID")
    return chain_id, contract.lower()


def _exact_robinhood_entry(registry: VenueRegistry, chain_id: int, contract: str):
    matches = [
        (entry, status)
        for entry, status in registry.representation_by_contract(
            chain_id=chain_id, contract_address=contract)
        if entry.platform == "robinhood"
    ]
    active = [(entry, status) for entry, status in matches
              if status is RegistryStatus.ACTIVE]
    if len(active) != 1:
        raise TokenizedLiveIdentityMismatch(
            "TOKENIZED_LIVE_EXACT_REGISTRY_BINDING_UNAVAILABLE")
    return active[0][0]


def market_observation_from_r_live(
    *,
    canonical_id: str,
    state: str,
    data: dict,
    registry: VenueRegistry,
    collected_at: datetime,
) -> MarketObservation | None:
    """Normalize one R-LIVE row into append-only Tokenized evidence.

    Only AVAILABLE rows carry usable price evidence. STALE/UNAVAILABLE rows
    remain operational collection outcomes and are not fabricated into market
    history. The last canonical observation remains immutable in the store and
    read-time freshness handles aging.
    """
    if state != "AVAILABLE":
        return None
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("TOKENIZED_COLLECTION_CLOCK_MUST_BE_AWARE")

    chain_id, contract = _parse_canonical_id(canonical_id)
    exact = data.get("exact_asset_key") if isinstance(data, dict) else None
    if not isinstance(exact, dict):
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_EXACT_ASSET_KEY_MISSING")
    if (exact.get("chain_id") != chain_id
            or str(exact.get("contract_address") or "").lower() != contract
            or exact.get("canonical_id") != canonical_id):
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_EXACT_ASSET_KEY_MISMATCH")

    entry = _exact_robinhood_entry(registry, chain_id, contract)
    if not entry.underlying_symbol:
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_UNDERLYING_UNAVAILABLE")

    token = data.get("token_reference")
    reference = data.get("robinhood_basis")
    if not isinstance(token, dict) or not isinstance(reference, dict):
        return None
    price = token.get("price_usd_per_token")
    source_ts = token.get("observed_at")
    ref_price = reference.get("price_usd_per_token")
    ref_ts = reference.get("observed_at")
    if price is None or source_ts is None:
        return None

    # Preserve source and reference clocks independently; collected_at is only
    # the FINCO transport/persistence clock.
    return MarketObservation(
        ts=str(source_ts),
        collected_at=collected_at.isoformat(),
        canonical_asset_id=entry.underlying_symbol,
        venue_id=entry.network or entry.platform,
        instrument_id=entry.contract_address or entry.representation_symbol,
        instrument_type=entry.instrument_type,
        price=str(price),
        reference_price=str(ref_price) if ref_price is not None else None,
        basis_bps=None,
        source=str(token.get("source") or "R_LIVE_TOKEN_REFERENCE"),
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=(
            ObservationStatus.QUARANTINED
            if entry.trading_halted is True else ObservationStatus.OK
        ),
        payload={
            "authority": "R_LIVE",
            "asset_key": canonical_id,
            "economic_asset_uid": data.get("economic_asset_uid"),
            "reference_state": reference.get("state"),
            "reference_source": reference.get("source"),
            "reference_observed_at": ref_ts,
            "comparison_unit": COMPARISON_UNIT,
            "registry_source": entry.source,
            "registry_source_ref": entry.source_ref,
            "trading_halted": entry.trading_halted,
        },
    )
