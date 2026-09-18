"""R0 Correction A — exact-input / chain binding adversarial tests.

Every mismatch case must fail closed, never produce QUOTE_OK, and preserve
an explicit typed failure state.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import (
    AssetRef,
    QuoteRequest,
    QuoteSide,
    QuoteStatus,
    SettlementReference,
    SettlementReferenceState,
)
from finco_radar.quotes.normalization import to_raw_amount

TOKEN = AssetRef(4663, "0x1111111111111111111111111111111111111111", symbol="STK", decimals=18)
USDG = AssetRef(4663, "0x2222222222222222222222222222222222222222", symbol="USDG", decimals=6)
TAKER = "0x3333333333333333333333333333333333333333"
SETTLEMENT = SettlementReference(
    asset=USDG,
    state=SettlementReferenceState.REFERENCE_CURRENT,
    usd_per_asset=Decimal("0.9998"),
    source="TEST_EXPLICIT_REFERENCE",
)
CHAIN = 4663


def _request(side: QuoteSide, notional: str = "100") -> QuoteRequest:
    return QuoteRequest(
        token=TOKEN,
        settlement=SETTLEMENT,
        side=side,
        requested_notional_usd=Decimal(notional),
        taker_address=TAKER,
        token_sizing_reference_usd=Decimal("200") if side is QuoteSide.SELL else None,
        token_sizing_reference_source="TEST" if side is QuoteSide.SELL else None,
    )


def _expected_raw(req: QuoteRequest) -> int:
    if req.side is QuoteSide.BUY:
        settlement_amount = req.requested_notional_usd / req.settlement.usd_per_asset
        return to_raw_amount(settlement_amount, req.settlement.asset.decimals or 0)
    token_amount = req.requested_notional_usd / req.token_sizing_reference_usd
    return to_raw_amount(token_amount, req.token.decimals or 0)


def _base_payload(from_addr: str, to_addr: str, from_amount: int, to_amount: int,
                  chain: int = CHAIN) -> dict[str, Any]:
    from_dec = USDG.decimals if from_addr.lower() == USDG.contract_address else TOKEN.decimals
    to_dec = TOKEN.decimals if to_addr.lower() == TOKEN.contract_address else USDG.decimals
    return {
        "id": "q-1", "type": "lifi", "tool": "mock-dex",
        "action": {
            "fromChainId": chain,
            "toChainId": chain,
            "fromToken": {"address": from_addr, "decimals": from_dec, "chainId": chain},
            "toToken": {"address": to_addr, "decimals": to_dec, "chainId": chain},
        },
        "estimate": {
            "fromAmount": str(from_amount), "toAmount": str(to_amount),
            "toAmountMin": str(int(to_amount * 0.995)),
            "feeCosts": [{"amountUSD": "0.10"}],
            "gasCosts": [{"amountUSD": "0.02"}],
            "executionDuration": 1.2,
        },
        "includedSteps": [],
        "transactionRequest": {"to": "0x44", "data": "0x5678"},
    }


def _adapter(payload: dict) -> LifiExecutionQuoteAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return LifiExecutionQuoteAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler),
                            base_url="https://example.invalid"))


def _assert_not_ok(quote):
    assert quote.status is not QuoteStatus.QUOTE_OK
    assert quote.raw_amount_in is None
    assert quote.unavailable_reason is not None


# ---------------------------------------------------------------------------
# A1 — exact input amount binding
# ---------------------------------------------------------------------------

def test_buy_wrong_input_amount_rejected():
    req = _request(QuoteSide.BUY)
    good = _expected_raw(req)
    bad = good + 1
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, bad, bad)
    q = _adapter(p).quote(req)
    _assert_not_ok(q)
    assert "input amount" in q.unavailable_reason.lower()


def test_sell_wrong_input_amount_rejected():
    req = _request(QuoteSide.SELL)
    good = _expected_raw(req)
    bad = good - 1
    p = _base_payload(TOKEN.contract_address, USDG.contract_address, bad, bad)
    q = _adapter(p).quote(req)
    _assert_not_ok(q)
    assert "input amount" in q.unavailable_reason.lower()


def test_exact_amount_accepted_buy():
    req = _request(QuoteSide.BUY)
    good = _expected_raw(req)
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, good, good)
    q = _adapter(p).quote(req)
    assert q.status is QuoteStatus.QUOTE_OK


def test_exact_amount_accepted_sell():
    req = _request(QuoteSide.SELL)
    good = _expected_raw(req)
    p = _base_payload(TOKEN.contract_address, USDG.contract_address, good, good)
    q = _adapter(p).quote(req)
    assert q.status is QuoteStatus.QUOTE_OK


# ---------------------------------------------------------------------------
# A2/A3 — chain binding
# ---------------------------------------------------------------------------

def test_buy_wrong_input_chain_rejected():
    req = _request(QuoteSide.BUY)
    good = _expected_raw(req)
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, good, good, chain=1)
    q = _adapter(p).quote(req)
    _assert_not_ok(q)
    assert "chain" in q.unavailable_reason.lower()


def test_sell_wrong_input_chain_rejected():
    req = _request(QuoteSide.SELL)
    good = _expected_raw(req)
    p = _base_payload(TOKEN.contract_address, USDG.contract_address, good, good, chain=137)
    q = _adapter(p).quote(req)
    _assert_not_ok(q)


def test_action_chain_correct_token_chain_wrong_rejected():
    good = _expected_raw(_request(QuoteSide.BUY))
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, good, good)
    p["action"]["fromToken"]["chainId"] = 1  # token chain disagrees
    p["action"]["fromToken"]["address"] = TOKEN.contract_address
    p["action"]["fromToken"]["decimals"] = TOKEN.decimals
    # swap from/to to match BUY direction
    p["action"]["fromToken"]["address"] = USDG.contract_address
    p["action"]["fromToken"]["decimals"] = USDG.decimals
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_token_chain_correct_action_chain_wrong_rejected():
    good = _expected_raw(_request(QuoteSide.BUY))
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, good, good)
    p["action"]["fromChainId"] = 999  # action chain disagrees
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_matching_address_on_wrong_chain_rejected():
    """Address matches textually but chain is wrong — must fail."""
    req = _request(QuoteSide.BUY)
    wrong_chain = 1
    p = _base_payload(
        USDG.contract_address, TOKEN.contract_address,
        _expected_raw(req), _expected_raw(req), chain=wrong_chain)
    q = _adapter(p).quote(req)
    _assert_not_ok(q)


# ---------------------------------------------------------------------------
# A4 — missing / malformed fields
# ---------------------------------------------------------------------------

def test_missing_from_amount_rejected():
    def m(s):
        s["estimate"].pop("fromAmount")
    subject = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    subject["estimate"].pop("fromAmount")
    q = _adapter(subject).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_missing_chain_binding_rejected():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    p["action"].pop("fromChainId")
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_malformed_amount_rejected():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    p["estimate"]["fromAmount"] = "not-a-number"
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_malformed_chain_id_rejected():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    p["action"]["fromChainId"] = "not-a-chain"
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


# ---------------------------------------------------------------------------
# A5 — raw provider evidence preserved
# ---------------------------------------------------------------------------

def test_provider_evidence_preserved_on_mismatch():
    req = _request(QuoteSide.BUY)
    good = _expected_raw(req)
    bad = good + 1
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, bad, bad)
    q = _adapter(p).quote(req)
    assert q.evidence is not None
    assert q.evidence.request_params.get("fromAmount") == str(good)
    assert q.evidence.response_fields["estimate"]["fromAmount"] == str(bad)
