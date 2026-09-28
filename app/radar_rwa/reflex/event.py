"""Minimal independent-event contract for the Reflex shadow experiment."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finco_radar.authority.contracts import AuthorityState

from .contracts import MarketSession, RwaReflexState


EVENT_POLICY_VERSION = "RWA_REFLEX_EVENT_POLICY_V1"


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
    policy_version: str = EVENT_POLICY_VERSION


def detect_new_event(
    state: RwaReflexState,
    *,
    previous_deviation_bps: Decimal | None,
    previous_observed_at: datetime | None,
    policy: ReflexEventPolicy = ReflexEventPolicy(),
) -> ReflexEvent | None:
    """Open one event only on a below-threshold -> above-threshold crossing.

    Repeated observations while the same dislocation remains above threshold do
    not create additional samples. A new sample therefore requires a subsequent
    observed normal/below-threshold state before another crossing.
    """
    if (state.state is not AuthorityState.AVAILABLE
            or state.market_session is not MarketSession.OPEN
            or state.observed_at is None
            or state.economic_asset_uid is None
            or state.premium_deviation_bps is None
            or state.structural_premium_bps is None
            or state.provenance is None
            or not state.provenance.registry_source):
        return None
    if previous_deviation_bps is None or previous_observed_at is None:
        return None
    if previous_observed_at.tzinfo is None or previous_observed_at.utcoffset() is None:
        raise ValueError("previous_observed_at must be timezone-aware")
    if previous_observed_at >= state.observed_at:
        raise ValueError("previous observation must precede event observation")
    threshold = policy.deviation_threshold_bps
    if abs(previous_deviation_bps) >= threshold or abs(state.premium_deviation_bps) < threshold:
        return None

    raw = "|".join((
        EVENT_POLICY_VERSION,
        state.economic_asset_uid,
        state.canonical_token.canonical_id,
        state.observed_at.isoformat(),
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
        structural_premium_bps=state.structural_premium_bps,
        initial_deviation_bps=state.premium_deviation_bps,
    )
