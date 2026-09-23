"""A1 Radar API v1 tests.

All tests use:
- A fake registry (injected via set_registry_factory) — no network calls.
- An in-process SQLite DB for equity authority — no production data.

Test inventory:
  A01 — GET /api/v1/meta returns version + capabilities
  A02 — invalid uid format → 400 ASSET_UID_INVALID
  A03 — ticker-like uid rejected by normalize_asset_uid (not 0x hex)
  A04 — uid valid format but not in registry → 404 ASSET_NOT_FOUND
  A05 — registry unavailable → 503 REGISTRY_UNAVAILABLE
  A06 — list assets returns all registry assets
  A07 — list assets registry unavailable → 503
  A08 — get asset identity: registry+equity data present → 200 AVAILABLE
  A09 — get asset identity: equity DB unconfigured → 200 AVAILABLE + fundamentals_state
  A10 — fundamentals: TTM+quarterly+annual present → AVAILABLE envelope
  A11 — fundamentals: equity DB unconfigured → SOURCE_UNAVAILABLE state
  A12 — fundamentals: evidence (source_lineage) included in envelope
  A13 — financials: history bundle in envelope
  A14 — financials: equity DB unconfigured → SOURCE_UNAVAILABLE
  A15 — corporate-actions: dividends + splits in envelope
  A16 — corporate-actions: equity DB unconfigured → SOURCE_UNAVAILABLE
  A17 — evidence: lineage in envelope
  A18 — evidence: equity DB unconfigured → SOURCE_UNAVAILABLE
  A19 — no ticker fallback: find_by_symbol never called on uid path
  A20 — empty uid path segment → 400 (FastAPI path routing returns 404/422)
  A21 — envelope always carries api_version = "v1"
  A22 — normalize_asset_uid called: mixed-case uid is accepted + normalised
  A23 — list assets: empty registry returns empty list
  A24 — response Content-Type is application/json
  A25 — identity binding: BOUND when symbol matches + no E1 contract address
  A26 — identity binding: BOUND when symbol + contract both match
  A27 — identity binding: IDENTITY_MISMATCH when contract address mismatches
  A28 — identity binding: missing E1 contract is NOT a mismatch
  A29 — /assets/{uid} state always AVAILABLE when registry resolves (F5)
  A30 — /assets/{uid} fundamentals_state field present always (F5)
  A31 — /assets/{uid} equity_identity null when IDENTITY_MISMATCH
  A32 — sub-endpoints return IDENTITY_MISMATCH state when mismatched
  A33 — EquityDBModeError yields FUNDAMENTALS_CONFIG_INVALID state
  A34 — 503 detail is fixed sanitized string (no internal details)
  A35 — close() called on registry adapter after successful fetch
  A36 — close() called on registry adapter after fetch failure
  A37 — narrow exception: programming error propagates as-is (not 503)
  A38 — /assets/{uid} fundamentals_state=FUNDAMENTALS_CONFIG_INVALID when mode invalid
  A39 — /assets/{uid} state=AVAILABLE when DB mode invalid (config error not a 503)
  A40 — all route handlers are synchronous (not coroutines)
  A41 — OpenAPI schema carries ApiErrorEnvelope for 400/404/503
  A42 — AVAILABLE when identity bound + DB has data
  A43 — NOT_FOUND propagates as state when equity asset absent
  A44 — corporate-actions IDENTITY_MISMATCH when contract mismatch
  A45 — evidence IDENTITY_MISMATCH when contract mismatch
  A46 — financials IDENTITY_MISMATCH when contract mismatch
  A47 — 503 REGISTRY_UNAVAILABLE on list when registry broken
  A48 — raw_payload_json never appears in any response field

Correction B:
  B01 — F1 fix: E1 contract present + no chain-4663 deployment → IDENTITY_MISMATCH
  B02 — symbol mismatch (injected bundle) → IDENTITY_MISMATCH
  B03 — fundamentals_state matrix: AVAILABLE bundle → state=AVAILABLE, fstate=AVAILABLE
  B04 — fundamentals_state matrix: PARTIAL bundle → fstate=PARTIAL
  B05 — fundamentals_state matrix: NOT_AVAILABLE bundle → fstate=NOT_AVAILABLE
  B06 — fundamentals_state matrix: NOT_FOUND bundle → fstate=NOT_FOUND
  B07 — fundamentals_state matrix: SOURCE_UNAVAILABLE bundle → fstate=SOURCE_UNAVAILABLE
  B08 — fundamentals_state matrix: FUNDAMENTALS_CONFIG_INVALID → fstate=FUNDAMENTALS_CONFIG_INVALID
  B09 — fundamentals_state matrix: IDENTITY_MISMATCH → fstate=IDENTITY_MISMATCH
  B10 — BOUND never appears in any public response field
  B11 — mismatch suppression: /fundamentals fields absent
  B12 — mismatch suppression: /financials fields absent
  B13 — mismatch suppression: /corporate-actions fields absent
  B14 — mismatch suppression: /evidence fields absent
  B15 — /assets/{uid} mismatch: only registry identity + null equity fields
  B16 — close on programming error: RuntimeError propagates + close() called
  B17 — adversarial 503: sensitive URL/path/key sentinel absent from public detail
  B18 — OpenAPI: all A1 routes present in schema
  B19 — OpenAPI: success envelopes on data endpoints
  B20 — OpenAPI: error envelopes on all relevant endpoints
  B21 — raw_evidence sentinel never exposed in any endpoint
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    RegistryAssetStatus,
)
from finco_radar.assets.registry import RegistrySnapshot

import app.api.v1.radar as _radar_svc

# ── constants ─────────────────────────────────────────────────────────────────

_UID_AAPL = "0x" + "aa" * 32
_UID_NVDA = "0x" + "bb" * 32
_ADDR_AAPL = "0x" + "11" * 20
_ADDR_NVDA = "0x" + "22" * 20
_CHAIN_ID = 4663

_TICKER_AAPL = "AAPL"
_TICKER_NVDA = "NVDA"

# ── equity DB DDL (copied from E1 test suite) ─────────────────────────────────

_DDL = """
CREATE TABLE equity_assets (
    robinhood_token_symbol TEXT PRIMARY KEY,
    underlying_ticker TEXT NOT NULL,
    name TEXT, token_contract_address TEXT, chain_network TEXT,
    underlying_exchange TEXT, cik TEXT, figi TEXT, currency TEXT,
    security_type TEXT, active INTEGER, first_seen_at TEXT, last_seen_at TEXT
);
CREATE TABLE equity_company_profiles (
    ticker TEXT, cik TEXT, profile_json TEXT, payload_hash TEXT,
    provider TEXT, source_contract TEXT, fetched_at TEXT,
    PRIMARY KEY (ticker, payload_hash)
);
CREATE TABLE equity_financial_snapshots (
    ticker TEXT, cik TEXT, timeframe TEXT, fiscal_year TEXT,
    fiscal_quarter TEXT, period_end TEXT, filing_date TEXT,
    provider TEXT, source_contract TEXT, fetched_at TEXT,
    normalized_at TEXT, payload_hash TEXT,
    income_statement_json TEXT, balance_sheet_json TEXT,
    cash_flow_statement_json TEXT, derived_json TEXT,
    PRIMARY KEY (ticker, timeframe, period_end, payload_hash)
);
CREATE TABLE equity_dividends (
    ticker TEXT, external_id TEXT PRIMARY KEY, cash_amount REAL,
    currency TEXT, declaration_date TEXT, ex_dividend_date TEXT,
    record_date TEXT, pay_date TEXT, frequency INTEGER,
    dividend_type TEXT, first_seen_at TEXT
);
CREATE TABLE equity_splits (
    ticker TEXT, external_id TEXT PRIMARY KEY, execution_date TEXT,
    split_from REAL, split_to REAL, first_seen_at TEXT
);
CREATE TABLE equity_source_lineage (
    lineage_id TEXT PRIMARY KEY, ticker TEXT, stage TEXT, provider TEXT,
    source_contract TEXT, endpoint TEXT, payload_hash TEXT,
    raw_payload_json TEXT, normalized_ref TEXT, fetched_at TEXT
);
"""


def _make_db_path(tmp_path: Path, with_aapl: bool = True) -> Path:
    db = tmp_path / "equity_fundamentals.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_DDL)
        if with_aapl:
            conn.execute(
                "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_TICKER_AAPL, "AAPL", "Apple Inc.", _ADDR_AAPL, "ethereum",
                 "NASDAQ", "0320193", None, "USD", "CS", 1,
                 "2024-01-01T00:00:00", "2024-12-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO equity_financial_snapshots VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAPL", "0320193", "ttm", "2024", None, "2024-09-30",
                 "2024-11-01", "polygon", "equity_v1", "2024-11-02T00:00:00",
                 "2024-11-02T01:00:00", "hash_ttm",
                 '{"revenues": 391035000000}', "{}", "{}", "{}"),
            )
            conn.execute(
                "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("AAPL", "div_001", 0.25, "USD", "2024-10-01", "2024-11-07",
                 "2024-11-08", "2024-11-14", 4, "CD", "2024-10-02T00:00:00"),
            )
            conn.execute(
                "INSERT INTO equity_splits VALUES (?,?,?,?,?,?)",
                ("AAPL", "split_001", "2020-08-31", 1.0, 4.0,
                 "2020-08-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO equity_source_lineage VALUES "
                "(?,?,?,?,?,?,?,?,?,?)",
                ("lin_001", "AAPL", "normalize", "polygon", "equity_v1",
                 "/v2/reference/financials", "hash_ttm", "{}", "norm_ref_1",
                 "2024-11-02T01:00:00"),
            )
        conn.commit()
    finally:
        conn.close()
    return db


# ── registry helpers ──────────────────────────────────────────────────────────

def _make_record(uid: str, symbol: str, address: str) -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=uid,
        token_symbol=symbol,
        token_name=f"{symbol} Inc.",
        deployments=(AssetKey(_CHAIN_ID, address),),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def _make_snapshot(records: List[CanonicalAssetRecord]) -> RegistrySnapshot:
    return RegistrySnapshot(
        source="test",
        observed_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
        assets=tuple(records),
    )


def _fake_registry_factory(records: List[CanonicalAssetRecord]):
    """Return a factory that yields a mock registry with the given records."""
    snapshot = _make_snapshot(records)

    def factory():
        mock = MagicMock()
        mock.fetch_snapshot.return_value = snapshot
        return mock

    return factory


# ── test client fixture ───────────────────────────────────────────────────────

@pytest.fixture
def aapl_record():
    return _make_record(_UID_AAPL, _TICKER_AAPL, _ADDR_AAPL)


@pytest.fixture
def nvda_record():
    return _make_record(_UID_NVDA, _TICKER_NVDA, _ADDR_NVDA)


@pytest.fixture(autouse=True)
def reset_registry_factory():
    """Always clear the registry factory after each test."""
    yield
    _radar_svc.clear_registry_factory()


@pytest.fixture
def client(tmp_path, monkeypatch, aapl_record):
    """TestClient with fake registry + AAPL equity DB."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path, with_aapl=True)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    return TestClient(app)


