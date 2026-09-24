"""FRED transport for Radar Economy.

The adapter retrieves observations only.  Series meaning, publisher, units,
transforms and freshness policy remain owned by the typed FINCO registry.
A missing API key fails closed to UNAVAILABLE and never fabricates a value.
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from typing import Callable

import httpx

from app.radar_economy.contracts import (
    EconomyObservation,
    EconomySeriesDefinition,
    EconomyState,
    EconomyTransform,
)

_FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredEconomyProvider:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 4.0,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("FRED_API_KEY", "")
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _client(self) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.Client(timeout=self.timeout_seconds)

    @staticmethod
    def _valid_observations(payload: dict) -> list[tuple[date, float]]:
        rows: list[tuple[date, float]] = []
        observations = payload.get("observations", [])
        if not isinstance(observations, list):
            return rows
        for row in observations:
            if not isinstance(row, dict):
                continue
            try:
                period = date.fromisoformat(str(row.get("date", "")))
                value = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                rows.append((period, value))
        rows.sort(key=lambda item: item[0])
        return rows

    @staticmethod
    def _transform(
        definition: EconomySeriesDefinition,
        rows: list[tuple[date, float]],
    ) -> tuple[float, float | None, date]:
        if not rows:
            raise ValueError("NO_VALID_OBSERVATIONS")

        latest_period, latest = rows[-1]
        transform = definition.transform

        if transform is EconomyTransform.LEVEL:
            previous = rows[-2][1] if len(rows) >= 2 else None
            return latest, previous, latest_period

        if transform is EconomyTransform.LEVEL_PERCENT_TO_BPS:
            previous = rows[-2][1] * 100.0 if len(rows) >= 2 else None
            return latest * 100.0, previous, latest_period

        if transform is EconomyTransform.PERIOD_CHANGE:
            if len(rows) < 2:
                raise ValueError("INSUFFICIENT_OBSERVATIONS_FOR_PERIOD_CHANGE")
            value = latest - rows[-2][1]
            previous = rows[-2][1] - rows[-3][1] if len(rows) >= 3 else None
            return value, previous, latest_period

        if transform is EconomyTransform.YOY_PERCENT_CHANGE:
            # Registry v1 uses this transform only for contiguous monthly CPI
            # series.  14 observations provide both the latest and previous
            # year-over-year readings without asking FRED to calculate them.
            if len(rows) < 13:
                raise ValueError("INSUFFICIENT_OBSERVATIONS_FOR_YOY")
            base = rows[-13][1]
            if base == 0:
                raise ValueError("ZERO_BASE_FOR_YOY")
            value = ((latest / base) - 1.0) * 100.0
            previous = None
            if len(rows) >= 14:
                prior_base = rows[-14][1]
                if prior_base != 0:
                    previous = ((rows[-2][1] / prior_base) - 1.0) * 100.0
            return value, previous, latest_period

        raise ValueError(f"UNSUPPORTED_TRANSFORM:{transform.value}")

    def _unavailable(
        self,
        definition: EconomySeriesDefinition,
        retrieved_at: datetime,
        reason: str,
    ) -> EconomyObservation:
        return EconomyObservation(
            key=definition.key,
            state=EconomyState.UNAVAILABLE,
            value=None,
            previous=None,
            period=None,
            retrieved_at=retrieved_at,
            source_series_id=definition.source_series_id,
            publisher=definition.publisher,
            transport=definition.transport,
            reason=reason,
        )

    def read(self, definition: EconomySeriesDefinition) -> EconomyObservation:
        retrieved_at = self.now()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        if definition.transport != "FRED":
            return self._unavailable(definition, retrieved_at, "UNSUPPORTED_TRANSPORT")
        if not self.api_key:
            return self._unavailable(definition, retrieved_at, "FRED_API_KEY_NOT_CONFIGURED")

        try:
            client = self._client()
            try:
                response = client.get(
                    _FRED_OBSERVATIONS_URL,
                    params={
                        "series_id": definition.source_series_id,
                        "api_key": self.api_key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 30,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                client.close()

            rows = self._valid_observations(payload)
            value, previous, period = self._transform(definition, rows)
            age_days = (retrieved_at.date() - period).days
            state = (
                EconomyState.FRESH
                if age_days <= definition.max_staleness_days
                else EconomyState.STALE
            )
            return EconomyObservation(
                key=definition.key,
                state=state,
                value=value,
                previous=previous,
                period=period,
                retrieved_at=retrieved_at,
                source_series_id=definition.source_series_id,
                publisher=definition.publisher,
                transport=definition.transport,
            )
        except Exception as exc:  # provider failures stay typed/unavailable at the UI boundary
            return self._unavailable(
                definition,
                retrieved_at,
                f"FRED_READ_FAILED:{type(exc).__name__}",
            )
