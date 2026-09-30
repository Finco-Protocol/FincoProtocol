"""Bounded, sanitized HTTP transport for TypeSafe Jev System One.

Design reference: experimental PR #119 (``typesafe_transport.py``). The retry, redaction and
failure-category behaviour is refactored here; nothing from that branch is imported.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping, Protocol

import httpx

from .contracts import FAILURE_CATEGORIES

TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_MODELS_URL = "https://api.typesafe.ai/v1/models"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-typesafe-request-id")


class JevTransportError(RuntimeError):
    """Sanitized failure containing only closed telemetry fields (never provider text)."""

    def __init__(self, failure_category: str, *, attempt_count: int | None = None,
                 latency_ms: Decimal | None = None) -> None:
        if failure_category not in FAILURE_CATEGORIES:
            failure_category = "NETWORK"
        self.failure_category = failure_category
        self.attempt_count = attempt_count
        self.latency_ms = latency_ms
        super().__init__(failure_category)


class _Transient(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _Response(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> object: ...


class _Client(Protocol):
    def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object],
             timeout: float) -> _Response: ...

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> _Response: ...


@dataclass(frozen=True)
class JevHttpConfig:
    timeout_seconds: float = 5.0
    max_retries: int = 2
    initial_backoff_seconds: float = 0.25
    max_total_seconds: float = 12.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_total_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")


def _retryable(status: int) -> bool:
    return status in (408, 429) or 500 <= status <= 599


def _category(status: int) -> str:
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


def _retry_after(response: _Response | None) -> float | None:
    if response is None:
        return None
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
        return any(_contains_secret(k, secret) or _contains_secret(v, secret) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret(v, secret) for v in value)
    return False


def _safe_request_id(response: _Response) -> str | None:
    headers = getattr(response, "headers", {}) or {}
    for name in _REQUEST_ID_HEADERS:
        value = headers.get(name)
        if isinstance(value, str) and _REQUEST_ID_RE.fullmatch(value):
            return value
    return None


class TypeSafeJevTransport:
    """Explicit-key transport. The key lives in memory only and is never serialized."""

    def __init__(self, api_key: str, *, client: _Client | None = None,
                 config: JevHttpConfig = JevHttpConfig(),
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key.strip()
        self._client = client
        self._config = config
        self._sleep = sleep
        self._clock = clock

    def __repr__(self) -> str:
        return "TypeSafeJevTransport(api_key=<redacted>)"

    __str__ = __repr__

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _call(self, method: str, url: str, body: Mapping[str, object] | None) -> _Response:
        timeout = self._config.timeout_seconds
        try:
            if self._client is not None:
                if method == "POST":
                    return self._client.post(url, headers=self._headers(), json=body or {}, timeout=timeout)
                return self._client.get(url, headers=self._headers(), timeout=timeout)
            if method == "POST":
                return httpx.post(url, headers=self._headers(), json=body, timeout=timeout)
            return httpx.get(url, headers=self._headers(), timeout=timeout)
        except httpx.TimeoutException:
            raise _Transient("TIMEOUT") from None
        except Exception:
            raise _Transient("NETWORK") from None

    def _failure(self, category: str, started: float, attempts: int) -> JevTransportError:
        elapsed = Decimal(str(max(0.0, (self._clock() - started) * 1000))).quantize(Decimal("0.001"))
        return JevTransportError(category, attempt_count=attempts, latency_ms=elapsed)

    def _request(self, method: str, url: str, body: Mapping[str, object] | None) -> dict:
        started = self._clock()
        max_attempts = self._config.max_retries + 1
        last = "NETWORK"
        for index in range(max_attempts):
            attempts = index + 1
            response = None
            try:
                response = self._call(method, url, body)
                status = response.status_code
                if status == 200:
                    try:
                        raw = response.json()
                    except Exception:
                        raise self._failure("INVALID_RESPONSE", started, attempts) from None
                    if not isinstance(raw, Mapping) or _contains_secret(raw, self._api_key):
                        raise self._failure("INVALID_RESPONSE", started, attempts)
                    payload = dict(raw)
                    latency = Decimal(str((self._clock() - started) * 1000)).quantize(Decimal("0.001"))
                    payload["_transport_meta"] = {
                        "latency_ms": str(latency),
                        "attempt_count": attempts,
                        "provider_request_id": _safe_request_id(response),
                    }
                    return payload
                last = _category(status)
                if not _retryable(status):
                    raise self._failure(last, started, attempts)
            except _Transient as exc:
                last = exc.category
            if index >= self._config.max_retries:
                raise self._failure(last, started, attempts) from None
            delay = max(self._config.initial_backoff_seconds * (2 ** index), _retry_after(response) or 0.0)
            if (self._clock() - started) + delay > self._config.max_total_seconds:
                raise self._failure("RETRY_BUDGET_EXHAUSTED", started, attempts) from None
            if delay:
                self._sleep(delay)
        raise self._failure("RETRY_BUDGET_EXHAUSTED", started, max_attempts)

    def evaluate(self, request: Mapping[str, object]) -> Mapping[str, object]:
        if not isinstance(request, Mapping):
            raise TypeError("request must be a mapping")
        return self._request("POST", TYPESAFE_SYSTEMONE_URL, request)

    def list_models(self) -> Mapping[str, object]:
        """Diagnostics / configuration validation only; never on the request path."""
        return self._request("GET", TYPESAFE_MODELS_URL, None)
