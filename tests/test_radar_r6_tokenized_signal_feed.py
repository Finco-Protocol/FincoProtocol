"""R6: live R5 lifecycle reuse, no-gate-no-read, exact evidence and HTML/API parity."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.crypto_terminal import tokenized_signal_read as shared
from app.crypto_terminal.tokenized_signal_lifecycle import (
    CONTRACT_VERSION, HISTORY_WINDOW, LifecycleKind, MAX_FEED_EVENTS,
    build_tokenized_signal_lifecycle,
)
from app.radar_ui import tokenized_router
from app.api.v1 import crypto_router
from app.radar_ui.tokenized_gating import TokenizedGates
from app.tokenized_access import TokenizedResource
from finco_radar.venues.store import VenueMarketStore
from tests.test_radar_tokenized_signal_lifecycle import (
    NOW, _append, _entry, _registry, _row,
)
from tests.test_tokenized_access_wiring import decision

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = VenueMarketStore(str(tmp_path / "signals.sqlite"))
    reg = _registry([_entry()])
    monkeypatch.setattr(tokenized_router, "_registry", lambda: reg)
    monkeypatch.setattr(tokenized_router, "_store", lambda: store)
    return SimpleNamespace(store=store, registry=reg, monkeypatch=monkeypatch)


def gates(history, dislocation):
    return TokenizedGates(
        basic=decision(TokenizedResource.BASIC, "inactive"),
        history=decision(TokenizedResource.HISTORY, "entitled" if history else "denied"),
        dislocation=decision(TokenizedResource.DISLOCATION, "entitled" if dislocation else "denied"),
    )


def feed(env, *, max_events=30):
    return shared.read_tokenized_signals(
        "NVDA", gates=gates(True, True), registry=env.registry,
        store=env.store, as_of=NOW, max_events=max_events,
    )


def _pin_r6_route_evidence(env, monkeypatch, as_of):
    """Freeze only the two request clocks and the API's default read dependencies."""
    from app.crypto_terminal import tokenized_read

    class _FixtureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc, "HTML route must request an aware UTC clock"
            return as_of

    assert as_of.tzinfo is not None and as_of.utcoffset() is not None
    monkeypatch.setattr(tokenized_router, "datetime", _FixtureDatetime)
    monkeypatch.setattr(crypto_router, "_request_as_of", lambda: as_of)
    monkeypatch.setattr(tokenized_read, "registry", lambda: env.registry)
    monkeypatch.setattr(tokenized_read, "store", lambda: env.store)


def _entitled_r6_html_client(monkeypatch):
    session = SimpleNamespace(user_id="r6-test", username="r6-test",
                              login_at=None, session_type="user")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)
    from app.radar_ui import tokenized_gating

    async def entitled(_request):
        return gates(True, True)

    monkeypatch.setattr(tokenized_gating, "resolve_tokenized_gates", entitled)
    app = FastAPI()
    app.include_router(tokenized_router.router)
    return TestClient(app, raise_server_exceptions=True)


def _forbid_r6_read_side_effects(monkeypatch):
    """Reuse R5's tested no-write/no-provider-call boundary for both routes."""
    import urllib.request

    def forbidden(*args, **kwargs):
        pytest.fail("R6_READ_SIDE_EFFECT_FORBIDDEN")

    for method in ("append_observation", "append_many", "append_many_batched"):
        monkeypatch.setattr(VenueMarketStore, method, forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


def test_projection_reuses_original_events_ids_timestamps_and_digests(env):
    before, after = _row(120, "100"), _row(40, "102")
    _append(env.store, before, after)
    canonical = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store, as_of=NOW)
    result = feed(env)
    assert result["policy_version"] == CONTRACT_VERSION
    assert result["current_deepstate_signals"] == "UNAVAILABLE"
    assert result["notifications_enabled"] is False
    assert len(result["events"]) == len(canonical.events) == 1
    event = result["events"][0]
    original = canonical.events[0]
    assert event["event_id"] == original.event_id
    assert event["kind"] == LifecycleKind.DISLOCATION_APPEARED.value
    assert event["source_observed_at"] == original.source_observed_at == after.ts
    assert event["source_observed_at"] != after.collected_at
    assert event["prior_observation_digest"] == before.resolved_digest()
    assert event["current_observation_digest"] == after.resolved_digest()
    assert event["identity"]["instrument_id"] == original.identity.instrument_id
    assert event["identity"]["chain_id"] == original.identity.chain_id
    assert event["threshold_bps"] == "100"
    assert event["eligible_for_future_alert"] is True
    assert "delivered" not in result


