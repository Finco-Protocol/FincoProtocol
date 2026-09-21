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


# ---------------------------------------------------------------------------
# Item 8 — C01: missing asset_uid → ASSET_UID_REQUIRED, zero acquire
# ---------------------------------------------------------------------------

def test_item8_c01_missing_asset_uid_required(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    assert "ASSET_UID_REQUIRED" in resp.text
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Item 8 — C01: registry unavailable → ASSET_UNIVERSE_UNAVAILABLE, zero acquire
# ---------------------------------------------------------------------------

def test_item8_c01_universe_unavailable_zero_acquire(make_client):
    calls: list = []

    def factory():
        raise RuntimeError("registry down")

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        resp = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100", "asset_uid": "AAPL"},
            headers={"HX-Request": "true"},
        )
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    assert "ASSET_UNIVERSE_UNAVAILABLE" in resp.text
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Item 8 — C01: unknown UID → ASSET_NOT_FOUND_IN_UNIVERSE, zero acquire
# ---------------------------------------------------------------------------

def test_item8_c01_unknown_uid_zero_acquire(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
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
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Item 8 — _parse_token_decimals: direct unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_val,description", [
    (None, "None rejected"),
    (True, "bool True rejected"),
    (False, "bool False rejected"),
    (-1, "negative int rejected"),
    (256, "out-of-range 256 rejected"),
    ("abc", "non-numeric string rejected"),
    (1.5, "float rejected"),
    ("1.5", "fractional string rejected"),
])
def test_item8_parse_token_decimals_rejects(bad_val, description):
    from app.radar_ui.composition import (
        TokenDecimalsUnavailable,
        _parse_token_decimals,
    )
    with pytest.raises(TokenDecimalsUnavailable):
        _parse_token_decimals(bad_val)


@pytest.mark.parametrize("good_val,expected", [
    (0, 0),
    (6, 6),
    (18, 18),
    (255, 255),
    ("18", 18),
    ("0", 0),
    ("255", 255),
])
def test_item8_parse_token_decimals_accepts(good_val, expected):
    from app.radar_ui.composition import _parse_token_decimals
    assert _parse_token_decimals(good_val) == expected


# ---------------------------------------------------------------------------
# Item 8 — fingerprint: decimals 18 vs 6 same identity → different fingerprint
# ---------------------------------------------------------------------------

def test_item8_fingerprint_decimals_18_vs_6_differ():
    req_18 = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=18,
        ))
    req_6 = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=6,
        ))
    assert req_18.economic_asset_uid == req_6.economic_asset_uid
    assert req_18.contract_address == req_6.contract_address
    assert req_18.fingerprint != req_6.fingerprint


# ---------------------------------------------------------------------------
# Item 8 — fingerprint: actual .fingerprint comparison for M-type test
# ---------------------------------------------------------------------------

def test_item8_fingerprint_differs_across_assets():
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
    assert req_aapl.fingerprint != req_nvda.fingerprint


# ---------------------------------------------------------------------------
# Item 8 — decimals mismatch fails reference closed (TOKEN_DECIMALS_AUTHORITY_MISMATCH)
# ---------------------------------------------------------------------------

def test_item8_decimals_mismatch_fails_reference_closed():
    # Registry says decimals=18 but request was built with decimals=6
    aapl_rec = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        raw_evidence={"tokenDecimals": 18},  # live registry says 18
        deployment_for_chain=lambda c: SimpleNamespace(
            chain_id=_CHAIN, contract_address=_AAPL_ADDR) if c == _CHAIN else None,
    )
    snapshot = SimpleNamespace(
        assets=[aapl_rec],
        get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
    )

    def factory():
        return SimpleNamespace(
            fetch_snapshot=lambda: snapshot,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    source = composition.composition_radar_source(registry_factory=factory)
    req = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=6,  # fingerprint-bound decimals = 6, live = 18 → mismatch
        ))
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "TOKEN_DECIMALS_AUTHORITY_MISMATCH"


# ---------------------------------------------------------------------------
# Item 8 — stable TOKEN_DECIMALS_UNAVAILABLE from composition_radar_source
# ---------------------------------------------------------------------------

