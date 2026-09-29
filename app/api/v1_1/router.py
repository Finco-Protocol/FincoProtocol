"""FINCO API v1.1 — Institutional Read-Only Surface router (Correction A).

Auth boundary: signed session cookie (finco_session or finco_demo).
X-User-Id header is NOT trusted — spoofed identity has zero authority.

HTTP status mapping:
  200  OK           — data returned; check envelope `state` for availability.
  401  Unauthorized — missing or invalid session.
  403  Forbidden    — valid session but project belongs to another user.
  404  Not Found    — project not found for this user.
  503  Unavailable  — authority layer temporarily unavailable (rare).

All handlers are synchronous (def) so FastAPI dispatches to a threadpool.
Schema version: institutional-v1.1.0
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse

from app.api.v1_1 import institutional as _svc
from app.api.v1_1.schemas import (
    API_VERSION,
    SCHEMA_VERSION,
    ApiErrorEnvelope,
    InstitutionalEnvelope,
    ProjectListEnvelope,
)

router = APIRouter()


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _resolve_user(request: Request) -> Optional[str]:
    """Resolve user_id from signed session cookie only.

    Never reads X-User-Id — spoofed headers have zero authority here.
    """
    from app.auth import resolve_request_session
    session = resolve_request_session(request)
    if session is None:
        return None
    return session.user_id


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=ApiErrorEnvelope(
            error="MISSING_USER_IDENTITY",
            detail="A valid signed session is required for institutional endpoints.",
        ).model_dump(),
    )


def _not_found(project_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ApiErrorEnvelope(
            error="PROJECT_NOT_FOUND",
            detail=f"No project found with id '{project_id}' for this user.",
            project_id=project_id,
        ).model_dump(),
    )


def _envelope(state: str, data: dict, project_id: Optional[str] = None,
              evidence: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state=state,
            project_id=project_id,
            data=data if data else None,
            evidence=evidence,
        ).model_dump(),
    )


def _unavailable_envelope(project_id: Optional[str], reason: str,
                          detail: str = "") -> JSONResponse:
    payload: dict = {"reason": reason}
    if detail:
        payload["detail"] = detail
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="UNAVAILABLE",
            project_id=project_id,
            data=payload,
        ).model_dump(),
    )


# ── GET /api/v1.1/supported-today ─────────────────────────────────────────────

@router.get("/supported-today")
def get_supported_today():
    """Return canonical PRODUCT_CAPABILITIES as the supported-today surface."""
    return JSONResponse(
        status_code=200,
        content={
            "api_version": API_VERSION,
            "schema_version": SCHEMA_VERSION,
            "state": "AVAILABLE",
            "data": _svc.get_supported_today(),
        },
    )


# ── GET /api/v1.1/projects ────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(request: Request):
    """List all non-archived projects for the authenticated user."""
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    try:
        data = _svc.get_projects_for_user(user_id)
    except Exception:
        return JSONResponse(
            status_code=503,
            content=ApiErrorEnvelope(
                error="SERVICE_UNAVAILABLE",
                detail="Project list temporarily unavailable.",
            ).model_dump(),
        )

    return JSONResponse(
        status_code=200,
        content=ProjectListEnvelope(
            state="AVAILABLE",
            data=data,
        ).model_dump(),
    )


# ── GET /api/v1.1/projects/{project_id}/last-run ──────────────────────────────

@router.get("/projects/{project_id}/last-run")
def get_last_run(project_id: str, request: Request):
    """Return canonical Last Run summary for a project.

    Correction A: state is AVAILABLE (committed run) or UNAVAILABLE (no run).
    STALE is not a valid state. Working Copy divergence exposed in run_identity.
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, data = _svc.get_last_run_summary(user_id, project_id)
    return _envelope(state, data, project_id=project_id)


# ── GET /api/v1.1/projects/{project_id}/run-identity ─────────────────────────

@router.get("/projects/{project_id}/run-identity")
def get_run_identity(project_id: str, request: Request):
    """Return run identity and certificate metadata for the canonical Last Run."""
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, data = _svc.get_run_identity(user_id, project_id)
    return _envelope(state, data, project_id=project_id)


# ── GET /api/v1.1/projects/{project_id}/run-certificate ──────────────────────

