"""Yield Monitoring Automation V1 -- scheduled background alert evaluation.

The runner is orchestration only.  These tests prove it reuses the canonical
watchlist, history, freshness and alert store; that manual Refresh and the
background run share ONE evaluator core; and the operational contract
(disabled default, typed exit codes, lock, sanitized report).

Synthetic fixtures only; no network.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from finco_yield import evaluate_alerts as runner
from finco_yield.history import ImmutableObservationRecord, YieldHistoryStore

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
U1, U2, U3 = "user-one", "user-two", "user-three"
SOURCE_URI = "https://evidence.test/vault"


# ── fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "finco.db"
    hist = tmp_path / "yield_history.jsonl"
    hist.touch()                          # an existing (empty) history is valid
    monkeypatch.setenv("FINCO_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(hist))
    monkeypatch.setenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_ALERT_LOCK_PATH", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    return SimpleNamespace(db=db, history=YieldHistoryStore(hist), tmp=tmp_path, mp=monkeypatch)


@pytest.fixture()
def uids():
    from finco_yield.registry import load_bundled_registry
    found = [o.uid for o in load_bundled_registry().all()][:3]
    assert len(found) == 3
    return found


def _observe(history, uid, at, **fields):
    payload = {"apy_total": fields.pop("apy", "0.04"), "tvl_usd": fields.pop("tvl", "1000000")}
    payload.update(fields)
    return history.append_idempotent(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=at, source_authority="NATIVE_ENRICHED",
        source_uri=SOURCE_URI, adapter_version="t", payload=payload))[0]


def _watch(user, uid):
    from finco_yield.watchlist import save_watchlist_item
    save_watchlist_item(user, uid)


def _run(at=T0, **kwargs):
    out = io.StringIO()
    code = runner.main([], now=lambda: at, out=out, **kwargs)
    return code, json.loads(out.getvalue())


def _alerts(user):
    from finco_yield.alerts_store import list_alerts
    return list_alerts(user)


def _types(user):
    return sorted(a["alert_type"] for a in _alerts(user))


class StubRegistry:
    def __init__(self, support_state):
        self.support_state = support_state

    def resolve(self, uid):
        return SimpleNamespace(support_state=self.support_state)


def _use_registry(env, registry):
    env.mp.setattr("finco_yield.registry.load_bundled_registry", lambda: registry)


# ── disabled default / config ────────────────────────────────────────────────

class TestEnablementAndConfig:
    def test_disabled_by_default_touches_nothing(self, env, monkeypatch):
        monkeypatch.delenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED")

        def boom():
            raise AssertionError("must not discover users when disabled")
        code, report = _run(discover_users=boom)
        assert code == 4 and report["status"] == "DISABLED"
        assert not env.db.exists()

    @pytest.mark.parametrize("value", ["0", "", "no", "false", "off"])
    def test_falsey_values_stay_disabled(self, env, monkeypatch, value):
        monkeypatch.setenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED", value)
        assert _run()[0] == 4

    def test_flag_helper_default_off(self, monkeypatch):
        from finco_yield.flags import alert_automation_enabled
        monkeypatch.delenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED", raising=False)
        assert alert_automation_enabled() is False
        monkeypatch.setenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED", "1")
        assert alert_automation_enabled() is True

    def test_missing_history_path_is_config_error(self, env, monkeypatch):
        monkeypatch.delenv("FINCO_YIELD_HISTORY_PATH")
        code, report = _run()
        assert code == 4 and report["status"] == "CONFIG_ERROR"

    def test_unwritable_lock_directory_is_config_error(self, env, monkeypatch):
        blocker = env.tmp / "blocker"
        blocker.write_text("x")
        monkeypatch.setenv("FINCO_YIELD_ALERT_LOCK_PATH", str(blocker / "sub" / "lock"))
        code, report = _run()
        assert code == 4 and report["status"] == "CONFIG_ERROR"

    def test_execution_flag_is_never_touched(self, env, uids):
        from finco_yield.flags import execution_enabled
        assert execution_enabled() is False
        _run()
        assert execution_enabled() is False
        import os
        assert "FINCO_YIELD_EXECUTION_ENABLED" not in os.environ


# ── discovery ────────────────────────────────────────────────────────────────

class TestDiscovery:
    def test_no_watchlists_is_ok_and_empty(self, env):
        code, report = _run()
        assert code == 0 and report["status"] == "OK"
        assert report["users_discovered"] == 0 and report["users_evaluated"] == 0 and report["alerts_created"] == 0

    def test_discovery_reads_only_the_canonical_watchlist(self, env, uids):
        from finco_yield.watchlist import list_watchlist_user_ids, remove_watchlist_item
        _watch(U2, uids[0]); _watch(U1, uids[0]); _watch(U1, uids[1])
        assert list_watchlist_user_ids() == [U1, U2]                    # distinct + sorted
        remove_watchlist_item(U2, uids[0])
        assert list_watchlist_user_ids() == [U1]

    def test_user_without_history_evaluates_cleanly_with_no_alerts(self, env, uids):
        _watch(U1, uids[0])
        code, report = _run()
        assert code == 0 and report["users_evaluated"] == 1 and report["alerts_created"] == 0
        assert _alerts(U1) == []


# ── evaluation semantics through the background path ────────────────────────

class TestEvaluationSemantics:
    def test_first_run_baselines_without_alerts(self, env, uids):
        from finco_yield.alerts_store import get_checkpoint
        _watch(U1, uids[0])
        h = _observe(env.history, uids[0], T0)
        code, report = _run(T0 + timedelta(minutes=1))
        assert code == 0 and report["alerts_created"] == 0 and _alerts(U1) == []
        assert get_checkpoint(U1, uids[0])["last_processed_observation_hash"] == h

    def test_subsequent_transition_creates_a_deterministic_alert(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=10), apy="0.05")
        code, report = _run(T0 + timedelta(minutes=11))
        assert code == 0 and report["alerts_created"] == 1
        (alert,) = _alerts(U1)
        assert alert["alert_type"] == "APY_CHANGED" and alert["field"] == "apy_total"
        assert alert["alert_id"].startswith("yal_") or alert["alert_id"]

    def test_idempotent_retry_creates_nothing_new(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=10), apy="0.05")
        _run(T0 + timedelta(minutes=11))
        before = _alerts(U1)
        for minutes in (12, 13):
            code, report = _run(T0 + timedelta(minutes=minutes))
            assert code == 0 and report["alerts_created"] == 0
        assert _alerts(U1) == before and len(before) == 1

    def test_retry_after_a_crash_before_checkpoint_is_deduped_by_alert_id(self, env, uids):
        from finco_yield.alerts_store import commit_alert_state, get_checkpoint
        _watch(U1, uids[0])
        h0 = _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=10), apy="0.05")
        _run(T0 + timedelta(minutes=11))
        (alert,) = _alerts(U1)
        # simulate "alert durable but checkpoint rolled back" by re-committing the old checkpoint
        commit_alert_state(U1, uids[0], [], last_processed_observation_hash=h0,
                           last_freshness_state="CURRENT", last_support_state="READ_ONLY_RESEARCH",
                           watch_saved_at=get_checkpoint(U1, uids[0])["watch_saved_at"])
        code, report = _run(T0 + timedelta(minutes=12))
        assert code == 0 and report["alerts_created"] == 0 and _alerts(U1) == [alert]

    def test_freshness_degradation_without_new_observation(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)
        _run(T0 + timedelta(minutes=1))                                  # CURRENT baseline
        code, report = _run(T0 + timedelta(hours=3))                     # no new observation
        assert code == 0 and report["alerts_created"] == 1
        assert _types(U1) == ["FRESHNESS_DEGRADED"]
        assert _run(T0 + timedelta(hours=3, minutes=10))[1]["alerts_created"] == 0   # not repeated

    def test_support_state_change_is_canonical(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)
        _use_registry(env, StubRegistry("DISCOVERY_ONLY"))
        _run(T0 + timedelta(minutes=1))
        _use_registry(env, StubRegistry("READ_ONLY_RESEARCH"))
        code, report = _run(T0 + timedelta(minutes=2))
        assert code == 0 and _types(U1) == ["SUPPORT_STATE_CHANGED"]

    def test_missing_to_zero_and_zero_to_missing_are_availability_changes(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0, apy=None)                     # MISSING
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=5), apy="0")   # explicit zero
        _run(T0 + timedelta(minutes=6))
        _observe(env.history, uids[0], T0 + timedelta(minutes=10), apy=None)  # MISSING again
        _run(T0 + timedelta(minutes=11))
        apy = [a for a in _alerts(U1) if a["alert_type"] == "APY_CHANGED"]
        assert len(apy) == 2
        by_current = {json.dumps(a["current"]): a for a in apy}
        zero = next(a for a in apy if a["previous"] is None)
        back = next(a for a in apy if a["current"] is None)
        assert zero["current"] in (0, "0", 0.0) and back["previous"] in (0, "0", 0.0)
        assert by_current                                               # verbatim values, no deltas computed
        assert all("delta" not in a for a in apy)

    def test_rewatch_starts_a_fresh_lifecycle_without_replay(self, env, uids):
        from finco_yield.watchlist import remove_watchlist_item
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        remove_watchlist_item(U1, uids[0])
        _observe(env.history, uids[0], T0 + timedelta(minutes=5), apy="0.09")
        _watch(U1, uids[0])
        code, report = _run(T0 + timedelta(minutes=6))
        assert code == 0 and report["alerts_created"] == 0 and _alerts(U1) == []   # no replay

    def test_every_unseen_transition_is_processed_in_order(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        for step, apy in ((5, "0.05"), (6, "0.06")):
            _observe(env.history, uids[0], T0 + timedelta(minutes=step), apy=apy)
        code, report = _run(T0 + timedelta(minutes=7))
        assert report["alerts_created"] == 2 and _types(U1) == ["APY_CHANGED", "APY_CHANGED"]


# ── multiple users, isolation, failures ──────────────────────────────────────

class TestUsersAndFailures:
    def _setup_three(self, env, uids):
        for user in (U1, U2, U3):
            _watch(user, uids[0])
        _observe(env.history, uids[0], T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=10), apy="0.05")

    def test_multiple_users_all_evaluated_with_one_shared_instant(self, env, uids):
        self._setup_three(env, uids)
        at = T0 + timedelta(minutes=11)
        code, report = _run(at)
        assert code == 0 and report["users_discovered"] == 3 and report["users_evaluated"] == 3
        assert report["alerts_created"] == 3 and report["failures"] == []
        stamps = {a["detected_at"] for u in (U1, U2, U3) for a in _alerts(u)}
        assert stamps == {at.isoformat()}                                 # ONE evaluation instant
        assert report["evaluated_at"] == at.isoformat().replace("+00:00", "Z")

    def test_per_user_alerts_are_isolated(self, env, uids):
        _watch(U1, uids[0]); _watch(U2, uids[1])
        for uid in uids[:2]:
            _observe(env.history, uid, T0, apy="0.04")
        _run(T0 + timedelta(minutes=1))
        _observe(env.history, uids[0], T0 + timedelta(minutes=5), apy="0.07")
        _run(T0 + timedelta(minutes=6))
        assert len(_alerts(U1)) == 1 and _alerts(U2) == []

    def test_persistence_failure_is_partial_and_isolated(self, env, uids):
        from finco_yield import alerts_eval
        from finco_yield.alerts_store import get_checkpoint
        self._setup_three(env, uids)
        real = alerts_eval.commit_alert_state

        def flaky(user_id, *args, **kwargs):
            if user_id == U2:
                raise sqlite3.OperationalError("database is locked")
            return real(user_id, *args, **kwargs)
        env.mp.setattr(alerts_eval, "commit_alert_state", flaky)
        before = get_checkpoint(U2, uids[0])
        code, report = _run(T0 + timedelta(minutes=11))
        assert code == 3 and report["status"] == "PARTIAL"
        assert report["users_evaluated"] == 2 and report["users_failed"] == 1
        assert report["failures"] == [{"user_ref": runner.user_ref(U2), "reason": "ALERT_EVALUATION_UNAVAILABLE"}]
        assert len(_alerts(U1)) == 1 and len(_alerts(U3)) == 1 and _alerts(U2) == []
        assert get_checkpoint(U2, uids[0]) == before                       # failed user's checkpoint did not move
        # the next run (persistence healthy again) delivers U2's alert exactly once
        env.mp.setattr(alerts_eval, "commit_alert_state", real)
        code, report = _run(T0 + timedelta(minutes=12))
        assert code == 0 and report["alerts_created"] == 1 and len(_alerts(U2)) == 1

    def test_all_users_failing_is_failed_not_success(self, env, uids):
        from finco_yield import alerts_eval
        self._setup_three(env, uids)

        def always(*a, **k):
            raise sqlite3.OperationalError("down")
        env.mp.setattr(alerts_eval, "commit_alert_state", always)
        code, report = _run(T0 + timedelta(minutes=11))
        assert code == 2 and report["status"] == "FAILED" and report["users_failed"] == 3
        assert report["users_evaluated"] == 0

    def test_unexpected_exception_for_one_user_never_stops_the_run(self, env, uids):
        from app.yield_alerts_gateway import YieldAlertsGateway
        self._setup_three(env, uids)
        real = YieldAlertsGateway.evaluate_user.__func__

        def sometimes(cls, user_id, **kw):
            if user_id == U1:
                raise RuntimeError("secret-bearing /home/private/path")
            return real(cls, user_id, **kw)
        env.mp.setattr(YieldAlertsGateway, "evaluate_user", classmethod(sometimes))
        code, report = _run(T0 + timedelta(minutes=11))
        assert code == 3 and report["users_evaluated"] == 2
        assert report["failures"][0]["reason"] == "ALERT_EVALUATION_ERROR"
        assert "secret-bearing" not in json.dumps(report) and "/home/private" not in json.dumps(report)

    def test_unavailable_history_is_failed_never_success(self, env, uids):
        _watch(U1, uids[0])
        env.history.path.write_bytes(b'{"opportunity_uid":"x"')           # torn / malformed
        code, report = _run()
        assert code == 2 and report["status"] == "FAILED" and report["reason"] == "YIELD_HISTORY_UNAVAILABLE"
        assert report["users_evaluated"] == 0 and _alerts(U1) == []

    def test_missing_history_file_is_failed_never_success(self, env, uids):
        _watch(U1, uids[0]); env.tmp.joinpath("yield_history.jsonl").unlink()
        code, report = _run()
        assert code == 2 and report["reason"] == "YIELD_HISTORY_UNAVAILABLE"

    def test_unavailable_registry_is_failed_never_success(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)

        def broken():
            raise OSError("registry gone")
        env.mp.setattr("finco_yield.registry.load_bundled_registry", broken)
        code, report = _run()
        assert code == 2 and report["reason"] == "YIELD_REGISTRY_UNAVAILABLE"

    def test_unavailable_watchlist_is_failed(self, env, uids):
        _observe(env.history, uids[0], T0)

        def broken():
            raise sqlite3.OperationalError("no db")
        code, report = _run(discover_users=broken)
        assert code == 2 and report["reason"] == "WATCHLIST_UNAVAILABLE"

    def test_invalid_freshness_input_is_never_converted_to_success(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)
        code, report = _run(datetime(2026, 10, 3, 12, 5))                  # naive evaluation clock
        assert code == 2 and report["status"] == "FAILED"
        assert report["users_failed"] == 1 and report["users_evaluated"] == 0


# ── lock / concurrency ───────────────────────────────────────────────────────

class TestLocking:
    def test_second_run_exits_locked_and_does_nothing(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)
        lock = Path(str(env.history.path) + ".alerts-eval.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)

            def boom():
                raise AssertionError("a locked run must not evaluate")
            code, report = _run(discover_users=boom)
        assert code == 75 and report["status"] == "LOCKED"
        # once released the same command runs normally
        assert _run(T0 + timedelta(minutes=1))[0] == 0

    def test_custom_lock_path_is_honoured(self, env, uids):
        custom = env.tmp / "locks" / "eval.lock"
        env.mp.setenv("FINCO_YIELD_ALERT_LOCK_PATH", str(custom))
        custom.parent.mkdir()
        with open(custom, "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert _run()[0] == 75
        assert _run()[0] == 0

    def test_lock_is_released_after_a_run(self, env, uids):
        for _ in range(3):
            assert _run()[0] == 0

    def test_lock_is_released_even_when_the_run_fails(self, env, uids):
        _watch(U1, uids[0]); env.tmp.joinpath("yield_history.jsonl").unlink()
        assert _run()[0] == 2                                              # no history file -> FAILED
        _observe(env.history, uids[0], T0)
        assert _run(T0 + timedelta(minutes=1))[0] == 0


# ── manual / background parity ───────────────────────────────────────────────

class _FixedDatetime(datetime):
    _fixed = T0

    @classmethod
    def now(cls, tz=None):
        return cls._fixed if tz is None else cls._fixed.astimezone(tz)


def _snapshot(user):
    from finco_yield.alerts_store import list_alerts
    conn = sqlite3.connect(str(__import__("os").environ["FINCO_DB_PATH"]))
    conn.row_factory = sqlite3.Row
    try:
        checkpoints = [
            (r["opportunity_uid"], r["last_processed_observation_hash"],
             r["last_freshness_state"], r["last_support_state"])
            for r in conn.execute("SELECT * FROM yield_alert_state WHERE user_id=? ORDER BY opportunity_uid", (user,))]
    finally:
        conn.close()
    alerts = sorted((a["alert_id"], a["alert_type"], a["field"], json.dumps(a["previous"]),
                     json.dumps(a["current"]), a["previous_observation_hash"],
                     a["current_observation_hash"], a["detected_at"]) for a in list_alerts(user))
    return alerts, checkpoints


class TestManualParity:
    def test_manual_refresh_delegates_to_the_shared_core(self, env, uids, monkeypatch):
        from app.yield_alerts_gateway import AlertsEvaluationOutcome, YieldAlertsGateway
        calls = []

        def spy(cls, user_id, **kw):
            calls.append((user_id, kw))
            return AlertsEvaluationOutcome(True, None, 0)
        monkeypatch.setattr(YieldAlertsGateway, "evaluate_user", classmethod(spy))
        result = YieldAlertsGateway().refresh(U1)
        assert calls == [(U1, {})] and result.available and result.created_count == 0

    def test_background_run_calls_the_same_core_once_per_user(self, env, uids, monkeypatch):
        from app.yield_alerts_gateway import AlertsEvaluationOutcome, YieldAlertsGateway
        _watch(U1, uids[0]); _watch(U2, uids[0])
        _observe(env.history, uids[0], T0)
        seen = []

        def spy(cls, user_id, **kw):
            seen.append(user_id)
            assert kw["history_store"] is not None and kw["registry"] is not None and kw["now"] == T0
            return AlertsEvaluationOutcome(True, None, 0)
        monkeypatch.setattr(YieldAlertsGateway, "evaluate_user", classmethod(spy))
        _run(T0)
        assert seen == [U1, U2]

    def test_manual_and_background_produce_equivalent_canonical_state(self, env, uids, tmp_path, monkeypatch):
        """Same history, watchlist, checkpoints, registry and evaluation time."""
        import finco_yield.alerts_eval as alerts_eval
        from app.yield_alerts_gateway import YieldAlertsGateway
        monkeypatch.setattr(alerts_eval, "datetime", _FixedDatetime)

        def at(moment):
            _FixedDatetime._fixed = moment

        steps = [
            (T0 + timedelta(minutes=1), None),                                         # baseline
            (T0 + timedelta(minutes=12), lambda h: _observe(h, uids[0], T0 + timedelta(minutes=10), apy="0.05")),
            (T0 + timedelta(hours=4), lambda h: _observe(h, uids[1], T0 + timedelta(hours=3), apy=None)),
        ]

        def drive(name, evaluate):
            # identical inputs, independent stores: same history content, same
            # watchlist, same registry, same evaluation instants.
            db_path, hist_path = tmp_path / f"{name}.db", tmp_path / f"{name}.jsonl"
            hist_path.touch()
            monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
            monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(hist_path))
            history = YieldHistoryStore(hist_path)
            _observe(history, uids[0], T0, apy="0.04", tvl="1000")
            _observe(history, uids[1], T0, apy="0.03", tvl="500")
            _watch("parity", uids[0]); _watch("parity", uids[1])
            for moment, mutate in steps:
                if mutate:
                    mutate(history)
                at(moment)
                evaluate(moment)
            return _snapshot("parity")

        manual = drive("manual", lambda moment: YieldAlertsGateway().refresh("parity"))
        background = drive("background", lambda moment: _run(moment))
        assert manual == background
        assert len(manual[0]) >= 2 and len(manual[1]) == 2                     # alerts really happened


# ── report / privacy / structure ─────────────────────────────────────────────

class TestReportAndSafety:
    def test_report_structure(self, env, uids):
        _watch(U1, uids[0])
        _observe(env.history, uids[0], T0)
        code, report = _run(T0 + timedelta(minutes=1))
        assert set(report) == {
            "schema", "status", "exit_code", "started_at", "finished_at", "evaluated_at",
            "users_discovered", "users_evaluated", "users_failed", "alerts_created",
            "failures", "reason"}
        assert report["schema"] == "YIELD_ALERT_EVALUATION_REPORT_V1" and report["status"] == "OK"
        assert report["exit_code"] == code == 0

    def test_report_is_one_json_line(self, env, uids):
        out = io.StringIO()
        runner.main([], now=lambda: T0, out=out)
        assert out.getvalue().count("\n") == 1

    def test_no_user_ids_secrets_or_paths_in_the_report(self, env, uids, monkeypatch):
        from finco_yield import alerts_eval
        secret_user = "alice@example.com"
        monkeypatch.setenv("SOME_API_TOKEN", "hunter2-token")
        _watch(secret_user, uids[0])
        _observe(env.history, uids[0], T0)
        monkeypatch.setattr(alerts_eval, "commit_alert_state",
                            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("/var/secret/path")))
        code, report = _run(T0 + timedelta(minutes=1))
        text = json.dumps(report)
        assert code == 2 and "alice" not in text and "example.com" not in text
        assert "hunter2" not in text and "/var/secret" not in text and str(env.tmp) not in text
        assert report["failures"][0]["user_ref"] == hashlib.sha256(secret_user.encode()).hexdigest()[:12]

    def test_user_ref_is_stable_and_not_the_raw_id(self):
        assert runner.user_ref("u") == runner.user_ref("u") and runner.user_ref("u") != "u"
        assert len(runner.user_ref("u")) == 12

    def test_runner_never_mutates_the_environment(self, env, uids):
        import os
        before = dict(os.environ)
        _run()
        assert dict(os.environ) == before

    def test_module_has_no_loop_sleep_network_or_delivery(self):
        src = (REPO / "finco_yield" / "evaluate_alerts.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.While)), "no loop in the runner"
        lowered = src.lower()
        for token in ("time.sleep", "smtplib", "telegram.", "discord.", "requests.", "httpx", "webpush"):
            assert token not in lowered
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add((node.module or ""))
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert not {m for m in imported if any(x in m for x in ("execution", "onchain", "providers", "live_sources"))}

    def test_runner_adds_no_economics_it_only_orchestrates(self):
        src = (REPO / "finco_yield" / "evaluate_alerts.py").read_text()
        for token in ("apy_total", "tvl_usd", "Decimal", "evaluate_freshness", "history_store.append"):
            assert token not in src


# ── deployment wiring / UX truth ─────────────────────────────────────────────

class TestDeployAndUx:
    base = REPO / "deploy" / "yield_alert_automation_v1"

    def test_units_are_prepared_not_installed(self):
        for service in (self.base / "finco-yield-alert-evaluator.service",
                        self.base / "staging" / "finco-staging-yield-alert-evaluator.service"):
            text = service.read_text()
            headers = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("[")]
            assert "[Install]" not in headers
            assert "Type=oneshot" in text and "flock -n -E 75" in text
            assert "python -m finco_yield.evaluate_alerts" in text
            assert "SuccessExitStatus=3" in text and "NoNewPrivileges=true" in text
        for timer, unit in ((self.base / "finco-yield-alert-evaluator.timer", "finco-yield-alert-evaluator.service"),
                            (self.base / "staging" / "finco-staging-yield-alert-evaluator.timer",
                             "finco-staging-yield-alert-evaluator.service")):
            text = timer.read_text()
            assert f"Unit={unit}" in text and "OnCalendar=*-*-* *:03/10:00" in text   # after the collector

    def test_env_examples_default_off_and_hold_no_secret(self):
        for example in (self.base / "yield-alert-evaluator.env.example",
                        self.base / "staging" / "yield-alert-evaluator.staging.env.example",
                        REPO / "deploy" / "staging.env.example"):
            text = example.read_text()
            assert "FINCO_YIELD_ALERT_AUTOMATION_ENABLED=0" in text
            if example.name == "staging.env.example":
                continue                  # shared file holds pre-existing placeholders
            for forbidden in ("API_KEY=", "TOKEN=", "SECRET=", "PASSWORD=", "BOT_TOKEN", "SMTP"):
                assert forbidden not in text.upper()
        assert "FINCO_YIELD_EXECUTION_ENABLED=0" in (REPO / "deploy" / "staging.env.example").read_text()

    def test_readme_does_not_claim_external_delivery(self):
        text = (self.base / "README.md").read_text()
        assert "Nothing is sent externally" in text
        assert "no email, Telegram, Discord" in text.lower() or "no email, telegram, discord" in text.lower()

    def _crypto_client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.crypto_ui import router
        app = FastAPI()
        app.include_router(router)
        monkeypatch.setattr("app.auth.resolve_request_session", lambda request: None)
        return TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    def test_crypto_page_states_automation_disabled_by_default(self, env, monkeypatch):
        monkeypatch.delenv("FINCO_YIELD_ALERT_AUTOMATION_ENABLED")
        import app.persistence.db as _db
        monkeypatch.setattr(_db, "DB_PATH", str(env.tmp / "crypto.db"))
        html = self._crypto_client(monkeypatch).get("/crypto").text
        assert "Background scheduler = NOT SHIPPED" in html
        assert "Email = NOT SHIPPED" in html and "Telegram = NOT SHIPPED" in html
        assert "ENABLED by configuration" not in html

    def test_crypto_page_states_configured_automation_without_claiming_delivery(self, env, monkeypatch):
        import app.persistence.db as _db
        monkeypatch.setattr(_db, "DB_PATH", str(env.tmp / "crypto.db"))
        html = self._crypto_client(monkeypatch).get("/crypto").text
        assert "Automated monitoring = ENABLED by configuration (in-app only)" in html
        assert "Background scheduler = NOT SHIPPED" not in html
        for external in ("Email", "Telegram", "Discord", "Push"):
            assert f"{external} = NOT SHIPPED" in html
        lowered = html.lower()
        assert "email sent" not in lowered and "notifications are sent" not in lowered
