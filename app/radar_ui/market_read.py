"""Cached read-only Robinhood bound-reference market surface.

Uses the existing R1 registry binding and R2 token-equivalent reference authority.
No AcquisitionService or executable quote path is called here.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from app.radar_ui import composition
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import normalize_asset_uid
from finco_radar.gap.engine import build_bound_reference_price


class MarketReadService:
    def __init__(self, registry_factory: Callable | None = None, *, ttl_seconds: float = 10.0):
        self.registry_factory = registry_factory
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._last_board: list[str] = []

    def _factory(self):
        factory = self.registry_factory or composition._registry_factory_override
        return factory() if factory else RobinhoodAssetRegistryAdapter(timeout_seconds=4.0)

    @staticmethod
    def _unavailable(uid: str) -> dict:
        return {"uid": uid, "state": "UNAVAILABLE", "price": None,
                "bid": None, "ask": None, "observed_at": None, "source": None}

    def _failure(self, uid: str) -> dict:
        old = self._cache.get(uid)
        if old and old[1]["state"] != "UNAVAILABLE":
            return {**old[1], "state": "STALE"}
        return self._unavailable(uid)

    def _read_one(self, registry, snapshot, asset, key) -> dict:
        composition.bind_reference_identity(
            asset, key, economic_asset_uid=asset.asset_uid,
            chain_id=key.chain_id, contract_address=key.contract_address,
        )
        binding, row = registry.fetch_bound_reference(snapshot, key)
        bound = build_bound_reference_price(asset, binding, row)
        age = (datetime.now(timezone.utc) - bound.generated_at).total_seconds()
        return {
            "uid": asset.asset_uid, "chain_id": key.chain_id,
            "contract_address": key.contract_address,
            "state": "FRESH" if -60 <= age <= 120 else "STALE",
            "price": str(bound.token_midpoint_usd_per_token),
            "bid": str(bound.token_bid_usd_per_token),
            "ask": str(bound.token_ask_usd_per_token),
            "observed_at": bound.generated_at.isoformat(),
            "source": bound.source,
            "market_state": "HALTED" if bound.is_trading_halt else "REFERENCE",
        }

    def read(self, *, uids: tuple[str, ...] = (), featured_symbols: tuple[str, ...] = ()) -> list[dict]:
        """One registry snapshot, bounded reference fanout, coalesced across callers."""
        with self._lock:
            now = time.monotonic()
            if uids and all(uid in self._cache and now - self._cache[uid][0] < self.ttl_seconds for uid in uids):
                return [self._cache[uid][1] for uid in uids]
            if featured_symbols and self._last_board and all(
                uid in self._cache and now - self._cache[uid][0] < self.ttl_seconds
                for uid in self._last_board
            ):
                return [self._cache[uid][1] for uid in self._last_board]

            try:
                registry = self._factory()
                try:
                    snapshot = registry.fetch_snapshot()
                    targets = []
                    if featured_symbols:
                        for symbol in featured_symbols:
                            matches = [a for a in snapshot.assets if a.token_symbol.upper() == symbol.upper()
                                       and a.deployment_for_chain(composition._TARGET_CHAIN_ID)]
                            if len(matches) == 1:
                                targets.append(matches[0])
                    else:
                        targets = [snapshot.get_by_uid(uid) for uid in uids]
                    resolved = []
                    for asset in targets:
                        if asset is None:
                            continue
                        key = asset.deployment_for_chain(composition._TARGET_CHAIN_ID)
                        if key is not None:
                            resolved.append((asset, key))
                    if uids:
                        resolved_ids = {asset.asset_uid for asset, _ in resolved}
                        for uid in uids:
                            if uid not in resolved_ids:
                                self._cache[uid] = (time.monotonic(), self._unavailable(uid))
                    if featured_symbols:
                        self._last_board = [asset.asset_uid for asset, _ in resolved]
                    for asset, key in resolved:
                        previous = self._cache.get(asset.asset_uid)
                        if previous and (
                            previous[1].get("chain_id"),
                            previous[1].get("contract_address", "").lower(),
                        ) != (key.chain_id, key.contract_address.lower()):
                            self._cache.pop(asset.asset_uid, None)
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        futures = [pool.submit(self._read_one, registry, snapshot, asset, key)
                                   for asset, key in resolved]
                        for (asset, key), future in zip(resolved, futures):
                            uid = asset.asset_uid
                            try:
                                row = future.result()
                                self._cache[uid] = (time.monotonic(), row)
                            except Exception:
                                self._cache[uid] = (time.monotonic(), self._failure(uid))
                finally:
                    close = getattr(registry, "close", None)
                    if callable(close):
                        close()
            except Exception:
                ids = list(self._last_board) if featured_symbols else list(uids)
                return [self._failure(uid) for uid in ids]

            ids = self._last_board if featured_symbols else list(uids)
            return [self._cache[uid][1] if uid in self._cache else self._unavailable(uid)
                    for uid in ids]
