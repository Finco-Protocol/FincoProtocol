"""Offline semantic coverage for R5 signals, evidence and history."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import AssetKey
from finco_radar.history.contracts import HistoryError, HistoryStatus, SignalChangeKind
from finco_radar.history.engine import build_history_entry, compare_signal_snapshots, validate_history_series
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.reference_state.contracts import ReferenceStateReason
from finco_radar.signals.contracts import (
    GapDirection, SignalAuthorityState, SignalComputationError, SignalPolicy,
    SignalStatus, SizePersistenceState, SpreadState,
)
from finco_radar.signals.engine import build_signal_snapshot
from tests.test_radar_r3_liquidity import build as build_r3
from tests.test_radar_r4_reference_state import build as build_r4


POLICY = SignalPolicy(Decimal("50"), Decimal("500"), Decimal("100"), Decimal("120"), Decimal("25"))


def snapshot(*, buy=("60", "70"), sell=("-60", "-70"), r3=None, r4=None, policy=POLICY):
    r3 = r3 or build_r3()
    buy_side = replace(r3.buy,
        small_gap_observation=replace(r3.buy.small_gap_observation, gap_bps=Decimal(buy[0])),
        large_gap_observation=replace(r3.buy.large_gap_observation, gap_bps=Decimal(buy[1])),
        directional_gap_delta_bps=Decimal(buy[1]) - Decimal(buy[0]))
    sell_side = replace(r3.sell,
        small_gap_observation=replace(r3.sell.small_gap_observation, gap_bps=Decimal(sell[0])),
        large_gap_observation=replace(r3.sell.large_gap_observation, gap_bps=Decimal(sell[1])),
        directional_gap_delta_bps=Decimal(sell[1]) - Decimal(sell[0]))
    return build_signal_snapshot(r3=replace(r3, buy=buy_side, sell=sell_side), r4=r4 or build_r4(), policy=policy)


def test_identity_and_exact_lineage_pass():
    assert snapshot().status is SignalStatus.SIGNALS_OK


@pytest.mark.parametrize("field,value", [("asset_uid", "0x" + "22" * 32), ("symbol", "OTHER"),
                                           ("canonical_key", AssetKey(4663, "0x" + "bb" * 20))])
def test_identity_mismatch_fails_closed(field, value):
    with pytest.raises(SignalComputationError) as exc:
        snapshot(r4=replace(build_r4(), **{field: value}))
    assert exc.value.status is SignalStatus.SIGNAL_IDENTITY_MISMATCH


@pytest.mark.parametrize("mutation", ["timestamp", "halt", "buy_price", "sell_price"])
def test_reference_lineage_mismatch_fails(mutation):
    r3 = build_r3()
    if mutation == "timestamp":
        side = replace(r3.buy, small_gap_observation=replace(r3.buy.small_gap_observation,
                       reference_generated_at=r3.buy.small_gap_observation.reference_generated_at + timedelta(seconds=1)))
        r3 = replace(r3, buy=side)
    elif mutation == "halt":
        side = replace(r3.buy, small_gap_observation=replace(r3.buy.small_gap_observation, reference_is_trading_halt=True))
        r3 = replace(r3, buy=side)
    elif mutation == "buy_price":
        side = replace(r3.buy, small_gap_observation=replace(r3.buy.small_gap_observation,
                       reference_price_usd_per_token=Decimal("106")))
        r3 = replace(r3, buy=side)
    else:
        side = replace(r3.sell, small_gap_observation=replace(r3.sell.small_gap_observation,
                       reference_price_usd_per_token=Decimal("96")))
        r3 = replace(r3, sell=side)
    with pytest.raises(SignalComputationError) as exc:
        snapshot(r3=r3)
    assert exc.value.status is SignalStatus.R3_R4_LINEAGE_MISMATCH


def test_input_skew_and_naive_time_fail_closed():
    r4 = build_r4(as_of=build_r4().as_of + timedelta(seconds=121))
    with pytest.raises(SignalComputationError) as exc:
        snapshot(r4=r4)
    assert exc.value.status is SignalStatus.SIGNAL_EVIDENCE_TIME_MISMATCH
    r3 = build_r3()
    object.__setattr__(r3.lineage, "produced_at", r3.lineage.produced_at.replace(tzinfo=None))
    with pytest.raises(SignalComputationError) as exc2:
        snapshot(r3=r3)
    assert exc2.value.status is SignalStatus.SIGNAL_EVIDENCE_TIME_MISMATCH


def test_unusable_reference_suppresses_but_preserves_reasons():
    r4 = replace(build_r4(), reference_usable=False,
                 blocking_reasons=(ReferenceStateReason.TRADING_HALTED,))
    snap = snapshot(r4=r4)
    assert not snap.signals_active and not snap.signal_events
    assert snap.authority_state is SignalAuthorityState.SUPPRESSED_REFERENCE_UNUSABLE
    assert snap.suppression_reasons == (ReferenceStateReason.TRADING_HALTED,)


def test_suppressed_to_active_material_state_is_signal_appeared():
    suppressed = snapshot(r4=replace(build_r4(), reference_usable=False,
                          blocking_reasons=(ReferenceStateReason.TRADING_HALTED,)))
    active = replace(snapshot(), observed_at=suppressed.observed_at + timedelta(minutes=1))
    assert SignalChangeKind.SIGNAL_APPEARED in kinds(suppressed, active)


def test_active_material_to_suppressed_is_authority_change_not_signal_cleared():
    active = snapshot()
    suppressed = replace(
        active,
        observed_at=active.observed_at + timedelta(minutes=1),
        signals_active=False,
        authority_state=SignalAuthorityState.SUPPRESSED_REFERENCE_UNUSABLE,
        suppression_reasons=(ReferenceStateReason.TRADING_HALTED,),
        signal_events=(),
    )
    result = kinds(active, suppressed)
    assert SignalChangeKind.AUTHORITY_STATE_CHANGED in result
    assert SignalChangeKind.SIGNAL_CLEARED not in result
    assert SignalChangeKind.DIRECTION_CHANGED not in result
    assert SignalChangeKind.SIZE_STATE_CHANGED not in result
    assert SignalChangeKind.MAGNITUDE_CHANGED not in result


def test_suppressed_to_suppressed_raw_gap_movement_has_no_economic_change_labels():
    r4 = replace(build_r4(), reference_usable=False,
                 blocking_reasons=(ReferenceStateReason.TRADING_HALTED,))
    before = snapshot(r4=r4)
    after = replace(snapshot(buy=("500", "700"), sell=("-500", "-700"), r4=r4),
                    observed_at=before.observed_at + timedelta(minutes=1))
    assert kinds(before, after) == {SignalChangeKind.UNCHANGED}


def test_zero_material_history_policy_is_invalid():
    with pytest.raises(SignalComputationError) as exc:
        replace(POLICY, material_history_change_bps=Decimal("0"))
    assert exc.value.status is SignalStatus.SIGNAL_POLICY_INVALID


@pytest.mark.parametrize("value,expected", [("50", GapDirection.PREMIUM), ("-50", GapDirection.DISCOUNT),
                                              ("49.999", GapDirection.WITHIN_THRESHOLD), ("0", GapDirection.WITHIN_THRESHOLD)])
def test_direction_thresholds(value, expected):
    assert snapshot(buy=(value, "0")).buy_assessment.small_gap_direction is expected


@pytest.mark.parametrize("values,expected", [
    (("0", "0"), SizePersistenceState.NO_MATERIAL_DISLOCATION),
    (("60", "70"), SizePersistenceState.PERSISTS),
    (("60", "0"), SizePersistenceState.DECAYS),
    (("0", "60"), SizePersistenceState.EMERGES_AT_SIZE),
    (("60", "-60"), SizePersistenceState.REVERSES),
    (("-60", "60"), SizePersistenceState.REVERSES),
])
def test_size_persistence(values, expected):
    assert snapshot(buy=values).buy_assessment.size_persistence_state is expected


def test_spread_states_and_negative_size_impact_semantics():
    r3 = build_r3()
    crossed = replace(r3, spread_small=replace(r3.spread_small, execution_spread_bps=Decimal("-1")),
                      spread_large=replace(r3.spread_large, execution_spread_bps=Decimal("501")),
                      buy=replace(r3.buy, r0_size_impact_bps=Decimal("-9999")))
    snap = snapshot(r3=crossed)
    assert snap.spread_small_state is SpreadState.CROSSED
    assert snap.spread_large_state is SpreadState.WIDE
    assert not snap.buy_assessment.adverse_size_impact
    assert "arbitrage" not in str(snap.to_evidence_dict()).lower()


def test_route_change_is_evidence_not_suppression_and_cost_is_unresolved():
    snap = snapshot()
    assert snap.signals_active
    assert snap.net_economics_authority == "COST_INCLUSION_UNRESOLVED"
    assert "profit" not in str(snap.to_evidence_dict()).lower()


def test_no_material_gap_means_no_event_but_valid_pass():
    snap = snapshot(buy=("0", "0"), sell=("0", "0"))
    assert snap.signals_active and snap.signal_events == ()


def changed(base, *, buy=None, sell=None, spread=None, minutes=1):
    current = snapshot(buy=buy or (str(base.buy_assessment.small_gap_bps), str(base.buy_assessment.large_gap_bps)),
                       sell=sell or (str(base.sell_assessment.small_gap_bps), str(base.sell_assessment.large_gap_bps)))
    if spread is not None:
        current = replace(current, spread_small_state=spread)
    return replace(current, observed_at=base.observed_at + timedelta(minutes=minutes))


def kinds(previous, current):
    return {c.kind for c in compare_signal_snapshots(previous, current)}


def test_history_digest_is_deterministic_and_unchanged():
    snap = snapshot()
    assert build_history_entry(snap).snapshot_digest == build_history_entry(snap).snapshot_digest
    assert kinds(snap, replace(snap, observed_at=snap.observed_at + timedelta(minutes=1))) == {SignalChangeKind.UNCHANGED}


def test_signal_appeared_and_cleared():
    neutral = snapshot(buy=("0", "0"), sell=("0", "0"))
    material = changed(neutral, buy=("60", "70"), sell=("0", "0"))
    assert SignalChangeKind.SIGNAL_APPEARED in kinds(neutral, material)
    assert SignalChangeKind.SIGNAL_CLEARED in kinds(material, changed(material, buy=("0", "0"), sell=("0", "0")))


def test_direction_size_liquidity_and_magnitude_changes():
    before = snapshot(buy=("60", "70"))
    replacement_spread = (SpreadState.CROSSED if before.spread_small_state is not SpreadState.CROSSED
                          else SpreadState.WIDE)
    after = changed(before, buy=("-60", "0"), spread=replacement_spread)
    result = kinds(before, after)
    assert {SignalChangeKind.DIRECTION_CHANGED, SignalChangeKind.SIZE_STATE_CHANGED,
            SignalChangeKind.LIQUIDITY_CONTEXT_CHANGED, SignalChangeKind.MAGNITUDE_CHANGED} <= result


def test_subthreshold_magnitude_does_not_emit_noise():
    before = snapshot(buy=("60", "70"))
    after = changed(before, buy=("61", "71"))
    assert SignalChangeKind.MAGNITUDE_CHANGED not in kinds(before, after)


def test_history_identity_policy_time_and_digest_validation():
    snap = snapshot()
    first = build_history_entry(snap)
    second = build_history_entry(replace(snap, observed_at=snap.observed_at + timedelta(minutes=1)))
    validate_history_series((first, second))
    with pytest.raises(HistoryError) as identity:
        validate_history_series((first, replace(second, asset_uid="other")))
    assert identity.value.status is HistoryStatus.HISTORY_EVIDENCE_INVALID
    other_policy = replace(POLICY, min_abs_gap_bps=Decimal("51"))
    other_snapshot = replace(snapshot(policy=other_policy),
                             observed_at=snap.observed_at + timedelta(minutes=2))
    other_entry = build_history_entry(other_snapshot)
    with pytest.raises(HistoryError) as policy:
        validate_history_series((first, other_entry))
    assert policy.value.status is HistoryStatus.HISTORY_POLICY_MISMATCH
    with pytest.raises(HistoryError) as time:
        validate_history_series((second, first))
    assert time.value.status is HistoryStatus.HISTORY_TIME_ORDER_INVALID
    with pytest.raises(HistoryError) as digest:
        validate_history_series((replace(first, snapshot_digest="0" * 64),))
    assert digest.value.status is HistoryStatus.HISTORY_EVIDENCE_INVALID


@pytest.mark.parametrize("field,value", [
    ("asset_uid", "0x" + "22" * 32),
    ("canonical_key", AssetKey(4663, "0x" + "bb" * 20)),
    ("symbol", "FORGED"),
    ("observed_at", snapshot().observed_at + timedelta(minutes=5)),
    ("policy", replace(POLICY, min_abs_gap_bps=Decimal("51"))),
])
def test_single_entry_forged_metadata_fails_closed(field, value):
    entry = build_history_entry(snapshot())
    with pytest.raises(HistoryError) as exc:
        validate_history_series((replace(entry, **{field: value}),))
    assert exc.value.status is HistoryStatus.HISTORY_EVIDENCE_INVALID


def test_governance_no_prohibited_top_level_fields():
    prohibited = {"score", "rank", "rating", "grade", "confidenceScore", "opportunityScore",
                  "buyRecommendation", "sellRecommendation", "arbitrage", "profit", "expectedReturn", "priceTarget"}
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                if key != "upstreamEvidence":
                    yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)
    assert prohibited.isdisjoint(set(keys(snapshot().to_evidence_dict())))
