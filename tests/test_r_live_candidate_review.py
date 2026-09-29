"""Admission tooling derives identity from registry fields; no ticker authority."""
from __future__ import annotations

import httpx
import pytest

from tools.r_live_v2_candidate_review import _batch, _registry_candidates


def row(symbol: str, uid: str, token: str, *, status: str = "ASSET_STATUS_ACTIVE",
        isin: str | None = "US0000000000", chain: int = 4663) -> dict:
    return {"tokenSymbol": symbol, "tokenName": "Example Robinhood Token", "id": uid,
            "status": status, "isin": isin,
            "deployments": [{"chainId": chain, "contractAddress": token}]}


def test_registry_candidate_discovery_is_not_shortlisted_by_symbol():
    first = row("UNFAMILIAR", "0x" + "11" * 32, "0x" + "aa" * 20)
    approved = row("APPROVED", "0x" + "22" * 32, "0x" + "bb" * 20)
    inactive = row("INACTIVE", "0x" + "33" * 32, "0x" + "cc" * 20,
                   status="ASSET_STATUS_INACTIVE")
    no_isin = row("NO_ISIN", "0x" + "44" * 32, "0x" + "dd" * 20, isin=None)
    wrong_chain = row("WRONG_CHAIN", "0x" + "55" * 32, "0x" + "ee" * 20, chain=1)
    eligible, candidates = _registry_candidates(
        [first, approved, inactive, no_isin, wrong_chain], {"0x" + "bb" * 20})
    assert len(eligible) == 2
    assert candidates == [("UNFAMILIAR", "0x" + "11" * 32, "0x" + "aa" * 20)]


def test_registry_identity_conflict_fails_closed():
    first = row("ONE", "0x" + "11" * 32, "0x" + "aa" * 20)
    duplicate = row("TWO", "0x" + "22" * 32, "0x" + "aa" * 20)
    with pytest.raises(ValueError, match="REGISTRY_IDENTITY_CONFLICT"):
        _registry_candidates([first, duplicate], set())


def test_readonly_batch_is_bounded_and_validates_all_responses():
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rpc.mainnet.chain.robinhood.com"
        import json
        calls = json.loads(request.content)
        sizes.append(len(calls))
        return httpx.Response(200, json=[{"jsonrpc": "2.0", "id": c["id"], "result": "0x123"}
                                         for c in reversed(calls)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert _batch(client, [("eth_chainId", [])] * 9) == ["0x123"] * 9
    assert sizes == [4, 4, 1]
