"""E3 Company Terminal view model.

Builds presentation dicts for GET /radar/equity/{economic_asset_uid}.

Rules:
- MISSING != ZERO: None → "—"; 0.0 → "0.00"
- Statement adapter: JSON rendered as-is; no unit conversions; no field
  hardcoding; nested dicts flattened deterministically as "parent.child"
- SOURCE_DATA_MALFORMED when a statement field is present but not valid JSON
- No market prices, no quotes, no spreads, no GAP fields
- identity_state: VERIFIED/IDENTITY_MISMATCH/PARTIAL_IDENTITY/NOT_AVAILABLE
- IDENTITY_MISMATCH suppresses all financial data sections
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from finco_radar.equity.config import EquityDBModeError
from finco_radar.equity.models import (
    AvailabilityState,
    EquityCompanyHistoryBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
)
from app.radar_ui.equity_view_model import _fmt_float, _fmt_currency, _fmt_percent, _fmt_ratio_raw


def get_history_for_terminal(
    token_symbol: str,
    **kwargs,
) -> EquityCompanyHistoryBundle:
    """E3 router entry point: resolve a token symbol to an EquityCompanyHistoryBundle.

    Lazy-imports get_equity_company_history from the E1 service so router.py
    never needs to import from finco_radar directly (frozen gate compliance).

    Catches EquityDBModeError at the application boundary and returns a
    FUNDAMENTALS_CONFIG_INVALID bundle rather than letting it become a 500.
    """
    from finco_radar.equity import get_equity_company_history
    try:
        return get_equity_company_history(token_symbol, **kwargs)
    except EquityDBModeError:
        return EquityCompanyHistoryBundle(
            robinhood_token_symbol=token_symbol,
            asset=None,
            company_profile=None,
            annual_history=(),
            quarterly_history=(),
            ttm_history=(),
            recent_dividends=(),
            recent_splits=(),
            source_lineage=(),
            availability=AvailabilityState.FUNDAMENTALS_CONFIG_INVALID,
            freshness=FundamentalsFreshness(
                ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
                ttm_normalized_at=None, quarterly_period_end=None,
                quarterly_fetched_at=None, annual_period_end=None,
                annual_fetched_at=None, profile_fetched_at=None,
                asset_last_seen_at=None,
            ),
        )


def validate_terminal_identity(
    selected_symbol: str,
    selected_contract: Optional[str],
    bundle: EquityCompanyHistoryBundle,
) -> str:
    """Compare Robinhood universe identity vs E1 DB identity.

    Compares symbol (case-insensitive) and contract address (case-insensitive).
    Returns one of: VERIFIED / IDENTITY_MISMATCH / PARTIAL_IDENTITY / NOT_AVAILABLE

    VERIFIED         both symbol and contract address match.
    IDENTITY_MISMATCH either symbol or contract mismatch (suppress all financials).
    PARTIAL_IDENTITY  either side has no contract address to compare.
    NOT_AVAILABLE    bundle.asset is None (DB lookup failed or not found).
    """
    if bundle.asset is None:
        return "NOT_AVAILABLE"

    db_asset = bundle.asset
    db_symbol = db_asset.robinhood_token_symbol
    db_contract = db_asset.token_contract_address

    symbol_match = db_symbol.upper() == selected_symbol.upper()

    if not selected_contract or not db_contract:
        return "PARTIAL_IDENTITY"

    contract_match = db_contract.lower() == selected_contract.lower()

    if symbol_match and contract_match:
        return "VERIFIED"
    return "IDENTITY_MISMATCH"


# ── statement adapter ─────────────────────────────────────────────────────────

def _flatten_dict(d: dict, prefix: str = "") -> List[Tuple[str, Any]]:
    """Flatten a dict deterministically.

    Nested dicts yield "parent.child" keys.
    Non-dict leaf values are returned as-is.
    Lists are skipped (not statement line items).
    Keys are sorted at each nesting level for deterministic output.
    """
    rows = []
    for key in sorted(d.keys()):
        val = d[key]
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            rows.extend(_flatten_dict(val, prefix=full_key))
        elif isinstance(val, list):
            pass  # lists are not statement line items; skip
        else:
            rows.append((full_key, val))
    return rows


def _fmt_statement_value(v: Any) -> str:
    """Format one statement field value for display.

    None  → "—"   (genuinely missing)
    0     → "0"   (explicit zero; not "—")
    float → str with up to 2 decimal places, commas
    int   → str with commas
    str   → as-is
    other → repr
    """
    if v is None:
        return "—"
    if isinstance(v, float):
        return _fmt_float(v, precision=2)
    if isinstance(v, int):
        return "{:,}".format(v)
    if isinstance(v, str):
        return v
    return repr(v)


def _adapt_statement(field: JsonField) -> dict:
    """Convert a JsonField statement to a presentation dict.

    Returns a dict with:
      'state': 'ABSENT' | 'SOURCE_DATA_MALFORMED' | 'AVAILABLE'
      'rows':  list of {'key': str, 'value': str} (only when AVAILABLE)
      'error': parse error string (only when SOURCE_DATA_MALFORMED)
    """
    if field.absent:
        return {"state": "ABSENT", "rows": [], "error": None}
    if field.parse_error is not None:
        return {
            "state": "SOURCE_DATA_MALFORMED",
            "rows": [],
            "error": field.parse_error,
        }
    assert field.value is not None
    raw_rows = _flatten_dict(field.value)
    return {
        "state": "AVAILABLE",
        "rows": [
            {"key": k, "value": _fmt_statement_value(v)}
            for k, v in raw_rows
        ],
        "error": None,
    }


# ── field presentation maps ───────────────────────────────────────────────────
# Source-proven from OpenClaw equity data; unknown fields rendered with raw key.

_INCOME_FIELD_MAP: Dict[str, str] = {
    "totalRevenue": "Total Revenue",
    "costOfRevenue": "Cost of Revenue",
    "grossProfit": "Gross Profit",
    "researchAndDevelopment": "R&D",
    "sellingGeneralAdministrative": "SG&A",
    "operatingExpenses": "Operating Expenses",
    "operatingIncome": "Operating Income",
    "ebitda": "EBITDA",
    "interestExpense": "Interest Expense",
    "incomeBeforeTax": "Income Before Tax",
    "incomeTaxExpense": "Income Tax",
    "netIncome": "Net Income",
    "eps": "EPS (Basic)",
    "epsDiluted": "EPS (Diluted)",
    "weightedAverageShares": "Shares (Basic)",
    "weightedAverageSharesDiluted": "Shares (Diluted)",
}

_BALANCE_FIELD_MAP: Dict[str, str] = {
    "cashAndEquivalents": "Cash & Equivalents",
    "shortTermInvestments": "Short-term Investments",
    "netReceivables": "Net Receivables",
    "inventory": "Inventory",
    "otherCurrentAssets": "Other Current Assets",
    "totalCurrentAssets": "Total Current Assets",
    "propertyPlantEquipment": "PP&E",
    "goodwill": "Goodwill",
    "intangibleAssets": "Intangible Assets",
    "longTermInvestments": "Long-term Investments",
    "totalNonCurrentAssets": "Total Non-Current Assets",
    "totalAssets": "Total Assets",
    "accountsPayable": "Accounts Payable",
    "shortTermDebt": "Short-term Debt",
    "deferredRevenue": "Deferred Revenue",
    "otherCurrentLiabilities": "Other Current Liabilities",
    "totalCurrentLiabilities": "Total Current Liabilities",
    "longTermDebt": "Long-term Debt",
    "deferredRevenueNonCurrent": "Deferred Revenue (Non-Current)",
    "totalNonCurrentLiabilities": "Total Non-Current Liabilities",
    "totalLiabilities": "Total Liabilities",
    "retainedEarnings": "Retained Earnings",
    "commonStock": "Common Stock",
    "totalStockholdersEquity": "Stockholders' Equity",
    "totalEquity": "Total Equity",
}

_CASHFLOW_FIELD_MAP: Dict[str, str] = {
    "operatingCashflow": "Operating Cash Flow",
    "capitalExpenditure": "Capital Expenditure",
    "freeCashFlow": "Free Cash Flow",
    "acquisitionsNet": "Acquisitions (Net)",
    "purchasesOfInvestments": "Purchases of Investments",
    "salesMaturitiesOfInvestments": "Sales of Investments",
    "otherInvestingActivites": "Other Investing Activities",
    "netCashUsedForInvestingActivites": "Net Investing Cash Flow",
    "debtRepayment": "Debt Repayment",
    "commonStockIssued": "Common Stock Issued",
    "commonStockRepurchased": "Common Stock Repurchased",
    "dividendsPaid": "Dividends Paid",
    "otherFinancingActivites": "Other Financing Activities",
    "netCashUsedProvidedByFinancingActivities": "Net Financing Cash Flow",
    "effectOfForexChangesOnCash": "FX Effect on Cash",
    "netChangeInCash": "Net Change in Cash",
    "cashAtEndOfPeriod": "Cash at End of Period",
    "cashAtBeginningOfPeriod": "Cash at Beginning of Period",
    "operatingCashFlow": "Operating Cash Flow",
    "investingCashFlow": "Investing Cash Flow",
    "financingCashFlow": "Financing Cash Flow",
}

_STMT_FIELD_MAPS: Dict[str, Dict[str, str]] = {
    "income_statement": _INCOME_FIELD_MAP,
    "balance_sheet": _BALANCE_FIELD_MAP,
    "cash_flow_statement": _CASHFLOW_FIELD_MAP,
}

_NAV_STMT_TO_FIELD_KEY: Dict[str, str] = {
    "income": "income_statement",
    "balance": "balance_sheet",
    "cashflow": "cash_flow_statement",
}


def _period_label(snap: FinancialSnapshot) -> str:
    """Human-readable period label for statement matrix column headers."""
    if snap.timeframe == "annual":
        return f"FY{snap.fiscal_year}" if snap.fiscal_year else (snap.period_end or "?")
    if snap.timeframe == "quarterly":
        q = snap.fiscal_quarter or ""
        y = snap.fiscal_year or ""
        label = f"{q} {y}".strip()
        return label or (snap.period_end or "?")
    return f"TTM {snap.period_end}" if snap.period_end else "TTM"


def _build_statement_matrix(
    snapshots: Sequence,
    stmt_key: str,
) -> dict:
    """Build a multi-period statement cross-tab for the Financials tab.

    stmt_key: "income_statement" | "balance_sheet" | "cash_flow_statement"

    Returns:
      period_headers: list[{label, period_end, timeframe, fiscal_year, fiscal_quarter, state}]
      rows: list[{field_key, label, cells: list[str]}]
      unit_note: "Source values — no unit conversion applied."
      available: bool
      stmt_key: str

    Cell values: "—" for missing/absent/malformed; formatted value otherwise.
    0/0.0 → displayed zero (MISSING != ZERO invariant).
    Negative values preserved.
    No unit conversions, no derived calculations.
    """
    field_map = _STMT_FIELD_MAPS.get(stmt_key, {})

    period_data: List[Tuple[dict, Optional[dict], str]] = []
    for snap in snapshots:
        stmt_field: JsonField = getattr(snap, stmt_key)
        header = {
            "label": _period_label(snap),
            "period_end": snap.period_end,
            "timeframe": snap.timeframe,
            "fiscal_year": snap.fiscal_year,
            "fiscal_quarter": snap.fiscal_quarter,
        }
        if stmt_field.absent:
            period_data.append((header, None, "NOT_AVAILABLE"))
        elif stmt_field.parse_error is not None:
            period_data.append((header, None, "SOURCE_DATA_MALFORMED"))
        else:
            flat = dict(_flatten_dict(stmt_field.value or {}))
            period_data.append((header, flat, "AVAILABLE"))

    # Union all field paths from available periods
    all_fields_set: set = set()
    for _, fdict, _ in period_data:
        if fdict is not None:
            all_fields_set.update(fdict.keys())

    # Known fields in map order, then unknown fields sorted alphabetically
    known_ordered = [k for k in field_map if k in all_fields_set]
    unknown_sorted = sorted(all_fields_set - set(known_ordered))
    all_fields = known_ordered + unknown_sorted

    period_headers = [
        {**h, "state": col_state}
        for h, _, col_state in period_data
    ]

    rows = []
    for fkey in all_fields:
        label = field_map.get(fkey, fkey)
        cells = []
        for _, fdict, col_state in period_data:
            if col_state != "AVAILABLE" or fdict is None:
                cells.append("—")
            elif fkey not in fdict:
                cells.append("—")
            else:
                cells.append(_fmt_statement_value(fdict[fkey]))
        rows.append({"field_key": fkey, "label": label, "cells": cells})

    return {
        "period_headers": period_headers,
        "rows": rows,
        "unit_note": "Source values — no unit conversion applied.",
        "available": len(period_data) > 0,
        "stmt_key": stmt_key,
    }


# ── snapshot row builder ──────────────────────────────────────────────────────

def _build_snapshot_row(snap: FinancialSnapshot) -> dict:
    """Build a compact derived-metrics row for the financial history table."""
    d = snap.derived
    return {
        "timeframe": snap.timeframe,
        "period_end": snap.period_end or "—",
        "filing_date": snap.filing_date or "—",
        "fiscal_year": snap.fiscal_year or "—",
        "fiscal_quarter": snap.fiscal_quarter or "—",
        "provider": snap.provider or "—",
        "revenues": _fmt_currency(d.revenues) if d else "—",
        "revenue_growth": _fmt_float(d.revenue_growth) if d else "—",
        "gross_margin": _fmt_percent(d.gross_margin) if d else "—",
        "ebit_margin": _fmt_percent(d.ebit_margin) if d else "—",
        "ebitda_margin": _fmt_percent(d.ebitda_margin) if d else "—",
        "net_margin": _fmt_percent(d.net_margin) if d else "—",
        "free_cash_flow": _fmt_currency(d.free_cash_flow) if d else "—",
        "fcf_margin": _fmt_percent(d.fcf_margin) if d else "—",
        "return_on_equity": _fmt_percent(d.return_on_equity) if d else "—",
        "net_debt": _fmt_currency(d.net_debt) if d else "—",
        "debt_to_equity": _fmt_ratio_raw(d.debt_to_equity) if d else "—",
        "income_statement": _adapt_statement(snap.income_statement),
        "balance_sheet": _adapt_statement(snap.balance_sheet),
        "cash_flow_statement": _adapt_statement(snap.cash_flow_statement),
    }


def _build_snapshot_evidence_row(snap: FinancialSnapshot) -> dict:
    """Build per-period evidence metadata. Never includes raw_payload_json."""
    return {
        "timeframe": snap.timeframe,
        "fiscal_year": snap.fiscal_year or "—",
        "fiscal_quarter": snap.fiscal_quarter or "—",
        "period_end": snap.period_end or "—",
        "filing_date": snap.filing_date or "—",
        "provider": snap.provider or "—",
        "source_contract": snap.source_contract or "—",
        "fetched_at": snap.fetched_at or "—",
        "normalized_at": snap.normalized_at or "—",
        "payload_hash": snap.payload_hash or "—",
    }


# ── main terminal view builder ────────────────────────────────────────────────

def build_terminal_view(
    bundle: EquityCompanyHistoryBundle,
    economic_asset_uid: str,
    fallback_name: str = "",
    identity_state: str = "NOT_AVAILABLE",
    selected_chain_id: Optional[str] = None,
    selected_contract_address: Optional[str] = None,
    nav: Optional[dict] = None,
) -> dict[str, Any]:
    """Build the E3 Company Terminal view dict from a history bundle.

    Always returns a dict; 'state' and 'nav' keys always present.

    identity_state controls financial data suppression:
      IDENTITY_MISMATCH → financial sections are empty (suppress all financials).
    """
    if nav is None:
        nav = {"tab": "overview", "timeframe": "annual", "statement": "income"}

    availability = bundle.availability

    if availability == AvailabilityState.FUNDAMENTALS_CONFIG_INVALID:
        return {
            "state": "FUNDAMENTALS_CONFIG_INVALID",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "nav": nav,
        }

    if availability == AvailabilityState.SOURCE_UNAVAILABLE:
        return {
            "state": "SOURCE_UNAVAILABLE",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "nav": nav,
        }

    if availability == AvailabilityState.NOT_FOUND:
        return {
            "state": "NOT_FOUND",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "symbol": bundle.robinhood_token_symbol,
            "nav": nav,
        }

    # NOT_AVAILABLE, PARTIAL, AVAILABLE
    asset = bundle.asset
    profile = bundle.company_profile

    # Company name: profile JSON name > asset.name > fallback_name > symbol
    company_name: str = fallback_name or bundle.robinhood_token_symbol
    if profile is not None:
        prof_json = profile.profile
        if prof_json.is_available and isinstance(prof_json.value, dict):
            n = prof_json.value.get("name")
            if isinstance(n, str) and n.strip():
                company_name = n.strip()
    if company_name == (fallback_name or bundle.robinhood_token_symbol) and asset and asset.name:
        company_name = asset.name

    # Identity section
    identity: Optional[dict] = None
    if asset is not None:
        identity = {
            "available": True,
            "symbol": asset.robinhood_token_symbol,
            "company_name": company_name,
            "underlying_ticker": asset.underlying_ticker,
            "exchange": asset.underlying_exchange,
            "currency": asset.currency,
            "security_type": asset.security_type,
            "cik": asset.cik,
            "figi": asset.figi,
        }

    # Profile section (Overview tab)
    profile_section: Optional[dict] = None
    if profile is not None:
        prof_json = profile.profile
        if prof_json.is_available and isinstance(prof_json.value, dict):
            profile_section = {
                "available": True,
                "rows": [
                    {"key": k, "value": _fmt_statement_value(v)}
                    for k, v in sorted(prof_json.value.items())
                    if not isinstance(v, (dict, list))
                ],
                "fetched_at": profile.fetched_at or "—",
                "provider": profile.provider or "—",
                "source_contract": profile.source_contract or "—",
                "payload_hash": profile.payload_hash or "—",
            }
        else:
            profile_section = {
                "available": False,
                "absent": prof_json.absent,
                "parse_error": prof_json.parse_error,
                "fetched_at": profile.fetched_at or "—",
                "payload_hash": profile.payload_hash or "—",
            }

    # Profile evidence (Evidence tab)
    if profile is not None:
        profile_evidence: dict = {
            "available": True,
            "provider": profile.provider or "—",
            "source_contract": profile.source_contract or "—",
            "fetched_at": profile.fetched_at or "—",
            "payload_hash": profile.payload_hash or "—",
        }
    else:
        profile_evidence = {
            "available": False,
            "provider": None,
            "source_contract": None,
            "fetched_at": None,
            "payload_hash": None,
        }

    # Snapshot evidence (all timeframes, all periods — no raw_payload_json)
    snapshot_evidence_rows = [
        _build_snapshot_evidence_row(s)
        for s in (
            list(bundle.annual_history)
            + list(bundle.quarterly_history)
            + list(bundle.ttm_history)
        )
    ]

    # IDENTITY_MISMATCH: suppress all financial data
    suppress_financials = (identity_state == "IDENTITY_MISMATCH")

    if suppress_financials:
        annual_rows: list = []
        quarterly_rows: list = []
        ttm_rows: list = []
        statement_matrix: dict = {
            "available": False,
            "period_headers": [],
            "rows": [],
            "unit_note": "Source values — no unit conversion applied.",
            "stmt_key": _NAV_STMT_TO_FIELD_KEY.get(nav.get("statement", "income"), "income_statement"),
        }
    else:
        annual_rows = [_build_snapshot_row(s) for s in bundle.annual_history]
        quarterly_rows = [_build_snapshot_row(s) for s in bundle.quarterly_history]
        ttm_rows = [_build_snapshot_row(s) for s in bundle.ttm_history]

        # Statement matrix for Financials tab
        nav_timeframe = nav.get("timeframe", "annual")
        nav_statement = nav.get("statement", "income")
        stmt_key = _NAV_STMT_TO_FIELD_KEY.get(nav_statement, "income_statement")
        timeframe_snapshots_map: dict = {
            "annual": bundle.annual_history,
            "quarterly": bundle.quarterly_history,
            "ttm": bundle.ttm_history,
        }
        snapshots_for_matrix = timeframe_snapshots_map.get(nav_timeframe, bundle.annual_history)
        statement_matrix = _build_statement_matrix(snapshots_for_matrix, stmt_key)

    # Corporate actions — all authority fields
    dividend_rows = [
        {
            "declaration_date": d.declaration_date or "—",
            "ex_dividend_date": d.ex_dividend_date or "—",
            "record_date": d.record_date or "—",
            "pay_date": d.pay_date or "—",
            "cash_amount": _fmt_float(d.cash_amount) if d.cash_amount is not None else "—",
            "currency": d.currency or "—",
            "frequency": str(d.frequency) if d.frequency is not None else "—",
            "dividend_type": d.dividend_type or "—",
        }
        for d in bundle.recent_dividends
    ]
    split_rows = [
        {
            "execution_date": s.execution_date or "—",
            "split_from": _fmt_float(s.split_from) if s.split_from is not None else "—",
            "split_to": _fmt_float(s.split_to) if s.split_to is not None else "—",
        }
        for s in bundle.recent_splits
    ]

    # Source lineage — no raw_payload_json
    lineage_rows = [
        {
            "lineage_id": lin.lineage_id,
            "stage": lin.stage or "—",
            "provider": lin.provider or "—",
            "source_contract": lin.source_contract or "—",
            "endpoint": lin.endpoint or "—",
            "payload_hash": lin.payload_hash or "—",
            "fetched_at": lin.fetched_at or "—",
        }
        for lin in bundle.source_lineage
    ]

    # Freshness
    freshness = bundle.freshness

    # Selected Robinhood identity for Token Market tab
    selected_token = {
        "symbol": bundle.robinhood_token_symbol,
        "economic_asset_uid": economic_asset_uid,
        "chain_id": selected_chain_id or "—",
        "contract_address": selected_contract_address or "—",
    }

    return {
        "state": availability.value,
        "available": availability in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL),
        "economic_asset_uid": economic_asset_uid,
        "symbol": bundle.robinhood_token_symbol,
        "company_name": company_name,
        "identity": identity,
        "identity_state": identity_state,
        "profile": profile_section,
        "profile_evidence": profile_evidence,
        "snapshot_evidence": snapshot_evidence_rows,
        "annual_history": annual_rows,
        "quarterly_history": quarterly_rows,
        "ttm_history": ttm_rows,
        "statement_matrix": statement_matrix,
        "dividends": dividend_rows,
        "splits": split_rows,
        "lineage": lineage_rows,
        "nav": nav,
        "selected_token": selected_token,
        "freshness": {
            "ttm_period_end": freshness.ttm_period_end or "—",
            "ttm_filing_date": freshness.ttm_filing_date or "—",
            "quarterly_period_end": freshness.quarterly_period_end or "—",
            "annual_period_end": freshness.annual_period_end or "—",
            "profile_fetched_at": freshness.profile_fetched_at or "—",
            "asset_last_seen_at": freshness.asset_last_seen_at or "—",
        },
        "execution_simulator_url": f"/radar?asset_uid={economic_asset_uid}#radar-panels",
        "radar_url": "/radar",
    }
