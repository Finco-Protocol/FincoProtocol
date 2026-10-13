"""Exact R-LIVE -> Tokenized Markets observation bridge.

This adapter consumes the existing reviewed R-LIVE authority output. It does
not discover identities, does not call providers, and never guesses by ticker.
"""
from __future__ import annotations

from datetime import datetime

from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry

COMPARISON_UNIT = "USD_PER_TOKENIZED_SHARE_EQUIVALENT"
EVIDENCE_CLOCK_CONTRACT = "TOKENIZED_RLIVE_MARKET_CLOCK_V2"


def _source_clock(fields: dict, key: str) -> datetime | None:
    """Only a source-provided, timezone-aware clock is admissible."""
    value = fields.get(key)
    if not isinstance(value, str):
        return None
    try:
        clock = datetime.fromisoformat(value)
    except ValueError:
        return None
    return clock if clock.tzinfo is not None and clock.utcoffset() is not None else None



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
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
    if policy is None:
        raise TokenizedLiveIdentityMismatch(
            "TOKENIZED_LIVE_EXACT_ASSET_KEY_UNAPPROVED")
    if not entry.underlying_symbol:
        raise TokenizedLiveIdentityMismatch("TOKENIZED_LIVE_UNDERLYING_UNAVAILABLE")
    if entry.underlying_symbol.strip().upper() != policy.symbol:
        raise TokenizedLiveIdentityMismatch(
            "TOKENIZED_LIVE_UNDERLYING_POLICY_MISMATCH")
    if data.get("economic_asset_uid") != policy.economic_asset_uid:
        raise TokenizedLiveIdentityMismatch(
            "TOKENIZED_LIVE_ECONOMIC_UID_MISMATCH")

    token = data.get("token_reference")
    reference = data.get("robinhood_basis")
    if not isinstance(token, dict) or not isinstance(reference, dict):
        return None
    price = token.get("price_usd_per_token")
    effective_ts = token.get("observed_at")
    ref_price = reference.get("price_usd_per_token")
    ref_ts = reference.get("observed_at")
    evidence = token.get("source_evidence")
    if price is None or not isinstance(evidence, dict):
        return None

    # The 300-second V3 TWAP ends at the pinned block. A Chainlink quote
    # timestamp or most recent pool swap is NOT that price-observation time.
    window_end = _source_clock(evidence, "dexWindowEndAt")
    block_at = _source_clock(evidence, "blockTimestamp")
    window_start = _source_clock(evidence, "dexWindowStartAt")
    oracle_at = _source_clock(evidence, "quoteUpdatedAt")
    activity_at = _source_clock(evidence, "lastPoolActivityAt")
    effective_at = _source_clock({"effective": effective_ts}, "effective")
    source_effective = _source_clock(evidence, "effectiveObservedAt")
    if any(t is None for t in (window_end, block_at, window_start,
                               oracle_at, activity_at, effective_at,
                               source_effective)):
        return None
    if (window_end != block_at
            or evidence.get("twapWindowSeconds") != policy.twap_window_seconds
            or (window_end - window_start).total_seconds()
                != policy.twap_window_seconds
            or not (oracle_at <= window_end and activity_at <= window_end)
            or (window_end - oracle_at).total_seconds()
                > policy.max_quote_age_seconds
            or (window_end - activity_at).total_seconds()
                > policy.max_pool_activity_age_seconds
            or effective_at != min(window_end, oracle_at, activity_at)
            or source_effective != effective_at):
        return None
    block_number = evidence.get("blockNumber")
    block_hash = evidence.get("blockHash")
    if (not isinstance(block_number, int) or isinstance(block_number, bool)
            or block_number < 0
            or not isinstance(block_hash, str)
            or len(block_hash) != 66
            or not block_hash.startswith("0x")
            or any(char not in "0123456789abcdefABCDEF"
                   for char in block_hash[2:])):
        return None
    if ref_ts is not None and _source_clock(reference, "observed_at") is None:
        return None

    # Never substitute collection time or composite/effective time for
    # MARKET time. Preserve original clocks and causal block identity.
    return MarketObservation(
        ts=evidence["dexWindowEndAt"],
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
            "evidence_clock_contract": EVIDENCE_CLOCK_CONTRACT,
            "asset_key": canonical_id,
            "market_observed_at": evidence["dexWindowEndAt"],
            "market_block_timestamp": evidence["blockTimestamp"],
            "market_block_number": block_number,
            "market_block_hash": block_hash,
            "twap_window_start_at": evidence["dexWindowStartAt"],
            "twap_window_seconds": evidence["twapWindowSeconds"],
            "last_pool_activity_at": evidence["lastPoolActivityAt"],
            "normalization_oracle_observed_at": evidence["quoteUpdatedAt"],
            "effective_evidence_at": evidence["effectiveObservedAt"],
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
