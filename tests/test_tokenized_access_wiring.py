"""Tokenized Markets access wiring (post-#179) — canonical decisions applied at the presentation boundary.

The canonical authority (evaluate_resource_access via ``app.tokenized_access``) is exercised in
test_crypto_access_integration_v1. Here the resolver is replaced by typed decisions to prove the ROUTER
wiring: protected history / dislocation payload is removed from the render context when denied, gating-off
keeps the existing ungated behaviour, and the public basic surface is always rendered.
"""
from __future__ import annotations

import ast
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.crypto_resource_access import CryptoAccessDecision, CryptoAccessState as S
from app.radar_ui import tokenized_gating, tokenized_router
from app.tokenized_access import TokenizedResource as R
from finco_radar.venues.store import VenueMarketStore
from tests.test_tokenized_live_intelligence_v1 import _market_obs
from tests.test_tokenized_markets_composition import ROBINHOOD_NVDA
from model_v2_governance import merge_base_ref

ROOT = Path(__file__).resolve().parents[1]


def decision(resource: R, kind: str) -> CryptoAccessDecision:
    if resource is R.BASIC:
        return CryptoAccessDecision(resource.value, S.PUBLIC, True, False, False, "PUBLIC_RESOURCE")
    return {
        "entitled": CryptoAccessDecision(resource.value, S.ENTITLED, True, True, True,
                                         "BALANCE_AT_OR_ABOVE_THRESHOLD"),
        "inactive": CryptoAccessDecision(resource.value, S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE, True, False,
                                         False, "TOKEN_GATING_OFF"),
        "denied": CryptoAccessDecision(resource.value, S.ENTITLEMENT_NOT_SATISFIED, False, False, True,
                                       "BALANCE_BELOW_THRESHOLD"),
    }[kind]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "venues.db"
    store = VenueMarketStore(db_path)
    now = datetime.now(timezone.utc)
    for price, age in (("101", timedelta(hours=25)), ("102", timedelta(seconds=30))):
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA, price=price, at=now - age,
            reference_at=now - age))
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db_path))
    session = SimpleNamespace(user_id="user-1", username="qa", login_at=None, session_type="user")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)

    captured = {}
    real = tokenized_router._templates.TemplateResponse

    def spy(*args, **kwargs):
        captured["context"] = kwargs.get("context")
        captured["name"] = kwargs.get("name")
        return real(*args, **kwargs)

    monkeypatch.setattr(tokenized_router._templates, "TemplateResponse", spy)
    app = FastAPI()
    app.include_router(tokenized_router.router)
    calls = []

    def set_gates(history="inactive", dislocation="inactive"):
        async def fake(request, resource, **kw):
            calls.append(resource)
            return decision(resource, {R.HISTORY: history, R.DISLOCATION: dislocation}.get(resource, "inactive"))
        monkeypatch.setattr(tokenized_gating, "resolve_tokenized_access", fake)

    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=True), captured=captured,
                           calls=calls, set_gates=set_gates, mp=monkeypatch)


def detail(env):
    page = env.client.get("/radar/tokenized-markets/NVDA")
    assert page.status_code == 200
    return page


def landing(env):
    page = env.client.get("/radar/tokenized-markets")
    assert page.status_code == 200
    return page


# ── gating off / entitled: existing behaviour preserved ──────────────────────────────────────────
@pytest.mark.parametrize("kind", ["inactive", "entitled"])
def test_ungated_or_entitled_detail_keeps_full_premium_surface(env, kind):
    env.set_gates(kind, kind)
    page = detail(env)
    for testid in ("tmd-history-table", "tmd-basis-history-chart", "tmd-cross-venue", "tmd-dislocation-events"):
        assert f'data-testid="{testid}"' in page.text, testid
    assert "tmd-premium-locked" not in page.text and "tmd-history-locked" not in page.text
    assert env.captured["context"]["basis_series"]


