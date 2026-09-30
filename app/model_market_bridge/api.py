"""Experimental READ-ONLY API for the Model ↔ Market Bridge contract.

Design-spike surface only.  It exposes evaluation of fixture-backed
bindings — no mutation, no admin CRUD, no Verify promotion.  Responses are
typed fail-closed decisions; UNAVAILABLE/UNKNOWN states are explicit.

Not part of any stable API contract; may change or be removed with the
experimental bridge module.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .contracts import BindingStatus, ReasonCode
from .registry import BridgeRegistry

router = APIRouter()


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
async def validate_model_market_binding(candidate: dict):
    """Validate a candidate binding structure against the V1 contract
    (read-only structural validation; nothing is persisted or promoted)."""
    from app.model_market_bridge import (
        BindingStatus, DeploymentIdentity, MarketEvidenceReference,
        ModelAssetKind, ModelMarketBindingV1, ProvenanceType, ReasonCode,
    )

    try:
        binding = ModelMarketBindingV1(
            model_asset_uid=str(candidate.get("model_asset_uid", "")),
            model_asset_kind=ModelAssetKind(str(candidate.get("model_asset_kind", ""))),
            economic_asset_uid=str(candidate.get("economic_asset_uid", "")),
            deployment=DeploymentIdentity(
                chain_id=int(candidate.get("chain_id", 0)),
                contract_address=str(candidate.get("contract_address", "")),
                deployment_type=str(candidate.get("deployment_type", "TOKEN")),
                venue=str(candidate.get("venue", "")),
                source_authority=str(candidate.get("deployment_source_authority", "")),
            ),
            evidence=MarketEvidenceReference(
                authority=str(candidate.get("market_evidence_authority", "")),
                ref=str(candidate.get("market_evidence_ref", "")),
                observed_at=datetime.fromisoformat(
                    str(candidate.get("observed_at", "")).replace("Z", "+00:00")),
            ),
            provenance_type=ProvenanceType(str(candidate.get("provenance_type", ""))),
            provenance_ref=str(candidate.get("provenance_ref", "")),
            status=BindingStatus.CANDIDATE,
        )
    except (ValueError, TypeError) as exc:
        return JSONResponse(status_code=200, content={
            "api_version": "v1.1",
            "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
            "valid": False,
            "reason": ReasonCode.MALFORMED_BINDING.value,
            "detail": str(exc),
        })
    return JSONResponse(status_code=200, content={
        "api_version": "v1.1",
        "surface": "EXPERIMENTAL_MODEL_MARKET_BRIDGE_V1",
        "valid": True,
        "binding_uid": binding.binding_uid,
        "status": binding.status.value,
        "note": "Structural validation only. Nothing is persisted, source-proven, or promoted to FINCO Verify.",
    })
