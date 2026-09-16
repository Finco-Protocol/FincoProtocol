"""Typed contracts for FINCO Radar R4 reference-state classification.

R4 owns reference-state classification only. It never emits signals, scores,
rankings or BUY/SELL/ARBITRAGE labels, and it never replaces R1 multiplier
authority or R2 reference-binding authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from finco_radar.assets.contracts import AssetKey


class ReferenceStateStatus(str, Enum):
    """Typed fail-closed status family for R4 computation attempts.

    Materially different causes never collapse to a generic BLOCKED.
    Infrastructure/network failures remain separate and are classified by the
    live proof as INFRASTRUCTURE_ERROR, never by the engine.

    Distinction from ReferenceStateReason (deliberate, Correction A): members
    of this enum are computation/boundary OUTCOMES — statuses that are thrown
    as ReferenceStateError or carried on successful computation results. Some
    members (MARKET_SESSION_UNRESOLVED, REFERENCE_STALE_UNEXPECTED,
    CORPORATE_ACTION_UNRESOLVED, MULTIPLIER_TRANSITION_UNRESOLVED) mirror
    blocking reasons; those are retained as vocabulary for boundaries that may
    throw in the future (for example a richer session authority), while the
    classified, successfully-computed versions of the same conditions surface
    as ReferenceStateReason values on a REFERENCE_STATE_OK snapshot with
    reference_usable=false. They are deliberately not thrown merely because a
    reference is unusable.
    """

    REFERENCE_STATE_OK = "REFERENCE_STATE_OK"
    REFERENCE_IDENTITY_MISMATCH = "REFERENCE_IDENTITY_MISMATCH"
    REFERENCE_EVIDENCE_INVALID = "REFERENCE_EVIDENCE_INVALID"
    MARKET_SESSION_UNRESOLVED = "MARKET_SESSION_UNRESOLVED"
    REFERENCE_STALE_UNEXPECTED = "REFERENCE_STALE_UNEXPECTED"
    CORPORATE_ACTION_EVIDENCE_INVALID = "CORPORATE_ACTION_EVIDENCE_INVALID"
    CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
    MULTIPLIER_TRANSITION_UNRESOLVED = "MULTIPLIER_TRANSITION_UNRESOLVED"
    EVIDENCE_TIME_MISMATCH = "EVIDENCE_TIME_MISMATCH"


class ReferenceStateError(ValueError):
    """Raised when reference state cannot be classified without guessing.

    Always carries a typed ReferenceStateStatus.
    """

    def __init__(
        self,
        message: str,
        status: ReferenceStateStatus = ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
    ) -> None:
        super().__init__(message)
        self.status = status


class CorporateActionEvidenceError(ReferenceStateError):
    """Typed error for malformed corporate-action source payloads."""


class AssetLifecycleState(str, Enum):
    """Official R1 asset lifecycle, verbatim from the registry status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNSPECIFIED = "UNSPECIFIED"


class HaltState(str, Enum):
    """Official isTradingHalt evidence. An old timestamp is never a halt."""

    NOT_HALTED = "NOT_HALTED"
    TRADING_HALTED = "TRADING_HALTED"


class FreshnessState(str, Enum):
    """Freshness of the official reference at the evaluation instant.

    EXPECTED_STATIC is a RESERVED future state: it is NOT reachable from the
    current point-in-time MarketSessionEvidence contract. A point-in-time
    CLOSED observation proves only that the session is closed now, not that the
    reference was expected to remain static across the whole interval in which
    it aged. It may become reachable only after a future source-backed session
    authority can prove the relevant non-updating interval / session-close
    boundary (R4_MARKET_SESSION_AUTHORITY_REQUIRED remains declared).
    """

    CURRENT = "CURRENT"
    EXPECTED_STATIC = "EXPECTED_STATIC"
    STALE_UNEXPECTED = "STALE_UNEXPECTED"
    UNRESOLVED = "UNRESOLVED"


