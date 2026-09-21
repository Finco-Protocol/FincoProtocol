"""Correction B — Home product truthfulness regression.

Verifies that protocol_home.html non-illustrative copy (trust strip and
architecture section) does not claim capabilities not currently exposed
by the browser product.

Rules:
- Trust strip and Radar architecture description must NOT claim Liquidity
  or cross-market as present surfaces.
- The illustrative composite MUST remain explicitly marked ILLUSTRATIVE
  so its illustrative values are not confused with live product claims.
- Non-browser ASGI test: no Playwright / real browser required.
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
import main_web  # noqa: E402


@pytest.fixture(scope="module")
def home_html():
    client = TestClient(main_web.app)
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


# ── Helper to extract a section of HTML between two markers ──────────────────

def _between(html: str, start_marker: str, end_marker: str) -> str:
    start = html.find(start_marker)
    if start == -1:
        return ""
    end = html.find(end_marker, start + len(start_marker))
    if end == -1:
        return ""
    return html[start:end + len(end_marker)]


# ── P01-A: trust strip does not claim Liquidity ───────────────────────────────

def test_p01_trust_strip_no_liquidity_claim(home_html):
    """Trust strip must not advertise Liquidity as a current surface."""
    trust_block = _between(home_html, 'class="proto-trust"', '</div>\n    </div>')
    assert trust_block, "proto-trust block not found"
    assert "liquidity" not in trust_block.lower(), (
        "Trust strip must not claim 'liquidity' as a currently exposed surface"
    )


def test_p01_trust_strip_has_execution_aware_copy(home_html):
    """Execution-Aware pillar's descriptive subcopy is truthful and specific.

    Scoped to the proto-trust__pillar-sub div that immediately follows the
    'Execution-Aware' pillar label, so the label text itself cannot satisfy
    any of the 'execution' / 'market state' / 'directional gap' assertions.
    """
    # Locate the Execution-Aware pillar label
    ea_idx = home_html.find("Execution-Aware")
    assert ea_idx != -1, "Execution-Aware pillar label not found in Home page"
    # The subcopy div immediately follows the label div in the same pillar
    sub_start = home_html.find("proto-trust__pillar-sub", ea_idx)
    assert sub_start != -1, (
        "proto-trust__pillar-sub element not found after Execution-Aware label"
    )
    content_start = home_html.find(">", sub_start) + 1
    content_end = home_html.find("</div>", content_start)
    assert content_end > content_start, (
        "Could not extract Execution-Aware pillar subcopy content"
    )
    subcopy = home_html[content_start:content_end]
    # Positive: subcopy must describe the three required concepts
    low = subcopy.lower()
    assert "market state" in low, (
        f"Execution-Aware subcopy missing 'market state'. Got: {subcopy!r}"
    )
    assert "execution" in low, (
        f"Execution-Aware subcopy missing 'execution'. Got: {subcopy!r}"
    )
    assert "directional gap" in low, (
        f"Execution-Aware subcopy missing 'directional gap'. Got: {subcopy!r}"
    )
    # Negative: subcopy must not claim liquidity
    assert "liquidity" not in low, (
        f"Execution-Aware subcopy must not claim 'liquidity'. Got: {subcopy!r}"
    )


# ── P01-B: Radar architecture description does not claim unsupported surfaces ─

def test_p01_radar_arch_no_liquidity_claim(home_html):
    """Radar product description in architecture section must not claim Liquidity."""
    # Extract the FINCO Radar product cell
    radar_block = _between(
        home_html,
        'proto-arch__product--readonly',
        '</a>',
    )
    assert radar_block, "FINCO Radar architecture cell not found"
    assert "liquidity" not in radar_block.lower(), (
        "Radar architecture description must not claim 'liquidity' as a current surface"
    )


def test_p01_radar_arch_no_cross_market_claim(home_html):
    """Radar architecture description must not claim cross-market as a current surface."""
    radar_block = _between(
        home_html,
        'proto-arch__product--readonly',
        '</a>',
    )
    assert radar_block, "FINCO Radar architecture cell not found"
    assert "cross-market" not in radar_block.lower(), (
        "Radar architecture description must not claim 'cross-market' as a current surface"
    )


def test_p01_radar_arch_describes_current_surfaces(home_html):
    """Radar architecture description must reference actually-exposed surfaces."""
    radar_block = _between(
        home_html,
        'proto-arch__product--readonly',
        '</a>',
    )
    assert radar_block, "FINCO Radar architecture cell not found"
    text = radar_block.lower()
    for term in ("execution", "gap", "evidence"):
        assert term in text, (
            f"Radar architecture description missing expected current surface term '{term}'"
        )


# ── P01-C: illustrative composite remains explicitly labelled ─────────────────

def test_p01_illustrative_composite_boundary_preserved(home_html):
    """Product composite must be explicitly marked ILLUSTRATIVE and non-live."""
    composite_block = _between(home_html, 'class="proto-composite"', '</div>\n        </div>')
    assert composite_block, "proto-composite block not found"
    text = composite_block.upper()
    assert "ILLUSTRATIVE" in text, (
        "Product composite must carry an explicit ILLUSTRATIVE label"
    )
    # Must also carry the non-live disclaimer
    lower = composite_block.lower()
    assert "not live" in lower or "non-live" in lower or "not live asset" in lower, (
        "Product composite must carry a non-live / not-live-asset disclaimer"
    )
