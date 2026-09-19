"""R0 Correction B — strict exact-input binding / fail-closed hardening."""
from __future__ import annotations

import copy
import httpx
import pytest

from finco_radar.quotes.contracts import QuoteSide, QuoteStatus
from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from test_radar_r0_exact_input_binding import (
    CHAIN, TOKEN, USDG, TAKER, SETTLEMENT,
    _adapter, _base_payload, _expected_raw, _request, _assert_not_ok,
)


def _mutated(mutator):
    payload = _base_payload(
        USDG.contract_address, TOKEN.contract_address,
        _expected_raw(_request(QuoteSide.BUY)),
        _expected_raw(_request(QuoteSide.BUY)))
    mutator(payload)
    return payload


# ---------------------------------------------------------------------------
# B2: strict amount type/representation
# ---------------------------------------------------------------------------

def test_b2_amount_numeric_integer_rejected():
    """LI.FI contract sends strings; numeric JSON int must be rejected."""
    def m(p):
        p["estimate"]["fromAmount"] = _expected_raw(_request(QuoteSide.BUY))
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_float_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = float(_expected_raw(_request(QuoteSide.BUY)))
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_boolean_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = True
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_whitespace_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = f" {1000} "
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_negative_string_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = "-1000"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_fractional_string_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = "1000.5"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_none_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = None
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b2_amount_off_by_one_rejected():
    def m(p):
        p["estimate"]["fromAmount"] = _expected_raw(_request(QuoteSide.BUY)) + 1
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


# ---------------------------------------------------------------------------
# B3: strict chain validation (all 4 positions)
# ---------------------------------------------------------------------------

def test_cb_b3_chain_float_fractional_rejected():
    def m(p):
        p["action"]["fromChainId"] = 4663.9
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_chain_boolean_rejected():
    def m(p):
        p["action"]["fromChainId"] = True
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_chain_none_rejected():
    def m(p):
        p["action"]["fromChainId"] = None
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_from_token_chain_wrong_rejected():
    def m(p):
        p["action"]["fromToken"]["chainId"] = 1
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_to_chain_wrong_rejected():
    def m(p):
        p["action"]["toChainId"] = 1
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_to_token_chain_wrong_rejected():
    def m(p):
        p["action"]["toToken"]["chainId"] = 1
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_from_token_chain_float_rejected():
    def m(p):
        p["action"]["fromToken"]["chainId"] = 4663.0
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_inconsistent_chain_fields_rejected():
    def m(p):
        p["action"]["fromChainId"] = CHAIN
        p["action"]["fromToken"]["chainId"] = 1
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b3_missing_from_chain_rejected():
    def m(p):
        p["action"].pop("fromChainId")
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


# ---------------------------------------------------------------------------
# B4: malformed nested structures fail closed
# ---------------------------------------------------------------------------

def test_cb_b4_estimate_not_mapping_rejected():
    def m(p):
        p["estimate"] = "bad"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b4_action_not_mapping_rejected():
    def m(p):
        p["action"] = "bad"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b4_from_token_not_mapping_rejected():
    def m(p):
        p["action"]["fromToken"] = "bad"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b4_to_token_not_mapping_rejected():
    def m(p):
        p["action"]["toToken"] = None
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    _assert_not_ok(q)


def test_cb_b4_fee_costs_scalar_member_rejected():
    def m(p):
        p["estimate"]["feeCosts"] = [42]
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    assert q.status is not QuoteStatus.QUOTE_OK


def test_cb_b4_included_steps_scalar_member_rejected():
    def m(p):
        p["includedSteps"] = ["not-a-mapping"]
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    assert q.status is not QuoteStatus.QUOTE_OK


def test_cb_b4_transaction_request_null_is_ok():
    """transactionRequest = None is a valid absence, not malformed."""
    def m(p):
        p["transactionRequest"] = None
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_OK


