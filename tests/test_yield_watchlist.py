"""Crypto utility V0 (Agent C) — Yield watchlist foundation.

Proves: canonical identity only (exact yld_* uid resolved through THE one
bundled registry; no ticker/name/fuzzy saving), deterministic duplicate
handling, save/list/remove, per-user binding, unauthorized-mutation
rejection, and the route contract (401 unauthenticated, 404 unknown uid,
form → /login redirect).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "watchlist.db"))


@pytest.fixture()
def first_uid():
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().all()[0].uid


@pytest.fixture()
def first_opportunity(first_uid):
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().resolve(first_uid)


# ── Store layer ───────────────────────────────────────────────────────────────

def test_save_list_remove_roundtrip(first_uid, first_opportunity):
    from finco_yield.watchlist import (
        list_watchlist_items, remove_watchlist_item, save_watchlist_item,
        watchlist_contains,
    )
    result = save_watchlist_item("user-1", first_uid)
    assert result["created"] is True
    assert result["opportunity_uid"] == first_uid
    assert watchlist_contains("user-1", first_uid)

    items = list_watchlist_items("user-1")
    assert len(items) == 1
    item = items[0]
    # canonical identity preserved exactly
    assert item["opportunity_uid"] == first_uid
    assert item["chain_id"] == first_opportunity.chain_id
    assert item["protocol"] == first_opportunity.protocol
    assert item["product_type"] == first_opportunity.product_type
    assert item["contract_address"] == first_opportunity.contract_address

    assert remove_watchlist_item("user-1", first_uid) is True
    assert list_watchlist_items("user-1") == []
    assert remove_watchlist_item("user-1", first_uid) is False


def test_duplicate_save_is_deterministic_noop(first_uid):
    from finco_yield.watchlist import list_watchlist_items, save_watchlist_item
    first = save_watchlist_item("user-1", first_uid)
    second = save_watchlist_item("user-1", first_uid)
    assert first["created"] is True
    assert second["created"] is False
    assert len(list_watchlist_items("user-1")) == 1


def test_unknown_uid_rejected_by_canonical_registry():
    """Valid uid FORMAT but not in the registry → typed unknown error.
    Identity authority is the registry, never display text."""
    import hashlib
    import json as _json
    from finco_yield.identity import YieldIdentity, yield_opportunity_uid
    from finco_yield.watchlist import (
        WatchlistOpportunityUnknown, save_watchlist_item,
    )
    ghost = yield_opportunity_uid(YieldIdentity(
        chain_id=1, protocol="ghost", product_type="vault",
        contract_address="0x" + "ff" * 20,
        underlying_assets=("0x" + "ee" * 20,),
    ))
    assert ghost.startswith("yld_")
    with pytest.raises(WatchlistOpportunityUnknown):
        save_watchlist_item("user-1", ghost)


@pytest.mark.parametrize("bad_uid", [
    "", "APPL", "aapl-token", "yld_short", "yld_" + "g" * 32,
    "yld_" + "A" * 32, "  yld_" + "a" * 32, "yld_" + "a" * 32 + " ",
])
def test_malformed_uid_rejected_never_fuzzy_matched(bad_uid):
    """No ticker, name, symbol, prefix or fuzzy matching ever saves an item."""
    from finco_yield.watchlist import WatchlistError, save_watchlist_item
    with pytest.raises(WatchlistError, match="YIELD_OPPORTUNITY_UID_MALFORMED"):
        save_watchlist_item("user-1", bad_uid)


def test_watchlist_rows_are_per_user(first_uid):
    from finco_yield.watchlist import list_watchlist_items, save_watchlist_item
    save_watchlist_item("user-1", first_uid)
    assert list_watchlist_items("user-2") == []
    save_watchlist_item("user-2", first_uid)
    assert len(list_watchlist_items("user-1")) == 1
    assert len(list_watchlist_items("user-2")) == 1


def test_save_requires_user(first_uid):
    from finco_yield.watchlist import WatchlistError, save_watchlist_item
    with pytest.raises(WatchlistError, match="WATCHLIST_USER_REQUIRED"):
        save_watchlist_item("", first_uid)


def test_no_fuzzy_matching_constructs_in_watchlist_module():
    import inspect
    from finco_yield import watchlist
    source = inspect.getsource(watchlist)
    for banned in ("difflib", "SequenceMatcher", "rapidfuzz", "thefuzz",
                   "fuzzywuzzy", "startswith(symbol", "lower() =="):
        assert banned not in source, banned


# ── Route layer ───────────────────────────────────────────────────────────────

@pytest.fixture()
def yield_client(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    from finco_yield.web import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture()
def fake_session(monkeypatch):
    session = SimpleNamespace(user_id="user-1", username="demo",
                              login_at=None, session_type="demo")
    monkeypatch.setattr("app.auth.resolve_request_session",
                        lambda request: session)
    return session


def test_route_save_requires_auth(yield_client, first_uid):
    response = yield_client.post(f"/yield/watchlist/{first_uid}")
    assert response.status_code == 401
    assert response.json()["reason"] == "WATCHLIST_AUTH_REQUIRED"


def test_route_form_save_redirects_to_login_when_unauthenticated(
        yield_client, first_uid):
    response = yield_client.post(
        f"/yield/watchlist/{first_uid}",
        content="",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login"


def test_route_save_list_remove_authenticated(
        yield_client, fake_session, first_uid):
    saved = yield_client.post(f"/yield/watchlist/{first_uid}")
    assert saved.status_code == 201
    assert saved.json()["state"] == "SAVED"
    assert saved.json()["created"] is True

    duplicate = yield_client.post(f"/yield/watchlist/{first_uid}")
    assert duplicate.status_code == 200  # deterministic idempotent no-op
    assert duplicate.json()["created"] is False

    listing = yield_client.get("/yield/watchlist.json")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["items"][0]["opportunity_uid"] == first_uid

    removed = yield_client.delete(f"/yield/watchlist/{first_uid}")
    assert removed.status_code == 200
    assert removed.json()["state"] == "REMOVED"

    after = yield_client.get("/yield/watchlist.json")
    assert after.json()["count"] == 0


def test_route_unknown_uid_typed_404(yield_client, fake_session):
    response = yield_client.post("/yield/watchlist/" + "yld_" + "b" * 32)
    assert response.status_code == 404
    assert response.json()["reason"] == "YIELD_OPPORTUNITY_UID_UNKNOWN"


def test_route_malformed_uid_typed_400(yield_client, fake_session):
    response = yield_client.post("/yield/watchlist/APPL")
    assert response.status_code == 400
    assert response.json()["reason"] == "YIELD_OPPORTUNITY_UID_MALFORMED"


def test_route_watchlist_requires_auth(yield_client):
    response = yield_client.get("/yield/watchlist.json")
    assert response.status_code == 401


def test_route_access_json_public_states(yield_client):
    """access.json presents typed states with no session; no balances or
    thresholds ever appear."""
    response = yield_client.get("/yield/access.json")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "FINCO_CRYPTO_ACCESS_PRESENTATION_V0"
    assert body["wallet"]["state"] == "DISCONNECTED"
    assert set(body["resources"]) == {
        "yield.basic", "yield.history", "yield.advanced_compare",
        "yield.alerts", "yield.execution_preflight",
    }
    payload = response.text
    assert "balance" not in payload.lower()
    assert "0 FINCO" not in payload


# ── Monitor page carries the access panel + watchlist ─────────────────────────

def test_monitor_page_renders_access_panel_and_watchlist(
        monkeypatch, tmp_path, first_uid):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finco_yield.web import router

    session = SimpleNamespace(user_id="user-1", username="demo",
                              login_at=None, session_type="demo")
    monkeypatch.setattr("app.auth.resolve_request_session",
                        lambda request: session)
    monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet",
                        lambda user_id: None)

    from finco_yield.watchlist import save_watchlist_item
    save_watchlist_item("user-1", first_uid)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    page = client.get("/yield/monitor")
    assert page.status_code == 200
    html = page.text
    assert 'data-testid="finco-access-panel"' in html
    assert "NOT_CONFIGURED" in html or "NOT_ACTIVATED" in html
    assert 'data-testid="access-row-yield.basic"' in html
    assert 'data-testid="access-row-yield.execution_preflight"' in html
    assert "execution is not enabled" in html
    assert 'data-testid="watchlist-row"' in html
    assert first_uid in html  # canonical identity rendered, not display ticker
    assert "0 FINCO" not in html
