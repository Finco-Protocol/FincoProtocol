"""LI.FI exact-input execution quote adapter for FINCO Radar R0."""
from __future__ import annotations

from datetime import datetime, timezone
import decimal
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import httpx

from ..contracts import (
    AssetRef,
    ExecutionQuote,
    QuoteEvidence,
    QuoteRequest,
    QuoteSide,
    QuoteStatus,
    RouteLeg,
)
from ..normalization import from_raw_amount, to_raw_amount


class LifiExecutionQuoteAdapter:
    source_name = "LIFI_V1_QUOTE"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://li.quest/v1",
        timeout_seconds: float = 20.0,
        api_key: str | None = None,
    ) -> None:
        self._owns_client = client is None
        headers = {"accept": "application/json"}
        if api_key:
            headers["x-lifi-api-key"] = api_key
        self.client = client or httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "LifiExecutionQuoteAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def quote(self, request: QuoteRequest) -> ExecutionQuote:
        quoted_at = datetime.now(timezone.utc)
        if not request.settlement.usable:
            return self._failure(
                request,
                QuoteStatus.SETTLEMENT_REFERENCE_UNAVAILABLE,
                "settlement asset does not have a usable explicit USD reference",
                quoted_at,
            )
        if request.token.decimals is None or request.settlement.asset.decimals is None:
            return self._failure(
                request,
                QuoteStatus.UNSUPPORTED_ASSET,
                "token and settlement decimals are required before quote normalization",
                quoted_at,
            )

        input_asset, output_asset, raw_amount = self._route_inputs(request)
        params = {
            "fromChain": str(request.token.chain_id),
            "toChain": str(request.token.chain_id),
            "fromToken": input_asset.contract_address,
            "toToken": output_asset.contract_address,
            "fromAmount": str(raw_amount),
            "fromAddress": request.taker_address,
            "toAddress": request.taker_address,
        }
        try:
            response = self.client.get("/quote", params=params)
        except httpx.HTTPError as exc:
            return self._failure(
                request,
                QuoteStatus.QUOTE_SOURCE_ERROR,
                f"quote transport error: {type(exc).__name__}",
                quoted_at,
                input_asset=input_asset,
                output_asset=output_asset,
                request_params=params,
            )

        if response.status_code >= 400:
            status, reason = _map_error(response)
            return self._failure(
                request,
                status,
                reason,
                quoted_at,
                input_asset=input_asset,
                output_asset=output_asset,
                request_params=params,
                response_fields=_safe_json(response),
            )

        try:
            payload = response.json()
            quote = self._parse_success(
                request=request,
                quoted_at=quoted_at,
                params=params,
                payload=payload,
                input_asset=input_asset,
                output_asset=output_asset,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._failure(
                request,
                QuoteStatus.QUOTE_SOURCE_ERROR,
                f"exact-input binding mismatch: {exc}",
                quoted_at,
                input_asset=input_asset,
                output_asset=output_asset,
                request_params=params,
                response_fields=_safe_json(response),
            )
        return quote

    def _route_inputs(self, request: QuoteRequest) -> tuple[AssetRef, AssetRef, int]:
        if request.side is QuoteSide.BUY:
            settlement_amount = request.requested_notional_usd / request.settlement.usd_per_asset  # type: ignore[operator]
            return (
                request.settlement.asset,
                request.token,
                to_raw_amount(settlement_amount, request.settlement.asset.decimals or 0),
            )

        token_amount = request.requested_notional_usd / request.token_sizing_reference_usd  # type: ignore[operator]
        return (
            request.token,
            request.settlement.asset,
            to_raw_amount(token_amount, request.token.decimals or 0),
        )

    def _parse_success(
        self,
        *,
        request: QuoteRequest,
        quoted_at: datetime,
        params: Mapping[str, str],
        payload: Mapping[str, Any],
        input_asset: AssetRef,
        output_asset: AssetRef,
    ) -> ExecutionQuote:
        # -- C2: root shape validation before any .get() access
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"provider response root must be a JSON object, "
                f"got {type(payload).__name__}")

        # -- structural validation: every provider-controlled container must
        # be a Mapping before any .get() call (B4).
        estimate = _require_mapping(payload.get("estimate"), "estimate")
        action = _require_mapping(payload.get("action"), "action")
        response_input = _require_mapping(action.get("fromToken"), "action.fromToken")
        response_output = _require_mapping(action.get("toToken"), "action.toToken")

        # -- C3: token addresses must be strings before .lower()
        for label, token_obj in (("fromToken", response_input), ("toToken", response_output)):
            addr = token_obj.get("address")
            if not isinstance(addr, str) or not addr.strip():
                raise ValueError(
                    f"provider response {label}.address must be a non-empty "
                    f"string, got {addr!r}")

        raw_in = _strict_int(estimate.get("fromAmount"), "estimate.fromAmount")
        raw_out = _strict_int(estimate.get("toAmount"), "estimate.toAmount")
        input_decimals = _strict_int(response_input.get("decimals"), "fromToken.decimals")
        output_decimals = _strict_int(response_output.get("decimals"), "toToken.decimals")

        # -- C4/A2/A3: strict chain binding — integer-only, no bool, no
        # float, no string, no None.  Exact equality with requested chain.
        expected_chain = request.token.chain_id
        for field_label, container, key in (
            ("action.fromChainId", action, "fromChainId"),
            ("fromToken.chainId", response_input, "chainId"),
            ("action.toChainId", action, "toChainId"),
            ("toToken.chainId", response_output, "chainId"),
        ):
            _require_exact_chain_int(container.get(key), field_label, expected_chain)

        # -- B2/A1: strict exact-input amount binding
        requested_raw = params.get("fromAmount") or ""
        _require_exact_raw_amount(
            estimate.get("fromAmount"), requested_raw,
            "estimate.fromAmount")

        if response_input["address"].lower() != input_asset.contract_address:
            raise ValueError("provider input asset does not match requested address")
        if response_output["address"].lower() != output_asset.contract_address:
            raise ValueError("provider output asset does not match requested address")
        if input_asset.decimals != input_decimals or output_asset.decimals != output_decimals:
            raise ValueError("provider decimals do not match canonical request metadata")

        route = tuple(_extract_route(payload))
        transaction = _require_mapping(
            payload.get("transactionRequest") or {}, "transactionRequest")
        fee_cost_usd = _sum_usd_costs(_require_sequence(estimate.get("feeCosts"), "feeCosts") if estimate.get("feeCosts") is not None else [])
        gas_cost_usd = _sum_usd_costs(_require_sequence(estimate.get("gasCosts"), "gasCosts") if estimate.get("gasCosts") is not None else [])
        evidence = QuoteEvidence(
            request_params=dict(params),
            response_fields={
                "id": payload.get("id"),
                "type": payload.get("type"),
                "tool": payload.get("tool"),
                "fromAmount": str(estimate.get("fromAmount")),
                "toAmount": str(estimate.get("toAmount")),
                "toAmountMin": str(estimate.get("toAmountMin")),
                "executionDuration": estimate.get("executionDuration"),
                "feeCosts": estimate.get("feeCosts") or [],
                "gasCosts": estimate.get("gasCosts") or [],
            },
            route=route,
            transaction_to=transaction.get("to"),
            transaction_data=transaction.get("data"),
            source_request_id=payload.get("id"),
        )
        return ExecutionQuote(
            chain_id=request.token.chain_id,
            token_address=request.token.contract_address,
            side=request.side,
            input_asset=input_asset,
            output_asset=output_asset,
            requested_notional_usd=request.requested_notional_usd,
            raw_amount_in=raw_in,
            raw_amount_out=raw_out,
            normalized_amount_in=from_raw_amount(raw_in, input_decimals),
            normalized_amount_out=from_raw_amount(raw_out, output_decimals),
            input_decimals=input_decimals,
            output_decimals=output_decimals,
            source=self.source_name,
            quoted_at=quoted_at,
            settlement_reference=request.settlement,
            status=QuoteStatus.QUOTE_OK,
            fee_cost_usd=fee_cost_usd,
            gas_cost_usd=gas_cost_usd,
            evidence=evidence,
        )

    def _failure(
        self,
        request: QuoteRequest,
        status: QuoteStatus,
        reason: str,
        quoted_at: datetime,
        *,
        input_asset: AssetRef | None = None,
        output_asset: AssetRef | None = None,
        request_params: Mapping[str, Any] | None = None,
        response_fields: Mapping[str, Any] | None = None,
    ) -> ExecutionQuote:
        if input_asset is None or output_asset is None:
            if request.side is QuoteSide.BUY:
                input_asset, output_asset = request.settlement.asset, request.token
            else:
                input_asset, output_asset = request.token, request.settlement.asset
        evidence = None
        if request_params is not None or response_fields is not None:
            evidence = QuoteEvidence(
                request_params=request_params or {},
                response_fields=response_fields or {},
            )
        return ExecutionQuote(
            chain_id=request.token.chain_id,
            token_address=request.token.contract_address,
            side=request.side,
            input_asset=input_asset,
            output_asset=output_asset,
            requested_notional_usd=request.requested_notional_usd,
            raw_amount_in=None,
            raw_amount_out=None,
            normalized_amount_in=None,
            normalized_amount_out=None,
            input_decimals=input_asset.decimals,
            output_decimals=output_asset.decimals,
            source=self.source_name,
            quoted_at=quoted_at,
            settlement_reference=request.settlement,
            status=status,
            unavailable_reason=reason,
            evidence=evidence,
        )


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    """B4: required Mapping — absent/null/wrong-type are typed errors."""
    if not isinstance(value, Mapping):
        raise ValueError(
            f"provider response field {name} must be a mapping, "
            f"got {type(value).__name__}")
    return value


