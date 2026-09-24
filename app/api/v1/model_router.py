"""A3 Model Reference API router — read-only GET endpoints.

HTTP status mapping:
  200  OK           — data returned
  404  Not Found    — key not in canonical supported set (exact membership only)

Supported keys: generic_solar_reference, generic_wind_reference.
Everything else (including storage, aliases, invalid format) → 404.

All route handlers are synchronous (def) so FastAPI dispatches to a threadpool.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1 import model_reference as _ref
from app.api.v1.schemas import (
    API_VERSION,
    ApiErrorEnvelope,
    ModelReferenceEnvelope,
    ModelReferenceListEnvelope,
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