def test_newest_first_preserves_canonical_chronological_engine(env):
    _append(env.store, _row(210, "100"), _row(160, "102"),
            _row(110, "99"), _row(30, "100"))
    original = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store, as_of=NOW)
    result = feed(env)
    assert [e["event_id"] for e in result["events"]] == [
        e.event_id for e in reversed(original.events)]
    assert result["events"][0]["kind"] == "DISLOCATION_CLEARED"
    assert result["events"][1]["kind"] == "DISLOCATION_DIRECTION_CHANGED"
    assert result["events"][-1]["kind"] == "DISLOCATION_APPEARED"
    assert result["events"][-1]["temporal_classification"] == "HISTORICAL"
    assert result["events"][0]["temporal_classification"] == "CURRENT"


def test_unknown_predecessor_and_empty_history_do_not_claim_crossing(env):
    _append(env.store, _row(20, "103"))
    result = feed(env)
    assert result["state"] == "NO_OBSERVED_EVENTS"
    assert result["events"] == []
    canonical = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store,
        as_of=NOW, include_no_change=True)
    assert canonical.events[0].previous_classification == "UNKNOWN_PRIOR"
    assert canonical.events[0].persistence_start_state == "PREHISTORY_UNAVAILABLE"
    assert canonical.events[0].eligible_for_future_alert is False


def test_stale_and_evidence_gap_do_not_become_clearings(env):
    _append(env.store, _row(300, "100"), _row(240, "102"),
            _row(180, "103", reference=None), _row(90, "103"))
    result = feed(env)
    kinds = [e["kind"] for e in result["events"]]
    assert "DISLOCATION_CLEARED" not in kinds
    assert "EVIDENCE_BECAME_UNAVAILABLE" in kinds
    assert "EVIDENCE_RECOVERED" in kinds
    recovered = next(e for e in result["events"] if e["kind"] == "EVIDENCE_RECOVERED")
    assert recovered["eligible_for_future_alert"] is False
    assert recovered["continuity_state"] == "GAP_OR_UNKNOWN"


def test_source_staleness_and_same_clock_cannot_prove_economic_event(env, tmp_path):
    _append(env.store, _row(3600, "100"), _row(1800, "102"))
    x = feed(env)
    assert any(e["kind"] == "EVIDENCE_BECAME_STALE" for e in x["events"])
    assert all(e["kind"] != "DISLOCATION_CLEARED" for e in x["events"])
    assert not any(e["eligible_for_future_alert"] for e in x["events"])
    other = VenueMarketStore(str(tmp_path / "collision.sqlite"))
    _append(other, _row(60, "100"), _row(60, "102"))
    collision = shared.read_tokenized_signals(
        "NVDA", gates=gates(True, True), registry=env.registry,
        store=other, as_of=NOW)
    assert not any(e["kind"] in ("DISLOCATION_APPEARED",
                                "DISLOCATION_CLEARED", "DISLOCATION_DIRECTION_CHANGED")
                   for e in collision["events"])


def test_sign_reversal_has_original_identity_and_separate_episode(env):
    _append(env.store, _row(200, "100"), _row(150, "102"), _row(30, "99"))
    x = feed(env)
    reversal = next(e for e in x["events"] if e["kind"] == "DISLOCATION_DIRECTION_CHANGED")
    assert reversal["previous_classification"] == "PREMIUM_DISLOCATION"
    assert reversal["current_classification"] == "DISCOUNT_DISLOCATION"
    assert reversal["identity"]["canonical_asset_id"] == "NVDA"


def test_output_bounds_and_exact_identity_fail_closed(env):
    _append(env.store, _row(160, "100"), _row(120, "102"), _row(70, "100"),
            _row(20, "102"))
    x = feed(env, max_events=2)
    assert len(x["events"]) <= 2
    assert len(x["events"]) == 2
    for size in (0, 31, MAX_FEED_EVENTS + 1, True):
        with pytest.raises(ValueError):
            shared.read_tokenized_signals(
                "NVDA", gates=gates(True, True),
                registry=env.registry, store=env.store, as_of=NOW, max_events=size)
    with pytest.raises(KeyError):
        shared.read_tokenized_signals(
            "UNKNOWN", gates=gates(True, True),
            registry=env.registry, store=env.store, as_of=NOW)


def test_missing_store_does_not_create_history(env, monkeypatch):
    monkeypatch.setattr("app.crypto_terminal.tokenized_read.store", lambda: None)
    x = shared.read_tokenized_signals(
        "NVDA", gates=gates(True, True), registry=env.registry, as_of=NOW)
    assert x["state"] == "HISTORY_UNAVAILABLE"
    assert x["events"] == []
    assert x["notifications_enabled"] is False
    assert x["current_deepstate_signals"] == "UNAVAILABLE"