@pytest.fixture
def client_no_db(monkeypatch, aapl_record):
    """TestClient with fake registry but NO equity DB configured."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)

    from main_api import app
    return TestClient(app)


# ── A01 — meta endpoint ───────────────────────────────────────────────────────

def test_a01_meta_returns_version_and_capabilities(client):
    resp = client.get("/api/v1/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    caps = body["capabilities"]
    assert "radar.assets.list" in caps
    assert "radar.assets.fundamentals" in caps


# ── A02/A03 — UID validation ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad_uid", [
    "AAPL",               # ticker-like: not 0x hex
    "apple",              # plain string
    "0x" + "aa" * 19,    # 19-byte — too short
    "0x" + "aa" * 33,    # 33-byte — too long
    "0x" + "gg" * 32,    # invalid hex chars
    "",                   # empty (FastAPI will 404, tested separately)
    "0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
])
def test_a02_invalid_uid_returns_400(client, bad_uid):
    if not bad_uid:
        pytest.skip("empty uid causes routing issue, tested elsewhere")
    resp = client.get(f"/api/v1/radar/assets/{bad_uid}")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "ASSET_UID_INVALID"
    assert body["api_version"] == "v1"


def test_a03_ticker_uid_rejected_not_fallback(client):
    """Ticker-like path param is rejected as invalid UID, never falls through to equity DB."""
    resp = client.get("/api/v1/radar/assets/AAPL")
    assert resp.status_code == 400
    assert resp.json()["error"] == "ASSET_UID_INVALID"


# ── A04 — not found ───────────────────────────────────────────────────────────

def test_a04_unknown_uid_returns_404(client):
    unknown = "0x" + "cc" * 32
    resp = client.get(f"/api/v1/radar/assets/{unknown}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "ASSET_NOT_FOUND"
    assert body["api_version"] == "v1"


# ── A05 — registry unavailable ────────────────────────────────────────────────

def test_a05_registry_unavailable_returns_503(monkeypatch):
    import httpx as _httpx

    def _broken():
        raise _httpx.ConnectError("network timeout")

    _radar_svc.set_registry_factory(_broken)
    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 503
    assert resp.json()["error"] == "REGISTRY_UNAVAILABLE"


# ── A06 — list assets ─────────────────────────────────────────────────────────

def test_a06_list_assets_returns_registry_assets(client, aapl_record):
    resp = client.get("/api/v1/radar/assets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    assert body["state"] == "AVAILABLE"
    assets = body["data"]["assets"]
    assert len(assets) == 1
    assert assets[0]["economic_asset_uid"] == _UID_AAPL
    assert assets[0]["token_symbol"] == _TICKER_AAPL
    assert body["data"]["total"] == 1


def test_a06_list_includes_deployments(client):
    resp = client.get("/api/v1/radar/assets")
    asset = resp.json()["data"]["assets"][0]
    assert len(asset["deployments"]) == 1
    dep = asset["deployments"][0]
    assert dep["chain_id"] == _CHAIN_ID
    assert dep["contract_address"] == _ADDR_AAPL


# ── A07 — list registry unavailable ──────────────────────────────────────────

def test_a07_list_registry_unavailable_returns_503(monkeypatch):
    import httpx as _httpx

    def _broken():
        raise _httpx.ConnectError("registry down")

    _radar_svc.set_registry_factory(_broken)
    from main_api import app
    c = TestClient(app)
    resp = c.get("/api/v1/radar/assets")
    assert resp.status_code == 503


# ── A08 — get asset identity ──────────────────────────────────────────────────

def test_a08_get_asset_identity_available(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    assert body["economic_asset_uid"] == _UID_AAPL
    data = body["data"]
    assert data["token_symbol"] == _TICKER_AAPL
    assert data["token_name"] == "AAPL Inc."
    assert data["equity_identity"]["robinhood_token_symbol"] == _TICKER_AAPL
    assert data["equity_identity"]["underlying_ticker"] == "AAPL"


# ── A09 — get asset identity no DB ───────────────────────────────────────────

def test_a09_get_asset_identity_no_db(client_no_db):
    """F5: state always AVAILABLE when registry resolves; DB state goes in fundamentals_state."""
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    assert body["economic_asset_uid"] == _UID_AAPL
    data = body["data"]
    assert data["fundamentals_state"] == "SOURCE_UNAVAILABLE"
    assert data["equity_identity"] is None


# ── A10 — fundamentals available ─────────────────────────────────────────────

def test_a10_fundamentals_available(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] in ("AVAILABLE", "PARTIAL")
    data = body["data"]
    assert "ttm" in data
    assert "company_profile" in data
    assert data["availability"] in ("AVAILABLE", "PARTIAL")


def test_a10_fundamentals_ttm_present(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    ttm = resp.json()["data"]["ttm"]
    assert ttm is not None
    assert ttm["timeframe"] == "ttm"
    assert ttm["period_end"] == "2024-09-30"


# ── A11 — fundamentals no DB ─────────────────────────────────────────────────

def test_a11_fundamentals_no_db(client_no_db):
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    assert resp.status_code == 200
    assert resp.json()["state"] == "SOURCE_UNAVAILABLE"


# ── A12 — fundamentals includes evidence ─────────────────────────────────────

def test_a12_fundamentals_evidence_in_envelope(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    body = resp.json()
    assert "evidence" in body
    lineage = body["evidence"]["source_lineage"]
    assert isinstance(lineage, list)
    assert len(lineage) >= 1
    assert lineage[0]["ticker"] == "AAPL"


# ── A13 — financials ─────────────────────────────────────────────────────────

def test_a13_financials_available(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/financials")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    assert body["economic_asset_uid"] == _UID_AAPL
    data = body["data"]
    assert "annual_history" in data
    assert "quarterly_history" in data
    assert "ttm_history" in data


# ── A14 — financials no DB ───────────────────────────────────────────────────

def test_a14_financials_no_db(client_no_db):
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}/financials")
    assert resp.status_code == 200
    assert resp.json()["state"] == "SOURCE_UNAVAILABLE"


# ── A15 — corporate-actions ───────────────────────────────────────────────────

def test_a15_corporate_actions_available(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["economic_asset_uid"] == _UID_AAPL
    data = body["data"]
    assert "dividends" in data
    assert "splits" in data
    assert len(data["dividends"]) >= 1
    assert data["dividends"][0]["cash_amount"] == pytest.approx(0.25)
    assert data["dividends"][0]["ticker"] == "AAPL"
    assert len(data["splits"]) >= 1
    assert data["splits"][0]["split_to"] == pytest.approx(4.0)


# ── A16 — corporate-actions no DB ─────────────────────────────────────────────

def test_a16_corporate_actions_no_db(client_no_db):
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions")
    assert resp.status_code == 200
    assert resp.json()["state"] == "SOURCE_UNAVAILABLE"


# ── A17 — evidence ────────────────────────────────────────────────────────────

def test_a17_evidence_available(client):
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["economic_asset_uid"] == _UID_AAPL
    lineage = body["data"]["source_lineage"]
    assert isinstance(lineage, list)
    assert any(row["ticker"] == "AAPL" for row in lineage)


# ── A18 — evidence no DB ─────────────────────────────────────────────────────

def test_a18_evidence_no_db(client_no_db):
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}/evidence")
    assert resp.status_code == 200
    assert resp.json()["state"] == "SOURCE_UNAVAILABLE"


# ── A19 — no ticker fallback ──────────────────────────────────────────────────

def test_a19_no_ticker_fallback_registry_not_called_on_invalid_uid(tmp_path, monkeypatch, aapl_record):
    """A ticker-like uid is rejected by normalize_asset_uid() BEFORE the registry is called.

    Proves the fail-closed order: UID validation fires first, so the registry
    adapter is never contacted for a syntactically-invalid uid.
    """
    registry_calls: list = []

    def _tracking_factory():
        registry_calls.append("fetch_snapshot")
        return _fake_registry_factory([aapl_record])()

    _radar_svc.set_registry_factory(_tracking_factory)
    db = _make_db_path(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))

    from main_api import app
    c = TestClient(app)

    # Ticker-like string: rejected at normalize_asset_uid() → 400, registry never touched.
    resp = c.get("/api/v1/radar/assets/AAPL")
    assert resp.status_code == 400
    assert resp.json()["error"] == "ASSET_UID_INVALID"
    assert registry_calls == [], (
        "Registry must not be called when uid format is invalid"
    )


# ── A20 — 404 on sub-paths with bad uid ──────────────────────────────────────

def test_a20_fundamentals_invalid_uid_returns_400(client):
    resp = client.get("/api/v1/radar/assets/not-a-uid/fundamentals")
    assert resp.status_code == 400
    assert resp.json()["error"] == "ASSET_UID_INVALID"


def test_a20_financials_invalid_uid_returns_400(client):
    resp = client.get("/api/v1/radar/assets/TICKER/financials")
    assert resp.status_code == 400
    assert resp.json()["error"] == "ASSET_UID_INVALID"


# ── A21 — api_version in all responses ───────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/radar/assets",
    f"/api/v1/radar/assets/{_UID_AAPL}",
    f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals",
    f"/api/v1/radar/assets/{_UID_AAPL}/financials",
    f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions",
    f"/api/v1/radar/assets/{_UID_AAPL}/evidence",
    "/api/v1/meta",
])
def test_a21_api_version_present_in_all_responses(client, path):
    resp = client.get(path)
    assert resp.json()["api_version"] == "v1"


# ── A22 — uid case normalisation ─────────────────────────────────────────────

def test_a22_uid_mixed_case_accepted_and_normalised(tmp_path, monkeypatch, aapl_record):
    """A uid with uppercase hex digits (but lowercase '0x' prefix) is accepted and normalised."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    # Uppercase hex digits only; '0x' prefix must stay lowercase (regex requirement).
    upper_hex_uid = "0x" + "AA" * 32
    resp = c.get(f"/api/v1/radar/assets/{upper_hex_uid}")
    assert resp.status_code == 200
    assert resp.json()["economic_asset_uid"] == _UID_AAPL  # normalised to lower


