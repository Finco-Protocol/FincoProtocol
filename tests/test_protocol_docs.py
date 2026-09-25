"""FINCO product documentation surface regression tests.

Scope:
- GET /docs/start public product documentation page
- Docs navigation activation in protocol nav + Model brand bar
- reviewed content boundaries from the Docs review draft
- temporary route separation from FastAPI's current /docs Swagger route

No financial, Model, Radar or API economic authority is changed by this suite.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    from app.protocol_ui.router import router as protocol_router

    app = FastAPI()
    app.include_router(protocol_router)
    return TestClient(app, raise_server_exceptions=True)


def test_docs01_product_docs_route_returns_200():
    client = _client()
    response = client.get("/docs/start")
    assert response.status_code == 200
    assert "FINCO Documentation" in response.text


def test_docs02_docs_nav_is_live_and_active():
    client = _client()
    html = client.get("/docs/start").text
    assert 'href="/docs/start"' in html
    assert 'aria-current="page"' in html
    assert ">\n        Docs\n      </a>" in html


def test_docs03_docs_is_not_a_placeholder_anymore():
    nav = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
    assert 'href="/docs/start"' in nav
    assert "Docs\n        <span class=\"proto-nav__soon\"" not in nav
    assert "Roadmap" in nav and "$FINCO" in nav
    assert "proto-nav__link--placeholder" in nav


def test_docs04_model_brand_bar_links_to_product_docs():
    brand = (REPO / "app/templates/partials/_brand_bar.html").read_text()
    assert 'href="/docs/start">Docs</a>' in brand
    assert 'aria-disabled="true" title="Coming soon">Roadmap</span>' in brand
    assert 'aria-disabled="true" title="Coming soon">$FINCO</span>' in brand


def test_docs05_task_first_start_here_content_present():
    client = _client()
    html = client.get("/docs/start").text
    for phrase in (
        "Model an asset",
        "Read market intelligence",
        "Understand the evidence",
        "Use FINCO programmatically",
        "A first 10-minute walkthrough",
    ):
        assert phrase in html


def test_docs06_working_vs_last_run_boundary_present():
    html = _client().get("/docs/start").text
    assert "Working" in html
    assert "Last Run" in html
    assert "last committed deterministic calculation authority" in html


def test_docs07_model_reference_scope_is_truthful():
    html = _client().get("/docs/start").text
    assert "Solar and Wind" in html
    assert "synthetic product references" in html
    assert "not market benchmarks" in html
    assert "Storage remains limited/reference scope" in html


def test_docs08_radar_domains_and_readonly_boundary_present():
    html = _client().get("/docs/start").text
    for phrase in ("Stocks", "Crypto", "Economy", "Stablecoin", "Perpetual", "Tokenized RWA"):
        assert phrase in html
    assert "no order is submitted" in html.lower()
    assert "No custody, wallet signing or order submission" in html


def test_docs09_verify_not_reintroduced_into_product_nav():
    html = _client().get("/docs/start").text
    assert 'href="/verify"' not in html
    assert "non-discoverable product surface" in html


def test_docs10_api_beta_contract_present():
    html = _client().get("/docs/start").text
    for fragment in (
        "/api/v1",
        "/model/references",
        "/preview",
        "/run",
        "/radar/assets",
        "execution-simulation",
    ):
        assert fragment in html
    assert "The API contract is still Beta" in html


def test_docs11_planned_token_does_not_claim_live_utility():
    html = _client().get("/docs/start").text
    assert "$FINCO" in html
    assert "token remains planned" in html.lower()
    assert "not a calculation authority" in html
    forbidden = ("staking is live", "guaranteed yield", "dividend rights", "token contract:")
    for phrase in forbidden:
        assert phrase not in html.lower()


def test_docs12_product_docs_have_no_provider_branding():
    html = _client().get("/docs/start").text
    for provider in ("CoinGecko", "DefiLlama", "Hyperliquid", "FRED", "Massive"):
        assert provider not in html


def test_docs13_docs_css_has_mobile_breakpoints_and_no_page_overflow_hack():
    css = (REPO / "static/css/protocol-docs.css").read_text()
    assert "@media (max-width: 620px)" in css
    assert "@media (max-width: 420px)" in css
    assert "overflow-x: hidden" not in css


def test_docs14_current_swagger_route_remains_separate_for_staging():
    """Until the API route-foundation change lands, product docs deliberately use
    /docs/start so the web app's existing FastAPI /docs route is not shadowed.
    """
    client = _client()
    swagger = client.get("/docs")
    product = client.get("/docs/start")
    assert swagger.status_code == 200
    assert "swagger" in swagger.text.lower()
    assert "FINCO Documentation" in product.text
    assert "FINCO Documentation" not in swagger.text
