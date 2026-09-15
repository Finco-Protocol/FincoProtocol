from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import (
    AssetRef,
    ExecutionQuote,
    QuoteRequest,
    QuoteSide,
    QuoteStatus,
    SettlementReference,
    SettlementReferenceState,
)
from finco_radar.quotes.normalization import (
    enforce_freshness,
    from_raw_amount,
    quote_size_impact_bps,
    to_raw_amount,
)

TOKEN = AssetRef(4663, "0x1111111111111111111111111111111111111111", symbol="STK", decimals=18)
USDG = AssetRef(4663, "0x2222222222222222222222222222222222222222", symbol="USDG", decimals=6)
TAKER = "0x3333333333333333333333333333333333333333"
SETTLEMENT = SettlementReference(
    asset=USDG,
    state=SettlementReferenceState.REFERENCE_CURRENT,
    usd_per_asset=Decimal("0.9998"),
    source="TEST_EXPLICIT_REFERENCE",
)


def request(side: QuoteSide, notional: str = "100") -> QuoteRequest:
    return QuoteRequest(
        token=TOKEN,
        settlement=SETTLEMENT,
        side=side,
        requested_notional_usd=Decimal(notional),
        taker_address=TAKER,
        token_sizing_reference_usd=Decimal("200") if side is QuoteSide.SELL else None,
        token_sizing_reference_source="TEST_SIZING_REFERENCE" if side is QuoteSide.SELL else None,
    )


def payload(from_address: str, to_address: str, from_amount: int, to_amount: int) -> dict:
    from_decimals = USDG.decimals if from_address.lower() == USDG.contract_address else TOKEN.decimals
    to_decimals = TOKEN.decimals if to_address.lower() == TOKEN.contract_address else USDG.decimals
    return {
        "id": "quote-1",
        "type": "lifi",
        "tool": "mock-dex",
        "action": {
            "fromToken": {"address": from_address, "decimals": from_decimals},
            "toToken": {"address": to_address, "decimals": to_decimals},
        },
        "estimate": {
            "fromAmount": str(from_amount),
            "toAmount": str(to_amount),
            "toAmountMin": str(int(to_amount * 0.995)),
            "feeCosts": [{"amountUSD": "0.10"}],
            "gasCosts": [{"amountUSD": "0.02"}],
            "executionDuration": 1.2,
        },
        "includedSteps": [
            {
                "tool": "mock-dex",
                "action": {
                    "fromToken": {"address": from_address},
                    "toToken": {"address": to_address},
                },
                "estimate": {"fromAmount": str(from_amount), "toAmount": str(to_amount)},
            }
        ],
        "transactionRequest": {"to": "0x4444444444444444444444444444444444444444", "data": "0x1234"},
    }


def adapter_for(handler):
    return LifiExecutionQuoteAdapter(client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.invalid"))


def test_decimal_normalization_is_exact_and_rounds_down() -> None:
    assert to_raw_amount(Decimal("1.23456789"), 6) == 1_234_567
    assert from_raw_amount(1_234_567, 6) == Decimal("1.234567")


def test_asset_ref_rejects_non_hex_address() -> None:
    with pytest.raises(ValueError, match="20-byte EVM hex address"):
        AssetRef(4663, "0x11111111111111111111111111111111111111zz", decimals=18)


def test_quote_request_rejects_non_hex_taker_address() -> None:
    with pytest.raises(ValueError, match="20-byte EVM hex address"):
        QuoteRequest(
            token=TOKEN,
            settlement=SETTLEMENT,
            side=QuoteSide.BUY,
            requested_notional_usd=Decimal("100"),
            taker_address="0x33333333333333333333333333333333333333zz",
        )


def test_buy_direction_uses_settlement_as_input_and_explicit_settlement_reference() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        params = dict(req.url.params)
        assert params["fromToken"] == USDG.contract_address
        assert params["toToken"] == TOKEN.contract_address
        expected_in = to_raw_amount(Decimal("100") / Decimal("0.9998"), 6)
        assert int(params["fromAmount"]) == expected_in
        return httpx.Response(200, json=payload(USDG.contract_address, TOKEN.contract_address, expected_in, 500000000000000000))

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.BUY))
    assert quote.status is QuoteStatus.QUOTE_OK
    assert quote.input_asset == USDG
    assert quote.output_asset == TOKEN
    assert quote.evidence and quote.evidence.transaction_data == "0x1234"


