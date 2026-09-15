"""Networked R0 proof: real Robinhood Chain Stock Token quotes through LI.FI.

This module is intentionally not part of the deterministic pytest ring. It is run
by a dedicated GitHub Action and emits reconstructible JSON evidence.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import httpx

from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import (
    AssetRef,
    QuoteRequest,
    QuoteSide,
    QuoteStatus,
    SettlementReference,
    SettlementReferenceState,
)
from finco_radar.quotes.normalization import quote_size_impact_bps

CHAIN_ID = 4663
ROBINHOOD_API = "https://api.robinhood.com/rhj"
LIFI_API = "https://li.quest/v1"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_SYMBOLS = ("AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL")
TAKER = "0x1111111111111111111111111111111111111111"
USDG_ADDRESS = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"


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
    # Canonical identity is address-based. Token metadata is queried by the known
    # Robinhood Chain USDG contract address; ticker resolution is never used.
    token = _get_json(
        client,
        f"{LIFI_API}/token",
        params={"chain": CHAIN_ID, "token": USDG_ADDRESS},
    )
    address = str(token["address"]).lower()
    if address != USDG_ADDRESS:
        raise RuntimeError("settlement metadata returned a different contract address")
    decimals = _erc20_decimals(client, address)
    if str(token.get("symbol", "")).upper() != "USDG":
        raise RuntimeError("canonical settlement address returned unexpected symbol")
    provider_price = Decimal(str(token.get("priceUSD") or "0"))
    if provider_price <= 0:
        state = SettlementReferenceState.REFERENCE_UNAVAILABLE
        price = None
    else:
        state = SettlementReferenceState.REFERENCE_CURRENT
        price = provider_price
    asset = AssetRef(CHAIN_ID, address, symbol="USDG", decimals=decimals)
    reference = SettlementReference(
        asset=asset,
        state=state,
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


def _asset_map(client: httpx.Client) -> dict[str, dict[str, Any]]:
    payload = _get_json(client, f"{ROBINHOOD_API}/assets")
    result: dict[str, dict[str, Any]] = {}
    for asset in payload.get("assets", []):
        symbol = str(asset.get("tokenSymbol") or "").upper()
        deployment = next(
            (d for d in asset.get("deployments", []) if int(d.get("chainId", 0)) == CHAIN_ID),
            None,
        )
        if symbol and deployment:
            result[symbol] = {**asset, "deployment": deployment}
    return result


def _token_reference(client: httpx.Client, symbol: str, multiplier: Decimal) -> tuple[Decimal, dict[str, Any]]:
    payload = _get_json(client, f"{ROBINHOOD_API}/prices/{symbol}")
    quotes = payload.get("quotes") or []
    if not quotes:
        raise RuntimeError(f"no official reference quote for {symbol}")
    quote = quotes[0]
    if quote.get("isTradingHalt"):
        raise RuntimeError(f"official reference is halted for {symbol}")
    bid = Decimal(str(quote["bid"]))
    ask = Decimal(str(quote["ask"]))
    midpoint = ((bid + ask) / Decimal("2")) * multiplier
    if midpoint <= 0:
        raise RuntimeError(f"invalid official reference for {symbol}")
    return midpoint, {
        "bid": str(bid),
        "ask": str(ask),
        "currency": quote.get("currency"),
        "generatedAt": quote.get("generatedAt"),
        "isTradingHalt": quote.get("isTradingHalt"),
        "currentMultiplier": str(multiplier),
        "tokenMidpointUsd": str(midpoint),
    }


def _quote_dict(quote: Any) -> dict[str, Any]:
    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return {str(k): convert(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [convert(v) for v in value]
        return value

    return convert(asdict(quote))


def _attach_observed_block(client: httpx.Client, quote: Any) -> Any:
    if quote.evidence is None:
        return quote
    block_hex = _rpc(client, "eth_blockNumber", [])
    block = _rpc(client, "eth_getBlockByNumber", [block_hex, False])
    evidence = replace(
        quote.evidence,
        observed_block_number=int(block_hex, 16),
        observed_block_hash=block.get("hash"),
        block_binding="OBSERVED_IMMEDIATELY_AFTER_QUOTE_SOURCE_UNBOUND",
    )
    return replace(quote, evidence=evidence)


def run(symbols: Iterable[str] = DEFAULT_SYMBOLS) -> dict[str, Any]:
    timeout = httpx.Timeout(25.0)
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as client:
        _, settlement_reference = _discover_settlement(client)
        assets = _asset_map(client)
        failures: list[dict[str, str]] = []

        with httpx.Client(base_url=LIFI_API, timeout=timeout, headers={"accept": "application/json"}) as lifi_client:
            adapter = LifiExecutionQuoteAdapter(client=lifi_client)
            for symbol in symbols:
                asset_meta = assets.get(symbol.upper())
                if not asset_meta:
                    failures.append({"symbol": symbol, "reason": "asset_not_in_official_registry"})
                    continue
                address = str(asset_meta["deployment"]["contractAddress"]).lower()
                try:
                    decimals = _erc20_decimals(client, address)
                    multiplier = Decimal(str(asset_meta["currentMultiplier"]))
                    token_reference_usd, reference_evidence = _token_reference(client, symbol, multiplier)
                    token = AssetRef(CHAIN_ID, address, symbol=symbol, decimals=decimals)
                    quotes = []
                    for side in (QuoteSide.BUY, QuoteSide.SELL):
                        for notional in (Decimal("100"), Decimal("1000")):
                            request = QuoteRequest(
                                token=token,
                                settlement=settlement_reference,
                                side=side,
                                requested_notional_usd=notional,
                                taker_address=TAKER,
                                token_sizing_reference_usd=token_reference_usd if side is QuoteSide.SELL else None,
                                token_sizing_reference_source="ROBINHOOD_STOCK_TOKEN_REFERENCE_MID_SIZING_ONLY" if side is QuoteSide.SELL else None,
                            )
                            quote = _attach_observed_block(client, adapter.quote(request))
                            quotes.append(quote)
                    if not all(q.status is QuoteStatus.QUOTE_OK for q in quotes):
                        failures.append(
                            {
                                "symbol": symbol,
                                "reason": ";".join(f"{q.side.value}-{q.requested_notional_usd}:{q.status.value}" for q in quotes if q.status is not QuoteStatus.QUOTE_OK),
                            }
                        )
                        continue
                    buy_small, buy_large = quotes[0], quotes[1]
                    sell_small, sell_large = quotes[2], quotes[3]
                    return {
                        "status": "PASS",
                        "chainId": CHAIN_ID,
                        "symbol": symbol,
                        "token": {"address": address, "decimals": decimals},
                        "settlementReference": _quote_dict(settlement_reference),
                        "tokenSizingReference": reference_evidence,
                        "quotes": [_quote_dict(q) for q in quotes],
                        "sizeImpactBps": {
                            "BUY": str(quote_size_impact_bps(buy_small, buy_large)),
                            "SELL": str(quote_size_impact_bps(sell_small, sell_large)),
                        },
                        "proofSemantics": "size impact is quote deterioration, not realized slippage",
                    }
                except Exception as exc:
                    failures.append({"symbol": symbol, "reason": f"{type(exc).__name__}:{exc}"})
                    continue

    return {"status": "BLOCKED", "chainId": CHAIN_ID, "attempts": failures}


def main() -> int:
    configured = os.getenv("RADAR_R0_SYMBOLS")
    symbols = tuple(s.strip().upper() for s in configured.split(",") if s.strip()) if configured else DEFAULT_SYMBOLS
    result = run(symbols)
    path = Path(os.getenv("RADAR_R0_EVIDENCE_PATH", "artifacts/radar_r0_live_quote_evidence.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
