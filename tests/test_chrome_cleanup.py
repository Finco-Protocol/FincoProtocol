"""Chrome cleanup regression tests — Tasks A–F (navigation cleanup pass).

Covers:
- A: Radar READ-ONLY product badge removed from protocol nav and home
- B: Model Limitations CTA removed from brand bar primary chrome
- C: Guide route returns HTTP 200 (regression for FileNotFoundError)
- D: ⌘K Search placeholder removed from brand bar
- E: v1.7 hard-coded version removed from brand bar
- F: Help remains; Guide remains; execution still Coming soon
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
import main_web  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    return TestClient(main_web.app)


@pytest.fixture(scope="module")
def home_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


# ─────────────────────────────────────────────────────────────────────────────
# A. Radar READ-ONLY product badge removed
# ─────────────────────────────────────────────────────────────────────────────

class TestRadarReadOnlyBadgeRemoved:
    """Radar must not be branded READ-ONLY in normal product chrome."""

    def test_protocol_nav_no_readonly_badge(self):
        """_protocol_nav.html must not render the READ-ONLY badge beside Radar."""
        nav_html = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        assert "READ-ONLY" not in nav_html, (
            "protocol nav still carries READ-ONLY badge beside Radar"
        )
        assert "proto-nav__badge" not in nav_html or "READ-ONLY" not in nav_html, (
            "proto-nav__badge with READ-ONLY still present"
        )

    def test_protocol_nav_radar_link_present(self):
        """Radar link still exists in protocol nav after badge removal."""
        nav_html = (REPO / "app/templates/partials/_protocol_nav.html").read_text()
        assert 'href="/radar"' in nav_html, "Radar nav link must still exist"

    def test_home_radar_card_no_readonly_badge(self, home_html):
        """FINCO home Radar capability card must not render READ-ONLY badge."""
        assert "READ-ONLY" not in home_html, (
            "FINCO home still renders READ-ONLY badge/label"
        )
        assert "Read-only execution simulation" not in home_html, (
            "FINCO home still renders 'Read-only execution simulation' bullet"
        )

    def test_home_radar_card_coming_soon_wording(self, home_html):
        """Radar card must use truthful 'coming soon' execution wording."""
        assert "coming soon" in home_html.lower() or "Coming soon" in home_html, (
            "Radar card must use coming-soon wording for execution"
        )

    def test_home_arch_radar_card_no_readonly_label(self, home_html):
        """Architecture Radar card must not render READ-ONLY label."""
        assert "proto-arch__product-readonly" not in home_html, (
            "Architecture card still carries proto-arch__product-readonly class"
        )
        assert 'proto-arch__product--readonly' not in home_html, (
            "Architecture card still carries proto-arch__product--readonly class"
        )

    def test_radar_index_no_readonly_state_chip(self):
        """Radar index.html must not render the READ-ONLY state chip in normal chrome."""
        radar_html = (REPO / "app/templates/radar/index.html").read_text()
        assert 'radar-state-chip--readonly' not in radar_html, (
            "radar/index.html still carries the READ-ONLY state chip"
        )


# ─────────────────────────────────────────────────────────────────────────────
# B. Model Limitations CTA removed from brand bar primary chrome
# ─────────────────────────────────────────────────────────────────────────────

class TestLimitationsRemovedFromBrandBar:
    """Limitations link must not appear in the brand bar primary chrome."""

    def test_brand_bar_no_limitations_link(self):
        """_brand_bar.html must not render a Limitations primary CTA."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert "/known-limitations" not in bar_html, (
            "brand bar still contains /known-limitations link"
        )
        assert "Limitations" not in bar_html, (
            "brand bar still contains 'Limitations' label"
        )

    def test_known_limitations_route_still_reachable(self, client):
        """The /known-limitations route must still exist as a deep link."""
        resp = client.get("/known-limitations")
        assert resp.status_code in (200, 302), (
            f"/known-limitations returned {resp.status_code}; route must remain available"
        )


# ─────────────────────────────────────────────────────────────────────────────
# C. Guide route returns HTTP 200 (regression for FileNotFoundError)
# ─────────────────────────────────────────────────────────────────────────────

