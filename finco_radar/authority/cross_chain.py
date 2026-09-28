"""Exact Robinhood-registry authority for a candidate BNB deployment.

CoinGecko can supply a candidate AssetKey, but never participates in the
economic-identity decision. This layer does not calculate prices or premiums.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import (
    AssetKey, RegistryConflictError, RegistrySourceError, normalize_asset_uid,
)
from finco_radar.assets.registry import RegistrySnapshot

from .contracts import AuthorityState
from .engine import select_robinhood_registry

BNB_CHAIN_ID = 56
_ROBINHOOD_SOURCE = RobinhoodAssetRegistryAdapter.source_name


@dataclass(frozen=True)
class CrossChainIdentityBinding:
    """Separate exact deployment and canonical economic-identity evidence."""

    state: AuthorityState
    external_asset_key: AssetKey | None
    economic_asset_uid: str | None
    canonical_deployments: tuple[AssetKey, ...]
    authority_source: str | None
    observed_at: datetime | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.state is AuthorityState.AVAILABLE:
            if (
                self.external_asset_key is None
                or self.external_asset_key.chain_id != BNB_CHAIN_ID
                or self.economic_asset_uid is None
                or self.external_asset_key not in self.canonical_deployments
                or not self.authority_source
                or self.observed_at is None
                or self.reason is not None
            ):
                raise ValueError("available binding needs exact canonical evidence")
            object.__setattr__(self, "economic_asset_uid", normalize_asset_uid(self.economic_asset_uid))
        elif self.economic_asset_uid is not None or self.canonical_deployments:
            raise ValueError("unavailable binding cannot assert economic identity")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("identity observation time must be timezone-aware")


@dataclass(frozen=True)
class CrossChainRegistryContext:
    selected: RegistrySnapshot | None
    origin: str | None
    retained: RegistrySnapshot | None
    state: AuthorityState
    reason: str | None


def _fresh(snapshot: RegistrySnapshot | None, as_of: datetime, max_age_seconds: int) -> bool:
    return (
        isinstance(snapshot, RegistrySnapshot)
        and snapshot.source == _ROBINHOOD_SOURCE
        and isinstance(snapshot.observed_at, datetime)
        and snapshot.observed_at.tzinfo is not None
        and snapshot.observed_at.utcoffset() is not None
        and 0 <= (as_of - snapshot.observed_at).total_seconds() <= max_age_seconds
    )


def select_cross_chain_registry(
    fetch_live: Callable[[], RegistrySnapshot],
    latest_valid_snapshot: RegistrySnapshot | None,
    *, as_of: datetime | Callable[[], datetime], max_age_seconds: int,
) -> CrossChainRegistryContext:
    """Reuse B1.0 live-first selection, retaining origin and conflict state."""
    if max_age_seconds <= 0:
        raise ValueError("positive registry age limit required")
    live: RegistrySnapshot | None = None
    try:
        live = fetch_live()
    except (RegistryConflictError, RegistrySourceError):
        # A malformed or conflicting live registry is not a routine outage.
        return CrossChainRegistryContext(
            None, None, None, AuthorityState.UNAVAILABLE,
            "LIVE_ROBINHOOD_REGISTRY_CONFLICT_OR_MALFORMED",
        )
    except Exception:
        pass  # existing B1.0 policy permits valid retained fallback on outage
    if (
        isinstance(live, RegistrySnapshot)
        and live.source == _ROBINHOOD_SOURCE
        and (
            not isinstance(live.observed_at, datetime)
            or live.observed_at.tzinfo is None
            or live.observed_at.utcoffset() is None
        )
    ):
        return CrossChainRegistryContext(
            None, None, None, AuthorityState.UNAVAILABLE,
            "LIVE_ROBINHOOD_REGISTRY_TIMESTAMP_INVALID",
        )

    # Evaluate freshness *after* live acquisition: its observed_at is created
    # during fetch and otherwise appears spuriously future relative to a prior
    # CoinGecko request timestamp.
    evaluation_time = as_of() if callable(as_of) else as_of
    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise ValueError("aware as_of required")

    retained = latest_valid_snapshot if _fresh(latest_valid_snapshot, evaluation_time, max_age_seconds) else None
    selected = select_robinhood_registry(
        lambda: live if _fresh(live, evaluation_time, max_age_seconds) else None,
        retained, as_of=evaluation_time,
        max_age_seconds=max_age_seconds,
    )
    if selected is not None:
        origin = "LIVE" if selected is live else "RETAINED"
        return CrossChainRegistryContext(
            selected, origin, retained if origin == "LIVE" else None,
            AuthorityState.AVAILABLE, None,
        )
    stale = any(
        isinstance(item, RegistrySnapshot)
        and item.source == _ROBINHOOD_SOURCE
        and isinstance(item.observed_at, datetime)
        and item.observed_at.tzinfo is not None
        and item.observed_at.utcoffset() is not None
        and (evaluation_time - item.observed_at).total_seconds() > max_age_seconds
        for item in (live, latest_valid_snapshot)
    )
    return CrossChainRegistryContext(
        None, None, None,
        AuthorityState.STALE if stale else AuthorityState.IDENTITY_UNAVAILABLE,
        "ROBINHOOD_REGISTRY_STALE" if stale else "ROBINHOOD_REGISTRY_UNAVAILABLE",
    )


def _missing(
    state: AuthorityState, key: AssetKey | None, reason: str,
    registry: RegistrySnapshot | None = None, origin: str | None = None,
) -> CrossChainIdentityBinding:
    return CrossChainIdentityBinding(
        state, key, None, (),
        f"{_ROBINHOOD_SOURCE}:{origin}" if registry is not None and origin else None,
        registry.observed_at if registry is not None else None, reason,
    )


def _retained_conflicts(
    selected: RegistrySnapshot, retained: RegistrySnapshot | None,
    key: AssetKey, expected_uid: str | None,
) -> bool:
    if retained is None:
        return False
    live_owner = selected.get_by_key(key)
    retained_owner = retained.get_by_key(key)
    if live_owner is None and retained_owner is not None:
        return True  # live withdrawal cannot be revived by retained evidence
    if live_owner is not None and retained_owner is not None and live_owner.asset_uid != retained_owner.asset_uid:
        return True
    if expected_uid is not None:
        live_asset = selected.get_by_uid(expected_uid)
        old_asset = retained.get_by_uid(expected_uid)
        if live_asset is not None and old_asset is not None:
            live_bnb = live_asset.deployment_for_chain(BNB_CHAIN_ID)
            old_bnb = old_asset.deployment_for_chain(BNB_CHAIN_ID)
            if live_bnb is not None and old_bnb is not None and live_bnb != old_bnb:
                return True
    elif live_owner is not None:
        old_asset = retained.get_by_uid(live_owner.asset_uid)
        if old_asset is not None:
            old_bnb = old_asset.deployment_for_chain(BNB_CHAIN_ID)
            if old_bnb is not None and old_bnb != key:
                return True
    return False


def resolve_cross_chain_identity(
    context: CrossChainRegistryContext,
    candidate: AssetKey | None,
    *, expected_economic_asset_uid: str | None = None,
) -> CrossChainIdentityBinding:
    """Bind only an exact chain-56 deployment owned by the expected UID."""
    if candidate is None:
        return _missing(AuthorityState.IDENTITY_UNAVAILABLE, None, "BNB_DEPLOYMENT_UNAVAILABLE")
    if candidate.chain_id != BNB_CHAIN_ID:
        return _missing(AuthorityState.IDENTITY_UNAVAILABLE, candidate, "NOT_BNB_CHAIN_56")
    try:
        expected_uid = (
            normalize_asset_uid(expected_economic_asset_uid)
            if expected_economic_asset_uid is not None else None
        )
    except (RegistrySourceError, AttributeError):
        return _missing(AuthorityState.UNAVAILABLE, candidate, "INVALID_EXPECTED_ECONOMIC_ASSET_UID")
    if context.selected is None:
        return _missing(context.state, candidate, context.reason or "ROBINHOOD_REGISTRY_UNAVAILABLE")

    registry = context.selected
    if _retained_conflicts(registry, context.retained, candidate, expected_uid):
        return _missing(
            AuthorityState.UNAVAILABLE, candidate, "LIVE_RETAINED_IDENTITY_CONFLICT",
            registry, context.origin,
        )
    owner = registry.get_by_key(candidate)
    if owner is None:
        return _missing(
            AuthorityState.IDENTITY_UNAVAILABLE, candidate, "CANONICAL_BNB_DEPLOYMENT_ABSENT",
            registry, context.origin,
        )
    if expected_uid is not None and owner.asset_uid != expected_uid:
        return _missing(
            AuthorityState.UNAVAILABLE, candidate, "DEPLOYMENT_OWNED_BY_DIFFERENT_UID",
            registry, context.origin,
        )
    return CrossChainIdentityBinding(
        AuthorityState.AVAILABLE, candidate, owner.asset_uid, owner.deployments,
        f"{_ROBINHOOD_SOURCE}:{context.origin}", registry.observed_at, None,
    )