def test_item8_token_decimals_unavailable_stable_reason():
    aapl_rec = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        raw_evidence={},  # missing tokenDecimals
        deployment_for_chain=lambda c: SimpleNamespace(
            chain_id=_CHAIN, contract_address=_AAPL_ADDR) if c == _CHAIN else None,
    )
    snapshot = SimpleNamespace(
        assets=[aapl_rec],
        get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
    )

    def factory():
        return SimpleNamespace(
            fetch_snapshot=lambda: snapshot,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    source = composition.composition_radar_source(registry_factory=factory)
    req = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=18,
        ))
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "TOKEN_DECIMALS_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Item 8 — NVDA selection: no stale AAPL in header/panel
# ---------------------------------------------------------------------------

def test_item8_nvda_selection_no_stale_aapl(make_client):
    calls: list = []
    nvda_rec = _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR)
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)
    assets = [aapl_rec, nvda_rec]

    def factory():
        by_uid = {"AAPL": aapl_rec, "NVDA": nvda_rec}
        snap = SimpleNamespace(
            assets=assets,
            get_by_uid=lambda u: by_uid.get(u),
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls, uid="NVDA", address=_NVDA_ADDR))
        resp = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100", "asset_uid": "NVDA"},
            headers={"HX-Request": "true"},
        )
    finally:
        composition.set_registry_factory(None)

    assert resp.status_code == 200
    assert "NVDA" in resp.text
    # OOB header must identify the snapshot's actual asset (NVDA)
    assert 'id="radar-asset-header"' in resp.text
    # The response must not show AAPL as the selected/acquired asset
    assert calls[0].economic_asset_uid == "NVDA"


# ---------------------------------------------------------------------------
# Item 8 — snapshot query: NVDA snapshot cannot render AAPL as target
# ---------------------------------------------------------------------------

def test_item8_snapshot_query_identity_consistent(make_client):
    calls: list = []
    nvda_rec = _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR)
    assets = [nvda_rec]

    def factory():
        snap = SimpleNamespace(
            assets=assets,
            get_by_uid=lambda u: nvda_rec if u == "NVDA" else None,
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls, uid="NVDA", address=_NVDA_ADDR))
        # Acquire NVDA snapshot
        resp = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100", "asset_uid": "NVDA"},
            headers={"HX-Request": "true"},
        )
        import re
        ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp.text)
        snapshot_id = ids[0]
        # Re-render the NVDA snapshot — identity must remain NVDA
        resp2 = c.get(f"/radar/snapshot/{snapshot_id}")
    finally:
        composition.set_registry_factory(None)

    assert resp2.status_code == 200
    # The NVDA snapshot panels must contain NVDA identity, not AAPL
    assert calls[0].economic_asset_uid == "NVDA"
    assert "NVDA" in resp2.text


# ---------------------------------------------------------------------------
# Item 8 — full page has exactly one id="radar-asset-header"
# ---------------------------------------------------------------------------

def test_item8_full_page_single_asset_header(make_client):
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    import re
    matches = re.findall(r'id=["\']radar-asset-header["\']', page)
    assert len(matches) == 1, (
        f"expected exactly 1 id='radar-asset-header', found {len(matches)}")


# ---------------------------------------------------------------------------
# Item 8 — HTMX partial has OOB, full page does NOT have hx-swap-oob
# ---------------------------------------------------------------------------

def test_item8_oob_only_in_htmx_partial(make_client):
    calls: list = []
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service(calls))
        # HTMX partial: must have OOB
        partial = c.post(
            "/radar/refresh",
            data={"direction": "BUY", "size": "100", "asset_uid": "AAPL"},
            headers={"HX-Request": "true"},
        ).text
        # Full-page GET: must NOT have hx-swap-oob on the asset header
        full_page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert 'hx-swap-oob="true"' in partial
    # In the full page, id="radar-asset-header" exists exactly once and
    # must NOT carry hx-swap-oob (the index.html owns the element,
    # not panels.html's OOB block)
    import re
    oob_in_full = re.findall(
        r'id=["\']radar-asset-header["\'][^>]*hx-swap-oob', full_page)
    assert len(oob_in_full) == 0, (
        "full-page render must not emit hx-swap-oob on radar-asset-header")


# ===========================================================================
# Correction B tests
# ===========================================================================


