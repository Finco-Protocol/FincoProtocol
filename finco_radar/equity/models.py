"""Typed immutable domain models for E1 equity fundamentals authority.

MISSING != ZERO is a hard invariant throughout.  Optional[float] fields
distinguish genuine 0.0 from absent/null.  JsonField preserves the
difference between a DB column that is NULL (absent) and one that
contains malformed JSON (parse error).

No market-price fields are present in any model.  This package is
fundamentals / reference authority only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── availability ─────────────────────────────────────────────────────────────

class AvailabilityState(str, Enum):
    """Typed availability for an equity fundamentals bundle or sub-component."""

    AVAILABLE = "AVAILABLE"           # asset + profile + TTM all present
    PARTIAL = "PARTIAL"               # some data present; not the full set
    NOT_AVAILABLE = "NOT_AVAILABLE"   # asset known but no financial data
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"  # DB missing / unreadable
    NOT_FOUND = "NOT_FOUND"           # token not in equity_assets


# ── JSON field wrapper ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JsonField:
    """A JSON column from the database; preserves absent vs malformed distinction.

    absent=True        DB column was NULL or empty string.
    parse_error        Non-None if field was present but not valid JSON.
    value              Parsed dict; None if absent or malformed.
    """

    value: Optional[dict]
    absent: bool
    parse_error: Optional[str]

    @property
    def is_available(self) -> bool:
        return not self.absent and self.parse_error is None


# ── asset identity ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EquityAssetIdentity:
    """Canonical mapping of a Robinhood token to its underlying equity."""

    robinhood_token_symbol: str
    underlying_ticker: str
    name: Optional[str]
    token_contract_address: Optional[str]
    chain_network: Optional[str]
    underlying_exchange: Optional[str]
    cik: Optional[str]
    figi: Optional[str]
    currency: Optional[str]
    security_type: Optional[str]
    active: bool
    first_seen_at: Optional[str]
    last_seen_at: Optional[str]


# ── company profile ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompanyProfile:
    """Latest company profile for a ticker (deterministic latest-fetched selection)."""

    ticker: str
    cik: Optional[str]
    provider: Optional[str]
    source_contract: Optional[str]
    payload_hash: Optional[str]
    fetched_at: Optional[str]
    profile: JsonField


# ── financial statements ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class DerivedFundamentals:
    """Source-derived metrics from derived_json.  Faithfully exposed; not computed.

    All fields are Optional[float].  A None value means the source record
    did not contain that key.  A 0.0 means the source explicitly provided zero.
    These must never be treated identically (MISSING != ZERO invariant).
    """

    revenues: Optional[float]
    revenue_growth: Optional[float]
    gross_margin: Optional[float]
    ebit_margin: Optional[float]
    ebitda_margin: Optional[float]
    net_margin: Optional[float]
    free_cash_flow: Optional[float]
    fcf_margin: Optional[float]
    return_on_equity: Optional[float]
    net_debt: Optional[float]
    debt_to_equity: Optional[float]
    source_field: JsonField


@dataclass(frozen=True)
class FinancialSnapshot:
    """One financial reporting period from equity_financial_snapshots.

    Statement fields use JsonField so callers can distinguish:
      absent  — column was NULL in DB
      valid   — parsed dict (values within may be None/0.0/negative)
      error   — present but malformed JSON (record remains available)
    """

    ticker: str
    cik: Optional[str]
    timeframe: str              # "annual" | "quarterly" | "ttm"
    fiscal_year: Optional[str]
    fiscal_quarter: Optional[str]
    period_end: Optional[str]
    filing_date: Optional[str]
    provider: Optional[str]
    source_contract: Optional[str]
    fetched_at: Optional[str]
    normalized_at: Optional[str]
    payload_hash: Optional[str]
    income_statement: JsonField
    balance_sheet: JsonField
    cash_flow_statement: JsonField
    derived_source: JsonField
    derived: Optional[DerivedFundamentals]


# ── corporate actions ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DividendRecord:
    ticker: str
    external_id: Optional[str]
    cash_amount: Optional[float]   # genuine 0.0 preserved
    currency: Optional[str]
    declaration_date: Optional[str]
    ex_dividend_date: Optional[str]
    record_date: Optional[str]
    pay_date: Optional[str]
    frequency: Optional[int]
    dividend_type: Optional[str]
    first_seen_at: Optional[str]


@dataclass(frozen=True)
class SplitRecord:
    ticker: str
    external_id: Optional[str]
    execution_date: Optional[str]
    split_from: Optional[float]
    split_to: Optional[float]
    first_seen_at: Optional[str]


# ── lineage ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceLineage:
    """Source provenance for a snapshot or filing."""

    lineage_id: Optional[str]
    ticker: str
    stage: Optional[str]
    provider: Optional[str]
    source_contract: Optional[str]
    endpoint: Optional[str]
    payload_hash: Optional[str]
    normalized_ref: Optional[str]
    fetched_at: Optional[str]


# ── freshness metadata ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FundamentalsFreshness:
    """Objective date metadata for freshness classification by the UI layer.

    E1 does not label data STALE based on hidden thresholds.
    The product layer may derive age and policy from these dates.
    """

    ttm_period_end: Optional[str]
    ttm_filing_date: Optional[str]
    ttm_fetched_at: Optional[str]
    ttm_normalized_at: Optional[str]
    quarterly_period_end: Optional[str]
    quarterly_fetched_at: Optional[str]
    annual_period_end: Optional[str]
    annual_fetched_at: Optional[str]
    profile_fetched_at: Optional[str]
    asset_last_seen_at: Optional[str]


# ── bundle ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EquityFundamentalsBundle:
    """Full read-only fundamentals result for one Robinhood token.

    Contains no market prices, no token prices, no OHLCV, no quotes,
    no execution prices, no spreads, no liquidity data.
    """

    robinhood_token_symbol: str
    asset: Optional[EquityAssetIdentity]
    company_profile: Optional[CompanyProfile]
    latest_ttm: Optional[FinancialSnapshot]
    latest_quarterly: Optional[FinancialSnapshot]
    latest_annual: Optional[FinancialSnapshot]
    recent_dividends: tuple[DividendRecord, ...]
    recent_splits: tuple[SplitRecord, ...]
    source_lineage_summary: tuple[SourceLineage, ...]
    availability: AvailabilityState
    freshness: FundamentalsFreshness
