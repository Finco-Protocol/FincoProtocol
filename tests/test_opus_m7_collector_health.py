"""Opus M-7 — systemic collector-health semantics."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import sqlite3

import pytest

from app.radar_rwa.collector_health import (
    CollectorHealthStore,
    DEGRADED,
    HEALTHY,
    UNHEALTHY,
    read_collector_health_readonly,
)
from app.radar_rwa import r_live_collect


class _Ledger:
    def close(self):
        return None


def _health_factory(path):
    return partial(CollectorHealthStore, path=str(path))


def _run(monkeypatch, tmp_path, statuses, *, rpc_error=None):
    db = tmp_path / "radar.db"
    keys = tuple(f"4663:0x{i:040x}" for i in range(len(statuses)))
    monkeypatch.setattr(r_live_collect, "APPROVED_BY_CANONICAL_ID", {key: object() for key in keys})
    index = [0]

    def fake_once(**kwargs):
        item = statuses[index[0]]
        index[0] += 1
        if item.get("process_error"):
            kwargs["process_errors"].append(item["process_error"])
        return {k: v for k, v in item.items() if k != "process_error"}

    monkeypatch.setattr(r_live_collect, "collect_once", fake_once)

    def rpc_health(_url):
        if rpc_error is not None:
            raise rpc_error

    response, exit_code = r_live_collect.collect_all_approved(
        rpc_url="https://rpc.example.invalid/",
        history_factory=lambda **_: _Ledger(),
        rpc_healthcheck=rpc_health,
        health_factory=_health_factory(db),
    )
    return db, response, exit_code


def test_m7_successful_cycle_updates_attempt_success_and_counts(monkeypatch, tmp_path):
    db, response, exit_code = _run(monkeypatch, tmp_path, [
        {"state": "AVAILABLE", "reason": None, "history_digest": "a"},
        {"state": "STALE", "reason": "POOL_ACTIVITY_STALE", "history_digest": None},
        {"state": "UNAVAILABLE", "reason": "NO_QUOTE", "history_digest": None},
    ])
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 0
    assert health.health_state == HEALTHY
    assert health.batch_outcome == "SUCCESS"
    assert health.last_attempt_at is not None and health.last_success_at is not None
    assert (health.assets_attempted, health.available_count, health.stale_count,
            health.unavailable_count) == (3, 1, 1, 1)
    assert "process_error" not in response


def test_m7_individual_market_unavailable_does_not_make_system_unhealthy(monkeypatch, tmp_path):
    db, _, exit_code = _run(monkeypatch, tmp_path, [
        {"state": "UNAVAILABLE", "reason": "MARKET_EVIDENCE_UNAVAILABLE", "history_digest": None},
        {"state": "UNAVAILABLE", "reason": "QUOTE_STALE", "history_digest": None},
    ])
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 0
    assert health.health_state == HEALTHY
    assert health.systemic_failure_reason is None


def test_m7_registry_wide_typed_failure_is_systemic(monkeypatch, tmp_path):
    db, response, exit_code = _run(monkeypatch, tmp_path, [
        {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
         "history_digest": None, "process_error": "REGISTRY_UNAVAILABLE"},
        {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
         "history_digest": None, "process_error": "REGISTRY_UNAVAILABLE"},
    ])
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 1
    assert response["process_error"] == "R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE"
    assert health.health_state == UNHEALTHY
    assert health.systemic_failure_reason == "REGISTRY_UNAVAILABLE"
    assert health.consecutive_systemic_failures == 1


def test_m7_global_rpc_failure_is_systemic_and_sanitized(monkeypatch, tmp_path):
    db, response, exit_code = _run(
        monkeypatch, tmp_path,
        [{"state": "AVAILABLE", "reason": None, "history_digest": "unused"}],
        rpc_error=RuntimeError("https://user:secret@example.invalid private error"),
    )
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 1
    assert response["process_error"] == "RPC_UNAVAILABLE"
    assert health.health_state == UNHEALTHY
    assert health.systemic_failure_reason == "RPC_UNAVAILABLE"
    payload = str(health.public_dict()) + str(response)
    assert "secret" not in payload and "example.invalid" not in payload


def test_m7_history_persistence_failure_is_systemic(monkeypatch, tmp_path):
    db, response, exit_code = _run(monkeypatch, tmp_path, [
        {"state": "UNAVAILABLE", "reason": "HISTORY_PERSISTENCE_UNAVAILABLE",
         "history_digest": None},
    ])
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 1
    assert response["process_error"] == "HISTORY_STORE_UNAVAILABLE"
    assert health.health_state == UNHEALTHY
    assert health.systemic_failure_reason == "HISTORY_STORE_UNAVAILABLE"


def test_m7_partial_runtime_failure_is_degraded_not_systemic(monkeypatch, tmp_path):
    db, _, exit_code = _run(monkeypatch, tmp_path, [
        {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
         "history_digest": None, "process_error": "R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE"},
        {"state": "AVAILABLE", "reason": None, "history_digest": "ok"},
    ])
    health = read_collector_health_readonly(path=str(db))
    assert exit_code == 1
    assert health.health_state == DEGRADED
    assert health.systemic_failure_reason is None
    assert health.consecutive_systemic_failures == 0


def test_m7_consecutive_systemic_failures_increment_and_success_resets(tmp_path):
    db = tmp_path / "radar.db"
    with CollectorHealthStore(path=str(db)) as store:
        store.record_attempt()
        first = store.record_systemic_failure("RPC_UNAVAILABLE")
        second = store.record_systemic_failure("RPC_UNAVAILABLE")
        success = store.record_success(attempted=2, available=1, stale=0, unavailable=1)
    assert first.consecutive_systemic_failures == 1
    assert second.consecutive_systemic_failures == 2
    assert success.consecutive_systemic_failures == 0
    assert success.health_state == HEALTHY


def test_m7_readonly_health_does_not_write_market_history(tmp_path):
    db = tmp_path / "radar.db"
    with CollectorHealthStore(path=str(db)) as store:
        store.record_attempt()
        store.record_systemic_failure("RPC_UNAVAILABLE")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE market_sentinel (value TEXT)")
        conn.execute("INSERT INTO market_sentinel VALUES ('unchanged')")
        conn.commit()
        before = conn.total_changes
    health = read_collector_health_readonly(path=str(db))
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT value FROM market_sentinel").fetchone()
    assert health.health_state == UNHEALTHY
    assert row == ("unchanged",)
    assert before == 1


def test_m7_restart_reload_preserves_failure_without_fabricated_success(tmp_path):
    db = tmp_path / "radar.db"
    with CollectorHealthStore(path=str(db)) as store:
        store.record_attempt(now=datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc))
        store.record_systemic_failure(
            "RPC_UNAVAILABLE", now=datetime(2026, 9, 29, 20, 1, tzinfo=timezone.utc)
        )
    reloaded = read_collector_health_readonly(path=str(db))
    assert reloaded.health_state == UNHEALTHY
    assert reloaded.last_success_at is None
    assert reloaded.systemic_failure_reason == "RPC_UNAVAILABLE"


def test_m7_missing_health_db_is_unhealthy_never_run_without_creating_file(tmp_path):
    db = tmp_path / "absent.db"
    health = read_collector_health_readonly(path=str(db))
    assert health.health_state == UNHEALTHY
    assert health.batch_outcome == "NEVER_RUN"
    assert health.last_success_at is None
    assert not db.exists()
