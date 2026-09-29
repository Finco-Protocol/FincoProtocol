"""Reviewed R-LIVE V1 authorities. Changes to these values require review.

The pool was verified on chain 4663 on 2026-09-28: Uniswap's official
factory returned it for the exact Paxos USDG and canonical Robinhood AAPL
pair at fee 500. Pool bytecode, token ordering, liquidity, cardinality 3000,
and a 300-second ``observe`` call were checked. Fee 100 had no pool.
A bounded 5000-block Swap-event check on 2026-09-28 found 15 swaps in
fee 500 and none in fee 3000 or 10000; fee 500 also had the largest active
liquidity. Runtime never discovers a replacement.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from finco_radar.assets.contracts import AssetKey


POLICY_VERSION = "R_LIVE_ONCHAIN_REFERENCE_V1"
POOL_AUTHORITY_VERSION = "R_LIVE_AAPL_USDG_V3_POOL_V1"
QUOTE_AUTHORITY_VERSION = "CHAINLINK_ROBINHOOD_USDG_USD_RDD_2026_09_28"
SUPPORTED_CHAIN_ID = 4663
TWAP_WINDOW_SECONDS = 300
MAX_BLOCK_AGE_SECONDS = 120
MAX_BLOCK_FUTURE_SKEW_SECONDS = 30
MAX_REGISTRY_AGE_SECONDS = 300
MAX_QUOTE_AGE_SECONDS = 86400  # Chainlink Robinhood RDD heartbeat
RPC_TIMEOUT_SECONDS = 15
RPC_TRANSIENT_RETRIES = 1


@dataclass(frozen=True)
class PoolAuthority:
    asset_key: AssetKey
    pool_address: str
    factory_address: str
    quote_token_address: str
    quote_feed_address: str
    fee: int
    token_decimals: int
    quote_decimals: int
    feed_decimals: int
    version: str = POOL_AUTHORITY_VERSION


@dataclass(frozen=True)
class RLiveAssetPolicy:
    """Reviewed identity and reference authority, never selected by ticker at runtime."""

    symbol: str  # display only
    economic_asset_uid: str
    pool: PoolAuthority
    reference_venue: str = "UNISWAP_V3_ROBINHOOD_CHAIN"
    provenance: tuple[tuple[str, str], ...] = (
        ("robinhood_registry", "https://api.robinhood.com/rhj/assets"),
        ("factory_chain_id", "4663"),
        ("reviewed_at_utc", "2026-09-29"),
    )
    authority_version: str = "R_LIVE_MULTI_ASSET_REFERENCE_V2"
    twap_window_seconds: int = TWAP_WINDOW_SECONDS
    max_block_age_seconds: int = MAX_BLOCK_AGE_SECONDS
    max_registry_age_seconds: int = MAX_REGISTRY_AGE_SECONDS
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS
    # A token market is current only if a Swap occurred within its 300s TWAP
    # window. A fresh chain block alone is not a fresh token market.
    max_pool_activity_age_seconds: int = TWAP_WINDOW_SECONDS
    pool_activity_lookback_blocks: int = 5000

    @property
    def asset_key(self) -> AssetKey:
        return self.pool.asset_key


AAPL_KEY = AssetKey(SUPPORTED_CHAIN_ID, "0xaf3d76f1834a1d425780943c99ea8a608f8a93f9")
AAPL_POOL = PoolAuthority(
    asset_key=AAPL_KEY,
    pool_address="0xaae0d815ee56e4092a5e5c2911e676fea50b2d6d",
    factory_address="0x1f7d7550b1b028f7571e69a784071f0205fd2efa",
    quote_token_address="0x5fc5360d0400a0fd4f2af552add042d716f1d168",
    quote_feed_address="0x61b7e5650328764b076a108eff5fa7282a1b9ad2",
    fee=500,
    token_decimals=18,
    quote_decimals=6,
    feed_decimals=8,
)

AAPL_UID = "0x00000000000000000000000000000000c2425be3658540dd8e2424cbf3c5c649"
_FACTORY = AAPL_POOL.factory_address
_USDG = AAPL_POOL.quote_token_address
_FEED = AAPL_POOL.quote_feed_address


def _reviewed(symbol: str, uid: str, token: str, pool: str, fee: int) -> RLiveAssetPolicy:
    key = AssetKey(SUPPORTED_CHAIN_ID, token)
    return RLiveAssetPolicy(symbol, uid, PoolAuthority(
        asset_key=key, pool_address=pool, factory_address=_FACTORY,
        quote_token_address=_USDG, quote_feed_address=_FEED, fee=fee,
        token_decimals=18, quote_decimals=6, feed_decimals=8,
        version=f"R_LIVE_{symbol}_USDG_V3_POOL_V2",
    ))


# Reviewed 2026-09-29 against the official Robinhood asset registry and chain
# 4663 factory/pool contracts. AAPL retains its exact V1 authority/version.
_APPROVED = (
    RLiveAssetPolicy("AAPL", AAPL_UID, AAPL_POOL, authority_version=POLICY_VERSION,
                     provenance=(("robinhood_registry", "https://api.robinhood.com/rhj/assets"),
                                 ("factory_chain_id", "4663"), ("reviewed_at_utc", "2026-09-28"))),
    _reviewed("NVDA", "0x00000000000000000000000000000000915f477416294f5099a5e0e09f327ce5", "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec", "0xd4eb21209c4d6093f80b5b84f5c45cc093ea14a3", 500),
    _reviewed("AMZN", "0x000000000000000000000000000000004f508d5e2a7042299694d85c2f362ad2", "0x12f190a9f9d7d37a250758b26824b97ce941bf54", "0x8ac92da74ab5f3b1d024dc1943ad7e15dc4179ef", 3000),
    _reviewed("GOOGL", "0x0000000000000000000000000000000053b69e2076884cc9ae2ada9bc7095df3", "0x2e0847e8910a9732eb3fb1bb4b70a580adad4fe3", "0x34d0dc122cf9a8eb296fc5e0d3a233625d7d19b7", 500),
    _reviewed("TSLA", "0x00000000000000000000000000000000cfece3244ea34bb29414dd9488b32d9f", "0x322f0929c4625ed5bad873c95208d54e1c003b2d", "0xf4acdaeeb7022862a763c9b1b885e11191c889e3", 3000),
    _reviewed("AVGO", "0x000000000000000000000000000000001bbb45628de84cb2917abd26680c7ab9", "0x156e175dd063a8ce274c50654ef40e0032b3fbcf", "0x5b7c404f1d7d77f9f3885ab13d7764f8a173028c", 3000),
    _reviewed("NFLX", "0x00000000000000000000000000000000500f14b2a92f44d6998e0e2b9cc9387e", "0xe0444ef8bf4ed74f74fd73686e2ddf4c1c5591e8", "0x59895c0302f41aeaa129d2fa2442cec01e7ef45e", 3000),
    _reviewed("AMD", "0x0000000000000000000000000000000086aeaac3c7d9422c90f6fd41aff0eaf7", "0x86923f96303d656e4aa86d9d42d1e57ad2023fdc", "0x48d284a2a4d3dc1b3da08231fe44317e7e7aa51f", 3000),
    # Review block 75763398, 2026-09-29. Exact registry deployments and
    # factory-returned pools passed pair/fee/decimals, 300s observe, liquidity,
    # cardinality, recent bounded Swap and USDG/USD quote checks. Admission
    # evidence (including rejected candidates) is retained in docs.
    _reviewed("DELL", "0x0000000000000000000000000000000014eaef73a2c44d62b7952cfd0a44ff51", "0x941ae714ec6d8130c7b75d67160ca08f1e7d11dd", "0xc30c89cb7815a1488b7998d15eec73961707fc5a", 10000),
    _reviewed("SNAP", "0x000000000000000000000000000000002993bb34578a4b92b8addda0fc4d697b", "0xf6589f11bc40b669e584073f428b05562f568733", "0x0ebd4650c9e641e9745b5a508a2d46935dfe753e", 3000),
    _reviewed("INTC", "0x000000000000000000000000000000002eb75a2c20d7423881b4f812c27d0abe", "0xc72b96e0e48ecd4dc75e1e45396e26300bc39681", "0x2e5a92f5013a64661a49312111be2e8abd33f56a", 3000),
    _reviewed("MSFT", "0x00000000000000000000000000000000307bb0113ca54f93adf80f4ff2bf681a", "0xe93237c50d904957cf27e7b1133b510c669c2e74", "0xeb60bcd1d920ad6e102690ccfc6fb488899e1510", 3000),
    _reviewed("META", "0x00000000000000000000000000000000343e7beca03644bcba2e50b8236784f5", "0xc0d6457c16cc70d6790dd43521c899c87ce02f35", "0x107a7cb40d8665360ba10e59471af06150a50922", 3000),
)
APPROVED_RLIVE_ASSETS = MappingProxyType({policy.asset_key: policy for policy in _APPROVED})
APPROVED_BY_CANONICAL_ID = MappingProxyType({policy.asset_key.canonical_id: policy for policy in _APPROVED})
# Compatibility alias for V1 callers; immutable and still exact-key indexed.
APPROVED_POOLS = MappingProxyType({key: policy.pool for key, policy in APPROVED_RLIVE_ASSETS.items()})