@router.get("/projects/{project_id}/run-certificate")
def get_run_certificate(project_id: str, request: Request):
    """Signed Run Certificate for the canonical committed Last Run.

    Authority separation: attests to provenance/integrity only — never a
    FINCO Verify claim.  No engine rerun; dirty Working Copy state does not
    alter the certified Last Run.  Fail-closed when no signing key is
    configured (SIGNING_KEY_UNAVAILABLE, 503).
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    project = get_project(project_id, user_id)
    if project is None:
        return _not_found(project_id)

    from app.api.v1_1 import institutional as _inst
    pr, ws = _inst._load_workspace(user_id, project_id)
    if pr is None:
        return _not_found(project_id)

    if getattr(ws, "user_id", None) != user_id and user_id != "1":
        return JSONResponse(
            status_code=403,
            content=ApiErrorEnvelope(
                error="FORBIDDEN",
                detail="This project belongs to another user.",
            ).model_dump(),
        )

    from app.services.run_certificate_service import (
        CertificateBuildUnavailable,
        SigningKeyUnavailable,
        issue_run_certificate,
    )
    try:
        certificate = issue_run_certificate(ws)
    except SigningKeyUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content=ApiErrorEnvelope(
                error=exc.REASON,
                detail="Run certificate signing is not configured on this deployment.",
            ).model_dump(),
        )
    except CertificateBuildUnavailable as exc:
        return JSONResponse(
            status_code=400,
            content=ApiErrorEnvelope(
                error=exc.REASON,
                detail=str(exc),
            ).model_dump(),
        )
    except Exception:
        return JSONResponse(
            status_code=503,
            content=ApiErrorEnvelope(
                error="CERTIFICATE_INTERNAL_ERROR",
                detail="Run certificate could not be produced.",
            ).model_dump(),
        )

    return _envelope("AVAILABLE", certificate, project_id=project_id)


# ── GET /api/v1.1/projects/{project_id}/kpis ─────────────────────────────────

@router.get("/projects/{project_id}/kpis")
def get_kpis(project_id: str, request: Request):
    """Return core institutional KPIs from the canonical Last Run.

    No model re-run. Values read from persisted last_runtime_summary.
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, data = _svc.get_kpis(user_id, project_id)
    return _envelope(state, data, project_id=project_id)


# ── GET /api/v1.1/projects/{project_id}/export-metadata ──────────────────────

@router.get("/projects/{project_id}/export-metadata")
def get_export_metadata(project_id: str, request: Request):
    """Return XLSX institutional export contract metadata (no file generated)."""
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, data = _svc.get_export_metadata(user_id, project_id)
    return _envelope(state, data, project_id=project_id)


# ── GET /api/v1.1/projects/{project_id}/export ───────────────────────────────

@router.get("/projects/{project_id}/export")
def get_export(project_id: str, request: Request):
    """Download XLSX institutional workbook for the canonical Last Run.

    Thin authenticated delegate to canonical Last Run XLSX export.
    Zero engine rerun. WC changes do not change the exported Last Run.
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    status_code, export_response = _svc.get_export_bytes(user_id, project_id)

    if hasattr(export_response, "has_error") and export_response.has_error():
        return HTMLResponse(
            content=export_response.error_content,
            status_code=export_response.status_code,
        )

    return StreamingResponse(
        iter([export_response.bytes_data]),
        media_type=export_response.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export_response.filename}"',
            "Content-Length": str(len(export_response.bytes_data)),
        },
    )


# ── GET /api/v1.1/projects/{project_id}/validation ───────────────────────────

@router.get("/projects/{project_id}/validation")
def get_validation(project_id: str, request: Request):
    """Return P1 institutional model validation for this project's vertical.

    Delegates to app.model_validation.runner.
    Runs against the canonical reference — not the user's Working Copy.
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, evidence = _svc.get_institutional_validation(user_id, project_id)
    return _envelope(state, {}, project_id=project_id, evidence=evidence)


# ── GET /api/v1.1/projects/{project_id}/verify ───────────────────────────────

@router.get("/projects/{project_id}/verify")
def get_verify(project_id: str, request: Request):
    """Return canonical Verify/evidence state for this project.

    Delegates to app.verified (asset_registry + composer).
    Fails closed when no source-proven binding exists in the registry.
    """
    user_id = _resolve_user(request)
    if not user_id:
        return _unauthorized()

    from app.persistence.projects_repository import get_project
    if get_project(project_id, user_id) is None:
        return _not_found(project_id)

    state, evidence = _svc.get_verify_state(user_id, project_id)
    return _envelope(state, {}, project_id=project_id, evidence=evidence)


# ── GET /api/v1.1/radar/r-live/{uid} ─────────────────────────────────────────

@router.get("/radar/r-live/{uid}")
def get_r_live(uid: str):
    """Return R-LIVE exact AssetKey reference data.

    Delegates to app.radar_rwa.r_live_service (read-only, zero history writes).
    UID must be exact canonical_id (chain:address) — no ticker/fuzzy identity.
    User session is NOT required: R-LIVE is a reference surface.
    """
    state, data = _svc.get_r_live(uid)
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state=state,
            data=data,
        ).model_dump(),
    )
