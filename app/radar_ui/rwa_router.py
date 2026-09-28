"""Read-only FINCO Radar RWA browser surface."""
from __future__ import annotations

from datetime import datetime, timezone
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_rwa.service import RwaDashboardService
from app.radar_rwa.bnb_service import BnbRwaDashboardService, serialize_bnb_snapshot
from app.radar_rwa.bnb_snapshot import unavailable_bnb_snapshot
from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore
from app.radar_rwa.r_live_service import collect_aapl_r_live
from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_policy import AAPL_KEY

router = APIRouter()
_templates = Jinja2Templates(directory="app/templates")
_rwa_service = RwaDashboardService()
_bnb_service = BnbRwaDashboardService()


@router.get("/radar/crypto/rwa/r-live/aapl/snapshot")
async def radar_r_live_aapl_snapshot():
    """Read-only exact AAPL reference; never infer an RPC endpoint or pool."""
    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        return {"state": "UNAVAILABLE", "reason": "RPC_NOT_CONFIGURED"}
    try:
        result = await run_in_threadpool(lambda: collect_aapl_r_live(rpc_url=rpc_url))
    except Exception:
        return {"state": "UNAVAILABLE", "reason": "R_LIVE_EVIDENCE_UNAVAILABLE"}
    premium = result.authority.premium
    basis = result.authority.underlying
    current = (result.onchain.state is AuthorityState.AVAILABLE
               and premium.state is AuthorityState.AVAILABLE
               and basis.state is AuthorityState.AVAILABLE)
    state = ("AVAILABLE" if current else "STALE" if AuthorityState.STALE in (
        result.onchain.state, premium.state, basis.state) else "UNAVAILABLE")
    observed = result.onchain.observed_at if current else None
    age = max(0, int((datetime.now(timezone.utc) - observed).total_seconds())) if observed else None
    return {
        "state": state,
        "source_label": "Direct On-Chain",
        "observation_age_seconds": age,
        "observed_at": observed.isoformat() if observed else None,
        "reason": None if current else premium.reason or result.onchain.reason or basis.reason,
        "reference": result.onchain.to_evidence_dict() if current else None,
        "robinhood_basis": {"state": basis.state.value,
                            "price_usd_per_token": str(basis.price_usd_per_token) if current else None,
                            "observed_at": basis.observed_at.isoformat() if current else None},
        "reference_premium": {"state": premium.state.value,
                              "value_bps": str(premium.value_bps) if current else None,
                              "reason": premium.reason},
        "history_digest": result.history_digest if current else None,
    }


@router.get("/radar/crypto/rwa/r-live/aapl/history")
async def radar_r_live_aapl_history(economic_asset_uid: str, contract_address: str):
    """Read existing append-only B1.3 ledger by exact UID and deployment."""
    try:
        uid = normalize_asset_uid(economic_asset_uid)
        key = AssetKey(4663, contract_address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_EXACT_IDENTITY") from exc
    if key != AAPL_KEY:
        raise HTTPException(status_code=400, detail="UNAPPROVED_EXACT_ASSETKEY")
    try:
        def read():
            store = BnbIntelligenceHistoryStore(allowed_chain_id=4663)
            try:
                return store.read(uid, key)
            finally:
                store.close()
        points = await run_in_threadpool(read)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="HISTORY_UNAVAILABLE") from exc
    return {"economic_asset_uid": uid, "asset_key": key.canonical_id, "points": points}


def set_rwa_service(service) -> None:
    global _rwa_service
    _rwa_service = service


def set_bnb_service(service) -> None:
    global _bnb_service
    _bnb_service = service


def _bnb_payload_failure(exc: Exception) -> dict:
    return serialize_bnb_snapshot(unavailable_bnb_snapshot(
        datetime.now(timezone.utc), f"BNB_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
    ))


def _route_failure(exc: Exception) -> dict:
    return {
        "state": "UNAVAILABLE",
        "counts": [],
        "sections": [],
        "reason": f"RWA_DASHBOARD_UNAVAILABLE:{type(exc).__name__}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "publisher": "CoinGecko",
        "transport": "CoinGecko Demo API",
        "list_source_url": "https://docs.coingecko.com/demo/reference/rwas-list",
        "markets_source_url": "https://docs.coingecko.com/demo/reference/rwas-markets",
    }


@router.get("/radar/crypto/rwa", response_class=HTMLResponse)
async def radar_crypto_rwa(request: Request):
    try:
        dashboard = await run_in_threadpool(_rwa_service.read_dashboard)
    except Exception as exc:  # noqa: BLE001 — browser boundary must fail closed
        dashboard = _route_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/rwa.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "crypto",
            "crypto_section": "rwa",
            "user": user,
        },
        status_code=200,
    )


@router.get("/radar/crypto/rwa/bnb/snapshot")
async def radar_crypto_rwa_bnb_snapshot():
    try:
        return await run_in_threadpool(_bnb_service.read_payload)
    except Exception as exc:  # read-only API boundary fails closed
        return _bnb_payload_failure(exc)


@router.get("/radar/crypto/rwa/bnb/history")
async def radar_crypto_rwa_bnb_history(economic_asset_uid: str, contract_address: str):
    """Network-free exact-identity history read; never search by symbol."""
    try:
        uid = normalize_asset_uid(economic_asset_uid)
        key = AssetKey(56, contract_address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_EXACT_IDENTITY") from exc
    try:
        points = await run_in_threadpool(lambda: _bnb_service.read_history(uid, key))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="HISTORY_UNAVAILABLE") from exc
    return {"economic_asset_uid": uid, "asset_key": key.canonical_id, "points": points}


@router.get("/radar/crypto/rwa/bnb", response_class=HTMLResponse)
async def radar_crypto_rwa_bnb(request: Request):
    try:
        dashboard = await run_in_threadpool(_bnb_service.read_payload)
    except Exception as exc:  # browser boundary must not leak provider diagnostics
        dashboard = _bnb_payload_failure(exc)

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/rwa_bnb.html",
        context={
            "dashboard": dashboard,
            "radar_domain": "crypto",
            "crypto_section": "rwa",
            "user": user,
        },
        status_code=200,
    )