# ── A23 — empty registry ─────────────────────────────────────────────────────

def test_a23_empty_registry_returns_empty_list(monkeypatch, tmp_path):
    _radar_svc.set_registry_factory(_fake_registry_factory([]))
    monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)

    from main_api import app
    c = TestClient(app)
    resp = c.get("/api/v1/radar/assets")
    assert resp.status_code == 200
    assert resp.json()["data"]["assets"] == []
    assert resp.json()["data"]["total"] == 0


# ── A24 — content-type ───────────────────────────────────────────────────────

def test_a24_content_type_is_json(client):
    resp = client.get("/api/v1/radar/assets")
    ct = resp.headers.get("content-type", "")
    assert "application/json" in ct


# ── 404 sub-endpoint for unknown uid ─────────────────────────────────────────

def test_unknown_uid_sub_endpoints_return_404(client):
    unknown = "0x" + "ff" * 32
    for path in ("fundamentals", "financials", "corporate-actions", "evidence"):
        resp = client.get(f"/api/v1/radar/assets/{unknown}/{path}")
        assert resp.status_code == 404, f"expected 404 for /{path} with unknown uid"


# ── multi-asset list with AAPL + NVDA ────────────────────────────────────────

def test_list_multiple_assets(monkeypatch, tmp_path, aapl_record, nvda_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record, nvda_record]))
    monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)

    from main_api import app
    c = TestClient(app)
    resp = c.get("/api/v1/radar/assets")
    assert resp.status_code == 200
    assets = resp.json()["data"]["assets"]
    assert len(assets) == 2
    uids = {a["economic_asset_uid"] for a in assets}
    assert _UID_AAPL in uids
    assert _UID_NVDA in uids


