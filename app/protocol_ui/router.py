"""Protocol shell routes: public verify surface (/verify).

The unified home (/) is handled directly in main_web.py since a route
conflict with the existing GET / handler would produce silent first-match wins.

Routes never touch financial economics, Radar authority, or frozen namespaces.
Verify is network-free: it calls the deterministic public corpus builder only.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))


@router.get("/verify", response_class=HTMLResponse)
async def protocol_verify(request: Request):
    """Public validation corpus — deterministic, network-free, synthetic only."""
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
    except Exception as exc:  # noqa: BLE001
        return _templates.TemplateResponse(
            request=request,
            name="protocol_verify.html",
            context={
                "user": user,
                "corpus": None,
                "corpus_valid": False,
                "error": f"Corpus build error: {exc}",
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
