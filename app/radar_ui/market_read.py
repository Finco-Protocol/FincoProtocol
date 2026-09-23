"""Cached read-only Robinhood bound-reference market surface.

Uses the existing registry and token-equivalent reference authority. No
AcquisitionService, executable quote, or GAP path is called here.
"""
from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock, BoundedSemaphore
from typing import Callable

from app.radar_ui import composition
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import normalize_asset_uid
from finco_radar.gap.engine import build_bound_reference_price


class MarketReadService:
    def __init__(self, registry_factory: Callable | None = None, *, ttl_seconds: float = 10.0):
        self.registry_factory = registry_factory
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()  # cache and in-flight metadata only; never held through provider I/O
        self._provider_slots = BoundedSemaphore(8)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._boards: dict[tuple[str, ...], tuple[float, list[dict]]] = {}
        self._inflight: dict[tuple, Future] = {}

    def _factory(self):
        factory = self.registry_factory or composition._registry_factory_override
        return factory() if factory else RobinhoodAssetRegistryAdapter(timeout_seconds=4.0)

    @staticmethod
    def _unavailable(uid: str | None, symbol: str | None = None) -> dict:
        return {"uid": uid, "symbol": symbol, "state": "UNAVAILABLE", "price": None,
                "bid": None, "ask": None, "observed_at": None, "source": None}

    @staticmethod
    def _stale(old: dict | None, uid: str | None, symbol: str | None = None) -> dict:
        if old and old.get("price") is not None:
            return {**old, "state": "STALE"}  # source observed_at is unchanged
        return MarketReadService._unavailable(uid, symbol)

    def _read_one(self, registry, snapshot, asset, key) -> dict:
        with self._provider_slots:
            composition.bind_reference_identity(
                asset, key, economic_asset_uid=asset.asset_uid,
                chain_id=key.chain_id, contract_address=key.contract_address,
            )
            binding, row = registry.fetch_bound_reference(snapshot, key)
            bound = build_bound_reference_price(asset, binding, row)
        age = (datetime.now(timezone.utc) - bound.generated_at).total_seconds()
        return {
            "uid": asset.asset_uid, "symbol": asset.token_symbol,
            "chain_id": key.chain_id, "contract_address": key.contract_address,
            "state": "FRESH" if -60 <= age <= 120 else "STALE",
            "price": str(bound.token_midpoint_usd_per_token),
            "bid": str(bound.token_bid_usd_per_token),
            "ask": str(bound.token_ask_usd_per_token),
            "observed_at": bound.generated_at.isoformat(),
            "source": bound.source,
            "market_state": "HALTED" if bound.is_trading_halt else "REFERENCE",
        }

    def _do_read(self, uids: tuple[str, ...], symbols: tuple[str, ...]) -> list[dict]:
        with self._lock:
            previous = self._boards.get(symbols, (0, []))[1] if symbols else []
            old_by_symbol = {row.get("symbol"): row for row in previous}
            old_by_uid = {uid: self._cache.get(uid, (0, None))[1] for uid in uids}
        try:
            with self._provider_slots:
                registry = self._factory()
                snapshot = registry.fetch_snapshot()
            try:
                if symbols:
                    targets = []
                    for symbol in symbols:
                        matches = [asset for asset in snapshot.assets
                                   if asset.token_symbol.upper() == symbol.upper()
                                   and asset.deployment_for_chain(composition._TARGET_CHAIN_ID)]
                        targets.append(matches[0] if len(matches) == 1 else None)
                else:
                    targets = [snapshot.get_by_uid(uid) for uid in uids]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    jobs = []
                    for asset in targets:
                        key = asset.deployment_for_chain(composition._TARGET_CHAIN_ID) if asset else None
                        jobs.append((asset, key, pool.submit(self._read_one, registry, snapshot, asset, key)
                                     if key else None))
                    results = []
                    for index, (asset, key, future) in enumerate(jobs):
                        symbol = symbols[index] if symbols else None
                        uid = asset.asset_uid if asset else (None if symbols else uids[index])
                        old = old_by_symbol.get(symbol) if symbols else old_by_uid.get(uid)
                        # Same UID is insufficient if a contract or chain changed.
                        if old and key and (old.get("chain_id"), (old.get("contract_address") or "").lower()) != (
                            key.chain_id, key.contract_address.lower()
                        ):
                            old = None
                        try:
                            row = future.result() if future else self._unavailable(uid, symbol)
                        except Exception:
                            row = self._stale(old, uid, symbol)
                        results.append({**row, "symbol": symbol or row.get("symbol")})
                return results
            finally:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
        except Exception:
            if symbols:
                return [self._stale(old_by_symbol.get(symbol), None, symbol) for symbol in symbols]
            return [self._stale(old_by_uid.get(uid), uid) for uid in uids]

    def read(self, *, uids: tuple[str, ...] = (), featured_symbols: tuple[str, ...] = ()) -> list[dict]:
        """One registry snapshot per distinct board or selected UID request.

        Same-key callers coalesce; unrelated selected requests can run while a
        board's provider fanout is in progress.
        """
        symbols = tuple(featured_symbols)
        requested = tuple(uids)
        key = ("board", symbols) if symbols else ("uid", requested)
        with self._lock:
            now = time.monotonic()
            if symbols:
                cached = self._boards.get(symbols)
                if cached and now - cached[0] < self.ttl_seconds:
                    return cached[1]
            elif requested and all(uid in self._cache and now - self._cache[uid][0] < self.ttl_seconds for uid in requested):
                return [self._cache[uid][1] for uid in requested]
            future = self._inflight.get(key)
            leader = future is None
            if leader:
                future = Future()
                self._inflight[key] = future
        if not leader:
            return future.result()
        try:
            result = self._do_read(requested, symbols)
            with self._lock:
                stamp = time.monotonic()
                if symbols:
                    self._boards[symbols] = (stamp, result)
                for row in result:
                    if row.get("uid"):
                        self._cache[row["uid"]] = (stamp, row)
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)


def board_metadata(rows: list[dict]) -> dict:
    """A board status derived exclusively from returned bound-reference rows."""
    counts = {state: sum(row.get("state") == state for row in rows)
              for state in ("FRESH", "STALE", "UNAVAILABLE")}
    observations = [row["observed_at"] for row in rows
                    if row.get("state") == "FRESH" and row.get("observed_at")]
    return {
        "state": "STALE" if counts["STALE"] else
                 "PARTIAL" if counts["FRESH"] and counts["UNAVAILABLE"] else
                 "FRESH" if counts["FRESH"] else "UNAVAILABLE",
        "refreshed_at": max(observations) if observations else None,
        "asset_count": len(rows), "fresh_count": counts["FRESH"],
        "stale_count": counts["STALE"], "unavailable_count": counts["UNAVAILABLE"],
    }
