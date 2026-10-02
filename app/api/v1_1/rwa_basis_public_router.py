"""FINCO API v1.1 — Public RWA Basis read-only surface.

Separate from the frozen seven-family R-LIVE public router. This module adds
no acquisition, execution, identity, wallet, signing, custody, or write path.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1_1.schemas import InstitutionalEnvelope

router = APIRouter()
_CACHE_HEADERS = {"Cache-Control": "no-store"}


@router.get("/radar/rwa-basis")
def list_rwa_basis():
    """Read the derived RWA Basis monitor from canonical snapshot/history."""
    from app.radar_rwa.rwa_basis import build_rwa_basis_monitor
    try:
        monitor = build_rwa_basis_monitor()
    except Exception:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={
                    "schema_version": "finco-rwa-basis-v1",
                    "reason": "RWA_BASIS_UNAVAILABLE",
                    "records": [],
                },
            ).model_dump(),
            headers=_CACHE_HEADERS,
        )
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state=monitor["state"],
            data={key: value for key, value in monitor.items() if key != "state"},
        ).model_dump(),
        headers=_CACHE_HEADERS,
    )


@router.get("/radar/rwa-basis/{economic_asset_uid}")
def get_rwa_basis(economic_asset_uid: str):
    """Exact economic_asset_uid lookup only; no ticker/name fallback."""
    from app.radar_rwa.rwa_basis import get_rwa_basis_record
    try:
        status, data = get_rwa_basis_record(economic_asset_uid)
    except Exception:
        status_value = "UNAVAILABLE"
        data = {
            "schema_version": "finco-rwa-basis-v1",
            "economic_asset_uid": economic_asset_uid,
            "evaluation_status": "UNAVAILABLE",
            "reason": "RWA_BASIS_UNAVAILABLE",
        }
    else:
        status_value = status.value
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(state=status_value, data=data).model_dump(),
        headers=_CACHE_HEADERS,
    )
