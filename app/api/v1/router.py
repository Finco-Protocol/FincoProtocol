"""A1 Radar API router — versioned read-only JSON endpoints.

All routes are read-only GET endpoints.  No write, execution, or
simulation endpoints exist in A1.

HTTP status mapping:
  200  OK           — data returned; check envelope `state` for availability detail
  400  Bad Request  — invalid economic_asset_uid format
  404  Not Found    — UID valid but no canonical asset exists
  503  Unavailable  — asset registry source is unavailable

The equity fundamentals DB being unavailable is NOT a 503; it is
represented as `state: "SOURCE_UNAVAILABLE"` in the envelope with HTTP 200
so callers can distinguish registry failures from DB snapshot gaps.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1 import radar as _radar
from app.api.v1.errors import (
    AssetNotFoundError,
    AssetUidInvalidError,
    RegistryUnavailableError,
)
from app.api.v1.schemas import (
    API_VERSION,
    AssetListEnvelope,
    RadarEnvelope,
    freshness_out,
)

router = APIRouter()


def _uid_invalid(uid: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "api_version": API_VERSION,
            "error": "ASSET_UID_INVALID",
            "economic_asset_uid": uid,
            "detail": detail,
        },
    )


def _not_found(uid: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "api_version": API_VERSION,
            "error": "ASSET_NOT_FOUND",
            "economic_asset_uid": uid,
            "detail": f"No canonical asset found for uid={uid!r}",
        },
    )


def _registry_unavailable(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "api_version": API_VERSION,
            "error": "REGISTRY_UNAVAILABLE",
            "detail": detail,
        },
    )


# ── GET /api/v1/radar/assets ──────────────────────────────────────────────────

@router.get("/radar/assets", response_model=None)
async def list_radar_assets():
    """List all canonical Radar assets from the current registry snapshot."""
    try:
        records = _radar.list_assets()
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))
    data = _radar.build_asset_list_data(records)
    return AssetListEnvelope(
        state="AVAILABLE",
        data=data,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid} ─────────────────────────────

@router.get("/radar/assets/{economic_asset_uid}", response_model=None)
async def get_radar_asset(economic_asset_uid: str):
    """Return canonical identity for one asset by its economic_asset_uid."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))

    # Fetch equity identity from the fundamentals bundle (no extra DB session).
    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    data = _radar.build_identity_data(record, bundle.asset)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/fundamentals ────────────────

@router.get("/radar/assets/{economic_asset_uid}/fundamentals", response_model=None)
async def get_radar_fundamentals(economic_asset_uid: str):
    """Return latest TTM/quarterly/annual fundamentals + company profile."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    data = _radar.build_fundamentals_data(bundle)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    evidence = _radar.build_evidence_data(bundle)
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
        evidence=evidence,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/financials ──────────────────

@router.get("/radar/assets/{economic_asset_uid}/financials", response_model=None)
async def get_radar_financials(economic_asset_uid: str):
    """Return multi-period financial history (annual, quarterly, TTM)."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))

    history = _radar.get_history_bundle(record.token_symbol)
    data = _radar.build_financials_data(history)
    fr = freshness_out(history.freshness) if history.freshness else None
    return RadarEnvelope(
        state=history.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/corporate-actions ───────────

@router.get("/radar/assets/{economic_asset_uid}/corporate-actions", response_model=None)
async def get_radar_corporate_actions(economic_asset_uid: str):
    """Return recent dividend and stock split history."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    data = _radar.build_corporate_actions_data(bundle)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/evidence ───────────────────

@router.get("/radar/assets/{economic_asset_uid}/evidence", response_model=None)
async def get_radar_evidence(economic_asset_uid: str):
    """Return source lineage / evidence for one asset."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError as exc:
        return _registry_unavailable(str(exc))

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    data = _radar.build_evidence_data(bundle)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/meta ──────────────────────────────────────────────────────────

@router.get("/meta", response_model=None)
async def get_api_meta():
    """API version and capability declaration."""
    return {
        "api_version": API_VERSION,
        "capabilities": [
            "radar.assets.list",
            "radar.assets.identity",
            "radar.assets.fundamentals",
            "radar.assets.financials",
            "radar.assets.corporate_actions",
            "radar.assets.evidence",
        ],
    }
