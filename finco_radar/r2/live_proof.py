"""Networked R2 proof: directional quote/reference gaps on canonical Stock Tokens."""
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
from finco_radar.assets.contracts import RegistryAssetStatus
from finco_radar.gap.contracts import GapComputationError, GapComparisonPolicy
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
from finco_radar.quotes.normalization import quote_size_impact_bps

CHAIN_ID = 4663
ROBINHOOD_API = "https://api.robinhood.com/rhj"
LIFI_API = "https://li.quest/v1"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
USDG_ADDRESS = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TAKER = "0x1111111111111111111111111111111111111111"
CANDIDATE_SYMBOLS = ("AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL")
NOTIONALS = (Decimal("100"), Decimal("1000"))

# C1: Explicit, caller-supplied comparison-time coherence policy.
# R4 is not yet applied; this is the only temporal gate R2 owns.
MAX_EVIDENCE_SKEW_SECONDS = int(os.getenv("RADAR_R2_MAX_SKEW_SECONDS", "120"))
_POLICY = GapComparisonPolicy(max_evidence_skew_seconds=MAX_EVIDENCE_SKEW_SECONDS)


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


def _route_tools(quote: Any) -> list[str]:
    if quote.evidence is None:
        return []
    tools = [leg.tool for leg in quote.evidence.route if leg.tool]
    if tools:
        return tools
    tool = quote.evidence.response_fields.get("tool")
    return [str(tool)] if tool else []


def _settlement_evidence_dict(settlement_ref: SettlementReference) -> dict[str, Any]:
    """C2: Full settlement conversion authority, reconstructible without other artifacts."""
    return {
        "chainId": settlement_ref.asset.chain_id,
        "contractAddress": settlement_ref.asset.contract_address,
        "symbol": settlement_ref.asset.symbol,
        "decimals": settlement_ref.asset.decimals,
        "usdPerAsset": str(settlement_ref.usd_per_asset) if settlement_ref.usd_per_asset is not None else None,
        "source": settlement_ref.source,
        "state": settlement_ref.state.value,
        "observedAt": settlement_ref.observed_at.isoformat() if settlement_ref.observed_at is not None else None,
        "canonicalIdentity": (
            f"{settlement_ref.asset.chain_id}:{settlement_ref.asset.contract_address}"
        ),
        "rawEvidence": dict(settlement_ref.raw_evidence),
    }


def _observation_dict(
    observation: Any,
    quote: Any,
    settlement_ref: SettlementReference,
) -> dict[str, Any]:
    return {
        "side": observation.side.value,
        "requestedNotionalUsd": str(observation.requested_notional_usd),
        "tokenAmount": str(observation.token_amount),
        "settlementAmountUsd": str(observation.settlement_amount_usd),
        "executionPriceUsdPerToken": str(observation.execution_price_usd_per_token),
        # Primary directional GAP metrics (C3)
        "referenceSide": observation.reference_side.value,
        "referencePriceUsdPerToken": str(observation.reference_price_usd_per_token),
        "gapBps": str(observation.gap_bps),
        # Neutral midpoint comparison (C3 — secondary analytic)
        "gapToMidBps": str(observation.gap_to_mid_bps),
        "quoteSource": observation.quote_source,
        "quotedAt": observation.quoted_at.isoformat(),
        "referenceGeneratedAt": observation.reference_generated_at.isoformat(),
        "settlementObservedAt": (
            observation.settlement_observed_at.isoformat()
            if observation.settlement_observed_at is not None
            else None
        ),
        "referenceIsTradingHalt": observation.reference_is_trading_halt,
        "feeCostUsd": str(observation.fee_cost_usd) if observation.fee_cost_usd is not None else None,
        "gasCostUsd": str(observation.gas_cost_usd) if observation.gas_cost_usd is not None else None,
        "costScope": observation.cost_scope,
        "referenceStateAuthority": observation.reference_state_authority,
        "routeTools": _route_tools(quote),
        # C2: Full settlement conversion evidence
        "settlementEvidence": _settlement_evidence_dict(settlement_ref),
    }


def _compute_actual_skew(observations: list[dict[str, Any]]) -> Decimal | None:
    """C1: Compute max observed skew across all four observations."""
    try:
        max_skew = Decimal("0")
        for obs in observations:
            ref_ts = datetime.fromisoformat(obs["referenceGeneratedAt"])
            sett_ts = datetime.fromisoformat(obs["settlementObservedAt"])
            quote_ts = datetime.fromisoformat(obs["quotedAt"])
            timestamps = [ref_ts, sett_ts, quote_ts]
            skew = Decimal(str((max(timestamps) - min(timestamps)).total_seconds()))
            if skew > max_skew:
                max_skew = skew
        return max_skew
    except Exception:
        return None