def test_sell_direction_uses_token_as_input_and_sizing_reference_only_for_amount() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        params = dict(req.url.params)
        assert params["fromToken"] == TOKEN.contract_address
        assert params["toToken"] == USDG.contract_address
        assert int(params["fromAmount"]) == 500000000000000000
        return httpx.Response(200, json=payload(TOKEN.contract_address, USDG.contract_address, 500000000000000000, 49_900_000))

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.SELL))
    assert quote.status is QuoteStatus.QUOTE_OK
    assert quote.input_asset == TOKEN
    assert quote.output_asset == USDG


def _quote(side: QuoteSide, notional: str, amount_in: str, amount_out: str) -> ExecutionQuote:
    input_asset, output_asset = (USDG, TOKEN) if side is QuoteSide.BUY else (TOKEN, USDG)
    return ExecutionQuote(
        chain_id=4663,
        token_address=TOKEN.contract_address,
        side=side,
        input_asset=input_asset,
        output_asset=output_asset,
        requested_notional_usd=Decimal(notional),
        raw_amount_in=1,
        raw_amount_out=1,
        normalized_amount_in=Decimal(amount_in),
        normalized_amount_out=Decimal(amount_out),
        input_decimals=input_asset.decimals,
        output_decimals=output_asset.decimals,
        source="TEST",
        quoted_at=datetime.now(timezone.utc),
        settlement_reference=SETTLEMENT,
        status=QuoteStatus.QUOTE_OK,
    )


def test_size_awareness_reports_quote_deterioration_not_slippage() -> None:
    small = _quote(QuoteSide.BUY, "100", "100", "0.50")
    large = _quote(QuoteSide.BUY, "1000", "1000", "4.90")
    assert quote_size_impact_bps(small, large) == Decimal("200")


def test_no_route_fails_closed_without_spot_price_fallback() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "No route found"})

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.BUY))
    assert quote.status is QuoteStatus.ROUTE_UNAVAILABLE
    assert quote.raw_amount_out is None


def test_insufficient_liquidity_is_typed_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Insufficient liquidity"})

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.BUY))
    assert quote.status is QuoteStatus.INSUFFICIENT_LIQUIDITY


def test_settlement_reference_unavailable_fails_before_network_call() -> None:
    unavailable = replace(
        SETTLEMENT,
        state=SettlementReferenceState.REFERENCE_UNAVAILABLE,
        usd_per_asset=None,
    )
    req = replace(request(QuoteSide.BUY), settlement=unavailable)

    def handler(req: httpx.Request) -> httpx.Response:
        pytest.fail("network must not be called without settlement reference")

    with adapter_for(handler) as adapter:
        quote = adapter.quote(req)
    assert quote.status is QuoteStatus.SETTLEMENT_REFERENCE_UNAVAILABLE


def test_stale_quote_is_explicit_state() -> None:
    quote = _quote(QuoteSide.BUY, "100", "100", "0.5")
    old = replace(quote, quoted_at=datetime.now(timezone.utc) - timedelta(seconds=31))
    stale = enforce_freshness(old, now=datetime.now(timezone.utc), max_age_seconds=30)
    assert stale.status is QuoteStatus.STALE_QUOTE


def test_adapter_transport_failure_is_typed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.BUY))
    assert quote.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_provider_decimal_mismatch_fails_closed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        p = payload(USDG.contract_address, TOKEN.contract_address, 100_000_000, 500000000000000000)
        p["action"]["fromToken"]["decimals"] = 18
        return httpx.Response(200, json=p)

    with adapter_for(handler) as adapter:
        quote = adapter.quote(request(QuoteSide.BUY))
    assert quote.status is QuoteStatus.QUOTE_SOURCE_ERROR
