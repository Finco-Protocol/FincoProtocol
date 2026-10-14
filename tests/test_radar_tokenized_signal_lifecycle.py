"""R5/WF-03 lifecycle evidence and negative regression contract.

No network, database writes by read paths, or legacy size/liquidity R5 math.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.crypto_terminal.tokenized_signal_lifecycle import (
    CONTRACT_VERSION, HISTORY_WINDOW, LifecycleKind,
    MAX_FEED_EVENTS, MAX_OBSERVATIONS_PER_REPRESENTATION,
    build_tokenized_signal_lifecycle,
)
from finco_radar.venues.observations import (
    FreshnessState, MarketObservation, ObservationStatus,
)
from finco_radar.venues.store import VenueMarketStore
from tests.test_tokenized_markets_composition import _entry, _registry

NOW = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
VENUE = "robinhood-chain"
CONTRACT = "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"
TYPE = "tokenized-equity"


@pytest.fixture(autouse=True)
def canonical_threshold(monkeypatch):
    monkeypatch.delenv("FINCO_TOKENIZED_DISLOCATION_THRESHOLD_BPS", raising=False)
    monkeypatch.delenv("FINCO_TOKENIZED_MARKET_MAX_AGE_SECONDS", raising=False)


@pytest.fixture
def store(tmp_path):
    return VenueMarketStore(str(tmp_path / "venue.sqlite"))


def _row(seconds_before: int, price: str, *, contract: str = CONTRACT,
         state=FreshnessState.AVAILABLE, status=ObservationStatus.OK,
         reference: str | None = "100", reference_clock: str | None = None,
         payload: dict | None = None, collected_offset_seconds: int = 1) -> MarketObservation:
    ts = NOW - timedelta(seconds=seconds_before)
    return MarketObservation(
        ts=ts.isoformat(), collected_at=(ts + timedelta(
            seconds=collected_offset_seconds)).isoformat(),
        canonical_asset_id="NVDA", venue_id=VENUE, instrument_id=contract,
        instrument_type=TYPE, price=price, reference_price=reference,
        source="fixture-reviewed-tokenized-market",
        freshness_state=state, observation_status=status,
        payload={
            "reference_state": "AVAILABLE" if reference is not None else "UNAVAILABLE",
            "reference_observed_at": (reference_clock if reference_clock is not None
                                       else ts.isoformat()),
            "comparison_unit": "USD_PER_TOKENIZED_SHARE_EQUIVALENT",
            **(payload or {}),
        },
    )


def _project(store, *, registry=None, now=NOW, asset="NVDA",
             include_no_change=False, max_events=60):
    return build_tokenized_signal_lifecycle(
        asset, registry=registry or _registry([_entry()]), store=store,
        as_of=now, include_no_change=include_no_change, max_events=max_events)


def _append(store, *rows):
    for row in rows:
        store.append_observation(row)


def _kinds(feed):
    return [e.kind for e in feed.events]


def test_proven_appearance_reuses_crossing_and_provenance(store):
    before = _row(120, "100")
    after = _row(60, "102")
    _append(store, before, after)
    result = _project(store)
    assert _kinds(result) == [LifecycleKind.DISLOCATION_APPEARED]
    event = result.events[0]
    assert event.previous_classification == "WITHIN_THRESHOLD"
    assert event.current_classification == "PREMIUM_DISLOCATION"
    assert event.proven_crossing_source_timestamp == after.ts
    assert event.source_observed_at == after.ts
    assert event.source_observed_at != after.collected_at
    assert event.prior_observation_digest == before.resolved_digest()
    assert event.current_observation_digest == after.resolved_digest()
    assert event.threshold_bps == "100"
    assert event.identity.contract_address == CONTRACT
    assert event.identity.chain_id == 4663
    assert event.continuity_state == "ADJACENT_OBSERVATIONS_ONLY"
    assert event.eligible_for_future_alert
    assert not result.notifications_enabled
    assert result.current_deepstate_signals == "UNAVAILABLE"
    assert result.policy_version == CONTRACT_VERSION
    with pytest.raises(FrozenInstanceError):
        event.kind = LifecycleKind.DISLOCATION_CLEARED


def test_deterministic_identity_repeated_reads_and_dedup(store):
    before, after = _row(100, "100"), _row(30, "103")
    _append(store, before, after)
    assert store.append_observation(after)[1] is False
    x, y = _project(store), _project(store)
    assert x == y
    assert x.events[0].event_id == y.events[0].event_id
    assert len(x.events[0].event_id) == 64


def test_clearing_and_sign_reversal_are_independent_real_events(store):
    _append(store,
            _row(200, "100"), _row(150, "102"),
            _row(100, "99"), _row(30, "100.2"))
    result = _project(store)
    assert _kinds(result) == [
        LifecycleKind.DISLOCATION_APPEARED,
        LifecycleKind.DISLOCATION_DIRECTION_CHANGED,
        LifecycleKind.DISLOCATION_CLEARED,
    ]
    assert result.events[1].previous_classification == "PREMIUM_DISLOCATION"
    assert result.events[1].current_classification == "DISCOUNT_DISLOCATION"
    assert result.events[-1].current_classification == "WITHIN_THRESHOLD"
    assert result.events[-1].eligible_for_future_alert


def test_observation_based_persistence_is_not_wall_clock_uptime(store):
    _append(store, _row(220, "100"), _row(180, "102"), _row(35, "103"))
    feed = _project(store)
    assert _kinds(feed) == [
        LifecycleKind.DISLOCATION_APPEARED,
        LifecycleKind.DISLOCATION_PERSISTENCE_UPDATED,
    ]
    last = feed.events[-1]
    assert last.persistence_start_state == "PROVEN_CROSSING"
    assert last.proven_crossing_source_timestamp == (NOW-timedelta(seconds=180)).isoformat()
    assert last.observed_span_seconds == 145
    assert last.continuity_state == "ADJACENT_OBSERVATIONS_ONLY"
    assert last.suppression_reason == "FACTUAL_CONTEXT_ONLY"


def test_initial_dislocation_has_unknown_prior_not_appeared(store):
    _append(store, _row(20, "103"))
    feed = _project(store)
    assert feed.events == ()
    diagnostic = _project(store, include_no_change=True)
    assert _kinds(diagnostic) == [LifecycleKind.NO_MATERIAL_CHANGE]
    assert diagnostic.events[0].previous_classification == "UNKNOWN_PRIOR"
    assert diagnostic.events[0].persistence_start_state == "PREHISTORY_UNAVAILABLE"


def test_missing_reference_is_evidence_gap_not_economic_clearing(store):
    _append(store, _row(200, "100"), _row(150, "102"),
            _row(100, "103", reference=None), _row(20, "103"))
    feed = _project(store)
    assert _kinds(feed) == [
        LifecycleKind.DISLOCATION_APPEARED,
        LifecycleKind.EVIDENCE_BECAME_UNAVAILABLE,
        LifecycleKind.EVIDENCE_RECOVERED,
    ]
    assert LifecycleKind.DISLOCATION_CLEARED not in _kinds(feed)
    assert not feed.events[-1].eligible_for_future_alert
    assert feed.events[-1].continuity_state == "GAP_OR_UNKNOWN"


def test_stale_current_evidence_suppresses_dislocation_economics(store):
    before = _row(3600, "100")
    after = _row(1800, "102")
    _append(store, before, after)
    feed = _project(store)
    assert _kinds(feed) == [LifecycleKind.EVIDENCE_BECAME_STALE]
    e = feed.events[-1]
    assert e.current_classification == "STALE"
    assert e.evidence_state == "STALE"
    assert e.temporal_classification == "CURRENT"
    assert not e.eligible_for_future_alert
    assert e.kind is not LifecycleKind.DISLOCATION_CLEARED
    assert e.source_observed_at == after.ts


def test_explicit_stale_row_is_evidence_transition_not_clear(store):
    _append(store, _row(140, "102"), _row(20, "100", state=FreshnessState.STALE))
    result = _project(store)
    assert _kinds(result) == [LifecycleKind.EVIDENCE_BECAME_STALE]
    assert not result.events[0].eligible_for_future_alert


def test_quarantined_row_never_generates_events_or_spurious_appearance(store):
    _append(store, _row(200, "100"), _row(150, "102", status=ObservationStatus.QUARANTINED),
            _row(30, "103"))
    feed = _project(store)
    assert not any(e.kind == LifecycleKind.DISLOCATION_APPEARED for e in feed.events)
    assert all(e.current_observation_digest != _row(
        150, "102", status=ObservationStatus.QUARANTINED).resolved_digest() for e in feed.events)


def test_same_ticker_other_contract_has_independent_episode(store):
    other_contract = "0x" + "cd" * 20
    _append(store,
            _row(220, "100"), _row(50, "102"),
            _row(190, "100", contract=other_contract),
            _row(60, "99", contract=other_contract))
    registry = _registry([_entry(), _entry(
        contract_address=other_contract, representation_symbol="NVDA_ALT")])
    feed = _project(store, registry=registry)
    appeared = [x for x in feed.events if x.kind == LifecycleKind.DISLOCATION_APPEARED]
    assert len(appeared) == 2
    assert {x.identity.instrument_id for x in appeared} == {CONTRACT, other_contract}
    assert all(x.prior_observation_digest is not None for x in appeared)


def test_equal_clock_different_digest_never_proves_causal_crossing(store):
    a = _row(60, "100")
    b = _row(60, "102")
    _append(store, a, b)
    feed = _project(store)
    assert not any(e.kind in (
        LifecycleKind.DISLOCATION_APPEARED,
        LifecycleKind.DISLOCATION_DIRECTION_CHANGED,
        LifecycleKind.DISLOCATION_CLEARED) for e in feed.events)
    assert any(e.basis_reason == "SOURCE_TIMESTAMP_COLLISION" for e in feed.events)


def test_out_of_order_provider_rows_do_not_create_false_economic_crossing(store, monkeypatch):
    # Simulate a corrupt store read order; the persisted store is ordered.
    earlier = _row(180, "100")
    later = _row(60, "102")
    _append(store, earlier, later)
    monkeypatch.setattr(store, "get_window_for_identity",
                        lambda *args, **kwargs: [later, earlier])
    feed = _project(store)
    assert not any(e.kind == LifecycleKind.DISLOCATION_APPEARED for e in feed.events)
    assert any(e.basis_reason == "SOURCE_TIME_ORDER_INVALID" for e in feed.events)


def test_existing_distribution_is_attached_but_insufficient_is_explicit(store):
    _append(store, _row(110, "100"), _row(20, "102"))
    event = _project(store).events[0]
    assert event.distribution.state == "INSUFFICIENT_HISTORY"
    assert event.distribution.usable_observation_count == 2
    assert event.eligible_for_future_alert  # no percentile/profit ranking


def test_distribution_reuses_183_histogram_and_percentile(store):
    for i in range(10):
        _append(store, _row(80 + (9-i)*480,
                            "100" if i == 0 else str(102 + i/10)))
    result = _project(store)
    assert len(result.events) > 0
    context = result.events[-1].distribution
    assert context.state == "AVAILABLE"
    assert context.usable_observation_count >= 8
    assert context.history_span_seconds >= 3600
    assert context.median_basis_bps is not None
    assert context.current_basis_percentile is not None


def test_malformed_lineage_and_wrong_chain_never_emit_valid_signal(store):
    bad = _row(50, "102", payload={"chain_id": 1})
    _append(store, _row(150, "100"), bad)
    assert not any(e.kind == LifecycleKind.DISLOCATION_APPEARED
                   for e in _project(store).events)
    with pytest.raises(KeyError):
        _project(store, asset="UNKNOWN")
    wrong = _registry([_entry(chain_id=1)])
    feed = _project(store, registry=wrong)
    assert not any(e.kind == LifecycleKind.DISLOCATION_APPEARED for e in feed.events)


def test_deepstate_payload_never_activates_a_current_tokenized_signal(store):
    _append(store, _row(120, "100"), _row(
        20, "102", payload={"deepstate_freshness_policy": "NOT_YET_APPROVED"}))
    assert not any(e.kind == LifecycleKind.DISLOCATION_APPEARED
                   for e in _project(store).events)


def test_history_bounds_output_limit_and_no_interpolation(store):
    _append(store, _row(8 * 86400, "100"))  # outside #183 seven-day window
    for i in range(350):
        seconds = 900 + (349 - i) * 2
        price = "100" if i % 2 == 0 else "102"
        _append(store, _row(seconds, price))
    feed = _project(store, max_events=5)
    assert HISTORY_WINDOW == timedelta(days=7)
    assert MAX_OBSERVATIONS_PER_REPRESENTATION == 256
    assert MAX_FEED_EVENTS == 60
    assert feed.source_observations_examined == 256
    assert len(feed.events) <= 5
    assert all(e.source_observed_at >= (NOW-HISTORY_WINDOW).isoformat()
               for e in feed.events)
    with pytest.raises(ValueError):
        _project(store, max_events=61)


def test_read_path_has_no_provider_calls_no_write_and_no_notifications(store, monkeypatch):
    _append(store, _row(100, "100"), _row(20, "102"))
    count = store.count()
    def forbidden(*args, **kwargs):
        raise AssertionError("R5_LIFECYCLE_READ_SIDE_EFFECT_FORBIDDEN")
    monkeypatch.setattr(VenueMarketStore, "append_observation", forbidden)
    monkeypatch.setattr(VenueMarketStore, "append_many", forbidden)
    monkeypatch.setattr(VenueMarketStore, "append_many_batched", forbidden)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    feed = _project(store)
    assert store.count() == count
    assert not feed.notifications_enabled
    assert _kinds(feed) == [LifecycleKind.DISLOCATION_APPEARED]


def test_frozen_namespaces_and_parallel_r4_isolation():
    from finance_integrity_governance import strictly_frozen_changes
    from model_v2_governance import model_v2_frozen_violations
    assert strictly_frozen_changes() == []
    assert model_v2_frozen_violations() == []
