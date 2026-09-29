"""Read-only R-LIVE product shell routes.

These routes render the R-LIVE landing table and per-asset detail shell.
They are strictly read-only: no history writes, no model runs, no authority
decisions.  The underlying R-LIVE authority (finco_radar/authority/r_live_policy.py)
is never imported or mutated here.

/radar              → 302 redirect to /radar/r-live
/radar/r-live       → R-LIVE landing table (AAPL populated via JS; others UNAVAILABLE)
/radar/r-live/{asset_uid} → per-asset detail shell (identity + methodology; no math)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")

# Static shell rows for assets that are not yet authority-approved.
# Only AAPL is authority-approved (finco_radar/authority/r_live_policy.py AAPL_KEY).
# These rows render as UNAVAILABLE — no numeric values fabricated.
_SHELL_ROWS = [
    {
        "asset_uid": "AAPL",
        "label": "Apple Inc.",
        "economic_basis": "Equity — NASDAQ-listed common stock",
        "approved": True,
        "state": "PENDING_JS",  # populated client-side from /radar/crypto/rwa/r-live/aapl/snapshot
    },
    {
        "asset_uid": "TSLA",
        "label": "Tesla Inc.",
        "economic_basis": "Equity — NASDAQ-listed common stock",
        "approved": False,
        "state": "UNAVAILABLE",
        "reason": "NOT_APPROVED",
    },
    {
        "asset_uid": "XAUT",
        "label": "Gold (Tokenized)",
        "economic_basis": "Physical commodity — troy ounce gold",
        "approved": False,
        "state": "UNAVAILABLE",
        "reason": "NOT_APPROVED",
    },
    {
        "asset_uid": "BRKB",
        "label": "Berkshire Hathaway B",
        "economic_basis": "Equity — NYSE-listed common stock",
        "approved": False,
        "state": "UNAVAILABLE",
        "reason": "NOT_APPROVED",
    },
]

# Detail shell methodology copy — no numeric values, no pricing math.
_AAPL_METHODOLOGY = (
    "Independent on-chain reference price derived from a single direct "
    "Robinhood on-chain pool observation. The economic basis (NASDAQ equity "
    "fair value) is sourced independently. Premium/discount reflects the gap "
    "between the on-chain token reference and the independently observed equity "
    "basis. This is a reference observation only — it is not a tradeable or "
    "executable price."
)


@router.get("/radar", response_class=RedirectResponse)
async def radar_root_redirect():
    """Redirect root /radar to /radar/r-live (R-LIVE is the default domain)."""
    return RedirectResponse(url="/radar/r-live", status_code=302)


@router.get("/radar/r-live", response_class=HTMLResponse)
async def radar_r_live_landing(request: Request):
    """R-LIVE landing table. AAPL row is populated client-side via JS.
    Non-approved rows render UNAVAILABLE — no numeric values fabricated.
    This handler performs zero history writes and zero authority mutations."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/r_live_landing.html",
        context={
            "radar_domain": "rlive",
            "rows": _SHELL_ROWS,
            "user": user,
        },
    )


@router.get("/radar/r-live/{asset_uid}", response_class=HTMLResponse)
async def radar_r_live_detail(request: Request, asset_uid: str):
    """Per-asset R-LIVE detail shell.
    Identity, deployment, economic basis, methodology disclosure.
    No pricing math performed here. AAPL data populated client-side via JS.
    Non-approved assets render an UNAVAILABLE shell."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)

    uid_upper = asset_uid.upper()
    row = next((r for r in _SHELL_ROWS if r["asset_uid"] == uid_upper), None)
    if row is None:
        row = {
            "asset_uid": uid_upper,
            "label": uid_upper,
            "economic_basis": "Unknown",
            "approved": False,
            "state": "UNAVAILABLE",
            "reason": "ASSET_NOT_IN_REGISTRY",
        }

    methodology = _AAPL_METHODOLOGY if row["approved"] else None
    return _templates.TemplateResponse(
        request=request,
        name="radar/r_live_detail.html",
        context={
            "radar_domain": "rlive",
            "row": row,
            "methodology": methodology,
            "user": user,
        },
    )
