"""CoinGecko acquisition for BNB-listed tokenized-asset market observations.

Three source endpoints provide category market data, provider coin IDs with
platform contracts, and platform-to-chain IDs. CoinGecko is observation-only:
none of these calls proves Robinhood/underlying economic identity.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

import httpx

from .bnb_contracts import TOKENIZED_CATEGORY_ID, BnbRwaMarketSnapshot
from .bnb_snapshot import compose_bnb_snapshot, unavailable_bnb_snapshot


_DEMO_ROOT = "https://api.coingecko.com/api/v3"


class CoinGeckoBnbRwaProvider:
    def __init__(
        self, api_key: str | None = None, *, timeout_seconds: float = 8.0,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("COINGECKO_DEMO_API_KEY", "")
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.Client(timeout=self.timeout_seconds)

    def _get(self, client: httpx.Client, path: str, *, params: dict | None = None):
        response = client.get(
            f"{_DEMO_ROOT}{path}", params=params,
            headers={"x-cg-demo-api-key": self.api_key},
        )
        response.raise_for_status()
        return response.json()

    def read_snapshot(self) -> BnbRwaMarketSnapshot:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        retrieved_at = retrieved_at.astimezone(timezone.utc)
        if not self.api_key:
            return unavailable_bnb_snapshot(retrieved_at, "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED")
        try:
            client = self._client()
            try:
                platforms = self._get(client, "/asset_platforms")
                coins = self._get(client, "/coins/list", params={"include_platform": "true"})
                markets = self._get(client, "/coins/markets", params={
                    "vs_currency": "usd", "category": TOKENIZED_CATEGORY_ID,
                    "order": "market_cap_desc", "per_page": 250, "page": 1,
                    "sparkline": "false", "price_change_percentage": "24h",
                })
            finally:
                client.close()
            return compose_bnb_snapshot(
                platforms=platforms, coins=coins, markets=markets,
                retrieved_at=retrieved_at,
            )
        except Exception as exc:  # fail closed; no substitute identity or market data
            return unavailable_bnb_snapshot(
                retrieved_at, f"COINGECKO_BNB_READ_FAILED:{type(exc).__name__}",
            )
