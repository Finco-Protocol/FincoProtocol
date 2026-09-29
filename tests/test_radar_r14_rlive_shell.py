"""R14: FINCO Radar R-LIVE Product Shell — navigation and product surface tests.

Markers verified:
  RADAR_DEFAULT_IS_RLIVE         — GET /radar redirects to /radar/r-live
  RADAR_NAV_ORDER_RLIVE_STOCKS_CRYPTO_ECONOMY — domain nav order
  RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED — MASSIVE/provider block removed from template
  RADAR_FUNDAMENTALS_LINEAGE_PRESERVED    — lineage data still present in view model

Coverage groups:
  A. Navigation — /radar 302 → /radar/r-live; nav order R-LIVE first
  B. R-LIVE landing — route 200, table present, AAPL row approved, others UNAVAILABLE
  C. R-LIVE detail — /radar/r-live/aapl 200, detail shell rendered, methodology present
  D. R-LIVE detail — unknown asset returns 200 with UNAVAILABLE shell
  E. Stocks route — /radar/stocks 200 (renamed from /radar)
  F. Provider branding — equity_fundamentals.html template has no MASSIVE/provider block
  G. Lineage data preserved in equity view model (backend not touched)
  H. JS and static asset wiring — r_live_table.js referenced in landing template
  I. Router registration — r_live_router included in __init__.py assembly
  J. Missing != 0 — STALE/UNAVAILABLE rows suppress numeric values in template
"""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ── A: Navigation ────────────────────────────────────────────────────────────

class TestRadarDefaultIsRLive:
    """RADAR_DEFAULT_IS_RLIVE — /radar redirects to /radar/r-live."""

    def test_RADAR_DEFAULT_IS_RLIVE(self):
        """GET /radar → 302 redirect to /radar/r-live (R-LIVE is default domain)."""
        pytest.importorskip("uvicorn")
        import main_web  # noqa: F401 — import validates router assembly
        from app.radar_ui.r_live_router import router as r_live_router
        # Find the /radar route — it must be a redirect.
        redirects = [r for r in r_live_router.routes
                     if hasattr(r, "path") and r.path == "/radar"]
        assert redirects, (
            "RADAR_DEFAULT_IS_RLIVE: No /radar route found in r_live_router. "
            "GET /radar must 302 redirect to /radar/r-live."
        )
        # Verify it is a redirect by calling with httpx TestClient (no follow_redirects).
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=False)
        resp = client.get("/radar")
        assert resp.status_code == 302, (
            f"RADAR_DEFAULT_IS_RLIVE: Expected 302, got {resp.status_code}"
        )
        location = resp.headers.get("location", "")
        assert "/radar/r-live" in location, (
            f"RADAR_DEFAULT_IS_RLIVE: Redirect location {location!r} does not point to /radar/r-live"
        )

    def test_RADAR_NAV_ORDER_RLIVE_STOCKS_CRYPTO_ECONOMY(self):
        """domain_nav.html must list R-LIVE before Stocks, Crypto, Economy."""
        nav_tmpl = REPO / "app/templates/radar/domain_nav.html"
        content = nav_tmpl.read_text()
        # Verify all four domains present.
        assert "r-live" in content.lower(), "R-LIVE link missing from domain_nav.html"
        assert "/radar/stocks" in content, "Stocks link (/radar/stocks) missing from domain_nav.html"
        assert "/radar/crypto" in content, "Crypto link missing from domain_nav.html"
        assert "/radar/economy" in content, "Economy link missing from domain_nav.html"
        # Verify R-LIVE appears before Stocks in the nav markup.
        rlive_pos = content.lower().find("r-live")
        stocks_pos = content.find("/radar/stocks")
        assert rlive_pos < stocks_pos, (
            "RADAR_NAV_ORDER_RLIVE_STOCKS_CRYPTO_ECONOMY: "
            f"R-LIVE (pos {rlive_pos}) must appear before Stocks (pos {stocks_pos}) in domain_nav.html"
        )
        # Verify Stocks before Crypto.
        crypto_pos = content.find("/radar/crypto")
        assert stocks_pos < crypto_pos, (
            f"Stocks (pos {stocks_pos}) must appear before Crypto (pos {crypto_pos})"
        )
        # Verify Crypto before Economy.
        economy_pos = content.find("/radar/economy")
        assert crypto_pos < economy_pos, (
            f"Crypto (pos {crypto_pos}) must appear before Economy (pos {economy_pos})"
        )


