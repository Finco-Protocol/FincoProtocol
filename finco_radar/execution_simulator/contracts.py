"""Typed contracts for FINCO Radar R8 — EXECUTION SIMULATOR.

R8 converts R7 observed theoretical dislocation into the economics actually
supported by executable quote evidence: exact USD gross execution edge per
side/notional, source-proven incremental costs, settlement adjustments and a
typed net-edge completeness state.

R8 is a READ-ONLY pre-trade SIMULATION. It never places or prepares a
transaction, never emits recommendations, and never claims realized profit.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from finco_radar.assets.contracts import AssetKey
from finco_radar.cross_market.contracts import deep_freeze
from finco_radar.liquidity.contracts import CostTreatmentState
from finco_radar.quotes.contracts import QuoteSide

SCHEMA_VERSION = "radar-r8-execution-simulator-v1"
PHASE = "R8"

#: Pure arithmetic-reconstruction tolerance for the mandatory R2/R8 handshake.
#: Division in Decimal context can leave sub-nanobps residuals on repeating
#: decimals; any real formula/sign error differs by whole basis points.
RECONSTRUCTION_TOLERANCE_BPS = Decimal("0.000001")


class ExecutionSimulationStatus(str, Enum):
    """Typed fail-closed status family. Causes are never collapsed."""

    EXECUTION_SIMULATION_OK = "EXECUTION_SIMULATION_OK"
    EXECUTION_QUOTE_UNAVAILABLE = "EXECUTION_QUOTE_UNAVAILABLE"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    R7_LINEAGE_MISMATCH = "R7_LINEAGE_MISMATCH"
    R3_LINEAGE_MISMATCH = "R3_LINEAGE_MISMATCH"
    R2_ECONOMICS_MISMATCH = "R2_ECONOMICS_MISMATCH"
    UPSTREAM_ECONOMICS_MISMATCH = "UPSTREAM_ECONOMICS_MISMATCH"
    TIMING_INVALID = "TIMING_INVALID"
    COST_TREATMENT_UNRESOLVED = "COST_TREATMENT_UNRESOLVED"
    COST_EVIDENCE_INCOMPLETE = "COST_EVIDENCE_INCOMPLETE"
    SETTLEMENT_ADJUSTMENT_UNAVAILABLE = "SETTLEMENT_ADJUSTMENT_UNAVAILABLE"
    SETTLEMENT_ADJUSTMENT_UNRESOLVED = "SETTLEMENT_ADJUSTMENT_UNRESOLVED"
    CLOSED_LOOP_NOT_PROVEN = "CLOSED_LOOP_NOT_PROVEN"
    NON_FINITE_ECONOMICS = "NON_FINITE_ECONOMICS"
    INPUT_INVALID = "INPUT_INVALID"


class ExecutionSimulationError(ValueError):
    """Raised when an R8 simulation cannot proceed without guessing."""

    def __init__(
        self,
        message: str,
        status: ExecutionSimulationStatus = ExecutionSimulationStatus.INPUT_INVALID,
    ) -> None:
        super().__init__(message)
        self.status = status


class ExecutionMode(str, Enum):
    """R8 v1 supports reference-relative execution only."""

    REFERENCE_RELATIVE = "REFERENCE_RELATIVE"
    CLOSED_LOOP = "CLOSED_LOOP"


class ClosedLoopState(str, Enum):
    """R8 v1 keeps closed-loop execution explicitly unproven."""

    CLOSED_LOOP_NOT_PROVEN = "CLOSED_LOOP_NOT_PROVEN"


class NetEdgeState(str, Enum):
    """Completeness of the net executable edge."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class NetEdgeBlocker(str, Enum):
    """Typed reasons why a net executable edge value is absent."""

    NONE = "NONE"
    COST_TREATMENT_UNRESOLVED = "COST_TREATMENT_UNRESOLVED"
    COST_EVIDENCE_INCOMPLETE = "COST_EVIDENCE_INCOMPLETE"
    SETTLEMENT_ADJUSTMENT_UNRESOLVED = "SETTLEMENT_ADJUSTMENT_UNRESOLVED"
    TIMING_INVALID = "TIMING_INVALID"