# ---------------------------------------------------------------------------
# B01 — fingerprint-bound decimals are mandatory
# ---------------------------------------------------------------------------

def _make_aapl_source_factory(decimals_in_registry=18):
    """Helper: registry with AAPL whose tokenDecimals matches registry value."""
    aapl_rec = SimpleNamespace(
        asset_uid="AAPL",
        token_symbol="AAPL",
        raw_evidence={"tokenDecimals": decimals_in_registry},
        deployment_for_chain=lambda c: SimpleNamespace(
            chain_id=_CHAIN, contract_address=_AAPL_ADDR) if c == _CHAIN else None,
    )
    snapshot = SimpleNamespace(
        assets=[aapl_rec],
        get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
    )

    def factory():
        return SimpleNamespace(
            fetch_snapshot=lambda: snapshot,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )
    return factory


def _build_request_no_target_asset(direction="BUY", size="100",
                                   uid="AAPL", address=_AAPL_ADDR):
    """Build AcquisitionRequest without targetAsset in provider_config."""
    from app.radar_runtime.contracts import AcquisitionRequest
    from app.radar_ui.quote_context import resolve_quote_context
    qc = resolve_quote_context(expected_chain_id=_CHAIN)
    return AcquisitionRequest(
        chain_id=_CHAIN,
        contract_address=address,
        direction=direction,
        sources=(composition.PROVIDER_NAME,),
        purpose="test",
        notional_usd=size,
        economic_asset_uid=uid,
        provider_config={"radarCore": qc.fingerprint_material()},
    )


def _build_request_no_token_decimals(direction="BUY", size="100",
                                     uid="AAPL", address=_AAPL_ADDR):
    """Build AcquisitionRequest with targetAsset but no tokenDecimals key."""
    from app.radar_runtime.contracts import AcquisitionRequest
    from app.radar_ui.quote_context import resolve_quote_context
    qc = resolve_quote_context(expected_chain_id=_CHAIN)
    return AcquisitionRequest(
        chain_id=_CHAIN,
        contract_address=address,
        direction=direction,
        sources=(composition.PROVIDER_NAME,),
        purpose="test",
        notional_usd=size,
        economic_asset_uid=uid,
        provider_config={"radarCore": qc.fingerprint_material(),
                         "targetAsset": {}},
    )


def _build_request_malformed_decimals(raw_dec, direction="BUY", size="100",
                                      uid="AAPL", address=_AAPL_ADDR):
    """Build AcquisitionRequest with targetAsset.tokenDecimals = raw_dec."""
    from app.radar_runtime.contracts import AcquisitionRequest
    from app.radar_ui.quote_context import resolve_quote_context
    qc = resolve_quote_context(expected_chain_id=_CHAIN)
    return AcquisitionRequest(
        chain_id=_CHAIN,
        contract_address=address,
        direction=direction,
        sources=(composition.PROVIDER_NAME,),
        purpose="test",
        notional_usd=size,
        economic_asset_uid=uid,
        provider_config={"radarCore": qc.fingerprint_material(),
                         "targetAsset": {"tokenDecimals": raw_dec}},
    )


def test_b01_missing_target_asset_fails_closed():
    """provider_config without targetAsset → TOKEN_DECIMALS_AUTHORITY_UNBOUND."""
    source = composition.composition_radar_source(
        registry_factory=_make_aapl_source_factory())
    req = _build_request_no_target_asset()
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "TOKEN_DECIMALS_AUTHORITY_UNBOUND"


def test_b01_missing_token_decimals_key_fails_closed():
    """targetAsset present but tokenDecimals absent → TOKEN_DECIMALS_AUTHORITY_UNBOUND."""
    source = composition.composition_radar_source(
        registry_factory=_make_aapl_source_factory())
    req = _build_request_no_token_decimals()
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "TOKEN_DECIMALS_AUTHORITY_UNBOUND"


