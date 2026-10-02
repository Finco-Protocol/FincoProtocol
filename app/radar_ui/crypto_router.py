"""Read-only FINCO Radar Crypto browser surface."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_crypto.service import CryptoDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_crypto_service = CryptoDashboardService()

# Local TTL cache: repeated page views within the window reuse one provider
# fan-out instead of re-reading CoinGecko per request. Deliberately a small
# local cache, not a shared caching framework.
_DASHBOARD_TTL_SECONDS = 45.0
_DASHBOARD_STALE_GRACE_SECONDS = 300.0
_dashboard_lock = threading.Lock()
_dashboard_fetch_lock = threading.Lock()
_dashboard_cache: dict = {"at": None, "value": None}


def set_crypto_service(service) -> None:
    """Inject deterministic Crypto dashboard service for tests/diagnostics."""
    global _crypto_service
    _crypto_service = service
    _reset_dashboard_cache()


def _reset_dashboard_cache() -> None:
    with _dashboard_lock:
        _dashboard_cache["at"] = None
        _dashboard_cache["value"] = None


def _read_dashboard_cached():
    """TTL-cached, single-flight dashboard read with typed last-known-good.

    See ``app.radar_ui._dashboard_lkg``: covers BOTH provider exceptions and
    services that fail closed internally with a fully typed UNAVAILABLE
    payload; within the stale-grace window the last-known-good payload is
    served as an explicit stale presentation (never as fresh/current) and a
    fully UNAVAILABLE result is never stored over it.
    """
    from app.radar_ui import _dashboard_lkg
    return _dashboard_lkg.read_with_last_known_good(
        cache=_dashboard_cache, lock=_dashboard_lock,
        fetch_lock=_dashboard_fetch_lock,
        fetch=_crypto_service.read_dashboard,
        ttl=_DASHBOARD_TTL_SECONDS, grace=_DASHBOARD_STALE_GRACE_SECONDS)


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
        dashboard = await run_in_threadpool(_read_dashboard_cached)
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
