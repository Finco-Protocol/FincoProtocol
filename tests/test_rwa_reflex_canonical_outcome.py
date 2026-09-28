from datetime import timedelta
from decimal import Decimal

from app.radar_rwa.reflex import (
    ReflexExperimentLedger,
    ReflexExperimentService,
    ReflexOutcomeObservation,
    ReflexShadowRunner,
)
from tests.rwa_reflex_helpers import NOW, authority, context


def _prediction(ledger: ReflexExperimentLedger) -> str:
    runner = ReflexShadowRunner(service=ReflexExperimentService(), ledger=ledger)
    captured = runner.capture_prediction(
        authority(),
        as_of=NOW,
        context=context(),
        previous_deviation_bps=Decimal("20"),
        previous_observed_at=NOW - timedelta(minutes=1),
    )
    return captured["prediction_digest"]


def _observation(
    ledger: ReflexExperimentLedger,
    prediction_digest: str,
    *,
    offset: timedelta,
    premium_bps: Decimal = Decimal("70"),
    authority_state: str = "AVAILABLE",
    market_session: str = "OPEN",
    identity_conflict: bool = False,
) -> ReflexOutcomeObservation:
    identity = ledger.prediction_identity(prediction_digest)
    assert identity is not None
    return ReflexOutcomeObservation(
        observed_at=NOW + offset,
        economic_asset_uid=identity["economic_asset_uid"],
        asset_key=identity["asset_key"],
        registry_source=identity["registry_source"],
        registry_observed_at=NOW + offset,
        authority_state=authority_state,
        market_session=market_session,
        reference_premium_bps=premium_bps,
        effective_gap_bps=Decimal("90"),
        liquidity_usd=Decimal("250000"),
        depth_1pct_usd=Decimal("84200"),
        identity_conflict=identity_conflict,
    )


def _finalize(ledger: ReflexExperimentLedger, prediction_digest: str, *, extra_seconds: int = 0):
    return ledger.finalize_canonical_outcome(
        prediction_digest,
        as_of=NOW + timedelta(minutes=65, seconds=extra_seconds),
    )


def test_observation_before_t_plus_60_is_never_selected():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        pre_target_digest = ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=59, seconds=59)),
        )

        finalized = _finalize(ledger, prediction_digest)

        assert finalized["canonical_outcome_state"] == "NO_LABEL"
        assert finalized["canonical_reason"] == "OUTCOME_ELIGIBLE_OBSERVATION_MISSING"
        assert finalized["candidate_digest"] is None
        assert finalized["candidate_digest"] != pre_target_digest
    finally:
        ledger.close()


def test_first_eligible_available_observation_in_window_is_selected():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        first_digest = ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=60, seconds=1), premium_bps=Decimal("70")),
        )
        ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=64), premium_bps=Decimal("80")),
        )

        finalized = _finalize(ledger, prediction_digest)

        assert finalized["canonical_outcome_state"] == "AVAILABLE"
        assert finalized["candidate_digest"] == first_digest
        assert finalized["horizon_seconds"] == 3601
        assert finalized["reference_premium_bps"] == "70"
    finally:
        ledger.close()


def test_later_eligible_observation_cannot_replace_finalized_outcome():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        first_digest = ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=60), premium_bps=Decimal("70")),
        )
        finalized = _finalize(ledger, prediction_digest)

        later_digest = ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=64), premium_bps=Decimal("95")),
        )
        repeated = _finalize(ledger, prediction_digest, extra_seconds=30)

        assert finalized["candidate_digest"] == first_digest
        assert repeated["candidate_digest"] == first_digest
        assert repeated["candidate_digest"] != later_digest
        assert repeated["reference_premium_bps"] == "70"
    finally:
        ledger.close()


def test_repeated_finalization_returns_same_immutable_outcome():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=61)),
        )

        first = _finalize(ledger, prediction_digest)
        repeated = _finalize(ledger, prediction_digest, extra_seconds=45)

        assert repeated == first
        assert repeated["finalized_at"] == first["finalized_at"]
    finally:
        ledger.close()


def test_no_eligible_observation_by_t_plus_65_finalizes_no_label():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        ledger.put_outcome(
            prediction_digest,
            _observation(
                ledger,
                prediction_digest,
                offset=timedelta(minutes=62),
                authority_state="STALE",
            ),
        )

        finalized = _finalize(ledger, prediction_digest)

        assert finalized["canonical_outcome_state"] == "NO_LABEL"
        assert finalized["canonical_reason"] == "OUTCOME_ELIGIBLE_OBSERVATION_MISSING"
        assert finalized["candidate_digest"] is None
    finally:
        ledger.close()


def test_identity_lineage_conflict_finalizes_no_label():
    ledger = ReflexExperimentLedger()
    try:
        prediction_digest = _prediction(ledger)
        conflict_digest = ledger.put_outcome(
            prediction_digest,
            _observation(
                ledger,
                prediction_digest,
                offset=timedelta(minutes=60),
                identity_conflict=True,
            ),
        )
        ledger.put_outcome(
            prediction_digest,
            _observation(ledger, prediction_digest, offset=timedelta(minutes=61)),
        )

        finalized = _finalize(ledger, prediction_digest)

        assert finalized["canonical_outcome_state"] == "NO_LABEL"
        assert finalized["canonical_reason"] == "OUTCOME_IDENTITY_LINEAGE_CONFLICT"
        assert finalized["candidate_digest"] == conflict_digest
        assert finalized["identity_conflict"] is True
    finally:
        ledger.close()
