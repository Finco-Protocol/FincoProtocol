from app.radar_rwa.reflex import LIVE_SAMPLE_BLOCKED, assess_live_sample_preconditions
from tests.rwa_reflex_helpers import authority


def test_zero_canonical_data_blocks_live_typesafe_sample():
    result = assess_live_sample_preconditions([], eligible_historical_observation_count=0, regular_session_observation_count=0)
    assert result.live_sample_allowed is False
    assert result.reason == LIVE_SAMPLE_BLOCKED
    assert result.premium_available_count == 0


def test_preflight_reports_each_canonical_readiness_count():
    result = assess_live_sample_preconditions(
        [authority()],
        eligible_historical_observation_count=30,
        regular_session_observation_count=30,
        frozen_baseline_training_ready=True,
        comparable_asset_cohort_confirmed=True,
    )
    assert result.chain_4663_canonical_identity_count == 1
    assert result.approved_independent_token_reference_count == 1
    assert result.premium_available_count == 1
    assert result.frozen_baseline_training_ready is True
    assert result.comparable_asset_cohort_confirmed is True
    assert result.live_sample_allowed is True
    assert result.reason is None


def test_preflight_blocks_when_baseline_or_cohort_is_not_frozen():
    for baseline_ready, cohort_ready in ((False, True), (True, False)):
        result = assess_live_sample_preconditions(
            [authority()],
            eligible_historical_observation_count=30,
            regular_session_observation_count=30,
            frozen_baseline_training_ready=baseline_ready,
            comparable_asset_cohort_confirmed=cohort_ready,
        )
        assert result.live_sample_allowed is False
        assert result.reason == LIVE_SAMPLE_BLOCKED
