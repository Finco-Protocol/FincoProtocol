"""FINCO API v1.1 — Public R-LIVE read-only surface.

Three unauthenticated endpoints only. No project list, no exports, no XLSX,
no validation, no run-certificate, no institutional project APIs.

Mounted in main_web.py under /api/v1.1 (alongside the existing /api/v1 surface).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1_1.schemas import InstitutionalEnvelope

router = APIRouter()


@router.get("/radar/r-live/assets")
def list_r_live_assets():
    """List reviewed identities — not a symbol-based runtime selector."""
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    assets = [
        {
            "canonical_id": p.asset_key.canonical_id,
            "economic_asset_uid": p.economic_asset_uid,
            "display_symbol": p.symbol,
            "authority_version": p.authority_version,
            "source": "Direct On-Chain",
        }
        for p in APPROVED_RLIVE_ASSETS.values()
    ]
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(state="AVAILABLE", data={"assets": assets}).model_dump(),
    )


@router.get("/radar/r-live/{uid}/history")
def get_r_live_history(uid: str, limit: int = 30):
    """Read explicitly historical B1.3 evidence for an exact approved identity.

    persist_history=False: this route never writes history.
    UID must be exact canonical_id — no ticker/fuzzy lookup.
    """
    from app.radar_rwa.r_live_service import read_r_live_history
    try:
        points = read_r_live_history(uid, limit=limit)
    except ValueError:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={"reason": "ASSET_OR_LIMIT_INVALID"},
            ).model_dump(),
        )
    except Exception:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={"reason": "HISTORY_UNAVAILABLE"},
            ).model_dump(),
        )
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE",
            data={"history_kind": "HISTORICAL", "points": points},
        ).model_dump(),
    )


@router.get("/radar/r-live/{uid}")
def get_r_live(uid: str):
    """Return R-LIVE exact AssetKey reference data.

    Delegates to app.radar_rwa.r_live_service (read-only, zero history writes).
    UID must be exact canonical_id — no ticker/fuzzy identity.
    No user session required: R-LIVE is a reference surface.
    """
    from app.api.v1_1 import institutional as _svc
    state, data = _svc.get_r_live(uid)
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(state=state, data=data).model_dump(),
    )
