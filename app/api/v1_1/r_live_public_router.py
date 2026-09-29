"""FINCO API v1.1 — Public R-LIVE read-only surface.

Public reference endpoints only. No project list, no exports, no XLSX,
no validation, no run-certificate, no institutional project APIs.

Mounted in main_web.py under /api/v1.1 (alongside the existing /api/v1 surface).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1_1.schemas import InstitutionalEnvelope

router = APIRouter()
_CURRENT_WORKERS = 2  # Bounded; no global cache or unbounded public RPC fan-out.


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


@router.get("/radar/r-live/current")
def stream_r_live_current():
    """Stream each exact-policy current result as it completes; never write history."""
    from app.api.v1_1 import institutional as _svc
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    policies = tuple(APPROVED_RLIVE_ASSETS.values())

    def rows():
        with ThreadPoolExecutor(max_workers=_CURRENT_WORKERS) as executor:
            futures = {executor.submit(_svc.get_r_live, p.asset_key.canonical_id): p
                       for p in policies}
            for future in as_completed(futures):
                policy = futures[future]
                try:
                    state, data = future.result()
                except Exception:
                    state, data = "UNAVAILABLE", {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}
                yield json.dumps({"canonical_id": policy.asset_key.canonical_id,
                                  "display_symbol": policy.symbol,
                                  "state": state, "data": data},
                                 separators=(",", ":")) + "\n"

    return StreamingResponse(rows(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store"})


@router.get("/radar/r-live/history/ranges")
def get_all_r_live_ranges():
    """One read-only landing summary response for all exact approved identities."""
    from app.radar_rwa.r_live_service import read_r_live_ranges
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    ranges = {}
    for policy in APPROVED_RLIVE_ASSETS.values():
        key = policy.asset_key.canonical_id
        try:
            ranges[key] = read_r_live_ranges(key)
        except Exception:
            ranges[key] = {"reason": "HISTORY_UNAVAILABLE"}
    return JSONResponse(status_code=200, content=InstitutionalEnvelope(
        state="AVAILABLE", data={"history_kind": "HISTORICAL", "assets": ranges}).model_dump(),
        headers={"Cache-Control": "no-store"})


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


@router.get("/radar/r-live/{uid}/history/ranges")
def get_r_live_ranges(uid: str):
    """Read-only complete 1h/24h B1.3 premium summaries by collection clock."""
    from app.radar_rwa.r_live_service import read_r_live_ranges
    try:
        ranges = read_r_live_ranges(uid)
    except ValueError:
        return JSONResponse(status_code=200, content=InstitutionalEnvelope(
            state="UNAVAILABLE", data={"reason": "ASSET_UID_INVALID"}).model_dump())
    except Exception:
        return JSONResponse(status_code=200, content=InstitutionalEnvelope(
            state="UNAVAILABLE", data={"reason": "HISTORY_UNAVAILABLE"}).model_dump())
    return JSONResponse(status_code=200, content=InstitutionalEnvelope(
        state="AVAILABLE", data={"history_kind": "HISTORICAL", **ranges}).model_dump())


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
