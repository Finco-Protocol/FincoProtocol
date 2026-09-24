"""A3 Model Reference API router — read-only GET endpoints.

HTTP status mapping:
  200  OK           — data returned
  400  Bad Request  — invalid reference key format
  404  Not Found    — key valid-format but not canonical

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


def _key_invalid(key: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "api_version": API_VERSION,
            "error": "REFERENCE_KEY_INVALID",
            "reference_key": key,
            "detail": detail,
        },
    )


def _not_found(key: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "api_version": API_VERSION,
            "error": "REFERENCE_NOT_FOUND",
            "reference_key": key,
            "detail": f"No canonical reference found for key={key!r}",
        },
    )


_KEY_FORMAT_DETAIL = "Reference key must match ^[a-z][a-z0-9_]{0,63}$."


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
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
    },
)
def get_model_reference(reference_key: str):
    """Return template metadata for one canonical reference."""
    key = _ref.validate_reference_key(reference_key)
    if key is None:
        return _key_invalid(reference_key, _KEY_FORMAT_DETAIL)
    if key not in _ref.VALID_REFERENCE_KEYS:
        return _not_found(key)
    pi = _ref.get_pi(key)
    data = _ref.build_reference_template_data(key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=key, data=data)


# ── GET /api/v1/model/references/{reference_key}/capex ───────────────────────

@router.get(
    "/model/references/{reference_key}/capex",
    response_model=ModelReferenceEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
    },
)
def get_model_reference_capex(reference_key: str):
    """Return canonical CAPEX items for one reference."""
    key = _ref.validate_reference_key(reference_key)
    if key is None:
        return _key_invalid(reference_key, _KEY_FORMAT_DETAIL)
    if key not in _ref.VALID_REFERENCE_KEYS:
        return _not_found(key)
    pi = _ref.get_pi(key)
    data = _ref.build_reference_capex_data(key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=key, data=data)


# ── GET /api/v1/model/references/{reference_key}/opex ────────────────────────

@router.get(
    "/model/references/{reference_key}/opex",
    response_model=ModelReferenceEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
    },
)
def get_model_reference_opex(reference_key: str):
    """Return canonical OPEX items for one reference."""
    key = _ref.validate_reference_key(reference_key)
    if key is None:
        return _key_invalid(reference_key, _KEY_FORMAT_DETAIL)
    if key not in _ref.VALID_REFERENCE_KEYS:
        return _not_found(key)
    pi = _ref.get_pi(key)
    data = _ref.build_reference_opex_data(key, pi)
    return ModelReferenceEnvelope(state="AVAILABLE", reference_key=key, data=data)
