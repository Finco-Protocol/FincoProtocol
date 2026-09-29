"""FINCO API v1.1 — Public R-LIVE read-only surface.

Six unauthenticated endpoints only. No project list, no exports, no XLSX,
no validation, no run-certificate, no institutional project APIs.

Mounted in main_web.py under /api/v1.1 (alongside the existing /api/v1 surface).
"""
from __future__ import annotations

import json
import os
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1_1.schemas import InstitutionalEnvelope

router = APIRouter()

# Process-wide gate: at most this many concurrent batch acquisitions.
# Each acquisition uses _CURRENT_WORKERS=2 RPC workers internally.
# Prevents unbounded upstream fan-out under simultaneous /current requests.
_MAX_CONCURRENT_ACQUISITIONS = 2
_ACQUISITION_GATE = threading.BoundedSemaphore(_MAX_CONCURRENT_ACQUISITIONS)


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
    """Stream all approved R-LIVE assets as NDJSON; one line per asset as it completes.

    ONE registry fetch and ONE shared RPC transport per request.
    Process-wide acquisition gate prevents unbounded concurrent upstream work.
    Zero history writes. Unauthenticated reference surface.

    Response: application/x-ndjson
    Each line: {"canonical_id": "...", "display_symbol": "...", "state": "...", "data": {...}}
    On RPC not configured: single JSON object {"state": "UNAVAILABLE", "reason": "..."}
    On gate full: all-UNAVAILABLE stream with reason ACQUISITION_GATE_FULL.
    """
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={"reason": "RPC_NOT_CONFIGURED"},
            ).model_dump(),
            headers={"Cache-Control": "no-store"},
        )

    def _stream():
        from app.radar_rwa.r_live_service import collect_r_live_batch
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID as _ids
        from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS

        acquired = _ACQUISITION_GATE.acquire(blocking=False)
        if not acquired:
            # Gate full: emit UNAVAILABLE for all assets rather than queueing
            for policy in APPROVED_RLIVE_ASSETS.values():
                row = {
                    "canonical_id": policy.asset_key.canonical_id,
                    "display_symbol": policy.symbol,
                    "state": "UNAVAILABLE",
                    "data": {"reason": "ACQUISITION_GATE_FULL"},
                }
                yield json.dumps(row, separators=(",", ":")) + "\n"
            return

        try:
            for canonical_id, state, data in collect_r_live_batch(rpc_url=rpc_url):
                policy = _ids.get(canonical_id)
                row = {
                    "canonical_id": canonical_id,
                    "display_symbol": policy.symbol if policy else None,
                    "state": state,
                    "data": data,
                }
                yield json.dumps(row, separators=(",", ":")) + "\n"
        except Exception:
            row = {"state": "UNAVAILABLE", "reason": "BATCH_ACQUISITION_FAILED"}
            yield json.dumps(row, separators=(",", ":")) + "\n"
        finally:
            _ACQUISITION_GATE.release()

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/radar/r-live/history/ranges")
def get_all_r_live_ranges():
    """One read-only landing summary response for all exact approved identities.

    Delegates to canonical read_r_live_ranges → read_r_live_range_summary_readonly.
    Uses collected_at clock. Zero writes. Unauthenticated reference surface.

    Response: {"state": "AVAILABLE", "data": {"history_kind": "HISTORICAL", "assets": {...}}}
    """
    from app.radar_rwa.r_live_service import read_r_live_ranges
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    ranges: dict = {}
    for policy in APPROVED_RLIVE_ASSETS.values():
        key = policy.asset_key.canonical_id
        try:
            ranges[key] = read_r_live_ranges(key)
        except Exception:
            ranges[key] = {"reason": "HISTORY_UNAVAILABLE"}
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE",
            data={"history_kind": "HISTORICAL", "assets": ranges},
        ).model_dump(),
        headers={"Cache-Control": "no-store"},
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


@router.get("/radar/r-live/{uid}/history/ranges")
def get_r_live_ranges(uid: str):
    """Read-only complete 1h/24h B1.3 premium summaries by collection clock.

    Delegates to canonical read_r_live_ranges → read_r_live_range_summary_readonly.
    Uses collected_at; digest-invalid history fails closed. Zero writes.
    UID must be exact canonical_id — no ticker/fuzzy lookup.
    """
    from app.radar_rwa.r_live_service import read_r_live_ranges
    try:
        ranges = read_r_live_ranges(uid)
    except ValueError:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={"reason": "ASSET_UID_INVALID"},
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
            data={"history_kind": "HISTORICAL", **ranges},
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
