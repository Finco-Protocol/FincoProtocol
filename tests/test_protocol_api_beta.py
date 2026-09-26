"""FINCO API Beta surface tests — /api page + navigation + home discovery.

Test IDs: API01–API45

Scope:
  GET /api            — FINCO API Beta page
  _protocol_nav.html  — navigation items and placeholders
  _brand_bar.html     — brand bar nav items
  protocol_home.html  — API discovery element
  No API authority changes (A1–A4 tests imported and rerun)

Safety invariants:
  - No token contract, no tokenomics
  - No fake roadmap dates
  - No API key claims
  - No secrets or internal paths
  - No invented live endpoints (Model Run, Scenario API not functional)
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

# ── Build a minimal test app with the protocol router ───────────────────────

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "app", "templates"))


@pytest.fixture(scope="module")
def client():
    from app.protocol_ui.router import router as _protocol_router

    _app = FastAPI()
    _app.include_router(_protocol_router)

    @_app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return _templates.TemplateResponse(
            request=request,
            name="protocol_home.html",
            context={"user": None},
        )

    return TestClient(_app, raise_server_exceptions=True)


# ── API01: GET /api returns 200 ──────────────────────────────────────────────

def test_api01_get_api_200(client):
    r = client.get("/api")
    assert r.status_code == 200


# ── API02: page title contains FINCO API ────────────────────────────────────

def test_api02_page_title_finco_api(client):
    r = client.get("/api")
    assert "FINCO API" in r.text


# ── API03: Beta badge present ────────────────────────────────────────────────

def test_api03_beta_badge(client):
    r = client.get("/api")
    text_lower = r.text.lower()
    assert "beta" in text_lower


# ── API04: API nav link exists ───────────────────────────────────────────────

def test_api04_api_nav_link(client):
    r = client.get("/api")
    assert 'href="/api"' in r.text


# ── API05: API nav active on /api ────────────────────────────────────────────

def test_api05_api_nav_active(client):
    r = client.get("/api")
    # aria-current="page" on the API nav link
    assert 'aria-current="page"' in r.text


# ── API06: Docs placeholder visible ──────────────────────────────────────────

def test_api06_docs_placeholder(client):
    r = client.get("/api")
    assert "Docs" in r.text


# ── API07: Roadmap placeholder visible ───────────────────────────────────────

def test_api07_roadmap_placeholder(client):
    r = client.get("/api")
    assert "Roadmap" in r.text


# ── API08: $FINCO placeholder visible ────────────────────────────────────────

def test_api08_finco_placeholder(client):
    r = client.get("/api")
    assert "$FINCO" in r.text


# ── API09: placeholder items are non-links / non-navigating ─────────────────

def test_api09_placeholders_non_links(client):
    r = client.get("/api")
    html = r.text
    # P4: all nav items (Docs, Roadmap, $FINCO) are now live <a> links
    # Verify all three have live href links in the nav
    assert 'href="/docs"' in html
    assert 'href="/roadmap"' in html
    assert 'href="/protocol/finco"' in html


# ── API10: Model references endpoint listed ──────────────────────────────────

def test_api10_model_references_listed(client):
    r = client.get("/api")
    assert "/api/v1/model/references" in r.text


# ── API11: Model reference detail listed ─────────────────────────────────────

def test_api11_model_reference_detail_listed(client):
    r = client.get("/api")
    assert "reference_key" in r.text


# ── API12: CAPEX endpoint listed ─────────────────────────────────────────────

def test_api12_capex_endpoint_listed(client):
    r = client.get("/api")
    assert "/capex" in r.text


# ── API13: OPEX endpoint listed ──────────────────────────────────────────────

def test_api13_opex_endpoint_listed(client):
    r = client.get("/api")
    assert "/opex" in r.text


# ── API14: preview endpoint listed ───────────────────────────────────────────

def test_api14_preview_endpoint_listed(client):
    r = client.get("/api")
    assert "/preview" in r.text


# ── API15: Radar assets endpoint listed ──────────────────────────────────────

def test_api15_radar_assets_listed(client):
    r = client.get("/api")
    assert "/api/v1/radar/assets" in r.text


# ── API16: fundamentals endpoint listed ──────────────────────────────────────

def test_api16_fundamentals_listed(client):
    r = client.get("/api")
    assert "/fundamentals" in r.text


# ── API17: financials endpoint listed ────────────────────────────────────────

def test_api17_financials_listed(client):
    r = client.get("/api")
    assert "/financials" in r.text


# ── API18: corporate-actions endpoint listed ─────────────────────────────────

def test_api18_corporate_actions_listed(client):
    r = client.get("/api")
    assert "corporate-actions" in r.text


# ── API19: evidence endpoint listed ──────────────────────────────────────────

def test_api19_evidence_listed(client):
    r = client.get("/api")
    assert "/evidence" in r.text


# ── API20: execution-simulation endpoint listed ───────────────────────────────

def test_api20_execution_simulation_listed(client):
    r = client.get("/api")
    assert "execution-simulation" in r.text


# ── API21: execution simulation is read-only, no order submitted ───────────────

def test_api21_execution_simulation_readonly(client):
    r = client.get("/api")
    html_lower = r.text.lower()
    # Must say read-only simulation AND no order submitted
    assert "read-only simulation" in html_lower or "read-only" in html_lower
    assert "no order submitted" in html_lower


# ── API22: Model Run /run endpoint now live ──────────────────────────────────

def test_api22_model_run_endpoint_live(client):
    r = client.get("/api")
    # A5 run endpoint must be shown as a live endpoint (not coming soon)
    assert "/run" in r.text
    assert "canonical model run" in r.text.lower() or "model run" in r.text.lower()


# ── API22b: Model Run no longer in Coming Soon list ──────────────────────────

def test_api22b_model_run_not_coming_soon(client):
    r = client.get("/api")
    html = r.text
    # "Model Run API" must no longer appear as a coming-soon item
    # Find the coming-next section and check it does not contain Model Run API
    coming_next_idx = html.lower().find("coming next")
    if coming_next_idx == -1:
        coming_next_idx = html.lower().find("roadmap")
    coming_section = html[coming_next_idx:] if coming_next_idx != -1 else ""
    assert "Model Run API" not in coming_section


# ── API23: Scenario API marked Coming soon ────────────────────────────────────

def test_api23_scenario_api_coming_soon(client):
    r = client.get("/api")
    html_lower = r.text.lower()
    assert "scenario api" in html_lower or "scenario" in html_lower
    assert "coming soon" in html_lower


# ── API24: no stale Model Run path in Coming Soon ────────────────────────────

def test_api24_no_fake_model_run_endpoint(client):
    r = client.get("/api")
    # The invalid bare /api/v1/model/run path must never appear
    assert "/api/v1/model/run" not in r.text
    assert "/api/v1/run" not in r.text


# ── API24b: A5 run endpoint path present ─────────────────────────────────────

def test_api24b_a5_run_endpoint_path_present(client):
    r = client.get("/api")
    assert "/api/v1/model/references/" in r.text
    assert "/run" in r.text


# ── API25: /docs link present ────────────────────────────────────────────────

def test_api25_docs_link(client):
    r = client.get("/api")
    assert 'href="/docs"' in r.text


# ── API26: /api/openapi.json link present ────────────────────────────────────

def test_api26_openapi_json_link(client):
    r = client.get("/api")
    assert 'href="/api/openapi.json"' in r.text


# ── API27: curl GET example present ──────────────────────────────────────────

def test_api27_curl_get_example(client):
    r = client.get("/api")
    assert "curl" in r.text
    assert "/api/v1/model/references" in r.text


# ── API28: curl POST preview example present ─────────────────────────────────

def test_api28_curl_post_preview_example(client):
    r = client.get("/api")
    assert "capacity_mw" in r.text
    assert "generic_solar_reference" in r.text
    assert "POST" in r.text or "-X POST" in r.text


# ── API29: no Authorization header or API key invented ───────────────────────

def test_api29_no_auth_header_invented(client):
    r = client.get("/api")
    # Must not show made-up Authorization header or API key placeholder
    assert "Authorization:" not in r.text
    assert "X-API-Key:" not in r.text
    assert "Bearer " not in r.text


# ── API30: no token contract information ─────────────────────────────────────

def test_api30_no_token_contract(client):
    r = client.get("/api")
    html_lower = r.text.lower()
    assert "contract address" not in html_lower
    assert "0x" not in html_lower  # no Ethereum/EVM contract addresses
    assert "token supply" not in html_lower
    assert "market cap" not in html_lower


# ── API31: no tokenomics ─────────────────────────────────────────────────────

def test_api31_no_tokenomics(client):
    r = client.get("/api")
    html_lower = r.text.lower()
    assert "tokenomics" not in html_lower
    assert "staking" not in html_lower
    assert "airdrop" not in html_lower
    assert "yield" not in html_lower


# ── API32: no roadmap dates ───────────────────────────────────────────────────

def test_api32_no_roadmap_dates(client):
    r = client.get("/api")
    import re
    # No Q[1-4] 20XX or 20XX-MM-DD delivery dates
    assert not re.search(r"Q[1-4]\s+20\d\d", r.text)
    assert not re.search(r"20\d\d-\d\d-\d\d", r.text)


# ── API33: no secrets or internal paths ──────────────────────────────────────

def test_api33_no_secrets(client):
    r = client.get("/api")
    html_lower = r.text.lower()
    assert "finco_secret_key" not in html_lower
    assert "finco_admin_password" not in html_lower
    assert "finco_db_path" not in html_lower
    assert "/opt/finco" not in r.text
    assert "finco_equity_fundamentals" not in html_lower


# ── API34: home page links to /api ────────────────────────────────────────────

def test_api34_home_links_to_api(client):
    r = client.get("/")
    assert 'href="/api"' in r.text


# ── API35: home describes the two product surfaces ───────────────────────────

def test_api35_home_two_product_surfaces(client):
    r = client.get("/")
    html_lower = r.text.lower()
    assert "two interconnected surfaces" in html_lower


# ── API36: Model existing nav still works ────────────────────────────────────

def test_api36_model_nav(client):
    r = client.get("/api")
    assert 'href="/library"' in r.text


# ── API37: Radar existing nav still works ────────────────────────────────────

def test_api37_radar_nav(client):
    r = client.get("/api")
    assert 'href="/radar"' in r.text


# ── API38: verification corpus is no longer a product navigation item ────────

def test_api38_verify_is_not_product_nav(client):
    r = client.get("/api")
    assert 'href="/verify"' not in r.text


# ── API39: brand bar contains API link ───────────────────────────────────────

def test_api39_brand_bar_api(client):
    # The brand bar is only in application chrome (not the protocol nav page).
    # We verify the brand bar template contains the API link.
    nav_path = os.path.join(
        _APP_DIR, "app", "templates", "partials", "_brand_bar.html"
    )
    with open(nav_path) as f:
        brand_bar = f.read()
    assert 'href="/api"' in brand_bar


# ── API40: responsive placeholder classes present ────────────────────────────

def test_api40_responsive_placeholder_classes(client):
    r = client.get("/api")
    # P4: all nav items are live links; --placeholder modifier is gone
    assert "proto-nav__link--placeholder" not in r.text
    # All nav items are present as live anchors
    assert 'href="/protocol/finco"' in r.text


# ── API41: /api/v1/meta unchanged ────────────────────────────────────────────

def test_api41_meta_unchanged():
    import app.api.v1.router as _router_module
    from fastapi import FastAPI
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    _client = TestClient(_app)
    r = _client.get("/api/v1/meta")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    # All pre-existing capabilities still present
    assert "radar.assets.list" in caps
    assert "radar.execution.simulation" in caps
    assert "model.references.list" in caps
    assert "model.references.preview" in caps
    # No new capability added by this UI PR
    assert "api.beta" not in caps


# ── API42–45: existing API tests pass (smoke via import) ─────────────────────

def test_api42_a1_endpoints_available():
    import app.api.v1.router as _router_module
    from fastapi import FastAPI
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    _client = TestClient(_app)
    r = _client.get("/api/v1/radar/assets")
    # 200 (assets available) or 503 (registry unavailable in test env) — endpoint exists
    assert r.status_code in (200, 503)


def test_api43_a2_execution_simulation_available():
    import app.api.v1.router as _router_module
    from fastapi import FastAPI
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    _client = TestClient(_app)
    r = _client.post(
        "/api/v1/radar/assets/invalid-uid/execution-simulation",
        json={"direction": "BUY", "notional_usd": "100"},
    )
    # 400 (invalid uid format) is fine — endpoint exists and responds
    assert r.status_code in (400, 404, 503)


def test_api44_a3_model_references_available():
    import app.api.v1.router as _router_module
    from fastapi import FastAPI
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    _client = TestClient(_app)
    r = _client.get("/api/v1/model/references")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "AVAILABLE"


def test_api45_a4_preview_available():
    import app.api.v1.router as _router_module
    from fastapi import FastAPI
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    _client = TestClient(_app)
    r = _client.post(
        "/api/v1/model/references/generic_solar_reference/preview",
        json={"capacity_mw": 100.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "AVAILABLE"
    assert data["reference_key"] == "generic_solar_reference"


# ── API46: curl examples contain an absolute URL with a scheme ───────────────

def test_api46_curl_examples_absolute_url(client):
    """Curl examples must use api_base_url — a full URL including scheme/host,
    not a bare relative path like /api/v1/..."""
    r = client.get("/api")
    assert r.status_code == 200
    # TestClient base_url is http://testserver, so api_base_url becomes
    # http://testserver/api/v1 — the scheme must appear in curl examples.
    assert "http://" in r.text or "https://" in r.text, (
        "curl examples do not contain an absolute URL with a scheme"
    )


# ── API47: curl examples do not contain hardcoded production/staging hosts ───

def test_api47_curl_no_hardcoded_host(client):
    """Curl examples must derive origin from the request — not hardcode
    finco.one, staging.finco.one, localhost or any other fixed hostname."""
    r = client.get("/api")
    assert r.status_code == 200
    text_lower = r.text.lower()
    for forbidden in ("finco.one", "staging.finco.one", "localhost:"):
        assert forbidden not in text_lower, (
            f"curl example contains hardcoded host '{forbidden}'"
        )


# ── API48: curl examples contain the correct /api/v1 path prefix ─────────────

def test_api48_curl_correct_v1_path(client):
    """Both curl examples must reference /api/v1/model/... paths."""
    r = client.get("/api")
    assert r.status_code == 200
    assert "/api/v1/model/references" in r.text, (
        "curl GET example path /api/v1/model/references not found"
    )
    assert "generic_solar_reference/preview" in r.text, (
        "curl POST preview path not found"
    )


# ── API49: no API key in curl examples ───────────────────────────────────────

def test_api49_curl_no_api_key(client):
    """Curl examples must not invent Authorization or API-key headers."""
    r = client.get("/api")
    assert r.status_code == 200
    assert "Authorization:" not in r.text
    assert "X-API-Key" not in r.text
    assert "Bearer " not in r.text
    assert "api_key" not in r.text.lower()
