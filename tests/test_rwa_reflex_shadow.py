from datetime import timedelta
from decimal import Decimal

import pytest

from app.radar_rwa.reflex import ReflexExperimentLedger, ReflexExperimentService, ReflexShadowRunner
from tests.rwa_reflex_helpers import NOW, authority, context


def test_shadow_runner_records_one_crossing_event_and_canonical_candidate():
    ledger = ReflexExperimentLedger()
    try:
        runner = ReflexShadowRunner(service=ReflexExperimentService(), ledger=ledger)
        captured = runner.capture_prediction(
            authority(), as_of=NOW, context=context(),
            previous_deviation_bps=Decimal("20"), previous_observed_at=NOW - timedelta(minutes=1),
        )
        prediction_digest = captured["prediction_digest"]
        assert captured["event"]["policy_version"] == "RWA_REFLEX_EVENT_POLICY_V2"
        assert captured["event"]["structural_premium_policy_version"] == "RWA_REFLEX_STRUCTURAL_PREMIUM_POLICY_V1"
        assert captured["event"]["history_cutoff_at"] < captured["event"]["event_start"]
        assert ledger.read_prediction(prediction_digest) is not None

        later = NOW + timedelta(hours=1)
        outcome_digest = runner.capture_outcome(
            prediction_digest, authority(premium_bps=Decimal("70"), observed_at=later),
            as_of=later, context=context(observed_at=later),
        )
        outcomes = ledger.read_outcomes(prediction_digest)
        assert len(outcomes) == 1
        assert outcomes[0]["observation_kind"] == "CANDIDATE_OBSERVATION"
        assert outcomes[0]["reference_premium_bps"] == "70"
        assert outcomes[0]["horizon_seconds"] == 3600
        assert outcomes[0]["source_contract"] == "FINCO_AUTHORITY_SNAPSHOT_V1"
        assert len(outcome_digest) == 64
    finally:
        ledger.close()


def test_repeated_above_threshold_observation_is_not_a_new_event():
    ledger = ReflexExperimentLedger()
    try:
        runner = ReflexShadowRunner(service=ReflexExperimentService(), ledger=ledger)
        with pytest.raises(ValueError, match="RWA_REFLEX_NO_NEW_INDEPENDENT_EVENT"):
            runner.capture_prediction(
                authority(), as_of=NOW, context=context(),
                previous_deviation_bps=Decimal("110"), previous_observed_at=NOW - timedelta(minutes=1),
            )
    finally:
        ledger.close()


def test_late_session_event_is_excluded_before_prediction():
    ledger = ReflexExperimentLedger()
    try:
        runner = ReflexShadowRunner(service=ReflexExperimentService(), ledger=ledger)
        late_context = context(session_close_at=NOW + timedelta(minutes=64))
        with pytest.raises(ValueError, match="INSUFFICIENT_REGULAR_SESSION_RUNWAY"):
            runner.capture_prediction(
                authority(), as_of=NOW, context=late_context,
                previous_deviation_bps=Decimal("20"), previous_observed_at=NOW - timedelta(minutes=1),
            )
    finally:
        ledger.close()


def test_outcome_must_be_built_from_available_authority_snapshot():
    ledger = ReflexExperimentLedger()
    try:
        runner = ReflexShadowRunner(service=ReflexExperimentService(), ledger=ledger)
        captured = runner.capture_prediction(
            authority(), as_of=NOW, context=context(),
            previous_deviation_bps=Decimal("20"), previous_observed_at=NOW - timedelta(minutes=1),
        )
        later = NOW + timedelta(hours=1)
        with pytest.raises(ValueError, match="AVAILABLE canonical"):
            runner.capture_outcome(
                captured["prediction_digest"],
                authority(observed_at=later, premium_state=__import__("finco_radar.authority.contracts", fromlist=["AuthorityState"]).AuthorityState.STALE),
                as_of=later, context=context(observed_at=later),
            )
    finally:
        ledger.close()
