"""A1/A2 Radar API router — versioned read-only JSON endpoints.

All GET routes are read-only.  The A2 POST route provides read-only
execution simulation analytics (no order submission or state mutation).

HTTP status mapping:
  200  OK           — data returned; check envelope `state` for availability detail
  400  Bad Request  — invalid economic_asset_uid format, or invalid simulation request
  404  Not Found    — UID valid but no canonical asset exists
  503  Unavailable  — asset registry source is unavailable

The equity fundamentals DB being unavailable is NOT a 503; it is
represented as `state: "SOURCE_UNAVAILABLE"` in the envelope with HTTP 200
so callers can distinguish registry failures from DB snapshot gaps.

All route handlers are synchronous (`def`, not `async def`) so FastAPI
dispatches them to a threadpool and does not block the ASGI event loop.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.api.v1 import execution as _execution
from app.api.v1 import radar as _radar
from app.radar_ui import composition as _composition
from app.api.v1.errors import (
    AssetNotFoundError,
    AssetUidInvalidError,
    RegistryUnavailableError,
)
from app.api.v1.schemas import (
    API_VERSION,
    ApiErrorEnvelope,
    AssetListEnvelope,
    ExecutionSimulationEnvelope,
    ExecutionSimulationRequest,
    RadarEnvelope,
    freshness_out,
)
from app.radar_runtime.contracts import RuntimeContractError

router = APIRouter()

_REGISTRY_UNAVAILABLE_DETAIL = "Asset registry is temporarily unavailable."

_ALLOWED_DIRECTIONS = frozenset({"BUY", "SELL"})
_ALLOWED_NOTIONALS = frozenset({"100", "1000"})


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


def _registry_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "api_version": API_VERSION,
            "error": "REGISTRY_UNAVAILABLE",
            "detail": _REGISTRY_UNAVAILABLE_DETAIL,
        },
    )


def _simulation_request_invalid(uid: Optional[str], detail: str) -> JSONResponse:
    content: dict = {
        "api_version": API_VERSION,
        "error": "SIMULATION_REQUEST_INVALID",
        "detail": detail,
    }
    if uid is not None:
        content["economic_asset_uid"] = uid
    return JSONResponse(status_code=400, content=content)


# ── GET /api/v1/radar/assets ──────────────────────────────────────────────────

@router.get(
    "/radar/assets",
    response_model=AssetListEnvelope,
    responses={503: {"model": ApiErrorEnvelope}},
)
def list_radar_assets():
    """List all canonical Radar assets from the current registry snapshot."""
    try:
        records = _radar.list_assets()
    except RegistryUnavailableError:
        return _registry_unavailable()
    data = _radar.build_asset_list_data(records)
    return AssetListEnvelope(
        state="AVAILABLE",
        data=data,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid} ─────────────────────────────

@router.get(
    "/radar/assets/{economic_asset_uid}",
    response_model=RadarEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def get_radar_asset(economic_asset_uid: str):
    """Return canonical identity for one asset by its economic_asset_uid.

    Top-level state is always AVAILABLE when the registry resolves the UID.
    The fundamentals_state field in data carries the equity DB availability.
    """
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    binding = _radar.bind_equity_identity(record, bundle)
    data = _radar.build_identity_data(record, bundle, binding)
    fr = freshness_out(bundle.freshness) if (binding == "BOUND" and bundle.freshness) else None
    return RadarEnvelope(
        state="AVAILABLE",
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/fundamentals ────────────────

@router.get(
    "/radar/assets/{economic_asset_uid}/fundamentals",
    response_model=RadarEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def get_radar_fundamentals(economic_asset_uid: str):
    """Return latest TTM/quarterly/annual fundamentals + company profile."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    binding = _radar.bind_equity_identity(record, bundle)
    if binding != "BOUND":
        return RadarEnvelope(
            state=binding,
            economic_asset_uid=uid,
            data={"availability": binding},
        )
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

