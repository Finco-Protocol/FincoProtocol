"""FINCO Equity fundamentals database — tests (mocked provider, no live API)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for name in ("app", "finco_core", "finco_radar"):
    p = str(REPO_ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)

from app.equity import repository as repo
from app.equity.db import connect
from app.equity.domain import EquitySnapshot, derive_fundamentals
from app.equity.providers import massive_legacy as ml
from app.equity.equity_fundamentals_ingest import _run_ticker_stage

API_KEY = "TESTKEY_abcdef123456"


@pytest.fixture()
def conn(tmp_path):
    with connect(str(tmp_path / "eq.db")) as c:
        yield c


@pytest.fixture()
def client():
    calls = []

    def transport(url, params):
        calls.append(url)
        if "tickers/" in url:
            payload = PROFILE_RAW
        elif "financials" in url:
            payload = FINANCIALS_RAW
        elif "dividends" in url:
            payload = DIVIDENDS_RAW
        elif "splits" in url:
            payload = SPLITS_RAW
        else:
            raise AssertionError(url)
        return 200, payload

    c = ml.MassiveLegacyClient(api_key=API_KEY, requests_per_minute=10000.0,
                               transport=transport)
    c.calls = calls
    return c


PROFILE_RAW = {
    "results": {"ticker": "AAPL", "name": "Apple Inc.", "cik": "0000320193",
                "composite_figi": "BBG000B9XRY4", "primary_exchange": "XNAS",
                "type": "CS", "currency_name": "usd", "sic_code": "3571",
                "description": "Apple", "total_employees": 166000,
                "address": {"city": "CUPERTINO"}},
}
FINANCIALS_RAW = {
    "results": [{
        "start_date": "2025-06-28", "end_date": "2026-06-27", "timeframe": "ttm",
        "fiscal_period": "TTM", "fiscal_year": "", "cik": "0000320193",
        "tickers": ["AAPL"], "company_name": "Apple Inc.",
        "financials": {
            "income_statement": {
                "revenues": {"value": 466.8, "unit": "USD", "label": "Revenues", "order": 100},
                "gross_profit": {"value": 227.1, "unit": "USD", "label": "Gross Profit", "order": 800},
                "net_income_loss": {"value": 128.9, "unit": "USD", "label": "Net Income", "order": 3500},
            },
            "balance_sheet": {
                "cash_and_cash_equivalents": {"value": 50.0, "unit": "USD", "label": "Cash", "order": 100},
                "total_debt": {"value": 100.0, "unit": "USD", "label": "Debt", "order": 500},
                "stockholders_equity": {"value": 60.0, "unit": "USD", "label": "Equity", "order": 800},
            },
            "cash_flow_statement": {
                "net_cash_flow_from_operating_activities": {"value": 146.7, "unit": "USD", "label": "CFO", "order": 100},
                "capital_expenditure": {"value": 12.5, "unit": "USD", "label": "CapEx", "order": 200},
            },
        },
    }]
}
DIVIDENDS_RAW = {"results": [
    {"cash_amount": 0.27, "currency": "USD", "declaration_date": "2026-04-30",
     "dividend_type": "CD", "ex_dividend_date": "2026-05-11", "frequency": 4,
     "id": "div1", "pay_date": "2026-05-14", "record_date": "2026-05-11",
     "ticker": "AAPL"},
]}
SPLITS_RAW = {"results": [
    {"execution_date": "2020-08-31", "id": "spl1", "split_from": 1,
     "split_to": 4, "ticker": "AAPL"},
]}


# -- normalization -----------------------------------------------------------

def test_normalize_financials():
    snaps = ml.normalize_financials(FINANCIALS_RAW, "AAPL")
    assert len(snaps) == 1
    s = snaps[0]
    assert s.ticker == "AAPL" and s.timeframe == "ttm" and s.period_end == "2026-06-27"
    assert s.income_statement["revenues"] == 466.8
    assert "unit" not in s.income_statement  # Massive envelope flattened


def test_derived_fundamentals():
    s = ml.normalize_financials(FINANCIALS_RAW, "AAPL")[0]
    d = derive_fundamentals(s)
    assert d["gross_margin"] == pytest.approx(227.1 / 466.8)
    assert d["net_margin"] == pytest.approx(128.9 / 466.8)
    assert d["free_cash_flow"] == pytest.approx(146.7 - 12.5)
    assert d["fcf_margin"] == pytest.approx((146.7 - 12.5) / 466.8)
    assert d["return_on_equity"] == pytest.approx(128.9 / 60.0)
    assert d["net_debt"] == pytest.approx(50.0)
    assert d["debt_to_equity"] == pytest.approx(100.0 / 60.0)
    # no market-dependent keys
    for banned in ("pe_ratio", "ev_ebitda", "dividend_yield", "dcf", "score"):
        assert banned not in d


def test_canonical_domain_has_no_massive_fields():
    snap = EquitySnapshot(ticker="X", cik=None, timeframe="ttm", fiscal_year=None,
                          fiscal_quarter=None, period_end=None, filing_date=None)
    domain_fields = set(snap.__dict__) | set(
        derive_fundamentals(snap))
    for field in domain_fields:
        assert "massive" not in str(field).lower()
        assert "polygon" not in str(field).lower()


# -- idempotency / history ---------------------------------------------------

def test_idempotent_reingestion(conn, client):
    assert _run_ticker_stage(conn, client, "financials", "AAPL") == "done"
    n1 = conn.execute("SELECT COUNT(*) n FROM equity_financial_snapshots").fetchone()["n"]
    assert _run_ticker_stage(conn, client, "financials", "AAPL",
                             skip_if_fresh=False) == "done"
    n2 = conn.execute("SELECT COUNT(*) n FROM equity_financial_snapshots").fetchone()["n"]
    assert n1 == n2 == 1


def test_restatement_preserves_history(conn, client):
    _run_ticker_stage(conn, client, "financials", "AAPL")
    restated = json.loads(json.dumps(FINANCIALS_RAW))
    restated["results"][0]["financials"]["income_statement"]["revenues"]["value"] = 470.0

    def transport(url, params):
        return 200, restated
    client2 = ml.MassiveLegacyClient(api_key=API_KEY, requests_per_minute=10000.0,
                                     transport=transport)
    _run_ticker_stage(conn, client2, "financials", "AAPL", skip_if_fresh=False)
    rows = conn.execute(
        "SELECT income_statement_json FROM equity_financial_snapshots "
        "ORDER BY fetched_at").fetchall()
    assert len(rows) == 2  # old version kept + new inserted
    values = sorted(json.loads(r["income_statement_json"])["revenues"] for r in rows)
    assert values == [466.8, 470.0]


def test_duplicate_dividends_and_splits(conn, client):
    _run_ticker_stage(conn, client, "dividends", "AAPL")
    _run_ticker_stage(conn, client, "dividends", "AAPL", skip_if_fresh=False)
    assert conn.execute("SELECT COUNT(*) n FROM equity_dividends").fetchone()["n"] == 1
    _run_ticker_stage(conn, client, "splits", "AAPL")
    _run_ticker_stage(conn, client, "splits", "AAPL", skip_if_fresh=False)
    assert conn.execute("SELECT COUNT(*) n FROM equity_splits").fetchone()["n"] == 1


# -- checkpoint / failure isolation ------------------------------------------

def test_checkpoint_resume(conn, client):
    _run_ticker_stage(conn, client, "financials", "AAPL")
    client.calls.clear()
    # second run skips via checkpoint
    assert _run_ticker_stage(conn, client, "financials", "AAPL") == "skipped"
    assert client.calls == []  # no API call made
    row = repo.checkpoint_get(conn, "financials:AAPL")
    assert row["status"] == "done"


def test_failed_ticker_does_not_abort_universe(conn):
    boom = {"results": [{"cash_amount": 1.0, "ticker": "BAD"}]}

    def transport(url, params):
        if "tickers/BAD" in url or params.get("ticker") == "BAD":
            return 500, {}
        if "dividends" in url:
            return 200, boom if params.get("ticker") == "BAD" else DIVIDENDS_RAW
        return 200, DIVIDENDS_RAW

    client = ml.MassiveLegacyClient(
        api_key=API_KEY, requests_per_minute=10000.0, max_retries=0,
        transport=transport)
    statuses = [
        _run_ticker_stage(conn, client, "dividends", t)
        for t in ("GOOD", "BAD", "GOOD2")
    ]
    assert statuses == ["done", "failed", "done"]
    assert repo.checkpoint_get(conn, "dividends:BAD")["status"] == "failed"


# -- assets ------------------------------------------------------------------

def test_disappeared_asset_marked_inactive_never_deleted(conn):
    from datetime import datetime, timezone
    from app.equity.domain import EquityAsset
    repo.upsert_asset(conn, EquityAsset(robinhood_token_symbol="AAA",
                                        underlying_ticker="AAA", name="A"))
    repo.upsert_asset(conn, EquityAsset(robinhood_token_symbol="BBB",
                                        underlying_ticker="BBB", name="B"))
    deactivated = repo.mark_disappeared_inactive(conn, ["AAA"])
    assert deactivated == 1
    row = conn.execute(
        "SELECT active FROM equity_assets WHERE robinhood_token_symbol='BBB'"
    ).fetchone()
    assert row["active"] == 0  # inactive but row preserved
    assert conn.execute("SELECT COUNT(*) n FROM equity_assets").fetchone()["n"] == 2


# -- secrets -----------------------------------------------------------------

def test_api_key_never_in_code_or_logs():
    # scan all equity module sources + scrubber behavior
    import app.equity
    base = Path(app.equity.__file__).parent
    for path in base.rglob("*.py"):
        assert "DUMMY_TEST_KEY" not in path.read_text(), path
    scrubbed = ml.scrub_secrets("Authorization: Bearer DUMMY_TEST_KEY_beef failed")
    assert "DUMMY_TEST_KEY" not in scrubbed


def test_client_requires_env_key(monkeypatch):
    monkeypatch.delenv(ml.ENV_API_KEY, raising=False)
    with pytest.raises(ml.MassiveLegacyError):
        ml.MassiveLegacyClient()


def test_retry_on_429(monkeypatch):
    attempts = {"n": 0}

    def transport(url, params):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return 429, {}
        return 200, DIVIDENDS_RAW

    sleeps = []
    monkeypatch.setattr(ml.time, "sleep", lambda s: sleeps.append(s))
    client = ml.MassiveLegacyClient(api_key="K", requests_per_minute=10000.0,
                                    transport=transport)
    payload = client.dividends("AAPL")
    assert payload["results"][0]["ticker"] == "AAPL"
    assert attempts["n"] == 3
    assert len(sleeps) >= 2  # backoff sleeps happened