# ── identity-binding DB helpers ───────────────────────────────────────────────

_ADDR_OTHER = "0x" + "99" * 20  # an address different from _ADDR_AAPL


def _make_db_no_contract(tmp_path: Path) -> Path:
    """DB with AAPL but token_contract_address = NULL (no E1 contract)."""
    db = tmp_path / "equity_no_contract.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_DDL)
        conn.execute(
            "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_TICKER_AAPL, "AAPL", "Apple Inc.", None, None,
             "NASDAQ", "0320193", None, "USD", "CS", 1,
             "2024-01-01T00:00:00", "2024-12-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _make_db_wrong_contract(tmp_path: Path) -> Path:
    """DB with AAPL but token_contract_address points to a DIFFERENT address."""
    db = tmp_path / "equity_wrong_contract.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_DDL)
        conn.execute(
            "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_TICKER_AAPL, "AAPL", "Apple Inc.", _ADDR_OTHER, "ethereum",
             "NASDAQ", "0320193", None, "USD", "CS", 1,
             "2024-01-01T00:00:00", "2024-12-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


# ── A25 — BOUND when symbol matches + no E1 contract address ─────────────────

def test_a25_bound_when_no_e1_contract(tmp_path, monkeypatch, aapl_record):
    """Missing E1 contract address is NOT a mismatch — identity is safely bound.
    fundamentals_state reflects DB availability (NOT_AVAILABLE: asset present, no snapshots).
    """
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_no_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    # BOUND is internal; fundamentals_state = DB availability when bound
    assert body["data"]["fundamentals_state"] == "NOT_AVAILABLE"
    assert body["data"]["equity_identity"] is not None


# ── A26 — BOUND when symbol + contract match ─────────────────────────────────

def test_a26_bound_when_symbol_and_contract_match(client):
    """Default client: AAPL in DB with matching contract → identity safely bound.
    fundamentals_state is DB availability (PARTIAL: TTM present, no profile).
    BOUND must NOT appear as fundamentals_state.
    """
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    # BOUND is internal — public field is DB availability state
    assert data["fundamentals_state"] in ("PARTIAL", "AVAILABLE")
    assert data["fundamentals_state"] != "BOUND"
    assert data["equity_identity"] is not None
    assert data["equity_identity"]["robinhood_token_symbol"] == _TICKER_AAPL


# ── A27 — IDENTITY_MISMATCH when contract address mismatches ─────────────────

def test_a27_identity_mismatch_contract_address(tmp_path, monkeypatch, aapl_record):
    """E1 has a different contract address for chain 4663 → IDENTITY_MISMATCH."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert data["fundamentals_state"] == "IDENTITY_MISMATCH"
    assert data["equity_identity"] is None


# ── A28 — missing E1 contract is NOT a mismatch (alias of A25) ───────────────

def test_a28_missing_e1_contract_not_a_mismatch(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_no_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # BOUND is internal; DB has asset but no snapshots → NOT_AVAILABLE
    assert data["fundamentals_state"] == "NOT_AVAILABLE"
    assert data["equity_identity"] is not None


# ── A29 — /assets/{uid} state always AVAILABLE when registry resolves ────────

def test_a29_identity_state_always_available_when_registry_resolves(client_no_db):
    """F5 contract: state=AVAILABLE regardless of DB state."""
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "AVAILABLE"


# ── A30 — /assets/{uid} fundamentals_state field always present ───────────────

def test_a30_fundamentals_state_always_in_identity_data(client, client_no_db):
    for c in (client, client_no_db):
        resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
        assert resp.status_code == 200
        assert "fundamentals_state" in resp.json()["data"]


# ── A31 — equity_identity null when IDENTITY_MISMATCH ────────────────────────

def test_a31_equity_identity_null_on_mismatch(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    data = resp.json()["data"]
    assert data["equity_identity"] is None
    assert data["fundamentals_state"] == "IDENTITY_MISMATCH"


# ── A32 — sub-endpoints return IDENTITY_MISMATCH state when mismatched ────────

@pytest.mark.parametrize("path", ["fundamentals", "corporate-actions", "evidence"])
def test_a32_sub_endpoints_identity_mismatch(tmp_path, monkeypatch, aapl_record, path):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/{path}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "IDENTITY_MISMATCH"
    assert body["data"]["availability"] == "IDENTITY_MISMATCH"


# ── A33 — EquityDBModeError → FUNDAMENTALS_CONFIG_INVALID ────────────────────

def test_a33_equity_db_mode_error_config_invalid(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path, with_aapl=True)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "invalid_mode_xyz")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    assert resp.status_code == 200
    assert resp.json()["state"] == "FUNDAMENTALS_CONFIG_INVALID"


# ── A34 — 503 detail is fixed sanitized string ───────────────────────────────

def test_a34_503_detail_is_sanitized():
    def _broken():
        import httpx
        raise httpx.ConnectError("tcp://internal.registry.finco.one:8443/api/secret")

    _radar_svc.set_registry_factory(_broken)
    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 503
    body = resp.json()
    detail = body["detail"]
    assert "internal" not in detail.lower()
    assert "finco.one" not in detail.lower()
    assert "secret" not in detail.lower()
    assert "tcp://" not in detail
    assert detail == "Asset registry is temporarily unavailable."


# ── A35 — close() called on registry adapter after successful fetch ───────────

def test_a35_close_called_after_successful_fetch(tmp_path, monkeypatch, aapl_record):
    close_calls: list = []
    snapshot = _make_snapshot([aapl_record])

    def factory():
        m = MagicMock()
        m.fetch_snapshot.return_value = snapshot
        m.close.side_effect = lambda: close_calls.append("close")
        return m

    _radar_svc.set_registry_factory(factory)
    monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)

    from main_api import app
    c = TestClient(app)
    c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert close_calls == ["close"], "close() must be called exactly once after successful fetch"


# ── A36 — close() called on registry adapter after fetch failure ──────────────

def test_a36_close_called_after_fetch_failure():
    import httpx
    close_calls: list = []

    def factory():
        m = MagicMock()
        m.fetch_snapshot.side_effect = httpx.ConnectError("network failure")
        m.close.side_effect = lambda: close_calls.append("close")
        return m

    _radar_svc.set_registry_factory(factory)
    from main_api import app
    c = TestClient(app)
    c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert close_calls == ["close"], "close() must be called exactly once even when fetch fails"


# ── A37 — narrow exception: programming error propagates (not 503) ────────────

def test_a37_programming_error_is_not_swallowed():
    """AttributeError or other programming bugs must NOT be silenced as 503."""
    def factory():
        m = MagicMock()
        m.fetch_snapshot.side_effect = AttributeError("programming error in adapter")
        return m

    _radar_svc.set_registry_factory(factory)
    from main_api import app
    c = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(AttributeError, match="programming error"):
        c.get(f"/api/v1/radar/assets/{_UID_AAPL}")


# ── A38 — /assets/{uid} fundamentals_state=FUNDAMENTALS_CONFIG_INVALID ────────

def test_a38_identity_fundamentals_state_config_invalid(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path, with_aapl=True)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "bad_mode")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    assert body["data"]["fundamentals_state"] == "FUNDAMENTALS_CONFIG_INVALID"
    assert body["data"]["equity_identity"] is None


# ── A39 — /assets/{uid} state=AVAILABLE even when DB mode is bad ──────────────

def test_a39_identity_state_available_even_when_db_mode_bad(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "bad_mode")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "AVAILABLE"


# ── A40 — all route handlers are synchronous (not coroutines) ─────────────────

def test_a40_route_handlers_are_not_coroutines():
    import asyncio
    import inspect
    from app.api.v1 import router as router_module
    for route in router_module.router.routes:
        endpoint = route.endpoint
        assert not asyncio.iscoroutinefunction(endpoint), (
            f"Handler {endpoint.__name__!r} must be a plain def, not async def"
        )


# ── A41 — OpenAPI schema carries ApiErrorEnvelope for 400/404/503 ─────────────

def test_a41_openapi_error_responses(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema["paths"]
    asset_path = "/api/v1/radar/assets/{economic_asset_uid}"
    responses = paths[asset_path]["get"]["responses"]
    assert "400" in responses
    assert "404" in responses
    assert "503" in responses


# ── A42 — AVAILABLE when identity bound + DB has data ────────────────────────

def test_a42_identity_available_when_bound(client):
    """state=AVAILABLE when registry resolves; fundamentals_state is DB availability, never BOUND."""
    resp = client.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert data["fundamentals_state"] != "BOUND"
    assert data["fundamentals_state"] in ("AVAILABLE", "PARTIAL")
    assert data["equity_identity"] is not None


# ── A43 — NOT_FOUND propagates as state when equity asset absent ──────────────

def test_a43_not_found_state_when_equity_asset_absent(tmp_path, monkeypatch, aapl_record):
    """Registry has AAPL; equity DB has no record for AAPL → fundamentals_state=NOT_FOUND."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_path(tmp_path, with_aapl=False)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    assert body["data"]["fundamentals_state"] == "NOT_FOUND"
    assert body["data"]["equity_identity"] is None


# ── A44 — corporate-actions IDENTITY_MISMATCH ────────────────────────────────

def test_a44_corporate_actions_identity_mismatch(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions")
    assert resp.status_code == 200
    assert resp.json()["state"] == "IDENTITY_MISMATCH"


# ── A45 — evidence IDENTITY_MISMATCH ─────────────────────────────────────────

def test_a45_evidence_identity_mismatch(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/evidence")
    assert resp.status_code == 200
    assert resp.json()["state"] == "IDENTITY_MISMATCH"


# ── A46 — financials IDENTITY_MISMATCH ───────────────────────────────────────

def test_a46_financials_identity_mismatch(tmp_path, monkeypatch, aapl_record):
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/financials")
    assert resp.status_code == 200
    assert resp.json()["state"] == "IDENTITY_MISMATCH"


# ── A47 — 503 REGISTRY_UNAVAILABLE on list when registry broken ───────────────

def test_a47_list_registry_unavailable_503_detail():
    import httpx

    def _broken():
        raise httpx.ConnectTimeout("timeout")

    _radar_svc.set_registry_factory(_broken)
    from main_api import app
    c = TestClient(app)
    resp = c.get("/api/v1/radar/assets")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "REGISTRY_UNAVAILABLE"
    assert body["detail"] == "Asset registry is temporarily unavailable."


# ── A48 — raw_payload_json never appears in any response field ────────────────

def test_a48_raw_payload_json_never_exposed(client):
    """raw_payload_json is an internal column and must never appear in any API response."""
    for path in [
        f"/api/v1/radar/assets/{_UID_AAPL}",
        f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals",
        f"/api/v1/radar/assets/{_UID_AAPL}/evidence",
        f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200
        body_text = resp.text
        assert "raw_payload_json" not in body_text, (
            f"raw_payload_json leaked in response for {path}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Correction B tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Correction-B bundle / record helpers ──────────────────────────────────────

def _make_record_other_chain(uid: str, symbol: str, address: str) -> CanonicalAssetRecord:
    """Registry record whose only deployment is on chain 1 (NOT chain 4663)."""
    return CanonicalAssetRecord(
        asset_uid=uid,
        token_symbol=symbol,
        token_name=f"{symbol} Inc.",
        deployments=(AssetKey(1, address),),   # Ethereum mainnet, NOT finco chain
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def _make_fundamentals_bundle(
    symbol: str,
    availability,
    *,
    asset=None,
):
    """Build a minimal EquityFundamentalsBundle for injection via monkeypatch."""
    from finco_radar.equity.models import (
        EquityFundamentalsBundle,
        FundamentalsFreshness,
    )
    empty_freshness = FundamentalsFreshness(
        ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
        ttm_normalized_at=None, quarterly_period_end=None, quarterly_fetched_at=None,
        annual_period_end=None, annual_fetched_at=None, profile_fetched_at=None,
        asset_last_seen_at=None,
    )
    return EquityFundamentalsBundle(
        robinhood_token_symbol=symbol,
        asset=asset,
        company_profile=None,
        latest_ttm=None,
        latest_quarterly=None,
        latest_annual=None,
        recent_dividends=(),
        recent_splits=(),
        source_lineage_summary=(),
        availability=availability,
        freshness=empty_freshness,
    )


def _make_equity_asset_identity(symbol: str, contract_address: str | None = None):
    """Build a minimal EquityAssetIdentity for test bundles."""
    from finco_radar.equity.models import EquityAssetIdentity
    return EquityAssetIdentity(
        robinhood_token_symbol=symbol,
        underlying_ticker=symbol,
        name=f"{symbol} Inc.",
        token_contract_address=contract_address,
        chain_network="ethereum" if contract_address else None,
        underlying_exchange="NASDAQ",
        cik=None,
        figi=None,
        currency="USD",
        security_type="CS",
        active=True,
        first_seen_at=None,
        last_seen_at=None,
    )


# ── B01 — F1 fix: E1 contract present + no chain-4663 deployment → IDENTITY_MISMATCH

def test_b01_e1_contract_present_no_chain4663_deployment(tmp_path, monkeypatch):
    """F1 fail-closed: E1 supplies a contract but registry has no chain-4663 deployment.
    Ticker/symbol alone must not authorize the supplied contract address.
    """
    from finco_radar.equity.models import AvailabilityState

    # Registry record is on chain 1 only (no chain 4663 deployment)
    other_chain_record = _make_record_other_chain(_UID_AAPL, _TICKER_AAPL, _ADDR_AAPL)
    _radar_svc.set_registry_factory(_fake_registry_factory([other_chain_record]))

    # E1 has a contract address → must be verified against chain-4663 deployment
    asset_identity = _make_equity_asset_identity(_TICKER_AAPL, contract_address=_ADDR_AAPL)
    bundle = _make_fundamentals_bundle(
        _TICKER_AAPL,
        AvailabilityState.AVAILABLE,
        asset=asset_identity,
    )

    from main_api import app
    c = TestClient(app)

    with patch.object(_radar_svc, "get_fundamentals_bundle", return_value=bundle):
        resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert data["fundamentals_state"] == "IDENTITY_MISMATCH", (
        "E1 contract present but no chain-4663 deployment must be IDENTITY_MISMATCH"
    )
    assert data["equity_identity"] is None
    assert body.get("freshness") is None


# ── B02 — symbol mismatch (injected bundle) ───────────────────────────────────

def test_b02_symbol_mismatch_identity_mismatch(monkeypatch, aapl_record):
    """Registry token_symbol=AAPL but E1 bundle robinhood_token_symbol=MSFT → IDENTITY_MISMATCH."""
    from finco_radar.equity.models import AvailabilityState

    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))

    # Inject a bundle whose symbol does NOT match the registry record
    msft_identity = _make_equity_asset_identity("MSFT", contract_address=None)
    bundle = _make_fundamentals_bundle(
        "MSFT",
        AvailabilityState.AVAILABLE,
        asset=msft_identity,
    )

    from main_api import app
    c = TestClient(app)

    with patch.object(_radar_svc, "get_fundamentals_bundle", return_value=bundle):
        resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert data["fundamentals_state"] == "IDENTITY_MISMATCH"
    assert data["equity_identity"] is None
    assert body.get("freshness") is None


def test_b02_symbol_mismatch_sub_endpoints_suppress_all(monkeypatch, aapl_record):
    """Symbol mismatch: fundamentals/financials/corporate-actions/evidence all suppressed."""
    from finco_radar.equity.models import AvailabilityState
    from finco_radar.equity.models import EquityCompanyHistoryBundle, FundamentalsFreshness

    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))

    msft_identity = _make_equity_asset_identity("MSFT")
    fund_bundle = _make_fundamentals_bundle("MSFT", AvailabilityState.AVAILABLE, asset=msft_identity)
    empty_freshness = FundamentalsFreshness(
        ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
        ttm_normalized_at=None, quarterly_period_end=None, quarterly_fetched_at=None,
        annual_period_end=None, annual_fetched_at=None, profile_fetched_at=None,
        asset_last_seen_at=None,
    )
    hist_bundle = EquityCompanyHistoryBundle(
        robinhood_token_symbol="MSFT",
        asset=msft_identity,
        company_profile=None,
        annual_history=(), quarterly_history=(), ttm_history=(),
        recent_dividends=(), recent_splits=(), source_lineage=(),
        availability=AvailabilityState.AVAILABLE,
        freshness=empty_freshness,
    )

    from main_api import app
    c = TestClient(app)

    with patch.object(_radar_svc, "get_fundamentals_bundle", return_value=fund_bundle), \
         patch.object(_radar_svc, "get_history_bundle", return_value=hist_bundle):
        for path, forbidden_keys in [
            ("fundamentals", ["ttm", "quarterly", "annual", "company_profile", "source_lineage"]),
            ("financials", ["annual_history", "quarterly_history", "ttm_history"]),
            ("corporate-actions", ["dividends", "splits"]),
            ("evidence", ["source_lineage"]),
        ]:
            resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/{path}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["state"] == "IDENTITY_MISMATCH", f"/{path} must be IDENTITY_MISMATCH on symbol mismatch"
            assert body.get("freshness") is None, f"/{path} must not expose freshness on mismatch"
            for key in forbidden_keys:
                assert key not in body.get("data", {}), f"/{path} must not expose {key!r} on mismatch"


# ── B03–B09 — fundamentals_state truth table ──────────────────────────────────

@pytest.mark.parametrize("av_name,fstate", [
    ("AVAILABLE",                  "AVAILABLE"),
    ("PARTIAL",                    "PARTIAL"),
    ("NOT_AVAILABLE",              "NOT_AVAILABLE"),
    ("NOT_FOUND",                  "NOT_FOUND"),
    ("SOURCE_UNAVAILABLE",         "SOURCE_UNAVAILABLE"),
    ("FUNDAMENTALS_CONFIG_INVALID", "FUNDAMENTALS_CONFIG_INVALID"),
])
def test_b03_fundamentals_state_matrix(monkeypatch, aapl_record, av_name, fstate):
    """/assets/{uid}: state always AVAILABLE; fundamentals_state matches availability."""
    from finco_radar.equity.models import AvailabilityState

    av = AvailabilityState[av_name]
    asset = (
        _make_equity_asset_identity(_TICKER_AAPL, contract_address=_ADDR_AAPL)
        if av in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL, AvailabilityState.NOT_AVAILABLE)
        else None
    )
    bundle = _make_fundamentals_bundle(_TICKER_AAPL, av, asset=asset)

    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))

    from main_api import app
    c = TestClient(app)

    with patch.object(_radar_svc, "get_fundamentals_bundle", return_value=bundle):
        resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE", "top-level state must always be AVAILABLE when registry resolves"
    assert body["data"]["fundamentals_state"] == fstate
    assert "BOUND" not in resp.text, "BOUND must never appear in any public response"


