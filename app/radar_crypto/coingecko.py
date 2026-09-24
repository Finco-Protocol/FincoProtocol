"""CoinGecko Demo API transport for Radar Crypto Overview.

One dashboard read performs at most two upstream calls: ``/global`` and one
batched ``/simple/price`` request for Bitcoin + Ethereum.  Missing credentials
or malformed upstream evidence fails closed; no alternative provider or guessed
market value is substituted.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.radar_crypto.contracts import (
    CryptoMetricDefinition,
    CryptoObservation,
    CryptoState,
)

_DEMO_ROOT = "https://api.coingecko.com/api/v3"


class CoinGeckoCryptoProvider:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 4.0,
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
    def _finite(value) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("NON_FINITE_VALUE")
        return parsed

    @staticmethod
    def _timestamp(value) -> datetime:
        timestamp = CoinGeckoCryptoProvider._finite(value)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    @staticmethod
    def _state(
        definition: CryptoMetricDefinition,
        retrieved_at: datetime,
        observed_at: datetime,
    ) -> CryptoState:
        age = max(0.0, (retrieved_at - observed_at).total_seconds())
        return (
            CryptoState.FRESH
            if age <= definition.max_staleness_seconds
            else CryptoState.STALE
        )

    @staticmethod
    def _unavailable(
        definition: CryptoMetricDefinition,
        retrieved_at: datetime,
        reason: str,
    ) -> CryptoObservation:
        return CryptoObservation(
            key=definition.key,
            state=CryptoState.UNAVAILABLE,
            value=None,
            change_24h=None,
            observed_at=None,
            retrieved_at=retrieved_at,
            source_endpoint=definition.source_endpoint,
            source_id=definition.source_id,
            publisher=definition.publisher,
            transport=definition.transport,
            reason=reason,
        )

    def _observation(
        self,
        definition: CryptoMetricDefinition,
        *,
        value: float,
        change_24h: float | None,
        observed_at: datetime,
        retrieved_at: datetime,
    ) -> CryptoObservation:
        if change_24h is not None:
            change_24h = self._finite(change_24h)
        return CryptoObservation(
            key=definition.key,
            state=self._state(definition, retrieved_at, observed_at),
            value=self._finite(value),
            change_24h=change_24h,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            source_endpoint=definition.source_endpoint,
            source_id=definition.source_id,
            publisher=definition.publisher,
            transport=definition.transport,
        )

    def _get(self, client: httpx.Client, path: str, *, params: dict | None = None) -> dict:
        response = client.get(
            f"{_DEMO_ROOT}{path}",
            params=params,
            headers={"x-cg-demo-api-key": self.api_key},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NON_OBJECT_PAYLOAD")
        return payload

    def _from_global(
        self,
        definition: CryptoMetricDefinition,
        payload: dict,
        retrieved_at: datetime,
    ) -> CryptoObservation:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("GLOBAL_DATA_MISSING")
        observed_at = self._timestamp(data.get("updated_at"))
        key = definition.key
        if key == "total_market_cap_usd":
            value = data["total_market_cap"]["usd"]
            change = data.get("market_cap_change_percentage_24h_usd")
        elif key == "total_volume_24h_usd":
            value = data["total_volume"]["usd"]
            change = data.get("volume_change_percentage_24h_usd")
        elif key == "btc_dominance":
            value = data["market_cap_percentage"]["btc"]
            change = None
        elif key == "eth_dominance":
            value = data["market_cap_percentage"]["eth"]
            change = None
        elif key == "active_cryptocurrencies":
            value = data["active_cryptocurrencies"]
            change = None
        else:
            raise ValueError("UNSUPPORTED_GLOBAL_METRIC")
        return self._observation(
            definition,
            value=value,
            change_24h=change,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
        )

    def _from_simple_price(
        self,
        definition: CryptoMetricDefinition,
        payload: dict,
        retrieved_at: datetime,
    ) -> CryptoObservation:
        bitcoin = payload.get("bitcoin")
        ethereum = payload.get("ethereum")
        if not isinstance(bitcoin, dict) or not isinstance(ethereum, dict):
            raise ValueError("MAJOR_ASSET_PRICE_DATA_MISSING")

        btc_observed = self._timestamp(bitcoin.get("last_updated_at"))
        eth_observed = self._timestamp(ethereum.get("last_updated_at"))
        if definition.key == "btc_price_usd":
            return self._observation(
                definition,
                value=bitcoin["usd"],
                change_24h=bitcoin.get("usd_24h_change"),
                observed_at=btc_observed,
                retrieved_at=retrieved_at,
            )
        if definition.key == "eth_price_usd":
            return self._observation(
                definition,
                value=ethereum["usd"],
                change_24h=ethereum.get("usd_24h_change"),
                observed_at=eth_observed,
                retrieved_at=retrieved_at,
            )
        if definition.key == "eth_btc_ratio":
            btc = self._finite(bitcoin["usd"])
            eth = self._finite(ethereum["usd"])
            if btc == 0:
                raise ValueError("ZERO_BTC_PRICE")
            observed_at = min(btc_observed, eth_observed)
            return self._observation(
                definition,
                value=eth / btc,
                change_24h=None,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
            )
        raise ValueError("UNSUPPORTED_SIMPLE_PRICE_METRIC")

    def read_all(
        self,
        definitions: tuple[CryptoMetricDefinition, ...],
    ) -> tuple[CryptoObservation, ...]:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        if not self.api_key:
            return tuple(
                self._unavailable(
                    definition,
                    retrieved_at,
                    "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED",
                )
                for definition in definitions
            )

        global_payload = None
        global_error = None
        simple_payload = None
        simple_error = None
        client = self._client()
        try:
            if any(d.source_endpoint == "/global" for d in definitions):
                try:
                    global_payload = self._get(client, "/global")
                except Exception as exc:  # noqa: BLE001
                    global_error = f"COINGECKO_GLOBAL_READ_FAILED:{type(exc).__name__}"
            if any(d.source_endpoint == "/simple/price" for d in definitions):
                try:
                    simple_payload = self._get(
                        client,
                        "/simple/price",
                        params={
                            "ids": "bitcoin,ethereum",
                            "vs_currencies": "usd",
                            "include_24hr_change": "true",
                            "include_last_updated_at": "true",
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    simple_error = f"COINGECKO_PRICE_READ_FAILED:{type(exc).__name__}"
        finally:
            client.close()

        observations: list[CryptoObservation] = []
        for definition in definitions:
            try:
                if definition.source_endpoint == "/global":
                    if global_payload is None:
                        observations.append(self._unavailable(
                            definition, retrieved_at, global_error or "GLOBAL_PAYLOAD_UNAVAILABLE"))
                    else:
                        observations.append(self._from_global(
                            definition, global_payload, retrieved_at))
                elif definition.source_endpoint == "/simple/price":
                    if simple_payload is None:
                        observations.append(self._unavailable(
                            definition, retrieved_at, simple_error or "PRICE_PAYLOAD_UNAVAILABLE"))
                    else:
                        observations.append(self._from_simple_price(
                            definition, simple_payload, retrieved_at))
                else:
                    observations.append(self._unavailable(
                        definition, retrieved_at, "UNSUPPORTED_SOURCE_ENDPOINT"))
            except Exception as exc:  # one malformed metric does not poison the dashboard
                observations.append(self._unavailable(
                    definition,
                    retrieved_at,
                    f"COINGECKO_NORMALIZATION_FAILED:{type(exc).__name__}",
                ))
        return tuple(observations)
