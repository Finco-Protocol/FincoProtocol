"""Read-only second-stage Robinhood identity enrichment for BNB observations."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.cross_chain import (
    CrossChainIdentityBinding, resolve_cross_chain_identity,
    select_cross_chain_registry,
)

from .bnb_contracts import BnbRwaMarketSnapshot


def _fetch_live_registry() -> RegistrySnapshot:
    with RobinhoodAssetRegistryAdapter() as adapter:
        return adapter.fetch_snapshot()


class BnbCrossChainIdentityService:
    """One registry selection per snapshot; latest valid live view retained in-app.

    Retention is process-local, not a new identity source. The retained object is
    the same validated Robinhood RegistrySnapshot accepted by B1.0 selection.
    """

    def __init__(
        self, fetch_live: Callable[[], RegistrySnapshot] | None = None,
        *, retained_snapshot: RegistrySnapshot | None = None,
        max_registry_age_seconds: int = 3600,
    ) -> None:
        if max_registry_age_seconds <= 0:
            raise ValueError("registry age limit must be positive")
        self.fetch_live = fetch_live or _fetch_live_registry
        self._retained_snapshot = retained_snapshot
        self.max_registry_age_seconds = max_registry_age_seconds
        self._lock = Lock()

    def selected_registry_snapshot(self) -> RegistrySnapshot | None:
        """Return the immutable official snapshot retained by the last resolution.

        B1.3 can consume the exact B1.2 evidence without a second registry fetch.
        It still independently checks age and UID at the B1.0 calculation gate.
        """
        with self._lock:
            return self._retained_snapshot

    def resolve_snapshot(
        self, snapshot: BnbRwaMarketSnapshot, *, as_of: datetime | None = None,
    ) -> dict[AssetKey, CrossChainIdentityBinding]:
        keys = {row.asset_key for row in snapshot.observations if row.asset_key is not None}
        if not keys:
            return {}
        with self._lock:
            retained = self._retained_snapshot
        context = select_cross_chain_registry(
            self.fetch_live, retained,
            as_of=as_of if as_of is not None else lambda: datetime.now(timezone.utc),
            max_age_seconds=self.max_registry_age_seconds,
        )
        if context.origin == "LIVE" and context.selected is not None:
            with self._lock:
                self._retained_snapshot = context.selected
        return {
            key: resolve_cross_chain_identity(context, key)
            for key in sorted(keys)
        }
