"""A2 Execution Simulation API adapter — Correction A.

Owns:
- execution service test seam (get_execution_service / set_execution_service)
- universe resolution seam (set_universe_fn / _get_universe)
- snapshot serializer (serialize_snapshot)
- identity invariant enforcement (asset + direction + notional)
- radar-core provider selection by canonical name
- outward-string safety boundary for metadata fields

DOES NOT:
- perform financial calculations
- recompute GAP
- modify E4 UI service singleton
- create new quote/reference engines
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

import httpx

from finco_radar.assets.contracts import RegistryConflictError, RegistrySourceError
from app.radar_ui.composition import SelectedAsset, fetch_robinhood_asset_universe
from app.radar_ui import composition as _composition
from app.api.v1.errors import RegistryUnavailableError


# ── service test seam ─────────────────────────────────────────────────────────

_execution_service_override: Optional[Any] = None


def get_execution_service() -> Any:
    """Return the configured acquisition service.

    In tests, call set_execution_service() to inject a deterministic fake.
    In production, builds the canonical service from composition.build_service()."""
    if _execution_service_override is not None:
        return _execution_service_override
    return _composition.build_service()


def set_execution_service(svc: Optional[Any]) -> None:
    """Test seam: inject a fake acquisition service (or None to clear)."""
    global _execution_service_override
    _execution_service_override = svc


# ── universe test seam ────────────────────────────────────────────────────────

_universe_fn_override: Optional[Callable[[], List[SelectedAsset]]] = None


def set_universe_fn(fn: Optional[Callable[[], List[SelectedAsset]]]) -> None:
    """Test seam: inject a function that returns a fake asset universe."""
    global _universe_fn_override
    _universe_fn_override = fn


def _get_universe() -> List[SelectedAsset]:
    if _universe_fn_override is not None:
        return _universe_fn_override()
    return fetch_robinhood_asset_universe()


def resolve_selected_asset(uid: str) -> Optional[SelectedAsset]:
    """Find the SelectedAsset for uid in the current canonical universe.

    Returns None if the UID is not present (caller maps this to 404).
    Raises RegistryUnavailableError ONLY for expected registry/network failures.
    Programming errors (RuntimeError, TypeError, etc.) propagate naturally."""
    try:
        universe = _get_universe()
    except RegistryUnavailableError:
        raise
    except (httpx.HTTPError, RegistrySourceError, RegistryConflictError) as exc:
        raise RegistryUnavailableError(str(exc)) from exc
    for asset in universe:
        if asset.economic_asset_uid == uid:
            return asset
    return None


# ── identity invariant ────────────────────────────────────────────────────────

class IdentityInvariantError(RuntimeError):
    """The immutable snapshot does not bind to the requested canonical identity."""


def _check_identity_invariant(
    payload: dict,
    selected_asset: SelectedAsset,
    direction: str,
    notional_usd: str,
) -> None:
    """Assert snapshot payload matches selected_asset identity AND exact request.

    Checks: UID, chain_id, contract_address, direction, notionalUsd.
    Raises IdentityInvariantError on any mismatch — fail closed, never
    serialize a simulation result for a different asset or request."""
    snap_uid = payload.get("economicAssetUid")
    snap_chain = payload.get("chainId")
    snap_contract = payload.get("contractAddress", "")
    if snap_uid != selected_asset.economic_asset_uid:
        raise IdentityInvariantError(
            f"snapshot uid {snap_uid!r} != requested "
            f"{selected_asset.economic_asset_uid!r}")
    if snap_chain != selected_asset.chain_id:
        raise IdentityInvariantError(
            f"snapshot chain {snap_chain!r} != requested "
            f"{selected_asset.chain_id!r}")
    if str(snap_contract).lower() != selected_asset.contract_address.lower():
        raise IdentityInvariantError(
            f"snapshot contract {snap_contract!r} != requested "
            f"{selected_asset.contract_address!r}")

    # Exact simulation binding: direction + notional must also match.
    snap_request = payload.get("request") or {}
    snap_direction = snap_request.get("direction")
    snap_notional = snap_request.get("notionalUsd")
    if snap_direction is None:
        raise IdentityInvariantError("snapshot request.direction is absent")
    if snap_notional is None:
        raise IdentityInvariantError("snapshot request.notionalUsd is absent")
    if snap_direction != direction:
        raise IdentityInvariantError(
            f"snapshot direction {snap_direction!r} != requested {direction!r}")
    if snap_notional != notional_usd:
        raise IdentityInvariantError(
            f"snapshot notionalUsd {snap_notional!r} != requested {notional_usd!r}")


# ── radar-core provider selection ─────────────────────────────────────────────

_RADAR_CORE_PROVIDER = "radar-core"


def _find_radar_core_provider(providers: list) -> dict:
    """Return the radar-core provider result dict, or empty dict if absent.

    Searches by canonical provider name, not list position."""
    for p in providers:
        if isinstance(p, dict) and p.get("provider") == _RADAR_CORE_PROVIDER:
            return p
    return {}


# ── outward-string safety boundary ───────────────────────────────────────────

_SAFE_METADATA_FALLBACK = "INTERNAL_DETAIL_REDACTED"


def _safe_metadata_string(s: Any, fallback: str = _SAFE_METADATA_FALLBACK) -> Optional[str]:
    """Return s if it looks like a safe canonical metadata string, else fallback.

    Canonical source labels (e.g. 'LiFi', 'FROZEN::BoundReferencePrice') and
    reason codes (e.g. 'NO_ROUTE', 'EXECUTION_UNAVAILABLE') contain no digits,
    no URL schemes, and no filesystem paths.  Strings that match any of those
    unsafe patterns are replaced with the stable fallback."""
    if s is None:
        return None
    if not isinstance(s, str):
        return fallback
    if '://' in s:           # URL scheme present
        return fallback
    if s.startswith('/'):    # Unix filesystem path
        return fallback
    if s.startswith('\\'):   # Windows filesystem path
        return fallback
    if any(c.isdigit() for c in s):  # Digits (suspicious in metadata labels)
        return fallback
    return s


# ── section serializers ───────────────────────────────────────────────────────

def _ref_section(ref: Any) -> dict:
    if not isinstance(ref, dict) or ref.get("available") is not True:
        raw_reason = (ref.get("reason") if isinstance(ref, dict) else None
                      ) or "REFERENCE_UNAVAILABLE"
        return {
            "available": False,
            "reason": _safe_metadata_string(raw_reason, "REFERENCE_UNAVAILABLE"),
        }
    return {
        "available": True,
        "reason": None,
        "price": ref.get("price"),
        "bid": ref.get("bid"),
        "ask": ref.get("ask"),
        "source": _safe_metadata_string(ref.get("source")),
        "observed_at": ref.get("observedAt"),
    }


def _exec_section(exec_: Any) -> dict:
    if not isinstance(exec_, dict) or exec_.get("available") is not True:
        # unavailableReason takes precedence over reason (canonical E4 semantics)
        raw_reason = None
        if isinstance(exec_, dict):
            raw_reason = exec_.get("unavailableReason") or exec_.get("reason")
        raw_reason = raw_reason or "EXECUTION_UNAVAILABLE"
        result: dict = {
            "available": False,
            "reason": _safe_metadata_string(raw_reason, "EXECUTION_UNAVAILABLE"),
        }
        # Preserve safe canonical metadata when present
        if isinstance(exec_, dict):
            for api_key, ev_key, apply_safety in (
                ("status",       "status",      False),
                ("source",       "source",      True),
                ("quoted_at",    "quotedAt",    False),
                ("side",         "side",        False),
                ("notional_usd", "notionalUsd", False),
            ):
                val = exec_.get(ev_key)
                if val is not None:
                    result[api_key] = _safe_metadata_string(val) if apply_safety else val
        return result
    result = {
        "available": True,
        "reason": None,
        "status": exec_.get("status"),
        "effective_price": exec_.get("effectivePrice"),
        "source": _safe_metadata_string(exec_.get("source")),
        "quoted_at": exec_.get("quotedAt"),
    }
    for api_key, ev_key in (
        ("raw_amount_in",        "rawAmountIn"),
        ("raw_amount_out",       "rawAmountOut"),
        ("normalized_amount_out", "normalizedAmountOut"),
    ):
        val = exec_.get(ev_key)
        if val is not None:
            result[api_key] = val
    return result


def _gap_section(gap: Any) -> dict:
    if not isinstance(gap, dict) or gap.get("available") is not True:
        raw_reason = (gap.get("reason") if isinstance(gap, dict) else None
                      ) or "GAP_UNAVAILABLE"
        return {
            "available": False,
            "reason": _safe_metadata_string(raw_reason, "GAP_UNAVAILABLE"),
        }
    return {
        "available": True,
        "reason": None,
        "gap_bps": gap.get("gapBps"),
        "gap_to_mid_bps": gap.get("gapToMidBps"),
        "quoted_at": gap.get("quotedAt"),
    }


# ── snapshot serializer ───────────────────────────────────────────────────────

def serialize_snapshot(
    snapshot: Any,
    selected_asset: SelectedAsset,
    direction: str,
    notional_usd: str,
) -> dict:
    """Serialize an immutable acquisition snapshot to the A2 response shape.

    Enforces the full identity invariant (UID + chain + contract + direction +
    notional) before any serialization.  Selects the canonical radar-core
    provider by name, not by list position.  Sources simulation fields from
    the immutable snapshot request rather than echoing HTTP parameters.
    Does NOT recalculate reference/execution/GAP values."""
    payload = snapshot.to_payload()
    _check_identity_invariant(payload, selected_asset, direction, notional_usd)

    state = payload.get("state", "UNAVAILABLE")
    completed_at = payload.get("completedAt")

    # Source simulation fields from the immutable snapshot request.
    snap_request = payload.get("request") or {}

    # Select radar-core provider by canonical name — not by list position.
    providers = payload.get("providers") or []
    rc_provider = _find_radar_core_provider(providers)
    evidence: dict = rc_provider.get("evidence") or {}

    ref = evidence.get("reference") or {}
    exec_ = evidence.get("execution") or {}
    gap = evidence.get("gap") or {}

    ref_sec = _ref_section(ref)
    exec_sec = _exec_section(exec_)
    gap_sec = _gap_section(gap)

    return {
        "state": state,
        "economic_asset_uid": selected_asset.economic_asset_uid,
        "snapshot_id": snapshot.snapshot_id,
        "simulation": {
            "simulation_only": True,
            "order_submitted": False,
            "direction": snap_request.get("direction"),
            "notional_usd": snap_request.get("notionalUsd"),
        },
        "identity": {
            "token_symbol": selected_asset.token_symbol,
            "chain_id": selected_asset.chain_id,
            "contract_address": selected_asset.contract_address,
        },
        "reference": ref_sec,
        "execution": exec_sec,
        "gap": gap_sec,
        "freshness": {
            "reference_observed_at": (
                ref.get("observedAt")
                if isinstance(ref, dict) and ref.get("available") is True
                else None
            ),
            "execution_quoted_at": (
                exec_.get("quotedAt")
                if isinstance(exec_, dict) and exec_.get("available") is True
                else None
            ),
            "gap_quoted_at": (
                gap.get("quotedAt")
                if isinstance(gap, dict) and gap.get("available") is True
                else None
            ),
            "completed_at": completed_at,
        },
    }
