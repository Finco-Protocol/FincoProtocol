"""Bounded, sanitized HTTP transport for the experimental TypeSafe Jev call."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from decimal import Decimal
from typing import Callable, Mapping, Protocol

import httpx


TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
_FAILURE_CATEGORIES = frozenset({
    "TIMEOUT", "NETWORK", "HTTP_408", "HTTP_429", "HTTP_5XX", "AUTH",
    "INVALID_REQUEST", "INVALID_RESPONSE", "RETRY_BUDGET_EXHAUSTED",
})


class TypeSafeJevTransportError(RuntimeError):
    """Sanitized failure containing only closed telemetry fields."""

    def __init__(
        self,
        failure_category: str,
        *,
        attempt_count: int | None = None,
        latency_ms: Decimal | None = None,
    ) -> None:
        if failure_category not in _FAILURE_CATEGORIES:
            failure_category = "NETWORK"
        self.failure_category = failure_category
        self.attempt_count = attempt_count
        self.latency_ms = latency_ms
        super().__init__(failure_category)


class _TransientNetworkError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _HttpResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]
    def json(self) -> object: ...


class _HttpClient(Protocol):
    def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object], timeout: float) -> _HttpResponse: ...


@dataclass(frozen=True)
class TypeSafeJevHttpConfig:
    timeout_seconds: float = 10.0
    max_retries: int = 3
    initial_backoff_seconds: float = 0.25
    max_total_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_total_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")


def _retryable_status(status: int) -> bool:
    return status in (408, 429) or 500 <= status <= 599


def _status_category(status: int) -> str:
    if status in (401, 403):
        return "AUTH"
    if status in (400, 404, 422):
        return "INVALID_REQUEST"
    if status == 408:
        return "HTTP_408"
    if status == 429:
        return "HTTP_429"
    if 500 <= status <= 599:
        return "HTTP_5XX"
    return "NETWORK"


def _retry_after_seconds(response: _HttpResponse) -> float | None:
    raw = getattr(response, "headers", {}).get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(str(raw))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None


def _contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(_contains_secret(key, secret) or _contains_secret(item, secret) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret(item, secret) for item in value)
    return False


class TypeSafeJevHttpTransport:
    """Explicit-key transport. The key is held in memory only and never serialized."""

    def __init__(
        self,
        api_key: str,
        *,
        client: _HttpClient | None = None,
        config: TypeSafeJevHttpConfig = TypeSafeJevHttpConfig(),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key.strip()
        self._client = client
        self._config = config
        self._sleep = sleep
        self._clock = clock

    def __repr__(self) -> str:
        return "TypeSafeJevHttpTransport(api_key=<redacted>)"

    def _post(self, request: Mapping[str, object]) -> _HttpResponse:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            if self._client is not None:
                return self._client.post(TYPESAFE_SYSTEMONE_URL, headers=headers, json=request, timeout=self._config.timeout_seconds)
            return httpx.post(TYPESAFE_SYSTEMONE_URL, headers=headers, json=request, timeout=self._config.timeout_seconds)
        except httpx.TimeoutException:
            raise _TransientNetworkError("TIMEOUT") from None
        except (httpx.NetworkError, OSError):
            raise _TransientNetworkError("NETWORK") from None
        except httpx.HTTPError:
            raise _TransientNetworkError("NETWORK") from None
        except Exception:
            raise _TransientNetworkError("NETWORK") from None

    def _failure(self, category: str, started: float, attempt_count: int) -> TypeSafeJevTransportError:
        elapsed = Decimal(str(max(0.0, (self._clock() - started) * 1000))).quantize(Decimal("0.001"))
        return TypeSafeJevTransportError(category, attempt_count=attempt_count, latency_ms=elapsed)

    def evaluate(self, request: Mapping[str, object]) -> Mapping[str, object]:
        if not isinstance(request, Mapping):
            raise TypeError("request must be a mapping")
        started = self._clock()
        max_attempts = self._config.max_retries + 1
        last_category = "NETWORK"

        for attempt_index in range(max_attempts):
            attempt_count = attempt_index + 1
            response = None
            try:
                response = self._post(request)
                status = response.status_code
                if status == 200:
                    try:
                        raw = response.json()
                    except Exception:
                        raise self._failure("INVALID_RESPONSE", started, attempt_count) from None
                    if not isinstance(raw, Mapping):
                        raise self._failure("INVALID_RESPONSE", started, attempt_count)
                    if _contains_secret(raw, self._api_key):
                        raise self._failure("INVALID_RESPONSE", started, attempt_count)
                    payload = dict(raw)
                    payload["_transport_meta"] = {
                        "latency_ms": str(Decimal(str((self._clock() - started) * 1000)).quantize(Decimal("0.001"))),
                        "attempt_count": attempt_count,
                    }
                    return payload
                last_category = _status_category(status)
                if not _retryable_status(status):
                    raise self._failure(last_category, started, attempt_count)
            except _TransientNetworkError as exc:
                last_category = exc.category

            if attempt_index >= self._config.max_retries:
                raise self._failure(last_category, started, attempt_count) from None
            exponential = self._config.initial_backoff_seconds * (2 ** attempt_index)
            provider_delay = _retry_after_seconds(response) if response is not None else None
            delay = max(exponential, provider_delay or 0.0)
            elapsed = self._clock() - started
            if elapsed + delay > self._config.max_total_seconds:
                raise self._failure("RETRY_BUDGET_EXHAUSTED", started, attempt_count) from None
            if delay:
                self._sleep(delay)

        raise self._failure("RETRY_BUDGET_EXHAUSTED", started, max_attempts)
