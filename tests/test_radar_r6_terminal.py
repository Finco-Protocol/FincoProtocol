"""Deterministic offline tests for the R6 read-only presentation authority."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finco_radar.assets.contracts import AssetKey
from finco_radar.history.engine import build_history_entry
from finco_radar.reference_state.contracts import ReferenceStateReason
from finco_radar.signals.contracts import SignalAuthorityState, SignalPolicy, SpreadState
from finco_radar.signals.engine import build_signal_snapshot
from finco_radar.terminal.contracts import TerminalError, TerminalStatus
from finco_radar.terminal.presenter import build_terminal_snapshot, reconstruct_terminal_digest
from finco_radar.terminal.web import create_radar_app, render_terminal_html
from tests.test_radar_r3_liquidity import build as build_r3
from tests.test_radar_r4_reference_state import build as build_r4

POLICY = SignalPolicy(Decimal("50"), Decimal("500"), Decimal("100"), Decimal("120"), Decimal("25"))


def compose(*, buy=None, sell=None, suppressed=False, crossed=False, route_changed=False):
    r3 = build_r3()
    if buy:
        b = replace(r3.buy,
            small_gap_observation=replace(r3.buy.small_gap_observation, gap_bps=Decimal(buy[0])),
            large_gap_observation=replace(r3.buy.large_gap_observation, gap_bps=Decimal(buy[1])),
            directional_gap_delta_bps=Decimal(buy[1]) - Decimal(buy[0]))
        r3 = replace(r3, buy=b)
    if sell:
        s = replace(r3.sell,
            small_gap_observation=replace(r3.sell.small_gap_observation, gap_bps=Decimal(sell[0])),
            large_gap_observation=replace(r3.sell.large_gap_observation, gap_bps=Decimal(sell[1])),
            directional_gap_delta_bps=Decimal(sell[1]) - Decimal(sell[0]))
        r3 = replace(r3, sell=s)
    if crossed:
        r3 = replace(r3, spread_small=replace(r3.spread_small, execution_spread_bps=Decimal("-1")))
    if route_changed:
        changed = replace(r3.buy.large_route_signature, legs=(("other", "a", "b"),))
        r3 = replace(r3, buy=replace(r3.buy, large_route_signature=changed))
    r4 = build_r4()
    if suppressed:
        r4 = replace(r4, reference_usable=False,
                     blocking_reasons=(ReferenceStateReason.TRADING_HALTED,))
    r5 = build_signal_snapshot(r3=r3, r4=r4, policy=POLICY)
    return r3, r4, r5


def terminal(*, token_name="AAA Token", previous=(), digest=None, **kwargs):
    r3, r4, r5 = compose(**kwargs)
    digest = digest or build_history_entry(r5).snapshot_digest
    snap = build_terminal_snapshot(token_name=token_name, r3=r3, r4=r4, r5=r5,
        source_signal_snapshot_digest=digest, generated_at=r5.observed_at + timedelta(seconds=1),
        git_head="r6-test-head", previous_history=previous,
        candidate_audit=({"symbol": "ZZZ", "status": "SKIPPED"},))
    return snap, (r3, r4, r5)


def test_exact_snapshot_builds_terminal_ok_and_digests_reconstruct():
    snap, _ = terminal()
    assert snap.status is TerminalStatus.TERMINAL_OK
    assert reconstruct_terminal_digest(snap) == snap.terminal_snapshot_digest
    assert snap.source_signal_snapshot_digest == snap.history_panel.current_digest


@pytest.mark.parametrize("target,field,value", [
    ("r4", "asset_uid", "0x" + "22" * 32),
    ("r4", "canonical_key", AssetKey(4663, "0x" + "bb" * 20)),
    ("r4", "symbol", "OTHER"),
])
def test_identity_mismatch_fails_typed(target, field, value):
    r3, r4, r5 = compose()
    r4 = replace(r4, **{field: value})
    with pytest.raises(TerminalError) as exc:
        build_terminal_snapshot(token_name="AAA", r3=r3, r4=r4, r5=r5,
            source_signal_snapshot_digest=build_history_entry(r5).snapshot_digest,
            generated_at=r5.observed_at, git_head="x")
    assert exc.value.status is TerminalStatus.TERMINAL_IDENTITY_MISMATCH


def test_forged_source_digest_and_upstream_binding_fail():
    with pytest.raises(TerminalError) as digest:
        terminal(digest="0" * 64)
    assert digest.value.status is TerminalStatus.TERMINAL_EVIDENCE_INVALID
    r3, r4, r5 = compose()
    forged = replace(r5, upstream_r3_evidence={})
    with pytest.raises(TerminalError) as binding:
        build_terminal_snapshot(token_name="AAA", r3=r3, r4=r4, r5=forged,
            source_signal_snapshot_digest=build_history_entry(forged).snapshot_digest,
            generated_at=forged.observed_at, git_head="x")
    assert binding.value.status is TerminalStatus.TERMINAL_EVIDENCE_INVALID


def test_naive_time_and_non_finite_formatting_fail():
    r3, r4, r5 = compose()
    with pytest.raises(TerminalError):
        build_terminal_snapshot(token_name="AAA", r3=r3, r4=r4, r5=r5,
            source_signal_snapshot_digest=build_history_entry(r5).snapshot_digest,
            generated_at=r5.observed_at.replace(tzinfo=None), git_head="x")
    broken = r3
    object.__setattr__(broken, "spread_delta_bps", Decimal("NaN"))
    forged = replace(r5, upstream_r3_evidence=broken.to_evidence_dict())
    with pytest.raises(TerminalError) as exc:
        build_terminal_snapshot(token_name="AAA", r3=broken, r4=r4, r5=forged,
            source_signal_snapshot_digest=build_history_entry(forged).snapshot_digest,
            generated_at=r5.observed_at, git_head="x")
    assert exc.value.status is TerminalStatus.TERMINAL_INPUT_INVALID


def test_reference_panel_preserves_states_and_unresolved_session():
    snap, (_, r4, _) = terminal()
    panel = snap.reference_panel
    assert panel.reference_usable is True
    assert panel.session_label == "Session authority unresolved"
    assert panel.halt_state == r4.halt_state.value
    assert panel.corporate_action_state == r4.corporate_action_state.value
    assert panel.multiplier_state == r4.multiplier_state.value


@pytest.mark.parametrize("field", ["asset_lifecycle", "halt_state", "freshness_state",
                                    "market_session_state", "corporate_action_state", "multiplier_state"])
def test_each_reference_classification_is_directly_preserved(field):
    snap, (_, r4, _) = terminal()
    upstream = {
        "asset_lifecycle": r4.asset_lifecycle_state.value,
        "halt_state": r4.halt_state.value,
        "freshness_state": r4.freshness_state.value,
        "market_session_state": r4.market_session_state.value,
        "corporate_action_state": r4.corporate_action_state.value,
        "multiplier_state": r4.multiplier_state.value,
    }
    assert getattr(snap.reference_panel, field) == upstream[field]


def test_suppression_is_explicit_and_not_no_material_signal():
    snap, _ = terminal(suppressed=True)
    assert snap.signal_panel.display_state == "SIGNALS SUPPRESSED"
    assert snap.signal_panel.suppression_reasons == ("TRADING_HALTED",)
    assert "NO MATERIAL" not in render_terminal_html(snap)
    assert "REFERENCE NOT USABLE FOR ACTIVE SIGNAL INTERPRETATION" in render_terminal_html(snap)


def test_active_no_material_is_distinct_from_suppression():
    snap, _ = terminal(buy=("0", "0"), sell=("0", "0"))
    assert snap.signal_panel.display_state == "NO MATERIAL SIGNAL"
    assert snap.signal_panel.signals_active


@pytest.mark.parametrize("buy,sell,expected", [
    (("-60", "-70"), ("0", "0"), ("DISCOUNT", "DISCOUNT")),
    (("0", "0"), ("60", "70"), ("PREMIUM", "PREMIUM")),
    (("60", "-60"), ("0", "0"), ("PREMIUM", "DISCOUNT")),
])
def test_gap_directions_are_copied_not_reinterpreted(buy, sell, expected):
    snap, _ = terminal(buy=buy, sell=sell)
    chosen = snap.market_panel[:2] if buy != ("0", "0") else snap.market_panel[2:]
    assert tuple(x.direction for x in chosen) == expected


def test_rounding_never_changes_upstream_classification():
    snap, _ = terminal(buy=("49.999", "50"), sell=("0", "0"))
    small, large = snap.market_panel[:2]
    assert small.gap_bps.display == "50.00 bps" and small.direction == "WITHIN_THRESHOLD"
    assert large.direction == "PREMIUM"


@pytest.mark.parametrize("index,side", [(0, "BUY"), (1, "BUY"), (2, "SELL"), (3, "SELL")])
def test_each_market_row_preserves_side_specific_reference_and_timestamps(index, side):
    snap, (r3, _, _) = terminal()
    row = snap.market_panel[index]
    upstream = (r3.buy.small_gap_observation, r3.buy.large_gap_observation,
                r3.sell.small_gap_observation, r3.sell.large_gap_observation)[index]
    assert row.side == side
    assert row.reference_price.raw == str(upstream.reference_price_usd_per_token)
    assert row.quote_timestamp == upstream.quoted_at.isoformat()
    assert row.reference_timestamp == upstream.reference_generated_at.isoformat()


def test_liquidity_values_routes_cost_and_crossed_are_preserved():
    snap, (r3, _, _) = terminal(crossed=True, route_changed=True)
    liq = snap.liquidity_panel
    assert liq.spread_small_bps.raw == str(r3.spread_small.execution_spread_bps)
    assert liq.buy_size_impact_bps.raw == str(r3.buy.r0_size_impact_bps)
    assert liq.spread_small_state == "CROSSED"
    assert liq.buy_route_changed
    assert liq.cost_authority == "COST_INCLUSION_UNRESOLVED"
    serialized = str(snap.to_evidence_dict()).lower()
    assert "arbitrage" not in serialized and "net_profit" not in serialized


def test_negative_size_impact_is_not_relabeled_adverse():
    r3, r4, _ = compose()
    r3 = replace(r3, buy=replace(r3.buy, r0_size_impact_bps=Decimal("-9999")))
    r5 = build_signal_snapshot(r3=r3, r4=r4, policy=POLICY)
    snap = build_terminal_snapshot(token_name="AAA", r3=r3, r4=r4, r5=r5,
        source_signal_snapshot_digest=build_history_entry(r5).snapshot_digest,
        generated_at=r5.observed_at, git_head="x")
    assert not snap.size_panel[0].adverse_size_impact


@pytest.mark.parametrize("field", ["spread_small_bps", "spread_large_bps", "spread_delta_bps",
                                    "buy_size_impact_bps", "sell_size_impact_bps"])
def test_each_liquidity_numeric_is_preserved_as_raw_authority(field):
    snap, (r3, _, _) = terminal()
    expected = {
        "spread_small_bps": r3.spread_small.execution_spread_bps,
        "spread_large_bps": r3.spread_large.execution_spread_bps,
        "spread_delta_bps": r3.spread_delta_bps,
        "buy_size_impact_bps": r3.buy.r0_size_impact_bps,
        "sell_size_impact_bps": r3.sell.r0_size_impact_bps,
    }
    assert getattr(snap.liquidity_panel, field).raw == str(expected[field])


def previous_entry(*, buy=("0", "0"), sell=("0", "0"), suppressed=False):
    _, _, r5 = compose(buy=buy, sell=sell, suppressed=suppressed)
    return build_history_entry(replace(r5, observed_at=r5.observed_at - timedelta(minutes=1)))


@pytest.mark.parametrize("previous,current,kind", [
    (previous_entry(), {"buy": ("60", "70")}, "SIGNAL_APPEARED"),
    (previous_entry(buy=("60", "70")), {"buy": ("0", "0")}, "SIGNAL_CLEARED"),
    (previous_entry(buy=("60", "70")), {"buy": ("60", "70"), "suppressed": True}, "AUTHORITY_STATE_CHANGED"),
])
def test_history_changes_are_consumed_from_r5(previous, current, kind):
    snap, _ = terminal(previous=(previous,), **current)
    kinds = {x.kind for x in snap.history_panel.changes}
    assert kind in kinds
    if kind == "AUTHORITY_STATE_CHANGED":
        assert "SIGNAL_CLEARED" not in kinds


def test_no_previous_observation_is_honest():
    snap, _ = terminal()
    assert not snap.history_panel.previous_observation_available
    assert snap.history_panel.message == "No previous comparable observation available"


def test_forged_history_metadata_and_policy_mismatch_fail_through_r5():
    forged = replace(previous_entry(), symbol="FORGED")
    with pytest.raises(TerminalError) as metadata:
        terminal(previous=(forged,))
    assert metadata.value.status is TerminalStatus.TERMINAL_HISTORY_INVALID
    other = previous_entry()
    other_policy = replace(POLICY, min_abs_gap_bps=Decimal("51"))
    other_snapshot = replace(other.signal_snapshot, policy=other_policy)
    mismatched = build_history_entry(other_snapshot)
    with pytest.raises(TerminalError) as policy:
        terminal(previous=(mismatched,))
    assert policy.value.status is TerminalStatus.TERMINAL_HISTORY_INVALID


def test_web_routes_are_read_only_and_escape_malicious_evidence():
    snap, _ = terminal(token_name='<script>alert("x")</script>')
    app = create_radar_app(lambda: snap)
    client = TestClient(app)
    page = client.get("/radar")
    assert page.status_code == 200 and "&lt;script&gt;" in page.text
    assert '<script>alert("x")</script>' not in page.text
    data = client.get("/radar/api/snapshot")
    assert data.status_code == 200 and data.json()["asset"]["canonicalKey"]
    assert client.get("/radar/api/health").json() == {"status": "ok", "authority": "R6_READ_ONLY"}
    methods = {m for route in app.routes for m in (getattr(route, "methods", None) or set())}
    assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods)
    assert "R6_APPLIED" in page.text and snap.terminal_snapshot_digest in page.text


def test_static_javascript_has_no_economic_or_unsafe_execution_logic():
    js = (Path(__file__).parents[1] / "finco_radar/terminal/static/radar_terminal.js").read_text()
    forbidden = ("eval(", "new Function", "innerHTML", "gap_bps", "spread_bps",
                 "size_impact", "min_abs_gap", "material_history", "classify")
    assert all(term not in js for term in forbidden)


@pytest.mark.parametrize("needle", ["eval(", "new Function", "innerHTML", "gap_bps",
                                     "spread_bps", "size_impact", "min_abs_gap",
                                     "material_history", "classify"])
def test_each_forbidden_client_side_construct_is_absent(needle):
    js = (Path(__file__).parents[1] / "finco_radar/terminal/static/radar_terminal.js").read_text()
    assert needle not in js


def test_governance_has_no_prohibited_fields_or_execution_routes():
    snap, _ = terminal()
    prohibited = {"score", "rank", "rating", "grade", "recommendation", "expectedReturn",
                  "priceTarget", "profit", "arbitrage", "prediction", "wallet", "trade", "swap", "sign"}
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value: yield from keys(item)
    assert prohibited.isdisjoint(set(keys(snap.to_evidence_dict())))


@pytest.mark.parametrize("prohibited", ["score", "rank", "rating", "grade", "recommendation",
                                         "expectedReturn", "priceTarget", "profit", "arbitrage",
                                         "prediction", "wallet", "trade", "swap", "sign"])
def test_each_prohibited_authority_field_is_absent(prohibited):
    snap, _ = terminal()
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value: yield from keys(item)
    assert prohibited not in set(keys(snap.to_evidence_dict()))


@pytest.mark.parametrize("path", ["/trade", "/swap", "/approve", "/sign", "/wallet"])
def test_no_execution_or_wallet_route_exists(path):
    snap, _ = terminal()
    client = TestClient(create_radar_app(lambda: snap))
    assert client.post(path).status_code == 404


def test_terminal_nested_evidence_is_deeply_immutable():
    snap, _ = terminal(buy=("60", "70"), previous=(previous_entry(),))
    with pytest.raises((AttributeError, TypeError)):
        snap.candidate_audit[0].status = "TAMPERED"
    with pytest.raises((AttributeError, TypeError)):
        snap.signal_panel.events[0].kind = "TAMPERED"
    with pytest.raises((AttributeError, TypeError)):
        snap.history_panel.changes[0].details_json = "{}"
    assert reconstruct_terminal_digest(snap) == snap.terminal_snapshot_digest


def test_web_fails_closed_if_snapshot_digest_is_stale():
    snap, _ = terminal()
    stale = replace(snap, git_head="tampered-without-redigest")
    client = TestClient(create_radar_app(lambda: stale), raise_server_exceptions=False)
    assert client.get("/radar").status_code == 500
    assert client.get("/radar/api/snapshot").status_code == 500
