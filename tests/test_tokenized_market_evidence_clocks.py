"""Forward-only R-LIVE token MARKET / oracle / reference clock regressions.

No RPC calls. No historical rewrites. #179 skew policy stays at 300 seconds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.radar_rwa.r_live_service import format_r_live_result
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.basis import BASIS_MAX_CLOCK_SKEW_SECONDS, basis_for_evidence
from finco_radar.venues.intelligence import (
    _basis_from_observation, effective_observation_state,
)
from finco_radar.venues.robinhood_live import (
    EVIDENCE_CLOCK_CONTRACT, market_observation_from_r_live,
)
from finco_radar.venues.store import VenueMarketStore
from tests.test_tokenized_live_intelligence_v1 import (
    NVDA_ID, NOW, _entry, _live_data, _registry,
)


def evidence(*, market=None, quote=None, reference=None, activity=None,
             block_number=100, price="102", collected=None):
    market = market or NOW - timedelta(seconds=30)
    quote = quote or market - timedelta(hours=23)
    activity = activity or market - timedelta(seconds=20)
    reference = reference or market + timedelta(seconds=10)
    data = _live_data(NVDA_ID, stamp=market, token_price=price)
    data["token_reference"]["observed_at"] = min(
        market, activity, quote).isoformat()
    clocks = data["token_reference"]["source_evidence"]
    clocks.update({
        "blockTimestamp": market.isoformat(),
        "dexWindowEndAt": market.isoformat(),
        "dexWindowStartAt": (market - timedelta(seconds=300)).isoformat(),
        "lastPoolActivityAt": activity.isoformat(),
        "quoteUpdatedAt": quote.isoformat(),
        "effectiveObservedAt": min(market, activity, quote).isoformat(),
        "blockNumber": block_number,
        "blockHash": "0x" + f"{block_number:064x}",
    })
    data["robinhood_basis"]["observed_at"] = reference.isoformat()
    observation = market_observation_from_r_live(
        canonical_id=NVDA_ID, state="AVAILABLE", data=data,
        registry=_registry([_entry()]), collected_at=collected or NOW)
    return observation, data


def test_market_clock_does_not_inherit_23h_old_oracle():
    obs, data = evidence()
    market = data["token_reference"]["source_evidence"]["dexWindowEndAt"]
    oracle = data["token_reference"]["source_evidence"]["quoteUpdatedAt"]
    assert obs is not None
    assert obs.ts == market
    assert obs.payload["market_observed_at"] == market
    assert obs.payload["normalization_oracle_observed_at"] == oracle
    assert obs.payload["last_pool_activity_at"] != market
    assert obs.payload["effective_evidence_at"] == oracle
    assert obs.payload["reference_observed_at"] == data["robinhood_basis"]["observed_at"]
    assert obs.payload["evidence_clock_contract"] == EVIDENCE_CLOCK_CONTRACT
    assert obs.collected_at == NOW.isoformat()
    assert obs.ts != oracle != obs.collected_at
    assert effective_observation_state(obs, as_of=NOW) == "AVAILABLE"


def test_exact_basis_keeps_300s_policy_with_old_valid_oracle():
    obs, _ = evidence()
    assert BASIS_MAX_CLOCK_SKEW_SECONDS == 300
    assert obs is not None
    assert _basis_from_observation(obs) == ("200", None)


def test_basis_rejects_market_reference_skew_over_300s():
    obs, data = evidence(reference=NOW + timedelta(seconds=301))
    assert obs is not None
    assert _basis_from_observation(obs) == (None, "EVIDENCE_SKEW_EXCEEDS_POLICY")
    assert basis_for_evidence(
        representation_price=obs.price, representation_state="AVAILABLE",
        representation_source_timestamp=obs.ts,
        reference_price=obs.reference_price, reference_state="AVAILABLE",
        reference_source_timestamp=data["robinhood_basis"]["observed_at"],
    )[1] == "EVIDENCE_SKEW_EXCEEDS_POLICY"


def test_fail_closed_missing_malformed_or_conflicting_market_evidence():
    _, original = evidence()
    for key, bad in (
        ("dexWindowEndAt", None),
        ("blockTimestamp", "not-an-iso-date"),
        ("quoteUpdatedAt", None),
        ("lastPoolActivityAt", "2026-10-10T00:00:00"),
        ("twapWindowSeconds", 42),
        ("blockHash", "0xnot-a-hash"),
    ):
        import copy
        data = copy.deepcopy(original)
        data["token_reference"]["source_evidence"][key] = bad
        assert market_observation_from_r_live(
            canonical_id=NVDA_ID, state="AVAILABLE", data=data,
            registry=_registry([_entry()]), collected_at=NOW) is None
    import copy
    data = copy.deepcopy(original)
    data["token_reference"]["source_evidence"].pop("dexWindowEndAt")
    assert market_observation_from_r_live(
        canonical_id=NVDA_ID, state="AVAILABLE", data=data,
        registry=_registry([_entry()]), collected_at=NOW) is None
    data = copy.deepcopy(original)
    data["token_reference"]["source_evidence"]["effectiveObservedAt"] = NOW.isoformat()
    assert market_observation_from_r_live(
        canonical_id=NVDA_ID, state="AVAILABLE", data=data,
        registry=_registry([_entry()]), collected_at=NOW) is None


def test_oracle_heartbeat_is_enforced_without_becoming_market_clock():
    p = APPROVED_BY_CANONICAL_ID[NVDA_ID]
    old_quote = NOW - timedelta(seconds=p.max_quote_age_seconds - 60)
    obs, _ = evidence(quote=old_quote)
    assert obs is not None
    assert effective_observation_state(obs, as_of=NOW) == "AVAILABLE"
    assert effective_observation_state(
        obs, as_of=NOW + timedelta(seconds=61)) == "STALE"
    invalid, _ = evidence(quote=NOW - timedelta(seconds=p.max_quote_age_seconds + 60))
    assert invalid is None


def test_collected_at_never_substitutes_source_time_or_changes_digest():
    a, _ = evidence()
    b, _ = evidence(collected=NOW + timedelta(minutes=5))
    assert a is not None and b is not None
    assert a.ts == b.ts
    assert a.payload == b.payload
    assert a.resolved_digest() == b.resolved_digest()


def test_true_pinned_market_identity_and_append_only_deduplication(tmp_path):
    store = VenueMarketStore(tmp_path / "market.db")
    first, _ = evidence()
    repeat, _ = evidence(collected=NOW + timedelta(minutes=3))
    assert first is not None
    assert repeat is not None
    # Both market samples share a single old Chainlink normalization clock.
    # Pin the same oracle across distinct TWAPs rather than synthesizing it.
    original_oracle = datetime.fromisoformat(first.payload["normalization_oracle_observed_at"])
    second, _ = evidence(market=NOW - timedelta(seconds=20), block_number=101,
                         quote=original_oracle, price="103")
    assert second is not None
    assert second.ts != first.ts
    assert second.payload["normalization_oracle_observed_at"] == first.payload["normalization_oracle_observed_at"]
    assert store.append_observation(first)[1] is True
    assert store.append_observation(repeat)[1] is False
    assert store.append_observation(second)[1] is True
    assert store.count() == 2
    assert first.payload["market_block_hash"] != second.payload["market_block_hash"]


def test_legacy_rows_remain_immutable_and_evaluated_on_original_clock(tmp_path):
    from dataclasses import replace
    obs, _ = evidence()
    assert obs is not None
    old = replace(
        obs, ts=obs.payload["effective_evidence_at"],
        payload={"authority": "R_LIVE", "reference_state": "AVAILABLE",
                 "reference_observed_at": obs.payload["reference_observed_at"]},
        digest=None)
    store = VenueMarketStore(tmp_path / "legacy.db")
    old_digest, created = store.append_observation(old)
    assert created
    new_digest, created = store.append_observation(obs)
    assert created and new_digest != old_digest
    legacy = store.get_latest_for_instrument(
        old.instrument_id, venue_id=old.venue_id)
    # The store contains both, and legacy timestamp has not been restamped.
    assert store.count() == 2
    assert _basis_from_observation(old)[1] == "EVIDENCE_SKEW_EXCEEDS_POLICY"
    assert old.ts == obs.payload["effective_evidence_at"]
    assert legacy.ts == obs.ts


def test_r_live_formatter_transmits_only_reviewed_source_evidence():
    raw, data = evidence()
    assert raw is not None
    clocks = data["token_reference"]["source_evidence"]
    onchain = SimpleNamespace(
        state=AuthorityState.AVAILABLE,
        observed_at=datetime.fromisoformat(clocks["effectiveObservedAt"]),
        evidence={**clocks, "retrievedAt": NOW.isoformat()})
    token = SimpleNamespace(state=AuthorityState.AVAILABLE,
                            price_usd_per_token=Decimal("102"),
                            source="UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
                            observed_at=onchain.observed_at, reason=None)
    underlying = SimpleNamespace(state=AuthorityState.AVAILABLE,
                                 price_usd_per_token=Decimal("100"),
                                 source="ROBINHOOD_STOCK_TOKEN_REFERENCE",
                                 observed_at=datetime.fromisoformat(
                                     data["robinhood_basis"]["observed_at"]),
                                 reason=None)
    premium = SimpleNamespace(state=AuthorityState.AVAILABLE,
                              value_bps=Decimal("200"), formula="test",
                              reason=None)
    result = SimpleNamespace(
        authority=SimpleNamespace(
            economic_asset_uid=APPROVED_BY_CANONICAL_ID[NVDA_ID].economic_asset_uid,
            token=token, underlying=underlying, premium=premium),
        onchain=onchain)
    state, output = format_r_live_result(NVDA_ID, result)
    assert state == "AVAILABLE"
    assert output["token_reference"]["source_evidence"]["quoteUpdatedAt"] == clocks["quoteUpdatedAt"]
    assert output["token_reference"]["source_evidence"]["dexWindowEndAt"] == clocks["dexWindowEndAt"]
    assert "retrievedAt" not in output["token_reference"]["source_evidence"]
    normalized = market_observation_from_r_live(
        canonical_id=NVDA_ID, state=state, data=output,
        registry=_registry([_entry()]), collected_at=NOW)
    assert normalized is not None
    assert normalized.ts == clocks["dexWindowEndAt"]
