"""Offline test matrix for the Robinhood live multi-asset universe feature.

Items A–V: deterministic, network-free.  Every test injects fakes through
the documented composition seams (set_registry_factory, set_service) and
exercises the real router + templates.

No wallet, no signing, no transaction submission.  No network calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore
from app.radar_ui import composition
from app.radar_ui import router as radar_router_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

_AAPL_ADDR = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_NVDA_ADDR = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_TSLA_ADDR = "0xcccccccccccccccccccccccccccccccccccccccc"
_CHAIN = 4663


def _make_asset_record(uid, symbol, name, address, chain_id=_CHAIN, decimals=18):
    key = SimpleNamespace(chain_id=chain_id, contract_address=address)
    return SimpleNamespace(
        asset_uid=uid,
        token_symbol=symbol,
        token_name=name,
        raw_evidence={"tokenDecimals": decimals},
        deployment_for_chain=lambda c, _k=key, _ch=chain_id: (
            _k if c == _ch else None),
    )


def _make_registry(assets: list, *, include_fetch_bound=True):
    by_uid = {a.asset_uid: a for a in assets}
    snapshot = SimpleNamespace(
        assets=assets,
        get_by_uid=lambda u: by_uid.get(u),
    )

    def fetch_bound(sn, key):
        return {}, {}

    ns = SimpleNamespace(fetch_snapshot=lambda: snapshot)
    if include_fetch_bound:
        ns.fetch_bound_reference = fetch_bound
    return ns


def _fake_core(calls: list, uid="AAPL", address=_AAPL_ADDR):
    def provider(request):
        calls.append(request)
        return {
            "evidence": {
                "asset": {
                    "symbol": uid,
                    "economicAssetUid": uid,
                    "chainId": _CHAIN,
                    "contractAddress": address,
                },
                "observedAt": "2026-09-19T12:00:00+00:00",
                "reference": {
                    "available": True,
                    "price": "150.00",
                    "bid": "149.90",
                    "ask": "150.10",
                    "source": "FROZEN::BoundReferencePrice",
                    "observedAt": "2026-09-19T11:59:00+00:00",
                },
                "execution": {
                    "available": False,
                    "side": request.direction,
                    "notionalUsd": request.notional_usd,
                    "status": "SETTLEMENT_UNAVAILABLE",
                    "source": None,
                    "quotedAt": "2026-09-19T12:00:00+00:00",
                },
                "gap": {"available": False,
                        "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
            },
            "observedAt": "2026-09-19T12:00:00+00:00",
        }
    return provider


def _build_service(calls: list, uid="AAPL", address=_AAPL_ADDR):
    return AcquisitionService(
        SnapshotStore(":memory:"),
        {"radar-core": _fake_core(calls, uid=uid, address=address)},
        config=ServiceConfig(
            per_provider_timeout_seconds=2.0,
            total_budget_seconds=5.0,
            max_concurrent_providers=4,
        ),
        clock=lambda: NOW,
    )


@pytest.fixture
def make_client():
    def _make(service):
        radar_router_module.set_service(service)
        app = FastAPI()
        app.include_router(radar_router_module.router)
        return TestClient(app)
    return _make


# ---------------------------------------------------------------------------
# A: universe contains multiple assets
# ---------------------------------------------------------------------------

def test_A_universe_contains_multiple_assets():
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR),
        _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR),
        _make_asset_record("TSLA", "TSLA", "Tesla Inc.", _TSLA_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    symbols = [a.token_symbol for a in result]
    assert "AAPL" in symbols
    assert "NVDA" in symbols
    assert "TSLA" in symbols
    assert len(result) == 3


# ---------------------------------------------------------------------------
# B: universe sorted deterministically (symbol, uid)
# ---------------------------------------------------------------------------

def test_B_universe_sorted_deterministically():
    assets = [
        _make_asset_record("TSLA", "TSLA", "Tesla Inc.", _TSLA_ADDR),
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR),
        _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    symbols = [a.token_symbol for a in result]
    assert symbols == sorted(symbols)


# ---------------------------------------------------------------------------
# C: selection uses UID not ticker
# ---------------------------------------------------------------------------

def test_C_selection_uses_uid_not_ticker(make_client):
    nvda_uid = "NVDA-uid-canonical"
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR),
        _make_asset_record(nvda_uid, "NVDA", "NVIDIA Corp.", _NVDA_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([], uid=nvda_uid, address=_NVDA_ADDR))
        page = c.get(f"/radar?asset_uid={nvda_uid}").text
    finally:
        composition.set_registry_factory(None)

    assert "NVDA" in page
    assert nvda_uid in page


# ---------------------------------------------------------------------------
# D: duplicate symbols don't create ambiguity (UID uniqueness)
# ---------------------------------------------------------------------------

def test_D_duplicate_symbols_no_ambiguity():
    uid_a = "TOKEN-A-canonical"
    uid_b = "TOKEN-B-canonical"
    addr_a = "0x" + "aa" * 20
    addr_b = "0x" + "bb" * 20
    assets = [
        _make_asset_record(uid_a, "SAME", "Token A", addr_a),
        _make_asset_record(uid_b, "SAME", "Token B", addr_b),
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    uids = {a.economic_asset_uid for a in result}
    assert uid_a in uids and uid_b in uids
    assert len(result) == 2


# ---------------------------------------------------------------------------
# E: invalid UID not in universe fails closed (ASSET_NOT_FOUND_IN_UNIVERSE)
# ---------------------------------------------------------------------------

def test_E_invalid_uid_fails_closed(make_client):
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        resp = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100",
                  "asset_uid": "DOES-NOT-EXIST"},
            headers={"HX-Request": "true"},
        )
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    assert "ASSET_NOT_FOUND_IN_UNIVERSE" in resp.text


# ---------------------------------------------------------------------------
# F: exact chain deployment enforced — asset without chain 4663 excluded
# ---------------------------------------------------------------------------

def test_F_exact_chain_deployment_enforced():
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR,
                           chain_id=_CHAIN),
        _make_asset_record("FOREIGN", "FOREIGN", "Foreign Asset",
                           "0x" + "ff" * 20, chain_id=1),  # Ethereum mainnet
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    uids = {a.economic_asset_uid for a in result}
    assert "AAPL" in uids
    assert "FOREIGN" not in uids


# ---------------------------------------------------------------------------
# G: wrong contract fails identity binding (A3)
# ---------------------------------------------------------------------------

def test_G_wrong_contract_fails_reference_identity():
    wrong_address = "0x" + "ee" * 20
    key = SimpleNamespace(chain_id=_CHAIN, contract_address=wrong_address)
    asset_record = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        raw_evidence={"tokenDecimals": 18},
        deployment_for_chain=lambda c: key if c == _CHAIN else None,
    )
    snapshot = SimpleNamespace(
        assets=[asset_record],
        get_by_uid=lambda u: asset_record if u == "AAPL" else None,
    )

    def factory():
        return SimpleNamespace(
            fetch_snapshot=lambda: snapshot,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    # build_request uses asset_config() which has a different contract
    source = composition.composition_radar_source(registry_factory=factory)
    request_obj = composition.build_request("BUY", "100")
    # contract mismatch: wrong_address != asset_config contractAddress
    result = source(request_obj)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "REFERENCE_IDENTITY_MISMATCH"


# ---------------------------------------------------------------------------
# H: tokenDecimals sourced from raw_evidence
# ---------------------------------------------------------------------------

def test_H_token_decimals_from_raw_evidence():
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR,
                           decimals=6),
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    assert len(result) == 1
    assert result[0].token_decimals == 6


# ---------------------------------------------------------------------------
# I: missing tokenDecimals in raw_evidence excludes asset
# ---------------------------------------------------------------------------

def test_I_missing_decimals_excluded():
    key = SimpleNamespace(chain_id=_CHAIN, contract_address=_AAPL_ADDR)
    asset_no_decimals = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        token_name="Apple Inc.",
        raw_evidence={},  # no tokenDecimals key
        deployment_for_chain=lambda c: key if c == _CHAIN else None,
    )

    def factory():
        snapshot = SimpleNamespace(assets=[asset_no_decimals])
        return SimpleNamespace(fetch_snapshot=lambda: snapshot)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# J: invalid tokenDecimals (non-numeric / negative) excludes asset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_val", ["notanumber", "-1", None])
def test_J_invalid_decimals_excluded(bad_val):
    key = SimpleNamespace(chain_id=_CHAIN, contract_address=_AAPL_ADDR)
    asset = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        token_name="Apple Inc.",
        raw_evidence={"tokenDecimals": bad_val},
        deployment_for_chain=lambda c: key if c == _CHAIN else None,
    )

    def factory():
        snapshot = SimpleNamespace(assets=[asset])
        return SimpleNamespace(fetch_snapshot=lambda: snapshot)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# K: AAPL not required — universe works without it
# ---------------------------------------------------------------------------

def test_K_aapl_not_required():
    assets = [
        _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR),
        _make_asset_record("TSLA", "TSLA", "Tesla Inc.", _TSLA_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    symbols = {a.token_symbol for a in result}
    assert "NVDA" in symbols and "TSLA" in symbols
    assert "AAPL" not in symbols


# ---------------------------------------------------------------------------
# L: same service handles two different assets sequentially
# ---------------------------------------------------------------------------

def test_L_same_service_handles_two_assets(make_client):
    calls: list = []
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)
    nvda_rec = _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR)
    assets = [aapl_rec, nvda_rec]

    def factory():
        by_uid = {"AAPL": aapl_rec, "NVDA": nvda_rec}
        snapshot = SimpleNamespace(
            assets=assets,
            get_by_uid=lambda u: by_uid.get(u),
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snapshot,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    service = _build_service(calls)
    composition.set_registry_factory(factory)
    try:
        c = make_client(service)
        r1 = c.post("/radar/refresh",
                    data={"direction": "BUY", "size": "100",
                          "asset_uid": "AAPL"},
                    headers={"HX-Request": "true"})
        r2 = c.post("/radar/refresh",
                    data={"direction": "BUY", "size": "100",
                          "asset_uid": "NVDA"},
                    headers={"HX-Request": "true"})
    finally:
        composition.set_registry_factory(None)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(calls) == 2
    assert calls[0].economic_asset_uid == "AAPL"
    assert calls[1].economic_asset_uid == "NVDA"


# ---------------------------------------------------------------------------
# M: request fingerprints differ across assets
# ---------------------------------------------------------------------------

def test_M_request_fingerprints_differ():
    req_aapl = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=18,
        ))
    req_nvda = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="NVDA",
            token_symbol="NVDA",
            token_name="NVIDIA Corp.",
            chain_id=_CHAIN,
            contract_address=_NVDA_ADDR,
            token_decimals=18,
        ))
    assert req_aapl.economic_asset_uid != req_nvda.economic_asset_uid
    assert req_aapl.contract_address != req_nvda.contract_address


# ---------------------------------------------------------------------------
# N: snapshot identity immutable after acquisition
# ---------------------------------------------------------------------------

def test_N_snapshot_identity_immutable(make_client):
    calls: list = []
    assets = [
        _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR),
    ]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post("/radar/refresh",
                      data={"direction": "BUY", "size": "100",
                            "asset_uid": "AAPL"},
                      headers={"HX-Request": "true"})
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    import re
    ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp.text)
    assert len(ids) >= 1
    # all IDs in the response are the same snapshot
    assert len(set(ids)) == 1


# ---------------------------------------------------------------------------
# O: snapshot re-render is network-free (no new calls after acquire)
# ---------------------------------------------------------------------------

def test_O_snapshot_rerender_network_free(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post("/radar/refresh",
                      data={"direction": "BUY", "size": "100",
                            "asset_uid": "AAPL"},
                      headers={"HX-Request": "true"})
        import re
        ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp.text)
        snapshot_id = ids[0]
        count_after_acquire = len(calls)
        # network-free re-render
        resp2 = c.get(f"/radar/snapshot/{snapshot_id}")
    finally:
        composition.set_registry_factory(None)

    assert resp2.status_code == 200
    assert len(calls) == count_after_acquire  # no new acquire calls


# ---------------------------------------------------------------------------
# P: Evidence Inspector is network-free
# ---------------------------------------------------------------------------

def test_P_evidence_inspector_network_free(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post("/radar/refresh",
                      data={"direction": "BUY", "size": "100",
                            "asset_uid": "AAPL"},
                      headers={"HX-Request": "true"})
        import re
        ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp.text)
        snapshot_id = ids[0]
        count_after_acquire = len(calls)
        resp2 = c.get(
            f"/radar/inspector/{snapshot_id}/reference.price")
    finally:
        composition.set_registry_factory(None)

    assert resp2.status_code == 200
    assert len(calls) == count_after_acquire


# ---------------------------------------------------------------------------
# Q: HTMX OOB swap updates asset header (no stale identity)
# ---------------------------------------------------------------------------

def test_Q_htmx_oob_swap_updates_asset_header(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post("/radar/refresh",
                      data={"direction": "BUY", "size": "100",
                            "asset_uid": "AAPL"},
                      headers={"HX-Request": "true"})
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    # The OOB div must be present in the partial response for HTMX to swap
    assert 'hx-swap-oob="true"' in resp.text
    assert 'id="radar-asset-header"' in resp.text


# ---------------------------------------------------------------------------
# R: non-JS full-page POST identity not stale (selected_from_snapshot)
# ---------------------------------------------------------------------------

def test_R_non_js_post_identity_not_stale(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post("/radar/refresh",
                      data={"direction": "BUY", "size": "100",
                            "asset_uid": "AAPL"})
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    assert "AAPL" in resp.text


# ---------------------------------------------------------------------------
# S: READ-ONLY boundary: no wallet/signing/transaction controls in UI
# ---------------------------------------------------------------------------

def test_S_read_only_boundary_no_wallet_controls(make_client):
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert "READ-ONLY" in page
    lower = page.lower()
    # Check for actual wallet-interaction controls, not just the word in
    # the READ-ONLY disclaimer ("no wallet, no signing…").
    for forbidden in ("connect wallet", "sendethereum", "sendtransaction",
                      "eth_sendtransaction", "web3.eth.sendtransaction",
                      "signmessage", "personal_sign", "eth_sign",
                      "requestaccounts"):
        assert forbidden not in lower, (
            f"found forbidden wallet control term: {forbidden!r}")


# ---------------------------------------------------------------------------
# T: $100 and $1,000 authority sizes preserved
# ---------------------------------------------------------------------------

def test_T_reviewed_sizes_preserved(make_client):
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert 'value="100"' in page
    assert 'value="1000"' in page
    # no arbitrary size input
    assert 'type="number"' not in page


# ---------------------------------------------------------------------------
# U: directional BUY/SELL controls preserved
# ---------------------------------------------------------------------------

def test_U_directional_gap_controls_preserved(make_client):
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert 'value="BUY"' in page
    assert 'value="SELL"' in page
    assert 'name="direction"' in page


# ---------------------------------------------------------------------------
# V: no wallet/signing/submission in any panel HTML (exhaustive)
# ---------------------------------------------------------------------------

def test_V_no_wallet_signing_in_panels(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        panels = c.post("/radar/refresh",
                        data={"direction": "BUY", "size": "100",
                              "asset_uid": "AAPL"},
                        headers={"HX-Request": "true"}).text
    finally:
        composition.set_registry_factory(None)

    lower = panels.lower()
    for forbidden in ("private key", "mnemonic", "seed phrase",
                      "eth_sendtransaction", "sendtransaction",
                      "signmessage", "personal_sign", "eth_sign"):
        assert forbidden not in lower, f"forbidden term found: {forbidden!r}"


# ---------------------------------------------------------------------------
# Extra: universe unavailable → page renders fail-closed, Refresh disabled
# ---------------------------------------------------------------------------

def test_universe_unavailable_refresh_disabled(make_client):
    def factory():
        raise RuntimeError("registry down")

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert resp_has_disabled_refresh(page)


def resp_has_disabled_refresh(page: str) -> bool:
    import re
    buttons = re.findall(
        r'<button[^>]*type=["\']submit["\'][^>]*>.*?</button>',
        page, re.S)
    for btn in buttons:
        if "Refresh" in btn and "disabled" in btn:
            return True
    return False


# ---------------------------------------------------------------------------
# Extra: fetch_robinhood_asset_universe seam isolation
# ---------------------------------------------------------------------------

def test_registry_factory_seam_isolation():
    calls = []

    def factory():
        calls.append(1)
        assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]
        return _make_registry(assets)

    result = composition.fetch_robinhood_asset_universe(
        registry_factory=factory, target_chain_id=_CHAIN)
    assert len(calls) == 1
    assert len(result) == 1
    assert result[0].economic_asset_uid == "AAPL"


def test_set_registry_factory_global_seam():
    calls = []

    def factory():
        calls.append(1)
        assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        result = composition.fetch_robinhood_asset_universe(
            target_chain_id=_CHAIN)
    finally:
        composition.set_registry_factory(None)
    assert len(calls) == 1
    assert len(result) == 1
    # seam cleared
    assert composition._registry_factory_override is None
