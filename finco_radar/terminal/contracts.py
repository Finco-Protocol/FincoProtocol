"""Immutable presentation contracts for FINCO Radar R6."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class TerminalStatus(str, Enum):
    TERMINAL_OK = "TERMINAL_OK"
    TERMINAL_INPUT_INVALID = "TERMINAL_INPUT_INVALID"
    TERMINAL_IDENTITY_MISMATCH = "TERMINAL_IDENTITY_MISMATCH"
    TERMINAL_EVIDENCE_INVALID = "TERMINAL_EVIDENCE_INVALID"
    TERMINAL_HISTORY_INVALID = "TERMINAL_HISTORY_INVALID"


class TerminalError(ValueError):
    def __init__(self, message: str, status: TerminalStatus) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class DisplayValue:
    raw: str
    display: str

    def to_dict(self) -> dict[str, str]:
        return {"raw": self.raw, "display": self.display}


@dataclass(frozen=True)
class AssetHeader:
    symbol: str
    token_name: str
    asset_uid: str
    chain_id: int
    contract_address: str
    canonical_key: str
    dom_key: str

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "tokenName": self.token_name,
                "assetUid": self.asset_uid, "chainId": self.chain_id,
                "contractAddress": self.contract_address,
                "canonicalKey": self.canonical_key, "domKey": self.dom_key}


@dataclass(frozen=True)
class ReferencePanel:
    official_bid: DisplayValue
    official_ask: DisplayValue
    current_multiplier: DisplayValue
    token_equivalent_bid: DisplayValue
    token_equivalent_ask: DisplayValue
    generated_at: str
    age_seconds: DisplayValue
    asset_lifecycle: str
    halt_state: str
    freshness_state: str
    market_session_state: str
    corporate_action_state: str
    multiplier_state: str
    reference_usable: bool
    blocking_reasons: tuple[str, ...]
    session_label: str

    def to_dict(self) -> dict[str, Any]:
        return {"officialReferenceBid": self.official_bid.to_dict(),
                "officialReferenceAsk": self.official_ask.to_dict(),
                "currentMultiplier": self.current_multiplier.to_dict(),
                "tokenEquivalentBid": self.token_equivalent_bid.to_dict(),
                "tokenEquivalentAsk": self.token_equivalent_ask.to_dict(),
                "referenceGeneratedAt": self.generated_at,
                "referenceAgeSeconds": self.age_seconds.to_dict(),
                "assetLifecycle": self.asset_lifecycle, "haltState": self.halt_state,
                "freshnessState": self.freshness_state,
                "marketSessionState": self.market_session_state,
                "corporateActionState": self.corporate_action_state,
                "multiplierState": self.multiplier_state,
                "referenceUsable": self.reference_usable,
                "blockingReasons": list(self.blocking_reasons),
                "sessionLabel": self.session_label}


@dataclass(frozen=True)
class MarketObservation:
    side: str
    notional_usd: str
    execution_price: DisplayValue
    reference_price: DisplayValue
    gap_bps: DisplayValue
    direction: str
    quote_timestamp: str
    reference_timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {"side": self.side, "notionalUsd": self.notional_usd,
                "executionPrice": self.execution_price.to_dict(),
                "officialReferencePrice": self.reference_price.to_dict(),
                "gapBps": self.gap_bps.to_dict(), "direction": self.direction,
                "quoteTimestamp": self.quote_timestamp,
                "referenceTimestamp": self.reference_timestamp}


@dataclass(frozen=True)
class SideSizePanel:
    side: str
    size_state: str
    small_gap_bps: DisplayValue
    large_gap_bps: DisplayValue
    directional_gap_delta_bps: DisplayValue
    size_impact_bps: DisplayValue
    adverse_size_impact: bool

    def to_dict(self) -> dict[str, Any]:
        return {"side": self.side, "sizePersistenceState": self.size_state,
                "smallGapBps": self.small_gap_bps.to_dict(),
                "largeGapBps": self.large_gap_bps.to_dict(),
                "directionalGapDeltaBps": self.directional_gap_delta_bps.to_dict(),
                "sizeImpactBps": self.size_impact_bps.to_dict(),
                "adverseSizeImpact": self.adverse_size_impact}


@dataclass(frozen=True)
class LiquidityPanel:
    spread_small_bps: DisplayValue
    spread_large_bps: DisplayValue
    spread_delta_bps: DisplayValue
    spread_small_state: str
    spread_large_state: str
    buy_size_impact_bps: DisplayValue
    sell_size_impact_bps: DisplayValue
    buy_route_changed: bool
    sell_route_changed: bool
    buy_small_route: str
    buy_large_route: str
    sell_small_route: str
    sell_large_route: str
    cost_authority: str
    cost_disclosure: str

    def to_dict(self) -> dict[str, Any]:
        return {"executionSpread100Bps": self.spread_small_bps.to_dict(),
                "executionSpread1000Bps": self.spread_large_bps.to_dict(),
                "spreadDeltaBps": self.spread_delta_bps.to_dict(),
                "spreadSmallState": self.spread_small_state,
                "spreadLargeState": self.spread_large_state,
                "buySizeImpactBps": self.buy_size_impact_bps.to_dict(),
                "sellSizeImpactBps": self.sell_size_impact_bps.to_dict(),
                "buyRouteChanged": self.buy_route_changed,
                "sellRouteChanged": self.sell_route_changed,
                "buySmallRoute": self.buy_small_route, "buyLargeRoute": self.buy_large_route,
                "sellSmallRoute": self.sell_small_route, "sellLargeRoute": self.sell_large_route,
                "costTreatmentAuthority": self.cost_authority,
                "costDisclosure": self.cost_disclosure}


@dataclass(frozen=True)
class SignalPanel:
    signals_active: bool
    authority_state: str
    suppression_reasons: tuple[str, ...]
    events: tuple[dict[str, Any], ...]
    display_state: str

    def to_dict(self) -> dict[str, Any]:
        return {"signalsActive": self.signals_active, "authorityState": self.authority_state,
                "suppressionReasons": list(self.suppression_reasons),
                "signalEvents": [dict(e) for e in self.events], "displayState": self.display_state}


@dataclass(frozen=True)
class HistoryPanel:
    previous_observation_available: bool
    message: str
    changes: tuple[dict[str, Any], ...]
    current_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"previousObservationAvailable": self.previous_observation_available,
                "message": self.message, "changes": [dict(c) for c in self.changes],
                "currentSnapshotDigest": self.current_digest}


@dataclass(frozen=True)
class TerminalSnapshot:
    status: TerminalStatus
    generated_at: datetime
    asset: AssetHeader
    reference_panel: ReferencePanel
    market_panel: tuple[MarketObservation, ...]
    size_panel: tuple[SideSizePanel, ...]
    liquidity_panel: LiquidityPanel
    signal_panel: SignalPanel
    history_panel: HistoryPanel
    candidate_audit: tuple[dict[str, str], ...]
    source_signal_snapshot_digest: str
    terminal_snapshot_digest: str
    git_head: str

    def to_evidence_dict(self) -> dict[str, Any]:
        return {"schemaVersion": "radar-r6-terminal-v1", "status": self.status.value,
                "generatedAt": self.generated_at.isoformat(), "asset": self.asset.to_dict(),
                "referencePanel": self.reference_panel.to_dict(),
                "marketPanel": [x.to_dict() for x in self.market_panel],
                "sizePanel": [x.to_dict() for x in self.size_panel],
                "liquidityPanel": self.liquidity_panel.to_dict(),
                "signalPanel": self.signal_panel.to_dict(),
                "historyPanel": self.history_panel.to_dict(),
                "boundaries": {"referenceStateAuthority": "R4_APPLIED",
                    "signalAuthority": "R5_APPLIED", "historyAuthority": "R5_APPLIED",
                    "terminalAuthority": "R6_APPLIED"},
                "sourceSignalSnapshotDigest": self.source_signal_snapshot_digest,
                "terminalSnapshotDigest": self.terminal_snapshot_digest,
                "candidateAudit": [dict(x) for x in self.candidate_audit],
                "gitHead": self.git_head,
                "executionAuthority": "READ_ONLY_NO_WALLET_NO_TRADE"}
