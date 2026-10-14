"""R3 historical Deepstate composition: exact proof, no implicit USDG parity.

Deterministic, network-free tests use the already reviewed on-chain fill fixture
and canonical R-LIVE market-clock fixture. No collector or financial change.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.crypto_terminal.deepstate_composition import (
    CURRENT_CROSS_VENUE, RAW_COMPARISON_UNIT,
    ReviewedNormalizationPolicy, build_deepstate_historical_context,
)
from finco_radar.authority.r_live_policy import (
    APPROVED_BY_CANONICAL_ID, QUOTE_AUTHORITY_VERSION,
)
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_CHAIN_ID, DEEPSTATE_POOL_ID, DEEPSTATE_ROUTER,
)
from finco_radar.venues.observations import FreshnessState, ObservationStatus
from finco_radar.venues.store import VenueMarketStore
from tests.test_radar_deepstate_nvda_market import (
    BLOCK_TIME, COLLECTED, _observations,
)
from tests.test_tokenized_market_evidence_clocks import evidence
from tests.test_tokenized_markets_composition import _entry, _registry


NOW = COLLECTED + timedelta(minutes=30)
NVDA_POLICY = next(p for p in APPROVED_BY_CANONICAL_ID.values()
                   if p.symbol == "NVDA")
CANDIDATE_POLICY = ReviewedNormalizationPolicy(
    source_authority=QUOTE_AUTHORITY_VERSION, max_quote_age_seconds=60)


@pytest.fixture
def store(tmp_path):
    return VenueMarketStore(tmp_path / "market.db")


def _read(store, *, registry=None, policy=None, asset="NVDA"):
    return build_deepstate_historical_context(
        asset, registry=registry or _registry([_entry()]), store=store,
        as_of=NOW, normalization_policy=policy)


def _fill(**changes):
    row = _observations()
    if changes:
        row = replace(row, payload={**row.payload, **changes})
    return row


def _normalized(row=None, *, rate="1.01", quote_at=BLOCK_TIME, source=True):
    row = row or _fill()
    p = dict(row.payload)
    p.update(usdg_usd_value=str(rate),
             usdg_usd_timestamp=quote_at.isoformat())
    if source:
        p.update(
            usdg_usd_source=QUOTE_AUTHORITY_VERSION,
            usdg_usd_feed_address=NVDA_POLICY.pool.quote_feed_address,
            usdg_usd_chain_id=DEEPSTATE_CHAIN_ID,
            usdg_usd_evidence_block_hash="0x" + "ab" * 32,
            usdg_usd_evidence_id="reviewed-test-source:quote-1",
        )
    return replace(row, payload=p)


def _rlive(stamp=BLOCK_TIME):
    row, _data = evidence(
        market=stamp, quote=stamp, activity=stamp,
        reference=stamp, collected=COLLECTED)
    assert row is not None
    return row


def test_true_historical_fill_is_proven_but_never_current(store):
    original = _fill()
    store.append_observation(original)
    context = _read(store)
    assert context.state == "HISTORICAL_EXECUTION_PROVEN"
    assert context.current_cross_venue_state == CURRENT_CROSS_VENUE == "UNAVAILABLE"
    assert context.current_executable_quote_state == "UNAVAILABLE"
    assert len(context.evidence) == 1
    fill = context.evidence[0]
    assert fill.evidence_state == "HISTORICAL_EXECUTION_PROVEN"
    assert fill.normalization_state == "MISSING_NORMALIZATION_EVIDENCE"
    assert fill.raw_unit == RAW_COMPARISON_UNIT == "USDG_PER_NVDA"
    assert fill.raw_price == original.price
    assert fill.execution_timestamp == BLOCK_TIME.isoformat()
    assert fill.collected_at == COLLECTED.isoformat()
    assert fill.block_number == original.payload["block_number"]
    assert fill.block_hash == original.payload["block_hash"]
    assert fill.transaction_hash == original.payload["transaction_hash"]
    assert fill.log_index == original.payload["log_index"]
    assert fill.match_index == 0
    assert context.historical_comparisons[0].reason == "MISSING_NORMALIZATION_EVIDENCE"
    assert context.historical_comparisons[0].divergence_bps is None
    with pytest.raises(FrozenInstanceError):
        fill.raw_price = "999"


def test_unknown_underlying_or_wrong_exact_representation_rejected(store):
    store.append_observation(_fill())
    assert _read(store, asset="AAPL").reason == "EXACT_IDENTITY_UNAVAILABLE"
    assert _read(store, asset="NVDA " ).reason == "EXACT_IDENTITY_UNAVAILABLE"
    wrong = _registry([_entry(contract_address="0x" + "11" * 20)])
    assert _read(store, registry=wrong).reason == "EXACT_IDENTITY_UNAVAILABLE"
    wrong_chain = _registry([_entry(chain_id=1)])
    assert _read(store, registry=wrong_chain).reason == "EXACT_IDENTITY_UNAVAILABLE"


@pytest.mark.parametrize("bad", [
    {"chain_id": 1},
    {"router": "0x" + "11" * 20},
    {"book_id": "0x" + "00" * 32},
    {"pool_id": "0x" + "00" * 32},
    {"deepstate_execution_timestamp": "2026-10-05T12:00:00+00:00"},
    {"transaction_hash": "invalid"},
    {"block_hash": "invalid"},
    {"block_number": -1},
    {"log_index": -1},
    {"match_index": -1},
    {"event_type": "Transfer"},
    {"deepstate_freshness_policy": "APPROVED"},
])
def test_invalid_or_wrong_contract_provenance_fails_closed(store, bad):
    store.append_observation(_fill(**bad))
    context = _read(store)
    assert context.evidence[0].evidence_state == "INVALID_MARKET_EVIDENCE"
    assert context.historical_comparisons[0].reason == "INVALID_MARKET_EVIDENCE"


def test_unknown_pool_cannot_be_selected(store):
    row = replace(_fill(), instrument_id="0x" + "ab" * 32)
    store.append_observation(row)
    assert _read(store).evidence == ()


@pytest.mark.parametrize("invalid_price", ["0", "-1", "NaN", "Infinity"])
def test_invalid_execution_price_never_comparable(store, invalid_price):
    if invalid_price in ("NaN", "Infinity"):
        # MarketObservation itself rejects non-finite data.
        with pytest.raises(ValueError):
            replace(_fill(), price=invalid_price)
        return
    store.append_observation(replace(_fill(), price=invalid_price))
    assert _read(store).evidence[0].evidence_state == "INVALID_MARKET_EVIDENCE"


def test_multiple_matches_keep_exact_identities_and_order(store):
    one = _fill()
    two = replace(one, payload={**one.payload, "match_index": 1})
    store.append_observation(one)
    store.append_observation(two)
    context = _read(store)
    assert len(context.evidence) == 2
    assert {e.match_index for e in context.evidence} == {0, 1}
    assert len({e.digest for e in context.evidence}) == 2
    assert {e.execution_timestamp for e in context.evidence} == {one.ts}


def test_source_clock_not_collection_clock_and_no_future_collection(store):
    store.append_observation(_fill())
    assert _read(store).evidence[0].execution_timestamp == BLOCK_TIME.isoformat()
    late = replace(_fill(), collected_at=(NOW + timedelta(days=1)).isoformat(),
                   payload={**_fill().payload, "match_index": 5})
    store.append_observation(late)
    assert len(_read(store).evidence) == 1


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "Infinity", "not-a-number"])
def test_bad_normalization_rate_fails_closed(store, rate):
    store.append_observation(_normalized(rate=rate))
    assert _read(store, policy=CANDIDATE_POLICY).evidence[0].normalized_usd_price is None


def test_no_usdg_parity_and_no_unapproved_normalization_even_with_rate(store):
    store.append_observation(_normalized())
    context = _read(store)
    assert context.evidence[0].normalization_state == "NORMALIZATION_POLICY_UNAPPROVED"
    assert context.evidence[0].normalized_usd_price is None
    assert context.historical_comparisons[0].divergence_bps is None


def test_missing_provenance_cannot_normalize_even_with_candidate_policy(store):
    store.append_observation(_normalized(source=False))
    assert _read(store, policy=CANDIDATE_POLICY).evidence[0].normalization_state == (
        "MISSING_NORMALIZATION_EVIDENCE")


def test_stale_or_future_normalization_rejected(store):
    store.append_observation(_normalized(quote_at=BLOCK_TIME - timedelta(seconds=61)))
    assert _read(store, policy=CANDIDATE_POLICY).evidence[0].normalization_state == (
        "NORMALIZATION_OUTSIDE_APPROVED_TIME_POLICY")
    # The second case needs no database mutation of the first evidence.
    fresh = _normalized(quote_at=BLOCK_TIME + timedelta(seconds=1))
    from app.crypto_terminal.deepstate_composition import _normalization
    assert _normalization(fresh, CANDIDATE_POLICY,
                          NVDA_POLICY.pool.quote_feed_address)[0] == (
                              "NORMALIZATION_OUTSIDE_APPROVED_TIME_POLICY")


def test_reviewed_hypothetical_policy_allows_historical_comparison_only(store):
    fill = _normalized()
    store.append_observation(fill)
    store.append_observation(_rlive())
    context = _read(store, policy=CANDIDATE_POLICY)
    ev = context.evidence[0]
    pair = context.historical_comparisons[0]
    assert ev.normalization_state == "AVAILABLE"
    assert Decimal(ev.normalized_usd_price) == Decimal(fill.price) * Decimal("1.01")
    assert pair.state == "HISTORICAL_COMPARISON_AVAILABLE"
    assert pair.reason is None
    assert pair.rlive_market_timestamp == BLOCK_TIME.isoformat()
    assert pair.source_skew_seconds == "0.0"
    assert pair.rlive_digest is not None
    assert pair.divergence_bps is not None
    assert pair.original_deepstate_unit == RAW_COMPARISON_UNIT
    assert context.current_cross_venue_state == "UNAVAILABLE"
    assert context.current_executable_quote_state == "UNAVAILABLE"


def test_300_second_skew_boundary_never_expands(store):
    from finco_radar.venues.basis import BASIS_MAX_CLOCK_SKEW_SECONDS
    assert BASIS_MAX_CLOCK_SKEW_SECONDS == 300
    store.append_observation(_normalized())
    store.append_observation(_rlive(BLOCK_TIME + timedelta(seconds=301)))
    context = _read(store, policy=CANDIDATE_POLICY)
    assert context.historical_comparisons[0].reason == "SOURCE_TIME_SKEW_EXCEEDED"
    assert context.historical_comparisons[0].divergence_bps is None


def test_wrong_rlive_economic_uid_and_unit_not_comparable(store):
    store.append_observation(_normalized())
    rlive = _rlive()
    bad = replace(rlive, payload={**rlive.payload, "economic_asset_uid": "wrong"})
    store.append_observation(bad)
    assert _read(store, policy=CANDIDATE_POLICY).historical_comparisons[0].state == (
        "HISTORICAL_COMPARISON_UNAVAILABLE")
    good_unit_bad = replace(rlive, payload={**rlive.payload, "comparison_unit": RAW_COMPARISON_UNIT})
    store.append_observation(good_unit_bad)
    result = _read(store, policy=CANDIDATE_POLICY)
    assert result.historical_comparisons[0].reason == "COMPARISON_UNIT_MISMATCH"
    assert all(p.divergence_bps is None for p in result.historical_comparisons)


def test_no_database_writes_or_fake_registry_representation(store, monkeypatch):
    store.append_observation(_fill())
    registry = _registry([_entry()])
    before = store.count()
    from finco_radar.venues.store import VenueMarketStore
    def fail_write(*args, **kwargs):
        raise AssertionError("READ_MODEL_DATABASE_WRITE_FORBIDDEN")
    monkeypatch.setattr(VenueMarketStore, "append_observation", fail_write)
    monkeypatch.setattr(VenueMarketStore, "append_many", fail_write)
    assert _read(store, registry=registry).state == "HISTORICAL_EXECUTION_PROVEN"
    assert store.count() == before
    assert len(registry.representations_for_underlying("NVDA")) == 1


def test_no_frozen_namespace_delta_on_branch():
    from finance_integrity_governance import strictly_frozen_changes
    from model_v2_governance import model_v2_frozen_violations
    from rc3_historical_anchor import changed_paths as _anchored
    assert strictly_frozen_changes(_anchored()) == []
    assert model_v2_frozen_violations(_anchored()) == []


def test_historical_300s_inclusive_boundary(store):
    store.append_observation(_normalized())
    store.append_observation(_rlive(BLOCK_TIME + timedelta(seconds=300)))
    result = _read(store, policy=CANDIDATE_POLICY)
    assert result.historical_comparisons[0].state == "HISTORICAL_COMPARISON_AVAILABLE"
    assert result.historical_comparisons[0].source_skew_seconds == "300.0"
    assert result.current_cross_venue_state == "UNAVAILABLE"


def test_malformed_normalization_time_and_cached_inconsistency_fail_closed(store):
    from app.crypto_terminal.deepstate_composition import _normalization
    bad_clock = replace(_normalized(), payload={**_normalized().payload,
                         "usdg_usd_timestamp": "not-a-clock"})
    assert _normalization(bad_clock, CANDIDATE_POLICY,
                          NVDA_POLICY.pool.quote_feed_address)[0] == (
                              "MISSING_NORMALIZATION_EVIDENCE")
    wrong_cached = replace(_normalized(), payload={**_normalized().payload,
                           "normalized_usd_price": "1"})
    assert _normalization(wrong_cached, CANDIDATE_POLICY,
                          NVDA_POLICY.pool.quote_feed_address)[0] == (
                              "INVALID_MARKET_EVIDENCE")


def test_deepstate_bad_execution_block_timestamp_distinct_from_collection(store):
    earlier = _fill()
    second_ts = BLOCK_TIME + timedelta(seconds=12)
    second = replace(earlier, ts=second_ts.isoformat(),
                     payload={**earlier.payload,
                              "deepstate_execution_timestamp": second_ts.isoformat(),
                              "block_number": earlier.payload["block_number"] + 1,
                              "block_hash": "0x" + "f0" * 32})
    store.append_observation(earlier)
    store.append_observation(second)
    result = _read(store)
    assert {x.execution_timestamp for x in result.evidence} == {
        earlier.ts, second.ts}
    assert {x.block_number for x in result.evidence} == {
        earlier.payload["block_number"], second.payload["block_number"]}


def test_execution_price_must_reconcile_to_canonical_raw_fill(store):
    corrupted = replace(_fill(), price="1234")
    store.append_observation(corrupted)
    result = _read(store)
    assert result.evidence[0].evidence_state == "INVALID_MARKET_EVIDENCE"
    assert result.historical_comparisons[0].divergence_bps is None