@router.get(
    "/radar/assets/{economic_asset_uid}/financials",
    response_model=RadarEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def get_radar_financials(economic_asset_uid: str):
    """Return multi-period financial history (annual, quarterly, TTM)."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    history = _radar.get_history_bundle(record.token_symbol)
    binding = _radar.bind_equity_identity(record, history)
    if binding != "BOUND":
        return RadarEnvelope(
            state=binding,
            economic_asset_uid=uid,
            data={"availability": binding},
        )
    data = _radar.build_financials_data(history)
    fr = freshness_out(history.freshness) if history.freshness else None
    return RadarEnvelope(
        state=history.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/corporate-actions ───────────

@router.get(
    "/radar/assets/{economic_asset_uid}/corporate-actions",
    response_model=RadarEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def get_radar_corporate_actions(economic_asset_uid: str):
    """Return recent dividend and stock split history."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    binding = _radar.bind_equity_identity(record, bundle)
    if binding != "BOUND":
        return RadarEnvelope(
            state=binding,
            economic_asset_uid=uid,
            data={"availability": binding},
        )
    data = _radar.build_corporate_actions_data(bundle)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── GET /api/v1/radar/assets/{economic_asset_uid}/evidence ───────────────────

@router.get(
    "/radar/assets/{economic_asset_uid}/evidence",
    response_model=RadarEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def get_radar_evidence(economic_asset_uid: str):
    """Return source lineage / evidence for one asset."""
    try:
        uid, record = _radar.resolve_asset(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))
    except AssetNotFoundError:
        return _not_found(economic_asset_uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    bundle = _radar.get_fundamentals_bundle(record.token_symbol)
    binding = _radar.bind_equity_identity(record, bundle)
    if binding != "BOUND":
        return RadarEnvelope(
            state=binding,
            economic_asset_uid=uid,
            data={"availability": binding},
        )
    data = _radar.build_evidence_data(bundle)
    fr = freshness_out(bundle.freshness) if bundle.freshness else None
    return RadarEnvelope(
        state=bundle.availability.value,
        economic_asset_uid=uid,
        data=data,
        freshness=fr,
    )


# ── POST /api/v1/radar/assets/{economic_asset_uid}/execution-simulation ────────

@router.post(
    "/radar/assets/{economic_asset_uid}/execution-simulation",
    response_model=ExecutionSimulationEnvelope,
    responses={
        400: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    },
)
def post_execution_simulation(
    economic_asset_uid: str,
    body: ExecutionSimulationRequest,
) -> Any:
    """Read-only execution simulation for a tokenized Robinhood equity.

    Returns canonical reference price, executable price, and directional GAP
    for the requested direction and notional.  Does NOT submit an order,
    connect a wallet, approve tokens, or recommend a trade direction.

    simulation_only: true  — this is analytics, not execution.
    order_submitted: false — no transaction is sent or signed.
    """
    # 1. Validate direction and notional — return 400 before any UID work
    # Strict string contract: only exact string values are accepted; integers,
    # floats, booleans, null, arrays, and objects all produce 400.
    direction = body.direction
    notional_usd = body.notional_usd

    if not isinstance(direction, str) or direction not in _ALLOWED_DIRECTIONS:
        return _simulation_request_invalid(
            None,
            f"direction must be BUY or SELL, got {direction!r}",
        )

    if not isinstance(notional_usd, str) or notional_usd not in _ALLOWED_NOTIONALS:
        return _simulation_request_invalid(
            None,
            f"notional_usd must be '100' or '1000', got {notional_usd!r}",
        )

    # 2. Validate UID format
    try:
        uid = _radar.validate_uid(economic_asset_uid)
    except AssetUidInvalidError as exc:
        return _uid_invalid(economic_asset_uid, str(exc))

    # 3. Resolve asset from canonical universe
    try:
        selected_asset = _execution.resolve_selected_asset(uid)
    except RegistryUnavailableError:
        return _registry_unavailable()

    if selected_asset is None:
        return _not_found(uid)

    # 4. Build canonical acquisition request (E4 authority)
    try:
        request = _composition.build_request(direction, notional_usd, selected_asset)
    except RuntimeContractError as exc:
        return _simulation_request_invalid(uid, str(exc))

    # 5. Acquire immutable snapshot — exactly once; programming errors propagate
    svc = _execution.get_execution_service()
    snapshot = svc.acquire(request)

    # 6. Serialize — identity invariant enforced inside; propagates on breach
    data = _execution.serialize_snapshot(snapshot, selected_asset, direction, notional_usd)

    return ExecutionSimulationEnvelope(
        state=data["state"],
        economic_asset_uid=data["economic_asset_uid"],
        snapshot_id=data["snapshot_id"],
        simulation=data["simulation"],
        identity=data["identity"],
        reference=data["reference"],
        execution=data["execution"],
        gap=data["gap"],
        freshness=data["freshness"],
    )


# ── GET /api/v1/meta ──────────────────────────────────────────────────────────

@router.get("/meta", response_model=None)
def get_api_meta():
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
            "radar.execution.simulation",
        ],
    }
