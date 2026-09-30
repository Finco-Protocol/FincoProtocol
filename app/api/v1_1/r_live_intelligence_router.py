"""Experimental read-only JEV Radar Intelligence route (V1.1).

Separate from ``r_live_public_router`` so the reviewed six-route public R-LIVE contract is
unchanged. GET performs no history write, no model/engine call, no Verify write and no
certificate issuance. In OFF and SHADOW modes the route makes zero Jev calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.v1_1.schemas import InstitutionalEnvelope
from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
from app.radar_rwa.jev_intelligence.contracts import (DISCLOSURE, FEATURE_SCHEMA_VERSION,
                                                       QUESTION_SCHEMA_VERSION, JevMode)

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store"}


def _envelope(state: str, data: dict) -> JSONResponse:
    return JSONResponse(status_code=200, headers=_HEADERS,
                        content=InstitutionalEnvelope(state=state, data=data).model_dump())


def _not_exposed(config: JevIntelligenceConfig, canonical_id: str, reason: str) -> JSONResponse:
    return _envelope("DISABLED", {
        "state": "DISABLED", "reason": reason, "label": "EXPERIMENTAL", "answers": None,
        "canonical_identity": {"canonical_id": canonical_id, "economic_asset_uid": None},
        "mode": config.mode.value,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "disclosure": DISCLOSURE,
    })


@router.get("/radar/r-live/{canonical_id}/intelligence")
def get_r_live_intelligence(canonical_id: str, request: Request):
    config = JevIntelligenceConfig.from_env()
    if config.mode is JevMode.OFF:
        return _not_exposed(config, canonical_id, "JEV_INTELLIGENCE_DISABLED")
    if config.mode is JevMode.SHADOW:  # shadow evaluates via operator jobs, never via public GET
        return _not_exposed(config, canonical_id, "JEV_SHADOW_MODE_NOT_EXPOSED")
    from app.runtime.client_rate_limit import enforce as _enforce_client
    limited = _enforce_client(request, "jev_intelligence")
    if limited is not None:
        return limited
    from app.radar_rwa.jev_intelligence.service import evaluate_intelligence
    result = evaluate_intelligence(canonical_id, config=config)
    return _envelope(result.state.value, result.to_public_dict())