class SettlementAdjustmentState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SOURCE_PROVEN_INCLUDED = "SOURCE_PROVEN_INCLUDED"
    SOURCE_PROVEN_EXCLUDED = "SOURCE_PROVEN_EXCLUDED"
    UNAVAILABLE = "UNAVAILABLE"
    UNRESOLVED = "UNRESOLVED"
    STALE = "STALE"


@dataclass(frozen=True)
class SettlementAdjustmentEvidence:
    """One explicitly evidenced post-trade settlement adjustment.

    The R0 QUOTE_SETTLEMENT_REFERENCE valuation is never deducted here again:
    it is already embedded in the settlement-converted execution economics.
    """

    state: SettlementAdjustmentState
    source: str
    observed_at: datetime | None
    amount_usd: Decimal | None = None
    currency: str | None = None
    treatment: str = "NOT_TREATED_CORRECTION_B_SCOPE"
    reason: str = ""
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.source.strip():
            raise ExecutionSimulationError(
                "settlement adjustment requires a non-empty source",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        if self.amount_usd is not None and (
            not self.amount_usd.is_finite() or self.amount_usd < 0
        ):
            raise ExecutionSimulationError(
                "settlement adjustment amount must be non-negative and finite",
                ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
            )
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ExecutionSimulationError(
                "settlement adjustment observed_at must be timezone-aware",
                ExecutionSimulationStatus.TIMING_INVALID,
            )


@dataclass(frozen=True)
class ExecutionScenario:
    """Typed canonical R8 simulation scenario."""

    economic_asset_uid: str
    canonical_asset_key: AssetKey
    side: QuoteSide
    requested_notional_usd: Decimal
    quote_source: str
    execution_mode: ExecutionMode = ExecutionMode.REFERENCE_RELATIVE
    r7_component_label: str | None = None
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if not self.economic_asset_uid.strip():
            raise ExecutionSimulationError(
                "scenario requires an economic asset UID",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        if not self.quote_source.strip():
            raise ExecutionSimulationError(
                "scenario requires a non-empty quote source",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        if not self.requested_notional_usd.is_finite() or self.requested_notional_usd <= 0:
            raise ExecutionSimulationError(
                "requested notional must be positive and finite",
                ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
            )
        # Correction A (F3): the evaluation instant is required and must be
        # timezone-aware BEFORE any subtraction is attempted. None or naive
        # values fail typed closed, never with a raw Python TypeError.
        if self.as_of is None:
            raise ExecutionSimulationError(
                "scenario as_of is required",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        if self.as_of.tzinfo is None:
            raise ExecutionSimulationError(
                "scenario as_of must be timezone-aware",
                ExecutionSimulationStatus.TIMING_INVALID,
            )


@dataclass(frozen=True)
class ScenarioQuoteEvidence:
    """Exact executable R0/R2/R3 evidence for one (side, notional) pair.

    Every field is copied from frozen upstream authority; nothing here is
    derived, interpolated or estimated by R8.
    """

    side: QuoteSide
    requested_notional_usd: Decimal
    token_amount: Decimal
    reference_price_usd_per_token: Decimal
    settlement_amount_usd: Decimal
    r2_gap_bps: Decimal
    quote_observed_at: datetime
    reference_generated_at: datetime
    settlement_observed_at: datetime | None
    canonical_asset_key: AssetKey
    venue: str
    route_signature: str | None
    route_changed: bool
    provider_fee_usd: Decimal | None
    provider_gas_usd: Decimal | None
    provider_cost_treatment: CostTreatmentState
    r0_quote_evidence: Mapping[str, Any] = field(default_factory=dict)
    r2_gap_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "r0_quote_evidence", deep_freeze(self.r0_quote_evidence))
        object.__setattr__(self, "r2_gap_evidence", deep_freeze(self.r2_gap_evidence))
        for name in (
            "requested_notional_usd",
            "token_amount",
            "reference_price_usd_per_token",
            "settlement_amount_usd",
            "r2_gap_bps",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ExecutionSimulationError(
                    f"{name} must be a finite Decimal",
                    ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
                )
        if self.requested_notional_usd <= 0:
            raise ExecutionSimulationError(
                "requested notional must be positive",
                ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
            )
        if self.token_amount <= 0 or self.reference_price_usd_per_token <= 0:
            raise ExecutionSimulationError(
                "token amount and reference price must be positive",
                ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
            )
        _require_aware(self.quote_observed_at, "quote observed_at")
        _require_aware(self.reference_generated_at, "reference generated_at")
        if self.settlement_observed_at is not None:
            _require_aware(self.settlement_observed_at, "settlement observed_at")

    @property
    def member_key(self) -> tuple[str, str, str]:
        return (self.side.value, str(self.requested_notional_usd), self.venue)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ExecutionSimulationError(
            f"{name} must be timezone-aware",
            ExecutionSimulationStatus.TIMING_INVALID,
        )


@dataclass(frozen=True)
class SimulationTimingPolicy:
    """Mandatory caller-supplied timing policy for R8-only evidence."""

    max_cost_evidence_age_seconds: Decimal
    max_settlement_evidence_age_seconds: Decimal

    def __post_init__(self) -> None:
        for name in (
            "max_cost_evidence_age_seconds",
            "max_settlement_evidence_age_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ExecutionSimulationError(
                    f"{name} must be a positive finite Decimal",
                    ExecutionSimulationStatus.INPUT_INVALID,
                )


@dataclass(frozen=True)
class GrossExecutionEconomics:
    """Exact USD gross execution economics with the mandatory R2 handshake."""

    benchmark_value_usd: Decimal
    settlement_amount_usd: Decimal
    token_amount: Decimal
    reference_price_usd_per_token: Decimal
    r2_gap_bps: Decimal
    gross_execution_edge_usd: Decimal
    gross_execution_edge_bps: Decimal
    side_adjusted_gap_bps: Decimal


@dataclass(frozen=True)
class ProviderCostResolution:
    """Typed resolution of provider fee/gas treatment (never guessed)."""

    treatment: CostTreatmentState
    provider_fee_usd: Decimal | None
    provider_gas_usd: Decimal | None
    provider_incremental_cost_usd: Decimal | None
    state: ExecutionSimulationStatus


@dataclass(frozen=True)
class SettlementResolution:
    """Typed resolution of settlement adjustments (never guessed)."""

    adjustment: SettlementAdjustmentEvidence | None
    settlement_incremental_cost_usd: Decimal | None
    state: ExecutionSimulationStatus


@dataclass(frozen=True)
class ExecutionSimulationResult:
    """Typed immutable result for exactly one scenario. Descriptive only."""

    status: ExecutionSimulationStatus
    scenario: ExecutionScenario
    net_edge_state: NetEdgeState
    net_edge_blockers: tuple[ExecutionSimulationStatus, ...]

    theoretical_dislocation_bps: Decimal | None
    r2_gap_bps: Decimal
    gross_execution_edge_bps: Decimal
    gross_execution_edge_usd: Decimal
    benchmark_value_usd: Decimal

    provider_fee_usd: Decimal | None
    provider_gas_usd: Decimal | None
    provider_cost_treatment: CostTreatmentState
    provider_incremental_cost_usd: Decimal | None

    settlement_adjustment_state: SettlementAdjustmentState | None
    settlement_incremental_cost_usd: Decimal | None

    net_executable_edge_bps: Decimal | None
    net_executable_edge_usd: Decimal | None

    route_signature: str | None
    route_changed: bool
    quote_source: str
    quote_observed_at: datetime
    reference_generated_at: datetime
    timing_blockers: tuple[ExecutionSimulationStatus, ...]

    r0_quote_evidence: Any
    r2_gap_evidence: Any

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "scenario": {
                "economicAssetUid": self.scenario.economic_asset_uid,
                "chainId": self.scenario.canonical_asset_key.chain_id,
                "contractAddress": self.scenario.canonical_asset_key.contract_address,
                "side": self.scenario.side.value,
                "requestedNotionalUsd": str(self.scenario.requested_notional_usd),
                "quoteSource": self.scenario.quote_source,
                "executionMode": self.scenario.execution_mode.value,
                "r7ComponentLabel": self.scenario.r7_component_label,
            },
            "netEdgeState": self.net_edge_state.value,
            "netEdgeBlockers": [b.value for b in self.net_edge_blockers],
            "theoreticalDislocationBps": (
                str(self.theoretical_dislocation_bps)
                if self.theoretical_dislocation_bps is not None
                else None
            ),
            "r2GapBps": str(self.r2_gap_bps),
            "grossExecutionEdgeBps": str(self.gross_execution_edge_bps),
            "grossExecutionEdgeUsd": str(self.gross_execution_edge_usd),
            "benchmarkValueUsd": str(self.benchmark_value_usd),
            "providerCost": {
                "feeUsd": str(self.provider_fee_usd) if self.provider_fee_usd is not None else None,
                "gasUsd": str(self.provider_gas_usd) if self.provider_gas_usd is not None else None,
                "treatment": self.provider_cost_treatment.value,
                "incrementalCostUsd": (
                    str(self.provider_incremental_cost_usd)
                    if self.provider_incremental_cost_usd is not None
                    else None
                ),
            },
            "settlementAdjustment": {
                "state": (
                    self.settlement_adjustment_state.value
                    if self.settlement_adjustment_state is not None
                    else None
                ),
                "incrementalCostUsd": (
                    str(self.settlement_incremental_cost_usd)
                    if self.settlement_incremental_cost_usd is not None
                    else None
                ),
            },
            "netExecutableEdgeBps": (
                str(self.net_executable_edge_bps)
                if self.net_executable_edge_bps is not None
                else None
            ),
            "netExecutableEdgeUsd": (
                str(self.net_executable_edge_usd)
                if self.net_executable_edge_usd is not None
                else None
            ),
            "route": {
                "signature": self.route_signature,
                "changed": self.route_changed,
                "semantics": "ROUTE_ECONOMICS_EMBEDDED_IN_EXECUTION_QUOTE",
            },
            "quoteObservedAt": self.quote_observed_at.isoformat(),
            "referenceGeneratedAt": self.reference_generated_at.isoformat(),
            "timingBlockers": [b.value for b in self.timing_blockers],
            "upstreamEvidence": {
                "r0QuoteEvidence": _plain(self.r0_quote_evidence),
                "r2GapEvidence": _plain(self.r2_gap_evidence),
            },
        }


def _plain(value: Any) -> Any:
    """Fresh plain JSON-compatible structure from (possibly frozen) input."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class SizeSensitivity:
    """Descriptive size sensitivity. Never an additional slippage cost."""

    side: QuoteSide
    small_notional_usd: Decimal
    large_notional_usd: Decimal
    gross_edge_change_bps: Decimal
    net_edge_change_bps: Decimal | None
    route_changed: bool

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "smallNotionalUsd": str(self.small_notional_usd),
            "largeNotionalUsd": str(self.large_notional_usd),
            "grossEdgeChangeBps": str(self.gross_edge_change_bps),
            "netEdgeChangeBps": (
                str(self.net_edge_change_bps) if self.net_edge_change_bps is not None else None
            ),
            "routeChanged": self.route_changed,
            "semantics": (
                "observed size sensitivity between exact quote scenarios; "
                "R0 sizeImpactBps is diagnostic evidence and is not deducted again"
            ),
        }


def _scenario_order(result: "ExecutionSimulationResult") -> tuple:
    """Deterministic canonical scenario order: side, notional, quote source."""
    return (
        result.scenario.side.value,
        str(result.scenario.requested_notional_usd),
        result.scenario.quote_source,
    )


@dataclass(frozen=True)
class ExecutionSimulationSnapshot:
    """Successful R8 output: canonical, deeply immutable, digested evidence."""

    status: ExecutionSimulationStatus
    economic_asset_uid: str
    canonical_asset_key: AssetKey
    scenarios: tuple[ExecutionSimulationResult, ...]
    size_sensitivity: tuple[SizeSensitivity, ...]
    closed_loop_state: ClosedLoopState
    simulation_policy: SimulationTimingPolicy
    upstream_evidence: Mapping[str, Any]
    source_digests: Mapping[str, str]
    synthetic: bool
    generated_at: datetime
    git_head: str
    r7_cross_market_digest: str
    r8_snapshot_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "upstream_evidence", deep_freeze(self.upstream_evidence))
        object.__setattr__(self, "source_digests", deep_freeze(self.source_digests))
        if self.status is not ExecutionSimulationStatus.EXECUTION_SIMULATION_OK:
            raise ExecutionSimulationError(
                "successful snapshot requires EXECUTION_SIMULATION_OK",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        ordered = tuple(sorted(self.scenarios, key=_scenario_order))
        if ordered != self.scenarios:
            raise ExecutionSimulationError(
                "scenarios must be supplied in deterministic canonical order",
                ExecutionSimulationStatus.INPUT_INVALID,
            )
        _require_aware(self.generated_at, "generated_at")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "gitHead": self.git_head,
            "generatedAt": self.generated_at.isoformat(),
            "economicAssetUid": self.economic_asset_uid,
            "canonicalAssetKey": {
                "chainId": self.canonical_asset_key.chain_id,
                "contractAddress": self.canonical_asset_key.contract_address,
            },
            "scenarios": [s.to_evidence_dict() for s in self.scenarios],
            "sizeSensitivity": [s.to_evidence_dict() for s in self.size_sensitivity],
            "costTreatment": sorted(
                {
                    s.provider_cost_treatment.value
                    for s in self.scenarios
                }
            ),
            "settlementTreatment": sorted(
                {
                    s.settlement_adjustment_state.value
                    for s in self.scenarios
                    if s.settlement_adjustment_state is not None
                }
            ),
            "closedLoopState": self.closed_loop_state.value,
            "simulationPolicy": {
                "maxCostEvidenceAgeSeconds": str(
                    self.simulation_policy.max_cost_evidence_age_seconds
                ),
                "maxSettlementEvidenceAgeSeconds": str(
                    self.simulation_policy.max_settlement_evidence_age_seconds
                ),
            },
            "upstreamEvidence": _plain(self.upstream_evidence),
            "sourceDigests": dict(self.source_digests),
            "boundaries": {
                "crossMarketAuthority": "R7_APPLIED",
                "executionSimulatorAuthority": "R8_APPLIED",
                "assetGraphAuthority": "R9_NOT_YET_APPLIED",
                "modelAuthority": "MODEL_NOT_YET_APPLIED",
                "verificationAuthority": "R11_NOT_YET_APPLIED",
            },
            "synthetic": self.synthetic,
            "r8SnapshotDigest": self.r8_snapshot_digest,
        }


def _require_aware(value: datetime, name: str) -> None:  # noqa: F811 - single definition
    if value.tzinfo is None:
        raise ExecutionSimulationError(
            f"{name} must be timezone-aware",
            ExecutionSimulationStatus.TIMING_INVALID,
        )


def canonical_evidence_bytes(evidence: Any) -> bytes:
    """Canonical JSON encoding used for every R8 digest."""
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compute_snapshot_digest(snapshot: "ExecutionSimulationSnapshot") -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("r8SnapshotDigest", None)
    return hashlib.sha256(canonical_evidence_bytes(evidence)).hexdigest()


def verify_serialized_evidence(evidence: Any) -> bool:
    """Fail-closed tamper detection over serialized R8 evidence."""
    if not isinstance(evidence, Mapping) or "r8SnapshotDigest" not in evidence:
        return False
    material = _plain(evidence)
    recorded = material.pop("r8SnapshotDigest")
    recomputed = hashlib.sha256(canonical_evidence_bytes(material)).hexdigest()
    return recorded == recomputed
