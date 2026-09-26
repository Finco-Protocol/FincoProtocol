"""P3 Run Certificate V1 — route integration tests.

Proves:
  RUN_CERTIFICATE_JSON_ROUTE_REACHABLE   — JSON route returns 200 + FINCO_RUN_CERTIFICATE_V1
  RUN_CERTIFICATE_HTML_ROUTE_REACHABLE   — HTML route returns 200 + certificate page
  RUN_CERTIFICATE_ROUTE_NO_SHADOWING     — project_code.json is NOT consumed by the HTML route
  Unauthenticated JSON  → 401
  Unauthenticated HTML  → 302 /login
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_client(tmp_path, monkeypatch):
    """TestClient backed by a temp DB pre-seeded with reference canonical last runs."""
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "route-int-test.db"))
    db.init_db()

    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )
    ensure_reference_models()
    ensure_reference_canonical_last_runs()

    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=False)


def _make_demo_cookie(user_id: str) -> dict[str, str]:
    from app.auth import create_demo_session_token, DEMO_COOKIE_NAME
    return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


def _make_demo_user_id() -> str:
    from app.auth import new_demo_user_id
    return new_demo_user_id()


def _solar_project_code() -> str:
    """Return the project_code for the seeded Solar reference model."""
    from app.persistence.projects_repository import get_reference_by_template_source
    rec = get_reference_by_template_source("generic_solar_reference")
    assert rec is not None, "Solar reference must be seeded"
    return rec.project_code


# ---------------------------------------------------------------------------
# B. JSON route reachability — RUN_CERTIFICATE_JSON_ROUTE_REACHABLE
# ---------------------------------------------------------------------------

class TestJsonRouteReachable:
    def test_json_route_returns_200_with_certificate(self, seeded_client):
        """RUN_CERTIFICATE_JSON_ROUTE_REACHABLE: GET .json returns 200 + FINCO_RUN_CERTIFICATE_V1 payload."""
        uid = _make_demo_user_id()
        project_code = _solar_project_code()

        resp = seeded_client.get(
            f"/verify/run/{project_code}.json",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, f"Expected application/json, got {content_type!r}"

        body = resp.json()
        assert body["schema"] == "FINCO_RUN_CERTIFICATE_V1", f"Missing schema in: {body}"
        assert body["certificate_id"].startswith("frc_"), f"Bad cert_id in: {body}"
        assert len(body["certificate_digest_sha256"]) == 64

    def test_json_route_unauthenticated_returns_401(self, seeded_client):
        """Unauthenticated JSON request → 401."""
        project_code = _solar_project_code()
        resp = seeded_client.get(
            f"/verify/run/{project_code}.json",
            follow_redirects=False,
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        body = resp.json()
        assert "authentication_required" in body.get("error", "")

    def test_json_route_not_found_returns_404(self, seeded_client):
        """JSON route returns 404 for a nonexistent project."""
        uid = _make_demo_user_id()
        resp = seeded_client.get(
            "/verify/run/nonexistent_project_xyz.json",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# B. HTML route reachability — RUN_CERTIFICATE_HTML_ROUTE_REACHABLE
# ---------------------------------------------------------------------------

class TestHtmlRouteReachable:
    def test_html_route_returns_200_with_certificate_page(self, seeded_client):
        """RUN_CERTIFICATE_HTML_ROUTE_REACHABLE: GET HTML route returns 200 + run certificate page."""
        uid = _make_demo_user_id()
        project_code = _solar_project_code()

        resp = seeded_client.get(
            f"/verify/run/{project_code}",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type, f"Expected text/html, got {content_type!r}"

        body = resp.text
        assert "INTEGRITY BOUND" in body, "HTML page must contain INTEGRITY BOUND status"
        assert "FINCO Run Certificate" in body, "HTML page must contain FINCO Run Certificate"

    def test_html_route_unauthenticated_redirects_to_login(self, seeded_client):
        """Unauthenticated HTML request → 302 /login."""
        project_code = _solar_project_code()
        resp = seeded_client.get(
            f"/verify/run/{project_code}",
            follow_redirects=False,
        )
        assert resp.status_code == 302, f"Expected 302, got {resp.status_code}"
        location = resp.headers.get("location", "")
        assert "/login" in location, f"Expected redirect to /login, got location={location!r}"


# ---------------------------------------------------------------------------
# B. No route shadowing — RUN_CERTIFICATE_ROUTE_NO_SHADOWING
# ---------------------------------------------------------------------------

class TestRouteNoShadowing:
    def test_json_suffix_not_consumed_by_html_route(self, seeded_client):
        """RUN_CERTIFICATE_ROUTE_NO_SHADOWING: GET .json returns JSON, not HTML.

        If the HTML route (/verify/run/{project_code}) were registered first and
        matched project_code='foo.json', this would return an HTML 404 instead of
        a JSON response.
        """
        uid = _make_demo_user_id()
        project_code = _solar_project_code()

        json_resp = seeded_client.get(
            f"/verify/run/{project_code}.json",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )
        html_resp = seeded_client.get(
            f"/verify/run/{project_code}",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )

        # JSON route returns JSON content type
        json_ct = json_resp.headers.get("content-type", "")
        assert "application/json" in json_ct, (
            f"JSON route must return application/json, got {json_ct!r}. "
            f"This indicates route shadowing: the HTML route consumed the .json URL."
        )

        # HTML route returns HTML content type
        html_ct = html_resp.headers.get("content-type", "")
        assert "text/html" in html_ct, (
            f"HTML route must return text/html, got {html_ct!r}."
        )

        # JSON route body is parseable JSON with correct schema
        body = json_resp.json()
        assert body.get("schema") == "FINCO_RUN_CERTIFICATE_V1", (
            f"JSON route body is not a certificate (shadowing suspected): {body}"
        )

    def test_html_route_does_not_serve_json_for_plain_code(self, seeded_client):
        """HTML route serves HTML (not JSON) for the plain project_code without .json suffix."""
        uid = _make_demo_user_id()
        project_code = _solar_project_code()

        resp = seeded_client.get(
            f"/verify/run/{project_code}",
            cookies=_make_demo_cookie(uid),
            follow_redirects=False,
        )
        assert "text/html" in resp.headers.get("content-type", ""), (
            "HTML route must return text/html for plain project_code"
        )
        body = resp.json() if "application/json" in resp.headers.get("content-type", "") else None
        assert body is None, "HTML route must not return JSON"