def _require_sequence(value: Any, name: str) -> list:
    """B4: required list — absent/null/wrong-type are typed errors."""
    if not isinstance(value, list):
        raise ValueError(
            f"provider response field {name} must be a list, "
            f"got {type(value).__name__}")
    return value


def _strict_int(value: Any, name: str) -> int:
    """B2: strict integer — no bool, no float, no None, no string coercion.
    Only exact Python int (or string of decimal digits per LI.FI contract)."""
    if isinstance(value, bool):
        raise ValueError(f"provider response field {name} must not be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(
        f"provider response field {name}={value!r} is not a valid integer "
        "in the LI.FI provider contract")


def _require_exact_chain_int(value: Any, name: str, expected: int) -> None:
    """C4: chain IDs must be exact Python int (excluding bool).  No string,
    float, bool, or None accepted.  Exact equality with requested chain."""
    if isinstance(value, bool):
        raise ValueError(
            f"provider response field {name} must not be a boolean")
    if not isinstance(value, int):
        raise ValueError(
            f"provider response field {name} must be an integer per the "
            f"LI.FI contract, got {type(value).__name__} ({value!r})")
    if value != expected:
        raise ValueError(
            f"provider response field {name}={value} does not match "
            f"requested chain {expected}")


def _require_exact_chain(value: Any, name: str, expected: int) -> None:
    """C4 (superseded by _require_exact_chain_int): kept for backwards compat."""
    _require_exact_chain_int(value, name, expected)


