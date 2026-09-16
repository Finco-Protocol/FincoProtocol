"""In-process live R1→R6 composition; no CLI artifact stitching."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import RegistryAssetStatus
from finco_radar.gap.contracts import GapComparisonPolicy
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
from finco_radar.r5.live_proof import (
    R2_SKEW, R3_SKEW, R4_CLOCK_SKEW, R4_REFERENCE_AGE, R4_SESSION_AGE, R5_POLICY,
)
from finco_radar.reference_state.adapters.robinhood import RobinhoodCorporateActionAdapter
from finco_radar.reference_state.contracts import MarketSessionEvidence, MarketSessionState, ReferenceStatePolicy
from finco_radar.reference_state.engine import build_reference_state_snapshot, match_corporate_actions
from finco_radar.signals.engine import build_signal_snapshot
from .contracts import TerminalError, TerminalSnapshot, TerminalStatus
from .presenter import build_terminal_snapshot


def build_live_terminal_snapshot(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> TerminalSnapshot:
    git_head, failures = _git_head(), []
    timeout = httpx.Timeout(25.0)
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as common:
        settlement = _discover_settlement(common)
        with httpx.Client(base_url=ROBINHOOD_API, timeout=timeout,
                          headers={"accept": "application/json"}) as rh, \
             httpx.Client(base_url=LIFI_API, timeout=timeout,
                          headers={"accept": "application/json"}) as lifi, \
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
                    quotes = []
                    for side in (QuoteSide.BUY, QuoteSide.SELL):
                        for notional in NOTIONALS:
                            quote = quote_adapter.quote(QuoteRequest(
                                token=token, settlement=settlement, side=side,
                                requested_notional_usd=notional, taker_address=TAKER,
                                token_sizing_reference_usd=(reference.token_midpoint_usd_per_token
                                                            if side is QuoteSide.SELL else None),
                                token_sizing_reference_source=("R6_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                                                               if side is QuoteSide.SELL else None),
                            ))
                            if quote.status is not QuoteStatus.QUOTE_OK:
                                raise RuntimeError(f"{side.value}-{notional} quote status {quote.status.value}")
                            quotes.append(quote)
                    observations = [compute_directional_gap(
                        reference, quote,
                        policy=GapComparisonPolicy(max_evidence_skew_seconds=R2_SKEW),
                    ) for quote in quotes]
                    produced_at = datetime.now(timezone.utc)
                    r3 = build_liquidity_snapshot(
                        asset=asset, asset_key=key, quotes=quotes, gap_observations=observations,
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
                        as_of=produced_at, registry_observed_at=registry_snapshot.observed_at,
                        corporate_actions_observed_at=ca_observed_at,
                    )
                    r5 = build_signal_snapshot(r3=r3, r4=r4, policy=R5_POLICY)
                    source_digest = build_history_entry(r5).snapshot_digest
                    audit = (*failures, {"symbol": asset.token_symbol, "status": "SELECTED",
                                        "detail": "complete atomic R1-R6 chain"})
                    return build_terminal_snapshot(
                        token_name=asset.token_name, r3=r3, r4=r4, r5=r5,
                        source_signal_snapshot_digest=source_digest,
                        generated_at=datetime.now(timezone.utc), git_head=git_head,
                        candidate_audit=audit,
                    )
                except Exception as exc:
                    status = getattr(getattr(exc, "status", None), "value", "INFRASTRUCTURE_ERROR")
                    failures.append({"symbol": requested_symbol, "status": status,
                                     "detail": f"{type(exc).__name__}:{exc}"})
    detail = "; ".join(f"{x['symbol']}={x['status']}" for x in failures)
    raise TerminalError(f"no atomic live candidate succeeded: {detail}",
                        TerminalStatus.TERMINAL_INPUT_INVALID)