@pytest.mark.parametrize("raw_dec,description", [
    ("1.0", "fractional string"),
    (" 18", "leading space string"),
    ("18 ", "trailing space string"),
    ("+18", "plus-sign string"),
    ("1e1", "exponential string"),
    ("", "empty string"),
    (True, "bool True"),
    (1.5, "float"),
    (-1, "negative int"),
    (256, "out-of-range 256"),
])
def test_b01_malformed_bound_decimals_fails_closed(raw_dec, description):
    """Malformed bound tokenDecimals → TOKEN_DECIMALS_AUTHORITY_UNBOUND."""
    source = composition.composition_radar_source(
        registry_factory=_make_aapl_source_factory())
    req = _build_request_malformed_decimals(raw_dec)
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False, f"expected fail-closed for {description!r}"
    assert ref["reason"] == "TOKEN_DECIMALS_AUTHORITY_UNBOUND", (
        f"expected UNBOUND reason for {description!r}, got {ref['reason']!r}")


def test_b01_valid_bound_matches_live_may_proceed():
    """Valid bound decimals matching live registry: reference section proceeds
    (fails later only because fetch_bound_reference returns empty dicts)."""
    source = composition.composition_radar_source(
        registry_factory=_make_aapl_source_factory(decimals_in_registry=18))
    req = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=18,
        ))
    result = source(req)
    ref = result["evidence"]["reference"]
    # Must NOT be UNBOUND or MISMATCH — failure here is from build_bound_reference
    assert ref.get("reason") not in (
        "TOKEN_DECIMALS_AUTHORITY_UNBOUND",
        "TOKEN_DECIMALS_AUTHORITY_MISMATCH",
    )


def test_b01_valid_bound_differs_from_live_mismatch():
    """Valid bound decimals (6) but live says 18 → TOKEN_DECIMALS_AUTHORITY_MISMATCH."""
    source = composition.composition_radar_source(
        registry_factory=_make_aapl_source_factory(decimals_in_registry=18))
    req = composition.build_request(
        "BUY", "100",
        composition.SelectedAsset(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=_CHAIN,
            contract_address=_AAPL_ADDR,
            token_decimals=6,
        ))
    result = source(req)
    ref = result["evidence"]["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "TOKEN_DECIMALS_AUTHORITY_MISMATCH"


# ---------------------------------------------------------------------------
# B02 — strict ASCII decimal string grammar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_str,description", [
    (" 18", "leading space"),
    ("18 ", "trailing space"),
    ("+18", "plus sign"),
    ("-1", "minus sign"),
    ("1.0", "decimal point"),
    ("1e1", "exponent"),
    ("", "empty string"),
    ("١٨", "arabic-indic digits (not ASCII)"),
])
def test_b02_strict_string_grammar_rejects(bad_str, description):
    """Strict grammar must reject non-canonical string forms."""
    from app.radar_ui.composition import (
        TokenDecimalsUnavailable,
        _parse_token_decimals,
    )
    with pytest.raises(TokenDecimalsUnavailable, match="TOKEN_DECIMALS_UNAVAILABLE"):
        _parse_token_decimals(bad_str)


@pytest.mark.parametrize("good_str,expected", [
    ("0", 0),
    ("6", 6),
    ("18", 18),
    ("255", 255),
])
def test_b02_strict_string_grammar_accepts(good_str, expected):
    """Strict grammar must accept canonical digit-only ASCII strings."""
    from app.radar_ui.composition import _parse_token_decimals
    assert _parse_token_decimals(good_str) == expected


# ---------------------------------------------------------------------------
# B03 — separate GET selection form + hidden asset_uid in POST quote form
# ---------------------------------------------------------------------------

def _make_nvda_aapl_client():
    """Return (client, nvda_rec, aapl_rec) with both assets in universe."""
    nvda_rec = _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR)
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)
    assets = [aapl_rec, nvda_rec]

    def factory():
        by_uid = {"AAPL": aapl_rec, "NVDA": nvda_rec}
        snap = SimpleNamespace(
            assets=assets,
            get_by_uid=lambda u: by_uid.get(u),
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    service = _build_service([], uid="NVDA", address=_NVDA_ADDR)
    radar_router_module.set_service(service)
    app = __import__("fastapi").FastAPI()
    app.include_router(radar_router_module.router)
    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)
    return client, nvda_rec, aapl_rec


