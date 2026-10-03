"""FINCO Crypto read-only API V1 — the first real crypto distribution surface.

Adapts EXISTING canonical read models (shared layer ``app.crypto_terminal``);
no product mathematics and no market-data acquisition happens here.

Concurrency contract (A40, same as every API V1 route): handlers are plain
synchronous ``def`` so FastAPI dispatches them to the worker threadpool.  The
canonical entitlement adapters are async; this module bridges to them with one
small ``_run_async`` helper (``asyncio.run`` is safe here because a
synchronous handler executes in a worker thread with no running event loop).
Ordinary synchronous read models are called directly — never re-wrapped.

Access (merged PR #180 authorities):
  * every endpoint first resolves ``crypto.api`` through
    ``app.crypto_api_access`` — canonical Decision.INACTIVE stays DENIED
    (the API is a new capability; gating-off never activates it);
  * tokenized premium resources resolve ``tokenized.history`` /
    ``tokenized.dislocation`` through ``app.tokenized_access`` — a denial
    is a typed 403 and the protected payload is never built;
  * denials expose only the sanitized safe fields.

Envelope contract (stable V1):
  api_version, schema_version, resource, state, as_of, data
  + canonical identity where applicable
  + access (safe per-resource states)
  Values that do not exist are null — never zero.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/crypto")

API_VERSION = "v1"
SCHEMA_VERSION = "finco-crypto-api-v1"
_CACHE = {"Cache-Control": "no-store"}

# One evaluation clock per request: the SAME as_of is passed into the shared
# read models and serialized as the envelope as_of.  Source observed_at stays
# separate and is never substituted.
_REQUEST_LIMIT_MAX = 60   # mirrors the reviewed Tokenized landing default


def _request_as_of() -> datetime:
    return datetime.now(timezone.utc)


def _run_async(coro):
    """Bridge a canonical async entitlement adapter from a synchronous
    API V1 handler (worker thread — no running event loop)."""
    return asyncio.run(coro)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _envelope(resource: str, state: str, data: Any, *,
              canonical_id: str | None = None,
              access: dict | None = None,
              reason: str | None = None,
              as_of: str | None = None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "resource": resource,
        "state": state,
        "as_of": as_of or _now(),
    }
    if canonical_id is not None:
        envelope["canonical_asset_id"] = canonical_id
    if access is not None:
        envelope["access"] = access
    if reason is not None:
        envelope["reason"] = reason
    envelope["data"] = data
    return envelope


def _denied(decision) -> JSONResponse:
    from app.crypto_api_access import api_denial_payload
    return JSONResponse(status_code=403,
                        content=api_denial_payload(decision),
                        headers=_CACHE)


def _tokenized_denied(decision) -> JSONResponse:
    from app.tokenized_access import denial_payload
    return JSONResponse(status_code=403,
                        content=denial_payload(decision),
                        headers=_CACHE)


def _require_crypto_api(request: Request):
    from app.crypto_api_access import resolve_api_access
    decision = _run_async(resolve_api_access(request))
    if not decision.access_allowed:
        return _denied(decision)
    return None


def _tokenized_gates(request: Request):
    from app.radar_ui.tokenized_gating import resolve_tokenized_gates
    return _run_async(resolve_tokenized_gates(request))


def _tokenized_access(request, resource):
    from app.tokenized_access import resolve_tokenized_access
    return _run_async(resolve_tokenized_access(request, resource))


def _float(value):
    return None if value is None else float(value)


def _jsonify(value):
    """Datetime-aware JSON-safe conversion for composed view objects."""
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return None if not value.is_finite() else float(value)
    return value


@router.get("/tokenized")
def crypto_tokenized_landing(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=_REQUEST_LIMIT_MAX),
):
    """Cross-venue Tokenized Markets landing (tokenized.basic — public)."""
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    from app.radar_ui.tokenized_gating import resolve_tokenized_gates

    gates = _run_async(resolve_tokenized_gates(request))
    from app.crypto_terminal.tokenized_read import landing_rows
    rows, meta = landing_rows(gates=gates, limit=limit, now=as_of)

    access = gates.public_view()
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "tokenized.landing", "AVAILABLE", {
            "total_underlyings": meta["total_underlyings"],
            "showing": meta["showing"],
            "history_available": meta["history_available"],
            "collector_health": meta["collector_health"],
            "rows": [_jsonify(row) for row in rows],
        },
        access=access, as_of=as_of.isoformat()))


@router.get("/tokenized/{canonical_asset_id}")
def crypto_tokenized_detail(request: Request, canonical_asset_id: str):
    """One canonical underlying: reference + representations + basis
    (tokenized.basic — public; premium fields redacted per access)."""
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    gates = _tokenized_gates(request)
    from app.crypto_terminal.tokenized_read import detail
    result = detail(canonical_asset_id, gates=gates, now=as_of)
    if not result["known"]:
        return JSONResponse(status_code=404, headers=_CACHE, content=_envelope(
            "tokenized.detail", "UNKNOWN_IDENTITY", None,
            canonical_id=canonical_asset_id,
            reason="CANONICAL_ASSET_ID_UNKNOWN", as_of=as_of.isoformat()))
    view = result["view"]
    data = {
        "underlying_name": view.underlying_name,
        "underlying_isin": view.underlying_isin,
        "overall_state": view.overall_state,
        "evaluation_time": view.evaluation_time,
        "reference": _jsonify(result["reference"]),
        "history_available": result["history_available"],
        "collector_health": _jsonify(result["collector_health"]),
        "representations": [_jsonify({
            "venue_id": r.venue_id, "instrument_id": r.instrument_id,
            "representation_type": r.representation_type,
            "network": r.network, "contract_address": r.contract_address,
            "status": r.status, "price": _float(r.price)
            if r.price is not None else None,
            "source_timestamp": r.source_timestamp,
            "collected_at": r.collected_at,
            "basis_bps": _float(r.basis_bps) if r.basis_bps is not None else None,
            "basis_reason": r.basis_reason,
            "freshness_state": r.freshness_state,
            "observation_status": r.observation_status,
            "source": r.source, "provenance": r.provenance,
        }) for r in view.representations],
    }
    if result["intelligence"] is not None:
        intel = result["intelligence"]
        data["intelligence"] = {
            "generated_at": intel.generated_at,
            "representations": [{
                "venue_id": r.venue_id, "instrument_id": r.instrument_id,
                "current_state": r.current_state,
                "latest_basis_bps": _float(r.latest_basis_bps)
                if r.latest_basis_bps is not None else None,
                "basis_change_24h_bps": _float(r.basis_change_24h_bps)
                if r.basis_change_24h_bps is not None else None,
                "basis_change_7d_bps": _float(r.basis_change_7d_bps)
                if r.basis_change_7d_bps is not None else None,
            } for r in intel.representations],
            "cross_venue": ({"state": intel.cross_venue.state,
                             "divergence_bps": _float(intel.cross_venue.divergence_bps)
                             if intel.cross_venue.divergence_bps is not None else None,
                             "reason": intel.cross_venue.reason}
                            if intel.cross_venue else None),
        }
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "tokenized.detail", "AVAILABLE", data,
        canonical_id=canonical_asset_id, access=gates.public_view(),
        as_of=as_of.isoformat()))


@router.get("/tokenized/{canonical_asset_id}/history")
def crypto_tokenized_history(request: Request, canonical_asset_id: str):
    """Canonical basis history (tokenized.history — holder resource)."""
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    from app.tokenized_access import TokenizedResource
    decision = _tokenized_access(request, TokenizedResource.HISTORY)
    if not decision.access_allowed:
        return _tokenized_denied(decision)
    gates = _tokenized_gates(request)
    from app.crypto_terminal.tokenized_read import detail
    result = detail(canonical_asset_id, gates=gates, now=as_of)
    if not result["known"]:
        return JSONResponse(status_code=404, headers=_CACHE, content=_envelope(
            "tokenized.history", "UNKNOWN_IDENTITY", None,
            canonical_id=canonical_asset_id,
            reason="CANONICAL_ASSET_ID_UNKNOWN", as_of=as_of.isoformat()))
    intelligence = result["intelligence"]
    series = []
    if intelligence is not None:
        for item in intelligence.representations:
            points = [{"t": p.t, "v": _float(p.v) if p.v is not None else None}
                      for p in item.points]
            series.append({
                "venue_id": item.venue_id,
                "instrument_id": item.instrument_id,
                "current_state": item.current_state,
                "latest_basis_bps": _float(item.latest_basis_bps)
                if item.latest_basis_bps is not None else None,
                "basis_change_24h_bps": _float(item.basis_change_24h_bps)
                if item.basis_change_24h_bps is not None else None,
                "basis_change_7d_bps": _float(item.basis_change_7d_bps)
                if item.basis_change_7d_bps is not None else None,
                "points": points,
            })
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "tokenized.history", "AVAILABLE",
        {"canonical_asset_id": canonical_asset_id, "series": series},
        canonical_id=canonical_asset_id, as_of=as_of.isoformat()))


@router.get("/tokenized/{canonical_asset_id}/dislocations")
def crypto_tokenized_dislocations(request: Request, canonical_asset_id: str):
    """Cross-venue divergence + dislocation events
    (tokenized.dislocation — holder resource)."""
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    from app.tokenized_access import TokenizedResource
    decision = _tokenized_access(request, TokenizedResource.DISLOCATION)
    if not decision.access_allowed:
        return _tokenized_denied(decision)
    gates = _tokenized_gates(request)
    from app.crypto_terminal.tokenized_read import detail
    result = detail(canonical_asset_id, gates=gates, now=as_of)
    if not result["known"]:
        return JSONResponse(status_code=404, headers=_CACHE, content=_envelope(
            "tokenized.dislocation", "UNKNOWN_IDENTITY", None,
            canonical_id=canonical_asset_id,
            reason="CANONICAL_ASSET_ID_UNKNOWN", as_of=as_of.isoformat()))
    intelligence = result["intelligence"]
    cross_venue = None
    events = []
    if intelligence is not None:
        if intelligence.cross_venue is not None:
            cv = intelligence.cross_venue
            cross_venue = {
                "state": cv.state,
                "divergence_bps": _float(cv.divergence_bps)
                if cv.divergence_bps is not None else None,
                "low_venue": cv.low_venue, "high_venue": cv.high_venue,
                "low_price": _float(cv.low_price) if cv.low_price is not None else None,
                "high_price": _float(cv.high_price) if cv.high_price is not None else None,
                "comparison_unit": cv.comparison_unit,
                "reason": cv.reason,
            }
        events = [{
            "observed_at": e.observed_at, "event_type": e.event_type,
            "venue_id": e.venue_id, "instrument_id": e.instrument_id,
            "value_bps": _float(e.value_bps) if e.value_bps is not None else None,
            "direction": e.direction,
            "threshold_bps": _float(e.threshold_bps)
            if e.threshold_bps is not None else None,
        } for e in intelligence.events]
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "tokenized.dislocation", "AVAILABLE",
        {"canonical_asset_id": canonical_asset_id,
         "cross_venue": cross_venue, "events": events},
        canonical_id=canonical_asset_id, as_of=as_of.isoformat()))


@router.get("/yield")
def crypto_yield_landing(request: Request):
    """Yield market intelligence (canonical history — read-only)."""
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    from app.crypto_terminal.yield_read import market_snapshot, movers, pool_rows, summary

    view = market_snapshot(now=as_of)
    access = _yield_history_access_state(request)
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "yield.market", "AVAILABLE",
        {"summary": summary(view),
         "movers_24h": movers(view, "24h"),
         "movers_7d": movers(view, "7d"),
         "pools": pool_rows(view)},
        access=access, as_of=as_of.isoformat()))


@router.get("/yield/{canonical_id}")
def crypto_yield_detail(request: Request, canonical_id: str):
    """One Yield pool.

    crypto.api ALLOW resolves first.  Then YieldResource.HISTORY is resolved
    BEFORE any protected history intelligence is built: denied callers get
    the BASIC pool payload (identity + current registry observation fields +
    provenance) and the history-derived intelligence is never constructed —
    not built-then-redacted.  This mirrors the existing Yield UI contract.
    An access-authority failure fails closed (typed unavailable, no 500).
    """
    as_of = _request_as_of()
    gate = _require_crypto_api(request)
    if gate is not None:
        return gate
    from finco_yield.access import YieldResource, resolve_yield_access

    # Fail-soft (same principle as _yield_history_access_state): an access
    # authority failure is typed UNAVAILABLE, never a 500, and never grants
    # access — the protected history intelligence is simply not built.
    try:
        history_decision = _run_async(
            resolve_yield_access(request, YieldResource.HISTORY))
        allowed = history_decision.access_allowed
        access_state = {"allowed": allowed,
                        "state": history_decision.state.value,
                        "reason": history_decision.reason}
    except Exception:
        allowed = False
        access_state = {"allowed": False,
                        "state": "ENTITLEMENT_AUTHORITY_UNAVAILABLE",
                        "reason": "ACCESS_AUTHORITY_ERROR"}
    from app.crypto_terminal.yield_read import pool_detail
    detail = pool_detail(canonical_id, now=as_of,
                         include_history_intelligence=allowed,
                         history_access=access_state)
    if detail is None:
        return JSONResponse(status_code=404, headers=_CACHE, content=_envelope(
            "yield.pool", "UNKNOWN_IDENTITY", None,
            canonical_id=canonical_id, reason="CANONICAL_ID_UNKNOWN",
            as_of=as_of.isoformat()))
    access = {"history": access_state}
    return JSONResponse(status_code=200, headers=_CACHE, content=_envelope(
        "yield.pool", "AVAILABLE", detail,
        canonical_id=canonical_id, access=access, as_of=as_of.isoformat()))


def _yield_history_access_state(request: Request) -> dict:
    """Safe HISTORY access-state exposure (never the protected payload)."""
    from finco_yield.access import YieldResource, resolve_yield_access
    try:
        decision = _run_async(resolve_yield_access(request, YieldResource.HISTORY))
        return {"history": {"allowed": decision.access_allowed,
                            "state": decision.state.value,
                            "reason": decision.reason}}
    except Exception:
        return {"history": {"allowed": False,
                            "state": "ENTITLEMENT_AUTHORITY_UNAVAILABLE",
                            "reason": "ACCESS_AUTHORITY_ERROR"}}