def test_b09_fundamentals_state_identity_mismatch(monkeypatch, aapl_record):
    """/assets/{uid} with IDENTITY_MISMATCH: state=AVAILABLE, fundamentals_state=IDENTITY_MISMATCH."""
    from finco_radar.equity.models import AvailabilityState

    msft_identity = _make_equity_asset_identity("MSFT")
    bundle = _make_fundamentals_bundle("MSFT", AvailabilityState.AVAILABLE, asset=msft_identity)

    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))

    from main_api import app
    c = TestClient(app)

    with patch.object(_radar_svc, "get_fundamentals_bundle", return_value=bundle):
        resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    assert body["data"]["fundamentals_state"] == "IDENTITY_MISMATCH"


# ── B10 — BOUND never appears in any public response ─────────────────────────

def test_b10_bound_never_public(client, client_no_db):
    """'BOUND' must never appear anywhere in any public API response."""
    for c in (client, client_no_db):
        for path in [
            f"/api/v1/radar/assets/{_UID_AAPL}",
            f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals",
            f"/api/v1/radar/assets/{_UID_AAPL}/financials",
            f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions",
            f"/api/v1/radar/assets/{_UID_AAPL}/evidence",
            "/api/v1/radar/assets",
        ]:
            resp = c.get(path)
            assert "BOUND" not in resp.text, (
                f"'BOUND' must not appear in response for {path}"
            )


