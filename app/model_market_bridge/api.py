"""Experimental READ-ONLY API for the Model ↔ Market Bridge contract.

Design-spike surface, **DEFAULT OFF**: every endpoint fails closed with 404
unless ``FINCO_MODEL_MARKET_BRIDGE_API_ENABLED`` is explicitly enabled in
the environment.  When enabled it exposes evaluation of fixture-backed
bindings only — no mutation, no admin CRUD, no Verify promotion, and no
production bindings.  Responses are typed fail-closed decisions;
UNAVAILABLE/UNKNOWN states are explicit.

Not part of any stable API contract; may change or be removed with the
experimental bridge module.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .contracts import BindingStatus, ReasonCode
from .registry import BridgeRegistry

router = APIRouter()

_ENABLED_ENV = "FINCO_MODEL_MARKET_BRIDGE_API_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Bounded-input contract for the validate spike: known keys only, and every
# value size-capped.  Oversized/unknown input is MALFORMED_BINDING, never an
# unbounded public body parse.
_ALLOWED_KEYS = frozenset({
    "model_asset_uid", "model_asset_kind", "economic_asset_uid", "chain_id",
    "contract_address", "deployment_type", "venue",
    "deployment_source_authority", "market_evidence_authority",
    "market_evidence_ref", "observed_at", "provenance_type", "provenance_ref",
})
_MAX_VALUE_LEN = 256
_MAX_BODY_KEYS = len(_ALLOWED_KEYS)


def _enabled() -> bool:
    return os.getenv(_ENABLED_ENV, "0").strip().lower() in _TRUTHY


def _disabled_response() -> JSONResponse:
    return JSONResponse(status_code=404, content={
        "api_version": "v1.1",
        "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
        "error": "SURFACE_DISABLED",
        "detail": (
            "The experimental Model ↔ Market Bridge API is disabled in this "
            "environment (default OFF)."
        ),
    })


def _fixture_registry() -> BridgeRegistry:
    """Synthetic fixture registry for the read-only spike.

    Deliberately synthetic: no production binding is exposed through this
    surface, and nothing here creates or promotes bindings.
    """
    from .fixtures import build_fixture_registry

    return build_fixture_registry()


@router.get("/model-market-bindings/{model_asset_uid}", include_in_schema=False)
def get_model_market_binding(model_asset_uid: str):
    """Evaluate the active binding of one Model asset (read-only, fail-closed)."""
    if not _enabled():
        return _disabled_response()
    from .fixtures import evaluate_model_asset

    decision = evaluate_model_asset(model_asset_uid)
    return JSONResponse(
        status_code=200,
        content={
            "api_version": "v1.1",
            "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
            "read_only": True,
            "model_asset_uid": model_asset_uid,
            "decision": {
                "status": decision.status.value,
                "reason": decision.reason.value,
                "binding_uid": decision.binding_uid or None,
                "lifecycle": decision.lifecycle.value,
                "evidence_state": decision.evidence_state.value,
                "detail": decision.detail,
            },
            "truth": {
                "source_proven_binding_is_not_verify": True,
                "production_verified_asset_count": 0,
            },
        },
    )


@router.post("/model-market-bindings/validate", include_in_schema=False)
async def validate_model_market_binding(request: Request):
    """Validate a candidate binding structure against the V1 contract.

    Bounded, read-only structural validation: known keys only, size-capped
    values, sanitized errors.  Nothing is persisted or promoted.
    """
    if not _enabled():
        return _disabled_response()

    from app.model_market_bridge import (
        BindingStatus, DeploymentIdentity, EvidenceState,
        MarketEvidenceReference, ModelAssetKind, ModelMarketBindingV1,
        ProvenanceType,
    )

    def _malformed(detail: str = "malformed candidate"):
        return JSONResponse(status_code=200, content={
            "api_version": "v1.1",
            "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
            "valid": False,
            "reason": ReasonCode.MALFORMED_BINDING.value,
            "detail": detail,
        })

    try:
        candidate = await request.json()
    except Exception:
        return _malformed("request body must be a JSON object")
    if not isinstance(candidate, dict):
        return _malformed("request body must be a JSON object")
    if len(candidate) > _MAX_BODY_KEYS:
        return _malformed("too many fields")
    unknown = set(candidate) - _ALLOWED_KEYS
    if unknown:
        return _malformed(f"unknown fields: {sorted(unknown)[:5]}")
    for key, value in candidate.items():
        if value is not None and len(str(value)) > _MAX_VALUE_LEN:
            return _malformed(f"field {key} exceeds the size limit")

    def _s(key: str, default: str = "") -> str:
        value = candidate.get(key)
        return default if value is None else str(value)

    try:
        chain_raw = _s("chain_id")
        binding = ModelMarketBindingV1(
            model_asset_uid=_s("model_asset_uid"),
            model_asset_kind=ModelAssetKind(_s("model_asset_kind")),
            economic_asset_uid=_s("economic_asset_uid"),
            deployment=DeploymentIdentity(
                chain_id=int(chain_raw) if chain_raw else 0,
                contract_address=_s("contract_address"),
                deployment_type=_s("deployment_type", "TOKEN"),
                venue=_s("venue"),
                source_authority=_s("deployment_source_authority"),
            ),
            evidence=MarketEvidenceReference(
                authority=_s("market_evidence_authority"),
                ref=_s("market_evidence_ref"),
                observed_at=datetime.fromisoformat(
                    _s("observed_at").replace("Z", "+00:00")),
                # The market authority owns evidence state; the validate
                # spike reports candidates as UNAVAILABLE (state unknown
                # until a canonical authority evaluates them).
                state=EvidenceState.UNAVAILABLE,
            ),
            provenance_type=ProvenanceType(_s("provenance_type")),
            provenance_ref=_s("provenance_ref"),
            status=BindingStatus.CANDIDATE,
        )
    except (ValueError, TypeError):
        # Sanitized: the contract error text is not echoed back.
        return _malformed("candidate fails MODEL_MARKET_BINDING_V1 structural contract")
    return JSONResponse(status_code=200, content={
        "api_version": "v1.1",
        "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
        "valid": True,
        "binding_uid": binding.binding_uid,
        "status": binding.status.value,
        "note": "Structural validation only. Nothing is persisted, source-proven, or promoted to FINCO Verify.",
    })
