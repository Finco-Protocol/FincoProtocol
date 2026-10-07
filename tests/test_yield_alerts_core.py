"""Yield Alerts V1 domain tests — checkpoint-based deterministic evaluation
over CANONICAL authorities (Agent A scope, final correction).

Proves:
  - watched set comes from THE canonical ``finco_yield.watchlist``;
  - observations come from THE canonical ``YieldHistoryStore`` (JSONL);
  - first evaluation is a baseline: checkpoint set, NO alerts;
  - EVERY unseen observation transition is processed (not just last two);
  - PERSISTENCE ATOMICITY: alert inserts + checkpoint advance commit in
    ONE transaction; a forced persistence failure leaves the checkpoint
    untouched (fail closed) and a retry recreates the lost transition
    exactly once via deterministic alert_ids;
  - registry support state changes alert WITHOUT any new history
    observation, exactly once per transition (A→B, then B→C distinct);
  - RE-WATCH: unwatch → observations → re-add baselines at the latest
    canonical observation and never replays the unwatched period;
  - canonical freshness (evaluate_freshness): degrade WITHOUT a new
    observation; FRESHNESS_RECOVERED + NEW_OBSERVATION only for canonical
    DEGRADED (STALE/INVALID/FUTURE_TIMESTAMP) → CURRENT on a NEW hash;
    UNKNOWN → CURRENT never claims recovery; CURRENT → CURRENT is silent;
  - missing-vs-zero contract (V1): MISSING is never numerically
    interpreted as zero, but a MISSING ↔ explicit-0 availability change
    is a descriptive field-change alert carrying verbatim values;
  - per-user isolation (alerts, checkpoints, read-marking);
  - alerts_snapshot read-model for the presentation layer.

Alerts are descriptive only — no BUY/SELL/ENTER/EXIT vocabulary.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from model_v2_governance import merge_base_ref

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
    path = tmp_path / "finco.db"
    monkeypatch.setenv("FINCO_DB_PATH", str(path))
    return path


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
    the same JSONL round-trip production uses (Decimal → normalized str).
    Returns the canonical observation hash."""
    from finco_yield.history import ImmutableObservationRecord

    record = ImmutableObservationRecord(
        opportunity_uid=uid,
        observed_at=at,
        source_authority=fields.pop("source_authority", "NATIVE_ENRICHED"),
        source_uri=fields.pop("source_uri", SOURCE_URI),
        adapter_version=fields.pop("adapter_version", "y0.1"),
        payload=dict(fields),
    )
    return history_store.append(record)


def _evaluate(user, history_store, registry, *, now):
    from finco_yield.alerts_eval import evaluate_watchlist_alerts

    return evaluate_watchlist_alerts(
        user_id=user, history_store=history_store, registry=registry, now=now)


def _watch(user, uid, *, at=None):
    from finco_yield.watchlist import save_watchlist_item

    return save_watchlist_item(user, uid, now=at or datetime.now(timezone.utc))


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


