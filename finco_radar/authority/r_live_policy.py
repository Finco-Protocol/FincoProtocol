"""Reviewed R-LIVE V1 authorities. Changes to these values require review.

The pool was verified on chain 4663 on 2026-09-28: Uniswap's official
factory returned it for the exact Paxos USDG and canonical Robinhood AAPL
pair at fee 500. Pool bytecode, token ordering, liquidity, cardinality 3000,
and a 300-second ``observe`` call were checked. Fee 100 had no pool; fee
3000 had lower active liquidity; fee 10000 had no recent activity in the
bounded 5000-block inspection. Runtime never discovers a replacement.
"""
from __future__ import annotations

from dataclasses import dataclass

from finco_radar.assets.contracts import AssetKey


POLICY_VERSION = "R_LIVE_ONCHAIN_REFERENCE_V1"
POOL_AUTHORITY_VERSION = "R_LIVE_AAPL_USDG_V3_POOL_V1"
QUOTE_AUTHORITY_VERSION = "CHAINLINK_ROBINHOOD_USDG_USD_RDD_2026_09_28"
SUPPORTED_CHAIN_ID = 4663
TWAP_WINDOW_SECONDS = 300
MAX_BLOCK_AGE_SECONDS = 120
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

APPROVED_POOLS = {AAPL_KEY: AAPL_POOL}
