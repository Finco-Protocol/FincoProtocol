"""Read-only FINCO Radar RWA browser surface."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_rwa.service import RwaDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_rwa_service = RwaDashboardService()


def set_rwa_service(service) -> None:
    global _rwa_service
    _rwa_service = service


def _route_failure(exc: Exception) -> dict:
    return {
        "state": "UNAVAILABLE",
        "counts": [],
        "sections": [],
        "reason": f"RWA_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "publisher": "CoinGecko",
        "transport": "CoinGecko Demo API",
        "list_source_url": "https://docs.coingecko.com/demo/reference/rwas-list",
        "markets_source_url": "https://docs.coingecko.com/demo/reference/rwas-markets",
    }


@router.get("/radar/crypto/rwa", response_class=HTMLResponse)
async def radar_crypto_rwa(request: Request):
    try:
        dashboard = await run_in_threadpool(_rwa_service.read_dashboard)
    except Exception as exc:  # noqa: BLE001 — browser boundary must fail closed
        dashboard = _route_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/rwa.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "crypto",
            "crypto_section": "rwa",
            "user": user,
        },
        status_code=200,
    )
