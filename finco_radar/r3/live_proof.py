"""Networked R3 proof: executable liquidity evidence on one canonical Stock Token.

One canonical asset, one coherent quote set: the same four R0 execution quote
objects feed the R2 directional GAP observations and the R3 liquidity snapshot.
Nothing is stitched from separate workflow artifacts.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, RegistryAssetStatus
from finco_radar.gap.contracts import GapComparisonPolicy, GapComputationError
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.liquidity.contracts import (
    LiquidityComparisonPolicy,
    LiquidityComputationError,
    LiquidityStatus,
)
from finco_radar.liquidity.engine import build_liquidity_snapshot
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

# C1-equivalent: explicit, caller-supplied policies. The engine has no hidden
# threshold — both windows are declared here, at the caller boundary.
R3_MAX_QUOTE_PAIR_SKEW_SECONDS = int(os.getenv("RADAR_R3_MAX_QUOTE_PAIR_SKEW_SECONDS", "120"))
R2_MAX_EVIDENCE_SKEW_SECONDS = int(os.getenv("RADAR_R3_R2_MAX_EVIDENCE_SKEW_SECONDS", "120"))
_R3_POLICY = LiquidityComparisonPolicy(max_quote_pair_skew_seconds=R3_MAX_QUOTE_PAIR_SKEW_SECONDS)
_R2_POLICY = GapComparisonPolicy(max_evidence_skew_seconds=R2_MAX_EVIDENCE_SKEW_SECONDS)


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


def _discover_settlement(client: httpx.Client) -> SettlementReference:
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
    return SettlementReference(
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


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _settlement_evidence_dict(settlement_ref: SettlementReference) -> dict[str, Any]:
    return {
        "chainId": settlement_ref.asset.chain_id,
        "contractAddress": settlement_ref.asset.contract_address,
        "symbol": settlement_ref.asset.symbol,
        "decimals": settlement_ref.asset.decimals,
        "usdPerAsset": (
            str(settlement_ref.usd_per_asset) if settlement_ref.usd_per_asset is not None else None
        ),
        "source": settlement_ref.source,
        "state": settlement_ref.state.value,
        "observedAt": (
            settlement_ref.observed_at.isoformat()
            if settlement_ref.observed_at is not None
            else None
        ),
        "canonicalIdentity": (
            f"{settlement_ref.asset.chain_id}:{settlement_ref.asset.contract_address}"
        ),
        "rawEvidence": dict(settlement_ref.raw_evidence),
    }


def _run(symbols: Iterable[str]) -> dict[str, Any]:
    produced_at = datetime.now(timezone.utc)
    git_head = _git_head()
    timeout = httpx.Timeout(25.0)
    failures: list[dict[str, str]] = []
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as client:
        settlement_reference = _discover_settlement(client)
        with httpx.Client(
            base_url=ROBINHOOD_API,
            timeout=timeout,
            headers={"accept": "application/json"},
        ) as robinhood_client:
            registry_adapter = RobinhoodAssetRegistryAdapter(client=robinhood_client)
            snapshot = registry_adapter.fetch_snapshot()

            with httpx.Client(
                base_url=LIFI_API,
                timeout=timeout,
                headers={"accept": "application/json"},
            ) as lifi_client:
                quote_adapter = LifiExecutionQuoteAdapter(client=lifi_client)
                for requested_symbol in symbols:
                    try:
                        # 1+2: fetch the canonical R1 registry and bind one exact deployment.
                        matches = snapshot.find_by_symbol(requested_symbol)
                        if len(matches) != 1:
                            raise RuntimeError(f"symbol discovery returned {len(matches)} matches")
                        asset = matches[0]
                        if asset.status is not RegistryAssetStatus.ACTIVE:
                            raise RuntimeError("canonical asset is not ACTIVE")
                        key: AssetKey | None = asset.deployment_for_chain(CHAIN_ID)
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

                        # 3+4: one coherent set of four fresh R0 execution quotes.
                        quote_map: dict[tuple[QuoteSide, Decimal], Any] = {}
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
                                        "R3_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                                        if side is QuoteSide.SELL
                                        else None
                                    ),
                                )
                                quote_map[(side, notional)] = quote_adapter.quote(request)

                        for (side, notional), quote in quote_map.items():
                            if quote.status is not QuoteStatus.QUOTE_OK:
                                raise LiquidityComputationError(
                                    f"{side.value}-{notional} quote status {quote.status.value}",
                                    (
                                        LiquidityStatus.INSUFFICIENT_LIQUIDITY
                                        if quote.status is QuoteStatus.INSUFFICIENT_LIQUIDITY
                                        else LiquidityStatus.QUOTE_UNAVAILABLE
                                    ),
                                )

                        # 5+7: R2 directional GAP observations from the SAME quote objects,
                        # under an explicit R2 comparison policy.
                        observations = {
                            slot: compute_directional_gap(
                                reference,
                                quote,
                                policy=_R2_POLICY,
                            )
                            for slot, quote in quote_map.items()
                        }

                        # 6+8: R3 snapshot from the SAME quotes + observations, under an
                        # explicit R3 quote-pair coherence policy.
                        liquidity_snapshot = build_liquidity_snapshot(
                            asset=asset,
                            asset_key=key,
                            quotes=list(quote_map.values()),
                            gap_observations=list(observations.values()),
                            policy=_R3_POLICY,
                            git_head=git_head,
                            produced_at=produced_at,
                        )

                        # 9: one reconstructible JSON artifact (flat, gate-friendly).
                        evidence = liquidity_snapshot.to_evidence_dict()
                        typed_status = evidence.pop("status")
                        return {
                            "status": "PASS",
                            "typedStatus": typed_status,
                            "gitHead": git_head,
                            "producedAt": produced_at.isoformat(),
                            "authority": (
                                "R3 executable liquidity evidence only: no score, no "
                                "classification, no trading signal, no reference-state "
                                "authority."
                            ),
                            "chainId": CHAIN_ID,
                            "settlementConversionEvidence": _settlement_evidence_dict(
                                settlement_reference
                            ),
                            **evidence,
                            "candidateAttempts": {
                                "selectedSymbol": asset.token_symbol,
                                "skippedCandidates": list(failures),
                                "skippedCandidateCount": len(failures),
                                "semantics": (
                                    "Audit-only. Candidates evaluated and rejected before the "
                                    "selected symbol succeeded. These did not contribute any "
                                    "observation; the selected candidate independently provided "
                                    "all four BUY/SELL observations from one coherent quote set."
                                ),
                            },
                        }
                    except LiquidityComputationError as exc:
                        failures.append(
                            {
                                "symbol": requested_symbol,
                                "status": exc.status.value,
                                "detail": str(exc),
                            }
                        )
                    except GapComputationError as exc:
                        failures.append(
                            {
                                "symbol": requested_symbol,
                                "status": exc.status.value,
                                "detail": str(exc),
                            }
                        )
                    except Exception as exc:
                        failures.append(
                            {
                                "symbol": requested_symbol,
                                "status": "INFRASTRUCTURE_ERROR",
                                "detail": f"{type(exc).__name__}:{exc}",
                            }
                        )
    return {
        "status": "BLOCKED",
        "typedStatus": failures[0]["status"] if failures else None,
        "chainId": CHAIN_ID,
        "gitHead": git_head,
        "producedAt": produced_at.isoformat(),
        "timingPolicy": {
            "maxQuotePairSkewSeconds": R3_MAX_QUOTE_PAIR_SKEW_SECONDS,
            "r2MaxEvidenceSkewSeconds": R2_MAX_EVIDENCE_SKEW_SECONDS,
        },
        "attempts": failures,
    }


def run(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> dict[str, Any]:
    try:
        return _run(symbols)
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "reason": f"INFRASTRUCTURE:{type(exc).__name__}:{exc}",
        }


def main() -> int:
    configured = os.getenv("RADAR_R3_SYMBOLS")
    symbols = (
        tuple(s.strip().upper() for s in configured.split(",") if s.strip())
        if configured
        else CANDIDATE_SYMBOLS
    )
    result = run(symbols)
    path = Path(
        os.getenv("RADAR_R3_EVIDENCE_PATH", "artifacts/radar_r3_finco_liquidity.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
