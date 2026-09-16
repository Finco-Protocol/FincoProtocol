"""Typed contracts for R5 descriptive signals; never recommendations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from finco_radar.assets.contracts import AssetKey
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.reference_state.contracts import ReferenceStateReason


class SignalStatus(str, Enum):
    SIGNALS_OK = "SIGNALS_OK"
    SIGNAL_IDENTITY_MISMATCH = "SIGNAL_IDENTITY_MISMATCH"
    R3_R4_LINEAGE_MISMATCH = "R3_R4_LINEAGE_MISMATCH"
    SIGNAL_EVIDENCE_TIME_MISMATCH = "SIGNAL_EVIDENCE_TIME_MISMATCH"
    SIGNAL_POLICY_INVALID = "SIGNAL_POLICY_INVALID"
    SIGNAL_INPUT_INVALID = "SIGNAL_INPUT_INVALID"
    NON_FINITE_SIGNAL_ECONOMICS = "NON_FINITE_SIGNAL_ECONOMICS"


class SignalComputationError(ValueError):
    def __init__(self, message: str, status: SignalStatus) -> None:
        super().__init__(message)
        self.status = status


class SignalAuthorityState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPPRESSED_REFERENCE_UNUSABLE = "SUPPRESSED_REFERENCE_UNUSABLE"


class GapDirection(str, Enum):
    PREMIUM = "PREMIUM"
    DISCOUNT = "DISCOUNT"
    WITHIN_THRESHOLD = "WITHIN_THRESHOLD"


class SizePersistenceState(str, Enum):
    NO_MATERIAL_DISLOCATION = "NO_MATERIAL_DISLOCATION"
    PERSISTS = "PERSISTS"
    DECAYS = "DECAYS"
    EMERGES_AT_SIZE = "EMERGES_AT_SIZE"
    REVERSES = "REVERSES"


class SpreadState(str, Enum):
    CROSSED = "CROSSED"
    WITHIN_POLICY = "WITHIN_POLICY"
    WIDE = "WIDE"


class SignalEventKind(str, Enum):
    REFERENCE_DISLOCATION = "REFERENCE_DISLOCATION"


@dataclass(frozen=True)
class SignalPolicy:
    min_abs_gap_bps: Decimal
    max_execution_spread_bps: Decimal
    max_adverse_size_impact_bps: Decimal
    max_input_skew_seconds: Decimal
    material_history_change_bps: Decimal

    def __post_init__(self) -> None:
        for name in (
            "min_abs_gap_bps", "max_execution_spread_bps",
            "max_adverse_size_impact_bps", "max_input_skew_seconds",
            "material_history_change_bps",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise SignalComputationError(
                    f"{name} must be a finite non-negative Decimal",
                    SignalStatus.SIGNAL_POLICY_INVALID,
                )
        if (self.min_abs_gap_bps == 0 or self.max_input_skew_seconds == 0
                or self.material_history_change_bps == 0):
            raise SignalComputationError(
                "min_abs_gap_bps, max_input_skew_seconds and material_history_change_bps must be positive",
                SignalStatus.SIGNAL_POLICY_INVALID,
            )

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "minAbsGapBps": str(self.min_abs_gap_bps),
            "maxExecutionSpreadBps": str(self.max_execution_spread_bps),
            "maxAdverseSizeImpactBps": str(self.max_adverse_size_impact_bps),
            "maxInputSkewSeconds": str(self.max_input_skew_seconds),
            "materialHistoryChangeBps": str(self.material_history_change_bps),
        }


@dataclass(frozen=True)
class SideAssessment:
    side: QuoteSide
    small_gap_bps: Decimal
    large_gap_bps: Decimal
    small_gap_direction: GapDirection
    large_gap_direction: GapDirection
    size_persistence_state: SizePersistenceState
    r0_size_impact_bps: Decimal
    directional_gap_delta_bps: Decimal
    adverse_size_impact: bool
    small_route_signature: str
    large_route_signature: str
    route_changed: bool

    @property
    def material(self) -> bool:
        return self.size_persistence_state is not SizePersistenceState.NO_MATERIAL_DISLOCATION

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "smallGapBps": str(self.small_gap_bps),
            "largeGapBps": str(self.large_gap_bps),
            "smallGapDirection": self.small_gap_direction.value,
            "largeGapDirection": self.large_gap_direction.value,
            "sizePersistenceState": self.size_persistence_state.value,
            "r0SizeImpactBps": str(self.r0_size_impact_bps),
            "directionalGapDeltaBps": str(self.directional_gap_delta_bps),
            "adverseSizeImpact": self.adverse_size_impact,
            "smallRouteSignature": self.small_route_signature,
            "largeRouteSignature": self.large_route_signature,
            "routeChanged": self.route_changed,
        }


@dataclass(frozen=True)
class SignalEvent:
    kind: SignalEventKind
    side: QuoteSide
    small_direction: GapDirection
    large_direction: GapDirection
    size_state: SizePersistenceState

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value, "side": self.side.value,
            "smallDirection": self.small_direction.value,
            "largeDirection": self.large_direction.value,
            "sizeState": self.size_state.value,
        }


@dataclass(frozen=True)
class SignalSnapshot:
    status: SignalStatus
    asset_uid: str
    canonical_key: AssetKey
    symbol: str
    observed_at: datetime
    signals_active: bool
    authority_state: SignalAuthorityState
    suppression_reasons: tuple[ReferenceStateReason, ...]
    buy_assessment: SideAssessment
    sell_assessment: SideAssessment
    spread_small_state: SpreadState
    spread_large_state: SpreadState
    signal_events: tuple[SignalEvent, ...]
    policy: SignalPolicy
    input_skew_seconds: Decimal
    net_economics_authority: str
    upstream_r3_evidence: dict[str, Any]
    upstream_r4_evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status is not SignalStatus.SIGNALS_OK:
            raise SignalComputationError("successful snapshot requires SIGNALS_OK", SignalStatus.SIGNAL_INPUT_INVALID)
        if self.observed_at.tzinfo is None:
            raise SignalComputationError("observed_at must be timezone-aware", SignalStatus.SIGNAL_EVIDENCE_TIME_MISMATCH)
        if not self.signals_active and self.signal_events:
            raise SignalComputationError("suppressed snapshot cannot contain events", SignalStatus.SIGNAL_INPUT_INVALID)

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "asset": {"assetUid": self.asset_uid, "canonicalKey": self.canonical_key.canonical_id,
                      "symbol": self.symbol, "chainId": self.canonical_key.chain_id,
                      "contractAddress": self.canonical_key.contract_address},
            "observedAt": self.observed_at.isoformat(),
            "signalsActive": self.signals_active,
            "signalAuthorityState": self.authority_state.value,
            "suppressionReasons": [r.value for r in self.suppression_reasons],
            "buyAssessment": self.buy_assessment.to_evidence_dict(),
            "sellAssessment": self.sell_assessment.to_evidence_dict(),
            "spreadSmallState": self.spread_small_state.value,
            "spreadLargeState": self.spread_large_state.value,
            "signalEvents": [e.to_evidence_dict() for e in self.signal_events],
            "policy": self.policy.to_evidence_dict(),
            "temporalEvidence": {"r3R4InputSkewSeconds": str(self.input_skew_seconds)},
            "netEconomicsAuthority": self.net_economics_authority,
            "upstreamEvidence": {"r3": self.upstream_r3_evidence, "r4": self.upstream_r4_evidence},
            "boundaries": {"referenceStateAuthority": "R4_APPLIED", "signalAuthority": "R5_APPLIED",
                           "historyAuthority": "R5_APPLIED", "terminalAuthority": "R6_NOT_YET_APPLIED"},
        }
