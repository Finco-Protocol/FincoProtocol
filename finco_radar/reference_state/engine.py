"""Fail-closed reference-state classification over frozen R1/R2 authorities.

R4 interprets the state of the official reference (lifecycle, halt, freshness,
market session, corporate actions, multiplier transitions) and produces typed
usability evidence. It never recomputes R2/R3 economics, never replaces the R1
multiplier authority, and never emits signals or scores.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from finco_radar.assets.contracts import AssetKey, CanonicalAssetRecord
from finco_radar.gap.contracts import BoundReferencePrice

from .contracts import (
    BLOCKING_REASON_PRECEDENCE,
    AssetLifecycleState,
    CorporateActionMatches,
    CorporateActionRow,
    CorporateActionState,
    FreshnessState,
    HaltState,
    MarketSessionEvidence,
    MarketSessionState,
    MultiplierEvidence,
    MultiplierState,
    ReferenceStateError,
    ReferenceStatePolicy,
    ReferenceStateReason,
    ReferenceStateSnapshot,
    ReferenceStateStatus,
)


def _lifecycle_from_status(asset: CanonicalAssetRecord) -> AssetLifecycleState:
    return AssetLifecycleState(asset.status.value.removeprefix("ASSET_STATUS_"))


def _decimal_seconds(delta_seconds: float) -> Decimal:
    return Decimal(str(delta_seconds))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ReferenceStateError(
            f"{name} must be timezone-aware",
            ReferenceStateStatus.EVIDENCE_TIME_MISMATCH,
        )


def match_corporate_actions(
    rows: Sequence[CorporateActionRow],
    *,
    asset: CanonicalAssetRecord,
    asset_key: AssetKey,
) -> CorporateActionMatches:
    """Bind corporate-action rows to the exact canonical asset. Fail closed.

    - A row with the canonical UID must also carry the canonical deployment.
    - A row sharing the ticker (or the deployment) while carrying a different
      UID is an identity conflict and fails closed: ticker never repairs
      identity, and one deployment cannot belong to two canonical UIDs.
    - Unrelated rows are ignored. Matching rows keep source order.
    """
    matched: list[CorporateActionRow] = []
    for row in rows:
        if row.action_uid == asset.asset_uid:
            if asset_key not in row.deployments:
                raise ReferenceStateError(
                    f"corporate action {row.action_uid} matches the canonical UID but "
                    "not the canonical deployment",
                    ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
                )
            matched.append(row)
        elif row.token_symbol == asset.token_symbol:
            raise ReferenceStateError(
                f"corporate action row for ticker {row.token_symbol} carries UID "
                f"{row.action_uid} which conflicts with canonical UID {asset.asset_uid}; "
                "ticker may never repair identity",
                ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
            )
        elif asset_key in row.deployments:
            raise ReferenceStateError(
                "corporate action row carries the canonical deployment under foreign "
                f"UID {row.action_uid}",
                ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
            )
    return CorporateActionMatches(
        asset_uid=asset.asset_uid,
        asset_key=asset_key,
        rows=tuple(matched),
    )


def effective_session_state(
    session_evidence: MarketSessionEvidence,
    *,
    as_of: datetime,
    policy: ReferenceStatePolicy,
) -> MarketSessionState:
    """Effective session state after evidence-freshness validation.

    OPEN/CLOSED claims older than max_session_evidence_age_seconds (or from
    beyond the clock-skew tolerance) cannot explain current staleness and
    downgrade to UNRESOLVED. The original evidence is preserved unchanged.
    """
    if session_evidence.state is MarketSessionState.UNRESOLVED:
        return MarketSessionState.UNRESOLVED
    observed_at = session_evidence.observed_at
    if observed_at is None:  # defensive; the contract enforces this
        return MarketSessionState.UNRESOLVED
    _require_aware(observed_at, "session evidence observed_at")
    evidence_age = _decimal_seconds((as_of - observed_at).total_seconds())
    if evidence_age < -Decimal(policy.max_clock_skew_seconds):
        raise ReferenceStateError(
            "session evidence observed_at lies in the future beyond the declared "
            "clock tolerance",
            ReferenceStateStatus.EVIDENCE_TIME_MISMATCH,
        )
    if evidence_age > Decimal(policy.max_session_evidence_age_seconds):
        return MarketSessionState.UNRESOLVED
    return session_evidence.state


def classify_freshness(
    *,
    age: Decimal,
    session_evidence: MarketSessionEvidence,
    as_of: datetime,
    policy: ReferenceStatePolicy,
) -> tuple[FreshnessState, MarketSessionState, tuple[ReferenceStateReason, ...]]:
    """Freshness classification. EXPECTED_STATIC is currently unreachable.

    A point-in-time CLOSED observation proves only that the session is closed
    at that instant — it does NOT prove the reference was expected to remain
    static across the whole interval in which it aged. Correction A therefore
    never classifies EXPECTED_STATIC from MarketSessionEvidence: an old
    reference with CLOSED (or UNRESOLVED) session evidence is UNRESOLVED and
    blocks with MARKET_SESSION_UNRESOLVED. Fresh source-backed OPEN evidence
    still proves the reference is unexpectedly old (STALE_UNEXPECTED). A
    current reference needs no session authority to explain its age.
    """
    if age <= Decimal(policy.max_live_reference_age_seconds):
        # A current reference needs no session authority to explain its age;
        # an unresolved session is recorded but does not block here.
        return (
            FreshnessState.CURRENT,
            effective_session_state(session_evidence, as_of=as_of, policy=policy),
            (),
        )

    effective_session = effective_session_state(
        session_evidence, as_of=as_of, policy=policy
    )
    if effective_session is MarketSessionState.OPEN:
        return (
            FreshnessState.STALE_UNEXPECTED,
            effective_session,
            (ReferenceStateReason.REFERENCE_STALE_UNEXPECTED,),
        )
    # CLOSED point evidence (or stale CLOSED evidence downgraded to
    # UNRESOLVED) cannot explain the full stale interval: fail closed.
    return (
        FreshnessState.UNRESOLVED,
        effective_session,
        (ReferenceStateReason.MARKET_SESSION_UNRESOLVED,),
    )


def classify_multiplier(
    *,
    current_multiplier: Decimal,
    pending_multiplier: Decimal | None,
    pending_effective_at: datetime | None,
    as_of: datetime,
) -> tuple[MultiplierState, MultiplierEvidence, tuple[ReferenceStateReason, ...]]:
    """Interpret the R1 current/pending multiplier pair.

    The official currentMultiplier remains R1's declared authority; R4 never
    substitutes the pending multiplier itself.
    """
    evidence = MultiplierEvidence(
        state=MultiplierState.CURRENT,
        current_multiplier=current_multiplier,
        pending_multiplier=pending_multiplier,
        pending_effective_at=pending_effective_at,
    )
    if pending_multiplier is None:
        return MultiplierState.CURRENT, evidence, ()
    if pending_effective_at is None:
        # Unreachable through the frozen R1 parser (which enforces the pair);
        # defensive against direct contract construction.
        return (
            MultiplierState.INCONSISTENT,
            evidence,
            (ReferenceStateReason.MULTIPLIER_STATE_INCONSISTENT,),
        )
    _require_aware(pending_effective_at, "pending multiplier effective time")
    if as_of >= pending_effective_at:
        evidence = MultiplierEvidence(
            state=MultiplierState.TRANSITION_DUE_UNRESOLVED,
            current_multiplier=current_multiplier,
            pending_multiplier=pending_multiplier,
            pending_effective_at=pending_effective_at,
        )
        return (
            MultiplierState.TRANSITION_DUE_UNRESOLVED,
            evidence,
            (ReferenceStateReason.MULTIPLIER_TRANSITION_UNRESOLVED,),
        )
    evidence = MultiplierEvidence(
        state=MultiplierState.PENDING_FUTURE,
        current_multiplier=current_multiplier,
        pending_multiplier=pending_multiplier,
        pending_effective_at=pending_effective_at,
    )
    return MultiplierState.PENDING_FUTURE, evidence, ()


def build_reference_state_snapshot(
    *,
    asset: CanonicalAssetRecord,
    reference: BoundReferencePrice,
    corporate_actions: CorporateActionMatches,
    session_evidence: MarketSessionEvidence,
    policy: ReferenceStatePolicy,
    as_of: datetime,
    registry_observed_at: datetime | None = None,
    corporate_actions_observed_at: datetime | None = None,
) -> ReferenceStateSnapshot:
    """Classify the official reference state, or raise a typed error.

    All evidence must bind to one exact canonical deployment. No freshness or
    session threshold exists inside the engine — the caller-supplied policy is
    mandatory.
    """
    # Identity binding (R4 re-verifies the frozen R1/R2 binding cheaply).
    if reference.asset_uid != asset.asset_uid:
        raise ReferenceStateError(
            "reference asset UID does not match the canonical asset",
            ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
        )
    if reference.asset_key not in asset.deployments:
        raise ReferenceStateError(
            "reference asset key is not owned by the canonical asset",
            ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
        )
    if reference.symbol != asset.token_symbol:
        raise ReferenceStateError(
            "reference symbol does not match canonical asset metadata",
            ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
        )
    if corporate_actions.asset_uid != asset.asset_uid:
        raise ReferenceStateError(
            "corporate-action matches bind a different asset UID",
            ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
        )
    if corporate_actions.asset_key != reference.asset_key:
        raise ReferenceStateError(
            "corporate-action matches bind a different canonical deployment",
            ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH,
        )

    # Timezone-awareness (fail closed before any arithmetic).
    _require_aware(as_of, "as_of")
    _require_aware(reference.generated_at, "reference generated_at")
    if registry_observed_at is not None:
        _require_aware(registry_observed_at, "registry observed_at")
    if corporate_actions_observed_at is not None:
        _require_aware(corporate_actions_observed_at, "corporate-action observed_at")

    # Reference age; negative beyond the declared skew tolerance fails closed.
    age = _decimal_seconds((as_of - reference.generated_at).total_seconds())
    if age < -Decimal(policy.max_clock_skew_seconds):
        raise ReferenceStateError(
            "reference generated_at lies in the future beyond the declared clock "
            "tolerance",
            ReferenceStateStatus.EVIDENCE_TIME_MISMATCH,
        )

    blocking: set[ReferenceStateReason] = set()

    # Asset lifecycle (official R1 status wins over any other evidence).
    lifecycle = _lifecycle_from_status(asset)
    if lifecycle is AssetLifecycleState.INACTIVE:
        blocking.add(ReferenceStateReason.ASSET_INACTIVE)

    # Halt (explicit official evidence; freshness and halt stay separate, so a
    # fresh-but-halted reference is never presented as a normal current one).
    halt = HaltState.TRADING_HALTED if reference.is_trading_halt else HaltState.NOT_HALTED
    if halt is HaltState.TRADING_HALTED:
        blocking.add(ReferenceStateReason.TRADING_HALTED)

    # Freshness vs market session.
    freshness, session_state, freshness_blockers = classify_freshness(
        age=age,
        session_evidence=session_evidence,
        as_of=as_of,
        policy=policy,
    )
    blocking.update(freshness_blockers)

    # Corporate actions (unknown/forward material is conservative UNRESOLVED).
    ca_state = corporate_actions.state
    if ca_state is CorporateActionState.UNRESOLVED:
        blocking.add(ReferenceStateReason.CORPORATE_ACTION_UNRESOLVED)

    # Multiplier transition.
    multiplier_state, multiplier_evidence, multiplier_blockers = classify_multiplier(
        current_multiplier=asset.current_multiplier,
        pending_multiplier=asset.pending_multiplier,
        pending_effective_at=asset.pending_multiplier_effective_at,
        as_of=as_of,
    )
    blocking.update(multiplier_blockers)

    ordered_reasons = tuple(
        reason for reason in BLOCKING_REASON_PRECEDENCE if reason in blocking
    )
    return ReferenceStateSnapshot(
        status=ReferenceStateStatus.REFERENCE_STATE_OK,
        asset_uid=asset.asset_uid,
        canonical_key=reference.asset_key,
        symbol=asset.token_symbol,
        asset_lifecycle_state=lifecycle,
        halt_state=halt,
        freshness_state=freshness,
        market_session_state=session_state,
        corporate_action_state=ca_state,
        multiplier_state=multiplier_state,
        reference_usable=not ordered_reasons,
        blocking_reasons=ordered_reasons,
        reference_age_seconds=age,
        as_of=as_of,
        reference_generated_at=reference.generated_at,
        reference_source=reference.source,
        raw_bid=reference.raw_bid_usd_per_share,
        raw_ask=reference.raw_ask_usd_per_share,
        currency=reference.currency,
        is_trading_halt=reference.is_trading_halt,
        current_multiplier=asset.current_multiplier,
        pending_multiplier=asset.pending_multiplier,
        pending_multiplier_effective_at=asset.pending_multiplier_effective_at,
        multiplier_evidence=multiplier_evidence,
        session_evidence=session_evidence,
        corporate_actions=corporate_actions,
        registry_observed_at=registry_observed_at,
        policy=policy,
        corporate_actions_observed_at=corporate_actions_observed_at,
    )
