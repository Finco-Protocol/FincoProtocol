from app.radar_rwa.reflex import LIVE_SAMPLE_BLOCKED, assess_live_sample_preconditions
from tests.rwa_reflex_helpers import authority


def test_zero_canonical_data_blocks_live_typesafe_sample():
    result = assess_live_sample_preconditions([], eligible_historical_observation_count=0, regular_session_observation_count=0)
    assert result.live_sample_allowed is False
    assert result.reason == LIVE_SAMPLE_BLOCKED
    assert result.premium_available_count == 0


def test_preflight_reports_each_canonical_readiness_count():
    result = assess_live_sample_preconditions(
        [authority()], eligible_historical_observation_count=30, regular_session_observation_count=30,
    )
    assert result.chain_4663_canonical_identity_count == 1
    assert result.approved_independent_token_reference_count == 1
    assert result.premium_available_count == 1
    assert result.live_sample_allowed is True
    assert result.reason is None