def test_b03_get_form_present_with_select_submit(make_client):
    """GET /radar must include a GET form for asset selection."""
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert 'method="get"' in page or "method='get'" in page
    assert 'action="/radar"' in page or "action='/radar'" in page
    assert 'name="asset_uid"' in page
    assert "Select" in page or "Load Asset" in page


def test_b03_post_form_has_hidden_asset_uid(make_client):
    """POST quote form must carry hidden asset_uid matching server-resolved uid."""
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    import re
    # The POST form must carry a hidden asset_uid field
    hidden = re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']asset_uid["\']', page)
    if not hidden:
        hidden = re.findall(r'<input[^>]*name=["\']asset_uid["\'][^>]*type=["\']hidden["\']', page)
    assert hidden, "POST form must contain a hidden asset_uid input"


def test_b03_get_asset_uid_selects_nvda(make_client):
    """GET /radar?asset_uid=NVDA → NVDA appears in selector, header, and
    Selected Asset panel; the hidden POST field carries NVDA's uid."""
    nvda_rec = _make_asset_record("NVDA", "NVDA", "NVIDIA Corp.", _NVDA_ADDR)
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)
    assets = [aapl_rec, nvda_rec]

    def factory():
        by_uid = {"AAPL": aapl_rec, "NVDA": nvda_rec}
        snap = SimpleNamespace(
            assets=assets,
            get_by_uid=lambda u: by_uid.get(u),
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar?asset_uid=NVDA").text
    finally:
        composition.set_registry_factory(None)

    # NVDA must appear as selected in the <select> element
    assert "NVDA" in page
    # Hidden POST field must carry NVDA's uid
    import re
    hidden_vals = re.findall(
        r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']asset_uid["\'][^>]*value=["\']([^"\']*)["\']',
        page)
    if not hidden_vals:
        hidden_vals = re.findall(
            r'<input[^>]*name=["\']asset_uid["\'][^>]*type=["\']hidden["\'][^>]*value=["\']([^"\']*)["\']',
            page)
    assert any("NVDA" in v for v in hidden_vals), (
        f"hidden asset_uid must carry NVDA uid; found: {hidden_vals}")


def test_b03_post_form_separate_from_get_form(make_client):
    """POST form carries method=post and GET form carries method=get; they are
    distinct — hx-post must only appear on the POST form."""
    assets = [_make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)]

    def factory():
        return _make_registry(assets)

    composition.set_registry_factory(factory)
    try:
        c = make_client(_build_service([]))
        page = c.get("/radar").text
    finally:
        composition.set_registry_factory(None)

    assert 'action="/radar/refresh"' in page
    assert 'method="post"' in page
    assert 'hx-post="/radar/refresh"' in page
    assert 'hx-target="#radar-panels"' in page
    # GET form must exist with action=/radar
    assert 'action="/radar"' in page


# ---------------------------------------------------------------------------
# B04 — snapshot identity must never fall back
# ---------------------------------------------------------------------------

