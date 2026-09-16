"""Pure R6 presenter: copies typed R3–R5 authority into terminal contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Mapping

from finco_radar.history.contracts import HistoryEntry, HistoryError
from finco_radar.history.engine import build_history_entry, compare_signal_snapshots, validate_history_series
from finco_radar.liquidity.contracts import LiquiditySnapshot
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.reference_state.contracts import ReferenceStateSnapshot
from finco_radar.signals.contracts import SignalSnapshot
from .contracts import (
    AssetHeader, DisplayValue, HistoryPanel, LiquidityPanel, MarketObservation,
    ReferencePanel, SideSizePanel, SignalPanel, TerminalError, TerminalSnapshot,
    TerminalStatus,
)


def _finite(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise TerminalError(f"{name} must be finite", TerminalStatus.TERMINAL_INPUT_INVALID)
    return value


def format_bps(value: Decimal) -> DisplayValue:
    value = _finite(value, "bps")
    return DisplayValue(str(value), f"{value:.2f} bps")


def format_usd_price(value: Decimal) -> DisplayValue:
    value = _finite(value, "USD price")
    return DisplayValue(str(value), f"${value:,.4f}")


def format_decimal(value: Decimal) -> DisplayValue:
    value = _finite(value, "decimal")
    return DisplayValue(str(value), f"{value:,.4f}")


def format_duration(value: Decimal) -> DisplayValue:
    value = _finite(value, "duration")
    return DisplayValue(str(value), f"{value:.0f}s")


def format_address(value: str) -> str:
    return value if len(value) <= 18 else f"{value[:10]}…{value[-8:]}"


def _assert_identity(r3: LiquiditySnapshot, r4: ReferenceStateSnapshot,
                     r5: SignalSnapshot) -> None:
    triples = {(r3.asset_uid, r3.canonical_key, r3.symbol),
               (r4.asset_uid, r4.canonical_key, r4.symbol),
               (r5.asset_uid, r5.canonical_key, r5.symbol)}
    if len(triples) != 1:
        raise TerminalError("R3/R4/R5 identity mismatch", TerminalStatus.TERMINAL_IDENTITY_MISMATCH)
    if r5.upstream_r3_evidence != r3.to_evidence_dict() or r5.upstream_r4_evidence != r4.to_evidence_dict():
        raise TerminalError("R5 upstream evidence does not bind supplied R3/R4 snapshots",
                            TerminalStatus.TERMINAL_EVIDENCE_INVALID)


def _observation(side, notional: str, obs) -> MarketObservation:
    return MarketObservation(
        side=side, notional_usd=notional,
        execution_price=format_usd_price(obs.execution_price_usd_per_token),
        reference_price=format_usd_price(obs.reference_price_usd_per_token),
        gap_bps=format_bps(obs.gap_bps), direction="",
        quote_timestamp=obs.quoted_at.isoformat(),
        reference_timestamp=obs.reference_generated_at.isoformat(),
    )


def _terminal_digest(snapshot: TerminalSnapshot) -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("terminalSnapshotDigest", None)
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reconstruct_terminal_digest(snapshot: TerminalSnapshot) -> str:
    return _terminal_digest(snapshot)


def build_terminal_snapshot(*, token_name: str, r3: LiquiditySnapshot,
                            r4: ReferenceStateSnapshot, r5: SignalSnapshot,
                            source_signal_snapshot_digest: str,
                            generated_at: datetime, git_head: str,
                            previous_history: tuple[HistoryEntry, ...] = (),
                            candidate_audit: Iterable[Mapping[str, str]] = ()) -> TerminalSnapshot:
    if generated_at.tzinfo is None:
        raise TerminalError("generated_at must be timezone-aware", TerminalStatus.TERMINAL_INPUT_INVALID)
    _assert_identity(r3, r4, r5)
    current_entry = build_history_entry(r5)
    if source_signal_snapshot_digest != current_entry.snapshot_digest:
        raise TerminalError("R5 source digest does not reconstruct", TerminalStatus.TERMINAL_EVIDENCE_INVALID)
    try:
        validate_history_series((*previous_history, current_entry))
    except HistoryError as exc:
        raise TerminalError(str(exc), TerminalStatus.TERMINAL_HISTORY_INVALID) from exc

    buy, sell = r5.buy_assessment, r5.sell_assessment
    observations = (
        replace(_observation("BUY", "100", r3.buy.small_gap_observation), direction=buy.small_gap_direction.value),
        replace(_observation("BUY", "1000", r3.buy.large_gap_observation), direction=buy.large_gap_direction.value),
        replace(_observation("SELL", "100", r3.sell.small_gap_observation), direction=sell.small_gap_direction.value),
        replace(_observation("SELL", "1000", r3.sell.large_gap_observation), direction=sell.large_gap_direction.value),
    )
    reference = ReferencePanel(
        official_bid=format_usd_price(r4.raw_bid), official_ask=format_usd_price(r4.raw_ask),
        current_multiplier=format_decimal(r4.current_multiplier),
        token_equivalent_bid=format_usd_price(r3.sell.small_gap_observation.reference_price_usd_per_token),
        token_equivalent_ask=format_usd_price(r3.buy.small_gap_observation.reference_price_usd_per_token),
        generated_at=r4.reference_generated_at.isoformat(), age_seconds=format_duration(r4.reference_age_seconds),
        asset_lifecycle=r4.asset_lifecycle_state.value, halt_state=r4.halt_state.value,
        freshness_state=r4.freshness_state.value, market_session_state=r4.market_session_state.value,
        corporate_action_state=r4.corporate_action_state.value, multiplier_state=r4.multiplier_state.value,
        reference_usable=r4.reference_usable,
        blocking_reasons=tuple(x.value for x in r4.blocking_reasons),
        session_label=("Session authority unresolved" if r4.market_session_state.value == "UNRESOLVED"
                       else r4.market_session_state.value.replace("_", " ").title()),
    )
    sizes = tuple(SideSizePanel(
        side=a.side.value, size_state=a.size_persistence_state.value,
        small_gap_bps=format_bps(a.small_gap_bps), large_gap_bps=format_bps(a.large_gap_bps),
        directional_gap_delta_bps=format_bps(a.directional_gap_delta_bps),
        size_impact_bps=format_bps(a.r0_size_impact_bps), adverse_size_impact=a.adverse_size_impact,
    ) for a in (buy, sell))
    cost_disclosure = (
        "Provider cost inclusion is unresolved. GAP and spread are reference/execution "
        "observations, not source-proven net-profit economics."
        if r5.net_economics_authority == "COST_INCLUSION_UNRESOLVED" else
        "Upstream cost-treatment authority is applied as recorded."
    )
    liquidity = LiquidityPanel(
        spread_small_bps=format_bps(r3.spread_small.execution_spread_bps),
        spread_large_bps=format_bps(r3.spread_large.execution_spread_bps),
        spread_delta_bps=format_bps(r3.spread_delta_bps),
        spread_small_state=r5.spread_small_state.value,
        spread_large_state=r5.spread_large_state.value,
        buy_size_impact_bps=format_bps(r3.buy.r0_size_impact_bps),
        sell_size_impact_bps=format_bps(r3.sell.r0_size_impact_bps),
        buy_route_changed=r3.buy.route_changed, sell_route_changed=r3.sell.route_changed,
        buy_small_route=r3.buy.small_route_signature.canonical_form(),
        buy_large_route=r3.buy.large_route_signature.canonical_form(),
        sell_small_route=r3.sell.small_route_signature.canonical_form(),
        sell_large_route=r3.sell.large_route_signature.canonical_form(),
        cost_authority=r5.net_economics_authority, cost_disclosure=cost_disclosure,
    )
    assessment_by_side = {a.side: a for a in (buy, sell)}
    events = tuple({**event.to_evidence_dict(),
                    "smallGapBps": str(assessment_by_side[event.side].small_gap_bps),
                    "largeGapBps": str(assessment_by_side[event.side].large_gap_bps),
                    "sizeImpactBps": str(assessment_by_side[event.side].r0_size_impact_bps),
                    "routeChanged": assessment_by_side[event.side].route_changed}
                   for event in r5.signal_events)
    display_state = ("SIGNALS SUPPRESSED" if not r5.signals_active else
                     ("ACTIVE SIGNALS" if events else "NO MATERIAL SIGNAL"))
    signal = SignalPanel(r5.signals_active, r5.authority_state.value,
                         tuple(x.value for x in r5.suppression_reasons), events, display_state)
    if previous_history:
        changes = tuple(x.to_evidence_dict() for x in
                        compare_signal_snapshots(previous_history[-1].signal_snapshot, r5))
        history = HistoryPanel(True, "Changes from previous comparable observation", changes,
                               current_entry.snapshot_digest)
    else:
        history = HistoryPanel(False, "No previous comparable observation available", (),
                               current_entry.snapshot_digest)
    snapshot = TerminalSnapshot(
        status=TerminalStatus.TERMINAL_OK, generated_at=generated_at,
        asset=AssetHeader(r5.symbol, token_name, r5.asset_uid, r5.canonical_key.chain_id,
                          r5.canonical_key.contract_address, r5.canonical_key.canonical_id,
                          hashlib.sha256(r5.canonical_key.canonical_id.encode()).hexdigest()[:16]),
        reference_panel=reference, market_panel=observations, size_panel=sizes,
        liquidity_panel=liquidity, signal_panel=signal, history_panel=history,
        candidate_audit=tuple(dict(x) for x in candidate_audit),
        source_signal_snapshot_digest=source_signal_snapshot_digest,
        terminal_snapshot_digest="", git_head=git_head,
    )
    return replace(snapshot, terminal_snapshot_digest=_terminal_digest(snapshot))