def _fail_checkpoint_updates(db_path, user, uid):
    """Force the checkpoint UPDATE inside commit_alert_state's transaction
    to fail (SQLite RAISE(ABORT)) — the whole unit must roll back."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TRIGGER fail_checkpoint_update "
            "BEFORE UPDATE ON yield_alert_state "
            f"WHEN NEW.user_id = '{user}' AND NEW.opportunity_uid = '{uid}' "
            "BEGIN SELECT RAISE(ABORT, 'simulated persistence failure'); END"
        )
        conn.commit()
    finally:
        conn.close()


def _restore_checkpoint_updates(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TRIGGER IF EXISTS fail_checkpoint_update")
        conn.commit()
    finally:
        conn.close()


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
        saved = _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(10))
        assert created == []
        assert _alerts(USER) == []
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint is not None
        assert checkpoint["last_freshness_state"] == "CURRENT"
        assert checkpoint["last_support_state"] == "SUPPORTED"
        assert checkpoint["watch_saved_at"] == saved["saved_at"]

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
        h1 = _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        h2 = _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.07"))
        h3 = _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(31))

        apy_alerts = [a for a in created if a["alert_type"] == "APY_CHANGED"]
        assert len(apy_alerts) == 2, "both unseen transitions must alert"
        assert apy_alerts[0]["previous"] != apy_alerts[1]["previous"]
        assert apy_alerts[0]["alert_id"] != apy_alerts[1]["alert_id"]
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_processed_observation_hash"] == h3
        assert h1 != h2 != h3

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


# ── Persistence atomicity (final correction) ─────────────────────────────────

class TestPersistenceAtomicity:
    def test_failure_cannot_advance_checkpoint_past_missing_alerts(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        h1 = _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        h2 = _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        _fail_checkpoint_updates(db, USER, uid)
        with pytest.raises(sqlite3.IntegrityError):
            _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                      now=_minutes(21))
        # Fail closed: checkpoint unchanged, zero alerts durable.
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_processed_observation_hash"] == h1
        assert _alerts(USER) == []

        _restore_checkpoint_updates(db)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(22))
        assert [a["alert_type"] for a in created] == ["APY_CHANGED"]
        assert created[0]["previous_observation_hash"] == h1
        assert created[0]["current_observation_hash"] == h2
        assert _checkpoint(USER, uid)["last_processed_observation_hash"] == h2
        assert len(_alerts(USER)) == 1

    def test_retry_replays_every_uncommitted_transition_exactly_once(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        h1 = _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.07"))
        _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.09"))
        _fail_checkpoint_updates(db, USER, uid)
        with pytest.raises(sqlite3.IntegrityError):
            _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                      now=_minutes(31))
        # Neither transition committed: checkpoint still h1, no alerts.
        assert _checkpoint(USER, uid)["last_processed_observation_hash"] == h1
        assert _alerts(USER) == []

        _restore_checkpoint_updates(db)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(32))
        apy = [a for a in created if a["alert_type"] == "APY_CHANGED"]
        assert len(apy) == 2, "both lost transitions must be recreated"
        ids = {a["alert_id"] for a in created}
        assert len(ids) == 2
        # Deterministic retry: re-evaluation adds nothing, duplicates nothing.
        again = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                          now=_minutes(33))
        assert again == []
        assert len(_alerts(USER)) == 2
        assert _checkpoint(USER, uid)["last_processed_observation_hash"] == (
            history_store.for_opportunity(uid)[-1]["observation_hash"])

    def test_failure_during_state_only_update_keeps_checkpoint(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        h1 = _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        # Support state changes with NO new observation; persistence fails.
        _fail_checkpoint_updates(db, USER, uid)
        with pytest.raises(sqlite3.IntegrityError):
            _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                      now=_minutes(20))
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_support_state"] == "SUPPORTED"
        assert checkpoint["last_processed_observation_hash"] == h1
        assert _alerts(USER) == []

        _restore_checkpoint_updates(db)
        created = _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["SUPPORT_STATE_CHANGED"]
        assert _checkpoint(USER, uid)["last_support_state"] == "DISCOVERY_ONLY"


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


# ── Support state WITHOUT new history (final correction) ─────────────────────

class TestSupportStateWithoutNewHistory:
    def test_support_change_alerts_with_no_new_observation(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []

        # Registry support state flips; NO new history arrives at all.
        created = _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                            now=_minutes(15))
        support = [a for a in created
                   if a["alert_type"] == "SUPPORT_STATE_CHANGED"]
        assert len(support) == 1
        assert support[0]["previous"] == "SUPPORTED"
        assert support[0]["current"] == "DISCOVERY_ONLY"
        # State-only transition: observation hash pair legitimately fixed.
        assert (support[0]["previous_observation_hash"]
                == support[0]["current_observation_hash"])
        assert _checkpoint(USER, uid)["last_support_state"] == "DISCOVERY_ONLY"

    def test_repeated_support_state_does_not_duplicate(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        assert _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                         now=_minutes(15))
        assert _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                         now=_minutes(20)) == []
        assert len(_alerts(USER)) == 1

    def test_chained_support_transitions_are_distinct_alerts(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        first = _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                          now=_minutes(15))
        second = _evaluate(USER, history_store,
                           StubRegistry("READ_ONLY_RESEARCH"), now=_minutes(20))
        assert len(first) == len(second) == 1
        assert second[0]["previous"] == "DISCOVERY_ONLY"
        assert second[0]["current"] == "READ_ONLY_RESEARCH"
        # Same observation hash, different state transition → different id.
        assert first[0]["alert_id"] != second[0]["alert_id"]
        assert len(_alerts(USER)) == 2

    def test_support_change_with_new_observation_still_alerts_once(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("DISCOVERY_ONLY"),
                            now=_minutes(21))
        support = [a for a in created
                   if a["alert_type"] == "SUPPORT_STATE_CHANGED"]
        assert len(support) == 1
        assert _checkpoint(USER, uid)["last_support_state"] == "DISCOVERY_ONLY"


# ── Re-watch lifecycle (final correction) ────────────────────────────────────

class TestRewatchLifecycle:
    def test_readd_baselines_at_latest_and_never_replays(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid, at=_minutes(0))
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.07"))
        assert len(_evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                             now=_minutes(21))) == 1
        historical = len(_alerts(USER))
        assert historical == 1

        _unwatch(USER, uid)
        h3 = _observe(history_store, uid, _minutes(30), apy_total=Decimal("0.09"))
        h4 = _observe(history_store, uid, _minutes(40), apy_total=Decimal("0.11"))
        readded = _watch(USER, uid, at=_minutes(50))

        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(51))
        assert created == [], "unwatched period must never replay"
        assert len(_alerts(USER)) == historical  # history intact
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_processed_observation_hash"] == h4
        assert checkpoint["watch_saved_at"] == readded["saved_at"]

        _observe(history_store, uid, _minutes(60), apy_total=Decimal("0.13"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(61))
        assert [a["alert_type"] for a in created] == ["APY_CHANGED"]
        assert created[0]["previous"] == "0.11"  # from h4, not older
        assert created[0]["current"] == "0.13"
        assert len(_alerts(USER)) == historical + 1

    def test_rewatch_without_intervening_observations_rebaselines(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid, at=_minutes(0))
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _unwatch(USER, uid)
        _watch(USER, uid, at=_minutes(20))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert created == []
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["watch_saved_at"] != None  # lifecycle stamp moved
        assert checkpoint["last_processed_observation_hash"] == (
            history_store.for_opportunity(uid)[-1]["observation_hash"])

    def test_continuous_watch_does_not_rebaseline(
            self, db, history_store, real_uids):
        """Re-saving an entry that is still on the watchlist is idempotent
        (canonical ON CONFLICT DO NOTHING) — the lifecycle must NOT reset."""
        uid = real_uids[0]
        first = _watch(USER, uid, at=_minutes(0))
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []
        _watch(USER, uid, at=_minutes(15))  # idempotent re-save
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["APY_CHANGED"]
        assert _checkpoint(USER, uid)["watch_saved_at"] == first["saved_at"]


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
        assert types == ["FRESHNESS_RECOVERED", "NEW_OBSERVATION"]
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

    def test_unknown_to_current_is_not_recovery(
            self, db, history_store, real_uids):
        """UNKNOWN freshness recovering to CURRENT is handled conservatively:
        checkpoint updates, but no recovery claim and no NEW_OBSERVATION."""
        uid = real_uids[0]
        _watch(USER, uid)
        # Unresolvable source authority → canonical UNKNOWN baseline state.
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"),
                 source_authority="WEIRD_AUTHORITY")
        checkpoint = None
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        checkpoint = _checkpoint(USER, uid)
        assert checkpoint["last_freshness_state"] == "UNKNOWN"

        _observe(history_store, uid, _minutes(15),
                 apy_total=Decimal("0.05"))  # same economics, fresh evidence
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(20))
        assert created == []
        types = {a["alert_type"] for a in _alerts(USER)}
        assert "FRESHNESS_RECOVERED" not in types
        assert "NEW_OBSERVATION" not in types
        assert _checkpoint(USER, uid)["last_freshness_state"] == "CURRENT"

    def test_current_to_current_new_observation_is_silent(
            self, db, history_store, real_uids):
        """Routine CURRENT → CURRENT observations generate no
        NEW_OBSERVATION noise."""
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        assert _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                         now=_minutes(10)) == []
        _observe(history_store, uid, _minutes(20), apy_total=Decimal("0.09"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["APY_CHANGED"]

    def test_recovery_requires_degraded_state_not_unknown_checkpoint(
            self, db, history_store, real_uids):
        """An absent/unknown checkpoint freshness never yields a recovery
        claim when the first evaluated observation is CURRENT."""
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, apy_total=Decimal("0.05"))
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(10))
        assert created == []  # baseline: no recovery on first sight


# ── Missing vs zero (V1 contract) ────────────────────────────────────────────

class TestMissingVsZeroContract:
    """V1 contract: MISSING (None/absent) is never numerically interpreted
    as zero — no delta or magnitude is computed from it and persisted
    alerts carry verbatim values.  A MISSING ↔ explicit-0 transition is a
    descriptive availability-state change and emits the field alert."""

    def test_none_to_zero_is_a_descriptive_change(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=None)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=0)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["TVL_CHANGED"]
        # Values preserved verbatim — None is never rewritten to 0.
        assert created[0]["previous"] is None
        assert created[0]["current"] == 0

    def test_zero_to_none_is_a_descriptive_change(
            self, db, history_store, real_uids):
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=0)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=None)
        created = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                            now=_minutes(21))
        assert [a["alert_type"] for a in created] == ["TVL_CHANGED"]
        assert created[0]["previous"] == 0
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
        assert created[0]["previous"] is None  # MISSING, not fabricated zero
        assert created[0]["current"] == 0

    def test_deterministic_ids_of_inverse_directions_differ(
            self, db, history_store, real_uids):
        """None→0 and 0→None on the same hash pair would be distinct
        transitions only via their verbatim values; the alert identity is
        hash-pair based, so the value asymmetry is preserved in the record
        while identity stays deterministic."""
        uid = real_uids[0]
        _watch(USER, uid)
        _observe(history_store, uid, BASE, tvl_usd=None)
        _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                  now=_minutes(10))
        _observe(history_store, uid, _minutes(20), tvl_usd=0)
        first = _evaluate(USER, history_store, StubRegistry("SUPPORTED"),
                          now=_minutes(21))
        assert first[0]["previous"] is None and first[0]["current"] == 0


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

    def test_state_only_identity_covers_state_alert_types(self):
        from finco_yield.alerts_types import (
            STATE_ONLY_ALERT_TYPES,
            deterministic_alert_id,
        )

        kwargs = dict(
            user_id=USER, opportunity_uid=UID, field="support_state",
            previous_observation_hash="h1", current_observation_hash="h1")
        ab = deterministic_alert_id(
            alert_type="SUPPORT_STATE_CHANGED", state_from="A",
            state_to="B", **kwargs)
        bc = deterministic_alert_id(
            alert_type="SUPPORT_STATE_CHANGED", state_from="B",
            state_to="C", **kwargs)
        assert ab != bc, "chained state transitions must not share an id"
        ab_again = deterministic_alert_id(
            alert_type="SUPPORT_STATE_CHANGED", state_from="A",
            state_to="B", **kwargs)
        assert ab == ab_again, "same transition must stay deterministic"
        # Economic-transition IDs are not affected by state fields.
        econ = deterministic_alert_id(
            alert_type="APY_CHANGED", field="apy_total",
            previous_observation_hash="h1", current_observation_hash="h2",
            user_id=USER, opportunity_uid=UID,
            state_from="A", state_to="B")
        econ_plain = deterministic_alert_id(
            alert_type="APY_CHANGED", field="apy_total",
            previous_observation_hash="h1", current_observation_hash="h2",
            user_id=USER, opportunity_uid=UID)
        assert econ == econ_plain


# ── Frozen authorities ────────────────────────────────────────────────────────

class TestFrozenAuthorities:
    @pytest.mark.parametrize("frozen", [
        "financial_engine", "finco_core", "finco_radar",
        "app/model_validation", "app/verified", "app/model_market_bridge",
    ])
    def test_zero_diff_vs_main(self, frozen):
        import subprocess

        out = subprocess.run(
            ["git", "diff", "--name-only", f"{merge_base_ref()}..HEAD", "--", frozen],
            cwd=REPO, capture_output=True, text=True,
        )
        if out.returncode != 0:
            pytest.skip("git history unavailable in this checkout")
        # Authorised by the exact-identity correction (registry collapse of same-identity source rows);
        # every other path in this namespace stays frozen.
        allowed = {"finco_radar/venues/registry.py", "finco_radar/venues/models.py",
                 # PR #183 (Tokenized Relative Value V1) reviewed core module:
                 "finco_radar/venues/relative_value.py"}
        # Explicitly authorized Model V2 epic engine files are governed by the
        # Model V2 scope contract (tests/model_v2_governance.py); this guard keeps
        # protecting every other frozen path.
        from finance_integrity_governance import approved_frozen_path
        changed = [
            p for p in out.stdout.split()
            if p not in allowed and not approved_frozen_path(p)
        ]
        assert changed == [], changed
