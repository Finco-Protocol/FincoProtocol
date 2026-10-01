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

def test_alerts_placeholder_integration_pending(client):
    html = client.get("/crypto").text
    assert 'data-testid="alerts-state">NOT_ACTIVATED<' in html
    assert "integration pending" in html
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
