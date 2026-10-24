"""Concept B NON-MODEL experience — isolated public React surface (V1).

Presentation-only host page for the integrated FINCO Concept B NON-MODEL
frontend (public Landing, Radar, Crypto and Roadmap preview surfaces, selected
by the owner as the "Modern Crypto Terminal" design).

Boundary contract:

* Adds NO authority of its own.  There is no bootstrap, no persistence, no
  session resolution and no backend call on this surface: the React bundle
  renders deterministic synthetic fixtures that are labelled as demo data in
  the UI itself.
* The canonical server-rendered surfaces stay untouched and authoritative:
  ``/radar/**`` (app.radar_ui), ``/crypto`` (app.crypto_ui), ``/roadmap``
  (app.protocol_ui) and the home page.  This route is one additional
  same-origin surface, never a replacement or redirect for them.
* Same-origin assets only (``/static/react/**``).  No inline script and no
  inline JSON — the bundle reads its configuration from data attributes,
  matching the UX-01 React PoC host-page contract (react_poc_router.py).
* Public by design: no authentication is required because the surface exposes
  only presentation state and labelled synthetic fixtures, and its footer
  links navigate to existing canonical host destinations without activating
  any capability.

Routing architecture note (GitHub integration V1): page-level routing stays
with the canonical FastAPI route table (this ``GET /v2/non-model`` route);
within the experience the Concept B component navigates via URL hash, which is
the established in-app navigation pattern of the host React application
("sections live in the URL hash, so Back/Forward and direct refresh work").
Direct entry (``/v2/non-model#/radar``), refresh and browser Back/Forward all
resolve inside the component; unsupported hashes render an explicit fallback.
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.utils.workbook_flag import env_flag

router = APIRouter()

NONMODEL_ASSET_VERSION = "conceptb-v1"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates", "v2"))


def nonmodel_preview_enabled() -> bool:
    """Admission gate: absent/empty → OFF (the route stays non-public).

    The Concept B preview is a design surface, not a deployed product: an
    ordinary deployment of main must NOT expose it.  Enabling it requires the
    explicit environment contract below, evaluated per request like every
    other FINCO React surface flag.
    """
    return env_flag("FINCO_NONMODEL_PREVIEW", default=False)


@router.get("/non-model", response_class=HTMLResponse)
async def nonmodel_experience_page():
    """Serve the Concept B NON-MODEL experience host page (gated, read-only)."""
    if not nonmodel_preview_enabled():
        return JSONResponse(
            {"ok": False, "code": "NONMODEL_PREVIEW_DISABLED"},
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    html = _templates.get_template("nonmodel_host.html").render(
        asset_version=NONMODEL_ASSET_VERSION,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
