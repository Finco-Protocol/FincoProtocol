"""Deterministic CoinGecko-observation composition for BNB chain 56.

No network access, economic-identity inference, execution price, or TVL source
exists in this layer. Market rows and deployment metadata join by provider ID,
never by symbol/name or resemblance to a Robinhood asset.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from finco_radar.assets.contracts import AssetKey, RegistrySourceError
from finco_radar.authority.contracts import AuthorityState

from .bnb_contracts import (
    BNB_MAINNET_CHAIN_ID, TOKENIZED_CATEGORY_ID, BnbRwaMarketObservation,
    BnbRwaMarketSnapshot,
)

MAX_CURRENT_AGE_SECONDS = 30 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60


def unavailable_bnb_snapshot(retrieved_at: datetime, reason: str) -> BnbRwaMarketSnapshot:
    return BnbRwaMarketSnapshot(
        retrieved_at=retrieved_at, state=AuthorityState.UNAVAILABLE,
        observations=(), observed_market_cap_usd=None, observed_volume_24h_usd=None,
        market_cap_contributors=0, volume_contributors=0, current_count=0,
        stale_count=0, deployment_available_count=0,
        deployment_unavailable_count=0, degraded_reasons=(), reason=reason,
    )


def _number(
    value: object, field: str, *, positive: bool = False, signed: bool = False,
) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field}:INVALID_NUMBER")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field}:INVALID_NUMBER") from exc
    if not number.is_finite() or (not signed and (number <= 0 if positive else number < 0)):
        raise ValueError(f"{field}:INVALID_ECONOMICS")
    return number


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("INVALID_OBSERVATION_TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_OBSERVATION_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("INVALID_OBSERVATION_TIME")
    return parsed.astimezone(timezone.utc)


def _platform_id(platforms: Sequence[Mapping[str, object]]) -> str:
    matches = [
        row.get("id") for row in platforms
        if isinstance(row, Mapping)
        and type(row.get("chain_identifier")) is int
        and row.get("chain_identifier") == BNB_MAINNET_CHAIN_ID
    ]
    if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0].strip():
        raise ValueError("BNB_PLATFORM_IDENTITY_UNAVAILABLE_OR_CONFLICTING")
    return matches[0].strip()


def _provider_id(row: object) -> str | None:
    if not isinstance(row, Mapping):
        return None
    value = row.get("id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def compose_bnb_snapshot(
    *, platforms: Sequence[Mapping[str, object]],
    coins: Sequence[Mapping[str, object]],
    markets: Sequence[Mapping[str, object]],
    retrieved_at: datetime,
    category_id: str = TOKENIZED_CATEGORY_ID,
) -> BnbRwaMarketSnapshot:
    """Compose a top-category-page observed set, not the whole BNB RWA universe.

    `/coins/markets` amounts are global to a CoinGecko coin ID. A BNB
    deployment listed by `/coins/list` does not make them chain-specific.
    """
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if category_id != TOKENIZED_CATEGORY_ID:
        raise ValueError("UNAPPROVED_RWA_CATEGORY")
    if not all(isinstance(rows, (list, tuple)) for rows in (platforms, coins, markets)):
        raise ValueError("COINGECKO_PAYLOAD_INVALID")
    try:
        platform_id = _platform_id(platforms)
    except ValueError as exc:
        return unavailable_bnb_snapshot(retrieved_at, str(exc))

    coin_counts = Counter(filter(None, (_provider_id(row) for row in coins)))
    market_counts = Counter(filter(None, (_provider_id(row) for row in markets)))
    coin_by_id = {
        _provider_id(row): row for row in coins
        if _provider_id(row) and coin_counts[_provider_id(row)] == 1
    }
    degraded: set[str] = set()
    if any(count > 1 for count in coin_counts.values()):
        degraded.add("DUPLICATE_PROVIDER_COIN_ID_EXCLUDED")
    if any(count > 1 for count in market_counts.values()):
        degraded.add("DUPLICATE_PROVIDER_MARKET_ID_EXCLUDED")

    candidates: list[BnbRwaMarketObservation] = []
    for raw in markets:
        provider_id = _provider_id(raw)
        if provider_id is None or market_counts[provider_id] != 1:
            degraded.add("INVALID_OR_DUPLICATE_MARKET_ID_EXCLUDED")
            continue
        coin = coin_by_id.get(provider_id)
        if coin is None:
            # A market row alone cannot establish a BNB listing or deployment.
            continue
        listed_platforms = coin.get("platforms")
        if not isinstance(listed_platforms, Mapping) or platform_id not in listed_platforms:
            continue
        symbol = raw.get("symbol")
        name = raw.get("name")
        if (
            not isinstance(symbol, str) or not symbol.strip()
            or not isinstance(name, str) or not name.strip()
            or not isinstance(coin.get("symbol"), str)
            or not isinstance(coin.get("name"), str)
            or symbol.casefold() != coin["symbol"].casefold()
            or name.casefold() != coin["name"].casefold()
        ):
            degraded.add("PROVIDER_ID_METADATA_CONFLICT_EXCLUDED")
            continue
        contract = listed_platforms[platform_id]
        asset_key: AssetKey | None = None
        deployment_reason: str | None = None
        if isinstance(contract, str) and contract.strip():
            try:
                asset_key = AssetKey(BNB_MAINNET_CHAIN_ID, contract)
            except RegistrySourceError:
                deployment_reason = "INVALID_BNB_CONTRACT_EVIDENCE"
        else:
            deployment_reason = "BNB_CONTRACT_UNAVAILABLE"
        try:
            observed_at = _timestamp(raw.get("last_updated"))
            price = _number(raw.get("current_price"), "PRICE", positive=True)
            market_cap = _number(raw.get("market_cap"), "MARKET_CAP")
            volume = _number(raw.get("total_volume"), "VOLUME_24H")
            change = _number(raw.get("price_change_percentage_24h"), "CHANGE_24H", signed=True)
        except ValueError:
            degraded.add("BAD_MARKET_ECONOMICS_EXCLUDED")
            continue
        try:
            circulating = _number(raw.get("circulating_supply"), "CIRCULATING_SUPPLY")
            total = _number(raw.get("total_supply"), "TOTAL_SUPPLY")
        except ValueError:
            degraded.add("BAD_MARKET_ECONOMICS_EXCLUDED")
            continue
        if observed_at is not None and (observed_at - retrieved_at).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            degraded.add("FUTURE_MARKET_OBSERVATION_EXCLUDED")
            continue
        unavailable_fields = tuple(
            field for field, value in (
                ("price_usd", price), ("market_cap_usd", market_cap),
                ("volume_24h_usd", volume), ("price_change_24h_pct", change),
                ("circulating_supply", circulating), ("total_supply", total),
            ) if value is None
        )
        if observed_at is None or price is None:
            state = AuthorityState.UNAVAILABLE
            unavailable_fields = tuple(sorted(set(unavailable_fields + ("observed_at",)))) if observed_at is None else unavailable_fields
        elif (retrieved_at - observed_at).total_seconds() > MAX_CURRENT_AGE_SECONDS:
            state = AuthorityState.STALE
        else:
            state = AuthorityState.AVAILABLE
        candidates.append(BnbRwaMarketObservation(
            provider_id=provider_id, symbol=symbol.upper(), name=name,
            asset_key=asset_key, deployment_reason=deployment_reason,
            observed_at=observed_at, state=state, price_usd=price,
            market_cap_usd=market_cap, volume_24h_usd=volume,
            price_change_24h_pct=change, circulating_supply=circulating,
            total_supply=total, unavailable_fields=unavailable_fields,
        ))

    deployment_counts = Counter(row.asset_key for row in candidates if row.asset_key is not None)
    if any(count > 1 for count in deployment_counts.values()):
        degraded.add("DUPLICATE_BNB_DEPLOYMENT_EXCLUDED")
    observations = tuple(sorted(
        (row for row in candidates if row.asset_key is None or deployment_counts[row.asset_key] == 1),
        key=lambda row: row.provider_id,
    ))
    current = tuple(row for row in observations if row.state is AuthorityState.AVAILABLE)
    stale = tuple(row for row in observations if row.state is AuthorityState.STALE)
    eligible = tuple(row for row in current if row.asset_key is not None)
    caps = tuple(row.market_cap_usd for row in eligible if row.market_cap_usd is not None)
    volumes = tuple(row.volume_24h_usd for row in eligible if row.volume_24h_usd is not None)
    if stale:
        degraded.add("STALE_ROWS_EXCLUDED_FROM_AGGREGATES")
    if any(row.asset_key is None for row in observations):
        degraded.add("UNRESOLVED_DEPLOYMENTS_EXCLUDED_FROM_AGGREGATES")
    state = (
        AuthorityState.AVAILABLE if eligible else
        AuthorityState.STALE if any(row.asset_key is not None for row in stale) else
        AuthorityState.UNAVAILABLE
    )
    return BnbRwaMarketSnapshot(
        retrieved_at=retrieved_at, state=state, observations=observations,
        observed_market_cap_usd=sum(caps, Decimal(0)) if caps else None,
        observed_volume_24h_usd=sum(volumes, Decimal(0)) if volumes else None,
        market_cap_contributors=len(caps), volume_contributors=len(volumes),
        current_count=len(current), stale_count=len(stale),
        deployment_available_count=sum(row.asset_key is not None for row in observations),
        deployment_unavailable_count=sum(row.asset_key is None for row in observations),
        degraded_reasons=tuple(sorted(degraded)),
        reason=None if state is AuthorityState.AVAILABLE else "NO_CURRENT_IDENTIFIED_BNB_OBSERVATIONS",
    )
