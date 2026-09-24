"""Read-only FINCO Radar Crypto browser surface."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_crypto.service import CryptoDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_crypto_service = CryptoDashboardService()


def set_crypto_service(service) -> None:
    """Inject deterministic Crypto dashboard service for tests/diagnostics."""
    global _crypto_service
    _crypto_service = service


def _route_failure(exc: Exception) -> dict:
    return {
        "state": "UNAVAILABLE",
        "metric_count": 0,
        "fresh_count": 0,
        "stale_count": 0,
        "unavailable_count": 0,
        "sections": [],
        "reason": f"CRYPTO_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/radar/crypto", response_class=HTMLResponse)
async def radar_crypto(request: Request):
    try:
        dashboard = await run_in_threadpool(_crypto_service.read_dashboard)
    except Exception as exc:  # noqa: BLE001 — fail closed at browser boundary
        dashboard = _route_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/crypto.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "crypto",
            "user": user,
        },
        status_code=200,
    )
