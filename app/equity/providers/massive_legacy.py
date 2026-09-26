"""Massive legacy reference-data adaptor.

Pipeline: Massive raw response -> normalized external record -> FINCO
EquitySnapshot/domain dataclasses. Massive-specific field names are mapped
here and never leak into the canonical domain contract.

API key handling:
  * read ONLY from the MASSIVE_API_KEY environment variable,
  * never hardcoded, never logged; errors/exceptions are scrubbed.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping, Optional

from ..domain import (
    CompanyProfile,
    Dividend,
    EquitySnapshot,
    Split,
)

MASSIVE_BASE_URL = "https://api.massive.com"
ENV_API_KEY = "MASSIVE_API_KEY"

_SECRET_PATTERNS = re.compile(r"(Bearer\s+)[^\s'\"]+", re.IGNORECASE)


def scrub_secrets(text: str) -> str:
    """Remove any bearer-token-looking secrets from log/error text."""
    return _SECRET_PATTERNS.sub(r"\1***", text)


class MassiveLegacyError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(scrub_secrets(message))
        self.status = status


class MassiveLegacyClient:
    """Thin HTTP client with retry/backoff and pacing (~4 req/min)."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = MASSIVE_BASE_URL,
        requests_per_minute: float = 4.0,
        max_retries: int = 4,
        transport=None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(ENV_API_KEY, "")
        if not key:
            raise MassiveLegacyError(
                f"{ENV_API_KEY} environment variable is not set; refusing to start"
            )
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._min_interval = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._last_request_at = 0.0
        self.request_count = 0
        self._transport = transport  # injectable for tests

    # -- HTTP ---------------------------------------------------------------

    def _http_get(self, url: str, params: dict | None) -> Mapping[str, Any]:
        if self._transport is not None:
            status, payload = self._transport(url, params)
            if status != 200:
                raise MassiveLegacyError(
                    f"Massive request failed with HTTP {status}", status=status
                )
            return payload
        import httpx

        response = httpx.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "accept": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise MassiveLegacyError(
                f"Massive transient error HTTP {response.status_code}",
                status=response.status_code,
            )
        if response.status_code != 200:
            raise MassiveLegacyError(
                f"Massive request failed with HTTP {response.status_code}",
                status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MassiveLegacyError("Massive returned invalid JSON") from exc

    def _get(self, path: str, params: dict | None = None) -> Mapping[str, Any]:
        url = self._base_url + path
        delay = self._min_interval
        for attempt in range(self._max_retries + 1):
            self._pace()
            try:
                self.request_count += 1
                return self._http_get(url, params)
            except MassiveLegacyError as exc:
                transient = exc.status in (429, 500, 502, 503, 504) or exc.status is None
                if not transient or attempt == self._max_retries:
                    raise
                time.sleep(min(delay, 60.0))
                delay *= 2
        raise MassiveLegacyError("unreachable")

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    # -- Endpoints ----------------------------------------------------------

    def company_profile(self, ticker: str) -> Mapping[str, Any]:
        return self._get(f"/v3/reference/tickers/{ticker}")

    def financials(self, ticker: str, limit: int = 100) -> Mapping[str, Any]:
        return self._get(
            "/vX/reference/financials", {"ticker": ticker, "limit": str(limit)}
        )

    def dividends(self, ticker: str, limit: int = 100) -> Mapping[str, Any]:
        return self._get(
            "/v3/reference/dividends", {"ticker": ticker, "limit": str(limit)}
        )

    def splits(self, ticker: str, limit: int = 100) -> Mapping[str, Any]:
        return self._get("/v3/reference/splits", {"ticker": ticker, "limit": str(limit)})


# ---------------------------------------------------------------------------
# Normalization: Massive raw -> FINCO canonical domain objects
# ---------------------------------------------------------------------------

def normalize_company_profile(raw: Mapping[str, Any]) -> CompanyProfile:
    result = raw.get("results") or {}
    if not isinstance(result, Mapping):
        raise MassiveLegacyError("Massive ticker payload missing results object")
    return CompanyProfile(
        ticker=str(result["ticker"]),
        name=str(result.get("name") or ""),
        cik=result.get("cik"),
        figi=result.get("composite_figi"),
        primary_exchange=result.get("primary_exchange"),
        security_type=result.get("type"),
        currency=result.get("currency_name"),
        description=result.get("description"),
        sic_code=str(result["sic_code"]) if result.get("sic_code") is not None else None,
        sic_description=result.get("sic_description"),
        homepage_url=result.get("homepage_url"),
        total_employees=result.get("total_employees"),
        list_date=result.get("list_date"),
        address=dict(result["address"]) if isinstance(result.get("address"), Mapping) else None,
        phone_number=result.get("phone_number"),
        share_class_shares_outstanding=result.get("share_class_shares_outstanding"),
    )


def _statement_normalized(raw_statement: Any) -> dict:
    """Flatten Massive {field: {value, unit, label, order}} to {field: value}."""
    if not isinstance(raw_statement, Mapping):
        return {}
    normalized: dict[str, float | None] = {}
    for key, entry in raw_statement.items():
        if isinstance(entry, Mapping) and "value" in entry:
            normalized[key] = entry.get("value")
    return normalized


def normalize_financials(raw: Mapping[str, Any], ticker_hint: str = "") -> list[EquitySnapshot]:
    rows = raw.get("results")
    if not isinstance(rows, list):
        raise MassiveLegacyError("Massive financials payload missing results list")
    snapshots: list[EquitySnapshot] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tickers = row.get("tickers") or []
        ticker = str(tickers[0]) if tickers else ticker_hint
        financials = row.get("financials") or {}
        snapshots.append(
            EquitySnapshot(
                ticker=ticker,
                cik=row.get("cik"),
                timeframe=str(row.get("timeframe") or ""),
                fiscal_year=str(row.get("fiscal_year") or "") or None,
                fiscal_quarter=str(row.get("fiscal_period") or "") or None
                if row.get("fiscal_period")
                else None,
                period_end=row.get("end_date"),
                filing_date=row.get("filing_date"),
                income_statement=_statement_normalized(
                    financials.get("income_statement")
                ),
                balance_sheet=_statement_normalized(
                    financials.get("balance_sheet")
                ),
                cash_flow_statement=_statement_normalized(
                    financials.get("cash_flow_statement")
                ),
            )
        )
    return snapshots


def normalize_dividends(raw: Mapping[str, Any], ticker_hint: str = "") -> list[Dividend]:
    rows = raw.get("results")
    if not isinstance(rows, list):
        raise MassiveLegacyError("Massive dividends payload missing results list")
    dividends: list[Dividend] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        dividends.append(
            Dividend(
                ticker=str(row.get("ticker") or ticker_hint),
                cash_amount=float(row["cash_amount"]) if row.get("cash_amount") is not None else None,
                currency=row.get("currency"),
                declaration_date=row.get("declaration_date"),
                ex_dividend_date=row.get("ex_dividend_date"),
                record_date=row.get("record_date"),
                pay_date=row.get("pay_date"),
                frequency=int(row["frequency"]) if row.get("frequency") is not None else None,
                dividend_type=row.get("dividend_type"),
            )
        )
    return dividends


def normalize_splits(raw: Mapping[str, Any], ticker_hint: str = "") -> list[Split]:
    rows = raw.get("results")
    if not isinstance(rows, list):
        raise MassiveLegacyError("Massive splits payload missing results list")
    splits: list[Split] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        splits.append(
            Split(
                ticker=str(row.get("ticker") or ticker_hint),
                execution_date=row.get("execution_date"),
                split_from=float(row["split_from"]) if row.get("split_from") is not None else None,
                split_to=float(row["split_to"]) if row.get("split_to") is not None else None,
            )
        )
    return splits