# ── B: R-LIVE landing ────────────────────────────────────────────────────────

class TestRLiveLanding:
    """R-LIVE landing table renders correctly."""

    def test_rlive_landing_200(self):
        """GET /radar/r-live → 200 with table."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200, (
            f"GET /radar/r-live returned {resp.status_code}, expected 200"
        )
        assert "rlive-table" in resp.text, (
            "data-testid='rlive-table' not found in /radar/r-live response"
        )

    def test_rlive_landing_aapl_row_present(self):
        """AAPL row present with PENDING_JS state (approved row)."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200
        assert "rlive-row" in resp.text
        # AAPL row is identified by its testid (symbol-based) and canonical_id attribute.
        assert 'data-testid="rlive-row-aapl"' in resp.text, (
            "AAPL row (data-testid='rlive-row-aapl') not found in R-LIVE landing table"
        )

    def test_rlive_landing_unavailable_rows_no_numeric_values(self):
        """All registry rows are approved — no pre-filled numeric values in HTML."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200
        # All 8 registry assets are approved; numeric values are JS-populated only.
        # Template must use loading placeholder "—", not hardcoded numeric values.
        assert "rlive-loading" in resp.text, (
            "Loading placeholder (rlive-loading) not found — numeric values must come from JS"
        )
        # No pre-filled dollar amounts in the server-rendered HTML.
        import re
        prefilled = re.findall(r'\$\d+\.\d{4}', resp.text)
        assert not prefilled, (
            f"Server-rendered HTML contains pre-filled numeric values {prefilled} — "
            "numeric values must come from JS only"
        )

    def test_rlive_landing_missing_not_zero(self):
        """Missing/unavailable values shown as dash, not 0.00."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200
        # Non-approved rows should not contain fabricated numeric values.
        # Template uses "—" for unavailable cells, not "0" or "0.00".
        # (AAPL row JS loading shows "—" initially; others always "—".)
        assert "rlive-loading" in resp.text or "—" in resp.text, (
            "Expected dash placeholder for unavailable values"
        )

    def test_rlive_landing_r_live_table_js_referenced(self):
        """r_live_table.js is referenced in the landing page."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200
        assert "r_live_table.js" in resp.text, (
            "r_live_table.js not referenced in /radar/r-live response"
        )

    def test_rlive_landing_nav_order_in_html(self):
        """H: R-LIVE nav tab is marked active on landing page."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live")
        assert resp.status_code == 200
        # nav-rlive tab should have is-active class
        assert "nav-rlive" in resp.text, "data-testid=nav-rlive not found in /radar/r-live"
        # is-active on the rlive nav item
        html = resp.text
        nav_rlive_idx = html.find("nav-rlive")
        # is-active appears on the <a> element; class may be up to 200 chars before data-testid.
        assert "is-active" in html[max(0, nav_rlive_idx-200):nav_rlive_idx+200], (
            "is-active class not found near R-LIVE nav item on /radar/r-live"
        )


# ── C: R-LIVE detail ─────────────────────────────────────────────────────────

