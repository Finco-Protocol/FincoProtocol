"""Focused regression tests for the public FINCO Roadmap surface."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    from app.protocol_ui.router import router as protocol_router

    app = FastAPI()
    app.include_router(protocol_router)
    return TestClient(app, raise_server_exceptions=True)


def test_roadmap_route_is_public_and_active():
    response = _client().get("/roadmap")
    assert response.status_code == 200
    assert "FINCO Roadmap" in response.text
    assert 'href="/roadmap"' in response.text
    assert 'aria-current="page"' in response.text


def test_roadmap_release_baseline_and_quarters():
    html = _client().get("/roadmap").text
    for phrase in (
        "Solar",
        "Wind",
        "Data Center",
        "EV Charging",
        "Q4 2026",
        "FINCO Signals",
        "Wallet Identity",
        "On-chain Verify",
        "Q1 2027",
        "FINCO Fair Value",
        "Fundamental Gap",
        "Tokenization Premium",
        "FINCO Agent Alpha",
    ):
        assert phrase in html


def test_roadmap_model_sales_track_is_explicit():
    html = _client().get("/roadmap").text
    for phrase in (
        "Institutional Modelling",
        "Institutional Model Runs",
        "Advanced Project Finance",
        "Scenario Control",
        "Institutional Reporting",
        "Enterprise Modelling Platform",
        "Team Workspaces &amp; Approvals",
        "Portfolio Modelling",
        "Advanced Financing Structures",
        "Audit &amp; Model Governance",
    ):
        assert phrase in html


def test_roadmap_future_items_are_targets_not_guarantees():
    html = _client().get("/roadmap").text
    assert "Target" in html
    assert "Targets are sequencing, not guarantees." in html
    assert "does not mean a token, financial product, investment return or launch date is guaranteed" in html
    assert "do not imply bank, audit or third-party certification" in html


def test_roadmap_keeps_finco_as_only_placeholder():
    nav = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
    brand = (REPO / "app/templates/partials/_brand_bar.html").read_text()
    assert 'href="/roadmap"' in nav
    assert 'href="/roadmap">Roadmap</a>' in brand
    assert "$FINCO" in nav and "$FINCO" in brand
    assert "Coming soon\">Roadmap" not in nav


def test_roadmap_css_has_mobile_breakpoints_without_overflow_hack():
    css = (REPO / "static/css/protocol-roadmap.css").read_text()
    assert ".proad-model-track__grid" in css
    assert "@media (max-width: 620px)" in css
    assert "@media (max-width: 420px)" in css
    assert "overflow-x: hidden" not in css
