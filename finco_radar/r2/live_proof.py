"""Networked R2 proof: directional quote/reference gaps on canonical Stock Tokens."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, RegistryAssetStatus
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import (
    AssetRef,
    QuoteRequest,
    QuoteSide,
    QuoteStatus,
    SettlementReference,
    SettlementReferenceState,
)

CHAIN_ID = 4663
ROBINHOOD_API = "https://api.robinhood.com/rhj"
LIFI_API = "https://li.quest/v1"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
USDG_ADDRESS = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TAKER = "0x1111111111111111111111111111111111111111"
CANDIDATE_SYMBOLS = ("AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL")
NOTIONALS = (Decimal("100"), Decimal("1000"))


def _get_json(client: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected JSON shape from {url}")
    return payload


def _rpc(client: httpx.Client, method: str, params: list[Any]) -> Any:
    response = client.post(
        PUBLIC_RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"RPC error for {method}: {payload['error']}")
    return payload["result"]


def _erc20_decimals(client: httpx.Client, address: str) -> int:
    result = _rpc(client, "eth_call", [{"to": address, "data": "0x313ce567"}, "latest"])
    return int(result, 16)


def _discover_settlement(client: httpx.Client) -> tuple[AssetRef, SettlementReference]:
    token = _get_json(
        client,
        f"{LIFI_API}/token",
        params={"chain": CHAIN_ID, "token": USDG_ADDRESS},
    )
    address = str(token["address"]).lower()
    if address != USDG_ADDRESS:
        raise RuntimeError("settlement metadata returned a different contract address")
    if str(token.get("symbol", "")).upper() != "USDG":
        raise RuntimeError("canonical settlement address returned unexpected symbol")
    decimals = _erc20_decimals(client, address)
    price = Decimal(str(token.get("priceUSD") or "0"))
    if not price.is_finite() or price <= 0:
        raise RuntimeError("settlement USD reference unavailable")
    asset = AssetRef(CHAIN_ID, address, symbol="USDG", decimals=decimals)
    reference = SettlementReference(
        asset=asset,
        state=SettlementReferenceState.REFERENCE_CURRENT,
        usd_per_asset=price,
        source="LIFI_TOKEN_METADATA_REFERENCE_ONLY",
        observed_at=datetime.now(timezone.utc),
        raw_evidence={
            "address": token.get("address"),
            "symbol": token.get("symbol"),
            "decimals": token.get("decimals"),
            "priceUSD": token.get("priceUSD"),
            "canonicalIdentity": f"{CHAIN_ID}:{address}",
        },
    )
    return asset, reference


def _route_tools(quote: Any) -> list[str]:
    if quote.evidence is None:
        return []
    tools = [leg.tool for leg in quote.evidence.route if leg.tool]
    if tools:
        return tools
    tool = quote.evidence.response_fields.get("tool")
    return [str(tool)] if tool else []


def _observation_dict(observation: Any, quote: Any) -> dict[str, Any]:
    return {
        "side": observation.side.value,
        "requestedNotionalUsd": str(observation.requested_notional_usd),
        "tokenAmount": str(observation.token_amount),
        "settlementAmountUsd": str(observation.settlement_amount_usd),
        "executionPriceUsdPerToken": str(observation.execution_price_usd_per_token),
        "referenceSide": observation.reference_side.value,
        "referencePriceUsdPerToken": str(observation.reference_price_usd_per_token),
        "gapBps": str(observation.gap_bps),
        "quoteSource": observation.quote_source,
        "quotedAt": observation.quoted_at.isoformat(),
        "referenceGeneratedAt": observation.reference_generated_at.isoformat(),
        "referenceIsTradingHalt": observation.reference_is_trading_halt,
        "feeCostUsd": str(observation.fee_cost_usd) if observation.fee_cost_usd is not None else None,
        "gasCostUsd": str(observation.gas_cost_usd) if observation.gas_cost_usd is not None else None,
        "costScope": observation.cost_scope,
        "referenceStateAuthority": observation.reference_state_authority,
        "routeTools": _route_tools(quote),
    }


def run(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> dict[str, Any]:
    timeout = httpx.Timeout(25.0)
    failures: list[dict[str, str]] = []
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as client:
        _, settlement_reference = _discover_settlement(client)
        registry_adapter = RobinhoodAssetRegistryAdapter(client=client)
        snapshot = registry_adapter.fetch_snapshot()

        with httpx.Client(base_url=LIFI_API, timeout=timeout, headers={"accept": "application/json"}) as lifi_client:
            quote_adapter = LifiExecutionQuoteAdapter(client=lifi_client)
            for requested_symbol in symbols:
                try:
                    matches = snapshot.find_by_symbol(requested_symbol)
                    if len(matches) != 1:
                        raise RuntimeError(f"symbol discovery returned {len(matches)} matches")
                    asset = matches[0]
                    if asset.status is not RegistryAssetStatus.ACTIVE:
                        raise RuntimeError("canonical asset is not ACTIVE")
                    key = asset.deployment_for_chain(CHAIN_ID)
                    if key is None:
                        raise RuntimeError("canonical asset has no Robinhood Chain deployment")
                    binding, price_row = registry_adapter.fetch_bound_reference(snapshot, key)
                    reference = build_bound_reference_price(asset, binding, price_row)
                    if reference.is_trading_halt:
                        raise RuntimeError("official reference is explicitly halted")

                    token_decimals = _erc20_decimals(client, key.contract_address)
                    token = AssetRef(
                        CHAIN_ID,
                        key.contract_address,
                        symbol=asset.token_symbol,
                        decimals=token_decimals,
                    )
                    observations: list[dict[str, Any]] = []
                    for side in (QuoteSide.BUY, QuoteSide.SELL):
                        for notional in NOTIONALS:
                            request = QuoteRequest(
                                token=token,
                                settlement=settlement_reference,
                                side=side,
                                requested_notional_usd=notional,
                                taker_address=TAKER,
                                token_sizing_reference_usd=(
                                    reference.token_midpoint_usd_per_token
                                    if side is QuoteSide.SELL
                                    else None
                                ),
                                token_sizing_reference_source=(
                                    "R2_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                                    if side is QuoteSide.SELL
                                    else None
                                ),
                            )
                            quote = quote_adapter.quote(request)
                            if quote.status is not QuoteStatus.QUOTE_OK:
                                raise RuntimeError(
                                    f"{side.value}-{notional} quote status {quote.status.value}"
                                )
                            observation = compute_directional_gap(reference, quote)
                            observations.append(_observation_dict(observation, quote))

                    return {
                        "status": "PASS",
                        "chainId": CHAIN_ID,
                        "asset": {
                            "assetUid": asset.asset_uid,
                            "canonicalKey": key.canonical_id,
                            "symbol": asset.token_symbol,
                            "currentMultiplier": str(asset.current_multiplier),
                        },
                        "reference": {
                            "source": reference.source,
                            "currency": reference.currency,
                            "rawBidUsdPerShare": str(reference.raw_bid_usd_per_share),
                            "rawAskUsdPerShare": str(reference.raw_ask_usd_per_share),
                            "tokenBidUsdPerToken": str(reference.token_bid_usd_per_token),
                            "tokenAskUsdPerToken": str(reference.token_ask_usd_per_token),
                            "tokenMidpointUsdPerToken": str(reference.token_midpoint_usd_per_token),
                            "generatedAt": reference.generated_at.isoformat(),
                            "isTradingHalt": reference.is_trading_halt,
                        },
                        "observations": observations,
                        "gapSemantics": (
                            "gap_bps=(quote_implied_token_price/reference_side_price-1)*10000; "
                            "BUY compares with official multiplier-adjusted ASK; SELL with BID; "
                            "positive=onchain price above reference, negative=below"
                        ),
                        "costSemantics": (
                            "R2 uses normalized route input/output amounts only; separately reported "
                            "feeCosts/gasCosts are preserved as evidence and are not added"
                        ),
                        "referenceStateAuthority": "R4_NOT_YET_APPLIED",
                    }
                except Exception as exc:
                    failures.append(
                        {"symbol": requested_symbol, "reason": f"{type(exc).__name__}:{exc}"}
                    )
                    continue
    return {"status": "BLOCKED", "chainId": CHAIN_ID, "attempts": failures}


def main() -> int:
    configured = os.getenv("RADAR_R2_SYMBOLS")
    symbols = (
        tuple(s.strip().upper() for s in configured.split(",") if s.strip())
        if configured
        else CANDIDATE_SYMBOLS
    )
    result = run(symbols)
    path = Path(
        os.getenv("RADAR_R2_EVIDENCE_PATH", "artifacts/radar_r2_finco_gap_evidence.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
