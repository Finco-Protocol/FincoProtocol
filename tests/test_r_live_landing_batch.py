"""One-request progressive current surface with exact policy identities."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1_1.r_live_public_router import router
from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS


ROOT = Path(__file__).resolve().parents[1]


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    return TestClient(app)


def test_batch_current_stream_uses_every_exact_policy_and_preserves_stale(monkeypatch):
    # /current now delegates to collect_r_live_batch (one registry + one shared RPC client).
    # Patch at that layer; the behavioral contract (all policies, STALE preserved) is unchanged.
    from app.radar_rwa import r_live_service
    policies = tuple(APPROVED_RLIVE_ASSETS.values())
    states = {policies[0].asset_key.canonical_id: "AVAILABLE",
              policies[1].asset_key.canonical_id: "STALE"}

    def batch(*, rpc_url, **kwargs):
        for policy in policies:
            cid = policy.asset_key.canonical_id
            state = states.get(cid, "UNAVAILABLE")
            data = {
                "reason": "POOL_ACTIVITY_STALE" if state == "STALE" else None,
                "b1_0_premium": {"value_bps": "12" if state == "AVAILABLE" else None},
            }
            yield cid, state, data

    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")
    monkeypatch.setattr(r_live_service, "collect_r_live_batch", batch)
    with client() as api:
        response = api.get("/api/v1.1/radar/r-live/current")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    items = [json.loads(line) for line in response.text.splitlines()]
    assert len(items) == len(policies)
    assert {row["canonical_id"] for row in items} == {p.asset_key.canonical_id for p in policies}
    stale = next(row for row in items if row["state"] == "STALE")
    assert stale["data"]["b1_0_premium"]["value_bps"] is None
    assert stale["data"]["reason"] == "POOL_ACTIVITY_STALE"


def test_batch_ranges_are_read_only_registry_driven(monkeypatch):
    # The bulk ranges endpoint delegates to the single-pass canonical batch
    # read over B1.3 history; every approved identity must be covered.
    from app.radar_rwa import bnb_history
    calls = []

    def ranges(pairs, **kwargs):
        calls.extend(key.canonical_id for _uid, key in pairs)
        return {key.canonical_id: {"range_1h": {"state": "UNAVAILABLE", "observation_count": 0},
                                   "range_24h": {"state": "UNAVAILABLE", "observation_count": 0},
                                   "last_available": None}
                for _uid, key in pairs}

    monkeypatch.setattr(bnb_history, "read_r_live_ranges_batch_readonly", ranges)
    with client() as api:
        response = api.get("/api/v1.1/radar/r-live/history/ranges")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["history_kind"] == "HISTORICAL"
    assert set(calls) == {p.asset_key.canonical_id for p in APPROVED_RLIVE_ASSETS.values()}
    assert set(data["assets"]) == set(calls)


def test_landing_is_snapshot_first_and_never_streams_live_acquisition():
    """Instant R-LIVE UX: the landing table reads the latest-snapshot
    endpoint only (plus read-only historical ranges); the live /current
    streaming acquisition is no longer on the page request path, and
    polling while cold hits the snapshot endpoint exclusively."""
    js = (ROOT / "static/radar/r_live_table.js").read_text(encoding="utf-8")
    assert js.count("fetch(") == 2
    assert 'SNAPSHOT_URL = "/api/v1.1/radar/r-live/snapshot"' in js
    assert "fetch(SNAPSHOT_URL" in js
    assert 'fetch("/api/v1.1/radar/r-live/history/ranges"' in js
    assert 'fetch("/api/v1.1/radar/r-live/current"' not in js
    assert "history?limit=100" not in js
    assert "data-canonical-id" in js
    assert "HISTORICAL · Last available" in js
    assert 'snap_state === "STALE"' in js
    assert 'snap_state === "AVAILABLE"' in js
    assert 'set_badge(row_el, snap_state)' in js
    assert 'snap_state === "STALE" && last' in js
    assert 'snap_state === "UNAVAILABLE" && last' not in js
    assert 'snap_data.b1_0_premium' in js
    assert 'Math.abs(parseFloat(premium_a.value_bps))' in js
    # cold-start polling reads the snapshot ONLY — never live acquisition
    assert "INITIALIZING" in js
    # continuous freshness: polling continues through every state and is
    # never torn down once the snapshot is warm
    assert "setInterval(poll_tick" in js
    assert "clearInterval" not in js
    assert "document.hidden" in js
    assert 'SNAPSHOT_URL = "/api/v1.1/radar/r-live/snapshot"' in js
    sorting = js.split('function sort_rows()', 1)[1].split('fetch("/api/v1.1/radar/r-live/history/ranges"', 1)[0]
    assert 'last.premium_bps' not in sorting
    template = (ROOT / "app/templates/radar/r_live_landing.html").read_text(encoding="utf-8")
    assert 'rlive-badge--loading' in template
    assert 'data-testid="rlive-initializing"' in template
    assert "cold_start" in template
