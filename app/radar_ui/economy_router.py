"""Read-only FINCO Radar Economy browser surface.

This module is presentation/orchestration only.  Macro values and source
binding are owned by ``app.radar_economy``; the route never fabricates a
fallback value and performs no wallet, signing, execution, or model action.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_economy.service import EconomyDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_economy_service = EconomyDashboardService()


def set_economy_service(service) -> None:
    """Inject a deterministic service for tests/diagnostics."""
    global _economy_service
    _economy_service = service


def _route_failure(exc: Exception) -> dict:
    """Fail closed at the page boundary without inventing macro observations."""
    return {
        "state": "UNAVAILABLE",
        "metric_count": 0,
        "fresh_count": 0,
        "stale_count": 0,
        "unavailable_count": 0,
        "sections": [],
        "reason": f"ECONOMY_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/radar/economy", response_class=HTMLResponse)
async def radar_economy(request: Request):
    try:
        dashboard = await run_in_threadpool(_economy_service.read_dashboard)
    except Exception as exc:  # noqa: BLE001 — browser boundary must fail closed
        dashboard = _route_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/economy.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "economy",
            "user": user,
        },
        status_code=200,
    )