# ---------------------------------------------------------------------------
# B5: raw diagnostic evidence on rejection
# ---------------------------------------------------------------------------

def test_cb_b5_rejection_preserves_both_sides():
    req = _request(QuoteSide.BUY)
    submitted = _expected_raw(req)
    provider_returned = submitted + 1
    payload = _base_payload(USDG.contract_address, TOKEN.contract_address,
                            provider_returned, provider_returned)
    q = _adapter(payload).quote(req)
    assert q.status is not QuoteStatus.QUOTE_OK
    assert q.evidence is not None
    # submitted
    assert q.evidence.request_params["fromAmount"] == str(submitted)
    # provider actually returned
    assert q.evidence.response_fields["estimate"]["fromAmount"] == str(provider_returned)
    # they differ
    assert q.evidence.request_params["fromAmount"] != (
        q.evidence.response_fields["estimate"]["fromAmount"])


# ---------------------------------------------------------------------------
# Correction D - D1/D2/D3/D4: nested route evidence + root shape + chain type
# ---------------------------------------------------------------------------

def _seed_nested_step(p: dict) -> None:
    """D3: append one well-formed nested route step mirroring the top-level
    leg, so nested-field mutations exercise the includedSteps evidence path."""
    p["includedSteps"].append({
        "tool": "nested-bridge",
        "action": copy.deepcopy(p["action"]),
        "estimate": {
            "fromAmount": p["estimate"]["fromAmount"],
            "toAmount": p["estimate"]["toAmount"],
        },
    })


def test_d3_nested_route_from_token_address_int():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["action"]["fromToken"]["address"] = 123
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_to_token_address_int():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["action"]["toToken"]["address"] = 456
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_from_token_address_empty():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["action"]["fromToken"]["address"] = ""
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_to_token_address_empty():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["action"]["toToken"]["address"] = ""
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_estimate_from_amount_missing():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"].pop("fromAmount")
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_estimate_to_amount_missing():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"].pop("toAmount")
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_from_amount_list():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["fromAmount"] = [1000]
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_to_amount_dict():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["toAmount"] = {"amount": 1000}
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_from_amount_bool():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["fromAmount"] = True
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_to_amount_float():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["toAmount"] = 1000.5
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_from_amount_malformed_string():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["fromAmount"] = "12.5"
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_to_amount_malformed_string():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["toAmount"] = "1e3"
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d3_nested_route_from_amount_padded_string():
    p = _base_payload(USDG.contract_address, TOKEN.contract_address, 1000, 1000)
    _seed_nested_step(p)
    p["includedSteps"][0]["estimate"]["fromAmount"] = " 1000 "
    q = _adapter(p).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_root_json_array():
    def handler(req):
        return httpx.Response(200, json=[])
    adapter = LifiExecutionQuoteAdapter(client=httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://x.invalid"))
    q = adapter.quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_root_json_string():
    def handler(req):
        return httpx.Response(200, json="bad")
    adapter = LifiExecutionQuoteAdapter(client=httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://x.invalid"))
    q = adapter.quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_root_json_number():
    def handler(req):
        return httpx.Response(200, json=123)
    adapter = LifiExecutionQuoteAdapter(client=httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://x.invalid"))
    q = adapter.quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_root_json_true():
    def handler(req):
        return httpx.Response(200, json=True)
    adapter = LifiExecutionQuoteAdapter(client=httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://x.invalid"))
    q = adapter.quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_root_json_null():
    def handler(req):
        return httpx.Response(200, content=b"null",
                              headers={"content-type": "application/json"})
    adapter = LifiExecutionQuoteAdapter(client=httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://x.invalid"))
    q = adapter.quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR


def test_d4_chain_string_rejected():
    def m(p):
        p["action"]["fromChainId"] = "4663"
    q = _adapter(_mutated(m)).quote(_request(QuoteSide.BUY))
    assert q.status is QuoteStatus.QUOTE_SOURCE_ERROR
