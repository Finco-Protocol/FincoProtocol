"""Internal shadow runner; no scheduler, route, secret discovery or public side effect."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState

from .contracts import RwaReflexContext
from .event import ReflexEventPolicy, detect_new_event
from .ledger import ReflexExperimentLedger, ReflexOutcomeObservation
from .service import ReflexExperimentService
from .state import build_reflex_state


class ReflexShadowRunner:
    def __init__(self, *, service: ReflexExperimentService, ledger: ReflexExperimentLedger) -> None:
        self.service = service
        self.ledger = ledger

    def capture_prediction(
        self,
        authority: AuthoritySnapshot,
        *,
        as_of: datetime,
        context: RwaReflexContext,
        previous_deviation_bps: Decimal | None,
        previous_observed_at: datetime | None,
        event_policy: ReflexEventPolicy = ReflexEventPolicy(),
        max_context_age_seconds: int = 300,
    ) -> dict[str, object]:
        state = build_reflex_state(
            authority, as_of=as_of, context=context,
            max_context_age_seconds=max_context_age_seconds,
        )
        event = detect_new_event(
            state,
            previous_deviation_bps=previous_deviation_bps,
            previous_observed_at=previous_observed_at,
            policy=event_policy,
        )
        if event is None:
            raise ValueError("RWA_REFLEX_NO_NEW_INDEPENDENT_EVENT")
        experiment = self.service.evaluate(
            authority, as_of=as_of, context=context,
            max_context_age_seconds=max_context_age_seconds,
        )
        event_payload = {
            "event_id": event.event_id,
            "economic_asset_uid": event.economic_asset_uid,
            "asset_key": event.asset_key,
            "registry_source": event.registry_source,
            "event_start": event.event_start.isoformat(),
            "prediction_time": event.prediction_time.isoformat(),
            "session": event.session.value,
            "structural_premium_bps": str(event.structural_premium_bps),
            "initial_deviation_bps": str(event.initial_deviation_bps),
            "session_date": event.session_date,
            "session_open_at": event.session_open_at.isoformat(),
            "session_close_at": event.session_close_at.isoformat(),
            "session_source": event.session_source,
            "session_resolver_version": event.session_resolver_version,
            "structural_premium_policy_version": event.structural_premium_policy_version,
            "history_cutoff_at": event.history_cutoff_at.isoformat(),
            "policy_version": event.policy_version,
        }
        experiment = {**experiment, "event": event_payload}
        digest = self.ledger.put_prediction(experiment)
        return {**experiment, "prediction_digest": digest}

    def capture_outcome(
        self,
        prediction_digest: str,
        authority: AuthoritySnapshot,
        *,
        as_of: datetime,
        context: RwaReflexContext,
        max_context_age_seconds: int = 300,
    ) -> str:
        """Build a raw candidate outcome from canonical authority only."""
        state = build_reflex_state(
            authority, as_of=as_of, context=context,
            max_context_age_seconds=max_context_age_seconds,
        )
        if state.state is not AuthorityState.AVAILABLE or state.observed_at is None or state.economic_asset_uid is None:
            raise ValueError("shadow outcome requires AVAILABLE canonical Reflex state")
        if state.provenance is None or not state.provenance.registry_source:
            raise ValueError("shadow outcome requires canonical registry provenance")
        outcome = ReflexOutcomeObservation(
            observed_at=state.observed_at,
            economic_asset_uid=state.economic_asset_uid,
            asset_key=state.canonical_token.canonical_id,
            registry_source=state.provenance.registry_source,
            registry_observed_at=state.provenance.registry_observed_at,
            authority_state=state.state.value,
            market_session=state.market_session.value,
            reference_premium_bps=state.reference_premium_bps,
            effective_gap_bps=state.effective_gap_bps,
            liquidity_usd=state.liquidity_usd,
            depth_1pct_usd=state.depth_1pct_usd,
            identity_conflict=False,
        )
        return self.ledger.put_outcome(prediction_digest, outcome)
