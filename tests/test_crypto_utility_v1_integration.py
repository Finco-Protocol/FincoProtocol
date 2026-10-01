"""Final A+B+C crypto-utility integration contracts.

Agent A remains alert/economic authority; Agent C remains routing/presentation;
D proves the narrow runtime seam between them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

USER = "integration-user"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    db = tmp_path / "finco.db"
    history = tmp_path / "yield_history.jsonl"
    monkeypatch.setenv("FINCO_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(history))
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    from app.crypto_alerts import reset_alerts_gateway
    reset_alerts_gateway(pending=False)
    yield SimpleNamespace(db=db, history=history)
    reset_alerts_gateway()


@pytest.fixture()
def client():
    from app.crypto_ui import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _session(monkeypatch, user_id=USER):
    session = None if user_id is None else SimpleNamespace(
        user_id=user_id, username="demo", login_at=None, session_type="demo")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)


def _uid():
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().all()[0].uid


def _watch(uid):
    from finco_yield.watchlist import save_watchlist_item
    return save_watchlist_item(USER, uid)


def _observe(path, uid, at, **fields):
    from finco_yield.history import ImmutableObservationRecord, YieldHistoryStore
    store = YieldHistoryStore(path)
    store.append(ImmutableObservationRecord(
        opportunity_uid=uid,
        observed_at=at,
        source_authority="NATIVE_ENRICHED",
        source_uri="https://evidence.test/integration",
        adapter_version="y0.1",
        payload=fields,
    ))


def _decision(state="TOKEN_ENTITLEMENT_FEATURE_INACTIVE", *,
              access_allowed=True, gate_active=False, reason="TOKEN_GATING_OFF"):
    from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource
    return YieldAccessDecision(
        resource=YieldResource.ALERTS,
        state=YieldAccessState(state),
        access_allowed=access_allowed,
        token_entitled=access_allowed and gate_active,
        gate_active=gate_active,
        reason=reason,
    )


def _stub_access(monkeypatch, decision=None):
    async def fake_resolve(request, resource):
        return decision or _decision()
    monkeypatch.setattr("finco_yield.access.resolve_yield_access", fake_resolve)


class TestGateway:
    def test_first_refresh_baselines_without_historical_alert_flood(self, _env):
        from app.yield_alerts_gateway import YieldAlertsGateway
        uid = _uid()
        _watch(uid)
        _observe(_env.history, uid, datetime.now(timezone.utc) - timedelta(minutes=3),
                 apy_total=Decimal("0.05"), tvl_usd=Decimal("1000000"))
        result = YieldAlertsGateway().refresh(USER)
        assert result.available is True
        assert result.created_count == 0
        assert result.snapshot.unread_count == 0
        assert result.snapshot.items == ()

    def test_new_apy_evidence_maps_to_stable_alert_and_read_state(self, _env):
        from app.yield_alerts_gateway import YieldAlertsGateway
        uid = _uid()
        _watch(uid)
        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        _observe(_env.history, uid, base, apy_total=Decimal("0.05"))
        gateway = YieldAlertsGateway()
        assert gateway.refresh(USER).created_count == 0
        _observe(_env.history, uid, base + timedelta(minutes=2),
                 apy_total=Decimal("0.07"))
        result = gateway.refresh(USER)
        assert result.created_count == 1
        assert result.snapshot.unread_count == 1
        item = result.snapshot.items[0]
        assert item["alert_type"] == "APY_CHANGED"
        assert item["opportunity_uid"] == uid
        assert item["field"] == "apy_total"
        assert item["previous"] == "0.05"
        assert item["current"] == "0.07"
        assert item["alert_id"] and item["label"] and item["detected_at"]
        assert item["opportunity_display"]
        alert_id = item["alert_id"]
        assert gateway.mark_read(USER, alert_id) is True
        after = gateway.snapshot(USER)
        assert after.unread_count == 0
        assert after.items[0]["alert_id"] == alert_id
        assert after.items[0]["read"] is True

    def test_mark_all_read_reduces_exact_unread_count_to_zero(self, _env):
        from app.yield_alerts_gateway import YieldAlertsGateway
        uid = _uid()
        _watch(uid)
        base = datetime.now(timezone.utc) - timedelta(minutes=8)
        _observe(_env.history, uid, base,
                 apy_total=Decimal("0.05"), tvl_usd=Decimal("100"))
        gateway = YieldAlertsGateway()
        gateway.refresh(USER)
        _observe(_env.history, uid, base + timedelta(minutes=2),
                 apy_total=Decimal("0.06"), tvl_usd=Decimal("110"))
        assert gateway.refresh(USER).snapshot.unread_count == 2
        assert gateway.mark_all_read(USER) == 2
        assert gateway.snapshot(USER).unread_count == 0

    def test_missing_history_is_unavailable_but_persisted_alerts_stay_readable(
            self, _env, monkeypatch):
        from app.yield_alerts_gateway import YieldAlertsGateway
        uid = _uid()
        _watch(uid)
        base = datetime.now(timezone.utc) - timedelta(minutes=6)
        _observe(_env.history, uid, base, apy_total=Decimal("0.05"))
        gateway = YieldAlertsGateway()
        gateway.refresh(USER)
        _observe(_env.history, uid, base + timedelta(minutes=2),
                 apy_total=Decimal("0.08"))
        gateway.refresh(USER)
        assert gateway.snapshot(USER).unread_count == 1
        monkeypatch.delenv("FINCO_YIELD_HISTORY_PATH")
        result = gateway.refresh(USER)
        assert result.available is False
        assert result.reason == "YIELD_HISTORY_UNAVAILABLE"
        assert result.created_count is None
        assert result.snapshot.available is True
        assert result.snapshot.unread_count == 1

    def test_malformed_history_is_not_interpreted_as_zero(self, _env):
        from app.yield_alerts_gateway import YieldAlertsGateway
        _env.history.write_text("{not-json}\n", encoding="utf-8")
        result = YieldAlertsGateway().refresh(USER)
        assert result.available is False
        assert result.reason == "YIELD_HISTORY_UNAVAILABLE"
        assert result.created_count is None


class TestRoutes:
    def test_anonymous_refresh_never_evaluates(self, client):
        response = client.post("/crypto/alerts/refresh", headers={"X-CSRF-Token": "x"})
        assert response.status_code == 401

    def test_inactive_gate_proceeds_after_csrf(self, client, monkeypatch):
        from app.auth import generate_csrf_token
        from app.crypto_alerts import AlertsSnapshot, set_alerts_gateway
        _session(monkeypatch)
        _stub_access(monkeypatch)
        calls = []

        class Gateway:
            def snapshot(self, user_id): return AlertsSnapshot(True, None, 0, ())
            def mark_read(self, *args): return False
            def mark_all_read(self, *args): return 0
            def refresh(self, user_id):
                calls.append(user_id)
                return SimpleNamespace(available=True, public_dict=lambda: {
                    "state": "REFRESHED", "reason": None, "created_count": 0, "alerts": {}})

        set_alerts_gateway(Gateway())
        assert client.post("/crypto/alerts/refresh").status_code == 403
        assert calls == []
        response = client.post("/crypto/alerts/refresh",
                               headers={"X-CSRF-Token": generate_csrf_token()})
        assert response.status_code == 200
        assert calls == [USER]

    def test_allow_proceeds(self, client, monkeypatch):
        from app.auth import generate_csrf_token
        from app.crypto_alerts import AlertsSnapshot, set_alerts_gateway
        _session(monkeypatch)
        _stub_access(monkeypatch, _decision(
            "ENTITLED", access_allowed=True, gate_active=True,
            reason="BALANCE_AT_OR_ABOVE_THRESHOLD"))
        calls = []

        class Gateway:
            def snapshot(self, user_id): return AlertsSnapshot(True, None, 0, ())
            def mark_read(self, *args): return False
            def mark_all_read(self, *args): return 0
            def refresh(self, user_id):
                calls.append(user_id)
                return SimpleNamespace(available=True, public_dict=lambda: {
                    "state": "REFRESHED", "reason": None, "created_count": 0, "alerts": {}})

        set_alerts_gateway(Gateway())
        assert client.post("/crypto/alerts/refresh",
                           headers={"X-CSRF-Token": generate_csrf_token()}).status_code == 200
        assert calls == [USER]

    def test_deny_fails_before_gateway_or_evaluator(self, client, monkeypatch):
        from app.auth import generate_csrf_token
        from app.crypto_alerts import set_alerts_gateway
        _session(monkeypatch)
        _stub_access(monkeypatch, _decision(
            "ENTITLEMENT_NOT_SATISFIED", access_allowed=False, gate_active=True,
            reason="BALANCE_BELOW_THRESHOLD"))
        calls = []

        class NeverGateway:
            def snapshot(self, user_id): calls.append("snapshot"); raise AssertionError
            def mark_read(self, *args): raise AssertionError
            def mark_all_read(self, *args): raise AssertionError
            def refresh(self, user_id): calls.append("refresh"); raise AssertionError

        set_alerts_gateway(NeverGateway())
        response = client.post("/crypto/alerts/refresh",
                               headers={"X-CSRF-Token": generate_csrf_token()})
        assert response.status_code == 403
        assert calls == []

    def test_get_alerts_is_read_only(self, client, monkeypatch):
        from app.crypto_alerts import AlertsSnapshot, set_alerts_gateway
        _session(monkeypatch)
        _stub_access(monkeypatch)
        calls = []

        class Gateway:
            def snapshot(self, user_id): calls.append("snapshot"); return AlertsSnapshot(True, None, 0, ())
            def mark_read(self, *args): return False
            def mark_all_read(self, *args): return 0
            def refresh(self, user_id): calls.append("refresh"); raise AssertionError

        set_alerts_gateway(Gateway())
        assert client.get("/crypto/alerts.json").status_code == 200
        assert calls == ["snapshot"]

    def test_missing_history_refresh_returns_typed_503(self, client, monkeypatch):
        from app.auth import generate_csrf_token
        from app.crypto_alerts import reset_alerts_gateway
        _session(monkeypatch)
        _stub_access(monkeypatch)
        monkeypatch.delenv("FINCO_YIELD_HISTORY_PATH")
        reset_alerts_gateway(pending=False)
        response = client.post("/crypto/alerts/refresh",
                               headers={"X-CSRF-Token": generate_csrf_token()})
        assert response.status_code == 503
        assert response.json()["state"] == "UNAVAILABLE"
        assert response.json()["reason"] == "YIELD_HISTORY_UNAVAILABLE"
        assert response.json()["created_count"] is None


class TestProductTruth:
    def test_execution_remains_off(self):
        from finco_yield.flags import execution_enabled
        assert execution_enabled() is False

    def test_production_finco_deployments_zero_gating_off_threshold_unset(self):
        from app.protocol.entitlement_policy import load_policy_set
        from app.protocol.token_deployments import approved_deployments
        policies = load_policy_set({})
        assert approved_deployments() == ()
        assert policies.gating_enabled is False
        holder_thresholds = [
            policy.minimum_balance
            for policy in policies.policies.values()
            if getattr(policy.access_mode, "value", policy.access_mode) == "FINCO_HOLDER"
        ]
        assert holder_thresholds and all(value is None for value in holder_thresholds)
