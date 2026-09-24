"""Read-only FINCO Radar Stablecoin liquidity browser surface."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_stablecoins.service import StablecoinDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_stablecoin_service = StablecoinDashboardService()


def set_stablecoin_service(service) -> None:
    global _stablecoin_service
    _stablecoin_service = service


def _route_failure(exc: Exception) -> dict:
    return {
        "state": "UNAVAILABLE",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "summary_rows": [],
        "top_assets": [],
        "publisher": "DefiLlama",
        "transport": "DefiLlama Stablecoins API",
        "source_endpoint": "/stablecoins?includePrices=true",
        "source_url": "https://defillama.com/stablecoins",
        "reason": f"STABLECOIN_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
    }


@router.get("/radar/crypto/stablecoins", response_class=HTMLResponse)
async def radar_stablecoins(request: Request):
    try:
        dashboard = await run_in_threadpool(_stablecoin_service.read_dashboard)
    except Exception as exc:  # noqa: BLE001
        dashboard = _route_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/stablecoins.html",
        context={
            "stablecoins": dashboard,
            "radar_domain": "crypto",
            "crypto_section": "stablecoins",
            "user": user,
        },
        status_code=200,
    )
