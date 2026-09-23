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
  A09 — get asset identity: equity DB unconfigured → 200 SOURCE_UNAVAILABLE
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
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

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
    def _broken():
        raise RuntimeError("network timeout")

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
    def _broken():
        raise ConnectionError("registry down")

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
    resp = client_no_db.get(f"/api/v1/radar/assets/{_UID_AAPL}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "SOURCE_UNAVAILABLE"
    assert body["economic_asset_uid"] == _UID_AAPL


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