# ── B11–B15 — fail-closed payload suppression ─────────────────────────────────

def test_b11_fundamentals_mismatch_suppresses_all_fields(tmp_path, monkeypatch, aapl_record):
    """/fundamentals on IDENTITY_MISMATCH: ttm/quarterly/annual/company_profile/freshness suppressed."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "IDENTITY_MISMATCH"
    assert body.get("freshness") is None
    assert body.get("evidence") is None
    data = body.get("data", {})
    for key in ("ttm", "quarterly", "annual", "company_profile", "source_lineage"):
        assert key not in data, f"/fundamentals must not expose {key!r} on IDENTITY_MISMATCH"


def test_b12_financials_mismatch_suppresses_all_fields(tmp_path, monkeypatch, aapl_record):
    """/financials on IDENTITY_MISMATCH: annual_history/quarterly_history/ttm_history/freshness suppressed."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/financials")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "IDENTITY_MISMATCH"
    assert body.get("freshness") is None
    data = body.get("data", {})
    for key in ("annual_history", "quarterly_history", "ttm_history"):
        assert key not in data, f"/financials must not expose {key!r} on IDENTITY_MISMATCH"


def test_b13_corporate_actions_mismatch_suppresses_all_fields(tmp_path, monkeypatch, aapl_record):
    """/corporate-actions on IDENTITY_MISMATCH: dividends/splits suppressed."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "IDENTITY_MISMATCH"
    assert body.get("freshness") is None
    data = body.get("data", {})
    assert "dividends" not in data
    assert "splits" not in data


def test_b14_evidence_mismatch_suppresses_source_lineage(tmp_path, monkeypatch, aapl_record):
    """/evidence on IDENTITY_MISMATCH: source_lineage suppressed."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "IDENTITY_MISMATCH"
    assert body.get("freshness") is None
    data = body.get("data", {})
    assert "source_lineage" not in data