@pytest.mark.parametrize("history,dislocation", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_exact_two_entitlement_gate_precedes_all_history_reads(env, monkeypatch, history, dislocation):
    calls = []
    original = shared.build_tokenized_signal_lifecycle

    def audited(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(shared, "build_tokenized_signal_lifecycle", audited)
    _append(env.store, _row(120, "100"), _row(20, "102"))
    x = shared.read_tokenized_signals(
        "NVDA", gates=gates(history, dislocation),
        registry=env.registry, store=env.store, as_of=NOW)
    if history and dislocation:
        assert x is not None and x["events"] and len(calls) == 1
    else:
        assert x is None and calls == []


def _api_client(env, monkeypatch, history=True, dislocation=True, crypto_allowed=True):
    calls = []
    monkeypatch.setattr(
        crypto_router, "_require_crypto_api",
        lambda req: None if crypto_allowed else JSONResponse(
            {"state": "CRYPTO_API_ACCESS_DENIED"}, status_code=403))
    def token_access(req, resource):
        calls.append(resource)
        return decision(resource,
                        "entitled" if ((resource is TokenizedResource.HISTORY and history)
                                       or (resource is TokenizedResource.DISLOCATION and dislocation))
                        else "denied")
    monkeypatch.setattr(crypto_router, "_tokenized_access", token_access)
    app = FastAPI()
    app.include_router(crypto_router.router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=True), calls


@pytest.mark.parametrize("history,dislocation", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_crypto_api_gates_before_lifecycle_composition(env, monkeypatch, history, dislocation):
    _append(env.store, _row(120, "100"), _row(20, "102"))
    actual = []
    original = shared.build_tokenized_signal_lifecycle
    def audited(*args, **kwargs):
        actual.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(shared, "build_tokenized_signal_lifecycle", audited)
    client, access_calls = _api_client(env, monkeypatch, history, dislocation)
    result = client.get("/api/v1/crypto/tokenized/NVDA/signals")
    if history and dislocation:
        assert result.status_code == 200
        assert result.json()["resource"] == "tokenized.signals"
        assert result.json()["api_version"] == "v1"
        assert result.json()["data"]["current_deepstate_signals"] == "UNAVAILABLE"
        assert len(actual) == 1
    else:
        assert result.status_code == 403
        assert actual == []
        assert "event_id" not in result.text
        assert "observation_digest" not in result.text
        assert "basis_bps" not in result.text
        assert "threshold_bps" not in result.text
        assert "tokenized.signals" not in result.text


def test_crypto_api_denied_before_even_entitlement_resolution(env, monkeypatch):
    calls = []
    original = shared.build_tokenized_signal_lifecycle
    monkeypatch.setattr(shared, "build_tokenized_signal_lifecycle",
                        lambda *a, **kw: calls.append(1) or original(*a, **kw))
    client, access = _api_client(env, monkeypatch, True, True, crypto_allowed=False)
    res = client.get("/api/v1/crypto/tokenized/NVDA/signals")
    assert res.status_code == 403 and calls == [] and access == []


def test_html_and_api_share_identical_event_ids_not_hidden_premium_fields(env, monkeypatch):
    rows = (_row(150, "100"), _row(80, "102"), _row(30, "100"))
    _append(env.store, *rows)
    expected = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store, as_of=NOW)
    assert len(expected.events) == 2, "fixture must prove appeared and cleared events"
    _pin_r6_route_evidence(env, monkeypatch, NOW)
    before_count = env.store.count()
    _forbid_r6_read_side_effects(monkeypatch)

    html = _entitled_r6_html_client(monkeypatch).get("/radar/tokenized-markets/NVDA")
    assert html.status_code == 200
    assert 'data-testid="tmd-signals-feed"' in html.text
    assert 'data-testid="tmd-signals-list"' in html.text
    assert html.text.count('data-testid="tmd-signal-event"') == len(expected.events)
    assert "HISTORICAL" in html.text and "CURRENT" in html.text
    assert 'data-testid="tmd-signals-locked"' not in html.text

    client, access_calls = _api_client(env, monkeypatch)
    api = client.get("/api/v1/crypto/tokenized/NVDA/signals")
    assert api.status_code == 200
    assert {TokenizedResource.HISTORY, TokenizedResource.DISLOCATION} <= set(access_calls)
    payload = api.json()
    assert payload["as_of"] == NOW.isoformat()
    assert payload["data"]["as_of"] == NOW.isoformat()
    assert payload["state"] == payload["data"]["state"] == "AVAILABLE"
    events = payload["data"]["events"]
    originals = list(reversed(expected.events))
    assert len(events) == len(originals) > 0
    assert [event["event_id"] for event in events] == [event.event_id for event in originals]
    assert [event["temporal_classification"] for event in events] == [
        event.temporal_classification for event in originals]
    assert {event["temporal_classification"] for event in events} == {"HISTORICAL", "CURRENT"}
    observed_clocks = {row.ts for row in rows}
    for event, original in zip(events, originals, strict=True):
        assert event["source_observed_at"] == original.source_observed_at
        assert event["source_observed_at"] in observed_clocks
        assert event["prior_observation_digest"] == original.prior_observation_digest
        assert event["current_observation_digest"] == original.current_observation_digest
        assert event["identity"] == asdict(original.identity)
        assert event["event_id"] in html.text
        assert event["source_observed_at"] in html.text
        assert event["prior_observation_digest"] in html.text
        assert event["current_observation_digest"] in html.text
        assert event["identity"]["instrument_id"] in html.text
        assert event["identity"]["contract_address"] in html.text
    assert payload["data"]["notifications_enabled"] is False
    assert payload["data"]["current_deepstate_signals"] == "UNAVAILABLE"
    assert env.store.count() == before_count


def test_html_and_api_expire_observed_events_without_fabricating_transitions(env, monkeypatch):
    """Eight days after the exact same observations, R5/HTML/API are truthfully empty."""
    rows = (_row(150, "100"), _row(80, "102"), _row(30, "100"))
    _append(env.store, *rows)
    assert HISTORY_WINDOW == timedelta(days=7)
    current = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store, as_of=NOW)
    assert current.events, "negative control requires real previously visible events"

    expired_at = NOW + timedelta(days=8)
    expired = build_tokenized_signal_lifecycle(
        "NVDA", registry=env.registry, store=env.store, as_of=expired_at)
    assert expired.events == ()
    assert expired.source_observations_examined == 0

    _pin_r6_route_evidence(env, monkeypatch, expired_at)
    before_count = env.store.count()
    _forbid_r6_read_side_effects(monkeypatch)
    html = _entitled_r6_html_client(monkeypatch).get("/radar/tokenized-markets/NVDA")
    assert html.status_code == 200
    assert 'data-testid="tmd-signals-feed"' in html.text
    assert 'data-testid="tmd-signals-empty"' in html.text
    assert 'data-testid="tmd-signals-list"' not in html.text
    assert 'data-testid="tmd-signal-event"' not in html.text
    assert 'data-testid="tmd-signals-locked"' not in html.text

    client, access_calls = _api_client(env, monkeypatch)
    api = client.get("/api/v1/crypto/tokenized/NVDA/signals")
    assert api.status_code == 200
    assert {TokenizedResource.HISTORY, TokenizedResource.DISLOCATION} <= set(access_calls)
    payload = api.json()
    assert payload["as_of"] == expired_at.isoformat()
    assert payload["state"] == payload["data"]["state"] == "NO_OBSERVED_EVENTS"
    assert payload["data"]["as_of"] == expired_at.isoformat()
    assert payload["data"]["events"] == []
    assert payload["data"]["source_observations_examined"] == 0
    assert payload["data"]["notifications_enabled"] is False
    assert payload["data"]["current_deepstate_signals"] == "UNAVAILABLE"
    assert env.store.count() == before_count


def test_html_one_gate_denied_never_composes_protected_feed(env, monkeypatch):
    from app.radar_ui import tokenized_gating
    session = SimpleNamespace(user_id="r6-test", username="r6-test",
                              login_at=None, session_type="user")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda req: session)
    async def partial(_req):
        return gates(False, True)
    monkeypatch.setattr(tokenized_gating, "resolve_tokenized_gates", partial)
    def denied_builder(*a, **kw):
        pytest.fail("protected lifecycle built under denied gate")
    monkeypatch.setattr(shared, "build_tokenized_signal_lifecycle", denied_builder)
    app = FastAPI()
    app.include_router(tokenized_router.router)
    page = TestClient(app, raise_server_exceptions=True).get(
        "/radar/tokenized-markets/NVDA")
    assert page.status_code == 200
    assert 'data-testid="tmd-signals-locked"' in page.text
    assert 'data-testid="tmd-signals-list"' not in page.text
    assert 'data-testid="tmd-signal-event"' not in page.text


def test_previous_routes_and_frozen_modules_preserved():
    from app.api.v1.crypto_router import router
    paths = {route.path for route in router.routes}
    assert "/crypto/tokenized/{canonical_asset_id}/signals" in paths
    assert "/crypto/tokenized/{canonical_asset_id}/dislocations" in paths
    assert "/crypto/tokenized/{canonical_asset_id}/history" in paths
    adapter = (ROOT / "app/crypto_terminal/tokenized_signal_read.py").read_text()
    for forbidden in ("append_observation(", "requests.get(", "httpx.get(",
                      "requests.post(", "collect_r_live_batch(", "execute_trade("):
        assert forbidden not in adapter
    assert (ROOT / "app/crypto_terminal/tokenized_signal_lifecycle.py").exists()
