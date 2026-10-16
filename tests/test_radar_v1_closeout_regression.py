"""Closeout regression matrix on existing exact Radar market authorities.

No independent basis, percentile, pricing or persistence formula is defined.
These tests call the frozen canonical functions with synthetic inputs only.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from finco_radar.venues.basis import BASIS_MAX_CLOCK_SKEW_SECONDS, basis_for_evidence
from finco_radar.venues.intelligence import (
    BasisPoint, RepresentationHistory, _basis_from_observation,
    effective_observation_state,
)
from finco_radar.venues.observations import (
    MarketObservation, FreshnessState, ObservationStatus,
)
from finco_radar.venues.relative_value import (
    MIN_HISTORY_SPAN_SECONDS, MIN_USABLE_OBSERVATIONS,
    compute_basis_distribution, compute_dislocation_persistence,
)
from finco_radar.venues.robinhood_live import EVIDENCE_CLOCK_CONTRACT
from app.crypto_terminal.deepstate_composition import (
    RAW_COMPARISON_UNIT, CURRENT_CROSS_VENUE, MAX_HISTORICAL_FILLS,
)

NOW = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)


def _history(values, *, state="AVAILABLE", last=None, interval=600):
    start = NOW - timedelta(seconds=(len(values) - 1) * interval + 60)
    points = tuple(BasisPoint(
        t=(start + timedelta(seconds=i * interval)).isoformat(),
        v=None if value is None else str(value),
        reason="MISSING_REFERENCE" if value is None else None,
    ) for i, value in enumerate(values))
    latest = str(values[-1]) if values and values[-1] is not None else None
    return RepresentationHistory(
        venue_id="fixture", instrument_id="contract",
        representation_type="tokenized-equity",
        current_state=state, latest_price="101",
        latest_basis_bps=latest if last is None else last,
        latest_basis_reason=None, basis_change_24h_bps=None,
        basis_change_7d_bps=None, points=points,
    )


def test_minimum_history_policies_are_immutable():
    assert MIN_USABLE_OBSERVATIONS == 8
    assert MIN_HISTORY_SPAN_SECONDS == 3600
    assert BASIS_MAX_CLOCK_SKEW_SECONDS == 300


@pytest.mark.parametrize("values,expected", [
    ([10] * 7, "INSUFFICIENT_HISTORY"),
    ([10] * 8, "AVAILABLE"),
    ([10] * 9, "AVAILABLE"),
])
def test_history_count_guard(values, expected):
    report = compute_basis_distribution(_history(values), now=NOW)
    assert report.state == expected


def test_history_span_guard():
    report = compute_basis_distribution(_history([5] * 8, interval=10), now=NOW)
    assert report.state == "INSUFFICIENT_HISTORY"
    assert report.history_span_seconds == 70


def test_duplicate_source_basis_points_do_not_inflate_history():
    history = _history([15] * 8)
    duplicates = replace(history, points=history.points + history.points)
    report = compute_basis_distribution(duplicates, now=NOW)
    assert report.usable_observation_count == 8


def test_missing_basis_never_becomes_zero_and_breaks_history():
    history = _history([10, 20, None, 30, 40, 50, 60, 70])
    report = compute_basis_distribution(history, now=NOW)
    assert report.usable_observation_count == 7
    assert report.state == "INSUFFICIENT_HISTORY"
    assert report.historical_median_basis_bps is None


def test_stale_current_does_not_erase_real_history_or_create_percentile():
    history = _history([100, 105, 110, 115, 120, 125, 130, 135], state="STALE")
    report = compute_basis_distribution(history, now=NOW)
    assert report.historical_median_basis_bps is not None
    assert report.current_basis_percentile is None
    assert report.state == "STALE"
    persistence = compute_dislocation_persistence(history, now=NOW)
    assert persistence.state == "STALE"
    assert persistence.duration_seconds is None


def test_unavailable_current_basis_disables_percentile_without_fabricating_zero():
    report = compute_basis_distribution(_history([1] * 8, last="invalid"), now=NOW)
    assert report.current_basis_percentile is None


def test_unknown_prior_dislocation_start_is_not_backdated():
    persistence = compute_dislocation_persistence(_history([150] * 8), now=NOW)
    assert persistence.state == "PREMIUM_DISLOCATION"
    assert persistence.start_state == "PREHISTORY_UNAVAILABLE"
    assert persistence.started_at is None
    assert persistence.duration_seconds is None


def test_sign_reversal_creates_distinct_episode():
    value = compute_dislocation_persistence(_history(
        [0, 120, 130, 140, -120, -135, -145, -150]), now=NOW)
    assert value.state == "DISCOUNT_DISLOCATION"
    assert value.start_state == "SIGN_REVERSAL"
    assert value.duration_seconds is not None


def test_missing_evidence_breaks_claim_of_continuity():
    value = compute_dislocation_persistence(_history(
        [0, 120, 140, None, 140, 150, 155, 160]), now=NOW)
    assert value.state == "PREMIUM_DISLOCATION"
    assert value.start_state == "PREHISTORY_UNAVAILABLE"
    assert value.duration_seconds is None


def test_threshold_equal_is_dislocation_not_within_threshold():
    value = compute_dislocation_persistence(_history(
        [0, 0, 0, 0, 0, 0, 0, 100]), now=NOW)
    assert value.state == "PREMIUM_DISLOCATION"


def test_price_market_reference_skew_over_five_minutes_is_rejected():
    m = NOW - timedelta(seconds=30)
    b, reason = basis_for_evidence(
        representation_price="102", representation_state="AVAILABLE",
        representation_source_timestamp=m.isoformat(),
        reference_price="100", reference_state="AVAILABLE",
        reference_source_timestamp=(m - timedelta(seconds=301)).isoformat(),
    )
    assert b is None and reason == "EVIDENCE_SKEW_EXCEEDS_POLICY"


def test_no_official_reference_never_generates_basis():
    m = NOW - timedelta(seconds=30)
    basis, reason = basis_for_evidence(
        representation_price="102", representation_state="AVAILABLE",
        representation_source_timestamp=m.isoformat(),
        reference_price=None, reference_state="UNAVAILABLE",
        reference_source_timestamp=None,
    )
    assert basis is None
    assert reason is not None


def _observation(*, status=ObservationStatus.OK, source=True, ref=True,
                 stale=False, v2=False):
    market = NOW - timedelta(minutes=1)
    payload = {
        "reference_state": "AVAILABLE" if ref else "UNAVAILABLE",
        "reference_observed_at": market.isoformat() if ref else None,
    }
    if v2:
        payload["evidence_clock_contract"] = EVIDENCE_CLOCK_CONTRACT
    return MarketObservation(
        ts=market.isoformat() if source else None,
        collected_at=NOW.isoformat(),
        canonical_asset_id="NVDA", venue_id="fixture",
        instrument_id="test-exact", instrument_type="tokenized-equity",
        price="102", reference_price="100" if ref else None,
        freshness_state=FreshnessState.STALE if stale else FreshnessState.AVAILABLE,
        observation_status=status, source="FIXTURE_ONLY", payload=payload,
    )


def test_quarantined_price_never_eligible_for_basis():
    basis, reason = _basis_from_observation(
        _observation(status=ObservationStatus.QUARANTINED))
    assert basis is None and reason == "REPRESENTATION_QUARANTINED"


def test_missing_source_time_does_not_inherit_collected_at():
    source, collected = MarketObservation.clocks(None, NOW)
    assert source is None and collected == NOW.isoformat()
    assert effective_observation_state(_observation(source=False), as_of=NOW) == "UNAVAILABLE"


def test_transport_recollection_does_not_change_canonical_digest():
    row = _observation()
    other = replace(row, collected_at=(NOW + timedelta(minutes=1)).isoformat())
    assert row.ts == other.ts
    assert row.compute_digest() == other.compute_digest()


def test_legacy_timestamp_and_v2_contract_remain_distinct():
    old = _observation()
    new = _observation(v2=True)
    assert "evidence_clock_contract" not in old.payload
    assert new.payload["evidence_clock_contract"] == EVIDENCE_CLOCK_CONTRACT
    assert old.resolved_digest() != new.resolved_digest()


def test_stale_observation_is_not_current_basis():
    assert effective_observation_state(_observation(stale=True), as_of=NOW) == "STALE"


def test_deepstate_product_claim_remains_historical_and_raw_usdg():
    assert RAW_COMPARISON_UNIT == "USDG_PER_NVDA"
    assert CURRENT_CROSS_VENUE == "UNAVAILABLE"
    assert MAX_HISTORICAL_FILLS == 120


def test_canonical_statuses_never_derive_distribution_from_transport_only():
    history = _history([])
    report = compute_basis_distribution(history, now=NOW)
    assert report.state == "UNAVAILABLE"
    assert report.usable_observation_count == 0
    assert report.current_basis_percentile is None