def _midpoint_analytics(
    buy_obs_100: dict[str, Any],
    sell_obs_100: dict[str, Any],
    buy_obs_1000: dict[str, Any],
    sell_obs_1000: dict[str, Any],
    ref_mid: Decimal,
) -> dict[str, Any]:
    """C3: Neutral midpoint analytics when both sides are available."""
    p_buy_100 = Decimal(buy_obs_100["executionPriceUsdPerToken"])
    p_sell_100 = Decimal(sell_obs_100["executionPriceUsdPerToken"])
    p_buy_1000 = Decimal(buy_obs_1000["executionPriceUsdPerToken"])
    p_sell_1000 = Decimal(sell_obs_1000["executionPriceUsdPerToken"])

    p_exec_mid_100 = (p_buy_100 + p_sell_100) / Decimal("2")
    p_exec_mid_1000 = (p_buy_1000 + p_sell_1000) / Decimal("2")

    mid_gap_bps_100 = ((p_exec_mid_100 / ref_mid) - Decimal("1")) * Decimal("10000")
    mid_gap_bps_1000 = ((p_exec_mid_1000 / ref_mid) - Decimal("1")) * Decimal("10000")

    spread_bps_100 = ((p_buy_100 - p_sell_100) / p_exec_mid_100) * Decimal("10000")
    spread_bps_1000 = ((p_buy_1000 - p_sell_1000) / p_exec_mid_1000) * Decimal("10000")

    return {
        "refMidUsdPerToken": str(ref_mid),
        "usd100": {
            "executionMidUsdPerToken": str(p_exec_mid_100),
            "midGapBps": str(mid_gap_bps_100),
            "quoteSpreadBps": str(spread_bps_100),
        },
        "usd1000": {
            "executionMidUsdPerToken": str(p_exec_mid_1000),
            "midGapBps": str(mid_gap_bps_1000),
            "quoteSpreadBps": str(spread_bps_1000),
        },
        "semantics": (
            "Neutral midpoint analytics only; not the primary FINCO GAP metric. "
            "P_ref_mid = (token_bid + token_ask) / 2. "
            "Quote spread is not realized slippage. "
            "R3 owns generalized liquidity/all-in-cost scoring."
        ),
    }


BUY_DELTA_INTERPRETATION = (
    "positive = larger size is worse (on-chain purchase is more expensive relative to "
    "the multiplier-adjusted ASK); negative = larger size is better"
)

SELL_DELTA_INTERPRETATION = (
    "positive = larger size is better (on-chain sale is richer relative to the "
    "multiplier-adjusted BID); negative = larger size is worse"
)


def _size_comparison(
    buy_obs_100: dict[str, Any],
    sell_obs_100: dict[str, Any],
    buy_obs_1000: dict[str, Any],
    sell_obs_1000: dict[str, Any],
) -> dict[str, Any]:
    """C4/D1: Deterministic size comparison of directional GAP across notionals.

    D1: The delta formulas are unchanged, but a positive delta does NOT mean "worse"
    on both sides. BUY gap rises when the on-chain purchase price rises, which is
    worse for the buyer. SELL gap rises when the on-chain sale proceeds rise, which
    is better for the seller. The interpretation is therefore side-specific.
    """
    buy_gap_100 = Decimal(buy_obs_100["gapBps"])
    sell_gap_100 = Decimal(sell_obs_100["gapBps"])
    buy_gap_1000 = Decimal(buy_obs_1000["gapBps"])
    sell_gap_1000 = Decimal(sell_obs_1000["gapBps"])

    buy_directional_gap_delta_bps = buy_gap_1000 - buy_gap_100
    sell_directional_gap_delta_bps = sell_gap_1000 - sell_gap_100

    result: dict[str, Any] = {
        "smallNotionalUsd": "100",
        "largeNotionalUsd": "1000",
        "buyGapBpsAt100": str(buy_gap_100),
        "buyGapBpsAt1000": str(buy_gap_1000),
        "sellGapBpsAt100": str(sell_gap_100),
        "sellGapBpsAt1000": str(sell_gap_1000),
        # C4/D1: formulas unchanged; interpretation is side-specific.
        "buyDirectionalGapDeltaBps": str(buy_directional_gap_delta_bps),
        "buyDeltaInterpretation": BUY_DELTA_INTERPRETATION,
        "sellDirectionalGapDeltaBps": str(sell_directional_gap_delta_bps),
        "sellDeltaInterpretation": SELL_DELTA_INTERPRETATION,
        # D2-final: r0BuySizeImpactBps and r0SellSizeImpactBps are injected by _run()
        # using quote_size_impact_bps from the same quote objects that produced the
        # directional GAP observations. The authority statement below records the formula
        # provenance. R2 does not redefine or reinterpret the R0 metric.
        "r0SizeImpactAuthority": (
            "Formula authority: finco_radar.quotes.normalization.quote_size_impact_bps. "
            "R2 records the canonical R0 metric over the same $100/$1000 quote pair used for "
            "directional GAP observations, for evidence alignment only. "
            "R2 does not redefine or reinterpret this metric. "
            "R0 size impact (output/input rate delta) is distinct from directional GAP delta "
            "(execution price vs multiplier-adjusted reference side). "
            "Neither is realized slippage. R3 owns liquidity/all-in-cost interpretation."
        ),
        "semantics": (
            "buyDirectionalGapDeltaBps = $1000 BUY directional GAP - $100 BUY directional GAP; "
            "sellDirectionalGapDeltaBps = $1000 SELL directional GAP - $100 SELL directional GAP. "
            "Sign interpretation is side-specific and must not be generalized: "
            f"BUY {BUY_DELTA_INTERPRETATION}; SELL {SELL_DELTA_INTERPRETATION}. "
            "These deltas are the R2 directional-GAP size comparison only; they are not "
            "the R0 size-impact metric and are not liquidity or all-in-cost scores (R3)."
        ),
    }
    return result