def test_real_default_policy_is_inactive_and_unchanged(env, monkeypatch):
    """No stub: canonical defaults -> INACTIVE -> premium surface shown, token truth stays False."""
    import asyncio
    for key in ("FINCO_TOKEN_GATING_ENABLED", "FINCO_ENTITLEMENT_POLICIES_JSON"):
        monkeypatch.delenv(key, raising=False)
    gates = asyncio.run(tokenized_gating.resolve_tokenized_gates(object()))
    assert gates.basic.state is S.PUBLIC
    for d in (gates.history, gates.dislocation):
        assert d.state is S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE
        assert d.access_allowed is True and d.token_entitled is False
    assert 'data-testid="tmd-basis-history-chart"' in detail(env).text


# ── history denied ───────────────────────────────────────────────────────────────────────────────
def test_history_denied_removes_history_payload_but_keeps_dislocation(env):
    env.set_gates(history="denied", dislocation="inactive")
    page = detail(env)
    ctx = env.captured["context"]
    assert ctx["basis_series"] == []
    for item in ctx["intelligence"].representations:
        assert item.points == () and item.basis_change_24h_bps is None and item.basis_change_7d_bps is None
    assert 'data-testid="tmd-history-locked"' in page.text
    assert 'data-testid="tmd-basis-history-chart"' not in page.text and "data-points" not in page.text
    assert 'data-testid="tmd-cross-venue"' in page.text           # dislocation resource unaffected
    assert ctx["access"]["history"]["allowed"] is False and ctx["access"]["dislocation"]["allowed"] is True


# ── dislocation denied ───────────────────────────────────────────────────────────────────────────
def test_dislocation_denied_removes_divergence_and_events_but_keeps_history(env):
    env.set_gates(history="entitled", dislocation="denied")
    page = detail(env)
    intel = env.captured["context"]["intelligence"]
    assert intel.events == ()
    assert (intel.cross_venue.state, intel.cross_venue.divergence_bps) == ("ACCESS_RESTRICTED", None)
    assert intel.cross_venue.low_venue is None and intel.cross_venue.high_price is None
    assert 'data-testid="tmd-dislocation-locked"' in page.text
    assert 'data-testid="tmd-cross-venue"' not in page.text
    assert 'data-testid="tmd-dislocation-events"' not in page.text
    assert 'data-testid="tmd-basis-history-chart"' in page.text   # history resource unaffected


def test_both_denied_never_builds_protected_context_and_basic_stays_public(env):
    env.set_gates(history="denied", dislocation="denied")
    page = detail(env)
    ctx = env.captured["context"]
    assert ctx["intelligence"] is None and ctx["basis_series"] == []
    assert 'data-testid="tmd-premium-locked"' in page.text
    assert ctx["view"] is not None and ctx["reference"] is not None      # basic identity/current state remain
    assert "NVDA" in page.text


