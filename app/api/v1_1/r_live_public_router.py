"""FINCO API v1.1 — Public R-LIVE read-only surface.

Five unauthenticated endpoints only. No project list, no exports, no XLSX,
no validation, no run-certificate, no institutional project APIs.

Mounted in main_web.py under /api/v1.1 (alongside the existing /api/v1 surface).
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1_1.schemas import InstitutionalEnvelope

router = APIRouter()


def _bps_range_str(points: list[dict], hours: float) -> str | None:
    """Compute lo/hi bps range over `hours` hours from B1.3 history points."""
    import time
    cutoff = time.time() - hours * 3600.0
    vals = []
    for p in points:
        raw = p.get("reference_premium_bps")
        if raw is None:
            continue
        obs = p.get("observed_at")
        if obs:
            try:
                from datetime import datetime
                t = datetime.fromisoformat(obs.replace("Z", "+00:00")).timestamp()
                if t < cutoff:
                    continue
            except Exception:
                continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    def _sign(v: float) -> str:
        return ("+" if v >= 0 else "") + f"{v:.1f}"
    return f"{_sign(lo)} / {_sign(hi)} bps"


@router.get("/radar/r-live/current")
def get_r_live_current():
    """Stream all approved R-LIVE assets as NDJSON; one line per asset as it completes.

    ONE registry fetch and ONE shared RPC transport per request.
    Zero history writes. Unauthenticated reference surface.

    Response: application/x-ndjson
    Each line: {"canonical_id": "...", "state": "AVAILABLE|STALE|UNAVAILABLE", "data": {...}}
    On RPC not configured: single JSON object {"state": "UNAVAILABLE", "reason": "RPC_NOT_CONFIGURED"}
    """
    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        return JSONResponse(
            status_code=200,
            content=InstitutionalEnvelope(
                state="UNAVAILABLE",
                data={"reason": "RPC_NOT_CONFIGURED"},
            ).model_dump(),
        )

    def _stream():
        from app.radar_rwa.r_live_service import collect_r_live_batch
        try:
            for canonical_id, state, data in collect_r_live_batch(rpc_url=rpc_url):
                row = {"canonical_id": canonical_id, "state": state, "data": data}
                yield json.dumps(row, separators=(",", ":")) + "\n"
        except Exception:
            row = {"state": "UNAVAILABLE", "reason": "BATCH_ACQUISITION_FAILED"}
            yield json.dumps(row, separators=(",", ":")) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.get("/radar/r-live/history/ranges")
def get_r_live_history_ranges():
    """Return 1h and 24h bps ranges for all approved assets from B1.3 history.

    ONE request replaces N per-asset history requests from the landing page.
    Read-only: zero writes. Unauthenticated reference surface.

    Response: {"state": "AVAILABLE", "data": {"ranges": {canonical_id: {range_1h, range_24h}}}}
    """
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    from app.radar_rwa.r_live_service import read_r_live_history

    ranges: dict[str, dict] = {}
    for canonical_id in APPROVED_BY_CANONICAL_ID:
        try:
            points = read_r_live_history(canonical_id, limit=100)
            ranges[canonical_id] = {
                "range_1h": _bps_range_str(points, 1.0),
                "range_24h": _bps_range_str(points, 24.0),
            }
        except Exception:
            ranges[canonical_id] = {"range_1h": None, "range_24h": None}

    return JSONResponse(
        status_code=200,
        content=InstitutionalEnvelope(
            state="AVAILABLE",
            data={"ranges": ranges},
        ).model_dump(),
    )


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