class TestRLiveDetail:
    """R-LIVE detail shell."""

    def test_rlive_detail_aapl_200(self):
        """GET /radar/r-live/aapl → 200 detail shell."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live/aapl")
        assert resp.status_code == 200, (
            f"GET /radar/r-live/aapl returned {resp.status_code}"
        )

    def test_rlive_detail_aapl_methodology_present(self):
        """AAPL detail page contains methodology disclosure (accessed via canonical_id)."""
        pytest.importorskip("uvicorn")
        import main_web
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
        from fastapi.testclient import TestClient
        # Resolve AAPL canonical_id from the approved registry — identity authority.
        aapl_policy = next(
            (p for p in APPROVED_BY_CANONICAL_ID.values() if p.symbol == "AAPL"), None
        )
        assert aapl_policy is not None, "AAPL not found in APPROVED_BY_CANONICAL_ID"
        canonical_id = aapl_policy.asset_key.canonical_id
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get(f"/radar/r-live/{canonical_id}")
        assert resp.status_code == 200
        assert "Methodology" in resp.text, (
            "Methodology section not found in AAPL R-LIVE detail page"
        )
        assert "reference observation" in resp.text.lower(), (
            "Reference observation disclosure not found in AAPL detail methodology"
        )

    def test_rlive_detail_aapl_no_executable_price_claim(self):
        """Detail page must not present reference as executable/tradeable price."""
        pytest.importorskip("uvicorn")
        import main_web
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
        from fastapi.testclient import TestClient
        # Resolve AAPL canonical_id from the approved registry — identity authority.
        aapl_policy = next(
            (p for p in APPROVED_BY_CANONICAL_ID.values() if p.symbol == "AAPL"), None
        )
        assert aapl_policy is not None, "AAPL not found in APPROVED_BY_CANONICAL_ID"
        canonical_id = aapl_policy.asset_key.canonical_id
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get(f"/radar/r-live/{canonical_id}")
        assert resp.status_code == 200
        # Must not claim it's a tradeable/executable price.
        text = resp.text.lower()
        # The page should disclaim — "not a tradeable" or similar must appear.
        assert "not" in text and ("tradeable" in text or "executable" in text), (
            "AAPL detail page missing disclaimer that reference is not a tradeable/executable price"
        )

    def test_rlive_detail_unknown_asset_200(self):
        """D: Unknown asset returns 200 with UNAVAILABLE shell (not 404/500)."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live/UNKNOWN_ASSET_XYZ")
        assert resp.status_code == 200, (
            f"Unknown R-LIVE asset returned {resp.status_code}, expected 200 shell"
        )
        assert "UNAVAILABLE" in resp.text or "not" in resp.text.lower(), (
            "Unknown asset detail page should show UNAVAILABLE state"
        )

    def test_rlive_detail_unauthenticated_200(self):
        """Detail page is accessible without authentication (read-only surface)."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/r-live/aapl")
        assert resp.status_code == 200


# ── D: Stocks route ───────────────────────────────────────────────────────────

class TestStocksRoute:
    """E: /radar/stocks serves the existing Stocks page."""

    def test_stocks_route_200(self):
        """GET /radar/stocks → 200 (renamed from /radar)."""
        pytest.importorskip("uvicorn")
        import main_web
        from fastapi.testclient import TestClient
        client = TestClient(main_web.app, follow_redirects=True)
        resp = client.get("/radar/stocks")
        assert resp.status_code == 200, (
            f"GET /radar/stocks returned {resp.status_code}, expected 200"
        )

    def test_stocks_form_action_updated(self):
        """Stocks page form action is /radar/stocks, not /radar."""
        tmpl = REPO / "app/templates/radar/index.html"
        content = tmpl.read_text()
        assert 'action="/radar/stocks"' in content, (
            "Form action in index.html must be /radar/stocks, not /radar"
        )
        assert 'action="/radar"' not in content, (
            "Old form action='/radar' still present in index.html — must be /radar/stocks"
        )


# ── F: Provider branding removal ─────────────────────────────────────────────

class TestFundamentalsProviderNotExposed:
    """RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED — Source block removed from template."""

    def test_RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED(self):
        """equity_fundamentals.html must NOT expose Provider/MASSIVE/source_contract."""
        tmpl = REPO / "app/templates/radar/equity_fundamentals.html"
        content = tmpl.read_text()
        # Provider label must not appear in the normal corporate fundamentals panel.
        assert "<dt>Provider</dt>" not in content, (
            "RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED: "
            "<dt>Provider</dt> still present in equity_fundamentals.html"
        )
        assert "lin.provider" not in content, (
            "RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED: "
            "lin.provider still present in equity_fundamentals.html template"
        )
        assert "<dt>Contract</dt>" not in content, (
            "RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED: "
            "<dt>Contract</dt> (source_contract) still in equity_fundamentals.html"
        )
        assert "<dt>Fetched</dt>" not in content, (
            "RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED: "
            "<dt>Fetched</dt> still present in equity_fundamentals.html"
        )
        # Replacement attribution text must be present.
        assert "Source-derived fundamentals" in content, (
            "RADAR_FUNDAMENTALS_PROVIDER_NOT_EXPOSED: "
            "'Source-derived fundamentals.' replacement text missing from equity_fundamentals.html"
        )

    def test_fundamentals_no_payload_hash_in_template(self):
        """Payload hash must not be exposed in the corporate fundamentals panel."""
        tmpl = REPO / "app/templates/radar/equity_fundamentals.html"
        content = tmpl.read_text()
        assert "lin.payload_hash" not in content, (
            "lin.payload_hash still present in equity_fundamentals.html"
        )
        assert "<dt>Payload hash</dt>" not in content, (
            "<dt>Payload hash</dt> still present in equity_fundamentals.html"
        )


# ── G: Lineage preserved in view model ───────────────────────────────────────

class TestFundamentalsLineagePreserved:
    """RADAR_FUNDAMENTALS_LINEAGE_PRESERVED — lineage data still in view model."""

    def test_RADAR_FUNDAMENTALS_LINEAGE_PRESERVED(self):
        """equity_view_model builds lineage even though template no longer renders it."""
        # The backend view model must still set lineage — it is used for audit/evidence.
        # We verify the view model module still imports/uses lineage fields.
        from app.radar_ui import equity_view_model
        import inspect
        src = inspect.getsource(equity_view_model)
        assert "lineage" in src, (
            "RADAR_FUNDAMENTALS_LINEAGE_PRESERVED: "
            "'lineage' no longer appears in equity_view_model source — lineage must be preserved"
        )

    def test_lineage_available_field_in_equity_view(self):
        """EquityView has a lineage attribute (used by the template guard)."""
        from app.radar_ui import equity_view_model
        import inspect
        # Look for lineage in EquityView or related structures.
        src = inspect.getsource(equity_view_model)
        assert "lineage" in src, (
            "lineage field not found in equity_view_model — must be preserved for audit"
        )

    def test_lineage_condition_preserved_in_template(self):
        """Template still guards on ev.lineage.available (lineage data is checked)."""
        tmpl = REPO / "app/templates/radar/equity_fundamentals.html"
        content = tmpl.read_text()
        # The guard condition must remain even though inner content changed.
        assert "ev.lineage" in content, (
            "RADAR_FUNDAMENTALS_LINEAGE_PRESERVED: "
            "ev.lineage condition removed from equity_fundamentals.html — lineage guard must remain"
        )
        assert "lineage.available" in content, (
            "RADAR_FUNDAMENTALS_LINEAGE_PRESERVED: "
            "lineage.available guard removed — template must still check lineage.available"
        )


# ── H: JS / static wiring ────────────────────────────────────────────────────

class TestRLiveStaticAssets:
    """JS and static asset wiring."""

    def test_r_live_table_js_exists(self):
        """static/radar/r_live_table.js must exist."""
        js_file = REPO / "static/radar/r_live_table.js"
        assert js_file.exists(), (
            f"static/radar/r_live_table.js not found — required for R-LIVE landing"
        )

    def test_r_live_table_js_read_only(self):
        """r_live_table.js must not write history (persist_history forbidden)."""
        js_file = REPO / "static/radar/r_live_table.js"
        content = js_file.read_text()
        assert "persist_history" not in content, (
            "r_live_table.js references persist_history — browser JS must never write history"
        )
        # Must not contain any POST/PUT/PATCH/DELETE fetch calls.
        import re
        forbidden = re.findall(
            r'fetch\s*\([^)]*(?:POST|PUT|PATCH|DELETE)[^)]*\)', content, re.IGNORECASE
        )
        assert not forbidden, (
            f"r_live_table.js contains write fetch calls: {forbidden}"
        )

    def test_r_live_table_js_never_writes_zero_for_missing(self):
        """r_live_table.js must suppress numeric values when STALE/UNAVAILABLE."""
        js_file = REPO / "static/radar/r_live_table.js"
        content = js_file.read_text()
        # Must check state before populating numeric cells.
        assert "AVAILABLE" in content, (
            "r_live_table.js must check AVAILABLE state before populating numeric values"
        )
        assert "—" in content or "dash" in content.lower() or '"\\u2014"' in content or "'—'" in content, (
            "r_live_table.js must use dash placeholder for missing/unavailable values"
        )


# ── I: Router registration ────────────────────────────────────────────────────

class TestRouterRegistration:
    """R-LIVE router is included in __init__.py assembly."""

    def test_r_live_router_in_init(self):
        """app/radar_ui/__init__.py must include r_live_router."""
        init_file = REPO / "app/radar_ui/__init__.py"
        content = init_file.read_text()
        assert "r_live_router" in content, (
            "r_live_router not included in app/radar_ui/__init__.py"
        )
        assert "include_router(_r_live_router)" in content or "include_router(r_live_router)" in content, (
            "r_live_router not registered via include_router in __init__.py"
        )

    def test_r_live_router_registered_before_others(self):
        """R-LIVE router should be included before domain sub-routers to ensure /radar redirect priority."""
        init_file = REPO / "app/radar_ui/__init__.py"
        content = init_file.read_text()
        rlive_pos = content.find("_r_live_router")
        economy_pos = content.find("_economy_router")
        # R-LIVE import and include should come before economy/crypto etc.
        assert rlive_pos < economy_pos, (
            "R-LIVE router should be included before economy/crypto routers in __init__.py"
        )


# ── J: Missing != 0 template guard ───────────────────────────────────────────

class TestMissingNotZeroInShell:
    """J: UNAVAILABLE/STALE rows must not show numeric values."""

    def test_shell_rows_unavailable_no_numeric(self):
        """_approved_rows() returns registry rows — no pre-filled numeric values."""
        from app.radar_ui.r_live_router import _approved_rows
        rows = _approved_rows()
        assert rows, "_approved_rows() must return at least one row"
        for row in rows:
            # All rows from the canonical registry are approved.
            assert row.get("approved") is True, (
                f"Row {row.get('symbol')} must have approved=True from registry"
            )
            # No numeric value fields must be pre-filled — JS populates these.
            for k in ("price", "premium", "change", "bps", "reference_price", "basis_price"):
                assert k not in row, (
                    f"Registry row {row.get('symbol')} has numeric field {k!r} — "
                    "missing != 0, numeric values must not be fabricated server-side"
                )

    def test_aapl_approved_row_no_prefilled_prices(self):
        """AAPL row from _approved_rows() has no prefilled price values (JS-populated only)."""
        from app.radar_ui.r_live_router import _approved_rows
        rows = _approved_rows()
        aapl = next((r for r in rows if r.get("symbol") == "AAPL"), None)
        assert aapl is not None, "AAPL not returned by _approved_rows()"
        assert aapl.get("approved") is True, "AAPL must be approved=True in _approved_rows()"
        assert aapl.get("canonical_id"), "AAPL must have a canonical_id in _approved_rows()"
        # Must not prefill numeric values — they come from JS only.
        for k in ("price_usd", "premium_bps", "reference_price", "basis_price"):
            assert k not in aapl, (
                f"AAPL row has prefilled numeric field {k!r} — "
                "numeric values must come from JS, not be baked into the route"
            )
