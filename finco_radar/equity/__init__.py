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
    EquityCompanyHistoryBundle,
    EquityFundamentalsBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
    SourceLineage,
    SplitRecord,
)
from .derived import compute_ttm_revenue_growth
from .service import (
    get_equity_company_history,
    get_equity_fundamentals,
    get_equity_fundamentals_many,
)

__all__ = [
    "AvailabilityState",
    "CompanyProfile",
    "compute_ttm_revenue_growth",
    "DerivedFundamentals",
    "DividendRecord",
    "EquityAssetIdentity",
    "EquityCompanyHistoryBundle",
    "EquityFundamentalsBundle",
    "FinancialSnapshot",
    "FundamentalsFreshness",
    "JsonField",
    "SourceLineage",
    "SplitRecord",
    "get_equity_company_history",
    "get_equity_fundamentals",
    "get_equity_fundamentals_many",
]
