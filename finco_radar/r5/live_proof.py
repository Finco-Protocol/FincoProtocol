"""Networked in-process R0→R5 proof over one canonical candidate."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import RegistryAssetStatus
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.history.engine import build_history_entry
from finco_radar.liquidity.contracts import LiquidityComparisonPolicy
from finco_radar.liquidity.engine import build_liquidity_snapshot
from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import AssetRef, QuoteRequest, QuoteSide, QuoteStatus
from finco_radar.r3.live_proof import (
    CHAIN_ID, CANDIDATE_SYMBOLS, LIFI_API, NOTIONALS, ROBINHOOD_API, TAKER,
    _discover_settlement, _erc20_decimals, _git_head,
)
from finco_radar.reference_state.adapters.robinhood import RobinhoodCorporateActionAdapter
from finco_radar.reference_state.contracts import MarketSessionEvidence, MarketSessionState, ReferenceStatePolicy
from finco_radar.reference_state.engine import build_reference_state_snapshot, match_corporate_actions
from finco_radar.signals.contracts import SignalPolicy
from finco_radar.signals.engine import build_signal_snapshot


def _decimal_env(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


R5_POLICY = SignalPolicy(
    min_abs_gap_bps=_decimal_env("RADAR_R5_MIN_ABS_GAP_BPS", "50"),
    max_execution_spread_bps=_decimal_env("RADAR_R5_MAX_EXECUTION_SPREAD_BPS", "500"),
    max_adverse_size_impact_bps=_decimal_env("RADAR_R5_MAX_ADVERSE_SIZE_IMPACT_BPS", "100"),
    max_input_skew_seconds=_decimal_env("RADAR_R5_MAX_INPUT_SKEW_SECONDS", "120"),
    material_history_change_bps=_decimal_env("RADAR_R5_MATERIAL_HISTORY_CHANGE_BPS", "25"),
)
R2_SKEW = int(os.getenv("RADAR_R5_R2_MAX_EVIDENCE_SKEW_SECONDS", "120"))
R3_SKEW = int(os.getenv("RADAR_R5_R3_MAX_QUOTE_PAIR_SKEW_SECONDS", "120"))
R4_REFERENCE_AGE = int(os.getenv("RADAR_R5_R4_MAX_LIVE_REFERENCE_AGE_SECONDS", "120"))
R4_SESSION_AGE = int(os.getenv("RADAR_R5_R4_MAX_SESSION_EVIDENCE_AGE_SECONDS", "86400"))
R4_CLOCK_SKEW = int(os.getenv("RADAR_R5_R4_MAX_CLOCK_SKEW_SECONDS", "5"))


def _run(symbols: Iterable[str]) -> dict[str, Any]:
    from finco_radar.gap.contracts import GapComparisonPolicy

    git_head, failures = _git_head(), []
    timeout = httpx.Timeout(25.0)
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as common:
        settlement = _discover_settlement(common)
        with httpx.Client(base_url=ROBINHOOD_API, timeout=timeout, headers={"accept": "application/json"}) as rh, \
             httpx.Client(base_url=LIFI_API, timeout=timeout, headers={"accept": "application/json"}) as lifi, \
             RobinhoodCorporateActionAdapter(client=rh) as ca_adapter:
            registry = RobinhoodAssetRegistryAdapter(client=rh)
            registry_snapshot = registry.fetch_snapshot()
            ca_rows, ca_observed_at = ca_adapter.fetch_rows()
            quote_adapter = LifiExecutionQuoteAdapter(client=lifi)
            for requested_symbol in symbols:
                try:
                    matches = registry_snapshot.find_by_symbol(requested_symbol)
                    if len(matches) != 1:
                        raise RuntimeError(f"symbol discovery returned {len(matches)} matches")
                    asset = matches[0]
                    if asset.status is not RegistryAssetStatus.ACTIVE:
                        raise RuntimeError("canonical asset is not ACTIVE")
                    key = asset.deployment_for_chain(CHAIN_ID)
                    if key is None:
                        raise RuntimeError("canonical deployment unavailable")
                    binding, price_row = registry.fetch_bound_reference(registry_snapshot, key)
                    reference = build_bound_reference_price(asset, binding, price_row)
                    token = AssetRef(CHAIN_ID, key.contract_address, symbol=asset.token_symbol,
                                     decimals=_erc20_decimals(common, key.contract_address))
                    quote_map = {}
                    for side in (QuoteSide.BUY, QuoteSide.SELL):
                        for notional in NOTIONALS:
                            quote = quote_adapter.quote(QuoteRequest(
                                token=token, settlement=settlement, side=side,
                                requested_notional_usd=notional, taker_address=TAKER,
                                token_sizing_reference_usd=(reference.token_midpoint_usd_per_token if side is QuoteSide.SELL else None),
                                token_sizing_reference_source=("R5_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY" if side is QuoteSide.SELL else None),
                            ))
                            if quote.status is not QuoteStatus.QUOTE_OK:
                                raise RuntimeError(f"{side.value}-{notional} quote status {quote.status.value}")
                            quote_map[(side, notional)] = quote
                    observations = [compute_directional_gap(reference, q,
                        policy=GapComparisonPolicy(max_evidence_skew_seconds=R2_SKEW)) for q in quote_map.values()]
                    produced_at = datetime.now(timezone.utc)
                    r3 = build_liquidity_snapshot(
                        asset=asset, asset_key=key, quotes=list(quote_map.values()),
                        gap_observations=observations,
                        policy=LiquidityComparisonPolicy(max_quote_pair_skew_seconds=R3_SKEW),
                        git_head=git_head, produced_at=produced_at,
                    )
                    r4 = build_reference_state_snapshot(
                        asset=asset, reference=reference,
                        corporate_actions=match_corporate_actions(ca_rows, asset=asset, asset_key=key),
                        session_evidence=MarketSessionEvidence(
                            state=MarketSessionState.UNRESOLVED,
                            source="R4_MARKET_SESSION_AUTHORITY_REQUIRED",
                        ),
                        policy=ReferenceStatePolicy(
                            max_live_reference_age_seconds=R4_REFERENCE_AGE,
                            max_session_evidence_age_seconds=R4_SESSION_AGE,
                            max_clock_skew_seconds=R4_CLOCK_SKEW,
                        ),
                        as_of=produced_at,
                        registry_observed_at=registry_snapshot.observed_at,
                        corporate_actions_observed_at=ca_observed_at,
                    )
                    r5 = build_signal_snapshot(r3=r3, r4=r4, policy=R5_POLICY)
                    entry = build_history_entry(r5)
                    evidence = r5.to_evidence_dict()
                    return {
                        "schemaVersion": "radar-r5-signals-history-v1", "status": "PASS",
                        "typedStatus": r5.status.value, "gitHead": git_head,
                        **evidence,
                        "history": {"previousObservationAvailable": False,
                                    "currentEntry": entry.to_evidence_dict(), "changes": []},
                        "candidateAttempts": {"selectedSymbol": asset.token_symbol,
                            "skippedCandidates": failures, "skippedCandidateCount": len(failures)},
                    }
                except Exception as exc:
                    status = getattr(getattr(exc, "status", None), "value", "INFRASTRUCTURE_ERROR")
                    failures.append({"symbol": requested_symbol, "status": status,
                                     "detail": f"{type(exc).__name__}:{exc}"})
    return {"schemaVersion": "radar-r5-signals-history-v1", "status": "BLOCKED",
            "gitHead": git_head, "policy": R5_POLICY.to_evidence_dict(), "attempts": failures}


def run(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> dict[str, Any]:
    try:
        return _run(symbols)
    except Exception as exc:
        return {"schemaVersion": "radar-r5-signals-history-v1", "status": "BLOCKED",
                "reason": f"INFRASTRUCTURE:{type(exc).__name__}:{exc}"}


def main() -> int:
    configured = os.getenv("RADAR_R5_SYMBOLS")
    result = run(tuple(s.strip().upper() for s in configured.split(",") if s.strip()) if configured else CANDIDATE_SYMBOLS)
    path = Path(os.getenv("RADAR_R5_EVIDENCE_PATH", "artifacts/radar_r5_signals_history_evidence.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
