"""Public, read-only Trust & Readiness pages (WF-10A).

Every route is GET-only, needs no sign-in, reads nothing from the database and sets no
cookie. Content comes from ``app.trust_readiness.registry`` and from live repository
authorities (``projection``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.trust_readiness import projection as P
from app.trust_readiness import registry as R
from app.trust_readiness.contracts import STATUS_LABEL

router = APIRouter()
TRUST_PREFIX = "/trust"

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))
_LABELS = {s.value: label for s, label in STATUS_LABEL.items()}


@dataclass(frozen=True)
class TrustPage:
    slug: str
    path: str
    nav: str
    title: str
    lede: str
    template: str


PAGES: tuple[TrustPage, ...] = (
    TrustPage("overview", "/trust", "Overview", "Trust and readiness",
              "What the FINCO Model product does about security, data and release readiness, and how sure we are.",
              "trust/index.html"),
    TrustPage("security", "/trust/security", "Security", "Product security overview",
              "The security controls the product has today, with the code and test behind each one.",
              "trust/security.html"),
    TrustPage("access", "/trust/access-controls", "Access controls", "Authentication and tenant-control audit",
              "How people sign in today, and how one user's data is separated from another's.",
              "trust/access.html"),
    TrustPage("data", "/trust/data-handling", "Data handling", "Data handling and privacy",
              "What the product stores, where, and what it can contain.",
              "trust/data-handling.html"),
    TrustPage("retention", "/trust/retention", "Retention", "Retention and deletion inventory",
              "How long each category of data is kept and how it is removed.",
              "trust/retention.html"),
    TrustPage("support", "/trust/support-matrix", "Support matrix", "Supported features and known limitations",
              "Which verticals and capabilities are live, in preview or not available.",
              "trust/support-matrix.html"),
    TrustPage("evidence", "/trust/run-evidence", "Run evidence", "Run evidence and integrity",
              "What a run check proves, what a signed certificate proves, and what neither proves.",
              "trust/run-evidence.html"),
    TrustPage("readiness", "/trust/readiness", "Release readiness", "Release-readiness checklist",
              "What is done, what is proposed and what is waiting on legal or operational decisions.",
              "trust/readiness.html"),
    TrustPage("gaps", "/trust/known-gaps", "Known gaps", "Known gaps",
              "Verified deviations from what a reader would reasonably expect, and what is not claimed.",
              "trust/known-gaps.html"),
    TrustPage("legal", "/trust/legal", "Legal documents", "Legal documents",
              "Terms, privacy notice and data processing agreement: not published.",
              "trust/legal.html"),
)
_BY_SLUG = {p.slug: p for p in PAGES}

_ACCESS_GAPS = ("gap.csrf_login_only", "gap.sessions_not_revocable", "gap.readyz_discloses_server_details",
                "gap.public_pages_set_a_cookie")
_RETENTION_GAPS = ("gap.demo_cleanup_skips_run_history", "gap.no_user_erasure_path")


def _gaps(keys):
    return [g for g in P.known_gaps_sorted() if g.key in keys]


def _grouped(areas):
    return {k: v for k, v in P.items_by_area(R.CONTROLS).items() if k in areas}


def _context(slug: str) -> dict:
    page = _BY_SLUG[slug]
    ctx = {
        "page_title": page.title, "page_lede": page.lede, "active": slug, "pages": PAGES,
        "labels": _LABELS, "legend": P.status_legend(), "area_labels": R.AREA_LABELS,
        "reviewed_on": R.REVIEWED_ON, "scope": R.SCOPE_STATEMENT, "not_claimed": R.NOT_CLAIMED,
    }
    all_items = R.all_items()
    if slug == "overview":
        ctx["counts"] = P.status_counts(all_items)
    elif slug == "security":
        ctx["groups"] = _grouped(("security_controls", "operations"))
    elif slug == "access":
        ctx["groups"] = _grouped(("access_control", "tenant_isolation"))
        ctx["gaps"] = _gaps(_ACCESS_GAPS)
    elif slug == "data":
        ctx["stores"] = R.DATA_STORES
    elif slug == "retention":
        ctx["stores"] = R.DATA_STORES
        ctx["gaps"] = _gaps(_RETENTION_GAPS)
    elif slug == "support":
        ctx["matrix"] = P.support_matrix()
        ctx["unavailable"] = P.unavailable_features()
    elif slug == "evidence":
        ctx["checks"] = P.integrity_checks()
        ctx["items"] = [i for i in R.CONTROLS if i.area == "run_evidence"]
    elif slug == "readiness":
        ctx["counts"] = P.status_counts(all_items)
        ctx["by_status"] = P.items_by_status(R.RELEASE_CHECKLIST)
    elif slug == "gaps":
        ctx["gaps"] = P.known_gaps_sorted()
    elif slug == "legal":
        ctx["docs"] = R.LEGAL_DOCUMENTS
    return ctx


def _render(request: Request, slug: str) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request, name=_BY_SLUG[slug].template, context=_context(slug),
        headers={"Cache-Control": "public, max-age=300"},
    )


def _register(page: TrustPage) -> None:
    async def view(request: Request, _slug: str = page.slug):
        return _render(request, _slug)

    view.__name__ = f"trust_{page.slug}"
    router.add_api_route(page.path, view, methods=["GET"], response_class=HTMLResponse,
                         include_in_schema=False)


for _page in PAGES:
    _register(_page)


@router.get("/trust/registry.json", include_in_schema=False)
async def trust_registry_json() -> JSONResponse:
    return JSONResponse(P.registry_json(), headers={"Cache-Control": "public, max-age=300"})
