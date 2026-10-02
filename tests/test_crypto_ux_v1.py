"""FINCO Crypto surface (utility UX V1) — /crypto presentation tests.

Proves the coherent crypto surface presents AUTHORITATIVE states only:

  - wallet DISCONNECTED / UNVERIFIED / VERIFIED from the existing store;
  - resource states from the canonical presentation model over the real
    evaluator (gating OFF by default → NOT_ACTIVATED; gating ON without an
    approved deployment → NOT_CONFIGURED) and over injected decisions
    (UNAVAILABLE evidence, explicit observed zero, UNLOCKED);
  - watchlist count/rows/empty state with exact canonical identity;
  - alerts consumption boundary: integration-pending placeholder, 401
    unauthenticated, CSRF-protected mark-read/mark-all via test-double
    gateway;
  - product truth copy: no fabricated token quantity, no threshold leakage,
    execution OFF, no hype.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_TOKEN_ADDRESS = "0x" + "ab" * 20
TEST_WALLET = "0x" + "cd" * 20


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "crypto.db"))
    # get_connection reads the frozen module constant — patch both
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "crypto.db"))
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    yield
    from app.crypto_alerts import reset_alerts_gateway
    reset_alerts_gateway()


@pytest.fixture()
def client():
    from app.crypto_ui import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture()
def client_factory():
    def _make(**kwargs):
        from app.crypto_ui import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app, follow_redirects=False, **kwargs)
    return _make


def _session(monkeypatch, user_id=None):
    session = SimpleNamespace(user_id=user_id or "user-1", username="demo",
                              login_at=None, session_type="demo") if user_id else None
    monkeypatch.setattr("app.auth.resolve_request_session",
                        lambda request: session)
    return session


def _verified_wallet(user_id="user-1"):
    from app.persistence.db import get_connection
    from app.protocol.wallet_auth import _ensure_wallet_table
    conn = get_connection()
    try:
        _ensure_wallet_table(conn)
        with conn:
            conn.execute(
                "INSERT INTO user_wallets (user_id, wallet_address, verified_at) "
                "VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "wallet_address=excluded.wallet_address, verified_at=excluded.verified_at",
                (user_id, TEST_WALLET, "2026-01-01T00:00:00+00:00"))
    finally:
        conn.close()


def _decision(decision="DENY", reason="BALANCE_BELOW_THRESHOLD", *,
              observed_balance=None, chain_id=None, token_address=None):
    return SimpleNamespace(decision=decision, reason_code=reason,
                           observed_balance=observed_balance,
                           chain_id=chain_id, token_address=token_address)


# ── Wallet states ─────────────────────────────────────────────────────────────

def test_wallet_disconnected_state(client):
    page = client.get("/crypto")
    assert page.status_code == 200
    assert 'data-testid="crypto-wallet"' in page.text
    assert "DISCONNECTED" in page.text


def test_wallet_unverified_state(client, monkeypatch):
    _session(monkeypatch, "user-1")
    page = client.get("/crypto")
    assert page.status_code == 200
    assert "UNVERIFIED" in page.text


def test_wallet_verified_state(client, monkeypatch):
    _session(monkeypatch, "user-1")
    _verified_wallet()
    page = client.get("/crypto")
    assert page.status_code == 200
    assert "VERIFIED" in page.text


# ── Resource states: real evaluator, default env ──────────────────────────────

def test_anonymous_resource_truth_basic_public_holder_not_activated(client):
    """Issue A: anonymous visitors still get canonical authority —
    yield.basic stays PUBLIC and holder resources stay NOT_ACTIVATED
    (gating off); nothing degrades to UNAVAILABLE for lack of a session."""
    html = client.get("/crypto").text
    basic_row = html.split('data-testid="crypto-access-row-yield.basic"', 1)[1][:400]
    assert "PUBLIC" in basic_row
    for key in ("yield.history", "yield.advanced_compare",
                "yield.execution_preflight"):
        row = html.split(f'data-testid="crypto-access-row-{key}"', 1)[1][:400]
        assert "NOT_ACTIVATED" in row, key
        assert "UNAVAILABLE" not in row, key


def test_gating_inactive_by_default_presents_not_activated(client, monkeypatch):
    """Token gating is not active by default: gated capabilities present
    NOT_ACTIVATED (no active gate denied anyone) while Basic Yield is PUBLIC."""
    _session(monkeypatch, "user-1")
    page = client.get("/crypto")
    html = page.text
    assert 'data-testid="crypto-access-row-yield.basic"' in html
    for key in ("yield.history", "yield.advanced_compare",
                "yield.execution_preflight"):
        row = html.split(f'data-testid="crypto-access-row-{key}"', 1)[1][:400]
        assert "NOT_ACTIVATED" in row, key
    assert "TOKEN_GATING_OFF" in html


def test_basic_yield_public_on_crypto_surface(client, monkeypatch):
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    basic_row = html.split('data-testid="crypto-access-row-yield.basic"', 1)[1][:400]
    assert "PUBLIC" in basic_row


def test_no_deployment_with_gating_enabled_maps_not_configured(
        client, monkeypatch):
    """Gating explicitly ON but zero approved deployments → the honest
    NOT_CONFIGURED state (production truth once gating is switched on)."""
    monkeypatch.setenv("FINCO_TOKEN_GATING_ENABLED", "1")
    monkeypatch.setenv("FINCO_ENTITLEMENT_POLICIES_JSON",
                       '{"yield.history": {"enabled": true}}')
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    history_row = html.split('data-testid="crypto-access-row-yield.history"', 1)[1][:400]
    assert "NOT_CONFIGURED" in history_row


# ── Injected authoritative decisions: unavailable / zero / unlocked ───────────

def test_unavailable_evidence_presented_not_zero(client, monkeypatch):
    decisions = {"yield.history": _decision("DENY", "BALANCE_EVIDENCE_UNAVAILABLE")}
    async def _decisions(wallet):
        return decisions
    monkeypatch.setattr("app.crypto_ui._resource_decisions", _decisions)
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    row = html.split('data-testid="crypto-access-row-yield.history"', 1)[1][:400]
    assert "UNAVAILABLE" in row
    assert "Observed balance" not in row  # missing ≠ zero


def test_explicit_observed_zero_may_be_displayed(client, monkeypatch):
    decisions = {"yield.history": _decision(
        "DENY", "BALANCE_BELOW_THRESHOLD", observed_balance=Decimal(0),
        chain_id=8453, token_address=TEST_TOKEN_ADDRESS)}
    async def _decisions(wallet):
        return decisions
    monkeypatch.setattr("app.crypto_ui._resource_decisions", _decisions)
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    row = html.split('data-testid="crypto-access-row-yield.history"', 1)[1][:400]
    assert "Observed balance 0 (chain 8453)" in row


def test_unlocked_state_presented_when_authoritative(client, monkeypatch):
    decisions = {"yield.history": _decision(
        "ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD", observed_balance=Decimal("2.5"),
        chain_id=8453, token_address=TEST_TOKEN_ADDRESS)}
    async def _decisions(wallet):
        return decisions
    monkeypatch.setattr("app.crypto_ui._resource_decisions", _decisions)
    _session(monkeypatch, "user-1")
    _verified_wallet()
    html = client.get("/crypto").text
    row = html.split('data-testid="crypto-access-row-yield.history"', 1)[1][:400]
    assert "UNLOCKED" in row
    assert "Observed balance 2.5 (chain 8453)" in row


# ── Watchlist UX ──────────────────────────────────────────────────────────────

def test_watchlist_empty_state_and_count(client, monkeypatch):
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    assert 'data-testid="watchlist-count">0<' in html
    assert 'data-testid="watchlist-empty"' in html


def test_watchlist_count_and_canonical_rows(client, monkeypatch):
    from finco_yield.registry import load_bundled_registry
    from finco_yield.watchlist import save_watchlist_item
    _session(monkeypatch, "user-1")
    uid = load_bundled_registry().all()[0].uid
    save_watchlist_item("user-1", uid)
    html = client.get("/crypto").text
    assert 'data-testid="watchlist-count">1<' in html
    assert 'data-testid="crypto-watchlist-row"' in html
    assert uid in html  # canonical identity rendered


def test_watchlist_anonymous_zero(client):
    html = client.get("/crypto").text
    assert 'data-testid="watchlist-count">0<' in html


# ── Alerts consumption boundary ───────────────────────────────────────────────

def test_alerts_anonymous_locked_without_gateway_call(client):
    """Anonymous: typed LOCKED / ALERTS_AUTH_REQUIRED — the gateway is never
    called with an empty identity, and unknown unread is never zero."""
    html = client.get("/crypto").text
    assert 'data-testid="alerts-state">LOCKED<' in html
    assert "ALERTS_AUTH_REQUIRED" in html
    assert "Sign in to view your alerts" in html
    assert "unread —" in html  # unknown, never fabricated zero
    assert "NOT SHIPPED" in html


def test_alerts_json_requires_auth(client):
    response = client.get("/crypto/alerts.json")
    assert response.status_code == 401


def test_alerts_json_pending_gateway(client, monkeypatch):
    _session(monkeypatch, "user-1")
    response = client.get("/crypto/alerts.json")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "ALERTS_INTEGRATION_PENDING"
    assert body["unread_count"] is None
    assert body["items"] == []


def test_alert_mark_read_requires_auth(client):
    response = client.post("/crypto/alerts/a-1/read",
                           headers={"X-CSRF-Token": "x"})
    assert response.status_code == 401


def test_alert_mark_read_csrf_required(client, monkeypatch):
    _session(monkeypatch, "user-1")
    for token in (None, "tampered"):
        headers = {"X-CSRF-Token": token} if token else {}
        response = client.post("/crypto/alerts/a-1/read", headers=headers)
        assert response.status_code == 403
        assert response.json()["reason"] == "CSRF_TOKEN_INVALID"


def test_alert_mark_read_pending_gateway_typed_501(client, monkeypatch):
    from app.auth import generate_csrf_token
    _session(monkeypatch, "user-1")
    response = client.post(
        "/crypto/alerts/a-1/read",
        headers={"X-CSRF-Token": generate_csrf_token()})
    assert response.status_code == 501
    assert response.json()["reason"] == "ALERTS_INTEGRATION_PENDING"


def test_alert_gateway_double_mark_read_and_read_all(client, monkeypatch):
    """Agent D connects a real gateway through set_alerts_gateway — proven
    here with an interface test double."""
    from app.auth import generate_csrf_token
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway,
    )

    class _Double:
        def __init__(self):
            self.read = []

        def snapshot(self, user_id):
            return AlertsSnapshot(available=True, reason=None,
                                  unread_count=1,
                                  items=({"alert_id": "a-1"},))

        def mark_read(self, user_id, alert_id):
            self.read.append(alert_id)
            return True

        def mark_all_read(self, user_id):
            return 2

    double = _Double()
    set_alerts_gateway(double)
    _session(monkeypatch, "user-1")
    header = {"X-CSRF-Token": generate_csrf_token()}

    listing = client.get("/crypto/alerts.json")
    assert listing.json()["available"] is True
    assert listing.json()["unread_count"] == 1

    marked = client.post("/crypto/alerts/a-1/read", headers=header)
    assert marked.status_code == 200
    assert marked.json()["state"] == "MARKED"
    assert double.read == ["a-1"]

    all_read = client.post("/crypto/alerts/read-all", headers=header)
    assert all_read.status_code == 200
    assert all_read.json() == {"state": "MARKED", "count": 2}


# ── Product truth / no hype / no fabricated numbers ───────────────────────────

def test_product_truth_copy_present(client):
    html = client.get("/crypto").text
    assert "NOT CONFIGURED" in html          # honest deployment truth
    assert "not active by default" in html   # gating truth
    assert "integration pending" in html     # alerts truth
    assert "NOT SHIPPED" in html             # external notifications truth


def test_execution_state_off_by_default(client):
    html = client.get("/crypto").text
    assert 'data-testid="crypto-execution"' in html
    assert ">OFF<" in html
    assert "never signs, custodies, or broadcasts" in html


@pytest.mark.parametrize("path", ["/crypto", "/crypto/alerts.json"])
def test_no_hype_copy_and_no_fabricated_quantities(client, monkeypatch, path):
    if path.endswith("alerts.json"):
        _session(monkeypatch, "user-1")
    html = client.get(path).text
    lowered = html.lower()
    for phrase in ("exclusive", "alpha", "best yield", "guaranteed",
                   "earn more", "buy finco", "0 finco", "hold"):
        assert phrase not in lowered, phrase
    # thresholds never leak
    assert "minimum_balance" not in html
    assert "threshold" not in lowered


# ── Issue B: the alerts gateway is never called with an empty identity ───────

def test_anonymous_crypto_never_calls_alerts_gateway(client, monkeypatch):
    """A gateway that raises on ANY call: anonymous /crypto must succeed
    without a single snapshot('') invocation."""
    from app.crypto_alerts import set_alerts_gateway

    class _RaisingGateway:
        def snapshot(self, user_id):
            raise AssertionError(f"gateway called with user_id={user_id!r}")

        def mark_read(self, user_id, alert_id):
            raise AssertionError("gateway mutation for anonymous user")

        def mark_all_read(self, user_id):
            raise AssertionError("gateway mutation for anonymous user")

    set_alerts_gateway(_RaisingGateway())
    page = client.get("/crypto")  # must not raise
    assert page.status_code == 200
    assert "ALERTS_AUTH_REQUIRED" in page.text


# ── Issue C: canonical yield.alerts server access enforced on routes ─────────

def _yield_access_decision(state="ENTITLEMENT_NOT_SATISFIED", *,
                           access_allowed=False, gate_active=True,
                           reason="BALANCE_BELOW_THRESHOLD"):
    """Crafted through the CANONICAL adapter types — no parallel evaluator."""
    from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource
    return YieldAccessDecision(
        resource=YieldResource.ALERTS,
        state=YieldAccessState(state),
        access_allowed=access_allowed,
        token_entitled=access_allowed and gate_active,
        gate_active=gate_active,
        reason=reason,
    )


@pytest.fixture()
def alerts_access_stub(monkeypatch):
    """Patch the canonical server-access boundary function; record calls."""
    calls = []

    def _install(state="ENTITLEMENT_NOT_SATISFIED", *, access_allowed=False,
                 gate_active=True, reason="BALANCE_BELOW_THRESHOLD"):
        async def fake_resolve(request, resource):
            calls.append(resource.value)
            return _yield_access_decision(state, access_allowed=access_allowed,
                                          gate_active=gate_active, reason=reason)
        monkeypatch.setattr("finco_yield.access.resolve_yield_access", fake_resolve)

    _install.calls = calls
    _install.install = _install
    return _install


def test_alerts_json_inactive_gating_proceeds_to_gateway(
        client, monkeypatch, alerts_access_stub):
    from app.auth import generate_csrf_token
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway,
    )
    calls = []
    double = SimpleNamespace(
        snapshot=lambda user_id: calls.append(user_id)
        or AlertsSnapshot(available=False, reason="ALERTS_INTEGRATION_PENDING",
                          unread_count=None, items=()),
        mark_read=lambda *a: True, mark_all_read=lambda *a: 0)
    set_alerts_gateway(double)
    alerts_access_stub.install(state="TOKEN_ENTITLEMENT_FEATURE_INACTIVE",
                               access_allowed=True, gate_active=False,
                               reason="TOKEN_GATING_OFF")
    _session(monkeypatch, "user-1")
    response = client.get("/crypto/alerts.json")
    reset_alerts_gateway()
    assert response.status_code == 200  # INACTIVE proceeds (no active gate)
    assert alerts_access_stub.calls == ["yield.alerts"]
    assert calls == ["user-1"]


def test_alerts_json_canonical_allow_proceeds(client, monkeypatch,
                                              alerts_access_stub):
    from app.auth import generate_csrf_token
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway,
    )
    calls = []
    double = SimpleNamespace(
        snapshot=lambda user_id: calls.append(user_id)
        or AlertsSnapshot(available=True, reason=None, unread_count=0,
                          items=()),
        mark_read=lambda *a: True, mark_all_read=lambda *a: 0)
    set_alerts_gateway(double)
    alerts_access_stub.install(state="ENTITLED", access_allowed=True,
                               gate_active=True,
                               reason="BALANCE_AT_OR_ABOVE_THRESHOLD")
    _session(monkeypatch, "user-1")
    response = client.get("/crypto/alerts.json")
    reset_alerts_gateway()
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert calls == ["user-1"]


@pytest.mark.parametrize("state,reason", [
    ("ENTITLEMENT_NOT_SATISFIED", "BALANCE_BELOW_THRESHOLD"),
    ("ENTITLEMENT_AUTHORITY_UNAVAILABLE", "RPC_UNAVAILABLE"),
    ("TOKEN_DEPLOYMENT_NOT_CONFIGURED", "NO_APPROVED_DEPLOYMENT"),
])
def test_alerts_json_canonical_deny_fails_closed_before_gateway(
        client, monkeypatch, alerts_access_stub, state, reason):
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway,
    )
    snapshot_calls = []
    double = SimpleNamespace(
        snapshot=lambda user_id: snapshot_calls.append(user_id)
        or AlertsSnapshot(available=True, reason=None, unread_count=0, items=()),
        mark_read=lambda *a: snapshot_calls.append("mutate") or True,
        mark_all_read=lambda *a: snapshot_calls.append("mutate") or 0)
    set_alerts_gateway(double)
    alerts_access_stub.install(state=state, access_allowed=False,
                               gate_active=True, reason=reason)
    _session(monkeypatch, "user-1")
    response = client.get("/crypto/alerts.json")
    reset_alerts_gateway()
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "YIELD_PREMIUM_REQUIRED"
    assert body["resource"] == "yield.alerts"
    assert body["reason"] == reason
    assert snapshot_calls == []  # DENY happens BEFORE any gateway access


def test_crypto_overview_denied_alerts_no_gateway_fetch(client, monkeypatch,
                                                        alerts_access_stub):
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway,
    )
    snapshot_calls = []
    double = SimpleNamespace(
        snapshot=lambda user_id: snapshot_calls.append(user_id)
        or AlertsSnapshot(available=True, reason=None, unread_count=1,
                          items=({"alert_id": "a-1"},)),
        mark_read=lambda *a: True, mark_all_read=lambda *a: 0)
    set_alerts_gateway(double)
    alerts_access_stub.install(state="ENTITLEMENT_NOT_SATISFIED",
                               access_allowed=False, gate_active=True,
                               reason="BALANCE_BELOW_THRESHOLD")
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    reset_alerts_gateway()
    assert 'data-testid="alerts-state">LOCKED<' in html
    assert "BALANCE_BELOW_THRESHOLD" in html
    assert snapshot_calls == []  # denied → no user-specific alerts payload


# ── Mutations: canonical access then CSRF then gateway ───────────────────────

def test_alert_mutations_canonical_deny_403_no_mutation(
        client, monkeypatch, alerts_access_stub):
    from app.auth import generate_csrf_token
    from app.crypto_alerts import set_alerts_gateway, reset_alerts_gateway
    mutations = []
    double = SimpleNamespace(
        snapshot=lambda user_id: AlertsSnapshot(
            available=True, reason=None, unread_count=1,
            items=({"alert_id": "a-1"},)),
        mark_read=lambda user_id, alert_id: mutations.append(("read", alert_id)) or True,
        mark_all_read=lambda user_id: mutations.append(("all",)) or 2)
    set_alerts_gateway(double)
    alerts_access_stub.install(state="ENTITLEMENT_NOT_SATISFIED",
                               access_allowed=False, gate_active=True,
                               reason="BALANCE_BELOW_THRESHOLD")
    _session(monkeypatch, "user-1")
    header = {"X-CSRF-Token": generate_csrf_token()}  # valid CSRF still denied
    read = client.post("/crypto/alerts/a-1/read", headers=header)
    all_read = client.post("/crypto/alerts/read-all", headers=header)
    reset_alerts_gateway()
    assert read.status_code == 403
    assert all_read.status_code == 403
    assert mutations == []  # canonical DENY precedes CSRF and gateway


def test_alert_mutations_csrf_enforced_after_access_allowed(
        client, monkeypatch, alerts_access_stub):
    from app.auth import generate_csrf_token
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway)
    mutations = []
    double = SimpleNamespace(
        snapshot=lambda user_id: AlertsSnapshot(
            available=True, reason=None, unread_count=1,
            items=({"alert_id": "a-1"},)),
        mark_read=lambda user_id, alert_id: mutations.append(("read", alert_id)) or True,
        mark_all_read=lambda user_id: mutations.append(("all",)) or 2)
    set_alerts_gateway(double)
    alerts_access_stub.install(state="ENTITLED", access_allowed=True,
                               gate_active=True,
                               reason="BALANCE_AT_OR_ABOVE_THRESHOLD")
    _session(monkeypatch, "user-1")

    missing = client.post("/crypto/alerts/a-1/read")
    invalid = client.post("/crypto/alerts/a-1/read",
                          headers={"X-CSRF-Token": "tampered"})
    valid = client.post("/crypto/alerts/a-1/read",
                        headers={"X-CSRF-Token": generate_csrf_token()})
    assert missing.status_code == 403
    assert invalid.status_code == 403
    assert valid.status_code == 200
    assert mutations == [("read", "a-1")]  # only the valid request mutated

    missing_all = client.post("/crypto/alerts/read-all")
    assert missing_all.status_code == 403
    valid_all = client.post("/crypto/alerts/read-all",
                            headers={"X-CSRF-Token": generate_csrf_token()})
    assert valid_all.status_code == 200
    reset_alerts_gateway()
    assert ("all",) in mutations


# ── Real alerts UX boundary (available gateway) ──────────────────────────────

def test_available_gateway_renders_full_alerts_ux(client, monkeypatch):
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway)
    double = SimpleNamespace(
        snapshot=lambda user_id: AlertsSnapshot(
            available=True, reason=None, unread_count=2,
            items=(
                {"alert_id": "a-1", "alert_type": "YIELD_RATE_CHANGE",
                 "opportunity_uid": "yld_" + "a" * 32,
                 "opportunity_display": "Spark USDC Vault",
                 "summary": "Reported APY changed.",
                 "value": "3.1% -> 2.9%",
                 "created_at": "2026-10-01T00:00:00+00:00",
                 "read": False},
                {"alert_id": "a-2", "alert_type": "YIELD_RATE_CHANGE",
                 "opportunity_uid": "yld_" + "b" * 32,
                 "opportunity_display": "Aave USDC",
                 "summary": "Reported APY changed.",
                 "value": "4.0% -> 4.2%",
                 "created_at": "2026-10-01T01:00:00+00:00",
                 "read": True},
            )),
        mark_read=lambda user_id, alert_id: True,
        mark_all_read=lambda user_id: 1)
    set_alerts_gateway(double)
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    assert 'data-testid="alerts-state">AVAILABLE<' in html
    assert "unread 2" in html
    assert html.count('data-testid="alerts-item"') == 2
    assert "YIELD_RATE_CHANGE" in html
    assert ("yld_" + "a" * 32) in html  # canonical opportunity identity
    assert "3.1% -&gt; 2.9%" in html    # gateway-provided summary (escaped)
    assert "2026-10-01T00:00:00+00:00" in html
    assert html.count('data-testid="alert-mark-read"') == 1  # one unread
    assert 'data-testid="alerts-mark-all-read"' in html
    assert "integration pending" not in html  # conditional copy flips
    assert "In-app alerts: available" in html
    assert "Email = NOT SHIPPED" in html      # external truth unchanged
    reset_alerts_gateway()


# ── Final correction: alerts access row follows canonical decision; the
#    Alerts PANEL independently reports backend availability ──────────────────

@pytest.fixture()
def installed_alerts_gateway(monkeypatch):
    from app.crypto_alerts import (
        AlertsSnapshot, set_alerts_gateway, reset_alerts_gateway,
    )
    double = SimpleNamespace(
        snapshot=lambda user_id: AlertsSnapshot(
            available=True, reason=None, unread_count=1,
            items=({"alert_id": "a-1", "alert_type": "YIELD_RATE_CHANGE",
                   "opportunity_uid": "yld_" + "a" * 32,
                   "opportunity_display": "Spark USDC Vault",
                   "summary": "Reported APY changed.", "value": None,
                   "created_at": "2026-10-01T00:00:00+00:00",
                   "read": False},)),
        mark_read=lambda user_id, alert_id: True,
        mark_all_read=lambda user_id: 1)
    set_alerts_gateway(double)
    yield double
    reset_alerts_gateway()


def _patch_alerts_access(monkeypatch, *, decision, reason,
                         access_allowed, gate_active):
    """Stub ONE canonical boundary function (no parallel evaluator)."""
    from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource
    crafted = YieldAccessDecision(
        resource=YieldResource.ALERTS, state=YieldAccessState(decision),
        access_allowed=access_allowed, token_entitled=access_allowed and gate_active,
        gate_active=gate_active, reason=reason)

    async def fake_resolve(request, resource):
        return crafted

    monkeypatch.setattr("finco_yield.access.resolve_yield_access", fake_resolve)


def _craft_all_decisions(alerts_decision):
    """Full canonical mapping for the access table: basic PUBLIC, alerts as
    given, other holders INACTIVE (gating off) — exactly what the canonical
    evaluator emits under the matching production configuration."""
    from app.crypto_access import (
        YIELD_ADVANCED_COMPARE, YIELD_ALERTS, YIELD_BASIC, YIELD_EXECUTION_PREFLIGHT,
        YIELD_HISTORY,
    )
    return {
        YIELD_BASIC: _decision("ALLOW", "PUBLIC_RESOURCE"),
        YIELD_ALERTS: alerts_decision,
        YIELD_HISTORY: _decision("INACTIVE", "TOKEN_GATING_OFF"),
        YIELD_ADVANCED_COMPARE: _decision("INACTIVE", "TOKEN_GATING_OFF"),
        YIELD_EXECUTION_PREFLIGHT: _decision("INACTIVE", "TOKEN_GATING_OFF"),
    }


def test_alerts_available_plus_allow_panel_and_row_agree(
        client, monkeypatch, installed_alerts_gateway):
    """Gateway AVAILABLE + canonical ALLOW: Alerts panel AVAILABLE and the
    $FINCO access row UNLOCKED — no contradiction, no delivery override."""
    async def _decisions(wallet):
        return _craft_all_decisions(_decision(
            "ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD"))
    monkeypatch.setattr("app.crypto_ui._resource_decisions", _decisions)
    _patch_alerts_access(monkeypatch, decision="ENTITLED",
                         reason="BALANCE_AT_OR_ABOVE_THRESHOLD",
                         access_allowed=True, gate_active=True)
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    assert 'data-testid="alerts-state">AVAILABLE<' in html
    assert "In-app alerts: available" in html
    alerts_row = html.split('data-testid="crypto-access-row-yield.alerts"', 1)[1][:400]
    assert "UNLOCKED" in alerts_row
    assert "NOT_ACTIVATED" not in alerts_row


def test_alerts_available_plus_inactive_gate_is_valid_not_contradictory(
        client, monkeypatch, installed_alerts_gateway):
    """Gateway AVAILABLE + canonical INACTIVE: service availability and
    token-gate state are intentionally separate — panel AVAILABLE while the
    access row reads NOT_ACTIVATED (the gate is simply off)."""
    async def _decisions(wallet):
        return _craft_all_decisions(_decision("INACTIVE", "TOKEN_GATING_OFF"))
    monkeypatch.setattr("app.crypto_ui._resource_decisions", _decisions)
    _patch_alerts_access(monkeypatch, decision="TOKEN_ENTITLEMENT_FEATURE_INACTIVE",
                         reason="TOKEN_GATING_OFF",
                         access_allowed=True, gate_active=False)
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    assert 'data-testid="alerts-state">AVAILABLE<' in html
    assert "In-app alerts: available" in html
    alerts_row = html.split('data-testid="crypto-access-row-yield.alerts"', 1)[1][:900]
    assert "NOT_ACTIVATED" in alerts_row
    assert "TOKEN_GATING_OFF" in alerts_row
    # wording clarifies NOT_ACTIVATED means the gate is off, not the service
    assert "the token gate is not active" in html


def test_alerts_access_row_note_has_no_delivery_claim(client, monkeypatch):
    _session(monkeypatch, "user-1")
    html = client.get("/crypto").text
    row = html.split('data-testid="crypto-access-row-yield.alerts"', 1)[1][:400]
    assert "shown separately" in row
    assert "not shipped" not in row.lower()
    assert "delivery" not in row.lower()


# ── Fail-soft runtime (manual-QA correction): /crypto never 500s ─────────────

class TestCryptoFailSoftAuthorities:
    """GET /crypto composes OPTIONAL authorities.  Any single authority
    outage (wallet store, entitlement evaluator, Yield watchlist, alerts
    access) must render a typed fail-soft state — never HTTP 500 and never
    a fabricated value.  Regression for the staging HTTP-500 QA report."""

    def test_wallet_store_outage_renders_unavailable(self, client, monkeypatch):
        import sqlite3
        _session(monkeypatch, "user-1")

        def boom(user_id):
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr("app.crypto_access.get_wallet_state", boom)
        page = client.get("/crypto")
        assert page.status_code == 200
        assert 'data-testid="crypto-wallet"' in page.text
        assert "UNAVAILABLE" in page.text
        assert 'data-testid="wallet-unavailable"' in page.text

    def test_evaluator_programming_error_propagates_not_masked(
            self, client_factory, monkeypatch):
        """Correction A: unexpected evaluator programming errors are NOT
        masked into a fake "no decisions" state — they propagate visibly."""
        _session(monkeypatch, "user-1")

        async def boom(wallet):
            raise RuntimeError("evaluator programming defect")

        monkeypatch.setattr("app.crypto_ui._resource_decisions", boom)
        with pytest.raises(RuntimeError):
            client_factory(raise_server_exceptions=True).get("/crypto")

    def test_watchlist_store_outage_never_renders_zero(
            self, client, monkeypatch):
        """unavailable != zero: a store outage must NOT render a factual
        count of 0 — the badge shows an em-dash plus a typed UNAVAILABLE
        state (correction C)."""
        import sqlite3
        _session(monkeypatch, "user-1")

        def boom(user_id):
            raise sqlite3.OperationalError("no such table: yield_watchlist")

        monkeypatch.setattr("finco_yield.watchlist.list_watchlist_items", boom)
        page = client.get("/crypto")
        assert page.status_code == 200
        assert 'data-testid="watchlist-count">—<' in page.text
        assert 'data-testid="watchlist-unavailable"' in page.text
        assert 'data-testid="watchlist-count">0<' not in page.text
        assert 'data-testid="watchlist-empty"' not in page.text

    def test_alerts_access_outage_renders_unavailable_snapshot(
            self, client, monkeypatch):
        _session(monkeypatch, "user-1")

        async def boom(request, resource):
            raise RuntimeError("entitlement authority unreachable")

        from finco_yield import access as access_mod
        monkeypatch.setattr(access_mod, "resolve_yield_access", boom)
        page = client.get("/crypto")
        assert page.status_code == 200
        assert 'data-testid="alerts-state">UNAVAILABLE<' in page.text
        assert "ALERT_EVALUATION_UNAVAILABLE" in page.text

    def test_all_optional_authorities_down_still_renders_page(
            self, client, monkeypatch):
        """Staging-equivalent worst case: every optional authority fails at
        once.  The page must render with typed states, never 500."""
        import sqlite3
        _session(monkeypatch, "user-1")

        def db_boom(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        async def evaluator_boom(wallet):
            raise RuntimeError("evaluator down")

        async def access_boom(request, resource):
            raise RuntimeError("access authority down")

        monkeypatch.setattr("app.crypto_access.get_wallet_state", db_boom)
        monkeypatch.setattr("finco_yield.watchlist.list_watchlist_items", db_boom)
        from finco_yield import access as access_mod
        monkeypatch.setattr(access_mod, "resolve_yield_access", access_boom)

        page = client.get("/crypto")
        assert page.status_code == 200
        assert "UNAVAILABLE" in page.text
        # Missing/unavailable evidence stays missing/unavailable — no zero
        # fabrication anywhere on the page.  The unavailable watchlist is
        # NOT presented as a factual zero count.
        assert "Observed balance" not in page.text
        assert 'data-testid="watchlist-count">—<' in page.text
        assert 'data-testid="watchlist-unavailable"' in page.text

    def test_anonymous_with_all_authorities_down_still_renders(
            self, client, monkeypatch):
        import sqlite3

        def db_boom(*a, **k):
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr("app.crypto_access.get_wallet_state", db_boom)
        monkeypatch.setattr("finco_yield.watchlist.list_watchlist_items", db_boom)
        page = client.get("/crypto")
        assert page.status_code == 200
        assert "DISCONNECTED" in page.text or "UNAVAILABLE" in page.text


class TestRunStageTimingIsolation:
    """Run-timing instrumentation (correction F): observational only, and
    context state must never leak between requests — a second run must not
    inherit stage marks from a prior request."""

    def test_consecutive_runs_do_not_inherit_stage_marks(self):
        import logging

        from app.services.run_stage_timing import (
            log_run_stages, start_run_stages,
        )

        records: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("finco.run_stages")
        handler = _Handler()
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            first = start_run_stages()
            first.mark("form_parsed")
            first.mark("model_completed")
            log_run_stages(project_type="Solar", origin="test")
            assert len(records) == 1
            assert "form_parsed" in records[0]
            assert "model_completed" in records[0]

            # A second run starts a FRESH timer: no inherited marks.
            records.clear()
            second = start_run_stages()
            second.mark("model_entered")
            log_run_stages(project_type="Wind", origin="test")
            assert len(records) == 1
            assert "form_parsed" not in records[0]
            assert "model_completed" not in records[0]
            assert "model_entered" in records[0]
            assert "request_received" in records[0]
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

    def test_marks_without_active_timer_are_noop(self):
        from app.services import run_stage_timing as timing

        # No active timer in this context: mark() must not raise.
        timing.mark("form_parsed")

    def test_unknown_and_duplicate_marks_ignored(self):
        from app.services.run_stage_timing import start_run_stages

        timer = start_run_stages()
        timer.mark("not_a_real_stage")  # unknown stage ignored
        first = dict(timer.stages)
        timer.mark("form_parsed")
        timer.mark("form_parsed")  # duplicate ignored
        assert timer.stages["form_parsed"] >= first.get("form_parsed", 0)
        assert "not_a_real_stage" not in timer.stages
        assert sum(1 for s in timer.stages if s == "form_parsed") == 1


class TestCryptoWalletContextOutage:
    """The residual unguarded wallet-authority call in /crypto (post-#163
    QA): wallet_context_for_session outage must degrade to typed unavailable
    decisions — never a 500."""

    def test_wallet_context_outage_renders_unavailable(self, client, monkeypatch):
        import sqlite3
        _session(monkeypatch, "user-1")

        def boom(session):
            raise sqlite3.OperationalError("wallet store unavailable")

        monkeypatch.setattr(
            "app.protocol.entitlement_evaluator.wallet_context_for_session", boom)
        page = client.get("/crypto")
        assert page.status_code == 200
        assert "UNAVAILABLE" in page.text
