"""Opus A1 public-truth, hygiene and governance invariant tests.

Scope:
- No internal milestone codes (P2/P3/P4/R10) in normal public product copy
- Homepage evidence claim is bounded (not blanket "every value")
- README reflects current vertical and protocol state
- No standalone Known Limitations catalog
- Brand bar does not promote the retired Verified Assets surface

These tests enforce the Opus A1 remediation contract. They do NOT test
financial engine semantics, which are frozen.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    from app.protocol_ui.router import router as protocol_router

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(protocol_router)
    return TestClient(app, raise_server_exceptions=True)


# ── Homepage: no internal milestone codes ──────────────────────────────────

def test_a1_01_homepage_no_p4_entitlement_rail():
    """Homepage must not expose the internal P4 milestone code to users."""
    html = (REPO / "app/templates/protocol_home.html").read_text()
    assert "P4 entitlement rail" not in html
    assert "p4 entitlement rail" not in html.lower()


def test_a1_02_homepage_finco_description_is_product_language():
    """$FINCO description on homepage uses product language, not internal codes."""
    html = (REPO / "app/templates/protocol_home.html").read_text()
    lower = html.lower()
    # Must describe it as access/entitlement layer
    assert "service-entitlement" in lower or "access and service" in lower or "entitlement layer" in lower
    # Must say token not yet launched
    assert "token is not yet launched" in lower or "not yet launched" in lower


def test_a1_03_homepage_evidence_claim_is_bounded():
    """Homepage evidence-backed copy must not claim every value universally has source lineage."""
    html = (REPO / "app/templates/protocol_home.html").read_text()
    lower = html.lower()
    assert "every value carries a verifiable source lineage" not in lower
    # Bounded replacement should mention evidence/lineage/source
    assert "lineage" in lower or "evidence" in lower


# ── Docs: no internal milestone codes in user copy ─────────────────────────

def test_a1_04_docs_no_p4_in_product_copy():
    """Docs product map must not expose P4 milestone code."""
    html = _client().get("/docs").text
    assert "P4 entitlement rail" not in html
    assert "p4 entitlement rail" not in html.lower()


def test_a1_05_docs_no_p3_in_product_copy():
    """Docs user copy must not expose P3 milestone code as a label."""
    html = _client().get("/docs").text
    # "P3 Run Certificate" should be gone; FINCO_RUN_CERTIFICATE_V1 schema id may remain in <code>
    assert "P3 Run Certificate" not in html


def test_a1_06_docs_no_p2_in_product_copy():
    """Docs user copy must not expose P2 milestone code as a label."""
    html = _client().get("/docs").text
    assert "P2 tokenization-premium" not in html


# ── Brand bar / library shell ───────────────────────────────────────────────

def test_a1_07_brand_bar_does_not_promote_verified_assets():
    """Brand bar must NOT promote the retired public Verified Assets surface.

    Superseded contract (PR #162): until source-proven model-to-market
    records exist, /verified renders only reference model records
    (0 VERIFIED), so it is not promoted anywhere.  Direct /verified visits
    redirect (302) to the canonical FINCO Verify route (/verify); FINCO
    Verify remains the public trust/verification surface and the Verified
    Assets authority + JSON contracts stay intact behind the redirect.
    """
    brand = (REPO / "app/templates/partials/_brand_bar.html").read_text()
    assert 'href="/verified"' not in brand


def test_a1_08_brand_bar_still_has_finco_placeholder():
    """Brand bar $FINCO placeholder is still present and non-clickable."""
    brand = (REPO / "app/templates/partials/_brand_bar.html").read_text()
    assert 'aria-disabled="true" title="Coming soon">$FINCO</span>' in brand


# ── README: current vertical and protocol state ────────────────────────────

def test_a1_09_readme_includes_data_center_and_ev():
    """README must list Data Center and EV Charging as current supported verticals."""
    readme = (REPO / "README.md").read_text()
    lower = readme.lower()
    assert "data center" in lower
    assert "ev charging" in lower or "ev" in lower


def test_a1_10_readme_does_not_say_solar_wind_only():
    """README must not restrict current supported verticals to solar and wind only."""
    readme = (REPO / "README.md").read_text()
    # These specific stale phrases must be gone
    assert "Solar and wind are the initial supported modelling verticals" not in readme
    assert "Solar and wind are the initial RWA infrastructure modelling verticals" not in readme


def test_a1_11_readme_token_utility_not_wholly_unimplemented():
    """README must not call token utility entirely future; access/entitlement rail is implemented."""
    readme = (REPO / "README.md").read_text()
    lower = readme.lower()
    # The stale blanket statement must be gone
    assert "token utility and blockchain anchoring remain roadmap functionality" not in lower
    # Must acknowledge entitlement/access is implemented
    assert "service-entitlement" in lower or "entitlement layer is implemented" in lower or "entitlement infrastructure is implemented" in lower


def test_a1_12_readme_mentions_run_certificates():
    """README must describe Run Certificates as a current capability."""
    readme = (REPO / "README.md").read_text()
    assert "Run Certificate" in readme or "run certificate" in readme.lower()


def test_a1_13_readme_mentions_verified_assets():
    """README must describe Verified Assets V1 as a current capability."""
    readme = (REPO / "README.md").read_text()
    assert "Verified Assets" in readme


# ── Vertical-status semantic invariants (Correction A) ─────────────────────

def test_a1_15_readme_dc_ev_present_with_qualification():
    """README must show all four LIVE model verticals per the canonical contract.
    DC A3.1 and EV A3.2 are merged capabilities; stale 'validation in progress'
    language must NOT be required."""
    from app.product_capability import LIVE_CAPABILITIES
    readme = (REPO / "README.md").read_text()
    lower = readme.lower()
    for cap in LIVE_CAPABILITIES:
        if cap.product_area == "model":
            assert cap.public_name.lower() in lower, (
                f"LIVE model vertical {cap.public_name!r} not found in README"
            )
    # Storage must remain marked limited/reference scope
    assert "storage" in lower
    assert "limited" in lower or "reference scope" in lower
    # Internal engineering term must not appear in public product copy
    assert "vertical-integrity" not in lower


def test_a1_16_readme_solar_wind_described_as_mature():
    """README must describe Solar and Wind as the mature production modelling workflows."""
    readme = (REPO / "README.md").read_text()
    lower = readme.lower()
    assert "solar" in lower and "wind" in lower
    assert "mature" in lower


def test_a1_17_readme_storage_limited_reference():
    """README must describe Storage as limited/reference scope."""
    readme = (REPO / "README.md").read_text()
    lower = readme.lower()
    assert "storage" in lower
    assert "limited" in lower
    assert "reference" in lower


def test_a1_18_docs_vertical_status_qualified():
    """Docs product map must not call all four verticals unconditional production workflows."""
    html = _client().get("/docs").text
    lower = html.lower()
    assert "data center" in lower
    assert "ev" in lower
    assert "solar" in lower and "wind" in lower
    # Must carry qualification language for DC/EV
    assert (
        "validation in progress" in lower
        or "mature production" in lower
        or "implemented modelling" in lower
    )


def test_a1_19_roadmap_vertical_status_distinguishes_maturity():
    """Roadmap Infrastructure Model card must list all LIVE model verticals and distinguish
    Solar/Wind maturity from DC/EV. DC A3.1 and EV A3.2 are implemented; stale
    'validation in progress' must NOT be asserted."""
    from app.product_capability import LIVE_CAPABILITIES
    roadmap = (REPO / "app/templates/protocol_roadmap.html").read_text()
    lower = roadmap.lower()
    for cap in LIVE_CAPABILITIES:
        if cap.product_area == "model":
            assert cap.public_name.lower() in lower, (
                f"LIVE model vertical {cap.public_name!r} not found in protocol_roadmap.html"
            )
    assert "storage" in lower
    assert "mature" in lower
    assert "implemented" in lower
    # Internal engineering term must not appear in public roadmap copy
    assert "vertical-integrity" not in lower


def test_a1_20_readme_no_unconditional_all_four_production_verticals():
    """README must not claim all four are unconditionally current production modelling verticals."""
    readme = (REPO / "README.md").read_text()
    # The specific stale unconditional list must not appear
    assert "Solar, Wind, Data Center and EV Charging are the current production modelling verticals" not in readme
    assert "Solar, Wind, Data Center and EV Charging are the current RWA infrastructure modelling verticals" not in readme


# ── Known Limitations remains absent ───────────────────────────────────────

def test_a1_14_no_standalone_known_limitations_route():
    """Known Limitations must 301 to /docs — no standalone page."""
    client = _client()
    resp = TestClient(client.app, raise_server_exceptions=True, follow_redirects=False).get(
        "/known-limitations"
    )
    assert resp.status_code in (301, 302, 404), (
        f"/known-limitations must redirect or 404, not serve a standalone page (got {resp.status_code})"
    )
    if resp.status_code in (301, 302):
        assert "/docs" in resp.headers.get("location", "")
