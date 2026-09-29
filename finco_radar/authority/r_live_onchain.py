"""Fail-closed, read-only V3 TWAP plus USDG/USD reference for exact AssetKeys.

All chain reads are pinned to one block. This module has no swap, wallet,
transaction, pool discovery, or executable-price path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any, Mapping, Protocol

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, RegistryAssetStatus
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityState, IndependentTokenReference

from .r_live_policy import (
    APPROVED_RLIVE_ASSETS, MAX_BLOCK_FUTURE_SKEW_SECONDS,
    QUOTE_AUTHORITY_VERSION, RPC_TIMEOUT_SECONDS,
    RPC_TRANSIENT_RETRIES, SUPPORTED_CHAIN_ID, PoolAuthority,
)


class Rpc(Protocol):
    def call(self, method: str, params: list[Any]) -> Any: ...


class RpcUnavailable(ValueError):
    """Never includes an endpoint, credential, response body, or transport repr."""


class JsonRpc:
    """Generic EVM transport. Inject an httpx client in tests; URL is private."""

    def __init__(self, url: str, *, client: httpx.Client | None = None,
                 timeout_seconds: int = RPC_TIMEOUT_SECONDS) -> None:
        if not url.startswith("https://"):
            raise ValueError("HTTPS_RPC_URL_REQUIRED")
        self._url = url
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def __repr__(self) -> str:
        return "JsonRpc(<redacted>)"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def call(self, method: str, params: list[Any]) -> Any:
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for attempt in range(RPC_TRANSIENT_RETRIES + 1):
            try:
                response = self._client.post(self._url, json=request)
                response.raise_for_status()
                payload = response.json()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt < RPC_TRANSIENT_RETRIES:
                    continue
                raise RpcUnavailable("RPC_TRANSPORT_UNAVAILABLE") from None
            except (httpx.HTTPError, ValueError):
                raise RpcUnavailable("RPC_RESPONSE_UNAVAILABLE") from None
            if not isinstance(payload, dict) or payload.get("error") is not None:
                raise RpcUnavailable("RPC_RESPONSE_UNAVAILABLE")
            return payload.get("result")
        raise RpcUnavailable("RPC_TRANSPORT_UNAVAILABLE")


@dataclass(frozen=True)
class OnchainReferenceObservation:
    state: AuthorityState
    asset_key: AssetKey
    registry_asset_uid: str | None
    reason: str | None
    price_usd_per_token: Decimal | None = None
    observed_at: datetime | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_independent_reference(self) -> IndependentTokenReference | None:
        if self.state is not AuthorityState.AVAILABLE:
            return None
        assert self.registry_asset_uid and self.price_usd_per_token and self.observed_at
        return IndependentTokenReference(
            self.registry_asset_uid, self.asset_key, self.price_usd_per_token,
            "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD", self.observed_at,
            evidence=self.evidence,
        )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "assetKey": self.asset_key.canonical_id,
                "assetUid": self.registry_asset_uid, "reason": self.reason,
                "priceUsdPerToken": str(self.price_usd_per_token) if self.price_usd_per_token is not None else None,
                "observedAt": self.observed_at.isoformat() if self.observed_at else None,
                "evidence": dict(self.evidence)}


class _BadEvidence(ValueError):
    pass


def _hex(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) % 2:
        raise _BadEvidence("MALFORMED_HEX")
    try:
        bytes.fromhex(value[2:])
    except ValueError:
        raise _BadEvidence("MALFORMED_HEX") from None
    return value[2:]


def _uint(value: Any) -> int:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) <= 2:
        raise _BadEvidence("MALFORMED_HEX_QUANTITY")
    try:
        return int(value[2:], 16)
    except ValueError:
        raise _BadEvidence("MALFORMED_HEX_QUANTITY") from None


def _words(value: Any, count: int) -> list[int]:
    raw = _hex(value)
    if len(raw) < 64 * count or len(raw) % 64:
        raise _BadEvidence("MALFORMED_ETH_CALL")
    return [int(raw[i * 64:(i + 1) * 64], 16) for i in range(count)]


def _address(value: Any) -> str:
    word = _words(value, 1)[0]
    if word >= 1 << 160:
        raise _BadEvidence("INVALID_ADDRESS_WORD")
    return f"0x{word:040x}"


def _signed(value: int) -> int:
    return value - (1 << 256) if value >= 1 << 255 else value


def _abi_string(value: Any) -> str:
    raw = _hex(value)
    words = _words(value, 2)
    if words[0] != 32 or words[1] > 128 or len(raw) < 128 + words[1] * 2:
        raise _BadEvidence("MALFORMED_ABI_STRING")
    try:
        return bytes.fromhex(raw[128:128 + words[1] * 2]).decode("utf-8")
    except UnicodeError:
        raise _BadEvidence("MALFORMED_ABI_STRING") from None


def _call(rpc: Rpc, address: str, data: str, block: str) -> Any:
    return rpc.call("eth_call", [{"to": address, "data": data}, block])


def _observe_calldata(window: int) -> str:
    return "0x883bdbfd" + f"{32:064x}{2:064x}{window:064x}{0:064x}"


def _tick_cumulatives(value: Any) -> tuple[int, int]:
    raw = _hex(value)
    words = _words(value, 6)
    if words[0] != 64 or words[2] != 2:
        raise _BadEvidence("INVALID_ORACLE_OBSERVATION")
    return _signed(words[3]), _signed(words[4])


def _quote_price(mean_tick: int, pool: PoolAuthority, token0: str) -> Decimal:
    if not -887272 <= mean_tick <= 887272:
        raise _BadEvidence("INVALID_TICK")
    with localcontext() as context:
        context.prec = 90
        ratio = Decimal("1.0001") ** mean_tick  # raw token1 / raw token0
        if token0 == pool.quote_token_address:
            return +(Decimal(10) ** (pool.token_decimals - pool.quote_decimals) / ratio)
        return +(ratio * Decimal(10) ** (pool.token_decimals - pool.quote_decimals))


def _availability(key: AssetKey, uid: str | None, reason: str,
                  state: AuthorityState = AuthorityState.UNAVAILABLE) -> OnchainReferenceObservation:
    return OnchainReferenceObservation(state, key, uid, reason)


def observe_onchain_reference(
    *, registry: RegistrySnapshot | None, key: AssetKey, rpc: Rpc,
    retrieved_at: datetime | None = None,
) -> OnchainReferenceObservation:
    """Observe only a reviewed exact deployment; never discover/select pools."""
    if retrieved_at is not None and (retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None):
        raise ValueError("retrieved_at must be timezone-aware")
    policy = APPROVED_RLIVE_ASSETS.get(key)
    if key.chain_id != SUPPORTED_CHAIN_ID or policy is None:
        return _availability(key, None, "POOL_NOT_APPROVED_FOR_EXACT_ASSETKEY")
    pool = policy.pool
    if (registry is None or registry.source != RobinhoodAssetRegistryAdapter.source_name
            or registry.observed_at.tzinfo is None):
        return _availability(key, None, "CANONICAL_REGISTRY_UNAVAILABLE")
    registry_age = ((retrieved_at or datetime.now(timezone.utc)) - registry.observed_at).total_seconds()
    if not 0 <= registry_age <= policy.max_registry_age_seconds:
        return _availability(key, None, "CANONICAL_REGISTRY_STALE", AuthorityState.STALE)
    asset = registry.get_by_key(key)
    if asset is None:
        return _availability(key, None, "CANONICAL_DEPLOYMENT_ABSENT")
    uid = asset.asset_uid
    if uid != policy.economic_asset_uid:
        return _availability(key, uid, "CANONICAL_ECONOMIC_UID_MISMATCH")
    if asset.status is not RegistryAssetStatus.ACTIVE:
        return _availability(key, uid, "CANONICAL_ASSET_NOT_ACTIVE")
    try:
        if _uint(rpc.call("eth_chainId", [])) != SUPPORTED_CHAIN_ID:
            raise _BadEvidence("CHAIN_ID_MISMATCH")
        block = rpc.call("eth_getBlockByNumber", ["latest", False])
        if not isinstance(block, dict):
            raise _BadEvidence("BLOCK_UNAVAILABLE")
        number = _uint(block.get("number"))
        block_hash = block.get("hash")
        if len(_hex(block_hash)) != 64:
            raise _BadEvidence("BLOCK_HASH_UNAVAILABLE")
        block_time = _uint(block.get("timestamp"))
        tag = f"0x{number:x}"
        now = retrieved_at or datetime.now(timezone.utc)
        age = int(now.timestamp()) - block_time
        if age < -MAX_BLOCK_FUTURE_SKEW_SECONDS or age > policy.max_block_age_seconds:
            return _availability(key, uid, "DEX_BLOCK_STALE", AuthorityState.STALE)
        for address, label in ((pool.factory_address, "FACTORY"),
                               (pool.pool_address, "POOL"),
                               (pool.quote_feed_address, "QUOTE_FEED")):
            if _hex(rpc.call("eth_getCode", [address, tag])) == "":
                raise _BadEvidence(f"{label}_CODE_MISSING")
        pair_data = ("0x1698ee82" + pool.asset_key.contract_address[2:].zfill(64)
                     + pool.quote_token_address[2:].zfill(64) + f"{pool.fee:064x}")
        if _address(_call(rpc, pool.factory_address, pair_data, tag)) != pool.pool_address:
            raise _BadEvidence("POOL_FACTORY_PROVENANCE_MISMATCH")
        if _address(_call(rpc, pool.pool_address, "0xc45a0155", tag)) != pool.factory_address:
            raise _BadEvidence("POOL_FACTORY_MISMATCH")
        token0 = _address(_call(rpc, pool.pool_address, "0x0dfe1681", tag))
        token1 = _address(_call(rpc, pool.pool_address, "0xd21220a7", tag))
        if {token0, token1} != {key.contract_address, pool.quote_token_address}:
            raise _BadEvidence("POOL_PAIR_MISMATCH")
        if _words(_call(rpc, pool.pool_address, "0xddca3f43", tag), 1)[0] != pool.fee:
            raise _BadEvidence("POOL_FEE_MISMATCH")
        token_decimals = _words(_call(rpc, key.contract_address, "0x313ce567", tag), 1)[0]
        quote_decimals = _words(_call(rpc, pool.quote_token_address, "0x313ce567", tag), 1)[0]
        if (token_decimals, quote_decimals) != (pool.token_decimals, pool.quote_decimals):
            raise _BadEvidence("TOKEN_DECIMALS_MISMATCH")
        liquidity = _words(_call(rpc, pool.pool_address, "0x1a686502", tag), 1)[0]
        slot = _words(_call(rpc, pool.pool_address, "0x3850c7bd", tag), 7)
        if liquidity <= 0 or slot[3] < 2:
            raise _BadEvidence("POOL_LIQUIDITY_OR_CARDINALITY_INSUFFICIENT")
        cumulative_start, cumulative_end = _tick_cumulatives(
            _call(rpc, pool.pool_address, _observe_calldata(policy.twap_window_seconds), tag))
        mean_tick = (cumulative_end - cumulative_start) // policy.twap_window_seconds
        token_quote = _quote_price(mean_tick, pool, token0)
        if _abi_string(_call(rpc, pool.quote_feed_address, "0x7284e416", tag)) != "USDG / USD":
            raise _BadEvidence("QUOTE_FEED_DESCRIPTION_MISMATCH")
        feed_decimals = _words(_call(rpc, pool.quote_feed_address, "0x313ce567", tag), 1)[0]
        if feed_decimals != pool.feed_decimals:
            raise _BadEvidence("QUOTE_FEED_DECIMALS_MISMATCH")
        round_id, raw_answer, started, updated, answered_in = _words(
            _call(rpc, pool.quote_feed_address, "0xfeaf968c", tag), 5)
        raw_answer = _signed(raw_answer)
        if (round_id <= 0 or raw_answer <= 0 or started <= 0 or updated < started
                or updated > block_time or answered_in < round_id):
            raise _BadEvidence("QUOTE_FEED_ROUND_INVALID")
        if block_time - updated > policy.max_quote_age_seconds:
            return _availability(key, uid, "QUOTE_FEED_STALE", AuthorityState.STALE)
        again = rpc.call("eth_getBlockByNumber", [tag, False])
        if not isinstance(again, dict) or again.get("hash") != block_hash:
            raise _BadEvidence("BLOCK_REORG_OR_MISMATCH")
        with localcontext() as context:
            context.prec = 90
            quote_usd = Decimal(raw_answer) / Decimal(10) ** feed_decimals
            token_usd = +(token_quote * quote_usd)
        block_at = datetime.fromtimestamp(block_time, timezone.utc)
        quote_at = datetime.fromtimestamp(updated, timezone.utc)
        observed = min(block_at, quote_at)
        evidence = {
            "policyVersion": policy.authority_version, "poolAuthorityVersion": pool.version,
            "quoteAuthorityVersion": QUOTE_AUTHORITY_VERSION,
            "assetKey": key.canonical_id, "registryAssetUid": uid,
            "chainId": SUPPORTED_CHAIN_ID, "dexProtocol": "UNISWAP", "dexVersion": "V3",
            "factory": pool.factory_address, "pool": pool.pool_address, "fee": pool.fee,
            "token0": token0, "token1": token1, "tokenDecimals": token_decimals,
            "quoteToken": pool.quote_token_address, "quoteDecimals": quote_decimals,
            "liquidity": str(liquidity), "observationCardinality": slot[3],
            "blockNumber": number, "blockHash": block_hash, "blockTimestamp": block_at.isoformat(),
            "twapWindowSeconds": policy.twap_window_seconds,
            "dexWindowStartAt": datetime.fromtimestamp(block_time - policy.twap_window_seconds, timezone.utc).isoformat(),
            "dexWindowEndAt": block_at.isoformat(),
            "tickCumulativeStart": str(cumulative_start),
            "tickCumulativeEnd": str(cumulative_end), "arithmeticMeanTick": mean_tick,
            "tokenQuotePrice": str(token_quote),
            "quoteUsdAuthority": pool.quote_feed_address, "quoteRoundId": str(round_id),
            "quoteAnswerRaw": str(raw_answer), "quoteFeedDecimals": feed_decimals,
            "quoteUsdPrice": str(quote_usd), "quoteStartedAt": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "quoteUpdatedAt": quote_at.isoformat(), "quoteAnsweredInRound": str(answered_in),
            "tokenUsdPrice": str(token_usd), "effectiveObservedAt": observed.isoformat(),
            "retrievedAt": (retrieved_at or datetime.now(timezone.utc)).isoformat(),
        }
        return OnchainReferenceObservation(AuthorityState.AVAILABLE, key, uid, None,
                                            token_usd, observed, evidence)
    except (_BadEvidence, RpcUnavailable, ValueError, TypeError, OverflowError) as exc:
        reason = str(exc) if isinstance(exc, _BadEvidence) else "RPC_OR_SOURCE_EVIDENCE_UNAVAILABLE"
        return _availability(key, uid, reason)
