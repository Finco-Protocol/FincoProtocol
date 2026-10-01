"""Public Verified Assets surface cleanup — focused regression.

The public Verified Assets product surface is retired from the FINCO UX:

  - primary navigation no longer links to /verified;
  - the homepage no longer promotes Verified Assets; the VERIFY protocol
    item points at the canonical FINCO Verify page;
  - direct GET /verified redirects (302) to the canonical FINCO Verify
    page, registered before the app.verified router so first-match wins;
  - the canonical FINCO Verify page stays reachable;
  - app/verified/** has ZERO diff — all verification authority, JSON
    contracts and the verified router module remain intact;
  - PRODUCTION verified asset count remains zero and the Generic
    Solar/Wind reference records are NOT silently labelled VERIFIED
    (they keep their MODEL_ONLY-style truth).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BASELINE_MAIN = "origin/main"


def _public_ui_client() -> TestClient:
    """The protocol_ui router exactly as mounted in main_web (before the
    app.verified router), so /verified first-match behaviour is real."""
    from app.protocol_ui.router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _homepage_templates() -> tuple[str, str]:
    nav = (ROOT / "app/templates/partials/_protocol_nav.html").read_text(encoding="utf-8")
    home = (ROOT / "app/templates/protocol_home.html").read_text(encoding="utf-8")
    brand = (ROOT / "app/templates/partials/_brand_bar.html").read_text(encoding="utf-8")
    return nav, home, brand


# ── Navigation / homepage promotion removed ──────────────────────────────────

def test_primary_nav_no_longer_links_verified():
    nav, _, _ = _homepage_templates()
    assert 'href="/verified"' not in nav
    assert "Verified" not in nav


def test_brand_bar_no_longer_links_verified():
    _, _, brand = _homepage_templates()
    assert 'href="/verified"' not in brand


def test_homepage_no_longer_promotes_verified_assets():
    _, home, _ = _homepage_templates()
    assert 'href="/verified"' not in home
    # the dedicated Verified Assets product card is gone
    assert "View Verified Assets" not in home
    assert 'class="proto-arch__product-name">Verified Assets<' not in home
    # FINCO Verify remains the promoted verification/trust surface, now on
    # the canonical route
    assert 'href="/protocol/verify"' in home
    assert "<strong>VERIFY</strong>" in home


# ── GET /verified redirect + canonical Verify reachability ───────────────────

def test_get_verified_redirects_to_canonical_verify():
    client = _public_ui_client()
    response = client.get("/verified")
    assert response.status_code == 302
    assert response.headers["location"] == "/protocol/verify"


def test_canonical_finco_verify_route_registered():
    """The canonical FINCO Verify page exists on the same public router and
    is reachable (authenticated contract is covered by its own suite; here
    we prove route presence, not auth semantics)."""
    from app.protocol_ui import router as protocol_ui_router
    paths = {route.path for route in protocol_ui_router.router.routes}
    assert "/verify" in paths


def test_verified_redirect_wins_over_verified_router():
    """Mount BOTH routers exactly as main_web.py does (protocol_ui first,
    app.verified second): the redirect still wins first-match, proving the
    real integration order hides the surface without deleting the module."""
    from app.protocol_ui.router import router as public_router
    from app.verified.router import router as verified_router
    app = FastAPI()
    app.include_router(public_router)
    app.include_router(verified_router)
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    response = client.get("/verified")
    assert response.status_code == 302
    assert response.headers["location"] == "/protocol/verify"


# ── app/verified/** frozen ────────────────────────────────────────────────────

def test_app_verified_package_has_zero_diff_vs_main():
    """app/verified/** — verification authority, registry, composer, status
    display and the verified router module — is byte-identical to main."""
    result = subprocess.run(
        ["git", "diff", BASELINE_MAIN, "--", "app/verified/"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "", result.stdout


def test_verified_router_module_still_present_with_all_contracts():
    """The route module is not deleted: JSON endpoints and the internal
    index handler remain for authority/compatibility consumers."""
    from app.verified import router as verified_router
    paths = {route.path for route in verified_router.router.routes}
    assert "/verified" in paths                      # original route intact
    assert "/verified/{asset_id}.json" in paths
    assert "/verified/{asset_id}" in paths


# ── Verified count zero; references not labelled VERIFIED ────────────────────

def test_production_verified_asset_count_remains_zero():
    from app.verified.asset_registry import list_asset_definitions
    from app.verified.router import _load_verified_asset
    def _status(record) -> str:
        status = record["status"]
        return status["value"] if isinstance(status, dict) else str(
            getattr(status, "value", status))

    verified = [
        asset_def.asset_id
        for asset_def in list_asset_definitions()
        if _status(_load_verified_asset(asset_def.asset_id)["record"]) == "VERIFIED"
    ]
    assert verified == []


def test_reference_models_not_silently_labelled_verified():
    """Generic Solar/Wind reference records keep their truthful
    non-VERIFIED status (reference model != Verified Asset)."""
    from app.verified.asset_registry import list_asset_definitions
    from app.verified.router import _load_verified_asset
    records = {
        asset_def.asset_id: _load_verified_asset(asset_def.asset_id)["record"]
        for asset_def in list_asset_definitions()
    }
    solar = records.get("generic_solar_reference")
    wind = records.get("generic_wind_reference")
    assert solar is not None and wind is not None
    for record in (solar, wind):
        status = record["status"]
        status_value = status["value"] if isinstance(status, dict) else str(
            getattr(status, "value", status))
        assert status_value != "VERIFIED"
