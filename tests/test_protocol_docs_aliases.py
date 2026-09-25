"""Compatibility tests for documentation route separation."""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.protocol_ui.router import router as protocol_router

    app = FastAPI()
    app.include_router(protocol_router)
    return TestClient(app, follow_redirects=False)


def test_api_docs_alias_redirects_to_current_swagger():
    response = _client().get("/api/docs")
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_api_openapi_alias_redirects_to_current_schema():
    response = _client().get("/api/openapi.json")
    assert response.status_code == 307
    assert response.headers["location"] == "/openapi.json"