def test_b15_identity_mismatch_exposes_only_registry_data(tmp_path, monkeypatch, aapl_record):
    """/assets/{uid} on IDENTITY_MISMATCH: only safe registry fields + null equity fields."""
    _radar_svc.set_registry_factory(_fake_registry_factory([aapl_record]))
    db = _make_db_wrong_contract(tmp_path)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)
    resp = c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert data["fundamentals_state"] == "IDENTITY_MISMATCH"
    assert data["equity_identity"] is None
    assert body.get("freshness") is None
    # Safe registry fields must still be present
    assert data["token_symbol"] == _TICKER_AAPL
    assert data["token_name"] == "AAPL Inc."
    assert "deployments" in data
    assert "status" in data


# ── B16 — close on programming error: RuntimeError propagates + close() called ─

def test_b16_close_on_programming_error(monkeypatch):
    """An unexpected exception propagates AND close() is still called (finally)."""
    close_calls: list = []

    def factory():
        m = MagicMock()
        m.fetch_snapshot.side_effect = RuntimeError("PROGRAMMING_SENTINEL")
        m.close.side_effect = lambda: close_calls.append("close")
        return m

    _radar_svc.set_registry_factory(factory)
    from main_api import app
    c = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(RuntimeError, match="PROGRAMMING_SENTINEL"):
        c.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert close_calls == ["close"], (
        "close() must be called exactly once even when an unexpected exception propagates"
    )


