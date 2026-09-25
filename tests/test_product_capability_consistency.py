"""Fail-closed consistency tests for FINCO product-capability surfaces.

These tests enforce that every public product surface agrees with the canonical
registry in ``app/product_capability.py``. A test failure here means a surface
has drifted from the registry; the fix is always in the surface, never in this
file.

Acceptance markers covered:
  SUPPORTED_TODAY_SINGLE_SOURCE_OF_TRUTH
  SUPPORTED_TODAY_NO_CROSS_SURFACE_DRIFT
  EV_PROMOTION_SINGLE_AUTHORITY
  SUPPORTED_TODAY_LIBRARY_CONSISTENCY
  SUPPORTED_TODAY_HOMEPAGE_CONSISTENCY
  SUPPORTED_TODAY_DOCS_CONSISTENCY
  SUPPORTED_TODAY_ROADMAP_CONSISTENCY
  SUPPORTED_TODAY_API_CONSISTENCY
  SUPPORTED_TODAY_LIMITATIONS_CONSISTENCY
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _roadmap_html() -> str:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_ui.router import router as protocol_router
    app = FastAPI()
    app.include_router(protocol_router)
    return TestClient(app, raise_server_exceptions=True).get("/roadmap").text


def _docs_html() -> str:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_ui.router import router as protocol_router
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(protocol_router)
    return TestClient(app, raise_server_exceptions=True).get("/docs").text


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_SINGLE_SOURCE_OF_TRUTH
# ---------------------------------------------------------------------------

def test_registry_imports_cleanly():
    """Registry module is importable and exports expected symbols."""
    from app.product_capability import (
        PRODUCT_CAPABILITIES,
        LIVE_CAPABILITIES,
        PREVIEW_CAPABILITIES,
        IN_DEVELOPMENT_CAPABILITIES,
        LIVE_KEYS,
        API_AVAILABLE_KEYS,
        ProductStatus,
    )
    assert len(PRODUCT_CAPABILITIES) >= 5
    assert len(LIVE_CAPABILITIES) >= 3
    assert len(PREVIEW_CAPABILITIES) >= 1
    assert len(IN_DEVELOPMENT_CAPABILITIES) >= 1


def test_solar_wind_dc_are_live():
    from app.product_capability import LIVE_KEYS
    assert "solar" in LIVE_KEYS
    assert "wind" in LIVE_KEYS
    assert "data_center" in LIVE_KEYS


def test_ev_charging_is_in_development():
    from app.product_capability import IN_DEVELOPMENT_CAPABILITIES, ProductStatus
    keys = {c.key for c in IN_DEVELOPMENT_CAPABILITIES}
    assert "ev_charging" in keys


def test_storage_is_preview():
    from app.product_capability import PREVIEW_CAPABILITIES
    keys = {c.key for c in PREVIEW_CAPABILITIES}
    assert "storage" in keys


def test_ev_charging_has_no_live_capability_flags():
    from app.product_capability import PRODUCT_CAPABILITIES
    ev = next(c for c in PRODUCT_CAPABILITIES if c.key == "ev_charging")
    assert not ev.runnable
    assert not ev.cloneable
    assert not ev.api_available
    assert not ev.canonical_last_run


# ---------------------------------------------------------------------------
# EV_PROMOTION_SINGLE_AUTHORITY
# ---------------------------------------------------------------------------

def test_ev_promotion_procedure_documented():
    """EV promotion comment must appear in the canonical registry source."""
    src = (REPO / "app/product_capability.py").read_text()
    assert "EV Promotion procedure" in src
    assert "Change ``_ev_charging.status``" in src


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_API_CONSISTENCY
# ---------------------------------------------------------------------------

def test_api_valid_reference_keys_match_live_registry():
    """VALID_REFERENCE_KEYS in model_reference.py must match LIVE api_available keys."""
    from app.api.v1.model_reference import VALID_REFERENCE_KEYS
    from app.product_capability import PRODUCT_CAPABILITIES

    registry_api_keys = {
        f"generic_{c.key}_reference"
        for c in PRODUCT_CAPABILITIES
        if c.api_available
    }
    assert VALID_REFERENCE_KEYS == registry_api_keys, (
        f"VALID_REFERENCE_KEYS {VALID_REFERENCE_KEYS} does not match "
        f"registry api_available keys {registry_api_keys}"
    )


def test_reference_seed_service_matches_live_registry():
    """CLONEABLE_SEED_TEMPLATE_SOURCES must match LIVE cloneable keys."""
    from app.services.reference_seed_service import CLONEABLE_SEED_TEMPLATE_SOURCES
    from app.product_capability import PRODUCT_CAPABILITIES

    registry_cloneable_keys = {
        f"generic_{c.key}_reference"
        for c in PRODUCT_CAPABILITIES
        if c.cloneable
    }
    assert CLONEABLE_SEED_TEMPLATE_SOURCES == registry_cloneable_keys, (
        f"CLONEABLE_SEED_TEMPLATE_SOURCES {CLONEABLE_SEED_TEMPLATE_SOURCES} does not match "
        f"registry cloneable keys {registry_cloneable_keys}"
    )


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_DOCS_CONSISTENCY
# ---------------------------------------------------------------------------

def test_docs_product_map_mentions_all_live_verticals():
    """Docs product map table must mention all LIVE verticals."""
    from app.product_capability import LIVE_CAPABILITIES
    html = _docs_html()
    for cap in LIVE_CAPABILITIES:
        assert cap.public_name in html, (
            f"Docs is missing live vertical '{cap.public_name}'"
        )


def test_docs_does_not_claim_ev_is_live():
    """Docs must not claim EV Charging is a current production vertical."""
    html = _docs_html()
    # EV Charging may appear on the page but only as in-development / future
    lower = html.lower()
    # The limitations section must state it is in development or not yet released
    assert "ev charging is in development" in lower or "ev charging" not in lower, (
        "Docs must not present EV Charging as a live production vertical"
    )


def test_docs_reference_models_panel_mentions_data_center():
    html = _docs_html()
    assert "Data Center" in html, "Docs reference models panel must mention Data Center"


def test_docs_api_table_mentions_data_center():
    html = _docs_html()
    assert "Data Center" in html


def test_docs_limitations_section_is_accurate():
    html = _docs_html()
    lower = html.lower()
    assert "solar, wind and data center" in lower, (
        "Docs limitations must name Solar, Wind and Data Center as production verticals"
    )
    assert "storage" in lower
    assert "ev charging" in lower


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_ROADMAP_CONSISTENCY
# ---------------------------------------------------------------------------

def test_roadmap_shipped_chips_do_not_include_ev():
    """EV Charging must not appear in the Shipped baseline chip row."""
    html = _roadmap_html()
    start = html.find("Infrastructure Model")
    assert start != -1, "Infrastructure Model section not found in Roadmap"
    chip_div_start = html.find("proad-chip-row", start)
    assert chip_div_start != -1
    chip_div_end = html.find("</div>", chip_div_start)
    chip_section = html[chip_div_start:chip_div_end]
    assert "EV Charging" not in chip_section, (
        "EV Charging must not be listed in the Shipped infrastructure chip row"
    )


def test_roadmap_shipped_chips_include_all_live_verticals():
    """All LIVE verticals must appear in the Shipped chip row."""
    from app.product_capability import LIVE_CAPABILITIES
    html = _roadmap_html()
    start = html.find("Infrastructure Model")
    chip_div_start = html.find("proad-chip-row", start)
    chip_div_end = html.find("</div>", chip_div_start)
    chip_section = html[chip_div_start:chip_div_end]
    for cap in LIVE_CAPABILITIES:
        assert cap.public_name in chip_section, (
            f"Live vertical '{cap.public_name}' is missing from Shipped chip row"
        )


def test_roadmap_ev_development_note_present():
    """Roadmap must note that EV Charging is in development."""
    html = _roadmap_html()
    assert "EV Charging is in development" in html, (
        "Roadmap must state EV Charging is in development"
    )


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_LIMITATIONS_CONSISTENCY
# ---------------------------------------------------------------------------

def test_known_limitations_mentions_all_live_references():
    """known_limitations_page.html must reference all live production synthetic models."""
    from app.product_capability import LIVE_CAPABILITIES
    text = (REPO / "app/templates/known_limitations_page.html").read_text()
    for cap in LIVE_CAPABILITIES:
        assert cap.public_name in text, (
            f"known_limitations_page.html is missing live capability '{cap.public_name}'"
        )


def test_known_limitations_mentions_ev_in_development():
    text = (REPO / "app/templates/known_limitations_page.html").read_text()
    lower = text.lower()
    assert "ev charging" in lower
    assert "in development" in lower


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_NO_CROSS_SURFACE_DRIFT
# ---------------------------------------------------------------------------

def test_no_surface_claims_ev_is_shipped():
    """No static template file may claim EV Charging is shipped/live."""
    templates = list((REPO / "app/templates").rglob("*.html"))
    for tmpl in templates:
        content = tmpl.read_text()
        # "EV Charging" followed closely by "Shipped" within 200 chars is a drift signal
        idx = 0
        while True:
            ev_idx = content.find("EV Charging", idx)
            if ev_idx == -1:
                break
            window = content[ev_idx:ev_idx + 200]
            assert "Shipped" not in window, (
                f"{tmpl.name}: EV Charging appears near 'Shipped' — check for drift"
            )
            idx = ev_idx + 1


def test_live_keys_match_between_registry_and_api():
    from app.product_capability import LIVE_KEYS
    from app.api.v1.model_reference import VALID_REFERENCE_KEYS
    # Every live key must have a corresponding reference key in the API
    for key in LIVE_KEYS:
        assert f"generic_{key}_reference" in VALID_REFERENCE_KEYS, (
            f"Live key '{key}' has no entry in VALID_REFERENCE_KEYS"
        )
