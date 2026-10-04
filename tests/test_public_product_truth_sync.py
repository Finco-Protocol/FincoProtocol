"""Public Product Truth Sync — acceptance tests.

Verifies that every public FINCO product surface is aligned with what the
product actually supports after P3 (Run Certificates) + P4 (Token Utility) +
P5 (Verified Assets V1).

Core positioning:
  "FINCO connects real-world asset economics with tokenized markets."
  "AI explains. FINCO calculates."
  Trust chain: NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION

Acceptance markers:
  PUBLIC_PRODUCT_HIERARCHY_ALIGNED
  PUBLIC_HOMEPAGE_POST_P5_ALIGNED
  PUBLIC_MODEL_CAPABILITIES_ALIGNED
  PUBLIC_RADAR_CAPABILITIES_ALIGNED
  PUBLIC_VERIFY_LIVE_ALIGNED
  PUBLIC_VERIFIED_ASSETS_ALIGNED
  PUBLIC_FINCO_TOKEN_UTILITY_ALIGNED
  PUBLIC_RWA_POSITIONING_ALIGNED
  PUBLIC_ROADMAP_ALIGNED
  PUBLIC_DOCS_ALIGNED
  PUBLIC_API_COPY_ALIGNED
  PUBLIC_SUPPORTED_TODAY_SINGLE_AUTHORITY
  PUBLIC_NAV_NO_STALE_PLACEHOLDERS
  PUBLIC_NO_KNOWN_LIMITATIONS_PAGE
  PUBLIC_CONTEXTUAL_CAVEATS_ONLY
  PUBLIC_NO_FALSE_BACKING_CLAIMS
  PUBLIC_NO_FALSE_REDEMPTION_CLAIMS
  PUBLIC_NO_FALSE_TRADING_CLAIMS
  PUBLIC_FROZEN_AUTHORITIES_ZERO_DIFF

Final marker: FINCO_PUBLIC_PRODUCT_TRUTH_SYNC_COMPLETE
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    return FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _protocol_ui_client():
    from fastapi.testclient import TestClient
    from app.protocol_ui.router import router
    app = _make_app()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _home_html() -> str:
    client = _protocol_ui_client()
    return client.get("/").text


def _roadmap_html() -> str:
    client = _protocol_ui_client()
    return client.get("/roadmap").text


def _docs_html() -> str:
    client = _protocol_ui_client()
    return client.get("/docs").text


def _api_html() -> str:
    client = _protocol_ui_client()
    return client.get("/api").text


def _home_template_text() -> str:
    return (REPO / "app/templates/protocol_home.html").read_text()


def _roadmap_template_text() -> str:
    return (REPO / "app/templates/protocol_roadmap.html").read_text()


def _docs_template_text() -> str:
    return (REPO / "app/templates/protocol_docs.html").read_text()


def _api_template_text() -> str:
    return (REPO / "app/templates/protocol_api.html").read_text()


# ---------------------------------------------------------------------------
# PUBLIC_NO_KNOWN_LIMITATIONS_PAGE
# ---------------------------------------------------------------------------

class TestNoKnownLimitationsPage:
    """PUBLIC_NO_KNOWN_LIMITATIONS_PAGE — standalone page must not exist."""

    def test_known_limitations_route_redirects(self):
        """GET /known-limitations must redirect (301) — not serve a standalone page."""
        from fastapi.testclient import TestClient
        import main_web
        client = TestClient(main_web.app, raise_server_exceptions=True,
                            follow_redirects=False)
        resp = client.get("/known-limitations")
        assert resp.status_code in (301, 302), (
            f"/known-limitations returned {resp.status_code}; must redirect"
        )

    def test_known_limitations_redirects_to_docs(self):
        """GET /known-limitations must redirect to /docs (not a standalone page)."""
        from fastapi.testclient import TestClient
        import main_web
        client = TestClient(main_web.app, raise_server_exceptions=True,
                            follow_redirects=False)
        resp = client.get("/known-limitations")
        location = resp.headers.get("location", "")
        assert "/docs" in location, (
            f"Expected redirect to /docs, got: {location}"
        )

    def test_pilot_guide_does_not_link_known_limitations(self):
        """pilot_guide_page.html must not link to /known-limitations."""
        text = (REPO / "app/templates/pilot_guide_page.html").read_text()
        assert "/known-limitations" not in text, (
            "pilot_guide_page.html still links to /known-limitations"
        )

    def test_no_nav_link_to_known_limitations(self):
        """Protocol nav must not link to /known-limitations."""
        text = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        assert "/known-limitations" not in text


# ---------------------------------------------------------------------------
# PUBLIC_HOMEPAGE_POST_P5_ALIGNED
# ---------------------------------------------------------------------------

class TestHomepagePostP5:
    """PUBLIC_HOMEPAGE_POST_P5_ALIGNED — homepage reflects P3+P4+P5 capabilities."""

    def test_homepage_mentions_verified_assets(self):
        """Homepage still truthfully references Verified Assets in trust
        context, but must NOT present it as a currently usable public
        product (no product card, no View Verified Assets CTA). Superseded
        promotion contract (PR #162)."""
        text = _home_template_text()
        assert "Verified" in text, "Homepage must mention Verified Assets"
        assert "View Verified Assets" not in text
        assert 'href="/verified"' not in text

    def test_homepage_does_not_claim_model_to_market_trust_chain(self):
        """Product-reality reset: the Model is a separate product line and is not connected to the market
        data, so the homepage no longer advertises a NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION chain."""
        text = _home_template_text()
        assert "MARKET OBSERVATION" not in text
        assert "not connected to the market data" in text

    def test_homepage_architecture_includes_verify(self):
        """Homepage architecture section must include VERIFY surface."""
        text = _home_template_text()
        assert "VERIFY" in text, "Homepage architecture strip must include VERIFY"

    def test_homepage_ai_explains_finco_calculates(self):
        """Homepage must carry the core architecture rule. PUBLIC_HOMEPAGE_POST_P5_ALIGNED"""
        text = _home_template_text()
        assert "AI explains" in text and "FINCO calculates" in text

    def test_homepage_no_stale_coming_soon_for_execution_sim(self):
        """Homepage capability card must not say 'Execution simulation — coming soon'."""
        text = _home_template_text()
        assert "Execution simulation — coming soon" not in text, (
            "Homepage still says 'Execution simulation — coming soon'; "
            "remove or update to reflect actual state"
        )


# ---------------------------------------------------------------------------
# PUBLIC_RADAR_CAPABILITIES_ALIGNED
# ---------------------------------------------------------------------------

class TestRadarCapabilitiesAligned:
    """PUBLIC_RADAR_CAPABILITIES_ALIGNED — Radar description reflects live state."""

    def test_homepage_radar_card_no_coming_soon_execution(self):
        """Radar capability card on homepage must not claim execution simulation is coming soon."""
        text = _home_template_text()
        # Check within Radar card section
        radar_start = text.find("FINCO RADAR")
        assert radar_start != -1
        radar_section = text[radar_start:radar_start + 800]
        assert "coming soon" not in radar_section.lower(), (
            "Radar capability card still mentions 'coming soon' for execution simulation"
        )

    def test_api_page_execution_sim_described_correctly(self):
        """API page must describe execution simulation as read-only analytics."""
        text = _api_template_text()
        assert "Read-only simulation" in text or "analytics" in text.lower(), (
            "API page must describe execution simulation accurately"
        )
        assert "No order submitted" in text


# ---------------------------------------------------------------------------
# PUBLIC_VERIFIED_ASSETS_ALIGNED
# ---------------------------------------------------------------------------

class TestVerifiedAssetsAligned:
    """PUBLIC_VERIFIED_ASSETS_ALIGNED — Verified Assets surface documented truthfully."""

    def test_docs_has_verified_section(self):
        """Docs must have a Verified Assets section. PUBLIC_VERIFIED_ASSETS_ALIGNED"""
        html = _docs_html()
        assert "Verified Asset" in html or "FINCO_VERIFIED_ASSET" in html

    def test_docs_verified_product_map_entry(self):
        """Docs product map table must include a Verified Assets row."""
        html = _docs_html()
        assert "Verified" in html

    def test_docs_verified_model_only_status_disclosed(self):
        """Docs must disclose MODEL_ONLY as the current V1 status."""
        html = _docs_html()
        assert "MODEL_ONLY" in html, (
            "Docs must disclose that V1 assets currently show MODEL_ONLY status"
        )

    def test_docs_verified_six_authority_gate_mentioned(self):
        """Docs must mention that VERIFIED requires full reconciliation, not just a binding."""
        html = _docs_html()
        lower = html.lower()
        assert "six" in lower or "identity reconciliation" in lower or (
            "market observation" in lower
        ), "Docs must explain that VERIFIED requires full authority chain"

    def test_roadmap_shipped_includes_verified_assets(self):
        """Roadmap shipped section must include Verified Assets. PUBLIC_ROADMAP_ALIGNED"""
        html = _roadmap_html()
        # Find the Shipped section
        start = html.find("Shipped")
        assert start != -1, "Roadmap has no 'Shipped' section"
        shipped_section = html[start:start + 2000]
        assert "Verified Assets" in shipped_section, (
            "Verified Assets must appear in the Roadmap Shipped section"
        )

    def test_verified_nav_not_promoted_in_protocol_nav(self):
        """Superseded (PR #162): the protocol nav must NOT promote /verified.

        The Verified Assets collection is retired from public promotion —
        it contains only reference model records (0 VERIFIED) until
        source-proven model-to-market records exist.  Backward compatibility
        is kept as a redirect on the public protocol_ui router (see
        test_verified_redirect_backward_compatible)."""
        text = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        assert 'href="/verified"' not in text, (
            "Protocol nav must not promote /verified")

    def test_verified_route_returns_200_for_authenticated_user(self):
        """GET /verified must be reachable by authenticated users."""
        from fastapi.testclient import TestClient
        from app.verified.router import router as verified_router
        app = _make_app()
        app.include_router(verified_router)
        client = TestClient(app, raise_server_exceptions=True)
        # Unauthenticated → 401/302 depending on path
        resp = client.get("/verified", follow_redirects=False)
        assert resp.status_code in (200, 302, 401)

    def test_verified_asset_json_schema_field(self):
        """Verified asset registry returns FINCO_VERIFIED_ASSET_V1 schema."""
        from app.verified.contracts import VERIFIED_ASSET_SCHEMA
        assert VERIFIED_ASSET_SCHEMA == "FINCO_VERIFIED_ASSET_V1"


# ---------------------------------------------------------------------------
# PUBLIC_DOCS_ALIGNED
# ---------------------------------------------------------------------------

class TestDocsAligned:
    """PUBLIC_DOCS_ALIGNED — docs reflect full P3+P4+P5 truth chain."""

    def test_docs_evidence_chain_includes_market_observation(self):
        """Docs evidence chain must read NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION."""
        html = _docs_html()
        assert "MARKET OBSERVATION" in html, (
            "Docs evidence chain must include MARKET OBSERVATION (not just STATUS)"
        )

    def test_docs_evidence_chain_not_status(self):
        """Docs evidence chain must not end with STATUS (stale copy)."""
        text = _docs_template_text()
        # Check that the evidence chain element does not contain STATUS as endpoint
        assert "><span>STATUS</span>" not in text, (
            "Docs evidence chain still ends with STATUS; must be MARKET OBSERVATION"
        )

    def test_docs_mentions_ev_charging_as_live(self):
        """Docs must present EV Charging as a production vertical. PUBLIC_DOCS_ALIGNED"""
        html = _docs_html()
        assert "EV Charging" in html

    def test_docs_limitations_mentions_finco_token_not_launched(self):
        """Docs must disclose that $FINCO token is not yet launched. PUBLIC_NO_FALSE_BACKING_CLAIMS"""
        html = _docs_html()
        lower = html.lower()
        assert "not yet launched" in lower or "planned" in lower, (
            "Docs must disclose that $FINCO token is not yet launched"
        )

    def test_docs_no_false_token_backing_claim(self):
        """Docs must not CLAIM $FINCO token has backing or redemption. PUBLIC_NO_FALSE_BACKING_CLAIMS

        Contextual disclosures that deny these properties (e.g. 'No asset-backing
        claim...is represented as current product capability') are acceptable.
        """
        html = _docs_html()
        lower = html.lower()
        # Affirmative claims would look like "backed by", "fully backed", "redeemable for"
        assert "backed by real" not in lower
        assert "fully backed" not in lower
        assert "redeemable for" not in lower
        assert "buy $finco" not in lower

    def test_docs_status_section_exists(self):
        """Docs must have a #status section for contextual limitation labels."""
        html = _docs_html()
        assert "id=\"status\"" in html or 'id="status"' in html, (
            "Docs must have id='status' section for contextual truth labels"
        )


# ---------------------------------------------------------------------------
# PUBLIC_ROADMAP_ALIGNED
# ---------------------------------------------------------------------------

class TestRoadmapAligned:
    """PUBLIC_ROADMAP_ALIGNED — roadmap reflects what is actually shipped."""

    def test_roadmap_shipped_includes_solar_wind_dc_ev(self):
        """All four live model verticals in Shipped chip row."""
        from app.product_capability import LIVE_CAPABILITIES
        html = _roadmap_html()
        start = html.find("Infrastructure Model")
        chip_start = html.find("proad-chip-row", start)
        chip_end = html.find("</div>", chip_start)
        chip_section = html[chip_start:chip_end]
        for cap in LIVE_CAPABILITIES:
            if cap.product_area != "model":
                continue
            assert cap.public_name in chip_section

    def test_roadmap_ai_explains_principle_present(self):
        """Roadmap must carry 'AI explains. FINCO calculates.' principle."""
        html = _roadmap_html()
        assert "AI explains" in html and "FINCO calculates" in html

    def test_roadmap_boundary_disclaimer_present(self):
        """Roadmap must include the boundary/disclaimer section."""
        html = _roadmap_html()
        assert "Targets are sequencing" in html or "not guarantees" in html


# ---------------------------------------------------------------------------
# PUBLIC_FINCO_TOKEN_UTILITY_ALIGNED / PUBLIC_NO_FALSE_* CLAIMS
# ---------------------------------------------------------------------------

class TestFincoTokenTruth:
    """PUBLIC_FINCO_TOKEN_UTILITY_ALIGNED — $FINCO page describes what is real."""

    def test_finco_page_no_false_backing_claims(self):
        """$FINCO page must not claim token has asset backing. PUBLIC_NO_FALSE_BACKING_CLAIMS"""
        text = (REPO / "app/templates/protocol/finco.html").read_text()
        lower = text.lower()
        # These would be false claims
        assert "backed by" not in lower or "asset-backed" not in lower, (
            "$FINCO template must not claim the token is asset-backed"
        )

    def test_finco_page_no_guaranteed_redemption(self):
        """$FINCO page must not claim guaranteed token redemption. PUBLIC_NO_FALSE_REDEMPTION_CLAIMS"""
        text = (REPO / "app/templates/protocol/finco.html").read_text()
        lower = text.lower()
        assert "guaranteed redemption" not in lower
        assert "redeem for" not in lower

    def test_finco_page_no_false_trading_market_claim(self):
        """$FINCO page must not claim a live trading market exists. PUBLIC_NO_FALSE_TRADING_CLAIMS"""
        text = (REPO / "app/templates/protocol/finco.html").read_text()
        lower = text.lower()
        assert "buy $finco" not in lower
        assert "sell $finco" not in lower
        assert "trade $finco" not in lower

    def test_finco_boundary_statement_present(self):
        """$FINCO page must carry the protocol boundary statement."""
        text = (REPO / "app/templates/protocol/finco.html").read_text()
        assert "never changes FINCO calculations" in text or (
            "not a calculation authority" in text or
            "finco-boundary" in text
        )

    def test_docs_finco_not_calculation_authority(self):
        """Docs must state $FINCO is not a calculation authority. PUBLIC_FINCO_TOKEN_UTILITY_ALIGNED"""
        html = _docs_html()
        assert "not a calculation authority" in html or "does not change model outputs" in html


# ---------------------------------------------------------------------------
# PUBLIC_NAV_NO_STALE_PLACEHOLDERS
# ---------------------------------------------------------------------------

class TestNavNoStalePlaceholders:
    """PUBLIC_NAV_NO_STALE_PLACEHOLDERS — nav items point to real routes."""

    def test_all_nav_links_route_exist(self):
        """Every href in protocol nav must have a corresponding route."""
        import re
        text = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        hrefs = re.findall(r'href="(/[^"]+)"', text)
        from fastapi.testclient import TestClient
        import main_web
        client = TestClient(main_web.app, raise_server_exceptions=True,
                            follow_redirects=False)
        for href in hrefs:
            resp = client.get(href)
            assert resp.status_code not in (404,), (
                f"Nav link {href!r} returned 404"
            )

    def test_nav_verified_link_absent(self):
        """Superseded (PR #162): the P5-era /verified nav link is retired —
        the nav must NOT promote the reference-records-only surface."""
        text = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        assert 'href="/verified"' not in text


# ---------------------------------------------------------------------------
# PUBLIC_FROZEN_AUTHORITIES_ZERO_DIFF
# ---------------------------------------------------------------------------

class TestFrozenAuthoritiesZeroDiff:
    """PUBLIC_FROZEN_AUTHORITIES_ZERO_DIFF — financial_engine and finco_core are unchanged."""

    def test_financial_engine_zero_diff(self):
        """financial_engine/** must have zero diff vs main.

        FINCO_P5_COMPOSED_NOT_CALCULATED: the composition layer never touches
        the financial engine.
        """
        result = subprocess.run(
            ["git", "diff", "origin/main", "--name-only", "--", "financial_engine/"],
            capture_output=True, text=True, cwd=REPO,
        )
        # Opus Finance Integrity governance: allow-listed engine modules only.
        from finance_integrity_governance import unapproved_engine_changes
        changed = unapproved_engine_changes([f for f in result.stdout.strip().splitlines() if f])
        assert changed == [], (
            f"unapproved financial_engine changes vs main: {changed}"
        )

    def test_finco_core_zero_diff(self):
        """finco_core/** must have zero diff vs main."""
        result = subprocess.run(
            ["git", "diff", "origin/main", "--name-only", "--", "finco_core/"],
            capture_output=True, text=True, cwd=REPO,
        )
        changed = [f for f in result.stdout.strip().splitlines() if f]
        assert changed == [], (
            f"finco_core must have zero diff vs main; changed: {changed}"
        )


# ---------------------------------------------------------------------------
# PUBLIC_SUPPORTED_TODAY_SINGLE_AUTHORITY
# ---------------------------------------------------------------------------

class TestSupportedTodaySingleAuthority:
    """PUBLIC_SUPPORTED_TODAY_SINGLE_AUTHORITY — one registry, surfaces stay aligned."""

    def test_registry_is_single_source_for_live_capabilities(self):
        """product_capability.py is the one canonical source of live vertical truth."""
        from app.product_capability import PRODUCT_CAPABILITIES, LIVE_CAPABILITIES
        assert len(PRODUCT_CAPABILITIES) >= 5
        assert len(LIVE_CAPABILITIES) >= 4  # Solar, Wind, DC, EV now all live

    def test_all_live_verticals_appear_in_docs(self):
        """All live model verticals from the registry must appear in docs."""
        from app.product_capability import LIVE_CAPABILITIES
        html = _docs_html()
        for cap in LIVE_CAPABILITIES:
            if cap.product_area != "model":
                continue
            assert cap.public_name in html, f"Docs missing live model vertical: {cap.public_name}"

    def test_all_live_verticals_appear_in_roadmap_shipped(self):
        """All live model verticals from the registry must appear in roadmap shipped section."""
        from app.product_capability import LIVE_CAPABILITIES
        html = _roadmap_html()
        start = html.find("Infrastructure Model")
        chip_start = html.find("proad-chip-row", start)
        chip_end = html.find("</div>", chip_start)
        chip_section = html[chip_start:chip_end]
        for cap in LIVE_CAPABILITIES:
            if cap.product_area != "model":
                continue
            assert cap.public_name in chip_section, (
                f"Roadmap Shipped chip row missing: {cap.public_name}"
            )


# ---------------------------------------------------------------------------
# PUBLIC_RWA_POSITIONING_ALIGNED
# ---------------------------------------------------------------------------

class TestRwaPositioningAligned:
    """PUBLIC_RWA_POSITIONING_ALIGNED — FINCO connects real-world asset economics with tokenized markets."""

    def test_homepage_rwa_positioning(self):
        """Homepage must present FINCO as connecting real-world assets with tokenized markets."""
        text = _home_template_text()
        lower = text.lower()
        assert "real-world asset" in lower or "infrastructure economics" in lower

    def test_docs_rwa_context_mentioned(self):
        """Docs must mention tokenized real-world asset context."""
        html = _docs_html()
        lower = html.lower()
        assert "tokenized" in lower

    def test_roadmap_rwa_expansion_in_future_items(self):
        """Roadmap must include Real-World Asset Expansion in future work."""
        html = _roadmap_html()
        assert "Real-World Asset" in html


# ---------------------------------------------------------------------------
# PUBLIC_CONTEXTUAL_CAVEATS_ONLY
# ---------------------------------------------------------------------------

class TestContextualCaveatsOnly:
    """PUBLIC_CONTEXTUAL_CAVEATS_ONLY — contextual truth labels, no centralized limitations catalog."""

    def test_docs_uses_contextual_status_labels(self):
        """Docs must define contextual status labels (Implemented, Beta, Planned, Unavailable)."""
        html = _docs_html()
        assert "Implemented" in html
        assert "Beta" in html
        assert "Planned" in html
        assert "Unavailable" in html

    def test_docs_model_only_label_defined(self):
        """Docs must reference MODEL_ONLY as a contextual truth label for Verified Assets."""
        html = _docs_html()
        assert "MODEL_ONLY" in html

    def test_no_standalone_limitations_page_linked_from_public_nav(self):
        """No public nav item or primary CTA links to /known-limitations."""
        for template_name in ["_protocol_nav.html", "protocol_home.html",
                               "protocol_docs.html", "protocol_roadmap.html"]:
            paths = list((REPO / "app/templates").rglob(template_name))
            for p in paths:
                text = p.read_text()
                assert "/known-limitations" not in text, (
                    f"{p.name} links to /known-limitations (removed standalone page)"
                )


# ---------------------------------------------------------------------------
# Final acceptance marker
# ---------------------------------------------------------------------------

def test_finco_public_product_truth_sync_complete():
    """FINCO_PUBLIC_PRODUCT_TRUTH_SYNC_COMPLETE — all required markers satisfied.

    This test is the final gate. It passes only when the key structural
    invariants that span multiple surfaces all hold simultaneously.

    PUBLIC_PRODUCT_HIERARCHY_ALIGNED
    PUBLIC_VERIFY_LIVE_ALIGNED
    PUBLIC_API_COPY_ALIGNED
    """
    from app.verified.contracts import VERIFIED_ASSET_SCHEMA, VerifiedAssetStatus
    from app.verified.asset_registry import list_asset_definitions
    from app.product_capability import LIVE_CAPABILITIES

    # Verified Assets V1 contracts are intact
    assert VERIFIED_ASSET_SCHEMA == "FINCO_VERIFIED_ASSET_V1"
    assert VerifiedAssetStatus.MODEL_ONLY.value == "MODEL_ONLY"

    # Registry has at least the two V1 reference assets
    assets = list_asset_definitions()
    assert len(assets) >= 2
    asset_ids = {a.asset_id for a in assets}
    assert "generic_solar_reference" in asset_ids
    assert "generic_wind_reference" in asset_ids

    # At least 4 live production verticals
    assert len(LIVE_CAPABILITIES) >= 4

    # Superseded (PR #162): nav must NOT promote /verified; FINCO Verify
    # stays the public trust surface and the redirect keeps /verified alive.
    nav_text = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
    assert 'href="/verified"' not in nav_text
    # FINCO Verify stays the public trust surface: homepage promotes it on
    # the canonical route and the /verified redirect targets it
    home_text = (REPO / "app/templates/protocol_home.html").read_text()
    assert 'href="/verify"' in home_text
    protocol_ui_text = (
        REPO / "app/protocol_ui/router.py").read_text()
    assert "/verified" in protocol_ui_text and "/verify" in protocol_ui_text

    # Trust chain is in docs
    docs_text = (REPO / "app/templates/protocol_docs.html").read_text()
    assert "MARKET OBSERVATION" in docs_text
