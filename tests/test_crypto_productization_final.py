"""Final PR #160 productization contracts for browser-form alerts and navigation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

USER = "productization-user"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "finco.db"))
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    from app.crypto_alerts import reset_alerts_gateway
    reset_alerts_gateway(pending=False)
    yield
    reset_alerts_gateway()


@pytest.fixture()
def client():
    from app.crypto_ui import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _session(monkeypatch):
    session = SimpleNamespace(
        user_id=USER, username="demo", login_at=None, session_type="demo")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)


def _allow_access(monkeypatch):
    from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource
    decision = YieldAccessDecision(
        resource=YieldResource.ALERTS,
        state=YieldAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
        access_allowed=True,
        token_entitled=False,
        gate_active=False,
        reason="TOKEN_GATING_OFF",
    )

    async def resolve(request, resource):
        return decision

    monkeypatch.setattr("finco_yield.access.resolve_yield_access", resolve)


def _deny_access(monkeypatch):
    from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource
    decision = YieldAccessDecision(
        resource=YieldResource.ALERTS,
        state=YieldAccessState.ENTITLEMENT_NOT_SATISFIED,
        access_allowed=False,
        token_entitled=False,
        gate_active=True,
        reason="BALANCE_BELOW_THRESHOLD",
    )

    async def resolve(request, resource):
        return decision

    monkeypatch.setattr("finco_yield.access.resolve_yield_access", resolve)


def _csrf():
    from app.auth import generate_csrf_token
    return generate_csrf_token()


class AvailableGateway:
    def __init__(self):
        self.calls = []

    def snapshot(self, user_id):
        from app.crypto_alerts import AlertsSnapshot
        self.calls.append(("snapshot", user_id))
        return AlertsSnapshot(True, None, 1, ({"alert_id": "a-1", "read": False},))

    def refresh(self, user_id):
        self.calls.append(("refresh", user_id))
        return SimpleNamespace(
            available=True,
            reason=None,
            public_dict=lambda: {
                "state": "REFRESHED", "reason": None,
                "created_count": 0, "alerts": {"available": True},
            },
        )

    def mark_read(self, user_id, alert_id):
        self.calls.append(("read", user_id, alert_id))
        return True

    def mark_all_read(self, user_id):
        self.calls.append(("all", user_id))
        return 1


def test_browser_form_refresh_success_redirects_to_crypto(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)
    gateway = AvailableGateway()
    set_alerts_gateway(gateway)
    response = client.post("/crypto/alerts/refresh", data={"csrf_token": _csrf()})
    assert response.status_code == 303
    assert response.headers["location"] == "/crypto"
    assert ("refresh", USER) in gateway.calls


def test_browser_form_mark_read_success_redirects_to_crypto(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)
    gateway = AvailableGateway()
    set_alerts_gateway(gateway)
    response = client.post("/crypto/alerts/a-1/read", data={"csrf_token": _csrf()})
    assert response.status_code == 303
    assert response.headers["location"] == "/crypto"
    assert ("read", USER, "a-1") in gateway.calls


def test_browser_form_mark_all_success_redirects_to_crypto(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)
    gateway = AvailableGateway()
    set_alerts_gateway(gateway)
    response = client.post("/crypto/alerts/read-all", data={"csrf_token": _csrf()})
    assert response.status_code == 303
    assert response.headers["location"] == "/crypto"
    assert ("all", USER) in gateway.calls


def test_api_style_post_retains_typed_json(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)
    gateway = AvailableGateway()
    set_alerts_gateway(gateway)
    response = client.post(
        "/crypto/alerts/refresh", headers={"X-CSRF-Token": _csrf()})
    assert response.status_code == 200
    assert response.json()["state"] == "REFRESHED"
    assert response.json()["created_count"] == 0


def test_browser_form_deny_is_403_before_gateway(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _deny_access(monkeypatch)

    class NeverGateway:
        def snapshot(self, *args): raise AssertionError("gateway accessed")
        def refresh(self, *args): raise AssertionError("evaluator accessed")
        def mark_read(self, *args): raise AssertionError("mutation accessed")
        def mark_all_read(self, *args): raise AssertionError("mutation accessed")

    set_alerts_gateway(NeverGateway())
    response = client.post("/crypto/alerts/refresh", data={"csrf_token": _csrf()})
    assert response.status_code == 403
    assert "location" not in response.headers
    assert response.json()["reason"] == "BALANCE_BELOW_THRESHOLD"


def test_browser_form_missing_or_invalid_csrf_is_403_before_mutation(client, monkeypatch):
    from app.crypto_alerts import set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)
    gateway = AvailableGateway()
    set_alerts_gateway(gateway)
    for data in ({"csrf_token": ""}, {"csrf_token": "invalid"}):
        response = client.post("/crypto/alerts/read-all", data=data)
        assert response.status_code == 403
        assert "location" not in response.headers
        assert response.json()["reason"] == "CSRF_TOKEN_INVALID"
    assert not any(call[0] == "all" for call in gateway.calls)


@pytest.mark.parametrize("reason", [
    "YIELD_HISTORY_UNAVAILABLE",
    "YIELD_REGISTRY_UNAVAILABLE",
    "ALERT_EVALUATION_UNAVAILABLE",
])
def test_browser_refresh_typed_failure_redirects_with_allowlisted_reason(
        client, monkeypatch, reason):
    from app.crypto_alerts import AlertsSnapshot, set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)

    class FailedGateway:
        def snapshot(self, user_id):
            return AlertsSnapshot(True, None, 0, ())
        def refresh(self, user_id):
            return SimpleNamespace(
                available=False,
                reason=reason,
                public_dict=lambda: {
                    "state": "UNAVAILABLE", "reason": reason,
                    "created_count": None, "alerts": {},
                },
            )

    set_alerts_gateway(FailedGateway())
    response = client.post("/crypto/alerts/refresh", data={"csrf_token": _csrf()})
    assert response.status_code == 303
    assert response.headers["location"] == f"/crypto?alerts_notice={reason}"


def test_api_refresh_typed_failure_remains_json_503(client, monkeypatch):
    from app.crypto_alerts import AlertsSnapshot, set_alerts_gateway
    _session(monkeypatch)
    _allow_access(monkeypatch)

    class FailedGateway:
        def snapshot(self, user_id):
            return AlertsSnapshot(True, None, 0, ())
        def refresh(self, user_id):
            return SimpleNamespace(
                available=False,
                reason="YIELD_HISTORY_UNAVAILABLE",
                public_dict=lambda: {
                    "state": "UNAVAILABLE",
                    "reason": "YIELD_HISTORY_UNAVAILABLE",
                    "created_count": None,
                    "alerts": {},
                },
            )

    set_alerts_gateway(FailedGateway())
    response = client.post(
        "/crypto/alerts/refresh", headers={"X-CSRF-Token": _csrf()})
    assert response.status_code == 503
    assert response.json()["reason"] == "YIELD_HISTORY_UNAVAILABLE"


def test_crypto_notice_renders_only_allowlisted_reason(client):
    allowed = client.get("/crypto?alerts_notice=YIELD_HISTORY_UNAVAILABLE")
    assert allowed.status_code == 200
    assert 'data-testid="alerts-notice"' in allowed.text
    assert "YIELD_HISTORY_UNAVAILABLE" in allowed.text

    arbitrary = client.get("/crypto?alerts_notice=%3Cscript%3Eowned%3C/script%3E")
    assert arbitrary.status_code == 200
    assert 'data-testid="alerts-notice"' not in arbitrary.text
    assert "owned" not in arbitrary.text


def test_crypto_shared_nav_marks_crypto_active(client):
    response = client.get("/crypto")
    assert response.status_code == 200
    nav = response.text.split('<nav class="proto-nav"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/library"' in nav and ">\n        Model\n" in nav
    assert 'href="/radar"' in nav and ">\n        Radar\n" in nav
    assert 'href="/yield"' in nav and ">\n        Yield\n" in nav
    crypto = nav.split('href="/crypto"', 1)[1].split("</a>", 1)[0]
    assert "proto-nav__link--active" in crypto
    assert 'aria-current="page"' in crypto
