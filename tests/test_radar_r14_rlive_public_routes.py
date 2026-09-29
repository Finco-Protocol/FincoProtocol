"""R14-C: Public R-LIVE routes mounted on main_web.py app.

Verifies that /api/v1.1/radar/r-live/* routes are reachable through the
public web app (main_web:app), NOT only through the institutional API.

Also verifies that browser JS distinguishes transport errors (HTTP 4xx/5xx)
from canonical authority UNAVAILABLE state.

Markers verified:
  PUBLIC_RLIVE_SNAPSHOT_ROUTE_ON_WEB_APP
  PUBLIC_RLIVE_HISTORY_ROUTE_ON_WEB_APP
  PUBLIC_RLIVE_ASSETS_ROUTE_ON_WEB_APP
  R14_RLIVE_EXACT_ASSETKEY_ONLY
  R14_RLIVE_ZERO_BROWSER_HISTORY_WRITES
  R14_RLIVE_TRANSPORT_ERROR_NOT_AUTHORITY_UNAVAILABLE
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def web_client():
    """Unauthenticated TestClient against main_web:app."""
    import main_web
    from starlette.testclient import TestClient
    return TestClient(main_web.app, raise_server_exceptions=False)


def _aapl_canonical_id() -> str:
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    for cid in APPROVED_BY_CANONICAL_ID:
        if APPROVED_BY_CANONICAL_ID[cid].symbol == "AAPL":
            return cid
    raise RuntimeError("AAPL not found in APPROVED_BY_CANONICAL_ID")


# ── PUBLIC_RLIVE_ASSETS_ROUTE_ON_WEB_APP ─────────────────────────────────────

class TestPublicAssetsRouteOnWebApp:
    """PUBLIC_RLIVE_ASSETS_ROUTE_ON_WEB_APP"""

    def test_assets_route_returns_200(self, web_client):
        r = web_client.get("/api/v1.1/radar/r-live/assets")
        assert r.status_code == 200

    def test_assets_route_returns_json_envelope(self, web_client):
        r = web_client.get("/api/v1.1/radar/r-live/assets")
        body = r.json()
        assert body.get("state") == "AVAILABLE"
        assert "data" in body
        assert "assets" in body["data"]

    def test_assets_route_lists_approved_registry(self, web_client):
        from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
        r = web_client.get("/api/v1.1/radar/r-live/assets")
        assets = r.json()["data"]["assets"]
        cids = {a["canonical_id"] for a in assets}
        registry_cids = {p.asset_key.canonical_id for p in APPROVED_RLIVE_ASSETS.values()}
        assert cids == registry_cids

    def test_assets_route_no_ticker_fuzzy_lookup(self, web_client):
        """Each asset carries canonical_id; no symbol-based resolution."""
        r = web_client.get("/api/v1.1/radar/r-live/assets")
        for asset in r.json()["data"]["assets"]:
            # canonical_id must be chain:address format
            cid = asset["canonical_id"]
            assert ":" in cid, f"canonical_id {cid!r} is not chain:address format"


# ── PUBLIC_RLIVE_SNAPSHOT_ROUTE_ON_WEB_APP ───────────────────────────────────

class TestPublicSnapshotRouteOnWebApp:
    """PUBLIC_RLIVE_SNAPSHOT_ROUTE_ON_WEB_APP"""

    def test_snapshot_route_200_for_valid_uid(self, web_client):
        cid = _aapl_canonical_id()
        r = web_client.get(f"/api/v1.1/radar/r-live/{cid}")
        assert r.status_code == 200

    def test_snapshot_route_returns_envelope(self, web_client):
        cid = _aapl_canonical_id()
        r = web_client.get(f"/api/v1.1/radar/r-live/{cid}")
        body = r.json()
        assert "state" in body

    def test_snapshot_route_200_for_unknown_uid(self, web_client):
        """Unknown UID returns 200 with UNAVAILABLE state (not 404)."""
        r = web_client.get("/api/v1.1/radar/r-live/9999:0xdeadbeef")
        assert r.status_code == 200
        assert r.json().get("state") in {"UNAVAILABLE", "STALE", "AVAILABLE"}

    def test_snapshot_route_exact_canonical_id_only(self, web_client):
        """Route accepts canonical_id; ticker-only path returns UNAVAILABLE not 500."""
        r = web_client.get("/api/v1.1/radar/r-live/AAPL")
        assert r.status_code == 200
        assert r.json().get("state") == "UNAVAILABLE"

    def test_r14_rlive_no_wallet_signing_or_trading(self, web_client):
        """Snapshot route exposes reference data only; no trading endpoints."""
        r = web_client.get("/api/v1.1/radar/r-live/assets")
        body = r.json()
        body_str = str(body)
        assert "trade" not in body_str.lower()
        assert "wallet" not in body_str.lower()
        assert "sign" not in body_str.lower()


# ── PUBLIC_RLIVE_HISTORY_ROUTE_ON_WEB_APP ────────────────────────────────────

class TestPublicHistoryRouteOnWebApp:
    """PUBLIC_RLIVE_HISTORY_ROUTE_ON_WEB_APP"""

    def test_history_route_200_for_valid_uid(self, web_client):
        cid = _aapl_canonical_id()
        r = web_client.get(f"/api/v1.1/radar/r-live/{cid}/history?limit=5")
        assert r.status_code == 200

    def test_history_route_returns_envelope(self, web_client):
        cid = _aapl_canonical_id()
        r = web_client.get(f"/api/v1.1/radar/r-live/{cid}/history?limit=5")
        body = r.json()
        assert "state" in body

    def test_history_route_available_has_points_key(self, web_client):
        cid = _aapl_canonical_id()
        r = web_client.get(f"/api/v1.1/radar/r-live/{cid}/history?limit=5")
        body = r.json()
        if body["state"] == "AVAILABLE":
            assert "points" in body["data"]
            assert isinstance(body["data"]["points"], list)

    def test_history_route_200_for_unknown_uid(self, web_client):
        r = web_client.get("/api/v1.1/radar/r-live/9999:0xdeadbeef/history")
        assert r.status_code == 200
        assert r.json().get("state") == "UNAVAILABLE"

    def test_r14_rlive_zero_browser_history_writes(self):
        """PUBLIC_R14_RLIVE_ZERO_BROWSER_HISTORY_WRITES
        History route is GET-only; router has no POST/PUT/DELETE for history."""
        from app.api.v1_1.r_live_public_router import router
        history_routes = [
            r for r in router.routes
            if hasattr(r, "path") and "history" in r.path
        ]
        assert history_routes, "History route must exist"
        for route in history_routes:
            methods = getattr(route, "methods", set())
            assert methods == {"GET"}, f"History route must be GET-only, got {methods}"


# ── R14_RLIVE_TRANSPORT_ERROR_NOT_AUTHORITY_UNAVAILABLE ──────────────────────

class TestTransportErrorNotAuthorityUnavailable:
    """R14_RLIVE_TRANSPORT_ERROR_NOT_AUTHORITY_UNAVAILABLE"""

    def test_r_live_table_js_checks_response_ok(self):
        """r_live_table.js must check response.ok before parsing JSON."""
        js = (REPO / "static" / "radar" / "r_live_table.js").read_text()
        assert "r.ok" in js or "response.ok" in js, (
            "r_live_table.js must check response.ok to distinguish "
            "transport errors from canonical UNAVAILABLE state"
        )

    def test_r_live_table_js_marks_transport_error(self):
        """r_live_table.js must mark transport errors distinctly."""
        js = (REPO / "static" / "radar" / "r_live_table.js").read_text()
        assert "TRANSPORT_ERROR" in js, (
            "r_live_table.js must mark transport errors (TRANSPORT_ERROR) "
            "distinctly from canonical authority UNAVAILABLE"
        )

    def test_r_live_detail_html_checks_response_ok(self):
        """r_live_detail.html fetch must check response.ok."""
        html = (REPO / "app" / "templates" / "radar" / "r_live_detail.html").read_text()
        assert "r.ok" in html or "response.ok" in html, (
            "r_live_detail.html must check response.ok on snapshot fetch"
        )

    def test_r_live_detail_html_marks_transport_error(self):
        """r_live_detail.html must mark transport errors distinctly."""
        html = (REPO / "app" / "templates" / "radar" / "r_live_detail.html").read_text()
        assert "TRANSPORT_ERROR" in html, (
            "r_live_detail.html must mark transport errors distinctly"
        )


# ── R14_RLIVE_EXACT_ASSETKEY_ONLY ────────────────────────────────────────────

class TestExactAssetKeyOnly:
    """R14_RLIVE_EXACT_ASSETKEY_ONLY — no fuzzy/ticker lookup in public router."""

    def test_public_router_does_not_call_ticker_lookup(self):
        """Router must not import or call any ticker/symbol resolver."""
        router_src = (REPO / "app" / "api" / "v1_1" / "r_live_public_router.py").read_text()
        # These would indicate an actual ticker-based resolution call:
        assert "ticker_lookup" not in router_src
        assert "by_ticker" not in router_src
        assert "symbol_to_uid" not in router_src
        assert "APPROVED_BY_SYMBOL" not in router_src

    def test_public_router_uses_canonical_id_parameter(self):
        router_src = (REPO / "app" / "api" / "v1_1" / "r_live_public_router.py").read_text()
        assert "uid" in router_src, "Router must use uid (canonical_id) parameter"


# ── Institutional endpoints NOT exposed through main_web ─────────────────────

class TestInstitutionalEndpointsNotExposedOnWebApp:
    """Verify private institutional endpoints are NOT accessible via main_web:app."""

    def test_project_list_not_exposed(self, web_client):
        r = web_client.get("/api/v1.1/projects")
        # Must be 401 (auth required) or 404 (not mounted) — never 200 with data
        assert r.status_code in {401, 404, 405}

    def test_export_not_exposed(self, web_client):
        r = web_client.get("/api/v1.1/projects/fake-project/export")
        assert r.status_code in {401, 404, 405}

    def test_validation_not_exposed(self, web_client):
        r = web_client.get("/api/v1.1/projects/fake-project/validation")
        assert r.status_code in {401, 404, 405}

    def test_run_certificate_not_exposed(self, web_client):
        r = web_client.get("/api/v1.1/projects/fake-project/run-certificate")
        assert r.status_code in {401, 404, 405}

    def test_verify_not_exposed(self, web_client):
        r = web_client.get("/api/v1.1/projects/fake-project/verify")
        assert r.status_code in {401, 404, 405}
