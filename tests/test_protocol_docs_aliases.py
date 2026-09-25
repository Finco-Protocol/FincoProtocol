"""Regression tests for API documentation and product documentation route architecture.

After the route-foundation change:
- /api/docs  → self-hosted Swagger UI (CSP-compliant, no CDN)
- /api/openapi.json → filtered public schema (/api/v1/** only)
- /docs      → FINCO product documentation
- /docs/start → 301 redirect to /docs (backward-compat alias)
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(follow_redirects: bool = False) -> TestClient:
    from app.protocol_ui.router import router as protocol_router

    # docs_url=None prevents FastAPI's default /docs conflicting with our /docs route
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(protocol_router)
    return TestClient(app, follow_redirects=follow_redirects)


def test_api_docs_returns_self_hosted_swagger():
    """GET /api/docs serves swagger-ui HTML — not a redirect, and from self-hosted assets."""
    response = _client(follow_redirects=True).get("/api/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()
    # Confirm assets are self-hosted (no CDN URLs)
    assert "cdn.jsdelivr.net" not in response.text
    assert "unpkg.com" not in response.text
    # Self-hosted asset paths
    assert "/static/vendor/swagger-ui/swagger-ui-bundle.js" in response.text
    assert "/static/vendor/swagger-ui/swagger-ui.css" in response.text


def test_api_docs_openapi_url_points_to_filtered_schema():
    """Swagger UI on /api/docs loads the filtered /api/openapi.json, not /openapi.json."""
    response = _client(follow_redirects=True).get("/api/docs")
    assert response.status_code == 200
    assert "/api/openapi.json" in response.text


def _full_client() -> TestClient:
    """TestClient using the full main_web app — required for /api/v1/** route presence."""
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=True)


def test_api_openapi_returns_filtered_schema():
    """GET /api/openapi.json returns filtered schema with /api/v1/** paths only."""
    response = _full_client().get("/api/openapi.json")
    assert response.status_code == 200
    data = response.json()
    paths = list(data.get("paths", {}).keys())
    assert any(p.startswith("/api/v1/") for p in paths), "schema must contain /api/v1/ paths"


def test_api_openapi_excludes_library_routes():
    """Public schema must not expose /library/** UI routes."""
    response = _full_client().get("/api/openapi.json")
    assert response.status_code == 200
    paths = list(response.json().get("paths", {}).keys())
    library_paths = [p for p in paths if p.startswith("/library")]
    assert library_paths == [], f"schema must not expose /library/** but found: {library_paths}"


def test_api_openapi_excludes_v2_workbook_routes():
    """Public schema must not expose /v2/workbook UI mutation routes."""
    response = _full_client().get("/api/openapi.json")
    assert response.status_code == 200
    paths = list(response.json().get("paths", {}).keys())
    v2_paths = [p for p in paths if p.startswith("/v2/")]
    assert v2_paths == [], f"schema must not expose /v2/** but found: {v2_paths}"


def test_docs_start_redirects_to_docs():
    """/docs/start is a permanent redirect to /docs."""
    response = _client(follow_redirects=False).get("/docs/start")
    assert response.status_code == 301
    assert response.headers["location"] == "/docs"


def test_docs_route_serves_product_docs():
    """GET /docs serves FINCO product documentation, not Swagger UI."""
    response = _client(follow_redirects=True).get("/docs")
    assert response.status_code == 200
    assert "FINCO Documentation" in response.text
    # Swagger UI must not appear on the product docs page
    assert "SwaggerUIBundle" not in response.text
