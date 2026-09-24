"""Hyperliquid perpetual asset-context transport for FINCO Radar.

The provider performs exactly one public ``metaAndAssetCtxs`` request and binds
contexts to symbols through the returned universe index.  It never assumes BTC
or ETH array positions and never substitutes data from another exchange.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.radar_derivatives.contracts import (
    DerivativesSnapshot,
    DerivativesState,
    PerpAssetSnapshot,
)

_INFO_URL = "https://api.hyperliquid.xyz/info"
_PUBLISHER = "Hyperliquid"
_TRANSPORT = "Hyperliquid Info API"
_ENDPOINT = "POST /info · metaAndAssetCtxs"
_TARGETS = ("BTC", "ETH")


class HyperliquidDerivativesProvider:
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
    def _number(value, name: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"NON_FINITE_{name}")
        return parsed

    def read(self) -> DerivativesSnapshot:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")

        client = self._client()
        try:
            response = client.post(
                _INFO_URL,
                json={"type": "metaAndAssetCtxs"},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            client.close()

        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError("MALFORMED_META_AND_ASSET_CONTEXTS")
        meta, contexts = payload
        if not isinstance(meta, dict) or not isinstance(contexts, list):
            raise ValueError("MALFORMED_META_AND_ASSET_CONTEXTS")
        universe = meta.get("universe")
        if not isinstance(universe, list) or len(universe) != len(contexts):
            raise ValueError("UNIVERSE_CONTEXT_LENGTH_MISMATCH")

        bound: dict[str, PerpAssetSnapshot] = {}
        for index, (asset_meta, context) in enumerate(zip(universe, contexts)):
            if not isinstance(asset_meta, dict) or not isinstance(context, dict):
                continue
            symbol = str(asset_meta.get("name", "")).strip().upper()
            if symbol not in _TARGETS:
                continue
            if symbol in bound:
                raise ValueError(f"DUPLICATE_SYMBOL:{symbol}")
            premium_raw = context.get("premium")
            premium = None if premium_raw is None else self._number(premium_raw, "PREMIUM")
            bound[symbol] = PerpAssetSnapshot(
                symbol=symbol,
                mark_price=self._number(context.get("markPx"), "MARK_PRICE"),
                oracle_price=self._number(context.get("oraclePx"), "ORACLE_PRICE"),
                funding_rate=self._number(context.get("funding"), "FUNDING"),
                open_interest_base=self._number(context.get("openInterest"), "OPEN_INTEREST"),
                day_notional_volume_usd=self._number(context.get("dayNtlVlm"), "DAY_NOTIONAL_VOLUME"),
                premium_rate=premium,
                retrieved_at=retrieved_at,
                publisher=_PUBLISHER,
                transport=_TRANSPORT,
                source_endpoint=_ENDPOINT,
                source_id=f"universe[{index}]={symbol}",
            )

        missing = [symbol for symbol in _TARGETS if symbol not in bound]
        if missing:
            raise ValueError("MISSING_REQUIRED_SYMBOLS:" + ",".join(missing))

        return DerivativesSnapshot(
            state=DerivativesState.AVAILABLE,
            assets=tuple(bound[symbol] for symbol in _TARGETS),
            retrieved_at=retrieved_at,
            publisher=_PUBLISHER,
            transport=_TRANSPORT,
            source_endpoint=_ENDPOINT,
        )
