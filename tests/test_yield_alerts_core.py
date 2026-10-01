"""Yield Alerts V1 domain tests — checkpoint-based deterministic evaluation
over CANONICAL authorities (Agent A scope, Correction C).

Proves:
  - watched set comes from THE canonical ``finco_yield.watchlist``;
  - observations come from THE canonical ``YieldHistoryStore`` (JSONL);
  - first evaluation is a baseline: checkpoint set, NO alerts;
  - EVERY unseen observation transition is processed (not just last two);
  - deterministic alert_id: identical transition → one record (dedupe);
  - canonical freshness (evaluate_freshness): degrade WITHOUT a new
    observation, recover + NEW_OBSERVATION when fresh evidence arrives
    after a stale period (CURRENT/STALE — never ``AVAILABLE``);
  - support state resolved through THE canonical registry;
  - missing != zero (None never diffs against 0; explicit 0 is data);
  - per-user isolation (alerts, checkpoints, read-marking);
  - unwatching stops future alerts, retains history;
  - alerts_snapshot read-model for the presentation layer.

Alerts are descriptive only — no BUY/SELL/ENTER/EXIT vocabulary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]

BASE = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
USER = "user-1"
USER2 = "user-2"
UID = "yld_" + "a" * 32  # replaced by real canonical uids in fixtures
OTHER_UID = "yld_" + "b" * 32

SOURCE_URI = "https://evidence.test/vault"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """One SQLite database per test for watchlist + alerts + checkpoints."""
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "finco.db"))
    return tmp_path / "finco.db"


@pytest.fixture()
def real_uids():
    from finco_yield.registry import load_bundled_registry

    registry = load_bundled_registry()
    uids = [opp.uid for opp in registry.all()][:2]
    assert len(uids) == 2
    return uids


@pytest.fixture()
def history_store(tmp_path):
    from finco_yield.history import YieldHistoryStore

    return YieldHistoryStore(tmp_path / "yield_history.jsonl")


class StubRegistry:
    """Registry stand-in exposing one mutable support state (the eval
    pipeline takes THE registry as a parameter; the bundled registry is
    exercised by the identity tests below)."""

    def __init__(self, support_state: str):
        self.support_state = support_state

    def resolve(self, opportunity_uid: str):
        return SimpleNamespace(support_state=self.support_state)


def _observe(history_store, uid, at, **fields) -> str:
    """Append ONE canonical observation; payload values canonicalise through
    the same JSONL round-trip production uses (Decimal → normalized str)."""
    from finco_yield.history import ImmutableObservationRecord

    payload = {k: v for k, v in fields.items()}
    record = ImmutableObservationRecord(
        opportunity_uid=uid,
        observed_at=at,
        source_authority="NATIVE_ENRICHED",
        source_uri=SOURCE_URI,
        adapter_version="y0.1",
        payload=payload,
    )
    return history_store.append(record)


def _evaluate(user, history_store, registry, *, now, db=None):
    from finco_yield.alerts_eval import evaluate_watchlist_alerts

    return evaluate_watchlist_alerts(
        user_id=user, history_store=history_store, registry=registry, now=now)


def _watch(user, uid):
    from finco_yield.watchlist import save_watchlist_item

    return save_watchlist_item(user, uid)


def _unwatch(user, uid):
    from finco_yield.watchlist import remove_watchlist_item

    return remove_watchlist_item(user, uid)


def _checkpoint(user, uid):
    from finco_yield.alerts_store import get_checkpoint

    return get_checkpoint(user, uid)


def _alerts(user):
    from finco_yield.alerts_store import list_alerts

    return list_alerts(user)


def _minutes(n):
    return BASE + timedelta(minutes=n)


# ── Canonical identity ────────────────────────────────────────────────────────

class TestCanonicalIdentity:
    def test_registry_uids_are_canonical_yld(self):
        from finco_yield.registry import load_bundled_registry

        registry = load_bundled_registry()
        for opp in registry.all():
            assert opp.uid.startswith("yld_")
            assert len(opp.uid) == len("yld_") + 32
        registry2 = load_bundled_registry()
        assert [o.uid for o in registry.all()] == [o.uid for o in registry2.all()]

    def test_watchlist_rejects_non_canonical_uid(self, db):
        from finco_yield.watchlist import WatchlistError, save_watchlist_item

        with pytest.raises(WatchlistError) as excinfo:
            save_watchlist_item(USER, "yld_zzzz")
        assert excinfo.value.REASON == "YIELD_OPPORTUNITY_UID_MALFORMED"

    def test_watchlist_rejects_well_formed_unknown_uid(self, db):
        from finco_yield.watchlist import WatchlistError, save_watchlist_item

        with pytest.raises(WatchlistError) as excinfo:
            save_watchlist_item(USER, UID)
        assert excinfo.value.REASON == "YIELD_OPPORTUNITY_UID_UNKNOWN"


# ── Baseline semantics ────────────────────────────────────────────────────────

class TestBaseline:
    def test_first_evaluation_baselines_without_alerts(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(10))
        assert created == []
        assert _alerts(USER) == []
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint is not None
        assert checkpoint["last_freshness_state"] == "CURRENT"
        assert checkpoint["last_support_state"] == "SUPPORTED"

    def test_baseline_freshness_uses_canonical_states_only(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=BASE + timedelta(hours=2))
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_freshness_state"] == "STALE"
        assert checkpoint["last_freshness_state"] != "AVAILABLE"


# ── Transition coverage ───────────────────────────────────────────────────────

class TestTransitions:
    def test_every_unseen_transition_processed_not_just_last_two(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.07"))
        _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(31))

        apy_alerts = [a for a in created if a["alert_type"] == "APY_CHANGED"]
        assert len(apy_alerts) == 2, "both unseen transitions must alert"
        assert apy_alerts[0]["previous"] != apy_alerts[1]["previous"]
        assert apy_alerts[0]["alert_id"] != apy_alerts[1]["alert_id"]
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_processed_observation_hash"] == (
            history_store.for_opportunity(uid)[-1]["observation_hash"])

    def test_multiple_field_types_in_one_transition(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE,
                 apy_total=Decimal("0.05"), tvl_usd=1000,
                 apy_rewards=Decimal("0.01"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []
        _observe(history_store, uid, _minutes(20),
                 apy_total=Decimal("0.07"), tvl_usd=1200,
                 apy_rewards=Decimal("0.02"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        types = [a["alert_type"] for a in created]
        assert types == ["APY_CHANGED", "TVL_CHANGED",
                         "REWARD_COMPONENT_CHANGED"]
        assert all(a["previous"] is not None and a["current"] is not None
                   for a in created)

    def test_unchanged_observation_produces_no_alerts(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert created == []
        assert _alerts(USER) == []


# ── Deterministic identity + dedupe ──────────────────────────────────────────

class TestDeterministicAlertId:
    def test_reevaluation_never_duplicates(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        created1 = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                             now=_minutes(21))
        assert len(created1) == 1
        created2 = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                             now=_minutes(22))
        assert created2 == []
        assert len(_alerts(USER)) == 1

    def test_new_transition_creates_new_alert(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(21))
        _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.11"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(31))
        assert len(created) == 1
        assert created[0]["alert_type"] == "APY_CHANGED"
        assert len(_alerts(USER)) == 2

    def test_same_transition_two_users_distinct_alerts(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _watch(USER2, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _evaluate(USER2, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        created1 = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                             now=_minutes(21))
        created2 = _evaluate(USER2, history_store, StubRegistry("SUPPORTED"),
                             now=_minutes(21))
        assert len(created1) == len(created2) == 1
        assert created1[0]["alert_id"] != created2[0]["alert_id"]


# ── Canonical freshness ───────────────────────────────────────────────────────

class TestFreshness:
    def test_degradation_without_new_observation(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []  # baseline CURRENT

        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=BASE + timedelta(hours=2))
        degraded = [a for a in created
                    if a["alert_type"] == "FRESHNESS_DEGRADED"]
        assert len(degraded) == 1
        assert degraded[0]["previous"] == "CURRENT"
        assert degraded[0]["current"] == "STALE"
        assert _checkpoint(USER, uid)["last_freshness_state"] == "STALE"

    def test_repeated_stale_evaluation_does_not_realert(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=BASE + timedelta(hours=2))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=BASE + timedelta(hours=3))
        assert created == []
        assert len(_alerts(USER)) == 1

    def test_recovery_after_stale_emits_recovered_and_new_observation(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=BASE + timedelta(hours=2))  # baseline STALE
        assert _alerts(USER) == []

        _observe(history_store, uid, BASE + timedelta(hours=2, minutes=10),
                 apy_total=Decimal("0.05"))  # same economics, fresh evidence
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=BASE + timedelta(hours=2, minutes=20))
        types = [a["alert_type"] for a in created]
        assert "FRESHNESS_RECOVERED" in types
        assert "NEW_OBSERVATION" in types
        assert "APY_CHANGED" not in types  # economics unchanged
        recovered = next(a for a in created
                         if a["alert_type"] == "FRESHNESS_RECOVERED")
        assert recovered["previous"] == "STALE"
        assert recovered["current"] == "CURRENT"
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_freshness_state"] == "CURRENT"
        # NEW_OBSERVATION carries no fabricated values.
        new_obs = next(a for a in created
                       if a["alert_type"] == "NEW_OBSERVATION")
        assert new_obs["previous"] is None and new_obs["current"] is None

    def test_stale_to_stale_new_observation_no_recovery(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=BASE + timedelta(hours=2))  # baseline STALE
        _observe(history_store, uid, BASE + timedelta(hours=1),
                 apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=BASE + timedelta(hours=3))
        types = {a["alert_type"] for a in created}
        assert "FRESHNESS_RECOVERED" not in types
        assert "NEW_OBSERVATION" not in types
        assert "APY_CHANGED" in types  # economics still diffed


# ── Support state (canonical registry authority) ─────────────────────────────

class TestSupportState:
    def test_support_state_change_alerts(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        # Same economics, registry support state changed.
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                            now=_minutes(21))
        support = [a for a in created
                   if a["alert_type"] == "SUPPORT_STATE_CHANGED"]
        assert len(support) == 1
        assert support[0]["previous"] == "SUPPORTED"
        assert support[0]["current"] == "DISCOVERY_ONLY"
        assert _checkpoint(USER, uid)["last_support_state"] == "DISCOVERY_ONLY"

    def test_unchanged_support_state_does_not_realert(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert created == []


# ── Missing != zero ───────────────────────────────────────────────────────────

class TestMissingIsNotZero:
    def test_none_to_zero_is_a_change(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=None)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=0)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["TVL_CHANGED"]
        assert created[0]["previous"] is None
        assert created[0]["current"] == 0

    def test_zero_to_none_is_a_change(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=0)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=None)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["TVL_CHANGED"]
        assert created[0]["current"] is None

    def test_none_to_none_and_zero_to_zero_are_not_changes(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=None, apy_rewards=0)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=None, apy_rewards=0)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert created == []

    def test_missing_field_never_becomes_zero(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        # tvl_usd was never observed; a new observation still omits it.
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.05"),
                 tvl_usd=0)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["TVL_CHANGED"]
        assert created[0]["previous"] is None  # missing, not fabricated zero


# ── Per-user scoping ──────────────────────────────────────────────────────────

class TestUserScoping:
    def test_no_alert_for_non_watched_opportunity(
            self, db, history_store, real_uids):
        watched_uid, other_uid = real_uids
        _watch(USER, watched_uid)
        _observe(history_store, other_uid, BASE, apy_total=Decimal("0.05"))
        _observe(history_store, other_uid, _minutes(20),
                 apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert created == []
        assert _alerts(USER) == []
        assert _checkpoint(USER, other_uid) is None

    def test_unwatching_stops_future_alerts_but_keeps_history(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(21))
        before = len(_alerts(USER))
        assert before == 1

        _unwatch(USER, uid)
        _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.11"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(31))
        assert created == []
        assert len(_alerts(USER)) == before  # history retained

    def test_user_isolation(self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER2, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER2, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        assert _evaluate(USER2, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(21))
        # USER never watched anything — no alerts, no checkpoint.
        assert _alerts(USER) == []
        assert _checkpoint(USER, uid) is None
        assert _checkpoint(USER2, uid) is not None


# ── Read state + snapshot read model ─────────────────────────────────────────

class TestReadStateAndSnapshot:
    def test_mark_read_by_alert_id_is_user_isolated(
            self, db, history_store, real_uids):
        from finco_yield.alerts_store import mark_read, unread_count

        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20),
                 apy_total=Decimal("0.07"), tvl_usd=1200)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert len(created) == 2
        assert unread_count(USER) == 2

        target = _alerts(USER)[0]["alert_id"]
        assert mark_read(USER2, target) is False  # wrong user: no mutation
        assert unread_count(USER) == 2
        assert mark_read(USER, target) is True
        assert unread_count(USER) == 1
        assert mark_read(USER, target) is False  # already read

    def test_mark_all_read(self, db, history_store, real_uids):
        from finco_yield.alerts_store import mark_all_read, unread_count

        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE,
                 apy_total=Decimal("0.05"), tvl_usd=1000)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20),
                 apy_total=Decimal("0.07"), tvl_usd=1200)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(21))
        before = unread_count(USER)
        assert before == 2
        assert mark_all_read(USER) == before
        assert unread_count(USER) == 0
        assert mark_all_read(USER2) == 0

    def test_alerts_snapshot(self, db, history_store, real_uids):
        from finco_yield.alerts_core import alerts_snapshot

        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE,
                 apy_total=Decimal("0.05"), tvl_usd=1000)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20),
                 apy_total=Decimal("0.07"), tvl_usd=1000)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(21))

        snapshot = alerts_snapshot(USER)
        assert snapshot["user_id"] == USER
        assert len(snapshot["alerts"]) == 1
        assert snapshot["unread_count"] == 1
        assert snapshot["alerts"][0]["alert_type"] == "APY_CHANGED"
        # Empty user snapshot is well-formed.
        empty = alerts_snapshot(USER2)
        assert empty == {"user_id": USER2, "alerts": [], "unread_count": 0}


# ── Descriptive-only vocabulary ───────────────────────────────────────────────

class TestDescriptiveOnly:
    def test_alert_types_are_descriptive(self):
        from finco_yield.alerts_types import AlertType

        values = {m.value.upper() for m in AlertType}
        for banned in ("BUY", "SELL", "ENTER", "EXIT", "BEST", "SAFE",
                       "UNSAFE"):
            assert banned not in values, banned

    def test_labels_are_descriptive(self):
        from finco_yield.alerts_types import ALERT_TYPE_LABELS

        for label in ALERT_TYPE_LABELS.values():
            lowered = label.lower()
            for banned in ("buy", "sell", "enter", "exit", "best", "safe",
                           "unsafe"):
                assert banned not in lowered, (label, banned)

    def test_facade_exports_resolve(self):
        import finco_yield.alerts_core as core

        for name in core.__all__:
            assert hasattr(core, name), name


# ── Frozen authorities ────────────────────────────────────────────────────────

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
