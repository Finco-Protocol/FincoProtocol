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

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


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
    assert 'href="/verify"' in home
    assert "<strong>VERIFY</strong>" in home


# ── GET /verified redirect + canonical Verify reachability ───────────────────

def test_get_verified_redirects_to_canonical_verify():
    client = _public_ui_client()
    response = client.get("/verified")
    assert response.status_code == 302
    assert response.headers["location"] == "/verify"


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
    assert response.headers["location"] == "/verify"


# ── app/verified/** frozen ────────────────────────────────────────────────────

def test_app_verified_semantic_frozen_authority_intact():
    """Semantic frozen-authority proof for app/verified/** — working tree
    only, NO Git commit-ancestry dependency (GitHub Public Safety uses a
    shallow checkout where HEAD~1 / origin/main may not exist; source-control
    ZERO DIFF for app/verified/** is instead asserted by the PR/full-history
    review diff, reported separately from pytest).

    Proves the preserved semantic contracts:
      1. the app.verified router module still exists;
      2-4. the original /verified route family remains registered there
           (/verified, /verified/{asset_id}, /verified/{asset_id}.json);
      5. the production verified asset count remains zero;
      6-7. Generic Solar / Generic Wind references remain != VERIFIED;
      8. the FINCO_VERIFIED_ASSET_V1 contract/schema remains present;
      9. the public protocol_ui redirect does not mutate the verified
         registry, composer or status authority (its handler body performs
         only a redirect).
    """
    # 1. router module exists with its authority imports intact
    from app.verified import router as verified_router
    assert verified_router is not None

    # 2-4. original route family still registered in app.verified
    paths = {route.path for route in verified_router.router.routes}
    assert "/verified" in paths
    assert "/verified/{asset_id}" in paths
    assert "/verified/{asset_id}.json" in paths

    # 5-7. production verified count zero; references not VERIFIED
    from app.verified.asset_registry import list_asset_definitions
    from app.verified.router import _load_verified_asset

    def _status_value(record) -> str:
        status = record["status"]
        return status["value"] if isinstance(status, dict) else str(
            getattr(status, "value", status))

    statuses = {
        asset_def.asset_id: _status_value(
            _load_verified_asset(asset_def.asset_id)["record"])
        for asset_def in list_asset_definitions()
    }
    assert statuses
    assert not any(value == "VERIFIED" for value in statuses.values())
    assert statuses.get("generic_solar_reference") != "VERIFIED"
    assert statuses.get("generic_wind_reference") != "VERIFIED"

    # 8. schema contract unchanged
    from app.verified.contracts import VERIFIED_ASSET_SCHEMA, VerifiedAssetStatus
    assert VERIFIED_ASSET_SCHEMA == "FINCO_VERIFIED_ASSET_V1"
    assert VerifiedAssetStatus.MODEL_ONLY.value == "MODEL_ONLY"

    # 9. the public redirect handler performs ONLY a redirect — it never
    #    touches the registry, composer or status authority
    import inspect
    from app.protocol_ui import router as protocol_ui_router
    source = inspect.getsource(
        protocol_ui_router.verified_assets_redirect)
    for forbidden in ("_load_verified_asset", "_load_all_verified_assets",
                      "asset_registry", "composer", "TemplateResponse"):
        assert forbidden not in source, forbidden
    assert 'RedirectResponse(url="/verify", status_code=302)' in source


def test_get_verified_real_app_redirect_follow_reaches_verify():
    """Real-app integration regression on the actual main_web.app mount
    order (protocol_ui router before the app.verified router):

      - GET /verified returns the intended 302 redirect to /verify;
      - following the redirect reaches the canonical FINCO Verify route
        contract (the deterministic public validation corpus page) and
        never a 404;
      - /verify keeps its existing canonical auth contract (unauthenticated
        request redirects to /login — unchanged by this cleanup);
      - no duplicate Verify route is registered.
    """
    import main_web
    client = TestClient(main_web.app, raise_server_exceptions=False,
                        follow_redirects=False)

    redirect = client.get("/verified")
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "/verify"

    # topology: exactly ONE canonical Verify route; /verified appears on
    # BOTH routers (public redirect first, original authority route second)
    # but the FIRST match — what a request hits — is the redirect handler.
    live_routes = [r for r in main_web.app.routes
                   if getattr(r, "path", "") in ("/verified", "/verify")]
    verify_routes = [r for r in live_routes if r.path == "/verify"]
    verified_routes = [r for r in live_routes if r.path == "/verified"]
    assert len(verify_routes) == 1  # no duplicate Verify route invented
    assert len(verified_routes) == 2
    assert verified_routes[0].endpoint.__name__ == "verified_assets_redirect"
    assert verified_routes[1].endpoint.__name__ == "verified_index"  # intact
    assert "/protocol/verify" not in {
        getattr(r, "path", None) for r in main_web.app.routes}

    # follow the redirect in the REAL app: unauthenticated /verify keeps its
    # canonical contract (redirect to /login), never a 404
    verify_resp = client.get("/verify")
    assert verify_resp.status_code != 404
    assert verify_resp.status_code in (200, 302)
    if verify_resp.status_code == 302:
        assert verify_resp.headers["location"] == "/login"

    # and following through with an authenticated session reaches the real
    # Verify page contract (200 with the deterministic corpus surface)
    from app.auth import COOKIE_NAME, create_session_token, make_session_cookie
    admin_cookie = make_session_cookie(create_session_token())["value"]
    page = client.get("/verify", cookies={COOKIE_NAME: admin_cookie})
    assert page.status_code == 200
    assert "FINCO" in page.text


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
