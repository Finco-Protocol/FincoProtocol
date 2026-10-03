"""PR #182 Correction B + post-#181 terminal/API integration gates."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.rwa_integrity.contracts import IdentityFlag
from app.rwa_integrity.read_model import build_underlying_integrity
from tests.test_rwa_integrity_correction_a import NOW, _entry, _registry


def _intel(states):
    return SimpleNamespace(
        representations=[
            SimpleNamespace(
                venue_id="robinhood-chain",
                instrument_id=e.contract_address,
                representation_type=e.instrument_type,
                current_state=state,
                latest_basis_bps=None,
            )
            for e, state in states
        ],
        cross_venue=None,
    )


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ({"price": "195.00", "state": "FRESH"}, "AVAILABLE"),
        ({"price": "195.00", "state": "AVAILABLE"}, "AVAILABLE"),
        ({"price": "195.00", "state": "STALE"}, "STALE"),
        ({"price": "195.00", "state": "UNAVAILABLE"}, "UNAVAILABLE"),
        ({"price": None, "state": "FRESH"}, "UNAVAILABLE"),
    ],
)
def test_reference_state_uses_canonical_state(monkeypatch, evidence, expected):
    monkeypatch.setattr(
        "app.rwa_integrity.read_model.build_tokenized_intelligence",
        lambda *a, **k: _intel([(_entry(), "UNAVAILABLE")]),
    )
    view = build_underlying_integrity(
        "NVDA", registry=_registry([_entry()]), store=object(), now=NOW,
        reference_evidence_reader=lambda symbol: evidence)
    assert view.reference_evidence_state == expected
    assert view.representations[0].reference_evidence_state == expected


def test_zero_active_has_no_false_single_dependency_flags():
    entry = _entry()
    registry = _registry([entry], quarantines=[{
        "network": entry.network,
        "contract_address": entry.contract_address,
        "classification": "impostor",
    }])
    view = build_underlying_integrity("NVDA", registry=registry, store=None, now=NOW)
    assert view.active_representation_count == 0
    for flag in (
        IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value,
        IdentityFlag.SINGLE_VENUE_DEPENDENCY.value,
        IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value,
        IdentityFlag.SINGLE_SOURCE_DEPENDENCY.value,
    ):
        assert flag not in view.dependency_flags


def test_one_active_has_exact_single_dependency_flags():
    view = build_underlying_integrity(
        "NVDA", registry=_registry([_entry()]), store=None, now=NOW)
    for flag in (
        IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value,
        IdentityFlag.SINGLE_VENUE_DEPENDENCY.value,
        IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value,
        IdentityFlag.SINGLE_SOURCE_DEPENDENCY.value,
    ):
        assert flag in view.dependency_flags


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (["AVAILABLE", "AVAILABLE"], "AVAILABLE"),
        (["AVAILABLE", "STALE"], "PARTIAL"),
        (["AVAILABLE", "UNAVAILABLE"], "PARTIAL"),
        (["STALE", "STALE"], "STALE"),
        (["UNAVAILABLE", "UNAVAILABLE"], "UNAVAILABLE"),
    ],
)
def test_market_coverage_preserves_stale(monkeypatch, states, expected):
    entries = [
        _entry(),
        _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network="ethereum", chain_id=1,
            contract_address="0x" + "22" * 20,
            source="xstocks-official-api",
            source_ref="xstocks-official-api#nvda"),
    ]
    monkeypatch.setattr(
        "app.rwa_integrity.read_model.build_tokenized_intelligence",
        lambda *a, **k: _intel(list(zip(entries, states))),
    )
    view = build_underlying_integrity(
        "NVDA", registry=_registry(entries), store=object(), now=NOW)
    assert view.market_evidence_coverage == expected


def _api_client(monkeypatch, tmp_path, *, allow_api):
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    from app.protocol.entitlement_evaluator import Decision
    from tests.test_unified_crypto_terminal_v1 import _patch_agent_a
    decision = Decision.ALLOW if allow_api else Decision.INACTIVE
    reason = "CRYPTO_API_ACTIVATED" if allow_api else "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"
    _patch_agent_a(monkeypatch, {"crypto.api": (decision, reason)})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_integrity_api_inactive_denies(monkeypatch, tmp_path):
    client = _api_client(monkeypatch, tmp_path, allow_api=False)
    response = client.get("/api/v1/crypto/tokenized/NVDA/integrity")
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_integrity_api_allow_is_sync_and_acquisition_free(monkeypatch, tmp_path):
    client = _api_client(monkeypatch, tmp_path, allow_api=True)

    import asyncio
    from app.api.v1.crypto_router import crypto_tokenized_integrity
    assert not asyncio.iscoroutinefunction(crypto_tokenized_integrity)

    response = client.get("/api/v1/crypto/tokenized/NVDA/integrity")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["resource"] == "tokenized.integrity"
    assert body["canonical_asset_id"] == "NVDA"
    assert body["as_of"] == body["data"]["generated_at"]
    assert body["data"]["attestation_evidence_state"] == "UNAVAILABLE"
    assert "trust_score" not in str(body).lower()
    for rep in body["data"]["representations"]:
        if rep["basis_evidence_state"] == "UNAVAILABLE":
            assert rep["basis_bps"] is None


def test_integrity_api_jsonifies_decimal_basis(monkeypatch, tmp_path):
    from decimal import Decimal
    client = _api_client(monkeypatch, tmp_path, allow_api=True)
    import app.crypto_terminal.integrity_read as integrity_read

    monkeypatch.setattr(
        integrity_read, "build_view",
        lambda *a, **k: SimpleNamespace(canonical_asset_id="NVDA"))
    monkeypatch.setattr(
        integrity_read, "as_data",
        lambda view: {"basis_bps": Decimal("12.5"), "missing": None})

    response = client.get("/api/v1/crypto/tokenized/NVDA/integrity")
    assert response.status_code == 200
    assert response.json()["data"]["basis_bps"] == 12.5
    assert response.json()["data"]["missing"] is None


def test_integrity_api_unknown_identity_typed_404(monkeypatch, tmp_path):
    client = _api_client(monkeypatch, tmp_path, allow_api=True)
    response = client.get("/api/v1/crypto/tokenized/ZZZZ/integrity")
    assert response.status_code == 404
    body = response.json()
    assert body["state"] == "UNKNOWN_IDENTITY"
    assert body["reason"] == "CANONICAL_ASSET_ID_UNKNOWN"
    assert body["data"] is None


def test_browser_detail_renders_integrity_without_new_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    from app.radar_ui.tokenized_router import router
    from types import SimpleNamespace
    monkeypatch.setattr(
        "app.auth.resolve_request_session",
        lambda request: SimpleNamespace(
            user_id="user-1", username="qa", login_at=None, session_type="user"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/radar/tokenized-markets/NVDA")
    assert response.status_code == 200
    assert 'data-testid="tmd-integrity"' in response.text
    assert "RWA Integrity" in response.text
    assert "trust score" in response.text.lower()


def test_failure_isolation_reference_reader_does_not_500():
    def broken(symbol):
        raise RuntimeError("reference authority unavailable")
    view = build_underlying_integrity(
        "NVDA", registry=_registry([_entry()]), store=None, now=NOW,
        reference_evidence_reader=broken)
    assert view.reference_evidence_state == "UNAVAILABLE"
    assert view.attestation_evidence_state == "UNAVAILABLE"


def test_integrity_source_has_no_score_holder_provider_or_execution_path():
    sources = "\n".join(
        open(path, encoding="utf-8").read().lower()
        for path in (
            "app/rwa_integrity/read_model.py",
            "app/rwa_integrity/contracts.py",
            "app/crypto_terminal/integrity_read.py",
        )
    )
    assert "trust_score" not in sources
    assert "holder_concentration" not in sources
    for forbidden in (
        "requests.", "httpx.", "urllib.request", "submit_order",
        "private_key", "sign_transaction", "custody(",
    ):
        assert forbidden not in sources
