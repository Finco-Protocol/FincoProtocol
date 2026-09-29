"""Read-only R-LIVE product shell routes.

These routes render the R-LIVE landing table and per-asset detail shell.
They are strictly read-only: no history writes, no model runs, no authority
decisions.  The underlying R-LIVE authority is never imported or mutated here.

/radar              → 302 redirect to /radar/r-live
/radar/r-live       → R-LIVE landing table (all approved assets, JS-populated)
/radar/r-live/{canonical_id_slug} → per-asset detail shell
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")

_METHODOLOGY = (
    "Independent on-chain reference price derived from a single direct "
    "Robinhood on-chain pool observation. The economic basis (NASDAQ equity "
    "fair value) is sourced independently. Premium/discount reflects the gap "
    "between the on-chain token reference and the independently observed equity "
    "basis. This is a reference observation only — it is not a tradeable or "
    "executable price."
)


def _approved_rows() -> list[dict]:
    """Build display rows from the canonical approved registry. Read-only."""
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    rows = []
    for policy in APPROVED_RLIVE_ASSETS.values():
        rows.append({
            "canonical_id": policy.asset_key.canonical_id,
            "symbol": policy.symbol,
            "approved": True,
            "state": "PENDING_JS",
        })
    return rows


@router.get("/radar", response_class=RedirectResponse)
async def radar_root_redirect():
    """Redirect root /radar to /radar/r-live (R-LIVE is the default domain)."""
    return RedirectResponse(url="/radar/r-live", status_code=302)


@router.get("/radar/r-live", response_class=HTMLResponse)
async def radar_r_live_landing(request: Request):
    """R-LIVE landing table. All approved rows populated client-side via JS.
    No numeric values fabricated server-side.
    This handler performs zero history writes and zero authority mutations."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/r_live_landing.html",
        context={
            "radar_domain": "rlive",
            "rows": _approved_rows(),
            "user": user,
            "asset_version": getattr(request.app.state, "asset_version", "dev"),
        },
    )


@router.get("/radar/r-live/{canonical_id_slug}", response_class=HTMLResponse)
async def radar_r_live_detail(request: Request, canonical_id_slug: str):
    """Per-asset R-LIVE detail shell.
    Identity, methodology disclosure.  No pricing math performed here.
    Data populated client-side via JS against the canonical read-only API."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)

    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id_slug)
    if policy is None:
        row = {
            "canonical_id": canonical_id_slug,
            "symbol": canonical_id_slug[:10],
            "approved": False,
            "state": "UNAVAILABLE",
            "reason": "ASSET_NOT_IN_REGISTRY",
        }
        methodology = None
    else:
        row = {
            "canonical_id": policy.asset_key.canonical_id,
            "symbol": policy.symbol,
            "approved": True,
            "state": "PENDING_JS",
        }
        methodology = _METHODOLOGY

    return _templates.TemplateResponse(
        request=request,
        name="radar/r_live_detail.html",
        context={
            "radar_domain": "rlive",
            "row": row,
            "methodology": methodology,
            "user": user,
            "asset_version": getattr(request.app.state, "asset_version", "dev"),
        },
    )
