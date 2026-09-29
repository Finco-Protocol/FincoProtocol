"""Network-free collector orchestration, process-health and secret-safety tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.radar_rwa import r_live_collect as collector
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID


class Ledger:
    def __init__(self, *, allowed_chain_id):
        assert allowed_chain_id == 4663
        self.closed = 0
        self.writes = []

    def close(self):
        self.closed += 1


def _result(key, state, *, reason=None, history=None):
    authority = SimpleNamespace(
        premium=SimpleNamespace(state=state, reason=reason),
        economic_asset_uid="0x" + "ab" * 32,
        canonical_token=SimpleNamespace(canonical_id=key),
    )
    onchain = SimpleNamespace(state=state, reason=reason,
                              observed_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
    if state is AuthorityState.AVAILABLE and history is not None:
        history.writes.append(key)
    return SimpleNamespace(authority=authority, onchain=onchain,
                           history_digest="digest" if state is AuthorityState.AVAILABLE else None)


def test_no_arg_batch_uses_complete_registry_and_one_serial_ledger(monkeypatch):
    keys = tuple(APPROVED_BY_CANONICAL_ID)
    assert len(keys) > 1
    ledger = Ledger(allowed_chain_id=4663)
    calls = []
    states = {keys[0]: AuthorityState.AVAILABLE,
              keys[1]: AuthorityState.STALE,
              keys[2]: AuthorityState.UNAVAILABLE}

    def acquire(*, canonical_asset_id, rpc_url, as_of, persist_history, history):
        assert rpc_url.endswith("/PRIVATE_TOKEN") and persist_history is True
        assert history is ledger
        calls.append(canonical_asset_id)
        state = states.get(canonical_asset_id, AuthorityState.AVAILABLE)
        return _result(canonical_asset_id, state, reason=(
            "POOL_ACTIVITY_STALE" if state is AuthorityState.STALE else
            "RPC_OR_SOURCE_EVIDENCE_UNAVAILABLE" if state is AuthorityState.UNAVAILABLE else None
        ), history=history)

    status, exit_code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid/PRIVATE_TOKEN", acquire=acquire,
        history_factory=lambda **kwargs: ledger,
        rpc_healthcheck=lambda _: None,
    )
    assert exit_code == 0  # mixed market states are not a process failure
    assert status["mode"] == "all_approved"
    assert status["asset_count"] == len(APPROVED_BY_CANONICAL_ID)
    assert calls == list(keys)
    assert ledger.closed == 1
    assert status["summary"] == {"available": len(keys) - 2, "stale": 1, "unavailable": 1}
    assert ledger.writes == [key for key in keys if states.get(key, AuthorityState.AVAILABLE)
                             is AuthorityState.AVAILABLE]
    assert all(row["history_digest"] is None for row in status["results"]
               if row["state"] != "AVAILABLE")
    assert "PRIVATE_TOKEN" not in json.dumps(status)


def test_batch_registry_count_is_derived_and_not_hardcoded(monkeypatch):
    keys = tuple(APPROVED_BY_CANONICAL_ID)[:2]
    monkeypatch.setattr(collector, "APPROVED_BY_CANONICAL_ID", dict.fromkeys(keys))
    ledger = Ledger(allowed_chain_id=4663)
    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid", history_factory=lambda **_: ledger,
        rpc_healthcheck=lambda _: None,
        acquire=lambda *, canonical_asset_id, history, **_: _result(
            canonical_asset_id, AuthorityState.STALE, reason="POOL_ACTIVITY_STALE"),
    )
    assert code == 0 and status["asset_count"] == 2
    assert status["summary"] == {"available": 0, "stale": 2, "unavailable": 0}
    assert ledger.closed == 1


def test_explicit_exact_key_collects_only_one_and_unapproved_fails_closed(monkeypatch, capsys):
    key = next(key for key in APPROVED_BY_CANONICAL_ID if key !=
               next(iter(APPROVED_BY_CANONICAL_ID)))
    calls = []
    def one(*, acquire, **_):
        calls.append(acquire.keywords["canonical_asset_id"])
        return {"state": "STALE", "reason": "POOL_ACTIVITY_STALE", "history_digest": None}
    monkeypatch.setattr(collector, "collect_once", one)
    assert collector.main(["--asset-key", key]) == 1
    assert calls == [key]
    assert json.loads(capsys.readouterr().out)["state"] == "STALE"
    assert collector.main(["--asset-key", "4663:0x" + "11" * 20]) == 1
    assert calls == [key]
    assert json.loads(capsys.readouterr().out)["reason"] == "ASSETKEY_NOT_APPROVED"


def test_no_arg_main_uses_batch_and_prints_safe_json(monkeypatch, capsys):
    expected = {"mode": "all_approved", "asset_count": 2, "results": [],
                "summary": {"available": 0, "stale": 2, "unavailable": 0}}
    monkeypatch.setattr(collector, "collect_all_approved", lambda: (expected, 0))
    assert collector.main([]) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_batch_config_and_ledger_failures_are_nonzero_and_redacted(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    status, code = collector.collect_all_approved()
    assert code == 1 and status["process_error"] == "RPC_NOT_CONFIGURED"
    def broken(**_):
        raise RuntimeError("https://rpc.invalid/PRIVATE_TOKEN")
    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid/PRIVATE_TOKEN", history_factory=broken,
        rpc_healthcheck=lambda _: None)
    assert code == 1 and status["process_error"] == "HISTORY_STORE_UNAVAILABLE"
    assert "PRIVATE_TOKEN" not in json.dumps(status)


def test_configured_but_unreachable_rpc_is_process_failure_without_secret():
    def unreachable(url):
        raise RuntimeError(f"transport failed for {url}")

    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid/PRIVATE_TOKEN", rpc_healthcheck=unreachable)
    assert code == 1
    assert status["process_error"] == "RPC_UNAVAILABLE"
    assert status["results"] == []
    assert "PRIVATE_TOKEN" not in json.dumps(status)


def test_rpc_preflight_checks_exact_chain_and_closes_transport(monkeypatch):
    calls = []

    class FakeRpc:
        def __init__(self, url):
            calls.append(("open", url))

        def call(self, method, params):
            calls.append((method, params))
            return hex(4663)

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(collector, "JsonRpc", FakeRpc)
    collector._check_rpc_health("https://rpc.invalid/PRIVATE_TOKEN")
    assert calls == [("open", "https://rpc.invalid/PRIVATE_TOKEN"),
                     ("eth_chainId", []), ("close",)]


def test_individual_exception_does_not_abort_batch_or_leak_secret():
    ledger = Ledger(allowed_chain_id=4663)
    calls = []
    def acquire(*, canonical_asset_id, **_):
        calls.append(canonical_asset_id)
        if len(calls) == 1:
            raise RuntimeError("https://rpc.invalid/PRIVATE_TOKEN")
        return _result(canonical_asset_id, AuthorityState.STALE,
                       reason="POOL_ACTIVITY_STALE")
    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid/PRIVATE_TOKEN", acquire=acquire,
        history_factory=lambda **_: ledger, rpc_healthcheck=lambda _: None)
    assert code == 1
    assert calls == list(APPROVED_BY_CANONICAL_ID)
    assert status["summary"]["unavailable"] == 1
    assert status["summary"]["stale"] == len(calls) - 1
    assert status["results"][0]["state"] == "UNAVAILABLE"
    assert status["results"][0]["reason"] == "R_LIVE_COLLECTION_UNAVAILABLE"
    assert status["process_error"] == "R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE"
    assert "PRIVATE_TOKEN" not in json.dumps(status)
    assert ledger.closed == 1


def test_every_acquisition_exception_attempts_every_asset_and_exits_nonzero():
    ledger = Ledger(allowed_chain_id=4663)
    calls = []

    def acquire(*, canonical_asset_id, **_):
        calls.append(canonical_asset_id)
        raise RuntimeError("https://rpc.invalid/PRIVATE_TOKEN raw exception")

    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid/PRIVATE_TOKEN", acquire=acquire,
        history_factory=lambda **_: ledger, rpc_healthcheck=lambda _: None)
    assert code == 1
    assert calls == list(APPROVED_BY_CANONICAL_ID)
    assert status["summary"] == {"available": 0, "stale": 0,
                                 "unavailable": len(calls)}
    assert status["process_error"] == "R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE"
    assert all(row["reason"] == "R_LIVE_COLLECTION_UNAVAILABLE"
               for row in status["results"])
    assert "PRIVATE_TOKEN" not in json.dumps(status)
    assert "raw exception" not in json.dumps(status)
    assert ledger.closed == 1


@pytest.mark.parametrize("market_state,reason", [
    (AuthorityState.STALE, "POOL_ACTIVITY_STALE"),
    (AuthorityState.UNAVAILABLE, "RPC_OR_SOURCE_EVIDENCE_UNAVAILABLE"),
])
def test_one_canonical_nonavailable_state_is_healthy_batch(market_state, reason):
    ledger = Ledger(allowed_chain_id=4663)
    calls = []

    def acquire(*, canonical_asset_id, **_):
        calls.append(canonical_asset_id)
        state = market_state if len(calls) == 1 else AuthorityState.AVAILABLE
        return _result(canonical_asset_id, state,
                       reason=reason if len(calls) == 1 else None,
                       history=ledger)

    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid", acquire=acquire,
        history_factory=lambda **_: ledger, rpc_healthcheck=lambda _: None)
    assert code == 0
    assert calls == list(APPROVED_BY_CANONICAL_ID)
    assert "process_error" not in status
    assert status["summary"][market_state.value.lower()] == 1
    assert ledger.closed == 1


def test_history_persistence_failure_is_process_failure():
    ledger = Ledger(allowed_chain_id=4663)
    def acquire(*, canonical_asset_id, **_):
        result = _result(canonical_asset_id, AuthorityState.AVAILABLE)
        result.history_digest = None
        return result
    status, code = collector.collect_all_approved(
        rpc_url="https://rpc.invalid", acquire=acquire,
        history_factory=lambda **_: ledger, rpc_healthcheck=lambda _: None)
    assert code == 1 and status["process_error"] == "HISTORY_STORE_UNAVAILABLE"
    assert ledger.closed == 1
