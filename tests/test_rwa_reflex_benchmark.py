from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from app.radar_rwa.reflex import (
    EmpiricalTransientBaselineConfig, ReflexExperimentLedger, ReflexExperimentService,
    ReflexOutcomeObservation, detect_new_event, evaluate_transient_baseline,
)
from app.radar_rwa.reflex.ledger import OUTCOME_SOURCE_CONTRACT
from tests.rwa_reflex_helpers import NOW, UID, KEY, authority, context, state


def _baseline_config():
    return EmpiricalTransientBaselineConfig(
        training_cutoff=NOW - timedelta(days=1), training_source="FROZEN_PREPERIOD",
        global_transient_count=12, global_total_count=20,
        cell_counts={"OPEN|100_TO_199_BPS|25K_TO_99K_USD": (8, 10)},
    )


def _experiment():
    s = state()
    event = detect_new_event(s, previous_deviation_bps=Decimal("20"), previous_observed_at=NOW - timedelta(minutes=1))
    assert event is not None
    payload = ReflexExperimentService(baseline_config=_baseline_config()).evaluate(authority(), as_of=NOW, context=context())
    return {**payload, "event": {
        "event_id": event.event_id, "economic_asset_uid": event.economic_asset_uid, "asset_key": event.asset_key,
        "registry_source": event.registry_source, "event_start": event.event_start.isoformat(),
        "prediction_time": event.prediction_time.isoformat(), "session": event.session.value,
        "structural_premium_bps": str(event.structural_premium_bps), "initial_deviation_bps": str(event.initial_deviation_bps),
        "policy_version": event.policy_version,
    }}


def _available_experiment(*, event_id: str, resolved_model: str = "jev-1.13.0",
                          request_schema: str = "RWA_REFLEX_JEV_REQUEST_V2"):
    payload = deepcopy(_experiment())
    payload["event"]["event_id"] = event_id
    payload["interpretation"].update({
        "state": "AVAILABLE",
        "request_schema_version": request_schema,
        "likely_transient_probability": "0.70",
        "resolved_model": resolved_model,
        "provider_request_id": f"req-{event_id}",
        "reason": None,
    })
    return payload


def test_empirical_baseline_returns_comparable_probability_with_information_parity():
    result = evaluate_transient_baseline(state(), config=_baseline_config())
    assert result["state"] == "AVAILABLE"
    assert result["transient_probability"] == "0.7"
    assert result["information_parity"] == "RWA_REFLEX_JEV_BASELINE_INFORMATION_PARITY"
    assert result["feature_state"] == {
        "schema_version": "RWA_REFLEX_FEATURES_V2", "market_session": "OPEN",
        "deviation_bucket": "100_TO_199_BPS", "depth_bucket": "25K_TO_99K_USD",
    }


def test_baseline_is_unavailable_without_frozen_preperiod_history():
    result = evaluate_transient_baseline(state(), config=EmpiricalTransientBaselineConfig())
    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == "FROZEN_PREPERIOD_BASELINE_INSUFFICIENT"


def test_baseline_training_cutoff_must_strictly_precede_prediction():
    config = EmpiricalTransientBaselineConfig(
        training_cutoff=NOW,
        training_source="INVALID_NON_PREPERIOD",
        global_transient_count=12,
        global_total_count=20,
    )
    with pytest.raises(ValueError, match="precede prediction"):
        evaluate_transient_baseline(state(), config=config)


def test_prediction_is_idempotent_but_second_prediction_for_same_event_is_rejected():
    ledger = ReflexExperimentLedger()
    try:
        payload = _experiment()
        digest = ledger.put_prediction(payload)
        assert ledger.put_prediction(payload) == digest
        changed = {**payload, "schema_version": "CHANGED_SAME_EVENT"}
        with pytest.raises(ValueError, match="RWA_REFLEX_EVENT_DUPLICATE"):
            ledger.put_prediction(changed)
        assert ledger.read_prediction(digest)["ledger_schema_version"] == "RWA_REFLEX_LEDGER_V2"
    finally:
        ledger.close()


def test_calibration_sample_stops_if_resolved_model_changes():
    ledger = ReflexExperimentLedger()
    try:
        ledger.put_prediction(_available_experiment(event_id="event-a", resolved_model="jev-1.13.0"))
        with pytest.raises(ValueError, match="RWA_REFLEX_MODEL_VERSION_CHANGED"):
            ledger.put_prediction(_available_experiment(event_id="event-b", resolved_model="jev-1.14.0"))
    finally:
        ledger.close()


def test_calibration_sample_stops_if_request_schema_changes():
    ledger = ReflexExperimentLedger()
    try:
        ledger.put_prediction(_available_experiment(event_id="event-a"))
        with pytest.raises(ValueError, match="RWA_REFLEX_REQUEST_SCHEMA_CHANGED"):
            ledger.put_prediction(_available_experiment(event_id="event-b", request_schema="RWA_REFLEX_JEV_REQUEST_V3"))
    finally:
        ledger.close()


def test_outcome_identity_and_source_contract_are_enforced():
    ledger = ReflexExperimentLedger()
    try:
        prediction = ledger.put_prediction(_experiment())
        good = ReflexOutcomeObservation(
            observed_at=NOW + timedelta(hours=1), economic_asset_uid=UID, asset_key=KEY.canonical_id,
            registry_source="ROBINHOOD_ASSET_REGISTRY", registry_observed_at=NOW,
            authority_state="AVAILABLE", market_session="OPEN", reference_premium_bps=Decimal("70"),
            effective_gap_bps=None, liquidity_usd=None, depth_1pct_usd=None,
        )
        digest = ledger.put_outcome(prediction, good)
        assert ledger.put_outcome(prediction, good) == digest
        bad_asset = ReflexOutcomeObservation(
            observed_at=NOW + timedelta(hours=1), economic_asset_uid="0x" + "77" * 32,
            asset_key=KEY.canonical_id, registry_source="ROBINHOOD_ASSET_REGISTRY", registry_observed_at=NOW,
            authority_state="AVAILABLE", market_session="OPEN", reference_premium_bps=Decimal("70"),
            effective_gap_bps=None, liquidity_usd=None, depth_1pct_usd=None,
        )
        with pytest.raises(ValueError, match="RWA_REFLEX_OUTCOME_CROSS_ASSET_REJECTED"):
            ledger.put_outcome(prediction, bad_asset)
        with pytest.raises(ValueError, match="RWA_REFLEX_OUTCOME_SOURCE_SPOOF_REJECTED"):
            ReflexOutcomeObservation(
                observed_at=NOW + timedelta(hours=1), economic_asset_uid=UID, asset_key=KEY.canonical_id,
                registry_source="ROBINHOOD_ASSET_REGISTRY", registry_observed_at=NOW,
                authority_state="AVAILABLE", market_session="OPEN", reference_premium_bps=Decimal("70"),
                effective_gap_bps=None, liquidity_usd=None, depth_1pct_usd=None, source_contract="SPOOFED",
            )
        assert OUTCOME_SOURCE_CONTRACT == "FINCO_AUTHORITY_SNAPSHOT_V1"
    finally:
        ledger.close()
