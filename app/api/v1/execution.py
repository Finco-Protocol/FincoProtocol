"""A2 Execution Simulation API adapter.

Owns:
- execution service test seam (get_execution_service / set_execution_service)
- universe resolution seam (set_universe_fn / _get_universe)
- snapshot serializer (serialize_snapshot)
- identity invariant enforcement

DOES NOT:
- perform financial calculations
- recompute GAP
- modify E4 UI service singleton
- create new quote/reference engines
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

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
    Raises RegistryUnavailableError if the universe cannot be fetched."""
    try:
        universe = _get_universe()
    except RegistryUnavailableError:
        raise
    except Exception as exc:
        raise RegistryUnavailableError(str(exc)) from exc
    for asset in universe:
        if asset.economic_asset_uid == uid:
            return asset
    return None


# ── identity invariant ────────────────────────────────────────────────────────

class IdentityInvariantError(RuntimeError):
    """The immutable snapshot does not bind to the requested canonical identity."""


def _check_identity_invariant(
    payload: dict, selected_asset: SelectedAsset
) -> None:
    """Assert snapshot payload matches selected_asset identity.

    Raises IdentityInvariantError on any mismatch — fail closed, never
    serialize a simulation result for a different asset."""
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


# ── section serializers ───────────────────────────────────────────────────────

def _ref_section(ref: Any) -> dict:
    if not isinstance(ref, dict) or ref.get("available") is not True:
        reason = (ref.get("reason") if isinstance(ref, dict) else None
                  ) or "REFERENCE_UNAVAILABLE"
        return {"available": False, "reason": reason}
    return {
        "available": True,
        "reason": None,
        "price": ref.get("price"),
        "bid": ref.get("bid"),
        "ask": ref.get("ask"),
        "source": ref.get("source"),
        "observed_at": ref.get("observedAt"),
    }


def _exec_section(exec_: Any) -> dict:
    if not isinstance(exec_, dict) or exec_.get("available") is not True:
        reason = (exec_.get("reason") if isinstance(exec_, dict) else None
                  ) or "EXECUTION_UNAVAILABLE"
        return {"available": False, "reason": reason}
    result: dict = {
        "available": True,
        "reason": None,
        "status": exec_.get("status"),
        "effective_price": exec_.get("effectivePrice"),
        "source": exec_.get("source"),
        "quoted_at": exec_.get("quotedAt"),
    }
    for api_key, ev_key in (
        ("raw_amount_in", "rawAmountIn"),
        ("raw_amount_out", "rawAmountOut"),
        ("normalized_amount_out", "normalizedAmountOut"),
    ):
        val = exec_.get(ev_key)
        if val is not None:
            result[api_key] = val
    return result


def _gap_section(gap: Any) -> dict:
    if not isinstance(gap, dict) or gap.get("available") is not True:
        reason = (gap.get("reason") if isinstance(gap, dict) else None
                  ) or "GAP_UNAVAILABLE"
        return {"available": False, "reason": reason}
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

    Enforces the identity invariant before any serialization.  Does NOT
    recalculate reference/execution/GAP values — returns them verbatim from
    the snapshot's canonical provider evidence."""
    payload = snapshot.to_payload()
    _check_identity_invariant(payload, selected_asset)

    state = payload.get("state", "UNAVAILABLE")
    completed_at = payload.get("completedAt")

    providers = payload.get("providers") or []
    evidence: dict = {}
    if providers and isinstance(providers[0], dict):
        evidence = providers[0].get("evidence") or {}

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
            "direction": direction,
            "notional_usd": notional_usd,
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
