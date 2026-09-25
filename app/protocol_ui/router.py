"""Protocol shell routes: public product surfaces and validation support.

The unified home (/) is handled directly in main_web.py since a route
conflict with the existing GET / handler would produce silent first-match wins.

GET /api         — human-facing FINCO API Beta page (no auth required).
GET /api/docs    — self-hosted Swagger UI for the public developer API.
GET /api/openapi.json — filtered public OpenAPI schema (/api/v1/** only).
GET /docs        — FINCO product documentation (no auth required).
GET /docs/start  — permanent redirect to /docs (backward-compatibility alias).
GET /roadmap     — FINCO public product roadmap (no auth required).

/api/docs serves swagger-ui from self-hosted static assets so that FINCO's
Content-Security-Policy (script-src 'self'; style-src 'self') is not violated.
The default FastAPI /docs route is disabled (docs_url=None in FastAPI constructor)
to free /docs for product documentation and to enforce CSP compliance.

Routes never touch financial economics, Radar authority, or frozen namespaces.
Verify is network-free: it calls the deterministic public corpus builder only.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))


@router.get("/verify", response_class=HTMLResponse)
async def protocol_verify(request: Request):
    """Non-discoverable validation corpus — deterministic, network-free, synthetic only."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        from finco_protocol.verification.public_corpus import (
            build_public_validation_corpus,
            verify_public_validation_corpus,
        )
        corpus = await run_in_threadpool(build_public_validation_corpus)
        corpus_valid = verify_public_validation_corpus(corpus)
    except Exception:  # noqa: BLE001
        logger.exception("Verification corpus build failed")
        return _templates.TemplateResponse(
            request=request,
            name="protocol_verify.html",
            context={
                "user": user,
                "corpus": None,
                "corpus_valid": False,
                "error": "Verification corpus is temporarily unavailable.",
            },
            status_code=200,
        )

    return _templates.TemplateResponse(
        request=request,
        name="protocol_verify.html",
        context={
            "user": user,
            "corpus": corpus,
            "corpus_valid": corpus_valid,
            "error": None,
        },
    )


@router.get("/api", response_class=HTMLResponse)
async def protocol_api_beta(request: Request):
    """FINCO API Beta overview page. Public — no auth required."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    api_base_url = str(request.base_url).rstrip("/") + "/api/v1"
    return _templates.TemplateResponse(
        request=request,
        name="protocol_api.html",
        context={
            "user": user,
            "proto_active_page": "api",
            "api_base_url": api_base_url,
        },
    )


@router.get("/api/docs", include_in_schema=False, response_class=HTMLResponse)
async def protocol_api_docs(request: Request):
    """Interactive API documentation — self-hosted Swagger UI.

    Serves swagger-ui from /static/vendor/swagger-ui/ to satisfy FINCO's
    Content-Security-Policy (script-src/style-src 'self' only — no CDN).
    """
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="FINCO Model API — Documentation",
        swagger_js_url="/static/vendor/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/vendor/swagger-ui/swagger-ui.css",
        swagger_favicon_url="/static/vendor/swagger-ui/favicon-32x32.png",
    )


@router.get("/api/openapi.json", include_in_schema=False)
async def protocol_api_openapi(request: Request):
    """Public OpenAPI schema — /api/v1/** endpoints only.

    Builds the schema from the canonical public v1 router mounted at /api/v1,
    not from the full main_web app route table.  This guarantees:
      - no internal UI routes (library, v2, radar-UI) in paths
      - no internal request-body models in components.schemas
      - schema is self-contained and identical regardless of what other
        routes are mounted on the web app
    """
    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi
    from app.api.v1.router import router as _public_v1_router

    _schema_app = FastAPI(
        title="FINCO Model API",
        version="1.0.0",
        description=(
            "Programmatic access to FINCO canonical reference models, "
            "capacity previews, and Radar equity data. "
            "All endpoints are read-only. No project is created by any call."
        ),
    )
    _schema_app.include_router(_public_v1_router, prefix="/api/v1")

    schema = get_openapi(
        title=_schema_app.title,
        version=_schema_app.version,
        description=_schema_app.description,
        routes=_schema_app.routes,
    )
    return JSONResponse(schema)


@router.get("/docs", response_class=HTMLResponse)
async def protocol_docs(request: Request):
    """FINCO product documentation. Public — no auth required."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="protocol_docs.html",
        context={
            "user": user,
            "proto_active_page": "docs",
        },
    )


@router.get("/docs/start", include_in_schema=False)
async def protocol_docs_start_alias():
    """Permanent redirect — /docs/start was the temporary path before /docs was freed."""
    return RedirectResponse(url="/docs", status_code=301)


@router.get("/model/methodology", response_class=HTMLResponse)
async def model_methodology(request: Request):
    """FINCO model methodology — public, no auth required."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="model_methodology.html",
        context={
            "user": user,
            "proto_active_page": "docs",
        },
    )


@router.get("/roadmap", response_class=HTMLResponse)
async def protocol_roadmap(request: Request):
    """FINCO public product roadmap. Public — no auth required."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="protocol_roadmap.html",
        context={
            "user": user,
            "proto_active_page": "roadmap",
        },
    )