def test_authority_failure_fails_closed_and_page_still_renders(env):
    async def boom(request, resource, **kw):
        raise RuntimeError("authority exploded https://secret.example/key")
    env.mp.setattr(tokenized_gating, "resolve_tokenized_access", boom)
    page = detail(env)
    ctx = env.captured["context"]
    assert ctx["intelligence"] is None and ctx["basis_series"] == []
    assert "secret.example" not in page.text and "exploded" not in page.text
    assert ctx["access"]["history"]["state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"


# ── landing ──────────────────────────────────────────────────────────────────────────────────────
def test_landing_denied_redacts_premium_columns_and_keeps_public_rows(env):
    env.set_gates(history="denied", dislocation="denied")
    page = landing(env)
    rows = env.captured["context"]["rows"]
    assert rows and all(r["basis_change_24h_bps"] is None and r["basis_change_7d_bps"] is None for r in rows)
    assert all(r["cross_venue_divergence_bps"] is None and r["cross_venue_state"] == "ACCESS_RESTRICTED"
               for r in rows)
    assert 'data-testid="tm-premium-access-note"' in page.text
    assert 'data-testid="tm-locked-history"' in page.text            # cross-venue detail lives on the asset page
    assert 'data-testid="tokenized-markets-table"' in page.text
    assert any(r["best_price"] for r in rows)                             # public current market state remains


def test_landing_ungated_keeps_existing_premium_columns(env):
    env.set_gates("inactive", "inactive")
    page = landing(env)
    assert "tm-premium-access-note" not in page.text and "tm-locked-history" not in page.text
    assert all(r["cross_venue_state"] != "ACCESS_RESTRICTED" for r in env.captured["context"]["rows"])


@pytest.mark.parametrize("history,dislocation", [("entitled", "denied"), ("denied", "entitled"),
                                                  ("inactive", "inactive"), ("denied", "denied")])
def test_redact_landing_row_only_removes_denied_resources(history, dislocation):
    gates = tokenized_gating.TokenizedGates(
        decision(R.BASIC, "inactive"), decision(R.HISTORY, history), decision(R.DISLOCATION, dislocation))
    row = {"best_price": "102", "best_basis_bps": "200", "basis_change_24h_bps": "100",
           "basis_change_7d_bps": "300", "cross_venue_divergence_bps": "40", "cross_venue_state": "AVAILABLE"}
    out = tokenized_gating.redact_landing_row(row, gates)
    assert (out["best_price"], out["best_basis_bps"]) == ("102", "200")        # public state never redacted
    history_denied, dislocation_denied = history == "denied", dislocation == "denied"
    assert (out["basis_change_24h_bps"] is None) is history_denied
    assert (out["basis_change_7d_bps"] is None) is history_denied
    assert (out["cross_venue_divergence_bps"] is None) is dislocation_denied
    assert (out["cross_venue_state"] == "ACCESS_RESTRICTED") is dislocation_denied
    assert row["basis_change_24h_bps"] == "100"                                # input not mutated


def test_only_the_three_tokenized_resources_are_resolved(env):
    env.set_gates("entitled", "denied")
    detail(env)
    assert env.calls == [R.BASIC, R.HISTORY, R.DISLOCATION]


# ── boundaries ───────────────────────────────────────────────────────────────────────────────────
def test_router_and_gating_hold_no_balance_rpc_or_evaluator_logic():
    forbidden_modules = {"app.protocol.entitlement_evaluator", "app.protocol.token_balance",
                         "app.protocol.token_deployments", "app.verified.token_entitlement"}
    for rel in ("app/radar_ui/tokenized_router.py", "app/radar_ui/tokenized_gating.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden_modules, (rel, node.module)
            elif isinstance(node, ast.Name):
                assert node.id not in {"evaluate_resource_access", "read_token_balance"}, (rel, node.id)


def test_market_data_authority_does_not_consult_access_authority():
    for path in (ROOT / "finco_radar" / "venues").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "tokenized_access" not in text and "evaluate_resource_access" not in text, path


@pytest.mark.parametrize("namespace", ["financial_engine", "finco_core", "finco_radar/venues"])
def test_frozen_namespaces_zero_diff(namespace):
    out = subprocess.run(["git", "diff", "--name-only", f"{merge_base_ref()}..HEAD", "--", namespace],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("git unavailable")
    # Authorised by the exact-identity correction (registry collapse of same-identity source rows);
    # every other path in this namespace stays frozen.
    allowed = {"finco_radar/venues/registry.py", "finco_radar/venues/models.py"}
    # Explicitly authorized Model V2 epic engine files are governed by the
    # Model V2 scope contract (tests/model_v2_governance.py); this guard keeps
    # protecting every other frozen path.
    from model_v2_governance import approved_by_active_model_v2_scope
    changed = [
        p for p in out.stdout.split()
        if p not in allowed and not approved_by_active_model_v2_scope(p)
    ]
    assert changed == [], changed
