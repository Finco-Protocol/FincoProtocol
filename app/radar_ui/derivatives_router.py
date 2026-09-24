"""Read-only FINCO Radar Crypto Derivatives browser surface."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_derivatives.service import DerivativesDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_derivatives_service = DerivativesDashboardService()


def set_derivatives_service(service) -> None:
    """Inject a deterministic service for tests/diagnostics."""
    global _derivatives_service
    _derivatives_service = service


@router.get("/radar/crypto/derivatives", response_class=HTMLResponse)
async def radar_crypto_derivatives(request: Request):
    dashboard = await run_in_threadpool(_derivatives_service.read_dashboard)
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/derivatives.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "crypto",
            "crypto_section": "derivatives",
            "user": user,
        },
        status_code=200,
    )