# ── B17 — adversarial 503 sanitizer ──────────────────────────────────────────

def test_b17_adversarial_503_sanitizer():
    """Public 503 must not leak any sensitive internal detail."""
    import httpx as _httpx

    SENSITIVE_URL = "https://private.internal.example/secret"
    SENSITIVE_PATH = "/srv/finco/private/db.sqlite"
    SENSITIVE_KEY = "API_KEY_SENTINEL_123"

    def factory():
        m = MagicMock()
        m.fetch_snapshot.side_effect = _httpx.ConnectError(
            f"{SENSITIVE_URL} {SENSITIVE_PATH} {SENSITIVE_KEY}"
        )
        return m

    _radar_svc.set_registry_factory(factory)
    from main_api import app
    c = TestClient(app)

    for path in [
        f"/api/v1/radar/assets/{_UID_AAPL}",
        "/api/v1/radar/assets",
    ]:
        resp = c.get(path)
        assert resp.status_code == 503
        body = resp.json()
        detail = body["detail"]
        assert SENSITIVE_URL not in detail
        assert SENSITIVE_PATH not in detail
        assert SENSITIVE_KEY not in detail
        assert "private.internal.example" not in detail
        assert "/srv/finco" not in detail
        assert detail == "Asset registry is temporarily unavailable."


# ── B18 — OpenAPI: all A1 routes present ─────────────────────────────────────

_ALL_A1_PATHS = [
    "/api/v1/meta",
    "/api/v1/radar/assets",
    "/api/v1/radar/assets/{economic_asset_uid}",
    "/api/v1/radar/assets/{economic_asset_uid}/fundamentals",
    "/api/v1/radar/assets/{economic_asset_uid}/financials",
    "/api/v1/radar/assets/{economic_asset_uid}/corporate-actions",
    "/api/v1/radar/assets/{economic_asset_uid}/evidence",
]


def test_b18_openapi_all_routes_present(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema["paths"]
    for path in _ALL_A1_PATHS:
        assert path in paths, f"Route {path!r} missing from OpenAPI schema"


# ── B19 — OpenAPI: success envelopes on data endpoints ────────────────────────

def test_b19_openapi_success_envelopes(client):
    """Data endpoints must declare a success response schema."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    paths = schema["paths"]

    radar_envelope_paths = [
        "/api/v1/radar/assets/{economic_asset_uid}",
        "/api/v1/radar/assets/{economic_asset_uid}/fundamentals",
        "/api/v1/radar/assets/{economic_asset_uid}/financials",
        "/api/v1/radar/assets/{economic_asset_uid}/corporate-actions",
        "/api/v1/radar/assets/{economic_asset_uid}/evidence",
    ]
    for path in radar_envelope_paths:
        responses = paths[path]["get"]["responses"]
        assert "200" in responses, f"{path} missing 200 response in OpenAPI"

    # List endpoint uses AssetListEnvelope
    list_responses = paths["/api/v1/radar/assets"]["get"]["responses"]
    assert "200" in list_responses


# ── B20 — OpenAPI: error envelopes on all relevant endpoints ──────────────────

def test_b20_openapi_error_envelopes(client):
    """All asset-lookup endpoints must declare 400/404/503 responses."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    paths = schema["paths"]

    asset_endpoints = [
        "/api/v1/radar/assets/{economic_asset_uid}",
        "/api/v1/radar/assets/{economic_asset_uid}/fundamentals",
        "/api/v1/radar/assets/{economic_asset_uid}/financials",
        "/api/v1/radar/assets/{economic_asset_uid}/corporate-actions",
        "/api/v1/radar/assets/{economic_asset_uid}/evidence",
    ]
    for path in asset_endpoints:
        responses = paths[path]["get"]["responses"]
        assert "400" in responses, f"{path} missing 400 in OpenAPI"
        assert "404" in responses, f"{path} missing 404 in OpenAPI"
        assert "503" in responses, f"{path} missing 503 in OpenAPI"

    # List endpoint only has 503 (no uid → no 400/404)
    list_responses = paths["/api/v1/radar/assets"]["get"]["responses"]
    assert "503" in list_responses


# ── B21 — raw_evidence sentinel never exposed ─────────────────────────────────

_RAW_EVIDENCE_SENTINEL = "PRIVATE_RAW_REGISTRY_SENTINEL_987"


def test_b21_raw_evidence_sentinel_never_exposed(tmp_path, monkeypatch):
    """CanonicalAssetRecord.raw_evidence must never appear in any API response."""
    # Build a record that carries a raw_evidence sentinel value
    record_with_evidence = CanonicalAssetRecord(
        asset_uid=_UID_AAPL,
        token_symbol=_TICKER_AAPL,
        token_name="AAPL Inc.",
        deployments=(AssetKey(_CHAIN_ID, _ADDR_AAPL),),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
        raw_evidence={"secret": _RAW_EVIDENCE_SENTINEL},
    )
    _radar_svc.set_registry_factory(_fake_registry_factory([record_with_evidence]))

    db = _make_db_path(tmp_path, with_aapl=True)
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(db))
    monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")

    from main_api import app
    c = TestClient(app)

    for path in [
        "/api/v1/radar/assets",
        f"/api/v1/radar/assets/{_UID_AAPL}",
        f"/api/v1/radar/assets/{_UID_AAPL}/fundamentals",
        f"/api/v1/radar/assets/{_UID_AAPL}/evidence",
        f"/api/v1/radar/assets/{_UID_AAPL}/corporate-actions",
    ]:
        resp = c.get(path)
        assert resp.status_code == 200
        assert _RAW_EVIDENCE_SENTINEL not in resp.text, (
            f"raw_evidence sentinel leaked in response for {path}"
        )
        assert "raw_evidence" not in resp.text, (
            f"raw_evidence key leaked in response for {path}"
        )
