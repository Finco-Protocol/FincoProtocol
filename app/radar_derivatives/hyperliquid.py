"""Hyperliquid perpetual transport for FINCO Radar Derivatives V2.

Primary context remains bound to ``metaAndAssetCtxs``. Auxiliary funding history
and predicted venue funding are read from Hyperliquid's documented Info API
endpoints and may fail independently without replacing the primary exchange
context or silently falling back to another provider.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from app.radar_derivatives.contracts import (
    DerivativesSnapshot,
    DerivativesState,
    FundingRatePoint,
    PerpAssetSnapshot,
    PredictedFundingRate,
)

_INFO_URL = "https://api.hyperliquid.xyz/info"
_PUBLISHER = "Hyperliquid"
_TRANSPORT = "Hyperliquid Info API"
_ENDPOINT = "POST /info"
_TARGETS = ("BTC", "ETH")
_VENUE_NAMES = {
    "HlPerp": "Hyperliquid",
    "BinPerp": "Binance",
    "BybitPerp": "Bybit",
}
_MAX_FUTURE_SKEW_SECONDS = 5 * 60


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

    @classmethod
    def _optional_number(cls, value, name: str) -> float | None:
        if value is None:
            return None
        return cls._number(value, name)

    @staticmethod
    def _timestamp_ms(value, name: str) -> datetime:
        if isinstance(value, bool):
            raise ValueError(f"INVALID_{name}")
        timestamp_ms = int(value)
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)

    @staticmethod
    def _max_leverage(value) -> int:
        if isinstance(value, bool):
            raise ValueError("INVALID_MAX_LEVERAGE")
        leverage = int(value)
        if leverage <= 0:
            raise ValueError("INVALID_MAX_LEVERAGE")
        return leverage

    @staticmethod
    def _funding_interval_hours(value, *, venue_code: str) -> int | None:
        # Hyperliquid settles hourly; keep that venue-local invariant explicit
        # when the aggregation omits the optional interval field. External
        # venues are never assigned a guessed interval.
        if value is None:
            return 1 if venue_code == "HlPerp" else None
        if isinstance(value, bool):
            raise ValueError(f"INVALID_FUNDING_INTERVAL:{venue_code}")
        interval = int(value)
        if interval <= 0:
            raise ValueError(f"INVALID_FUNDING_INTERVAL:{venue_code}")
        return interval

    @staticmethod
    def _post(client: httpx.Client, body: dict):
        response = client.post(
            _INFO_URL,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    def _parse_primary(self, payload, retrieved_at: datetime) -> tuple[PerpAssetSnapshot, ...]:
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

            impact_raw = context.get("impactPxs")
            impact_bid = None
            impact_ask = None
            if impact_raw is not None:
                if not isinstance(impact_raw, list) or len(impact_raw) != 2:
                    raise ValueError(f"INVALID_IMPACT_PRICES:{symbol}")
                impact_bid = self._number(impact_raw[0], f"{symbol}_IMPACT_BID")
                impact_ask = self._number(impact_raw[1], f"{symbol}_IMPACT_ASK")

            bound[symbol] = PerpAssetSnapshot(
                symbol=symbol,
                mark_price=self._number(context.get("markPx"), f"{symbol}_MARK_PRICE"),
                oracle_price=self._number(context.get("oraclePx"), f"{symbol}_ORACLE_PRICE"),
                prev_day_price=self._number(context.get("prevDayPx"), f"{symbol}_PREV_DAY_PRICE"),
                mid_price=self._optional_number(context.get("midPx"), f"{symbol}_MID_PRICE"),
                impact_bid_price=impact_bid,
                impact_ask_price=impact_ask,
                funding_rate=self._number(context.get("funding"), f"{symbol}_FUNDING"),
                open_interest_base=self._number(context.get("openInterest"), f"{symbol}_OPEN_INTEREST"),
                day_notional_volume_usd=self._number(
                    context.get("dayNtlVlm"), f"{symbol}_DAY_NOTIONAL_VOLUME"
                ),
                premium_rate=self._optional_number(context.get("premium"), f"{symbol}_PREMIUM"),
                max_leverage=self._max_leverage(asset_meta.get("maxLeverage")),
                retrieved_at=retrieved_at,
                publisher=_PUBLISHER,
                transport=_TRANSPORT,
                source_endpoint="POST /info · metaAndAssetCtxs",
                source_id=f"universe[{index}]={symbol}",
            )

        missing = [symbol for symbol in _TARGETS if symbol not in bound]
        if missing:
            raise ValueError("MISSING_REQUIRED_SYMBOLS:" + ",".join(missing))
        return tuple(bound[symbol] for symbol in _TARGETS)

    def _read_funding_history(
        self,
        client: httpx.Client,
        retrieved_at: datetime,
    ) -> tuple[FundingRatePoint, ...]:
        start_at = retrieved_at - timedelta(hours=24)
        start_ms = int(start_at.timestamp() * 1000)
        end_ms = int(retrieved_at.timestamp() * 1000)
        points: list[FundingRatePoint] = []
        seen: set[tuple[str, int]] = set()

        for symbol in _TARGETS:
            payload = self._post(
                client,
                {
                    "type": "fundingHistory",
                    "coin": symbol,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            )
            if not isinstance(payload, list):
                raise ValueError(f"FUNDING_HISTORY_INVALID:{symbol}")
            for raw in payload:
                if not isinstance(raw, dict):
                    raise ValueError(f"FUNDING_HISTORY_ROW_INVALID:{symbol}")
                returned_symbol = str(raw.get("coin", "")).strip().upper()
                if returned_symbol != symbol:
                    raise ValueError(f"FUNDING_HISTORY_SYMBOL_MISMATCH:{symbol}")
                observed_at = self._timestamp_ms(raw.get("time"), f"{symbol}_FUNDING_TIME")
                if (observed_at - retrieved_at).total_seconds() > _MAX_FUTURE_SKEW_SECONDS:
                    raise ValueError(f"FUNDING_HISTORY_FUTURE_TIMESTAMP:{symbol}")
                if observed_at < start_at - timedelta(minutes=5):
                    raise ValueError(f"FUNDING_HISTORY_OUTSIDE_WINDOW:{symbol}")
                key = (symbol, int(observed_at.timestamp() * 1000))
                if key in seen:
                    raise ValueError(f"FUNDING_HISTORY_DUPLICATE:{symbol}")
                seen.add(key)
                points.append(
                    FundingRatePoint(
                        symbol=symbol,
                        funding_rate=self._number(raw.get("fundingRate"), f"{symbol}_HISTORY_RATE"),
                        premium_rate=self._optional_number(
                            raw.get("premium"), f"{symbol}_HISTORY_PREMIUM"
                        ),
                        observed_at=observed_at,
                    )
                )

        points.sort(key=lambda point: (point.symbol, point.observed_at))
        return tuple(points)

    def _read_predicted_funding(
        self,
        client: httpx.Client,
    ) -> tuple[PredictedFundingRate, ...]:
        payload = self._post(client, {"type": "predictedFundings"})
        if not isinstance(payload, list):
            raise ValueError("PREDICTED_FUNDING_INVALID")

        rows: list[PredictedFundingRate] = []
        seen: set[tuple[str, str]] = set()
        returned_targets: set[str] = set()
        for item in payload:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("PREDICTED_FUNDING_ROW_INVALID")
            symbol = str(item[0]).strip().upper()
            if symbol not in _TARGETS:
                continue
            returned_targets.add(symbol)
            venues = item[1]
            if not isinstance(venues, list):
                raise ValueError(f"PREDICTED_FUNDING_VENUES_INVALID:{symbol}")
            for venue_item in venues:
                if not isinstance(venue_item, list) or len(venue_item) != 2:
                    raise ValueError(f"PREDICTED_FUNDING_VENUE_ROW_INVALID:{symbol}")
                venue_code = str(venue_item[0]).strip()
                if not venue_code:
                    raise ValueError(f"PREDICTED_FUNDING_VENUE_CODE_INVALID:{symbol}")
                detail = venue_item[1]
                # Hyperliquid may return a null detail when a venue does not list
                # the asset. That is absence of venue evidence, not corruption.
                if detail is None:
                    continue
                if not isinstance(detail, dict):
                    raise ValueError(f"PREDICTED_FUNDING_VENUE_DETAIL_INVALID:{symbol}")
                key = (symbol, venue_code)
                if key in seen:
                    raise ValueError(f"PREDICTED_FUNDING_DUPLICATE:{symbol}:{venue_code}")
                seen.add(key)
                rows.append(
                    PredictedFundingRate(
                        symbol=symbol,
                        venue_code=venue_code,
                        venue_name=_VENUE_NAMES.get(venue_code, venue_code),
                        funding_rate=self._number(
                            detail.get("fundingRate"), f"{symbol}_{venue_code}_PREDICTED_RATE"
                        ),
                        next_funding_at=self._timestamp_ms(
                            detail.get("nextFundingTime"),
                            f"{symbol}_{venue_code}_NEXT_FUNDING_TIME",
                        ),
                        funding_interval_hours=self._funding_interval_hours(
                            detail.get("fundingIntervalHours"), venue_code=venue_code
                        ),
                    )
                )

        missing = [symbol for symbol in _TARGETS if symbol not in returned_targets]
        if missing:
            raise ValueError("PREDICTED_FUNDING_MISSING_SYMBOLS:" + ",".join(missing))
        return tuple(rows)

    def read(self) -> DerivativesSnapshot:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        retrieved_at = retrieved_at.astimezone(timezone.utc)

        client = self._client()
        try:
            primary_payload = self._post(client, {"type": "metaAndAssetCtxs"})
            assets = self._parse_primary(primary_payload, retrieved_at)

            funding_history: tuple[FundingRatePoint, ...] = ()
            funding_history_reason = None
            try:
                funding_history = self._read_funding_history(client, retrieved_at)
            except Exception as exc:  # auxiliary source fails independently
                funding_history_reason = f"FUNDING_HISTORY_READ_FAILED:{type(exc).__name__}"

            predicted_funding: tuple[PredictedFundingRate, ...] = ()
            predicted_funding_reason = None
            try:
                predicted_funding = self._read_predicted_funding(client)
            except Exception as exc:  # auxiliary source fails independently
                predicted_funding_reason = f"PREDICTED_FUNDING_READ_FAILED:{type(exc).__name__}"
        finally:
            client.close()

        return DerivativesSnapshot(
            state=DerivativesState.AVAILABLE,
            assets=assets,
            retrieved_at=retrieved_at,
            publisher=_PUBLISHER,
            transport=_TRANSPORT,
            source_endpoint=_ENDPOINT,
            funding_history=funding_history,
            predicted_funding=predicted_funding,
            funding_history_reason=funding_history_reason,
            predicted_funding_reason=predicted_funding_reason,
        )