def _run(symbols: Iterable[str]) -> dict[str, Any]:
    produced_at = datetime.now(timezone.utc)
    git_head = _git_head()
    timeout = httpx.Timeout(25.0)
    failures: list[dict[str, str]] = []
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as client:
        _, settlement_reference = _discover_settlement(client)
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

                        # Obtain all four observations: BUY×2 + SELL×2
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
                                        "R2_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                                        if side is QuoteSide.SELL
                                        else None
                                    ),
                                )
                                quote_map[(side, notional)] = quote_adapter.quote(request)

                        # Validate all quotes OK before computing any GAP
                        for (side, notional), q in quote_map.items():
                            if q.status is not QuoteStatus.QUOTE_OK:
                                raise RuntimeError(
                                    f"{side.value}-{notional} quote status {q.status.value}"
                                )

                        # Compute directional GAP with explicit coherence policy (C1)
                        obs_map: dict[tuple[QuoteSide, Decimal], dict[str, Any]] = {}
                        for (side, notional), q in quote_map.items():
                            observation = compute_directional_gap(
                                reference, q, policy=_POLICY
                            )
                            obs_map[(side, notional)] = _observation_dict(
                                observation, q, settlement_reference
                            )

                        buy_100 = obs_map[(QuoteSide.BUY, Decimal("100"))]
                        sell_100 = obs_map[(QuoteSide.SELL, Decimal("100"))]
                        buy_1000 = obs_map[(QuoteSide.BUY, Decimal("1000"))]
                        sell_1000 = obs_map[(QuoteSide.SELL, Decimal("1000"))]

                        observations = [buy_100, sell_100, buy_1000, sell_1000]

                        # C1: Compute actual evidence skew
                        actual_skew = _compute_actual_skew(observations)

                        # C3: Neutral midpoint analytics (secondary)
                        midpoint_analytics = _midpoint_analytics(
                            buy_100, sell_100, buy_1000, sell_1000,
                            reference.token_midpoint_usd_per_token,
                        )

                        # C4/D1: Deterministic size comparison
                        size_cmp = _size_comparison(buy_100, sell_100, buy_1000, sell_1000)

                        # D2-final: Record canonical R0 size-impact using the SAME quote objects
                        # used to produce the directional GAP observations above. Not recomputed
                        # from gap values — uses quote_size_impact_bps (output/input rate delta).
                        size_cmp["r0BuySizeImpactBps"] = str(quote_size_impact_bps(
                            quote_map[(QuoteSide.BUY, Decimal("100"))],
                            quote_map[(QuoteSide.BUY, Decimal("1000"))],
                        ))
                        size_cmp["r0SellSizeImpactBps"] = str(quote_size_impact_bps(
                            quote_map[(QuoteSide.SELL, Decimal("100"))],
                            quote_map[(QuoteSide.SELL, Decimal("1000"))],
                        ))

                        return {
                            "status": "PASS",
                            # C6: provenance
                            "gitHead": git_head,
                            "producedAt": produced_at.isoformat(),
                            "chainId": CHAIN_ID,
                            # C6: canonical R1 asset identity
                            "asset": {
                                "assetUid": asset.asset_uid,
                                "canonicalKey": key.canonical_id,
                                "symbol": asset.token_symbol,
                                "currentMultiplier": str(asset.current_multiplier),
                            },
                            # C6+C7: multiplier-adjusted reference with provenance
                            "reference": {
                                "source": reference.source,
                                "currency": reference.currency,
                                "generatedAt": reference.generated_at.isoformat(),
                                "isTradingHalt": reference.is_trading_halt,
                                # C7: raw equity prices (BID/ASK from official /prices endpoint)
                                "rawBidUsdPerShare": str(reference.raw_bid_usd_per_share),
                                "rawAskUsdPerShare": str(reference.raw_ask_usd_per_share),
                                # C7: token-equivalent prices (raw × currentMultiplier)
                                "tokenBidUsdPerToken": str(reference.token_bid_usd_per_token),
                                "tokenAskUsdPerToken": str(reference.token_ask_usd_per_token),
                                "tokenMidpointUsdPerToken": str(reference.token_midpoint_usd_per_token),
                                # C7: multiplier semantics formula
                                "currentMultiplier": str(reference.current_multiplier),
                                "multiplierFormula": reference.multiplier_formula,
                                "multiplierSemantics": (
                                    "currentMultiplier from official Robinhood asset registry "
                                    "maps on-chain token denomination to economic exposure per token unit. "
                                    "raw_equity_price × currentMultiplier = token_equivalent_price. "
                                    "Multiplier applied exactly once to BID and ASK separately."
                                ),
                            },
                            # C1: explicit coherence policy and observed skew
                            "coherencePolicy": {
                                "maxEvidenceSkewSeconds": MAX_EVIDENCE_SKEW_SECONDS,
                                "actualMaxSkewSeconds": str(actual_skew) if actual_skew is not None else None,
                                "authority": "R2_COMPARISON_TIME_COHERENCE_ONLY",
                                "r4Boundary": (
                                    "R4 not yet applied. R4 will own market-open/closed semantics, "
                                    "expected-static reference classification, stale/paused/halted/"
                                    "corporate-action state, and reference-state authorization."
                                ),
                            },
                            # C2: settlement conversion evidence (at artifact level)
                            "settlementConversionEvidence": _settlement_evidence_dict(settlement_reference),
                            # All four observations with embedded settlement evidence
                            "observations": observations,
                            # C3: neutral midpoint analytics (secondary — not the primary FINCO GAP metric)
                            "midpointAnalytics": midpoint_analytics,
                            # C4/D1: deterministic size comparison
                            "sizeComparison": size_cmp,
                            # D3: audit-only record of candidates skipped before this one.
                            # Acceptance is unchanged: the single candidate above still had
                            # to supply all four valid observations on its own. Observations
                            # are never stitched across candidates.
                            "candidateAttempts": {
                                "selectedSymbol": asset.token_symbol,
                                "skippedCandidates": list(failures),
                                "skippedCandidateCount": len(failures),
                                "semantics": (
                                    "Audit-only. Candidates evaluated and rejected before the "
                                    "selected symbol succeeded. These did not contribute any "
                                    "observation; the selected candidate independently provided "
                                    "all four BUY/SELL observations."
                                ),
                            },
                            "gapSemantics": (
                                "PRIMARY: gap_bps=(quote_implied_token_price/reference_side_price-1)*10000; "
                                "BUY compares with official multiplier-adjusted ASK; SELL with BID; "
                                "positive=onchain price above reference, negative=below. "
                                "SECONDARY: gapToMidBps uses P_ref_mid=(token_bid+token_ask)/2. "
                                "None of these are trading signals."
                            ),
                            "costSemantics": (
                                "R2 uses normalized route input/output amounts only; separately reported "
                                "feeCosts/gasCosts are preserved as evidence and are not added"
                            ),
                            "referenceStateAuthority": "R4_NOT_YET_APPLIED",
                        }
                    except GapComputationError as exc:
                        # D3: typed failure — preserve GapStatus for downstream consumers.
                        failures.append({
                            "symbol": requested_symbol,
                            "status": exc.status.value,
                            "detail": str(exc),
                        })
                    except Exception as exc:
                        # D3: non-GapComputationError — classify as infrastructure failure.
                        failures.append({
                            "symbol": requested_symbol,
                            "status": "INFRASTRUCTURE_ERROR",
                            "detail": f"{type(exc).__name__}:{exc}",
                        })
    return {
        "status": "BLOCKED",
        "chainId": CHAIN_ID,
        "gitHead": git_head,
        "producedAt": produced_at.isoformat(),
        "attempts": failures,
    }


def run(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> dict[str, Any]:
    try:
        return _run(symbols)
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "chainId": CHAIN_ID,
            "reason": f"INFRASTRUCTURE:{type(exc).__name__}:{exc}",
        }


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
