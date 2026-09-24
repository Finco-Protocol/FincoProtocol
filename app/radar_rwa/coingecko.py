"""CoinGecko Demo API transport for Radar RWA intelligence.

The dedicated CoinGecko RWA endpoints aggregate tokenized versions of the same
underlying real-world asset across issuers.  They do not provide the underlying
spot-market authority.  This adapter keeps that boundary explicit and never
turns tokenized-market data into a premium/discount claim.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.radar_rwa.contracts import (
    RwaAssetMarket,
    RwaAssetState,
    RwaAssetType,
    RwaSnapshot,
    RwaSnapshotState,
)

_DEMO_ROOT = "https://api.coingecko.com/api/v3"
_MAX_STALENESS_SECONDS = 30 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60


class CoinGeckoRwaProvider:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 5.0,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None
            else os.environ.get("COINGECKO_DEMO_API_KEY", "")
        )
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.Client(timeout=self.timeout_seconds)

    @staticmethod
    def _finite_optional(value) -> float | None:
        if value is None:
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("NON_FINITE_RWA_VALUE")
        return parsed

    @staticmethod
    def _timestamp(value) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("RWA_LAST_UPDATED_MISSING")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("RWA_LAST_UPDATED_NAIVE")
        return parsed.astimezone(timezone.utc)

    def _get(self, client: httpx.Client, path: str, *, params: dict | None = None):
        response = client.get(
            f"{_DEMO_ROOT}{path}",
            params=params,
            headers={"x-cg-demo-api-key": self.api_key},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _normalize_universe(payload) -> dict[str, tuple[str, str, RwaAssetType]]:
        if not isinstance(payload, list) or not payload:
            raise ValueError("RWA_LIST_INVALID")
        universe: dict[str, tuple[str, str, RwaAssetType]] = {}
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError("RWA_LIST_ROW_INVALID")
            rwa_id = str(row.get("id", "")).strip()
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            asset_type = RwaAssetType(str(row.get("asset_type", "")).strip())
            if not rwa_id or not symbol or not name:
                raise ValueError("RWA_LIST_IDENTITY_MISSING")
            if rwa_id in universe:
                raise ValueError("RWA_LIST_DUPLICATE_ID")
            universe[rwa_id] = (symbol, name, asset_type)
        return universe

    def _normalize_market_rows(
        self,
        payload,
        universe: dict[str, tuple[str, str, RwaAssetType]],
        retrieved_at: datetime,
        *,
        expected_type: RwaAssetType | None = None,
    ) -> tuple[RwaAssetMarket, ...]:
        if not isinstance(payload, list):
            raise ValueError("RWA_MARKETS_INVALID")
        rows: list[RwaAssetMarket] = []
        seen: set[str] = set()
        for raw in payload:
            if not isinstance(raw, dict):
                raise ValueError("RWA_MARKET_ROW_INVALID")
            rwa_id = str(raw.get("id", "")).strip()
            if not rwa_id or rwa_id in seen or rwa_id not in universe:
                raise ValueError("RWA_MARKET_IDENTITY_INVALID")
            seen.add(rwa_id)
            symbol = str(raw.get("symbol", "")).strip()
            name = str(raw.get("name", "")).strip()
            asset_type = RwaAssetType(str(raw.get("asset_type", "")).strip())
            list_symbol, list_name, list_type = universe[rwa_id]
            if symbol.casefold() != list_symbol.casefold() or name != list_name or asset_type is not list_type:
                raise ValueError("RWA_SOURCE_BINDING_MISMATCH")
            if expected_type is not None and asset_type is not expected_type:
                raise ValueError("RWA_ASSET_TYPE_FILTER_MISMATCH")
            market = raw.get("tokenized_market_data")
            if not isinstance(market, dict):
                raise ValueError("RWA_TOKENIZED_MARKET_DATA_MISSING")
            observed_at = self._timestamp(market.get("last_updated"))
            future_skew = (observed_at - retrieved_at).total_seconds()
            if future_skew > _MAX_FUTURE_SKEW_SECONDS:
                raise ValueError("RWA_SOURCE_TIMESTAMP_IN_FUTURE")
            age_seconds = max(0.0, (retrieved_at - observed_at).total_seconds())
            state = (
                RwaAssetState.FRESH
                if age_seconds <= _MAX_STALENESS_SECONDS
                else RwaAssetState.STALE
            )
            rows.append(RwaAssetMarket(
                id=rwa_id,
                symbol=symbol.upper(),
                name=name,
                asset_type=asset_type,
                state=state,
                current_price=self._finite_optional(market.get("current_price")),
                market_cap=self._finite_optional(market.get("market_cap")),
                total_volume=self._finite_optional(market.get("total_volume")),
                price_change_24h=self._finite_optional(market.get("price_change_percentage_24h")),
                price_change_7d=self._finite_optional(market.get("price_change_percentage_7d_in_currency")),
                price_change_30d=self._finite_optional(market.get("price_change_percentage_30d_in_currency")),
                observed_at=observed_at,
                retrieved_at=retrieved_at,
            ))
        return tuple(rows)

    @staticmethod
    def _unavailable(retrieved_at: datetime, reason: str) -> RwaSnapshot:
        return RwaSnapshot(
            state=RwaSnapshotState.UNAVAILABLE,
            retrieved_at=retrieved_at,
            total_count=0,
            stock_count=0,
            commodity_count=0,
            etf_count=0,
            leaders=(),
            stock_leaders=(),
            reason=reason,
        )

    def read_snapshot(self) -> RwaSnapshot:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        retrieved_at = retrieved_at.astimezone(timezone.utc)
        if not self.api_key:
            return self._unavailable(retrieved_at, "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED")

        try:
            client = self._client()
            try:
                universe_payload = self._get(client, "/rwas/list")
                leaders_payload = self._get(client, "/rwas/markets", params={
                    "order": "market_cap_desc",
                    "per_page": 12,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d,30d",
                })
                stock_payload = self._get(client, "/rwas/markets", params={
                    "asset_type": "stock",
                    "order": "market_cap_desc",
                    "per_page": 12,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d,30d",
                })
            finally:
                client.close()

            universe = self._normalize_universe(universe_payload)
            leaders = self._normalize_market_rows(leaders_payload, universe, retrieved_at)
            stock_leaders = self._normalize_market_rows(
                stock_payload, universe, retrieved_at, expected_type=RwaAssetType.STOCK,
            )
            counts = {asset_type: 0 for asset_type in RwaAssetType}
            for _, _, asset_type in universe.values():
                counts[asset_type] += 1
            return RwaSnapshot(
                state=RwaSnapshotState.AVAILABLE,
                retrieved_at=retrieved_at,
                total_count=len(universe),
                stock_count=counts[RwaAssetType.STOCK],
                commodity_count=counts[RwaAssetType.COMMODITY],
                etf_count=counts[RwaAssetType.ETF],
                leaders=leaders,
                stock_leaders=stock_leaders,
            )
        except Exception as exc:  # fail closed at provider boundary
            return self._unavailable(
                retrieved_at,
                f"COINGECKO_RWA_READ_FAILED:{type(exc).__name__}",
            )
