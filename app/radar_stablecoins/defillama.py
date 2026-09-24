"""DefiLlama Stablecoins API transport.

The public stablecoin list endpoint provides current + previous day/week/month
circulating amounts and optional prices.  The endpoint does not expose a source
observation timestamp, so FINCO records only retrieval time and deliberately
uses AVAILABLE/UNAVAILABLE rather than claiming FRESH/STALE.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.radar_stablecoins.contracts import (
    StablecoinAssetRecord,
    StablecoinSnapshot,
    StablecoinState,
)

_BASE_URL = "https://stablecoins.llama.fi"
_ENDPOINT = "/stablecoins?includePrices=true"
_PUBLISHER = "DefiLlama"
_TRANSPORT = "DefiLlama Stablecoins API"


class DefiLlamaStablecoinProvider:
    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.Client(timeout=self.timeout_seconds)

    @staticmethod
    def _number(container: dict, key: str, *, required: bool = False) -> float | None:
        value = container.get(key)
        if value is None:
            if required:
                raise ValueError(f"MISSING_{key}")
            return None
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"INVALID_{key}")
        return parsed

    @classmethod
    def _pegged_usd(cls, value, *, required: bool = False) -> float | None:
        if not isinstance(value, dict):
            if required:
                raise ValueError("MISSING_PEGGED_ASSET")
            return None
        return cls._number(value, "peggedUSD", required=required)

    @classmethod
    def _parse_asset(cls, raw: dict) -> StablecoinAssetRecord | None:
        if raw.get("pegType") != "peggedUSD":
            return None
        current = cls._pegged_usd(raw.get("circulating"), required=True)
        price_raw = raw.get("price")
        price = None
        if price_raw is not None:
            price = float(price_raw)
            if not math.isfinite(price) or price < 0:
                raise ValueError("INVALID_PRICE")
        return StablecoinAssetRecord(
            asset_id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            symbol=str(raw.get("symbol", "")),
            peg_type="peggedUSD",
            current=current,
            previous_day=cls._pegged_usd(raw.get("circulatingPrevDay")),
            previous_week=cls._pegged_usd(raw.get("circulatingPrevWeek")),
            previous_month=cls._pegged_usd(raw.get("circulatingPrevMonth")),
            price=price,
        )

    def _unavailable(self, retrieved_at: datetime, reason: str) -> StablecoinSnapshot:
        return StablecoinSnapshot(
            state=StablecoinState.UNAVAILABLE,
            retrieved_at=retrieved_at,
            assets=(),
            publisher=_PUBLISHER,
            transport=_TRANSPORT,
            source_endpoint=_ENDPOINT,
            reason=reason,
        )

    def read_snapshot(self) -> StablecoinSnapshot:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        try:
            client = self._client()
            try:
                response = client.get(
                    f"{_BASE_URL}/stablecoins",
                    params={"includePrices": "true"},
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                client.close()
            if not isinstance(payload, dict) or not isinstance(payload.get("peggedAssets"), list):
                raise ValueError("INVALID_STABLECOINS_PAYLOAD")
            assets: list[StablecoinAssetRecord] = []
            for raw in payload["peggedAssets"]:
                if not isinstance(raw, dict):
                    continue
                if raw.get("pegType") != "peggedUSD":
                    continue
                # A malformed USD-pegged row could bias the aggregate downward;
                # fail the complete snapshot instead of silently omitting it.
                parsed = self._parse_asset(raw)
                if parsed is not None:
                    assets.append(parsed)
            if not assets:
                raise ValueError("NO_VALID_USD_STABLECOINS")
            return StablecoinSnapshot(
                state=StablecoinState.AVAILABLE,
                retrieved_at=retrieved_at,
                assets=tuple(assets),
                publisher=_PUBLISHER,
                transport=_TRANSPORT,
                source_endpoint=_ENDPOINT,
            )
        except Exception as exc:  # provider boundary is fail-closed
            return self._unavailable(
                retrieved_at,
                f"DEFILLAMA_STABLECOINS_READ_FAILED:{type(exc).__name__}",
            )
