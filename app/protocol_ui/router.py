"""Protocol shell routes: public product surfaces and validation support.

The unified home (/) is handled directly in main_web.py since a route
conflict with the existing GET / handler would produce silent first-match wins.

GET /api is the human-facing FINCO API Beta page (no auth required).
GET /docs/start is the human-facing FINCO product documentation page (no auth required).
The temporary /docs/start path avoids colliding with the web app's current FastAPI
interactive docs route at /docs. Stable /api/docs and /api/openapi.json aliases are
provided now so the backing API service can later own those paths without changing
public links.

Routes never touch financial economics, Radar authority, or frozen namespaces.
Verify is network-free: it calls the deterministic public corpus builder only.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
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


@router.get("/api/docs", include_in_schema=False)
async def protocol_api_docs_alias():
    """Stable public alias for the current FastAPI Swagger surface."""
    return RedirectResponse(url="/docs", status_code=307)


@router.get("/api/openapi.json", include_in_schema=False)
async def protocol_openapi_alias():
    """Stable public alias for the current FastAPI OpenAPI schema."""
    return RedirectResponse(url="/openapi.json", status_code=307)


@router.get("/docs/start", response_class=HTMLResponse)
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
