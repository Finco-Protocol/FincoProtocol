"""FINCO API v1.1 — Public R-LIVE read-only surface.

Six unauthenticated endpoints only. No project list, no exports, no XLSX,
no validation, no run-certificate, no institutional project APIs.

Mounted in main_web.py under /api/v1.1 (alongside the existing /api/v1 surface).
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1_1.schemas import InstitutionalEnvelope
from app.radar_rwa.r_live_public_acquisition import (
    PUBLIC_RLIVE_ACQUISITION,
    R_LIVE_SERVICE_BUSY,
    RLiveBatchAcquisitionFailed,
    RLiveServiceBusy,
    current_acquisition_key,
)

router = APIRouter()
_R_LIVE_CACHE_HEADERS = {"Cache-Control": "no-store"}


@router.get("/radar/r-live/assets")
def list_r_live_assets():
    """List reviewed identities plus read-only collector operational health."""
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    from app.radar_rwa.collector_health import read_collector_health_readonly
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
    health = read_collector_health_readonly()
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE",
            data={"assets": assets, "collector_health": health.public_dict()},
        ).model_dump(),
        headers=_R_LIVE_CACHE_HEADERS,
    )


@router.get("/radar/r-live/snapshot")
def read_r_live_snapshot(request: Request):
    """Instant read-only latest-snapshot view of all approved R-LIVE assets.

    INSTANT R-LIVE UX: this endpoint reads the persistent latest-snapshot
    projection written by the background canonical collector. It performs
    ZERO live acquisition — no Robinhood API, no Robinhood Chain RPC, no
    Uniswap observe, no Chainlink fetch, no batch collection — so the page
    never waits on the chain. Freshness is re-evaluated at READ time
    against the canonical R-LIVE policy: evidence that aged out becomes
    STALE; incomplete evidence is UNAVAILABLE; timestamps are never
    rewritten. Cold start returns typed INITIALIZING immediately.
    """
    from app.radar_rwa.r_live_snapshot_view import build_snapshot_view

    view = build_snapshot_view()
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state=view["state"],
            data={k: v for k, v in view.items() if k != "state"},
        ).model_dump(),
        headers=_R_LIVE_CACHE_HEADERS,
    )


@router.get("/radar/r-live/current")
def stream_r_live_current(request: Request):
    """Stream current approved R-LIVE assets with bounded public acquisition.

    Identical simultaneous requests share one in-flight canonical batch. New
    distinct work is rejected with HTTP 429 when process capacity is exhausted.
    Operational SERVICE_BUSY is deliberately distinct from market UNAVAILABLE.
    Completed current values are not cached and evidence timestamps are never
    rewritten by this layer. Zero history writes. Unauthenticated reference surface.
    """
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID as _ids
    from app.runtime.client_rate_limit import enforce as _enforce_client

    limited = _enforce_client(request, "r_live_current")
    if limited is not None:
        return limited
    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE", data={"reason": "RPC_NOT_CONFIGURED"}
            ).model_dump(),
            headers=_R_LIVE_CACHE_HEADERS,
        )

    def _producer():
        from app.radar_rwa.r_live_service import collect_r_live_batch
        return collect_r_live_batch(rpc_url=rpc_url)

    try:
        subscription = PUBLIC_RLIVE_ACQUISITION.subscribe(
            current_acquisition_key(rpc_url), _producer
        )
    except RLiveServiceBusy:
        return JSONResponse(
            status_code=429,
            content={"state": "SERVICE_BUSY", "reason": R_LIVE_SERVICE_BUSY},
            headers=_R_LIVE_CACHE_HEADERS,
        )

    def _stream():
        try:
            for canonical_id, state, data in subscription:
                policy = _ids.get(canonical_id)
                row = {
                    "canonical_id": canonical_id,
                    "display_symbol": policy.symbol if policy else None,
                    "state": state,
                    "data": data,
                }
                yield json.dumps(row, separators=(",", ":")) + "\n"
        except RLiveBatchAcquisitionFailed:
            row = {"state": "UNAVAILABLE", "reason": "BATCH_ACQUISITION_FAILED"}
            yield json.dumps(row, separators=(",", ":")) + "\n"
        finally:
            subscription.close()

    return StreamingResponse(
        _stream(), media_type="application/x-ndjson", headers=_R_LIVE_CACHE_HEADERS
    )


@router.get("/radar/r-live/history/ranges")
def get_all_r_live_ranges():
    """One read-only landing summary response for all exact approved identities.

    Single-pass batch read over the canonical B1.3 history (one store read
    for all approved identities — same rows, ordering, digest verification
    and summaries as the per-asset read). Uses collected_at clock. Zero
    writes. Unauthenticated reference surface.
    """
    from app.radar_rwa.bnb_history import read_r_live_ranges_batch_readonly
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    pairs = [(policy.economic_asset_uid, policy.asset_key)
             for policy in APPROVED_RLIVE_ASSETS.values()]
    try:
        ranges = read_r_live_ranges_batch_readonly(pairs, include_series=True,
                                                   max_series_points=48)
    except Exception:
        ranges = {policy.asset_key.canonical_id: {"reason": "HISTORY_UNAVAILABLE"}
                  for policy in APPROVED_RLIVE_ASSETS.values()}
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE", data={"history_kind": "HISTORICAL", "assets": ranges}
        ).model_dump(),
        headers=_R_LIVE_CACHE_HEADERS,
    )


@router.get("/radar/r-live/{uid}/history")
def get_r_live_history(uid: str, limit: int = 30):
    """Read explicitly historical B1.3 evidence for an exact approved identity.

    persist_history=False: this route never writes history.
    UID must be exact canonical_id — no ticker/fuzzy identity.
    """
    from app.radar_rwa.r_live_service import read_r_live_history
    try:
        points = read_r_live_history(uid, limit=limit)
    except ValueError:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE", data={"reason": "ASSET_OR_LIMIT_INVALID"}
            ).model_dump(),
        )
    except Exception:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE", data={"reason": "HISTORY_UNAVAILABLE"}
            ).model_dump(),
        )
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE", data={"history_kind": "HISTORICAL", "points": points}
        ).model_dump(),
    )


@router.get("/radar/r-live/{uid}/history/ranges")
def get_r_live_ranges(uid: str):
    """Read-only complete 1h/24h B1.3 premium summaries by collection clock.

    Delegates to canonical read_r_live_ranges → read_r_live_range_summary_readonly.
    Uses collected_at; digest-invalid history fails closed. Zero writes.
    UID must be exact canonical_id — no ticker/fuzzy identity.
    """
    from app.radar_rwa.r_live_service import read_r_live_ranges
    try:
        ranges = read_r_live_ranges(uid)
    except ValueError:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE", data={"reason": "ASSET_UID_INVALID"}
            ).model_dump(),
        )
    except Exception:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE", data={"reason": "HISTORY_UNAVAILABLE"}
            ).model_dump(),
        )
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE", data={"history_kind": "HISTORICAL", **ranges}
        ).model_dump(),
    )


@router.get("/radar/r-live/{uid}")
def get_r_live(uid: str, request: Request):
    """Return R-LIVE exact AssetKey reference data.

    Delegates to app.radar_rwa.r_live_service (read-only, zero history writes).
    UID must be exact canonical_id — no ticker/fuzzy identity.
    No user session required: R-LIVE is a reference surface.
    """
    from app.api.v1_1 import institutional as _svc
    from app.runtime.client_rate_limit import enforce as _enforce_client
    limited = _enforce_client(request, "r_live_current")
    if limited is not None:
        return limited
    try:
        state, data = _svc.get_r_live(uid)
    except RLiveServiceBusy:
        return JSONResponse(
            status_code=429,
            content={"state": "SERVICE_BUSY", "reason": R_LIVE_SERVICE_BUSY},
            headers={**_R_LIVE_CACHE_HEADERS, "Retry-After": "5"},
        )
    try:  # Optional JEV SHADOW observation: enqueue-only, never blocks, never alters this response.
        from app.radar_rwa.jev_intelligence.shadow import observe as _jev_shadow_observe
        _jev_shadow_observe(uid, state, data)
    except Exception:
        pass
    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(state=state, data=data).model_dump(),
    )
