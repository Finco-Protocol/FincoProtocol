"""finco_radar.equity — E1 read-only equity fundamentals authority.

Resolves Robinhood stock tokens to underlying equity company profiles
and financial reporting data from the equity_fundamentals.db SQLite source.

Authority boundary:
  - This package is FUNDAMENTALS / REFERENCE only.
  - No market prices. No Robinhood API calls. No live data.
  - The equity_fundamentals.db is opened read-only; never mutated.
"""
from .models import (
    AvailabilityState,
    CompanyProfile,
    DerivedFundamentals,
    DividendRecord,
    EquityAssetIdentity,
    EquityFundamentalsBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
    SourceLineage,
    SplitRecord,
)
from .service import get_equity_fundamentals, get_equity_fundamentals_many

__all__ = [
    "AvailabilityState",
    "CompanyProfile",
    "DerivedFundamentals",
    "DividendRecord",
    "EquityAssetIdentity",
    "EquityFundamentalsBundle",
    "FinancialSnapshot",
    "FundamentalsFreshness",
    "JsonField",
    "SourceLineage",
    "SplitRecord",
    "get_equity_fundamentals",
    "get_equity_fundamentals_many",
]
