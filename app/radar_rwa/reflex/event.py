"""Independent-event contract for the Reflex shadow experiment."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from finco_radar.authority.contracts import AuthorityState

from .contracts import HISTORY_METHODOLOGY_VERSION, MarketSession, RwaReflexState


EVENT_POLICY_VERSION = "RWA_REFLEX_EVENT_POLICY_V2"
STRUCTURAL_PREMIUM_POLICY_VERSION = "RWA_REFLEX_STRUCTURAL_PREMIUM_POLICY_V1"
CANONICAL_PREMIUM_HISTORY_SOURCE = "FINCO_CANONICAL_PREMIUM_HISTORY"
CANONICAL_PREMIUM_HISTORY_WINDOW = "trailing_5_regular_sessions"
MINIMUM_STRUCTURAL_HISTORY_SAMPLES = 5
OUTCOME_FINALIZATION_RUNWAY_SECONDS = 65 * 60
PRE_T0_HISTORY_STRICT_REASON = "RWA_REFLEX_PRE_T0_HISTORY_NOT_STRICT"
STRUCTURAL_PREMIUM_POLICY_REASON = "RWA_REFLEX_STRUCTURAL_PREMIUM_POLICY_INVALID"
SESSION_BOUNDARY_MISSING_REASON = "RWA_REFLEX_REGULAR_SESSION_BOUNDARY_MISSING"
INSUFFICIENT_REGULAR_SESSION_RUNWAY = "INSUFFICIENT_REGULAR_SESSION_RUNWAY"


@dataclass(frozen=True)
class ReflexEventPolicy:
    deviation_threshold_bps: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        if not self.deviation_threshold_bps.is_finite() or self.deviation_threshold_bps <= 0:
            raise ValueError("event deviation threshold must be positive and finite")


@dataclass(frozen=True)
class ReflexEvent:
    event_id: str
    economic_asset_uid: str
    asset_key: str
    registry_source: str
    event_start: datetime
    prediction_time: datetime
    session: MarketSession
    structural_premium_bps: Decimal
    initial_deviation_bps: Decimal
    session_date: str
    session_open_at: datetime
    session_close_at: datetime
    session_source: str
    session_resolver_version: str
    structural_premium_policy_version: str
    history_cutoff_at: datetime
    policy_version: str = EVENT_POLICY_VERSION


def _validate_structural_policy(state: RwaReflexState) -> tuple[Decimal, datetime]:
    provenance = state.provenance
    if provenance is None:
        raise ValueError(STRUCTURAL_PREMIUM_POLICY_REASON)
    cutoff = provenance.history_observed_at
    if cutoff is None or state.observed_at is None:
        raise ValueError(STRUCTURAL_PREMIUM_POLICY_REASON)
    if cutoff >= state.observed_at:
        raise ValueError(PRE_T0_HISTORY_STRICT_REASON)
    if (
        provenance.history_source != CANONICAL_PREMIUM_HISTORY_SOURCE
        or provenance.history_methodology_version != HISTORY_METHODOLOGY_VERSION
        or provenance.history_window != CANONICAL_PREMIUM_HISTORY_WINDOW
        or provenance.history_median_bps is None
        or provenance.history_sample_count is None
        or provenance.history_sample_count < MINIMUM_STRUCTURAL_HISTORY_SAMPLES
    ):
        raise ValueError(STRUCTURAL_PREMIUM_POLICY_REASON)
    return provenance.history_median_bps, cutoff


def _validate_same_session_runway(state: RwaReflexState) -> tuple[str, datetime, datetime]:
    provenance = state.provenance
    if provenance is None or state.observed_at is None:
        raise ValueError(SESSION_BOUNDARY_MISSING_REASON)
    session_date = provenance.regular_session_date
    session_open = provenance.regular_session_open_at
    session_close = provenance.regular_session_close_at
    if not session_date or session_open is None or session_close is None:
        raise ValueError(SESSION_BOUNDARY_MISSING_REASON)
    if not provenance.session_source.strip() or not provenance.session_resolver_version.strip():
        raise ValueError(SESSION_BOUNDARY_MISSING_REASON)
    if state.observed_at < session_open or state.observed_at >= session_close:
        raise ValueError(SESSION_BOUNDARY_MISSING_REASON)
    if state.observed_at + timedelta(seconds=OUTCOME_FINALIZATION_RUNWAY_SECONDS) > session_close:
        raise ValueError(INSUFFICIENT_REGULAR_SESSION_RUNWAY)
    return session_date, session_open, session_close


def detect_new_event(
    state: RwaReflexState,
    *,
    previous_deviation_bps: Decimal | None,
    previous_observed_at: datetime | None,
    policy: ReflexEventPolicy = ReflexEventPolicy(),
) -> ReflexEvent | None:
    """Open one event only on a below-threshold -> above-threshold crossing.

    Event eligibility is stricter than generic Reflex-state availability. A
    scoreable sample must prove the structural premium is frozen strictly
    before t0 and that the complete T+60..T+65 outcome window stays inside the
    same regular session.
    """
    if (
        state.state is not AuthorityState.AVAILABLE
        or state.market_session is not MarketSession.OPEN
        or state.observed_at is None
        or state.economic_asset_uid is None
        or state.reference_premium_bps is None
        or state.provenance is None
        or not state.provenance.registry_source
    ):
        return None
    if previous_deviation_bps is None or previous_observed_at is None:
        return None
    if previous_observed_at.tzinfo is None or previous_observed_at.utcoffset() is None:
        raise ValueError("previous_observed_at must be timezone-aware")
    if previous_observed_at >= state.observed_at:
        raise ValueError("previous observation must precede event observation")

    structural_premium, history_cutoff = _validate_structural_policy(state)
    deviation = state.reference_premium_bps - structural_premium
    threshold = policy.deviation_threshold_bps
    if abs(previous_deviation_bps) >= threshold or abs(deviation) < threshold:
        return None

    session_date, session_open, session_close = _validate_same_session_runway(state)
    raw = "|".join((
        EVENT_POLICY_VERSION,
        STRUCTURAL_PREMIUM_POLICY_VERSION,
        state.economic_asset_uid,
        state.canonical_token.canonical_id,
        state.observed_at.isoformat(),
        history_cutoff.isoformat(),
    ))
    event_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return ReflexEvent(
        event_id=event_id,
        economic_asset_uid=state.economic_asset_uid,
        asset_key=state.canonical_token.canonical_id,
        registry_source=state.provenance.registry_source,
        event_start=state.observed_at,
        prediction_time=state.observed_at,
        session=state.market_session,
        structural_premium_bps=structural_premium,
        initial_deviation_bps=deviation,
        session_date=session_date,
        session_open_at=session_open,
        session_close_at=session_close,
        session_source=state.provenance.session_source,
        session_resolver_version=state.provenance.session_resolver_version,
        structural_premium_policy_version=STRUCTURAL_PREMIUM_POLICY_VERSION,
        history_cutoff_at=history_cutoff,
    )
