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


@pytest.fixture(scope="module")
def client():
    return TestClient(main_web.app)


@pytest.fixture(scope="module")
def guide_html():
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
    return main_web.templates.TemplateResponse(
        request=Request(scope),
        name="base.html",
        context={"asset_version": "test"},
    ).body.decode("utf-8")


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
    """/library redirects to canonical React My Projects and SSR base footer omits pilot links."""

    def test_library_page_returns_200(self, client):
        redir = client.get("/library", follow_redirects=False)
        assert redir.status_code in (200, 302)
        if redir.status_code == 302:
            assert redir.headers["location"].startswith("/v2/model-react")
        resp = client.get("/library")
        assert resp.status_code == 200

    def test_pilot_guide_absent_from_library_footer(self, guide_html):
        footer = _extract_app_footer(guide_html)
        assert footer, "app-footer element not found in shared SSR base page"
        assert "Pilot Guide" not in footer
        assert "/pilot-guide" not in footer

    def test_known_limitations_absent_from_library_footer(self, guide_html):
        footer = _extract_app_footer(guide_html)
        assert "Known Limitations" not in footer
        assert "/known-limitations" not in footer

    def test_validation_status_absent_from_library_footer(self, guide_html):
        footer = _extract_app_footer(guide_html)
        assert "Validation Status" not in footer

    def test_financial_disclaimer_present_on_library_page(self, guide_html):
        footer = _extract_app_footer(guide_html)
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

    def test_protocol_nav_present_on_library_page(self, guide_html):
        # Shared SSR base.html includes the protocol nav without internal Verify links
        assert "/radar" in guide_html
        assert 'href="/verify"' not in guide_html

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


def test_canonical_react_library_renders_financial_disclaimer_and_excludes_pilot_links(monkeypatch, tmp_path):
    """Under default React ON, the canonical My Projects page shows the modelling disclaimer and no pilot links."""
    playwright = pytest.importorskip("playwright.sync_api")
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    import socket, threading, time, os, uvicorn
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "footer-react.db"))
    db.init_db()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    try:
        opts = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
        if os.environ.get("FINCO_TEST_CHROMIUM_PATH"):
            opts["executable_path"] = os.environ["FINCO_TEST_CHROMIUM_PATH"]
        with playwright.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(**opts)
            except Exception as exc:
                pytest.skip(f"chromium unavailable: {exc}")
            ctx = browser.new_context()
            ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="footer-u", username="footer-u"), "url": base}])
            page = ctx.new_page()
            page.goto(base + "/v2/model-react/", wait_until="load")
            footer = page.locator('[data-testid="react-library-footer"]')
            footer.wait_for(timeout=20000)
            txt = footer.inner_text()
            assert "financial modelling" in txt and "investment" in txt
            for forbidden in ("Pilot Guide", "Known Limitations", "Validation Status"):
                assert forbidden not in txt
            browser.close()
    finally:
        server.should_exit = True
        t.join(5)