class MarketSessionState(str, Enum):
    """Source-backed market/session state. Capability is not session state."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNRESOLVED = "UNRESOLVED"


class CorporateActionState(str, Enum):
    """Aggregated corporate-action state for the exact canonical asset.

    COMPLETED is semantically neutral: R4 has no recency authority (no age
    threshold, no source contract bounding endpoint recency), so a completed
    action is never labelled as recent. processDate is preserved as evidence
    for any future authority that defines recency.
    """

    NONE = "NONE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    UNRESOLVED = "UNRESOLVED"


class MultiplierState(str, Enum):
    """Interpretation of the R1 current/pending multiplier pair."""

    CURRENT = "CURRENT"
    PENDING_FUTURE = "PENDING_FUTURE"
    TRANSITION_DUE_UNRESOLVED = "TRANSITION_DUE_UNRESOLVED"
    INCONSISTENT = "INCONSISTENT"


class ReferenceStateReason(str, Enum):
    """Typed blocking reasons; reference_usable is false iff this is non-empty."""

    ASSET_INACTIVE = "ASSET_INACTIVE"
    TRADING_HALTED = "TRADING_HALTED"
    REFERENCE_STALE_UNEXPECTED = "REFERENCE_STALE_UNEXPECTED"
    MARKET_SESSION_UNRESOLVED = "MARKET_SESSION_UNRESOLVED"
    MULTIPLIER_TRANSITION_UNRESOLVED = "MULTIPLIER_TRANSITION_UNRESOLVED"
    MULTIPLIER_STATE_INCONSISTENT = "MULTIPLIER_STATE_INCONSISTENT"
    CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"


#: Deterministic precedence order for blocking reasons (most structural first).
BLOCKING_REASON_PRECEDENCE: tuple[ReferenceStateReason, ...] = (
    ReferenceStateReason.ASSET_INACTIVE,
    ReferenceStateReason.TRADING_HALTED,
    ReferenceStateReason.REFERENCE_STALE_UNEXPECTED,
    ReferenceStateReason.MARKET_SESSION_UNRESOLVED,
    ReferenceStateReason.MULTIPLIER_TRANSITION_UNRESOLVED,
    ReferenceStateReason.MULTIPLIER_STATE_INCONSISTENT,
    ReferenceStateReason.CORPORATE_ACTION_UNRESOLVED,
)


@dataclass(frozen=True)
class ReferenceStatePolicy:
    """Mandatory caller-supplied reference-state policy. No engine defaults.

    max_live_reference_age_seconds: reference age at or below this is CURRENT.
    max_session_evidence_age_seconds: OPEN/CLOSED session evidence older than
        this cannot classify freshness and downgrades to UNRESOLVED.
    max_clock_skew_seconds: tolerated negative age (clock skew); anything more
        negative fails closed with EVIDENCE_TIME_MISMATCH.

    Correction A: the former max_close_alignment_seconds field was removed.
    Point-in-time CLOSED evidence never authorizes EXPECTED_STATIC (it cannot
    prove the reference was expected to remain static across the interval in
    which it aged), so no close-alignment knob has valid semantics.
    """

    max_live_reference_age_seconds: int
    max_session_evidence_age_seconds: int
    max_clock_skew_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "max_live_reference_age_seconds",
            "max_session_evidence_age_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_clock_skew_seconds < 0:
            raise ValueError("max_clock_skew_seconds must be non-negative")


@dataclass(frozen=True)
class MarketSessionEvidence:
    """Caller-supplied market/session evidence.

    OPEN/CLOSED states demand positive provenance: a non-empty source name and
    a timezone-aware observed_at. UNRESOLVED must not fabricate observations —
    it records why the state could not be established.
    """

    state: MarketSessionState
    source: str
    observed_at: datetime | None = None
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.state, MarketSessionState):
            raise ReferenceStateError(
                "market session state must be a MarketSessionState",
                ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
            )
        if not self.source.strip():
            raise ReferenceStateError(
                "market session evidence requires a non-empty source",
                ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
            )
        if self.state is MarketSessionState.UNRESOLVED:
            if self.observed_at is not None:
                raise ReferenceStateError(
                    "UNRESOLVED session evidence must not fabricate observations",
                    ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
                )
        else:
            if self.observed_at is None:
                raise ReferenceStateError(
                    f"{self.state.value} session evidence requires observed_at",
                    ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
                )
            if self.observed_at.tzinfo is None:
                raise ReferenceStateError(
                    "session evidence observed_at must be timezone-aware",
                    ReferenceStateStatus.EVIDENCE_TIME_MISMATCH,
                )


@dataclass(frozen=True)
class CorporateActionRow:
    """One parsed official corporate-action row; raw evidence preserved.

    Known types carry their canonical details variant key; unknown/forward
    types are preserved verbatim and must never borrow another type's
    semantics. Unknown wire statuses are observable without being guessed.
    """

    action_uid: str
    action_type: str
    status: str
    token_symbol: str
    deployments: tuple[AssetKey, ...]
    process_date: date | None
    details: Mapping[str, Any]
    known_type: bool
    known_status: bool
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_type.strip():
            raise CorporateActionEvidenceError(
                "corporate action type is required",
                ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID,
            )
        if not self.status.strip():
            raise CorporateActionEvidenceError(
                "corporate action status is required",
                ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID,
            )
        if not self.deployments:
            raise CorporateActionEvidenceError(
                "corporate action row must carry at least one deployment",
                ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID,
            )

    @property
    def is_in_progress(self) -> bool:
        return self.status == "CORPORATE_ACTION_STATUS_IN_PROGRESS"

    @property
    def is_completed(self) -> bool:
        return self.status == "CORPORATE_ACTION_STATUS_COMPLETED"


@dataclass(frozen=True)
class CorporateActionMatches:
    """Deterministically ordered corporate-action rows bound to one asset."""

    asset_uid: str
    asset_key: AssetKey
    rows: tuple[CorporateActionRow, ...]
    rejected_conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for row in self.rows:
            if row.action_uid != self.asset_uid:
                raise ReferenceStateError(
                    "matched corporate-action row carries a different asset UID",
                    ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
                )
            if self.asset_key not in row.deployments:
                raise ReferenceStateError(
                    "matched corporate-action row does not carry the canonical deployment",
                    ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
                )

    @property
    def state(self) -> CorporateActionState:
        """Aggregate state; unknown/forward material is conservative UNRESOLVED."""
        if not self.rows:
            return CorporateActionState.NONE
        for row in self.rows:
            if row.is_in_progress and not row.known_type:
                return CorporateActionState.UNRESOLVED
            if not row.known_status:
                return CorporateActionState.UNRESOLVED
        if any(row.is_in_progress for row in self.rows):
            return CorporateActionState.IN_PROGRESS
        if any(row.is_completed for row in self.rows):
            return CorporateActionState.COMPLETED
        return CorporateActionState.UNRESOLVED


@dataclass(frozen=True)
class MultiplierEvidence:
    """Multiplier interpretation evidence; R1 remains the multiplier authority."""

    state: MultiplierState
    current_multiplier: Decimal
    pending_multiplier: Decimal | None
    pending_effective_at: datetime | None


@dataclass(frozen=True)
class ReferenceStateSnapshot:
    """Successful R4 output: typed reference-state classification.

    There is no score, no ranking and no trading signal anywhere in this
    contract or its serialization. R4 classifies state only.
    """

    status: ReferenceStateStatus
    asset_uid: str
    canonical_key: AssetKey
    symbol: str
    asset_lifecycle_state: AssetLifecycleState
    halt_state: HaltState
    freshness_state: FreshnessState
    market_session_state: MarketSessionState
    corporate_action_state: CorporateActionState
    multiplier_state: MultiplierState
    reference_usable: bool
    blocking_reasons: tuple[ReferenceStateReason, ...]
    reference_age_seconds: Decimal
    as_of: datetime
    reference_generated_at: datetime
    reference_source: str
    raw_bid: Decimal
    raw_ask: Decimal
    currency: str
    is_trading_halt: bool
    current_multiplier: Decimal
    pending_multiplier: Decimal | None
    pending_multiplier_effective_at: datetime | None
    multiplier_evidence: MultiplierEvidence
    session_evidence: MarketSessionEvidence
    corporate_actions: CorporateActionMatches
    registry_observed_at: datetime | None
    policy: ReferenceStatePolicy
    corporate_actions_observed_at: datetime | None

    def __post_init__(self) -> None:
        if self.status is not ReferenceStateStatus.REFERENCE_STATE_OK:
            raise ReferenceStateError(
                "a ReferenceStateSnapshot is only produced for REFERENCE_STATE_OK; "
                "failures travel as typed ReferenceStateError",
                ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
            )
        if self.reference_usable != (not self.blocking_reasons):
            raise ReferenceStateError(
                "reference_usable must be true exactly when no blocking reasons exist",
                ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
            )
        if self.as_of.tzinfo is None or self.reference_generated_at.tzinfo is None:
            raise ReferenceStateError(
                "as_of and reference generated_at must be timezone-aware",
                ReferenceStateStatus.EVIDENCE_TIME_MISMATCH,
            )
        if not self.reference_usable and not self.blocking_reasons:
            raise ReferenceStateError(
                "unusable reference requires blocking reasons",
                ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
            )
        for reason in self.blocking_reasons:
            if not isinstance(reason, ReferenceStateReason):
                raise ReferenceStateError(
                    "blocking reasons must be ReferenceStateReason values",
                    ReferenceStateStatus.REFERENCE_EVIDENCE_INVALID,
                )

    def to_evidence_dict(self) -> dict[str, Any]:
        """Reconstructible camelCase serialization for the evidence artifact."""
        ca_rows = [
            {
                "actionUid": row.action_uid,
                "type": row.action_type,
                "knownType": row.known_type,
                "status": row.status,
                "knownStatus": row.known_status,
                "processDate": (
                    row.process_date.isoformat() if row.process_date is not None else None
                ),
                "tokenSymbol": row.token_symbol,
                "deployments": [
                    {"chainId": d.chain_id, "contractAddress": d.contract_address}
                    for d in row.deployments
                ],
                "details": dict(row.details),
                "rawEvidence": dict(row.raw_evidence),
            }
            for row in self.corporate_actions.rows
        ]
        return {
            "status": self.status.value,
            "asset": {
                "assetUid": self.asset_uid,
                "canonicalKey": self.canonical_key.canonical_id,
                "symbol": self.symbol,
                "chainId": self.canonical_key.chain_id,
                "contractAddress": self.canonical_key.contract_address,
            },
            "states": {
                "assetLifecycle": self.asset_lifecycle_state.value,
                "halt": self.halt_state.value,
                "freshness": self.freshness_state.value,
                "marketSession": self.market_session_state.value,
                "corporateAction": self.corporate_action_state.value,
                "multiplier": self.multiplier_state.value,
            },
            "referenceUsable": self.reference_usable,
            "blockingReasons": [reason.value for reason in self.blocking_reasons],
            "timing": {
                "asOf": self.as_of.isoformat(),
                "referenceGeneratedAt": self.reference_generated_at.isoformat(),
                "referenceAgeSeconds": str(self.reference_age_seconds),
                "registryObservedAt": (
                    self.registry_observed_at.isoformat()
                    if self.registry_observed_at is not None
                    else None
                ),
                "corporateActionsObservedAt": (
                    self.corporate_actions_observed_at.isoformat()
                    if self.corporate_actions_observed_at is not None
                    else None
                ),
            },
            "referenceEvidence": {
                "source": self.reference_source,
                "rawBid": str(self.raw_bid),
                "rawAsk": str(self.raw_ask),
                "currency": self.currency,
                "isTradingHalt": self.is_trading_halt,
            },
            "multiplierEvidence": {
                "state": self.multiplier_evidence.state.value,
                "currentMultiplier": str(self.multiplier_evidence.current_multiplier),
                "pendingMultiplier": (
                    str(self.multiplier_evidence.pending_multiplier)
                    if self.multiplier_evidence.pending_multiplier is not None
                    else None
                ),
                "pendingMultiplierEffectiveAt": (
                    self.multiplier_evidence.pending_effective_at.isoformat()
                    if self.multiplier_evidence.pending_effective_at is not None
                    else None
                ),
            },
            "marketSessionEvidence": {
                "state": self.session_evidence.state.value,
                "source": self.session_evidence.source,
                "observedAt": (
                    self.session_evidence.observed_at.isoformat()
                    if self.session_evidence.observed_at is not None
                    else None
                ),
                "rawEvidence": dict(self.session_evidence.raw_evidence),
            },
            "corporateActionEvidence": {
                "state": self.corporate_actions.state.value,
                "matchCount": len(ca_rows),
                "rejectedConflicts": list(self.corporate_actions.rejected_conflicts),
                "rows": ca_rows,
            },
            "policy": {
                "maxLiveReferenceAgeSeconds": self.policy.max_live_reference_age_seconds,
                "maxSessionEvidenceAgeSeconds": self.policy.max_session_evidence_age_seconds,
                "maxClockSkewSeconds": self.policy.max_clock_skew_seconds,
            },
            "boundaries": {
                "referenceStateAuthority": "R4_APPLIED",
                "signalAuthority": "R5_NOT_YET_APPLIED",
                "terminalAuthority": "R6_NOT_YET_APPLIED",
            },
        }
