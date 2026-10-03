"""Yield Intelligence V1 Correction B — value-bearing observation binding.

Each economic value is bound to the EXACT canonical observation that supplied
it: a newer APY-missing (e.g. TVL-only) observation can neither refresh an
older APY nor lend the APY its own freshness — and vice versa.  The mover
horizon anchor is the APY-bearing observation's timestamp.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finco_yield.history import YieldHistoryStore
from finco_yield.market import _RequestHistory, build_market_view
from finco_yield.observation import ImmutableObservationRecord

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class FakeObservation:
    apy_total = None
    tvl_usd = None
    apy_base = None
    apy_rewards = None
    apy_total_30d_avg = None
    apy_30d_avg_source = None
    withdrawal_type = None


class FakeOpportunity:
    def __init__(self, uid, name):
        self.uid = uid
        self.name = name
        self.observation = FakeObservation()


class FakeRegistry:
    def __init__(self, *opportunities):
        self._items = list(opportunities)

    def all(self):
        return tuple(self._items)


class FakeTreasury:
    usable = True
    state = "AVAILABLE"
    source = "FRED_DGS3MO"
    yield_percent = Decimal("4.28")


def _record(store, uid, observed_at, payload):
    store.append(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=observed_at,
        source_authority="NATIVE_ENRICHED", source_uri="https://test",
        adapter_version="test", payload=payload))


def _view(store_path, *opportunities):
    return build_market_view(_RequestHistory(store_path),
                             FakeRegistry(*opportunities), as_of=NOW,
                             treasury=FakeTreasury())


def test_stale_apy_plus_newer_current_tvl_only_row_is_not_a_current_mover(tmp_path):
    """Old STALE APY + new CURRENT TVL-only row: the TVL row can neither
    refresh the APY nor lend it freshness -> no current mover, no spread."""
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_x", NOW - timedelta(hours=2),
            {"apy_total": "0.0400", "tvl_usd": "5000000"})            # APY row: STALE
    _record(store, "yld_x", NOW - timedelta(minutes=5),
            {"apy_total": None, "tvl_usd": "6000000"})                # TVL-only: CURRENT
    view = _view(store.path, FakeOpportunity("yld_x", "X"))
    intel = view.pools["yld_x"]
    assert intel.latest_apy == Decimal("0.0400")     # bound: older APY survives
    assert intel.latest_apy_currentness == "STALE"
    assert intel.latest_tvl == Decimal("6000000")    # newer TVL independently
    assert intel.latest_tvl_currentness == "CURRENT"
    assert intel.currentness == "CURRENT"            # newest row overall IS current
    assert all(m.uid != "yld_x" for horizon in ("24h", "7d")
               for m in view.movers[horizon]), "stale APY must not rank as a current mover"
    assert intel.spread_bps is None, "stale APY + fresh treasury -> no spread"
    assert view.pools_above_floor == 0, "TVL floor eligibility needs CURRENT tvl too"


def test_stale_tvl_plus_newer_current_apy_only_row_fails_floor_eligibility(tmp_path):
    """Old STALE TVL + new CURRENT APY-only row: the APY side is current, but
    TVL-floor eligibility requires a CURRENT TVL-bearing observation."""
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_y", NOW - timedelta(hours=2),
            {"apy_total": None, "tvl_usd": "5000000"})            # TVL row: STALE
    _record(store, "yld_y", NOW - timedelta(minutes=5),
            {"apy_total": "0.0440", "tvl_usd": None})             # APY-only: CURRENT
    view = _view(store.path, FakeOpportunity("yld_y", "Y"))
    intel = view.pools["yld_y"]
    assert intel.latest_apy == Decimal("0.0440")
    assert intel.latest_apy_currentness == "CURRENT"
    assert intel.latest_tvl == Decimal("5000000")
    assert intel.latest_tvl_currentness == "STALE"
    assert view.pools_above_floor == 0, "stale TVL must fail floor eligibility"
    assert all(m.uid != "yld_y" for horizon in ("24h", "7d")
               for m in view.movers[horizon])
    # the APY side itself is current: the Treasury spread remains allowed
    assert intel.spread_bps == Decimal("12.00")


def test_apy_bearing_row_anchors_the_mover_horizon_cutoff(tmp_path):
    """A newer TVL-only row must not move the 24h cutoff: the anchor is the
    newest APY-BEARING observation's timestamp.

    Timeline (all CURRENT rows, minutes before NOW):
      T-25h  APY 0.0420
      T-24.15h APY 0.0435
      T-23h  TVL only (no APY)
      T-0.2h APY 0.0440  <- APY-bearing anchor

    APY-anchored cutoff = T-24.2h -> the 0.0435 row (T-24.15h, NEWER than
    the cutoff) is excluded -> baseline 0.0420 -> delta +20 bps.
    A TVL-anchored cutoff (T-24.1h) would WRONGLY include the 0.0435 row and
    produce +5 bps against it — the assertion below pins the APY anchor.
    """
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_z", NOW - timedelta(hours=25),
            {"apy_total": "0.0420", "tvl_usd": "5000000"})
    _record(store, "yld_z", NOW - timedelta(hours=24.15),
            {"apy_total": "0.0435", "tvl_usd": "5000000"})
    _record(store, "yld_z", NOW - timedelta(hours=23),
            {"apy_total": None, "tvl_usd": "5000000"})
    _record(store, "yld_z", NOW - timedelta(hours=0.2),
            {"apy_total": "0.0440", "tvl_usd": "5000000"})
    view = _view(store.path, FakeOpportunity("yld_z", "Z"))
    intel = view.pools["yld_z"]
    assert intel.deltas["24h"] == Decimal("20.0"), (
        "the 24h cutoff must be anchored on the APY-bearing observation "
        "(a TVL-only anchor would produce +5 bps)")
    assert intel.deltas["7d"] is None   # no 7d-old baseline -> unavailable
    assert next(m for m in view.movers["24h"] if m.uid == "yld_z").delta_bps \
        == Decimal("20.0")


def test_both_sides_current_preserves_normal_mover_eligibility(tmp_path):
    """Newest APY row CURRENT + newest TVL row CURRENT -> normal mover
    eligibility (floor passed, ranked, spread allowed)."""
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_ok", NOW - timedelta(hours=25),
            {"apy_total": "0.0400", "tvl_usd": None})
    _record(store, "yld_ok", NOW - timedelta(hours=0.2),
            {"apy_total": "0.0440", "tvl_usd": "5000000"})
    view = _view(store.path, FakeOpportunity("yld_ok", "OK"))
    intel = view.pools["yld_ok"]
    assert intel.latest_apy_currentness == "CURRENT"
    assert intel.latest_tvl_currentness == "CURRENT"
    assert view.pools_above_floor == 1
    mover = next(m for m in view.movers["24h"] if m.uid == "yld_ok")
    assert mover.delta_bps == Decimal("40.0") and mover.direction == "UP"
    assert intel.spread_bps == Decimal("12.00")


def test_baseline_search_skips_valueless_newer_rows(tmp_path):
    """The baseline lookup walks only APY-bearing observations: a newer
    APY-missing row can neither serve as a baseline nor hide one."""
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_w", NOW - timedelta(hours=30),
            {"apy_total": "0.0420", "tvl_usd": "5000000"})
    _record(store, "yld_w", NOW - timedelta(hours=10),
            {"apy_total": None, "tvl_usd": "5000000"})
    _record(store, "yld_w", NOW - timedelta(hours=0.2),
            {"apy_total": "0.0440", "tvl_usd": None})
    view = _view(store.path, FakeOpportunity("yld_w", "W"))
    intel = view.pools["yld_w"]
    # cutoff (APY-anchored NOW-0.2h minus 24h = T-24.2h) -> baseline 0.0420
    assert intel.deltas["24h"] == Decimal("20.0")
    assert intel.deltas["24h"] != Decimal("0.0"), "an APY-missing row is never a baseline"
