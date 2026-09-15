"""LI.FI exact-input execution quote adapter for FINCO Radar R0."""
from __future__ import annotations

from datetime import datetime, timezone
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
                f"malformed quote response: {type(exc).__name__}",
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
        estimate = payload["estimate"]
        raw_in = int(estimate["fromAmount"])
        raw_out = int(estimate["toAmount"])
        response_input = payload["action"]["fromToken"]
        response_output = payload["action"]["toToken"]
        input_decimals = int(response_input["decimals"])
        output_decimals = int(response_output["decimals"])

        if response_input["address"].lower() != input_asset.contract_address:
            raise ValueError("provider input asset does not match requested address")
        if response_output["address"].lower() != output_asset.contract_address:
            raise ValueError("provider output asset does not match requested address")
        if input_asset.decimals != input_decimals or output_asset.decimals != output_decimals:
            raise ValueError("provider decimals do not match canonical request metadata")

        route = tuple(_extract_route(payload))
        transaction = payload.get("transactionRequest") or {}
        fee_cost_usd = _sum_usd_costs(estimate.get("feeCosts") or [])
        gas_cost_usd = _sum_usd_costs(estimate.get("gasCosts") or [])
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


def _extract_route(payload: Mapping[str, Any]) -> list[RouteLeg]:
    steps = payload.get("includedSteps") or []
    route: list[RouteLeg] = []
    for step in steps:
        action = step.get("action") or {}
        estimate = step.get("estimate") or {}
        from_token = action.get("fromToken") or {}
        to_token = action.get("toToken") or {}
        route.append(
            RouteLeg(
                tool=str(step.get("tool") or payload.get("tool") or "UNKNOWN"),
                from_asset=str(from_token.get("address") or ""),
                to_asset=str(to_token.get("address") or ""),
                from_amount_raw=(str(estimate["fromAmount"]) if estimate.get("fromAmount") is not None else None),
                to_amount_raw=(str(estimate["toAmount"]) if estimate.get("toAmount") is not None else None),
            )
        )
    if not route:
        action = payload.get("action") or {}
        estimate = payload.get("estimate") or {}
        route.append(
            RouteLeg(
                tool=str(payload.get("tool") or "UNKNOWN"),
                from_asset=str((action.get("fromToken") or {}).get("address") or ""),
                to_asset=str((action.get("toToken") or {}).get("address") or ""),
                from_amount_raw=(str(estimate["fromAmount"]) if estimate.get("fromAmount") is not None else None),
                to_amount_raw=(str(estimate["toAmount"]) if estimate.get("toAmount") is not None else None),
            )
        )
    return route


def _sum_usd_costs(costs: list[Mapping[str, Any]]) -> Decimal | None:
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