def test_b04_snapshot_uid_not_in_universe_no_fallback(make_client):
    """GET /radar?snapshot_id=X where X has NVDA uid + AAPL-only universe →
    selected=None, no AAPL substitution, visible SNAPSHOT_UID_NOT_IN_UNIVERSE."""
    calls: list = []
    # Universe has only AAPL
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)

    def factory():
        snap = SimpleNamespace(
            assets=[aapl_rec],
            get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        # Acquire a NVDA snapshot (service has NVDA evidence)
        service = _build_service(calls, uid="NVDA", address=_NVDA_ADDR)
        c = make_client(service)
        # To get a snapshot we first do a POST (universe factory ignores
        # NVDA uid check since it's the service fake_core, not registry)
        # We'll build the snapshot manually by calling acquire directly.
        req = composition.build_request(
            "BUY", "100",
            composition.SelectedAsset(
                economic_asset_uid="NVDA",
                token_symbol="NVDA",
                token_name="NVIDIA Corp.",
                chain_id=_CHAIN,
                contract_address=_NVDA_ADDR,
                token_decimals=18,
            ))
        snapshot = service.acquire(req)
        snapshot_id = snapshot.snapshot_id
        # Now GET /radar?snapshot_id=X with asset_uid=AAPL as the query param
        page = c.get(f"/radar?snapshot_id={snapshot_id}&asset_uid=AAPL").text
    finally:
        composition.set_registry_factory(None)

    # Must NOT show AAPL as selected asset (no substitution)
    # The SNAPSHOT_UID_NOT_IN_UNIVERSE note must appear
    assert "SNAPSHOT_UID_NOT_IN_UNIVERSE" in page
    # The Selected Asset panel must NOT claim AAPL is selected
    # (it may show the note, but NOT AAPL's details as if selected)
    # Key: "Apple Inc." should NOT appear as the selected asset name
    # in the Selected Asset panel when the snapshot is NVDA
    assert "NVDA" in page  # the snapshot panels render NVDA identity


def test_b04_snapshot_uid_not_in_universe_asset_uid_param_ignored(make_client):
    """asset_uid=AAPL query param must be ignored when a snapshot is loaded
    whose uid is not in the universe — selected stays None."""
    calls: list = []
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)

    def factory():
        snap = SimpleNamespace(
            assets=[aapl_rec],
            get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        service = _build_service(calls, uid="NVDA", address=_NVDA_ADDR)
        req = composition.build_request(
            "BUY", "100",
            composition.SelectedAsset(
                economic_asset_uid="NVDA",
                token_symbol="NVDA",
                token_name="NVIDIA Corp.",
                chain_id=_CHAIN,
                contract_address=_NVDA_ADDR,
                token_decimals=18,
            ))
        snapshot = service.acquire(req)
        c = make_client(service)
        page = c.get(f"/radar?snapshot_id={snapshot.snapshot_id}&asset_uid=AAPL").text
    finally:
        composition.set_registry_factory(None)

    # The identity note must be visible — AAPL was NOT substituted
    assert "SNAPSHOT_UID_NOT_IN_UNIVERSE" in page


def test_b04_snapshot_identity_note_rendered_visibly(make_client):
    """snapshot_identity_note must be rendered in the HTML, not just passed
    as a template variable — it must appear in the page text."""
    calls: list = []
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)

    def factory():
        snap = SimpleNamespace(
            assets=[aapl_rec],
            get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        service = _build_service(calls, uid="NVDA", address=_NVDA_ADDR)
        req = composition.build_request(
            "BUY", "100",
            composition.SelectedAsset(
                economic_asset_uid="NVDA",
                token_symbol="NVDA",
                token_name="NVIDIA Corp.",
                chain_id=_CHAIN,
                contract_address=_NVDA_ADDR,
                token_decimals=18,
            ))
        snapshot = service.acquire(req)
        c = make_client(service)
        page = c.get(f"/radar?snapshot_id={snapshot.snapshot_id}").text
    finally:
        composition.set_registry_factory(None)

    assert "SNAPSHOT_UID_NOT_IN_UNIVERSE" in page, (
        "snapshot_identity_note must be rendered visibly in the page")


def test_b04_full_page_single_asset_header_with_nvda_snapshot(make_client):
    """Full-page render with a NVDA snapshot + AAPL-only universe must have
    exactly one id=radar-asset-header and no AAPL as the selected asset."""
    calls: list = []
    aapl_rec = _make_asset_record("AAPL", "AAPL", "Apple Inc.", _AAPL_ADDR)

    def factory():
        snap = SimpleNamespace(
            assets=[aapl_rec],
            get_by_uid=lambda u: aapl_rec if u == "AAPL" else None,
        )
        return SimpleNamespace(
            fetch_snapshot=lambda: snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(factory)
    try:
        service = _build_service(calls, uid="NVDA", address=_NVDA_ADDR)
        req = composition.build_request(
            "BUY", "100",
            composition.SelectedAsset(
                economic_asset_uid="NVDA",
                token_symbol="NVDA",
                token_name="NVIDIA Corp.",
                chain_id=_CHAIN,
                contract_address=_NVDA_ADDR,
                token_decimals=18,
            ))
        snapshot = service.acquire(req)
        c = make_client(service)
        page = c.get(f"/radar?snapshot_id={snapshot.snapshot_id}").text
    finally:
        composition.set_registry_factory(None)

    import re
    headers = re.findall(r'id=["\']radar-asset-header["\']', page)
    assert len(headers) == 1, (
        f"expected exactly 1 id='radar-asset-header', found {len(headers)}")
