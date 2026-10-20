"""Institutional portfolio monitoring: GET only, authenticated owner scope."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from decimal import Decimal, InvalidOperation

from app.v2.portfolio_projection import build_portfolio, SORT_KEYS
from app.v2.portfolio_reads import load_portfolio, PortfolioReadError

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request):
    from app.v2.router import _get_current_user
    from main_web import templates
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302, headers=NO_STORE)
    filters = {key: request.query_params.get(key, "").strip()
               for key in ("technology", "country", "project", "stage", "review", "sort", "minimum", "maximum")}
    if any(len(value) > 160 for value in filters.values()):
        return HTMLResponse("Invalid portfolio filter.", status_code=422, headers=NO_STORE)
    try:
        limits = [Decimal(filters[key]) for key in ("minimum", "maximum") if filters[key]]
        if any(not value.is_finite() or abs(value) > Decimal("1e18") for value in limits):
            raise ValueError
        if limits and (not filters["sort"] or (len(limits) == 2 and limits[0] > limits[1])):
            raise ValueError
    except (ValueError, InvalidOperation):
        return HTMLResponse("Invalid financial metric range.", status_code=422, headers=NO_STORE)
    if (any(len(value) > 160 for value in filters.values())
            or filters["sort"] not in SORT_KEYS | {""}
            or filters["review"] not in {"", "review", "stale", "no_run", "low_dscr", "credit_missing"}):
        return HTMLResponse("Invalid portfolio filter.", status_code=422, headers=NO_STORE)
    try:
        view = build_portfolio(load_portfolio(user.user_id), **filters)
    except PortfolioReadError:
        return HTMLResponse("Portfolio evidence temporarily unavailable. Refresh to try again.", status_code=503, headers=NO_STORE)
    return templates.TemplateResponse(request=request, name="portfolio_monitoring.html",
                                      context={"user": user, "portfolio": view}, headers=NO_STORE)
