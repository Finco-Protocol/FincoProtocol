"""Explicit FINCO Yield public integration boundary.

The canonical data/runtime router remains ``finco_yield.web.router``.  This
module only keeps the primary public ``/yield`` product entry reachable when
``FINCO_YIELD_ENABLED`` is OFF; in that state no Yield registry, history,
watchlist, wallet, or opportunity data is loaded.  When the runtime flag is ON,
the canonical Yield router is mounted unchanged.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from finco_yield.flags import yield_enabled
from finco_yield.web import router as _yield_router


router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_templates = Jinja2Templates(directory=str(_REPO_ROOT / "app" / "templates"))
_templates.env.autoescape = True


if yield_enabled():
    # One runtime/data authority: expose the reviewed canonical Yield router.
    router.include_router(_yield_router)
else:
    @router.get("/yield", response_class=HTMLResponse, include_in_schema=False)
    async def yield_feature_gated_landing(request: Request):
        """Truthful public product shell while Yield runtime remains disabled."""
        from app.auth import resolve_request_session

        return _templates.TemplateResponse(
            request=request,
            name="yield/disabled.html",
            context={"user": resolve_request_session(request)},
        )
