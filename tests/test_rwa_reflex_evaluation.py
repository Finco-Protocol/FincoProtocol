from decimal import Decimal

import pytest

from app.radar_rwa.reflex import ReflexOutcomePolicy, evaluate_recorded_outcome


def prediction(jev="0.80", baseline="0.60"):
    return {
        "event": {"session": "OPEN", "structural_premium_bps": "20", "initial_deviation_bps": "122"},
        "interpretation": {"likely_transient_probability": jev},
        "baseline": {"state": "AVAILABLE", "transient_probability": baseline},
    }


def outcome(premium="70", horizon=3600, session="OPEN", authority_state="AVAILABLE"):
    return {"reference_premium_bps": premium, "horizon_seconds": horizon,
            "market_session": session, "authority_state": authority_state}


def test_v2_labels_transient_from_frozen_structural_deviation_and_scores_both_forecasts():
    result = evaluate_recorded_outcome(prediction(), outcome())
    assert result["outcome_policy_version"] == "RWA_REFLEX_OUTCOME_POLICY_V2"
    assert result["label"] == "TRANSIENT"
    assert result["outcome_deviation_bps"] == "50"
    assert result["compression_ratio"] == str(Decimal("50") / Decimal("122"))
    assert result["jev_brier"] == "0.0400"
    assert result["baseline_brier"] == "0.1600"
    assert result["jev_log_loss"] > 0
    assert result["baseline_log_loss"] > 0


def test_v2_labels_not_transient_when_deviation_does_not_halve():
    result = evaluate_recorded_outcome(prediction(), outcome(premium="130"))
    assert result["label"] == "NOT_TRANSIENT"
    assert result["jev_brier"] == "0.6400"


@pytest.mark.parametrize("kwargs,reason", [
    ({"session": "CLOSED"}, "OUTCOME_SESSION_BOUNDARY"),
    ({"authority_state": "STALE"}, "OUTCOME_CANONICAL_NOT_AVAILABLE"),
    ({"horizon": 5000}, "OUTCOME_OUTSIDE_HORIZON_WINDOW"),
])
def test_ineligible_outcomes_are_typed_no_label(kwargs, reason):
    result = evaluate_recorded_outcome(prediction(), outcome(**kwargs))
    assert result["label"] == "NO_LABEL"
    assert result["label_reason"] == reason
    assert result["jev_brier"] is None


def test_probability_validation_and_clipping_are_versioned():
    policy = ReflexOutcomePolicy(probability_clip=Decimal("0.001"))
    result = evaluate_recorded_outcome(prediction(jev="1", baseline="0"), outcome(), policy=policy)
    assert result["policy"]["probability_clip"] == "0.001"
    assert result["jev_log_loss"] > 0
    assert result["baseline_log_loss"] > 0
    with pytest.raises(ValueError, match="between 0 and 1"):
        evaluate_recorded_outcome(prediction(jev="1.5"), outcome())