class TestGuideRouteFixed:
    """GET /pilot-guide must return HTTP 200 with guide content."""

    def test_pilot_guide_returns_200(self, client):
        """GET /pilot-guide must not return 500; root cause was missing docs/external_pilot_guide.md."""
        resp = client.get("/pilot-guide")
        assert resp.status_code == 200, (
            f"/pilot-guide returned {resp.status_code}; expected 200. "
            "Root cause: docs/external_pilot_guide.md was missing."
        )

    def test_pilot_guide_content_visible(self, client):
        """Guide page must render actual guide content, not an error page."""
        resp = client.get("/pilot-guide")
        assert resp.status_code == 200
        text = resp.text
        assert "Pilot Guide" in text or "pilot" in text.lower(), (
            "Guide page rendered without expected guide content"
        )
        assert "Something went wrong" not in text, (
            "Guide page rendered the error page instead of guide content"
        )

    def test_guide_source_file_exists(self):
        """docs/external_pilot_guide.md must exist (regression guard for FileNotFoundError)."""
        guide_path = REPO / "docs" / "external_pilot_guide.md"
        assert guide_path.exists(), (
            f"docs/external_pilot_guide.md is missing; this caused the /pilot-guide 500"
        )
        assert guide_path.stat().st_size > 0, (
            "docs/external_pilot_guide.md is empty"
        )


# ─────────────────────────────────────────────────────────────────────────────
# D. ⌘K Search placeholder removed from brand bar
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchPlaceholderRemoved:
    """The dead ⌘K Search placeholder must not appear in brand bar chrome."""

    def test_brand_bar_no_cmd_k(self):
        """_brand_bar.html must not render the ⌘K command palette placeholder."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert "⌘K" not in bar_html, (
            "brand bar still contains ⌘K placeholder"
        )

    def test_brand_bar_no_search_kbd(self):
        """_brand_bar.html must not render the Search placeholder label."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert "fo-brand-bar__kbd" not in bar_html, (
            "brand bar still carries the Search kbd span for the command palette placeholder"
        )


# ─────────────────────────────────────────────────────────────────────────────
# E. v1.7 hard-coded version removed from brand bar
# ─────────────────────────────────────────────────────────────────────────────

class TestHardcodedVersionRemoved:
    """The hard-coded v1.7 version label must not appear in brand bar chrome."""

    def test_brand_bar_no_v17(self):
        """_brand_bar.html must not contain hard-coded v1.7 version string."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert "v1.7" not in bar_html, (
            "brand bar still contains hard-coded version v1.7"
        )
        assert "fo-brand-bar__version" not in bar_html, (
            "brand bar still contains the version span element"
        )


# ─────────────────────────────────────────────────────────────────────────────
# F. Help remains; Guide remains; Radar execution still Coming soon
# ─────────────────────────────────────────────────────────────────────────────

class TestPreservedChrome:
    """Help and Guide must remain in brand bar; execution Coming soon preserved."""

    def test_brand_bar_help_remains(self):
        """Help (?) link must remain in brand bar."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert 'href="/help"' in bar_html, (
            "brand bar is missing the Help link"
        )

    def test_brand_bar_guide_remains(self):
        """Guide link must remain in brand bar."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text()
        assert 'href="/pilot-guide"' in bar_html, (
            "brand bar is missing the Guide link"
        )

    def test_radar_execution_still_coming_soon(self):
        """Radar index.html must still render 'Coming soon' for execution simulation."""
        radar_html = (REPO / "app/templates/radar/index.html").read_text()
        assert "Coming soon" in radar_html or "coming soon" in radar_html.lower(), (
            "Radar execution 'Coming soon' text was removed"
        )

    def test_radar_execution_no_active_cta(self):
        """Radar execution form button must remain disabled — no wallet action exposed."""
        radar_html = (REPO / "app/templates/radar/index.html").read_text()
        assert 'disabled' in radar_html, (
            "Radar execution panel appears to have no disabled controls — check execution was not accidentally enabled"
        )
