"""R-LIVE composition: exact on-chain reference into B1.0 and B1.3.

The on-chain layer supplies only the independent token reference. Existing
Robinhood binding owns the comparison basis; B1.0 owns premium arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityPolicy, AuthoritySnapshot
from finco_radar.authority.engine import build_authority_snapshot
from finco_radar.authority.r_live_onchain import (
    JsonRpc, OnchainReferenceObservation, Rpc, observe_onchain_reference,
)
from finco_radar.authority.r_live_policy import (
    AAPL_KEY, APPROVED_BY_CANONICAL_ID, MAX_QUOTE_AGE_SECONDS, MAX_REGISTRY_AGE_SECONDS,
)
from finco_radar.assets.contracts import AssetKey
from finco_radar.gap.contracts import BoundReferencePrice
from finco_radar.gap.engine import build_bound_reference_price

from .bnb_history import (BnbIntelligenceHistoryStore, make_r_live_history_point,
                          read_r_live_points_readonly, read_r_live_range_summary_readonly)


R_LIVE_AUTHORITY_POLICY = AuthorityPolicy(
    max_registry_age_seconds=MAX_REGISTRY_AGE_SECONDS,
    max_reference_age_seconds=MAX_QUOTE_AGE_SECONDS,
    max_execution_age_seconds=120,
    max_evidence_skew_seconds=MAX_QUOTE_AGE_SECONDS,
    approved_token_reference_sources=frozenset({"UNISWAP_V3_TWAP_CHAINLINK_USDG_USD"}),
)


@dataclass(frozen=True)
class RLiveResult:
    onchain: OnchainReferenceObservation
    authority: AuthoritySnapshot
    history_digest: str | None


def compose_r_live(
    *, registry: RegistrySnapshot | None, underlying: BoundReferencePrice | None,
    rpc: Rpc, as_of: datetime | None = None, history: BnbIntelligenceHistoryStore | None = None,
    key: AssetKey = AAPL_KEY,
) -> RLiveResult:
    """Pure B1.0 integration; optional append to the existing B1.3 ledger."""
    observation = observe_onchain_reference(
        registry=registry, key=key, rpc=rpc, retrieved_at=as_of,
    )
    clock = as_of or datetime.now(timezone.utc)
    snapshot = build_authority_snapshot(
        registry=registry, key=key, underlying_reference=underlying,
        token_reference=observation.to_independent_reference(),
        execution_quote=None, as_of=clock, policy=R_LIVE_AUTHORITY_POLICY,
    )
    point = make_r_live_history_point(snapshot, observation)
    digest = None
    if history is not None and point is not None:
        try:
            digest = history.put_r_live(point)
        except Exception:
            pass  # storage failure cannot erase a source-proven live reference
    return RLiveResult(observation, snapshot, digest)


def collect_r_live(*, canonical_asset_id: str, rpc_url: str, as_of: datetime | None = None,
                   persist_history: bool = False,
                   history: BnbIntelligenceHistoryStore | None = None) -> RLiveResult:
    """Acquire an approved exact identity; persistence is opt-in for jobs only."""
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_asset_id)
    if policy is None:
        raise ValueError("R_LIVE_EXACT_ASSETKEY_NOT_APPROVED")
    key = policy.asset_key
    if history is not None and not persist_history:
        raise ValueError("HISTORY_REQUIRES_EXPLICIT_PERSISTENCE")
    with RobinhoodAssetRegistryAdapter() as adapter:
        registry = adapter.fetch_snapshot()
        asset = registry.get_by_key(key)
        underlying = None
        if asset is not None and asset.asset_uid == policy.economic_asset_uid:
            try:
                binding, row = adapter.fetch_bound_reference(registry, key)
                underlying = build_bound_reference_price(asset, binding, row)
            except Exception:
                underlying = None  # independent reference survives unavailable basis
    rpc = JsonRpc(rpc_url)
    owned_history = persist_history and history is None
    ledger = history if persist_history else None
    if persist_history and ledger is None:
        try:
            ledger = BnbIntelligenceHistoryStore(allowed_chain_id=4663)
        except Exception:
            ledger = None
    try:
        return compose_r_live(registry=registry, underlying=underlying, rpc=rpc,
                              as_of=as_of, history=ledger, key=key)
    finally:
        rpc.close()
        if owned_history and ledger is not None:
            ledger.close()


def collect_aapl_r_live(*, rpc_url: str, as_of: datetime | None = None,
                        persist_history: bool = False,
                        history: BnbIntelligenceHistoryStore | None = None) -> RLiveResult:
    """V1-compatible AAPL collector, including its explicit writer boundary."""
    return collect_r_live(canonical_asset_id=AAPL_KEY.canonical_id, rpc_url=rpc_url,
                          as_of=as_of, persist_history=persist_history, history=history)


def read_r_live_history(canonical_asset_id: str, *, limit: int = 30,
                        history: BnbIntelligenceHistoryStore | None = None) -> list[dict]:
    """Read B1.3 evidence for the reviewed UID/key pair, never by symbol."""
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_asset_id)
    if policy is None:
        raise ValueError("R_LIVE_EXACT_ASSETKEY_NOT_APPROVED")
    if not 1 <= limit <= 100:
        raise ValueError("R_LIVE_HISTORY_LIMIT_INVALID")
    if history is None:
        return read_r_live_points_readonly(policy.economic_asset_uid, policy.asset_key, limit=limit)
    return history.read(policy.economic_asset_uid, policy.asset_key, limit=limit)


# ── Batch acquisition ──────────────────────────────────────────────────────────

_CURRENT_WORKERS = 2  # Benchmark with 2, 3, 4 before raising; do not exceed 4.


def format_r_live_result(canonical_id: str, result: RLiveResult) -> tuple[str, dict]:
    """Serialize an RLiveResult for API response.

    Returns (state, data) with the same structure as get_r_live() in institutional.py.
    Authority composite-state logic mirrors _r_live_composite_state; do not diverge.
    """
    from finco_radar.authority.contracts import AuthorityState

    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
    if policy is None:
        return "UNAVAILABLE", {"reason": "ASSET_UID_INVALID"}

    authority = result.authority
    onchain = result.onchain
    token = authority.token
    underlying = authority.underlying
    premium = authority.premium

    components = [onchain.state, token.state, underlying.state, premium.state]
    if all(s is AuthorityState.AVAILABLE for s in components):
        state = "AVAILABLE"
    elif (onchain.state is AuthorityState.STALE
          and underlying.state not in (AuthorityState.UNAVAILABLE, AuthorityState.IDENTITY_UNAVAILABLE)):
        state = "STALE"
    elif any(s in (AuthorityState.UNAVAILABLE, AuthorityState.IDENTITY_UNAVAILABLE) for s in components):
        state = "UNAVAILABLE"
    else:
        state = "STALE"

    is_current = (state == "AVAILABLE")

    data: dict = {
        "exact_asset_key": {
            "canonical_id": policy.asset_key.canonical_id,
            "chain_id": policy.asset_key.chain_id,
            "contract_address": policy.asset_key.contract_address,
        },
        "economic_asset_uid": authority.economic_asset_uid or policy.economic_asset_uid,
        "token_reference": {
            "state": token.state.value,
            "price_usd_per_token": str(token.price_usd_per_token) if (is_current and token.price_usd_per_token is not None) else None,
            "source": token.source,
            "observed_at": token.observed_at.isoformat() if token.observed_at else None,
            "reason": token.reason,
        },
        "robinhood_basis": {
            "state": underlying.state.value,
            "price_usd_per_token": str(underlying.price_usd_per_token) if (is_current and underlying.price_usd_per_token is not None) else None,
            "source": underlying.source,
            "observed_at": underlying.observed_at.isoformat() if underlying.observed_at else None,
            "reason": underlying.reason,
        },
        "b1_0_premium": {
            "state": premium.state.value,
            "value_bps": str(premium.value_bps) if (is_current and premium.value_bps is not None) else None,
            "formula": premium.formula,
            "reason": premium.reason,
        },
        "observed_at": onchain.observed_at.isoformat() if onchain.observed_at else None,
        "freshness": _format_freshness(onchain.evidence),
    }
    return state, data


def _format_freshness(evidence) -> dict:
    """Presentation-only ages from canonical on-chain evidence timestamps.

    Mirrors institutional._r_live_freshness; Market/Oracle ages are distinct.
    """
    fields = evidence if isinstance(evidence, dict) else dict(evidence or {})

    def parsed(name: str) -> datetime | None:
        raw = fields.get(name)
        if not isinstance(raw, str):
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return value.astimezone(timezone.utc) if (value.tzinfo and value.utcoffset() is not None) else None

    retrieved = parsed("retrievedAt")

    def age(name: str) -> int | None:
        source = parsed(name)
        if source is None or retrieved is None:
            return None
        seconds = (retrieved - source).total_seconds()
        return int(seconds) if seconds >= 0 else None

    return {
        "market_activity_age_seconds": age("lastPoolActivityAt"),
        "quote_feed_age_seconds": age("quoteUpdatedAt"),
        "block_age_seconds": age("blockTimestamp"),
        "last_pool_activity_at": fields.get("lastPoolActivityAt"),
        "quote_updated_at": fields.get("quoteUpdatedAt"),
        "block_timestamp": fields.get("blockTimestamp"),
        "effective_evidence_at": fields.get("effectiveObservedAt"),
        "retrieved_at": fields.get("retrievedAt"),
    }


def read_r_live_ranges(canonical_asset_id: str, *, as_of: datetime | None = None) -> dict:
    """Read-only complete 1h/24h ranges for one exact approved AssetKey."""
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_asset_id)
    if policy is None:
        raise ValueError("R_LIVE_EXACT_ASSETKEY_NOT_APPROVED")
    return read_r_live_range_summary_readonly(
        policy.economic_asset_uid, policy.asset_key, as_of=as_of)


def collect_r_live_batch(
    *,
    rpc_url: str,
    workers: int = _CURRENT_WORKERS,
    as_of: datetime | None = None,
    canonical_ids: tuple[str, ...] | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Acquire an explicit approved R-LIVE subset, or all approved assets.

    canonical_ids is exact AssetKey canonical identity only. Omitting it
    preserves the existing all-approved R-LIVE contract; bounded callers
    may pass an already-reviewed exact subset.

    ONE RegistrySnapshot is fetched for the entire batch (not one per asset).
    ONE shared httpx.Client is used for RPC calls across all assets.
    Per-asset acquisition exceptions produce UNAVAILABLE for that asset; the
    remaining assets are still attempted.
    Registry acquisition failure is fail-closed: all assets resolve UNAVAILABLE.
    Zero history writes (persist_history is always False).
    The shared RPC client is closed exactly once in the finally block.

    Yields (canonical_id, state, data_dict) in as_completed order (not registry order).
    """
    import httpx
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    if not 1 <= workers <= 4:
        raise ValueError("BATCH_WORKERS_OUT_OF_RANGE")

    if canonical_ids is None:
        selected_ids = list(APPROVED_BY_CANONICAL_ID)
    else:
        selected_ids = list(canonical_ids)
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("R_LIVE_BATCH_DUPLICATE_EXACT_ASSETKEY")
        if any(canonical_id not in APPROVED_BY_CANONICAL_ID
               for canonical_id in selected_ids):
            raise ValueError("R_LIVE_BATCH_EXACT_ASSETKEY_NOT_APPROVED")
    shared_rpc_client = httpx.Client(timeout=15)

    try:
        with RobinhoodAssetRegistryAdapter() as adapter:
            try:
                registry: RegistrySnapshot | None = adapter.fetch_snapshot()
            except Exception:
                # Fail-closed: registry unavailable means no asset can be AVAILABLE.
                # Pass registry=None through compose_r_live; the existing
                # observe_onchain_reference contract returns CANONICAL_REGISTRY_UNAVAILABLE.
                registry = None

            def _acquire_one(canonical_id: str) -> tuple[str, str, dict]:
                policy = APPROVED_BY_CANONICAL_ID[canonical_id]
                key = policy.asset_key

                # Source-bound reference: per-asset, validated against shared registry.
                underlying = None
                if registry is not None:
                    asset = registry.get_by_key(key)
                    if asset is not None and asset.asset_uid == policy.economic_asset_uid:
                        try:
                            binding, row = adapter.fetch_bound_reference(registry, key)
                            underlying = build_bound_reference_price(asset, binding, row)
                        except Exception:
                            underlying = None  # independent reference survives

                # Per-asset JsonRpc wrapper; injected client is NOT owned here.
                rpc = JsonRpc(rpc_url, client=shared_rpc_client)
                # rpc.close() is a no-op since _owns_client=False for injected clients.

                try:
                    result = compose_r_live(
                        registry=registry, underlying=underlying,
                        rpc=rpc, as_of=as_of, history=None, key=key,
                    )
                except Exception:
                    return canonical_id, "UNAVAILABLE", {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}

                state, data = format_r_live_result(canonical_id, result)
                return canonical_id, state, data

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_acquire_one, cid): cid for cid in selected_ids}
                for future in _as_completed(futures):
                    try:
                        yield future.result()
                    except Exception:
                        cid = futures[future]
                        yield cid, "UNAVAILABLE", {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}
    finally:
        shared_rpc_client.close()
