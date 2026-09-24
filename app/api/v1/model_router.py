"""A3/A4 Model Reference API router — read-only GET endpoints + A4 preview POST.

HTTP status mapping:
  200  OK           — data returned
  400  Bad Request  — invalid preview request (A4 only)
  404  Not Found    — key not in canonical supported set (exact membership only)

Supported keys: generic_solar_reference, generic_wind_reference.
Everything else (including storage, aliases, invalid format) → 404.

All route handlers are synchronous (def) so FastAPI dispatches to a threadpool.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1 import model_preview as _preview
from app.api.v1 import model_reference as _ref
from app.api.v1.schemas import (
    API_VERSION,
    ApiErrorEnvelope,
    ModelReferenceEnvelope,
    ModelReferenceListEnvelope,
    ModelReferencePreviewEnvelope,
    ModelReferencePreviewRequest,
)

router = APIRouter()


def _not_found(key: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "api_version": API_VERSION,
            "error": "MODEL_REFERENCE_NOT_FOUND",
            "detail": "No canonical model reference found for the requested key.",
        },
    )


def _preview_invalid(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "api_version": API_VERSION,
            "error": "MODEL_PREVIEW_REQUEST_INVALID",
            "detail": detail,
        },
    )


# ── GET /api/v1/model/references ──────────────────────────────────────────────

@router.get(
    "/model/references",
    response_model=ModelReferenceListEnvelope,
)
def list_model_references():
    """List all canonical model references."""
    data = _ref.build_references_list_data()
    return ModelReferenceListEnvelope(state="AVAILABLE", data=data)


# ── GET /api/v1/model/references/{reference_key} ──────────────────────────────

@router.get(
    "/model/references/{reference_key}",
    response_model=ModelReferenceEnvelope,
    responses={404: {"model": ApiErrorEnvelope}},
)
def get_model_reference(reference_key: str):
    """Return full grouped reference detail for one canonical reference."""
    if not _ref.is_supported_key(reference_key):
        return _not_found(reference_key)
    pi = _ref.get_pi(reference_key)
    data = _ref.build_reference_detail_data(reference_key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=reference_key, data=data)


# ── GET /api/v1/model/references/{reference_key}/capex ───────────────────────

@router.get(
    "/model/references/{reference_key}/capex",
    response_model=ModelReferenceEnvelope,
    responses={404: {"model": ApiErrorEnvelope}},
)
def get_model_reference_capex(reference_key: str):
    """Return canonical CAPEX items for one reference."""
    if not _ref.is_supported_key(reference_key):
        return _not_found(reference_key)
    pi = _ref.get_pi(reference_key)
    data = _ref.build_reference_capex_data(reference_key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=reference_key, data=data)


# ── GET /api/v1/model/references/{reference_key}/opex ────────────────────────

@router.get(
    "/model/references/{reference_key}/opex",
    response_model=ModelReferenceEnvelope,
    responses={404: {"model": ApiErrorEnvelope}},
)
def get_model_reference_opex(reference_key: str):
    """Return canonical OPEX items for one reference."""
    if not _ref.is_supported_key(reference_key):
        return _not_found(reference_key)
    pi = _ref.get_pi(reference_key)
    data = _ref.build_reference_opex_data(reference_key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=reference_key, data=data)


# ── POST /api/v1/model/references/{reference_key}/preview ────────────────────

@router.post(
    "/model/references/{reference_key}/preview",
    response_model=ModelReferencePreviewEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
    },
)
def post_model_reference_preview(
    reference_key: str,
    body: ModelReferencePreviewRequest,
) -> JSONResponse | ModelReferencePreviewEnvelope:
    """Stateless capacity-scaling preview for one canonical reference.

    Returns scaled CAPEX/OPEX seed rows and preserved reference assumptions
    for the requested capacity_mw. No project is created. No model runs.
    """
    if not _ref.is_supported_key(reference_key):
        return _not_found(reference_key)
    extra = body.model_extra
    if extra:
        extra_keys = ", ".join(sorted(extra.keys()))
        return _preview_invalid(
            f"Unexpected field(s): {extra_keys}. Only capacity_mw is accepted."
        )
    capacity_mw, err = _preview.validate_capacity_mw(body.capacity_mw)
    if err:
        return _preview_invalid(err)
    data = _preview.build_preview_response_data(reference_key, capacity_mw)
    return ModelReferencePreviewEnvelope(
        state="AVAILABLE",
        reference_key=reference_key,
        data=data,
    )
