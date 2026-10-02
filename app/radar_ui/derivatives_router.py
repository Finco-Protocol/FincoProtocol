"""Read-only FINCO Radar Crypto Derivatives browser surface."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_derivatives.service import DerivativesDashboardService

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_derivatives_service = DerivativesDashboardService()

# Local TTL cache: repeated page views within the window reuse one provider
# fan-out instead of re-reading Hyperliquid per request. Deliberately a small
# local cache, not a shared caching framework.
_DASHBOARD_TTL_SECONDS = 45.0
_DASHBOARD_STALE_GRACE_SECONDS = 300.0
_dashboard_lock = threading.Lock()
_dashboard_fetch_lock = threading.Lock()
_dashboard_cache: dict = {"at": None, "value": None}


def set_derivatives_service(service) -> None:
    """Inject a deterministic service for tests/diagnostics."""
    global _derivatives_service
    _derivatives_service = service
    _reset_dashboard_cache()


def _reset_dashboard_cache() -> None:
    with _dashboard_lock:
        _dashboard_cache["at"] = None
        _dashboard_cache["value"] = None


def _payload_cacheable(value) -> bool:
    # A fully UNAVAILABLE dashboard is never cached — a transient provider
    # outage must not pin the failure for the TTL window.
    return not (isinstance(value, dict) and value.get("state") == "UNAVAILABLE")


def _read_dashboard_cached():
    """TTL-cached, single-flight dashboard read.

    Provider I/O runs outside the cache lock; concurrent identical misses
    coalesce on the fetch lock. On provider failure the last-known-good
    payload is served within the stale-grace window and is never erased.
    Cached payloads keep their canonical timestamps — serving them is a
    repetition of a real observation, never a fabricated new one.
    """
    now = time.monotonic()
    with _dashboard_lock:
        at, value = _dashboard_cache["at"], _dashboard_cache["value"]
    if value is not None and at is not None and (now - at) < _DASHBOARD_TTL_SECONDS:
        return value
    with _dashboard_fetch_lock:
        now = time.monotonic()
        with _dashboard_lock:
            at, value = _dashboard_cache["at"], _dashboard_cache["value"]
        if value is not None and at is not None and (now - at) < _DASHBOARD_TTL_SECONDS:
            return value
        try:
            value = _derivatives_service.read_dashboard()
        except Exception:
            with _dashboard_lock:
                at, value = _dashboard_cache["at"], _dashboard_cache["value"]
            if value is not None and at is not None \
                    and (time.monotonic() - at) < _DASHBOARD_STALE_GRACE_SECONDS:
                return value
            raise
        if _payload_cacheable(value):
            with _dashboard_lock:
                _dashboard_cache["at"] = now
                _dashboard_cache["value"] = value
        return value


def _route_failure(exc: Exception) -> dict:
    """Fail closed at the browser boundary without inventing observations."""
    return {
        "state": "UNAVAILABLE",
        "sections": [],
        "reason": f"DERIVATIVES_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/radar/crypto/derivatives", response_class=HTMLResponse)
async def radar_crypto_derivatives(request: Request):
    try:
        dashboard = await run_in_threadpool(_read_dashboard_cached)
    except Exception as exc:  # noqa: BLE001 — fail closed at browser boundary
        dashboard = _route_failure(exc)
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
