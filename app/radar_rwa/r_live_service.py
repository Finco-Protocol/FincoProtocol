"""R-LIVE composition: exact on-chain reference into B1.0 and B1.3.

The on-chain layer supplies only the independent token reference. Existing
Robinhood binding owns the comparison basis; B1.0 owns premium arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityPolicy, AuthoritySnapshot
from finco_radar.authority.engine import build_authority_snapshot
from finco_radar.authority.r_live_onchain import (
    JsonRpc, OnchainReferenceObservation, Rpc, observe_onchain_reference,
)
from finco_radar.authority.r_live_policy import AAPL_KEY, MAX_QUOTE_AGE_SECONDS, MAX_REGISTRY_AGE_SECONDS
from finco_radar.gap.contracts import BoundReferencePrice
from finco_radar.gap.engine import build_bound_reference_price

from .bnb_history import BnbIntelligenceHistoryStore, make_r_live_history_point


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
) -> RLiveResult:
    """Pure B1.0 integration; optional append to the existing B1.3 ledger."""
    observation = observe_onchain_reference(
        registry=registry, key=AAPL_KEY, rpc=rpc, retrieved_at=as_of,
    )
    clock = as_of or datetime.now(timezone.utc)
    snapshot = build_authority_snapshot(
        registry=registry, key=AAPL_KEY, underlying_reference=underlying,
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


def collect_aapl_r_live(*, rpc_url: str, as_of: datetime | None = None,
                        persist_history: bool = False,
                        history: BnbIntelligenceHistoryStore | None = None) -> RLiveResult:
    """Acquire read-only by default; only an explicit collector path may write."""
    if history is not None and not persist_history:
        raise ValueError("HISTORY_REQUIRES_EXPLICIT_PERSISTENCE")
    with RobinhoodAssetRegistryAdapter() as adapter:
        registry = adapter.fetch_snapshot()
        asset = registry.get_by_key(AAPL_KEY)
        underlying = None
        if asset is not None:
            try:
                binding, row = adapter.fetch_bound_reference(registry, AAPL_KEY)
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
                              as_of=as_of, history=ledger)
    finally:
        rpc.close()
        if owned_history and ledger is not None:
            ledger.close()