def _require_exact_raw_amount(
    value: Any, requested_raw: str, name: str,
) -> None:
    """B2: strict exact-input amount binding.  The provider must return a
    string of decimal digits exactly equal to the submitted raw amount.
    Rejects numeric JSON integers, floats, booleans, None, whitespace,
    signed values, fractional values, and off-by-one."""
    if value is None:
        raise ValueError(
            f"provider response field {name} is missing; "
            "input amount binding is required for exact-input authority")
    if not isinstance(value, str):
        raise ValueError(
            f"provider response field {name} must be a string per the "
            f"LI.FI contract, got {type(value).__name__} ({value!r})")
    if value != value.strip():
        raise ValueError(
            f"provider response field {name} has whitespace padding: "
            f"{value!r}")
    if not value.isdigit():
        raise ValueError(
            f"provider response field {name}={value!r} is not a valid "
            "unsigned decimal-digit string")
    if value != requested_raw:
        raise ValueError(
            f"provider input amount {value} does not equal the exact "
            f"amount submitted {requested_raw}; this response evidences "
            "a different trade")


def _validate_raw_amount(value: Any, name: str) -> str:
    """D2: nested raw amounts must be valid per the LI.FI contract.
    Rejects missing/null, bool, float, list, dict, malformed strings,
    signed/fractional strings; accepts exact int or decimal-digit string."""
    if value is None:
        raise ValueError(f"provider response field {name} must be present "
                         "per the LI.FI provider contract")
    if isinstance(value, bool):
        raise ValueError(f"{name} must not be a boolean")
    if isinstance(value, float):
        raise ValueError(f"{name} must not be a float")
    if isinstance(value, (list, dict)):
        raise ValueError(f"{name} must not be {type(value).__name__}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped != value:
            raise ValueError(f"{name} has whitespace padding: {value!r}")
        if not stripped.isdigit():
            raise ValueError(
                f"{name}={value!r} is not a valid unsigned decimal-digit string")
        return stripped
    raise ValueError(f"{name} has unsupported type {type(value).__name__}")


def _extract_route(payload: Mapping[str, Any]) -> list[RouteLeg]:
    """C1: malformed route steps/entries produce typed errors, never skipped."""
    steps = payload.get("includedSteps")
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        raise ValueError(
            f"provider response includedSteps must be a list, got {type(steps).__name__}")
    route: list[RouteLeg] = []
    for step in steps:
        if not isinstance(step, Mapping):
            raise ValueError(
                f"provider response includedSteps member must be a mapping, "
                f"got {type(step).__name__}")
        action = step.get("action")
        if not isinstance(action, Mapping):
            raise ValueError("includedSteps member has non-mapping action")
        estimate = step.get("estimate")
        if not isinstance(estimate, Mapping):
            raise ValueError("includedSteps member has non-mapping estimate")
        from_token = action.get("fromToken")
        to_token = action.get("toToken")
        if not isinstance(from_token, Mapping):
            raise ValueError("includedSteps member has non-mapping fromToken")
        if not isinstance(to_token, Mapping):
            raise ValueError("includedSteps member has non-mapping toToken")
        # D1: nested token addresses must be non-empty strings
        for tok_label, tok_obj in (("fromToken", from_token), ("toToken", to_token)):
            addr = tok_obj.get("address")
            if not isinstance(addr, str) or not addr.strip():
                raise ValueError(
                    f"includedSteps member {tok_label}.address must be a "
                    f"non-empty string, got {addr!r}")
        # D2: nested raw amounts must be valid
        from_amt_raw = estimate.get("fromAmount")
        to_amt_raw = estimate.get("toAmount")
        from_amt = _validate_raw_amount(from_amt_raw, "includedSteps estimate.fromAmount")
        to_amt = _validate_raw_amount(to_amt_raw, "includedSteps estimate.toAmount")
        route.append(
            RouteLeg(
                tool=str(step.get("tool") or payload.get("tool") or "UNKNOWN"),
                from_asset=from_token["address"],
                to_asset=to_token["address"],
                from_amount_raw=from_amt,
                to_amount_raw=to_amt,
            )
        )
    if not route:
        action = payload.get("action")
        if not isinstance(action, Mapping):
            action = {}
        estimate = payload.get("estimate")
        if not isinstance(estimate, Mapping):
            estimate = {}
        from_token = action.get("fromToken")
        to_token = action.get("toToken")
        from_addr = str(from_token.get("address") or "") if isinstance(from_token, Mapping) else ""
        to_addr = str(to_token.get("address") or "") if isinstance(to_token, Mapping) else ""
        from_amt = str(estimate["fromAmount"]) if isinstance(estimate.get("fromAmount"), (str, int)) else None
        to_amt = str(estimate["toAmount"]) if isinstance(estimate.get("toAmount"), (str, int)) else None
        route.append(
            RouteLeg(
                tool=str(payload.get("tool") or "UNKNOWN"),
                from_asset=from_addr,
                to_asset=to_addr,
                from_amount_raw=from_amt,
                to_amount_raw=to_amt,
            )
        )
    return route


def _sum_usd_costs(costs: list) -> Decimal | None:
    """C1: malformed cost members produce typed errors, never silently skipped."""
    for cost in costs:
        if not isinstance(cost, Mapping):
            raise ValueError(
                f"provider response cost entry must be a mapping, "
                f"got {type(cost).__name__}")
    total = Decimal("0")
    seen = False
    for cost in costs:
        amount = cost.get("amountUSD")
        if amount is None:
            continue
        total += Decimal(str(amount))
        seen = True
    return total if seen else None


def _safe_json(response: httpx.Response) -> Mapping[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, Mapping) else {"body": data}
    except ValueError:
        return {"body": response.text[:1000]}


def _map_error(response: httpx.Response) -> tuple[QuoteStatus, str]:
    payload = _safe_json(response)
    message = str(payload.get("message") or payload.get("error") or payload).lower()
    if response.status_code in {401, 403}:
        return QuoteStatus.AUTH_REQUIRED, "quote authority rejected authentication"
    if response.status_code == 429:
        return QuoteStatus.RATE_LIMITED, "quote authority rate limit exceeded"
    if response.status_code == 404 or "no route" in message or "no available" in message:
        return QuoteStatus.ROUTE_UNAVAILABLE, "no executable route returned by quote authority"
    if "liquidity" in message or "insufficient" in message:
        return QuoteStatus.INSUFFICIENT_LIQUIDITY, "quote authority reports insufficient liquidity"
    if "token" in message and ("unsupported" in message or "not found" in message):
        return QuoteStatus.UNSUPPORTED_ASSET, "quote authority does not support requested asset"
    return QuoteStatus.QUOTE_SOURCE_ERROR, f"quote authority HTTP {response.status_code}"
