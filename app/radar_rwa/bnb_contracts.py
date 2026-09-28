"""BNB tokenized-asset market observations, separate from RWA overview and B1 identity.

CoinGecko's coin market quantities are coin-level/global, even when its platform
metadata lists a BNB deployment. They are never BNB-chain TVL or Robinhood
economic-reference evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthorityState


BNB_MAINNET_CHAIN_ID = 56
TOKENIZED_CATEGORY_ID = "tokenized-products"
GLOBAL_MARKET_SCOPE = "COINGECKO_COIN_GLOBAL_NOT_BNB_SPECIFIC"
RWA_TVL_REASON = "NO_RWA_SPECIFIC_TVL_AUTHORITY"


@dataclass(frozen=True)
class BnbRwaMarketObservation:
    provider_id: str
    symbol: str
    name: str
    asset_key: AssetKey | None
    deployment_reason: str | None
    observed_at: datetime | None
    state: AuthorityState
    price_usd: Decimal | None
    market_cap_usd: Decimal | None
    volume_24h_usd: Decimal | None
    price_change_24h_pct: Decimal | None
    circulating_supply: Decimal | None
    total_supply: Decimal | None
    unavailable_fields: tuple[str, ...]
    source: str = "CoinGecko"
    market_endpoint: str = "/coins/markets"
    deployment_endpoint: str = "/coins/list?include_platform=true"
    classification: str = TOKENIZED_CATEGORY_ID
    market_scope: str = GLOBAL_MARKET_SCOPE
    robinhood_binding: AuthorityState = AuthorityState.IDENTITY_UNAVAILABLE

    def __post_init__(self) -> None:
        if not self.provider_id or not self.symbol or not self.name:
            raise ValueError("provider identity fields are required")
        if self.asset_key is not None and self.asset_key.chain_id != BNB_MAINNET_CHAIN_ID:
            raise ValueError("BNB observation must use mainnet chain 56")
        if self.asset_key is None and not self.deployment_reason:
            raise ValueError("missing deployment needs a reason")
        if self.asset_key is not None and self.deployment_reason is not None:
            raise ValueError("identified deployment cannot carry an unavailable reason")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")
        if self.robinhood_binding is not AuthorityState.IDENTITY_UNAVAILABLE:
            raise ValueError("B1.1 cannot assert Robinhood economic binding")
        if self.market_scope != GLOBAL_MARKET_SCOPE:
            raise ValueError("CoinGecko coin-level metrics cannot be called BNB-specific")


@dataclass(frozen=True)
class BnbRwaMarketSnapshot:
    retrieved_at: datetime
    state: AuthorityState
    observations: tuple[BnbRwaMarketObservation, ...]
    observed_market_cap_usd: Decimal | None
    observed_volume_24h_usd: Decimal | None
    market_cap_contributors: int
    volume_contributors: int
    current_count: int
    stale_count: int
    deployment_available_count: int
    deployment_unavailable_count: int
    degraded_reasons: tuple[str, ...]
    reason: str | None = None
    chain_id: int = BNB_MAINNET_CHAIN_ID
    category_id: str = TOKENIZED_CATEGORY_ID
    market_scope: str = GLOBAL_MARKET_SCOPE
    rwa_tvl_usd: None = None
    rwa_tvl_reason: str = RWA_TVL_REASON
    source: str = "CoinGecko"
    source_endpoints: tuple[str, ...] = (
        "/asset_platforms", "/coins/list?include_platform=true", "/coins/markets",
    )

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.chain_id != BNB_MAINNET_CHAIN_ID or self.market_scope != GLOBAL_MARKET_SCOPE:
            raise ValueError("BNB chain and global market scope are fixed")
        if self.rwa_tvl_usd is not None or self.rwa_tvl_reason != RWA_TVL_REASON:
            raise ValueError("no RWA-specific TVL source is authorized")
        for count in (
            self.market_cap_contributors, self.volume_contributors, self.current_count,
            self.stale_count, self.deployment_available_count,
            self.deployment_unavailable_count,
        ):
            if isinstance(count, bool) or count < 0:
                raise ValueError("snapshot counts must be nonnegative integers")
