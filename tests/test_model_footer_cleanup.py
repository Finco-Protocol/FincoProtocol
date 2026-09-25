"""Model footer pilot-link cleanup — regression tests.

Verifies that the three pilot-era documentation links (Pilot Guide,
Known Limitations, Validation Status) are absent from the shared product
footer while the financial modelling disclaimer, primary navigation, and
underlying documentation routes remain intact.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
import main_web  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FOOTER_TEMPLATE = REPO / "app/templates/partials/_app_footer.html"
LIBRARY_TEMPLATE = REPO / "app/templates/library/project_library.html"


@pytest.fixture(scope="module")
def client():
    return TestClient(main_web.app)


@pytest.fixture(scope="module")
def library_html(client):
    resp = client.get("/library")
    assert resp.status_code == 200
    return resp.text


def _extract_app_footer(html: str) -> str:
    """Return only the <footer class="app-footer">…</footer> region."""
    start = html.find('<footer class="app-footer">')
    if start == -1:
        return ""
    end = html.find("</footer>", start)
    return html[start: end + len("</footer>")] if end != -1 else html[start:]


# ── Footer template source ────────────────────────────────────────────────────

class TestFooterTemplateSource:
    """The footer partial must not contain the three pilot documentation links."""

    def test_pilot_guide_link_absent_from_footer_template(self):
        html = FOOTER_TEMPLATE.read_text(encoding="utf-8")
        assert "Pilot Guide" not in html
        assert "/pilot-guide" not in html

    def test_known_limitations_link_absent_from_footer_template(self):
        html = FOOTER_TEMPLATE.read_text(encoding="utf-8")
        assert "Known Limitations" not in html
        assert "/known-limitations" not in html

    def test_validation_status_link_absent_from_footer_template(self):
        html = FOOTER_TEMPLATE.read_text(encoding="utf-8")
        assert "Validation Status" not in html

    def test_financial_disclaimer_present_in_footer_template(self):
        html = FOOTER_TEMPLATE.read_text(encoding="utf-8")
        assert "financial modelling" in html
        assert "investment" in html
        assert "app-footer-caveat" in html


# ── Model library page (HTTP render) ─────────────────────────────────────────

class TestModelLibraryPage:
    """The rendered Model library page must omit pilot links and keep disclaimer."""

    def test_library_page_returns_200(self, client):
        resp = client.get("/library")
        assert resp.status_code == 200

    def test_pilot_guide_absent_from_library_footer(self, library_html):
        footer = _extract_app_footer(library_html)
        assert footer, "app-footer element not found in library page"
        assert "Pilot Guide" not in footer
        assert "/pilot-guide" not in footer

    def test_known_limitations_absent_from_library_footer(self, library_html):
        footer = _extract_app_footer(library_html)
        assert "Known Limitations" not in footer
        assert "/known-limitations" not in footer

    def test_validation_status_absent_from_library_footer(self, library_html):
        footer = _extract_app_footer(library_html)
        assert "Validation Status" not in footer

    def test_financial_disclaimer_present_on_library_page(self, library_html):
        footer = _extract_app_footer(library_html)
        assert "financial modelling" in footer
        assert "investment" in footer


# ── Underlying documentation routes still reachable ──────────────────────────

class TestDocumentationRoutesPreserved:
    """Removing footer links must not remove the documentation routes themselves."""

    def test_pilot_guide_route_still_returns_200(self, client):
        resp = client.get("/pilot-guide")
        assert resp.status_code == 200

    def test_known_limitations_route_still_returns_200(self, client):
        resp = client.get("/known-limitations")
        assert resp.status_code in (200, 302)


# ── Primary navigation unchanged ─────────────────────────────────────────────

class TestPrimaryNavigation:
    """Model / Radar / API remain product navigation; Verify is internal."""

    def test_protocol_nav_present_on_library_page(self, library_html):
        # The library page extends base.html which includes the protocol nav
        assert "/radar" in library_html
        assert 'href="/verify"' not in library_html

    def test_brand_bar_guide_link_preserved(self):
        """Brand bar still carries the Guide shortcut — only footer is changed."""
        bar_html = (REPO / "app/templates/partials/_brand_bar.html").read_text(encoding="utf-8")
        assert 'href="/pilot-guide"' in bar_html

    def test_radar_templates_not_touched(self):
        """No Radar template should have changed as a result of this cleanup."""
        radar_dir = REPO / "app/templates/radar"
        for path in radar_dir.glob("*.html"):
            # Just confirm the footer partial is not included in Radar templates
            content = path.read_text(encoding="utf-8")
            assert "_app_footer.html" not in content, (
                f"Radar template {path.name} unexpectedly includes _app_footer.html"
            )
