"""Typed execution-provider clients. Provider JSON is infrastructure, never FINCO authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Any

import httpx

from .identity import canonical_address


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str = "Execution provider is temporarily unavailable.",
    ):
        super().__init__(message)
        self.code = code
        self.public_message = message


class ProviderValidationError(ProviderError):
    def __init__(self, message: str):
        super().__init__("PROVIDER_RESPONSE_REJECTED", message)


@dataclass(frozen=True)
class ProviderTransaction:
    to: str
    data: str
    value: int
    gas: int | None = None


@dataclass(frozen=True)
class NormalizedProviderQuote:
    provider: str
    chain_id: int
    input_token: str
    output_token: str
    input_amount: int
    expected_output: int | None
    receiver: str
    approval_target: str | None
    transaction: ProviderTransaction
    created_at: datetime
    expires_at: datetime
    provider_quote_id: str | None = None
    fee_summary: tuple[str, ...] = ()


def _int(value: Any, field: str) -> int:
    try:
        result = (
            int(value, 16)
            if isinstance(value, str) and value.startswith("0x")
            else int(value)
        )
    except (ValueError, TypeError) as exc:
        raise ProviderValidationError(f"invalid provider {field}") from exc
    if result < 0:
        raise ProviderValidationError(f"invalid provider {field}")
    return result


def _allowed(name: str) -> frozenset[str]:
    out = set()
    for value in os.getenv(name, "").split(","):
        value = value.strip()
        if value:
            out.add(canonical_address(value))
    return frozenset(out)


def _require_allowed(
    address: str,
    allowed: frozenset[str],
    label: str,
) -> str:
    normalized = canonical_address(address)
    if not allowed or normalized not in allowed:
        raise ProviderValidationError(f"unexpected {label}")
    return normalized


def _provider_http_error(status_code: int | None) -> ProviderError:
    if status_code == 401:
        return ProviderError("PROVIDER_AUTHENTICATION_FAILED")
    if status_code == 403:
        return ProviderError("PROVIDER_FORBIDDEN")
    if status_code == 429:
        return ProviderError("PROVIDER_RATE_LIMITED")
    if status_code is not None and status_code >= 500:
        return ProviderError("PROVIDER_UPSTREAM_UNAVAILABLE")
    return ProviderError("PROVIDER_HTTP_ERROR")


def _request_json(client: Any, url: str, **kwargs: Any) -> dict:
    """Make one provider request and expose only typed, sanitized failures."""
    try:
        response = client.get(url, **kwargs)
    except httpx.TimeoutException:
        raise ProviderError("PROVIDER_TIMEOUT") from None
    except httpx.RequestError:
        raise ProviderError("PROVIDER_NETWORK_ERROR") from None
    except Exception:
        # Custom/test transports and future clients must not leak exception text.
        raise ProviderError("PROVIDER_NETWORK_ERROR") from None

    try:
        response.raise_for_status()
    except Exception:
        raise _provider_http_error(getattr(response, "status_code", None)) from None

    try:
        payload = response.json()
    except Exception:
        raise ProviderError("PROVIDER_MALFORMED_JSON") from None

    if not isinstance(payload, dict):
        raise ProviderError("PROVIDER_MALFORMED_JSON")
    return payload


class ZeroXClient:
    base_url = "https://api.0x.org"

    def __init__(self, api_key=None, client=None, quote_ttl_seconds: int = 30):
        self.api_key = api_key or os.getenv("ZERO_X_API_KEY")
        self.client = client or httpx.Client(timeout=10)
        self.quote_ttl_seconds = quote_ttl_seconds

    @property
    def configured(self):
        return bool(self.api_key)

    def quote(
        self,
        *,
        chain_id: int,
        sell_token: str,
        buy_token: str,
        sell_amount: int,
        taker: str,
    ) -> NormalizedProviderQuote:
        if not self.api_key:
            raise ProviderError("NOT_CONFIGURED", "0x API is not configured.")
        sell_token = canonical_address(sell_token)
        buy_token = canonical_address(buy_token)
        taker = canonical_address(taker)
        payload = _request_json(
            self.client,
            f"{self.base_url}/swap/allowance-holder/quote",
            params={
                "chainId": chain_id,
                "sellToken": sell_token,
                "buyToken": buy_token,
                "sellAmount": str(sell_amount),
                "taker": taker,
            },
            headers={"0x-api-key": self.api_key, "0x-version": "v2"},
        )
        return self.normalize(
            payload,
            chain_id=chain_id,
            sell_token=sell_token,
            buy_token=buy_token,
            sell_amount=sell_amount,
            taker=taker,
        )

    def normalize(
        self,
        payload: dict,
        *,
        chain_id: int,
        sell_token: str,
        buy_token: str,
        sell_amount: int,
        taker: str,
    ) -> NormalizedProviderQuote:
        if not isinstance(payload, dict) or not isinstance(
            payload.get("transaction"), dict
        ):
            raise ProviderValidationError("malformed 0x response")
        tx = payload["transaction"]
        tx_to = _require_allowed(
            tx.get("to", ""),
            _allowed(f"FINCO_YIELD_0X_TRANSACTION_TARGETS_{chain_id}"),
            "0x transaction target",
        )
        data = tx.get("data")
        if not isinstance(data, str) or not data.startswith("0x"):
            raise ProviderValidationError("invalid 0x calldata")

        approval = None
        issues = payload.get("issues") or {}
        allowance = issues.get("allowance") if isinstance(issues, dict) else None
        if isinstance(allowance, dict) and allowance.get("spender"):
            approval = _require_allowed(
                allowance["spender"],
                _allowed(f"FINCO_YIELD_0X_APPROVAL_TARGETS_{chain_id}"),
                "0x approval target",
            )

        if (
            payload.get("sellAmount") is not None
            and _int(payload["sellAmount"], "sellAmount") != sell_amount
        ):
            raise ProviderValidationError("0x sell amount mismatch")

        now = datetime.now(timezone.utc)
        return NormalizedProviderQuote(
            "0X_V2",
            chain_id,
            canonical_address(sell_token),
            canonical_address(buy_token),
            sell_amount,
            _int(payload["buyAmount"], "buyAmount")
            if payload.get("buyAmount") is not None
            else None,
            canonical_address(taker),
            approval,
            ProviderTransaction(
                tx_to,
                data,
                _int(tx.get("value", 0), "value"),
                _int(tx["gas"], "gas") if tx.get("gas") is not None else None,
            ),
            now,
            now + timedelta(seconds=self.quote_ttl_seconds),
            str(payload.get("zid")) if payload.get("zid") else None,
            ("provider fees disclosed",) if payload.get("fees") else (),
        )


class EnsoClient:
    base_url = "https://api.enso.build/api/v1"

    def __init__(self, api_key=None, client=None, quote_ttl_seconds: int = 30):
        self.api_key = api_key or os.getenv("ENSO_API_KEY")
        self.client = client or httpx.Client(timeout=10)
        self.quote_ttl_seconds = quote_ttl_seconds

    @property
    def configured(self):
        return bool(self.api_key)

    def route(
        self,
        *,
        chain_id: int,
        input_token: str,
        output_token: str,
        amount: int,
        sender: str,
        receiver: str,
    ) -> NormalizedProviderQuote:
        if not self.api_key:
            raise ProviderError("NOT_CONFIGURED", "Enso API is not configured.")
        sender = canonical_address(sender)
        receiver = canonical_address(receiver)
        if sender != receiver:
            raise ProviderValidationError(
                "Enso final receiver must equal connected wallet"
            )
        payload = _request_json(
            self.client,
            f"{self.base_url}/shortcuts/route",
            params={
                "chainId": chain_id,
                "fromAddress": sender,
                "receiver": receiver,
                "tokenIn": canonical_address(input_token),
                "tokenOut": canonical_address(output_token),
                "amountIn": str(amount),
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self.normalize(
            payload,
            chain_id=chain_id,
            input_token=input_token,
            output_token=output_token,
            amount=amount,
            receiver=receiver,
        )

    def normalize(
        self,
        payload: dict,
        *,
        chain_id: int,
        input_token: str,
        output_token: str,
        amount: int,
        receiver: str,
    ) -> NormalizedProviderQuote:
        if not isinstance(payload, dict):
            raise ProviderValidationError("malformed Enso response")
        tx = payload.get("tx") or payload.get("transaction") or payload
        if not isinstance(tx, dict):
            raise ProviderValidationError("Enso transaction unavailable")
        tx_to = _require_allowed(
            tx.get("to", ""),
            _allowed(f"FINCO_YIELD_ENSO_TRANSACTION_TARGETS_{chain_id}"),
            "Enso transaction target",
        )
        data = tx.get("data")
        if not isinstance(data, str) or not data.startswith("0x"):
            raise ProviderValidationError("invalid Enso calldata")
        expected = payload.get("amountOut") or payload.get("amountOutMin")
        now = datetime.now(timezone.utc)
        return NormalizedProviderQuote(
            "ENSO",
            chain_id,
            canonical_address(input_token),
            canonical_address(output_token),
            amount,
            _int(expected, "amountOut") if expected is not None else None,
            canonical_address(receiver),
            None,
            ProviderTransaction(
                tx_to,
                data,
                _int(tx.get("value", 0), "value"),
                _int(tx["gas"], "gas") if tx.get("gas") is not None else None,
            ),
            now,
            now + timedelta(seconds=self.quote_ttl_seconds),
            str(payload.get("routeId")) if payload.get("routeId") else None,
        )
