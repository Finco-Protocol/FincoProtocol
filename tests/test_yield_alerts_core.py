"""Yield Alerts V1 domain tests — deterministic change detection, typed
alerts, per-user persistence and dedupe (Agent A scope).

Proves:
  - exact canonical yld_* UID identity;
  - APY / TVL / reward-component changes;
  - freshness degrade / recover;
  - support state change;
  - missing != zero (None never diffs against 0 or another value);
  - explicit zero is valid observed data;
  - duplicate prevention (same transition never creates a second alert);
  - per-user isolation;
  - no alert for non-watched opportunities;
  - read / mark-all-read / unread-count transitions.

Alerts are descriptive only — no BUY/SELL/ENTER/EXIT vocabulary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _iso(dt):
    return dt.isoformat()


def _row(uid, h, at, **fields):
    row = {
        "opportunity_uid": uid,
        "observation_hash": h,
        "observed_at": _iso(at),
    }
    row.update(fields)
    return row


@pytest.fixture()
def stores(tmp_path):
    from finco_yield.alerts_store import PerUserAlertStore, WatchlistStore

    return (WatchlistStore(tmp_path / "watchlist.jsonl"),
            PerUserAlertStore(tmp_path / "alerts.jsonl"))


BASE = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
UID = "yld_" + "a" * 32
OTHER_UID = "yld_" + "b" * 32
USER = "user-1"
USER2 = "user-2"


def _mk_registry():
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry()


def test_registry_uids_are_canonical_yld():
    reg = _mk_registry()
    for opp in reg.all():
        assert opp.uid.startswith("yld_")
        assert len(opp.uid) == len("yld_") + 32
    # exact canonical identity — two loads produce identical UIDs
    reg2 = _mk_registry()
    assert [o.uid for o in reg.all()] == [o.uid for o in reg2.all()]


class TestChangeDetection:
    def _detect(self, prev_fields, curr_fields, uid=UID):
        from finco_yield.alerts_types import DetectionContext, detect_changes
        prev = _row(uid, "h1", BASE, **prev_fields)
        curr = _row(uid, "h2", BASE + timedelta(hours=6), **curr_fields)
        return detect_changes(DetectionContext(
            opportunity_uid=uid, previous=prev, current=curr,
            previous_hash="h1", current_hash="h2"))

    def test_apy_change_detected(self):
        result = self._detect({"apy_total": 0.05}, {"apy_total": 0.07})
        fields = {c.field: (c.previous, c.current) for c in result.changes}
        assert "apy_total" in fields
        assert fields["apy_total"] == (0.05, 0.07)

    def test_tvl_change_detected(self):
        result = self._detect({"tvl_usd": 1_000_000}, {"tvl_usd": 900_000})
        assert any(c.field == "tvl_usd" for c in result.changes)

    def test_reward_component_change_detected(self):
        result = self._detect({"apy_rewards": 0.02}, {"apy_rewards": 0.035})
        assert any(c.field == "apy_rewards" for c in result.changes)

    def test_freshness_degrade_detected(self):
        result = self._detect(
            {"freshness_state": "AVAILABLE"}, {"freshness_state": "STALE"})
        assert result.degraded
        assert not result.recovered

    def test_freshness_recover_detected(self):
        result = self._detect(
            {"freshness_state": "STALE"}, {"freshness_state": "AVAILABLE"})
        assert result.recovered
        assert not result.degraded

    def test_support_state_change_detected(self):
        result = self._detect(
            {"support_state": "SUPPORTED"}, {"support_state": "PARTIAL"})
        assert any(c.field == "support_state" for c in result.changes)

    def test_missing_is_not_zero(self):
        """None (missing) vs 0 (explicit zero) is a change; None vs None is
        not.  Zero is never fabricated from a missing value."""
        # None -> 0 is a change.
        result = self._detect({"tvl_usd": None}, {"tvl_usd": 0})
        assert any(c.field == "tvl_usd" for c in result.changes)
        # 0 -> None is a change.
        result = self._detect({"tvl_usd": 0}, {"tvl_usd": None})
        assert any(c.field == "tvl_usd" for c in result.changes)
        # None -> None is NOT a change.
        result = self._detect({"tvl_usd": None}, {"tvl_usd": None})
        assert not any(c.field == "tvl_usd" for c in result.changes)

    def test_explicit_zero_is_valid_data(self):
        """Explicit 0 in both observations is equal (no change), proving 0
        is real data rather than treated as missing."""
        result = self._detect({"apy_rewards": 0}, {"apy_rewards": 0})
        assert not any(c.field == "apy_rewards" for c in result.changes)
        # And 0 -> 5 is a genuine change.
        result = self._detect({"apy_rewards": 0}, {"apy_rewards": 5})
        assert any(c.field == "apy_rewards" for c in result.changes)

    def test_identical_observations_produce_no_changes(self):
        fields = {"apy_total": 0.05, "tvl_usd": 1000, "freshness_state": "FRESH"}
        result = self._detect(fields, fields)
        assert not result.changes
        assert not result.degraded and not result.recovered


# ── Per-user persistence ─────────────────────────────────────────────────────

def _watch_and_feed(watchlist, alert_store, user, uid, rows):
    watchlist.watch(user, uid)
    from finco_yield.alerts_eval import evaluate_watchlist_alerts
    return evaluate_watchlist_alerts(
        user_id=user, history_rows=rows, watchlist=watchlist,
        alert_store=alert_store, detected_at=BASE + timedelta(days=1))


class TestPersistence:
    def test_typed_events_persisted(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05, tvl_usd=1000),
            _row(UID, "h2", BASE + timedelta(hours=6),
                 apy_total=0.07, tvl_usd=1200),
        ]
        created = _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        assert created, "expected at least one persisted alert"
        types = {a["alert_type"] for a in created}
        assert "APY_CHANGED" in types
        assert "TVL_CHANGED" in types
        alerts = alert_store.list_alerts(USER)
        assert len(alerts) == len(created)
        assert all(a["read"] is False for a in alerts)

    def test_no_alert_for_non_watched_opportunity(self, stores):
        watchlist, alert_store = stores
        # OTHER_UID is NOT watched — only UID is.
        watchlist.watch(USER, UID)
        rows = [
            _row(OTHER_UID, "h1", BASE, apy_total=0.05),
            _row(OTHER_UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        from finco_yield.alerts_eval import evaluate_watchlist_alerts
        created = evaluate_watchlist_alerts(
            user_id=USER, history_rows=rows, watchlist=watchlist,
            alert_store=alert_store, detected_at=BASE + timedelta(days=1))
        assert created == []
        assert alert_store.list_alerts(USER) == []

    def test_user_isolation(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER2, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05),
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        _watch_and_feed(watchlist, alert_store, USER2, UID, rows)
        # USER (different user) has no alerts.
        assert alert_store.list_alerts(USER) == []
        assert alert_store.unread_count(USER) == 0
        # USER2 has the alert.
        assert alert_store.unread_count(USER2) > 0

    def test_unwatching_stops_future_alerts_but_keeps_history(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows1 = [
            _row(UID, "h1", BASE, apy_total=0.05),
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        _watch_and_feed(watchlist, alert_store, USER, UID, rows1)
        before = len(alert_store.list_alerts(USER))
        assert before > 0

        watchlist.unwatch(USER, UID)
        watchlist.unwatch(USER, OTHER_UID)
        rows2 = [
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
            _row(UID, "h3", BASE + timedelta(hours=12), apy_total=0.12),
        ]
        # Correction: after unwatching, the evaluation must not re-watch.
        # Call evaluate_watchlist_alerts directly (no watchlist.watch).
        from finco_yield.alerts_eval import evaluate_watchlist_alerts
        created_after = evaluate_watchlist_alerts(
            user_id=USER, history_rows=rows2, watchlist=watchlist,
            alert_store=alert_store, detected_at=BASE + timedelta(days=1))
        assert created_after == [], (
            "unwatched opportunity must not produce new alerts")
        # Historical alerts retained.
        assert len(alert_store.list_alerts(USER)) == before


class TestDedupe:
    def test_same_transition_never_duplicates(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05),
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        created1 = _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        created2 = _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        assert created1, "first evaluation must create alerts"
        assert created2 == [], "same transition must be deduped"
        unread = alert_store.unread_count(USER)
        assert unread == len(created1), (
            f"expected {len(created1)} alerts, got {unread}")

    def test_new_transition_creates_new_alert(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows1 = [
            _row(UID, "h1", BASE, apy_total=0.05),
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        _watch_and_feed(watchlist, alert_store, USER, UID, rows1)
        rows2 = [
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
            _row(UID, "h3", BASE + timedelta(hours=12), apy_total=0.12),
        ]
        created2 = _watch_and_feed(watchlist, alert_store, USER, UID, rows2)
        assert created2, "a new transition must create a new alert"


class TestReadState:
    def test_mark_read_and_unread_count(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05, tvl_usd=1000),
            _row(UID, "h2", BASE + timedelta(hours=6),
                 apy_total=0.09, tvl_usd=1200),
        ]
        _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        initial = alert_store.unread_count(USER)
        assert initial >= 2

        # Mark one alert type read.
        alert_type = alert_store.list_alerts(USER)[0]["alert_type"]
        marked = alert_store.mark_read(USER, UID, alert_type)
        assert marked >= 1
        assert alert_store.unread_count(USER) == initial - marked

    def test_mark_all_read(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05, tvl_usd=1000),
            _row(UID, "h2", BASE + timedelta(hours=6),
                 apy_total=0.09, tvl_usd=1200),
        ]
        _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        before = alert_store.unread_count(USER)
        assert before > 0
        marked = alert_store.mark_all_read(USER)
        assert marked == before
        assert alert_store.unread_count(USER) == 0

    def test_mark_read_is_user_isolated(self, stores):
        watchlist, alert_store = stores
        watchlist.watch(USER, UID)
        rows = [
            _row(UID, "h1", BASE, apy_total=0.05),
            _row(UID, "h2", BASE + timedelta(hours=6), apy_total=0.09),
        ]
        _watch_and_feed(watchlist, alert_store, USER, UID, rows)
        # USER2 marking read must not affect USER's alerts.
        assert alert_store.mark_all_read(USER2) == 0
        assert alert_store.unread_count(USER) > 0


# ── Descriptive-only vocabulary ──────────────────────────────────────────────

class TestDescriptiveOnly:
    def test_alert_types_are_descriptive(self):
        from finco_yield.alerts_types import AlertType

        values = {m.value.upper() for m in AlertType}
        for banned in ("BUY", "SELL", "ENTER", "EXIT", "BEST", "SAFE", "UNSAFE"):
            assert banned not in values, banned

    def test_labels_are_descriptive(self):
        from finco_yield.alerts_types import ALERT_TYPE_LABELS

        for label in ALERT_TYPE_LABELS.values():
            lowered = label.lower()
            for banned in ("buy", "sell", "enter", "exit", "best", "safe", "unsafe"):
                assert banned not in lowered, (label, banned)


# ── Frozen authorities ───────────────────────────────────────────────────────

class TestFrozenAuthorities:
    @pytest.mark.parametrize("frozen", [
        "financial_engine", "finco_core", "finco_radar",
        "app/model_validation", "app/verified", "app/model_market_bridge",
    ])
    def test_zero_diff_vs_main(self, frozen):
        import subprocess

        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", frozen],
            cwd=REPO, capture_output=True, text=True,
        )
        if out.returncode != 0:
            pytest.skip("git history unavailable in this checkout")
        assert out.stdout.strip() == "", out.stdout
